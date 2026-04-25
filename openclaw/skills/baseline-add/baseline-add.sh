#!/bin/bash
# baseline-add.sh — Add a finding to the scanner baseline
# Usage: ./skills/baseline-add/baseline-add.sh <target_ip> <port> <scanner> [baseline_type]
# baseline_type: ports (default), nuclei, tls
#
# SSHes to the correct scanner VM and appends the entry to the baseline file.
# Logs the change for audit trail.

set -uo pipefail

TARGET_IP="${1:-}"
PORT="${2:-}"
SCANNER="${3:-}"
BASELINE_TYPE="${4:-ports}"

SSH_KEY="/home/app-user/.ssh/one_key"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"
SUDO_PASS="${SCANNER_SUDO_PASS:?SCANNER_SUDO_PASS env var not set — add to .env}"

if [ -z "$TARGET_IP" ] || [ -z "$PORT" ] || [ -z "$SCANNER" ]; then
  echo "ERROR: Usage: baseline-add.sh <target_ip> <port> <scanner> [ports|nuclei|tls]"
  echo "Example: baseline-add.sh 203.0.113.X 8443 grsec01"
  exit 1
fi

# Map scanner hostname to IP
case "$SCANNER" in
  nlsec01) SCANNER_IP="10.0.181.X" ;;
  grsec01) SCANNER_IP="10.0.X.X" ;;
  *)
    echo "ERROR: Unknown scanner '$SCANNER'. Use nlsec01 or grsec01."
    exit 1
    ;;
esac

BASELINE_DIR="/opt/scans/baseline"
case "$BASELINE_TYPE" in
  ports)   BASELINE_FILE="$BASELINE_DIR/ports.txt" ;;
  nuclei)  BASELINE_FILE="$BASELINE_DIR/nuclei.txt" ;;
  tls)     BASELINE_FILE="$BASELINE_DIR/testssl-issues.txt" ;;
  *)
    echo "ERROR: Unknown baseline type '$BASELINE_TYPE'. Use ports, nuclei, or tls."
    exit 1
    ;;
esac

echo "=== Baseline Add ==="
echo "Target: $TARGET_IP"
echo "Port: $PORT"
echo "Scanner: $SCANNER ($SCANNER_IP)"
echo "Baseline type: $BASELINE_TYPE"
echo ""

# Step 1: Check current baseline for this entry
echo "--- Step 1: Checking current baseline ---"
CURRENT=$(ssh $SSH_OPTS "operator@$SCANNER_IP" "echo '$SUDO_PASS' | sudo -S cat $BASELINE_FILE 2>/dev/null" 2>&1 | grep -v "^Warning\|sudo.*password")

if echo "$CURRENT" | grep -q "$PORT.*$TARGET_IP\|$TARGET_IP.*$PORT"; then
  echo "Port $PORT for $TARGET_IP is ALREADY in baseline. No action needed."
  exit 0
fi
echo "Port $PORT for $TARGET_IP is NOT in baseline. Adding..."

# Step 2: Get the current service info from latest scan
echo ""
echo "--- Step 2: Getting service info from latest scan ---"
SERVICE_INFO=$(ssh $SSH_OPTS "operator@$SCANNER_IP" "echo '$SUDO_PASS' | sudo -S bash -c 'LATEST=\$(ls -t /opt/scans/weekly/ 2>/dev/null | head -1); grep \"$PORT/tcp\" /opt/scans/weekly/\$LATEST/nmap.txt 2>/dev/null | head -1 || echo \"$PORT/tcp open unknown\"'" 2>&1 | grep -v "^Warning\|sudo.*password" | head -1)
echo "Service: $SERVICE_INFO"

# Step 3: Append to baseline
echo ""
echo "--- Step 3: Appending to baseline ---"
# For ports baseline, append the nmap-style line
ENTRY="$SERVICE_INFO"
EXPIRY_DATE=$(date -u -d '+90 days' +%F 2>/dev/null || date -u -v+90d +%F 2>/dev/null || echo "2026-06-28")
if [ -z "$ENTRY" ] || [ "$ENTRY" = "$PORT/tcp open unknown" ]; then
  ENTRY="$PORT/tcp  open  unknown  # Baseline: $(date -u +%F) Expires: $EXPIRY_DATE Added-by: baseline-add"
else
  ENTRY="$ENTRY  # Baseline: $(date -u +%F) Expires: $EXPIRY_DATE Added-by: baseline-add"
fi

ssh $SSH_OPTS "operator@$SCANNER_IP" "echo '$SUDO_PASS' | sudo -S bash -c 'echo \"$ENTRY\" >> $BASELINE_FILE'" 2>&1 | grep -v "^Warning\|sudo.*password"
echo "Added: $ENTRY"

# Step 4: Verify
echo ""
echo "--- Step 4: Verifying ---"
VERIFY=$(ssh $SSH_OPTS "operator@$SCANNER_IP" "echo '$SUDO_PASS' | sudo -S grep '$PORT' $BASELINE_FILE 2>/dev/null" 2>&1 | grep -v "^Warning\|sudo.*password")
if [ -n "$VERIFY" ]; then
  echo "Verified: $VERIFY"
  echo ""
  echo "Baseline updated successfully. Tomorrow's scan will NOT flag port $PORT on $TARGET_IP."
else
  echo "WARNING: Verification failed — check baseline file manually."
fi

# Step 5: Log the change
echo ""
TRIAGE_LOG="/app/cubeos/claude-context/triage.log"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
  app-user@nl-claude01 \
  "echo '$(date -u +%FT%TZ)|${TARGET_IP}|baseline_add_port_${PORT}|${SCANNER}|baseline_updated|0|0|none' >> '$TRIAGE_LOG'" 2>/dev/null || true
echo "Logged to triage.log."
