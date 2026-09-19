#!/bin/bash
# Usage: ./yt-update-state.sh <issue-id> <state-name>
# Updates the State custom field on a YouTrack issue.
# Requires numeric ID — fetches it from readable ID first.
# Valid states: Open, In Progress, To Verify, Done
set -eu
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace /app/claude-gateway; do [ -r "$d/.env" ] && . "$d/.env" && break; done
: "${YOUTRACK_TOKEN:=${YOUTRACK_API_TOKEN:-}}"
: "${YOUTRACK_URL:=https://youtrack.example.net}"


ISSUE_ID="${1:?Usage: yt-update-state.sh <issue-id> <state-name>}"
STATE="${2:?Usage: yt-update-state.sh <issue-id> <state-name>}"

# Get numeric ID from readable ID
NUMERIC_ID=$(curl -sS --fail \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  "${YOUTRACK_URL}/api/issues/${ISSUE_ID}?fields=id" | jq -r .id)

if [ -z "$NUMERIC_ID" ] || [ "$NUMERIC_ID" = "null" ]; then
  echo "{\"error\": \"Could not resolve numeric ID for ${ISSUE_ID}\"}" >&2
  exit 1
fi

# Build JSON body safely using jq
BODY=$(jq -n \
  --arg state "$STATE" \
  '{"customFields":[{"$type":"StateIssueCustomField","name":"State","value":{"$type":"StateBundleElement","name":$state}}]}')

curl -sS --fail \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST \
  -d "$BODY" \
  "${YOUTRACK_URL}/api/issues/${NUMERIC_ID}?fields=customFields(name,value(name))"
