# gr-fw01

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:edge/CLAUDE.md**
- | gr-fw01 | 203.0.113.X (InAlan DHCP) | 10.0.58.X | InAlan (primary), LTE (failover) | frr01 (.15.3), frr02 (.15.4) | K8s .58.20, .58.21, .58.22 (3 nodes) |
- **GR ASA single-WAN:** gr-fw01 has one ISP (InAlan, DHCP on `outside_inalan`) with LTE backup (10.0.X.X/30, metric 10). SLA monitor pings NL ASA (203.0.113.X).
- **IPsec tunnel groups on gr-fw01:**
- **GR site (gr-fw01):**
- │  NL ASA (nl-fw01)│◄══════►│  GR ASA (gr-fw01)│

**gr:CLAUDE.md**
- | Find a device/VM | `netbox_get_objects(object_type="dcim.device", filters={"name": "gr-fw01"}, fields=["id","name","status","site","role"])` | `curl` to LibreNMS or `grep` through configs |
- | Get IP assignments | `netbox_get_objects(object_type="ipam.ipaddress", filters={"device": "gr-fw01"}, fields=["address","dns_name","description"])` | `grep` through IaC files |
- - **Hostnames**: `gr<role><number>` (e.g., `gr-fw01` = GR firewall 01)
- gr   skg01  fw    01     → gr-fw01 (firewall)

**gr:network/CLAUDE.md**
- | gr-fw01 | Firewall | Cisco ASA | Core firewall, NAT, VPN, BGP |
- │   │   └── gr-fw01
- ## GR ASA (gr-fw01)
- - Do not modify IPsec tunnel configuration on gr-fw01 without coordinating with the remote peers (NL ASA, CH VPS, NO VPS) — tunnels must match on both ends

**gr:edge/CLAUDE.md**
- ### ASA Firewall (gr-fw01)
- | Config backup | `network/oxidized/Firewall/gr-fw01` |
- 3. **Check ASA BGP:** `show bgp summary` on gr-fw01 — verify peers .58.20-22 and .15.3-4
- 1. **Check ASA crypto sessions:** `show crypto ipsec sa` on gr-fw01
- - Do not modify IPsec tunnel configuration on gr-fw01 without coordinating with the remote peers (NL ASA, CH VPS, NO VPS)

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-10 | BGP peer down — Freedom VTI to NL (10.255.200.X) | NL ASA Freedom VTI tunnel is down. GR ASA sees BGP session d | GR auto-failovers to FRR transit (LP 100) via VPS in ~30s. V | 0.9 |
| 2026-04-03 | Service up/down | EEM watchdog timer auto-reload | EEM watchdog reboot (590400s timer, ~6d20h cycle). GR total  | 0.9 |

## Lessons Learned

- **SCHEDULED-ASA-GR-001**: GR ASA EEM watchdog reboot (~6d20h cycle). GR total outage + NL VPN tunnel drop. Cross-site alerts expected. Auto-recovery in 5-10 min. See SCHEDULED-ASA-NL-001 lesson.

## Related Memory Entries

- **ASA Weekly Reboot — DISABLED** (project): EEM watchdog auto-reboot REMOVED from both ASAs on 2026-04-10. Reboot watcher cron disabled.
- **ASA floating-conn for route changes** (feedback): Enable timeout floating-conn on ASA to auto-teardown stale connections when BGP/routing changes. Use netmiko for ASA automation, not expect.
- **GR ASA SSH requires stepstone via gr-pve01** (feedback): SSH to gr-fw01 only works via gr-pve01 as a jump host — direct SSH from NL is rejected (connection reset).
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **VPN Mesh Stats API** (project): Portfolio mesh-stats webhook — live SSH tunnel status, ping latency, RIPE BGP, 9 unique tunnels. Script at scripts/vpn-mesh-stats.py.
- **NAT/PAT Audit 2026-04-09** (project): Tri-WAN PAT completed on NL ASA (28 rules). GR ASA NAT_dmz_servers02 /29→/27 fix. Both saved.
- **OOB Access via PiKVM + Cloudflare Tunnel** (project): BROKEN (2026-03-21) — PiKVM bricked by forced package upgrade. Requires physical access to GR site to recover. Cloudflare tunnel config still exists but PiKVM is offline.
- **VTI Migration + BGP Site Subnet Routing** (project): VTI tunnels (2026-04-09) + full BGP inter-site routing (2026-04-10). No static inter-site routes. 3-tier LP failover: Freedom 200, xs4all 150, FRR transit 100.

*Compiled: 2026-04-11 14:13 UTC*