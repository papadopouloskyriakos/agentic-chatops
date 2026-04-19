#!/bin/bash
# chaos-preflight.sh — instant readiness check for chaos testing
# Usage: bash scripts/chaos-preflight.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_DIR/.env" 2>/dev/null || true

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
PASS=0; FAIL=0; WARN=0

check() {
    local label="$1"; local result="$2"
    if [ "$result" = "ok" ]; then
        printf "  ${GREEN}PASS${NC}  %s\n" "$label"
        PASS=$((PASS + 1))
    elif [ "$result" = "warn" ]; then
        printf "  ${YELLOW}WARN${NC}  %s\n" "$label"
        WARN=$((WARN + 1))
    else
        printf "  ${RED}FAIL${NC}  %s\n" "$label"
        FAIL=$((FAIL + 1))
    fi
}

echo "Chaos Engineering Pre-Flight Check"
echo "==================================="
echo ""

# 1. No active chaos test
echo "[Infrastructure State]"
if [ -f "$HOME/chaos-state/chaos-active.json" ]; then
    check "No active chaos test" "fail — test running"
else
    check "No active chaos test" "ok"
fi

# 2. No maintenance mode
if [ -f "$HOME/gateway.maintenance" ]; then
    check "No maintenance mode" "fail — maintenance active"
else
    check "No maintenance mode" "ok"
fi

# 3. Rate limit
RATE_INFO=$(python3 -c "
import json, datetime
try:
    with open('$HOME/chaos-state/chaos-history.json') as f:
        h = json.load(f)
    if not h:
        print('ok|no history')
    else:
        last = datetime.datetime.fromisoformat(h[-1]['started_at'].replace('Z', '+00:00'))
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - last).total_seconds()
        if elapsed >= 600:
            print(f'ok|last test {int(elapsed/60)}min ago')
        else:
            print(f'fail|rate limited, {int(600-elapsed)}s remaining')
except Exception:
    print('ok|no history')
" 2>/dev/null)
RATE_STATUS=$(echo "$RATE_INFO" | cut -d'|' -f1)
RATE_MSG=$(echo "$RATE_INFO" | cut -d'|' -f2)
check "Rate limit clear ($RATE_MSG)" "$RATE_STATUS"

# 4. ASA shun table
echo ""
echo "[Network]"
SHUN=$(python3 -c "
import sys; sys.path.insert(0, '$REPO_DIR/scripts/lib')
from asa_ssh import ssh_nl_asa_command
out = ssh_nl_asa_command(['show shun'])
lines = [l.strip() for l in out.splitlines() if l.strip() and 'show' not in l and 'nl' not in l]
print(len(lines))
" 2>/dev/null)
if [ "${SHUN:-1}" = "0" ]; then
    check "ASA shun table empty" "ok"
else
    check "ASA shun table empty" "fail — $SHUN entries"
fi

# 5. All 6 NL tunnels up
TUNNELS=$(python3 -c "
import sys; sys.path.insert(0, '$REPO_DIR/scripts/lib')
from asa_ssh import ssh_nl_asa_command
out = ssh_nl_asa_command(['show interface ip brief | include Tunnel'])
up = sum(1 for l in out.splitlines() if 'Tunnel' in l and l.split()[-1] == 'up')
total = sum(1 for l in out.splitlines() if 'Tunnel' in l)
print(f'{up}|{total}')
" 2>/dev/null)
TUP=$(echo "$TUNNELS" | cut -d'|' -f1)
TTOT=$(echo "$TUNNELS" | cut -d'|' -f2)
if [ "${TUP:-0}" -ge 6 ]; then
    check "NL ASA tunnels $TUP/$TTOT up" "ok"
elif [ "${TUP:-0}" -ge 4 ]; then
    check "NL ASA tunnels $TUP/$TTOT up (some down)" "warn"
else
    check "NL ASA tunnels $TUP/$TTOT up" "fail"
fi

# 6. BGP peers
BGP=$(python3 -c "
import sys; sys.path.insert(0, '$REPO_DIR/scripts/lib')
from asa_ssh import ssh_nl_asa_command
out = ssh_nl_asa_command(['show bgp summary'])
total = 0; est = 0
for line in out.splitlines():
    parts = line.split()
    if len(parts) >= 9 and parts[0].count('.') == 3:
        total += 1
        if parts[-1].isdigit(): est += 1
print(f'{est}|{total}')
" 2>/dev/null)
BEST=$(echo "$BGP" | cut -d'|' -f1)
BTOT=$(echo "$BGP" | cut -d'|' -f2)
if [ "${BEST:-0}" -ge 7 ]; then
    check "BGP peers $BEST/$BTOT established" "ok"
else
    check "BGP peers $BEST/$BTOT established" "warn"
fi

# 7. HTTP endpoints
echo ""
echo "[Services]"
HTTP_OK=0; HTTP_TOTAL=0
for d in kyriakos.papadopoulos.tech get.cubeos.app meshsat.net mulecube.com hub.meshsat.net matrix.example.net; do
    CODE=$(curl -sk -o /dev/null -w "%{http_code}" --connect-timeout 5 "https://$d/" 2>/dev/null)
    HTTP_TOTAL=$((HTTP_TOTAL + 1))
    if [ "$CODE" = "200" ]; then HTTP_OK=$((HTTP_OK + 1)); fi
done
if [ "$HTTP_OK" = "$HTTP_TOTAL" ]; then
    check "HTTP endpoints $HTTP_OK/$HTTP_TOTAL healthy" "ok"
else
    check "HTTP endpoints $HTTP_OK/$HTTP_TOTAL healthy" "fail"
fi

# 8. DMZ containers
for host in nl-dmz01 gr-dmz01; do
    COUNT=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new -i ~/.ssh/one_key \
        "operator@$host" 'docker ps -q 2>/dev/null | wc -l' 2>/dev/null)
    if [ "${COUNT:-0}" -ge 20 ]; then
        check "$host containers ($COUNT running)" "ok"
    else
        check "$host containers (${COUNT:-0} running)" "fail"
    fi
done

# 9. Prometheus
echo ""
echo "[Monitoring]"
PROM=$(curl -s -o /dev/null -w "%{http_code}" "http://10.0.X.X:30090/-/healthy" 2>/dev/null)
check "Prometheus healthy" "$([ "$PROM" = "200" ] && echo ok || echo fail)"

# 10. LibreNMS alerts
for site in "NL|https://nl-nms01.example.net|REDACTED_LIBRENMS_NL_KEY" \
            "GR|https://gr-nms01.example.net|REDACTED_LIBRENMS_GR_KEY"; do
    IFS='|' read -r LABEL URL KEY <<< "$site"
    ALERTS=$(curl -sk -H "X-Auth-Token: $KEY" "$URL/api/v0/alerts?state=1" 2>/dev/null | \
        python3 -c "import sys,json; print(len(json.load(sys.stdin).get('alerts',[])))" 2>/dev/null)
    if [ "${ALERTS:-1}" = "0" ]; then
        check "LibreNMS $LABEL: 0 active alerts" "ok"
    else
        check "LibreNMS $LABEL: ${ALERTS:-?} active alerts" "warn"
    fi
done

# 11. HAProxy backends
echo ""
echo "[HAProxy]"
for vps in "NO|198.51.100.X" "CH|198.51.100.X"; do
    IFS='|' read -r LABEL IP <<< "$vps"
    DOWN=$(ssh -o ConnectTimeout=5 -i ~/.ssh/one_key "operator@$IP" \
        "echo '${CISCO_ASA_PASSWORD}' | sudo -S bash -c 'echo \"show stat\" | socat - UNIX-CONNECT:/var/run/haproxy/admin.sock' 2>/dev/null" 2>&1 | \
        grep -v "^#\|FRONTEND\|BACKEND\|Authorized\|stats\|password" | grep -c "DOWN" 2>/dev/null)
    if [ "${DOWN:-1}" = "0" ]; then
        check "HAProxy $LABEL: all backends UP" "ok"
    else
        check "HAProxy $LABEL: ${DOWN:-?} backends DOWN" "fail"
    fi
done

# Summary
echo ""
echo "==================================="
TOTAL=$((PASS + FAIL + WARN))
if [ "$FAIL" = "0" ]; then
    printf "${GREEN}READY${NC} — $PASS/$TOTAL checks passed"
    [ "$WARN" -gt 0 ] && printf " ($WARN warnings)"
    echo ""
else
    printf "${RED}NOT READY${NC} — $FAIL failed, $PASS passed, $WARN warnings\n"
fi
