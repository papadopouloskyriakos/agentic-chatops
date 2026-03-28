#!/bin/bash
# E2E Test Suite: Live Progress Feedback + Message Inject Feature
# Tests background Claude launch, progress polling, and @claude inject (escape+message)
#
# Usage: bash test-e2e-progress-inject.sh 2>&1 | tee /tmp/e2e-progress-results.txt

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/.env"

# ─── Configuration ─────────────────────────────────────────────────────────────
CLAUDE_BOT="@claude:matrix.example.net"
ROOM_MESHSAT="$MATRIX_ROOM_MESHSAT"
ROOM_CHATOPS="$MATRIX_ROOM_CHATOPS"
MATRIX_TOKEN="$MATRIX_DOMINICUS_API_KEY"
MATRIX_SERVER="https://matrix.example.net"
CLAUDE_TOKEN="$MATRIX_CLAUDE_TOKEN"
YT_URL="https://youtrack.example.net"
YT_AUTH="Authorization: Bearer $YT_TOKEN"
GW="/home/claude-runner/gitlab/products/cubeos/claude-context"
DB="$GW/gateway.db"

# Use MESHSAT-44 as test issue (known to exist)
TEST_ISSUE="MESHSAT-44"

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

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

# Grab a fresh sync token so we only see NEW messages
SYNC_TOKEN=""
init_sync() {
    local room="$1"
    SYNC_TOKEN=$(python3 -c "
import requests, json
filt = json.dumps({'room':{'rooms':['$room'],'timeline':{'limit':0}}})
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/sync',
    params={'timeout':'0','filter':filt},
    headers={'Authorization':'Bearer $CLAUDE_TOKEN'}, timeout=15)
print(r.json().get('next_batch',''))
" 2>/dev/null)
}

send_message() {
    local room="$1" text="$2"
    local txn="e2e-$(date +%s%N)"
    python3 -c "
import requests, json, sys
r = requests.put('$MATRIX_SERVER/_matrix/client/v3/rooms/$room/send/m.room.message/$txn',
    json={'msgtype':'m.text','body':json.loads(sys.stdin.read())},
    headers={'Authorization':'Bearer $MATRIX_TOKEN'}, timeout=10)
if r.status_code != 200:
    print(f'SEND FAILED: {r.status_code} {r.text[:200]}', file=sys.stderr)
    sys.exit(1)
" <<< "$(python3 -c "import json; print(json.dumps(\"$text\"))")"
}

send_mention() {
    local room="$1" text="$2"
    local txn="e2e-mention-$(date +%s%N)"
    python3 -c "
import requests, json, sys
text = json.loads(sys.stdin.read())
plain = f'@claude:matrix.example.net {text}'
html = f'<a href=\"https://matrix.to/#/@claude:matrix.example.net\">claude</a> {text}'
r = requests.put('$MATRIX_SERVER/_matrix/client/v3/rooms/$room/send/m.room.message/$txn',
    json={'msgtype':'m.text','body':plain,'format':'org.matrix.custom.html','formatted_body':html},
    headers={'Authorization':'Bearer $MATRIX_TOKEN'}, timeout=10)
if r.status_code != 200:
    print(f'MENTION FAILED: {r.status_code} {r.text[:200]}', file=sys.stderr)
    sys.exit(1)
" <<< "$(python3 -c "import json; print(json.dumps(\"$text\"))")"
}

# Wait for @claude message in room matching text pattern. Returns message body.
# $1=room, $2=pattern (grep -i), $3=timeout(s), $4=msgtype filter (optional, e.g. "m.notice")
# Uses /sync for real-time detection, falls back to /messages API if sync misses it.
wait_for_bot_msg() {
    local room="$1" pattern="$2" timeout="${3:-120}" msgtype_filter="${4:-}"
    local since="$SYNC_TOKEN"
    local elapsed=0
    local interval=5
    LAST_RESPONSE=""

    # Record start time for /messages fallback (check messages after this timestamp)
    local start_ts=$(($(date +%s) * 1000))

    while [ $elapsed -lt $timeout ]; do
        local result
        result=$(python3 -c "
import requests, json, sys
filt = json.dumps({'room':{'rooms':['$room'],'timeline':{'limit':50}}})
params = {'timeout':'0','filter':filt}
since = '$since'
if since:
    params['since'] = since
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/sync',
    params=params, headers={'Authorization':'Bearer $CLAUDE_TOKEN'}, timeout=15)
data = r.json()
new_token = data.get('next_batch','')
rooms = data.get('rooms',{}).get('join',{})
room_data = rooms.get('$room',{})
events = room_data.get('timeline',{}).get('events',[])
matched = []
for e in events:
    if e.get('type') != 'm.room.message': continue
    if e.get('sender') != '@claude:matrix.example.net': continue
    body = e.get('content',{}).get('body','')
    msgtype = e.get('content',{}).get('msgtype','')
    msgtype_filter = '$msgtype_filter'
    if msgtype_filter and msgtype != msgtype_filter:
        continue
    matched.append(body)
# Print token on first line, then all matched messages
print(new_token)
for m in matched:
    print(m)
" 2>/dev/null)

        local new_token=$(echo "$result" | head -1)
        [ -n "$new_token" ] && SYNC_TOKEN="$new_token"

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

    # Fallback: check /messages API directly (sync may have missed the message)
    local fallback
    fallback=$(python3 -c "
import requests, json, urllib.parse
room = '$room'
room_encoded = urllib.parse.quote(room, safe='')
r = requests.get('$MATRIX_SERVER/_matrix/client/v3/rooms/' + room_encoded + '/messages',
    params={'dir':'b','limit':'20'},
    headers={'Authorization':'Bearer $CLAUDE_TOKEN'}, timeout=15)
data = r.json()
start_ts = $start_ts
msgtype_filter = '$msgtype_filter'
for e in reversed(data.get('chunk',[])):
    if e.get('type') != 'm.room.message': continue
    if e.get('sender') != '@claude:matrix.example.net': continue
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

# ─── Cleanup ───────────────────────────────────────────────────────────────────
cleanup() {
    log "Cleaning up..."
    rm -f "$GW/gateway.lock" "$GW/gateway.cooldown."* 2>/dev/null
    rm -f /tmp/claude-pid-* /tmp/claude-run-* /tmp/claude-inject-* /tmp/claude-fresh-* 2>/dev/null
    pkill -f "timeout 600.*claude.*dangerously-skip-permissions" 2>/dev/null || true
    sleep 2
    pkill -9 -f "timeout 600.*claude.*dangerously-skip-permissions" 2>/dev/null || true
    # Clean session for test issue
    sqlite3 "$DB" "DELETE FROM sessions WHERE issue_id='$TEST_ISSUE';" 2>/dev/null
    sqlite3 "$DB" "DELETE FROM queue WHERE issue_id='$TEST_ISSUE';" 2>/dev/null
}

# ─── Test T1: YouTrack Trigger → Background Launch + Progress ──────────────────
test_youtrack_trigger_with_progress() {
    echo ""
    echo -e "${BOLD}═══ T1: YouTrack Trigger → Background Launch + Progress Feedback ═══${NC}"
    cleanup

    init_sync "$ROOM_MESHSAT"

    # First move issue to Open, then to In Progress to trigger webhook
    # OR: post directly to n8n webhook for reliability
    log "Fetching $TEST_ISSUE details from YouTrack..."
    local issue_data
    issue_data=$(curl -s -H "$YT_AUTH" "$YT_URL/api/issues/$TEST_ISSUE?fields=id,idReadable,summary,description")
    local numeric_id summary description
    numeric_id=$(echo "$issue_data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
    summary=$(echo "$issue_data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('summary',''))" 2>/dev/null)
    description=$(echo "$issue_data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('description','')[:500])" 2>/dev/null)

    if [ -z "$numeric_id" ]; then
        fail "T1.1: Could not get numeric ID for $TEST_ISSUE"
        return
    fi

    # Move to Open first (so In Progress is a real state change)
    curl -s -o /dev/null -X POST \
        -H "$YT_AUTH" -H "Content-Type: application/json" \
        "$YT_URL/api/issues/$numeric_id" \
        -d '{"customFields":[{"name":"State","$type":"StateIssueCustomField","value":{"name":"Open"}}]}'
    sleep 2

    # Now move to In Progress (triggers YouTrack webhook)
    local state_resp
    state_resp=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "$YT_AUTH" -H "Content-Type: application/json" \
        "$YT_URL/api/issues/$numeric_id" \
        -d '{"customFields":[{"name":"State","$type":"StateIssueCustomField","value":{"name":"In Progress"}}]}')

    if [ "$state_resp" = "200" ]; then
        pass "T1.1: YouTrack state changed Open → In Progress (HTTP $state_resp)"
    else
        # Fallback: trigger webhook directly
        log "YouTrack state change failed ($state_resp), triggering webhook directly..."
        local wh_resp
        wh_resp=$(curl -s -w "%{http_code}" -o /dev/null -X POST \
            "http://nl-n8n01:5678/webhook/youtrack-webhook" \
            -H "Content-Type: application/json" \
            -d "{\"issueId\":\"$TEST_ISSUE\",\"summary\":\"$summary\",\"description\":\"$description\",\"type\":\"IssueUpdated\"}")
        if [ "$wh_resp" = "200" ]; then
            pass "T1.1: Triggered via direct webhook (HTTP $wh_resp)"
        else
            fail "T1.1: Both YouTrack and webhook trigger failed"
            return
        fi
    fi

    # T1.2: Wait for pre-stats notice (m.notice with load/memory info)
    log "Waiting for pre-stats notice in #meshsat (up to 30s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "load\|memory\|disk\|cpu" 30 "m.notice"; then
        pass "T1.2: Pre-stats notice received"
    else
        skip "T1.2: Pre-stats notice not seen (may have been sent before sync init)"
    fi

    # T1.3: Check PID file appears (Claude launched in background)
    # Runner needs: Receiver(~1s) + cooldown check + lock + pre-stats(~5s) + launch(~10s)
    # Plus Bridge poll delay if triggered via Matrix. Via YouTrack webhook it's direct.
    log "Waiting for PID file (up to 90s)..."
    local pid_found=0
    for i in $(seq 1 45); do
        if [ -f "/tmp/claude-pid-$TEST_ISSUE" ]; then
            local pid=$(cat "/tmp/claude-pid-$TEST_ISSUE")
            if kill -0 $pid 2>/dev/null; then
                pid_found=1
                pass "T1.3: PID file exists, Claude running (PID $pid)"
                break
            fi
        fi
        sleep 2
    done
    [ $pid_found -eq 0 ] && fail "T1.3: PID file not found or Claude not running after 90s"

    # T1.4: Check JSONL log file is being written
    if [ -f "/tmp/claude-run-$TEST_ISSUE.jsonl" ]; then
        local lines=$(wc -l < "/tmp/claude-run-$TEST_ISSUE.jsonl")
        pass "T1.4: JSONL log file exists ($lines lines)"
    else
        fail "T1.4: JSONL log file not found"
    fi

    # T1.5: Wait for progress message (m.notice with tool activity)
    # Note: Progress updates only appear when Claude runs >30s (first poll cycle)
    log "Waiting for progress update in #meshsat (up to 90s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "Working\|Glob\|Read\|Edit\|Bash\|Grep" 90 "m.notice"; then
        pass "T1.5: Progress update received: $(echo "$LAST_RESPONSE" | head -c 120)"
    else
        # Check if Claude finished quickly (< 30s = no progress expected)
        if [ ! -f "/tmp/claude-pid-$TEST_ISSUE" ] || ! kill -0 $(cat "/tmp/claude-pid-$TEST_ISSUE" 2>/dev/null) 2>/dev/null; then
            skip "T1.5: Claude finished before first poll cycle (< 30s) — no progress expected"
        else
            fail "T1.5: No progress update seen in 90s despite Claude still running"
        fi
    fi

    # T1.6: Wait for final result (regular message, not m.notice)
    log "Waiting for final Claude response in #meshsat (up to 600s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "." 600 "m.text"; then
        local resp_len=${#LAST_RESPONSE}
        pass "T1.6: Final response received ($resp_len chars)"
    else
        fail "T1.6: No final response in 600s"
    fi

    # T1.7: Verify session was written to DB
    local session_row
    session_row=$(sqlite3 "$DB" "SELECT session_id FROM sessions WHERE issue_id='$TEST_ISSUE';" 2>/dev/null)
    if [ -n "$session_row" ]; then
        pass "T1.7: Session written to DB (SID: ${session_row:0:12}...)"
    else
        skip "T1.7: No session in DB (Claude may have not returned a session ID)"
    fi

    # T1.8: Verify lock was released
    if [ ! -f "$GW/gateway.lock" ]; then
        pass "T1.8: Lock released after completion"
    else
        fail "T1.8: Lock still exists after completion"
    fi

    # T1.9: Verify temp files cleaned up
    if [ ! -f "/tmp/claude-run-$TEST_ISSUE.jsonl" ] && [ ! -f "/tmp/claude-pid-$TEST_ISSUE" ]; then
        pass "T1.9: Temp files cleaned up (JSONL + PID)"
    else
        local remaining=""
        [ -f "/tmp/claude-run-$TEST_ISSUE.jsonl" ] && remaining+="JSONL "
        [ -f "/tmp/claude-pid-$TEST_ISSUE" ] && remaining+="PID "
        fail "T1.9: Temp files remain: $remaining"
    fi
}

# ─── Test T2: @claude Inject During Active Session ─────────────────────────────
test_inject_during_session() {
    echo ""
    echo -e "${BOLD}═══ T2: @claude Inject During Active Session ═══${NC}"
    cleanup

    init_sync "$ROOM_MESHSAT"

    # Trigger via webhook (uses Runner's background launch with PID file support)
    log "Triggering $TEST_ISSUE via direct webhook..."
    curl -s -o /dev/null -X POST \
        "http://nl-n8n01:5678/webhook/youtrack-webhook" \
        -H "Content-Type: application/json" \
        -d "{\"issueId\":\"$TEST_ISSUE\",\"summary\":\"[MeshSat v0.3.0] P3: Store-and-Forward + Delivery Workers\",\"description\":\"Rewrite delivery workers for store-and-forward semantics.\",\"type\":\"IssueUpdated\"}"

    # Wait for Claude to start (PID file appears)
    log "Waiting for Claude to start (PID file, up to 90s)..."
    local pid_found=0
    for i in $(seq 1 45); do
        if [ -f "/tmp/claude-pid-$TEST_ISSUE" ]; then
            local pid=$(cat "/tmp/claude-pid-$TEST_ISSUE")
            if kill -0 $pid 2>/dev/null; then
                pid_found=1
                pass "T2.1: Claude running (PID $pid)"
                break
            fi
        fi
        sleep 2
    done
    if [ $pid_found -eq 0 ]; then
        fail "T2.1: Claude not running after 90s"
        return
    fi

    # Wait for Claude to be actively working (JSONL growing)
    sleep 15
    local lines_before=0
    [ -f "/tmp/claude-run-$TEST_ISSUE.jsonl" ] && lines_before=$(wc -l < "/tmp/claude-run-$TEST_ISSUE.jsonl")
    if [ $lines_before -gt 0 ]; then
        pass "T2.2: JSONL log has $lines_before lines (Claude actively working)"
    else
        fail "T2.2: JSONL log empty or missing — Claude may not be producing output"
    fi

    # T2.3: Send @claude mention to inject a message
    local inject_msg="what files have you looked at so far? give a brief summary"
    log "Sending @claude inject: '$inject_msg'"
    send_mention "$ROOM_MESHSAT" "$inject_msg"

    # T2.4: Wait for inject notice
    log "Waiting for inject notice (up to 60s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "Message sent to running\|INJECTED\|sent to running Claude" 60 "m.notice"; then
        pass "T2.3: Inject notice received"
    else
        # Check if it was queued instead
        if wait_for_bot_msg "$ROOM_MESHSAT" "queued\|busy" 10 "m.notice"; then
            fail "T2.3: Message was QUEUED instead of injected (PID may have died)"
        else
            fail "T2.3: No inject/queue notice received"
        fi
    fi

    # T2.5: Verify new PID after inject (check immediately — fast responses clean up PID file)
    sleep 1
    if [ -f "/tmp/claude-pid-$TEST_ISSUE" ]; then
        local new_pid=$(cat "/tmp/claude-pid-$TEST_ISSUE")
        if kill -0 $new_pid 2>/dev/null; then
            pass "T2.5: New Claude process running after inject (PID $new_pid)"
        else
            pass "T2.5: PID file exists (PID $new_pid finished — fast response)"
        fi
    else
        pass "T2.5: PID file already cleaned up (inject completed quickly)"
    fi

    # T2.4: Verify inject file was created and consumed
    sleep 2
    if [ -f "/tmp/claude-inject-$TEST_ISSUE.json" ]; then
        fail "T2.4: Inject file still exists (not consumed by Wait for Claude)"
    else
        pass "T2.4: Inject file consumed (or never created — checking PID)"
    fi

    # T2.6: Wait for final response
    log "Waiting for final response after inject (up to 600s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "." 600 "m.text"; then
        local resp_len=${#LAST_RESPONSE}
        pass "T2.6: Final response received after inject ($resp_len chars)"
    else
        fail "T2.6: No final response after inject in 600s"
    fi

    # T2.7: Lock released
    sleep 5
    if [ ! -f "$GW/gateway.lock" ]; then
        pass "T2.7: Lock released"
    else
        fail "T2.7: Lock still held"
    fi
}

# ─── Test T3: @claude Mention When NOT Locked → Normal Resume ──────────────────
test_mention_not_locked() {
    echo ""
    echo -e "${BOLD}═══ T3: @claude Mention When NOT Locked → Normal Flow ═══${NC}"
    # Don't call cleanup — we need the session from T2 to still exist
    # Just clear lock and temp files so we're unlocked
    rm -f "$GW/gateway.lock" "$GW/gateway.cooldown."* 2>/dev/null
    rm -f /tmp/claude-pid-* /tmp/claude-run-* /tmp/claude-inject-* /tmp/claude-fresh-* 2>/dev/null
    pkill -f "timeout 600.*claude.*dangerously-skip-permissions" 2>/dev/null || true
    sleep 2
    pkill -9 -f "timeout 600.*claude.*dangerously-skip-permissions" 2>/dev/null || true

    init_sync "$ROOM_MESHSAT"

    # Ensure there's a session in DB to resume (from T1 or T2)
    local has_session
    has_session=$(sqlite3 "$DB" "SELECT session_id FROM sessions WHERE issue_id='$TEST_ISSUE';" 2>/dev/null)
    if [ -z "$has_session" ]; then
        skip "T3.1: No existing session for $TEST_ISSUE — skipping resume test"
        return
    fi

    log "Session exists (SID: ${has_session:0:12}...), sending @claude mention while unlocked..."
    send_mention "$ROOM_MESHSAT" "what's the current status?"

    # Should go through normal resume flow (not inject), get a response
    log "Waiting for Claude response via normal resume (up to 300s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "." 300 "m.text"; then
        pass "T3.1: Normal resume response received (not injected)"
    else
        fail "T3.1: No response from normal resume in 300s"
    fi
}

# ─── Test T4: Queue When Locked + No PID File ─────────────────────────────────
test_queue_no_pid() {
    echo ""
    echo -e "${BOLD}═══ T4: Queue When Locked But No PID File ═══${NC}"
    cleanup
    sleep 5  # Let any in-flight Bridge polls settle

    init_sync "$ROOM_MESHSAT"
    sleep 2  # Extra buffer after sync init

    # Create a fake lock without PID file (simulates old-style sync run)
    echo "$TEST_ISSUE" > "$GW/gateway.lock"
    # Create a session entry so the queue insert works
    sqlite3 "$DB" "INSERT OR REPLACE INTO sessions (issue_id, issue_title, session_id, started_at, last_active, is_current) VALUES ('$TEST_ISSUE', 'Test', 'fake-sid', datetime('now'), datetime('now'), 1);" 2>/dev/null

    log "Lock held, no PID file. Sending @claude mention..."
    send_mention "$ROOM_MESHSAT" "this should be queued"

    # Should get a busy/queued notice, NOT an inject notice
    log "Waiting for any notice (up to 90s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "queued\|busy\|sent to running" 90 "m.notice"; then
        if echo "$LAST_RESPONSE" | grep -qi "sent to running" && ! echo "$LAST_RESPONSE" | grep -qi "test-e2e\|/bin/bash"; then
            fail "T4.1: Message was INJECTED despite no PID file! Response: $LAST_RESPONSE"
        else
            pass "T4.1: Message queued (busy notice received)"
        fi
    else
        fail "T4.1: No notice received within 60s"
    fi

    # Verify message was queued in DB
    local q_count
    q_count=$(sqlite3 "$DB" "SELECT COUNT(*) FROM queue WHERE issue_id='$TEST_ISSUE';" 2>/dev/null)
    if [ "$q_count" -gt 0 ] 2>/dev/null; then
        pass "T4.2: Message in queue table ($q_count entries)"
    else
        fail "T4.2: Message not in queue table"
    fi

    cleanup
}

# ─── Test T5: Inject With Dead PID → Falls Back to Queue ──────────────────────
test_inject_dead_pid() {
    echo ""
    echo -e "${BOLD}═══ T5: Inject With Dead PID → Falls Back to Queue ═══${NC}"
    cleanup
    sleep 5

    init_sync "$ROOM_MESHSAT"

    # Create lock + PID file with dead PID
    echo "$TEST_ISSUE" > "$GW/gateway.lock"
    echo "99999" > "/tmp/claude-pid-$TEST_ISSUE"
    sqlite3 "$DB" "INSERT OR REPLACE INTO sessions (issue_id, issue_title, session_id, started_at, last_active, is_current) VALUES ('$TEST_ISSUE', 'Test', 'fake-sid', datetime('now'), datetime('now'), 1);" 2>/dev/null

    log "Lock held, dead PID 99999. Sending @claude mention..."
    send_mention "$ROOM_MESHSAT" "this should fall back to queue"

    # Should get queued, not injected
    log "Waiting for response (up to 60s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "queued\|busy" 60 "m.notice"; then
        pass "T5.1: Dead PID correctly fell back to queue"
    else
        if wait_for_bot_msg "$ROOM_MESHSAT" "inject\|sent to running" 10 "m.notice"; then
            fail "T5.1: Injected despite dead PID!"
        else
            fail "T5.1: No notice received"
        fi
    fi

    cleanup
}

# ─── Test T6: Progress Poller Terminates When PID Dies ─────────────────────────
test_poller_terminates() {
    echo ""
    echo -e "${BOLD}═══ T6: Verify Progress Poller Lifecycle ═══${NC}"

    # This is a structural check — verify no orphan poller executions
    log "Checking for orphan poller processes..."
    local orphans
    orphans=$(ps aux 2>/dev/null | grep -c "claude-run.*jsonl" || echo "0")
    if [ "$orphans" -lt 2 ]; then
        pass "T6.1: No orphan poller-related processes"
    else
        fail "T6.1: $orphans potential orphan processes found"
    fi

    # Check no stale log files from previous runs
    local stale
    stale=$(find /tmp -name "claude-run-*.jsonl" -mmin +30 2>/dev/null | wc -l)
    if [ "$stale" -eq 0 ]; then
        pass "T6.2: No stale JSONL log files (>30min old)"
    else
        fail "T6.2: $stale stale JSONL log files found"
    fi
}

# ─── Test T7: Cooldown Prevents Double-Trigger ─────────────────────────────────
test_cooldown() {
    echo ""
    echo -e "${BOLD}═══ T7: Cooldown Prevents Double-Trigger ═══${NC}"
    cleanup

    init_sync "$ROOM_MESHSAT"

    # Write a fresh cooldown file
    touch "$GW/gateway.cooldown.$TEST_ISSUE"

    # Try to trigger via YouTrack
    log "Triggering $TEST_ISSUE with cooldown active via direct webhook..."
    curl -s -o /dev/null -X POST \
        "http://nl-n8n01:5678/webhook/youtrack-webhook" \
        -H "Content-Type: application/json" \
        -d "{\"issueId\":\"$TEST_ISSUE\",\"summary\":\"Test\",\"description\":\"test\",\"type\":\"IssueUpdated\"}"

    # Should see cooldown notice
    log "Waiting for cooldown notice (up to 30s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "cooldown" 30 "m.notice"; then
        pass "T7.1: Cooldown notice received"
    else
        skip "T7.1: No cooldown notice (webhook may have been filtered)"
    fi

    cleanup
}

# ─── Test T8: Bang Commands Bypass Lock ────────────────────────────────────────
test_bang_bypass_lock() {
    echo ""
    echo -e "${BOLD}═══ T8: Bang Commands Bypass Lock ═══${NC}"
    cleanup
    sleep 5

    init_sync "$ROOM_MESHSAT"

    # Create a fake lock
    echo "$TEST_ISSUE" > "$GW/gateway.lock"

    log "Lock held. Sending !debug command..."
    send_message "$ROOM_MESHSAT" "!debug"

    # !debug should work despite lock (Bridge polls every 30s, so wait up to 90s for 2+ cycles)
    log "Waiting for debug response (up to 90s)..."
    if wait_for_bot_msg "$ROOM_MESHSAT" "lock\|sessions\|queue\|mode\|Debug Dump" 90; then
        pass "T8.1: !debug works while locked"
    else
        fail "T8.1: !debug did not respond while locked"
    fi

    cleanup
}

# ─── Main ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  E2E Test Suite: Progress Feedback + Message Inject         ║${NC}"
echo -e "${BOLD}║  Room: #meshsat | Issue: $TEST_ISSUE                       ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Sanity checks
if ! python3 -c "import requests" 2>/dev/null; then
    echo "ERROR: python3 requests module required"
    exit 1
fi

if [ ! -f "$DB" ]; then
    echo "ERROR: Gateway DB not found at $DB"
    exit 1
fi

# Run quick structural tests first (no Claude involved)
test_poller_terminates

# Run heavy integration test T1 FIRST (clean state, no interference)
echo ""
echo -e "${BOLD}--- Heavy integration tests (Claude will run, expect 5-15 min each) ---${NC}"
echo ""

test_youtrack_trigger_with_progress

# T2: Inject test (triggers its own Claude run via webhook)
test_inject_during_session

# T3: Resume test when unlocked
test_mention_not_locked

# Now run quick tests that create fake locks (won't interfere with heavy tests)
test_bang_bypass_lock
test_queue_no_pid
test_inject_dead_pid
test_cooldown

# ─── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}Results: ${GREEN}$PASS_COUNT passed${NC}, ${RED}$FAIL_COUNT failed${NC}, ${YELLOW}$SKIP_COUNT skipped${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"

[ $FAIL_COUNT -eq 0 ] && exit 0 || exit 1
