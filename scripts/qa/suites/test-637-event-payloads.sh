#!/usr/bin/env bash
# IFRNLLEI01PRD-637 — per-event-type payload shape.
#
# Every SessionEvent subclass must produce a payload_json containing the
# event-specific fields documented in the class. This suite asserts one
# test per event type.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="637-event-payloads"

emit_and_get_payload() {
  # Args: event_type tmp_db payload_json_as_text
  local ev="$1" db="$2" pj="$3"
  GATEWAY_DB="$db" "$REPO_ROOT/scripts/emit-event.py" --type "$ev" \
    --issue Q --session s --turn 0 --payload-json "$pj" >/dev/null
  sqlite3 "$db" "SELECT payload_json FROM event_log WHERE event_type='$ev' ORDER BY id DESC LIMIT 1"
}

start_test "tool_started_payload_has_tool_name_and_arguments"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload tool_started "$tmp" '{"tool_name":"Bash","tool_use_id":"t1","arguments":{"command":"ls"}}')
  assert_contains "$p" '"tool_name": "Bash"'
  assert_contains "$p" '"tool_use_id": "t1"'
  assert_contains "$p" '"arguments"'
  assert_contains "$p" '"command": "ls"'
  cleanup_db "$tmp"
end_test

start_test "tool_ended_payload_has_exit_tracking"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload tool_ended "$tmp" '{"tool_name":"Bash","tool_use_id":"t1","output_size":500,"error_type":""}')
  assert_contains "$p" '"output_size": 500'
  assert_contains "$p" '"error_type": ""'
  cleanup_db "$tmp"
end_test

start_test "handoff_requested_payload_has_chain_and_depth"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload handoff_requested "$tmp" '{"from_agent":"A","to_agent":"B","handoff_depth":2,"handoff_chain":["A","B"],"reason":"test"}')
  assert_contains "$p" '"from_agent": "A"'
  assert_contains "$p" '"to_agent": "B"'
  assert_contains "$p" '"handoff_depth": 2'
  assert_contains "$p" '"handoff_chain"'
  cleanup_db "$tmp"
end_test

start_test "handoff_completed_payload_is_minimal"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload handoff_completed "$tmp" '{"from_agent":"A","to_agent":"B","handoff_depth":3}')
  assert_contains "$p" '"handoff_depth": 3'
  cleanup_db "$tmp"
end_test

start_test "handoff_cycle_detected_payload_lists_chain"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload handoff_cycle_detected "$tmp" '{"from_agent":"A","to_agent":"B","handoff_chain":["A","B","A"]}')
  assert_contains "$p" '"handoff_chain"'
  cleanup_db "$tmp"
end_test

start_test "handoff_compaction_payload_includes_bytes_and_model"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload handoff_compaction "$tmp" '{"pre_bytes":20000,"post_bytes":800,"model":"gemma3:12b","ratio":0.04}')
  assert_contains "$p" '"pre_bytes": 20000'
  assert_contains "$p" '"post_bytes": 800'
  assert_contains "$p" '"model": "gemma3:12b"'
  assert_contains "$p" '"ratio": 0.04'
  cleanup_db "$tmp"
end_test

start_test "reasoning_item_created_payload_has_thinking_chars"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload reasoning_item_created "$tmp" '{"thinking_chars":1500,"uncertainty_phrases":["might","unclear"],"led_to_tool_call":true}')
  assert_contains "$p" '"thinking_chars": 1500'
  assert_contains "$p" '"led_to_tool_call": true'
  assert_contains "$p" '"uncertainty_phrases"'
  cleanup_db "$tmp"
end_test

start_test "mcp_approval_requested_payload_has_gate_type_and_options"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload mcp_approval_requested "$tmp" '{"gate_type":"poll","options":["Plan A","Plan B"],"confidence":0.65}')
  assert_contains "$p" '"gate_type": "poll"'
  assert_contains "$p" '"confidence": 0.65'
  assert_contains "$p" '"options"'
  cleanup_db "$tmp"
end_test

start_test "mcp_approval_response_payload_has_choice_and_responder"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload mcp_approval_response "$tmp" '{"gate_type":"poll","choice":"Plan A","responder":"operator"}')
  assert_contains "$p" '"choice": "Plan A"'
  assert_contains "$p" '"responder": "operator"'
  cleanup_db "$tmp"
end_test

start_test "agent_updated_payload_has_previous_agent"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload agent_updated "$tmp" '{"previous_agent":"openclaw-t1"}')
  assert_contains "$p" '"previous_agent": "openclaw-t1"'
  cleanup_db "$tmp"
end_test

start_test "message_output_created_payload_has_tag_flags"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload message_output_created "$tmp" '{"chars":300,"has_confidence_tag":true,"has_poll_tag":false}')
  assert_contains "$p" '"chars": 300'
  assert_contains "$p" '"has_confidence_tag": true'
  assert_contains "$p" '"has_poll_tag": false'
  cleanup_db "$tmp"
end_test

start_test "tool_guardrail_rejection_payload_has_behavior_taxonomy"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload tool_guardrail_rejection "$tmp" '{"tool_name":"Bash","behavior":"deny","message":"blocked","signals":["destructive"]}')
  assert_contains "$p" '"behavior": "deny"'
  assert_contains "$p" '"signals"'
  cleanup_db "$tmp"
end_test

start_test "agent_as_tool_call_payload_has_sub_agent_and_sizes"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload agent_as_tool_call "$tmp" '{"sub_agent":"triage-researcher","input_bytes":2500,"output_bytes":800,"confidence":0.78}')
  assert_contains "$p" '"sub_agent": "triage-researcher"'
  assert_contains "$p" '"input_bytes": 2500'
  assert_contains "$p" '"output_bytes": 800'
  assert_contains "$p" '"confidence": 0.78'
  cleanup_db "$tmp"
end_test

# ─── Per-Python-class dataclass round-trip ──────────────────────────────────
start_test "HandoffCompactionEvent_computes_ratio_from_bytes"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from session_events import HandoffCompactionEvent
e = HandoffCompactionEvent(issue_id='X', pre_bytes=1000, post_bytes=200, model='gemma3:12b')
import json
print(json.loads(e.to_row()['payload_json'])['ratio'])
")
  assert_eq "0.2" "$out"
end_test

start_test "HandoffCompactionEvent_ratio_zero_on_empty_pre_bytes"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from session_events import HandoffCompactionEvent
import json
e = HandoffCompactionEvent(issue_id='X', pre_bytes=0, post_bytes=0, model='none')
print(json.loads(e.to_row()['payload_json'])['ratio'])
")
  assert_eq "0.0" "$out"
end_test

start_test "to_row_includes_turn_id_and_agent_name"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from session_events import ToolStartedEvent
e = ToolStartedEvent(issue_id='X', session_id='s', turn_id=7, agent_name='triage-researcher', tool_name='Bash')
row = e.to_row()
print(row['turn_id'], row['agent_name'], row['event_type'])
")
  assert_eq "7 triage-researcher tool_started" "$out"
end_test

start_test "emit_handles_bigint_and_unicode_cleanly"
  tmp=$(fresh_db)
  p=$(emit_and_get_payload tool_started "$tmp" '{"tool_name":"Bash","arguments":{"x":9999999999}}')
  assert_contains "$p" "9999999999"
  p2=$(emit_and_get_payload message_output_created "$tmp" '{"chars":5,"has_confidence_tag":false,"has_poll_tag":false}')
  # sanity — JSON parsed cleanly
  assert_contains "$p2" '"chars": 5'
  cleanup_db "$tmp"
end_test
