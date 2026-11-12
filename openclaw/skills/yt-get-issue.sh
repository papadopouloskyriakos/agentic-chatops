#!/bin/bash
# Usage: ./yt-get-issue.sh <issue-id>
# Fetches full issue details including comments from YouTrack.
set -eu
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace /app/claude-gateway; do [ -r "$d/.env" ] && . "$d/.env" && break; done
: "${YOUTRACK_TOKEN:=${YOUTRACK_API_TOKEN:-}}"
: "${YOUTRACK_URL:=https://youtrack.example.net}"


ISSUE_ID="${1:?Usage: yt-get-issue.sh <issue-id>}"

curl -sS --fail \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  "${YOUTRACK_URL}/api/issues/${ISSUE_ID}?fields=id,idReadable,summary,description,created,updated,resolved,customFields(name,value(name,login)),tags(name),comments(text,author(login),created)"
