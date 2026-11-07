#!/usr/bin/env bash
# Harness² reuse R6 — flywheel identity check (scripts/check-flywheel-identity.py).
# Builds a throwaway DB with the five stage tables and asserts the three verdicts
# (ok / broken / idle), the duplicate-judgment detector and the textfile output.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="flywheel-identity"
CHK="$REPO_ROOT/scripts/check-flywheel-identity.py"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
DB="$TMP/t.db"

mkdb() {
  rm -f "$DB"
  sqlite3 "$DB" <<'SQL'
CREATE TABLE sessions (issue_id TEXT, session_id TEXT, started_at TEXT, last_active TEXT, paused INTEGER DEFAULT 0, model TEXT);
CREATE TABLE session_log (issue_id TEXT, session_id TEXT, started_at TEXT, ended_at TEXT, resolution_type TEXT);
CREATE TABLE session_judgment (issue_id TEXT, session_id TEXT, judged_at TEXT, overall_score REAL);
CREATE TABLE session_transcripts (issue_id TEXT, created_at TEXT);
CREATE TABLE lessons_learned (issue_id TEXT, lesson TEXT, verdict TEXT, created_at TEXT);
CREATE TABLE session_harness (session_id TEXT PRIMARY KEY, issue_id TEXT, harness_fp TEXT);
SQL
}
# a session that ended 5h ago (inside the 2h..26h window)
add_session() { # issue sid
  sqlite3 "$DB" "INSERT INTO session_log VALUES ('$1','$2', datetime('now','-6 hours'), datetime('now','-5 hours'), 'auto_resolved');"
}
complete_stages() { # issue sid
  sqlite3 "$DB" "INSERT INTO session_judgment VALUES ('$1','$2', datetime('now','-4 hours'), 4.0);
INSERT INTO session_transcripts VALUES ('$1', datetime('now','-4 hours'));
INSERT INTO lessons_learned VALUES ('$1','NO_ENTRY','no_entry', datetime('now','-4 hours'));
INSERT INTO session_harness VALUES ('$2','$1','abcd1234abcd1234');"
}

start_test "script_compiles"
  python3 -m py_compile "$CHK" || fail_test "py_compile failed"
end_test

start_test "identity_ok_when_every_stage_present"
  mkdb; add_session IFRNLLEI01PRD-1 s1; complete_stages IFRNLLEI01PRD-1 s1
  add_session IFRNLLEI01PRD-2 s2; complete_stages IFRNLLEI01PRD-2 s2
  out=$(python3 "$CHK" --db "$DB" --json); rc=$?
  assert_eq 0 "$rc" "exit code"
  assert_contains "$out" '"status": "ok"' "status ok"
  assert_contains "$out" '"eligible": 2' "two eligible"
end_test

start_test "broken_when_judge_and_archive_missing"
  mkdb; add_session IFRNLLEI01PRD-3 s3; add_session IFRNLLEI01PRD-4 s4
  sqlite3 "$DB" "INSERT INTO lessons_learned VALUES ('IFRNLLEI01PRD-3','x','entry',datetime('now','-4 hours'));"
  out=$(python3 "$CHK" --db "$DB" --json); rc=$?
  assert_eq 1 "$rc" "exit code"
  assert_contains "$out" '"status": "broken"' "status broken"
  assert_contains "$out" '"judged"' "judged listed"
  assert_contains "$out" '"archived"' "archived listed"
end_test

start_test "idle_when_no_session_in_window"
  mkdb
  sqlite3 "$DB" "INSERT INTO session_log VALUES ('IFRNLLEI01PRD-5','s5', datetime('now','-40 hours'), datetime('now','-39 hours'), 'completed');"
  out=$(python3 "$CHK" --db "$DB" --json); rc=$?
  assert_eq 3 "$rc" "exit code"
  assert_contains "$out" '"status": "idle"' "status idle"
  assert_contains "$out" '"closed_30d": 1' "30d counter sees the old session"
end_test

start_test "duplicate_judgments_break_identity"
  mkdb; add_session IFRNLLEI01PRD-6 s6; complete_stages IFRNLLEI01PRD-6 s6
  sqlite3 "$DB" "INSERT INTO session_judgment VALUES ('IFRNLLEI01PRD-6','s6', datetime('now','-3 hours'), 3.0);"
  out=$(python3 "$CHK" --db "$DB" --json); rc=$?
  assert_eq 1 "$rc" "exit code"
  assert_contains "$out" '"duplicate_judgments": 1' "dup count"
end_test

start_test "synthetic_and_cli_ids_are_excluded"
  mkdb; add_session cli-abc s7; add_session SYN-1 s8
  out=$(python3 "$CHK" --db "$DB" --json); rc=$?
  assert_eq 3 "$rc" "idle because both ids are excluded"
end_test

start_test "textfile_metrics_written"
  mkdb; add_session IFRNLLEI01PRD-9 s9; complete_stages IFRNLLEI01PRD-9 s9
  python3 "$CHK" --db "$DB" --out "$TMP/fw.prom" >/dev/null; rc=$?
  assert_eq 0 "$rc" "exit"
  assert_file_exists "$TMP/fw.prom"
  body=$(cat "$TMP/fw.prom")
  assert_contains "$body" 'gateway_flywheel_identity_ok 1' "ok gauge"
  assert_contains "$body" 'gateway_flywheel_stage_ratio{stage="judged"} 1' "stage ratio"
  assert_contains "$body" 'gateway_flywheel_last_run_timestamp_seconds' "timestamp"
end_test
