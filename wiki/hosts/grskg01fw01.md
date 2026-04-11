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

**gateway:CLAUDE.md**
- - **gr-fw01 (GR):** `event timer watchdog time 590400` (~6d 20h from last boot)

## BGP Routing (2026-04-10)

**7 BGP peers** — all inter-site routing via BGP, zero static inter-site routes:

| Peer | IP | AS | Role | LP |
|------|-----|-----|------|-----|
| NL ASA Freedom VTI | 10.255.200.10 | 65000 | Direct to NL (primary) | 200 |
| NL ASA xs4all VTI | 10.255.200.0 | 65000 | Direct to NL (dormant) | 150 |
| GR FRR01 | 10.0.X.X | 65000 | Route reflector (transit backup) | 100 |
| GR FRR02 | 10.0.X.X | 65000 | Route reflector (transit backup) | 100 |
| GR K8s worker1-3 | 10.0.58.X-22 | 65001 | Cilium MetalLB VIPs | — |

**Route-maps:** FREEDOM_IN, XS4ALL_IN, FRR_TRANSIT_IN, BLOCK_SITE_TO_CILIUM.

**SSH access:** Via stepstone only — `ssh -i ~/.ssh/one_key -p 2222 app-user@203.0.113.X` then netmiko to 10.0.X.X.

**Troubleshooting:** `show bgp ipv4 unicast summary`, `show route bgp`, `show crypto ipsec sa | include interface|pkts dec`. After route changes: `clear conn address <subnet> netmask <mask>`.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Service up/down | EEM watchdog timer auto-reload | EEM watchdog reboot (590400s timer, ~6d20h cycle). GR total  | 0.9 |

## Related Memory Entries

- **ASA Weekly Reboot Suppression** (project): EEM watchdog timers on both ASAs auto-reboot weekly; 4-layer suppression prevents false alerts
- **GR ASA SSH requires stepstone via gr-pve01** (feedback): SSH to gr-fw01 only works via gr-pve01 as a jump host — direct SSH from NL is rejected (connection reset).
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **OOB Access via PiKVM + Cloudflare Tunnel** (project): BROKEN (2026-03-21) — PiKVM bricked by forced package upgrade. Requires physical access to GR site to recover. Cloudflare tunnel config still exists but PiKVM is offline.
- **VTI Migration Completed 2026-04-09** (project): ASA crypto-map VPN replaced with VTI tunnels. Dual-WAN. strongSwan swanctl+XFRM. BGP transit overlay. E2E failover proven.

*Compiled: 2026-04-09 06:53 UTC*