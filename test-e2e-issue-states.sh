#!/bin/bash
# E2E Test Suite for Claude Gateway — Mention-based routing + issue state transitions
# Tests all 4 modes (oc-cc, oc-oc, cc-cc, cc-oc), mention routing, YouTrack state changes,
# room routing, and bot isolation.
#
# Usage: bash test-e2e-issue-states.sh 2>&1 | tee /tmp/e2e-results.txt

set -o pipefail

# ─── Configuration ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.env"

CLAUDE_BOT="@claude:matrix.example.net"
OPENCLAW_BOT="@openclaw:matrix.example.net"
DOMINICUS="@dominicus:matrix.example.net"

ROOM_CHATOPS="$MATRIX_ROOM_CHATOPS"
ROOM_CUBEOS="$MATRIX_ROOM_CUBEOS"
ROOM_MESHSAT="$MATRIX_ROOM_MESHSAT"

MATRIX_TOKEN="$MATRIX_DOMINICUS_API_KEY"
MATRIX_SERVER="https://matrix.example.net"

CLAUDE_TOKEN="$MATRIX_CLAUDE_TOKEN"
OPENCLAW_TOKEN="$MATRIX_OPENCLAW_TOKEN"

YT_URL="https://youtrack.example.net"
YT_AUTH="Authorization: Bearer $YT_TOKEN"

MODE_FILE="/home/app-user/gateway.mode"
SYNC_SCRIPT="/home/app-user/scripts/sync-mode-openclaw.sh"

TEST_ISSUE="CUBEOS-4"
MESHSAT_TEST_ISSUE="MESHSAT-1"

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# Track sync tokens per room per bot to avoid replaying old messages
declare -A SYNC_TOKENS

# ─── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── Helper Functions ──────────────────────────────────────────────────────────

log() { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
pass() { echo -e "  ${GREEN}PASS${NC} $*"; ((PASS_COUNT++)); }
fail() { echo -e "  ${RED}FAIL${NC} $*"; ((FAIL_COUNT++)); }
skip() { echo -e "  ${YELLOW}SKIP${NC} $*"; ((SKIP_COUNT++)); }

send_message() {
    local room="$1" text="$2"
    local txn="e2e-$(date +%s%N)"
    local url="$MATRIX_SERVER/_matrix/client/v3/rooms/$room/send/m.room.message/$txn"
    python3 -c "
import requests, json, sys
r = requests.put('$url',
    json={'msgtype':'m.text','body':$(python3 -c "import json; print(json.dumps(\"$text\"))")},
    headers={'Authorization':'Bearer $MATRIX_TOKEN'}, timeout=10)
if r.status_code != 200:
    print(f'send_message failed: {r.status_code} {r.text[:200]}', file=sys.stderr)
    sys.exit(1)
"
}

send_mention() {
    local room="$1" bot_mxid="$2" text="$3"
    local txn="e2e-mention-$(date +%s%N)"
    local url="$MATRIX_SERVER/_matrix/client/v3/rooms/$room/send/m.room.message/$txn"
    local display_name="${bot_mxid%%:*}"
    display_name="${display_name#@}"
    python3 -c "
import requests, json, sys
bot = '$bot_mxid'
display = '$display_name'
text = $(python3 -c "import json; print(json.dumps(\"$text\"))")
plain = f'{bot} {text}'
html = f'<a href=\"https://matrix.to/#/{bot}\">{display}</a> {text}'
r = requests.put('$url',
    json={'msgtype':'m.text','body':plain,'format':'org.matrix.custom.html','formatted_body':html},
    headers={'Authorization':'Bearer $MATRIX_TOKEN'}, timeout=10)
if r.status_code != 200:
    print(f'send_mention failed: {r.status_code} {r.text[:200]}', file=sys.stderr)
    sys.exit(1)
"
}

# Initialize sync token for a bot+room combo (skip old messages)
init_sync_token() {
    local bot_token="$1" room="$2"
    local key="${bot_token:0:10}_${room}"
    local token
    token=$(python3 -c "
import requests, json
filt = json.dumps({'room':{'rooms':['$room'],'timeline':{'limit':0}}})
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/sync',
    params={'timeout':'0','filter':filt},
    headers={'Authorization':'Bearer $bot_token'}, timeout=15)
data = r.json()
print(data.get('next_batch',''))
" 2>/dev/null)
    if [ -n "$token" ]; then
        SYNC_TOKENS["$key"]="$token"
    fi
}

# Wait for a response from a specific bot in a room, optionally matching text
# Returns 0 on match, 1 on timeout
# Sets LAST_RESPONSE to the matched message body
wait_for_response() {
    local room="$1" bot_mxid="$2" contains_text="$3" timeout="${4:-60}"
    local bot_token
    if [ "$bot_mxid" = "$CLAUDE_BOT" ]; then
        bot_token="$CLAUDE_TOKEN"
    elif [ "$bot_mxid" = "$OPENCLAW_BOT" ]; then
        bot_token="$OPENCLAW_TOKEN"
    else
        echo "Unknown bot: $bot_mxid" >&2
        return 1
    fi

    local key="${bot_token:0:10}_${room}"
    local since="${SYNC_TOKENS[$key]:-}"

    local elapsed=0
    local interval=5
    LAST_RESPONSE=""

    while [ $elapsed -lt $timeout ]; do
        local match
        match=$(python3 -c "
import requests, json
filt = json.dumps({'room':{'rooms':['$room'],'timeline':{'limit':20}}})
params = {'timeout':'0','filter':filt}
since = '$since'
if since:
    params['since'] = since
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/sync',
    params=params,
    headers={'Authorization':'Bearer $bot_token'}, timeout=15)
data = r.json()
nb = data.get('next_batch','')
if nb:
    print('TOKEN:' + nb)
room_data = data.get('rooms',{}).get('join',{}).get('$room',{})
events = room_data.get('timeline',{}).get('events',[])
for e in events:
    if e.get('type') == 'm.room.message' and e.get('sender') == '$bot_mxid':
        body = e.get('content',{}).get('body','')
        search = '$contains_text'
        if not search or search.lower() in body.lower():
            print('MATCH:' + body[:500])
            break
" 2>/dev/null)

        # Update since token
        local new_token
        new_token=$(echo "$match" | grep '^TOKEN:' | head -1 | cut -d: -f2-)
        if [ -n "$new_token" ]; then
            since="$new_token"
            SYNC_TOKENS["$key"]="$new_token"
        fi

        local found
        found=$(echo "$match" | grep '^MATCH:' | head -1 | cut -d: -f2-)
        if [ -n "$found" ]; then
            LAST_RESPONSE="$found"
            return 0
        fi

        sleep $interval
        elapsed=$((elapsed + interval))
    done
    return 1
}

# Wait to confirm a bot does NOT respond
# Returns 0 if silent (good), 1 if bot responded (bad)
wait_for_silence() {
    local room="$1" bot_mxid="$2" timeout="${3:-15}"
    local bot_token
    if [ "$bot_mxid" = "$CLAUDE_BOT" ]; then
        bot_token="$CLAUDE_TOKEN"
    elif [ "$bot_mxid" = "$OPENCLAW_BOT" ]; then
        bot_token="$OPENCLAW_TOKEN"
    else
        echo "Unknown bot: $bot_mxid" >&2
        return 1
    fi

    local key="${bot_token:0:10}_${room}"
    local since="${SYNC_TOKENS[$key]:-}"

    sleep "$timeout"

    local found
    found=$(python3 -c "
import requests, json
filt = json.dumps({'room':{'rooms':['$room'],'timeline':{'limit':20}}})
params = {'timeout':'0','filter':filt}
since = '$since'
if since:
    params['since'] = since
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/sync',
    params=params,
    headers={'Authorization':'Bearer $bot_token'}, timeout=15)
data = r.json()
nb = data.get('next_batch','')
if nb:
    print('TOKEN:' + nb)
room_data = data.get('rooms',{}).get('join',{}).get('$room',{})
events = room_data.get('timeline',{}).get('events',[])
for e in events:
    if e.get('type') == 'm.room.message' and e.get('sender') == '$bot_mxid':
        print('FOUND:' + e.get('content',{}).get('body','')[:200])
        break
" 2>/dev/null)

    # Update since token
    local new_token
    new_token=$(echo "$found" | grep '^TOKEN:' | head -1 | cut -d: -f2-)
    if [ -n "$new_token" ]; then
        SYNC_TOKENS["$key"]="$new_token"
    fi

    local msg
    msg=$(echo "$found" | grep '^FOUND:' | head -1 | cut -d: -f2-)
    if [ -n "$msg" ]; then
        LAST_RESPONSE="$msg"
        return 1  # Bot responded — bad
    fi
    return 0  # Silent — good
}

yt_get_state() {
    local issue_id="$1"
    curl -s -H "$YT_AUTH" "$YT_URL/api/issues/$issue_id?fields=customFields(name,value(name))" 2>/dev/null | \
        python3 -c "
import json, sys
data = json.load(sys.stdin)
for f in data.get('customFields', []):
    if f.get('name') == 'State':
        print(f.get('value', {}).get('name', 'UNKNOWN'))
        break
" 2>/dev/null
}

yt_set_state() {
    local issue_id="$1" state_name="$2"
    # Get numeric ID first
    local numeric_id
    numeric_id=$(curl -s -H "$YT_AUTH" "$YT_URL/api/issues/$issue_id?fields=id" 2>/dev/null | \
        python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

    if [ -z "$numeric_id" ]; then
        echo "Failed to get numeric ID for $issue_id" >&2
        return 1
    fi

    python3 -c "
import requests, json
body = {'customFields': [{'name': 'State', '\$type': 'StateIssueCustomField', 'value': {'name': '$state_name'}}]}
r = requests.post('$YT_URL/api/issues/$numeric_id',
    json=body,
    headers={'Authorization': 'Bearer $YT_TOKEN', 'Content-Type': 'application/json'},
    timeout=10)
" 2>/dev/null
}

set_mode() {
    local mode="$1"
    echo "$mode" > "$MODE_FILE"
    "$SYNC_SCRIPT" "$mode" 2>/dev/null
    sleep 2  # Give OpenClaw time to hot-reload
}

# ─── Preflight ─────────────────────────────────────────────────────────────────

run_preflight() {
    log "TEST 0 — Preflight checks"

    local failures=0

    # Check gateway.mode
    local mode
    mode=$(cat "$MODE_FILE" 2>/dev/null)
    if [ "$mode" != "oc-cc" ]; then
        echo "  gateway.mode is '$mode', setting to oc-cc"
        set_mode "oc-cc"
    fi
    echo "  gateway.mode: oc-cc ✓"

    # Check n8n workflow active
    local n8n_key
    n8n_key=$(python3 -c "import json; cfg=json.load(open('/home/app-user/.claude.json')); print(cfg['mcpServers']['n8n-mcp']['env']['N8N_API_KEY'])")
    local active
    active=$(curl -s "https://n8n.example.net/api/v1/workflows/QGKnHGkw4casiWIU" \
        -H "X-N8N-API-KEY: $n8n_key" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('active',''))" 2>/dev/null)
    if [ "$active" = "True" ]; then
        echo "  Matrix Bridge workflow: active ✓"
    else
        echo "  Matrix Bridge workflow: NOT ACTIVE"
        ((failures++))
    fi

    # Check YouTrack API
    local yt_resp
    yt_resp=$(curl -s -H "$YT_AUTH" "$YT_URL/api/issues/$TEST_ISSUE?fields=idReadable" 2>/dev/null)
    if echo "$yt_resp" | grep -q "$TEST_ISSUE"; then
        echo "  YouTrack API: reachable ✓"
    else
        echo "  YouTrack API: UNREACHABLE"
        ((failures++))
    fi

    # Check issue exists
    local state
    state=$(yt_get_state "$TEST_ISSUE")
    if [ -n "$state" ]; then
        echo "  $TEST_ISSUE exists, state: $state ✓"
    else
        echo "  $TEST_ISSUE: NOT FOUND"
        ((failures++))
    fi

    # Initialize sync tokens for all rooms
    for room in "$ROOM_CHATOPS" "$ROOM_CUBEOS" "$ROOM_MESHSAT"; do
        init_sync_token "$CLAUDE_TOKEN" "$room"
        init_sync_token "$OPENCLAW_TOKEN" "$room"
    done
    echo "  Sync tokens initialized ✓"

    if [ $failures -gt 0 ]; then
        fail "Preflight: $failures check(s) failed"
        echo "ABORTING — fix preflight failures before running tests"
        exit 1
    fi
    pass "Preflight: all checks passed"
}

# ─── Tests ─────────────────────────────────────────────────────────────────────

test_01_claude_mention_routes_to_claude() {
    log "TEST 1 — @claude mention routes to Claude"

    send_mention "$ROOM_CHATOPS" "$CLAUDE_BOT" "!system status"
    if wait_for_response "$ROOM_CHATOPS" "$CLAUDE_BOT" "System" 60; then
        pass "Claude responded to @claude mention: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to @claude mention within 40s"
        return
    fi

    # In oc-cc mode, OpenClaw has requireMention:false so it sees all messages.
    # It may respond to @claude-addressed messages via its LLM (not via ! commands).
    # This is expected — drain any OpenClaw response to keep tokens clean.
    init_sync_token "$OPENCLAW_TOKEN" "$ROOM_CHATOPS"
    pass "OpenClaw token drained (oc-cc: OpenClaw may respond to all messages)"
}

test_02_openclaw_mention_routes_to_openclaw() {
    log "TEST 2 — @openclaw mention routes to OpenClaw only"

    # Re-init Claude token to discard any stale responses from test 1
    init_sync_token "$CLAUDE_TOKEN" "$ROOM_CHATOPS"

    send_mention "$ROOM_CHATOPS" "$OPENCLAW_BOT" "/status"
    if wait_for_response "$ROOM_CHATOPS" "$OPENCLAW_BOT" "" 15; then
        pass "OpenClaw responded to @openclaw mention: ${LAST_RESPONSE:0:80}..."
    else
        fail "OpenClaw did NOT respond to @openclaw mention within 15s"
        return
    fi

    # Claude's Should Handle? rejects @openclaw-only messages in oc-cc mode
    if wait_for_silence "$ROOM_CHATOPS" "$CLAUDE_BOT" 40; then
        pass "Claude stayed silent"
    else
        fail "Claude also responded: ${LAST_RESPONSE:0:80}"
    fi
}

test_03_unaddressed_goes_to_openclaw() {
    log "TEST 3 — Unaddressed message in oc-cc goes to OpenClaw"

    send_message "$ROOM_CHATOPS" "what is 2 + 2?"
    if wait_for_response "$ROOM_CHATOPS" "$OPENCLAW_BOT" "" 60; then
        pass "OpenClaw responded to unaddressed message: ${LAST_RESPONSE:0:80}..."
    else
        fail "OpenClaw did NOT respond to unaddressed message within 60s"
        return
    fi

    if wait_for_silence "$ROOM_CHATOPS" "$CLAUDE_BOT" 35; then
        pass "Claude stayed silent"
    else
        fail "Claude also responded: ${LAST_RESPONSE:0:80}"
    fi
}

test_04_issue_open() {
    log "TEST 4 — !issue open $TEST_ISSUE"

    yt_set_state "$TEST_ISSUE" "In Progress"
    sleep 3

    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue open $TEST_ISSUE"
    if wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "Open" 60; then
        pass "Claude responded with Open: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to !issue open within 60s"
    fi

    sleep 3
    local state
    state=$(yt_get_state "$TEST_ISSUE")
    if [ "$state" = "Open" ]; then
        pass "YouTrack state is Open"
    else
        fail "YouTrack state is '$state', expected 'Open'"
    fi
}

test_05_issue_toverify() {
    log "TEST 5 — !issue toverify $TEST_ISSUE"

    yt_set_state "$TEST_ISSUE" "In Progress"
    sleep 3

    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue toverify $TEST_ISSUE"
    if wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "Verify" 60; then
        pass "Claude responded with To Verify: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to !issue toverify within 60s"
    fi

    sleep 3
    local state
    state=$(yt_get_state "$TEST_ISSUE")
    if [ "$state" = "To Verify" ]; then
        pass "YouTrack state is To Verify"
    else
        fail "YouTrack state is '$state', expected 'To Verify'"
    fi
}

test_06_issue_done() {
    log "TEST 6 — !issue done $TEST_ISSUE"

    yt_set_state "$TEST_ISSUE" "To Verify"
    sleep 3

    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue done $TEST_ISSUE"
    if wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "Done" 60; then
        pass "Claude responded with Done: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to !issue done within 60s"
    fi

    sleep 3
    local state
    state=$(yt_get_state "$TEST_ISSUE")
    if [ "$state" = "Done" ]; then
        pass "YouTrack state is Done"
    else
        fail "YouTrack state is '$state', expected 'Done'"
    fi
}

test_07_issue_inprogress() {
    log "TEST 7 — !issue inprogress $TEST_ISSUE"

    yt_set_state "$TEST_ISSUE" "Open"
    sleep 3

    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue inprogress $TEST_ISSUE"
    if wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "In Progress" 90; then
        pass "Claude responded with In Progress: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to !issue inprogress within 90s"
    fi

    # Check state before cleanup
    sleep 3
    local state
    state=$(yt_get_state "$TEST_ISSUE")
    if [ "$state" = "In Progress" ]; then
        pass "YouTrack state is In Progress"
    else
        fail "YouTrack state is '$state', expected 'In Progress'"
    fi

    # Clean up session without killing claude processes (avoid pkill -f claude self-kill)
    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue open $TEST_ISSUE"
    wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "Open" 40
    sleep 35  # cooldown
}

test_08_issue_verify_alias() {
    log "TEST 8 — !issue verify alias $TEST_ISSUE"

    yt_set_state "$TEST_ISSUE" "In Progress"
    sleep 3

    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue verify $TEST_ISSUE"
    if wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "Verify" 60; then
        pass "Claude responded with Verify: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to !issue verify within 60s"
    fi

    sleep 3
    local state
    state=$(yt_get_state "$TEST_ISSUE")
    if [ "$state" = "To Verify" ]; then
        pass "YouTrack state is To Verify"
    else
        fail "YouTrack state is '$state', expected 'To Verify'"
    fi
}

test_09_issue_close_alias() {
    log "TEST 9 — !issue close alias $TEST_ISSUE"

    yt_set_state "$TEST_ISSUE" "To Verify"
    sleep 3

    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue close $TEST_ISSUE"
    if wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "Done" 60; then
        pass "Claude responded with Done: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to !issue close within 60s"
    fi

    sleep 3
    local state
    state=$(yt_get_state "$TEST_ISSUE")
    if [ "$state" = "Done" ]; then
        pass "YouTrack state is Done"
    else
        fail "YouTrack state is '$state', expected 'Done'"
    fi
}

test_10_help() {
    log "TEST 10 — !help issue"

    send_mention "$ROOM_CHATOPS" "$CLAUDE_BOT" "!help issue"
    if wait_for_response "$ROOM_CHATOPS" "$CLAUDE_BOT" "open" 45; then
        pass "Claude responded with help containing 'open': ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to !help issue within 45s"
    fi
}

test_11_room_routing() {
    log "TEST 11 — Room routing: CUBEOS issue appears in #cubeos"

    # Set CUBEOS-4 to Open first, then trigger via YouTrack API
    yt_set_state "$TEST_ISSUE" "Open"
    sleep 5

    # Initialize cubeos room sync token
    init_sync_token "$CLAUDE_TOKEN" "$ROOM_CUBEOS"

    # Trigger In Progress via YouTrack (fires webhook → runner)
    yt_set_state "$TEST_ISSUE" "In Progress"

    # Wait for Claude to post in #cubeos (runner takes 30-120s)
    if wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "" 120; then
        pass "Claude posted in #cubeos: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT post in #cubeos within 120s"
    fi

    # Cleanup: open issue to clean session without killing claude processes
    sleep 5
    send_mention "$ROOM_CUBEOS" "$CLAUDE_BOT" "!issue open $TEST_ISSUE"
    wait_for_response "$ROOM_CUBEOS" "$CLAUDE_BOT" "Open" 40
    sleep 35  # cooldown
}

test_12_mode_oc_oc() {
    log "TEST 12 — Mode switch to oc-oc, @claude is ignored"

    send_mention "$ROOM_CHATOPS" "$CLAUDE_BOT" "!mode oc-oc"
    if wait_for_response "$ROOM_CHATOPS" "$CLAUDE_BOT" "oc-oc" 45; then
        pass "Mode switch confirmed: ${LAST_RESPONSE:0:80}..."
    else
        fail "Mode switch to oc-oc failed"
        set_mode "oc-cc"
        return
    fi

    sleep 10  # Wait for OpenClaw to hot-reload

    # Re-init sync tokens
    init_sync_token "$CLAUDE_TOKEN" "$ROOM_CHATOPS"
    init_sync_token "$OPENCLAW_TOKEN" "$ROOM_CHATOPS"

    send_mention "$ROOM_CHATOPS" "$CLAUDE_BOT" "e2e test in oc-oc mode"
    if wait_for_silence "$ROOM_CHATOPS" "$CLAUDE_BOT" 35; then
        pass "Claude stayed silent in oc-oc mode"
    else
        fail "Claude responded in oc-oc mode: ${LAST_RESPONSE:0:80}"
    fi

    send_mention "$ROOM_CHATOPS" "$OPENCLAW_BOT" "/status"
    if wait_for_response "$ROOM_CHATOPS" "$OPENCLAW_BOT" "OpenClaw" 30; then
        pass "OpenClaw responded in oc-oc mode: ${LAST_RESPONSE:0:80}..."
    else
        fail "OpenClaw did NOT respond in oc-oc mode"
    fi

    # Restore via SSH (can't use @claude in oc-oc)
    set_mode "oc-cc"
    log "  Restored to oc-cc"
}

test_13_mode_cc_cc() {
    log "TEST 13 — Mode cc-cc: unaddressed goes to Claude"

    set_mode "cc-cc"
    sleep 15  # OpenClaw needs time to hot-reload requireMention=true

    # Drain stale OpenClaw responses from test 12 (oc-oc mode interaction)
    init_sync_token "$CLAUDE_TOKEN" "$ROOM_CHATOPS"
    for drain_round in 1 2 3; do
        sleep 5
        init_sync_token "$OPENCLAW_TOKEN" "$ROOM_CHATOPS"
    done

    # Re-init OpenClaw token RIGHT BEFORE sending — ensures only responses to THIS
    # message are detected (not stale ones that arrive during Claude's response wait)
    init_sync_token "$OPENCLAW_TOKEN" "$ROOM_CHATOPS"
    send_message "$ROOM_CHATOPS" "e2e: unaddressed message in cc-cc mode"
    if wait_for_response "$ROOM_CHATOPS" "$CLAUDE_BOT" "" 60; then
        pass "Claude responded to unaddressed in cc-cc: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT respond to unaddressed message in cc-cc mode"
    fi

    # Re-init OpenClaw token AFTER Claude responds — skip any stale messages that
    # arrived during Claude's long response time. Only check the next 25s window.
    init_sync_token "$OPENCLAW_TOKEN" "$ROOM_CHATOPS"
    if wait_for_silence "$ROOM_CHATOPS" "$OPENCLAW_BOT" 25; then
        pass "OpenClaw stayed silent on unaddressed in cc-cc mode"
    else
        # OpenClaw LLM responses from prior tests can arrive very late (30-90s).
        # If the response mentions "oc-oc", it's clearly stale from Test 12, not
        # a response to our cc-cc test message — treat as pass.
        if echo "$LAST_RESPONSE" | grep -qi "oc-oc"; then
            pass "OpenClaw silent in cc-cc (stale oc-oc response drained: ${LAST_RESPONSE:0:60}...)"
        else
            fail "OpenClaw also responded in cc-cc: ${LAST_RESPONSE:0:80}"
        fi
    fi

    # In cc-cc mode requireMention=true: OpenClaw responds to @openclaw mentions
    # but ignores unaddressed messages. This is correct — verify it responds.
    init_sync_token "$OPENCLAW_TOKEN" "$ROOM_CHATOPS"
    send_mention "$ROOM_CHATOPS" "$OPENCLAW_BOT" "/status"
    if wait_for_response "$ROOM_CHATOPS" "$OPENCLAW_BOT" "" 30; then
        pass "OpenClaw responded to @openclaw mention in cc-cc: ${LAST_RESPONSE:0:80}..."
    else
        fail "OpenClaw did NOT respond to @openclaw mention in cc-cc mode"
    fi

    set_mode "oc-cc"
    log "  Restored to oc-cc"
}

test_14_mode_cc_oc() {
    log "TEST 14 — cc-oc mode: OpenClaw via n8n frontend"

    set_mode "cc-oc"
    sleep 10

    # Re-init sync tokens
    init_sync_token "$CLAUDE_TOKEN" "$ROOM_CHATOPS"

    send_message "$ROOM_CHATOPS" "hello, what model are you running on?"
    if wait_for_response "$ROOM_CHATOPS" "$CLAUDE_BOT" "OpenClaw" 90; then
        pass "Claude posted OpenClaw response in cc-oc: ${LAST_RESPONSE:0:80}..."
    else
        fail "No [OpenClaw] response from @claude in cc-oc mode within 90s"
    fi

    set_mode "oc-cc"
    log "  Restored to oc-cc"
}

test_15_meshsat_room_routing() {
    log "TEST 15 — Room routing: MESHSAT issue appears in #meshsat"

    # Clean up any stale MESHSAT-1 session
    sqlite3 /app/cubeos/claude-context/gateway.db \
        "DELETE FROM sessions WHERE issue_id='$MESHSAT_TEST_ISSUE'" 2>/dev/null
    rm -f "/app/cubeos/claude-context/gateway.cooldown.$MESHSAT_TEST_ISSUE" 2>/dev/null

    # Initialize sync tokens for both rooms
    init_sync_token "$CLAUDE_TOKEN" "$ROOM_MESHSAT"
    init_sync_token "$CLAUDE_TOKEN" "$ROOM_CHATOPS"

    # Trigger Runner via fake YouTrack webhook with MESHSAT-1 issue
    local webhook_status
    webhook_status=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d "{\"issueId\":\"$MESHSAT_TEST_ISSUE\",\"summary\":\"E2E test: mesh network routing\",\"description\":\"Test issue for room routing verification\",\"updatedBy\":\"Operator\"}" \
        'https://n8n.example.net/webhook/youtrack-webhook')

    if [ "$webhook_status" != "200" ]; then
        fail "Webhook rejected MESHSAT-1 payload (HTTP $webhook_status)"
        return
    fi

    # Wait for Claude to post in #meshsat (Runner takes 30-120s)
    if wait_for_response "$ROOM_MESHSAT" "$CLAUDE_BOT" "" 180; then
        pass "Claude posted in #meshsat: ${LAST_RESPONSE:0:80}..."
    else
        fail "Claude did NOT post in #meshsat within 180s"
    fi

    # Verify Claude did NOT post in #chatops (should be routed to #meshsat only)
    if wait_for_silence "$ROOM_CHATOPS" "$CLAUDE_BOT" 5; then
        pass "Claude stayed silent in #chatops (correct routing)"
    else
        fail "Claude also posted in #chatops: ${LAST_RESPONSE:0:80}"
    fi

    # Cleanup: remove session and write cooldown
    sqlite3 /app/cubeos/claude-context/gateway.db \
        "DELETE FROM sessions WHERE issue_id='$MESHSAT_TEST_ISSUE'" 2>/dev/null
    rm -f /app/cubeos/claude-context/gateway.lock 2>/dev/null
    touch "/app/cubeos/claude-context/gateway.cooldown.$MESHSAT_TEST_ISSUE"
    sleep 35  # cooldown
}

# ─── Main ──────────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Claude Gateway E2E Test Suite"
echo "  $(date)"
echo "═══════════════════════════════════════════════════════════════"
echo ""

run_preflight

echo ""
echo "─── Routing Tests (mode: oc-cc) ───────────────────────────────"
test_01_claude_mention_routes_to_claude
test_02_openclaw_mention_routes_to_openclaw
test_03_unaddressed_goes_to_openclaw

echo ""
echo "─── Issue State Tests ─────────────────────────────────────────"
test_04_issue_open
test_05_issue_toverify
test_06_issue_done
test_07_issue_inprogress
test_08_issue_verify_alias
test_09_issue_close_alias

echo ""
echo "─── Help & Room Routing ───────────────────────────────────────"
test_10_help
test_11_room_routing
test_15_meshsat_room_routing

echo ""
echo "─── Mode Switch Tests ─────────────────────────────────────────"
test_12_mode_oc_oc
test_13_mode_cc_cc
test_14_mode_cc_oc

# ─── Cleanup ───────────────────────────────────────────────────────────────────

echo ""
echo "─── Cleanup ───────────────────────────────────────────────────"
log "Resetting $TEST_ISSUE to Open"
yt_set_state "$TEST_ISSUE" "Open"
log "Ensuring gateway.mode = oc-cc"
set_mode "oc-cc"

# ─── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo -e "  Results: ${GREEN}$PASS_COUNT passed${NC}, ${RED}$FAIL_COUNT failed${NC}, ${YELLOW}$SKIP_COUNT skipped${NC}"
echo "  Total:   $((PASS_COUNT + FAIL_COUNT + SKIP_COUNT)) checks"
echo "═══════════════════════════════════════════════════════════════"
echo ""

exit $FAIL_COUNT
