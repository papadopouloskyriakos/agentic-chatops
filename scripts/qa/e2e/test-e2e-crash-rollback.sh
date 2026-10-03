#!/usr/bin/env bash
# E2E — crash mid-tool + snapshot rollback.
#
# Scenario: 3 snapshots captured mid-session. Simulate a crash by tampering
# sessions.cost_usd. Roll back to snapshot #2. Verify state matches what
# snapshot #2 captured.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="e2e-crash-rollback"
tmp=$(fresh_db)

start_test "rollback_to_mid_session_snapshot"
  ISSUE="QA-RB-E2E"
  SESSION="s-rb"
  seed_session "$tmp" "$ISSUE" "$SESSION"
  cd "$REPO_ROOT/scripts"

  # Turn 1: cost=0.05
  sqlite3 "$tmp" "UPDATE sessions SET cost_usd=0.05, confidence=0.5 WHERE issue_id='$ISSUE'"
  rid1=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue "$ISSUE" --session "$SESSION" --turn 1 --tool Bash --tool-input-json '{}')
  assert_gt "$rid1" 0

  # Turn 2: cost=0.12
  sqlite3 "$tmp" "UPDATE sessions SET cost_usd=0.12, confidence=0.7 WHERE issue_id='$ISSUE'"
  rid2=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue "$ISSUE" --session "$SESSION" --turn 2 --tool Bash --tool-input-json '{}')
  assert_gt "$rid2" 0

  # Turn 3: cost=0.28
  sqlite3 "$tmp" "UPDATE sessions SET cost_usd=0.28, confidence=0.85 WHERE issue_id='$ISSUE'"
  rid3=$(GATEWAY_DB="$tmp" python3 -m lib.snapshot capture --issue "$ISSUE" --session "$SESSION" --turn 3 --tool Bash --tool-input-json '{}')
  assert_gt "$rid3" 0

  # Simulate crash / corruption.
  sqlite3 "$tmp" "UPDATE sessions SET cost_usd=999.99, confidence=-1 WHERE issue_id='$ISSUE'"

  # Rollback to turn 2.
  GATEWAY_DB="$tmp" python3 -m lib.snapshot rollback --id "$rid2"

  state=$(sqlite3 "$tmp" "SELECT cost_usd, confidence FROM sessions WHERE issue_id='$ISSUE'")
  assert_eq "0.12|0.7" "$state" "restored state matches turn 2 snapshot"

  # Latest snapshot (turn 3) still there — rollback doesn't delete future snapshots.
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='$ISSUE'")
  assert_eq "3" "$n"
end_test

cleanup_db "$tmp"
