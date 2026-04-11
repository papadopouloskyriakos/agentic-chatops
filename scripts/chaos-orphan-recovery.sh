#!/bin/bash
# chaos-orphan-recovery.sh — Recover from orphaned chaos state after unclean reboot.
#
# @reboot cron: if chaos-active.json survives a reboot, either recover immediately
# (if expired) or schedule a dead-man switch for the remaining duration.
#
# Cron: @reboot /app/claude-gateway/scripts/chaos-orphan-recovery.sh

set -uo pipefail

STATE="$HOME/chaos-state/chaos-active.json"
REPO="$HOME/gitlab/n8n/claude-gateway"
ENV_FILE="$REPO/.env"
LOG_TAG="[chaos-orphan-recovery]"

[ -f "$STATE" ] || exit 0

logger "$LOG_TAG Found orphaned chaos state, checking expiry..."

# Source .env for CISCO_ASA_PASSWORD
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

# Check expiry
EXPIRES=$(python3 -c "import json; print(json.load(open('$STATE'))['expires_at'])" 2>/dev/null)
if [ -z "$EXPIRES" ]; then
    logger "$LOG_TAG Corrupt state file, removing"
    rm -f "$STATE"
    exit 0
fi

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [[ "$NOW" > "$EXPIRES" ]]; then
    logger "$LOG_TAG State expired, running immediate recovery"
    CHAOS_INTERNAL_RECOVER=1 python3 "$REPO/scripts/chaos-test.py" recover
else
    REMAINING=$(python3 -c "
import json, datetime
s = json.load(open('$STATE'))
exp = datetime.datetime.fromisoformat(s['expires_at'].replace('Z', '+00:00'))
now = datetime.datetime.now(datetime.timezone.utc)
print(max(int((exp - now).total_seconds()) + 60, 10))" 2>/dev/null)
    logger "$LOG_TAG State still active, scheduling dead-man in ${REMAINING}s"
    nohup bash -c "sleep $REMAINING && CHAOS_INTERNAL_RECOVER=1 python3 $REPO/scripts/chaos-test.py recover" &>/dev/null &
fi
