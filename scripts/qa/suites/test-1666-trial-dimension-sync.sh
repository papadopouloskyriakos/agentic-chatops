#!/usr/bin/env bash
# IFRNLLEI01PRD-1666 — trial-dimension whitelist sync guard.
#
# The prompt-patch A/B pipeline has TWO dimension whitelists that MUST stay
# identical or trials silently break:
#   * assign side  — DIMENSIONS in scripts/prompt-trial-assign.py
#                    (which dimensions get an active_trial_for() lookup per session)
#   * finalize side — _JUDGMENT_DIM_COLS in scripts/lib/prompt_patch_trial.py
#                    (which dimensions collect_arm_scores() can score)
#
# Drift is invisible and fatal in BOTH directions:
#   * in DIMENSIONS but not _JUDGMENT_DIM_COLS -> assigned, then the finalizer
#     raises ValueError("unknown dimension") -> the trial can never conclude.
#   * in _JUDGMENT_DIM_COLS but not DIMENSIONS -> DEAD ON ARRIVAL: the trial is
#     registered + active but never assigned -> 0 samples -> "inconclusive"
#     forever. This is exactly how trial 9 (overall_score) was silently dead
#     until 2026-07-07 (the dimension was scoreable but not assignable).
#
# Invariant: the two sets are EQUAL. This suite fails loudly on any drift.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="1666-trial-dimension-sync"

# Extract both whitelists via python (authoritative — no brittle grep of tuples).
read -r ASSIGN_SET FINAL_SET EQUAL MISSING_FROM_ASSIGN MISSING_FROM_FINAL <<EOF
$(cd "$REPO_ROOT/scripts" && python3 - <<'PY'
import importlib.util, os, sys

# assign-side DIMENSIONS
spec = importlib.util.spec_from_file_location("pta", "prompt-trial-assign.py")
pta = importlib.util.module_from_spec(spec); spec.loader.exec_module(pta)
assign = set(pta.DIMENSIONS)

# finalize-side _JUDGMENT_DIM_COLS
sys.path.insert(0, "lib")
import prompt_patch_trial as lib
final = set(lib._JUDGMENT_DIM_COLS.keys())

equal = "yes" if assign == final else "no"
missing_from_assign = ",".join(sorted(final - assign)) or "-"   # scoreable but NOT assignable (dead trials)
missing_from_final  = ",".join(sorted(assign - final)) or "-"   # assignable but NOT scoreable (ValueError)
print(len(assign), len(final), equal, missing_from_assign, missing_from_final)
PY
)
EOF

start_test "assign_and_finalize_dimension_sets_are_identical"
  assert_eq "yes" "$EQUAL"
end_test

start_test "no_scoreable_dimension_is_unassignable_dead_on_arrival"
  # e.g. overall_score used to live here — a registered trial that never gets samples.
  assert_eq "-" "$MISSING_FROM_ASSIGN"
end_test

start_test "no_assignable_dimension_is_unscoreable_finalizer_crash"
  assert_eq "-" "$MISSING_FROM_FINAL"
end_test

start_test "overall_score_is_now_assignable"
  # Regression pin for the exact trial-9 defect fixed 2026-07-07.
  cd "$REPO_ROOT/scripts"
  HAS=$(python3 -c "import importlib.util; s=importlib.util.spec_from_file_location('m','prompt-trial-assign.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('yes' if 'overall_score' in m.DIMENSIONS else 'no')")
  assert_eq "yes" "$HAS"
end_test
