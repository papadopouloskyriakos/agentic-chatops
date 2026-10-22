#!/bin/bash
# Usage: ./yt-get-comments.sh <issue-id>
# Fetches all comments for a YouTrack issue.
set -eu
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace /app/claude-gateway; do [ -r "$d/.env" ] && . "$d/.env" && break; done
: "${YOUTRACK_TOKEN:=${YOUTRACK_API_TOKEN:-}}"
: "${YOUTRACK_URL:=https://youtrack.example.net}"


ISSUE_ID="${1:?Usage: yt-get-comments.sh <issue-id>}"

curl -sS --fail \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  "${YOUTRACK_URL}/api/issues/${ISSUE_ID}/comments?fields=id,text,author(login),created"
