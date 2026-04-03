#!/bin/bash
# asa-reboot-watch.sh — Predictive ASA reboot maintenance window manager
# Runs via cron every 5 minutes. Checks ASA uptimes, predicts reboot,
# activates/deactivates maintenance suppression across all 4 layers.
#
# Usage:
#   asa-reboot-watch.sh              — normal operation (cron)
#   asa-reboot-watch.sh --dry-run    — show predictions without acting
#   asa-reboot-watch.sh --status     — show current state
#
# Both ASAs use EEM watchdog timers:
#   nl-fw01: event timer watchdog time 604800  (7 days)
#   gr-fw01: event timer watchdog time 590400  (6d 20h)

set -uo pipefail

REPO_DIR="/app/claude-gateway"
SCRIPT_DIR="$REPO_DIR/scripts"
ENV_FILE="$REPO_DIR/.env"
MAINT_FILE="/home/app-user/gateway.maintenance"
MAINT_ENDED_FILE="/home/app-user/gateway.maintenance-ended"
STATE_DIR="/home/app-user/scripts/maintenance-state"
LOG_TAG="[asa-reboot-watch]"
DRY_RUN=false

# Parse args
case "${1:-}" in
  --dry-run) DRY_RUN=true ;;
  --status)
    echo "$LOG_TAG Status at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ -f "$MAINT_FILE" ]; then
      echo "  gateway.maintenance: ACTIVE"
      cat "$MAINT_FILE" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  Event: {d.get(\"event_id\",\"?\")}  Reason: {d.get(\"reason\",\"?\")}')" 2>/dev/null
    else
      echo "  gateway.maintenance: inactive"
    fi
    if [ -f "$MAINT_ENDED_FILE" ]; then
      ended=$(cat "$MAINT_ENDED_FILE")
      now=$(date +%s)
      elapsed=$(( now - ended ))
      if [ "$elapsed" -lt 900 ]; then
        echo "  Cooldown: active ($(( (900 - elapsed) / 60 ))min remaining)"
      else
        echo "  Cooldown: expired"
      fi
    fi
    for sf in "$STATE_DIR"/asa-reboot-*.state; do
      [ -f "$sf" ] && echo "  State file: $(basename "$sf") = $(cat "$sf")"
    done 2>/dev/null
    exit 0
    ;;
esac

# Load env
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

mkdir -p "$STATE_DIR"

# --- ASA Configuration ---
declare -A ASA_WATCHDOG=(
  [nl-fw01]=604800
  [gr-fw01]=590400
)
declare -A ASA_SITE=(
  [nl-fw01]=nl
  [gr-fw01]=gr
)

# Thresholds (seconds)
PRE_REBOOT_WINDOW=600      # Activate maintenance 10 min before expected reboot
POST_REBOOT_DETECT=900     # ASA uptime < 15 min = just rebooted
MAINT_WINDOW_DURATION=20   # LibreNMS maintenance duration (minutes)

# Matrix config
MATRIX_URL="${MATRIX_HOMESERVER:-https://matrix.example.net}"
BOT_TOKEN="${MATRIX_CLAUDE_TOKEN:-}"
NL_ROOM="!AOMuEtXGyzGFLgObKN:matrix.example.net"
GR_ROOM="!NKosBPujbWMevzHaaM:matrix.example.net"

# LibreNMS config
NL_LIBRENMS_URL="${LIBRENMS_URL:-https://nl-nms01.example.net}"
NL_LIBRENMS_TOKEN="${LIBRENMS_API_KEY:-}"
GR_LIBRENMS_URL="${LIBRENMS_GR_URL:-https://gr-nms01.example.net}"
GR_LIBRENMS_TOKEN="${LIBRENMS_GR_API_KEY:-}"

# --- Utility Functions ---

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $LOG_TAG $1"; }

post_matrix() {
  local msg="$1" room="$2"
  [ -z "$BOT_TOKEN" ] && return 0
  local txn="asa-watch-$(date +%s%N)-$$"
  curl -sf --max-time 10 -X PUT \
    -H "Authorization: Bearer $BOT_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg m "$msg" '{msgtype:"m.notice",body:$m}')" \
    "$MATRIX_URL/_matrix/client/v3/rooms/$room/send/m.room.message/$txn" \
    >/dev/null 2>&1 || true
}

# Get ASA uptime in seconds. Returns empty string on failure.
get_asa_uptime_seconds() {
  local device="$1"
  local uptime_str=""

  if [ "$device" = "nl-fw01" ]; then
    # NL ASA: direct via Netmiko
    uptime_str=$(CISCO_PASSWORD="${CISCO_ASA_PASSWORD:?CISCO_ASA_PASSWORD env var not set}" python3 /home/app-user/scripts/network-check.py \
      nl-fw01 "show version | include up" 2>/dev/null | grep -i "up " | head -1)
  elif [ "$device" = "gr-fw01" ]; then
    # GR ASA: step through gr-pve01 via expect
    uptime_str=$(ssh -i ~/.ssh/one_key -o ConnectTimeout=10 -o StrictHostKeyChecking=no root@gr-pve01 'expect -c "
      log_user 0
      spawn ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o StrictHostKeyChecking=no -o ConnectTimeout=10 operator@10.0.X.X
      expect \"assword:\"
      send \"${CISCO_ASA_PASSWORD:?}\r\"
      expect \">\"
      send \"enable\r\"
      expect \"assword:\"
      send \"${CISCO_ASA_PASSWORD:?}\r\"
      expect \"#\"
      log_user 1
      send \"show version | include up\r\"
      expect \"#\"
      log_user 0
      send \"exit\r\"
      expect eof
    "' 2>/dev/null | grep -i "up " | grep -v "^show " | head -1)
  fi

  [ -z "$uptime_str" ] && return 1

  # Parse uptime string: "gr-fw01 up 1 day 13 hours" or "nl-fw01 up 2 hours 30 mins"
  python3 -c "
import re, sys
s = '''$uptime_str'''
total = 0
for m in re.finditer(r'(\d+)\s+(day|hour|min|sec)', s, re.IGNORECASE):
    val = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith('day'): total += val * 86400
    elif unit.startswith('hour'): total += val * 3600
    elif unit.startswith('min'): total += val * 60
    elif unit.startswith('sec'): total += val
if total > 0:
    print(total)
else:
    sys.exit(1)
" 2>/dev/null
}

# Set LibreNMS maintenance on all devices for a site
set_librenms_maintenance() {
  local site="$1"
  local api_url token

  if [ "$site" = "nl" ]; then
    api_url="$NL_LIBRENMS_URL/api/v0"
    token="$NL_LIBRENMS_TOKEN"
  else
    api_url="$GR_LIBRENMS_URL/api/v0"
    token="$GR_LIBRENMS_TOKEN"
  fi

  [ -z "$token" ] && { log "WARN: No LibreNMS token for site=$site"; return 1; }

  # Get all device hostnames
  local devices
  devices=$(curl -sk --max-time 15 -H "X-Auth-Token: $token" \
    "$api_url/devices?type=all" 2>/dev/null | \
    python3 -c "import json,sys; [print(d['hostname']) for d in json.load(sys.stdin).get('devices',[])]" 2>/dev/null)

  [ -z "$devices" ] && { log "WARN: Could not list devices for site=$site"; return 1; }

  local count=0
  while IFS= read -r hostname; do
    [ -z "$hostname" ] && continue
    curl -sk --max-time 10 -X POST \
      -H "X-Auth-Token: $token" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"ASA weekly reboot\",\"duration\":\"0:${MAINT_WINDOW_DURATION}\",\"notes\":\"Automated: EEM watchdog timer reboot\"}" \
      "$api_url/devices/$hostname/maintenance/" >/dev/null 2>&1 && ((count++))
  done <<< "$devices"

  log "Set LibreNMS maintenance on $count devices (site=$site, duration=${MAINT_WINDOW_DURATION}min)"
}

# --- Main Logic ---

activate_maintenance() {
  local event_id="$1" device="$2" site="$3" time_to_reboot="$4"

  if $DRY_RUN; then
    log "DRY-RUN: Would activate maintenance for $device (event=$event_id, TTR=${time_to_reboot}s)"
    return 0
  fi

  # Don't re-activate if already active for this event
  if [ -f "$MAINT_FILE" ]; then
    existing_event=$(python3 -c "import json; print(json.load(open('$MAINT_FILE')).get('event_id',''))" 2>/dev/null)
    if [ "$existing_event" = "$event_id" ]; then
      log "Maintenance already active for $event_id, skipping"
      return 0
    fi
  fi

  log "ACTIVATING maintenance for $device (event=$event_id, TTR=${time_to_reboot}s)"

  # Layer 2: Create gateway.maintenance file
  cat > "$MAINT_FILE" << EOF
{
  "reason": "Scheduled ASA reboot ($device) — EEM watchdog timer",
  "event_id": "$event_id",
  "device": "$device",
  "site": "$site",
  "started_by": "asa-reboot-watch",
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "expected_duration_min": $MAINT_WINDOW_DURATION
}
EOF

  # Layer 1: Set LibreNMS maintenance on affected site(s)
  set_librenms_maintenance "$site"
  # If NL ASA reboots, GR VPN also drops
  if [ "$site" = "nl" ]; then
    set_librenms_maintenance "gr"
  fi

  # Save state for deactivation tracking
  echo "active:$(date +%s):$event_id" > "$STATE_DIR/asa-reboot-${device}.state"

  # Post Matrix notice
  local room="$NL_ROOM"
  [ "$site" = "gr" ] && room="$GR_ROOM"
  post_matrix "🔧 [ASA Reboot Watch] Maintenance mode activated — $device EEM watchdog reboot expected in ~$((time_to_reboot / 60))min. All alerts will be suppressed for ${MAINT_WINDOW_DURATION}min." "$room"
  # Also notify NL room if GR ASA affects VPN
  if [ "$site" = "gr" ]; then
    post_matrix "🔧 [ASA Reboot Watch] GR ASA ($device) reboot expected in ~$((time_to_reboot / 60))min — IPsec VPN may drop briefly." "$NL_ROOM"
  fi
}

deactivate_maintenance() {
  local event_id="$1" device="$2" site="$3" uptime="$4"

  if $DRY_RUN; then
    log "DRY-RUN: Would deactivate maintenance for $device (event=$event_id, uptime=${uptime}s)"
    return 0
  fi

  # Only deactivate if currently active for this event
  if [ -f "$MAINT_FILE" ]; then
    existing_event=$(python3 -c "import json; print(json.load(open('$MAINT_FILE')).get('event_id',''))" 2>/dev/null)
    if [ "$existing_event" != "$event_id" ]; then
      return 0
    fi
  else
    return 0
  fi

  log "DEACTIVATING maintenance for $device (event=$event_id, uptime=${uptime}s post-reboot)"

  # Layer 2: Remove gateway.maintenance, set cooldown
  rm -f "$MAINT_FILE"
  date +%s > "$MAINT_ENDED_FILE"

  # Update state
  echo "recovered:$(date +%s):$event_id" > "$STATE_DIR/asa-reboot-${device}.state"

  # Post Matrix notice
  local room="$NL_ROOM"
  [ "$site" = "gr" ] && room="$GR_ROOM"
  post_matrix "✅ [ASA Reboot Watch] $device back up (uptime: $((uptime / 60))min). Maintenance mode deactivated. 15min cooldown active." "$room"
  if [ "$site" = "nl" ] || [ "$site" = "gr" ]; then
    # Notify the other room about VPN recovery
    local other_room="$GR_ROOM"
    [ "$site" = "gr" ] && other_room="$NL_ROOM"
    post_matrix "✅ [ASA Reboot Watch] $device recovered — VPN tunnel should re-establish shortly." "$other_room"
  fi
}

# --- Process Each ASA ---

log "Starting check"

for device in "${!ASA_WATCHDOG[@]}"; do
  watchdog=${ASA_WATCHDOG[$device]}
  site=${ASA_SITE[$device]}
  event_id="${site}-asa-weekly-reboot"

  # Get current uptime
  uptime_sec=$(get_asa_uptime_seconds "$device" 2>/dev/null) || {
    log "WARN: Could not get uptime for $device (SSH failed or device unreachable)"
    # If device is unreachable and maintenance is active for this event, it might be rebooting now
    if [ -f "$MAINT_FILE" ]; then
      existing_event=$(python3 -c "import json; print(json.load(open('$MAINT_FILE')).get('event_id',''))" 2>/dev/null)
      if [ "$existing_event" = "$event_id" ]; then
        log "  Device unreachable during active maintenance — reboot likely in progress"
      fi
    fi
    continue
  }

  time_to_reboot=$(( watchdog - uptime_sec ))
  uptime_human=$(python3 -c "
s=$uptime_sec
d,r=divmod(s,86400); h,r=divmod(r,3600); m,_=divmod(r,60)
parts=[]
if d: parts.append(f'{d}d')
if h: parts.append(f'{h}h')
if m: parts.append(f'{m}m')
print(' '.join(parts) or '0m')
" 2>/dev/null)

  ttr_human=$(python3 -c "
s=$time_to_reboot
if s < 0: s = 0
d,r=divmod(s,86400); h,r=divmod(r,3600); m,_=divmod(r,60)
parts=[]
if d: parts.append(f'{d}d')
if h: parts.append(f'{h}h')
if m: parts.append(f'{m}m')
print(' '.join(parts) or '<1m')
" 2>/dev/null)

  if $DRY_RUN; then
    log "  $device: uptime=$uptime_human, watchdog=${watchdog}s, TTR=$ttr_human ($time_to_reboot s)"
  fi

  # Decision logic
  if [ "$time_to_reboot" -le "$PRE_REBOOT_WINDOW" ] && [ "$time_to_reboot" -gt 0 ]; then
    # Reboot imminent — activate maintenance
    activate_maintenance "$event_id" "$device" "$site" "$time_to_reboot"

  elif [ "$uptime_sec" -lt "$POST_REBOOT_DETECT" ]; then
    # ASA just rebooted (uptime < 15 min) — check if we should deactivate
    deactivate_maintenance "$event_id" "$device" "$site" "$uptime_sec"

    # Post-reboot VPN tunnel validation (added 2026-04-03 — stale SA incident)
    # Run in background to not block the 5min cron cycle
    VPN_CHECK="$SCRIPT_DIR/post-reboot-vpn-check.sh"
    VPN_STATE_FILE="$STATE_DIR/vpn-check-${device}.running"
    if [ -x "$VPN_CHECK" ] && [ ! -f "$VPN_STATE_FILE" ]; then
      log "Launching post-reboot VPN check for $device in background..."
      touch "$VPN_STATE_FILE"
      $DRY_RUN && DRY_FLAG="--dry-run" || DRY_FLAG=""
      (
        "$VPN_CHECK" "$device" "$site" $DRY_FLAG >> "$STATE_DIR/vpn-check-${device}.log" 2>&1
        rm -f "$VPN_STATE_FILE"
      ) &
    elif [ -f "$VPN_STATE_FILE" ]; then
      log "VPN check already running for $device — skipping"
    fi

  else
    # Normal operation — no action needed
    if $DRY_RUN; then
      log "  $device: normal operation (next reboot in $ttr_human)"
    fi
  fi
done

log "Check complete"
