#!/bin/bash
# test-qa-harness-subshell.sh — the assert lib itself: a failure inside a `( … )` subshell MUST be
# recorded (TG-403, found porting IFRNLLEI01PRD-1824 to TG). Before the failmark fix, fail_test wrote
# only a shell variable, the subshell discarded it, and 7 live assertions in
# test-1824-mutation-shadow-mode could never fail — two full rounds of mutation testing ran against an
# oracle that could not go red. This suite is that killing mutation kept in-band: revert the lib's
# failmark mechanism and subshell_assert_failure_is_recorded goes red here, forever.
# QA_SUITE_TIMEOUT: 30
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-qa-harness-subshell"

# Run one inner test case in a THROWAWAY harness (own bash, own result file) and print its JSONL.
_inner_run() { # $1 = snippet run between start_test/end_test in the inner harness
  local tmp
  tmp="$(mktemp)"
  bash -c '
    set -u
    QA_RESULT_FILE="$1"; export QA_RESULT_FILE
    QA_SUITE_NAME=inner; export QA_SUITE_NAME
    source "$2/scripts/qa/lib/assert.sh"
    start_test inner_case
    eval "$3"
    end_test
  ' _ "$tmp" "$REPO_ROOT" "$1" >/dev/null 2>&1
  cat "$tmp"
  rm -f "$tmp" "$tmp".*
}

# ── the defect: a subshell assert failure must reach the record ───────────────
start_test "subshell_assert_failure_is_recorded"
OUT="$(_inner_run '( assert_eq AAA BBB "deliberate subshell failure" )')"
assert_contains "$OUT" '"status": "FAIL"' "a failing assert inside ( ) must record FAIL, not PASS"
assert_contains "$OUT" 'deliberate subshell failure' "the FAIL record must carry the subshell's own detail"
end_test

# ── anti-vacuity: a passing subshell assert must still be PASS ────────────────
start_test "subshell_passing_assert_stays_pass"
OUT="$(_inner_run '( assert_eq AAA AAA "same" )')"
assert_contains "$OUT" '"status": "PASS"' "a passing subshell test must not be poisoned by the mark files"
end_test

# ── regression floor: plain (non-subshell) failure path unchanged ─────────────
start_test "parent_shell_failure_still_recorded"
OUT="$(_inner_run 'assert_eq AAA BBB "plain failure"')"
assert_contains "$OUT" '"status": "FAIL"' "the ordinary failure path must keep working"
end_test

# ── skip parity: skip_test from a subshell must record SKIP ───────────────────
start_test "subshell_skip_is_recorded"
OUT="$(_inner_run '( skip_test "skipped from a subshell" )')"
assert_contains "$OUT" '"status": "SKIP"' "a subshelled skip_test must record SKIP, not PASS"
end_test
