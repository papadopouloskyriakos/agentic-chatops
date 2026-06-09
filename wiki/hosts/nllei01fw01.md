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

**nl:native/smtp/CLAUDE.md**
- 1. **Wide ACL blast radius (NL).** `network/configs/Firewall/nl-fw01` has SMTP-permit ACLs to `nlsmtp-gpg01` from nearly every inside/DMZ VLAN (cctv, guest, servers01-03, vpn01, iot, room-a, mgmt, corosync, nfs) plus the `outside_freedom_access_in` exception for `WHITELIST_KYRIAKOS` → `nlsmtp-gpg01-smtp`. An IP/hostname change touches a lot of network config; coordinate with `network/configs/Firewall/` updates. **GR firewall coverage is not yet audited** — equivalent ACLs likely exist on `gr-fw01` but were not surveyed during the 2026-04-26 catch-up.
- - `network/configs/Firewall/nl-fw01` — NL ASA objects (`nlsmtp-gpg01`, `nlsmtp-gpg01-smtp`, `nlsmtp-dkim01`) + the SMTP ACL fan-in. **GR firewall objects on `gr-fw01` not yet audited.**

**gr:edge/CLAUDE.md**
- - **NL ASA config:** `infrastructure/nl/production/network/configs/Firewall/nl-fw01`

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-13-003): Error budget consumpti | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-14-009): Convergence 64.3s exce | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-14-009): Error budget consumpti | 0.8 |
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

- **agents-cli audit + adoption plan (2026-04-23)** (project): Deep audit of claude-gateway vs google/agents-cli. 16-dimension scorecard, 10 patterns to steal, 6 to skip, 4-phase adoption plan in /home/app-user/.claude/plans/drifting-napping-donut.md. Plan file approved by ExitPlanMode, but 3 open questions still need user steer before any implementation begins.
- **ASA Weekly Reboot — DISABLED** (project): EEM watchdog auto-reboot REMOVED from both ASAs on 2026-04-10. Reboot watcher cron disabled.
- **BGP community scheme for inter-site path selection (YT-200 fix)** (project): Community origin-tagging at VPS edges + receiver-side LP policy on ASAs, deployed 2026-04-23 to fix GR Prometheus scrape asymmetry. Scales to any future site/edge.
- **Budget migration 2026-04-21 — completion state + outstanding items** (project): xs4all->budget rename + rtr01 WAN-edge isolation migration; completed Steps 1-8; etherchannel attempt aborted after my channel-group 1 mistake caused mgmt outage; rtr01 reload-safety recovered it. Open items for follow-up.
- **Dual-WAN VPN full parity (Freedom + xs4all)** (project): Both NL WANs have full S2S tunnel coverage. Freedom PPPoE outage auto-handled via xs4all failover, QoS cron, SMS alerting, and trained triage scripts.
- **ASA floating-conn for route changes** (feedback): Enable timeout floating-conn on ASA to auto-teardown stale connections when BGP/routing changes. Use netmiko for ASA automation, not expect.
- **GR ASA access — direct via grclaude01 netmiko (not OOB public IP)** (feedback): To diagnose/query gr-fw01, SSH direct to grclaude01 over VPN and drive netmiko from `/tmp/netmiko-venv/`. Do NOT go via OOB 203.0.113.X:2222 unless VPN is down.
- **Add per-peer LP override when introducing a new ISP edge (rtr01-style), not just blanket FRR_TRANSIT_IN** (feedback): When a new edge router (e.g. rtr01) is added and directly peers iBGP with remote endpoints (VPS, other sites), the FRR RRs may reflect the same prefix via two NHs — one via the new edge (Budget), one via the old Freedom path. Both arrive at the core ASA under the same `FRR_TRANSIT_IN` (LP 100) route-map — tie-break picks the new edge. But the REPLY from the remote endpoint comes back on the original Freedom-path interface → asymmetric routing → stateful drop on ASA (rpf-violated, nat-rpf-failed). Add a per-peer route-map (e.g. `FREEDOM_FRR_IN` applied only to the FRR that reflects the Freedom-NH version) matching a VPS_LOOPBACKS-style prefix-list and setting LP 200. ASA 9.16 does NOT support `match ip next-hop` in BGP inbound route-maps — must use prefix-list match only, scoped per neighbor.
- **lib/devices.py expects CISCO_PASSWORD; nl-claude01 has CISCO_ASA_PASSWORD** (feedback): For ad-hoc netmiko queries against NL Cisco gear, alias CISCO_ASA_PASSWORD into CISCO_PASSWORD before calling lib.devices helpers
- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **Never reuse an existing channel-group number when adding a new LACP bundle** (feedback): P0 rule — always `show etherchannel summary` first; reusing an existing Po number modifies the existing bundle's config AND absorbs new members into it, which can cut the production path that the existing bundle carries.
- **Re-read CLAUDE.md before concluding when finding contradicts it** (feedback): When a live-system probe seems to contradict an architectural claim, re-read the relevant CLAUDE.md section verbatim before concluding the doc is outdated or wrong. The contradiction usually means I'm querying the wrong device.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **VPN Mesh Stats API** (project): Portfolio mesh-stats webhook — live SSH tunnel status, ping latency, RIPE BGP, 9 unique tunnels, standby-aware compound status. Script at scripts/vpn-mesh-stats.py.
- **NAT/PAT Audit 2026-04-09** (project): Tri-WAN PAT completed on NL ASA (28 rules). GR ASA NAT_dmz_servers02 /29→/27 fix. Both saved.
- **notrf01dmz01 + notrf01dmz02 onboarding — in flight 2026-05-05** (project): Two new public-IP DMZ Docker hosts at Gigahost NO. Unit 1+2+3 done (hardening, UFW, full 6-tunnel IPsec mesh including xs4all via rtr01). Unit 4 (FRR + iBGP) partially up — 3/8 BGP peers established. Plan at /home/app-user/.claude/plans/wobbly-snacking-biscuit.md.
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
- **rtr01 syslog source-binding fix (2026-04-22)** (project): IOS-XE F0/0 data-plane ACL logs (fman_fp_image) arrive with no hostname in the syslog header; syslog-ng then falls back to source IP if reverse-DNS fails. Fix = /etc/hosts entry on syslog-ng server. Durable + libc-backed; holistic-health guardrail added.
- **VPS DMZ /27 route is now BGP-driven (not static) on both VPSs** (project): Removed `ip route add 10.0.X.X/27 dev xfrm-nl-f/xfrm-nl` lines from /etc/systemd/system/swanctl-loader.service on notrf01vps01 + chzrh01vps01. FRR now installs the /27 via BGP (proto bgp metric 20 via 10.0.X.X). BFD-driven sub-second failover now actually works for DMZ service traffic.
- **VTI Migration + BGP Site Subnet Routing** (project): VTI tunnels (2026-04-09) + full BGP inter-site routing (2026-04-10). No static inter-site routes. 3-tier LP failover: Freedom 200, xs4all 150, FRR transit 100.

*Compiled: 2026-05-06 00:48 UTC*