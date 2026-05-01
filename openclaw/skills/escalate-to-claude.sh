#!/bin/bash
# escalate-to-claude.sh — Escalate to Claude Code via n8n webhook
#
# Usage: ./escalate-to-claude.sh <ISSUE-ID> [summary text]

set -eu

# Load credentials
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace; do
  [ -r "$d/.env" ] && . "$d/.env" && break
done

ISSUE_ID="${1:-}"
shift 2>/dev/null || true
SUMMARY="$*"

if [ -z "$ISSUE_ID" ]; then
  echo "ERROR: Usage: escalate-to-claude.sh <ISSUE-ID> [summary]"
  exit 1
fi

if ! echo "$ISSUE_ID" | grep -qE '^[A-Z0-9]+-[0-9]+$'; then
  echo "ERROR: Invalid issue ID format: $ISSUE_ID (expected e.g. CUBEOS-4)"
  exit 1
fi

N8N_WEBHOOK="https://n8n.example.net/webhook/youtrack-webhook"
YT_URL="${YOUTRACK_URL:-https://youtrack.example.net}"
YT_TOKEN="${YOUTRACK_TOKEN:-}"

# If no summary provided, fetch from YouTrack
if [ -z "$SUMMARY" ] && [ -n "$YT_TOKEN" ]; then
  SUMMARY=$(curl -s -H "Authorization: Bearer $YT_TOKEN" \
    "$YT_URL/api/issues/$ISSUE_ID?fields=summary" 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('summary',''))" 2>/dev/null || echo "")
fi

if [ -z "$SUMMARY" ]; then
  SUMMARY="Escalated from OpenClaw"
fi

# Move issue to In Progress (use command API — direct field update silently fails due to YT workflow restrictions)
if [ -n "$YT_TOKEN" ]; then
  curl -s -X POST \
    -H "Authorization: Bearer $YT_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"issues\":[{\"idReadable\":\"$ISSUE_ID\"}],\"query\":\"state In Progress\"}" \
    "$YT_URL/api/commands" >/dev/null 2>&1 || true
fi

# Build JSON payload safely (handles quotes in summary)
JSON_BODY=$(python3 -c "import json,sys; print(json.dumps({'issueId': sys.argv[1], 'summary': sys.argv[2], 'updatedBy': 'openclaw'}))" "$ISSUE_ID" "$SUMMARY")

# Fire the n8n webhook
HTTP_CODE=$(curl -s -o /tmp/escalate_response.txt -w '%{http_code}' \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$JSON_BODY" \
  "$N8N_WEBHOOK" 2>/dev/null || echo "000")

RESPONSE=$(cat /tmp/escalate_response.txt 2>/dev/null || echo "")

if [ "$HTTP_CODE" = "200" ]; then
  echo "OK: Escalated $ISSUE_ID to Claude Code (HTTP $HTTP_CODE)"
else
  echo "WARN: Webhook returned HTTP $HTTP_CODE (n8n may be temporarily unavailable)"
  echo "Response: $RESPONSE"
  echo "The issue was moved to In Progress. Claude Code session may start when n8n recovers."
fi
