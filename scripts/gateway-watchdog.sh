#!/bin/bash
# gateway-watchdog.sh — Monitors gateway workflows, auto-heals, alerts on state change
# Runs as cron every 5 minutes on nl-claude01 as app-user
set -euo pipefail

# --- Configuration ---
ENV_FILE="/app/claude-gateway/.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

STATE_DIR="/home/app-user/scripts/watchdog-state"
N8N_URL="https://n8n.example.net"
N8N_API_KEY=$(jq -r '.mcpServers["n8n-mcp"].env.N8N_API_KEY' /home/app-user/.claude.json 2>/dev/null || echo "")
ALERTS_ROOM="${MATRIX_ROOM_ALERTS:-!xeNxtpScJWCmaFjeCL:matrix.example.net}"
MATRIX_URL="${MATRIX_HOMESERVER:-https://matrix.example.net}"
BOT_TOKEN="${MATRIX_CLAUDE_TOKEN:-}"
BOUNCE_INTERVAL=21600  # 6 hours

# Workflow IDs
declare -A WORKFLOWS=(
  [youtrack-receiver]="e3e2SFPKc1DLsisi"
  [app-user]="qadF2WcaBsIR7SWG"
  [progress-poller]="uRRkYbRfWuPXrv3b"
  [matrix-bridge]="QGKnHGkw4casiWIU"
  [session-end]="rgRGPOZgPcFCvv84"
  [librenms-receiver]="Ids38SbH48q4JdLN"
  [prometheus-receiver]="CqrN7hNiJsATcJGE"
  [librenms-receiver-gr]="HI9UkcxNDxx6MEFD"
  [prometheus-receiver-gr]="bdAYIiLh5vVyMDW7"
)
ZOMBIE_MAX_AGE=3600  # Kill queued executions older than 1 hour

mkdir -p "$STATE_DIR"

# --- Utility functions ---
log_msg() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

post_alert() {
  local msg="$1"
  local txn_id="watchdog-$(date +%s%N)-$$"
  if [ -n "$BOT_TOKEN" ]; then
    curl -sf --max-time 10 -X PUT \
      -H "Authorization: Bearer $BOT_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg m "$msg" '{msgtype:"m.notice",body:$m}')" \
      "$MATRIX_URL/_matrix/client/v3/rooms/$ALERTS_ROOM/send/m.room.message/$txn_id" \
      >/dev/null 2>&1 || true
  fi
}

# Returns 0 (true) if state changed. Prevents alert spam.
state_changed() {
  local key="$1" new_val="$2"
  local file="$STATE_DIR/state_$key"
  local old_val=""
  [ -f "$file" ] && old_val=$(cat "$file")
  if [ "$old_val" != "$new_val" ]; then
    echo "$new_val" > "$file"
    return 0
  fi
  return 1
}

# --- Layer 0: n8n Health ---
check_n8n_health() {
  if curl -sf --max-time 10 "$N8N_URL/healthz" >/dev/null 2>&1; then
    if state_changed "n8n_health" "ok"; then
      post_alert "[WATCHDOG] n8n recovered and is healthy"
      log_msg "n8n recovered"
    fi
    return 0
  fi

  log_msg "n8n health check FAILED"

  # Restart backoff: 15 minutes
  local restart_ts_file="$STATE_DIR/n8n_restart_ts"
  if [ -f "$restart_ts_file" ]; then
    local last_restart
    last_restart=$(cat "$restart_ts_file")
    local now
    now=$(date +%s)
    if (( now - last_restart < 900 )); then
      if state_changed "n8n_health" "down_backoff"; then
        post_alert "[WATCHDOG] n8n is DOWN. Restart attempted <15min ago, backing off."
      fi
      log_msg "n8n down, restart backoff active"
      return 1
    fi
  fi

  log_msg "Restarting n8n via PVE..."
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes \
    nl-pve01 "pct exec VMID_REDACTED -- systemctl restart n8n" 2>/dev/null || true
  date +%s > "$restart_ts_file"

  sleep 30

  if curl -sf --max-time 10 "$N8N_URL/healthz" >/dev/null 2>&1; then
    if state_changed "n8n_health" "ok"; then
      post_alert "[WATCHDOG] n8n was DOWN, restarted successfully"
    fi
    log_msg "n8n restarted successfully"
    return 0
  else
    if state_changed "n8n_health" "down"; then
      post_alert "[WATCHDOG] n8n is DOWN. Restart failed. Manual intervention needed."
    fi
    log_msg "n8n restart FAILED"
    return 1
  fi
}

# --- Layer 1: Workflow activation status ---
check_workflow_active() {
  local name="$1" wf_id="$2"
  local response
  response=$(curl -sf --max-time 10 \
    -H "X-N8N-API-KEY: $N8N_API_KEY" \
    "$N8N_URL/api/v1/workflows/$wf_id" 2>/dev/null) || true

  if [ -z "$response" ]; then
    if state_changed "wf_${name}" "unreachable"; then
      post_alert "[WATCHDOG] Cannot query workflow '$name' ($wf_id)"
    fi
    return 1
  fi

  local active
  active=$(echo "$response" | jq -r '.active')

  if [ "$active" = "true" ]; then
    if state_changed "wf_${name}" "active"; then
      post_alert "[WATCHDOG] Workflow '$name' is active again"
    fi
    return 0
  else
    log_msg "Workflow '$name' is INACTIVE, reactivating..."
    curl -sf --max-time 10 -X POST \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      "$N8N_URL/api/v1/workflows/$wf_id/activate" >/dev/null 2>&1 || true

    if state_changed "wf_${name}" "reactivated"; then
      post_alert "[WATCHDOG] Workflow '$name' was INACTIVE. Reactivated."
    fi
    log_msg "Reactivated '$name'"
    return 0
  fi
}

# --- Layer 2: Proactive Bridge bounce (every 6h) ---
check_bridge_bounce() {
  local bridge_id="${WORKFLOWS[matrix-bridge]}"
  local bounce_ts_file="$STATE_DIR/bridge_bounce_ts"
  local now
  now=$(date +%s)

  local last_bounce=0
  [ -f "$bounce_ts_file" ] && last_bounce=$(cat "$bounce_ts_file")

  if (( now - last_bounce >= BOUNCE_INTERVAL )); then
    log_msg "Proactive Bridge bounce (every 6h)..."

    curl -sf --max-time 10 -X POST \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      "$N8N_URL/api/v1/workflows/$bridge_id/deactivate" >/dev/null 2>&1 || true

    sleep 5

    curl -sf --max-time 10 -X POST \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      "$N8N_URL/api/v1/workflows/$bridge_id/activate" >/dev/null 2>&1 || true

    echo "$now" > "$bounce_ts_file"
    log_msg "Bridge bounced successfully"
    post_alert "[WATCHDOG] Proactive Bridge bounce completed (scheduled every 6h)"
  fi
}

# --- Layer 3: Bridge error detection ---
check_bridge_errors() {
  local bridge_id="${WORKFLOWS[matrix-bridge]}"
  local response
  response=$(curl -sf --max-time 10 \
    -H "X-N8N-API-KEY: $N8N_API_KEY" \
    "$N8N_URL/api/v1/executions?workflowId=$bridge_id&limit=5&status=error" 2>/dev/null) || true

  [ -z "$response" ] && return

  local error_count
  error_count=$(echo "$response" | jq '.data | length' 2>/dev/null || echo 0)

  if [ "$error_count" -gt 0 ]; then
    local latest_error_time
    latest_error_time=$(echo "$response" | jq -r '.data[0].startedAt' 2>/dev/null || echo "")
    [ -z "$latest_error_time" ] && return

    local latest_error_ts
    latest_error_ts=$(date -d "$latest_error_time" +%s 2>/dev/null || echo 0)
    local now
    now=$(date +%s)
    local age=$(( now - latest_error_ts ))

    # If error within last 10 minutes, bounce reactively
    if (( age < 600 )); then
      if state_changed "bridge_errors" "error_$latest_error_ts"; then
        log_msg "Bridge has recent error ($((age/60))m ago), bouncing..."
        post_alert "[WATCHDOG] Bridge error detected ($((age/60))m ago). Bouncing..."

        curl -sf --max-time 10 -X POST \
          -H "X-N8N-API-KEY: $N8N_API_KEY" \
          "$N8N_URL/api/v1/workflows/$bridge_id/deactivate" >/dev/null 2>&1 || true
        sleep 5
        curl -sf --max-time 10 -X POST \
          -H "X-N8N-API-KEY: $N8N_API_KEY" \
          "$N8N_URL/api/v1/workflows/$bridge_id/activate" >/dev/null 2>&1 || true

        echo "$(date +%s)" > "$STATE_DIR/bridge_bounce_ts"
        log_msg "Bridge bounced after error"
      fi
    fi
  fi
}

# --- Layer 4: Kill zombie executions ---
cleanup_zombie_executions() {
  local now
  now=$(date +%s)
  local killed=0

  # Query executions with status=running (catches "Queued" zombies too)
  for status_filter in "running" "waiting"; do
    local response
    response=$(curl -sf --max-time 10 \
      -H "X-N8N-API-KEY: $N8N_API_KEY" \
      "$N8N_URL/api/v1/executions?status=$status_filter&limit=50" 2>/dev/null) || continue

    local exec_ids
    exec_ids=$(echo "$response" | jq -r '.data[] | select(.startedAt != null) | "\(.id)|\(.startedAt)|\(.workflowId)"' 2>/dev/null) || continue

    while IFS='|' read -r exec_id started_at wf_id; do
      [ -z "$exec_id" ] && continue
      local started_ts
      started_ts=$(date -d "$started_at" +%s 2>/dev/null || echo 0)
      local age=$(( now - started_ts ))

      if (( age > ZOMBIE_MAX_AGE )); then
        log_msg "Killing zombie execution $exec_id (workflow: $wf_id, age: $((age/3600))h$((age%3600/60))m)"
        curl -sf --max-time 10 -X DELETE \
          -H "X-N8N-API-KEY: $N8N_API_KEY" \
          "$N8N_URL/api/v1/executions/$exec_id" >/dev/null 2>&1 || true
        killed=$((killed + 1))
      fi
    done <<< "$exec_ids"
  done

  if [ "$killed" -gt 0 ]; then
    post_alert "[WATCHDOG] Cleaned up $killed zombie execution(s) (queued >1h)"
    log_msg "Cleaned $killed zombie executions"
  fi
}

# --- Layer 5: Stale per-slot lock detection ---
check_stale_locks() {
  local gw_dir="/app/cubeos/claude-context"
  local now
  now=$(date +%s)

  for slot in dev infra-nl infra-gr; do
    local lock_file="$gw_dir/gateway.lock.$slot"
    [ -f "$lock_file" ] || continue

    local lock_age=$(( now - $(stat -c %Y "$lock_file") ))
    if (( lock_age > 600 )); then
      local lock_content
      lock_content=$(cat "$lock_file" 2>/dev/null || echo "unknown")
      log_msg "Stale lock detected: $slot ($lock_content, age: $((lock_age/60))m)"
      rm -f "$lock_file"
      if state_changed "stale_lock_$slot" "cleaned_$now"; then
        post_alert "[WATCHDOG] Stale lock cleaned: slot=$slot, issue=$lock_content (age: $((lock_age/60))m)"
      fi
    fi
  done

  # Also clean up any legacy gateway.lock file
  local legacy_lock="$gw_dir/gateway.lock"
  if [ -f "$legacy_lock" ]; then
    local legacy_age=$(( now - $(stat -c %Y "$legacy_lock") ))
    log_msg "Legacy gateway.lock found (age: $((legacy_age/60))m), removing"
    rm -f "$legacy_lock"
    post_alert "[WATCHDOG] Removed legacy gateway.lock file (migrated to per-slot locks)"
  fi
}

# --- Main ---
main() {
  log_msg "=== Watchdog run start ==="

  # Layer 0: n8n health (if down, skip everything else)
  if ! check_n8n_health; then
    log_msg "n8n is down, skipping workflow checks"
    log_msg "=== Watchdog run complete ==="
    return
  fi

  # Layer 1: All workflows active
  for name in "${!WORKFLOWS[@]}"; do
    check_workflow_active "$name" "${WORKFLOWS[$name]}"
  done

  # Layer 2: Proactive Bridge bounce (every 6h)
  check_bridge_bounce

  # Layer 3: Bridge error detection
  check_bridge_errors

  # Layer 4: Kill zombie executions (queued/running for >1h)
  cleanup_zombie_executions

  # Layer 5: Stale per-slot lock detection
  check_stale_locks

  # Log rotation (keep last 500 lines)
  local log_file="$STATE_DIR/watchdog.log"
  if [ -f "$log_file" ] && [ "$(wc -l < "$log_file")" -gt 1000 ]; then
    tail -500 "$log_file" > "${log_file}.tmp" && mv "${log_file}.tmp" "$log_file"
  fi

  log_msg "=== Watchdog run complete ==="
}

main
