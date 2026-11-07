#!/bin/bash
# audit-renovate-decisions.sh — weekly band-aware invariant auditor for the Renovate MR Autonomy
# lane (IFRNLLEI01PRD-1645). Mirrors audit-risk-decisions.sh.
#
# INVARIANT (FAIL/exit 1 if any row matches): a LIVE, AUTO decision that bypassed the safety floor —
#   CI not green, review not APPROVE, or a required/critical-tier snapshot not verified.
# shadow-mode rows are exempt (they never enact). Read-only; safe anytime. Used by the weekly cron
# + holistic-agentic-health.sh.
set -u
DB="${GATEWAY_DB:-/home/app-user/gateway-state/gateway.db}"
DAYS="${1:-90}"
[ -f "$DB" ] || { echo "DB not found: $DB" >&2; exit 1; }

sql(){ sqlite3 "$DB" "$1" 2>/dev/null; }
have=$(sql "SELECT name FROM sqlite_master WHERE type='table' AND name='renovate_autonomy_audit'")
[ -z "$have" ] && { echo "renovate_autonomy_audit table absent (lane never ran) — nothing to audit."; exit 0; }

SINCE=$(( $(date -u +%s) - DAYS*86400 ))
FLOOR="mode='live' AND decision='AUTO' AND (
     ci_status != 'success'
  OR review_verdict != 'APPROVE'
  OR ( (snapshot_required='true' OR tier='critical')
       AND COALESCE(json_extract(gates_json,'\$.snapshot_verified'),0) != 1 ) )"

echo "=== Renovate MR Autonomy invariant audit (last ${DAYS}d) ==="
echo "-- decisions by outcome/tier/mode --"
sql "SELECT decision, COALESCE(NULLIF(tier,''),'none') tier, mode, COUNT(*) n
     FROM renovate_autonomy_audit WHERE ts >= $SINCE
     GROUP BY decision, tier, mode ORDER BY n DESC;" | sed 's/^/  /'

VIOL=$(sql "SELECT COUNT(*) FROM renovate_autonomy_audit WHERE ts >= $SINCE AND ($FLOOR);")
VIOL=${VIOL:-0}
echo "-- floor breaches (live AUTO without CI-green ∧ review-APPROVE ∧ verified-snapshot): $VIOL --"
if [ "$VIOL" -gt 0 ]; then
  echo "!! INVARIANT VIOLATION — offending rows:" >&2
  sql "SELECT id, project_id, mr_iid, tier, ci_status, review_verdict, gates_json
       FROM renovate_autonomy_audit WHERE ts >= $SINCE AND ($FLOOR);" | sed 's/^/  /' >&2
  echo "   Freeze the lane immediately:  rm ~/gateway.renovate_autonomy" >&2
  exit 1
fi
echo "OK — no floor breaches. Invariant holds."
exit 0
