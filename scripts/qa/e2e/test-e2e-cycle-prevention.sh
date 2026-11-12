#!/usr/bin/env bash
# E2E — runaway recursion is prevented before it happens.
#
# Scenario: a misconfigured sub-agent chain tries to escalate back to the same
# agent. The cycle detector rolls back the bump, emits a typed event, and the
# agent-as-tool wrapper refuses to spawn.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="e2e-cycle-prevention"
tmp=$(fresh_db)

start_test "cycle_caught_and_bump_not_persisted"
  ISSUE="QA-CYC"
  cd "$REPO_ROOT/scripts"
  # Build a chain of 3 legitimate escalations.
  GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0,'lib')
from handoff_depth import bump
bump('$ISSUE','openclaw-t1','claude-code-t2')
bump('$ISSUE','claude-code-t2','triage-researcher')
bump('$ISSUE','triage-researcher','k8s-diagnostician')
" >/dev/null 2>&1

  pre_depth=$(sqlite3 "$tmp" "SELECT handoff_depth FROM sessions WHERE issue_id='$ISSUE'")
  assert_eq "3" "$pre_depth"

  # Now try to escalate back to an agent already in the chain.
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"
  out=$(echo '{"agent":"triage-researcher","prompt":"p","issue_id":"'$ISSUE'","parent_agent":"k8s-diagnostician"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call 2>&1)
  rc=$?
  unset_mock_claude

  assert_ne "0" "$rc" "call should have failed"
  assert_contains "$out" "cycle"

  # Depth should not have advanced.
  post_depth=$(sqlite3 "$tmp" "SELECT handoff_depth FROM sessions WHERE issue_id='$ISSUE'")
  assert_eq "$pre_depth" "$post_depth" "depth should not advance on cycle"

  # Typed event present.
  cycles=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_cycle_detected'")
  assert_ge "$cycles" "1"

  # The mocked claude binary was NOT spawned (no agent_as_tool_call event with exit_code=0 for this one).
  atc=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='agent_as_tool_call'")
  assert_eq "0" "$atc" "sub-agent must not have been spawned"
end_test

cleanup_db "$tmp"
