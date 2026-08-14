#!/bin/bash
# freedom-ont-drill-trigger.sh — One-shot trigger for a monthly Freedom-ONT
# failover drill. Posts the Matrix notice + installs the chaos-active
# suppression marker. Operator still runs the `shutdown` manually on
# nl-sw01 Gi1/0/36 per the scenario's `manual_execute: true` flag.
#
# Invoked by a cron entry (one-off; self-removes after firing to keep the
# crontab clean). Scheduled per IFRNLLEI01PRD-695 acceleration request
# 2026-04-22.
#
# Expected sequence after this fires:
#   08:00 CEST  — operator reads Matrix notice, SSHes sw01, issues shutdown
#   08:00-08:30 — budget-pppoe-health.sh / mesh-stats capture Budget-only state
#   ~08:30 CEST — operator issues `no shutdown`, recovery timings captured
#   next freedom-qos-toggle.sh run  — SMS on UP/DOWN transition as usual
#   post-drill   — operator (or Claude) writes chaos_experiments row via
#                  chaos_baseline.write_experiment()

set -uo pipefail

REPO_DIR="/app/claude-gateway"
LOG="$HOME/logs/claude-gateway/freedom-ont-drill.log"
CHAOS_ACTIVE_FILE="$HOME/chaos-state/chaos-active.json"
MATRIX_ROOM_INFRA_NL="!AOMuEtXGyzGFLgObKN:matrix.example.net"

mkdir -p "$(dirname "$LOG")" "$(dirname "$CHAOS_ACTIVE_FILE")"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG"; }

notify_matrix() {
    local message="$1"
    local token=""
    if [ -f "$REPO_DIR/.env" ]; then
        token=$(grep '^MATRIX_CLAUDE_TOKEN=' "$REPO_DIR/.env" | cut -d= -f2- | tr -d "'\"")
    fi
    [ -z "$token" ] && { log "MATRIX_CLAUDE_TOKEN not found — skipping notify"; return 0; }

    echo "$message" | MATRIX_TOKEN="$token" MATRIX_ROOM="$MATRIX_ROOM_INFRA_NL" python3 -c '
import sys, urllib.request, urllib.parse, json, ssl, os, time
msg = sys.stdin.read().strip()
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
room = os.environ["MATRIX_ROOM"]; token = os.environ["MATRIX_TOKEN"]
txn = f"ont-drill-{int(time.time())}-{os.getpid()}"
url = f"https://matrix.example.net/_matrix/client/v3/rooms/{urllib.parse.quote(room, safe=\"\")}/send/m.room.message/{txn}"
body = json.dumps({"msgtype": "m.notice", "body": msg, "format": "org.matrix.custom.html", "formatted_body": msg.replace("\n","<br>")}).encode()
req = urllib.request.Request(url, data=body, method="PUT")
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type", "application/json")
try:
    urllib.request.urlopen(req, context=ctx, timeout=10)
    print("notice posted")
except Exception as e:
    print(f"matrix error: {e}", file=sys.stderr)
' 2>&1 | tee -a "$LOG"
}

log "=== Freedom-ONT drill trigger fired ==="

# Preflight gate (IFRNLLEI01PRD-708) — runs BEFORE both the primitive and
# fallback branches so every dispatch path is protected. Prevents collision
# with any other chaos drill that already owns ~/chaos-state/chaos-active.json,
# and bails on maintenance mode, rate-limit, or shun-table entries.
PREFLIGHT="$REPO_DIR/scripts/chaos-preflight.sh"
if [ -x "$PREFLIGHT" ] && ! bash "$PREFLIGHT" >> "$LOG" 2>&1; then
    log "ABORT: chaos-preflight.sh returned NOT READY — refusing to dispatch drill"
    notify_matrix "[CHAOS DRILL] Freedom-ONT drill ABORTED — preflight NOT READY. Inspect $LOG for the blocking check (most likely a concurrent chaos test holds ~/chaos-state/chaos-active.json)."
    # Self-remove the one-shot cron entry — operator must re-install once clear.
    (crontab -l 2>/dev/null | grep -v "freedom-ont-drill-trigger.sh") | crontab -
    log "one-shot cron entry removed after ABORT — operator must re-install"
    exit 0
fi

# 2026-04-22 [IFRNLLEI01PRD-705]: if the ios-port-shutdown primitive is
# available, dispatch the autonomous drill instead of just posting a
# Matrix reminder. The autonomous runner installs its own chaos-active
# marker + sends its own Matrix notices + writes the chaos_experiments
# row on completion. No operator action required.
PRIMITIVE="$REPO_DIR/scripts/chaos-port-shutdown.py"
if [ -x "$PRIMITIVE" ]; then
    log "dispatching autonomous drill via $PRIMITIVE"
    # 15-min observation, 30-min hard cap via watchdog inside the script.
    # Detach so cron can exit cleanly — the drill itself runs ~20-30 min.
    nohup python3 "$PRIMITIVE" \
        --scenario freedom-ont-shutdown \
        >> "$LOG" 2>&1 &
    log "background PID=$! — cron trigger exiting; drill runs to completion asynchronously"
    # Self-remove the cron entry (one-shot cleanup) and exit
    (crontab -l 2>/dev/null | grep -v "freedom-ont-drill-trigger.sh") | crontab -
    log "one-shot cron entry removed — drill continuing in background"
    exit 0
fi

# Fallback path — primitive not installed: post operator-nudge notice
# (same as pre-705 behaviour; kept so this script remains useful if the
# primitive is ever removed or disabled).
log "primitive not found at $PRIMITIVE — falling back to Matrix operator nudge"

# ── Install chaos-active suppression marker (90 min) ────────────────────────
cat > "$CHAOS_ACTIVE_FILE" <<JSON
{
  "scenario": "freedom-ont-shutdown",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "expires_at": "$(date -u -d '+90 min' +%Y-%m-%dT%H:%M:%SZ)",
  "triggered_by": "scheduled-drill",
  "operator_action_required": true,
  "referenced_in": "IFRNLLEI01PRD-695",
  "suppressions": [
    "freedom-qos-toggle-sms",
    "pppoe-down-alerts",
    "vti-idle-bgp-alerts",
    "mesh-degraded-level-alert"
  ]
}
JSON
log "chaos-active marker installed (90 min window): $CHAOS_ACTIVE_FILE"

# ── Post the Matrix notice ──────────────────────────────────────────────────
notify_matrix "[CHAOS DRILL] Monthly Freedom-ONT failover drill — NOW.

Scenario: freedom-ont-shutdown (IFRNLLEI01PRD-695)
Chaos-active window: 90 min from $(date -u +%H:%M)Z

STEP 1 — Shut the ONT port (operator):
  ssh operator@nl-sw01
  conf t
   interface GigabitEthernet1/0/36
    shutdown
   end

STEP 2 — Observe (automatic):
  - ASA outside_freedom will lose PPPoE within ~10s
  - SLA track 1 goes down, default route flips to outside_budget
  - Budget VTIs carry inter-site BGP
  - Tenant Internet restored via rtr01 Dialer1 within ~60-90s
  - mesh-stats banner flips to: Degraded (Freedom down, Budget holding)

STEP 3 — Restore (after 15-30 min):
  conf t
   interface Gi1/0/36
    power inline never
    power inline auto
    shutdown
    no shutdown
   end

  (The power-cycle pattern forces a clean ONT PoE re-detect.
  See memory feedback freedom_ont_poe_recycle_gotcha_20260422.md
  and docs/failover-simulation-freedom-ont-20260422.md §15.)

STEP 4 — Post-drill:
  Write a chaos_experiments row (Claude will do this on request).
  SLO: max 120s convergence on recovery. Today's baseline was
  exactly 120s — beat it or match it."

log "=== drill trigger complete ==="

# ── Self-remove the cron entry (one-shot) ────────────────────────────────────
# Remove the line that invokes THIS script so it doesn't re-fire if the
# next scheduled time window rolls around.
(crontab -l 2>/dev/null | grep -v "freedom-ont-drill-trigger.sh") | crontab -
log "one-shot cron entry removed"
