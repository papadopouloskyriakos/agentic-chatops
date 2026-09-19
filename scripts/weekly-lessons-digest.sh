#!/bin/bash
# weekly-lessons-digest.sh — Summarize lessons learned from past week, post to Matrix #alerts
# Cron: 0 7 * * 1 (Monday 07:00 UTC)
set -euo pipefail

DB="$HOME/gitlab/products/cubeos/claude-context/gateway.db"
MATRIX_URL="https://matrix.example.net"
ALERTS_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
TOKEN_FILE="$HOME/.matrix-claude-token"

if [ ! -f "$DB" ]; then
  echo "DB not found: $DB"
  exit 0
fi

# Get lessons from last 7 days
LESSONS=$(sqlite3 -separator '|' "$DB" \
  "SELECT issue_id, lesson FROM lessons_learned
   WHERE created_at > datetime('now', '-7 days')
   ORDER BY created_at DESC;" 2>/dev/null) || true

if [ -z "$LESSONS" ]; then
  exit 0
fi

COUNT=$(echo "$LESSONS" | wc -l)

# Build digest message
MSG="**Weekly Lessons Digest** ($COUNT lesson(s) from last 7 days):\n\n"
while IFS='|' read -r issue_id lesson; do
  MSG="${MSG}- **${issue_id}**: ${lesson}\n"
done <<< "$LESSONS"

MSG="${MSG}\nReview these for potential SOUL.md/CLAUDE.md updates."

# Post to Matrix #alerts
if [ -f "$TOKEN_FILE" ]; then
  TOKEN=$(cat "$TOKEN_FILE")
  TXN="lessons-digest-$(date +%s)"
  BODY=$(printf '{"msgtype":"m.notice","body":"%s","format":"org.matrix.custom.html","formatted_body":"%s"}' \
    "$(echo -e "$MSG" | sed 's/"/\\"/g')" \
    "$(echo -e "$MSG" | sed 's/\*\*/<strong>/;s/\*\*/<\/strong>/' | sed 's/"/\\"/g')")

  curl -sf -X PUT \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$BODY" \
    "${MATRIX_URL}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/${TXN}" >/dev/null 2>&1 || true
fi

echo "Posted $COUNT lessons to #alerts"
