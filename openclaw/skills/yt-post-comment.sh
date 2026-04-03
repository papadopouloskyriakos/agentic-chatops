#!/bin/bash
# Usage: ./yt-post-comment.sh <issue-id> "<comment text>"
# Posts a comment to a YouTrack issue.
set -eu
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace; do [ -r "$d/.env" ] && . "$d/.env" && break; done

ISSUE_ID="${1:?Usage: yt-post-comment.sh <issue-id> \"<comment text>\"}"
COMMENT="${2:?Usage: yt-post-comment.sh <issue-id> \"<comment text>\"}"

# Build JSON body safely using jq
BODY=$(jq -n --arg text "$COMMENT" '{text: $text}')

curl -sS --fail \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST \
  -d "$BODY" \
  "${YOUTRACK_URL}/api/issues/${ISSUE_ID}/comments?fields=id,text,author(login),created"
