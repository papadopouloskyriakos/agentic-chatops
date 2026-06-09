#!/bin/bash
# bgp-mesh-watchdog.sh — Cross-device iBGP mesh health observability
#
# Polls `show bgp summary` on every BGP-speaking device in the mesh
# (nlrtr01, nl-fw01, gr-fw01, nlk8s-frr01/02,
# grk8s-frr01/02, notrf01vps01, chzrh01vps01) and reports whether
# each expected (local_host → neighbor) session is Established.
#
# Single source of truth for the iBGP mesh shape. Catches the class of
# failure where ASA 9.16 silently drops a BGP session without emitting
# a Prometheus signal (ASA 9.16 has no BGP SNMP export).
#
# Cron: */5 * * * * /app/claude-gateway/scripts/bgp-mesh-watchdog.sh
#
# Emits:
#   bgp_session_state{local_host, neighbor} 0|1   (1 = Established)
#   bgp_session_unreachable{local_host} 0|1       (1 = SSH to device failed)
#   bgp_mesh_established_count
#   bgp_mesh_missing_count                          (expected - established - unreachable)
#   bgp_mesh_total_expected
#   bgp_mesh_last_run_timestamp
#
# Introduced 2026-04-22 [IFRNLLEI01PRD-671].

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

# shellcheck source=scripts/lib/suppression-gates.sh
source "$REPO_DIR/scripts/lib/suppression-gates.sh"
check_suppression_gates || exit 0

metrics_file="/var/lib/node_exporter/textfile_collector/bgp_mesh_watchdog.prom"
tmp="${metrics_file}.tmp"

out=$(cd "$REPO_DIR" && python3 <<'PYEOF'
"""
Poll every BGP speaker, emit per-session state, aggregate counters.

Expected-mesh shape lives here as the single source of truth. Editing
this dict when the topology changes is the point — it makes silent
drift loud.
"""
import json, sys
sys.path.insert(0, "scripts/lib")

from asa_ssh import ssh_nl_asa_command, ssh_gr_asa_command
from ios_ssh import ssh_rtr01_command
from frr_ssh import ssh_nl_frr_command, ssh_gr_frr_command, ssh_vps_frr_command, parse_bgp_summary

# Map: local_host → (probe fn, list of expected neighbor IPs)
EXPECTED = {
    "nlrtr01": (
        lambda: ssh_rtr01_command(["show ip bgp summary"]),
        ["10.255.200.X",  # gr-fw01 via Budget VTI
         "10.255.200.X",  # notrf01vps01 via Budget VTI
         "10.255.200.X",  # chzrh01vps01 via Budget VTI
         "10.0.X.X", # nl-fw01 iBGP transit
         "10.0.X.X", # nlk8s-frr01
         "10.0.X.X"],# nlk8s-frr02
    ),
    "nl-fw01": (
        lambda: ssh_nl_asa_command(["show bgp summary"]),
        ["10.255.200.X",  # gr-fw01 via Freedom VTI
         "10.0.X.X",  # nlrtr01 transit
         "10.0.X.X",  # nlk8s-frr01
         "10.0.X.X"], # nlk8s-frr02
    ),
    "gr-fw01": (
        lambda: ssh_gr_asa_command(["show bgp summary"]),
        ["10.255.200.X",   # nlrtr01 via Budget VTI
         "10.255.200.X",  # nl-fw01 via Freedom VTI
         "10.0.X.X",   # grk8s-frr01
         "10.0.X.X"],  # grk8s-frr02
    ),
    "nlk8s-frr01": (
        lambda: ssh_nl_frr_command(1, ["show bgp summary"]),
        ["10.255.200.X",  # notrf01vps01 via Freedom VTI
         "10.255.200.X",  # chzrh01vps01 via Freedom VTI
         "10.0.X.X",   # grk8s-frr01
         "10.0.X.X",   # grk8s-frr02
         "10.0.X.X",  # nlrtr01
         "10.0.X.X",  # nl-fw01
         "10.0.X.X"], # nlk8s-frr02
    ),
    "nlk8s-frr02": (
        lambda: ssh_nl_frr_command(2, ["show bgp summary"]),
        ["10.255.200.X",   # notrf01vps01 via Budget VTI
         "10.255.200.X",   # chzrh01vps01 via Budget VTI
         "10.0.X.X",
         "10.0.X.X",
         "10.0.X.X",
         "10.0.X.X",
         "10.0.X.X"], # nlk8s-frr01
    ),
    "grk8s-frr01": (
        lambda: ssh_gr_frr_command(1, ["show bgp summary"]),
        ["10.255.200.X",   # notrf01vps01 via GR VTI
         "10.255.200.X",   # chzrh01vps01 via GR VTI
         "10.0.X.X",   # gr-fw01
         "10.0.X.X",   # grk8s-frr02
         "10.0.X.X",  # nlk8s-frr01
         "10.0.X.X"], # nlk8s-frr02
    ),
    "grk8s-frr02": (
        lambda: ssh_gr_frr_command(2, ["show bgp summary"]),
        ["10.255.200.X",
         "10.255.200.X",
         "10.0.X.X",
         "10.0.X.X",
         "10.0.X.X",
         "10.0.X.X"],
    ),
    "notrf01vps01": (
        lambda: ssh_vps_frr_command("198.51.100.X", ["show bgp summary"]),
        ["10.255.X.X",    # chzrh01vps01 iBGP
         "10.255.200.X",   # nlrtr01 via Budget VTI
         "10.0.X.X",   # grk8s-frr01
         "10.0.X.X",   # grk8s-frr02
         "10.0.X.X",  # nlk8s-frr01
         "10.0.X.X"], # nlk8s-frr02
    ),
    "chzrh01vps01": (
        lambda: ssh_vps_frr_command("198.51.100.X", ["show bgp summary"]),
        ["10.255.X.X",    # notrf01vps01 iBGP
         "10.255.200.X",   # nlrtr01 via Budget VTI
         "10.0.X.X",
         "10.0.X.X",
         "10.0.X.X",
         "10.0.X.X"],
    ),
}

result = {"devices": {}, "unreachable": []}
total_expected = 0
total_established = 0

for local_host, (probe, expected_neighbors) in EXPECTED.items():
    total_expected += len(expected_neighbors)
    out = probe()
    if out.startswith("ERROR:"):
        result["unreachable"].append(local_host)
        result["devices"][local_host] = {"unreachable": True, "sessions": {}}
        continue
    peers = parse_bgp_summary(out)
    sessions = {}
    for n in expected_neighbors:
        info = peers.get(n)
        if info is None:
            sessions[n] = {"state": "missing", "established": 0}
        else:
            est = 1 if info["state"] == "established" else 0
            sessions[n] = {"state": info["state"], "established": est}
            total_established += est
    result["devices"][local_host] = {"unreachable": False, "sessions": sessions}

result["total_expected"] = total_expected
result["total_established"] = total_established
result["total_missing"] = total_expected - total_established - sum(
    len(EXPECTED[h][1]) for h in result["unreachable"]
)
print(json.dumps(result))
PYEOF
)

# Emit Prometheus textfile
{
    echo "# HELP bgp_session_state 1 if the expected iBGP session is Established, else 0"
    echo "# TYPE bgp_session_state gauge"
    echo "# HELP bgp_session_unreachable 1 if the local host was unreachable via SSH this cycle"
    echo "# TYPE bgp_session_unreachable gauge"
    python3 - <<EOF
import json
r = json.loads('''$out''')
for host, d in r["devices"].items():
    print(f'bgp_session_unreachable{{local_host="{host}"}} {1 if d["unreachable"] else 0}')
    for n, info in d["sessions"].items():
        print(f'bgp_session_state{{local_host="{host}",neighbor="{n}"}} {info["established"]}')
EOF
    total_expected=$(echo "$out" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['total_expected'])")
    total_established=$(echo "$out" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['total_established'])")
    total_missing=$(echo "$out" | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['total_missing'])")
    cat <<PROM
# HELP bgp_mesh_total_expected Total count of iBGP sessions expected across the mesh
# TYPE bgp_mesh_total_expected gauge
bgp_mesh_total_expected $total_expected
# HELP bgp_mesh_established_count Sessions currently Established
# TYPE bgp_mesh_established_count gauge
bgp_mesh_established_count $total_established
# HELP bgp_mesh_missing_count Expected sessions that are reachable but NOT Established
# TYPE bgp_mesh_missing_count gauge
bgp_mesh_missing_count $total_missing
# HELP bgp_mesh_last_run_timestamp Unix ts of last run
# TYPE bgp_mesh_last_run_timestamp gauge
bgp_mesh_last_run_timestamp $(date +%s)
PROM
} > "$tmp"

mv "$tmp" "$metrics_file"
