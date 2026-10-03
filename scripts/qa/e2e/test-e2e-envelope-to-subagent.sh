#!/usr/bin/env bash
# E2E — HandoffInputData envelope flows through agent_as_tool into the
# sub-agent's process environment + prompt text.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="e2e-envelope-to-subagent"

start_test "mocked_subagent_receives_envelope_env_var"
  tmp=$(fresh_db)
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"

  # Pack a recognizable envelope so we can look for its marker.
  cd "$REPO_ROOT/scripts"
  B64=$(echo '{"input_history":[{"role":"user","content":"RECOGNIZABLE_E2E_MARKER"}],"pre_handoff_items":["netbox"],"new_items":[],"run_context":{"tier":"T1"}}' \
    | GATEWAY_DB="$tmp" python3 -m lib.handoff pack --issue QA-E2E-ENV --from openclaw-t1 --to triage-researcher --depth 1 --chain '["openclaw-t1","triage-researcher"]')

  # Invoke agent_as_tool with an explicit handoff_data payload.
  echo "{\"agent\":\"triage-researcher\",\"prompt\":\"go\",\"issue_id\":\"QA-E2E-ENV\",\"parent_agent\":\"claude-code-t2\",\"handoff_data\":{\"issue_id\":\"QA-E2E-ENV\",\"from_agent\":\"openclaw-t1\",\"to_agent\":\"triage-researcher\",\"input_history\":[{\"role\":\"user\",\"content\":\"RECOGNIZABLE_E2E_MARKER\"}]}}" | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10 >/dev/null

  # The mocked claude wrote env + args to MOCK_CLAUDE_LAST.
  assert_file_exists "$MOCK_CLAUDE_LAST"
  invocation=$(cat "$MOCK_CLAUDE_LAST")

  # Env-var shipped:
  assert_contains "$invocation" "HANDOFF_INPUT_DATA_B64="

  # Prompt text (ARGS) contains the marker — the sub-agent sees the
  # parent's prior context via as_prompt_section().
  assert_contains "$invocation" "RECOGNIZABLE_E2E_MARKER"

  # Also verify the prompt includes the PRIOR CONTEXT marker header.
  assert_contains "$invocation" "PRIOR CONTEXT"

  unset_mock_claude
  cleanup_db "$tmp"
end_test

start_test "agent_as_tool_call_event_payload_shape"
  tmp=$(fresh_db)
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"

  echo '{"agent":"triage-researcher","prompt":"investigate this","issue_id":"QA-EVT-SHAPE","parent_agent":"claude-code-t2"}' | \
    GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10 >/dev/null

  payload=$(sqlite3 "$tmp" "SELECT payload_json FROM event_log WHERE event_type='agent_as_tool_call'")
  assert_contains "$payload" '"sub_agent": "triage-researcher"'
  assert_contains "$payload" '"confidence": 0.72'
  # input_bytes should be non-zero (the prompt was >100 bytes).
  ib=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.input_bytes') FROM event_log WHERE event_type='agent_as_tool_call'")
  assert_gt "$ib" 100
  # output_bytes should also be non-zero (mock emits 3 JSONL lines).
  ob=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.output_bytes') FROM event_log WHERE event_type='agent_as_tool_call'")
  assert_gt "$ob" 50

  unset_mock_claude
  cleanup_db "$tmp"
end_test
