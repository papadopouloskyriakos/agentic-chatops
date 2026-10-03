#!/bin/bash
# verify-scheduled-reboot-boot.sh <hostname> <fire_utc>
#
# Two-phase verify-and-reopen (decision 1, 2026-06-29) for the scheduled-reboot
# suppression. Launched non-blocking by tier1-suppression-flow.sh right after a
# phaseSR suppression. Within ~60s it SSHes the host and checks the ACTUAL boot
# reason of the reboot that just matched the scheduled window:
#
#   CLEAN    -> the previous boot ended with systemd-reboot (the scheduled
#               shutdown). Bumps the verified counter. No action.
#   REACTIVE -> OOM / kernel panic / watchdog / self-heal / hard reset (the
#               irreducible residual: a reactive reboot that coincidentally
#               landed in-window). REOPENS: pages #alerts + force-escalates a
#               real Tier 2 investigation + bumps the misclassified counter.
#   UNKNOWN  -> no clean signature found. Treated as REACTIVE (reopen) — the
#               safe direction. "Guaranteed reversal" beats a quiet false-suppress.
#
# Best-effort throughout: never raises (it is nohup'd and detached). Idempotent
# per (host, fire_utc) via a small dedup file so a flapping alert doesn't reopen
# repeatedly for the same boot.
set -uo pipefail

HOSTNAME="${1:-}"
FIRE_UTC="${2:-}"
REPO="/app/claude-gateway"
LOGDIR="/home/app-user/logs/claude-gateway"
STATE_DIR="/home/app-user/gateway-state"
COUNTERS="$STATE_DIR/scheduled-reboot-verify-counters.json"
DEDUP_DIR="/tmp/sched-reboot-verify"
mkdir -p "$LOGDIR" "$STATE_DIR" "$DEDUP_DIR" 2>/dev/null
LOG="$LOGDIR/scheduled-reboot-verify.log"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }

[ -n "$HOSTNAME" ] && [ -n "$FIRE_UTC" ] || { log "ERR: usage $0 <hostname> <fire_utc>"; exit 2; }

# Dedup: one reopen per (host, fire_utc) window.
DEDUP_KEY="$(echo -n "${HOSTNAME}|${FIRE_UTC}" | md5sum | cut -c1-16)"
[ -f "$DEDUP_DIR/$DEDUP_KEY" ] && { log "DEDUP skip $HOSTNAME fire=$FIRE_UTC (already verified)"; exit 0; }
# Hold the dedup slot for 30 min, then allow a re-verify.
{ date -u +%s; } > "$DEDUP_DIR/$DEDUP_KEY"

bump_counter() {  # <key>
  python3 - "$COUNTERS" "$1" <<'PY' 2>/dev/null || true
import json, os, sys
path, key = sys.argv[1], sys.argv[2]
try: d = json.load(open(path))
except Exception: d = {}
d[key] = int(d.get(key, 0)) + 1
json.dump(d, open(path, "w"))
PY
}

# ── SSH to the host (try the fleet keys; first that works) ────────────────────
ssh_run() {  # <cmd>
  local key
  for key in ~/.ssh/one_key ~/.ssh/id_ed25519 ~/.ssh/id_rsa; do
    [ -f "$key" ] || continue
    ssh -i "$key" -o StrictHostKeyChecking=no -o ConnectTimeout=8 -o BatchMode=yes \
        "root@${HOSTNAME}" "$1" 2>/dev/null && return 0
  done
  return 1
}

log "VERIFY start host=$HOSTNAME fire=$FIRE_UTC"

# The reboot that just matched the window is the transition boot[-2] -> boot[-1].
# The REASON lives at the END of the previous boot (journalctl -b -1).
PREV_BOOT_TAIL=$(ssh_run 'journalctl -b -1 -n 80 --no-pager 2>/dev/null || journalctl -b 0 -n 80 --no-pager 2>/dev/null')
SSH_OK=$?

if [ $SSH_OK -ne 0 ] || [ -z "$PREV_BOOT_TAIL" ]; then
  log "WARN $HOSTNAME: could not SSH / no journal — cannot confirm clean; LEAVING SUPPRESSED (verify inconclusive, not a confirmed misclassify). Counted as verify_unreachable."
  bump_counter verify_unreachable
  exit 0
fi

# Clean signatures: the previous boot reached the reboot target via systemd-reboot.
# Reactive signatures: anything that is NOT a clean scheduled shutdown.
if printf '%s' "$PREV_BOOT_TAIL" | grep -qiE 'reached target reboot\.target|systemd-reboot\.service|systemd-shutdown\[1\]|syncing filesystems'; then
  CLEAN=1
elif printf '%s' "$PREV_BOOT_TAIL" | grep -qiE 'oom-kill|out of memory|invoked oom|kernel panic|watchdog|hung_task|emergency|selfheal|self-heal|nvml|thermal|Power Button'; then
  CLEAN=0   # explicitly reactive
else
  CLEAN=0   # unknown -> treat as reopen (safe direction)
fi

if [ "$CLEAN" = "1" ]; then
  log "VERIFY CLEAN $HOSTNAME fire=$FIRE_UTC — scheduled reboot confirmed, no action."
  bump_counter verified
  exit 0
fi

# ── REOPEN: not a clean scheduled reboot ──────────────────────────────────────
log "REOPEN $HOSTNAME fire=$FIRE_UTC — boot was NOT a clean scheduled reboot (CLEAN=$CLEAN). Escalating + paging."
bump_counter misclassified

# 1. Audit row (best-effort) so the misclassification is queryable.
DB="/app/cubeos/claude-context/gateway.db"
PAYLOAD="{\"host\":\"${HOSTNAME}\",\"fire_utc\":\"${FIRE_UTC}\",\"clean\":false,\"action\":\"reopened\",\"ts\":\"$(date -u +%FT%TZ)\"}"
[ -w "$DB" ] && sqlite3 "$DB" \
  "INSERT INTO event_log (issue_id, agent_name, event_type, payload_json) VALUES ('','scheduled-reboot-verify','scheduled_reboot_misclassified','${PAYLOAD}');" 2>/dev/null || true

# 2. Page #alerts (best-effort via the bot API; creds in .env).
ALERTS_ROOM='!xeNxtpScJWCmaFjeCL:matrix.example.net'
HS="${MATRIX_HOME_SERVER:-https://matrix.example.net}"
TOK="${MATRIX_ACCESS_TOKEN:-$(grep -E '^MATRIX_ACCESS_TOKEN=|^MATRIX_BOT_TOKEN=' "$REPO/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"')}"
if [ -n "$TOK" ]; then
  TXN="schedreboot-$(date -u +%s%N)"
  MSG="⚠️ SCHEDULED-REBOOT REOPEN: ${HOSTNAME} reboot at ${FIRE_UTC} was NOT a clean scheduled reboot (phaseSR two-phase verify). A reactive cause (OOM/watchdog/self-heal) landed in the suppression window — force-investigating. See $LOG."
  curl -s -m 8 -X PUT "${HS}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/${TXN}" \
    -H "Authorization: Bearer ${TOK}" -H "Content-Type: application/json" \
    -d "{\"msgtype\":\"m.text\",\"body\":$(printf '%s' "$MSG" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')}" >/dev/null 2>&1 || true
fi

# 3. Force a real Tier 2 investigation (the actual reopen).
ESC="$REPO/openclaw/skills/escalate-to-claude.sh"
if [ -x "$ESC" ]; then
  "$ESC" "SCHEDREBOOT-${HOSTNAME}-$(date -u +%s)" \
    "Scheduled-reboot two-phase verify REOPENED for ${HOSTNAME} (fire ${FIRE_UTC}): the boot was NOT a clean systemd-reboot. Root-cause this reboot as you would any unexpected reboot — do NOT assume it was the scheduled one. Evidence in $LOG." \
    >/dev/null 2>&1 || log "WARN: escalate-to-claude.sh failed (Matrix page + event_log still recorded)"
fi

log "REOPEN complete $HOSTNAME fire=$FIRE_UTC"
exit 0
