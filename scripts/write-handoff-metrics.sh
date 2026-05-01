#!/usr/bin/env bash
# write-handoff-metrics.sh — Prometheus exporter for handoff depth
# (IFRNLLEI01PRD-643). Cron: */5.
#
# Metrics:
#   handoff_depth_max     Gauge  -- max depth across active sessions
#   handoff_depth_p95     Gauge  -- p95 depth across active sessions
#   handoff_depth_sessions Gauge -- count of sessions at each depth bucket
#   handoff_cycle_detected_total Counter -- all-time cycles detected
set -uo pipefail
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
OUT_DIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/prometheus/node-exporter}"
OUT_FILE="${OUT_DIR}/handoff_depth.prom"
TMP_FILE="${OUT_FILE}.tmp"

[ -f "$DB" ] || exit 1

if ! sqlite3 "$DB" "SELECT 1 FROM pragma_table_info('sessions') WHERE name='handoff_depth'" | grep -q 1; then
  echo "# handoff_depth column not yet migrated; skipping" > "$TMP_FILE"
  mv "$TMP_FILE" "$OUT_FILE" 2>/dev/null || true
  exit 0
fi

{
  MAX_DEPTH=$(sqlite3 "$DB" "SELECT COALESCE(MAX(handoff_depth),0) FROM sessions WHERE is_current=1")
  echo "# HELP handoff_depth_max Max handoff_depth across currently-active sessions."
  echo "# TYPE handoff_depth_max gauge"
  echo "handoff_depth_max ${MAX_DEPTH}"

  P95=$(sqlite3 "$DB" "
    WITH ranked AS (
      SELECT handoff_depth,
             ROW_NUMBER() OVER (ORDER BY handoff_depth) AS rn,
             COUNT(*)    OVER ()                        AS n
      FROM sessions
      WHERE is_current=1
    )
    SELECT COALESCE(handoff_depth,0) FROM ranked WHERE rn = CAST(n * 0.95 + 0.5 AS INTEGER)
    LIMIT 1
  " 2>/dev/null)
  echo "# HELP handoff_depth_p95 p95 handoff_depth across currently-active sessions."
  echo "# TYPE handoff_depth_p95 gauge"
  echo "handoff_depth_p95 ${P95:-0}"

  echo "# HELP handoff_depth_sessions Count of currently-active sessions at each depth."
  echo "# TYPE handoff_depth_sessions gauge"
  sqlite3 "$DB" "SELECT handoff_depth, COUNT(*) FROM sessions WHERE is_current=1 GROUP BY handoff_depth" | \
    while IFS='|' read -r d c; do
      [ -n "$d" ] && echo "handoff_depth_sessions{depth=\"${d}\"} ${c}"
    done

  if sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE name='event_log' AND type='table'" | grep -q 1; then
    CYCLE_N=$(sqlite3 "$DB" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_cycle_detected'")
    echo "# HELP handoff_cycle_detected_total All-time count of detected handoff cycles."
    echo "# TYPE handoff_cycle_detected_total counter"
    echo "handoff_cycle_detected_total ${CYCLE_N}"
  fi
} > "$TMP_FILE"

mv "$TMP_FILE" "$OUT_FILE"
