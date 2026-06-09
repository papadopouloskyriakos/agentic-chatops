#!/bin/bash
# write-chaos-metrics.sh — Chaos experiment Prometheus metrics
# Runs as cron every 5 minutes on nl-claude01 as app-user
DB=/app/cubeos/claude-context/gateway.db
OUT=/var/lib/node_exporter/textfile_collector/chaos_metrics.prom
TMPOUT="${OUT}.tmp"

[ -f "$DB" ] || exit 0

> "$TMPOUT"

# Total experiments
echo "# HELP chaos_experiments_total Total chaos experiments run" >> "$TMPOUT"
echo "# TYPE chaos_experiments_total gauge" >> "$TMPOUT"
TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_experiments;" 2>/dev/null || echo 0)
echo "chaos_experiments_total $TOTAL" >> "$TMPOUT"

# By verdict
echo "# HELP chaos_experiments_by_verdict Experiment count by verdict" >> "$TMPOUT"
echo "# TYPE chaos_experiments_by_verdict gauge" >> "$TMPOUT"
for v in PASS DEGRADED FAIL UNKNOWN; do
    COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_experiments WHERE verdict='$v';" 2>/dev/null || echo 0)
    echo "chaos_experiments_by_verdict{verdict=\"$v\"} $COUNT" >> "$TMPOUT"
done

# By chaos type
echo "# HELP chaos_experiments_by_type Experiment count by type" >> "$TMPOUT"
echo "# TYPE chaos_experiments_by_type gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT chaos_type, COUNT(*) FROM chaos_experiments GROUP BY chaos_type;" 2>/dev/null | while IFS='|' read -r TYPE COUNT; do
    echo "chaos_experiments_by_type{type=\"${TYPE}\"} $COUNT" >> "$TMPOUT"
done

# Average convergence by chaos type (last 30d)
echo "# HELP chaos_convergence_avg_seconds Average convergence time by type (last 30d)" >> "$TMPOUT"
echo "# TYPE chaos_convergence_avg_seconds gauge" >> "$TMPOUT"
sqlite3 "$DB" "
    SELECT chaos_type, AVG(convergence_seconds)
    FROM chaos_experiments
    WHERE convergence_seconds IS NOT NULL
      AND started_at > datetime('now', '-30 days')
    GROUP BY chaos_type;" 2>/dev/null | while IFS='|' read -r TYPE AVG; do
    echo "chaos_convergence_avg_seconds{type=\"${TYPE}\"} $AVG" >> "$TMPOUT"
done

# Pass rate (last 30d)
echo "# HELP chaos_pass_rate Pass rate of experiments (last 30d)" >> "$TMPOUT"
echo "# TYPE chaos_pass_rate gauge" >> "$TMPOUT"
RATE=$(sqlite3 "$DB" "
    SELECT CAST(SUM(CASE WHEN verdict='PASS' THEN 1 ELSE 0 END) AS FLOAT) / MAX(COUNT(*), 1)
    FROM chaos_experiments
    WHERE started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chaos_pass_rate $RATE" >> "$TMPOUT"

# Latest experiment details
echo "# HELP chaos_last_experiment_timestamp Unix timestamp of last experiment" >> "$TMPOUT"
echo "# TYPE chaos_last_experiment_timestamp gauge" >> "$TMPOUT"
LAST_TS=$(sqlite3 "$DB" "
    SELECT strftime('%s', started_at)
    FROM chaos_experiments
    ORDER BY id DESC LIMIT 1;" 2>/dev/null || echo 0)
echo "chaos_last_experiment_timestamp ${LAST_TS:-0}" >> "$TMPOUT"

echo "# HELP chaos_last_convergence_seconds Convergence time of most recent experiment" >> "$TMPOUT"
echo "# TYPE chaos_last_convergence_seconds gauge" >> "$TMPOUT"
LAST_CONV=$(sqlite3 "$DB" "
    SELECT COALESCE(convergence_seconds, 0)
    FROM chaos_experiments
    ORDER BY id DESC LIMIT 1;" 2>/dev/null || echo 0)
echo "chaos_last_convergence_seconds ${LAST_CONV:-0}" >> "$TMPOUT"

# Per-tunnel convergence (latest per target)
echo "# HELP chaos_tunnel_convergence_seconds Latest convergence per tunnel target" >> "$TMPOUT"
echo "# TYPE chaos_tunnel_convergence_seconds gauge" >> "$TMPOUT"
sqlite3 "$DB" "
    SELECT json_extract(targets, '$.tunnels_killed[0].tunnel') as tunnel,
           json_extract(targets, '$.tunnels_killed[0].wan') as wan,
           convergence_seconds
    FROM chaos_experiments
    WHERE chaos_type='tunnel' AND convergence_seconds IS NOT NULL
    ORDER BY id DESC
    LIMIT 10;" 2>/dev/null | while IFS='|' read -r TUNNEL WAN CONV; do
    [ -z "$TUNNEL" ] && continue
    echo "chaos_tunnel_convergence_seconds{tunnel=\"${TUNNEL}\",wan=\"${WAN}\"} $CONV" >> "$TMPOUT"
done

# Error budget consumed (sum of last 30d)
echo "# HELP chaos_error_budget_consumed_pct Total error budget consumed (last 30d)" >> "$TMPOUT"
echo "# TYPE chaos_error_budget_consumed_pct gauge" >> "$TMPOUT"
BUDGET=$(sqlite3 "$DB" "
    SELECT COALESCE(SUM(error_budget_consumed_pct), 0)
    FROM chaos_experiments
    WHERE started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
echo "chaos_error_budget_consumed_pct $BUDGET" >> "$TMPOUT"

# Chaos findings (ISO 8.6 improvement tracker)
echo "# HELP chaos_findings_open Open findings by severity" >> "$TMPOUT"
echo "# TYPE chaos_findings_open gauge" >> "$TMPOUT"
for sev in critical high medium low; do
    COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_findings WHERE severity='$sev' AND status='open';" 2>/dev/null || echo 0)
    echo "chaos_findings_open{severity=\"$sev\"} $COUNT" >> "$TMPOUT"
done

echo "# HELP chaos_findings_total Total findings by status" >> "$TMPOUT"
echo "# TYPE chaos_findings_total gauge" >> "$TMPOUT"
for stat in open in-progress verified closed; do
    COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_findings WHERE status='$stat';" 2>/dev/null || echo 0)
    echo "chaos_findings_total{status=\"$stat\"} $COUNT" >> "$TMPOUT"
done

echo "# HELP chaos_retrospectives_total Total retrospectives generated" >> "$TMPOUT"
echo "# TYPE chaos_retrospectives_total gauge" >> "$TMPOUT"
RETRO=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_retrospectives;" 2>/dev/null || echo 0)
echo "chaos_retrospectives_total $RETRO" >> "$TMPOUT"

# Composite resilience score (LitmusChaos LC-4)
echo "# HELP chaos_resilience_score Weighted resilience score 0-100" >> "$TMPOUT"
echo "# TYPE chaos_resilience_score gauge" >> "$TMPOUT"
SCORE=$(sqlite3 "$DB" "
    SELECT CAST(
        COALESCE(
            (SELECT COUNT(*) * 100.0 / NULLIF(COUNT(*), 0) FROM chaos_experiments
             WHERE chaos_type='tunnel' AND verdict='PASS' AND started_at > datetime('now', '-90 days')), 0
        ) * 0.4 +
        COALESCE(
            (SELECT COUNT(*) * 100.0 / NULLIF(COUNT(*), 0) FROM chaos_experiments
             WHERE chaos_type='dmz' AND verdict='PASS' AND started_at > datetime('now', '-90 days')), 0
        ) * 0.3 +
        COALESCE(
            (SELECT COUNT(*) * 100.0 / NULLIF(COUNT(*), 0) FROM chaos_experiments
             WHERE chaos_type='container' AND verdict='PASS' AND started_at > datetime('now', '-90 days')), 0
        ) * 0.2 +
        COALESCE(
            (SELECT COUNT(*) * 100.0 / NULLIF(COUNT(*), 0) FROM chaos_experiments
             WHERE chaos_type='combined' AND verdict='PASS' AND started_at > datetime('now', '-90 days')), 0
        ) * 0.1
    AS INTEGER);" 2>/dev/null || echo 0)
echo "chaos_resilience_score $SCORE" >> "$TMPOUT"

# Exercise metrics (CMM Level 3)
echo "# HELP chaos_exercises_total Total scheduled exercises run" >> "$TMPOUT"
echo "# TYPE chaos_exercises_total gauge" >> "$TMPOUT"
EX_TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_exercises;" 2>/dev/null || echo 0)
echo "chaos_exercises_total $EX_TOTAL" >> "$TMPOUT"

echo "# HELP chaos_exercises_by_type Exercise count by type" >> "$TMPOUT"
echo "# TYPE chaos_exercises_by_type gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT exercise_type, COUNT(*) FROM chaos_exercises GROUP BY exercise_type;" 2>/dev/null | while IFS='|' read -r TYPE COUNT; do
    echo "chaos_exercises_by_type{type=\"${TYPE}\"} $COUNT" >> "$TMPOUT"
done

echo "# HELP chaos_exercise_pass_rate Exercise pass rate (last 90d)" >> "$TMPOUT"
echo "# TYPE chaos_exercise_pass_rate gauge" >> "$TMPOUT"
EX_RATE=$(sqlite3 "$DB" "
    SELECT CAST(SUM(CASE WHEN fail_count=0 AND degraded_count=0 THEN 1 ELSE 0 END) AS FLOAT) / MAX(COUNT(*), 1)
    FROM chaos_exercises
    WHERE started_at > datetime('now', '-90 days');" 2>/dev/null || echo 0)
echo "chaos_exercise_pass_rate $EX_RATE" >> "$TMPOUT"

echo "# HELP chaos_last_exercise_age_seconds Seconds since last scheduled exercise" >> "$TMPOUT"
echo "# TYPE chaos_last_exercise_age_seconds gauge" >> "$TMPOUT"
EX_AGE=$(sqlite3 "$DB" "
    SELECT CAST((julianday('now') - julianday(started_at)) * 86400 AS INTEGER)
    FROM chaos_exercises ORDER BY id DESC LIMIT 1;" 2>/dev/null || echo 0)
echo "chaos_last_exercise_age_seconds ${EX_AGE:-0}" >> "$TMPOUT"

# Per-scenario repetition counts (NIST statistical validity, IFRNLLEI01PRD-577)
echo "# HELP chaos_experiment_count_per_scenario Repetitions per chaos scenario (all time)" >> "$TMPOUT"
echo "# TYPE chaos_experiment_count_per_scenario gauge" >> "$TMPOUT"
sqlite3 "$DB" "
    SELECT chaos_type, targets, COUNT(*) as reps
    FROM chaos_experiments
    GROUP BY chaos_type, targets;" 2>/dev/null | while IFS='|' read -r CTYPE TARGETS REPS; do
    LABEL=$(echo "$TARGETS" | sed 's/[^a-zA-Z0-9_-]/_/g' | head -c 60)
    echo "chaos_experiment_count_per_scenario{type=\"${CTYPE}\",target=\"${LABEL}\"} $REPS" >> "$TMPOUT"
done

echo "# HELP chaos_min_reps_per_scenario Minimum repetitions across all scenarios" >> "$TMPOUT"
echo "# TYPE chaos_min_reps_per_scenario gauge" >> "$TMPOUT"
MIN_REPS=$(sqlite3 "$DB" "
    SELECT MIN(cnt) FROM (
        SELECT COUNT(*) as cnt FROM chaos_experiments GROUP BY chaos_type, targets
    );" 2>/dev/null || echo 0)
echo "chaos_min_reps_per_scenario ${MIN_REPS:-0}" >> "$TMPOUT"

# Atomic rename
mv "$TMPOUT" "$OUT"
