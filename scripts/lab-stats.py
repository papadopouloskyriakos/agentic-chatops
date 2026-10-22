#!/usr/bin/env python3
"""Generate lab stats JSON for portfolio 'At a Glance' widget.

Queries NetBox API + kubectl + n8n API for live infrastructure counts.
Called by n8n webhook workflow via SSH.
"""
import json
import datetime
import os
import subprocess
import urllib.request
import ssl

NETBOX_URL = "https://netbox.example.net"
NETBOX_TOKEN = "REDACTED_4bd0c65f"
# NetBox role IDs (from /api/dcim/device-roles/)
ROLE_K8S_CTRL = 34     # "K8s Controller"
ROLE_K8S_WORKER = 35   # "K8s Worker"

# Site IDs in NetBox
SITE_NL = 1   # nl
SITE_GR = 2   # gr
SITE_CH = 5   # chzrh01
SITE_NO = 6   # notrf01
SITE_GR2 = 3  # gr2

# SSL context for self-signed cert
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def nb_get(endpoint, params=""):
    """GET a NetBox API endpoint and return parsed JSON."""
    url = f"{NETBOX_URL}{endpoint}?limit=1{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {NETBOX_TOKEN}"})
    with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
        return json.loads(resp.read())


def nb_count(endpoint, params=""):
    """Get count from a NetBox API list endpoint."""
    return nb_get(endpoint, params).get("count", 0)


def nb_list(endpoint, params="", limit=100):
    """Get list of results from a NetBox API endpoint."""
    url = f"{NETBOX_URL}{endpoint}?limit={limit}{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {NETBOX_TOKEN}"})
    with urllib.request.urlopen(req, context=CTX, timeout=15) as resp:
        return json.loads(resp.read())


def kubectl_node_count():
    """Get live K8s node count and version from both clusters."""
    total = 0
    version = ""
    per_site = {}
    kubectl = "/home/app-user/.local/bin/kubectl"
    contexts = {
        "kubernetes-admin@kubernetes": "NL",
        "gr": "GR",
    }
    for ctx, site in contexts.items():
        try:
            out = subprocess.check_output(
                [kubectl, "--context", ctx, "get", "nodes", "-o", "json"],
                timeout=10, stderr=subprocess.DEVNULL
            )
            data = json.loads(out)
            nodes = data.get("items", [])
            total += len(nodes)
            per_site[site] = len(nodes)
            if not version and nodes:
                version = nodes[0].get("status", {}).get("nodeInfo", {}).get("kubeletVersion", "")
        except Exception:
            continue
    return total if total > 0 else None, version, per_site


def get_storage_tb():
    """Aggregate ZFS pool sizes from PVE nodes + Synology."""
    total_bytes = 0

    pve_hosts = [
        "nl-pve01", "nl-pve02", "nl-pve03",
        "gr-pve01", "gr-pve02",
    ]
    for host in pve_hosts:
        try:
            if host.startswith("gr"):
                cmd = ["ssh", "-i", "/home/app-user/.ssh/one_key",
                       "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                       f"root@{host}", "zpool list -Hp -o name,size 2>/dev/null || true"]
            else:
                cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
                       host, "zpool list -Hp -o name,size 2>/dev/null || true"]
            out = subprocess.check_output(cmd, timeout=10, stderr=subprocess.DEVNULL).decode()
            for line in out.strip().split("\n"):
                parts = line.split()
                if len(parts) == 2:
                    total_bytes += int(parts[1])
        except Exception:
            continue

    # Non-ZFS storage (hardware RAID / NAS — rarely changes)
    # nl-nas01 (DS1621+): SHR, 5x 24TB Exos = ~72 TB
    # DS1513+: SHR, 4x 14TB IronWolf Pro = ~42 TB
    # gr-pve02: PERC H710P RAID5 14.5TB + RAID0 7.3TB = ~22 TB
    extra_tb = 72 + 42 + 22
    total_tb = total_bytes / (1024 ** 4)

    if total_tb > 5:
        total_tb += extra_tb
    else:
        total_tb = 148

    return round(total_tb)


def get_device_roles():
    """Get device counts grouped by role."""
    data = nb_list("/api/dcim/device-roles/", "&fields=id,name,slug")
    roles = data.get("results", [])
    role_counts = []
    for role in roles:
        count = nb_count("/api/dcim/devices/", f"&role_id={role['id']}")
        if count > 0:
            role_counts.append({
                "role": role["name"],
                "slug": role["slug"],
                "count": count,
            })
    role_counts.sort(key=lambda x: -x["count"])
    return role_counts


def get_per_site_counts():
    """Get device and VM counts per site."""
    sites_data = nb_list("/api/dcim/sites/", "&fields=id,name,slug")
    sites = []
    for site in sites_data.get("results", []):
        sid = site["id"]
        devs = nb_count("/api/dcim/devices/", f"&site_id={sid}")
        vms = nb_count("/api/virtualization/virtual-machines/", f"&site_id={sid}")
        sites.append({
            "name": site["name"],
            "slug": site["slug"],
            "devices": devs,
            "vms": vms,
            "total": devs + vms,
        })
    sites.sort(key=lambda x: -x["total"])
    return sites


def get_n8n_workflow_stats():
    """Count gateway workflows and total nodes from exported JSON files."""
    import glob
    import os
    wf_dir = "/app/claude-gateway/workflows"
    try:
        files = glob.glob(os.path.join(wf_dir, "claude-gateway-*.json"))
        count = 0
        total_nodes = 0
        for f in files:
            with open(f) as fh:
                wf = json.load(fh)
            name = wf.get("name", "")
            if name.startswith("NL - ") or name.startswith("GR - "):
                count += 1
                total_nodes += len(wf.get("nodes", []))
        return count, total_nodes
    except Exception:
        return None, None


# Edge VPS nodes (not in the PVE cluster — standalone, SSH'd individually).
# Keyed by hostname; site label is for grouping/cross-check with the portfolio.
EDGE_VPS = ["chzrh01vps01", "notrf01vps01", "txhou01vps01"]

# PVE cluster members to query for node aggregates. NL+GR share ONE Proxmox
# cluster, so `pvesh get /cluster/resources --type node` against ANY member
# returns all nodes. nl-pve01 is the documented "Known Host Pressure" host
# and has repeatedly wedged its pmxcfs under load (2026-06-23/-27/-30) — when
# pmxcfs stalls, a pvesh call enters D-state and CANNOT be killed (not even by
# the SSH client dying), so a caller pinned to pve01 strands a permanent orphan
# every poll and 100+ of them deadlock pmxcfs entirely. Query a HEALTHY member
# first; pve01 stays last as a fallback only. Env-overridable.
PVE_CLUSTER_HOSTS = [
    h.strip() for h in os.environ.get(
        "LAB_STATS_PVE_HOSTS",
        "nl-pve03,nlpve04,nl-pve02,nl-pve01",
    ).split(",") if h.strip()
]

# Single RTX 3090 Ti (24 GiB), PCI-passed-through to the gpu01 VM on pve03 —
# invisible to the host's nvidia-smi, so it can't be probed live. Stable constant.
GPU_VRAM_GB = 24


def get_compute():
    """Live per-site compute aggregates + host list.

    NL and GR PVE hosts share ONE Proxmox cluster, so a single
    `pvesh get /cluster/resources` returns all nodes; split by hostname prefix.
    Edge VPS are standalone — SSH each for nproc / RAM / disk.

    Auto-discovers new hosts (e.g. a freshly-added PVE node or VPS appears in
    the aggregates with no code change), so the portfolio Summary can never
    silently understate the fleet the way the old hardcoded numbers did.
    """
    compute = {
        "nl": {"threads": 0, "ram_gb": 0, "hosts": []},
        "gr": {"threads": 0, "ram_gb": 0, "hosts": []},
        "edge": {"threads": 0, "ram_gb": 0, "storage_gb": 0, "hosts": []},
        "gpu_vram_gb": GPU_VRAM_GB,
    }

    # --- PVE cluster nodes (NL + GR in one cluster) ---
    # Try each cluster member in turn (healthy host first, pve01 last) so a
    # single wedged host can neither dark-stall the call nor strand D-state
    # pvesh orphans. Server-side `timeout` reclaims a slow-but-not-wedged pmxcfs.
    out = None
    for host in PVE_CLUSTER_HOSTS:
        try:
            cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=8",
                   host,
                   "timeout 20 pvesh get /cluster/resources --type node "
                   "--output-format json 2>/dev/null"]
            out = subprocess.check_output(cmd, timeout=30, stderr=subprocess.DEVNULL).decode()
            break
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, Exception):
            continue
    try:
        if out is None:
            raise RuntimeError("all PVE cluster members unreachable")
        for n in json.loads(out):
            name = n.get("node", "")
            threads = int(n.get("maxcpu", 0) or 0)
            ram_gb = round(int(n.get("maxmem", 0) or 0) / (1024 ** 3))
            if name.startswith("nl"):
                site = "nl"
            elif name.startswith("gr"):
                site = "gr"
            else:
                continue
            compute[site]["threads"] += threads
            compute[site]["ram_gb"] += ram_gb
            compute[site]["hosts"].append({"node": name, "threads": threads, "ram_gb": ram_gb})
        compute["nl"]["hosts"].sort(key=lambda h: h["node"])
        compute["gr"]["hosts"].sort(key=lambda h: h["node"])
    except Exception:
        pass

    # --- Edge VPS (standalone) ---
    for host in EDGE_VPS:
        try:
            probe = "echo $(nproc) $(free -m | awk '/Mem:/{print $2}') " \
                    "$(df -BG --output=size / | tail -1 | tr -dc '0-9')"
            cmd = ["ssh", "-i", "/home/app-user/.ssh/one_key",
                   "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=8",
                   f"operator@{host}", probe]
            out = subprocess.check_output(cmd, timeout=12, stderr=subprocess.DEVNULL).decode().split()
            threads = int(out[0])
            ram_gb = round(int(out[1]) / 1024)
            disk_gb = int(out[2])
            compute["edge"]["threads"] += threads
            compute["edge"]["ram_gb"] += ram_gb
            compute["edge"]["storage_gb"] += disk_gb
            compute["edge"]["hosts"].append({
                "node": host, "threads": threads, "ram_gb": ram_gb, "storage_gb": disk_gb,
            })
        except Exception:
            continue

    return compute


try:
    # --- NetBox core counts ---
    devices = nb_count("/api/dcim/devices/")
    vms = nb_count("/api/virtualization/virtual-machines/")
    ips = nb_count("/api/ipam/ip-addresses/")
    prefixes = nb_count("/api/ipam/prefixes/")
    vlans = nb_count("/api/ipam/vlans/")
    phys_interfaces = nb_count("/api/dcim/interfaces/")
    vm_interfaces = nb_count("/api/virtualization/interfaces/")
    cables = nb_count("/api/dcim/cables/")
    sites_count = nb_count("/api/dcim/sites/")
    manufacturers = nb_count("/api/dcim/manufacturers/")

    # --- K8s: prefer live kubectl, fall back to NetBox ---
    k8s_ctrl_nb = nb_count("/api/virtualization/virtual-machines/", f"&role_id={ROLE_K8S_CTRL}")
    k8s_worker_nb = nb_count("/api/virtualization/virtual-machines/", f"&role_id={ROLE_K8S_WORKER}")
    k8s_count, k8s_version, k8s_per_site = kubectl_node_count()
    if k8s_count is None:
        k8s_count = k8s_ctrl_nb + k8s_worker_nb
    if not k8s_version:
        k8s_version = "v1.34.2"

    # --- Storage ---
    storage_tb = get_storage_tb()

    # --- Device inventory by role ---
    device_roles = get_device_roles()

    # --- Per-site breakdown ---
    site_breakdown = get_per_site_counts()

    # --- n8n workflow stats ---
    wf_count, wf_nodes = get_n8n_workflow_stats()

    # --- Live compute aggregates (PVE cluster + edge VPS) ---
    compute = get_compute()

    # --- Build response ---
    result = {
        # At a Glance cards
        "managed_objects": {
            "total": devices + vms,
            "detail": f"{devices} devices + {vms} VMs",
        },
        "kubernetes_nodes": {
            "total": k8s_count,
            "detail": f"{k8s_version} / Cilium CNI",
            "per_site": k8s_per_site,
        },
        "raw_storage_tb": {
            "total": storage_tb,
            "detail": "ZFS + SHR + SeaweedFS",
        },
        "ip_addresses": {
            "total": ips,
            "detail": f"{prefixes} prefixes / {vlans} VLANs",
        },
        "iot_devices": {
            "total": next((r["count"] for r in device_roles if r["slug"] == "iot-device"), 0),
            "detail": "Zigbee / ESPHome / Frigate",
        },
        "network_interfaces": {
            "total": phys_interfaces + vm_interfaces,
            "detail": f"{cables} documented cables",
        },

        # Platform stack
        "platform": {
            "sites": sites_count,
            "manufacturers": manufacturers,
            "workflows": wf_count,
            "workflow_nodes": wf_nodes,
        },

        # Device inventory by role
        "device_roles": device_roles,

        # Per-site breakdown
        "sites": site_breakdown,

        # Live compute aggregates + host discovery (PVE cluster + edge VPS)
        "compute": compute,

        "updated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    print(json.dumps(result))

except Exception as e:
    import traceback
    print(json.dumps({
        "error": str(e),
        "traceback": traceback.format_exc(),
        "updated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }))
