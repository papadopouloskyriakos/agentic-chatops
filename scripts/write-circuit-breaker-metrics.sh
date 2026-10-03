#!/bin/bash
# write-circuit-breaker-metrics.sh — IFRNLLEI01PRD-631
# Exports circuit_breakers SQLite table to Prometheus textfile.
# Runs as cron every 5 minutes on nl-claude01 as app-user.

set -u
DB="/app/cubeos/claude-context/gateway.db"
OUT="/var/lib/node_exporter/textfile_collector/circuit_breaker_metrics.prom"
PYTHON_PATH="/app/claude-gateway/scripts"

[ -f "$DB" ] || exit 0

# Delegate to the Python exporter — single source of truth for metric format.
cd "$PYTHON_PATH" && python3 -m lib.circuit_breaker --db "$DB" export "$OUT" 2>/dev/null
