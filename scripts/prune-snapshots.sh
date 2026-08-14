#!/bin/bash
# prune-snapshots.sh — delete session_state_snapshot rows older than 7 days.
# Cron: `15 3 * * *` (daily). IFRNLLEI01PRD-636.
set -euo pipefail
DAYS="${SNAPSHOT_RETENTION_DAYS:-7}"
cd /app/claude-gateway/scripts
python3 -m lib.snapshot prune --days "$DAYS"
