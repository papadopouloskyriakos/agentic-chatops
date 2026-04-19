#!/bin/bash
# vti-freedom-recovery.sh — Auto-recover NL↔GR Freedom VTI datapath
#
# Two failure modes covered:
#
#   (A) Interface-down — Tunnel4 (Freedom→GR) DOWN while Tunnel1 (xs4all→GR) UP.
#       IKE SA race condition on shared peer IP 203.0.113.X.
#       Ref: vti_bgp_outage_20260411.md.
#       Fix: shut/no-shut Tunnel1 to clear blocking xs4all IKE SA.
#
#   (B) IPsec-SA-stuck — Tunnel4 UP, IKE SAs UP, ESP counters incrementing,
#       but inner packets black-holed → BGP (10.255.200.X) stuck Idle/Active.
#       Ref: incident_gr_isolation_20260417.md.
#       Fix: clear crypto ipsec sa peer 203.0.113.X (re-negotiate child SAs).
#
# Cron: */3 * * * * /app/claude-gateway/scripts/vti-freedom-recovery.sh
#
# Safety:
#   - No-op during gateway.maintenance or active chaos
#   - Cooldown: won't re-act within 10 min of last action
#   - Mode-A trigger: Freedom WAN UP + Tunnel4 DOWN + Tunnel1 UP
#   - Mode-B trigger: Freedom WAN UP + Tunnel4 UP + BGP 10.255.200.X not-Established
#   - Graceful exit if ASA SSH is saturated (historical failure mode)

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="/home/app-user/scripts/maintenance-state/vti-freedom-recovery.state"
LOG="/home/app-user/scripts/maintenance-state/vti-freedom-recovery.log"
ASA_IP="10.0.181.X"
ASA_USER="operator"
ASA_PASS=""
COOLDOWN_SECONDS=600

if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi
ASA_PASS="${CISCO_ASA_PASSWORD:?CISCO_ASA_PASSWORD not set - source .env or set env var}"

mkdir -p "$(dirname "$STATE_FILE")"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [vti-freedom-recovery] $*" >> "$LOG"; }

# Cooldown
if [ -f "$STATE_FILE" ]; then
    last_bounce=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
    now=$(date +%s)
    elapsed=$(( now - last_bounce ))
    if [ "$elapsed" -lt "$COOLDOWN_SECONDS" ]; then
        exit 0
    fi
fi

# Maintenance suppression
if [ -f "/home/app-user/gateway.maintenance" ]; then
    exit 0
fi

# Chaos suppression
if [ -f "$HOME/chaos-state/chaos-active.json" ]; then
    exit 0
fi

# Single-session netmiko-based ASA check + recover
result=$(ASA_IP="$ASA_IP" ASA_USER="$ASA_USER" ASA_PASS="$ASA_PASS" python3 <<'PYEOF'
import os, sys, json, time

try:
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
except ImportError:
    print(json.dumps({"error": "netmiko not installed"}))
    sys.exit(0)

ASA_IP = os.environ["ASA_IP"]
ASA_USER = os.environ["ASA_USER"]
ASA_PASS = os.environ["ASA_PASS"]

def connect():
    return ConnectHandler(
        device_type="cisco_asa", host=ASA_IP,
        username=ASA_USER, password=ASA_PASS,
        conn_timeout=15, read_timeout_override=30,
    )

try:
    c = connect()
except NetmikoAuthenticationException as e:
    # "Too many simultaneous connections" surfaces as auth failure here;
    # back off silently — next cron run will retry.
    msg = str(e).lower()
    if "too many" in msg or "already exist" in msg:
        print(json.dumps({"error": "asa_ssh_saturated"}))
    else:
        print(json.dumps({"error": f"auth: {e}"}))
    sys.exit(0)
except (NetmikoTimeoutException, Exception) as e:
    print(json.dumps({"error": f"connect: {e}"}))
    sys.exit(0)

def send(cmd, rt=15):
    return c.send_command(cmd, read_timeout=rt)

state = {}

# Freedom WAN state
fout = send("show interface outside_freedom | include address")
state["freedom_up"] = ("unassigned" not in fout) and ("45.138" in fout)

# Tunnel1 / Tunnel4 interface state
tout = send("show interface ip brief | include ^Tunnel1 |^Tunnel4 ")
state["tunnel1_up"] = False
state["tunnel4_up"] = False
for line in tout.splitlines():
    p = line.split()
    if len(p) >= 5:
        if p[0] == "Tunnel1" and p[4] == "up":
            state["tunnel1_up"] = True
        elif p[0] == "Tunnel4" and p[4] == "up":
            state["tunnel4_up"] = True

# BGP direct to GR via Freedom VTI
bout = send("show bgp summary | include 10.255.200.X")
# Expected healthy line ends with a prefix count (integer); unhealthy shows
# textual state like "Idle", "Active", "Connect"
state["bgp_healthy"] = False
for line in bout.splitlines():
    if "10.255.200.X" in line:
        tok = line.split()
        if tok:
            last = tok[-1]
            state["bgp_healthy"] = last.isdigit()
        break

# Decide mode
mode = None
if state["freedom_up"]:
    if not state["tunnel4_up"] and state["tunnel1_up"]:
        mode = "A_iface_down"
    elif state["tunnel4_up"] and not state["bgp_healthy"]:
        mode = "B_ipsec_stuck"

state["mode"] = mode

if mode is None:
    state["action"] = "none"
    print(json.dumps(state))
    c.disconnect()
    sys.exit(0)

# Action
if mode == "B_ipsec_stuck":
    # Targeted: clear crypto ipsec sa peer — forces child SA re-negotiation
    # without disrupting IKE or bouncing interfaces. Proven fix from
    # incident_gr_isolation_20260417.md (BGP recovered in <15s).
    out = send("clear crypto ipsec sa peer 203.0.113.X", rt=30)
    state["action"] = "clear_ipsec_sa_peer"
    state["action_out"] = out.strip()[:200]
    time.sleep(25)
elif mode == "A_iface_down":
    # Legacy: bounce Tunnel1 to clear blocking xs4all IKE SA
    c.config_mode()
    c.send_config_set(["interface Tunnel1", "shutdown"], read_timeout=15)
    c.exit_config_mode()
    time.sleep(20)
    c.config_mode()
    c.send_config_set(["interface Tunnel1", "no shutdown"], read_timeout=15)
    c.exit_config_mode()
    time.sleep(10)
    state["action"] = "bounce_tunnel1"

# Post-action verification
post_bout = send("show bgp summary | include 10.255.200.X")
state["post_bgp"] = post_bout.strip()
post_t = send("show interface ip brief | include ^Tunnel4 ")
state["post_tunnel4"] = post_t.strip()

c.disconnect()
print(json.dumps(state))
PYEOF
)

# Parse result
if [ -z "$result" ]; then
    log "ERROR: empty response from python"
    exit 1
fi

err=$(echo "$result" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('error',''))" 2>/dev/null)
if [ -n "$err" ]; then
    # Silent backoff on SSH saturation; log other errors
    if [ "$err" = "asa_ssh_saturated" ]; then
        log "backoff: ASA SSH saturated, skipping cycle"
    else
        log "ERROR: $err"
    fi
    exit 1
fi

action=$(echo "$result" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('action',''))" 2>/dev/null)

if [ "$action" = "none" ] || [ -z "$action" ]; then
    # Healthy or not-triggerable — nothing to log
    exit 0
fi

# Record cooldown timestamp
date +%s > "$STATE_FILE"

mode=$(echo "$result" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('mode',''))" 2>/dev/null)
post_bgp=$(echo "$result" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('post_bgp',''))" 2>/dev/null)

log "ACTION=$action MODE=$mode"
log "POST-BGP: $post_bgp"
