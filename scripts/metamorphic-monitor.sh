#!/bin/bash
# metamorphic-monitor.sh — Lightweight metamorphic self-modification hooks (Gap E)
# Monitors 3 self-modification behaviors and proposes/executes changes when thresholds met.
# Cron: 0 */6 * * * (same cadence as regression-detector.sh)
#
# Behaviors:
#   1. Auto-variant promotion — promote winning A/B variant when statistically significant
#   2. Cost-adaptive plan mode — auto-enable plan-only when category cost exceeds ceiling
#   3. Self-healing prompt rollback — propose rollback when regression correlates with variant change
#
# All actions post to Matrix #alerts. None modify production without human approval
# unless --auto-apply is passed (for future use once trust is established).
set -uo pipefail

DB="$HOME/gitlab/products/cubeos/claude-context/gateway.db"
REPO="$HOME/gitlab/n8n/claude-gateway"
MATRIX_URL="https://matrix.example.net"
ALERTS_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
MATRIX_TOKEN=$(cat "$HOME/.matrix-claude-token" 2>/dev/null || echo "")
PROM_FILE="$HOME/gitlab/products/cubeos/claude-context/metamorphic.prom"

AUTO_APPLY=false
[ "${1:-}" = "--auto-apply" ] && AUTO_APPLY=true

# ─── Helpers ───
post_alert() {
  local msg="$1"
  echo -e "$msg"
  [ -z "$MATRIX_TOKEN" ] && return
  local txn="metamorphic-$(date +%s%N)"
  curl -sf --max-time 10 \
    -X PUT \
    -H "Authorization: Bearer $MATRIX_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"msgtype\":\"m.notice\",\"body\":$(python3 -c "import json; print(json.dumps('''$msg'''))" 2>/dev/null || echo "\"$msg\"")}" \
    "${MATRIX_URL}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/${txn}" \
    >/dev/null 2>&1 || true
}

# Initialize metrics
VARIANT_PROMOTED=0
COST_ADAPTIVE_TRIGGERED=0
ROLLBACK_PROPOSED=0

echo "=== Metamorphic Monitor — $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

***REMOVED***═
# 1. AUTO-VARIANT PROMOTION
# If one variant significantly outperforms the other on confidence
# with sufficient sample size, propose (or auto-apply) promotion.
***REMOVED***═
echo ""
echo "── 1. Auto-variant promotion ──"

V1_DATA=$(sqlite3 "$DB" "
  SELECT COUNT(*), COALESCE(AVG(confidence),-1), COALESCE(AVG(cost_usd),0), COALESCE(AVG(duration_seconds),0)
  FROM session_log
  WHERE prompt_variant='react_v1' AND confidence >= 0
    AND ended_at > datetime('now', '-30 days');" 2>/dev/null || echo "0|-1|0|0")
V2_DATA=$(sqlite3 "$DB" "
  SELECT COUNT(*), COALESCE(AVG(confidence),-1), COALESCE(AVG(cost_usd),0), COALESCE(AVG(duration_seconds),0)
  FROM session_log
  WHERE prompt_variant='react_v2' AND confidence >= 0
    AND ended_at > datetime('now', '-30 days');" 2>/dev/null || echo "0|-1|0|0")

IFS='|' read -r V1N V1CONF V1COST V1DUR <<< "$V1_DATA"
IFS='|' read -r V2N V2CONF V2COST V2DUR <<< "$V2_DATA"

V1N=${V1N:-0}; V2N=${V2N:-0}
MIN_SAMPLES=25  # per variant for significance

if [ "$V1N" -ge "$MIN_SAMPLES" ] && [ "$V2N" -ge "$MIN_SAMPLES" ]; then
  # Compare confidence (primary metric)
  CONF_DIFF=$(echo "$V2CONF - $V1CONF" | bc -l 2>/dev/null || echo "0")
  CONF_DIFF_ABS=$(echo "$CONF_DIFF" | tr -d '-')

  # Significant = >0.05 difference in avg confidence
  if [ "$(echo "$CONF_DIFF_ABS > 0.05" | bc -l 2>/dev/null)" = "1" ]; then
    if [ "$(echo "$CONF_DIFF > 0" | bc -l 2>/dev/null)" = "1" ]; then
      WINNER="react_v2"
      LOSER="react_v1"
      WINNER_CONF="$V2CONF"
      LOSER_CONF="$V1CONF"
    else
      WINNER="react_v1"
      LOSER="react_v2"
      WINNER_CONF="$V1CONF"
      LOSER_CONF="$V2CONF"
    fi

    VARIANT_PROMOTED=1
    post_alert "METAMORPHIC: Auto-variant promotion candidate
Winner: $WINNER (avg confidence: $(printf '%.3f' "$WINNER_CONF"), n=$( [ "$WINNER" = "react_v1" ] && echo "$V1N" || echo "$V2N"))
Loser: $LOSER (avg confidence: $(printf '%.3f' "$LOSER_CONF"), n=$( [ "$LOSER" = "react_v1" ] && echo "$V1N" || echo "$V2N"))
Delta: $(printf '%.3f' "$CONF_DIFF_ABS")
Action: Promote $WINNER as default. Review and update Build Prompt A/B split."
  else
    echo "  No significant difference (delta=$(printf '%.3f' "$CONF_DIFF_ABS"), threshold=0.05)"
  fi
else
  echo "  Insufficient data: v1=$V1N, v2=$V2N (need $MIN_SAMPLES each)"
fi

***REMOVED***═
# 2. COST-ADAPTIVE PLAN MODE
# If a category's average cost exceeds the ceiling, flag it for
# automatic plan-only mode on future sessions of that category.
***REMOVED***═
echo ""
echo "── 2. Cost-adaptive plan mode ──"

COST_CEILING=3.0  # USD per session

EXPENSIVE_CATS=$(sqlite3 "$DB" "
  SELECT alert_category, COUNT(*), ROUND(AVG(cost_usd),2), ROUND(MAX(cost_usd),2)
  FROM session_log
  WHERE alert_category != '' AND cost_usd > 0
    AND ended_at > datetime('now', '-30 days')
  GROUP BY alert_category
  HAVING AVG(cost_usd) > $COST_CEILING AND COUNT(*) >= 3;" 2>/dev/null || echo "")

if [ -n "$EXPENSIVE_CATS" ]; then
  while IFS='|' read -r cat count avg_cost max_cost; do
    [ -z "$cat" ] && continue
    COST_ADAPTIVE_TRIGGERED=1
    post_alert "METAMORPHIC: Cost-adaptive plan mode triggered
Category: $cat (n=$count, avg=\$$avg_cost, max=\$$max_cost, ceiling=\$$COST_CEILING)
Action: Consider adding $cat to auto-plan-mode list in Build Prompt."
  done <<< "$EXPENSIVE_CATS"
else
  echo "  No categories exceed \$$COST_CEILING avg cost"
fi

***REMOVED***═
# 3. SELF-HEALING PROMPT ROLLBACK
# If a regression is detected AND it correlates with a variant
# performing worse than baseline, propose rolling back to the
# other variant or the last known-good configuration.
***REMOVED***═
echo ""
echo "── 3. Self-healing prompt rollback ──"

# Compare last 7d vs prior 7d per variant
ROLLBACK_NEEDED=false
for VARIANT in react_v1 react_v2; do
  CURRENT=$(sqlite3 "$DB" "
    SELECT COUNT(*), COALESCE(AVG(confidence),-1)
    FROM session_log
    WHERE prompt_variant='$VARIANT' AND confidence >= 0
      AND ended_at > datetime('now', '-7 days');" 2>/dev/null || echo "0|-1")
  PRIOR=$(sqlite3 "$DB" "
    SELECT COUNT(*), COALESCE(AVG(confidence),-1)
    FROM session_log
    WHERE prompt_variant='$VARIANT' AND confidence >= 0
      AND ended_at BETWEEN datetime('now', '-14 days') AND datetime('now', '-7 days');" 2>/dev/null || echo "0|-1")

  IFS='|' read -r CN CCONF <<< "$CURRENT"
  IFS='|' read -r PN PCONF <<< "$PRIOR"
  CN=${CN:-0}; PN=${PN:-0}

  if [ "$CN" -ge 3 ] && [ "$PN" -ge 3 ]; then
    DROP=$(echo "$PCONF - $CCONF" | bc -l 2>/dev/null || echo "0")
    if [ "$(echo "$DROP > 0.15" | bc -l 2>/dev/null)" = "1" ]; then
      ROLLBACK_NEEDED=true
      ROLLBACK_PROPOSED=1
      OTHER=$( [ "$VARIANT" = "react_v1" ] && echo "react_v2" || echo "react_v1" )
      post_alert "METAMORPHIC: Prompt rollback candidate
Variant: $VARIANT confidence dropped $(printf '%.2f' "$PCONF") -> $(printf '%.2f' "$CCONF") (delta: -$(printf '%.2f' "$DROP"))
Period: 7d vs prior 7d (n=$CN vs n=$PN)
Action: Consider routing 100% traffic to $OTHER until $VARIANT is investigated."
    fi
  fi
done

if [ "$ROLLBACK_NEEDED" = false ]; then
  echo "  No variant regressions detected"
fi

***REMOVED***═
# 4. TOPOLOGY CHANGE READINESS
# Track signals that would justify spawning new agent types or
# changing the tier architecture.
***REMOVED***═
echo ""
echo "── 4. Topology change signals ──"

# Signal A: Escalation rate — if >50% of T1 sessions escalate to T2, T1 is underperforming
TOTAL_INFRA=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM session_log
  WHERE (issue_id LIKE 'IFRNLLEI01PRD%' OR issue_id LIKE 'IFRGRSKG01PRD%')
    AND ended_at > datetime('now', '-30 days');" 2>/dev/null || echo "0")
# (All infra sessions that reach session_log went through T2, so escalation rate = infra/total_alerts)
echo "  Infra sessions (30d): $TOTAL_INFRA"

# Signal B: Cross-tier review disagreement rate
DISAGREE=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM a2a_task_log
  WHERE action LIKE '%DISAGREE%'
    AND created_at > datetime('now', '-30 days');" 2>/dev/null || echo "0")
TOTAL_REVIEWS=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM a2a_task_log
  WHERE action LIKE '%REVIEW%'
    AND created_at > datetime('now', '-30 days');" 2>/dev/null || echo "0")
if [ "${TOTAL_REVIEWS:-0}" -gt 0 ]; then
  DISAGREE_PCT=$((DISAGREE * 100 / TOTAL_REVIEWS))
  echo "  Review disagreement rate: ${DISAGREE_PCT}% ($DISAGREE/$TOTAL_REVIEWS)"
  if [ "$DISAGREE_PCT" -gt 30 ]; then
    post_alert "METAMORPHIC: High cross-tier disagreement rate: ${DISAGREE_PCT}% ($DISAGREE/$TOTAL_REVIEWS in 30d).
Consider: adding a 3rd review perspective, adjusting SOUL.md confidence thresholds, or creating a specialized triage agent for the disagreeing category."
  fi
else
  echo "  No cross-tier review data yet"
fi

# Signal C: Unresolved sessions (sessions that ended with confidence < 0.5)
LOW_CONF=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM session_log
  WHERE confidence >= 0 AND confidence < 0.5
    AND ended_at > datetime('now', '-30 days');" 2>/dev/null || echo "0")
TOTAL_CONF=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM session_log
  WHERE confidence >= 0
    AND ended_at > datetime('now', '-30 days');" 2>/dev/null || echo "0")
if [ "${TOTAL_CONF:-0}" -gt 5 ]; then
  LOW_PCT=$((LOW_CONF * 100 / TOTAL_CONF))
  echo "  Low-confidence sessions (<0.5): ${LOW_PCT}% ($LOW_CONF/$TOTAL_CONF)"
  if [ "$LOW_PCT" -gt 25 ]; then
    post_alert "METAMORPHIC: ${LOW_PCT}% of sessions end with confidence < 0.5 ($LOW_CONF/$TOTAL_CONF in 30d).
Consider: adding domain-specific agents, improving RAG coverage, or decomposing complex issues (Gap D)."
  fi
else
  echo "  Insufficient confidence data ($TOTAL_CONF sessions, need 5+)"
fi

echo ""

# ─── Write Prometheus metrics ───
cat > "${PROM_FILE}.tmp" <<EOF
# HELP chatops_metamorphic_variant_promoted Whether a variant promotion was proposed (0/1)
# TYPE chatops_metamorphic_variant_promoted gauge
chatops_metamorphic_variant_promoted $VARIANT_PROMOTED
# HELP chatops_metamorphic_cost_adaptive Whether cost-adaptive plan mode was triggered (0/1)
# TYPE chatops_metamorphic_cost_adaptive gauge
chatops_metamorphic_cost_adaptive $COST_ADAPTIVE_TRIGGERED
# HELP chatops_metamorphic_rollback_proposed Whether a prompt rollback was proposed (0/1)
# TYPE chatops_metamorphic_rollback_proposed gauge
chatops_metamorphic_rollback_proposed $ROLLBACK_PROPOSED
# HELP chatops_metamorphic_v1_count Sessions using react_v1 (30d)
# TYPE chatops_metamorphic_v1_count gauge
chatops_metamorphic_v1_count ${V1N:-0}
# HELP chatops_metamorphic_v2_count Sessions using react_v2 (30d)
# TYPE chatops_metamorphic_v2_count gauge
chatops_metamorphic_v2_count ${V2N:-0}
# HELP chatops_metamorphic_v1_confidence Avg confidence for react_v1 (30d)
# TYPE chatops_metamorphic_v1_confidence gauge
chatops_metamorphic_v1_confidence ${V1CONF:--1}
# HELP chatops_metamorphic_v2_confidence Avg confidence for react_v2 (30d)
# TYPE chatops_metamorphic_v2_confidence gauge
chatops_metamorphic_v2_confidence ${V2CONF:--1}
# HELP chatops_metamorphic_timestamp Last metamorphic monitor run
# TYPE chatops_metamorphic_timestamp gauge
chatops_metamorphic_timestamp $(date +%s)
EOF
mv "${PROM_FILE}.tmp" "$PROM_FILE"

echo "Prometheus metrics written to $PROM_FILE"
echo "=== Done ==="
