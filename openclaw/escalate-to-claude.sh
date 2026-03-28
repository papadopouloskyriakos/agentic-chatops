#!/bin/bash
# escalate-to-claude.sh — Escalate to Claude Code via n8n webhook
#
# Usage: ./escalate-to-claude.sh <ISSUE-ID> [summary text]

set -eu

# Load credentials
for d in /root/.openclaw/workspace /home/node/.openclaw/workspace; do
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

# Build NL-A2A/v1 envelope (structured inter-agent communication)
# Accepts optional env vars from triage scripts for richer context
JSON_BODY=$(python3 -c "
import json, sys, os, uuid, datetime
msg_id = str(uuid.uuid4())[:8]
envelope = {
    'protocol': 'nl-a2a/v1',
    'messageId': msg_id,
    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
    'from': {'tier': 1, 'agent': 'openclaw'},
    'to': {'tier': 2, 'agent': 'claude-code'},
    'type': 'escalation',
    'issueId': sys.argv[1],
    'payload': {
        'summary': sys.argv[2],
        'escalationReason': []
    },
    'context': {
        'completedSteps': []
    }
}
# Enrich with triage context if available (set by triage scripts)
if os.environ.get('TRIAGE_CONFIDENCE'):
    envelope['context']['confidence'] = float(os.environ['TRIAGE_CONFIDENCE'])
if os.environ.get('TRIAGE_COMPLETED_STEPS'):
    envelope['context']['completedSteps'] = os.environ['TRIAGE_COMPLETED_STEPS'].split(',')
if os.environ.get('TRIAGE_HOSTNAME'):
    envelope['payload']['hostname'] = os.environ['TRIAGE_HOSTNAME']
if os.environ.get('TRIAGE_ALERT_RULE'):
    envelope['payload']['alertRule'] = os.environ['TRIAGE_ALERT_RULE']
if os.environ.get('TRIAGE_SEVERITY'):
    envelope['payload']['severity'] = os.environ['TRIAGE_SEVERITY']
if os.environ.get('TRIAGE_SITE'):
    envelope['payload']['site'] = os.environ['TRIAGE_SITE']
if os.environ.get('TRIAGE_ESCALATION_REASON'):
    envelope['payload']['escalationReason'] = os.environ['TRIAGE_ESCALATION_REASON'].split(',')

# Backwards compatibility: flatten key fields for n8n receiver
envelope['summary'] = sys.argv[2]
envelope['updatedBy'] = 'openclaw'

print(json.dumps(envelope))
" "$ISSUE_ID" "$SUMMARY")

# Log to A2A task log
MSG_ID=$(echo "$JSON_BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('messageId',''))" 2>/dev/null || echo "")
DB_A2A="/home/claude-runner/gitlab/products/cubeos/claude-context/gateway.db"
if [ -n "$MSG_ID" ]; then
  sqlite3 "$DB_A2A" "INSERT INTO a2a_task_log (message_id, issue_id, from_tier, from_agent, to_tier, to_agent, message_type, state, payload_summary, confidence)
    VALUES ('$MSG_ID', '$ISSUE_ID', 1, 'openclaw', 2, 'claude-code', 'escalation', 'escalated',
    '$(echo "$SUMMARY" | head -c 200 | tr "'" " ")',
    ${TRIAGE_CONFIDENCE:--1});" 2>/dev/null || true
fi

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
