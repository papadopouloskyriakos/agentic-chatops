#!/bin/bash
# Usage: ./yt-post-comment.sh <issue-id> "<comment text>"
# Posts a comment to a YouTrack issue.
set -eu
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace /app/claude-gateway; do [ -r "$d/.env" ] && . "$d/.env" && break; done
# Map app-user's .env var names to the names this script expects.
: "${YOUTRACK_TOKEN:=${YOUTRACK_API_TOKEN:-}}"
: "${YOUTRACK_URL:=https://youtrack.example.net}"

ISSUE_ID="${1:?Usage: yt-post-comment.sh <issue-id> \"<comment text>\"}"
COMMENT="${2:?Usage: yt-post-comment.sh <issue-id> \"<comment text>\"}"

# Safety: convert literal \n sequences to real newlines (prevents double-escaping)
COMMENT=$(printf '%b' "$COMMENT")

# Build JSON body safely using jq
BODY=$(jq -n --arg text "$COMMENT" '{text: $text}')

curl -sS --fail \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST \
  -d "$BODY" \
  "${YOUTRACK_URL}/api/issues/${ISSUE_ID}/comments?fields=id,text,author(login),created"
