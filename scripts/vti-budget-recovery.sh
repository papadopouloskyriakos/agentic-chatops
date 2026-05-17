#!/bin/bash
# vti-budget-recovery.sh — Auto-recover Budget-side VTI datapath on nlrtr01
#
# Mirror of vti-freedom-recovery.sh for the Budget ISP. After the 2026-04-21
# migration, rtr01 owns Tunnel1/2/3 to GR / NO VPS / CH VPS. If any Tunnel
# is UP but the corresponding iBGP session is stuck Idle/Active (classic
# IPsec-SA-stuck pattern), clear the child SA to force re-negotiation.
#
# Cron: */3 * * * * /app/claude-gateway/scripts/vti-budget-recovery.sh
#
# Safety:
#   - Suppression gate (maintenance + chaos)
#   - 10-min cooldown (won't re-act within 10 min of last action)
#   - Only acts when Dialer1 is UP (don't chase a dead ISP)
#   - Only acts on ONE peer per run to avoid cascading resets
#
# Introduced 2026-04-22 [IFRNLLEI01PRD-670].

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="/home/app-user/scripts/maintenance-state/vti-budget-recovery.state"
LOG="/home/app-user/scripts/maintenance-state/vti-budget-recovery.log"
COOLDOWN_SECONDS=600

if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

mkdir -p "$(dirname "$STATE_FILE")"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [vti-budget-recovery] $*" >> "$LOG"; }

# Cooldown
if [ -f "$STATE_FILE" ]; then
    last=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    [ "$(( now - last ))" -lt "$COOLDOWN_SECONDS" ] && exit 0
fi

# Suppression
# shellcheck source=scripts/lib/suppression-gates.sh
source "$REPO_DIR/scripts/lib/suppression-gates.sh"
check_suppression_gates || exit 0

# Probe rtr01: Dialer1 + Tunnel1/2/3 + BGP peer states
result=$(cd "$REPO_DIR" && python3 <<'PYEOF'
import json, sys
sys.path.insert(0, "scripts/lib")
from ios_ssh import ssh_rtr01_command, ssh_rtr01_config, parse_dialer_status, parse_tunnel_status

out = ssh_rtr01_command([
    "show ip interface brief | include Dialer1",
    "show ip interface brief | include ^Tunnel",
    "show ip bgp summary | include ^10\\.255\\.200\\.",
])
if out.startswith("ERROR:"):
    print(json.dumps({"error": out}))
    sys.exit(0)

state = {
    "dialer": parse_dialer_status(out),
    "tunnels": parse_tunnel_status(out),
    "bgp": {},
}

# Parse BGP lines — columns: neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd
for line in out.splitlines():
    parts = line.split()
    if len(parts) >= 10 and parts[0].startswith("10.255.200."):
        neighbor = parts[0]
        # last token is State (text) or Pfx count (digits) if Established
        last = parts[-1]
        state["bgp"][neighbor] = "established" if last.isdigit() else last.lower()

# Tunnel ↔ peer mapping (hardcoded: from rtr01 topology)
tunnel_to_peer = {
    1: ("10.255.200.X",  "203.0.113.X"),     # Tunnel1 → gr-fw01
    2: ("10.255.200.X",  "198.51.100.X"),   # Tunnel2 → notrf01vps01
    3: ("10.255.200.X",  "198.51.100.X"),      # Tunnel3 → chzrh01vps01
}

# Decide action: only if Dialer1 UP AND some tunnel's BGP not healthy
dialer_up = state["dialer"]["line"] == "up" and state["dialer"]["proto"] == "up"
state["dialer_up"] = dialer_up
state["action"] = None
state["action_peer"] = None
state["action_tunnel"] = None

if dialer_up:
    for tid, (bgp_neighbor, peer_public_ip) in tunnel_to_peer.items():
        tun_up = state["tunnels"].get(tid) == "up"
        bgp_state = state["bgp"].get(bgp_neighbor, "missing")
        if tun_up and bgp_state != "established":
            state["action"] = "clear_ipsec_sa_peer"
            state["action_peer"] = peer_public_ip
            state["action_tunnel"] = tid
            break  # only one peer per run

if state["action"]:
    ok = ssh_rtr01_config([f"clear crypto ipsec sa peer {state['action_peer']}"])
    state["executed"] = bool(ok)

print(json.dumps(state))
PYEOF
)

if [ -z "$result" ]; then
    log "ERROR: empty response from probe"
    exit 1
fi

err=$(echo "$result" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('error',''))" 2>/dev/null)
if [ -n "$err" ]; then
    log "probe error: $err"
    exit 1
fi

action=$(echo "$result" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('action') or '')" 2>/dev/null)

# Write Prometheus counter on action
metrics_file="/var/lib/node_exporter/textfile_collector/vti_budget_recovery.prom"
if [ -d "$(dirname "$metrics_file")" ]; then
    # Read previous counter, increment on action
    prev_total=$(awk '/^vti_budget_recovery_actions_total/{print $NF}' "$metrics_file" 2>/dev/null || echo 0)
    prev_total=${prev_total:-0}
    new_total=$prev_total
    [ -n "$action" ] && new_total=$(( prev_total + 1 ))
    cat > "${metrics_file}.tmp" <<PROM
# HELP vti_budget_recovery_actions_total Count of clear-ipsec-sa actions taken on rtr01 since boot
# TYPE vti_budget_recovery_actions_total counter
vti_budget_recovery_actions_total $new_total
# HELP vti_budget_recovery_last_action_timestamp Unix ts of last successful action (0 if never)
# TYPE vti_budget_recovery_last_action_timestamp gauge
vti_budget_recovery_last_action_timestamp $([ -n "$action" ] && date +%s || echo 0)
PROM
    mv "${metrics_file}.tmp" "$metrics_file"
fi

if [ -z "$action" ]; then
    exit 0
fi

date +%s > "$STATE_FILE"
action_peer=$(echo "$result" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('action_peer',''))" 2>/dev/null)
action_tunnel=$(echo "$result" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('action_tunnel',''))" 2>/dev/null)
log "ACTION=$action TUNNEL=$action_tunnel PEER=$action_peer"

# Post to Matrix #infra-nl-prod on action
MATRIX_TOKEN="${MATRIX_CLAUDE_TOKEN:-}"
if [ -n "$MATRIX_TOKEN" ]; then
    MATRIX_ROOM="!AOMuEtXGyzGFLgObKN:matrix.example.net"
    TXN_ID="vti-budget-$(date +%s%N)-$$"
    curl -sf --max-time 10 -X PUT \
      "https://matrix.example.net/_matrix/client/v3/rooms/${MATRIX_ROOM}/send/m.room.message/${TXN_ID}" \
      -H "Authorization: Bearer ${MATRIX_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"msgtype\":\"m.notice\",\"body\":\"[vti-budget-recovery] Cleared IPsec SA peer ${action_peer} on nlrtr01 (Tunnel${action_tunnel} BGP unhealthy).\"}" \
      >/dev/null 2>&1 || true
fi
