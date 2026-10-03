#!/usr/bin/env bash
# IFRNLLEI01PRD-643 — concurrent handoff_depth bumps must not lose updates.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="643-concurrent"

start_test "ten_parallel_bumps_each_commit_exactly_once"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Fire 10 parallel bumps with distinct agent names → each should commit
  # uniquely, final depth = 10 (but we halt at 10), so fire 8 parallel bumps.
  for i in 1 2 3 4 5 6 7 8; do
    GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-CC --from parent --bump-to "agent-$i" >/dev/null &
  done
  wait
  depth=$(sqlite3 "$tmp" "SELECT handoff_depth FROM sessions WHERE issue_id='QA-CC'")
  # Every bump ran in a separate IMMEDIATE transaction; final depth must be 8.
  assert_eq 8 "$depth"
  # handoff_chain should contain all 8 agents (order non-deterministic).
  chain=$(sqlite3 "$tmp" "SELECT handoff_chain FROM sessions WHERE issue_id='QA-CC'")
  for i in 1 2 3 4 5 6 7 8; do
    assert_contains "$chain" "\"agent-$i\""
  done
  # 8 handoff_requested events emitted.
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_requested'")
  assert_eq 8 "$n"
  cleanup_db "$tmp"
end_test

start_test "malformed_handoff_chain_json_falls_back_to_empty_list"
  tmp=$(fresh_db)
  # Corrupt the chain column with invalid JSON.
  sqlite3 "$tmp" "INSERT INTO sessions (issue_id, handoff_depth, handoff_chain, schema_version) VALUES ('BAD',0,'not-json',1)"
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 -m lib.handoff_depth BAD)
  assert_contains "$out" '"chain": []'
end_test

start_test "DepthState_default_values_are_sane"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from handoff_depth import DepthState
d = DepthState()
assert d.depth == 0
assert d.chain == []
assert d.should_poll is False
assert d.should_halt is False
assert d.cycle_agent is None
print('ok')
")
  assert_eq "ok" "$out"
end_test
