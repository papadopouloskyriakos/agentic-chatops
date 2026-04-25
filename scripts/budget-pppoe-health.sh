#!/bin/bash
# budget-pppoe-health.sh — Monitor Budget PPPoE health on nlrtr01
#
# Post 2026-04-21 migration, the Budget ISP (formerly xs4all) terminates on
# nlrtr01 Dialer1 (203.0.113.X). This is the Freedom-side mirror
# monitor: emits Prometheus metrics every run; when Budget+Freedom are
# simultaneously DOWN, fires an SMS (total-internet-loss warning).
#
# Cron: */2 * * * * /app/claude-gateway/scripts/budget-pppoe-health.sh
#
# Introduced 2026-04-22 [IFRNLLEI01PRD-670].

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="/home/app-user/scripts/maintenance-state/budget-pppoe.state"
LOG_TAG="[budget-pppoe]"

if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

mkdir -p "$(dirname "$STATE_FILE")"

# Maintenance + chaos suppression
# shellcheck source=scripts/lib/suppression-gates.sh
source "$REPO_DIR/scripts/lib/suppression-gates.sh"
check_suppression_gates || exit 0

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
        -u "${key}:${secret}" -d "From=${from}" -d "To=${to}" -d "Body=${msg}" \
        > /dev/null 2>&1
}

# Query rtr01 Dialer1 state via ios_ssh lib.
# Also query Freedom state via asa_ssh for dual-fail detection.
query_state() {
    cd "$REPO_DIR" && python3 <<'PYEOF'
import sys
sys.path.insert(0, "scripts/lib")
from ios_ssh import ssh_rtr01_command, parse_dialer_status
from asa_ssh import ssh_nl_asa_command

rtr_out = ssh_rtr01_command(["show ip interface brief | include Dialer1"])
if rtr_out.startswith("ERROR:"):
    print("BUDGET=UNKNOWN"); print("BUDGET_IP=unknown")
else:
    d = parse_dialer_status(rtr_out)
    up = (d["line"] == "up" and d["proto"] == "up")
    print(f"BUDGET={'UP' if up else 'DOWN'}")
    print(f"BUDGET_IP={d['ip']}")

fw_out = ssh_nl_asa_command(["show interface outside_freedom | include address"])
if fw_out.startswith("ERROR:"):
    print("FREEDOM=UNKNOWN")
else:
    print(f"FREEDOM={'DOWN' if 'unassigned' in fw_out else 'UP'}")
PYEOF
}

write_prom() {
    local budget_up="$1" freedom_up="$2" budget_ip="$3"
    local metrics_file="/var/lib/node_exporter/textfile_collector/budget_pppoe.prom"
    local tmp="${metrics_file}.tmp"
    [ -d "$(dirname "$metrics_file")" ] || return 0
    cat > "$tmp" <<PROM
# HELP budget_pppoe_up Budget PPPoE (rtr01 Dialer1) line+proto up (1=up, 0=down)
# TYPE budget_pppoe_up gauge
budget_pppoe_up $budget_up
# HELP budget_pppoe_dual_wan_down Both Freedom and Budget unavailable (1=total outage, 0=at least one path up)
# TYPE budget_pppoe_dual_wan_down gauge
budget_pppoe_dual_wan_down $([ "$budget_up" = "0" ] && [ "$freedom_up" = "0" ] && echo 1 || echo 0)
# HELP budget_pppoe_info PPPoE assigned public IP (label only; value is always 1)
# TYPE budget_pppoe_info gauge
budget_pppoe_info{ip="${budget_ip}"} 1
PROM
    mv "$tmp" "$metrics_file"
}

# ── Main ──

current_state=$(cat "$STATE_FILE" 2>/dev/null || echo "unknown")
out=$(query_state)
budget=$(echo "$out" | awk -F= '/^BUDGET=/{print $2}')
budget_ip=$(echo "$out" | awk -F= '/^BUDGET_IP=/{print $2}')
freedom=$(echo "$out" | awk -F= '/^FREEDOM=/{print $2}')

# Fallback: if rtr01 SSH failed, ping Dialer1 IP from outside
if [ "$budget" = "UNKNOWN" ] || [ -z "$budget" ]; then
    if ping -c 2 -W 3 203.0.113.X >/dev/null 2>&1; then
        budget="UP"
        logger "$LOG_TAG Ping fallback: Budget Dialer1 IP reachable — marking UP"
    else
        budget="DOWN"
        logger "$LOG_TAG Ping fallback: Budget Dialer1 IP unreachable — marking DOWN"
    fi
fi

b_int=$([ "$budget" = "UP" ] && echo 1 || echo 0)
f_int=$([ "$freedom" = "UP" ] && echo 1 || echo 0)
write_prom "$b_int" "$f_int" "$budget_ip"

# Transition logic — only fire SMS on *entering* dual-fail state
if [ "$b_int" = "0" ] && [ "$f_int" = "0" ] && [ "$current_state" != "dual-fail" ]; then
    logger "$LOG_TAG CRITICAL: Budget+Freedom both DOWN — total internet loss"
    send_sms "[NL-INFRA] BUDGET+FREEDOM BOTH DOWN. Total internet loss. Budget PPPoE (rtr01 Dialer1) unavailable AND Freedom PPPoE (fw01 outside_freedom) unavailable. Check rtr01 + fw01 + ONTs."
    echo "dual-fail" > "$STATE_FILE"
elif [ "$b_int" = "1" ] && [ "$current_state" = "dual-fail" ]; then
    logger "$LOG_TAG Budget recovered from dual-fail"
    send_sms "[NL-INFRA] BUDGET RECOVERED. At least one ISP path restored (budget=${budget}, freedom=${freedom})."
    echo "budget-up" > "$STATE_FILE"
else
    echo "budget=${budget}-freedom=${freedom}" > "$STATE_FILE"
fi
