#!/usr/bin/env bash
# write-turn-metrics.sh — Prometheus exporter for session_turns (IFRNLLEI01PRD-638).
# Cron: */5.
#
# Metrics:
#   session_turn_cost_usd_p50       p50 llm_cost_usd across completed turns (24h window)
#   session_turn_cost_usd_p95       p95 cost
#   session_turn_duration_p50       p50 duration_ms across completed turns (24h)
#   session_turn_duration_p95       p95 duration
#   session_turn_tool_count_avg     mean tools per turn (24h)
#   session_turns_total             all-time turn count
set -uo pipefail
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
OUT_DIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/prometheus/node-exporter}"
OUT_FILE="${OUT_DIR}/session_turns.prom"
TMP_FILE="${OUT_FILE}.tmp"

[ -f "$DB" ] || exit 1

if ! sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_turns'" | grep -q 1; then
  echo "# session_turns not yet created" > "$TMP_FILE"
  mv "$TMP_FILE" "$OUT_FILE" 2>/dev/null || true
  exit 0
fi

{
  TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_turns")
  echo "# HELP session_turns_total All-time count of session turns recorded."
  echo "# TYPE session_turns_total counter"
  echo "session_turns_total ${TOTAL}"

  COST_P50=$(sqlite3 "$DB" "
    WITH w AS (SELECT llm_cost_usd, ROW_NUMBER() OVER (ORDER BY llm_cost_usd) AS rn, COUNT(*) OVER () AS n
               FROM session_turns WHERE ended_at IS NOT NULL AND ended_at >= datetime('now','-1 day'))
    SELECT COALESCE(llm_cost_usd,0) FROM w WHERE rn = CAST(n*0.50+0.5 AS INTEGER) LIMIT 1
  ")
  COST_P95=$(sqlite3 "$DB" "
    WITH w AS (SELECT llm_cost_usd, ROW_NUMBER() OVER (ORDER BY llm_cost_usd) AS rn, COUNT(*) OVER () AS n
               FROM session_turns WHERE ended_at IS NOT NULL AND ended_at >= datetime('now','-1 day'))
    SELECT COALESCE(llm_cost_usd,0) FROM w WHERE rn = CAST(n*0.95+0.5 AS INTEGER) LIMIT 1
  ")
  echo "# HELP session_turn_cost_usd_p50 p50 llm_cost_usd per turn (24h window)."
  echo "# TYPE session_turn_cost_usd_p50 gauge"
  echo "session_turn_cost_usd_p50 ${COST_P50:-0}"
  echo "# HELP session_turn_cost_usd_p95 p95 llm_cost_usd per turn (24h window)."
  echo "# TYPE session_turn_cost_usd_p95 gauge"
  echo "session_turn_cost_usd_p95 ${COST_P95:-0}"

  DUR_P50=$(sqlite3 "$DB" "
    WITH w AS (SELECT duration_ms, ROW_NUMBER() OVER (ORDER BY duration_ms) AS rn, COUNT(*) OVER () AS n
               FROM session_turns WHERE ended_at IS NOT NULL AND duration_ms >= 0 AND ended_at >= datetime('now','-1 day'))
    SELECT COALESCE(duration_ms,0) FROM w WHERE rn = CAST(n*0.50+0.5 AS INTEGER) LIMIT 1
  ")
  DUR_P95=$(sqlite3 "$DB" "
    WITH w AS (SELECT duration_ms, ROW_NUMBER() OVER (ORDER BY duration_ms) AS rn, COUNT(*) OVER () AS n
               FROM session_turns WHERE ended_at IS NOT NULL AND duration_ms >= 0 AND ended_at >= datetime('now','-1 day'))
    SELECT COALESCE(duration_ms,0) FROM w WHERE rn = CAST(n*0.95+0.5 AS INTEGER) LIMIT 1
  ")
  echo "# HELP session_turn_duration_p50 p50 duration_ms per turn (24h)."
  echo "# TYPE session_turn_duration_p50 gauge"
  echo "session_turn_duration_p50 ${DUR_P50:-0}"
  echo "# HELP session_turn_duration_p95 p95 duration_ms per turn (24h)."
  echo "# TYPE session_turn_duration_p95 gauge"
  echo "session_turn_duration_p95 ${DUR_P95:-0}"

  TOOL_AVG=$(sqlite3 "$DB" "SELECT COALESCE(ROUND(AVG(tool_count),2),0) FROM session_turns WHERE ended_at >= datetime('now','-1 day')")
  echo "# HELP session_turn_tool_count_avg Mean tool calls per turn (24h)."
  echo "# TYPE session_turn_tool_count_avg gauge"
  echo "session_turn_tool_count_avg ${TOOL_AVG}"
} > "$TMP_FILE"

mv "$TMP_FILE" "$OUT_FILE"
