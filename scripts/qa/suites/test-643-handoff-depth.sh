#!/usr/bin/env bash
# IFRNLLEI01PRD-643 — handoff depth counter + cycle detection.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="643-handoff-depth"

start_test "sessions_has_handoff_depth_column"
  tmp=$(fresh_db)
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('sessions') WHERE name='handoff_depth'")
  assert_eq 1 "$n"
  m=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('sessions') WHERE name='handoff_chain'")
  assert_eq 1 "$m"
  cleanup_db "$tmp"
end_test

start_test "read_empty_state"
  tmp=$(fresh_db)
  out=$(cd "$REPO_ROOT/scripts" && GATEWAY_DB="$tmp" python3 -m lib.handoff_depth NONEXISTENT-1)
  assert_contains "$out" '"depth": 0'
  assert_contains "$out" '"chain": []'
  cleanup_db "$tmp"
end_test

start_test "five_bumps_trigger_poll_threshold"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  for i in 1 2 3 4 5; do
    GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-5 --from parent --bump-to "agent-$i" >/dev/null
  done
  depth=$(sqlite3 "$tmp" "SELECT handoff_depth FROM sessions WHERE issue_id='QA-5'")
  assert_eq "5" "$depth"
  out=$(GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-5)
  assert_contains "$out" '"should_poll": true'
  cleanup_db "$tmp"
end_test

start_test "cycle_detection_rollbacks_and_raises"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-C --from parent --bump-to agent-a >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-C --from parent --bump-to agent-b >/dev/null
  # Attempt cycle: agent-a appears in chain already. Should exit non-zero + rollback depth.
  assert_exit_code 3 env GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-C --from parent --bump-to agent-a
  depth=$(sqlite3 "$tmp" "SELECT handoff_depth FROM sessions WHERE issue_id='QA-C'")
  assert_eq "2" "$depth"  # depth didn't advance
  cleanup_db "$tmp"
end_test

start_test "halt_at_depth_10"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  for i in 1 2 3 4 5 6 7 8 9; do
    GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-H --from parent --bump-to "agent-$i" >/dev/null
  done
  assert_exit_code 4 env GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-H --from parent --bump-to agent-10
  cleanup_db "$tmp"
end_test

start_test "event_log_captures_each_bump_and_cycle"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0,'lib')
from handoff_depth import bump, HandoffCycleDetected
bump('Q-E','parent','a1')
bump('Q-E','parent','a2')
try: bump('Q-E','parent','a1')
except HandoffCycleDetected: pass
" >/dev/null 2>&1
  hr=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_requested'")
  assert_eq "3" "$hr"
  hc=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_cycle_detected'")
  assert_eq "1" "$hc"
  cleanup_db "$tmp"
end_test

start_test "dry_run_mode_no_persistence"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-D --from parent --bump-to a --dry-run)
  assert_contains "$out" '"would_depth": 1'
  depth=$(sqlite3 "$tmp" "SELECT COALESCE(handoff_depth,0) FROM sessions WHERE issue_id='QA-D'")
  # Row doesn't exist, so empty result.
  assert_eq "" "$depth"
  cleanup_db "$tmp"
end_test

start_test "prom_exporter_reflects_state"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-P --from parent --bump-to a >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-P --from parent --bump-to b >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.handoff_depth QA-P --from parent --bump-to c >/dev/null
  sqlite3 "$tmp" "UPDATE sessions SET is_current=1 WHERE issue_id='QA-P'"
  prom_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$prom_dir" "$REPO_ROOT/scripts/write-handoff-metrics.sh"
  out=$(cat "$prom_dir/handoff_depth.prom")
  assert_contains "$out" "handoff_depth_max 3"
  rm -rf "$prom_dir"
  cleanup_db "$tmp"
end_test
