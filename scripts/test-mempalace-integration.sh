#!/bin/bash
# test-mempalace-integration.sh — E2E validation of MemPalace integration
# Tests: schema, transcript archival, temporal validity, agent diary, hooks, RRF, regression
set -euo pipefail

DB="/app/cubeos/claude-context/gateway.db"
SCRIPTS="/app/claude-gateway/scripts"
SETTINGS="/app/claude-gateway/.claude/settings.json"
PASS=0
FAIL=0
WARN=0

result() {
  local status="$1" test_name="$2" detail="${3:-}"
  if [ "$status" = "PASS" ]; then
    echo "  [PASS] $test_name"
    PASS=$((PASS + 1))
  elif [ "$status" = "WARN" ]; then
    echo "  [WARN] $test_name — $detail"
    WARN=$((WARN + 1))
  else
    echo "  [FAIL] $test_name — $detail"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== MemPalace Integration Test Suite ==="
echo "Date: $(date -u '+%Y-%m-%d %H:%M UTC')"
echo

# --- 1. Schema Tests ---
echo "--- 1. Schema Tests ---"

COL_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('session_transcripts');")
[ "$COL_COUNT" -ge 9 ] && result "PASS" "session_transcripts table exists ($COL_COUNT cols)" || result "FAIL" "session_transcripts table" "expected 9 cols, got $COL_COUNT"

COL_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('agent_diary');")
[ "$COL_COUNT" -ge 7 ] && result "PASS" "agent_diary table exists ($COL_COUNT cols)" || result "FAIL" "agent_diary table" "expected 7 cols, got $COL_COUNT"

HAS_VALID=$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('incident_knowledge') WHERE name='valid_until';")
[ "$HAS_VALID" -eq 1 ] && result "PASS" "incident_knowledge.valid_until column exists" || result "FAIL" "valid_until column" "not found"

# --- 2. Transcript Archival Test ---
echo
echo "--- 2. Transcript Archival Test ---"

# Create synthetic JSONL
TEST_ISSUE="TEST-MEMPAL-001"
TEST_JSONL="/tmp/claude-run-${TEST_ISSUE}.jsonl"
cat > "$TEST_JSONL" << 'JSONL'
{"type":"message","message":{"role":"user","content":"What is the disk usage on nl-pve01?"}}
{"type":"message","message":{"role":"assistant","content":"Let me check the disk usage on nl-pve01 using Proxmox MCP.\n\nThe root filesystem is at 72% usage (45GB of 62GB). The ZFS pool is at 58% (2.1TB of 3.6TB). No immediate action needed."}}
{"type":"message","message":{"role":"user","content":"What about nl-pve03?"}}
{"type":"message","message":{"role":"assistant","content":"nl-pve03 root filesystem is at 81% (50GB of 62GB). This is approaching the 85% warning threshold. Recommend clearing old kernel packages with apt autoremove."}}
{"type":"result","result":"Disk check complete. nl-pve01 OK, nl-pve03 needs attention at 81%.","cost_usd":0.05}
JSONL

# Clean up any previous test data
sqlite3 "$DB" "DELETE FROM session_transcripts WHERE issue_id='$TEST_ISSUE';"

# Run archival (without embedding to avoid Ollama dependency in tests)
python3 "$SCRIPTS/archive-session-transcript.py" "$TEST_ISSUE" 2>/dev/null
CHUNK_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_transcripts WHERE issue_id='$TEST_ISSUE';")
[ "$CHUNK_COUNT" -ge 2 ] && result "PASS" "Transcript archived ($CHUNK_COUNT chunks)" || result "FAIL" "Transcript archival" "expected >=2 chunks, got $CHUNK_COUNT"

# Verify content was stored
HAS_CONTENT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_transcripts WHERE issue_id='$TEST_ISSUE' AND content LIKE '%nl-pve01%';")
[ "$HAS_CONTENT" -ge 1 ] && result "PASS" "Transcript content searchable (hostname found)" || result "FAIL" "Content search" "hostname not found in chunks"

# Verify idempotency
python3 "$SCRIPTS/archive-session-transcript.py" "$TEST_ISSUE" 2>/dev/null
CHUNK_COUNT2=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_transcripts WHERE issue_id='$TEST_ISSUE';")
[ "$CHUNK_COUNT2" -eq "$CHUNK_COUNT" ] && result "PASS" "Idempotent (re-run same count: $CHUNK_COUNT2)" || result "FAIL" "Idempotency" "count changed from $CHUNK_COUNT to $CHUNK_COUNT2"

# --- 3. Temporal Validity Test ---
echo
echo "--- 3. Temporal Validity Test ---"

# Insert test entry
sqlite3 "$DB" "INSERT INTO incident_knowledge (alert_rule, hostname, site, resolution, confidence, issue_id, embedding) VALUES ('TestAlert', 'test-host01', 'nl', 'Old resolution', 0.8, 'TEST-TEMP-001', '');"
OLD_ID=$(sqlite3 "$DB" "SELECT id FROM incident_knowledge WHERE issue_id='TEST-TEMP-001' ORDER BY id DESC LIMIT 1;")

# Invalidate it
python3 "$SCRIPTS/kb-semantic-search.py" invalidate "test-host01" "TestAlert" 2>/dev/null
HAS_VALID_UNTIL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge WHERE id=$OLD_ID AND valid_until IS NOT NULL;")
[ "$HAS_VALID_UNTIL" -eq 1 ] && result "PASS" "Invalidation sets valid_until" || result "FAIL" "Invalidation" "valid_until not set"

# Insert newer entry (should remain valid)
sqlite3 "$DB" "INSERT INTO incident_knowledge (alert_rule, hostname, site, resolution, confidence, issue_id, embedding) VALUES ('TestAlert', 'test-host01', 'nl', 'New resolution', 0.9, 'TEST-TEMP-002', '');"

# Check that only new entry is returned (valid_until filter)
VALID_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge WHERE hostname='test-host01' AND alert_rule='TestAlert' AND (valid_until IS NULL OR valid_until > datetime('now'));")
[ "$VALID_COUNT" -eq 1 ] && result "PASS" "Temporal filter: only current entry visible ($VALID_COUNT)" || result "FAIL" "Temporal filter" "expected 1 valid, got $VALID_COUNT"

# --- 4. Agent Diary Test ---
echo
echo "--- 4. Agent Diary Test ---"

python3 "$SCRIPTS/agent-diary.py" write triage-researcher "nl-pve01 disk at 72%, ZFS healthy" --issue TEST-DIARY-001 --tags "disk,storage" 2>/dev/null
DIARY_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM agent_diary WHERE agent_name='triage-researcher';")
[ "$DIARY_COUNT" -ge 1 ] && result "PASS" "Agent diary write ($DIARY_COUNT entries)" || result "FAIL" "Diary write" "no entries found"

python3 "$SCRIPTS/agent-diary.py" write cisco-asa-specialist "VTI Tunnel1 UP, latency 12ms to GR" --issue TEST-DIARY-002 --tags "vpn,tunnel" 2>/dev/null
DIARY_TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM agent_diary;")
[ "$DIARY_TOTAL" -ge 2 ] && result "PASS" "Multiple agents write ($DIARY_TOTAL total)" || result "FAIL" "Multi-agent" "expected >=2, got $DIARY_TOTAL"

# Read back
INJECT=$(python3 "$SCRIPTS/agent-diary.py" inject triage-researcher --last 3 2>/dev/null)
echo "$INJECT" | grep -q "agent_diary" && result "PASS" "Diary inject produces XML tags" || result "FAIL" "Diary inject" "missing XML tags"

# --- 5. Hook Tests ---
echo
echo "--- 5. Hook Tests ---"

[ -x "$SCRIPTS/hooks/mempal-session-save.sh" ] && result "PASS" "Stop hook executable" || result "FAIL" "Stop hook" "not executable"
[ -x "$SCRIPTS/hooks/mempal-precompact.sh" ] && result "PASS" "PreCompact hook executable" || result "FAIL" "PreCompact hook" "not executable"

python3 -c "
import json
s = json.load(open('$SETTINGS'))
hooks = s.get('hooks', {})
has_stop = 'Stop' in hooks and len(hooks['Stop']) > 0
has_precompact = 'PreCompact' in hooks and len(hooks['PreCompact']) > 0
print('stop:' + str(has_stop) + ',precompact:' + str(has_precompact))
" 2>/dev/null | grep -q "stop:True,precompact:True" && result "PASS" "Hooks registered in settings.json" || result "FAIL" "Hook registration" "missing from settings.json"

# Test stop hook (simulate below-threshold)
echo '{"session_id":"test-123","stop_hook_active":false}' | "$SCRIPTS/hooks/mempal-session-save.sh" 2>/dev/null | grep -q '{}' && result "PASS" "Stop hook allows exit (no transcript)" || result "WARN" "Stop hook" "unexpected output"

# --- 6. Script Syntax ---
echo
echo "--- 6. Script Syntax ---"

bash -n "$SCRIPTS/hooks/mempal-session-save.sh" 2>/dev/null && result "PASS" "mempal-session-save.sh syntax" || result "FAIL" "Save hook syntax" "bash -n failed"
bash -n "$SCRIPTS/hooks/mempal-precompact.sh" 2>/dev/null && result "PASS" "mempal-precompact.sh syntax" || result "FAIL" "PreCompact hook syntax" "bash -n failed"
python3 -c "import py_compile; py_compile.compile('$SCRIPTS/archive-session-transcript.py', doraise=True)" 2>/dev/null && result "PASS" "archive-session-transcript.py syntax" || result "FAIL" "Archive script syntax" "compile failed"
python3 -c "import py_compile; py_compile.compile('$SCRIPTS/agent-diary.py', doraise=True)" 2>/dev/null && result "PASS" "agent-diary.py syntax" || result "FAIL" "Diary script syntax" "compile failed"
python3 -c "import py_compile; py_compile.compile('$SCRIPTS/kb-semantic-search.py', doraise=True)" 2>/dev/null && result "PASS" "kb-semantic-search.py syntax (with modifications)" || result "FAIL" "KB search syntax" "compile failed"

# --- 7. Regression Test ---
echo
echo "--- 7. Regression Test ---"

# Verify existing search still works (keyword mode, no Ollama dependency)
python3 "$SCRIPTS/kb-semantic-search.py" search "test query" --mode keyword --limit 1 2>/dev/null
SEARCH_EXIT=$?
[ $SEARCH_EXIT -eq 0 ] && result "PASS" "Existing keyword search works" || result "FAIL" "Keyword search regression" "exit code $SEARCH_EXIT"

# Verify invalidate command exists
python3 "$SCRIPTS/kb-semantic-search.py" invalidate "nonexistent-host" "nonexistent-rule" 2>/dev/null
INV_EXIT=$?
[ $INV_EXIT -eq 0 ] && result "PASS" "Invalidate command works" || result "FAIL" "Invalidate command" "exit code $INV_EXIT"

# --- Cleanup ---
echo
echo "--- Cleanup ---"
sqlite3 "$DB" "DELETE FROM session_transcripts WHERE issue_id LIKE 'TEST-%';"
sqlite3 "$DB" "DELETE FROM incident_knowledge WHERE issue_id LIKE 'TEST-TEMP-%';"
sqlite3 "$DB" "DELETE FROM agent_diary WHERE issue_id LIKE 'TEST-DIARY-%';"
rm -f "$TEST_JSONL"
echo "Test data cleaned up."

# --- Summary ---
echo
TOTAL=$((PASS + FAIL + WARN))
echo "=== Summary: $TOTAL tests | PASS: $PASS | FAIL: $FAIL | WARN: $WARN ==="
[ "$FAIL" -eq 0 ] && echo "ALL TESTS PASSED" || echo "FAILURES DETECTED — review above"
exit $FAIL
