#!/usr/bin/env bash
# Generate synthetic alert scenarios for evaluation
# Produces scripts/eval-sets/synthetic.json with 40 scenarios
# 8 categories x 5 variations each, with perturbations
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${SCRIPT_DIR}/eval-sets/synthetic.json"

# Hostname pools per site
NL_HOSTS=(
  nl-pve01 nl-pve02 nl-pve03
  nl-nas01 nl-nas02
  nl-gpu01
  nl-fw01
  nlk8sctrl01 nlk8sctrl02 nlk8sctrl03
  nlk8swrkr01 nlk8swrkr02 nlk8swrkr03
)
GR_HOSTS=(
  gr-pve01 gr-pve02
  gr-pihole01
  gr-fw01
  grk8sctrl01 grk8sctrl02 grk8sctrl03
)

# Perturbation functions
perturb_hostname() {
  local host="$1"
  local variant="$2"
  case $variant in
    0) echo "$host" ;;                                    # clean
    1) echo "${host^^}" ;;                                # ALL CAPS
    2) echo " ${host} " ;;                                # extra whitespace
    3) echo "${host/01/1}" ;;                             # drop leading zero
    4) local mid=$((${#host} / 2)); echo "${host:0:$mid}${host:$mid}" ;;  # clean (fallback)
  esac
}

get_site() {
  local host="$1"
  if [[ "$host" == nl* ]]; then echo "nl"; else echo "gr"; fi
}

get_yt_project() {
  local host="$1"
  if [[ "$host" == nl* ]]; then echo "IFRNLLEI01PRD"; else echo "IFRGRSKG01PRD"; fi
}

get_matrix_room() {
  local host="$1"
  if [[ "$host" == nl* ]]; then echo "#infra-nl-prod"; else echo "#infra-gr-prod"; fi
}

# Build JSON using python for correctness
export SYNTHETIC_OUTPUT="$OUTPUT"
python3 << 'PYEOF'
import json
import os
import random

random.seed(42)

NL_HOSTS = [
    "nl-pve01", "nl-pve02", "nl-pve03",
    "nl-nas01", "nl-nas02",
    "nl-gpu01",
    "nl-fw01",
    "nlk8sctrl01", "nlk8sctrl02", "nlk8sctrl03",
    "nlk8swrkr01", "nlk8swrkr02", "nlk8swrkr03",
]
GR_HOSTS = [
    "gr-pve01", "gr-pve02",
    "gr-pihole01",
    "gr-fw01",
    "grk8sctrl01", "grk8sctrl02", "grk8sctrl03",
]
ALL_HOSTS = NL_HOSTS + GR_HOSTS
SEVERITIES = ["critical", "warning", "critical", "warning", "critical"]

def site_of(h):
    return "nl" if h.startswith("nl") else "gr"

def yt_project(h):
    return "IFRNLLEI01PRD" if h.startswith("nl") else "IFRGRSKG01PRD"

def matrix_room(h):
    return "#infra-nl-prod" if h.startswith("nl") else "#infra-gr-prod"

def perturb(h, variant):
    if variant == 0:
        return h
    elif variant == 1:
        return h.upper()
    elif variant == 2:
        return f"  {h}  "
    elif variant == 3:
        return h.replace("01", "1", 1)
    else:
        return h

# ── Template definitions ──────────────────────────────────────────────

templates = []

# 1. Availability (5 variations)
avail_rules = [
    "Device Down! Due to no ICMP response.",
    "Device Down! Due to no SNMP response.",
    "Host unreachable — ping timeout after 30s",
    "Device offline — no response to health check",
    "Device Down! Due to no ICMP response.",
]
avail_hosts = [NL_HOSTS[0], GR_HOSTS[0], NL_HOSTS[5], GR_HOSTS[2], NL_HOSTS[1]]
for i in range(5):
    h = avail_hosts[i]
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Availability: {avail_rules[i][:40]} ({site_of(h).upper()})",
        "category": "availability",
        "site": site_of(h),
        "payload": {
            "alert_type": "librenms",
            "hostname": perturb(h, i),
            "alert_rule": avail_rules[i],
            "severity": SEVERITIES[i],
            "state": "alert",
        },
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(h),
            "matrix_room": matrix_room(h),
            "triage_must_contain": ["netbox", "ping"],
            "confidence_range": [0.3, 0.9],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "max_cost_usd": 3.0,
            "alert_category": "availability",
        },
    })

# 2. Resource (5 variations)
res_rules = [
    "CPU usage exceeds 90% threshold",
    "Memory usage critical — 95% utilized",
    "High CPU load average on host",
    "Swap usage exceeds 80%",
    "OOM condition detected on host",
]
res_hosts = [NL_HOSTS[0], GR_HOSTS[0], NL_HOSTS[5], NL_HOSTS[1], GR_HOSTS[1]]
for i in range(5):
    h = res_hosts[i]
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Resource: {res_rules[i][:40]} ({site_of(h).upper()})",
        "category": "resource",
        "site": site_of(h),
        "payload": {
            "alert_type": "librenms",
            "hostname": perturb(h, i),
            "alert_rule": res_rules[i],
            "severity": SEVERITIES[i],
            "state": "alert",
        },
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(h),
            "matrix_room": matrix_room(h),
            "triage_must_contain": ["resource", "usage"],
            "confidence_range": [0.3, 0.9],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "max_cost_usd": 3.0,
            "alert_category": "resource",
        },
    })

# 3. Storage (5 variations)
sto_rules = [
    "Disk usage exceeds 90% on /data",
    "iSCSI LUN latency exceeds 50ms threshold",
    "NFS mount stale on Synology target",
    "Storage pool usage critical — 92% full",
    "SeaweedFS volume server unreachable",
]
sto_hosts = [NL_HOSTS[3], GR_HOSTS[1], NL_HOSTS[4], NL_HOSTS[0], NL_HOSTS[3]]
for i in range(5):
    h = sto_hosts[i]
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Storage: {sto_rules[i][:40]} ({site_of(h).upper()})",
        "category": "storage",
        "site": site_of(h),
        "payload": {
            "alert_type": "librenms" if i < 3 else "prometheus",
            "hostname": perturb(h, i),
            "alert_rule": sto_rules[i],
            "severity": SEVERITIES[i],
            "state": "alert" if i < 3 else "firing",
        },
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(h),
            "matrix_room": matrix_room(h),
            "triage_must_contain": ["storage", "disk"],
            "confidence_range": [0.3, 0.9],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "max_cost_usd": 3.0,
            "alert_category": "storage",
        },
    })

# 4. Network (5 variations)
net_rules = [
    "Port status up/down on interface GigabitEthernet0/24",
    "BGP neighbor 10.0.X.X down",
    "VLAN 181 trunk port flapping",
    "Interface down on Gi0/12 — CRC errors",
    "VPN tunnel to gr-fw01 unreachable",
]
net_hosts = [NL_HOSTS[6], GR_HOSTS[3], NL_HOSTS[6], GR_HOSTS[3], NL_HOSTS[6]]
for i in range(5):
    h = net_hosts[i]
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Network: {net_rules[i][:40]} ({site_of(h).upper()})",
        "category": "network",
        "site": site_of(h),
        "payload": {
            "alert_type": "librenms",
            "hostname": perturb(h, i),
            "alert_rule": net_rules[i],
            "severity": SEVERITIES[i],
            "state": "alert",
        },
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(h),
            "matrix_room": matrix_room(h),
            "triage_must_contain": ["interface", "network"],
            "confidence_range": [0.3, 0.9],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "max_cost_usd": 2.0,
            "alert_category": "network",
        },
    })

# 5. Kubernetes (5 variations)
k8s_rules = [
    {"alertname": "ContainerOOMKilled", "namespace": "logging", "pod": "loki-0"},
    {"alertname": "etcdInsufficientMembers", "namespace": "kube-system", "pod": "etcd-ctrl01"},
    {"alertname": "KubePodCrashLooping", "namespace": "monitoring", "pod": "prometheus-0"},
    {"alertname": "CiliumAgentUnhealthy", "namespace": "kube-system", "pod": "cilium-agent-abc12"},
    {"alertname": "NodeNotReady", "namespace": "", "pod": ""},
]
k8s_hosts = [NL_HOSTS[10], NL_HOSTS[7], GR_HOSTS[4], NL_HOSTS[11], GR_HOSTS[5]]
for i in range(5):
    h = k8s_hosts[i]
    rule = k8s_rules[i]
    payload = {
        "alert_type": "prometheus",
        "alertname": rule["alertname"],
        "namespace": rule["namespace"],
        "severity": SEVERITIES[i],
        "status": "firing",
    }
    if rule["pod"]:
        payload["pod"] = rule["pod"]
    else:
        payload["instance"] = perturb(h, i)
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Kubernetes: {rule['alertname']} ({site_of(h).upper()})",
        "category": "kubernetes",
        "site": site_of(h),
        "payload": payload,
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(h),
            "matrix_room": matrix_room(h),
            "triage_must_contain": ["kubectl", "pod"],
            "confidence_range": [0.3, 0.9],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "max_cost_usd": 3.0,
            "alert_category": "kubernetes",
        },
    })

# 6. Certificate (5 variations)
cert_rules = [
    "TLS certificate expiring in 7 days for matrix.example.net",
    "SSL certificate expired on n8n.example.net",
    "Certificate expiry warning — 3 days remaining",
    "TLS handshake failure on port 443",
    "Certificate chain incomplete — missing intermediate",
]
cert_hosts = [NL_HOSTS[0], NL_HOSTS[2], GR_HOSTS[0], NL_HOSTS[1], GR_HOSTS[1]]
for i in range(5):
    h = cert_hosts[i]
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Certificate: {cert_rules[i][:40]} ({site_of(h).upper()})",
        "category": "certificate",
        "site": site_of(h),
        "payload": {
            "alert_type": "prometheus",
            "hostname": perturb(h, i),
            "alert_rule": cert_rules[i],
            "severity": SEVERITIES[i],
            "state": "firing",
        },
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(h),
            "matrix_room": matrix_room(h),
            "triage_must_contain": ["certificate", "expir"],
            "confidence_range": [0.3, 0.9],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "max_cost_usd": 2.0,
            "alert_category": "certificate",
        },
    })

# 7. Maintenance (5 variations)
maint_rules = [
    "Scheduled maintenance on PVE host — kernel upgrade",
    "Firmware upgrade in progress on Synology NAS",
    "Scheduled reboot — ASA watchdog timer expiring",
    "Maintenance window active — K8s node drain",
    "Scheduled upgrade — PVE host kernel 6.8 to 6.11",
]
maint_hosts = [NL_HOSTS[1], NL_HOSTS[3], GR_HOSTS[3], NL_HOSTS[10], GR_HOSTS[0]]
for i in range(5):
    h = maint_hosts[i]
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Maintenance: {maint_rules[i][:40]} ({site_of(h).upper()})",
        "category": "maintenance",
        "site": site_of(h),
        "payload": {
            "alert_type": "librenms",
            "hostname": perturb(h, i),
            "alert_rule": maint_rules[i],
            "severity": "warning",
            "state": "alert",
            "maintenance_context": True,
        },
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(h),
            "matrix_room": matrix_room(h),
            "triage_must_contain": ["maintenance", "scheduled"],
            "confidence_range": [0.3, 0.8],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "max_cost_usd": 2.0,
            "alert_category": "maintenance",
        },
    })

# 8. Correlated (5 variations)
corr_groups = [
    {"hosts": ["nl-pve01", "nl-pve02", "nl-pve03"], "rule": "Service up/down", "burst": 3},
    {"hosts": ["gr-pve01", "gr-pve02", "gr-pihole01"], "rule": "Device Down!", "burst": 3},
    {"hosts": ["nlk8swrkr01", "nlk8swrkr02", "nlk8swrkr03"], "rule": "Node NotReady", "burst": 3},
    {"hosts": ["nl-nas01", "nl-nas02"], "rule": "Storage offline", "burst": 2},
    {"hosts": ["grk8sctrl01", "grk8sctrl02", "grk8sctrl03", "gr-fw01"], "rule": "Multiple alerts", "burst": 4},
]
for i in range(5):
    g = corr_groups[i]
    primary = g["hosts"][0]
    templates.append({
        "id": f"SYN-{len(templates)+1:02d}",
        "name": f"Correlated: {g['rule']} — {g['burst']} hosts ({site_of(primary).upper()})",
        "category": "correlated",
        "site": site_of(primary),
        "payload": {
            "alert_type": "correlated",
            "hosts": g["hosts"],
            "alert_rule": g["rule"],
            "severity": SEVERITIES[i],
            "burst_count": g["burst"],
            "burst_window_minutes": 5,
        },
        "expected": {
            "issue_created": True,
            "yt_project": yt_project(primary),
            "matrix_room": matrix_room(primary),
            "triage_must_contain": ["correlated", "shared root cause"],
            "confidence_range": [0.3, 0.8],
            "must_have_react": True,
            "must_have_approval_gate": True,
            "must_have_poll": True,
            "max_cost_usd": 5.0,
            "alert_category": "correlated",
            "plan_mode": True,
        },
    })

# Verify count
assert len(templates) == 40, f"Expected 40 scenarios, got {len(templates)}"

# Write output
output_path = os.environ["SYNTHETIC_OUTPUT"]

with open(output_path, "w") as f:
    json.dump(templates, f, indent=2)

print(f"Generated {len(templates)} synthetic scenarios")
for cat in ["availability", "resource", "storage", "network", "kubernetes", "certificate", "maintenance", "correlated"]:
    count = sum(1 for t in templates if t["category"] == cat)
    print(f"  {cat}: {count}")
PYEOF

echo "Wrote $(python3 -c "import json; print(len(json.load(open('$OUTPUT'))))" ) scenarios to $OUTPUT"
