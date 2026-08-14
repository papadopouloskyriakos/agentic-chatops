#!/usr/bin/env bash
# IFRNLLEI01PRD-638 — per-turn + session-end hook edge cases.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="638-edge-cases"

start_test "post_tool_use_with_is_error_increments_tool_errors"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0 >/dev/null
  echo '{"tool_name":"Bash","tool_use_id":"t1","is_error":true,"output_size":0}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q CLAUDE_SESSION_ID=s TURN_ID=0 bash "$REPO_ROOT/scripts/hooks/post-tool-use.sh"
  e=$(sqlite3 "$tmp" "SELECT tool_errors FROM session_turns WHERE session_id='s'")
  assert_eq 1 "$e"
  # tool_ended event has error_type=error
  et=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.error_type') FROM event_log WHERE event_type='tool_ended'")
  assert_eq "error" "$et"
  cleanup_db "$tmp"
end_test

start_test "post_tool_use_empty_stdin_silent_zero"
  tmp=$(fresh_db)
  rc=0
  out=$(echo '' | GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$REPO_ROOT/scripts/hooks/post-tool-use.sh") || rc=$?
  assert_eq 0 "$rc"
  assert_eq "" "$out"
  cleanup_db "$tmp"
end_test

start_test "session_start_empty_stdin_silent_zero"
  tmp=$(fresh_db)
  rc=0
  out=$(echo '' | GATEWAY_DB="$tmp" bash "$REPO_ROOT/scripts/hooks/session-start.sh") || rc=$?
  assert_eq 0 "$rc"
  cleanup_db "$tmp"
end_test

start_test "user_prompt_submit_without_poll_marker_does_not_emit_approval_response"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0 >/dev/null
  echo '{"session_id":"s","prompt":"just a normal question about pods"}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$REPO_ROOT/scripts/hooks/user-prompt-submit.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='mcp_approval_response'")
  assert_eq 0 "$n"
  cleanup_db "$tmp"
end_test

start_test "user_prompt_submit_detects_YES_as_approval"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0 >/dev/null
  echo '{"session_id":"s","prompt":"yes"}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$REPO_ROOT/scripts/hooks/user-prompt-submit.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='mcp_approval_response'")
  assert_eq 1 "$n"
  cleanup_db "$tmp"
end_test

# ─── session-end.sh (on_final_output equivalent) ────────────────────────────
start_test "session_end_hook_flips_agent_back_to_operator"
  tmp=$(fresh_db)
  echo '{"session_id":"s-END"}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q AGENT_NAME=claude-code-t2 \
    bash "$REPO_ROOT/scripts/hooks/session-end.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='agent_updated' AND agent_name='operator' AND session_id='s-END'")
  assert_eq 1 "$n"
  payload=$(sqlite3 "$tmp" "SELECT payload_json FROM event_log WHERE session_id='s-END'")
  assert_contains "$payload" '"previous_agent": "claude-code-t2"'
  assert_contains "$payload" '"source": "session_end"'
  cleanup_db "$tmp"
end_test

start_test "session_end_hook_finalises_open_turn"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s-END2 --turn 0 >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s-END2 --turn 1 >/dev/null
  # ended_at is NULL on both.
  echo '{"session_id":"s-END2"}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$REPO_ROOT/scripts/hooks/session-end.sh"
  # The LAST open turn (1) should now be ended.
  t=$(sqlite3 "$tmp" "SELECT ended_at FROM session_turns WHERE session_id='s-END2' AND turn_id=1")
  assert_ne "" "$t" "ended_at should be set on turn 1"
  cleanup_db "$tmp"
end_test

start_test "session_end_hook_no_session_id_silent"
  tmp=$(fresh_db)
  rc=0
  out=$(echo '{"session_id":""}' | GATEWAY_DB="$tmp" bash "$REPO_ROOT/scripts/hooks/session-end.sh") || rc=$?
  assert_eq 0 "$rc"
  cleanup_db "$tmp"
end_test

start_test "end_turn_accumulates_cost_across_calls"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0 >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter end --session s --turn 0 --cost 0.10 --input-tokens 100 >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter end --session s --turn 0 --cost 0.05 --input-tokens 50 >/dev/null
  cost=$(sqlite3 "$tmp" "SELECT llm_cost_usd FROM session_turns WHERE session_id='s'")
  itk=$(sqlite3 "$tmp" "SELECT input_tokens FROM session_turns WHERE session_id='s'")
  assert_eq "0.15" "$cost"
  assert_eq "150" "$itk"
  cleanup_db "$tmp"
end_test
