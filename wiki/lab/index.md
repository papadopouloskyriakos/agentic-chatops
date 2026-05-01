# 03_Lab Reference Library

> ~5,200 files, ~10,724 MB. Compiled 2026-04-11 14:13 UTC.

Physical documentation, wiring diagrams, firmware, topology. Synced via Syncthing.

**WARNING:** 03_Lab is supplementary reference (Level 4 in the data trust hierarchy).
Always verify against live device config.

## Structure

| Directory | Files | Size (MB) | Subdirectories |
|-----------|-------|-----------|----------------|
| CH | 2 | 0.6 |  |
| Cross-Site | 266 | 53.5 | Designs, Knowledge, Network, Servers |
| GR | 1,171 | 3,174.1 | Inalan, Vodafone, gr, gr2 |
| NL | 2,291 | 4,876.8 | Changes, Firmware, Inventory, Network, Projects (+2 more) |
| NO | 0 | 0.0 |  |
| Research | 1,470 | 2,619.5 | Analog Computers, Baofeng_Ham_Radio, Cisco_Lab, Flipper Zero, HackRF Portapack H2 (+1 more) |

**Path:** `/app/reference-library/`
**Query tool:** `openclaw/skills/lab-lookup/lab-lookup.sh`

### Available Commands

- `port-map <hostname>` — switch port, VLAN, patchpanel location
- `nic-config <hostname>` — NIC interfaces, bonds, VLANs, IPs
- `vlan-devices <vlan_id>` — all devices on a VLAN
- `switch-ports <switch>` — all populated ports on a switch
- `docs <hostname>` — list reference files for a host
- `ups-pdu <site>` — UPS and PDU port assignments