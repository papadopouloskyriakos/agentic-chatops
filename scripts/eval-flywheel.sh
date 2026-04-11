#!/usr/bin/env bash
# Evaluation Flywheel — monthly Analyze>Measure>Improve cycle
# Cron: 0 4 1 * * (1st of month, 04:00 UTC)
# Implements OpenAI eval best practice: continuous quality improvement
#
# Usage:
#   eval-flywheel.sh                  # Full cycle (Analyze + Measure + Improve)
#   eval-flywheel.sh --analyze-only   # Phase 1 only (dry run)
#   eval-flywheel.sh --no-post        # Skip Matrix notification
set -euo pipefail
source "$(dirname "$0")/eval-config.sh" 2>/dev/null || true

DB="${EVAL_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
MONTH=$(date +%Y%m)
PREV_MONTH=$(date -d "last month" +%Y%m 2>/dev/null || date -v-1m +%Y%m 2>/dev/null || echo "000000")
REPORT="/tmp/eval-flywheel-${MONTH}.json"
PROM_FILE="/var/lib/node_exporter/textfile_collector/eval_flywheel.prom"
LOG_TAG="[eval-flywheel]"

ANALYZE_ONLY=false
NO_POST=false
while [ $# -gt 0 ]; do
  case "$1" in
    --analyze-only) ANALYZE_ONLY=true; shift ;;
    --no-post) NO_POST=true; shift ;;
    *) shift ;;
  esac
done

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $LOG_TAG $*"; }

# Verify DB exists
if [ ! -f "$DB" ]; then
  log "ERROR: Database not found at $DB"
  exit 1
fi

# Verify session_judgment table exists
if ! sqlite3 "$DB" "SELECT 1 FROM session_judgment LIMIT 0" 2>/dev/null; then
  log "ERROR: session_judgment table does not exist in $DB"
  exit 1
fi

echo "=== EVALUATION FLYWHEEL — $MONTH ==="
echo ""

# ──────────────────────────────────────────────────────────────────────
echo "=== PHASE 1: ANALYZE (last 30 days) ==="
# ──────────────────────────────────────────────────────────────────────

# Total sessions judged in the last 30 days
TOTAL_JUDGED=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
" 2>/dev/null || echo 0)
log "Sessions judged (30d): $TOTAL_JUDGED"

# Guard: exit gracefully when no judgment data exists
if [ "${TOTAL_JUDGED:-0}" -eq 0 ]; then
  log "CRITICAL: No sessions judged in 30 days. Evaluation pipeline may be broken."
  # Write zero-state prom file so Prometheus doesn't go stale
  if [ -d "$(dirname "$PROM_FILE")" ]; then
    cat > "${PROM_FILE}.tmp" <<PROMEOF
# HELP eval_flywheel_status Evaluation flywheel status (0=no data, 1=healthy)
# TYPE eval_flywheel_status gauge
eval_flywheel_status 0
# HELP chatops_eval_flywheel_judged Sessions judged in last 30 days
# TYPE chatops_eval_flywheel_judged gauge
chatops_eval_flywheel_judged 0
# HELP chatops_eval_flywheel_timestamp Last flywheel run timestamp
# TYPE chatops_eval_flywheel_timestamp gauge
chatops_eval_flywheel_timestamp $(date +%s)
PROMEOF
    mv "${PROM_FILE}.tmp" "$PROM_FILE"
    log "Zero-state Prometheus metrics written to $PROM_FILE"
  fi
  if [ "$NO_POST" = "false" ]; then
    TOKEN_FILE="$HOME/.matrix-claude-token"
    if [ -f "$TOKEN_FILE" ]; then
      TOKEN=$(cat "$TOKEN_FILE")
      ALERTS_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
      TXN="eval-flywheel-zero-${MONTH}-$(date +%s)"
      MSG="CRITICAL: Eval Flywheel $MONTH — 0 sessions judged in 30 days. Pipeline may be broken. Run: llm-judge.sh --backfill"
      curl -sf -X PUT \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"msgtype\":\"m.notice\",\"body\":\"$(echo "$MSG" | sed 's/"/\\"/g')\"}" \
        "${MATRIX_URL:-https://matrix.example.net}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/${TXN}" >/dev/null 2>&1 || true
      log "Zero-data alert posted to Matrix #alerts"
    fi
  fi
  exit 0
fi

# Average scores per dimension (COALESCE handles NULL when no rows match)
DIMENSION_AVGS=$(sqlite3 -separator '|' "$DB" "
  SELECT
    COALESCE(ROUND(AVG(CASE WHEN investigation_quality > 0 THEN investigation_quality END), 2), 0) AS avg_iq,
    COALESCE(ROUND(AVG(CASE WHEN evidence_based > 0 THEN evidence_based END), 2), 0) AS avg_eb,
    COALESCE(ROUND(AVG(CASE WHEN actionability > 0 THEN actionability END), 2), 0) AS avg_ac,
    COALESCE(ROUND(AVG(CASE WHEN safety_compliance > 0 THEN safety_compliance END), 2), 0) AS avg_sc,
    COALESCE(ROUND(AVG(CASE WHEN completeness > 0 THEN completeness END), 2), 0) AS avg_cm,
    COALESCE(ROUND(AVG(CASE WHEN overall_score > 0 THEN overall_score END), 2), 0) AS avg_overall
  FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
" 2>/dev/null || echo "0|0|0|0|0|0")

AVG_IQ=$(echo "$DIMENSION_AVGS" | cut -d'|' -f1)
AVG_EB=$(echo "$DIMENSION_AVGS" | cut -d'|' -f2)
AVG_AC=$(echo "$DIMENSION_AVGS" | cut -d'|' -f3)
AVG_SC=$(echo "$DIMENSION_AVGS" | cut -d'|' -f4)
AVG_CM=$(echo "$DIMENSION_AVGS" | cut -d'|' -f5)
AVG_OVERALL=$(echo "$DIMENSION_AVGS" | cut -d'|' -f6)

log "Averages: IQ=$AVG_IQ EB=$AVG_EB AC=$AVG_AC SC=$AVG_SC CM=$AVG_CM Overall=$AVG_OVERALL"

# Count low scores (any dimension < 3) grouped by dimension
LOW_SCORES=$(sqlite3 -json "$DB" "
  SELECT
    'investigation_quality' AS dimension,
    COUNT(*) AS low_count,
    GROUP_CONCAT(issue_id, ', ') AS examples
  FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND investigation_quality > 0 AND investigation_quality < 3
  UNION ALL
  SELECT
    'evidence_based' AS dimension,
    COUNT(*) AS low_count,
    GROUP_CONCAT(issue_id, ', ') AS examples
  FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND evidence_based > 0 AND evidence_based < 3
  UNION ALL
  SELECT
    'actionability' AS dimension,
    COUNT(*) AS low_count,
    GROUP_CONCAT(issue_id, ', ') AS examples
  FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND actionability > 0 AND actionability < 3
  UNION ALL
  SELECT
    'safety_compliance' AS dimension,
    COUNT(*) AS low_count,
    GROUP_CONCAT(issue_id, ', ') AS examples
  FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND safety_compliance > 0 AND safety_compliance < 3
  UNION ALL
  SELECT
    'completeness' AS dimension,
    COUNT(*) AS low_count,
    GROUP_CONCAT(issue_id, ', ') AS examples
  FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND completeness > 0 AND completeness < 3
" 2>/dev/null || echo "[]")

# Rejection rate
REJECT_COUNT=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND recommended_action = 'reject'
" 2>/dev/null || echo 0)

IMPROVE_COUNT=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND recommended_action = 'improve'
" 2>/dev/null || echo 0)

APPROVE_COUNT=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND recommended_action = 'approve'
" 2>/dev/null || echo 0)

log "Actions: approve=$APPROVE_COUNT improve=$IMPROVE_COUNT reject=$REJECT_COUNT"

# Top concerns from rejected/improve sessions
TOP_CONCERNS=$(sqlite3 -json "$DB" "
  SELECT issue_id, overall_score, recommended_action, concerns
  FROM session_judgment
  WHERE judged_at >= datetime('now', '-30 days')
    AND recommended_action IN ('reject', 'improve')
    AND concerns != ''
  ORDER BY overall_score ASC
  LIMIT 5
" 2>/dev/null || echo "[]")

if [ "$ANALYZE_ONLY" = true ]; then
  log "Analyze-only mode — skipping Measure and Improve phases"
  # Still generate partial report
  python3 -c "
import json, sys

def safe_float(v, default=0.0):
    try:
        return float(v) if v else default
    except (ValueError, TypeError):
        return default

def safe_json(s):
    try:
        return json.loads(s) if s and s != '[]' else []
    except (json.JSONDecodeError, ValueError):
        return []

report = {
    'month': '$MONTH',
    'phase': 'analyze_only',
    'total_judged': int('${TOTAL_JUDGED:-0}' or 0),
    'averages': {
        'investigation_quality': safe_float('${AVG_IQ:-0}'),
        'evidence_based': safe_float('${AVG_EB:-0}'),
        'actionability': safe_float('${AVG_AC:-0}'),
        'safety_compliance': safe_float('${AVG_SC:-0}'),
        'completeness': safe_float('${AVG_CM:-0}'),
        'overall': safe_float('${AVG_OVERALL:-0}')
    },
    'action_breakdown': {
        'approve': int('${APPROVE_COUNT:-0}' or 0),
        'improve': int('${IMPROVE_COUNT:-0}' or 0),
        'reject': int('${REJECT_COUNT:-0}' or 0)
    },
    'low_scores': safe_json('''$LOW_SCORES'''),
    'top_concerns': safe_json('''$TOP_CONCERNS''')
}
with open('$REPORT', 'w') as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2))
" 2>/dev/null
  log "Report saved to $REPORT"
  exit 0
fi

# ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== PHASE 2: MEASURE ==="
# ──────────────────────────────────────────────────────────────────────

# Run holdout set (offline-safe subset for CI environments)
HOLDOUT_PASS=0
HOLDOUT_FAIL=0
HOLDOUT_TOTAL=0

if [ -f "$REPO/scripts/eval-sets/regression.json" ]; then
  log "Running holdout measurement via golden-test-suite --set regression --offline..."
  HOLDOUT_OUTPUT=$(bash "$REPO/scripts/golden-test-suite.sh" --set regression --offline 2>&1 || true)
  HOLDOUT_PASS=$(echo "$HOLDOUT_OUTPUT" | grep -c "PASS:" || true)
  HOLDOUT_FAIL=$(echo "$HOLDOUT_OUTPUT" | grep -c "FAIL:" || true)
  # Ensure numeric values (grep -c with || true can produce empty on some shells)
  HOLDOUT_PASS="${HOLDOUT_PASS:-0}"
  HOLDOUT_FAIL="${HOLDOUT_FAIL:-0}"
  HOLDOUT_TOTAL=$((HOLDOUT_PASS + HOLDOUT_FAIL))
  log "Holdout results: $HOLDOUT_PASS/$HOLDOUT_TOTAL passed"
else
  log "WARNING: No regression eval set found, skipping holdout measurement"
fi

# Compare with previous month's results (from Prometheus file)
PREV_PASS_RATE="N/A"
PREV_HOLDOUT_PASS=0
PREV_HOLDOUT_TOTAL=0
PREV_REPORT="/tmp/eval-flywheel-${PREV_MONTH}.json"
if [ -f "$PREV_REPORT" ]; then
  PREV_HOLDOUT_PASS=$(python3 -c "
import json
with open('$PREV_REPORT') as f:
    d = json.load(f)
print(d.get('measure', {}).get('holdout_pass', 0))
" 2>/dev/null || echo 0)
  PREV_HOLDOUT_TOTAL=$(python3 -c "
import json
with open('$PREV_REPORT') as f:
    d = json.load(f)
print(d.get('measure', {}).get('holdout_total', 0))
" 2>/dev/null || echo 0)
  if [ "$PREV_HOLDOUT_TOTAL" -gt 0 ] 2>/dev/null; then
    PREV_PASS_RATE=$(python3 -c "print(round($PREV_HOLDOUT_PASS / $PREV_HOLDOUT_TOTAL * 100, 1))" 2>/dev/null || echo "N/A")
  fi
fi

CURR_PASS_RATE="N/A"
if [ "$HOLDOUT_TOTAL" -gt 0 ] 2>/dev/null; then
  CURR_PASS_RATE=$(python3 -c "print(round($HOLDOUT_PASS / $HOLDOUT_TOTAL * 100, 1))" 2>/dev/null || echo "N/A")
fi

log "Pass rate: current=${CURR_PASS_RATE}% previous=${PREV_PASS_RATE}%"

# Overfitting detection: compare regression pass rate improvement vs holdout stagnation
# Pull the golden-test.prom for regression pass rate (run every 2 weeks)
GOLDEN_PROM="$HOME/gitlab/products/cubeos/claude-context/golden-test.prom"
REGRESSION_PASS=0
REGRESSION_TOTAL=0
if [ -f "$GOLDEN_PROM" ]; then
  # Prom file uses labeled metrics: chatops_golden_test_pass{set="regression"} 56
  # Skip comment/HELP/TYPE lines (start with #)
  REGRESSION_PASS=$(grep -v "^#" "$GOLDEN_PROM" 2>/dev/null | grep "chatops_golden_test_pass" | head -1 | awk '{print $2}' || true)
  REGRESSION_TOTAL=$(grep -v "^#" "$GOLDEN_PROM" 2>/dev/null | grep "chatops_golden_test_total" | head -1 | awk '{print $2}' || true)
  # Default to 0 if empty
  REGRESSION_PASS="${REGRESSION_PASS:-0}"
  REGRESSION_TOTAL="${REGRESSION_TOTAL:-0}"
fi

OVERFIT_WARNING="false"
if [ "$REGRESSION_TOTAL" -gt 0 ] 2>/dev/null && [ "$HOLDOUT_TOTAL" -gt 0 ] 2>/dev/null; then
  OVERFIT_WARNING=$(python3 -c "
reg_rate = $REGRESSION_PASS / $REGRESSION_TOTAL * 100
hold_rate = $HOLDOUT_PASS / $HOLDOUT_TOTAL * 100
# Overfitting signal: regression >95% but holdout <80%, or gap >20 points
if reg_rate > 95 and hold_rate < 80:
    print('true')
elif (reg_rate - hold_rate) > 20:
    print('true')
else:
    print('false')
" 2>/dev/null || echo "false")
fi

if [ "$OVERFIT_WARNING" = "true" ]; then
  log "WARNING: Possible overfitting detected — regression pass rate high but holdout stagnant"
fi

# ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== PHASE 3: IMPROVE ==="
# ──────────────────────────────────────────────────────────────────────

# Generate improvement suggestions based on low-scoring dimensions
IMPROVEMENTS=$(python3 -c "
import json

low_scores = json.loads('''$LOW_SCORES''') if '''$LOW_SCORES''' != '[]' else []
suggestions = []

dimension_fixes = {
    'investigation_quality': {
        'prompt': 'Add explicit THOUGHT/ACTION/OBSERVATION chain requirement to Build Prompt',
        'tooling': 'Verify SSH connectivity to investigation targets before session start',
        'training': 'Add negative example showing hallucinated vs real investigation'
    },
    'evidence_based': {
        'prompt': 'Require citing specific command output in every claim',
        'tooling': 'Inject RAG results from incident_knowledge with higher relevance threshold',
        'training': 'Grade existing high-scoring sessions as few-shot examples'
    },
    'actionability': {
        'prompt': 'Enforce step-by-step remediation format with numbered commands',
        'tooling': 'Auto-inject playbook-lookup results for known issue patterns',
        'training': 'Add POLL option requirement for any system-modifying action'
    },
    'safety_compliance': {
        'prompt': 'Strengthen human-in-the-loop language in system prompt',
        'tooling': 'Add PreToolUse hook for destructive commands',
        'training': 'Add golden test for unauthorized change detection'
    },
    'completeness': {
        'prompt': 'Add checklist reminder (CONFIDENCE, category, structured fields)',
        'tooling': 'Post-process validation before Matrix post',
        'training': 'Reject responses missing CONFIDENCE in eval set'
    }
}

for item in low_scores:
    dim = item.get('dimension', '')
    count = item.get('low_count', 0)
    if count > 0 and dim in dimension_fixes:
        suggestions.append({
            'dimension': dim,
            'failures': count,
            'examples': (item.get('examples', '') or '')[:200],
            'fixes': dimension_fixes[dim]
        })

# Sort by failure count descending
suggestions.sort(key=lambda x: x['failures'], reverse=True)
print(json.dumps(suggestions, indent=2))
" 2>/dev/null || echo "[]")

log "Improvement suggestions generated"

# Run prompt improver to apply patches based on low-scoring dimensions
log "Running prompt improver..."
python3 "$REPO/scripts/prompt-improver.py" --apply 2>/dev/null || log "WARN: prompt-improver failed"

# ──────────────────────────────────────────────────────────────────────
# Build final JSON report
# ──────────────────────────────────────────────────────────────────────

OVERFIT_PYTHON=$( [ "$OVERFIT_WARNING" = "true" ] && echo "True" || echo "False" )

python3 -c "
import json

def safe_float(v, default=0.0):
    try:
        return float(v) if v else default
    except (ValueError, TypeError):
        return default

def safe_json(s):
    try:
        return json.loads(s) if s and s != '[]' else []
    except (json.JSONDecodeError, ValueError):
        return []

report = {
    'month': '$MONTH',
    'generated_at': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
    'analyze': {
        'total_judged': int('${TOTAL_JUDGED:-0}' or 0),
        'averages': {
            'investigation_quality': safe_float('${AVG_IQ:-0}'),
            'evidence_based': safe_float('${AVG_EB:-0}'),
            'actionability': safe_float('${AVG_AC:-0}'),
            'safety_compliance': safe_float('${AVG_SC:-0}'),
            'completeness': safe_float('${AVG_CM:-0}'),
            'overall': safe_float('${AVG_OVERALL:-0}')
        },
        'action_breakdown': {
            'approve': int('${APPROVE_COUNT:-0}' or 0),
            'improve': int('${IMPROVE_COUNT:-0}' or 0),
            'reject': int('${REJECT_COUNT:-0}' or 0)
        },
        'low_scores': safe_json('''$LOW_SCORES'''),
        'top_concerns': safe_json('''$TOP_CONCERNS''')
    },
    'measure': {
        'holdout_pass': int('${HOLDOUT_PASS:-0}' or 0),
        'holdout_fail': int('${HOLDOUT_FAIL:-0}' or 0),
        'holdout_total': int('${HOLDOUT_TOTAL:-0}' or 0),
        'pass_rate_pct': safe_float('$CURR_PASS_RATE') if '$CURR_PASS_RATE' != 'N/A' else None,
        'previous_pass_rate_pct': safe_float('$PREV_PASS_RATE') if '$PREV_PASS_RATE' != 'N/A' else None,
        'regression_pass': int('${REGRESSION_PASS:-0}' or 0),
        'regression_total': int('${REGRESSION_TOTAL:-0}' or 0),
        'overfitting_warning': $OVERFIT_PYTHON
    },
    'improve': {
        'suggestions': safe_json('''$IMPROVEMENTS'''),
        'overfit_warning': $OVERFIT_PYTHON
    }
}

with open('$REPORT', 'w') as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2))
" 2>/dev/null

log "Report saved to $REPORT"

# ──────────────────────────────────────────────────────────────────────
# Write Prometheus metrics
# ──────────────────────────────────────────────────────────────────────

if [ -d "$(dirname "$PROM_FILE")" ]; then
  cat > "${PROM_FILE}.tmp" <<PROMEOF
# HELP chatops_eval_flywheel_judged Sessions judged in last 30 days
# TYPE chatops_eval_flywheel_judged gauge
chatops_eval_flywheel_judged $TOTAL_JUDGED
# HELP chatops_eval_flywheel_avg_overall Average overall score (1-5)
# TYPE chatops_eval_flywheel_avg_overall gauge
chatops_eval_flywheel_avg_overall ${AVG_OVERALL:-0}
# HELP chatops_eval_flywheel_approve_count Sessions recommended approve
# TYPE chatops_eval_flywheel_approve_count gauge
chatops_eval_flywheel_approve_count $APPROVE_COUNT
# HELP chatops_eval_flywheel_reject_count Sessions recommended reject
# TYPE chatops_eval_flywheel_reject_count gauge
chatops_eval_flywheel_reject_count $REJECT_COUNT
# HELP chatops_eval_flywheel_holdout_pass Holdout set pass count
# TYPE chatops_eval_flywheel_holdout_pass gauge
chatops_eval_flywheel_holdout_pass $HOLDOUT_PASS
# HELP chatops_eval_flywheel_holdout_total Holdout set total count
# TYPE chatops_eval_flywheel_holdout_total gauge
chatops_eval_flywheel_holdout_total $HOLDOUT_TOTAL
# HELP chatops_eval_flywheel_overfit Overfitting warning flag (0=ok, 1=warning)
# TYPE chatops_eval_flywheel_overfit gauge
chatops_eval_flywheel_overfit $([ "$OVERFIT_WARNING" = "true" ] && echo 1 || echo 0)
# HELP chatops_eval_flywheel_timestamp Last flywheel run timestamp
# TYPE chatops_eval_flywheel_timestamp gauge
chatops_eval_flywheel_timestamp $(date +%s)
PROMEOF
  mv "${PROM_FILE}.tmp" "$PROM_FILE"
  log "Prometheus metrics written to $PROM_FILE"
fi

# ──────────────────────────────────────────────────────────────────────
# Post summary to Matrix #alerts
# ──────────────────────────────────────────────────────────────────────

if [ "$NO_POST" = false ]; then
  TOKEN_FILE="$HOME/.matrix-claude-token"
  if [ -f "$TOKEN_FILE" ]; then
    TOKEN=$(cat "$TOKEN_FILE")
    ALERTS_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
    TXN="eval-flywheel-${MONTH}-$(date +%s)"

    # Build summary message
    OVERFIT_MSG=""
    [ "$OVERFIT_WARNING" = "true" ] && OVERFIT_MSG=" | OVERFITTING WARNING"

    MSG="Eval Flywheel $MONTH: ${TOTAL_JUDGED} sessions judged | Avg overall: ${AVG_OVERALL:-0}/5 | approve=$APPROVE_COUNT improve=$IMPROVE_COUNT reject=$REJECT_COUNT | Holdout: ${HOLDOUT_PASS}/${HOLDOUT_TOTAL}${OVERFIT_MSG}"

    curl -sf -X PUT \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"msgtype\":\"m.notice\",\"body\":\"$(echo "$MSG" | sed 's/"/\\"/g')\"}" \
      "${MATRIX_URL:-https://matrix.example.net}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/${TXN}" >/dev/null 2>&1 || true
    log "Summary posted to Matrix #alerts"
  else
    log "WARNING: Matrix token not found, skipping notification"
  fi
fi

echo ""
echo "=== FLYWHEEL COMPLETE ==="
