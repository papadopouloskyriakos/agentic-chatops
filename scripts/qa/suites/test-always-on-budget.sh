#!/usr/bin/env bash
# Harness² reuse R1 — always-on budget audit (scripts/audit-always-on-budget.sh).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="always-on-budget"
AUD="$REPO_ROOT/scripts/audit-always-on-budget.sh"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

start_test "bash_syntax"
  bash -n "$AUD" || fail_test "bash -n"
end_test

start_test "small_repo_is_ok"
  mkdir -p "$TMP/small/.claude/rules"; echo "hi" > "$TMP/small/CLAUDE.md"; echo "r" > "$TMP/small/.claude/rules/a.md"
  out=$(bash "$AUD" --json "$TMP/small"); rc=$?
  assert_eq 0 "$rc" "exit"
  assert_contains "$out" '"state":"ok"' "ok state"
  assert_contains "$out" '"rules_files":1' "rules counted"
end_test

start_test "over_fail_line_exits_1"
  mkdir -p "$TMP/big"; head -c 5000 /dev/zero | tr '\0' 'x' > "$TMP/big/CLAUDE.md"
  out=$(bash "$AUD" --json --warn 1000 --fail 4000 "$TMP/big"); rc=$?
  assert_eq 1 "$rc" "exit 1"
  assert_contains "$out" '"state":"fail"' "fail state"
end_test

start_test "between_warn_and_fail_is_warn_exit_0"
  mkdir -p "$TMP/mid"; head -c 2000 /dev/zero | tr '\0' 'x' > "$TMP/mid/CLAUDE.md"
  out=$(bash "$AUD" --json --warn 1000 --fail 4000 "$TMP/mid"); rc=$?
  assert_eq 0 "$rc" "exit 0"
  assert_contains "$out" '"state":"warn"' "warn state"
end_test

start_test "build_prompt_surface_is_measured_in_default_sweep"
  out=$(bash "$AUD" --json)
  assert_contains "$out" '"surface":"build-prompt"' "build prompt row present"
end_test

start_test "real_gateway_repo_is_reported"
  out=$(bash "$AUD" --json "$REPO_ROOT"); rc=$?
  assert_contains "$out" '"surface":"repo"' "repo row"
  # The gateway repo is far over the warn line today; the audit must say so, not hide it.
  assert_contains "$out" '"state":"fail"' "gateway CLAUDE.md+rules over the fail line (known, R1 finding)"
end_test
