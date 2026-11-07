#!/bin/bash
# G5 KG traversal regression test — validates plan-execution primary path.
#
# Each case pins a query + expected outcome type:
#   primary — WITH RECURSIVE fires with strict/OR'd filters, no "widened" log
#   widened — widened to drop entity_type (planner's type guess was wrong but
#             filters still match something)
#   fallback — graph has no literal match, embedding cosine finds semantic ones
#
# Outcomes are marker-based: each code path emits a distinctive stderr line.
# See kb-semantic-search.py execute_plan() for the markers.

set -u

cd "$(dirname "$0")/.."
PASS=0; FAIL=0

check() {
  local name="$1" result="$2"
  if [ "$result" = "PASS" ]; then
    echo "  [PASS] $name"
    PASS=$((PASS+1))
  else
    echo "  [FAIL] $name — $result"
    FAIL=$((FAIL+1))
  fi
}

run_query() {
  local query="$1" err_log="$2"
  timeout 30 python3 scripts/kb-semantic-search.py traverse "$query" 2>"$err_log"
}

count_depth_lines() {
  grep -c "^\[depth=" "$1" 2>/dev/null || echo 0
}

echo "===== KG TRAVERSE TESTS ====="

# Case 1: primary path (strict or OR'd, type-restricted) should fire.
# nl-pve01 is a concrete host entity — strict filter should match.
echo ""
echo "Case 1: primary path — known host"
out=$(run_query "which services depend on nl-pve01" /tmp/kg-p1.err)
stdlen=$(echo -n "$out" | wc -c)
depths=$(grep -c "^\[depth=" <<< "$out")
[ "$depths" -gt 3 ] && check "≥4 traversal rows returned ($depths)" "PASS" || check "traversal rows" "$depths rows (expected >3)"
if grep -q "widened\|fallback to embedding" /tmp/kg-p1.err; then
  check "primary path fired (no widen/fallback)" "widened or fallback log present"
else
  check "primary path fired (no widen/fallback)" "PASS"
fi
if grep -q "traverse] plan:" /tmp/kg-p1.err; then
  check "plan logged" "PASS"
else
  check "plan logged" "no plan log"
fi

# Case 2: widened path — planner chose wrong entity_type, OR filters + type-drop save it.
echo ""
echo "Case 2: widened — Freedom ISP (planner likely picks chaos_experiment)"
out=$(run_query "what chaos experiments involved Freedom ISP" /tmp/kg-p2.err)
depths=$(grep -c "^\[depth=" <<< "$out")
[ "$depths" -gt 3 ] && check "≥4 traversal rows returned ($depths)" "PASS" || check "traversal rows" "$depths rows"
if grep -q "widened" /tmp/kg-p2.err; then
  check "widening log present (primary had 0 seeds)" "PASS"
elif grep -q "fallback to embedding" /tmp/kg-p2.err; then
  check "widening log present" "fallback fired instead — widening didn't help"
else
  # This can happen if the planner chose "service" directly (strict match works).
  # Accept it — the primary path covered the case.
  check "widening log present (or primary was sufficient)" "PASS"
fi

# Case 3: fallback — query about a concept the graph doesn't have as a named entity.
echo ""
echo "Case 3: fallback — 'GR isolation' (not a named entity in current graph)"
out=$(run_query "what services affected by GR isolation" /tmp/kg-p3.err)
depths=$(grep -c "^\[depth=" <<< "$out")
[ "$depths" -gt 3 ] && check "≥4 semantic matches returned ($depths)" "PASS" || check "semantic matches" "$depths rows"
if grep -q "fallback to embedding" /tmp/kg-p3.err; then
  check "embedding fallback fired (as expected)" "PASS"
else
  check "embedding fallback fired" "no fallback log — but graph doesn't have 'GR isolation' entity"
fi

# Case 4: planner robustness — multi-entity question should force hops>=2.
echo ""
echo "Case 4: multi-hop cue forces hops>=2"
out=$(run_query "show me what cascades from a pve01 memory pressure incident" /tmp/kg-p4.err)
if grep -oE '"hops": ?[0-9]' /tmp/kg-p4.err | grep -qE '2|3'; then
  check "planner chose hops>=2" "PASS"
else
  check "planner chose hops>=2" "picked hops=1 despite cascades cue"
fi

# Case 5: no traceback across any run
echo ""
echo "Case 5: no tracebacks"
if grep -l "Traceback" /tmp/kg-p*.err 2>/dev/null; then
  check "all runs clean (no traceback)" "traceback in one of the runs"
else
  check "all runs clean (no traceback)" "PASS"
fi

echo ""
echo "Category KG: $PASS PASS / $FAIL FAIL out of $((PASS + FAIL))"

if [ "$FAIL" -gt 0 ]; then
  for n in 1 2 3 4; do
    echo ""
    echo "--- /tmp/kg-p${n}.err tail ---"
    tail -10 "/tmp/kg-p${n}.err" 2>/dev/null
  done
fi

[ "$FAIL" -eq 0 ]
