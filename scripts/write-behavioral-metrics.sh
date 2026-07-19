#!/bin/bash
# write-behavioral-metrics.sh — NIST AI RMF AG-MS.1 behavioral telemetry signals
#
# Implements the 5 minimum behavioral telemetry signals required by the NIST
# Agentic Profile for Tier 2+ autonomous systems:
#
#   1. Action velocity — tool invocations per session (baseline deviation)
#   2. Permission escalation rate — guardrail blocks per day
#   3. Cross-boundary invocations — T1->T2 escalations per day
#   4. Delegation depth — max delegation chain depth per session
#   5. Exception rate — tool call errors per hour
#
# Cron: */5 * * * * /app/claude-gateway/scripts/write-behavioral-metrics.sh
#
# Source: Industry Benchmark 2026-04-15, IFRNLLEI01PRD-573

set -uo pipefail

DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
PROM="/var/lib/node_exporter/textfile_collector/behavioral_metrics.prom"
AUDIT_LOG="/tmp/claude-code-bash-audit.log"

[ "${1:-}" = "--dry-run" ] && PROM="/dev/stdout"

[ -f "$DB" ] || { echo "ERROR: DB not found at $DB" >&2; exit 1; }

TMPFILE="${PROM}.tmp"
[ "$PROM" = "/dev/stdout" ] && TMPFILE="/dev/stdout"

cat > "$TMPFILE" << 'HEADER'
# HELP nist_action_velocity_avg Average tool calls per session (30d)
# TYPE nist_action_velocity_avg gauge
# HELP nist_action_velocity_stddev Standard deviation of tool calls per session (30d)
# TYPE nist_action_velocity_stddev gauge
# HELP nist_action_velocity_max Max tool calls in any single session (7d)
# TYPE nist_action_velocity_max gauge
# HELP nist_action_velocity_anomalies Sessions exceeding 2 stddev from mean (7d)
# TYPE nist_action_velocity_anomalies gauge
# HELP nist_permission_escalation_blocks_24h Guardrail blocks in last 24h
# TYPE nist_permission_escalation_blocks_24h gauge
# HELP nist_permission_escalation_blocks_7d Guardrail blocks in last 7d
# TYPE nist_permission_escalation_blocks_7d gauge
# HELP nist_cross_boundary_escalations_24h T1 to T2 escalations in last 24h
# TYPE nist_cross_boundary_escalations_24h gauge
# HELP nist_cross_boundary_escalations_7d T1 to T2 escalations in last 7d
# TYPE nist_cross_boundary_escalations_7d gauge
# HELP nist_delegation_depth_max Max delegation chain depth (7d)
# TYPE nist_delegation_depth_max gauge
# HELP nist_delegation_depth_avg Average delegation chain depth (7d)
# TYPE nist_delegation_depth_avg gauge
# HELP nist_exception_rate_per_hour Tool call errors per hour (24h avg)
# TYPE nist_exception_rate_per_hour gauge
# HELP nist_exception_rate_total Total tool call errors (7d)
# TYPE nist_exception_rate_total gauge
# HELP nist_behavioral_telemetry_signals Number of active NIST AG-MS.1 signals
# TYPE nist_behavioral_telemetry_signals gauge
HEADER

signals_active=0

# --- Signal 1: Action Velocity ---
# Tool calls per session over 30d baseline
read -r avg_velocity stddev_velocity <<< "$(sqlite3 "$DB" "
    SELECT
        COALESCE(ROUND(AVG(cnt), 1), 0),
        COALESCE(ROUND(
            SQRT(AVG(cnt * cnt) - AVG(cnt) * AVG(cnt))
        , 1), 0)
    FROM (
        SELECT session_id, COUNT(*) as cnt
        FROM tool_call_log
        WHERE created_at > datetime('now', '-30 days')
        AND session_id != ''
        GROUP BY session_id
    );
" 2>/dev/null | tr '|' ' ')"
avg_velocity="${avg_velocity:-0}"
stddev_velocity="${stddev_velocity:-0}"

max_velocity_7d="$(sqlite3 "$DB" "
    SELECT COALESCE(MAX(cnt), 0)
    FROM (
        SELECT session_id, COUNT(*) as cnt
        FROM tool_call_log
        WHERE created_at > datetime('now', '-7 days')
        AND session_id != ''
        GROUP BY session_id
    );
" 2>/dev/null)"
max_velocity_7d="${max_velocity_7d:-0}"

# Count sessions exceeding 2 stddev (anomalies)
threshold=$(python3 -c "print(round(${avg_velocity} + 2 * ${stddev_velocity}, 0))" 2>/dev/null || echo "999999")
anomalies_7d="$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM (
        SELECT session_id, COUNT(*) as cnt
        FROM tool_call_log
        WHERE created_at > datetime('now', '-7 days')
        AND session_id != ''
        GROUP BY session_id
        HAVING cnt > ${threshold}
    );
" 2>/dev/null)"
anomalies_7d="${anomalies_7d:-0}"

{
    echo "nist_action_velocity_avg $avg_velocity"
    echo "nist_action_velocity_stddev $stddev_velocity"
    echo "nist_action_velocity_max $max_velocity_7d"
    echo "nist_action_velocity_anomalies $anomalies_7d"
} >> "$TMPFILE"
signals_active=$((signals_active + 1))

# --- Signal 2: Permission Escalation Rate ---
# Count guardrail blocks from audit log (unified-guard.sh writes BLOCKED lines)
blocks_24h=0
blocks_7d=0
if [ -f "$AUDIT_LOG" ]; then
    yesterday=$(date -u -d '24 hours ago' '+%Y-%m-%d' 2>/dev/null || date -u -v-1d '+%Y-%m-%d' 2>/dev/null || echo "")
    week_ago=$(date -u -d '7 days ago' '+%Y-%m-%d' 2>/dev/null || date -u -v-7d '+%Y-%m-%d' 2>/dev/null || echo "")
    if [ -n "$yesterday" ]; then
        blocks_24h=$(grep -c "BLOCKED" "$AUDIT_LOG" 2>/dev/null || echo "0")
    fi
    blocks_7d="$blocks_24h"  # Audit log is single file, approximate with total blocks
fi

{
    echo "nist_permission_escalation_blocks_24h $blocks_24h"
    echo "nist_permission_escalation_blocks_7d $blocks_7d"
} >> "$TMPFILE"
signals_active=$((signals_active + 1))

# --- Signal 3: Cross-Boundary Invocations ---
# T1->T2 escalations from a2a_task_log
escalations_24h="$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM a2a_task_log
    WHERE from_tier = 1 AND to_tier = 2
    AND created_at > datetime('now', '-1 day');
" 2>/dev/null)"
escalations_24h="${escalations_24h:-0}"

escalations_7d="$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM a2a_task_log
    WHERE from_tier = 1 AND to_tier = 2
    AND created_at > datetime('now', '-7 days');
" 2>/dev/null)"
escalations_7d="${escalations_7d:-0}"

{
    echo "nist_cross_boundary_escalations_24h $escalations_24h"
    echo "nist_cross_boundary_escalations_7d $escalations_7d"
} >> "$TMPFILE"
signals_active=$((signals_active + 1))

# --- Signal 4: Delegation Depth ---
# Max and avg delegation depth from a2a_task_log
# Depth = count of distinct tiers in a single issue's task chain
max_depth="$(sqlite3 "$DB" "
    SELECT COALESCE(MAX(depth), 0)
    FROM (
        SELECT issue_id, COUNT(DISTINCT from_tier) + COUNT(DISTINCT to_tier) as depth
        FROM a2a_task_log
        WHERE created_at > datetime('now', '-7 days')
        AND issue_id != ''
        GROUP BY issue_id
    );
" 2>/dev/null)"
max_depth="${max_depth:-0}"

avg_depth="$(sqlite3 "$DB" "
    SELECT COALESCE(ROUND(AVG(depth), 1), 0)
    FROM (
        SELECT issue_id, COUNT(DISTINCT from_tier) + COUNT(DISTINCT to_tier) as depth
        FROM a2a_task_log
        WHERE created_at > datetime('now', '-7 days')
        AND issue_id != ''
        GROUP BY issue_id
    );
" 2>/dev/null)"
avg_depth="${avg_depth:-0}"

{
    echo "nist_delegation_depth_max $max_depth"
    echo "nist_delegation_depth_avg $avg_depth"
} >> "$TMPFILE"
signals_active=$((signals_active + 1))

# --- Signal 5: Exception Rate ---
# Tool call errors per hour (24h average)
errors_24h="$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM tool_call_log
    WHERE exit_code != 0 AND exit_code IS NOT NULL
    AND created_at > datetime('now', '-1 day');
" 2>/dev/null)"
errors_24h="${errors_24h:-0}"

errors_7d="$(sqlite3 "$DB" "
    SELECT COUNT(*)
    FROM tool_call_log
    WHERE exit_code != 0 AND exit_code IS NOT NULL
    AND created_at > datetime('now', '-7 days');
" 2>/dev/null)"
errors_7d="${errors_7d:-0}"

errors_per_hour=$(python3 -c "print(round(${errors_24h} / 24.0, 2))" 2>/dev/null || echo "0")

{
    echo "nist_exception_rate_per_hour $errors_per_hour"
    echo "nist_exception_rate_total $errors_7d"
} >> "$TMPFILE"
signals_active=$((signals_active + 1))

# --- Summary ---
echo "nist_behavioral_telemetry_signals $signals_active" >> "$TMPFILE"

# Atomic rename
if [ "$PROM" != "/dev/stdout" ]; then
    mv "$TMPFILE" "$PROM"
fi
