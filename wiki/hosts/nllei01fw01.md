# nl-fw01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-fw01 | ASA 5508-X | ASA 9.16(4) | 10.0.181.X | Netmiko | Core firewall, NAT, VPN, BGP |
- | `asa` | firewall | 1 | Cisco ASA5508 firewall — check config in `network/configs/Firewall/nl-fw01` |
- 5. Check firewall DHCP reservations: `grep <ip> network/configs/Firewall/nl-fw01`
- Available devices: nl-sw01, nlrtr01, nl-fw01, nllte01, nlap01-04.
- | nl-fw01 | 10.0.181.X | ASA | ASA5508 | password (operator) |

**nl:network/CLAUDE.md**
- | nl-fw01 | ASA 5508-X | ASA 9.16(4) | 10.0.181.X | Core firewall, NAT, VPN, BGP | Netmiko (ASA prompts incompatible with NAPALM) |
- │   ├── Firewall/           # nl-fw01
- **Tested against the real nl-fw01 config (2031 lines):** parses all 1964 config lines, recognizes all ASA constructs (304 ACLs, 203 object networks, 289 crypto entries, 87 NAT rules, 32 interfaces, 7 tunnel-groups), and produces zero remediation when comparing identical configs.
- **nl-fw01 (ASA 5508-X, ASA 9.16(4)):**

**nl:edge/CLAUDE.md**
- | nl-fw01 | 203.0.113.X (Freedom PPPoE) | 10.0.181.X | Freedom (primary), XS4ALL (backup), LTE (failover) | frr01 (.192.3), frr02 (.192.4) | K8s .85.20, .85.21, .85.22, .85.23 (4 nodes) |
- **NL ASA dual-WAN:** nl-fw01 has **two independent ISP uplinks** (Freedom and XS4ALL, both PPPoE) with **identical crypto maps on both interfaces**. This provides ISP-level redundancy for the IPsec mesh — if Freedom fails, all tunnels failover to XS4ALL automatically. SLA monitor pings GR ASA (203.0.113.X) every 10s to detect failures. LTE (10.0.X.X/30) is a tertiary failover with metric 20.
- **Inter-site IPsec (ASA ↔ ASA):** The two ASAs maintain a massive site-to-site IPsec mesh between them — **38+ crypto map entries per WAN interface** on nl-fw01, covering every VLAN-to-VLAN pair between sites (management, K8s, DMZ, NFS, corosync, servers, CCTV, IoT, guest, rooms). This is the backbone that enables cross-site services (Galera replication, DRBD sync, Cilium ClusterMesh, FreeIPA replication, etc.).
- **IPsec tunnel groups on nl-fw01:**
- **NL site (nl-fw01):**

**nl:native/synology/CLAUDE.md**
- **nl-nas02**: No iptables module loaded. No DSM firewall active. Relies entirely on upstream ASA firewall (nl-fw01).

**gr:edge/CLAUDE.md**
- - **NL ASA config:** `infrastructure/nl/production/network/configs/Firewall/nl-fw01`

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-10 | BGP peer down — Freedom VTI to GR (10.255.200.X) | Freedom VTI tunnel (Tunnel4) is down. Check: show interface  | BGP auto-failover to FRR transit (LP 100) in ~30s. Verify: s | 0.9 |
| 2026-04-10 | xs4all VTI tunnel UP but zero ESP traffic (Bytes Rx: 0) | EXPECTED BEHAVIOR. ASA tunnel source interface does NOT over | No action needed. xs4all activates only when Freedom ISP goe | 1.0 |
| 2026-04-10 | Cross-site corosync/NFS blackhole after BGP route change | Stale ASA connection table entries from old forwarding path. | Clear connections on BOTH ASAs: clear conn address 192.168.8 | 0.9 |
| 2026-04-10 | Freedom ISP PPPoE down — full BGP failover | Freedom PPPoE died. SLA track 1 detects in ~15s. Default rou | Automatic failover. Verify: 1) show track 1 (DOWN), 2) show  | 0.9 |
| 2026-04-08 | Service up/down | Freedom ISP PPPoE session dropped. ASA outside_freedom (Po1. | xs4all WAN carries all traffic automatically (full tunnel pa | 1.0 |
| 2026-04-03 | Service up/down | EEM watchdog timer auto-reload | Weekly EEM watchdog reboot (604800s timer). Total NL outage  | 0.9 |
| 2026-04-03 | Devices up/down | EEM watchdog timer auto-reload | Weekly EEM watchdog reboot. Cascading device-down alerts exp | 0.9 |

## Lessons Learned

- **SCHEDULED-ASA-NL-002**: ASA EEM watchdog reboots cause cascading device-down alerts across all site hosts. Expected and suppressed by asa-reboot-watch.sh. Auto-recovery in 5-10 min. See SCHEDULED-ASA-NL-001 lesson.
- **SCHEDULED-ASA-NL-001**: ASA EEM watchdog reboots are scheduled and expected. NL: 604800s (7d), GR: 590400s (~6d20h). Reboot times drift ~5min/cycle. All alerts during the window are suppressed by asa-reboot-watch.sh. No action needed — auto-recovery in 5-10 min.
- **IFRNLLEI01PRD-381**: Freedom ISP PPPoE outages cause cascading NL+GR alerts (up/down on all NL devices + GR VPN-dependent devices). First check: show vpdn pppinterface on NL ASA. xs4all WAN takes over automatically via SLA track failover. Wait 15 min before investigating — most services self-recover.

## Related Memory Entries

- **ASA Weekly Reboot — DISABLED** (project): EEM watchdog auto-reboot REMOVED from both ASAs on 2026-04-10. Reboot watcher cron disabled.
- **Dual-WAN VPN full parity (Freedom + xs4all)** (project): Both NL WANs have full S2S tunnel coverage. Freedom PPPoE outage auto-handled via xs4all failover, QoS cron, SMS alerting, and trained triage scripts.
- **ASA floating-conn for route changes** (feedback): Enable timeout floating-conn on ASA to auto-teardown stale connections when BGP/routing changes. Use netmiko for ASA automation, not expect.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **VPN Mesh Stats API** (project): Portfolio mesh-stats webhook — live SSH tunnel status, ping latency, RIPE BGP, 9 unique tunnels. Script at scripts/vpn-mesh-stats.py.
- **NAT/PAT Audit 2026-04-09** (project): Tri-WAN PAT completed on NL ASA (28 rules). GR ASA NAT_dmz_servers02 /29→/27 fix. Both saved.
- **VTI Migration + BGP Site Subnet Routing** (project): VTI tunnels (2026-04-09) + full BGP inter-site routing (2026-04-10). No static inter-site routes. 3-tier LP failover: Freedom 200, xs4all 150, FRR transit 100.

*Compiled: 2026-04-11 14:13 UTC*