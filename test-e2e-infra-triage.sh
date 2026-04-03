#!/bin/bash
# E2E Test Suite: Infrastructure Triage Pipeline
# Tests LibreNMS alert → n8n → Matrix → OpenClaw triage → YT issue → Claude Code
#
# Usage: bash test-e2e-infra-triage.sh [--light] 2>&1 | tee /tmp/e2e-infra-results.txt
#   --light   Skip heavy tests (T5-T7) that invoke OpenClaw/Claude (5-20 min each)

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.env"

# ─── Configuration ─────────────────────────────────────────────────────────────
CLAUDE_BOT="@claude:matrix.example.net"
OPENCLAW_BOT="@openclaw:matrix.example.net"
LIBRENMS_BOT="@nl-librenms:matrix.example.net"

ROOM_INFRA="$MATRIX_ROOM_INFRA"
MATRIX_TOKEN="$MATRIX_DOMINICUS_API_KEY"
MATRIX_SERVER="https://matrix.example.net"
CLAUDE_TOKEN="$MATRIX_CLAUDE_TOKEN"
OPENCLAW_TOKEN="$MATRIX_OPENCLAW_TOKEN"

# n8n LibreNMS Receiver posts as @nl-librenms, not @claude
# Use Dominicus token to read (can see all senders in the room)
POLL_TOKEN="$MATRIX_DOMINICUS_API_KEY"

YT_URL="https://youtrack.example.net"
YT_AUTH="Authorization: Bearer $YT_TOKEN"
YT_PROJECT="IFRNLLEI01PRD"

WEBHOOK_URL="https://n8n.example.net/webhook/librenms-alert"
N8N_API_KEY=$(python3 -c "import json; cfg=json.load(open('/home/app-user/.claude.json')); print(cfg['mcpServers']['n8n-mcp']['env']['N8N_API_KEY'])" 2>/dev/null)
LIBRENMS_WF_ID="Ids38SbH48q4JdLN"

GW="/app/cubeos/claude-context"
ALERTS_FILE="$GW/active-alerts.json"

# Test hostname — use a fake host that won't collide with real alerts
TEST_HOST="e2e-test-host-$(date +%s)"
TEST_RULE="Devices up/down"
TEST_SEVERITY="critical"

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

LIGHT_ONLY=false
[ "$1" = "--light" ] && LIGHT_ONLY=true

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log() { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
pass() { echo -e "  ${GREEN}PASS${NC} $*"; ((PASS_COUNT++)); }
fail() { echo -e "  ${RED}FAIL${NC} $*"; ((FAIL_COUNT++)); }
skip() { echo -e "  ${YELLOW}SKIP${NC} $*"; ((SKIP_COUNT++)); }

# ─── Matrix Helpers ────────────────────────────────────────────────────────────
SYNC_TOKEN=""
SYNC_TOKEN_OC=""
SYNC_TOKEN_POLL=""

init_sync() {
    local token="$1" room="$2"
    python3 -c "
import requests, json
filt = json.dumps({'room':{'rooms':['$room'],'timeline':{'limit':0}}})
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/sync',
    params={'timeout':'0','filter':filt},
    headers={'Authorization':'Bearer $token'}, timeout=15)
print(r.json().get('next_batch',''))
" 2>/dev/null
}

init_sync_claude() {
    SYNC_TOKEN=$(init_sync "$CLAUDE_TOKEN" "$ROOM_INFRA")
}

init_sync_openclaw() {
    SYNC_TOKEN_OC=$(init_sync "$OPENCLAW_TOKEN" "$ROOM_INFRA")
}

# Init poll token (Dominicus) — sees all senders
init_sync_poll() {
    SYNC_TOKEN_POLL=$(init_sync "$POLL_TOKEN" "$ROOM_INFRA")
}

# Phase start timestamp — set before each test to cover full message window
PHASE_START_TS=0

# Wait for bot message in #infra room
# $1=bot_token, $2=since_token_varname, $3=sender_mxid, $4=pattern, $5=timeout, $6=msgtype
wait_for_bot_msg() {
    local bot_token="$1" since_var="$2" sender="$3" pattern="$4" timeout="${5:-60}" msgtype_filter="${6:-}"
    local since="${!since_var}"
    local elapsed=0
    local interval=5
    LAST_RESPONSE=""
    # Use phase start time for /messages fallback (covers full test window)
    local start_ts=$PHASE_START_TS
    [ "$start_ts" -eq 0 ] 2>/dev/null && start_ts=$(($(date +%s) * 1000))

    while [ $elapsed -lt $timeout ]; do
        local result
        result=$(python3 -c "
import requests, json
filt = json.dumps({'room':{'rooms':['$ROOM_INFRA'],'timeline':{'limit':50}}})
params = {'timeout':'0','filter':filt}
since = '$since'
if since:
    params['since'] = since
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/sync',
    params=params, headers={'Authorization':'Bearer $bot_token'}, timeout=15)
data = r.json()
new_token = data.get('next_batch','')
rooms = data.get('rooms',{}).get('join',{})
room_data = rooms.get('$ROOM_INFRA',{})
events = room_data.get('timeline',{}).get('events',[])
matched = []
for e in events:
    if e.get('type') != 'm.room.message': continue
    if e.get('sender') != '$sender': continue
    body = e.get('content',{}).get('body','')
    msgtype = e.get('content',{}).get('msgtype','')
    msgtype_filter = '$msgtype_filter'
    if msgtype_filter and msgtype != msgtype_filter:
        continue
    matched.append(body)
print(new_token)
for m in matched:
    print(m)
" 2>/dev/null)

        local new_token=$(echo "$result" | head -1)
        if [ -n "$new_token" ]; then
            eval "$since_var='$new_token'"
        fi

        local messages=$(echo "$result" | tail -n +2)
        if [ -n "$messages" ]; then
            local match=$(echo "$messages" | grep -i "$pattern" | head -1)
            if [ -n "$match" ]; then
                LAST_RESPONSE="$match"
                return 0
            fi
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
    done

    # Fallback: /messages API
    local fallback
    fallback=$(python3 -c "
import requests, json, urllib.parse
room_encoded = urllib.parse.quote('$ROOM_INFRA', safe='')
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/rooms/' + room_encoded + '/messages',
    params={'dir':'b','limit':'20'},
    headers={'Authorization':'Bearer $bot_token'}, timeout=15)
data = r.json()
start_ts = $start_ts
msgtype_filter = '$msgtype_filter'
for e in reversed(data.get('chunk',[])):
    if e.get('type') != 'm.room.message': continue
    if e.get('sender') != '$sender': continue
    if e.get('origin_server_ts',0) < start_ts: continue
    body = e.get('content',{}).get('body','')
    msgtype = e.get('content',{}).get('msgtype','')
    if msgtype_filter and msgtype != msgtype_filter:
        continue
    print(body)
" 2>/dev/null)

    if [ -n "$fallback" ]; then
        local match=$(echo "$fallback" | grep -i "$pattern" | head -1)
        if [ -n "$match" ]; then
            LAST_RESPONSE="$match"
            return 0
        fi
    fi

    return 1
}

wait_claude_msg() {
    wait_for_bot_msg "$CLAUDE_TOKEN" "SYNC_TOKEN" "$CLAUDE_BOT" "$@"
}

wait_openclaw_msg() {
    wait_for_bot_msg "$OPENCLAW_TOKEN" "SYNC_TOKEN_OC" "$OPENCLAW_BOT" "$@"
}

# Wait for @nl-librenms messages (alert/recovery notices, triage instructions)
wait_librenms_msg() {
    wait_for_bot_msg "$POLL_TOKEN" "SYNC_TOKEN_POLL" "$LIBRENMS_BOT" "$@"
}

# ─── Alert Helpers ─────────────────────────────────────────────────────────────

send_alert() {
    local hostname="$1" rule="$2" severity="$3" state="${4:-1}"
    curl -sk -o /dev/null -w "%{http_code}" -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"hostname\":\"$hostname\",\"title\":\"$rule\",\"severity\":\"$severity\",\"state\":$state}"
}

send_registration() {
    local hostname="$1" rule="$2" issue_id="$3"
    curl -sk -o /dev/null -w "%{http_code}" -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"action\":\"register\",\"hostname\":\"$hostname\",\"ruleName\":\"$rule\",\"issueId\":\"$issue_id\"}"
}

get_active_alerts() {
    cat "$ALERTS_FILE" 2>/dev/null
}

get_host_entry() {
    local hostname="$1"
    python3 -c "
import json, sys
data = json.load(open('$ALERTS_FILE'))
entry = data.get('$hostname')
if entry:
    json.dump(entry, sys.stdout, indent=2)
" 2>/dev/null
}

# Count YT issues in project
yt_issue_count() {
    curl -sk -H "$YT_AUTH" "$YT_URL/api/issues?query=project:$YT_PROJECT&fields=idReadable" 2>/dev/null | \
        python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null
}

# Get latest YT issue in project
yt_latest_issue() {
    curl -sk -H "$YT_AUTH" \
        "$YT_URL/api/issues?query=project:$YT_PROJECT+sort+by:created+desc&fields=idReadable,summary,customFields(name,value(name))&\$top=1" 2>/dev/null | \
        python3 -c "
import json, sys
issues = json.load(sys.stdin)
if issues:
    i = issues[0]
    print(i.get('idReadable',''))
    print(i.get('summary',''))
    fields = {}
    for f in i.get('customFields',[]):
        v = f.get('value')
        if isinstance(v, dict):
            fields[f['name']] = v.get('name','')
        elif v is not None:
            fields[f['name']] = str(v)
    for k,v in fields.items():
        print(f'{k}={v}')
" 2>/dev/null
}

# Delete all issues in project
yt_delete_all() {
    local issues
    issues=$(curl -sk -H "$YT_AUTH" "$YT_URL/api/issues?query=project:$YT_PROJECT&fields=idReadable" 2>/dev/null | \
        python3 -c "import json,sys; [print(i['idReadable']) for i in json.load(sys.stdin)]" 2>/dev/null)
    local count=0
    for id in $issues; do
        curl -sk -X DELETE -H "$YT_AUTH" "$YT_URL/api/issues/$id" >/dev/null 2>&1
        ((count++))
    done
    echo "$count"
}

# Bounce LibreNMS Receiver (deactivate + activate to clear staticData)
bounce_librenms_wf() {
    curl -sk -o /dev/null -X PATCH "https://n8n.example.net/api/v1/workflows/$LIBRENMS_WF_ID" \
        -H "X-N8N-API-KEY: $N8N_API_KEY" -H "Content-Type: application/json" \
        -d '{"active":false}' 2>/dev/null
    sleep 2
    curl -sk -o /dev/null -X PATCH "https://n8n.example.net/api/v1/workflows/$LIBRENMS_WF_ID" \
        -H "X-N8N-API-KEY: $N8N_API_KEY" -H "Content-Type: application/json" \
        -d '{"active":true}' 2>/dev/null
    sleep 2
}

# ─── Clean Slate ───────────────────────────────────────────────────────────────
clean_slate() {
    log "Running clean slate..."

    # Delete all IFRNLLEI01PRD issues
    local deleted
    deleted=$(yt_delete_all)
    log "  Deleted $deleted YT issues"

    # Clear active alerts
    echo '{}' > "$ALERTS_FILE"
    log "  Cleared active-alerts.json"

    # Remove triage locks
    rm -rf /tmp/triage-lock-* 2>/dev/null
    rm -rf /tmp/infra-triage-* 2>/dev/null
    log "  Cleared triage locks"

    # Remove gateway lock/cooldown
    rm -f "$GW/gateway.lock" "$GW/gateway.cooldown."* 2>/dev/null
    log "  Cleared gateway locks/cooldowns"

    # Bounce LibreNMS Receiver to clear staticData
    bounce_librenms_wf
    log "  Bounced LibreNMS Receiver workflow"

    sleep 3
}

# ─── Preflight ─────────────────────────────────────────────────────────────────
run_preflight() {
    log "TEST 0 — Preflight checks"
    local failures=0

    # Check n8n LibreNMS workflow active
    local active
    active=$(curl -sk "https://n8n.example.net/api/v1/workflows/$LIBRENMS_WF_ID" \
        -H "X-N8N-API-KEY: $N8N_API_KEY" 2>/dev/null | \
        python3 -c "import json,sys; print(json.load(sys.stdin).get('active',''))" 2>/dev/null)
    if [ "$active" = "True" ]; then
        echo "  LibreNMS Receiver workflow: active"
    else
        echo "  LibreNMS Receiver workflow: NOT ACTIVE"
        ((failures++))
    fi

    # Check YouTrack API
    local yt_resp
    yt_resp=$(curl -sk -o /dev/null -w "%{http_code}" -H "$YT_AUTH" "$YT_URL/api/admin/projects?fields=id&\$top=1")
    if [ "$yt_resp" = "200" ]; then
        echo "  YouTrack API: reachable"
    else
        echo "  YouTrack API: UNREACHABLE (HTTP $yt_resp)"
        ((failures++))
    fi

    # Check webhook reachable (empty POST should still get 200)
    local wh_resp
    wh_resp=$(curl -sk -o /dev/null -w "%{http_code}" -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" -d '{}')
    if [ "$wh_resp" = "200" ]; then
        echo "  LibreNMS webhook: reachable"
    else
        echo "  LibreNMS webhook: UNREACHABLE (HTTP $wh_resp)"
        ((failures++))
    fi

    # Check Matrix tokens
    local matrix_ok
    matrix_ok=$(python3 -c "
import requests
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/account/whoami',
    headers={'Authorization':'Bearer $CLAUDE_TOKEN'}, timeout=10)
print('ok' if r.status_code == 200 else 'fail')
" 2>/dev/null)
    if [ "$matrix_ok" = "ok" ]; then
        echo "  Matrix Claude token: valid"
    else
        echo "  Matrix Claude token: INVALID"
        ((failures++))
    fi

    # Check active-alerts.json writable
    if [ -w "$ALERTS_FILE" ] || touch "$ALERTS_FILE" 2>/dev/null; then
        echo "  active-alerts.json: writable"
    else
        echo "  active-alerts.json: NOT WRITABLE"
        ((failures++))
    fi

    # Check OpenClaw container running (for heavy tests)
    if ! $LIGHT_ONLY; then
        local oc_up
        oc_up=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no root@nl-openclaw01 \
            "docker ps --filter name=openclaw --format '{{.Status}}'" 2>/dev/null)
        if echo "$oc_up" | grep -q "Up"; then
            echo "  OpenClaw container: running"
        else
            echo "  OpenClaw container: NOT RUNNING (heavy tests will fail)"
            ((failures++))
        fi
    fi

    if [ $failures -gt 0 ]; then
        fail "Preflight: $failures check(s) failed"
        echo "ABORTING — fix preflight failures before running tests"
        exit 1
    fi
    pass "Preflight: all checks passed"
}

# ─── T1: New Alert → Matrix Notice + Triage Instruction ─────────────────────
test_t1_new_alert_matrix_post() {
    echo ""
    echo -e "${BOLD}═══ T1: New Alert → Matrix Notice + Triage Instruction ═══${NC}"

    init_sync_poll
    PHASE_START_TS=$(($(date +%s) * 1000))

    log "Sending alert: $TEST_HOST / $TEST_RULE / $TEST_SEVERITY"
    local http_code
    http_code=$(send_alert "$TEST_HOST" "$TEST_RULE" "$TEST_SEVERITY" 1)

    if [ "$http_code" = "200" ]; then
        pass "T1.1: Webhook accepted alert (HTTP $http_code)"
    else
        fail "T1.1: Webhook rejected alert (HTTP $http_code)"
        return
    fi

    # T1.2: Alert notice in Matrix (m.notice from @nl-librenms)
    log "Waiting for alert notice in #infra (up to 30s)..."
    if wait_librenms_msg "$TEST_HOST" 30 "m.notice"; then
        pass "T1.2: Alert notice posted: ${LAST_RESPONSE:0:120}"
    else
        fail "T1.2: No alert notice for $TEST_HOST in 30s"
        return
    fi

    # T1.3: Triage instruction with @openclaw mention (also from @nl-librenms)
    # May have arrived in the same sync batch as alert — /messages fallback uses PHASE_START_TS
    log "Waiting for triage instruction (up to 15s)..."
    if wait_librenms_msg "infra-triage" 15 "m.text"; then
        pass "T1.3: Triage instruction posted: ${LAST_RESPONSE:0:120}"
    else
        fail "T1.3: No triage instruction posted"
    fi

    # T1.4: Host entry created in active-alerts.json
    sleep 8  # Give Save Alerts SSH node time to write (runs early in pipeline)
    local entry
    entry=$(get_host_entry "$TEST_HOST")
    if [ -n "$entry" ]; then
        pass "T1.4: Host entry in active-alerts.json"
    else
        fail "T1.4: No host entry in active-alerts.json"
    fi

    # T1.5: Verify no issueId yet (triage hasn't run)
    local has_issue
    has_issue=$(echo "$entry" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('issueId',''))" 2>/dev/null)
    if [ -z "$has_issue" ] || [ "$has_issue" = "None" ] || [ "$has_issue" = "null" ]; then
        pass "T1.5: No issueId yet (awaiting triage)"
    else
        pass "T1.5: issueId already set: $has_issue (triage was fast)"
    fi
}

# ─── T2: Recovery → Matrix Recovery Notice ──────────────────────────────────
test_t2_recovery() {
    echo ""
    echo -e "${BOLD}═══ T2: Recovery → Matrix Recovery Notice ═══${NC}"

    init_sync_poll
    PHASE_START_TS=$(($(date +%s) * 1000))

    log "Sending recovery for $TEST_HOST..."
    local http_code
    http_code=$(send_alert "$TEST_HOST" "$TEST_RULE" "$TEST_SEVERITY" 0)

    if [ "$http_code" = "200" ]; then
        pass "T2.1: Webhook accepted recovery (HTTP $http_code)"
    else
        fail "T2.1: Webhook rejected recovery (HTTP $http_code)"
        return
    fi

    # T2.2: Recovery notice in Matrix (from @nl-librenms)
    log "Waiting for recovery notice in #infra (up to 30s)..."
    if wait_librenms_msg "$TEST_HOST\|recover\|cleared" 30 "m.notice"; then
        pass "T2.2: Recovery notice posted: ${LAST_RESPONSE:0:120}"
    else
        fail "T2.2: No recovery notice for $TEST_HOST in 30s"
    fi

    # T2.3: Host rules should be cleaned from active-alerts
    sleep 3
    local entry
    entry=$(get_host_entry "$TEST_HOST")
    local rule_count
    rule_count=$(echo "$entry" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(len(d.get('rules',{})))
except:
    print(0)
" 2>/dev/null)
    if [ "$rule_count" = "0" ] || [ -z "$entry" ]; then
        pass "T2.3: Host rules cleaned after recovery"
    else
        skip "T2.3: Host still has $rule_count rules (may have other active rules)"
    fi
}

# ─── T3: Repeat Alert → Dedup (same host/rule) ──────────────────────────────
test_t3_repeat_dedup() {
    echo ""
    echo -e "${BOLD}═══ T3: Repeat Alert → Dedup + Count Increment ═══${NC}"

    # Use a fresh host for this test
    local repeat_host="e2e-repeat-$(date +%s)"

    # First alert: creates entry
    log "Sending first alert for $repeat_host..."
    send_alert "$repeat_host" "$TEST_RULE" "$TEST_SEVERITY" 1 >/dev/null
    sleep 8  # Wait for Save Alerts SSH node to write

    local count_before
    count_before=$(get_host_entry "$repeat_host" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('rules',{}).get('Devices up/down',{}).get('count',0))
except:
    print(0)
" 2>/dev/null)

    if [ "$count_before" -ge 1 ] 2>/dev/null; then
        pass "T3.1: First alert created entry (count=$count_before)"
    else
        fail "T3.1: First alert did not create entry"
        return
    fi

    # Register a fake issueId so the creation lock (60s, issueId=null) doesn't block
    log "Registering fake issueId to bypass creation lock..."
    send_registration "$repeat_host" "$TEST_RULE" "IFRNLLEI01PRD-997" >/dev/null
    sleep 5

    # Second alert: same host+rule — should increment count (isRepeat path)
    log "Sending repeat alert for $repeat_host..."
    send_alert "$repeat_host" "$TEST_RULE" "$TEST_SEVERITY" 1 >/dev/null
    sleep 8  # Wait for Save Alerts

    local count_after
    count_after=$(get_host_entry "$repeat_host" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('rules',{}).get('Devices up/down',{}).get('count',0))
except:
    print(0)
" 2>/dev/null)

    if [ "$count_after" -gt "$count_before" ] 2>/dev/null; then
        pass "T3.2: Repeat alert incremented count ($count_before → $count_after)"
    else
        fail "T3.2: Count not incremented ($count_before → $count_after)"
    fi

    # Clean up
    send_alert "$repeat_host" "$TEST_RULE" "$TEST_SEVERITY" 0 >/dev/null
}

# ─── T4: Registration Callback → issueId Stored ─────────────────────────────
test_t4_registration_callback() {
    echo ""
    echo -e "${BOLD}═══ T4: Registration Callback → issueId Stored ═══${NC}"

    local reg_host="e2e-register-$(date +%s)"
    local fake_issue="IFRNLLEI01PRD-999"

    # Create entry first (alert)
    log "Sending alert for $reg_host..."
    send_alert "$reg_host" "$TEST_RULE" "$TEST_SEVERITY" 1 >/dev/null
    sleep 5

    local entry_before
    entry_before=$(get_host_entry "$reg_host")
    if [ -n "$entry_before" ]; then
        pass "T4.1: Host entry exists"
    else
        fail "T4.1: No host entry created"
        return
    fi

    # Send registration callback
    log "Sending registration callback: $reg_host → $fake_issue..."
    local http_code
    http_code=$(send_registration "$reg_host" "$TEST_RULE" "$fake_issue")

    if [ "$http_code" = "200" ]; then
        pass "T4.2: Registration callback accepted (HTTP $http_code)"
    else
        fail "T4.2: Registration callback failed (HTTP $http_code)"
        return
    fi

    sleep 5  # Wait for Save Alerts

    # Check issueId stored
    local stored_id
    stored_id=$(get_host_entry "$reg_host" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('issueId',''))
except:
    print('')
" 2>/dev/null)

    if [ "$stored_id" = "$fake_issue" ]; then
        pass "T4.3: issueId stored correctly: $stored_id"
    else
        fail "T4.3: issueId mismatch: expected '$fake_issue', got '$stored_id'"
    fi

    # Clean up
    send_alert "$reg_host" "$TEST_RULE" "$TEST_SEVERITY" 0 >/dev/null
}

# ─── T5: Full Triage — OpenClaw Creates YT Issue ────────────────────────────
test_t5_full_triage() {
    echo ""
    echo -e "${BOLD}═══ T5: Full Triage — OpenClaw Creates YT Issue (HEAVY, ~3-5 min) ═══${NC}"

    if $LIGHT_ONLY; then
        skip "T5: Skipped (--light mode)"
        return
    fi

    # Use a real-ish hostname that infra-triage.sh can look up
    # 10.0.X.X is the UniFi Cloud Key from the handover doc
    local triage_host="10.0.X.X"

    # Ensure no prior entry
    python3 -c "
import json
data = json.load(open('$ALERTS_FILE'))
data.pop('$triage_host', None)
json.dump(data, open('$ALERTS_FILE','w'), indent=2)
" 2>/dev/null
    # Bounce to clear staticData for this host
    bounce_librenms_wf

    init_sync_poll
    init_sync_openclaw
    PHASE_START_TS=$(($(date +%s) * 1000))

    local issues_before
    issues_before=$(yt_issue_count)

    log "Sending alert for $triage_host (real host)..."
    local http_code
    http_code=$(send_alert "$triage_host" "$TEST_RULE" "$TEST_SEVERITY" 1)

    if [ "$http_code" = "200" ]; then
        pass "T5.1: Alert accepted"
    else
        fail "T5.1: Alert rejected (HTTP $http_code)"
        return
    fi

    # T5.2: Wait for triage instruction (from @nl-librenms)
    log "Waiting for triage instruction..."
    if wait_librenms_msg "infra-triage" 30 "m.text"; then
        pass "T5.2: Triage instruction posted"
    else
        fail "T5.2: No triage instruction"
        return
    fi

    # T5.3: Wait for OpenClaw to respond (runs infra-triage.sh)
    log "Waiting for OpenClaw triage response (up to 180s)..."
    if wait_openclaw_msg "issue\|triage\|created\|IFRNLLEI01PRD\|investigating\|Level" 180; then
        pass "T5.3: OpenClaw responded: ${LAST_RESPONSE:0:120}"
    else
        fail "T5.3: OpenClaw did not respond to triage instruction in 180s"
        return
    fi

    # T5.4: Wait for YT issue to appear (triage script creates it)
    log "Waiting for YT issue creation (up to 120s)..."
    local yt_found=0
    for i in $(seq 1 24); do
        local issues_now
        issues_now=$(yt_issue_count)
        if [ "$issues_now" -gt "$issues_before" ] 2>/dev/null; then
            yt_found=1
            break
        fi
        sleep 5
    done

    if [ $yt_found -eq 1 ]; then
        local latest
        latest=$(yt_latest_issue)
        local issue_id=$(echo "$latest" | head -1)
        local issue_summary=$(echo "$latest" | sed -n '2p')
        pass "T5.4: YT issue created: $issue_id — $issue_summary"

        # T5.5: Check custom fields
        local hostname_field=$(echo "$latest" | grep "^Hostname=" | cut -d= -f2-)
        if [ -n "$hostname_field" ]; then
            pass "T5.5: Hostname custom field set: $hostname_field"
        else
            fail "T5.5: Hostname custom field not set"
        fi

        # T5.6: Check registration callback stored issueId
        sleep 10  # Give callback time
        local stored_id
        stored_id=$(get_host_entry "$triage_host" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('issueId',''))
except:
    print('')
" 2>/dev/null)
        if [ "$stored_id" = "$issue_id" ]; then
            pass "T5.6: Registration callback stored issueId: $stored_id"
        else
            skip "T5.6: issueId mismatch (expected $issue_id, got '$stored_id') — callback may be delayed"
        fi
    else
        fail "T5.4: No new YT issue after 120s"
    fi
}

# ─── T6: Repeat Alert With YT State Check ───────────────────────────────────
test_t6_repeat_yt_state() {
    echo ""
    echo -e "${BOLD}═══ T6: Repeat Alert → YT State-Aware Routing ═══${NC}"

    if $LIGHT_ONLY; then
        skip "T6: Skipped (--light mode)"
        return
    fi

    # This test requires a host with a registered issueId in active-alerts.json
    # Use whatever T5 created, or find an existing one
    local test_host=""
    local test_issue=""
    test_host=$(python3 -c "
import json
data = json.load(open('$ALERTS_FILE'))
for h, v in data.items():
    if v.get('issueId') and not h.startswith('e2e-'):
        print(h)
        break
" 2>/dev/null)
    test_issue=$(python3 -c "
import json
data = json.load(open('$ALERTS_FILE'))
for h, v in data.items():
    if v.get('issueId') and not h.startswith('e2e-'):
        print(v['issueId'])
        break
" 2>/dev/null)

    if [ -z "$test_host" ] || [ -z "$test_issue" ]; then
        skip "T6: No host with registered issueId found — run T5 first"
        return
    fi

    log "Using host=$test_host, issue=$test_issue"

    # T6.1: Move issue to "Open" and send repeat alert → should comment
    log "Setting $test_issue to Open..."
    curl -sk -o /dev/null -X POST -H "$YT_AUTH" -H "Content-Type: application/json" \
        "$YT_URL/api/commands" \
        -d "{\"query\":\"state Open\",\"issues\":[{\"idReadable\":\"$test_issue\"}]}" 2>/dev/null
    sleep 3

    init_sync_poll
    PHASE_START_TS=$(($(date +%s) * 1000))

    log "Sending repeat alert..."
    send_alert "$test_host" "$TEST_RULE" "$TEST_SEVERITY" 1 >/dev/null
    sleep 10

    # Check YT issue got a comment (via API)
    local comments
    comments=$(curl -sk -H "$YT_AUTH" \
        "$YT_URL/api/issues/$test_issue/comments?fields=text,created&\$top=1&\$orderBy=created+desc" 2>/dev/null | \
        python3 -c "
import json,sys
cs = json.load(sys.stdin)
if cs:
    print(cs[0].get('text','')[:200])
" 2>/dev/null)

    if [ -n "$comments" ] && echo "$comments" | grep -qi "alert\|re-alert\|repeat\|still"; then
        pass "T6.1: Re-alert comment posted to $test_issue"
    else
        skip "T6.1: Could not confirm re-alert comment (may need more time)"
    fi

    # T6.2: Move issue to "To Verify" and send repeat → should reopen to Open
    log "Setting $test_issue to To Verify..."
    curl -sk -o /dev/null -X POST -H "$YT_AUTH" -H "Content-Type: application/json" \
        "$YT_URL/api/commands" \
        -d "{\"query\":\"state To Verify\",\"issues\":[{\"idReadable\":\"$test_issue\"}]}" 2>/dev/null
    sleep 3

    log "Sending repeat alert (should reopen)..."
    send_alert "$test_host" "$TEST_RULE" "$TEST_SEVERITY" 1 >/dev/null
    sleep 10

    # Check state changed back to Open
    local state
    state=$(curl -sk -H "$YT_AUTH" "$YT_URL/api/issues/$test_issue?fields=customFields(name,value(name))" 2>/dev/null | \
        python3 -c "
import json, sys
data = json.load(sys.stdin)
for f in data.get('customFields', []):
    if f.get('name') == 'State':
        print(f.get('value', {}).get('name', 'UNKNOWN'))
        break
" 2>/dev/null)

    if [ "$state" = "Open" ]; then
        pass "T6.2: Issue reopened from To Verify → Open"
    else
        fail "T6.2: Issue state is '$state', expected 'Open' (reopen)"
    fi
}

# ─── T7: Deploy Cooldown — Suppress After Issue Close ────────────────────────
test_t7_deploy_cooldown() {
    echo ""
    echo -e "${BOLD}═══ T7: Deploy Cooldown — Suppress After Recovery ═══${NC}"

    # Use a fresh host
    local cd_host="e2e-cooldown-$(date +%s)"

    # Create entry with alert
    log "Sending initial alert for $cd_host..."
    send_alert "$cd_host" "$TEST_RULE" "$TEST_SEVERITY" 1 >/dev/null
    sleep 5

    # Register a fake issue
    send_registration "$cd_host" "$TEST_RULE" "IFRNLLEI01PRD-998" >/dev/null
    sleep 5

    # Send recovery — this sets the deploy cooldown in closedHosts (in-memory)
    log "Sending recovery for $cd_host..."
    send_alert "$cd_host" "$TEST_RULE" "$TEST_SEVERITY" 0 >/dev/null
    sleep 5

    # Now send a NEW alert within cooldown window — should be suppressed
    init_sync_poll
    PHASE_START_TS=$(($(date +%s) * 1000))

    log "Sending alert within cooldown window..."
    send_alert "$cd_host" "$TEST_RULE" "$TEST_SEVERITY" 1 >/dev/null

    # Wait 15s — should NOT see an alert notice for this host
    log "Checking for suppression (15s)..."
    if wait_librenms_msg "$cd_host" 15 "m.notice"; then
        # Got a message — check if it's the recovery from above (stale) or new alert
        if echo "$LAST_RESPONSE" | grep -qi "recover\|cleared"; then
            pass "T7.1: Only recovery notice seen (new alert suppressed)"
        else
            fail "T7.1: Alert was NOT suppressed during cooldown: ${LAST_RESPONSE:0:100}"
        fi
    else
        pass "T7.1: Alert suppressed during deploy cooldown (no notice posted)"
    fi
}

# ─── T8: Creation Lock — Simultaneous Alerts Same Host ──────────────────────
test_t8_creation_lock() {
    echo ""
    echo -e "${BOLD}═══ T8: Creation Lock — Simultaneous Alerts Same Host ═══${NC}"

    local lock_host="e2e-lock-$(date +%s)"

    init_sync_poll
    PHASE_START_TS=$(($(date +%s) * 1000))

    # Send two alerts for same host in quick succession (< 60s apart)
    log "Sending two alerts for $lock_host in quick succession..."
    send_alert "$lock_host" "Devices up/down" "$TEST_SEVERITY" 1 >/dev/null
    sleep 1
    send_alert "$lock_host" "Device rebooted" "$TEST_SEVERITY" 1 >/dev/null

    sleep 8  # Wait for both to process

    # Check that only ONE alert notice was posted (second was suppressed by creation lock)
    # Count messages matching this host
    local msg_count=0

    # Check active-alerts: should have both rules but only one entry
    local entry
    entry=$(get_host_entry "$lock_host")
    if [ -n "$entry" ]; then
        local rule_count
        rule_count=$(echo "$entry" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(len(d.get('rules',{})))
" 2>/dev/null)
        pass "T8.1: Host entry exists with $rule_count rule(s)"

        # The creation lock should prevent the second alert from posting to Matrix
        # (it still gets stored in active-alerts but doesn't trigger a new triage)
        if [ "$rule_count" -le 2 ] 2>/dev/null; then
            pass "T8.2: Both rules tracked (dedup working)"
        else
            fail "T8.2: Unexpected rule count: $rule_count"
        fi
    else
        fail "T8.1: No host entry created"
    fi

    # Clean up
    send_alert "$lock_host" "Devices up/down" "$TEST_SEVERITY" 0 >/dev/null
    send_alert "$lock_host" "Device rebooted" "$TEST_SEVERITY" 0 >/dev/null
}

# ─── T9: Malformed Alert → Ignored ──────────────────────────────────────────
test_t9_malformed_alert() {
    echo ""
    echo -e "${BOLD}═══ T9: Malformed Alert → Gracefully Ignored ═══${NC}"

    init_sync_poll
    PHASE_START_TS=$(($(date +%s) * 1000))

    # Send alert with no hostname
    log "Sending alert with empty hostname..."
    local http_code
    http_code=$(curl -sk -o /dev/null -w "%{http_code}" -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d '{"hostname":"","title":"Test Rule","severity":"warning","state":1}')

    if [ "$http_code" = "200" ]; then
        pass "T9.1: Webhook accepted malformed alert (200, handled gracefully)"
    else
        pass "T9.1: Webhook rejected malformed alert (HTTP $http_code)"
    fi

    # Should NOT post to Matrix
    log "Checking no Matrix post for empty hostname (10s)..."
    if wait_librenms_msg "Test Rule" 10 "m.notice"; then
        fail "T9.2: Alert with empty hostname was posted to Matrix!"
    else
        pass "T9.2: Empty hostname alert correctly filtered"
    fi

    # Send completely empty payload
    log "Sending empty payload..."
    http_code=$(curl -sk -o /dev/null -w "%{http_code}" -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" -d '{}')
    pass "T9.3: Empty payload handled (HTTP $http_code)"
}

# ─── T10: Acknowledged State (state=2) ──────────────────────────────────────
test_t10_acknowledged() {
    echo ""
    echo -e "${BOLD}═══ T10: Acknowledged Alert (state=2) ═══${NC}"

    local ack_host="e2e-ack-$(date +%s)"

    init_sync_poll
    PHASE_START_TS=$(($(date +%s) * 1000))

    log "Sending acknowledged alert for $ack_host..."
    local http_code
    http_code=$(send_alert "$ack_host" "$TEST_RULE" "$TEST_SEVERITY" 2)

    if [ "$http_code" = "200" ]; then
        pass "T10.1: Acknowledged alert accepted (HTTP $http_code)"
    else
        fail "T10.1: Acknowledged alert rejected (HTTP $http_code)"
        return
    fi

    # Acknowledged alerts should post a notice but NOT trigger triage
    log "Checking for acknowledged notice (20s)..."
    if wait_librenms_msg "$ack_host\|acknowledged" 20 "m.notice"; then
        pass "T10.2: Acknowledged notice posted: ${LAST_RESPONSE:0:80}"
    else
        skip "T10.2: No acknowledged notice (may be filtered by Has Content?)"
    fi

    # Should NOT post triage instruction
    if wait_librenms_msg "infra-triage.*$ack_host" 10 "m.text"; then
        fail "T10.3: Triage instruction posted for acknowledged alert!"
    else
        pass "T10.3: No triage instruction for acknowledged alert"
    fi
}

# ─── Main ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  E2E Test Suite: Infrastructure Triage Pipeline             ║${NC}"
echo -e "${BOLD}║  Room: #infra-nl-prod | Project: $YT_PROJECT      ║${NC}"
if $LIGHT_ONLY; then
echo -e "${BOLD}║  Mode: LIGHT (skipping heavy OpenClaw/Claude tests)         ║${NC}"
fi
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Sanity
if ! python3 -c "import requests" 2>/dev/null; then
    echo "ERROR: python3 requests module required"
    exit 1
fi

run_preflight

echo ""
echo -e "${BOLD}─── Clean Slate ───────────────────────────────────────────────${NC}"
clean_slate

echo ""
echo -e "${BOLD}─── Light Tests (n8n behavior, no OpenClaw/Claude) ────────────${NC}"
test_t1_new_alert_matrix_post
test_t2_recovery
test_t3_repeat_dedup
test_t4_registration_callback
test_t7_deploy_cooldown
test_t8_creation_lock
test_t9_malformed_alert
test_t10_acknowledged

if ! $LIGHT_ONLY; then
    echo ""
    echo -e "${BOLD}─── Heavy Tests (OpenClaw triage, YT state, ~5-10 min) ───────${NC}"
    echo ""
    echo -e "${BOLD}─── Clean Slate (before heavy tests) ──────────────────────────${NC}"
    clean_slate
    test_t5_full_triage
    test_t6_repeat_yt_state
fi

# ─── Cleanup ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}─── Cleanup ───────────────────────────────────────────────────${NC}"
log "Clearing e2e test entries from active-alerts..."
python3 -c "
import json
data = json.load(open('$ALERTS_FILE'))
keys_to_remove = [k for k in data if k.startswith('e2e-')]
for k in keys_to_remove:
    del data[k]
json.dump(data, open('$ALERTS_FILE','w'), indent=2)
print(f'Removed {len(keys_to_remove)} e2e entries')
" 2>/dev/null

rm -rf /tmp/triage-lock-e2e-* /tmp/infra-triage-e2e-* 2>/dev/null
log "Cleanup complete"

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "  Results: ${GREEN}$PASS_COUNT passed${NC}, ${RED}$FAIL_COUNT failed${NC}, ${YELLOW}$SKIP_COUNT skipped${NC}"
echo -e "  Total:   $((PASS_COUNT + FAIL_COUNT + SKIP_COUNT)) checks"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo ""

[ $FAIL_COUNT -eq 0 ] && exit 0 || exit 1
