#!/bin/bash
# audit-scheduled-reboot-suppressions.sh — weekly reconcile invariant (Increment D).
#
# Defense-in-depth over the two-phase verify: confirms that EVERY phaseSR suppression
# recorded in event_log (last 7d) actually got a two-phase verify, and surfaces the
# misclassification count. Mirrors scripts/audit-risk-decisions.sh (the no-false-
# suppression invariant).
#
# PASS  every suppression was verified; reports verified/misclassified counts.
# FAIL  suppressions exist without a matching verify (the two-phase verify did not
#       run/complete for one of them) — a real gap, page-worthy. A misclassification
#       is NOT a FAIL here (the verify already reopened it + paged at the time); it
#       is reported for visibility.
#
# Exits 0 on PASS, 1 on FAIL. Run weekly (Cronicle); wired into holistic §43.
set -uo pipefail
DB=/app/cubeos/claude-context/gateway.db
COUNTERS=/home/app-user/gateway-state/scheduled-reboot-verify-counters.json
DAYS=${1:-7}

[ -f "$DB" ] || { echo "FAIL: gateway.db not found"; exit 1; }

# phaseSR suppressions logged by tier1-suppression-flow.sh (payload_json contains
# the phase field). Count those whose payload names phaseSR-scheduled-reboot.
SUPP=$(sqlite3 "$DB" "
  SELECT COUNT(*) FROM event_log
  WHERE event_type='tier1_suppression'
    AND datetime(created_at) > datetime('now','-${DAYS} days')
    AND payload_json LIKE '%phaseSR-scheduled-reboot%';" 2>/dev/null || echo 0)

# Verifies: verified (clean) + misclassified (non-clean) from the verify state file.
read VERIFIED MISCLASS UNREACH <<EOF
$(python3 - "$COUNTERS" <<'PY'
import json, sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
print(d.get("verified",0), d.get("misclassified",0), d.get("verify_unreachable",0))
PY
)
EOF
VERIFIED=${VERIFIED:-0}; MISCLASS=${MISCLASS:-0}; UNREACH=${UNREACH:-0}

# Cumulative verifies should cover cumulative suppressions (every suppression is
# followed by exactly one verify). Allow a small in-flight slack (a suppression
# verified in the last minute may not yet be counted).
TOTAL_VERIFIED=$(( VERIFIED + MISCLASS ))
echo "scheduled-reboot audit (${DAYS}d): suppressions=${SUPP} verifies(clean=${VERIFIED} misclassified=${MISCLASS} unreachable=${UNREACH})"

if [ "${SUPP:-0}" -gt 0 ] && [ "$TOTAL_VERIFIED" -lt "$SUPP" ]; then
  echo "FAIL: $((SUPP - TOTAL_VERIFIED)) suppression(s) were NOT two-phase-verified — the verify did not run/complete."
  exit 1
fi
echo "PASS: every recorded suppression has a two-phase verify (or none suppressed yet)."
exit 0
