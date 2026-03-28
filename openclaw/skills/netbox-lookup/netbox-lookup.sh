#!/bin/bash
# NetBox CMDB lookup script for OpenClaw
# Usage: ./netbox-lookup.sh <command> <argument>
# Commands: device, vmid, ip, vlans, site-vms, site-devices, interfaces, search
#
# Requires: NETBOX_URL, NETBOX_TOKEN in environment (loaded from .env)

set -euo pipefail

# Load credentials
if [ -f /home/node/.openclaw/workspace/.env ]; then
  source /home/node/.openclaw/workspace/.env
fi

NETBOX_URL="${NETBOX_URL:-https://netbox.example.net}"
NETBOX_TOKEN="${NETBOX_TOKEN:-}"

if [ -z "$NETBOX_TOKEN" ]; then
  echo "ERROR: NETBOX_TOKEN not set. Add it to .env"
  exit 1
fi

CMD="${1:-help}"
ARG="${2:-}"

# Helper: call NetBox API
nb_api() {
  local endpoint="$1"
  curl -sk \
    -H "Authorization: Token $NETBOX_TOKEN" \
    -H "Accept: application/json" \
    "${NETBOX_URL}/api/${endpoint}" 2>/dev/null
}

# Helper: format JSON output
nb_format() {
  python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    results = data.get('results', [data] if 'id' in data else [])
    count = data.get('count', len(results))
    print(f'Found {count} result(s):')
    print()
    for r in results:
        # Device/VM common fields
        name = r.get('name', r.get('display', ''))
        status = r.get('status', {})
        if isinstance(status, dict):
            status = status.get('label', status.get('value', ''))
        site = r.get('site', {})
        if isinstance(site, dict):
            site = site.get('name', '')
        role = r.get('role', r.get('device_role', {}))
        if isinstance(role, dict):
            role = role.get('name', '')
        cluster = r.get('cluster', {})
        if isinstance(cluster, dict):
            cluster = cluster.get('name', '')

        # IP address fields
        address = r.get('address', '')
        dns_name = r.get('dns_name', '')
        description = r.get('description', '')

        # Interface fields
        itype = r.get('type', {})
        if isinstance(itype, dict):
            itype = itype.get('label', '')

        # VLAN fields
        vid = r.get('vid', '')

        # Custom fields
        cf = r.get('custom_fields', {})

        # Print based on what's available
        if address:
            print(f'  {address:<25} dns={dns_name or \"-\":<30} desc={description or \"-\"}')
        elif vid:
            print(f'  VLAN {vid:<5} {name:<30} status={status}  desc={description or \"-\"}')
        elif itype:
            print(f'  {name:<25} type={itype:<15} desc={description or \"-\"}')
        else:
            line = f'  {name:<30} status={status}'
            if site:
                line += f'  site={site}'
            if role:
                line += f'  role={role}'
            if cluster:
                line += f'  cluster={cluster}'
            if cf:
                vmid = cf.get('vmid', cf.get('VMID', ''))
                pve = cf.get('pve_host', cf.get('PVE Host', ''))
                if vmid:
                    line += f'  vmid={vmid}'
                if pve:
                    line += f'  pve={pve}'
            print(line)
    if count > len(results):
        print(f'\n  ... and {count - len(results)} more (showing first {len(results)})')
except Exception as e:
    print(f'Parse error: {e}')
    print(sys.stdin.read() if hasattr(sys.stdin, 'read') else '')
" 2>/dev/null
}

case "$CMD" in
  device)
    [ -z "$ARG" ] && { echo "Usage: $0 device <hostname>"; exit 1; }
    echo "=== NetBox: Device/VM lookup for '$ARG' ==="
    # Try devices first
    RESULT=$(nb_api "dcim/devices/?name=${ARG}&limit=5")
    COUNT=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
    if [ "$COUNT" -gt 0 ]; then
      echo "Type: Physical Device"
      echo "$RESULT" | nb_format
    else
      # Try VMs
      RESULT=$(nb_api "virtualization/virtual-machines/?name=${ARG}&limit=5")
      COUNT=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
      if [ "$COUNT" -gt 0 ]; then
        echo "Type: Virtual Machine"
        echo "$RESULT" | nb_format
      else
        # Fuzzy search
        echo "Exact match not found. Trying fuzzy search..."
        RESULT=$(nb_api "dcim/devices/?name__ic=${ARG}&limit=10")
        COUNT=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
        RESULT2=$(nb_api "virtualization/virtual-machines/?name__ic=${ARG}&limit=10")
        COUNT2=$(echo "$RESULT2" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
        if [ "$COUNT" -gt 0 ]; then
          echo "Matching devices:"
          echo "$RESULT" | nb_format
        fi
        if [ "$COUNT2" -gt 0 ]; then
          echo "Matching VMs:"
          echo "$RESULT2" | nb_format
        fi
        if [ "$COUNT" -eq 0 ] && [ "$COUNT2" -eq 0 ]; then
          echo "Not found in NetBox (device or VM)."
        fi
      fi
    fi
    ;;

  vmid)
    [ -z "$ARG" ] && { echo "Usage: $0 vmid <vmid>"; exit 1; }
    echo "=== NetBox: VM by VMID '$ARG' ==="
    RESULT=$(nb_api "virtualization/virtual-machines/?cf_vmid=${ARG}&limit=5")
    echo "$RESULT" | nb_format
    ;;

  ip)
    [ -z "$ARG" ] && { echo "Usage: $0 ip <hostname>"; exit 1; }
    echo "=== NetBox: IP addresses for '$ARG' ==="
    # Try device IPs
    RESULT=$(nb_api "ipam/ip-addresses/?device=${ARG}&limit=50")
    COUNT=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)
    if [ "$COUNT" -gt 0 ]; then
      echo "$RESULT" | nb_format
    else
      # Try VM IPs
      RESULT=$(nb_api "ipam/ip-addresses/?virtual_machine=${ARG}&limit=50")
      echo "$RESULT" | nb_format
    fi
    ;;

  vlans)
    [ -z "$ARG" ] && { echo "Usage: $0 vlans <site-slug>"; exit 1; }
    echo "=== NetBox: VLANs at site '$ARG' ==="
    RESULT=$(nb_api "ipam/vlans/?site=${ARG}&limit=100&ordering=vid")
    echo "$RESULT" | nb_format
    ;;

  site-vms)
    [ -z "$ARG" ] && { echo "Usage: $0 site-vms <site-slug>"; exit 1; }
    echo "=== NetBox: Virtual Machines at site '$ARG' ==="
    RESULT=$(nb_api "virtualization/virtual-machines/?site=${ARG}&limit=100&ordering=name")
    echo "$RESULT" | nb_format
    ;;

  site-devices)
    [ -z "$ARG" ] && { echo "Usage: $0 site-devices <site-slug>"; exit 1; }
    echo "=== NetBox: Physical Devices at site '$ARG' ==="
    RESULT=$(nb_api "dcim/devices/?site=${ARG}&limit=100&ordering=name")
    echo "$RESULT" | nb_format
    ;;

  interfaces)
    [ -z "$ARG" ] && { echo "Usage: $0 interfaces <device-name>"; exit 1; }
    echo "=== NetBox: Interfaces on '$ARG' ==="
    RESULT=$(nb_api "dcim/interfaces/?device=${ARG}&limit=100&ordering=name")
    echo "$RESULT" | nb_format
    ;;

  search)
    [ -z "$ARG" ] && { echo "Usage: $0 search <keyword>"; exit 1; }
    echo "=== NetBox: Global search for '$ARG' ==="
    echo ""
    echo "--- Devices ---"
    nb_api "dcim/devices/?name__ic=${ARG}&limit=10" | nb_format
    echo ""
    echo "--- Virtual Machines ---"
    nb_api "virtualization/virtual-machines/?name__ic=${ARG}&limit=10" | nb_format
    echo ""
    echo "--- IP Addresses ---"
    nb_api "ipam/ip-addresses/?dns_name__ic=${ARG}&limit=10" | nb_format
    ;;

  help|*)
    echo "NetBox CMDB Lookup"
    echo ""
    echo "Usage: $0 <command> <argument>"
    echo ""
    echo "Commands:"
    echo "  device <hostname>     Find a device or VM by name"
    echo "  vmid <vmid>           Find VM by Proxmox VMID"
    echo "  ip <hostname>         Get IP addresses for a device/VM"
    echo "  vlans <site>          List VLANs at a site (nl, gr)"
    echo "  site-vms <site>       List all VMs at a site"
    echo "  site-devices <site>   List all physical devices at a site"
    echo "  interfaces <device>   List interfaces on a device"
    echo "  search <keyword>      Search across devices, VMs, and IPs"
    ;;
esac
