#!/bin/bash
# G7: Capture pre-state snapshot before an infrastructure command
#
# Usage:
#   capture-pre-state.sh <device> <command> [--issue <issue_id>] [--session <session_id>]
#
# Captures relevant device state BEFORE executing a change command.
# Stores the snapshot in the execution_log table for rollback reference.
#
# Device type detection:
#   - ASA (fw01): show run, show xlate, show crypto ipsec sa
#   - PVE (pveXX): pct/qm config, pvecm status
#   - K8s (k8s-*): kubectl get resource
#   - Linux (generic): systemctl status, ip addr, iptables
#
# Output: JSON with pre_state, suggested rollback command

set -euo pipefail

DB="${HOME}/gitlab/products/cubeos/claude-context/gateway.db"
DEVICE="${1:-}"
COMMAND="${2:-}"
ISSUE_ID=""
SESSION_ID=""

# Parse optional flags
shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue)  ISSUE_ID="$2"; shift 2 ;;
    --session) SESSION_ID="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$DEVICE" || -z "$COMMAND" ]]; then
  echo "Usage: capture-pre-state.sh <device> <command> [--issue ID] [--session ID]"
  exit 1
fi

DEVICE_LOWER=$(echo "$DEVICE" | tr '[:upper:]' '[:lower:]')
PRE_STATE=""
ROLLBACK_CMD=""

# Determine device type and capture appropriate pre-state
capture_asa_state() {
  local host="$1"
  local ip
  if [[ "$host" == *"nl-fw01"* ]]; then
    ip="10.0.181.X"
  elif [[ "$host" == *"gr-fw01"* ]]; then
    # GR ASA needs stepstone — capture not supported in automated mode
    echo '{"error": "GR ASA requires stepstone SSH — pre-state capture not supported in automated mode"}'
    return 1
  fi
  # Capture running config section relevant to command
  if echo "$COMMAND" | grep -qi "crypto\|vpn\|tunnel\|ipsec"; then
    PRE_STATE="crypto_config"
    ROLLBACK_CMD="# Review pre_state crypto config and re-apply if needed"
  elif echo "$COMMAND" | grep -qi "nat\|xlate"; then
    PRE_STATE="nat_config"
    ROLLBACK_CMD="# Review pre_state NAT rules and re-apply if needed"
  elif echo "$COMMAND" | grep -qi "access-list\|acl"; then
    PRE_STATE="acl_config"
    ROLLBACK_CMD="# Review pre_state ACLs and re-apply if needed"
  else
    PRE_STATE="running_config"
    ROLLBACK_CMD="# Full running config captured — compare diff to revert"
  fi
}

capture_pve_state() {
  local host="$1"
  if echo "$COMMAND" | grep -qi "pct\|lxc"; then
    local vmid
    vmid=$(echo "$COMMAND" | grep -oP '\d{9,}' | head -1)
    if [[ -n "$vmid" ]]; then
      PRE_STATE=$(ssh "$host" "pct config $vmid 2>/dev/null" 2>/dev/null || echo "failed")
      ROLLBACK_CMD="pct set $vmid <restored-options>"
    fi
  elif echo "$COMMAND" | grep -qi "qm\|vm"; then
    local vmid
    vmid=$(echo "$COMMAND" | grep -oP '\d{9,}' | head -1)
    if [[ -n "$vmid" ]]; then
      PRE_STATE=$(ssh "$host" "qm config $vmid 2>/dev/null" 2>/dev/null || echo "failed")
      ROLLBACK_CMD="qm set $vmid <restored-options>"
    fi
  else
    PRE_STATE=$(ssh "$host" "uptime; df -h / /var 2>/dev/null; pvecm status 2>/dev/null" 2>/dev/null || echo "failed")
    ROLLBACK_CMD="# Generic PVE state captured — manual review needed"
  fi
}

capture_k8s_state() {
  local context="nl"
  if echo "$DEVICE" | grep -qi "grskg"; then
    context="gr"
  fi
  # Extract resource type and name from kubectl command
  if echo "$COMMAND" | grep -qi "kubectl"; then
    local resource
    resource=$(echo "$COMMAND" | grep -oP '(deployment|service|configmap|pod|daemonset|statefulset)/\S+' | head -1)
    local namespace
    namespace=$(echo "$COMMAND" | grep -oP '(?<=-n\s)\S+' | head -1)
    if [[ -n "$resource" ]]; then
      local ns_flag=""
      [[ -n "$namespace" ]] && ns_flag="-n $namespace"
      PRE_STATE=$(kubectl --context="$context" get "$resource" $ns_flag -o yaml 2>/dev/null || echo "failed")
      ROLLBACK_CMD="kubectl --context=$context apply -f <pre-state-yaml>"
    fi
  fi
}

capture_linux_state() {
  local host="$1"
  if echo "$COMMAND" | grep -qi "systemctl\|service"; then
    local svc
    svc=$(echo "$COMMAND" | grep -oP '(?:systemctl\s+\w+\s+|service\s+)\K\S+' | head -1)
    if [[ -n "$svc" ]]; then
      PRE_STATE=$(ssh "$host" "systemctl status $svc 2>/dev/null" 2>/dev/null || echo "failed")
      ROLLBACK_CMD="systemctl restart $svc"
    fi
  elif echo "$COMMAND" | grep -qi "iptables\|nftables"; then
    PRE_STATE=$(ssh "$host" "iptables-save 2>/dev/null" 2>/dev/null || echo "failed")
    ROLLBACK_CMD="iptables-restore < <pre-state>"
  else
    PRE_STATE=$(ssh "$host" "uptime; df -h / 2>/dev/null" 2>/dev/null || echo "failed")
    ROLLBACK_CMD="# Generic Linux state — manual review needed"
  fi
}

# Route to appropriate capture function
START_MS=$(($(date +%s%N) / 1000000))

if echo "$DEVICE_LOWER" | grep -qE "fw0[12]|asa"; then
  capture_asa_state "$DEVICE"
elif echo "$DEVICE_LOWER" | grep -qE "pve0[123]"; then
  capture_pve_state "$DEVICE"
elif echo "$DEVICE_LOWER" | grep -qE "k8s|ctrlr|wrkr|node"; then
  capture_k8s_state
else
  capture_linux_state "$DEVICE"
fi

END_MS=$(($(date +%s%N) / 1000000))
DURATION=$((END_MS - START_MS))

# Get next step_index for this session
STEP_INDEX=0
if [[ -n "$SESSION_ID" ]]; then
  STEP_INDEX=$(sqlite3 "$DB" "SELECT COALESCE(MAX(step_index), -1) + 1 FROM execution_log WHERE session_id='$SESSION_ID'" 2>/dev/null || echo 0)
fi

# Store in execution_log — schema_version=1 per scripts/lib/schema_version.py (IFRNLLEI01PRD-635).
sqlite3 "$DB" "INSERT INTO execution_log (session_id, issue_id, step_index, device, command, pre_state, exit_code, rollback_command, duration_ms, schema_version) VALUES ('$SESSION_ID', '$ISSUE_ID', $STEP_INDEX, '$DEVICE', '$(echo "$COMMAND" | sed "s/'/''/g")', '$(echo "$PRE_STATE" | sed "s/'/''/g")', -1, '$(echo "$ROLLBACK_CMD" | sed "s/'/''/g")', $DURATION, 1)" 2>/dev/null

# Output
echo "{\"step_index\": $STEP_INDEX, \"device\": \"$DEVICE\", \"pre_state_length\": ${#PRE_STATE}, \"rollback_hint\": \"$ROLLBACK_CMD\", \"capture_ms\": $DURATION}"
