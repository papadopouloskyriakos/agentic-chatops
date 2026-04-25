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

total=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days')")
echo "Classifications in window: ${total}"
[ "$total" = "0" ] && { echo "(no rows — nothing to audit yet)"; exit 0; }

echo
echo "-- By risk level --"
sqlite3 -header -column "$DB" "SELECT risk_level, COUNT(*) AS n, SUM(auto_approved) AS auto_ok FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days') GROUP BY risk_level ORDER BY n DESC"
echo
echo "-- By alert category --"
sqlite3 -header -column "$DB" "SELECT alert_category, risk_level, COUNT(*) AS n FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days') GROUP BY alert_category, risk_level ORDER BY alert_category, n DESC"
echo
echo "-- Invariant check: auto_approved rows with risk_level != 'low' --"
bad=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days') AND auto_approved = 1 AND risk_level != 'low'")
if [ "$bad" -gt 0 ]; then
    echo "!!! FAIL: ${bad} auto-approved row(s) had risk_level != 'low'. Detail:"
    sqlite3 -header -column "$DB" "SELECT issue_id, classified_at, alert_category, risk_level, operator_override, signals_json FROM session_risk_audit WHERE classified_at >= datetime('now','-${DAYS} days') AND auto_approved = 1 AND risk_level != 'low'"
    exit 1
fi
echo "OK: invariant holds (no non-low auto-approvals)."

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
