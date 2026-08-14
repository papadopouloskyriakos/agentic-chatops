#!/usr/bin/env bash
# IFRNLLEI01PRD-637 — event_log edge cases + Prometheus exporter robustness.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="637-edge-cases"

start_test "payload_json_is_sorted_for_reproducibility"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from session_events import emit, ToolStartedEvent
emit(ToolStartedEvent(issue_id='X', session_id='s', turn_id=0, tool_name='Bash', tool_use_id='t1'))
"
  payload=$(sqlite3 "$tmp" "SELECT payload_json FROM event_log")
  # Keys should appear in alphabetical order
  first_two_keys=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(','.join(list(d.keys())[:2]))" "$payload")
  assert_eq "arguments,tool_name" "$first_two_keys"
  cleanup_db "$tmp"
end_test

start_test "emitted_at_is_populated"
  tmp=$(fresh_db)
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" --type tool_started --issue Q --session s --turn 0 --payload-json '{"tool_name":"Bash"}' >/dev/null
  t=$(sqlite3 "$tmp" "SELECT emitted_at FROM event_log WHERE issue_id='Q'")
  # Should look like YYYY-MM-DD HH:MM:SS
  assert_contains "$t" "2026-"
end_test

start_test "session_id_correlation_across_events"
  tmp=$(fresh_db)
  for i in 1 2 3; do
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" --type tool_started \
      --issue Q --session corr-s --turn $i \
      --payload-json "{\"tool_name\":\"Bash\",\"n\":$i}" >/dev/null
  done
  n=$(sqlite3 "$tmp" "SELECT COUNT(DISTINCT turn_id) FROM event_log WHERE session_id='corr-s'")
  assert_eq 3 "$n"
  cleanup_db "$tmp"
end_test

start_test "event_ordering_by_emitted_at"
  tmp=$(fresh_db)
  for i in 1 2 3; do
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" --type tool_started \
      --issue Q --session ord-s --turn $i \
      --payload-json "{\"tool_name\":\"Bash\",\"n\":$i}" >/dev/null
  done
  # IDs must be monotonically increasing with turn_id (we insert in turn order).
  ids=$(sqlite3 "$tmp" "SELECT id FROM event_log WHERE session_id='ord-s' ORDER BY id")
  py_sorted=$(python3 -c "
ids = '''$ids'''.split()
print('ok' if ids == sorted(ids, key=int) else 'out-of-order')
")
  assert_eq "ok" "$py_sorted"
  cleanup_db "$tmp"
end_test

# ─── Prometheus exporter robustness ────────────────────────────────────────
start_test "prom_exporter_empty_db_emits_valid_output"
  tmp=$(fresh_db)
  prom_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$prom_dir" \
    "$REPO_ROOT/scripts/write-event-metrics.sh"
  out=$(cat "$prom_dir/event_log.prom")
  # Even with no rows, HELP/TYPE lines must appear.
  assert_contains "$out" "# TYPE event_log_rate_per_type gauge"
  rm -rf "$prom_dir"
  cleanup_db "$tmp"
end_test

start_test "prom_exporter_missing_table_graceful_no_op"
  tmp=$(mktemp --suffix=.db)
  # Never run migrations; event_log doesn't exist yet.
  sqlite3 "$tmp" "CREATE TABLE other(x)"
  prom_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$prom_dir" \
    "$REPO_ROOT/scripts/write-event-metrics.sh"
  out=$(cat "$prom_dir/event_log.prom")
  assert_contains "$out" "not yet created"
  rm -rf "$prom_dir"; rm -f "$tmp"
end_test

start_test "cli_returns_nonzero_when_event_soft_fails"
  # Writing into a DB where event_log table doesn't exist → emit returns -1.
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" "CREATE TABLE other(x)"
  rc=0
  out=$(GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" --type tool_started \
    --issue Q --payload-json '{}' 2>&1) || rc=$?
  assert_eq 1 "$rc"
  rm -f "$tmp"
end_test

start_test "unknown_agent_name_in_event_does_not_break_insert"
  # agent_name is a free-form string; any UTF-8 should pass.
  tmp=$(fresh_db)
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" --type agent_updated \
    --issue Q --session s --turn 0 --agent "agent-名前-测试" \
    --payload-json '{"previous_agent":"x"}' >/dev/null
  agent=$(sqlite3 "$tmp" "SELECT agent_name FROM event_log WHERE issue_id='Q'")
  assert_eq "agent-名前-测试" "$agent"
  cleanup_db "$tmp"
end_test
