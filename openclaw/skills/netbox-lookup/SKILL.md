---
name: netbox-lookup
description: Look up infrastructure devices, VMs, IPs, VLANs, and interfaces from NetBox CMDB. Use this skill FIRST for any question about what a host is, where it lives, its IP, VLAN, or role. Covers all NL and GR sites (310+ objects). Preferred over LibreNMS for device identification.
allowed-tools: Bash
user-invocable: true
metadata:
  openclaw:
    always: true
---

# NetBox Infrastructure Lookup

NetBox is the source of truth for device/VM identity, IP addressing, VLANs, and cabling across all sites.

## WHEN to use this skill (ALWAYS for these):

- "what is nl-gpu01?" -> run `./skills/netbox-lookup/netbox-lookup.sh device nl-gpu01`
- "what VM has VMID VMID_REDACTED?" -> run `./skills/netbox-lookup/netbox-lookup.sh vmid VMID_REDACTED`
- "what IPs does gr-fw01 have?" -> run `./skills/netbox-lookup/netbox-lookup.sh ip gr-fw01`
- "what VLANs at gr?" -> run `./skills/netbox-lookup/netbox-lookup.sh vlans gr`
- "list all GR VMs" -> run `./skills/netbox-lookup/netbox-lookup.sh site-vms gr`
- "list all NL devices" -> run `./skills/netbox-lookup/netbox-lookup.sh site-devices nl`
- "what interfaces on nl-sw01?" -> run `./skills/netbox-lookup/netbox-lookup.sh interfaces nl-sw01`
- Any question about device identity, location, role, IP, VLAN, or cabling

## HOW to use

Run the appropriate command using the `exec` tool:

```bash
# Find a device or VM by name
./skills/netbox-lookup/netbox-lookup.sh device <hostname>

# Find VM by Proxmox VMID
./skills/netbox-lookup/netbox-lookup.sh vmid <vmid>

# Get IP addresses for a device/VM
./skills/netbox-lookup/netbox-lookup.sh ip <hostname>

# List VLANs at a site
./skills/netbox-lookup/netbox-lookup.sh vlans <site>

# List all VMs at a site
./skills/netbox-lookup/netbox-lookup.sh site-vms <site>

# List all physical devices at a site
./skills/netbox-lookup/netbox-lookup.sh site-devices <site>

# List interfaces on a device
./skills/netbox-lookup/netbox-lookup.sh interfaces <device>

# Search for anything by keyword
./skills/netbox-lookup/netbox-lookup.sh search <keyword>
```

## CRITICAL RULES

1. **RUN THE TOOL FIRST.** Do NOT answer from memory. NetBox is the source of truth for infrastructure identity.
2. **Do NOT escalate lookups.** Questions about device info, IPs, VLANs are YOUR job (Tier 1).
3. **Do NOT recommend the command to the user.** YOU run it yourself using the `exec` tool.
4. **Use this BEFORE infra-triage.sh** when you need to identify what a host is.
