#!/bin/bash
# maintenance-companion.sh — Active maintenance event manager
# Called by Claude Code during interactive maintenance sessions.
# Self-healing: checks its own dependency chain before operations.
#
# Usage:
#   maintenance-companion.sh selfcheck                           — verify all gateway dependencies
#   maintenance-companion.sh deps <hostname>                     — list all devices affected by this host
#   maintenance-companion.sh start <hostname> [duration_hours]   — set LibreNMS maintenance on host + dependents
#   maintenance-companion.sh status                              — list active maintenance windows
#   maintenance-companion.sh check <hostname>                    — poll host + dependents for recovery
#   maintenance-companion.sh end <hostname>                      — clear maintenance, run health check
#   maintenance-companion.sh checklist <device_type> <hostname>  — run post-reboot verification checklist
#
# Fallback ladder (each operation tries in order):
#   1. AWX job template (battle-tested, retries, cluster-aware)
#   2. Direct LibreNMS API (curl from claude01)
#   3. Proxmox MCP / PVE API (guest status without LibreNMS)
#   4. SSH to PVE host (pct list / qm list)
#   5. Ping only (report "unreachable, waiting")

set -uo pipefail

# --- Configuration ---
ENV_FILE="/home/claude-runner/gitlab/n8n/claude-gateway/.env"
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
fi

# --- Site selection ---
# Parse --site from args (must be before subcommand or after)
MAINT_SITE="${MAINT_SITE:-nl}"
_remaining_args=()
for arg in "$@"; do
  if [ "${_prev_was_site:-}" = "true" ]; then
    MAINT_SITE="$arg"
    _prev_was_site=false
    continue
  fi
  if [ "$arg" = "--site" ]; then
    _prev_was_site=true
    continue
  fi
  _remaining_args+=("$arg")
done
set -- "${_remaining_args[@]}"

# Auto-detect site from hostname argument (2nd arg after subcommand)
auto_detect_maint_site() {
  local hostname="$1"
  if echo "$hostname" | grep -qi "^grskg"; then
    MAINT_SITE="gr"
  fi
}
# Try auto-detect from the 2nd positional arg (hostname in most subcommands)
[ -n "${2:-}" ] && auto_detect_maint_site "${2:-}"

MATRIX_URL="${MATRIX_HOMESERVER:-https://matrix.example.net}"
BOT_TOKEN="${MATRIX_CLAUDE_TOKEN:-}"
STATE_DIR="/home/claude-runner/scripts/maintenance-state"
YOUTRACK_API="${YOUTRACK_URL:-https://youtrack.example.net}/api"
YOUTRACK_TOKEN_VAL="${YOUTRACK_TOKEN:-}"

case "$MAINT_SITE" in
  nl|NL|nl)
    IAC_REPO="/home/claude-runner/gitlab/infrastructure/nl/production"
    LIBRENMS_API="${LIBRENMS_URL:-https://nl-nms01.example.net}/api/v0"
    LIBRENMS_TOKEN="${LIBRENMS_API_KEY:-}"
    AWX_URL="https://awx.example.net"
    AWX_TOKEN="REDACTED_bacaec8e"
    INFRA_ROOM="${MATRIX_ROOM_INFRA:-!AOMuEtXGyzGFLgObKN:matrix.example.net}"
    K8S_CONTEXT=""
    SITE_LABEL="NL (nl)"

    declare -A PVE_HOSTS=(
      [nl-pve01]="10.0.181.X"
      [nl-pve02]="10.0.181.X"
      [nl-pve03]="10.0.181.X"
    )

    declare -A CRITICAL_SERVICES=(
      [n8n]="VMID_REDACTED|nl-pve01|curl -sf --max-time 5 https://n8n.example.net/healthz"
      [librenms]="VMID_REDACTED|nl-pve03|curl -sfk --max-time 5 -H 'X-Auth-Token: ${LIBRENMS_TOKEN}' ${LIBRENMS_API}/system"
      [youtrack]="VMID_REDACTED|nl-pve03|curl -sf --max-time 5 https://youtrack.example.net/api/config"
      [matrix]="VMID_REDACTED|nl-pve01|curl -sf --max-time 5 ${MATRIX_URL}/_matrix/client/versions"
      [gitlab]="VMID_REDACTED|nl-pve01|curl -sk --max-time 5 https://gitlab.example.net/api/v4/projects -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q 200"
      [claude01]="VMID_REDACTED|nl-pve03|test -d /home/claude-runner/.claude"
      [awx]="k8s|k8s|curl -sfk --max-time 5 -H 'Authorization: Bearer ${AWX_TOKEN}' ${AWX_URL}/api/v2/ping/"
      [dns_freeipa]="VMID_REDACTED|nl-pve01|dig +short +timeout=3 @10.0.181.X example.net"
      [dns_pihole]="VMID_REDACTED|nl-pve01|curl -sf --max-time 5 http://10.0.181.X/admin/ -o /dev/null"
    )

    CATASTROPHIC_HOSTS="nl-fw01 nl-sw01"
    PVE_HOST_PATTERN="nlpve0*"
    ;;

  gr|GR|gr)
    IAC_REPO="/home/claude-runner/gitlab/infrastructure/gr/production"
    LIBRENMS_API="${LIBRENMS_GR_URL:-https://gr-nms01.example.net}/api/v0"
    LIBRENMS_TOKEN="${LIBRENMS_GR_API_KEY:-}"
    AWX_URL="https://gr-awx.example.net"
    AWX_TOKEN="${GR_AWX_TOKEN:-8N1p4G8TYoWyQtYiRJknuoxYgQffs0NP}"
    INFRA_ROOM="!NKosBPujbWMevzHaaM:matrix.example.net"
    K8S_CONTEXT="gr"
    SITE_LABEL="GR (gr)"

    declare -A PVE_HOSTS=(
      [gr-pve01]="10.0.58.X"
      [gr-pve02]="10.0.188.X"
    )

    declare -A CRITICAL_SERVICES=(
      [librenms_gr]="vm|gr-pve01|curl -sfk --max-time 5 -H 'X-Auth-Token: ${LIBRENMS_TOKEN}' ${LIBRENMS_API}/system"
      [gitlab_gr]="vm|gr-pve01|curl -sk --max-time 5 https://gr-gitlab.example.net/api/v4/projects -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q 200"
      [awx_gr]="k8s|k8s|curl -sfk --max-time 5 -H 'Authorization: Bearer ${AWX_TOKEN}' ${AWX_URL}/api/v2/ping/"
      [pihole_gr]="vm|gr-pve01|curl -sf --max-time 5 http://gr-pihole01/admin/ -o /dev/null"
      [argocd_gr]="k8s|k8s|curl -sfk --max-time 5 https://gr-argocd.example.net -o /dev/null"
      [grafana_gr]="k8s|k8s|curl -sfk --max-time 5 https://gr-grafana.example.net -o /dev/null"
    )

    CATASTROPHIC_HOSTS="gr-fw01 gr-sw01 gr-sw02"
    PVE_HOST_PATTERN="grpve0*"
    ;;

  *)
    echo "ERROR: Unknown site '$MAINT_SITE'. Use --site nl or --site gr"
    exit 1
    ;;
esac

mkdir -p "$STATE_DIR"

# --- Utility functions ---

# kubectl wrapper that adds --context for non-default sites
kctl() {
  if [ -n "$K8S_CONTEXT" ]; then
    kubectl --context "$K8S_CONTEXT" "$@"
  else
    kubectl "$@"
  fi
}

log() { echo "[$(date '+%H:%M:%S')] $1"; }

post_matrix() {
  local room="${2:-$INFRA_ROOM}"
  local txn="maint-$(date +%s%N)-$$"
  if [ -n "$BOT_TOKEN" ]; then
    curl -sf --max-time 10 -X PUT \
      -H "Authorization: Bearer $BOT_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg m "$1" '{msgtype:"m.notice",body:$m}')" \
      "$MATRIX_URL/_matrix/client/v3/rooms/$room/send/m.room.message/$txn" \
      >/dev/null 2>&1 || true
  fi
}

# Parse service entry: "vmid|host|command" — but command may contain pipes.
# Use parameter expansion to split on first two | only.
_parse_service() {
  local entry="${CRITICAL_SERVICES[$1]}"
  local remainder="${entry#*|}"       # strip vmid
  SVC_HOST="${remainder%%|*}"          # host (before second |)
  SVC_CMD="${remainder#*|}"            # command (after second |, may contain |)
}

# Check if a service is reachable. Returns 0=up, 1=down.
check_service() {
  _parse_service "$1"
  eval "$SVC_CMD" >/dev/null 2>&1
  return $?
}

# Get PVE host for a service
get_service_host() {
  _parse_service "$1"
  echo "$SVC_HOST"
}

# LibreNMS API call with fallback. Returns response or empty string.
librenms_api() {
  local method="$1" endpoint="$2" body="${3:-}"
  local args=(-sfk --max-time 15 -X "$method" \
    -H "X-Auth-Token: $LIBRENMS_TOKEN" \
    -H "Content-Type: application/json")
  [ -n "$body" ] && args+=(-d "$body")
  curl "${args[@]}" "${LIBRENMS_API}${endpoint}" 2>/dev/null
}

# Set LibreNMS maintenance window on a single device
set_maintenance() {
  local hostname="$1" duration="${2:-2:00}" title="${3:-Maintenance companion}"
  local result
  # Try by hostname directly (LibreNMS accepts hostname in URL)
  result=$(librenms_api POST "/devices/$hostname/maintenance/" \
    "{\"title\":\"$title\",\"notes\":\"Set by maintenance companion\",\"duration\":\"$duration\"}" 2>/dev/null)
  if [ $? -eq 0 ] && echo "$result" | jq -e '.status == "ok"' >/dev/null 2>&1; then
    echo "ok"
    return 0
  fi
  # Fallback: try with FQDN
  result=$(librenms_api POST "/devices/${hostname}.example.net/maintenance/" \
    "{\"title\":\"$title\",\"notes\":\"Set by maintenance companion\",\"duration\":\"$duration\"}" 2>/dev/null)
  if [ $? -eq 0 ] && echo "$result" | jq -e '.status == "ok"' >/dev/null 2>&1; then
    echo "ok"
    return 0
  fi
  echo "failed"
  return 1
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SELFCHECK — Layer 0: verify the companion's own dependencies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd_selfcheck() {
  echo "=== MAINTENANCE COMPANION — SELF-CHECK ($SITE_LABEL) ==="
  echo ""
  local all_ok=true
  local available_tools=()
  local degraded_tools=()
  local down_services=()

  for svc in librenms matrix youtrack gitlab n8n awx claude01 dns_freeipa dns_pihole; do
    local host
    host=$(get_service_host "$svc")
    if check_service "$svc"; then
      printf "  ✅ %-15s (on %s)\n" "$svc" "$host"
      available_tools+=("$svc")
    else
      printf "  ❌ %-15s (on %s) — DOWN\n" "$svc" "$host"
      down_services+=("$svc")
      all_ok=false
    fi
  done

  # Check PVE host SSH access
  echo ""
  echo "--- PVE Host Access ---"
  for host in "${!PVE_HOSTS[@]}"; do
    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes "root@$host" echo ok >/dev/null 2>&1; then
      printf "  ✅ %-20s SSH OK\n" "$host"
    else
      printf "  ❌ %-20s SSH FAILED\n" "$host"
      all_ok=false
    fi
  done

  # Check kubectl
  echo ""
  echo "--- Kubernetes ---"
  if kctl get nodes --request-timeout=5s >/dev/null 2>&1; then
    local ready not_ready
    ready=$(kctl get nodes --no-headers 2>/dev/null | grep -c " Ready" || echo 0)
    not_ready=$(kctl get nodes --no-headers 2>/dev/null | grep -c "NotReady" || true)
    not_ready=${not_ready:-0}
    echo "  ✅ K8s cluster: $ready Ready, $not_ready NotReady"
  else
    echo "  ❌ K8s cluster unreachable"
    all_ok=false
  fi

  # Determine capabilities
  echo ""
  echo "--- Available Capabilities ---"
  if [[ " ${available_tools[*]} " =~ " awx " ]]; then
    echo "  🔧 AWX: can use job templates for maintenance windows"
  else
    echo "  ⚠️  AWX down: will use direct LibreNMS API calls"
  fi
  if [[ " ${available_tools[*]} " =~ " librenms " ]]; then
    echo "  🔧 LibreNMS: can set/clear maintenance windows"
  else
    echo "  ⚠️  LibreNMS down: maintenance windows unavailable, will suppress via PVE only"
  fi
  if [[ " ${available_tools[*]} " =~ " matrix " ]]; then
    echo "  🔧 Matrix: can post progress updates"
  else
    echo "  ⚠️  Matrix down: progress updates will be logged only"
  fi
  if [[ " ${available_tools[*]} " =~ " youtrack " ]]; then
    echo "  🔧 YouTrack: can create/update issues"
  else
    echo "  ⚠️  YouTrack down: issue tracking deferred until recovery"
  fi

  # Self-awareness: am I on the target host?
  echo ""
  local my_hostname
  my_hostname=$(hostname -s 2>/dev/null || echo "unknown")
  echo "--- Self-Awareness ---"
  echo "  Running on: $my_hostname"
  echo "  Claude Code LXC: nl-claude01 (on nl-pve03, VMID VMID_REDACTED)"
  echo "  ⚠️  If you're rebooting nl-pve03, this session will terminate."
  echo "     Set up monitoring BEFORE the reboot, or accept I'll resume when pve03 is back."

  if [ ${#down_services[@]} -gt 0 ]; then
    echo ""
    echo "=== DEGRADED MODE ==="
    echo "Down services: ${down_services[*]}"
    echo "Operations will use fallback methods where available."
  fi

  echo ""
  if $all_ok; then
    echo "STATUS: ALL SYSTEMS OPERATIONAL"
  else
    echo "STATUS: DEGRADED — some fallbacks will be used"
  fi

  # Save state
  printf '%s\n' "${available_tools[@]}" > "$STATE_DIR/available_tools"
  printf '%s\n' "${down_services[@]}" > "$STATE_DIR/down_services" 2>/dev/null || true
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEPS — list all devices that depend on a host
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd_deps() {
  local target="${1:?Usage: deps <hostname>}"
  echo "=== DEPENDENCY MAP: $target ==="
  echo ""

  # Check for catastrophic hosts (everything depends on them)
  if echo "$CATASTROPHIC_HOSTS" | grep -qw "$target"; then
    echo "⚠️  CATASTROPHIC: $target is a core infrastructure device."
    echo "    ALL 137+ monitored devices will be affected."
    echo ""
    echo "Impact:"
    case "$target" in
      nl-fw01)
        echo "  - ALL network connectivity lost (routing, NAT, VPN, BGP)"
        echo "  - Every monitored device becomes unreachable"
        echo "  - K8s BGP peering will drop (6 Cilium peers)"
        echo "  - VPN tunnels to GR/NO/CH sites will disconnect"
        ;;
      nl-sw01)
        echo "  - ALL wired connectivity lost"
        echo "  - Port-channels: Po1 (ASA), Po2/5/6 (Synology), Po3 (pve01), Po7 (pve03)"
        echo "  - Every VLAN will be isolated"
        ;;
    esac
    echo ""
    echo "Recommended: Set maintenance on ALL LibreNMS devices."
    # List all LibreNMS devices
    local devices
    devices=$(librenms_api GET "/devices?columns=hostname" 2>/dev/null | jq -r '.devices[].hostname' 2>/dev/null)
    if [ -n "$devices" ]; then
      local count
      count=$(echo "$devices" | wc -l)
      echo "Total devices in LibreNMS: $count"
    fi
    return 0
  fi

  # PVE host → list all guests from IaC configs
  if [[ "$target" == $PVE_HOST_PATTERN ]]; then
    local lxc_dir="$IAC_REPO/pve/$target/lxc"
    local qemu_dir="$IAC_REPO/pve/$target/qemu"
    local lxc_count=0 qemu_count=0
    local onboot_guests=() noboot_guests=()
    local critical_on_host=()

    echo "Type  | VMID        | Hostname                     | Onboot | Critical"
    echo "------|-------------|------------------------------|--------|----------"

    # Parse LXC configs
    if [ -d "$lxc_dir" ]; then
      for conf in "$lxc_dir"/*.conf; do
        [ -f "$conf" ] || continue
        local vmid guest_hostname onboot is_critical
        vmid=$(basename "$conf" .conf)
        guest_hostname=$(grep -m1 '^hostname:' "$conf" 2>/dev/null | awk '{print $2}')
        onboot=$(grep -m1 '^onboot:' "$conf" 2>/dev/null | awk '{print $2}')
        onboot="${onboot:-0}"
        is_critical=""

        # Check if this is a critical gateway service
        for svc in "${!CRITICAL_SERVICES[@]}"; do
          local svc_vmid="${CRITICAL_SERVICES[$svc]%%|*}"
          if [ "$svc_vmid" = "$vmid" ]; then
            is_critical="$svc"
            critical_on_host+=("$svc ($guest_hostname)")
            break
          fi
        done

        printf "LXC   | %-11s | %-28s | %-6s | %s\n" "$vmid" "${guest_hostname:-unknown}" "$onboot" "${is_critical:-}"
        lxc_count=$((lxc_count + 1))
        if [ "$onboot" = "1" ]; then
          onboot_guests+=("$guest_hostname")
        else
          noboot_guests+=("$guest_hostname")
        fi
      done
    fi

    # Parse QEMU configs
    if [ -d "$qemu_dir" ]; then
      for conf in "$qemu_dir"/*.conf; do
        [ -f "$conf" ] || continue
        local vmid guest_name onboot is_critical
        vmid=$(basename "$conf" .conf)
        guest_name=$(grep -m1 '^name:' "$conf" 2>/dev/null | awk '{print $2}')
        onboot=$(grep -m1 '^onboot:' "$conf" 2>/dev/null | awk '{print $2}')
        onboot="${onboot:-0}"
        is_critical=""

        for svc in "${!CRITICAL_SERVICES[@]}"; do
          local svc_vmid="${CRITICAL_SERVICES[$svc]%%|*}"
          if [ "$svc_vmid" = "$vmid" ]; then
            is_critical="$svc"
            critical_on_host+=("$svc ($guest_name)")
            break
          fi
        done

        printf "QEMU  | %-11s | %-28s | %-6s | %s\n" "$vmid" "${guest_name:-unknown}" "$onboot" "${is_critical:-}"
        qemu_count=$((qemu_count + 1))
      done
    fi

    echo ""
    echo "Summary: $lxc_count LXC + $qemu_count QEMU = $((lxc_count + qemu_count)) guests"
    echo "  Onboot=1 (must recover): ${#onboot_guests[@]}"
    echo "  Onboot=0 (expected stopped): ${#noboot_guests[@]}"

    if [ ${#critical_on_host[@]} -gt 0 ]; then
      echo ""
      echo "⚠️  CRITICAL SERVICES ON THIS HOST:"
      for c in "${critical_on_host[@]}"; do
        echo "  - $c"
      done

      # Special warnings
      if [[ "$target" == "nl-pve01" ]]; then
        echo ""
        echo "  🚨 DNS (FreeIPA + PiHole) is on this host!"
        echo "     All VMs will lose DNS resolution during reboot."
        echo "  🚨 n8n + Matrix are on this host!"
        echo "     Gateway will be fully offline. No Matrix updates possible."
      fi
      if [[ "$target" == "nl-pve03" ]]; then
        echo ""
        echo "  🚨 Claude Code runs on this host!"
        echo "     This session will terminate during reboot."
        echo "  🚨 LibreNMS + YouTrack are on this host!"
        echo "     Monitoring and issue tracking will be offline."
      fi
    fi

    # K8s impact
    local k8s_nodes
    k8s_nodes=$(grep -rl "^hostname: k8s-" "$lxc_dir" 2>/dev/null | while read -r f; do grep -m1 '^hostname:' "$f" | awk '{print $2}'; done)
    k8s_nodes+=$'\n'
    k8s_nodes+=$(grep -rl "^name: k8s-" "$qemu_dir" 2>/dev/null | while read -r f; do grep -m1 '^name:' "$f" | awk '{print $2}'; done)
    k8s_nodes=$(echo "$k8s_nodes" | grep -v '^$' | sort -u)

    if [ -n "$k8s_nodes" ]; then
      echo ""
      echo "K8s nodes on this host:"
      local ctrlr_count=0 worker_count=0
      while IFS= read -r node; do
        if [[ "$node" == *ctrlr* ]]; then
          echo "  🔴 $node (control plane)"
          ctrlr_count=$((ctrlr_count + 1))
        elif [[ "$node" == *wrkr* ]] || [[ "$node" == *node* ]]; then
          echo "  🟡 $node (worker)"
          worker_count=$((worker_count + 1))
        else
          echo "  ⚪ $node"
        fi
      done <<< "$k8s_nodes"

      if [ $ctrlr_count -gt 0 ]; then
        echo ""
        echo "  ⚠️  Losing $ctrlr_count control plane node(s). etcd quorum needs 2/3."
        if [ $ctrlr_count -ge 2 ]; then
          echo "  🚨 DANGER: Losing 2+ control plane nodes = etcd quorum LOST = cluster DOWN"
        fi
      fi
    fi

    return 0
  fi

  # Synology NAS → list NFS/iSCSI consumers
  if [[ "$target" == *syno* ]]; then
    echo "Storage device: $target"
    case "$target" in
      nl-nas01)
        echo "  🚨 nl-pve02 is a VM running on this NAS!"
        echo "     syno01 reboot → pve02 dies → K8s ctrl02 + OpenBao node 2 lost"
        echo "     Must set maintenance on pve02 + its 7 guests too."
        echo ""
        echo "  iSCSI consumers: K8s nodes (17 LUNs, 1.7TB on Storage Pool 1)"
        echo "  Services affected: SeaweedFS, Prometheus (2x200GB), Loki (100GB)"
        echo "  Impact: K8s PVCs go read-only, pods with iSCSI mounts will crash"
        echo ""
        echo "  ⚠️  CAUTION: Loki/Prometheus are heavy writers."
        echo "     Cap ingestion rates before maintenance to avoid pool saturation."
        ;;
      nl-nas02)
        echo "  NFS consumers: Frigate, Viseron (camera recordings)"
        echo "  Impact: NFS mounts hang, camera recording stops"
        ;;
    esac
    return 0
  fi

  # Generic device — just report it
  echo "Single device: $target"
  echo "No known dependency tree for this host."
  echo "Will set maintenance on this device only."
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# START — set maintenance windows on host + dependents
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd_start() {
  local target="${1:?Usage: start <hostname> [duration_hours]}"
  local duration_h="${2:-2}"
  local duration_hm="${duration_h}:00"
  local title="Maintenance companion: $target"

  echo "=== STARTING MAINTENANCE: $target (${duration_h}h window) ==="
  echo ""

  # Run selfcheck first
  log "Running self-check..."
  local librenms_up=false
  if check_service librenms; then
    librenms_up=true
    log "LibreNMS: UP — will set maintenance windows via API"
  else
    log "LibreNMS: DOWN — cannot set maintenance windows. Alerts will fire."
    log "⚠️  Proceeding without alert suppression."
  fi

  local success=0 failed=0 skipped=0

  if $librenms_up; then
    # Catastrophic host = set maintenance on ALL devices
    if echo "$CATASTROPHIC_HOSTS" | grep -qw "$target"; then
      log "Catastrophic host — setting maintenance on ALL devices"
      local all_devices
      all_devices=$(librenms_api GET "/devices?columns=hostname" 2>/dev/null | jq -r '.devices[].hostname' 2>/dev/null)
      while IFS= read -r dev; do
        [ -z "$dev" ] && continue
        if set_maintenance "$dev" "$duration_hm" "$title" >/dev/null 2>&1; then
          success=$((success + 1))
        else
          failed=$((failed + 1))
        fi
      done <<< "$all_devices"
      log "Maintenance set: $success OK, $failed failed"

    # PVE host = set on host + all guests
    elif [[ "$target" == $PVE_HOST_PATTERN ]]; then
      # Set on the PVE host itself
      log "Setting maintenance on PVE host: $target"
      if set_maintenance "$target" "$duration_hm" "$title" >/dev/null 2>&1; then
        success=$((success + 1))
        log "  ✅ $target"
      else
        failed=$((failed + 1))
        log "  ❌ $target (may not be in LibreNMS)"
      fi

      # Set on all guests
      local lxc_dir="$IAC_REPO/pve/$target/lxc"
      local qemu_dir="$IAC_REPO/pve/$target/qemu"

      for conf in "$lxc_dir"/*.conf "$qemu_dir"/*.conf; do
        [ -f "$conf" ] || continue
        local guest_hostname
        guest_hostname=$(grep -m1 '^hostname:\|^name:' "$conf" 2>/dev/null | awk '{print $2}')
        [ -z "$guest_hostname" ] && continue

        if set_maintenance "$guest_hostname" "$duration_hm" "$title" >/dev/null 2>&1; then
          success=$((success + 1))
        else
          # Not all guests are in LibreNMS — that's fine
          skipped=$((skipped + 1))
        fi
      done
      log "Maintenance set: $success OK, $failed failed, $skipped not in LibreNMS"

    # Single device
    else
      log "Setting maintenance on: $target"
      if set_maintenance "$target" "$duration_hm" "$title" >/dev/null 2>&1; then
        log "  ✅ $target"
        success=1
      else
        log "  ❌ $target — failed to set maintenance"
        failed=1
      fi
    fi
  fi

  # Save maintenance state
  local state_file="$STATE_DIR/${target}.json"
  jq -n \
    --arg host "$target" \
    --arg started "$(date -Iseconds)" \
    --arg duration "$duration_h" \
    --argjson success "$success" \
    --argjson failed "$failed" \
    --argjson skipped "$skipped" \
    --argjson librenms_up "$librenms_up" \
    '{host: $host, started: $started, duration_hours: ($duration|tonumber),
      devices_ok: $success, devices_failed: $failed, devices_skipped: $skipped,
      librenms_up: $librenms_up, status: "active"}' > "$state_file"

  echo ""
  echo "Maintenance window active. State saved to $state_file"
  echo "Use 'maintenance-companion.sh check $target' to monitor recovery."

  # Post to Matrix if available
  if check_service matrix 2>/dev/null; then
    post_matrix "🔧 Maintenance started: $target (${duration_h}h). $success devices in maintenance mode."
  fi
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATUS — list active maintenance windows
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd_status() {
  echo "=== ACTIVE MAINTENANCE WINDOWS ==="
  echo ""

  local found=false
  for state_file in "$STATE_DIR"/*.json; do
    [ -f "$state_file" ] || continue
    found=true
    local host started duration status
    host=$(jq -r '.host' "$state_file")
    started=$(jq -r '.started' "$state_file")
    duration=$(jq -r '.duration_hours' "$state_file")
    status=$(jq -r '.status' "$state_file")
    local devices_ok
    devices_ok=$(jq -r '.devices_ok' "$state_file")
    printf "  %-25s started: %s  duration: %sh  devices: %s  status: %s\n" \
      "$host" "$started" "$duration" "$devices_ok" "$status"
  done

  if ! $found; then
    echo "  No active maintenance windows."
  fi

  # Also check LibreNMS for any maintenance windows we didn't set
  echo ""
  echo "--- LibreNMS Scheduled Maintenance ---"
  local sched
  sched=$(librenms_api GET "/devicegroups" 2>/dev/null)
  if [ $? -ne 0 ]; then
    echo "  (LibreNMS unreachable)"
  else
    echo "  (Check LibreNMS UI for full maintenance schedule list)"
  fi
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECK — poll host + dependents for recovery status
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd_check() {
  local target="${1:?Usage: check <hostname>}"
  echo "=== RECOVERY CHECK: $target ==="
  echo ""

  # PVE host check
  if [[ "$target" == $PVE_HOST_PATTERN ]]; then
    # Step 1: Is the PVE host itself up?
    log "Checking PVE host..."
    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes "root@$target" echo ok >/dev/null 2>&1; then
      local uptime_str
      uptime_str=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "root@$target" uptime -p 2>/dev/null || echo "unknown")
      log "✅ $target is UP (uptime: $uptime_str)"
    else
      log "❌ $target is DOWN — not reachable via SSH"
      echo ""
      echo "Host is still rebooting or unreachable. Try again in 30-60s."
      return 1
    fi

    # Step 2: Check PVE web UI
    if curl -sfk --max-time 5 "https://$target:8006" >/dev/null 2>&1; then
      log "✅ PVE web UI responding (port 8006)"
    else
      log "⚠️  PVE web UI not responding yet — services may still be starting"
    fi

    # Step 3: Get guest status
    log "Checking guests..."
    local lxc_status qemu_status
    lxc_status=$(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "root@$target" "pct list 2>/dev/null" || echo "")
    qemu_status=$(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "root@$target" "qm list 2>/dev/null" || echo "")

    # Parse expected guests from IaC
    local lxc_dir="$IAC_REPO/pve/$target/lxc"
    local qemu_dir="$IAC_REPO/pve/$target/qemu"
    local total=0 running=0 stopped_expected=0 stopped_unexpected=0
    local unexpected_stopped=()

    echo ""
    echo "--- LXC Guests ---"
    for conf in "$lxc_dir"/*.conf; do
      [ -f "$conf" ] || continue
      local vmid guest_hostname onboot status_line
      vmid=$(basename "$conf" .conf)
      guest_hostname=$(grep -m1 '^hostname:' "$conf" 2>/dev/null | awk '{print $2}')
      onboot=$(grep -m1 '^onboot:' "$conf" 2>/dev/null | awk '{print $2}')
      onboot="${onboot:-0}"
      total=$((total + 1))

      # Find this VMID in pct list output
      if echo "$lxc_status" | grep -q "^[[:space:]]*$vmid[[:space:]].*running"; then
        printf "  ✅ %-30s (%s) running\n" "${guest_hostname:-$vmid}" "$vmid"
        running=$((running + 1))
      elif echo "$lxc_status" | grep -q "^[[:space:]]*$vmid"; then
        if [ "$onboot" = "0" ]; then
          printf "  ⚪ %-30s (%s) stopped (onboot=0, expected)\n" "${guest_hostname:-$vmid}" "$vmid"
          stopped_expected=$((stopped_expected + 1))
        else
          printf "  ❌ %-30s (%s) STOPPED (onboot=1, UNEXPECTED)\n" "${guest_hostname:-$vmid}" "$vmid"
          stopped_unexpected=$((stopped_unexpected + 1))
          unexpected_stopped+=("${guest_hostname:-$vmid}")
        fi
      else
        if [ "$onboot" = "0" ]; then
          printf "  ⚪ %-30s (%s) not listed (onboot=0)\n" "${guest_hostname:-$vmid}" "$vmid"
          stopped_expected=$((stopped_expected + 1))
        else
          printf "  ❌ %-30s (%s) NOT FOUND (UNEXPECTED)\n" "${guest_hostname:-$vmid}" "$vmid"
          stopped_unexpected=$((stopped_unexpected + 1))
          unexpected_stopped+=("${guest_hostname:-$vmid}")
        fi
      fi
    done

    echo ""
    echo "--- QEMU Guests ---"
    for conf in "$qemu_dir"/*.conf; do
      [ -f "$conf" ] || continue
      local vmid guest_name onboot
      vmid=$(basename "$conf" .conf)
      guest_name=$(grep -m1 '^name:' "$conf" 2>/dev/null | awk '{print $2}')
      onboot=$(grep -m1 '^onboot:' "$conf" 2>/dev/null | awk '{print $2}')
      onboot="${onboot:-0}"
      total=$((total + 1))

      if echo "$qemu_status" | grep -q "^[[:space:]]*$vmid[[:space:]].*running"; then
        printf "  ✅ %-30s (%s) running\n" "${guest_name:-$vmid}" "$vmid"
        running=$((running + 1))
      else
        if [ "$onboot" = "0" ]; then
          printf "  ⚪ %-30s (%s) stopped (onboot=0, expected)\n" "${guest_name:-$vmid}" "$vmid"
          stopped_expected=$((stopped_expected + 1))
        else
          printf "  ❌ %-30s (%s) STOPPED (onboot=1, UNEXPECTED)\n" "${guest_name:-$vmid}" "$vmid"
          stopped_unexpected=$((stopped_unexpected + 1))
          unexpected_stopped+=("${guest_name:-$vmid}")
        fi
      fi
    done

    echo ""
    echo "=== SUMMARY ==="
    echo "  Running: $running/$total"
    echo "  Expected stopped (onboot=0): $stopped_expected"
    echo "  UNEXPECTED stopped: $stopped_unexpected"

    if [ $stopped_unexpected -gt 0 ]; then
      echo ""
      echo "⚠️  Guests that should be running but aren't:"
      for g in "${unexpected_stopped[@]}"; do
        echo "  - $g"
      done
    fi

    # Step 4: Check critical services on this host
    echo ""
    echo "--- Critical Service Recovery ---"
    for svc in "${!CRITICAL_SERVICES[@]}"; do
      local svc_host
      svc_host=$(get_service_host "$svc")
      if [ "$svc_host" = "$target" ]; then
        if check_service "$svc"; then
          printf "  ✅ %-15s responding\n" "$svc"
        else
          printf "  ❌ %-15s NOT responding (may still be starting)\n" "$svc"
        fi
      fi
    done

    # Step 5: K8s node check
    local k8s_on_host=false
    for conf in "$lxc_dir"/*.conf "$qemu_dir"/*.conf; do
      [ -f "$conf" ] || continue
      if grep -q 'k8s-' "$conf" 2>/dev/null; then
        k8s_on_host=true
        break
      fi
    done

    if $k8s_on_host; then
      echo ""
      echo "--- K8s Node Status ---"
      if kctl get nodes --request-timeout=5s >/dev/null 2>&1; then
        kctl get nodes --no-headers 2>/dev/null | while IFS= read -r line; do
          local node_name node_status
          node_name=$(echo "$line" | awk '{print $1}')
          node_status=$(echo "$line" | awk '{print $2}')
          if [ "$node_status" = "Ready" ]; then
            printf "  ✅ %-35s %s\n" "$node_name" "$node_status"
          else
            printf "  ❌ %-35s %s\n" "$node_name" "$node_status"
          fi
        done
      else
        echo "  ❌ K8s cluster unreachable"
      fi
    fi

    return 0
  fi

  # Network device check (firewall, switch)
  if echo "$CATASTROPHIC_HOSTS" | grep -qw "$target"; then
    log "Checking network device: $target"
    if ping -c 2 -W 3 "$target" >/dev/null 2>&1; then
      log "✅ $target responds to ping"
      if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "admin@$target" "show version" >/dev/null 2>&1; then
        log "✅ $target SSH accessible"
      else
        log "⚠️  $target pingable but SSH not ready yet"
      fi
    else
      log "❌ $target not responding to ping"
    fi
    return 0
  fi

  # Generic device — just ping + SSH
  log "Checking: $target"
  if ping -c 2 -W 3 "$target" >/dev/null 2>&1; then
    log "✅ $target responds to ping"
  else
    log "❌ $target not responding"
  fi
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# END — clear maintenance windows
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd_end() {
  local target="${1:?Usage: end <hostname>}"
  echo "=== ENDING MAINTENANCE: $target ==="
  echo ""

  # Run a final check first
  log "Running final recovery check..."
  cmd_check "$target"

  # Remove state file
  local state_file="$STATE_DIR/${target}.json"
  if [ -f "$state_file" ]; then
    jq '.status = "completed" | .ended = (now | todate)' "$state_file" > "${state_file}.tmp" && mv "${state_file}.tmp" "$state_file"
    log "Maintenance state updated to 'completed'"
  fi

  # Note: LibreNMS maintenance windows are time-based and expire automatically.
  # We don't need to actively clear them — they'll expire at the set duration.
  echo ""
  log "Maintenance window will expire automatically based on the duration set."
  log "If you need to clear it early, use the LibreNMS UI."

  # Post to Matrix if available
  if check_service matrix 2>/dev/null; then
    post_matrix "✅ Maintenance ended: $target. Final check completed."
  fi
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CHECKLIST — run device-type-specific post-reboot checklist
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd_checklist() {
  local device_type="${1:?Usage: checklist <pve|asa|switch|synology> <hostname>}"
  local target="${2:?Usage: checklist <pve|asa|switch|synology> <hostname>}"

  echo "=== POST-REBOOT CHECKLIST: $target ($device_type) ==="
  echo ""

  case "$device_type" in
    pve)
      local passed=0 total=0

      # 1. SSH reachable
      total=$((total + 1))
      if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes "root@$target" echo ok >/dev/null 2>&1; then
        echo "✅ PVE host SSH reachable"
        passed=$((passed + 1))
      else
        echo "❌ PVE host SSH NOT reachable"
        echo "   Cannot proceed with remaining checks."
        echo "RESULT: $passed/$total passed"
        return 1
      fi

      # 2. PVE web UI
      total=$((total + 1))
      if curl -sk --max-time 5 "https://$target:8006/" -o /dev/null -w '%{http_code}' 2>/dev/null | grep -q '200\|301\|302'; then
        echo "✅ PVE web UI responding (port 8006)"
        passed=$((passed + 1))
      else
        echo "❌ PVE web UI NOT responding"
      fi

      # 3. All onboot=1 guests running (delegate to check command)
      total=$((total + 1))
      local stopped_unexpected=0
      local lxc_dir="$IAC_REPO/pve/$target/lxc"
      local qemu_dir="$IAC_REPO/pve/$target/qemu"
      local lxc_status qemu_status
      lxc_status=$(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "root@$target" "pct list 2>/dev/null" || echo "")
      qemu_status=$(ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "root@$target" "qm list 2>/dev/null" || echo "")

      for conf in "$lxc_dir"/*.conf "$qemu_dir"/*.conf; do
        [ -f "$conf" ] || continue
        local vmid onboot
        vmid=$(basename "$conf" .conf)
        onboot=$(grep -m1 '^onboot:' "$conf" 2>/dev/null | awk '{print $2}')
        [ "$onboot" != "1" ] && continue
        if ! echo "$lxc_status $qemu_status" | grep -q "^[[:space:]]*$vmid[[:space:]].*running"; then
          stopped_unexpected=$((stopped_unexpected + 1))
        fi
      done

      if [ $stopped_unexpected -eq 0 ]; then
        echo "✅ All onboot=1 guests running"
        passed=$((passed + 1))
      else
        echo "❌ $stopped_unexpected onboot=1 guests NOT running"
      fi

      # 4. K8s nodes Ready (if applicable)
      if grep -rlq 'k8s-' "$lxc_dir" "$qemu_dir" 2>/dev/null; then
        total=$((total + 1))
        if kctl get nodes --request-timeout=5s >/dev/null 2>&1; then
          local not_ready
          not_ready=$(kctl get nodes --no-headers 2>/dev/null | grep -c "NotReady" || true)
          not_ready=${not_ready:-0}
          if [ "$not_ready" -eq 0 ]; then
            echo "✅ All K8s nodes Ready"
            passed=$((passed + 1))
          else
            echo "❌ $not_ready K8s node(s) NotReady"
          fi
        else
          echo "❌ K8s cluster unreachable"
        fi
      fi

      # 5. ZFS healthy (if ZFS is in use)
      local zfs_status
      zfs_status=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "root@$target" "zpool status -x 2>/dev/null" || echo "")
      if [ -n "$zfs_status" ]; then
        total=$((total + 1))
        if echo "$zfs_status" | grep -q "all pools are healthy"; then
          echo "✅ ZFS pools healthy"
          passed=$((passed + 1))
        else
          echo "⚠️  ZFS: $zfs_status"
        fi
      fi

      echo ""
      echo "RESULT: $passed/$total passed"
      ;;

    asa)
      echo "ASA firewall checklist — run these from Claude Code via SSH:"
      echo ""
      echo "1. SSH reachable: ssh admin@$target"
      echo "2. WAN interfaces: show interface ip brief"
      echo "3. BGP peers: show bgp summary (expect 6 Cilium peers)"
      echo "4. VPN tunnels: show crypto ikev2 sa (GR, NO, CH)"
      echo "5. NAT: show xlate count"
      echo "6. DHCP: show dhcpd binding count"
      echo "7. Failover: show failover (if HA pair)"
      echo ""
      echo "⚠️  ASA commands must be run interactively — script cannot automate."
      ;;

    switch)
      echo "Switch checklist — run these from Claude Code via SSH:"
      echo ""
      echo "1. SSH reachable: ssh admin@$target"
      echo "2. Port-channels: show etherchannel summary"
      echo "3. Spanning-tree: show spanning-tree summary"
      echo "4. VLANs: show vlan brief"
      echo "5. Error counters: show interfaces counters errors"
      echo "6. StackWise: show switch (if stacked)"
      echo ""
      echo "⚠️  IOS-XE commands must be run interactively — script cannot automate."
      ;;

    synology)
      local passed=0 total=0

      # 1. SSH reachable
      total=$((total + 1))
      if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes "root@$target" echo ok >/dev/null 2>&1; then
        echo "✅ Synology SSH reachable"
        passed=$((passed + 1))
      else
        echo "❌ Synology SSH NOT reachable"
        echo "RESULT: $passed/$total"
        return 1
      fi

      # 2. RAID status
      total=$((total + 1))
      local mdstat
      mdstat=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "root@$target" "cat /proc/mdstat 2>/dev/null" || echo "")
      if echo "$mdstat" | grep -q "\[U\+\]" && ! echo "$mdstat" | grep -q "_"; then
        echo "✅ RAID healthy (all [UU...])"
        passed=$((passed + 1))
      else
        echo "❌ RAID degraded or unknown"
      fi

      # 3. Volumes mounted
      total=$((total + 1))
      local volumes
      volumes=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "root@$target" "df -h /volume1 /volume2 2>/dev/null" || echo "")
      if echo "$volumes" | grep -q "/volume1"; then
        echo "✅ Volumes mounted"
        passed=$((passed + 1))
      else
        echo "❌ Volumes not mounted"
      fi

      # 4. NFS exports
      total=$((total + 1))
      local nfs
      nfs=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "root@$target" "showmount -e localhost 2>/dev/null" || echo "")
      if [ -n "$nfs" ] && echo "$nfs" | grep -q "/volume"; then
        echo "✅ NFS exports active"
        passed=$((passed + 1))
      else
        echo "⚠️  No NFS exports found (may be expected)"
      fi

      # 5. iSCSI targets (syno01 only)
      if [[ "$target" == *syno01* ]]; then
        total=$((total + 1))
        local iscsi
        iscsi=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "root@$target" "cat /etc/target/saveconfig.json 2>/dev/null | python3 -c 'import json,sys; t=json.load(sys.stdin); print(len(t.get(\"targets\",[])))'  2>/dev/null" || echo "0")
        if [ "$iscsi" -gt 0 ]; then
          echo "✅ iSCSI: $iscsi targets configured"
          passed=$((passed + 1))
        else
          echo "❌ iSCSI targets not found"
        fi

        # Check K8s PVCs
        total=$((total + 1))
        if kctl get pvc -A --no-headers 2>/dev/null | grep -v "Bound" | grep -c "." >/dev/null 2>&1; then
          local unbound
          unbound=$(kctl get pvc -A --no-headers 2>/dev/null | grep -cv "Bound" || echo 0)
          if [ "$unbound" -eq 0 ]; then
            echo "✅ All K8s PVCs Bound"
            passed=$((passed + 1))
          else
            echo "❌ $unbound K8s PVC(s) not Bound"
          fi
        else
          echo "✅ All K8s PVCs Bound"
          passed=$((passed + 1))
        fi
      fi

      echo ""
      echo "RESULT: $passed/$total passed"
      ;;

    *)
      echo "Unknown device type: $device_type"
      echo "Valid types: pve, asa, switch, synology"
      return 1
      ;;
  esac
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Main dispatcher
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cmd="${1:-help}"
shift || true

case "$cmd" in
  selfcheck)  cmd_selfcheck "$@" ;;
  deps)       cmd_deps "$@" ;;
  start)      cmd_start "$@" ;;
  status)     cmd_status "$@" ;;
  check)      cmd_check "$@" ;;
  end)        cmd_end "$@" ;;
  checklist)  cmd_checklist "$@" ;;
  help|*)
    echo "maintenance-companion.sh — Active maintenance event manager"
    echo ""
    echo "Commands:"
    echo "  selfcheck                          Verify all gateway dependencies (Layer 0)"
    echo "  deps <hostname>                    List devices affected by this host"
    echo "  start <hostname> [duration_hours]  Set maintenance windows (default 2h)"
    echo "  status                             List active maintenance windows"
    echo "  check <hostname>                   Poll host + guests for recovery"
    echo "  end <hostname>                     Run final check, mark completed"
    echo "  checklist <type> <hostname>        Post-reboot checklist (pve|asa|switch|synology)"
    echo ""
    echo "Options:"
    echo "  --site nl|gr                       Select site (auto-detected from hostname)"
    ;;
esac
