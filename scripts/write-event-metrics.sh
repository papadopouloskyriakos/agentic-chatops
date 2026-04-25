#!/usr/bin/env bash
# write-event-metrics.sh — Prometheus exporter for event_log (IFRNLLEI01PRD-637).
#
# Writes per-event_type rate and latency histograms to the textfile
# collector spool so node_exporter picks them up.
#
# Cron: */5 * * * * ~/gitlab/n8n/claude-gateway/scripts/write-event-metrics.sh
#
# Metrics emitted (textfile spool lines):
#   event_log_rate_per_type{event_type=""}   -- events/min over last 5min
#   event_log_duration_ms_p50{event_type=""} -- p50 duration_ms for typed events
#   event_log_duration_ms_p95{event_type=""}
#   event_log_total_rows{event_type=""}      -- all-time counter
#
# Writes atomically: builds file in .tmp then mv into place so node_exporter
# never reads a half-written prom file.
set -uo pipefail
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
OUT_DIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/prometheus/node-exporter}"
OUT_FILE="${OUT_DIR}/event_log.prom"
TMP_FILE="${OUT_FILE}.tmp"

[ -f "$DB" ] || { echo "DB not found: $DB" >&2; exit 1; }

# Short-circuit if table doesn't exist yet (pre-migration host).
if ! sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_log'" | grep -q 1; then
  echo "# event_log table not yet created; skipping" > "$TMP_FILE"
  mv "$TMP_FILE" "$OUT_FILE" 2>/dev/null || true
  exit 0
fi

{
  echo "# HELP event_log_rate_per_type Events per minute over the last 5 minutes by event_type."
  echo "# TYPE event_log_rate_per_type gauge"
  sqlite3 "$DB" "SELECT event_type, ROUND(CAST(COUNT(*) AS REAL)/5.0, 3) FROM event_log WHERE emitted_at >= datetime('now','-5 minutes') GROUP BY event_type" | \
    while IFS='|' read -r et rate; do
      [ -n "$et" ] && echo "event_log_rate_per_type{event_type=\"${et}\"} ${rate}"
    done

  echo "# HELP event_log_duration_ms_p50 p50 duration_ms by event_type (last 1h, rows with duration_ms>=0)."
  echo "# TYPE event_log_duration_ms_p50 gauge"
  # SQLite has no PERCENTILE_CONT. Approximation: ORDER + LIMIT/OFFSET using
  # window functions (SQLite >= 3.25). Falls back to single-row MEDIAN via
  # a subquery that picks the middle row deterministically.
  sqlite3 "$DB" "
    WITH windowed AS (
      SELECT event_type, duration_ms,
             ROW_NUMBER() OVER (PARTITION BY event_type ORDER BY duration_ms) AS rn,
             COUNT(*)     OVER (PARTITION BY event_type)                     AS n
      FROM event_log
      WHERE emitted_at >= datetime('now','-1 hour') AND duration_ms >= 0
    )
    SELECT event_type, duration_ms FROM windowed WHERE rn = CAST(n * 0.50 + 0.5 AS INTEGER)
  " | while IFS='|' read -r et p50; do
    [ -n "$et" ] && echo "event_log_duration_ms_p50{event_type=\"${et}\"} ${p50}"
  done

  echo "# HELP event_log_duration_ms_p95 p95 duration_ms by event_type (last 1h, rows with duration_ms>=0)."
  echo "# TYPE event_log_duration_ms_p95 gauge"
  sqlite3 "$DB" "
    WITH windowed AS (
      SELECT event_type, duration_ms,
             ROW_NUMBER() OVER (PARTITION BY event_type ORDER BY duration_ms) AS rn,
             COUNT(*)     OVER (PARTITION BY event_type)                     AS n
      FROM event_log
      WHERE emitted_at >= datetime('now','-1 hour') AND duration_ms >= 0
    )
    SELECT event_type, duration_ms FROM windowed WHERE rn = CAST(n * 0.95 + 0.5 AS INTEGER)
  " | while IFS='|' read -r et p95; do
    [ -n "$et" ] && echo "event_log_duration_ms_p95{event_type=\"${et}\"} ${p95}"
  done

  echo "# HELP event_log_total_rows All-time event count by event_type."
  echo "# TYPE event_log_total_rows counter"
  sqlite3 "$DB" "SELECT event_type, COUNT(*) FROM event_log GROUP BY event_type" | \
    while IFS='|' read -r et c; do
      [ -n "$et" ] && echo "event_log_total_rows{event_type=\"${et}\"} ${c}"
    done
} > "$TMP_FILE"

mv "$TMP_FILE" "$OUT_FILE"
