#!/usr/bin/env bash
# IFRNLLEI01PRD-642 — agent-as-tool edge cases.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="642-edge-cases"

start_test "list_returns_valid_json"
  out=$("$REPO_ROOT/scripts/agent_as_tool.py" list)
  python3 -c "import json,sys; json.loads('''$out''')" 2>/dev/null || fail_test "list output is not valid JSON"
end_test

start_test "describe_includes_body_bytes"
  out=$("$REPO_ROOT/scripts/agent_as_tool.py" describe triage-researcher)
  assert_contains "$out" '"body_bytes"'
  # body_bytes > 0
  bb=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['body_bytes'])" "$out")
  assert_gt "$bb" 100
end_test

start_test "call_rejects_missing_agent_or_prompt"
  tmp=$(fresh_db)
  rc=0
  echo '{"prompt":"just a prompt"}' | GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call >/dev/null 2>&1 || rc=$?
  assert_eq 2 "$rc"
  cleanup_db "$tmp"
end_test

start_test "mock_spawn_with_handoff_data_payload"
  tmp=$(fresh_db)
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"
  echo '{"agent":"triage-researcher","prompt":"go","issue_id":"Q-HD","parent_agent":"claude-code-t2","handoff_data":{"issue_id":"Q-HD","from_agent":"openclaw-t1","to_agent":"triage-researcher","input_history":[{"role":"user","content":"pve01 down"}]}}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10 >/dev/null
  # Mock should have received HANDOFF_INPUT_DATA_B64
  inv=$(cat "$MOCK_CLAUDE_LAST")
  assert_contains "$inv" "HANDOFF_INPUT_DATA_B64="
  unset_mock_claude
  cleanup_db "$tmp"
end_test

start_test "handoff_data_with_unknown_field_ignored_gracefully"
  tmp=$(fresh_db)
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"
  # Extra field that is not in HandoffInputData.__dataclass_fields__
  echo '{"agent":"triage-researcher","prompt":"go","issue_id":"Q-UF","parent_agent":"claude-code-t2","handoff_data":{"issue_id":"Q-UF","from_agent":"openclaw-t1","to_agent":"triage-researcher","bogus_field":"ignored"}}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10 >/tmp/o.$$ 2>&1
  rc=$?
  out=$(cat /tmp/o.$$); rm -f /tmp/o.$$
  assert_eq 0 "$rc"
  assert_contains "$out" '"agent": "triage-researcher"'
  unset_mock_claude
  cleanup_db "$tmp"
end_test

start_test "parse_result_fallback_when_no_result_jsonl_line"
  # Simulate a mock claude that emits garbage instead of a result record.
  # The wrapper should fall back to whole stdout as summary.
  tmp=$(fresh_db)
  dir=/tmp/.qa_mock_claude_noresult.$$
  mkdir -p "$dir"
  cat > "$dir/claude" <<'M'
#!/usr/bin/env bash
printf '%s\n' 'just plain text — CONFIDENCE: 0.5 — no jsonl result line'
M
  chmod +x "$dir/claude"
  export CLAUDE_BIN="$dir/claude"
  out=$(echo '{"agent":"triage-researcher","prompt":"p","issue_id":"Q-FB","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10)
  assert_contains "$out" '"confidence": 0.5'
  assert_contains "$out" "no jsonl result line"
  rm -rf "$dir"; unset CLAUDE_BIN
  cleanup_db "$tmp"
end_test

start_test "timeout_surfaced_as_exit_124"
  # A claude-cli that never exits.
  tmp=$(fresh_db)
  dir=/tmp/.qa_mock_claude_sleep.$$
  mkdir -p "$dir"
  cat > "$dir/claude" <<'M'
#!/usr/bin/env bash
sleep 30
M
  chmod +x "$dir/claude"
  export CLAUDE_BIN="$dir/claude"
  out=$(echo '{"agent":"triage-researcher","prompt":"p","issue_id":"Q-TO","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 2)
  assert_contains "$out" '"exit_code": 124'
  rm -rf "$dir"; unset CLAUDE_BIN
  cleanup_db "$tmp"
end_test

start_test "halt_detection_dry_run_shows_depth_in_error"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0,'lib')
from handoff_depth import bump
for i in range(9): bump('Q-HE','claude-code-t2',f'agent-{i}')
" >/dev/null
  out=$(echo '{"agent":"triage-researcher","prompt":"p","issue_id":"Q-HE","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --dry-run 2>&1)
  assert_contains "$out" "halt"
  assert_contains "$out" "\"depth_info\""
  cleanup_db "$tmp"
end_test
