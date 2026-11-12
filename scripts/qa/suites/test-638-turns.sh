#!/usr/bin/env bash
# IFRNLLEI01PRD-638 — per-turn lifecycle hooks + session_turns.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="638-turns"

start_test "session_turns_table_exists_with_unique_constraint"
  tmp=$(fresh_db)
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='session_turns'")
  assert_eq 1 "$n"
  # Verify (session_id, turn_id) UNIQUE.
  sqlite3 "$tmp" "INSERT INTO session_turns (session_id, turn_id, schema_version) VALUES ('s',0,1)"
  rc=0
  err=$(sqlite3 "$tmp" "INSERT INTO session_turns (session_id, turn_id, schema_version) VALUES ('s',0,1)" 2>&1) || rc=$?
  assert_ne 0 "$rc" "UNIQUE(session_id,turn_id) should reject duplicate"
  assert_contains "$err" "UNIQUE"
  cleanup_db "$tmp"
end_test

start_test "begin_turn_is_idempotent"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  rid1=$(GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0)
  rid2=$(GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0)
  assert_eq "$rid1" "$rid2"
  cleanup_db "$tmp"
end_test

start_test "tool_count_increments"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0 >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter tool  --session s --turn 0
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter tool  --session s --turn 0
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter tool  --session s --turn 0 --error
  n=$(sqlite3 "$tmp" "SELECT tool_count FROM session_turns WHERE session_id='s'")
  e=$(sqlite3 "$tmp" "SELECT tool_errors FROM session_turns WHERE session_id='s'")
  assert_eq 3 "$n"
  assert_eq 1 "$e"
  cleanup_db "$tmp"
end_test

start_test "end_turn_records_cost_and_duration"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 0 >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter end \
    --session s --turn 0 --cost 0.15 --input-tokens 500 --output-tokens 200 \
    --duration-ms 1800
  out=$(sqlite3 "$tmp" "SELECT llm_cost_usd, input_tokens, output_tokens, duration_ms FROM session_turns WHERE session_id='s'")
  assert_eq "0.15|500|200|1800" "$out"
  cleanup_db "$tmp"
end_test

start_test "session_start_hook_seeds_turn_zero"
  tmp=$(fresh_db)
  echo '{"session_id":"sess-A","source":"startup"}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$REPO_ROOT/scripts/hooks/session-start.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_turns WHERE session_id='sess-A' AND turn_id=0")
  assert_eq 1 "$n"
  # agent_updated event too.
  e=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='agent_updated'")
  assert_eq 1 "$e"
  cleanup_db "$tmp"
end_test

start_test "post_tool_use_hook_bumps_tool_count"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session s --turn 3 >/dev/null
  echo '{"tool_name":"Bash","tool_use_id":"t1","is_error":false,"output_size":500}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q CLAUDE_SESSION_ID=s TURN_ID=3 bash "$REPO_ROOT/scripts/hooks/post-tool-use.sh"
  n=$(sqlite3 "$tmp" "SELECT tool_count FROM session_turns WHERE session_id='s' AND turn_id=3")
  assert_eq 1 "$n"
  cleanup_db "$tmp"
end_test

start_test "user_prompt_submit_advances_turn_and_detects_poll_response"
  tmp=$(fresh_db)
  # Seed turn 0 so the next turn goes to 1.
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session sess-U --turn 0 >/dev/null
  echo '{"session_id":"sess-U","prompt":"Plan A"}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$REPO_ROOT/scripts/hooks/user-prompt-submit.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_turns WHERE session_id='sess-U'")
  assert_ge 2 "$n"
  approval=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='mcp_approval_response'")
  assert_eq 1 "$approval"
  cleanup_db "$tmp"
end_test

start_test "prom_exporter_computes_percentiles"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Seed 10 turns with known durations.
  for i in 0 1 2 3 4 5 6 7 8 9; do
    GATEWAY_DB="$tmp" python3 -m lib.turn_counter begin --issue Q --session sp --turn $i >/dev/null
    GATEWAY_DB="$tmp" python3 -m lib.turn_counter end   --session sp --turn $i --cost 0.01 --duration-ms $((100+10*i))
  done
  prom_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$prom_dir" "$REPO_ROOT/scripts/write-turn-metrics.sh"
  out=$(cat "$prom_dir/session_turns.prom")
  assert_contains "$out" "session_turns_total 10"
  assert_contains "$out" "session_turn_duration_p50"
  assert_contains "$out" "session_turn_duration_p95"
  rm -rf "$prom_dir"
  cleanup_db "$tmp"
end_test
