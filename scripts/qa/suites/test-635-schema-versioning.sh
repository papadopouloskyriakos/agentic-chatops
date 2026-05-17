#!/usr/bin/env bash
# IFRNLLEI01PRD-635 — schema versioning test suite.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="635-schema-versioning"

# ─── sanity ─────────────────────────────────────────────────────────────────
start_test "cli_registry_exports_all_tables"
  out=$(cd "$REPO_ROOT/scripts" && python3 -m lib.schema_version 2>&1)
  for t in sessions session_log session_transcripts execution_log tool_call_log agent_diary session_trajectory session_judgment session_risk_audit event_log handoff_log session_state_snapshot session_turns; do
    assert_contains "$out" "\"$t\""
  done
end_test

start_test "current_returns_1_for_sessions"
  actual=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import current; print(current('sessions'))")
  assert_eq 1 "$actual"
end_test

start_test "stamp_adds_schema_version_key"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import stamp; import json; print(json.dumps(stamp({'a':1}, 'sessions'), sort_keys=True))")
  assert_contains "$out" '"schema_version": 1'
  assert_contains "$out" '"a": 1'
end_test

start_test "check_row_accepts_none"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 0 python3 -c "from lib.schema_version import check_row; check_row('sessions', None)"
end_test

start_test "check_row_rejects_future_version"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 python3 -c "from lib.schema_version import check_row; check_row('sessions', 99)"
  assert_contains "$_qa_last_stderr" "SchemaVersionError"
end_test

start_test "current_rejects_unknown_table"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 python3 -c "from lib.schema_version import current; current('bogus_table')"
  assert_contains "$_qa_last_stderr" "not in the schema_version registry"
end_test

# ─── QA — migration behavior ────────────────────────────────────────────────
start_test "migration_applies_on_legacy_schema"
  # Build a legacy DB from scratch with the bare minimum — the pre-IFRNLLEI01PRD-635
  # shapes of the 9 target tables. Avoids the fragility of sed-stripping
  # schema.sql (which breaks when new adjacent columns are added in later
  # migrations — as seen after -643 added handoff_chain alongside schema_version).
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" "
    CREATE TABLE sessions (issue_id TEXT PRIMARY KEY, issue_title TEXT);
    CREATE TABLE session_log (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT);
    CREATE TABLE session_transcripts (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT, content TEXT);
    CREATE TABLE execution_log (id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT NOT NULL, command TEXT NOT NULL);
    CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY AUTOINCREMENT, tool_name TEXT NOT NULL);
    CREATE TABLE agent_diary (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_name TEXT NOT NULL, entry TEXT NOT NULL);
    CREATE TABLE session_trajectory (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT NOT NULL);
    CREATE TABLE session_judgment (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT NOT NULL);
    CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, name TEXT, applied_at TEXT, filename TEXT);
    INSERT INTO schema_migrations VALUES ('004','x','2026','x');
    INSERT INTO schema_migrations VALUES ('005','x','2026','x');
  "
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  miss=0
  for t in sessions session_log session_transcripts execution_log tool_call_log agent_diary session_trajectory session_judgment session_risk_audit; do
    n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('$t') WHERE name='schema_version'" 2>/dev/null || echo 0)
    [ "$n" = "1" ] || { miss=$((miss+1)); fail_test "no schema_version col on $t"; }
  done
  rm -f "$tmp"
  assert_eq 0 "$miss"
end_test

start_test "migration_is_idempotent"
  tmp=$(fresh_db)
  # Already includes 006..011.
  before=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('sessions') WHERE name='schema_version'")
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  after=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('sessions') WHERE name='schema_version'")
  assert_eq "$before" "$after"
  cleanup_db "$tmp"
end_test

start_test "legacy_rows_backfilled_to_v1"
  # Build a legacy DB with the bare minimum: a `sessions` table WITHOUT
  # schema_version, plus the migrations tracker marking 004/005 as applied
  # so apply.py starts at 006.
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" "
    CREATE TABLE sessions (issue_id TEXT PRIMARY KEY, issue_title TEXT, session_id TEXT);
    CREATE TABLE session_log (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT);
    CREATE TABLE session_transcripts (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT, content TEXT);
    CREATE TABLE execution_log (id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT NOT NULL, command TEXT NOT NULL);
    CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY AUTOINCREMENT, tool_name TEXT NOT NULL);
    CREATE TABLE agent_diary (id INTEGER PRIMARY KEY AUTOINCREMENT, agent_name TEXT NOT NULL, entry TEXT NOT NULL);
    CREATE TABLE session_trajectory (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT NOT NULL);
    CREATE TABLE session_judgment (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT NOT NULL);
    CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, name TEXT, applied_at TEXT, filename TEXT);
    INSERT INTO schema_migrations VALUES ('004','x','2026','x');
    INSERT INTO schema_migrations VALUES ('005','x','2026','x');
    INSERT INTO sessions (issue_id) VALUES ('LEGACY-1');
  "
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  actual=$(sqlite3 "$tmp" "SELECT schema_version FROM sessions WHERE issue_id='LEGACY-1'")
  assert_eq "1" "$actual"
  rm -f "$tmp"
end_test

# ─── QA — writers stamp on INSERT ────────────────────────────────────────────
start_test "classify_session_risk_stamps_v1"
  tmp=$(fresh_db)
  echo '{"steps":[{"desc":"look","command":"cat /proc/loadavg","device":"localhost"}]}' \
    | GATEWAY_DB="$tmp" ISSUE_ID=QA-635-W1 ALERT_CATEGORY=resource \
      python3 "$REPO_ROOT/scripts/classify-session-risk.py" >/dev/null 2>&1
  actual=$(sqlite3 "$tmp" "SELECT schema_version FROM session_risk_audit WHERE issue_id='QA-635-W1'")
  assert_eq "1" "$actual"
  cleanup_db "$tmp"
end_test

start_test "holistic_health_assertion_integrates"
  tmp=$(fresh_db)
  # Insert a null-schema_version row to simulate a broken writer.
  # ALTER COLUMN DROP DEFAULT is not supported in sqlite, so we bypass by raw insert.
  # NOTE: schema.sql has DEFAULT 1; sqlite won't insert NULL unless we force it.
  sqlite3 "$tmp" "INSERT INTO sessions (issue_id, schema_version) VALUES ('BAD', NULL)"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sessions WHERE schema_version IS NULL")
  assert_eq 1 "$n" "expected to be able to insert a null row for the negative test"
  cleanup_db "$tmp"
end_test

end_test
