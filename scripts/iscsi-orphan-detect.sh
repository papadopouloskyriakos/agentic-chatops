#!/bin/bash
# iscsi-orphan-detect.sh — Detect orphaned iSCSI initiator sessions on GR K8s workers
# Runs hourly via cron. Compares active iSCSI sessions against Bound K8s PVs.
# Posts to Matrix #infra-gr-prod if orphans found.
#
# Usage: ./iscsi-orphan-detect.sh [--clean] [--site nl|gr]
#   --clean   Attempt to clean up orphaned sessions (logout + delete node record + send_targets)
#   --site    Site to check (default: gr)

set -euo pipefail

CLEAN=false
SITE="gr"
K8S_CONTEXT="gr"
PVE_RELAY="gr-pve01"
WORKERS="grk8s-node01 grk8s-node02 grk8s-node03"
ISCSI_PORTAL="10.0.188.X:3260"
MATRIX_ROOM="!NKosBPujbWMevzHaaM:matrix.example.net"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clean) CLEAN=true; shift ;;
    --site)
      SITE="$2"; shift 2
      if [[ "$SITE" == "nl" ]]; then
        K8S_CONTEXT="kubernetes-admin@kubernetes"
        PVE_RELAY=""
        WORKERS="nlk8s-node01 nlk8s-node02 nlk8s-node03 nlk8s-node04"
        ISCSI_PORTAL="10.0.181.X:3260"
        MATRIX_ROOM="!AOMuEtXGyzGFLgObKN:matrix.example.net"
      fi
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

SSH_KEY="$HOME/.ssh/one_key"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes"

# Helper: SSH to a K8s node (via pve relay for GR)
ssh_node() {
  local node="$1"; shift
  local result
  if [[ "$SITE" == "gr" ]]; then
    result=$(ssh $SSH_OPTS -i "$SSH_KEY" root@nl-pve01 \
      "ssh $SSH_OPTS root@${PVE_RELAY} 'ssh $SSH_OPTS root@${node} \"$*\"'" 2>&1)
  else
    result=$(ssh $SSH_OPTS -i "$SSH_KEY" root@"${node}" "$@" 2>&1)
  fi
  local rc=$?
  if [[ $rc -ne 0 ]] && echo "$result" | grep -qi "permission denied\|connection refused\|timed out\|no route"; then
    echo "SSH_ERROR: $node unreachable ($rc)" >&2
    return 1
  fi
  echo "$result"
  return $rc
}

# Step 1: Get all active iSCSI PVs (Bound + Released have legitimate sessions)
echo "Checking K8s PVs (context: $K8S_CONTEXT)..."
ACTIVE_PVCS=$(kubectl --context "$K8S_CONTEXT" get pv -o json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for pv in data['items']:
    phase = pv['status']['phase']
    if phase in ('Bound', 'Released'):
        sc = pv['spec'].get('storageClassName', '')
        if 'iscsi' in sc:
            print(pv['metadata']['name'])
" 2>/dev/null || true)

if [[ -z "$ACTIVE_PVCS" ]]; then
  echo "WARNING: Could not retrieve PVs from K8s. Aborting."
  exit 1
fi

ACTIVE_COUNT=$(echo "$ACTIVE_PVCS" | wc -l)
echo "Found $ACTIVE_COUNT active iSCSI PVs (Bound + Released)"

# Step 2: Check each worker node for iSCSI sessions
ORPHANS=""
ORPHAN_COUNT=0
TOTAL_SESSIONS=0

SSH_FAILURES=0

for node in $WORKERS; do
  echo "Checking $node..."
  SESSIONS=$(ssh_node "$node" "iscsiadm -m session 2>/dev/null" 2>/dev/null) || true

  if [[ -z "$SESSIONS" ]] || echo "$SESSIONS" | grep -q "SSH_ERROR"; then
    if echo "$SESSIONS" 2>/dev/null | grep -q "SSH_ERROR"; then
      echo "  WARNING: Could not reach $node via SSH — skipping (results incomplete)"
      SSH_FAILURES=$((SSH_FAILURES + 1))
    else
      echo "  No iSCSI sessions"
    fi
    continue
  fi

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    TOTAL_SESSIONS=$((TOTAL_SESSIONS + 1))

    # Extract PVC name from IQN (last component after colon)
    PVC_NAME=$(echo "$line" | grep -oP 'pvc-[0-9a-f-]+' || true)
    [[ -z "$PVC_NAME" ]] && continue

    # Check if this PVC is in the active PV list (Bound or Released)
    if ! echo "$ACTIVE_PVCS" | grep -q "^${PVC_NAME}$"; then
      ORPHAN_COUNT=$((ORPHAN_COUNT + 1))
      IQN=$(echo "$line" | grep -oP 'iqn\.[^\s]+' || true)
      ORPHANS="${ORPHANS}${node}|${PVC_NAME}|${IQN}\n"
      echo "  ORPHAN: $PVC_NAME on $node"

      if [[ "$CLEAN" == "true" ]]; then
        echo "  Cleaning up $PVC_NAME on $node..."
        PORTAL_DIR=$(echo "$ISCSI_PORTAL" | tr ':' ',')

        # Step 1: Try normal logout
        ssh_node "$node" "iscsiadm -m node -T ${IQN} -p ${ISCSI_PORTAL} --logout" 2>/dev/null || true

        # Step 2: Remove all persistent config (prevents re-creation on iscsid restart)
        ssh_node "$node" "rm -rf /etc/iscsi/nodes/${IQN} /etc/iscsi/send_targets/${PORTAL_DIR}/${IQN}*" 2>/dev/null || true

        # Step 3: Try iscsiadm delete (may fail if kernel session is stuck)
        ssh_node "$node" "iscsiadm -m node -T ${IQN} -p ${ISCSI_PORTAL} -o delete" 2>/dev/null || true

        # Step 4: Kill stuck kernel sessions by finding the session ID and setting recovery_tmo=1
        # This forces the kernel to tear down FREE-state sessions that iscsiadm can't logout
        SID=$(ssh_node "$node" "iscsiadm -m session 2>/dev/null | grep '${IQN}' | grep -oP '\\[\\K[0-9]+'" 2>/dev/null || true)
        if [[ -n "$SID" ]]; then
          echo "  Kernel session $SID still active — attempting recovery_tmo teardown..."
          ssh_node "$node" "echo 1 > /sys/class/iscsi_session/session${SID}/recovery_tmo" 2>/dev/null || true
          sleep 3
          # Verify
          STILL=$(ssh_node "$node" "iscsiadm -m session 2>/dev/null | grep -c '${IQN}'" 2>/dev/null || echo "0")
          if [[ "$STILL" -gt 0 ]]; then
            echo "  WARNING: Kernel session stuck in FREE state. Node reboot required to clear."
          else
            echo "  Kernel session cleared."
          fi
        else
          echo "  Cleaned successfully."
        fi
      fi
    fi
  done <<< "$SESSIONS"
done

echo ""
echo "Summary: $TOTAL_SESSIONS total sessions, $ORPHAN_COUNT orphans across $SITE site"
if [[ $SSH_FAILURES -gt 0 ]]; then
  echo "WARNING: $SSH_FAILURES node(s) unreachable via SSH — results may be incomplete"
fi

# Step 3: Post to Matrix if orphans found
if [[ $ORPHAN_COUNT -gt 0 ]]; then
  # Build message
  ORPHAN_LIST=""
  while IFS='|' read -r node pvc iqn; do
    [[ -z "$node" ]] && continue
    ORPHAN_LIST="${ORPHAN_LIST}• ${pvc} on ${node}\n"
  done < <(echo -e "$ORPHANS")

  MSG="⚠️ <b>iSCSI Orphan Detection (${SITE^^})</b><br><br>${ORPHAN_COUNT} orphaned iSCSI session(s) found — initiator sessions with no matching Bound PV:<br><pre>$(echo -e "$ORPHAN_LIST")</pre>These sessions spam dmesg on the iSCSI target host. Clean up with:<br><code>scripts/iscsi-orphan-detect.sh --clean --site ${SITE}</code><br>Stuck kernel sessions require a node reboot after cleanup."

  # Load Matrix token (same env var as gateway-watchdog.sh)
  MATRIX_TOKEN="${MATRIX_CLAUDE_TOKEN:-}"

  if [[ -n "$MATRIX_TOKEN" ]]; then
    TXN_ID="iscsi-orphan-$(date +%s%N)-$$"
    curl -sf --max-time 10 -X PUT \
      "https://matrix.example.net/_matrix/client/v3/rooms/${MATRIX_ROOM}/send/m.room.message/${TXN_ID}" \
      -H "Authorization: Bearer ${MATRIX_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "{\"msgtype\": \"m.notice\", \"format\": \"org.matrix.custom.html\", \"formatted_body\": \"${MSG}\", \"body\": \"iSCSI Orphan Detection: ${ORPHAN_COUNT} orphaned session(s) found on ${SITE^^} site\"}" \
      >/dev/null 2>&1 && echo "Posted to Matrix" || echo "Matrix post failed (non-critical)"
  else
    echo "No MATRIX_TOKEN found, skipping Matrix notification"
  fi

  exit 2  # exit 2 = orphans found (for monitoring)
fi

echo "No orphans found."
exit 0
