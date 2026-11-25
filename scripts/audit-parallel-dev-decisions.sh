#!/usr/bin/env bash
# audit-parallel-dev-decisions.sh — weekly audit of parallel-dev auto-merge decisions
# (IFRNLLEI01PRD-928 Phase 6, sibling of audit-risk-decisions.sh for cc-cc infra side)
#
# Reports on the 7-day rolling window:
#  - How many features completed
#  - Auto-merge rate
#  - needs-human rate (and reasons)
#  - Failed-feature rate
#
# Intended to run from /etc/cron.weekly/. Emits to stdout; cron-mailer ships it.

set -euo pipefail

DB=/home/app-user/gateway-state/gateway.db
SINCE=$(( $(date +%s) - 7*86400 ))

echo "=== parallel-dev decision audit — 7-day window starting $(date -d @$SINCE -Iseconds) ==="
echo

echo "== features by status (7d) =="
sqlite3 "$DB" "
SELECT status, count(*) AS n
  FROM features
 WHERE created_at >= $SINCE
 GROUP BY status
 ORDER BY n DESC;"

echo
echo "== merged features (with MR + risk score) =="
sqlite3 -header -column "$DB" "
SELECT feature_id, repo_slug,
       round(feature_risk_score, 2) AS risk,
       total_work_units AS workers,
       mr_iid,
       round((completed_at - created_at) / 60.0, 1) AS mins
  FROM features
 WHERE status='done' AND created_at >= $SINCE
 ORDER BY created_at DESC
 LIMIT 30;"

echo
echo "== failed features (need investigation) =="
sqlite3 -header -column "$DB" "
SELECT feature_id, repo_slug,
       round(feature_risk_score, 2) AS risk,
       total_work_units AS workers
  FROM features
 WHERE status IN ('failed','aborted') AND created_at >= $SINCE
 ORDER BY created_at DESC
 LIMIT 30;"

echo
echo "== per-worker failure modes (work_units status) =="
sqlite3 -header -column "$DB" "
SELECT status, count(*) AS n
  FROM work_units
 WHERE created_at >= $SINCE
 GROUP BY status
 ORDER BY n DESC;"

echo
echo "== auto-merge eligibility (live classifier check on this week's features) =="
for fid in $(sqlite3 "$DB" "SELECT feature_id FROM features WHERE created_at >= $SINCE ORDER BY created_at DESC LIMIT 20"); do
  /home/app-user/gateway-state/bin/classify-feature-risk.py "$fid" --json 2>/dev/null \
    | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(f'  {r[\"feature_id\"]:25s}  auto_merge={r[\"auto_merge\"]}  risk={r.get(\"feature_risk_score\",0):.2f}  failed={r.get(\"failed_count\",0)}')"
done
