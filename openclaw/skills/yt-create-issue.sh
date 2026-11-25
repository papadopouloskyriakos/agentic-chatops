#!/bin/bash
# Usage: ./yt-create-issue.sh <project-short-name> "<summary>" "<description>"
set -eu
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace /app/claude-gateway; do [ -r "$d/.env" ] && . "$d/.env" && break; done
: "${YOUTRACK_TOKEN:=${YOUTRACK_API_TOKEN:-}}"
: "${YOUTRACK_URL:=https://youtrack.example.net}"


PROJECT="${1:?Usage: yt-create-issue.sh <project-short-name> \"<summary>\" \"<description>\"}"
SUMMARY="${2:?Usage: yt-create-issue.sh <project-short-name> \"<summary>\" \"<description>\"}"
DESCRIPTION="${3:-}"

BODY=$(jq -n \
  --arg proj "$PROJECT" \
  --arg sum "$SUMMARY" \
  --arg desc "$DESCRIPTION" \
  '{project: {shortName: $proj}, summary: $sum, description: $desc}')

curl -sS --fail \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST \
  -d "$BODY" \
  "${YOUTRACK_URL}/api/issues?fields=id,idReadable,summary,description"
