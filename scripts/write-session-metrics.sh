#!/bin/bash
# write-session-metrics.sh — Session cost and outcome Prometheus metrics
# Runs as cron every 5 minutes on nl-claude01 as app-user
DB=/app/cubeos/claude-context/gateway.db
OUT=/var/lib/node_exporter/textfile_collector/session_metrics.prom
TMPOUT="${OUT}.tmp"

# Bail if DB doesn't exist
[ -f "$DB" ] || exit 0

# Start fresh
> "$TMPOUT"

# Total cost (all time)
echo "# HELP chatops_session_cost_total Total Claude API cost in USD" >> "$TMPOUT"
echo "# TYPE chatops_session_cost_total gauge" >> "$TMPOUT"
TOTAL_COST=$(sqlite3 "$DB" "SELECT COALESCE(SUM(cost_usd),0) FROM session_log WHERE cost_usd > 0;" 2>/dev/null || echo 0)
echo "chatops_session_cost_total $TOTAL_COST" >> "$TMPOUT"

# Cost over rolling 7 days
echo "# HELP chatops_session_cost_7d Claude API cost over last 7 days" >> "$TMPOUT"
echo "# TYPE chatops_session_cost_7d gauge" >> "$TMPOUT"
COST_7D=$(sqlite3 "$DB" "SELECT COALESCE(SUM(cost_usd),0) FROM session_log WHERE cost_usd > 0 AND started_at > datetime('now', '-7 days');" 2>/dev/null || echo 0)
echo "chatops_session_cost_7d $COST_7D" >> "$TMPOUT"

# Average cost per project (last 30 days)
echo "# HELP chatops_session_cost_avg Average session cost by project (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_session_cost_avg gauge" >> "$TMPOUT"
sqlite3 "$DB" "
SELECT
  CASE
    WHEN issue_id LIKE 'IFRNLLEI01PRD-%' THEN 'infra-nl'
    WHEN issue_id LIKE 'IFRGRSKG01PRD-%' THEN 'infra-gr'
    ELSE 'dev'
  END AS project,
  COALESCE(AVG(cost_usd),0)
FROM session_log
WHERE cost_usd > 0 AND started_at > datetime('now', '-30 days')
GROUP BY project;" 2>/dev/null | \
while IFS='|' read -r project avg_cost; do
    echo "chatops_session_cost_avg{project=\"$project\"} $avg_cost"
done >> "$TMPOUT"

# Average duration (last 30 days)
echo "# HELP chatops_session_duration_avg_seconds Average session duration in seconds (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_session_duration_avg_seconds gauge" >> "$TMPOUT"
AVG_DUR=$(sqlite3 "$DB" "SELECT COALESCE(AVG(duration_seconds),0) FROM session_log WHERE duration_seconds > 0 AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chatops_session_duration_avg_seconds $AVG_DUR" >> "$TMPOUT"

# Average turns (last 30 days)
echo "# HELP chatops_session_turns_avg Average turns per session (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_session_turns_avg gauge" >> "$TMPOUT"
AVG_TURNS=$(sqlite3 "$DB" "SELECT COALESCE(AVG(num_turns),0) FROM session_log WHERE num_turns > 0 AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chatops_session_turns_avg $AVG_TURNS" >> "$TMPOUT"

# Average confidence (last 30 days)
echo "# HELP chatops_session_confidence_avg Average confidence score (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_session_confidence_avg gauge" >> "$TMPOUT"
AVG_CONF=$(sqlite3 "$DB" "SELECT COALESCE(AVG(confidence),0) FROM session_log WHERE confidence >= 0 AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chatops_session_confidence_avg $AVG_CONF" >> "$TMPOUT"

# Sessions by resolution type (last 30 days)
echo "# HELP chatops_sessions_by_resolution Sessions by resolution type (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_sessions_by_resolution gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT COALESCE(resolution_type,'unknown'), COUNT(*) FROM session_log WHERE started_at > datetime('now', '-30 days') GROUP BY resolution_type;" 2>/dev/null | \
while IFS='|' read -r rtype count; do
    echo "chatops_sessions_by_resolution{type=\"$rtype\"} $count"
done >> "$TMPOUT"

# Total sessions logged (all time, for reference)
echo "# HELP chatops_sessions_total Total sessions in log" >> "$TMPOUT"
echo "# TYPE chatops_sessions_total gauge" >> "$TMPOUT"
TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log;" 2>/dev/null || echo 0)
echo "chatops_sessions_total $TOTAL" >> "$TMPOUT"

# Knowledge base entries (total + last 90 days)
echo "# HELP chatops_knowledge_entries_total Total entries in incident knowledge base" >> "$TMPOUT"
echo "# TYPE chatops_knowledge_entries_total gauge" >> "$TMPOUT"
KB_TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge;" 2>/dev/null || echo 0)
echo "chatops_knowledge_entries_total $KB_TOTAL" >> "$TMPOUT"

echo "# HELP chatops_knowledge_entries_90d Knowledge entries created in last 90 days" >> "$TMPOUT"
echo "# TYPE chatops_knowledge_entries_90d gauge" >> "$TMPOUT"
KB_90D=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge WHERE created_at > datetime('now', '-90 days');" 2>/dev/null || echo 0)
echo "chatops_knowledge_entries_90d $KB_90D" >> "$TMPOUT"

echo "# HELP chatops_knowledge_embedded_total Knowledge entries with vector embeddings" >> "$TMPOUT"
echo "# TYPE chatops_knowledge_embedded_total gauge" >> "$TMPOUT"
KB_EMBEDDED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM incident_knowledge WHERE embedding IS NOT NULL AND embedding != '';" 2>/dev/null || echo 0)
echo "chatops_knowledge_embedded_total $KB_EMBEDDED" >> "$TMPOUT"

# Feedback counts (all time)
echo "# HELP chatops_feedback_total Total feedback reactions" >> "$TMPOUT"
echo "# TYPE chatops_feedback_total gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT feedback_type, COUNT(*) FROM session_feedback GROUP BY feedback_type;" 2>/dev/null | \
while IFS='|' read -r ftype count; do
    echo "chatops_feedback_total{type=\"$ftype\"} $count"
done >> "$TMPOUT"

# Feedback rate (last 7 days)
echo "# HELP chatops_feedback_7d Feedback reactions in last 7 days" >> "$TMPOUT"
echo "# TYPE chatops_feedback_7d gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT feedback_type, COUNT(*) FROM session_feedback WHERE created_at > datetime('now', '-7 days') GROUP BY feedback_type;" 2>/dev/null | \
while IFS='|' read -r ftype count; do
    echo "chatops_feedback_7d{type=\"$ftype\"} $count"
done >> "$TMPOUT"

# Prompt variant comparison (last 30 days)
echo "# HELP chatops_variant_confidence_avg Avg confidence by prompt variant (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_variant_confidence_avg gauge" >> "$TMPOUT"
echo "# HELP chatops_variant_cost_avg Avg cost by prompt variant (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_variant_cost_avg gauge" >> "$TMPOUT"
echo "# HELP chatops_variant_sessions Sessions by prompt variant (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_variant_sessions gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT prompt_variant, COALESCE(AVG(confidence),-1), COALESCE(AVG(cost_usd),0), COUNT(*)
FROM session_log
WHERE prompt_variant != '' AND prompt_variant IS NOT NULL
  AND started_at > datetime('now', '-30 days')
GROUP BY prompt_variant;" 2>/dev/null | \
while IFS='|' read -r variant avg_conf avg_cost count; do
    [ -z "$variant" ] && continue
    echo "chatops_variant_confidence_avg{variant=\"$variant\"} $avg_conf"
    echo "chatops_variant_cost_avg{variant=\"$variant\"} $avg_cost"
    echo "chatops_variant_sessions{variant=\"$variant\"} $count"
done >> "$TMPOUT"

# Resolution type distribution (last 30 days, with feedback-based scoring)
echo "# HELP chatops_resolution_scored Sessions with scored outcomes (last 30d)" >> "$TMPOUT"
echo "# TYPE chatops_resolution_scored gauge" >> "$TMPOUT"
SCORED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE resolution_type != 'unknown' AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chatops_resolution_scored $SCORED" >> "$TMPOUT"

# Lessons learned (total)
echo "# HELP chatops_lessons_total Total lessons learned entries" >> "$TMPOUT"
echo "# TYPE chatops_lessons_total gauge" >> "$TMPOUT"
LESSONS_TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM lessons_learned;" 2>/dev/null || echo 0)
echo "chatops_lessons_total $LESSONS_TOTAL" >> "$TMPOUT"

# Cost per alert category (30d)
echo "# HELP chatops_cost_by_category Average cost by alert category (30d)" >> "$TMPOUT"
echo "# TYPE chatops_cost_by_category gauge" >> "$TMPOUT"
echo "# HELP chatops_cost_by_category_n Session count by alert category (30d)" >> "$TMPOUT"
echo "# TYPE chatops_cost_by_category_n gauge" >> "$TMPOUT"
echo "# HELP chatops_duration_by_category Average duration by alert category (30d)" >> "$TMPOUT"
echo "# TYPE chatops_duration_by_category gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT alert_category, COALESCE(AVG(cost_usd),0), COUNT(*), COALESCE(AVG(duration_seconds),0)
FROM session_log
WHERE alert_category != '' AND alert_category IS NOT NULL
  AND started_at > datetime('now', '-30 days')
GROUP BY alert_category;" 2>/dev/null | \
while IFS='|' read -r cat avg_cost count avg_dur; do
    [ -z "$cat" ] && continue
    echo "chatops_cost_by_category{category=\"$cat\"} $avg_cost"
    echo "chatops_cost_by_category_n{category=\"$cat\"} $count"
    echo "chatops_duration_by_category{category=\"$cat\"} $avg_dur"
done >> "$TMPOUT"

# Cost efficiency: sessions under/over budget (30d)
echo "# HELP chatops_cost_under_budget Sessions under $5 cost ceiling (30d)" >> "$TMPOUT"
echo "# TYPE chatops_cost_under_budget gauge" >> "$TMPOUT"
UNDER=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE cost_usd > 0 AND cost_usd <= 5 AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
OVER=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE cost_usd > 5 AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chatops_cost_under_budget $UNDER" >> "$TMPOUT"
echo "# HELP chatops_cost_over_budget Sessions over $5 cost ceiling (30d)" >> "$TMPOUT"
echo "# TYPE chatops_cost_over_budget gauge" >> "$TMPOUT"
echo "chatops_cost_over_budget $OVER" >> "$TMPOUT"

# Cost per site (30d)
echo "# HELP chatops_cost_by_site Total cost by site (30d)" >> "$TMPOUT"
echo "# TYPE chatops_cost_by_site gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT
  CASE WHEN issue_id LIKE 'IFRNLLEI01PRD-%' THEN 'nl'
       WHEN issue_id LIKE 'IFRGRSKG01PRD-%' THEN 'gr'
       ELSE 'dev' END AS site,
  COALESCE(SUM(cost_usd),0)
FROM session_log WHERE cost_usd > 0 AND started_at > datetime('now', '-30 days')
GROUP BY site;" 2>/dev/null | \
while IFS='|' read -r site total; do
    echo "chatops_cost_by_site{site=\"$site\"} $total"
done >> "$TMPOUT"

# Confidence calibration: predicted vs actual success rate (90d)
echo "# HELP chatops_confidence_calibration Actual thumbs-up rate per confidence band (90d)" >> "$TMPOUT"
echo "# TYPE chatops_confidence_calibration gauge" >> "$TMPOUT"
echo "# HELP chatops_confidence_calibration_n Sample size per confidence band (90d)" >> "$TMPOUT"
echo "# TYPE chatops_confidence_calibration_n gauge" >> "$TMPOUT"
sqlite3 "$DB" "
SELECT
  CASE
    WHEN sl.confidence >= 0.8 THEN 'high_0.8_1.0'
    WHEN sl.confidence >= 0.5 THEN 'medium_0.5_0.8'
    ELSE 'low_0.0_0.5'
  END AS band,
  COUNT(*) AS total,
  SUM(CASE WHEN sf.feedback_type = 'thumbs_up' THEN 1 ELSE 0 END) AS successes
FROM session_log sl
JOIN session_feedback sf ON sl.issue_id = sf.issue_id
WHERE sl.confidence >= 0 AND sl.started_at > datetime('now', '-90 days')
GROUP BY band;" 2>/dev/null | \
while IFS='|' read -r band total successes; do
    if [ -n "$total" ] && [ "$total" -gt 0 ]; then
        rate=$(python3 -c "print(f'{$successes / $total:.2f}')" 2>/dev/null || echo 0)
        echo "chatops_confidence_calibration{band=\"$band\"} $rate"
        echo "chatops_confidence_calibration_n{band=\"$band\"} $total"
    fi
done >> "$TMPOUT"

# Guardrail metrics
echo "# HELP chatops_guardrail_exec_blocked Exec commands blocked by safe-exec (all time)" >> "$TMPOUT"
echo "# TYPE chatops_guardrail_exec_blocked gauge" >> "$TMPOUT"
EXEC_BLOCKED=$(grep -c "^.*BLOCKED" /tmp/openclaw-exec.log 2>/dev/null || echo 0)
echo "chatops_guardrail_exec_blocked $EXEC_BLOCKED" >> "$TMPOUT"

echo "# HELP chatops_guardrail_exec_allowed Exec commands allowed by safe-exec (all time)" >> "$TMPOUT"
echo "# TYPE chatops_guardrail_exec_allowed gauge" >> "$TMPOUT"
EXEC_ALLOWED=$(grep -c "^.*ALLOWED" /tmp/openclaw-exec.log 2>/dev/null || echo 0)
echo "chatops_guardrail_exec_allowed $EXEC_ALLOWED" >> "$TMPOUT"

echo "# HELP chatops_guardrail_injections_detected Prompt injection patterns detected (all time)" >> "$TMPOUT"
echo "# TYPE chatops_guardrail_injections_detected gauge" >> "$TMPOUT"
# This is tracked in Bridge staticData — approximate from exec log if available
echo "chatops_guardrail_injections_detected 0" >> "$TMPOUT"

# A2A task log metrics
echo "# HELP chatops_a2a_messages_total A2A messages by type (all time)" >> "$TMPOUT"
echo "# TYPE chatops_a2a_messages_total gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT message_type, COUNT(*) FROM a2a_task_log GROUP BY message_type;" 2>/dev/null | \
while IFS='|' read -r mtype count; do
    echo "chatops_a2a_messages_total{type=\"$mtype\"} $count"
done >> "$TMPOUT"

echo "# HELP chatops_a2a_reviews_total A2A review verdicts (all time)" >> "$TMPOUT"
echo "# TYPE chatops_a2a_reviews_total gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT
  CASE WHEN payload_summary LIKE '%AGREE%' AND payload_summary NOT LIKE '%DISAGREE%' THEN 'agree'
       WHEN payload_summary LIKE '%DISAGREE%' THEN 'disagree'
       WHEN payload_summary LIKE '%AUGMENT%' THEN 'augment'
       ELSE 'unknown' END as verdict, COUNT(*)
FROM a2a_task_log WHERE message_type='review' GROUP BY verdict;" 2>/dev/null | \
while IFS='|' read -r verdict count; do
    echo "chatops_a2a_reviews_total{verdict=\"$verdict\"} $count"
done >> "$TMPOUT"

###############################################################################
# SUBSYSTEM METRICS (ChatOps / ChatSecOps / ChatDevOps taxonomy)
###############################################################################
echo "# HELP chatops_subsystem_sessions Sessions by subsystem (30d)" >> "$TMPOUT"
echo "# TYPE chatops_subsystem_sessions gauge" >> "$TMPOUT"
echo "# HELP chatops_subsystem_confidence Avg confidence by subsystem (30d)" >> "$TMPOUT"
echo "# TYPE chatops_subsystem_confidence gauge" >> "$TMPOUT"
echo "# HELP chatops_subsystem_cost Avg cost by subsystem (30d)" >> "$TMPOUT"
echo "# TYPE chatops_subsystem_cost gauge" >> "$TMPOUT"

for sub in chatops chatsecops chatdevops; do
  SUB_N=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE subsystem='$sub' AND started_at > datetime('now', '-30 days')" 2>/dev/null || echo 0)
  SUB_CONF=$(sqlite3 "$DB" "SELECT COALESCE(ROUND(AVG(confidence),3),0) FROM sessions WHERE subsystem='$sub' AND confidence > 0 AND started_at > datetime('now', '-30 days')" 2>/dev/null || echo 0)
  SUB_COST=$(sqlite3 "$DB" "SELECT COALESCE(ROUND(AVG(cost_usd),4),0) FROM sessions WHERE subsystem='$sub' AND cost_usd > 0 AND started_at > datetime('now', '-30 days')" 2>/dev/null || echo 0)
  echo "chatops_subsystem_sessions{subsystem=\"$sub\"} $SUB_N" >> "$TMPOUT"
  echo "chatops_subsystem_confidence{subsystem=\"$sub\"} $SUB_CONF" >> "$TMPOUT"
  echo "chatops_subsystem_cost{subsystem=\"$sub\"} $SUB_COST" >> "$TMPOUT"
done

mv "$TMPOUT" "$OUT"
