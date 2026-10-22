#!/usr/bin/env bash
# IFRNLLEI01PRD-642 — agent-as-tool wrapper.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="642-agent-as-tool"

start_test "registry_discovers_all_10_agents"
  out=$("$REPO_ROOT/scripts/agent_as_tool.py" list)
  for a in triage-researcher code-explorer k8s-diagnostician cisco-asa-specialist \
           storage-specialist security-analyst workflow-validator \
           dependency-analyst ci-debugger; do
    assert_contains "$out" "\"$a\""
  done
end_test

start_test "describe_returns_agent_spec"
  out=$("$REPO_ROOT/scripts/agent_as_tool.py" describe triage-researcher)
  assert_contains "$out" '"name": "triage-researcher"'
  assert_contains "$out" '"model": "haiku"'
  assert_contains "$out" '"max_turns": 15'
end_test

start_test "describe_unknown_agent_errors"
  assert_exit_code 1 "$REPO_ROOT/scripts/agent_as_tool.py" describe bogus-agent
end_test

start_test "dry_run_does_not_persist_or_spawn"
  tmp=$(fresh_db)
  out=$(echo '{"agent":"triage-researcher","prompt":"investigate nl-pve01","issue_id":"QA-AT-1","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --dry-run)
  assert_contains "$out" '"cmd"'
  assert_contains "$out" "triage-researcher"
  # No row persisted (dry-run):
  n=$(sqlite3 "$tmp" "SELECT COALESCE(handoff_depth,0) FROM sessions WHERE issue_id='QA-AT-1'")
  assert_eq "" "$n"
  cleanup_db "$tmp"
end_test

start_test "dry_run_detects_cycle"
  tmp=$(fresh_db)
  # Seed a chain that already contains our target.
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0,'lib')
from handoff_depth import bump
bump('QA-CY','claude-code-t2','triage-researcher')
bump('QA-CY','claude-code-t2','code-explorer')
" >/dev/null
  out=$(echo '{"agent":"triage-researcher","prompt":"p","issue_id":"QA-CY","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --dry-run 2>&1)
  rc=$?
  assert_eq "1" "$rc"
  assert_contains "$out" "cycle"
  cleanup_db "$tmp"
end_test

start_test "dry_run_detects_would_halt_at_depth"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Advance depth to 9
  GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0,'lib')
from handoff_depth import bump
for i in range(9):
    bump('QA-HA','claude-code-t2',f'agent-{i}')
" >/dev/null
  out=$(echo '{"agent":"triage-researcher","prompt":"p","issue_id":"QA-HA","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --dry-run 2>&1)
  rc=$?
  assert_eq "1" "$rc"
  assert_contains "$out" "halt"
  cleanup_db "$tmp"
end_test

start_test "mocked_spawn_parses_confidence_and_findings"
  tmp=$(fresh_db)
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"
  out=$(echo '{"agent":"triage-researcher","prompt":"p","issue_id":"QA-MK","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10)
  assert_contains "$out" '"confidence": 0.72'
  assert_contains "$out" '"summary"'
  assert_contains "$out" "finding A"
  assert_contains "$out" '"agent": "triage-researcher"'
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='agent_as_tool_call'")
  assert_eq "1" "$n"
  unset_mock_claude
  cleanup_db "$tmp"
end_test
