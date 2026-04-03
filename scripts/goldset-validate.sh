#!/bin/bash
# goldset-validate.sh — Validate session_log entries against goldset expectations
# Usage: ./goldset-validate.sh [--scenario GS-XX] [--last N]
#   --scenario GS-XX : validate a specific scenario's session
#   --last N         : validate the last N session_log entries against all matching scenarios
#   (no args)        : validate all session_log entries from today
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DB="$HOME/gitlab/products/cubeos/claude-context/gateway.db"
GOLDSET="$REPO/scripts/goldset-scenarios.json"
PASS=0
FAIL=0
WARN=0
SKIP=0

pass() { PASS=$((PASS+1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }
warn() { WARN=$((WARN+1)); echo "  WARN: $1"; }
skip() { SKIP=$((SKIP+1)); echo "  SKIP: $1"; }

# Parse args
SCENARIO=""
LAST_N=""
while [ $# -gt 0 ]; do
  case "$1" in
    --scenario) SCENARIO="$2"; shift 2 ;;
    --last) LAST_N="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

echo "=== Goldset Validation — $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
echo ""

# Load goldset scenarios
if [ ! -f "$GOLDSET" ]; then
  echo "ERROR: goldset-scenarios.json not found at $GOLDSET"
  exit 1
fi

# Get session_log entries to validate
if [ -n "$LAST_N" ]; then
  QUERY="SELECT id, issue_id, issue_title, cost_usd, num_turns, duration_seconds, confidence, resolution_type, alert_category, prompt_variant FROM session_log ORDER BY id DESC LIMIT $LAST_N"
elif [ -n "$SCENARIO" ]; then
  echo "Scenario mode: looking for sessions matching $SCENARIO"
  QUERY="SELECT id, issue_id, issue_title, cost_usd, num_turns, duration_seconds, confidence, resolution_type, alert_category, prompt_variant FROM session_log ORDER BY id DESC LIMIT 50"
else
  QUERY="SELECT id, issue_id, issue_title, cost_usd, num_turns, duration_seconds, confidence, resolution_type, alert_category, prompt_variant FROM session_log WHERE ended_at > datetime('now', '-1 day') ORDER BY id DESC"
fi

# ── Test 1: Column population check ──
echo "T1: Column population (non-default values in session_log)"

TOTAL_ROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log;")
COST_POP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE cost_usd > 0;")
CONF_POP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE confidence >= 0;")
CAT_POP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE alert_category != '' AND alert_category IS NOT NULL;")
VAR_POP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE prompt_variant != '' AND prompt_variant IS NOT NULL;")
RES_POP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE resolution_type != 'unknown';")
DUR_POP=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE duration_seconds > 0;")

echo "  Total session_log rows: $TOTAL_ROWS"
echo "  cost_usd populated:     $COST_POP/$TOTAL_ROWS"
echo "  confidence populated:   $CONF_POP/$TOTAL_ROWS"
echo "  alert_category set:     $CAT_POP/$TOTAL_ROWS"
echo "  prompt_variant set:     $VAR_POP/$TOTAL_ROWS"
echo "  resolution_type set:    $RES_POP/$TOTAL_ROWS"
echo "  duration_seconds > 0:   $DUR_POP/$TOTAL_ROWS"

[ "$COST_POP" -gt 0 ] && pass "cost_usd has non-zero values" || warn "cost_usd all zeros (no sessions since fix?)"
[ "$CONF_POP" -gt 0 ] && pass "confidence has valid values" || warn "confidence all -1 (no sessions since fix?)"
[ "$CAT_POP" -gt 0 ] && pass "alert_category populated" || warn "alert_category all empty"
[ "$VAR_POP" -gt 0 ] && pass "prompt_variant recorded" || warn "prompt_variant all empty (no sessions since fix?)"

echo ""

# ── Test 2: A/B variant distribution ──
echo "T2: A/B variant distribution"
V1=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE prompt_variant = 'react_v1';")
V2=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE prompt_variant = 'react_v2';")
VTOTAL=$((V1 + V2))
if [ "$VTOTAL" -gt 0 ]; then
  V1_PCT=$((V1 * 100 / VTOTAL))
  V2_PCT=$((V2 * 100 / VTOTAL))
  echo "  react_v1: $V1 ($V1_PCT%)"
  echo "  react_v2: $V2 ($V2_PCT%)"
  if [ "$V1_PCT" -ge 30 ] && [ "$V1_PCT" -le 70 ]; then
    pass "variant distribution within 30-70% range"
  else
    warn "variant distribution skewed: v1=$V1_PCT%"
  fi
else
  skip "no variant data yet"
fi

echo ""

# ── Test 3: Alert category distribution ──
echo "T3: Alert category distribution"
sqlite3 "$DB" "SELECT alert_category, COUNT(*) as n FROM session_log WHERE alert_category != '' GROUP BY alert_category ORDER BY n DESC;" 2>/dev/null | while IFS='|' read -r cat count; do
  echo "  $cat: $count"
done
CAT_DISTINCT=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT alert_category) FROM session_log WHERE alert_category != '';")
if [ "$CAT_DISTINCT" -ge 2 ]; then
  pass "multiple alert categories present ($CAT_DISTINCT)"
elif [ "$CAT_DISTINCT" -eq 1 ]; then
  warn "only 1 alert category present"
else
  skip "no alert categories yet"
fi

echo ""

# ── Test 4: Cost tracking sanity ──
echo "T4: Cost tracking sanity"
AVG_COST=$(sqlite3 "$DB" "SELECT ROUND(AVG(cost_usd), 4) FROM session_log WHERE cost_usd > 0;" 2>/dev/null)
MAX_COST=$(sqlite3 "$DB" "SELECT ROUND(MAX(cost_usd), 4) FROM session_log WHERE cost_usd > 0;" 2>/dev/null)
if [ -n "$AVG_COST" ] && [ "$AVG_COST" != "" ]; then
  echo "  avg cost: \$$AVG_COST"
  echo "  max cost: \$$MAX_COST"
  pass "cost data present"
  # Sanity: max cost shouldn't exceed $10
  MAX_INT=$(echo "$MAX_COST" | cut -d. -f1)
  if [ "${MAX_INT:-0}" -le 10 ]; then
    pass "max cost within $10 ceiling"
  else
    fail "max cost exceeds $10: \$$MAX_COST"
  fi
else
  skip "no cost data yet"
fi

echo ""

# ── Test 5: Confidence distribution ──
echo "T5: Confidence distribution"
CONF_STATS=$(sqlite3 "$DB" "SELECT
  ROUND(AVG(confidence), 2),
  ROUND(MIN(confidence), 2),
  ROUND(MAX(confidence), 2),
  COUNT(*)
FROM session_log WHERE confidence >= 0;" 2>/dev/null)
if [ -n "$CONF_STATS" ]; then
  IFS='|' read -r avg_conf min_conf max_conf conf_count <<< "$CONF_STATS"
  if [ "${conf_count:-0}" -gt 0 ]; then
    echo "  avg confidence: $avg_conf"
    echo "  range: $min_conf - $max_conf"
    echo "  count: $conf_count"
    pass "confidence data present ($conf_count entries)"
  else
    skip "no confidence scores yet"
  fi
else
  skip "no confidence data"
fi

echo ""

# ── Test 6: Per-variant performance comparison ──
echo "T6: Per-variant performance (APE readiness)"
V1_STATS=$(sqlite3 "$DB" "SELECT COUNT(*), ROUND(AVG(confidence),2), ROUND(AVG(cost_usd),4), ROUND(AVG(duration_seconds),0) FROM session_log WHERE prompt_variant='react_v1' AND confidence >= 0;" 2>/dev/null)
V2_STATS=$(sqlite3 "$DB" "SELECT COUNT(*), ROUND(AVG(confidence),2), ROUND(AVG(cost_usd),4), ROUND(AVG(duration_seconds),0) FROM session_log WHERE prompt_variant='react_v2' AND confidence >= 0;" 2>/dev/null)
if [ -n "$V1_STATS" ] && [ -n "$V2_STATS" ]; then
  IFS='|' read -r v1n v1conf v1cost v1dur <<< "$V1_STATS"
  IFS='|' read -r v2n v2conf v2cost v2dur <<< "$V2_STATS"
  echo "  react_v1: n=$v1n, avg_conf=$v1conf, avg_cost=\$$v1cost, avg_dur=${v1dur}s"
  echo "  react_v2: n=$v2n, avg_conf=$v2conf, avg_cost=\$$v2cost, avg_dur=${v2dur}s"
  V1N=${v1n:-0}
  V2N=${v2n:-0}
  COMBINED=$((V1N + V2N))
  if [ "$COMBINED" -ge 50 ]; then
    pass "sufficient data for A/B comparison ($COMBINED sessions)"
  elif [ "$COMBINED" -ge 10 ]; then
    warn "preliminary A/B data ($COMBINED sessions, need 50+)"
  else
    skip "insufficient A/B data ($COMBINED sessions, need 50+)"
  fi
else
  skip "no per-variant data"
fi

echo ""

# ── Test 7: APE readiness assessment ──
echo "T7: APE readiness"
TOTAL_LABELED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE confidence >= 0 AND cost_usd > 0 AND prompt_variant != '';" 2>/dev/null)
echo "  Fully labeled sessions (confidence + cost + variant): $TOTAL_LABELED"
if [ "${TOTAL_LABELED:-0}" -ge 200 ]; then
  pass "APE READY: 200+ labeled sessions"
elif [ "${TOTAL_LABELED:-0}" -ge 100 ]; then
  warn "APE approaching: $TOTAL_LABELED/200 labeled sessions"
elif [ "${TOTAL_LABELED:-0}" -ge 10 ]; then
  warn "APE early: $TOTAL_LABELED/200 labeled sessions"
else
  skip "APE not ready: $TOTAL_LABELED/200 labeled sessions"
fi

echo ""

# ── Test 8: Factored cognition readiness (Gap D) ──
echo "T8: Factored cognition readiness"
COMPLEX_TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE num_turns > 0 AND cost_usd > 0;" 2>/dev/null)
COMPLEX_HIGH=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE (num_turns > 10 OR cost_usd > 3.0) AND num_turns > 0;" 2>/dev/null)
echo "  Sessions with tracking data: ${COMPLEX_TOTAL:-0}"
echo "  Sessions exceeding 10 turns or \$3: ${COMPLEX_HIGH:-0}"
if [ "${COMPLEX_TOTAL:-0}" -gt 0 ]; then
  COMPLEX_PCT=$((${COMPLEX_HIGH:-0} * 100 / COMPLEX_TOTAL))
  echo "  Complex session ratio: ${COMPLEX_PCT}%"
  if [ "$COMPLEX_PCT" -ge 20 ]; then
    warn "FACTORED COGNITION JUSTIFIED: ${COMPLEX_PCT}% of sessions are complex (>20% threshold)"
  else
    pass "factored cognition not yet needed (${COMPLEX_PCT}% complex, threshold 20%)"
  fi
else
  skip "no tracked sessions yet — need cost+turns data to assess"
fi

echo ""

# ── Test 9: Metamorphic readiness (Gap E) ──
echo "T9: Metamorphic self-modification readiness"
# Check: do we have enough per-variant data for auto-promotion?
V1_30D=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE prompt_variant='react_v1' AND confidence >= 0 AND ended_at > datetime('now', '-30 days');" 2>/dev/null)
V2_30D=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE prompt_variant='react_v2' AND confidence >= 0 AND ended_at > datetime('now', '-30 days');" 2>/dev/null)
echo "  Variant data (30d): v1=${V1_30D:-0}, v2=${V2_30D:-0} (need 25 each for auto-promotion)"
# Check: do we have per-category cost data for cost-adaptive mode?
CAT_WITH_COST=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT alert_category) FROM session_log WHERE alert_category != '' AND cost_usd > 0;" 2>/dev/null)
echo "  Categories with cost data: ${CAT_WITH_COST:-0} (need 3+ sessions per category)"
# Check: do we have enough data for rollback detection?
WEEK_SESSIONS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE confidence >= 0 AND ended_at > datetime('now', '-7 days');" 2>/dev/null)
echo "  Recent sessions with confidence (7d): ${WEEK_SESSIONS:-0} (need 3+ per variant)"

METAMORPHIC_READY=0
[ "${V1_30D:-0}" -ge 25 ] && [ "${V2_30D:-0}" -ge 25 ] && METAMORPHIC_READY=$((METAMORPHIC_READY + 1))
[ "${CAT_WITH_COST:-0}" -ge 2 ] && METAMORPHIC_READY=$((METAMORPHIC_READY + 1))
[ "${WEEK_SESSIONS:-0}" -ge 6 ] && METAMORPHIC_READY=$((METAMORPHIC_READY + 1))

if [ "$METAMORPHIC_READY" -eq 3 ]; then
  pass "all 3 metamorphic behaviors have sufficient data"
elif [ "$METAMORPHIC_READY" -ge 1 ]; then
  warn "partial metamorphic readiness ($METAMORPHIC_READY/3 behaviors have data)"
else
  skip "metamorphic not ready — no labeled data yet"
fi

echo ""

# ── Summary ──
echo "═══════════════════════════════════════"
echo "Results: $PASS passed, $FAIL failed, $WARN warnings, $SKIP skipped"
echo "═══════════════════════════════════════"

# Write Prometheus metrics
PROM_FILE="$HOME/gitlab/products/cubeos/claude-context/goldset-validation.prom"
cat > "${PROM_FILE}.tmp" <<EOF
# HELP chatops_goldset_pass Goldset validation pass count
# TYPE chatops_goldset_pass gauge
chatops_goldset_pass $PASS
# HELP chatops_goldset_fail Goldset validation fail count
# TYPE chatops_goldset_fail gauge
chatops_goldset_fail $FAIL
# HELP chatops_goldset_warn Goldset validation warning count
# TYPE chatops_goldset_warn gauge
chatops_goldset_warn $WARN
# HELP chatops_goldset_labeled_sessions Fully labeled sessions for APE
# TYPE chatops_goldset_labeled_sessions gauge
chatops_goldset_labeled_sessions ${TOTAL_LABELED:-0}
# HELP chatops_goldset_complex_session_pct Percentage of sessions exceeding 10 turns or 3 USD
# TYPE chatops_goldset_complex_session_pct gauge
chatops_goldset_complex_session_pct ${COMPLEX_PCT:-0}
# HELP chatops_goldset_timestamp Last goldset validation timestamp
# TYPE chatops_goldset_timestamp gauge
chatops_goldset_timestamp $(date +%s)
EOF
mv "${PROM_FILE}.tmp" "$PROM_FILE"

exit $FAIL
