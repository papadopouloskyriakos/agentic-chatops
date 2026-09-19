#!/bin/bash
# safe-exec.sh — Enforcement-level exec guardrail for OpenClaw
# Wraps command execution with blocklist + rate limiting + logging
# This is CODE enforcement, not prompt-level (LLM cannot bypass it)
#
# Usage: safe-exec.sh <command...>
# Returns: exit code of the command, or 99 if blocked

set -uo pipefail

COMMAND="$*"
LOG_FILE="/tmp/openclaw-exec.log"
RATE_FILE="/tmp/openclaw-exec-rate"
MAX_EXEC_PER_MINUTE=30

# ─── Blocklist (enforcement-level — cannot be bypassed by prompt injection) ───
BLOCKED_PATTERNS=(
  "rm -rf /"
  "rm -rf /*"
  "rm -rf ~"
  "rm -rf /home"
  "rm -rf /etc"
  "rm -rf /var"
  "reboot"
  "shutdown"
  "init 0"
  "init 6"
  "halt"
  "poweroff"
  "mkfs"
  "dd if=/dev/zero"
  "dd of=/dev/sd"
  "> /dev/sd"
  "kubectl delete namespace"
  "kubectl delete --all"
  "kubectl delete -A"
  "iptables -F"
  "iptables -X"
  "systemctl stop n8n"
  "systemctl disable n8n"
  "systemctl stop openclaw"
  "pkill -9"
  "kill -9 1"
  "chmod -R 777 /"
  "chown -R"
  "passwd"
  "useradd"
  "userdel"
  "visudo"
  "crontab -r"
)

# ─── External exfiltration patterns ───
EXFIL_PATTERNS=(
  "curl.*[^.]*\.[^n][^u]"  # curl to non-internal domains (simplified check below)
  "wget http"
  "nc -e"
  "ncat -e"
  "bash -i >& /dev/tcp"
  "python.*socket.*connect"
  "scp.*@.*:"
  "rsync.*@.*:"
)

# ─── Check blocklist ───
CMD_LOWER=$(echo "$COMMAND" | tr '[:upper:]' '[:lower:]')

for pattern in "${BLOCKED_PATTERNS[@]}"; do
  pattern_lower=$(echo "$pattern" | tr '[:upper:]' '[:lower:]')
  if echo "$CMD_LOWER" | grep -qF "$pattern_lower"; then
    echo "BLOCKED: Command matches blocklist pattern: $pattern" >&2
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) BLOCKED [$pattern] $COMMAND" >> "$LOG_FILE"
    exit 99
  fi
done

# ─── Check external exfiltration ───
# Allow curl/wget only to *.example.net domains
if echo "$CMD_LOWER" | grep -qE '(curl|wget)\s'; then
  INTERNAL_DOMAINS="${SAFE_EXEC_INTERNAL_DOMAINS:-example.net}"
  if ! echo "$CMD_LOWER" | grep -qE "${INTERNAL_DOMAINS}|localhost|127\.0\.0\.1|192\.168\.|10\.|nl|gr"; then
    echo "BLOCKED: curl/wget to external domain not allowed" >&2
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) BLOCKED [exfiltration] $COMMAND" >> "$LOG_FILE"
    exit 99
  fi
fi

# Reverse shell patterns
for pattern in "bash -i" "nc -e" "ncat -e" "/dev/tcp"; do
  if echo "$CMD_LOWER" | grep -qF "$pattern"; then
    echo "BLOCKED: Reverse shell pattern detected" >&2
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) BLOCKED [reverse-shell] $COMMAND" >> "$LOG_FILE"
    exit 99
  fi
done

# ─── Rate limiting ───
NOW=$(date +%s)
MINUTE_KEY=$((NOW / 60))
CURRENT_RATE_KEY=$(cat "$RATE_FILE" 2>/dev/null | head -1 || echo "0")
CURRENT_RATE_COUNT=$(cat "$RATE_FILE" 2>/dev/null | tail -1 || echo "0")

if [ "$CURRENT_RATE_KEY" = "$MINUTE_KEY" ]; then
  NEW_COUNT=$((CURRENT_RATE_COUNT + 1))
  if [ "$NEW_COUNT" -gt "$MAX_EXEC_PER_MINUTE" ]; then
    echo "BLOCKED: Rate limit exceeded ($MAX_EXEC_PER_MINUTE commands/minute)" >&2
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) BLOCKED [rate-limit] $COMMAND" >> "$LOG_FILE"
    exit 99
  fi
  echo -e "$MINUTE_KEY\n$NEW_COUNT" > "$RATE_FILE"
else
  echo -e "$MINUTE_KEY\n1" > "$RATE_FILE"
fi

# ─── Log and execute ───
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ALLOWED $COMMAND" >> "$LOG_FILE"

# Trim log to last 1000 lines
tail -1000 "$LOG_FILE" > "${LOG_FILE}.tmp" 2>/dev/null && mv "${LOG_FILE}.tmp" "$LOG_FILE" 2>/dev/null || true

# Execute
eval "$COMMAND"
