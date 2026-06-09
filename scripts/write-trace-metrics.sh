#!/bin/bash
# Write trace/OTel metrics to Prometheus textfile collector
# Cron: */5 * * * *
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
PROM="/var/lib/node_exporter/textfile_collector/trace_metrics.prom"

# Traced sessions (active + archived)
TRACED_ACTIVE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE trace_id != ''" 2>/dev/null || echo 0)
TRACED_LOG=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE trace_id != ''" 2>/dev/null || echo 0)
TOTAL_TRACED=$((TRACED_ACTIVE + TRACED_LOG))

# Span stats from tool_call_log (7-day window)
SPAN_7D=$(sqlite3 "$DB" "SELECT COUNT(*) FROM tool_call_log WHERE created_at > datetime('now', '-7 days')" 2>/dev/null || echo 0)
SPAN_ERRORS_7D=$(sqlite3 "$DB" "SELECT COUNT(*) FROM tool_call_log WHERE error_type != '' AND created_at > datetime('now', '-7 days')" 2>/dev/null || echo 0)

# Average session duration (traced only)
AVG_DUR=$(sqlite3 "$DB" "SELECT COALESCE(ROUND(AVG(duration_seconds),0),0) FROM session_log WHERE trace_id != '' AND duration_seconds > 0" 2>/dev/null || echo 0)

# Tool call latency percentiles (7d)
P50_MS=$(sqlite3 "$DB" "SELECT COALESCE(duration_ms,0) FROM tool_call_log WHERE duration_ms > 0 AND created_at > datetime('now','-7 days') ORDER BY duration_ms LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM tool_call_log WHERE duration_ms > 0 AND created_at > datetime('now','-7 days'))" 2>/dev/null || echo 0)
P95_MS=$(sqlite3 "$DB" "SELECT COALESCE(duration_ms,0) FROM tool_call_log WHERE duration_ms > 0 AND created_at > datetime('now','-7 days') ORDER BY duration_ms LIMIT 1 OFFSET (SELECT COUNT(*)*95/100 FROM tool_call_log WHERE duration_ms > 0 AND created_at > datetime('now','-7 days'))" 2>/dev/null || echo 0)

# Execution log (infra commands)
EXEC_7D=$(sqlite3 "$DB" "SELECT COUNT(*) FROM execution_log WHERE created_at > datetime('now', '-7 days')" 2>/dev/null || echo 0)
EXEC_DEVICES=$(sqlite3 "$DB" "SELECT COUNT(DISTINCT device) FROM execution_log WHERE created_at > datetime('now', '-7 days')" 2>/dev/null || echo 0)

cat > "$PROM" << METRICS
# HELP trace_sessions_total Total sessions with trace IDs (active + archived)
# TYPE trace_sessions_total gauge
trace_sessions_total $TOTAL_TRACED
# HELP trace_spans_7d Tool call spans in last 7 days
# TYPE trace_spans_7d gauge
trace_spans_7d $SPAN_7D
# HELP trace_span_errors_7d Spans with errors in last 7 days
# TYPE trace_span_errors_7d gauge
trace_span_errors_7d $SPAN_ERRORS_7D
# HELP trace_avg_session_duration_seconds Average traced session duration
# TYPE trace_avg_session_duration_seconds gauge
trace_avg_session_duration_seconds $AVG_DUR
# HELP trace_tool_latency_p50_ms Tool call latency p50 (7d)
# TYPE trace_tool_latency_p50_ms gauge
trace_tool_latency_p50_ms $P50_MS
# HELP trace_tool_latency_p95_ms Tool call latency p95 (7d)
# TYPE trace_tool_latency_p95_ms gauge
trace_tool_latency_p95_ms $P95_MS
# HELP trace_execution_commands_7d Infrastructure commands executed (7d)
# TYPE trace_execution_commands_7d gauge
trace_execution_commands_7d $EXEC_7D
# HELP trace_execution_devices_7d Unique devices targeted (7d)
# TYPE trace_execution_devices_7d gauge
trace_execution_devices_7d $EXEC_DEVICES
# HELP trace_export_timestamp Last trace metrics export time
# TYPE trace_export_timestamp gauge
trace_export_timestamp $(date +%s)
METRICS
