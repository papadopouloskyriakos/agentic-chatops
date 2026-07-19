#!/usr/bin/env bash
# IFRNLLEI01PRD-748 — Long-horizon reasoning replay eval (G1.P0.1).
#
# Smoke + integration tests for `scripts/long-horizon-replay.py`. Closes
# NVIDIA dim #9 (data flywheel evaluation pillar — long-horizon component).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="748-long-horizon-replay"
SCRIPT="$REPO_ROOT/scripts/long-horizon-replay.py"
MIGRATION="$REPO_ROOT/scripts/migrations/015_long_horizon_replay.sql"

# ─── T1 script + migration files exist ─────────────────────────────────────
start_test "files_exist"
  if [ ! -f "$SCRIPT" ]; then
    fail_test "missing $SCRIPT"
  elif [ ! -f "$MIGRATION" ]; then
    fail_test "missing $MIGRATION"
  fi
end_test

# ─── T2 script parses cleanly with python ──────────────────────────────────
start_test "script_parses"
  rc=0
  python3 -m py_compile "$SCRIPT" >/dev/null 2>&1 || rc=$?
  assert_eq 0 "$rc" "py_compile failed"
end_test

# ─── T3 migration creates the table on a fresh DB ──────────────────────────
start_test "migration_creates_table"
  tmp=$(fresh_db)
  sqlite3 "$tmp" < "$MIGRATION"
  cnt=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='long_horizon_replay_results'")
  assert_eq "1" "$cnt" "table not created"
  cleanup_db "$tmp"
end_test

# ─── T4 migration is idempotent (no error if applied twice) ────────────────
start_test "migration_idempotent"
  tmp=$(fresh_db)
  rc=0
  sqlite3 "$tmp" < "$MIGRATION" || rc=$?
  sqlite3 "$tmp" < "$MIGRATION" || rc=$?
  assert_eq 0 "$rc" "second apply errored"
  cleanup_db "$tmp"
end_test

# ─── T5 dry-run on empty DB returns 0 and produces JSON summary ────────────
start_test "dry_run_empty_db"
  tmp=$(fresh_db)
  sqlite3 "$tmp" < "$MIGRATION"
  rc=0
  out=$(GATEWAY_DB="$tmp" python3 "$SCRIPT" --dry-run --limit 5 --json --db "$tmp" 2>&1) || rc=$?
  assert_eq 0 "$rc" "exit code"
  assert_contains "$out" '"scored_count": 0' "scored_count missing"
  assert_contains "$out" '"dry_run": true' "dry_run flag missing"
  cleanup_db "$tmp"
end_test

# ─── T6 schema versioning stamp ────────────────────────────────────────────
start_test "schema_version_stamped_on_insert"
  tmp=$(fresh_db)
  sqlite3 "$tmp" < "$MIGRATION"
  # Seed one session + one transcript chunk + a tool_call_log row so
  # candidate_sessions returns at least one row.
  sqlite3 "$tmp" "INSERT INTO sessions (issue_id, session_id, num_turns, duration_seconds, cost_usd, schema_version) \
                  VALUES ('TEST-1','sess-test',5,300,0.05,1);"
  sqlite3 "$tmp" "INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, schema_version) \
                  VALUES ('TEST-1','sess-test',0,'assistant','first reply about disk',1);"
  sqlite3 "$tmp" "INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, schema_version) \
                  VALUES ('TEST-1','sess-test',1,'assistant','followup about disk space',1);"
  sqlite3 "$tmp" "INSERT INTO tool_call_log (session_id, issue_id, tool_name, schema_version) VALUES ('sess-test','TEST-1','Bash',1);"
  rc=0
  GATEWAY_DB="$tmp" python3 "$SCRIPT" --limit 5 --db "$tmp" >/dev/null 2>&1 || rc=$?
  assert_eq 0 "$rc" "replay script errored"
  ver=$(sqlite3 "$tmp" "SELECT schema_version FROM long_horizon_replay_results LIMIT 1")
  assert_eq "1" "$ver" "schema_version not stamped"
  composite=$(sqlite3 "$tmp" "SELECT composite_score FROM long_horizon_replay_results LIMIT 1")
  # any numeric in [0,1] ok
  assert_ge "$composite" "0.0" "composite below 0"
  assert_lt "$composite" "1.01" "composite above 1"
  cleanup_db "$tmp"
end_test

# ─── T7 candidate ordering by num_turns DESC ───────────────────────────────
start_test "candidates_ordered_by_num_turns_desc"
  tmp=$(fresh_db)
  sqlite3 "$tmp" < "$MIGRATION"
  sqlite3 "$tmp" "INSERT INTO sessions (issue_id, session_id, num_turns, cost_usd, schema_version) VALUES ('A','s-a',2,0.01,1);"
  sqlite3 "$tmp" "INSERT INTO sessions (issue_id, session_id, num_turns, cost_usd, schema_version) VALUES ('B','s-b',9,0.05,1);"
  sqlite3 "$tmp" "INSERT INTO sessions (issue_id, session_id, num_turns, cost_usd, schema_version) VALUES ('C','s-c',5,0.02,1);"
  GATEWAY_DB="$tmp" python3 "$SCRIPT" --limit 3 --db "$tmp" >/dev/null 2>&1
  first=$(sqlite3 "$tmp" "SELECT issue_id FROM long_horizon_replay_results ORDER BY id ASC LIMIT 1")
  assert_eq "B" "$first" "first replayed session should be 'B' (num_turns=9)"
  cleanup_db "$tmp"
end_test

# ─── T8 schema_version registry has the table ──────────────────────────────
start_test "schema_version_registry_has_entry"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION; print(CURRENT_SCHEMA_VERSION.get('long_horizon_replay_results', 'MISSING'))")
  assert_eq "1" "$out" "schema_version registry missing long_horizon_replay_results"
end_test
