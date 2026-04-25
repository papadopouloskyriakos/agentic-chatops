# nl-pve02

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-pve02 | Proxmox hypervisor (**VM on nl-nas01**) | `ssh nl-pve02` |

**nl:native/pve/CLAUDE.md**
- | nl-pve02 | Ryzen V1500B | 8C/8T | 16.8 GB | None (direct) | 36.5 GB ext4 | Low-tier, VM on Synology |

**nl:pve/CLAUDE.md**
- | nl-pve02 | Synology DS1621+ VM | Ryzen V1500B (8C) | 16 GB | NAS iSCSI | 7 | 0 |
- ├── nl-pve02/

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Service up/down. |  | Resolved via Claude session IFRNLLEI01PRD-338 | 0.8 |

## Lessons Learned

- **IFRNLLEI01PRD-338**: nl-pve02 service flaps during iSCSI storage operations or kernel module reloads. This host has the longest uptime (105+ days) and is pending kernel maintenance.

## Related Memory Entries

- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.

## Physical Documentation (03_Lab)

- `03_Lab/NL/Servers/nl-pve02/20241203_nl-pve02_interfaces.txt`
- `03_Lab/NL/Servers/nl-pve02/20250515_nl-pve02_ansible_inventory.yaml`
- `03_Lab/NL/Servers/nl-pve02/lxc/VMID_REDACTED - nlgitea01/20241104_nlgitea01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/VMID_REDACTED - nlsemaphore01/20241104_nlsemaphore01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/VMID_REDACTED - nlsemaphore01/playbooks/apt.yml`
- `03_Lab/NL/Servers/nl-pve02/lxc/125 - nlmeshcentral01/20240410_nlmeshcentral01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230919-1905_nlbaikal01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Dutch Lessons.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Family.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Fitness.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- F∴M∴.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Global Schema Placeholder.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Health.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- PT1-OT - LAB - DOWNTIME.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Personal.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Project Baltimore.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Social.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Trips.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Work.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/baikal_personal_cal_configs.txt`

*Compiled: 2026-04-11 14:13 UTC*