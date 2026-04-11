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
- **NL ASA dual-WAN:** nl-fw01 has **two independent ISP uplinks** (Freedom and XS4ALL, both PPPoE) with **dual VTI tunnels per peer** (6 total: Tunnel1-3 on xs4all, Tunnel4-6 on Freedom). SLA track 1 monitors Freedom BNG; failover switches default route to xs4all (metric 10). LTE (10.0.X.X/30) is a tertiary failover with metric 20.
- **Inter-site VTI (ASA ↔ ASA + VPS):** Route-based VTI tunnels (migrated from crypto-maps 2026-04-09). 9 unique tunnels total: 6 on NL ASA, 2 on GR ASA, 1 VPS-to-VPS (NO↔CH). Point-to-point IPs from 10.255.200.0/24. Old crypto-maps unbound but in running config for rollback.
- **IPsec tunnel groups on nl-fw01:**
- **NL site (nl-fw01):**

**nl:native/synology/CLAUDE.md**
- **nl-nas02**: No iptables module loaded. No DSM firewall active. Relies entirely on upstream ASA firewall (nl-fw01).

**gr:edge/CLAUDE.md**
- - **NL ASA config:** `infrastructure/nl/production/network/configs/Firewall/nl-fw01`

**gateway:CLAUDE.md**
- - **nl-fw01 (NL):** `event timer watchdog time 604800` (7 days from last boot)

## BGP Routing (2026-04-10)

**8 BGP peers** — all inter-site routing via BGP, zero static inter-site routes:

| Peer | IP | AS | Role | LP |
|------|-----|-----|------|-----|
| GR ASA Freedom VTI | 10.255.200.11 | 65000 | Direct to GR (primary) | 200 |
| GR ASA xs4all VTI | 10.255.200.1 | 65000 | Direct to GR (dormant) | 150 |
| NL FRR01 | 10.0.X.X | 65000 | Route reflector (transit backup) | 100 |
| NL FRR02 | 10.0.X.X | 65000 | Route reflector (transit backup) | 100 |
| NL K8s worker1-4 | 10.0.X.X-23 | 65001 | Cilium MetalLB VIPs | — |

**Route-maps:** FREEDOM_IN, XS4ALL_IN, FRR_TRANSIT_IN, BLOCK_SITE_TO_CILIUM.

**Troubleshooting:** `show bgp ipv4 unicast summary` (peers), `show route bgp` (installed routes), `show crypto ipsec sa | include interface|pkts dec` (tunnel health). After route changes: `clear conn address <subnet> netmask <mask>`.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-08 | Service up/down | Freedom ISP PPPoE session dropped. ASA outside_freedom (Po1. | xs4all WAN carries all traffic automatically (full tunnel pa | 1.0 |
| 2026-04-03 | Service up/down | EEM watchdog timer auto-reload | Weekly EEM watchdog reboot (604800s timer). Total NL outage  | 0.9 |
| 2026-04-03 | Devices up/down | EEM watchdog timer auto-reload | Weekly EEM watchdog reboot. Cascading device-down alerts exp | 0.9 |

## Related Memory Entries

- **ASA Weekly Reboot Suppression** (project): EEM watchdog timers on both ASAs auto-reboot weekly; 4-layer suppression prevents false alerts
- **Dual-WAN VPN full parity (Freedom + xs4all)** (project): Both NL WANs have full S2S tunnel coverage. Freedom PPPoE outage auto-handled via xs4all failover, QoS cron, SMS alerting, and trained triage scripts.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **VTI Migration Completed 2026-04-09** (project): ASA crypto-map VPN replaced with VTI tunnels. Dual-WAN. strongSwan swanctl+XFRM. BGP transit overlay. E2E failover proven.

*Compiled: 2026-04-09 06:53 UTC*