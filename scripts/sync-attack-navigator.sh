#!/bin/bash
# Sync ATT&CK Navigator layer to nlsec01
# Regenerates the layer from mitre-mapping.json and copies to the Navigator container volume.
# Cron: 0 */12 * * * (every 12h, or after mitre-mapping.json changes)

set -uo pipefail

REPO="/app/claude-gateway"

# Load secrets from .env
ENV_FILE="$REPO/.env"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }
LAYER="$REPO/docs/attack-navigator-layer.json"
SCANNER_IP="10.0.181.X"
SSH_KEY="$HOME/.ssh/one_key"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -o BatchMode=yes"
SUDO_PASS="${SCANNER_SUDO_PASS:?SCANNER_SUDO_PASS env var not set}"

# Step 1: Regenerate layer from current mapping
python3 "$REPO/scripts/export-attack-navigator.py" 2>/dev/null || { echo "ERROR: export failed"; exit 1; }

# Step 2: Copy to scanner
scp $SSH_OPTS "$LAYER" "operator@$SCANNER_IP:/tmp/chatsecops-coverage.json" 2>/dev/null || { echo "ERROR: scp failed"; exit 1; }

# Step 3: Move into container volume
# Update both: host volume (persists across container recreate) and live nginx path
ssh $SSH_OPTS "operator@$SCANNER_IP" "echo '$SUDO_PASS' | sudo -S bash -c 'cp /tmp/chatsecops-coverage.json /opt/attack-navigator/layers/chatsecops-coverage.json'" 2>/dev/null | grep -v "^Warning\|sudo.*password"
# Container volume mount serves from /opt/attack-navigator/layers/ → /usr/share/nginx/html/assets/layers/
# No need to docker restart — nginx serves the file directly via bind mount

echo "[$(date -u +%FT%TZ)] Navigator layer synced ($(python3 -c "import json; print(len(json.load(open('$LAYER'))['techniques']))" 2>/dev/null) techniques)"
