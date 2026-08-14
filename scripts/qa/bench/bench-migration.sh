#!/usr/bin/env bash
# Migration latency on a production-shaped DB (10K+ rows across 5 tables).
#
# Verifies that the schema_versioning migration completes quickly on a DB
# with realistic row counts. Anything over 5s on a fresh build suggests
# missing indices or accidental full-table rewrites.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"
source "$REPO_ROOT/scripts/qa/lib/bench.sh"

export QA_SUITE_NAME="bench-migration"

start_test "migration_006_on_10k_row_legacy_db"
  tmp=$(mktemp --suffix=.db)
  # Legacy schema (no schema_version columns).
  sqlite3 "$tmp" "
    CREATE TABLE sessions (issue_id TEXT PRIMARY KEY, issue_title TEXT, session_id TEXT, cost_usd REAL);
    CREATE TABLE session_log (id INTEGER PRIMARY KEY, issue_id TEXT, outcome TEXT);
    CREATE TABLE session_transcripts (id INTEGER PRIMARY KEY, issue_id TEXT, content TEXT);
    CREATE TABLE execution_log (id INTEGER PRIMARY KEY, issue_id TEXT, device TEXT NOT NULL, command TEXT NOT NULL);
    CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, issue_id TEXT, tool_name TEXT NOT NULL);
    CREATE TABLE agent_diary (id INTEGER PRIMARY KEY, agent_name TEXT NOT NULL, entry TEXT NOT NULL);
    CREATE TABLE session_trajectory (id INTEGER PRIMARY KEY, issue_id TEXT NOT NULL);
    CREATE TABLE session_judgment (id INTEGER PRIMARY KEY, issue_id TEXT NOT NULL);
    CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, name TEXT, applied_at TEXT, filename TEXT);
    INSERT INTO schema_migrations VALUES ('004','x','2026','x');
    INSERT INTO schema_migrations VALUES ('005','x','2026','x');
  "
  # Seed 10K rows distributed across versioned tables. Stream SQL via stdin
  # to avoid "Argument list too long" on big shells.
  python3 -c "
print('BEGIN;')
for i in range(2000):
    print(f\"INSERT INTO sessions VALUES ('ISS-{i}','t','s',0.05);\")
for i in range(3000):
    print(f\"INSERT INTO session_log (issue_id, outcome) VALUES ('ISS-{i%2000}','done');\")
for i in range(3000):
    print(f\"INSERT INTO session_transcripts (issue_id, content) VALUES ('ISS-{i%2000}','c{i}');\")
for i in range(2000):
    print(f\"INSERT INTO execution_log (issue_id, device, command) VALUES ('ISS-{i%2000}','d','cmd{i}');\")
print('COMMIT;')
" | sqlite3 "$tmp"

  # Benchmark: run the migration, capture duration.
  data=$(bench_time_ms 1 migration_006_on_10k_rows -- env GATEWAY_DB="$tmp" \
    python3 "$REPO_ROOT/scripts/migrations/apply.py")
  duration_ms=$(printf '%s' "$data" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["p50"])')
  [ "${QA_VERBOSE:-0}" = "1" ] && echo "    migration_on_10k_rows = ${duration_ms}ms" >&2

  # Verify the migration actually added the column.
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('sessions') WHERE name='schema_version'")
  assert_eq 1 "$n"
  # Verify rows got backfilled.
  null_rows=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sessions WHERE schema_version IS NULL")
  assert_eq 0 "$null_rows"

  # Soft perf assertion: should complete in <30s on any reasonable hardware.
  assert_lt "$duration_ms" "30000" "migration_006 on 10K rows should take <30s"

  rm -f "$tmp"
end_test
