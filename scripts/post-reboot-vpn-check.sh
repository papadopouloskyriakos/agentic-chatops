#!/bin/bash
# post-reboot-vpn-check.sh — Post-ASA-reboot cross-site tunnel validation
#
# Called by asa-reboot-watch.sh after deactivate_maintenance().
# Validates IPsec SAs re-established and cross-site traffic flows
# across ALL critical subnet pairs — not just management.
#
# Usage:
#   post-reboot-vpn-check.sh <device> <site> [--dry-run]
#
# The stale SA problem affects ALL crypto-map entries on the ASA.
# Management traffic may work (masking the failure) while DMZ, K8s,
# storage, and corosync subnets are silently blackholed.
#
# Probes performed per subnet pair:
#   - TCP connect to service-specific ports
#   - ICMP as fallback
#   - Results logged and alerted per-pair

set -uo pipefail

DEVICE="${1:?Usage: post-reboot-vpn-check.sh <device> <site> [--dry-run]}"
SITE="${2:?Missing site: nl or gr}"
DRY_RUN=false
[ "${3:-}" = "--dry-run" ] && DRY_RUN=true

LOG_TAG="[vpn-check]"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Matrix posting
MATRIX_TOKEN=$(grep MATRIX_ACCESS_TOKEN "$REPO_DIR/.env" 2>/dev/null | cut -d= -f2-)
MATRIX_URL="https://matrix.example.net"
NL_ROOM='!AOMuEtXGyzGFLgObKN:matrix.example.net'
GR_ROOM='!NKosBPujbWMevzHaaM:matrix.example.net'
ALERTS_ROOM='!xeNxtpScJWCmaFjeCL:matrix.example.net'

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $LOG_TAG $*"; }

post_matrix() {
  local msg="$1" room="$2"
  [ -z "$MATRIX_TOKEN" ] && return
  $DRY_RUN && { log "DRY-RUN: Would post to Matrix: $msg"; return; }
  curl -s -X PUT "${MATRIX_URL}/_matrix/client/v3/rooms/${room}/send/m.room.message/$(date +%s%N)" \
    -H "Authorization: Bearer $MATRIX_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"msgtype\":\"m.notice\",\"body\":\"$msg\"}" >/dev/null 2>&1
}

***REMOVED***
# CROSS-SITE PROBE DEFINITIONS
# Each entry: "label|target_ip|port1,port2,...|protocol"
# protocol: tcp (connect test) or icmp (ping only)
# These represent ALL critical services that traverse the IPsec tunnel.
***REMOVED***

# When NL ASA reboots: test NL→GR reachability
NL_TO_GR_PROBES=(
  "GR Management|10.0.X.X|22|tcp"
  "GR DMZ (Galera)|10.0.X.X|3306,4567,4568|tcp"
  "GR K8s API (ClusterMesh)|10.0.58.X|6443|tcp"
  "GR K8s Worker|10.0.58.X|10250|tcp"
  "GR Servers|10.0.X.X||icmp"
)

# When GR ASA reboots: test GR→NL reachability
GR_TO_NL_PROBES=(
  "NL Management|10.0.181.X|22|tcp"
  "NL DMZ (Galera)|10.0.X.X|3306,4567,4568|tcp"
  "NL n8n (alert pipeline)|10.0.181.X|5678|tcp"
  "NL Matrix (chat)|10.0.181.X|8008|tcp"
  "NL K8s API (ClusterMesh)|10.0.181.X|6443|tcp"
  "NL K8s Worker|10.0.181.X|10250|tcp"
  "NL Servers|10.0.181.X||icmp"
)

# ASA SSH access
ASA_USER="operator"
ASA_PASS="${CISCO_ASA_PASSWORD:?CISCO_ASA_PASSWORD env var not set}"
NL_ASA_IP="10.0.181.X"
GR_ASA_IP="10.0.X.X"
GR_PVE_STEP="root@gr-pve01"

MAX_RETRIES=3
RETRY_DELAY=30

log "Starting post-reboot cross-site tunnel check for $DEVICE ($SITE)"

# ─── Step 1: Wait for ASA to stabilize ───
log "Step 1: Waiting 60s for ASA + IKE stabilization..."
$DRY_RUN || sleep 60

# ─── Step 2: Check IKEv2 SA state ───
check_ike_sa() {
  log "Step 2: Checking IKEv2 SA state on $DEVICE..."

  local sa_output=""
  if [ "$SITE" = "nl" ]; then
    sa_output=$(ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
      -o ConnectTimeout=15 -o StrictHostKeyChecking=no \
      "$ASA_USER@$NL_ASA_IP" "show crypto ikev2 sa" 2>/dev/null) || {
      log "ERROR: Cannot SSH to NL ASA"
      return 1
    }
  else
    sa_output=$(ssh -i ~/.ssh/one_key -o ConnectTimeout=15 -o StrictHostKeyChecking=no \
      "$GR_PVE_STEP" "ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
      -o ConnectTimeout=10 -o StrictHostKeyChecking=no $ASA_USER@$GR_ASA_IP \
      'show crypto ikev2 sa'" 2>/dev/null) || {
      log "ERROR: Cannot SSH to GR ASA (via stepping stone)"
      return 1
    }
  fi

  if echo "$sa_output" | grep -iqE 'READY|ESTABLISHED'; then
    local sa_count=$(echo "$sa_output" | grep -ciE 'READY|ESTABLISHED')
    log "  IKEv2 SA: $sa_count tunnel(s) ESTABLISHED"
    return 0
  else
    log "  IKEv2 SA: NOT established"
    return 1
  fi
}

# ─── Step 3: Probe all cross-site subnet pairs ───
probe_all_subnets() {
  log "Step 3: Probing cross-site subnet pairs..."

  local probes=()
  if [ "$SITE" = "nl" ]; then
    probes=("${NL_TO_GR_PROBES[@]}")
  else
    probes=("${GR_TO_NL_PROBES[@]}")
  fi

  local total=0 passed=0 failed=0
  local failed_labels=""

  for probe in "${probes[@]}"; do
    IFS='|' read -r label target_ip ports protocol <<< "$probe"
    ((total++))

    if [ "$protocol" = "tcp" ] && [ -n "$ports" ]; then
      # TCP connect test for each port
      local port_ok=true
      IFS=',' read -ra PORT_ARRAY <<< "$ports"
      for port in "${PORT_ARRAY[@]}"; do
        if $DRY_RUN; then
          log "  DRY-RUN: Would probe $label ($target_ip:$port)"
          continue
        fi
        if timeout 5 bash -c "echo >/dev/tcp/$target_ip/$port" 2>/dev/null; then
          log "  OK: $label ($target_ip:$port)"
        else
          log "  FAIL: $label ($target_ip:$port) — blackholed or refused"
          port_ok=false
        fi
      done
      $port_ok && ((passed++)) || { ((failed++)); failed_labels="$failed_labels, $label"; }
    else
      # ICMP fallback
      if $DRY_RUN; then
        log "  DRY-RUN: Would ping $label ($target_ip)"
        ((passed++))
        continue
      fi
      if ping -c 2 -W 3 "$target_ip" >/dev/null 2>&1; then
        log "  OK: $label ($target_ip) — ICMP"
        ((passed++))
      else
        log "  FAIL: $label ($target_ip) — ICMP unreachable"
        ((failed++))
        failed_labels="$failed_labels, $label"
      fi
    fi
  done

  log "  Subnet probe results: $passed/$total passed, $failed failed"
  [ -n "$failed_labels" ] && log "  Failed: ${failed_labels#, }"

  return $failed
}

# ─── Step 4: Clear stale SAs (remediation) ───
clear_stale_sas() {
  log "Step 4: CLEARING stale SAs on REMOTE side..."

  if $DRY_RUN; then
    log "DRY-RUN: Would run 'clear xlate' + 'clear crypto ipsec sa' on remote ASA"
    return 0
  fi

  # Always clear on the REMOTE side (the one that DIDN'T reboot)
  # because the rebooted ASA has fresh SAs but the remote has stale ones
  if [ "$SITE" = "nl" ]; then
    # NL rebooted → clear GR (remote side has stale SAs)
    ssh -i ~/.ssh/one_key -o ConnectTimeout=15 -o StrictHostKeyChecking=no \
      "$GR_PVE_STEP" "ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
      -o ConnectTimeout=10 -o StrictHostKeyChecking=no $ASA_USER@$GR_ASA_IP \
      'clear xlate
       clear crypto ipsec sa'" 2>/dev/null
    log "  Cleared xlate + IPsec SA on gr-fw01 (remote/stale side)"
  else
    # GR rebooted → clear NL (remote side has stale SAs)
    ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
      -o ConnectTimeout=15 -o StrictHostKeyChecking=no \
      "$ASA_USER@$NL_ASA_IP" "clear xlate
       clear crypto ipsec sa" 2>/dev/null
    log "  Cleared xlate + IPsec SA on nl-fw01 (remote/stale side)"
  fi

  log "  Waiting 30s for IKE renegotiation..."
  sleep 30
}

# ─── Main Flow ───
TUNNEL_OK=false

for attempt in $(seq 1 $MAX_RETRIES); do
  log "=== Attempt $attempt/$MAX_RETRIES ==="

  IKE_OK=false
  SUBNET_FAILURES=0

  # Check IKE SA
  check_ike_sa && IKE_OK=true

  # Probe ALL cross-site subnets (even if IKE looks OK — the incident
  # proved IKE can appear established while specific subnet SAs are stale)
  probe_all_subnets
  SUBNET_FAILURES=$?

  if $IKE_OK && [ "$SUBNET_FAILURES" -eq 0 ]; then
    TUNNEL_OK=true
    log "All cross-site probes passed — tunnel fully operational"
    break
  fi

  # Tunnel has stale SAs — attempt remediation
  if [ "$attempt" -lt "$MAX_RETRIES" ]; then
    log "Tunnel issues: IKE=$IKE_OK, subnet failures=$SUBNET_FAILURES — clearing stale SAs..."
    clear_stale_sas
  fi
done

# ─── Report Results ───
ROOM="$NL_ROOM"
[ "$SITE" = "gr" ] && ROOM="$GR_ROOM"
DIRECTION=$( [ "$SITE" = "nl" ] && echo "NL→GR" || echo "GR→NL" )

if $TUNNEL_OK; then
  post_matrix "✅ [Post-Reboot VPN Check] $DEVICE — All cross-site probes passed ($DIRECTION). DMZ/K8s/management connectivity verified." "$ROOM"
  log "RESULT: PASS"
  exit 0
else
  MSG="🔴 [Post-Reboot VPN Check] $DEVICE — Cross-site tunnel STALE after $MAX_RETRIES attempts ($DIRECTION). $SUBNET_FAILURES subnet pair(s) unreachable. Services at risk: Galera, ClusterMesh, SeaweedFS, alert pipeline. Manual: SSH to remote ASA, run 'clear xlate' + 'clear crypto ipsec sa'."
  post_matrix "$MSG" "$ROOM"
  post_matrix "$MSG" "$ALERTS_ROOM"
  log "RESULT: FAIL — $SUBNET_FAILURES subnet pairs unreachable"
  exit 1
fi
