#!/usr/bin/env bash
# Assertion helpers for the QA suite.
#
# Contract: each test file sources this lib, declares its tests with
# `start_test <name>` / `assert_...`, and the helpers themselves manage
# the per-test pass/fail state. A test that never reaches `end_test`
# because an assertion aborted is still recorded — the EXIT trap in the
# runner catches it.
#
# All assertions write one JSONL line per call to $QA_RESULT_FILE so the
# run-qa-suite.sh orchestrator can roll up a scorecard.

# shellcheck shell=bash
set -u

QA_TEST_NAME="${QA_TEST_NAME:-unknown}"
QA_SUITE_NAME="${QA_SUITE_NAME:-unknown}"
QA_RESULT_FILE="${QA_RESULT_FILE:-/tmp/qa-results.jsonl}"

# Per-test state (reset on start_test).
: "${_qa_test_started:=0}"
: "${_qa_test_failed:=0}"
: "${_qa_test_skipped:=0}"
: "${_qa_t_begin_ms:=0}"

_now_ms() { python3 -c 'import time; print(int(time.time()*1000))'; }

_emit_record() {
  # Args: status(PASS|FAIL|SKIP) detail(string)
  local status="$1" detail="${2:-}"
  local now duration_ms
  now=$(_now_ms)
  duration_ms=$(( now - _qa_t_begin_ms ))
  [ "$_qa_t_begin_ms" -eq 0 ] && duration_ms=0
  python3 -c '
import json,sys
print(json.dumps({
  "suite": sys.argv[1],
  "test":  sys.argv[2],
  "status": sys.argv[3],
  "detail": sys.argv[4],
  "duration_ms": int(sys.argv[5]),
}))
' "$QA_SUITE_NAME" "$QA_TEST_NAME" "$status" "$detail" "$duration_ms" \
    >> "$QA_RESULT_FILE"
}

# --------------------------------------------------------------------------
# Test lifecycle
# --------------------------------------------------------------------------

start_test() {
  QA_TEST_NAME="$1"
  _qa_test_started=1
  _qa_test_failed=0
  _qa_test_skipped=0
  _qa_t_begin_ms=$(_now_ms)
  [ "${QA_VERBOSE:-0}" = "1" ] && printf "  . %s::%s\n" "$QA_SUITE_NAME" "$QA_TEST_NAME" >&2
}

end_test() {
  if [ "$_qa_test_started" -eq 0 ]; then return 0; fi
  if   [ "$_qa_test_failed"  -eq 1 ]; then _emit_record FAIL "${_qa_fail_detail:-}" ; \
         printf "  \e[31mFAIL\e[0m %s::%s — %s\n" "$QA_SUITE_NAME" "$QA_TEST_NAME" "${_qa_fail_detail:-}" >&2
  elif [ "$_qa_test_skipped" -eq 1 ]; then _emit_record SKIP "${_qa_skip_detail:-}" ; \
         [ "${QA_VERBOSE:-0}" = "1" ] && printf "  \e[36mSKIP\e[0m %s::%s — %s\n" "$QA_SUITE_NAME" "$QA_TEST_NAME" "${_qa_skip_detail:-}" >&2
  else                                     _emit_record PASS "" ; \
         [ "${QA_VERBOSE:-0}" = "1" ] && printf "  \e[32mPASS\e[0m %s::%s\n" "$QA_SUITE_NAME" "$QA_TEST_NAME" >&2
  fi
  _qa_test_started=0
  _qa_fail_detail=""
  _qa_skip_detail=""
}

skip_test() {
  _qa_test_skipped=1
  _qa_skip_detail="${1:-skipped}"
}

fail_test() {
  _qa_test_failed=1
  _qa_fail_detail="${1:-fail}"
}

# --------------------------------------------------------------------------
# Assertions. Each sets _qa_test_failed on miss, records a detail, and
# continues (tests can chain multiple checks).
# --------------------------------------------------------------------------

assert_eq() {
  local expected="$1" actual="$2" msg="${3:-assert_eq}"
  if [ "$expected" != "$actual" ]; then
    fail_test "${msg}: expected=$(printf %q "$expected") actual=$(printf %q "$actual")"
  fi
}

assert_ne() {
  local a="$1" b="$2" msg="${3:-assert_ne}"
  if [ "$a" = "$b" ]; then
    fail_test "${msg}: both=$(printf %q "$a")"
  fi
}

assert_gt() {
  local a="$1" b="$2" msg="${3:-assert_gt}"
  if [ "$(python3 -c "print(1 if float('$a') > float('$b') else 0)")" != "1" ]; then
    fail_test "${msg}: not ($a > $b)"
  fi
}

assert_ge() {
  local a="$1" b="$2" msg="${3:-assert_ge}"
  if [ "$(python3 -c "print(1 if float('$a') >= float('$b') else 0)")" != "1" ]; then
    fail_test "${msg}: not ($a >= $b)"
  fi
}

assert_lt() {
  local a="$1" b="$2" msg="${3:-assert_lt}"
  if [ "$(python3 -c "print(1 if float('$a') < float('$b') else 0)")" != "1" ]; then
    fail_test "${msg}: not ($a < $b)"
  fi
}

assert_contains() {
  local haystack="$1" needle="$2" msg="${3:-assert_contains}"
  if ! printf '%s' "$haystack" | grep -qF -- "$needle"; then
    fail_test "${msg}: needle=$(printf %q "$needle") not in haystack (len=${#haystack})"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" msg="${3:-assert_not_contains}"
  if printf '%s' "$haystack" | grep -qF -- "$needle"; then
    fail_test "${msg}: needle=$(printf %q "$needle") unexpectedly present"
  fi
}

assert_file_exists() {
  local p="$1" msg="${2:-assert_file_exists}"
  if [ ! -f "$p" ]; then fail_test "${msg}: missing $p"; fi
}

assert_exit_code() {
  # Usage: assert_exit_code 2 bash some-script args ...
  # CRITICAL: never manipulate set -e / set -u here. The suites set neither
  # (only `set -u` to catch unset vars in test code itself), and errexit
  # leaking across assertions has been the #1 source of ghost test losses.
  local expected="$1"; shift
  local rc=0
  "$@" >/tmp/qa_stdout.$$ 2>/tmp/qa_stderr.$$ || rc=$?
  local out err
  out=$(cat /tmp/qa_stdout.$$ 2>/dev/null || true)
  err=$(cat /tmp/qa_stderr.$$ 2>/dev/null || true)
  rm -f /tmp/qa_stdout.$$ /tmp/qa_stderr.$$
  if [ "$rc" != "$expected" ]; then
    fail_test "assert_exit_code: expected=$expected actual=$rc stderr=$(printf %q "${err:0:200}")"
  fi
  export _qa_last_stdout="$out"
  export _qa_last_stderr="$err"
}
