#!/bin/bash
# write-sla-metrics.sh — SLA and timing Prometheus metrics
# Cron: */5 * * * * (same cadence as session metrics)

DB="/app/cubeos/claude-context/gateway.db"
OUT="/var/lib/node_exporter/textfile_collector/sla_metrics.prom"
TMPOUT="${OUT}.tmp"

[ -f "$DB" ] || exit 0
> "$TMPOUT"

# ── MTTR: Mean Time to Resolution (session started_at to ended_at) ──
echo "# HELP chatops_sla_mttr_avg_seconds Average time from session start to end (30d)" >> "$TMPOUT"
echo "# TYPE chatops_sla_mttr_avg_seconds gauge" >> "$TMPOUT"
sqlite3 "$DB" "
SELECT
  CASE
    WHEN issue_id LIKE 'IFRNLLEI01PRD-%' THEN 'infra-nl'
    WHEN issue_id LIKE 'IFRGRSKG01PRD-%' THEN 'infra-gr'
    ELSE 'dev'
  END AS project,
  COALESCE(AVG(CAST((julianday(ended_at) - julianday(started_at)) * 86400 AS INTEGER)), 0)
FROM session_log
WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
  AND started_at > datetime('now', '-30 days')
GROUP BY project;" 2>/dev/null | \
while IFS='|' read -r project mttr; do
    echo "chatops_sla_mttr_avg_seconds{project=\"$project\"} $mttr"
done >> "$TMPOUT"

# ── MTTR P90 ──
echo "# HELP chatops_sla_mttr_p90_seconds P90 resolution time (30d)" >> "$TMPOUT"
echo "# TYPE chatops_sla_mttr_p90_seconds gauge" >> "$TMPOUT"
sqlite3 "$DB" "
SELECT
  CASE
    WHEN issue_id LIKE 'IFRNLLEI01PRD-%' THEN 'infra-nl'
    WHEN issue_id LIKE 'IFRGRSKG01PRD-%' THEN 'infra-gr'
    ELSE 'dev'
  END AS project,
  CAST((julianday(ended_at) - julianday(started_at)) * 86400 AS INTEGER) AS dur
FROM session_log
WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
  AND started_at > datetime('now', '-30 days')
ORDER BY dur;" 2>/dev/null | \
python3 -c "
import sys
from collections import defaultdict
data = defaultdict(list)
for line in sys.stdin:
    parts = line.strip().split('|')
    if len(parts) == 2:
        data[parts[0]].append(int(parts[1]))
for project, durations in data.items():
    if durations:
        idx = int(len(durations) * 0.9)
        print(f'chatops_sla_mttr_p90_seconds{{project=\"{project}\"}} {durations[min(idx, len(durations)-1)]}')
" 2>/dev/null >> "$TMPOUT"

# ── Session duration stats (by project) ──
echo "# HELP chatops_sla_session_duration_avg Average session duration seconds (30d)" >> "$TMPOUT"
echo "# TYPE chatops_sla_session_duration_avg gauge" >> "$TMPOUT"
sqlite3 "$DB" "
SELECT
  CASE
    WHEN issue_id LIKE 'IFRNLLEI01PRD-%' THEN 'infra-nl'
    WHEN issue_id LIKE 'IFRGRSKG01PRD-%' THEN 'infra-gr'
    ELSE 'dev'
  END AS project,
  COALESCE(AVG(duration_seconds), 0)
FROM session_log
WHERE duration_seconds > 0 AND started_at > datetime('now', '-30 days')
GROUP BY project;" 2>/dev/null | \
while IFS='|' read -r project avg_dur; do
    echo "chatops_sla_session_duration_avg{project=\"$project\"} $avg_dur"
done >> "$TMPOUT"

# ── Quality score trends ──
echo "# HELP chatops_quality_7d Rolling 7-day quality score average" >> "$TMPOUT"
echo "# TYPE chatops_quality_7d gauge" >> "$TMPOUT"
Q7D=$(sqlite3 "$DB" "SELECT COALESCE(AVG(quality_score),0) FROM session_quality WHERE quality_score >= 0 AND created_at > datetime('now', '-7 days');" 2>/dev/null || echo 0)
echo "chatops_quality_7d $Q7D" >> "$TMPOUT"

echo "# HELP chatops_quality_30d Rolling 30-day quality score average" >> "$TMPOUT"
echo "# TYPE chatops_quality_30d gauge" >> "$TMPOUT"
Q30D=$(sqlite3 "$DB" "SELECT COALESCE(AVG(quality_score),0) FROM session_quality WHERE quality_score >= 0 AND created_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chatops_quality_30d $Q30D" >> "$TMPOUT"

# ── Quality dimensions (7d averages) ──
echo "# HELP chatops_quality_dimension_7d Rolling 7-day dimension averages" >> "$TMPOUT"
echo "# TYPE chatops_quality_dimension_7d gauge" >> "$TMPOUT"
for dim in confidence_score cost_efficiency response_completeness feedback_score resolution_speed; do
    VAL=$(sqlite3 "$DB" "SELECT COALESCE(AVG($dim),0) FROM session_quality WHERE $dim >= 0 AND created_at > datetime('now', '-7 days');" 2>/dev/null || echo 0)
    echo "chatops_quality_dimension_7d{dimension=\"$dim\"} $VAL"
done >> "$TMPOUT"

# ── Escalation count (A2A task log) ──
echo "# HELP chatops_sla_escalations_30d Escalations in last 30 days" >> "$TMPOUT"
echo "# TYPE chatops_sla_escalations_30d gauge" >> "$TMPOUT"
ESC=$(sqlite3 "$DB" "SELECT COUNT(*) FROM a2a_task_log WHERE message_type='escalation' AND created_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chatops_sla_escalations_30d $ESC" >> "$TMPOUT"

# ── Time to first feedback (session start to first reaction) ──
echo "# HELP chatops_sla_feedback_latency_avg Average seconds from session start to first feedback (30d)" >> "$TMPOUT"
echo "# TYPE chatops_sla_feedback_latency_avg gauge" >> "$TMPOUT"
FEED_LAT=$(sqlite3 "$DB" "
SELECT COALESCE(AVG(CAST((julianday(sf.created_at) - julianday(sl.started_at)) * 86400 AS INTEGER)), 0)
FROM session_log sl
JOIN session_feedback sf ON sl.issue_id = sf.issue_id
WHERE sl.started_at > datetime('now', '-30 days')
  AND sf.created_at > sl.started_at;" 2>/dev/null || echo 0)
echo "chatops_sla_feedback_latency_avg $FEED_LAT" >> "$TMPOUT"

mv "$TMPOUT" "$OUT"
