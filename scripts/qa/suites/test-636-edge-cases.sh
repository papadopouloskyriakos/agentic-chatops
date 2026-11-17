#!/usr/bin/env bash
# IFRNLLEI01PRD-636 — snapshot edge cases.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="636-edge-cases"

start_test "capture_with_no_sessions_row_still_writes_snapshot"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  rid=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue ORPHAN --session s --turn 1 --tool Bash --tool-input-json '{}')
  assert_gt "$rid" 0
  # snapshot_data should have empty sessions_row (not present).
  data=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot latest --issue ORPHAN)
  assert_contains "$data" '"snapshot_data"'
  cleanup_db "$tmp"
end_test

start_test "rollback_with_empty_snapshot_data_is_safe"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Insert a manually-crafted snapshot with empty data.
  sqlite3 "$tmp" "INSERT INTO session_state_snapshot (issue_id, session_id, turn_id, pending_tool, pending_tool_input, snapshot_data, snapshot_bytes, schema_version) VALUES ('EMPTY','s',0,'Bash','{}','{}',2,1)"
  rid=$(sqlite3 "$tmp" "SELECT id FROM session_state_snapshot WHERE issue_id='EMPTY'")
  # rollback to this row — should not error, just do nothing.
  out=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot rollback --id "$rid" 2>&1)
  assert_contains "$out" "rolled back to snapshot"
  cleanup_db "$tmp"
end_test

start_test "rollback_ignores_unknown_columns_in_snapshot"
  tmp=$(fresh_db)
  seed_session "$tmp" "FWD" "s"
  cd "$REPO_ROOT/scripts"
  # Forge a snapshot with a future column that doesn't exist in today's sessions.
  sqlite3 "$tmp" "INSERT INTO session_state_snapshot (issue_id, session_id, turn_id, pending_tool, snapshot_data, snapshot_bytes, schema_version) VALUES ('FWD','s',1,'Bash','{\"sessions_row\":{\"issue_id\":\"FWD\",\"cost_usd\":0.42,\"future_col_XYZ\":\"garbage\"}}',60,1)"
  rid=$(sqlite3 "$tmp" "SELECT id FROM session_state_snapshot WHERE issue_id='FWD'")
  out=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot rollback --id "$rid" 2>&1)
  assert_contains "$out" "rolled back"
  cost=$(sqlite3 "$tmp" "SELECT cost_usd FROM sessions WHERE issue_id='FWD'")
  assert_eq "0.42" "$cost"
  cleanup_db "$tmp"
end_test

start_test "hook_with_missing_issue_id_exits_silent_zero"
  tmp=$(fresh_db)
  rc=0
  out=$(echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | \
    env -u ISSUE_ID GATEWAY_DB="$tmp" CLAUDE_SESSION_ID=s TURN_ID=1 \
    bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh") || rc=$?
  assert_eq 0 "$rc"
  assert_eq "" "$out"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot")
  assert_eq 0 "$n"
  cleanup_db "$tmp"
end_test

start_test "hook_with_empty_stdin_silent"
  tmp=$(fresh_db)
  rc=0
  out=$(echo '' | GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh") || rc=$?
  assert_eq 0 "$rc"
  cleanup_db "$tmp"
end_test

start_test "prune_with_zero_matching_rows_reports_0"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot prune --days 7)
  assert_contains "$out" "pruned 0"
  cleanup_db "$tmp"
end_test

start_test "prune_only_snapshots_older_than_N"
  tmp=$(fresh_db)
  seed_session "$tmp" "PRUNE-MIX" "s"
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue PRUNE-MIX --session s --turn 1 --tool Bash --tool-input-json '{}' >/dev/null
  GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue PRUNE-MIX --session s --turn 2 --tool Bash --tool-input-json '{}' >/dev/null
  # Age one of them back; keep the other recent.
  sqlite3 "$tmp" "UPDATE session_state_snapshot SET snapshot_at=datetime('now','-30 days') WHERE turn_id=1"
  GATEWAY_DB="$tmp" python3 -m lib.snapshot prune --days 7 >/dev/null
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='PRUNE-MIX'")
  assert_eq 1 "$n"
  kept=$(sqlite3 "$tmp" "SELECT turn_id FROM session_state_snapshot WHERE issue_id='PRUNE-MIX'")
  assert_eq 2 "$kept"
  cleanup_db "$tmp"
end_test

start_test "latest_returns_highest_id"
  tmp=$(fresh_db)
  seed_session "$tmp" "LAT" "s"
  cd "$REPO_ROOT/scripts"
  for i in 1 2 3; do
    GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue LAT --session s --turn $i --tool Bash --tool-input-json "{\"n\":$i}" >/dev/null
  done
  out=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot latest --issue LAT)
  assert_contains "$out" '"turn_id": 3'
  cleanup_db "$tmp"
end_test

start_test "latest_returns_null_on_missing_issue"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  rc=0
  out=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot latest --issue NOPE) || rc=$?
  assert_contains "$out" "null"
  assert_eq 1 "$rc"
  cleanup_db "$tmp"
end_test

# ─── Mutating tools all snapshot; read-only don't ──────────────────────────
start_test "hook_snapshots_Edit_Write_Task_but_not_Read_Grep_Glob_LS"
  tmp=$(fresh_db)
  seed_session "$tmp" "MIX" "s"
  # Mutating
  for t in Bash Edit Write Task; do
    echo '{"tool_name":"'$t'","tool_input":{"x":1}}' | \
      GATEWAY_DB="$tmp" ISSUE_ID=MIX CLAUDE_SESSION_ID=s TURN_ID=1 \
      bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh"
  done
  mutating=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='MIX'")
  assert_eq 4 "$mutating"
  # Read-only
  for t in Read Grep Glob LS ToolSearch; do
    echo '{"tool_name":"'$t'","tool_input":{}}' | \
      GATEWAY_DB="$tmp" ISSUE_ID=MIX CLAUDE_SESSION_ID=s TURN_ID=1 \
      bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh"
  done
  total=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='MIX'")
  assert_eq 4 "$total"
  cleanup_db "$tmp"
end_test
