# gr-fw01

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:edge/CLAUDE.md**
- | gr-fw01 | 203.0.113.X (InAlan DHCP) | 10.0.58.X | InAlan (primary), LTE (failover) | grk8s-frr01 (.15.3), grk8s-frr02 (.15.4) | K8s .58.20, .58.21, .58.22 (3 nodes) |
- **DHCP-distributed DNS must be ISP-agnostic** on any multi-WAN ASA. All 8 DHCP scopes on `nl-fw01` now hand out either `1.1.1.1 8.8.8.8` (rooms a/b/c/d, cctv, guest, iot — public anycast) or `10.0.181.X` (mgmt — internal pi-hole). Until 2026-05-08 the 6 tenant/dmz scopes were pinned to Freedom's resolvers (`198.51.100.X`, `185.232.98.76`); during that day's Freedom outage tenants kept full L3 internet via Budget but lost DNS silently — Freedom's resolvers drop UDP/53 from non-Freedom source IPs even though they still answer ICMP. Symptom: messaging apps work, browsers show "site can't be reached." Diagnostic: `dig @<isp-resolver> <name>` from a probe egressing the failover ISP — silent timeout confirms the source-IP ACL. See memory `feedback_dhcp_dns_pinned_to_isp.md` and `incident_freedom_pppoe_20260508.md` Gap E. **GR parity check pending** — `gr-fw01` should be audited for the same pattern with InAlan resolvers before the next InAlan outage.
- **GR ASA single-WAN:** gr-fw01 has one ISP (InAlan, DHCP on `outside_inalan`) with LTE backup (10.0.X.X/30, metric 10). SLA monitor pings NL ASA (203.0.113.X).
- **VPS IPsec (ASA ↔ VPS):** Each ASA also terminates tunnels from VPS nodes (CH + NO + TX) and the Norway DMZ hosts (notrf01dmz01–04), providing them with access to DMZ, management, and K8s VLANs. These use the VTI-PROPOSAL (aes-256/sha-256). NL ASA's VTIs source from `outside_freedom`; GR ASA's source from `outside_inalan` (see vti-tx etc. in `network/oxidized/Firewall/gr-fw01`).
- **IPsec tunnel groups on gr-fw01:**

**nl:native/smtp/CLAUDE.md**
- 1. **Wide ACL blast radius (NL).** `network/configs/Firewall/nl-fw01` has SMTP-permit ACLs to `nlsmtp-gpg01` from nearly every inside/DMZ VLAN (cctv, guest, servers01-03, vpn01, iot, room-a, mgmt, corosync, nfs) plus the `outside_freedom_access_in` exception for `WHITELIST_KYRIAKOS` → `nlsmtp-gpg01-smtp`. An IP/hostname change touches a lot of network config; coordinate with `network/configs/Firewall/` updates. **GR firewall coverage is not yet audited** — equivalent ACLs likely exist on `gr-fw01` but were not surveyed during the 2026-04-26 catch-up.
- - `network/configs/Firewall/nl-fw01` — NL ASA objects (`nlsmtp-gpg01`, `nlsmtp-gpg01-smtp`, `nlsmtp-dkim01`) + the SMTP ACL fan-in. **GR firewall objects on `gr-fw01` not yet audited.**

**gr:CLAUDE.md**
- | Find a device/VM | `netbox_get_objects(object_type="dcim.device", filters={"name": "gr-fw01"}, fields=["id","name","status","site","role"])` | `curl` to LibreNMS or `grep` through configs |
- | Get IP assignments | `netbox_get_objects(object_type="ipam.ipaddress", filters={"device": "gr-fw01"}, fields=["address","dns_name","description"])` | `grep` through IaC files |
- - **Hostnames**: `gr<role><number>` (e.g., `gr-fw01` = GR firewall 01)
- gr   skg01  fw    01     → gr-fw01 (firewall)

**gr:network/CLAUDE.md**
- | gr-fw01 | Firewall | Cisco ASA | cisco_asa | Core firewall, NAT, VPN, BGP |
- │   ├── Firewall/gr-fw01
- - **Runner:** `k8s`-tagged GR runner (id=1 on `gr-gitlab01`), egresses from `10.0.58.X/24`. Requires `ssh 10.0.58.X 255.255.255.0 inside_k8s` permit on gr-fw01 (added 2026-04-24).
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
| 2026-06-01 | chaos-tunnel |  | Chaos finding (chaos-2026-06-01-004): Convergence 45.0s exce | 0.8 |
| 2026-06-01 | chaos-tunnel |  | Chaos finding (chaos-2026-06-01-005): Convergence 45.0s exce | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-13-008): Convergence 45.0s exce | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-13-009): Convergence 45.0s exce | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-13-010): Convergence 60.0s exce | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-13-010): Error budget consumpti | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-13-011): Convergence 60.0s exce | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-13-011): Error budget consumpti | 0.8 |
| 2026-04-14 | chaos-tunnel |  | Chaos finding (chaos-2026-04-14-011): Convergence 45.0s exce | 0.8 |
| 2026-04-10 | BGP peer down — Freedom VTI to NL (10.255.200.X) | NL ASA Freedom VTI tunnel is down. GR ASA sees BGP session d | GR auto-failovers to FRR transit (LP 100) via VPS in ~30s. V | 0.9 |
| 2026-04-03 | Service up/down | EEM watchdog timer auto-reload | EEM watchdog reboot (590400s timer, ~6d20h cycle). GR total  | 0.9 |

## Lessons Learned

- **SCHEDULED-ASA-GR-001**: GR ASA EEM watchdog reboot (~6d20h cycle). GR total outage + NL VPN tunnel drop. Cross-site alerts expected. Auto-recovery in 5-10 min. See SCHEDULED-ASA-NL-001 lesson.

## Related Memory Entries

- **agents-cli audit + adoption plan (2026-04-23)** (project): Deep audit of claude-gateway vs google/agents-cli. 16-dimension scorecard, 10 patterns to steal, 6 to skip, 4-phase adoption plan in /home/app-user/.claude/plans/drifting-napping-donut.md. Plan file approved by ExitPlanMode, but 3 open questions still need user steer before any implementation begins.
- **ASA Weekly Reboot — DISABLED** (project): EEM watchdog auto-reboot REMOVED from both ASAs on 2026-04-10. Reboot watcher cron disabled.
- **BGP community scheme for inter-site path selection (YT-200 fix)** (project): Community origin-tagging at VPS edges + receiver-side LP policy on ASAs, deployed 2026-04-23 to fix GR Prometheus scrape asymmetry. Scales to any future site/edge.
- **Budget migration 2026-04-21 — completion state + outstanding items** (project): xs4all->budget rename + rtr01 WAN-edge isolation migration; completed Steps 1-8; etherchannel attempt aborted after my channel-group 1 mistake caused mgmt outage; rtr01 reload-safety recovered it. Open items for follow-up.
- **cloudflare_dns_api_access_20260624** (reference): Standing Cloudflare DNS API access for the example.net zone — token in .env; manage public A/CNAME records via the API; never ask the operator for the token again
- **feedback-always-netmiko-for-cisco** (feedback): "ALWAYS use netmiko (device_type cisco_asa / cisco_ios) for ANY Cisco ASA/IOS access — never sshpass, expect, or raw ssh/paramiko command-channel."
- **ASA floating-conn for route changes** (feedback): Enable timeout floating-conn on ASA to auto-teardown stale connections when BGP/routing changes. Use netmiko for ASA automation, not expect.
- **GR ASA access — direct via grclaude01 netmiko (not OOB public IP)** (feedback): To diagnose/query gr-fw01, SSH direct to grclaude01 over VPN and drive netmiko from `/tmp/netmiko-venv/`. Do NOT go via OOB 203.0.113.X:2222 unless VPN is down.
- **feedback_asa_shun_vti** (feedback): ASA threat-detection scanning-threat shun recurring issue — ANY new trusted infrastructure subnet must be added to whitelist_shun_nlgr_all_subnets on nl-fw01 (+ GR ASA), else it WILL be shunned during high-traffic events. Missing entries caused incidents 2026-04-12 (VTI mesh) and 2026-04-22 (rtr01 transit /30).
- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **GR ASA SSH requires stepstone via gr-pve01** (feedback): SSH to gr-fw01 only works via gr-pve01 as a jump host — direct SSH from NL is rejected (connection reset).
- **GR iSCSI Server (gr-pve02)** (project): GR K8s iSCSI storage — ZFS zvols on PERC H710P, architecture, tunables, AWX PVC fix, SeaweedFS migrated to NFS/sdc
- **incident_grdmz02_oom_shun_20260413** (project): grdmz02 OOM-killed twice on 2026-04-13, ASA shunned DMZ IP 10.0.X.X causing total network loss
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, grdmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **VPN Mesh Stats API** (project): Portfolio mesh-stats webhook — live SSH tunnel status, ping latency, RIPE BGP, 9 unique tunnels, standby-aware compound status. Script at scripts/vpn-mesh-stats.py.
- **NAT/PAT Audit 2026-04-09** (project): Tri-WAN PAT completed on NL ASA (28 rules). GR ASA NAT_dmz_servers02 /29→/27 fix. Both saved.
- **notrf01dmz01/02 + txhou01vps01 TCP-unreachable from NL 2026-05-08** (project): 3 newly-onboarded mesh peers (notrf01dmz01 10.255.X.X, notrf01dmz02 10.255.X.X, txhou01vps01 10.255.X.X) were TCP+ICMP unreachable from NL because the NL edge ASA was missing inbound VTI access-group bindings. Resolved same day by operator's ACL fix (clears IFRNLLEI01PRD-849 + -684 ASABindingDrift)
- **OOB Access via PiKVM + Cloudflare Tunnel** (project): BROKEN (2026-03-21) — PiKVM bricked by forced package upgrade. Requires physical access to GR site to recover. Cloudflare tunnel config still exists but PiKVM is offline.
- **postiz_gr-fw01_firewall_rules_pending_migration_20260624** (project): 2026-06-24 — gr-fw01 (GR ASA) firewall rules around the migrated postiz still point at GR; the :80 Meta-webhook static-NAT is BROKEN, Cloudflare still pins postiz to GR. Pending migration to nl-fw01.
- **postiz_migration_gr_to_nl_20260624** (project): 2026-06-24 migrated grpostiz01 (privileged Docker LXC) cross-site to nlpostiz01 on nlpve04 to relieve gr-pve01 memory pressure (the chronic etcd-cascade root). Full DNS/NPM/e2e done.
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
- **session-thermal-and-gr-unreachable-20260616** (project): "2026-06-16 triage — NL \"thermal\" was stale phantom data; GR site was isolated ~06-15 22:58 → RECOVERED by 2026-06-17 (GR back online, reachable from NL)"
- **status-degraded-no-dmz-bgp-20260619** (project): "2026-06-19 status page \"Degraded — BGP 83/87\" root cause = 4 idle Norway-DMZ BGP sessions (notrf01dmz01 GR-leg stuck + tx-edge↔notrf01dmz03/04 idle); plus edge/CLAUDE.md audit findings."
- **txhou01vps01 onboarding complete (2026-05-06)** (project): Third edge VPS at iFog Houston, TX. AS64512 IPv6 transit + 7 IPsec tunnels into the mesh + 9 iBGP peers + HAProxy edge serving 9 IPv6 anycasts + omoikane backends. End-to-end on the live status page (5th country site).
- **VTI Migration + BGP Site Subnet Routing** (project): VTI tunnels (2026-04-09) + full BGP inter-site routing (2026-04-10). No static inter-site routes. 3-tier LP failover: Freedom 200, xs4all 150, FRR transit 100.

*Compiled: 2026-07-03 04:30 UTC*