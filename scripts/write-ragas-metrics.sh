#!/bin/bash
# write-ragas-metrics.sh — RAGAS evaluation metrics for Prometheus textfile collector
#
# Reads ragas_evaluation table from gateway.db and exports aggregate metrics.
#
# Cron: */5 * * * * /app/claude-gateway/scripts/write-ragas-metrics.sh
# Source: Industry Benchmark 2026-04-15, IFRNLLEI01PRD-572

set -u

DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
PROM="/var/lib/node_exporter/textfile_collector/ragas_metrics.prom"

[ "${1:-}" = "--dry-run" ] && PROM="/dev/stdout"
[ -f "$DB" ] || { echo "ERROR: DB not found at $DB" >&2; exit 1; }

TABLE_EXISTS=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='ragas_evaluation';" 2>/dev/null || echo "0")
[ "$TABLE_EXISTS" = "0" ] && exit 0

TMPFILE="${PROM}.tmp"
[ "$PROM" = "/dev/stdout" ] && TMPFILE="/dev/stdout"

cat > "$TMPFILE" << 'HEADER'
# HELP ragas_faithfulness_avg Average faithfulness score (7d)
# TYPE ragas_faithfulness_avg gauge
# HELP ragas_precision_avg Average context precision (7d)
# TYPE ragas_precision_avg gauge
# HELP ragas_recall_avg Average context recall (7d)
# TYPE ragas_recall_avg gauge
# HELP ragas_evaluations_total Total RAGAS evaluations (all time)
# TYPE ragas_evaluations_total gauge
# HELP ragas_evaluations_7d RAGAS evaluations in last 7 days
# TYPE ragas_evaluations_7d gauge
# HELP ragas_below_threshold Evaluations with faithfulness below 0.80 (7d)
# TYPE ragas_below_threshold gauge
HEADER

read -r FAITH PREC RECALL <<< "$(sqlite3 "$DB" "
    SELECT
        COALESCE(ROUND(AVG(CASE WHEN faithfulness >= 0 THEN faithfulness END), 3), -1),
        COALESCE(ROUND(AVG(CASE WHEN context_precision >= 0 THEN context_precision END), 3), -1),
        COALESCE(ROUND(AVG(CASE WHEN context_recall >= 0 THEN context_recall END), 3), -1)
    FROM ragas_evaluation
    WHERE created_at > datetime('now', '-7 days');
" 2>/dev/null | tr '|' ' ')" || true

TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ragas_evaluation;" 2>/dev/null || echo 0)
TOTAL_7D=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ragas_evaluation WHERE created_at > datetime('now', '-7 days');" 2>/dev/null || echo 0)
BELOW=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ragas_evaluation WHERE created_at > datetime('now', '-7 days') AND faithfulness >= 0 AND faithfulness < 0.80;" 2>/dev/null || echo 0)

{
    echo "ragas_faithfulness_avg ${FAITH:--1}"
    echo "ragas_precision_avg ${PREC:--1}"
    echo "ragas_recall_avg ${RECALL:--1}"
    echo "ragas_evaluations_total ${TOTAL:-0}"
    echo "ragas_evaluations_7d ${TOTAL_7D:-0}"
    echo "ragas_below_threshold ${BELOW:-0}"
} >> "$TMPFILE"

if [ "$PROM" != "/dev/stdout" ]; then
    mv "$TMPFILE" "$PROM"
fi
