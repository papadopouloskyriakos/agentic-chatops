#!/bin/bash
# audit-risk-decisions.sh — IFRNLLEI01PRD-632
#
# Inspect session_risk_audit rows and emit:
#  - Summary: auto-approval rate by category
#  - Red-flag check: any auto_approved=1 row for risk_level != 'low'
#    (should never happen — the classifier only auto-approves on low,
#    but an operator manual override or a classifier bug would surface here)
#  - Top matched signals by frequency
#
# Read-only; safe to run anytime. Used by the weekly audit cron and by
# holistic-agentic-health.sh.

set -u
DB="${GATEWAY_DB:-/app/cubeos/claude-context/gateway.db}"
DAYS="${1:-7}"

[ -f "$DB" ] || { echo "DB not found: $DB" >&2; exit 1; }

audit_model_based_invariant() {
  # ── IFRNLLEI01PRD-1044: model-based-invariant audit ─────────────────────────
  # The operator's acceptance test, run weekly: can an approved remediation
  # exist without a machine-computed, committed prediction? Three checks:
  #  (1) structural — the live Runner export still carries the prediction gate
  #      in default-DENY shape (Commit Prediction node + Prepare Result block);
  #  (2) data — every kind='action' prediction joins a session_risk_audit row
  #      on plan_hash (a prediction without a classification is an anomaly);
  #  (3) data — action predictions are being committed at all when mixed/high
  #      sessions flow (zero-rate after gate deploy with nonzero remediation
  #      traffic = the Commit Prediction node silently broke).
  echo
  echo "-- Model-based invariant (IFRNLLEI01PRD-1044) --"
  RUNNER_EXPORT="$(dirname "$0")/../workflows/claude-gateway-runner.json"
  if [ -f "$RUNNER_EXPORT" ]; then
      if grep -q "prediction-gate" "$RUNNER_EXPORT" \
         && grep -q "Commit Prediction" "$RUNNER_EXPORT" \
         && grep -q "POLL-WITHHELD:NO-PREDICTION" "$RUNNER_EXPORT"; then
          echo "OK: Runner export carries the prediction gate (default-deny shape intact)."
      else
          echo "!!! FAIL: Runner export is missing the prediction gate — the invariant is structurally unenforced. Re-check workflow qadF2WcaBsIR7SWG."
          exit 2
      fi
  else
      echo "(runner export not found at $RUNNER_EXPORT — skip structural check)"
  fi
  if sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE name='infragraph_predictions'" | grep -q 1; then
      orphans=$(sqlite3 "$DB" "
        SELECT COUNT(*) FROM infragraph_predictions p
        WHERE p.kind='action'
          AND p.created_at >= datetime('now','-${DAYS} days')
          AND p.plan_hash != ''
          AND NOT EXISTS (SELECT 1 FROM session_risk_audit a WHERE a.plan_hash = p.plan_hash)")
      n_action=$(sqlite3 "$DB" "
        SELECT COUNT(*) FROM infragraph_predictions
        WHERE kind='action' AND created_at >= datetime('now','-${DAYS} days')")
      echo "action predictions (${DAYS}d): ${n_action}; without matching risk-audit row: ${orphans}"
      if [ "$orphans" -gt 0 ]; then
          echo "!!! WARN: ${orphans} action prediction(s) have no session_risk_audit join — investigate plan_hash drift between classify-session-risk.py and infragraph-predict-plan.py."
      fi
  else
      echo "(infragraph_predictions not yet migrated — skip prediction audit)"
  fi
}


echo "=== Risk classification audit — last ${DAYS} days ==="
echo

# Ensure the table exists before querying. schema_version added per
# IFRNLLEI01PRD-635; keep in sync with scripts/lib/schema_version.py.
sqlite3 "$DB" "CREATE TABLE IF NOT EXISTS session_risk_audit (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id          TEXT NOT NULL,
    classified_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    alert_category    TEXT,
    risk_level        TEXT NOT NULL,
    auto_approved     INTEGER NOT NULL DEFAULT 0,
    signals_json      TEXT,
    plan_hash         TEXT,
    operator_override TEXT,
    schema_version    INTEGER DEFAULT 1
)" 2>/dev/null
# IFRNLLEI01PRD-1108: band columns (idempotent; classify-session-risk.py adds them
# too). Tolerate "duplicate column" on already-migrated DBs.
for col in "band TEXT" "auto_proceed_on_timeout INTEGER" "sms_required INTEGER"; do
  sqlite3 "$DB" "ALTER TABLE session_risk_audit ADD COLUMN $col" 2>/dev/null || true
done

total=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days')")
echo "Classifications in window: ${total}"
[ "$total" = "0" ] && { echo "(no rows — nothing to audit yet)"; audit_model_based_invariant; exit 0; }

echo
echo "-- By risk level --"
sqlite3 -header -column "$DB" "SELECT risk_level, COUNT(*) AS n, SUM(auto_approved) AS auto_ok FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days') GROUP BY risk_level ORDER BY n DESC"
echo
echo "-- By alert category --"
sqlite3 -header -column "$DB" "SELECT alert_category, risk_level, COUNT(*) AS n FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days') GROUP BY alert_category, risk_level ORDER BY alert_category, n DESC"
echo
echo "-- Invariant check: no unsafe auto-approval (band-aware, IFRNLLEI01PRD-1102) --"
# Three violation classes, all FAIL:
#  (a) LEGACY rows (band NULL, autonomy-forward off): auto_approved=1 with risk!='low'.
#  (b) AUTONOMY rows: auto_approved=1 but band is NOT an auto band (AUTO/AUTO_NOTICE)
#      — an inconsistency between the flag and the band.
#  (c) ANY auto-approved row carrying a FLOOR signal (irreversible:* / critical:p0-reboot
#      / deviation) — the safety floor must never co-occur with an auto-approval.
INV_WHERE="classified_at >= datetime('now','-${DAYS} days') AND auto_approved = 1 AND (
    (band IS NULL AND risk_level != 'low')
    OR (band IS NOT NULL AND band NOT IN ('AUTO','AUTO_NOTICE'))
    OR signals_json LIKE '%irreversible:%'
    OR signals_json LIKE '%critical:p0-reboot%'
    OR signals_json LIKE '%deviation%'
)"
bad=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_risk_audit WHERE $INV_WHERE")
if [ "$bad" -gt 0 ]; then
    echo "!!! FAIL: ${bad} unsafe auto-approval(s) — auto outside AUTO/AUTO_NOTICE, or a floor signal in an auto row. Detail:"
    sqlite3 -header -column "$DB" "SELECT issue_id, classified_at, alert_category, risk_level, band, operator_override, signals_json FROM session_risk_audit WHERE $INV_WHERE"
    echo "REMEDIATION: freeze the gate with 'rm ~/gateway.autonomy_forward' and inspect classify-session-risk.py band logic."
    exit 1
fi
echo "OK: invariant holds (every auto-approval is low/AUTO/AUTO_NOTICE and floor-free)."

echo
echo "-- Top 10 signals in window --"
sqlite3 "$DB" "SELECT signals_json FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days')" \
  | python3 -c "
import json,sys
from collections import Counter
c = Counter()
for line in sys.stdin:
    try: c.update(json.loads(line))
    except: pass
for sig,n in c.most_common(10):
    print(f'  {n:4d}  {sig}')
"

# IFRNLLEI01PRD-639 (2026-04-20): guardrail rejection invariant.
# Every 'reject_content' or 'deny' rejection in event_log must carry a
# non-empty `message` — otherwise Claude sees an unhelpful denial that
# may cause it to retry blindly. Counts rejections by behavior over the
# same window so the audit surfaces trends week-over-week.
echo
echo "-- Tool guardrail rejections (last ${DAYS} days) --"
has_event_log=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='event_log'" 2>/dev/null || echo 0)
if [ "$has_event_log" = "1" ]; then
    sqlite3 -header -column "$DB" "
      SELECT json_extract(payload_json,'\$.behavior') AS behavior,
             json_extract(payload_json,'\$.tool_name') AS tool,
             COUNT(*) AS n,
             SUM(CASE WHEN COALESCE(json_extract(payload_json,'\$.message'),'')='' THEN 1 ELSE 0 END) AS empty_msg
      FROM event_log
      WHERE event_type='tool_guardrail_rejection'
        AND emitted_at >= datetime('now','-${DAYS} days')
      GROUP BY 1,2 ORDER BY n DESC"
    echo
    echo "-- Invariant check: reject_content rows with empty message --"
    empty_msg=$(sqlite3 "$DB" "
      SELECT COUNT(*) FROM event_log
      WHERE event_type='tool_guardrail_rejection'
        AND emitted_at >= datetime('now','-${DAYS} days')
        AND json_extract(payload_json,'\$.behavior')='reject_content'
        AND COALESCE(json_extract(payload_json,'\$.message'),'') = ''")
    if [ "$empty_msg" -gt 0 ]; then
        echo "!!! FAIL: ${empty_msg} reject_content event(s) had empty message. Rejecting content without an explanation blinds the agent. Check the hook that emitted them."
        exit 2
    fi
    echo "OK: reject_content invariant holds (all have non-empty messages)."
else
    echo "(event_log table not yet migrated — skip rejection audit)"
fi

audit_model_based_invariant
