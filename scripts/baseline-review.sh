#!/bin/bash
# Weekly Baseline Review — CTI-confirmed safe findings
# Reads baseline-suggestions.json, posts summary to Matrix for operator approval.
# Cron: 0 8 * * 1 (Monday 08:00, after weekly-lessons-digest)

set -euo pipefail

SUGGESTIONS_FILE="/app/cubeos/claude-context/baseline-suggestions.json"
MATRIX_URL="https://matrix.example.net"
ALERTS_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
TOKEN_FILE="$HOME/.matrix-claude-token"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

post_alert() {
  local msg="$1"
  if [ -f "$TOKEN_FILE" ]; then
    local token
    token=$(cat "$TOKEN_FILE")
    local txn="baseline-review-$(date +%s)-$RANDOM"
    curl -sf --max-time 10 -X PUT \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -d "{\"msgtype\":\"m.text\",\"body\":\"$(echo "$msg" | sed 's/"/\\"/g' | sed 's/\n/\\n/g')\"}" \
      "${MATRIX_URL}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/${txn}" >/dev/null 2>&1 || true
  fi
}

if [ ! -f "$SUGGESTIONS_FILE" ]; then
  log "No baseline suggestions file — nothing to review"
  exit 0
fi

# Count suggestions
COUNT=$(python3 -c "
import json
try:
    with open('$SUGGESTIONS_FILE') as f:
        suggestions = json.load(f)
    if not isinstance(suggestions, list):
        suggestions = []
    print(len(suggestions))
except:
    print(0)
" 2>/dev/null)

if [ "${COUNT:-0}" -eq 0 ]; then
  log "No pending baseline suggestions"
  exit 0
fi

# Build summary
SUMMARY=$(python3 -c "
import json
from datetime import datetime
with open('$SUGGESTIONS_FILE') as f:
    suggestions = json.load(f)

by_scanner = {}
for s in suggestions:
    scanner = s.get('scanner', 'unknown')
    if scanner not in by_scanner:
        by_scanner[scanner] = []
    by_scanner[scanner].append(s)

lines = []
for scanner, items in by_scanner.items():
    lines.append(f'Scanner {scanner} ({len(items)} suggestion(s)):')
    for item in items:
        lines.append(f'  - {item.get(\"finding\",\"?\")} on {item.get(\"target\",\"?\")} (CTI: {item.get(\"ctiReputation\",\"?\")})')
print('\n'.join(lines))
" 2>/dev/null)

MSG="[Baseline Review] $COUNT finding(s) confirmed safe by CrowdSec CTI this week:

$SUMMARY

To apply to scanner baselines, run: !baseline-apply
To dismiss all: !baseline-dismiss
To review individually: !baseline-show"

post_alert "$MSG"
log "Posted baseline review: $COUNT suggestions"

# --- Phase 2: Check for expired baseline entries ---
SSH_KEY="$HOME/.ssh/one_key"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -o BatchMode=yes"
SUDO_PASS="${SCANNER_SUDO_PASS:?SCANNER_SUDO_PASS env var not set}"
TODAY=$(date -u +%F)

EXPIRED=""
for scanner_info in "grsec01:10.0.X.X" "nlsec01:10.0.181.X"; do
  SCANNER="${scanner_info%%:*}"
  SCANNER_IP="${scanner_info##*:}"
  RESULT=$(ssh $SSH_OPTS "operator@$SCANNER_IP" "echo '$SUDO_PASS' | sudo -S grep 'Expires:' /opt/scans/baseline/ports.txt 2>/dev/null" 2>&1 | grep -v "^Warning\|sudo.*password" || true)
  if [ -n "$RESULT" ]; then
    while IFS= read -r line; do
      EXPIRY=$(echo "$line" | grep -oP 'Expires: \K[0-9-]+' 2>/dev/null || true)
      if [ -n "$EXPIRY" ] && [[ "$EXPIRY" < "$TODAY" ]]; then
        EXPIRED="$EXPIRED\n  - $SCANNER: $line"
      fi
    done <<< "$RESULT"
  fi
done

if [ -n "$EXPIRED" ]; then
  EXPIRED_MSG="[Baseline Expiry] The following baseline entries have EXPIRED and need re-review:
$(echo -e "$EXPIRED")

Remove expired entries or renew with: !baseline-add <target> <port> <scanner>"
  post_alert "$EXPIRED_MSG"
  log "Posted expired baseline entries alert"
fi
