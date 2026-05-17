#!/usr/bin/env bash
# IFRNLLEI01PRD-637 — typed event taxonomy test suite.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="637-events"

start_test "event_types_registry_has_expected_entries"
  # Tracks the live registry — bump only when EVENT_TYPES tuple changes intentionally.
  # 17 = 13 OpenAI-SDK adoption batch + 4 NVIDIA P0+P1 (team_charter,
  # its_budget_consumed, intermediate_rail_check, session_replay_invoked).
  n=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.session_events import EVENT_TYPES; print(len(EVENT_TYPES))")
  assert_eq "17" "$n"
end_test

start_test "all_event_classes_instantiate_with_defaults"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 0 python3 -c "
from lib.session_events import (
  ToolStartedEvent, ToolEndedEvent, HandoffRequestedEvent,
  HandoffCompletedEvent, HandoffCycleDetectedEvent, HandoffCompactionEvent,
  ReasoningItemCreatedEvent, MCPApprovalRequestedEvent,
  MCPApprovalResponseEvent, AgentUpdatedEvent, MessageOutputEvent,
  ToolGuardrailRejectionEvent, AgentAsToolCallEvent,
)
for C in (ToolStartedEvent, ToolEndedEvent, HandoffRequestedEvent,
          HandoffCompletedEvent, HandoffCycleDetectedEvent, HandoffCompactionEvent,
          ReasoningItemCreatedEvent, MCPApprovalRequestedEvent,
          MCPApprovalResponseEvent, AgentUpdatedEvent, MessageOutputEvent,
          ToolGuardrailRejectionEvent, AgentAsToolCallEvent):
    e = C(issue_id='X', session_id='s', turn_id=0, agent_name='a')
    row = e.to_row()
    assert row['event_type'], 'missing event_type on ' + C.__name__
    assert isinstance(row['payload_json'], str)
"
end_test

start_test "cli_emit_inserts_row"
  tmp=$(fresh_db)
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" \
    --type tool_started --issue Q-1 --session s --turn 0 \
    --payload-json '{"tool_name":"Bash","tool_use_id":"t1","arguments":{"command":"ls"}}' >/dev/null
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='tool_started' AND issue_id='Q-1'")
  assert_eq "1" "$n"
  cleanup_db "$tmp"
end_test

start_test "cli_rejects_unknown_event_type"
  tmp=$(fresh_db)
  assert_exit_code 2 env GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" \
    --type bogus_type --issue Q-2 --payload-json '{}'
  cleanup_db "$tmp"
end_test

start_test "cli_rejects_bad_payload_json"
  tmp=$(fresh_db)
  assert_exit_code 2 env GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" \
    --type tool_started --issue Q-3 --payload-json 'not-json'
  cleanup_db "$tmp"
end_test

start_test "python_emit_returns_row_id"
  tmp=$(fresh_db)
  out=$(GATEWAY_DB="$tmp" PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from session_events import emit, ToolEndedEvent
rid = emit(ToolEndedEvent(issue_id='Q-4', session_id='s', turn_id=3, duration_ms=55, tool_name='Bash', exit_code=0, output_size=100))
print(rid)
")
  assert_gt "$out" 0
  n=$(sqlite3 "$tmp" "SELECT duration_ms FROM event_log WHERE issue_id='Q-4'")
  assert_eq "55" "$n"
  cleanup_db "$tmp"
end_test

start_test "soft_error_when_table_missing"
  tmp=$(mktemp --suffix=.db)
  : > "$tmp"  # empty file; connecting will succeed, INSERT will fail on missing table
  sqlite3 "$tmp" "CREATE TABLE other(x INTEGER)"
  out=$(GATEWAY_DB="$tmp" PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from session_events import emit, ToolStartedEvent
print(emit(ToolStartedEvent(issue_id='Q', session_id='s')))
" 2>&1)
  assert_contains "$out" "-1"
  rm -f "$tmp"
end_test

start_test "concurrent_emit_no_loss"
  tmp=$(fresh_db)
  for i in 1 2 3 4 5 6 7 8 9 10; do
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" \
      --type tool_started --issue "Q-C-$i" --session s --turn 0 \
      --payload-json "{\"tool_name\":\"T$i\"}" >/dev/null &
  done
  wait
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='tool_started'")
  assert_eq 10 "$n"
  cleanup_db "$tmp"
end_test

start_test "prom_exporter_emits_valid_format"
  tmp=$(fresh_db)
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" \
    --type tool_started --issue Q --session s --turn 0 --payload-json '{}' >/dev/null
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" \
    --type tool_ended --issue Q --session s --turn 0 --duration-ms 100 --payload-json '{}' >/dev/null
  prom_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$prom_dir" "$REPO_ROOT/scripts/write-event-metrics.sh"
  out=$(cat "$prom_dir/event_log.prom")
  assert_contains "$out" "event_log_total_rows{event_type=\"tool_started\"}"
  assert_contains "$out" "event_log_total_rows{event_type=\"tool_ended\"}"
  assert_contains "$out" "event_log_duration_ms_p50{event_type=\"tool_ended\"}"
  rm -rf "$prom_dir"
  cleanup_db "$tmp"
end_test
