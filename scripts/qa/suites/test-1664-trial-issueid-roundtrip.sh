#!/usr/bin/env bash
# IFRNLLEI01PRD-1664/1666 — regression guard for the trial issue_id WRITE path.
# The empty-issue_id (pre-MR!155) and quoted-issue_id (pre-MR!156) defects both wrote
# session_trial_assignment rows that could not join session_judgment on issue_id, silently
# starving every A/B trial (the ~2.5-month dark pipeline). prompt-trial-assign.py must
# normalize at the write point: quoted -> clean, empty -> skip (no junk row).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1664-trial-issueid-roundtrip"

# seed an isolated DB with one active trial on a real judged dimension
seed_trial() {
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$1" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate
start_trial('build-prompt','evidence_based',[Candidate(0,'t','instr','c')],baseline_mean=3.0)"
}
# assign <db> <raw-issue-arg> and echo the DISTINCT issue_id(s) stored (or EMPTY)
stored_id() {
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$1" python3 prompt-trial-assign.py --issue "$2" --surface build-prompt >/dev/null 2>&1
  sqlite3 "$1" "SELECT COALESCE(GROUP_CONCAT(DISTINCT issue_id),'EMPTY') FROM session_trial_assignment"
}

start_test "quoted_issue_id_is_stored_without_quotes"
  tmp=$(fresh_db); seed_trial "$tmp"
  assert_eq "IFRNLLEI01PRD-999" "$(stored_id "$tmp" '"IFRNLLEI01PRD-999"')"
  cleanup_db "$tmp"
end_test

start_test "empty_quoted_issue_id_writes_no_row"
  tmp=$(fresh_db); seed_trial "$tmp"
  stored_id "$tmp" '""' >/dev/null
  assert_eq "0" "$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_trial_assignment")"
  cleanup_db "$tmp"
end_test

start_test "clean_issue_id_stored_clean"
  tmp=$(fresh_db); seed_trial "$tmp"
  assert_eq "IFRNLLEI01PRD-777" "$(stored_id "$tmp" 'IFRNLLEI01PRD-777')"
  cleanup_db "$tmp"
end_test
