#!/bin/bash
# write-agent-metrics.sh — Per-tier agent performance Prometheus metrics
# Runs as cron every 5 minutes on nl-claude01 as claude-runner
DB=/home/claude-runner/gitlab/products/cubeos/claude-context/gateway.db
TRIAGE_LOG=/home/claude-runner/gitlab/products/cubeos/claude-context/triage.log
OUT=/var/lib/node_exporter/textfile_collector/agent_metrics.prom
TMPOUT="${OUT}.tmp"

> "$TMPOUT"

# ============================================================================
# Tier 1 (OpenClaw) metrics — from triage.log
# Format: timestamp|hostname|rule_name|site|outcome|confidence|duration|issue_id
# ============================================================================
if [ -f "$TRIAGE_LOG" ]; then
    CUTOFF_30D=$(date -d '30 days ago' -u +%FT%TZ 2>/dev/null || echo "1970-01-01T00:00:00Z")

    echo "# HELP agent_openclaw_triage_total Tier 1 triage outcomes (last 30d)" >> "$TMPOUT"
    echo "# TYPE agent_openclaw_triage_total gauge" >> "$TMPOUT"
    for site in nl gr; do
        for outcome in escalated resolved; do
            COUNT=$(awk -F'|' -v s="$site" -v o="$outcome" -v c="$CUTOFF_30D" \
                '$1 >= c && $4 == s && $5 == o {n++} END {print n+0}' "$TRIAGE_LOG")
            echo "agent_openclaw_triage_total{site=\"$site\",outcome=\"$outcome\"} $COUNT" >> "$TMPOUT"
        done
    done

    echo "# HELP agent_openclaw_avg_confidence Tier 1 average confidence (last 30d)" >> "$TMPOUT"
    echo "# TYPE agent_openclaw_avg_confidence gauge" >> "$TMPOUT"
    for site in nl gr; do
        AVG=$(awk -F'|' -v s="$site" -v c="$CUTOFF_30D" \
            '$1 >= c && $4 == s && $6+0 > 0 {sum+=$6; n++} END {if(n>0) printf "%.2f", sum/n; else print 0}' "$TRIAGE_LOG")
        echo "agent_openclaw_avg_confidence{site=\"$site\"} $AVG" >> "$TMPOUT"
    done

    # Trim log older than 90 days
    CUTOFF_90D=$(date -d '90 days ago' -u +%FT%TZ 2>/dev/null || echo "1970-01-01T00:00:00Z")
    TMP_LOG="${TRIAGE_LOG}.tmp"
    awk -F'|' -v c="$CUTOFF_90D" '$1 >= c' "$TRIAGE_LOG" > "$TMP_LOG" 2>/dev/null && mv "$TMP_LOG" "$TRIAGE_LOG"
fi

# ============================================================================
# Tier 2 (Claude Code) metrics — from session_log
# ============================================================================
if [ -f "$DB" ]; then
    echo "# HELP agent_claude_sessions_total Tier 2 sessions by outcome and project (last 30d)" >> "$TMPOUT"
    echo "# TYPE agent_claude_sessions_total gauge" >> "$TMPOUT"
    sqlite3 "$DB" "
    SELECT
      CASE
        WHEN issue_id LIKE 'IFRNLLEI01PRD-%' THEN 'infra-nl'
        WHEN issue_id LIKE 'IFRGRSKG01PRD-%' THEN 'infra-gr'
        ELSE 'dev'
      END AS project,
      COALESCE(outcome,'unknown'),
      COUNT(*)
    FROM session_log
    WHERE started_at > datetime('now', '-30 days')
    GROUP BY project, outcome;" 2>/dev/null | \
    while IFS='|' read -r project outcome count; do
        echo "agent_claude_sessions_total{project=\"$project\",outcome=\"$outcome\"} $count"
    done >> "$TMPOUT"

    echo "# HELP agent_claude_avg_cost_usd Tier 2 average cost per session (last 30d)" >> "$TMPOUT"
    echo "# TYPE agent_claude_avg_cost_usd gauge" >> "$TMPOUT"
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
        echo "agent_claude_avg_cost_usd{project=\"$project\"} $avg_cost"
    done >> "$TMPOUT"

    echo "# HELP agent_claude_avg_duration_seconds Tier 2 average session duration (last 30d)" >> "$TMPOUT"
    echo "# TYPE agent_claude_avg_duration_seconds gauge" >> "$TMPOUT"
    AVG_DUR=$(sqlite3 "$DB" "SELECT COALESCE(AVG(duration_seconds),0) FROM session_log WHERE duration_seconds > 0 AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
    echo "agent_claude_avg_duration_seconds $AVG_DUR" >> "$TMPOUT"

    echo "# HELP agent_claude_validation_retry_rate Fraction of sessions needing validation retry (last 30d)" >> "$TMPOUT"
    echo "# TYPE agent_claude_validation_retry_rate gauge" >> "$TMPOUT"
    # Approximate: sessions with confidence=-1 (missing) / total
    TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
    MISSING_CONF=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE confidence < 0 AND started_at > datetime('now', '-30 days');" 2>/dev/null || echo 0)
    if [ "$TOTAL" -gt 0 ]; then
        RATE=$(awk "BEGIN {printf \"%.2f\", $MISSING_CONF / $TOTAL}")
    else
        RATE=0
    fi
    echo "agent_claude_validation_retry_rate $RATE" >> "$TMPOUT"
fi

mv "$TMPOUT" "$OUT"
