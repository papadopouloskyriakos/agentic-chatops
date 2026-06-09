#!/usr/bin/env bash
# IFRNLLEI01PRD-636 — immutable per-turn snapshots.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="636-snapshots"

start_test "session_state_snapshot_table_exists"
  tmp=$(fresh_db)
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='session_state_snapshot'")
  assert_eq 1 "$n"
  cleanup_db "$tmp"
end_test

start_test "capture_creates_row_with_schema_version"
  tmp=$(fresh_db)
  seed_session "$tmp" "QA-SNAP-1" "s1"
  cd "$REPO_ROOT/scripts"
  rid=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue QA-SNAP-1 --session s1 --turn 3 --tool Bash --tool-input-json '{"command":"ls"}')
  assert_gt "$rid" "0"
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM session_state_snapshot WHERE id=$rid")
  assert_eq "1" "$sv"
  cleanup_db "$tmp"
end_test

start_test "snapshot_data_captures_sessions_row_and_usage"
  tmp=$(fresh_db)
  seed_session "$tmp" "QA-SNAP-2" "s1"
  sqlite3 "$tmp" "UPDATE sessions SET cost_usd=0.25, confidence=0.8 WHERE issue_id='QA-SNAP-2'"
  sqlite3 "$tmp" "INSERT INTO llm_usage (tier,model,issue_id,input_tokens,output_tokens,cost_usd) VALUES (2,'opus','QA-SNAP-2',500,200,0.25)"
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue QA-SNAP-2 --session s1 --turn 1 --tool Bash --tool-input-json '{}' >/dev/null
  out=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot latest --issue QA-SNAP-2)
  assert_contains "$out" '"cost_usd": 0.25'
  assert_contains "$out" '"confidence": 0.8'
  assert_contains "$out" '"input_tokens": 500'
  cleanup_db "$tmp"
end_test

start_test "multiple_snapshots_preserved"
  tmp=$(fresh_db)
  seed_session "$tmp" "QA-SNAP-3" "s1"
  cd "$REPO_ROOT/scripts"
  for i in 1 2 3; do
    GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue QA-SNAP-3 --session s1 --turn $i --tool Bash --tool-input-json "{\"n\":$i}" >/dev/null
  done
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='QA-SNAP-3'")
  assert_eq 3 "$n"
  cleanup_db "$tmp"
end_test

start_test "rollback_restores_sessions_row"
  tmp=$(fresh_db)
  seed_session "$tmp" "QA-RB" "s1"
  sqlite3 "$tmp" "UPDATE sessions SET cost_usd=0.10, confidence=0.7 WHERE issue_id='QA-RB'"
  cd "$REPO_ROOT/scripts"
  rid=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue QA-RB --session s1 --turn 1 --tool Bash --tool-input-json '{}')
  # Tamper:
  sqlite3 "$tmp" "UPDATE sessions SET cost_usd=999, confidence=-1 WHERE issue_id='QA-RB'"
  GATEWAY_DB="$tmp" python3 -m lib.snapshot rollback --id "$rid"
  out=$(sqlite3 "$tmp" "SELECT cost_usd, confidence FROM sessions WHERE issue_id='QA-RB'")
  assert_eq "0.1|0.7" "$out"
  cleanup_db "$tmp"
end_test

start_test "rollback_nonexistent_id_returns_error"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 env GATEWAY_DB="$tmp" python3 -m lib.snapshot rollback --id 99999
  cleanup_db "$tmp"
end_test

start_test "prune_deletes_old_rows"
  tmp=$(fresh_db)
  seed_session "$tmp" "QA-PR" "s1"
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue QA-PR --session s1 --turn 1 --tool Bash --tool-input-json '{}' >/dev/null
  # Force the row timestamp back 10 days.
  sqlite3 "$tmp" "UPDATE session_state_snapshot SET snapshot_at=datetime('now','-10 days') WHERE issue_id='QA-PR'"
  out=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot prune --days 7)
  assert_contains "$out" "pruned 1"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='QA-PR'")
  assert_eq 0 "$n"
  cleanup_db "$tmp"
end_test

start_test "snapshot_hook_skips_read_only_tools"
  tmp=$(fresh_db)
  seed_session "$tmp" "QA-HR" "s1"
  # Call hook with Read tool — should NOT snapshot.
  echo '{"tool_name":"Read","tool_input":{"file_path":"/etc/hostname"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=QA-HR CLAUDE_SESSION_ID=s1 TURN_ID=1 bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='QA-HR'")
  assert_eq 0 "$n"
  # And Grep.
  echo '{"tool_name":"Grep","tool_input":{"pattern":"x"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=QA-HR CLAUDE_SESSION_ID=s1 TURN_ID=1 bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='QA-HR'")
  assert_eq 0 "$n"
  # Bash DOES snapshot.
  echo '{"tool_name":"Bash","tool_input":{"command":"kubectl get pods"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=QA-HR CLAUDE_SESSION_ID=s1 TURN_ID=1 bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='QA-HR'")
  assert_eq 1 "$n"
  cleanup_db "$tmp"
end_test
