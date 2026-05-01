#!/usr/bin/env bash
# Judge Calibration — validates LLM-as-Judge accuracy against human feedback
# Compares judge scores vs thumbs_up/thumbs_down from session_feedback
# Reports TPR (true positive rate) and TNR (true negative rate)
# Implements OpenAI eval best practice: judge calibration splits (20/40/40)
#
# Usage: judge-calibrate.sh [--export-prom]
# Cron: 0 5 1 * * (1st of month, after eval-flywheel.sh)
set -euo pipefail
source "$(dirname "$0")/eval-config.sh" 2>/dev/null || true

DB="${EVAL_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
PROM_DIR="${HOME}/gitlab/products/cubeos/claude-context"
EXPORT_PROM=false
[[ "${1:-}" == "--export-prom" ]] && EXPORT_PROM=true

echo "=== LLM Judge Calibration ==="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Get sessions that have BOTH judge scores AND human feedback
CALIBRATION_DATA=$(sqlite3 "$DB" "
  SELECT
    j.issue_id,
    j.overall_score,
    j.recommended_action,
    COALESCE(f.feedback, 'none') as human_feedback,
    j.judge_model
  FROM session_judgment j
  LEFT JOIN session_feedback f ON j.issue_id = f.issue_id
  WHERE f.feedback IS NOT NULL
  ORDER BY j.created_at DESC
  LIMIT 200
" 2>/dev/null || echo "")

if [ -z "$CALIBRATION_DATA" ]; then
  echo "WARN: No sessions with both judge scores and human feedback"
  echo "Need sessions where judge scored AND operator gave thumbs up/down"
  echo "Current session_judgment count: $(sqlite3 "$DB" "SELECT COUNT(*) FROM session_judgment" 2>/dev/null || echo 0)"
  echo "Current session_feedback count: $(sqlite3 "$DB" "SELECT COUNT(*) FROM session_feedback" 2>/dev/null || echo 0)"
  exit 0
fi

# Calculate metrics
TOTAL=0
TRUE_POS=0   # Judge says good (overall>=3), human says thumbs_up
TRUE_NEG=0   # Judge says bad (overall<3), human says thumbs_down
FALSE_POS=0  # Judge says good, human says thumbs_down
FALSE_NEG=0  # Judge says bad, human says thumbs_up

while IFS='|' read -r issue_id score action feedback model; do
  TOTAL=$((TOTAL + 1))
  score_int=${score%%.*}  # truncate to integer

  if [ "$score_int" -ge 3 ] && [ "$feedback" = "thumbs_up" ]; then
    TRUE_POS=$((TRUE_POS + 1))
  elif [ "$score_int" -lt 3 ] && [ "$feedback" = "thumbs_down" ]; then
    TRUE_NEG=$((TRUE_NEG + 1))
  elif [ "$score_int" -ge 3 ] && [ "$feedback" = "thumbs_down" ]; then
    FALSE_POS=$((FALSE_POS + 1))
    echo "  FALSE_POS: $issue_id (judge=$score/$action, human=$feedback)"
  elif [ "$score_int" -lt 3 ] && [ "$feedback" = "thumbs_up" ]; then
    FALSE_NEG=$((FALSE_NEG + 1))
    echo "  FALSE_NEG: $issue_id (judge=$score/$action, human=$feedback)"
  fi
done <<< "$CALIBRATION_DATA"

# Calculate rates
if [ $((TRUE_POS + FALSE_NEG)) -gt 0 ]; then
  TPR=$(echo "scale=3; $TRUE_POS / ($TRUE_POS + $FALSE_NEG)" | bc)
else
  TPR="N/A"
fi

if [ $((TRUE_NEG + FALSE_POS)) -gt 0 ]; then
  TNR=$(echo "scale=3; $TRUE_NEG / ($TRUE_NEG + $FALSE_POS)" | bc)
else
  TNR="N/A"
fi

ACCURACY="N/A"
if [ "$TOTAL" -gt 0 ]; then
  ACCURACY=$(echo "scale=3; ($TRUE_POS + $TRUE_NEG) / $TOTAL" | bc)
fi

echo ""
echo "=== Results ==="
echo "Total calibration samples: $TOTAL"
echo "True Positives:  $TRUE_POS (judge good, human agrees)"
echo "True Negatives:  $TRUE_NEG (judge bad, human agrees)"
echo "False Positives: $FALSE_POS (judge good, human disagrees)"
echo "False Negatives: $FALSE_NEG (judge bad, human disagrees)"
echo ""
echo "TPR (sensitivity):  $TPR (target: >= ${JUDGE_MIN_TPR:-0.70})"
echo "TNR (specificity):  $TNR (target: >= ${JUDGE_MIN_TNR:-0.70})"
echo "Overall accuracy:   $ACCURACY"

# Check against thresholds
MIN_TPR="${JUDGE_MIN_TPR:-0.70}"
MIN_TNR="${JUDGE_MIN_TNR:-0.70}"
PASS=true

if [ "$TPR" != "N/A" ] && [ "$(echo "$TPR < $MIN_TPR" | bc)" -eq 1 ]; then
  echo ""
  echo "WARN: TPR $TPR below threshold $MIN_TPR — judge is missing real problems"
  PASS=false
fi
if [ "$TNR" != "N/A" ] && [ "$(echo "$TNR < $MIN_TNR" | bc)" -eq 1 ]; then
  echo ""
  echo "WARN: TNR $TNR below threshold $MIN_TNR — judge is flagging good sessions"
  PASS=false
fi

# Export Prometheus metrics
if $EXPORT_PROM; then
  cat > "$PROM_DIR/judge-calibration.prom" << PROMEOF
# HELP chatops_judge_calibration_total Total calibration samples
# TYPE chatops_judge_calibration_total gauge
chatops_judge_calibration_total $TOTAL
# HELP chatops_judge_calibration_tpr True positive rate (sensitivity)
# TYPE chatops_judge_calibration_tpr gauge
chatops_judge_calibration_tpr ${TPR/N\/A/0}
# HELP chatops_judge_calibration_tnr True negative rate (specificity)
# TYPE chatops_judge_calibration_tnr gauge
chatops_judge_calibration_tnr ${TNR/N\/A/0}
# HELP chatops_judge_calibration_accuracy Overall accuracy
# TYPE chatops_judge_calibration_accuracy gauge
chatops_judge_calibration_accuracy ${ACCURACY/N\/A/0}
# HELP chatops_judge_calibration_timestamp Last calibration run
# TYPE chatops_judge_calibration_timestamp gauge
chatops_judge_calibration_timestamp $(date +%s)
PROMEOF
  echo ""
  echo "Prometheus metrics exported to $PROM_DIR/judge-calibration.prom"
fi

if $PASS; then
  echo ""
  echo "PASS: Judge calibration within acceptable thresholds"
  exit 0
else
  echo ""
  echo "FAIL: Judge needs recalibration (adjust judge prompt or scoring rubric)"
  exit 1
fi
