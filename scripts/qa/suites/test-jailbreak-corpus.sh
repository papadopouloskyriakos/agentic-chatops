#!/usr/bin/env bash
# IFRNLLEI01PRD-748 — Jailbreak corpus regression suite (G1.P0.2).
#
# Drives every fixture in `scripts/qa/fixtures/jailbreak-corpus.json` through
# `scripts/lib/jailbreak_detector.py` and asserts that the detected category
# set matches `expected_categories` exactly. Regression-detector against the
# five NVIDIA-DLI-08 fragility vectors.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="748-jailbreak-corpus"
FIXTURE="$REPO_ROOT/scripts/qa/fixtures/jailbreak-corpus.json"
LIB="$REPO_ROOT/scripts/lib/jailbreak_detector.py"

# ─── T1 fixture file exists and parses ─────────────────────────────────────
start_test "fixture_file_exists_and_parses"
  if [ ! -f "$FIXTURE" ]; then
    fail_test "missing $FIXTURE"
  elif ! python3 -c "import json; json.load(open('$FIXTURE'))" 2>/dev/null; then
    fail_test "fixture JSON did not parse"
  fi
end_test

# ─── T2 fixture has ≥ 30 entries ───────────────────────────────────────────
start_test "fixture_has_thirty_plus_entries"
  count=$(python3 -c "import json; print(len(json.load(open('$FIXTURE'))['fixtures']))")
  if [ "$count" -ge 30 ]; then
    :
  else
    fail_test "expected ≥30 fixtures, got $count"
  fi
end_test

# ─── T3 detector library exists and parses ─────────────────────────────────
start_test "detector_lib_exists_and_parses"
  if [ ! -f "$LIB" ]; then
    fail_test "missing $LIB"
  elif ! python3 -m py_compile "$LIB" 2>/dev/null; then
    fail_test "py_compile failed"
  fi
end_test

# ─── T4 every fixture's expected_categories matches detector output ────────
start_test "all_fixtures_match_expected_categories"
  out=$(python3 - <<PY
import json, sys, importlib.util
spec = importlib.util.spec_from_file_location("jbd", "$LIB")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
data = json.load(open("$FIXTURE"))
mismatches = []
for fix in data["fixtures"]:
    expected = set(fix["expected_categories"])
    actual = m.categories_hit(fix["payload"])
    if expected != actual:
        mismatches.append({"id": fix["id"], "expected": sorted(expected), "actual": sorted(actual)})
print(json.dumps(mismatches))
PY
)
  if [ "$out" = "[]" ]; then
    :
  else
    fail_test "mismatches: $out"
  fi
end_test

# ─── T5 every fixture has the required keys ────────────────────────────────
start_test "fixtures_have_required_keys"
  out=$(python3 - <<PY
import json
required = {"id","category","payload","expected_categories","description"}
data = json.load(open("$FIXTURE"))
bad = [f["id"] for f in data["fixtures"] if not required.issubset(set(f.keys()))]
print(json.dumps(bad))
PY
)
  assert_eq "[]" "$out" "fixtures missing keys"
end_test

# ─── T6 each of 5 vectors has at least one positive fixture ────────────────
start_test "all_five_vectors_have_positive_fixture"
  out=$(python3 - <<PY
import json
data = json.load(open("$FIXTURE"))
needed = {"asterisk-obfuscation","persona-shift","retroactive-history-edit","context-injection","lost-in-middle-bait"}
seen = set()
for f in data["fixtures"]:
    for c in f["expected_categories"]:
        seen.add(c)
print(json.dumps(sorted(needed - seen)))
PY
)
  assert_eq "[]" "$out" "missing positive fixtures for: $out"
end_test

# ─── T7 at least one negative-control fixture exists ───────────────────────
start_test "has_at_least_one_negative_control"
  out=$(python3 - <<PY
import json
data = json.load(open("$FIXTURE"))
neg = [f["id"] for f in data["fixtures"] if not f["expected_categories"]]
print(len(neg))
PY
)
  if [ "$out" -ge 1 ]; then
    :
  else
    fail_test "no negative-control fixtures"
  fi
end_test

# ─── T8 detector handles empty / None / non-string gracefully ──────────────
start_test "detector_handles_edge_cases"
  out=$(python3 - <<PY
import importlib.util
spec = importlib.util.spec_from_file_location("jbd", "$LIB")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(len(m.detect_all("")), len(m.detect_all(None)), len(m.detect_all("x")))
PY
)
  assert_eq "0 0 0" "$out" "detector failed on edge cases"
end_test
