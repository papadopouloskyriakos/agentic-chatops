#!/bin/bash
# freedom-qos-toggle.sh — Freedom PPPoE state monitor + alerting
#
# Runs via cron every 2 minutes. Detects Freedom PPPoE UP/DOWN transitions and:
#   - Sends a Twilio SMS on state change
#   - Emits Prometheus textfile metrics (freedom_pppoe_up, freedom_bng_rtt_ms,
#     freedom_ont_port_errors)
#   - Samples sw01 Gi1/0/36 CRC errors every 7th run (~every 15 min)
#
# Cron: */2 * * * * /app/claude-gateway/scripts/freedom-qos-toggle.sh
#
# HISTORY:
#   2026-04-22 (initial refactor, IFRNLLEI01PRD-669):
#     - SMS text: "xs4all" → "budget (rtr01)" after the xs4all→budget migration
#     - Uses scripts/lib/suppression-gates.sh maintenance + chaos gate
#     - ASA queries consolidated via scripts/lib/asa_ssh.py (1 SSH session/run)
#     - sw01 CRC query gated to every 7th run
#     - DRY_RUN=1 env var prints SMS payload instead of sending
#   2026-04-22 (Path B simplification, IFRNLLEI01PRD-<new>):
#     - Removed apply_qos() / remove_qos() — referenced XS4ALL-ROOM-*-PM
#       policy-maps that no longer exist on fw01 post-migration (silent no-op).
#     - Per-tenant QoS is now permanently installed on nlrtr01
#       (TENANT_DL_NORMAL 15 Mbps down, TENANT_UL_NORMAL 5 Mbps up per room)
#       via service-policy output on Dialer1 + Gi0/0/0.2. Only effective when
#       rtr01 is in path (i.e. during a Freedom-down failover). No toggle
#       needed because Budget uplink ≥ 25 Mbps handles the 4×5=20 Mbps tenant
#       aggregate with headroom for BGP + mgmt.
#     - Script's remaining job is observability + alerting, not enforcement.
#       Name kept for cron-entry stability.

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="/home/app-user/scripts/maintenance-state/freedom-qos.state"
COUNTER_FILE="/home/app-user/scripts/maintenance-state/freedom-qos.counter"
LOG_TAG="[freedom-qos]"
SW01_HOST="10.0.181.X"
SW01_USER="operator"

# Load env
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi
ASA_PASS="${CISCO_ASA_PASSWORD:?CISCO_ASA_PASSWORD not set - source .env or set env var}"

mkdir -p "$(dirname "$STATE_FILE")"

# Maintenance + chaos suppression (shared helper, IFRNLLEI01PRD-672)
# shellcheck source=scripts/lib/suppression-gates.sh
source "$REPO_DIR/scripts/lib/suppression-gates.sh"
check_suppression_gates || exit 0

# Send SMS via Twilio — or echo body when DRY_RUN=1
send_sms() {
    local msg="$1"
    if [ "${DRY_RUN:-0}" = "1" ]; then
        echo "[DRY_RUN SMS] $msg"
        return 0
    fi
    local acct="${TWILIO_ACCOUNT_SID:-}"
    local key="${TWILIO_API_KEY_SID:-}"
    local secret="${TWILIO_API_KEY_SECRET:-}"
    local from="${TWILIO_FROM_NUMBER:-}"
    local to="${TWILIO_TO_NUMBER:-}"
    [ -z "$acct" ] || [ -z "$key" ] || [ -z "$to" ] && return 1
    curl -s -X POST "https://api.twilio.com/2010-04-01/Accounts/${acct}/Messages.json" \
        -u "${key}:${secret}" \
        -d "From=${from}" \
        -d "To=${to}" \
        -d "Body=${msg}" > /dev/null 2>&1
}

# Consolidated ASA query — 1 SSH session, returns Freedom status + SLA RTT
# via scripts/lib/asa_ssh.py. Stdout format: "FREEDOM=UP|DOWN\nSLA_RTT=<int>"
query_asa() {
    cd "$REPO_DIR" && python3 <<'PYEOF'
import sys
sys.path.insert(0, "scripts/lib")
from asa_ssh import ssh_nl_asa_command

out = ssh_nl_asa_command([
    "show interface outside_freedom | include address",
    "show sla monitor operational-state 1 | include Latest RTT",
])

if out.startswith("ERROR:"):
    print("FREEDOM=UNKNOWN")
    print("SLA_RTT=-1")
    sys.exit(0)

freedom = "DOWN" if "unassigned" in out else "UP"
print(f"FREEDOM={freedom}")

rtt = -1
for line in out.splitlines():
    if "Latest RTT" in line and ":" in line:
        val = line.split(":")[-1].strip()
        try:
            rtt = int(val)
        except ValueError:
            pass
        break
print(f"SLA_RTT={rtt}")
PYEOF
}

# sw01 CRC query — aes128-ctr cipher needed; runs only every 7th cycle.
query_sw01_crc() {
    python3 <<PYEOF
import pexpect, sys
try:
    child = pexpect.spawn(
        "ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "
        "-o Ciphers=aes128-ctr,aes256-ctr "
        "-o HostKeyAlgorithms=+ssh-rsa "
        "-o KexAlgorithms=diffie-hellman-group14-sha1 "
        "-o PubkeyAcceptedAlgorithms=+ssh-rsa "
        "${SW01_USER}@${SW01_HOST}",
        timeout=15, encoding="utf-8",
    )
    child.expect("[Pp]assword:")
    child.sendline("${ASA_PASS}")
    i = child.expect([">", "#", "[Pp]assword:", pexpect.TIMEOUT], timeout=15)
    if i not in (0, 1):
        sys.exit(1)
    child.sendline("show interface Gi1/0/36 | include CRC|errors|drops")
    child.expect("#", timeout=10)
    output = child.before
    child.sendline("exit")
    child.close()
    for line in output.splitlines():
        if "input errors" in line:
            parts = line.strip().split()
            try:
                print(parts[0]); sys.exit(0)
            except (IndexError, ValueError):
                print("0"); sys.exit(0)
    print("0")
except Exception:
    sys.exit(1)
PYEOF
}

log_ont_health() {
    local freedom_status="$1" sla_rtt="$2" crc_errors="$3"
    local metrics_file="/var/lib/node_exporter/textfile_collector/freedom_ont.prom"
    local tmp="${metrics_file}.tmp"
    [ -d "$(dirname "$metrics_file")" ] || return 0
    cat > "$tmp" <<PROM
# HELP freedom_bng_rtt_ms RTT to Freedom BNG gateway in milliseconds
# TYPE freedom_bng_rtt_ms gauge
freedom_bng_rtt_ms ${sla_rtt:--1}
# HELP freedom_ont_port_errors Total input errors on sw01 Gi1/0/36 (ONT port)
# TYPE freedom_ont_port_errors counter
freedom_ont_port_errors ${crc_errors:-0}
# HELP freedom_pppoe_up Freedom PPPoE session status (1=up, 0=down)
# TYPE freedom_pppoe_up gauge
freedom_pppoe_up $([ "$freedom_status" = "UP" ] && echo 1 || echo 0)
PROM
    mv "$tmp" "$metrics_file"
}

# ── Main ──────────────────────────────────────────────────────────────────

# Update run counter (used to gate the sw01 CRC query to every 7th run)
current_counter=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
current_counter=$(( (current_counter + 1) % 7 ))
echo "$current_counter" > "$COUNTER_FILE"

current_state=$(cat "$STATE_FILE" 2>/dev/null || echo "unknown")

# One SSH session for both Freedom status + SLA RTT
asa_out=$(query_asa)
freedom_status=$(echo "$asa_out" | awk -F= '/^FREEDOM=/{print $2}')
sla_rtt=$(echo "$asa_out" | awk -F= '/^SLA_RTT=/{print $2}')

# ASA SSH fallback: the previous implementation pinged 198.51.100.X (Freedom
# BRAS public IP) to infer state. That's broken — BRAS is reachable from ANY
# ISP, so pings succeed over Budget when Freedom is actually DOWN, producing
# false "Freedom RECOVERED" SMS (caught 2026-04-22 during a live failover test).
#
# When the ASA query fails, we CANNOT reliably infer Freedom state remotely.
# Safer: retain the previous `current_state` value, log a warning, and skip
# the state-transition + SMS logic for this run. On the next */2 tick the ASA
# query will likely succeed and the correct state will emit.
if [ "$freedom_status" = "UNKNOWN" ] || [ -z "$freedom_status" ]; then
    logger "$LOG_TAG WARN: ASA query failed; skipping state-transition (retaining current_state=${current_state})"
    freedom_status=""   # sentinel: skip transitions below
fi

# sw01 CRC — expensive SSH, only every 7th run (~every 15 min on */2 cron)
crc_errors=""
if [ "$current_counter" -eq 0 ]; then
    crc_errors=$(query_sw01_crc 2>/dev/null || echo "")
fi

# State transitions — SMS on Freedom UP/DOWN flip.
# Tenant QoS is NOT toggled here; the permanent 15/5 cap on rtr01
# (TENANT_DL_NORMAL + BUDGET_UL_PARENT_NORMAL, attached to Dialer1 +
# Gi0/0/0.2) engages automatically whenever Budget is in the tenant data
# path (i.e. during a Freedom-down failover).
if [ "$freedom_status" = "DOWN" ] && [ "$current_state" != "freedom-down" ]; then
    logger "$LOG_TAG Freedom DOWN — Budget (rtr01) carrying tenant traffic at 15/5 cap"
    send_sms "[NL-INFRA] Freedom ISP DOWN. PPPoE lost on outside_freedom. Budget (rtr01) carrying all S2S tunnels + tenants at 15/5 Mbps each (rtr01 HQoS). Physical fix: power-cycle ONT on sw01 Gi1/0/36."
    echo "freedom-down" > "$STATE_FILE"
elif [ "$freedom_status" = "UP" ] && [ "$current_state" != "freedom-up" ]; then
    logger "$LOG_TAG Freedom UP — tenants back on Freedom path, rtr01 HQoS inert"
    send_sms "[NL-INFRA] Freedom ISP RECOVERED. PPPoE re-established. Tenants back on Freedom path at full bandwidth. rtr01 HQoS (15/5 cap) now idle."
    echo "freedom-up" > "$STATE_FILE"
fi

# Always log ONT health metrics (with or without fresh CRC sample)
log_ont_health "$freedom_status" "$sla_rtt" "$crc_errors"
