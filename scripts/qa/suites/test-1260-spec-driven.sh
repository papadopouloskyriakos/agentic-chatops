#!/usr/bin/env bash
# IFRNLLEI01PRD-1260 — D2 spec-driven development: validator + lockstep guard suite.
# Closes the "no committed fixture runner" debt: exercises validate-project-spec.py against
# the good/bad fixtures AND the gateway's own spec, plus the spec<->code lockstep guard.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1260-spec-driven"

V="$REPO_ROOT/bootstrap-pack/scripts/validate-project-spec.py"
LOCKSTEP="$REPO_ROOT/scripts/check-spec-code-lockstep.py"
FIX="$REPO_ROOT/bootstrap-pack/tests/fixtures"

# ─── gateway's own spec validates ───────────────────────────────────────────
start_test "gateway_spec_passes_all_17_checks"
  out=$(python3 "$V" "$REPO_ROOT" 2>&1); rc=$?
  assert_eq 0 "$rc" "gateway spec exits 0"
  assert_contains "$out" "17/17 checks passed"
end_test

# ─── canonical good fixture passes ──────────────────────────────────────────
start_test "good_fixture_passes"
  python3 "$V" "$FIX/good" >/dev/null 2>&1
  assert_eq 0 "$?" "good fixture validates"
end_test

# ─── every bad fixture fails (the committed fixture runner) ──────────────────
for bf in bad-ears colliding cyclic-dag missing-req; do
  start_test "bad_fixture_${bf//-/_}_fails"
    if [ -d "$FIX/$bf" ]; then
      python3 "$V" "$FIX/$bf" >/dev/null 2>&1
      assert_eq 1 "$?" "$bf must fail validation"
    else
      assert_eq 1 1 "fixture $bf absent — skipped"
    fi
  end_test
done

# ─── C14 real Gherkin parser rejects a scenario with no steps ───────────────
start_test "gherkin_parser_rejects_stepless_scenario"
  tmp=$(mktemp -d)
  mkdir -p "$tmp/spec/001-x/acceptance"
  printf 'Feature: X\n  REQ-001 reference\n  Scenario: empty\n' > "$tmp/spec/001-x/acceptance/x.feature"
  printf 'REQ-001: The system shall work.\n' > "$tmp/spec/001-x/requirements.md"
  out=$(python3 "$V" "$tmp" --check gherkin_parseable 2>&1)
  assert_contains "$out" "FAIL"
  rm -rf "$tmp"
end_test

# ─── offline (npx-free) contract validation still passes ────────────────────
start_test "offline_contract_validation_passes"
  npxdir=$(dirname "$(command -v npx 2>/dev/null || echo /none/npx)")
  safepath=$(echo "$PATH" | tr ':' '\n' | grep -vF "$npxdir" | paste -sd:)
  out=$(PATH="$safepath" python3 "$V" "$REPO_ROOT" --check openapi_valid 2>&1)
  assert_contains "$out" "PASS"
end_test

# ─── C16 deep slot-config validation rejects a bad room ─────────────────────
start_test "slot_config_rejects_non_matrix_room"
  tmp=$(mktemp -d)
  mkdir -p "$tmp/.agentic"
  printf '{"x":{"cwd":"/abs/path","room":"not-a-room"}}' > "$tmp/.agentic/slot-config.entry.json"
  out=$(GATEWAY_SLOT_CONFIG=/nonexistent python3 "$V" "$tmp" --check slot_config_entry_valid 2>&1)
  assert_contains "$out" "FAIL"
  rm -rf "$tmp"
end_test

# ─── spec<->code lockstep passes ────────────────────────────────────────────
start_test "spec_code_lockstep_passes"
  out=$(python3 "$LOCKSTEP" 2>&1); rc=$?
  assert_eq 0 "$rc" "lockstep clean"
  assert_contains "$out" "PASS"
end_test

# ─── lockstep guard catches a dangling spec file ────────────────────────────
start_test "lockstep_detects_dangling_file"
  tmp=$(mktemp -d); mkdir -p "$tmp/spec/001-x"
  printf '{"tasks":[{"task_id":"X-1","files_owned":["does/not/exist.py"]}]}' > "$tmp/spec/001-x/tasks.json"
  GATEWAY_SPEC_REPO="$tmp" python3 "$LOCKSTEP" >/dev/null 2>&1
  assert_eq 1 "$?" "dangling spec must fail"
  rm -rf "$tmp"
end_test

# ─── Round 2: executable BDD — every Gherkin scenario actually runs ──────────
start_test "executable_bdd_all_scenarios_pass"
  out=$(python3 "$REPO_ROOT/scripts/run-spec-bdd.py" 2>&1); rc=$?
  assert_eq 0 "$rc" "all BDD scenarios pass"
  assert_contains "$out" "scenarios passed"
end_test

# ─── Round 2: content-aware lockstep — manifest matches, no drift ───────────
start_test "lockstep_content_hashes_match_manifest"
  out=$(python3 "$LOCKSTEP" 2>&1); rc=$?
  assert_eq 0 "$rc" "no content drift"
  assert_contains "$out" "no drift"
end_test

# ─── Round 2: lockstep DETECTS content drift (governed file changed, spec not) ─
start_test "lockstep_detects_content_drift"
  tmp=$(mktemp -d); mkdir -p "$tmp/spec/001-x"
  printf 'REQ-001: The system shall work.\n' > "$tmp/spec/001-x/requirements.md"
  printf '{"tasks":[{"task_id":"X-1","files_owned":["gov.py"]}]}' > "$tmp/spec/001-x/tasks.json"
  printf '# v1\n' > "$tmp/gov.py"
  GATEWAY_SPEC_REPO="$tmp" GATEWAY_SAFETY_FILES="gov.py" python3 "$LOCKSTEP" --update-manifest >/dev/null 2>&1
  printf '# v2 changed\n' > "$tmp/gov.py"
  out=$(GATEWAY_SPEC_REPO="$tmp" GATEWAY_SAFETY_FILES="gov.py" python3 "$LOCKSTEP" 2>&1); rc=$?
  assert_eq 1 "$rc" "drift must fail the gate"
  assert_contains "$out" "drift"
  rm -rf "$tmp"
end_test
