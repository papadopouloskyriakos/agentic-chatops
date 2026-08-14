#!/bin/bash
# Lab reference lookup — queries 03_Lab for physical layer infrastructure context.
# Usage: ./skills/lab-lookup/lab-lookup.sh <command> <arg>
#
# Commands:
#   port-map <hostname>      Switch port, VLAN, patchpanel for a device
#   nic-config <hostname>    NIC interfaces, bonds, VLANs, IPs
#   vlan-devices <vlan_id>   All devices on a VLAN
#   switch-ports <switch>    All populated ports on a switch
#   docs <hostname>          List reference files in 03_Lab for a host
#   ups-pdu <site>           UPS and PDU port assignments (nl or gr)
#
# Runs locally on nl-claude01, or SSHes there from OpenClaw container.

set -uo pipefail

COMMAND="${1:?Usage: lab-lookup.sh <command> <arg>}"
ARG="${2:?Usage: lab-lookup.sh <command> <arg>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect environment and run appropriately
if [ -f "/app/reference-library/Cross-Site/network_info.xlsx" ] && python3 -c "import openpyxl" 2>/dev/null; then
  # Local execution (nl-claude01)
  python3 "$SCRIPT_DIR/lab-lookup.py" "$COMMAND" "$ARG" 2>/dev/null
else
  # SSH fallback (OpenClaw container or any machine without openpyxl)
  SSH_KEY="${SSH_KEY:-/home/app-user/.ssh/one_key}"
  [ ! -f "$SSH_KEY" ] && SSH_KEY="$HOME/.ssh/one_key"
  [ ! -f "$SSH_KEY" ] && SSH_KEY="$HOME/.ssh/id_rsa"

  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
    -i "$SSH_KEY" app-user@nl-claude01 \
    "python3 ~/gitlab/n8n/claude-gateway/openclaw/skills/lab-lookup/lab-lookup.py '$COMMAND' '$ARG'" 2>/dev/null
fi
