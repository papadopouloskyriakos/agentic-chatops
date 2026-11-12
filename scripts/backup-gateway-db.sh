#!/bin/bash
# SQLite gateway.db backup — daily backup with 7-day retention
# Cron: 0 2 * * * /app/claude-gateway/scripts/backup-gateway-db.sh
#
# Creates timestamped backups + integrity check. Keeps 7 most recent.
# Resilience fix for single-point-of-failure identified in audit.

set -uo pipefail

DB="/app/cubeos/claude-context/gateway.db"
BACKUP_DIR="/app/cubeos/claude-context/backups"
RETENTION=7
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/gateway-${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

# Catch-up safety (IFRNLLEI01PRD-2992): the Cronicle event runs with catch_up, which replays EVERY
# missed daily tick back to back after downtime. A backup younger than BACKUP_MIN_INTERVAL_MIN
# (default 60) makes a run a no-op, so N replays leave one fresh backup instead of N identical copies
# that would rotate the older restore points out. FORCE=1 overrides (e.g. before a risky change).
MIN_INTERVAL_MIN="${BACKUP_MIN_INTERVAL_MIN:-60}"
if [ "${FORCE:-0}" != "1" ]; then
  NEWEST=$(ls -t "${BACKUP_DIR}"/gateway-*.db 2>/dev/null | head -1)
  if [ -n "$NEWEST" ] && [ -n "$(find "$NEWEST" -mmin -"$MIN_INTERVAL_MIN" 2>/dev/null)" ]; then
    echo "SKIP: $(basename "$NEWEST") is younger than ${MIN_INTERVAL_MIN} min (catch-up replay or repeat run); FORCE=1 to override"
    exit 0
  fi
fi

# Use SQLite online backup (safe even if DB is in use)
sqlite3 "$DB" ".backup '${BACKUP_FILE}'" 2>/dev/null
if [ $? -ne 0 ]; then
  echo "ERROR: SQLite backup failed"
  rm -f "$BACKUP_FILE"   # a partial file must not satisfy the catch-up freshness guard above
  exit 1
fi

# Verify backup integrity
INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check" 2>/dev/null)
if [ "$INTEGRITY" != "ok" ]; then
  echo "ERROR: Backup integrity check failed: $INTEGRITY"
  rm -f "$BACKUP_FILE"
  exit 1
fi

# Count tables and rows for verification
TABLES=$(sqlite3 "$BACKUP_FILE" ".tables" 2>/dev/null | wc -w)
SESSIONS=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM sessions" 2>/dev/null || echo 0)
KNOWLEDGE=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM incident_knowledge" 2>/dev/null || echo 0)

echo "BACKUP OK: ${BACKUP_FILE} (${TABLES} tables, ${SESSIONS} sessions, ${KNOWLEDGE} knowledge entries)"

# Rotate: keep only N most recent backups
ls -t "${BACKUP_DIR}"/gateway-*.db 2>/dev/null | tail -n +$((RETENTION + 1)) | xargs rm -f 2>/dev/null

# Report size
SIZE=$(du -sh "$BACKUP_FILE" 2>/dev/null | cut -f1)
echo "Size: ${SIZE}, Retention: ${RETENTION} backups"
