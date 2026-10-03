#!/bin/bash
# write-tool-metrics.sh — Write tool call metrics to Prometheus textfile collector
#
# Reads tool_call_log and execution_log from gateway.db, emits per-tool
# call counts, error rates, and average durations as Prometheus gauges.
#
# Usage:
#   write-tool-metrics.sh            # Write metrics to textfile collector
#   write-tool-metrics.sh --dry-run  # Print to stdout only

set -uo pipefail

DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
PROM="/var/lib/node_exporter/textfile_collector/tool_metrics.prom"

[ "${1:-}" = "--dry-run" ] && PROM="/dev/stdout"

[ -f "$DB" ] || { echo "ERROR: DB not found at $DB" >&2; exit 1; }

TMPFILE="${PROM}.tmp"
[ "$PROM" = "/dev/stdout" ] && TMPFILE="/dev/stdout"

cat > "$TMPFILE" << 'HEADER'
# HELP tool_calls_total Total tool calls by tool name (last 7d)
# TYPE tool_calls_total gauge
# HELP tool_error_rate Error rate per tool 0-1 (last 7d)
# TYPE tool_error_rate gauge
# HELP tool_avg_duration_ms Average duration per tool call (last 7d)
# TYPE tool_avg_duration_ms gauge
HEADER

sqlite3 -separator '|' "$DB" "
  SELECT tool_name,
         COUNT(*) as total,
         SUM(CASE WHEN error_type != '' AND error_type IS NOT NULL THEN 1 ELSE 0 END) as errors,
         ROUND(AVG(duration_ms), 0) as avg_ms
  FROM tool_call_log
  WHERE created_at > datetime('now', '-7 days')
  GROUP BY tool_name
  HAVING total >= 5
  ORDER BY total DESC
  LIMIT 30
" 2>/dev/null | while IFS='|' read -r tool total errors avg_ms; do
  safe_tool=$(echo "$tool" | tr '/' '_' | tr ' ' '_' | tr -d '"')
  echo "tool_calls_total{tool=\"$safe_tool\"} $total" >> "$TMPFILE"
  if [ "$total" -gt 0 ]; then
    rate=$(echo "scale=4; ${errors:-0} / $total" | bc 2>/dev/null || echo 0)
    echo "tool_error_rate{tool=\"$safe_tool\"} $rate" >> "$TMPFILE"
  fi
  echo "tool_avg_duration_ms{tool=\"$safe_tool\"} ${avg_ms:-0}" >> "$TMPFILE"
done

# Execution log metrics
cat >> "$TMPFILE" << 'HEADER2'
# HELP execution_commands_7d Total execution commands (last 7d)
# TYPE execution_commands_7d gauge
# HELP execution_failures_7d Failed executions (last 7d)
# TYPE execution_failures_7d gauge
# HELP execution_devices_7d Unique devices with executions (last 7d)
# TYPE execution_devices_7d gauge
HEADER2

sqlite3 -separator '|' "$DB" "
  SELECT COUNT(*) as total,
         SUM(CASE WHEN exit_code != 0 THEN 1 ELSE 0 END) as failed,
         COUNT(DISTINCT device) as devices
  FROM execution_log
  WHERE created_at > datetime('now', '-7 days')
" 2>/dev/null | IFS='|' read -r exec_total exec_failed exec_devices

echo "execution_commands_7d ${exec_total:-0}" >> "$TMPFILE"
echo "execution_failures_7d ${exec_failed:-0}" >> "$TMPFILE"
echo "execution_devices_7d ${exec_devices:-0}" >> "$TMPFILE"

# Tool call summary stats
cat >> "$TMPFILE" << 'HEADER3'
# HELP tool_calls_distinct_7d Distinct tool names called (last 7d)
# TYPE tool_calls_distinct_7d gauge
# HELP tool_calls_total_7d Total tool calls across all tools (last 7d)
# TYPE tool_calls_total_7d gauge
HEADER3

DISTINCT_TOOLS=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT tool_name) FROM tool_call_log WHERE created_at > datetime('now', '-7 days')" 2>/dev/null || echo 0)
TOTAL_CALLS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM tool_call_log WHERE created_at > datetime('now', '-7 days')" 2>/dev/null || echo 0)
echo "tool_calls_distinct_7d $DISTINCT_TOOLS" >> "$TMPFILE"
echo "tool_calls_total_7d $TOTAL_CALLS" >> "$TMPFILE"

# Atomically move temp to final (skip if dry-run)
if [ "$PROM" != "/dev/stdout" ]; then
  mv "$TMPFILE" "$PROM"
fi
