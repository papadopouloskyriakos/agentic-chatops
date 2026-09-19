#!/usr/bin/env python3
"""Live service health aggregator for portfolio status page.

Queries Gatus API for endpoint statuses, adds supplementary checks
(CrowdSec, ClusterMesh, Ollama, n8n, Matrix, YouTrack) from Prometheus
and direct HTTP probes. OpenClaw probe was removed 2026-05-01 after
the LXC was stopped during the 2026-04-29 cc-cc cutover.

Called by n8n webhook via SSH. Output: sanitized JSON.
"""
import json
import datetime
import os
import subprocess
import urllib.request
import ssl

GATUS_NL_URL = "https://nl-gatus.example.net/api/v1/endpoints/statuses?page=1&pageSize=100"
GATUS_GR_URL = "https://gr-gatus.example.net/api/v1/endpoints/statuses?page=1&pageSize=100"
PROM_URL = "http://10.0.X.X:30090"
PROM_GR_URL = "http://10.0.58.X:30090"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# Services to EXCLUDE from Gatus (replaced by better checks or not portfolio-worthy)
EXCLUDE = {
    "Goldpinger (NL)", "Goldpinger (GR)",
    "Hubble UI (NL)", "Hubble UI (GR)",
    "K8s Dashboard (NL)", "K8s Dashboard (GR)",
    "Velero UI",
    "IPsec Tunnels",  # replaced by live VTI check from mesh-stats
}

# Remap Gatus group names (strip emojis)
GROUP_MAP = {
    "\U0001f310 Network (AS64512)": "Network (AS64512)",
    "\U0001f527 Core Platform": "Core Platform",
    "\U0001f4be Storage & Backup": "Storage & Backup",
    "\U0001f4ca Observability": "Observability",
    "\U0001f504 GitOps & Automation": "GitOps & Automation",
    "\U0001f512 Security & Secrets": "Security & Detection",
    "\U0001f4f1 Applications": "Applications",
}

# Category sort order
CATEGORY_ORDER = [
    "Network (AS64512)",
    "Core Platform",
    "AI & Automation",
    "Storage & Backup",
    "Observability",
    "GitOps & Automation",
    "Security & Detection",
    "Applications",
]


def gatus_fetch(url=None, retries=3):
    """Fetch all endpoint statuses from a Gatus API instance. L6: retry with backoff."""
    import time as _time
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url or GATUS_NL_URL)
            with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception:
            if attempt < retries - 1:
                _time.sleep(0.5 * (attempt + 1))
    return []


def prom_query(query):
    """Execute a PromQL instant query."""
    url = f"{PROM_URL}/api/v1/query?query={urllib.request.quote(query)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "success":
                return data["data"]["result"]
    except Exception:
        pass
    return []


def http_check(url, timeout=5):
    """Quick HTTP health check. Returns (up, response_time_ms)."""
    import time
    try:
        req = urllib.request.Request(url)
        start = time.time()
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as resp:
            elapsed = int((time.time() - start) * 1000)
            return resp.status < 400, elapsed
    except Exception:
        return False, 0


def http_check_from_gr(urls):
    """Run HTTP checks from GR site via grclaude01. Returns {url: [up, rt_ms]}."""
    import tempfile

    url_list = json.dumps(urls)
    script = f"""import json,time,urllib.request,ssl
ctx=ssl.create_default_context()
ctx.check_hostname=False
ctx.verify_mode=ssl.CERT_NONE
urls={url_list}
R={{}}
for u in urls:
    try:
        s=time.time();urllib.request.urlopen(u,context=ctx,timeout=5);R[u]=[True,int((time.time()-s)*1000)]
    except:
        R[u]=[False,0]
print(json.dumps(R))
"""
    # Write script locally, SCP to GR, execute, clean up
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        local_path = f.name

    try:
        remote_path = "/tmp/_gr_health_check.py"
        subprocess.run(
            ["scp", "-P", "2222", "-o", "StrictHostKeyChecking=no",
             "-i", os.path.expanduser("~/.ssh/one_key"),
             local_path, f"app-user@203.0.113.X:{remote_path}"],
            capture_output=True, timeout=10,
        )
        result = subprocess.run(
            ["ssh", "-p", "2222", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=10", "-i", os.path.expanduser("~/.ssh/one_key"),
             "app-user@203.0.113.X",
             f"python3 {remote_path}"],
            capture_output=True, text=True, timeout=60,
        )
        if result.stdout.strip():
            return json.loads(result.stdout)
        return {url: [None, -1] for url in urls}  # H5: distinguish "unknown" from "down"
    except Exception:
        return {url: [None, -1] for url in urls}  # H5: SSH failure = unknown, not down
    finally:
        os.unlink(local_path)


def prom_query_gr(query):
    """Execute a PromQL query against GR Prometheus via SSH."""
    try:
        encoded = urllib.request.quote(query)
        result = subprocess.run(
            ["ssh", "-p", "2222", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=10", "-i", os.path.expanduser("~/.ssh/one_key"),
             "app-user@203.0.113.X",
             f"curl -s --max-time 5 'http://10.0.58.X:30090/api/v1/query?query={encoded}'"],
            capture_output=True, text=True, timeout=20,
        )
        if result.stdout.strip():
            data = json.loads(result.stdout)
            if data.get("status") == "success":
                return data["data"]["result"]
    except Exception:
        pass
    return []


def get_gr_prometheus_checks():
    """Run the same Prometheus-based checks from GR Prometheus perspective."""
    checks = {}

    # FRR BGP Sessions (state=1 means Established in frr_exporter)
    results = prom_query_gr("frr_bgp_peer_state")
    established = sum(1 for r in results if int(float(r["value"][1])) == 1)
    checks["FRR BGP Sessions"] = {"up": established > 0, "rt": 0}

    # Cilium BGP Sessions
    results = prom_query_gr("cilium_bgp_control_plane_session_state")
    cilium_up = sum(1 for r in results if int(float(r["value"][1])) == 1)
    checks["Cilium BGP Sessions"] = {"up": cilium_up > 0, "rt": 0}

    # ClusterMesh
    results = prom_query_gr("cilium_clustermesh_remote_cluster_readiness_status")
    cm_up = any(int(float(r["value"][1])) == 1 for r in results)
    checks["ClusterMesh"] = {"up": cm_up, "rt": 0}

    # VTI Tunnels — cross-site, same from both perspectives
    checks["VTI Tunnels"] = None

    # Edge NO/CH — cross-site, same from both perspectives
    checks["Edge: Sandefjord (NO)"] = None
    checks["Edge: Zürich (CH)"] = None

    # Cilium CNI — check agent is running via any cilium metric
    results = prom_query_gr("cilium_agent_api_process_time_seconds_count")
    checks["Cilium CNI (NL)"] = {"up": len(results) > 0, "rt": 0}
    checks["Cilium CNI (GR)"] = {"up": len(results) > 0, "rt": 0}

    # K8s API
    results = prom_query_gr('up{job="apiserver"}')
    checks["NL Kubernetes API"] = {"up": any(int(float(r["value"][1])) == 1 for r in results), "rt": 0}
    checks["GR Kubernetes API"] = {"up": any(int(float(r["value"][1])) == 1 for r in results), "rt": 0}

    # Loki, cert-manager, CrowdSec, SeaweedFS S3 — these run on NL K8s only
    # or are not scraped by GR Prometheus. For the GR column, we confirm
    # cross-site reachability (if the NL check is up and GR→NL tunnel is up,
    # the service is reachable from GR). Mark as None to inherit from NL status.
    # CrowdSec: site-specific, checked from respective Prometheus
    # cert-manager: NL K8s only, not scraped by GR
    for name in ["CrowdSec LAPI (NL)", "CrowdSec LAPI (GR)", "cert-manager"]:
        checks[name] = None

    return checks


def get_supplementary_checks():
    """Additional checks not in Gatus: AI services, ChatOps, CrowdSec, ClusterMesh."""
    checks = []

    # Ollama (GPU inference)
    up, rt = http_check("https://ollama.example.net/api/tags")
    checks.append({
        "name": "Ollama (RTX 3090 Ti)",
        "group": "AI & Automation",
        "up": up,
        "response_time_ms": rt,
        "site": "NL",
    })

    # OpenClaw probe removed 2026-05-01: LXC VMID_REDACTED stopped (onboot=0) during
    # the 2026-04-29 cc-cc cutover. Tier 1 dispatch is now deterministic shell on
    # nl-claude01 via run-triage.sh — no Tier 1 LLM endpoint to probe.

    # n8n
    up, rt = http_check("https://n8n.example.net/healthz")
    checks.append({
        "name": "n8n Workflows",
        "group": "AI & Automation",
        "up": up,
        "response_time_ms": rt,
        "site": "NL",
    })

    # Matrix/Synapse
    up, rt = http_check("https://matrix.example.net/_matrix/client/versions")
    checks.append({
        "name": "Matrix (Synapse)",
        "group": "AI & Automation",
        "up": up,
        "response_time_ms": rt,
        "site": "NL",
    })

    # YouTrack
    up, rt = http_check("https://youtrack.example.net/api/config")
    checks.append({
        "name": "YouTrack",
        "group": "AI & Automation",
        "up": up,
        "response_time_ms": rt,
        "site": "NL",
    })

    # VTI Tunnels (from mesh-stats API — live SSH check)
    try:
        with urllib.request.urlopen("https://n8n.example.net/webhook/mesh-stats",
                                    context=CTX, timeout=30) as resp:
            mesh = json.loads(resp.read())
            tunnels = mesh.get("tunnels", [])
            tun_active = sum(1 for t in tunnels if t.get("status") == "up")
            tun_standby = sum(1 for t in tunnels if t.get("status") == "standby")
            tun_down = len(tunnels) - tun_active - tun_standby
            tun_total = len(tunnels) or 9
            label = f"VTI Tunnels ({tun_active}/{tun_total}"
            if tun_standby:
                label += f", {tun_standby} standby"
            label += ")"
            checks.append({
                "name": label,
                "group": "Network (AS64512)",
                "up": tun_down == 0,  # standby is healthy
                "response_time_ms": 0,
                "site": "cross-site",
            })
    except Exception:
        checks.append({
            "name": "VTI Tunnels",
            "group": "Network (AS64512)",
            "up": False,
            "response_time_ms": 0,
            "site": "cross-site",
        })

    # ClusterMesh (from Prometheus)
    clustermesh_up = False
    for r in prom_query("cilium_clustermesh_remote_cluster_readiness_status"):
        if int(float(r["value"][1])) == 1:
            clustermesh_up = True
    checks.append({
        "name": "ClusterMesh",
        "group": "Network (AS64512)",
        "up": clustermesh_up,
        "response_time_ms": 0,
        "site": "cross-site",
    })

    # CrowdSec NL (from Prometheus - check LAPI is up)
    crowdsec_nl_up = False
    for r in prom_query('up{job="crowdsec", instance=~"nl.*"}'):
        crowdsec_nl_up = int(float(r["value"][1])) == 1
    if not crowdsec_nl_up:
        # Fallback: direct check
        crowdsec_nl_up, _ = http_check("http://10.0.X.X:30090/api/v1/query?query=up", timeout=3)
    checks.append({
        "name": "CrowdSec LAPI (NL)",
        "group": "Security & Detection",
        "up": crowdsec_nl_up,
        "response_time_ms": 0,
        "site": "NL",
        "_merge_id": "crowdsec",
    })

    # CrowdSec GR
    crowdsec_gr_up = False
    for r in prom_query('up{job="crowdsec", instance=~"gr.*"}'):
        crowdsec_gr_up = int(float(r["value"][1])) == 1
    checks.append({
        "name": "CrowdSec LAPI (GR)",
        "group": "Security & Detection",
        "up": crowdsec_gr_up,
        "response_time_ms": 0,
        "site": "GR",
        "_merge_id": "crowdsec",
    })

    return checks


def _parse_gatus(data):
    """Parse Gatus endpoint list into {name: {up, rt_ms, group, uptime_pct}} dict."""
    result = {}
    for ep in data:
        name = ep.get("name", "")
        if name in EXCLUDE:
            continue
        group = GROUP_MAP.get(ep.get("group", ""), ep.get("group", ""))
        results = ep.get("results", [])
        last = results[-1] if results else {}
        up = last.get("success", False)
        duration_ns = last.get("duration", 0)
        rt_ms = duration_ns // 1000000 if duration_ns > 100000 else duration_ns
        uptime_pct = 0
        if results:
            recent = results[-20:]
            uptime_pct = round(sum(1 for r in recent if r.get("success")) / len(recent) * 100, 1)
        result[name] = {"up": up, "rt_ms": rt_ms, "group": group, "uptime_pct": uptime_pct}
    return result


def main():
    from concurrent.futures import ThreadPoolExecutor

    # Dual-Gatus: NL checks from NL, GR checks from GR — no SSH backfill needed
    # Also run GR HTTP batch for supplementary services not in GR Gatus
    # OpenClaw URL removed 2026-05-01 with the cc-cc cutover.
    supp_gr_urls = [
        "https://ollama.example.net/api/tags",
        "https://n8n.example.net/healthz",
        "https://matrix.example.net/_matrix/client/versions",
        "https://youtrack.example.net/api/config",
    ]
    supp_gr_name_map = {
        "ollama.example.net": "Ollama (RTX 3090 Ti)",
        "n8n.example.net": "n8n Workflows",
        "matrix.example.net": "Matrix (Synapse)",
        "youtrack.example.net": "YouTrack",
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_nl = pool.submit(gatus_fetch, GATUS_NL_URL)
        f_gr = pool.submit(gatus_fetch, GATUS_GR_URL)
        f_supp = pool.submit(get_supplementary_checks)
        f_gr_http = pool.submit(http_check_from_gr, supp_gr_urls)

    nl_gatus = _parse_gatus(f_nl.result())
    gr_gatus = _parse_gatus(f_gr.result())
    supplementary = f_supp.result()
    gr_supp = {}
    for url, (up, rt) in f_gr_http.result().items():
        for domain, name in supp_gr_name_map.items():
            if domain in url:
                gr_supp[name] = {"up": up, "rt_ms": rt}

    # Override NL Gatus timeouts with direct checks from this host
    # (Gatus K8s pod can't reach VPS HAProxy directly, but claude01 can via VTI)
    for name in list(nl_gatus.keys()):
        if nl_gatus[name]["rt_ms"] > 5000 and nl_gatus[name]["up"] is False:
            # Try direct HTTP check as fallback
            gatus_url = None
            if "Sandefjord" in name:
                gatus_url = "https://198.51.100.X"
            elif "rich" in name:
                gatus_url = "https://198.51.100.X"
            if gatus_url:
                ok, rt = http_check(gatus_url, timeout=8)
                if ok:
                    nl_gatus[name]["up"] = True
                    nl_gatus[name]["rt_ms"] = rt

    # Merge NL + GR Gatus by name. NL is primary (determines group, up status).
    # Services in NL but not GR: assume cross-site reachable, mirror NL status
    services = []
    for name, nl in nl_gatus.items():
        gr = gr_gatus.get(name, {"rt_ms": nl["rt_ms"], "up": nl["up"]})
        # Determine site from name
        site = "cross-site"
        if "(NL)" in name:
            site = "NL"
        elif "(GR)" in name:
            site = "GR"
        elif "GR " in name:
            site = "GR"
        elif "NL " in name:
            site = "NL"

        services.append({
            "name": name,
            "group": nl["group"],
            "up": nl["up"] or gr.get("up", False),  # operational if EITHER site can reach it
            "up_from_nl": nl["up"],
            "site": site,
            "uptime_pct": nl["uptime_pct"],
            "response_time_nl_ms": nl["rt_ms"],
            "response_time_gr_ms": gr.get("rt_ms"),
            "up_from_gr": gr.get("up"),
        })

    # Add supplementary checks (AI services, VTI, CrowdSec, ClusterMesh)
    for check in supplementary:
        nl_up = check["up"]
        check["response_time_nl_ms"] = check.pop("response_time_ms")
        # Check if GR HTTP batch has this service
        gr_data = gr_supp.get(check["name"])
        if gr_data:
            check["response_time_gr_ms"] = gr_data["rt_ms"]
            check["up_from_gr"] = gr_data["up"]
            check["up"] = check["up"] or gr_data["up"]  # up if either site
        elif check.get("site") == "cross-site":
            check["response_time_gr_ms"] = check["response_time_nl_ms"]
            check["up_from_gr"] = check["up"]
        elif check.get("site") == "GR":
            check["response_time_gr_ms"] = check["response_time_nl_ms"]
            check["response_time_nl_ms"] = 0  # Prometheus check from NL perspective
            check["up_from_gr"] = check["up"]
        else:
            check["response_time_gr_ms"] = None
            check["up_from_gr"] = None
        check.setdefault("up_from_nl", nl_up)
        check["uptime_pct"] = 100.0 if check["up"] else 0.0
        services.append(check)

    # Merge CrowdSec into one entry with both columns (matched by _merge_id, not display name)
    crowdsec_nl = None
    crowdsec_gr = None
    merged = []
    for svc in services:
        mid = svc.get("_merge_id")
        if mid == "crowdsec" and svc.get("site") == "NL":
            crowdsec_nl = svc
        elif mid == "crowdsec" and svc.get("site") == "GR":
            crowdsec_gr = svc
        else:
            merged.append(svc)
    if crowdsec_nl or crowdsec_gr:
        nl_up = (crowdsec_nl or {}).get("up", False)
        gr_up = (crowdsec_gr or {}).get("up", False)
        merged.append({
            "name": "CrowdSec LAPI",
            "group": "Security & Detection",
            "up": nl_up and gr_up,
            "up_from_nl": nl_up,
            "site": "cross-site",
            "uptime_pct": 100.0,
            "response_time_nl_ms": 0 if nl_up else -1,
            "response_time_gr_ms": 0 if gr_up else -1,
            "up_from_gr": gr_up,
        })
    services = merged

    # Group by category
    # Count "up" consistently with what the frontend displays per column:
    # a service is fully operational only if all displayed perspectives agree.
    categories = {}
    for svc in services:
        group = svc["group"]
        if group not in categories:
            categories[group] = {"services": [], "up": 0, "total": 0}
        categories[group]["services"].append(svc)
        categories[group]["total"] += 1
        nl_up = svc.get("up_from_nl") if svc.get("up_from_nl") is not None else svc["up"]
        gr_up = svc.get("up_from_gr")
        if gr_up is not None:
            fully_up = nl_up and gr_up
        else:
            fully_up = nl_up
        if fully_up:
            categories[group]["up"] += 1

    # Build ordered output
    ordered = []
    for cat_name in CATEGORY_ORDER:
        if cat_name in categories:
            cat = categories[cat_name]
            ordered.append({
                "name": cat_name,
                "up": cat["up"],
                "total": cat["total"],
                "services": sorted(cat["services"], key=lambda s: s["name"]),
            })

    # Any remaining categories not in the order
    for cat_name, cat in categories.items():
        if cat_name not in CATEGORY_ORDER:
            ordered.append({
                "name": cat_name,
                "up": cat["up"],
                "total": cat["total"],
                "services": sorted(cat["services"], key=lambda s: s["name"]),
            })

    total_up = sum(c["up"] for c in ordered)
    total_all = sum(c["total"] for c in ordered)

    output = {
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_services": total_all,
        "total_up": total_up,
        "all_operational": total_up == total_all,
        "categories": ordered,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
