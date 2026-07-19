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
- ### WAN Connections (verified on live nl-fw01 2026-06-19: `xs4all` 0×, `budget` 73×)
- **nl-fw01 (ASA 5508-X, ASA 9.16(4)):**

**nl:edge/CLAUDE.md**
- | nl-fw01 | 203.0.113.X (Freedom PPPoE) | 10.0.181.X | Freedom (primary, PPPoE Po1.6), Budget via nlrtr01 (backup, outside_budget routed /30 10.0.X.X/30 Po1.2), LTE (failover) | nlk8s-frr01 (.192.3), nlk8s-frr02 (.192.4) | K8s .85.20, .85.21, .85.22, .85.23 (4 nodes) |
- **NL ASA dual-WAN (post-2026-04-21 budget migration):** nl-fw01 has **two WAN paths**, verified on the live device 2026-06-19 (`xs4all` appears 0× in the running-config; `budget` 73×):
- **DHCP-distributed DNS must be ISP-agnostic** on any multi-WAN ASA. All 8 DHCP scopes on `nl-fw01` now hand out either `1.1.1.1 8.8.8.8` (rooms a/b/c/d, cctv, guest, iot — public anycast) or `10.0.181.X` (mgmt — internal pi-hole). Until 2026-05-08 the 6 tenant/dmz scopes were pinned to Freedom's resolvers (`198.51.100.X`, `185.232.98.76`); during that day's Freedom outage tenants kept full L3 internet via Budget but lost DNS silently — Freedom's resolvers drop UDP/53 from non-Freedom source IPs even though they still answer ICMP. Symptom: messaging apps work, browsers show "site can't be reached." Diagnostic: `dig @<isp-resolver> <name>` from a probe egressing the failover ISP — silent timeout confirms the source-IP ACL. See memory `feedback_dhcp_dns_pinned_to_isp.md` and `incident_freedom_pppoe_20260508.md` Gap E. **GR parity check pending** — `gr-fw01` should be audited for the same pattern with InAlan resolvers before the next InAlan outage.
- **Inter-site IPsec (ASA ↔ ASA):** The two ASAs maintain a site-to-site IPsec mesh — now **route-based VTI** (the 2026-04-09 migration removed all crypto maps; **live nl-fw01 has 0 `crypto map`, 8 VTI tunnels**, verified 2026-06-19). NL↔GR runs over `vti-gr-f` (NL, Freedom Tu4) + `vti-nl`/`vti-nl-f` (GR); every cross-site VLAN pair is reached by **BGP routes over the VTI mesh** (no per-VLAN crypto ACLs). This is the backbone that enables cross-site services (Galera replication, DRBD sync, Cilium ClusterMesh, FreeIPA replication, etc.).
- **IPsec tunnel groups on nl-fw01:**

**nl:native/synology/CLAUDE.md**
- **nl-nas02**: No iptables module loaded. No DSM firewall active. Relies entirely on upstream ASA firewall (nl-fw01).

**nl:native/smtp/CLAUDE.md**
- 1. **Wide ACL blast radius (NL).** `network/configs/Firewall/nl-fw01` has SMTP-permit ACLs to `nlsmtp-gpg01` from nearly every inside/DMZ VLAN (cctv, guest, servers01-03, vpn01, iot, room-a, mgmt, corosync, nfs) plus the `outside_freedom_access_in` exception for `WHITELIST_KYRIAKOS` → `nlsmtp-gpg01-smtp`. An IP/hostname change touches a lot of network config; coordinate with `network/configs/Firewall/` updates. **GR firewall coverage is not yet audited** — equivalent ACLs likely exist on `gr-fw01` but were not surveyed during the 2026-04-26 catch-up.
- - `network/configs/Firewall/nl-fw01` — NL ASA objects (`nlsmtp-gpg01`, `nlsmtp-gpg01-smtp`, `nlsmtp-dkim01`) + the SMTP ACL fan-in. **GR firewall objects on `gr-fw01` not yet audited.**

**gr:edge/CLAUDE.md**
- - **NL ASA config:** `infrastructure/nl/production/network/configs/Firewall/nl-fw01`

**gateway:CLAUDE.md**
- - **Freedom XGS-PON PPPoE outage on nl-fw01 outside_freedom RESOLVED 2026-05-13 (IFRNLLEI01PRD-891, closed 2026-05-15):** 4d 15h 14m outage on line F0381391 — down 2026-05-08 07:46:36 UTC (ASA Track 1, BRAS `198.51.100.X` stopped returning PADO), restored between 2026-05-12 23:59 and 2026-05-13 00:00 UTC after Freedom NOC field-engineer dispatch + OLT/BRAS service-binding refresh (mechanism: ONT physical swap forces de-registration of old PON serial + new registration + BRAS re-bind in same window). First post-recovery NAT through assigned WAN IP `203.0.113.X` observed at 2026-05-13 00:56:09 UTC. Day-count NAT-events syslog evidence on nl-fw01: May-08=968k → May-09..12=0 each → May-13=863k → May-14=957k. Failover via `outside_budget → nlrtr01 Dialer1` carried all 6 affected VTIs (Tunnel4-9) the whole 4.6 days — **zero user-visible downtime**. Customer-side surface was fully exhausted (3 days of `shut/no shut` cycles + PoE cycles produced visible PADI egress but zero PADO return); phone NOC `088-0115666` (English supported) on 2026-05-11 was the action that triggered dispatch. Full post-mortem + reusable PPPoE diagnostic playbook + customer detail (postcode 2315 HP nr 17, customer F0381391, ASA `fake@freedom.nl` username is decorative, BRAS at `198.51.100.X`): [`memory/freedom_pppoe_outage_resolved_20260513.md`](memory/freedom_pppoe_outage_resolved_20260513.md).

**other:/app/n8n/social-media-autoposter/CLAUDE.md**
- - **Postiz** — self-hosted at postiz.example.net (backend **nlpostiz01** `10.0.181.X` on nlpve04 — migrated cross-site from grpostiz01 on 2026-06-24; Postgres `postiz-db-local` user `postiz-user`). **Image posts depend on an inbound Meta fetch:** Postiz embeds a public media URL `https://postiz.example.net/uploads/...` (built from `FRONTEND_URL`, injected by the `Postiz (Upload File)` → Create Post nodes as `image[].path`), and **Meta's servers (AS32934) fetch it inbound** → public DNS `postiz → 203.0.113.X` → `nl-fw01` (META_AS32934 permit → NPM:443). If FB/IG images stop attaching, check that path (firewall ACL hit, Cloudflare A record, `/uploads` serving 200).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-01 | chaos-tunnel |  | Chaos finding (chaos-2026-06-01-001): Convergence 38.4s exce | 0.8 |
| 2026-06-01 | chaos-tunnel |  | Chaos finding (chaos-2026-06-01-001): Error budget consumpti | 0.8 |
| 2026-05-27 | chaos-tunnel |  | Chaos finding (chaos-2026-05-27-001): Convergence 41.6s exce | 0.8 |
| 2026-05-27 | chaos-tunnel |  | Chaos finding (chaos-2026-05-27-001): Error budget consumpti | 0.8 |
| 2026-05-13 | chaos-tunnel |  | Chaos finding (chaos-2026-05-13-001): Convergence 31.8s exce | 0.8 |
| 2026-05-13 | chaos-tunnel |  | Chaos finding (chaos-2026-05-13-001): Error budget consumpti | 0.8 |
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
- **ASA 9.16 BGP limitations — why FRR sidecars exist + why ASAs don't peer with remote RRs** (feedback): Two hard ASA 9.16 constraints (no neighbor update-source, to-the-box cross-interface drop) make direct ASA↔remote-RR iBGP peerings impossible. FRR sidecars are the CCIE-correct workaround. Adding more ASA iBGP sessions is architectural regression.
- **ASA Weekly Reboot — DISABLED** (project): EEM watchdog auto-reboot REMOVED from both ASAs on 2026-04-10. Reboot watcher cron disabled.
- **BGP community scheme for inter-site path selection (YT-200 fix)** (project): Community origin-tagging at VPS edges + receiver-side LP policy on ASAs, deployed 2026-04-23 to fix GR Prometheus scrape asymmetry. Scales to any future site/edge.
- **Budget migration 2026-04-21 — completion state + outstanding items** (project): xs4all->budget rename + rtr01 WAN-edge isolation migration; completed Steps 1-8; etherchannel attempt aborted after my channel-group 1 mistake caused mgmt outage; rtr01 reload-safety recovered it. Open items for follow-up.
- **cloudflare_dns_api_access_20260624** (reference): Standing Cloudflare DNS API access for the example.net zone — token in .env; manage public A/CNAME records via the API; never ask the operator for the token again
- **Dual-WAN VPN full parity (Freedom + xs4all)** (project): Both NL WANs have full S2S tunnel coverage. Freedom PPPoE outage auto-handled via xs4all failover, QoS cron, SMS alerting, and trained triage scripts.
- **ASA after-auto source dynamic PAT has rpf-check side-effect on inbound traffic** (feedback): `nat (<src_zone>, <outside_X>) after-auto source dynamic any interface` silently rpf-drops inbound traffic on outside_X destined to src_zone when source doesn't match the interface IP. Fix is Section-1 identity NAT for the specific subnet pair.
- **feedback-always-netmiko-for-cisco** (feedback): "ALWAYS use netmiko (device_type cisco_asa / cisco_ios) for ANY Cisco ASA/IOS access — never sshpass, expect, or raw ssh/paramiko command-channel."
- **ASA 9.16 PPPoE/VPDN show commands — which exist, which don't** (feedback): Skip the dead command list when diagnosing PPPoE on nl-fw01 — show vpdn session/tunnel and show pppoe* do not exist; use show interface + show ip address + show track + tracked routes + ping via the other WAN
- **ASA floating-conn for route changes** (feedback): Enable timeout floating-conn on ASA to auto-teardown stale connections when BGP/routing changes. Use netmiko for ASA automation, not expect.
- **GR ASA access — direct via grclaude01 netmiko (not OOB public IP)** (feedback): To diagnose/query gr-fw01, SSH direct to grclaude01 over VPN and drive netmiko from `/tmp/netmiko-venv/`. Do NOT go via OOB 203.0.113.X:2222 unless VPN is down.
- **ASA show dhcpd CLI gotchas** (feedback): ASA `show dhcpd binding` / `show dhcpd state` reject interface filter; client-id has 01 hwtype prefix that must be stripped to recover MAC.
- **feedback_asa_shun_vti** (feedback): ASA threat-detection scanning-threat shun recurring issue — ANY new trusted infrastructure subnet must be added to whitelist_shun_nlgr_all_subnets on nl-fw01 (+ GR ASA), else it WILL be shunned during high-traffic events. Missing entries caused incidents 2026-04-12 (VTI mesh) and 2026-04-22 (rtr01 transit /30).
- **ASA syslog timestamps are in the ASA local clock (CEST), not UTC** (feedback): Avoid 2h labelling errors when copying ASA log lines into customer/vendor emails — ASA timestamp = clock timezone setting, not UTC
- **Add per-peer LP override when introducing a new ISP edge (rtr01-style), not just blanket FRR_TRANSIT_IN** (feedback): When a new edge router (e.g. rtr01) is added and directly peers iBGP with remote endpoints (VPS, other sites), the FRR RRs may reflect the same prefix via two NHs — one via the new edge (Budget), one via the old Freedom path. Both arrive at the core ASA under the same `FRR_TRANSIT_IN` (LP 100) route-map — tie-break picks the new edge. But the REPLY from the remote endpoint comes back on the original Freedom-path interface → asymmetric routing → stateful drop on ASA (rpf-violated, nat-rpf-failed). Add a per-peer route-map (e.g. `FREEDOM_FRR_IN` applied only to the FRR that reflects the Freedom-NH version) matching a VPS_LOOPBACKS-style prefix-list and setting LP 200. ASA 9.16 does NOT support `match ip next-hop` in BGP inbound route-maps — must use prefix-list match only, scoped per neighbor.
- **lib/devices.py expects CISCO_PASSWORD; nl-claude01 has CISCO_ASA_PASSWORD** (feedback): For ad-hoc netmiko queries against NL Cisco gear, alias CISCO_ASA_PASSWORD into CISCO_PASSWORD before calling lib.devices helpers
- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **Never reuse an existing channel-group number when adding a new LACP bundle** (feedback): P0 rule — always `show etherchannel summary` first; reusing an existing Po number modifies the existing bundle's config AND absorbs new members into it, which can cut the production path that the existing bundle carries.
- **PPPoE Discovery failure is never an MTU/MSS issue** (feedback): When PADI/PADO fails, do not chase MTU 1500 vs 1492 vs MSS clamping 1448 — Discovery is L2 pre-IP and MSS only applies to TCP segments inside an up PPP session
- **Re-read CLAUDE.md before concluding when finding contradicts it** (feedback): When a live-system probe seems to contradict an architectural claim, re-read the relevant CLAUDE.md section verbatim before concluding the doc is outdated or wrong. The contradiction usually means I'm querying the wrong device.
- **Freedom ONT (Genexis XGS-PON) requires forced PoE re-detect after long down** (feedback): Plain `no shutdown` on nl-sw01 Gi1/0/36 after a long Freedom-down window is not enough — the ONT loses PON training and needs `power inline never` → `power inline auto` + `shut`/`no shut` to cold-boot cleanly. 2026-04-22 recovery exercise.
- **freedom-pppoe-outage-resolved-20260513** (project): "Post-mortem of the 4d 15h Freedom XGS-PON PPPoE outage on nl-fw01 (line F0381391). Down 2026-05-08 09:46:36 UTC (BRAS stopped returning PADO), restored 2026-05-13 ~00:00 UTC after Freedom NOC field-engineer dispatch + OLT/BRAS service-binding refresh. Failover via outside_budget → nlrtr01 Dialer1 carried all 6 affected VTIs with zero user-visible downtime."
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, grdmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **k8s-residual-triage-20260617** (project): "2026-06-17 — closed/triaged the residual open IFRNLLEI01PRD K8s alerts after the auto-resolve pipeline repair. seaweedfs filer OOM fix (MRs), notrf01dmz01 is a KNOWN scrape-path gap (not a real down), InfragraphPrecisionDrop is slow-recovery."
- **nlrtr01 budget VDSL port-utilisation alarm during 2026-05-09 Freedom outage** (project): Diagnosed direction-mismatch artefact on Et0/1/0.6 (LibreNMS port_id 123127). Real DS sync 111 Mbps / US sync 33 Mbps; Cisco BW = 33 Mbps; LibreNMS ifSpeed = 33,000,000 → rule 6 false-fires. Operator chose Option A — override ifSpeed to 111,000,000.
- **VPN Mesh Stats API** (project): Portfolio mesh-stats webhook — live SSH tunnel status, ping latency, RIPE BGP, 9 unique tunnels, standby-aware compound status. Script at scripts/vpn-mesh-stats.py.
- **NAT/PAT Audit 2026-04-09** (project): Tri-WAN PAT completed on NL ASA (28 rules). GR ASA NAT_dmz_servers02 /29→/27 fix. Both saved.
- **NL traffic-shaping audit during 2026-05-09 Freedom outage** (project): Read-only netmiko audit of rtr01 + nl-fw01 QoS state. Only one rule actually bites traffic — rtr01 Dialer1 egress 30 Mbps single-FIFO shape. All 8 per-tenant ACLs lifetime-zero. nl-fw01 throttle PMs all unattached + ACLs inactive. Improvement gaps documented for future hardening.
- **notrf01dmz01/02 + txhou01vps01 TCP-unreachable from NL 2026-05-08** (project): 3 newly-onboarded mesh peers (notrf01dmz01 10.255.X.X, notrf01dmz02 10.255.X.X, txhou01vps01 10.255.X.X) were TCP+ICMP unreachable from NL because the NL edge ASA was missing inbound VTI access-group bindings. Resolved same day by operator's ACL fix (clears IFRNLLEI01PRD-849 + -684 ASABindingDrift)
- **postiz_gr-fw01_firewall_rules_pending_migration_20260624** (project): 2026-06-24 — gr-fw01 (GR ASA) firewall rules around the migrated postiz still point at GR; the :80 Meta-webhook static-NAT is BROKEN, Cloudflare still pins postiz to GR. Pending migration to nl-fw01.
- **postiz_migration_gr_to_nl_20260624** (project): 2026-06-24 migrated grpostiz01 (privileged Docker LXC) cross-site to nlpostiz01 on nlpve04 to relieve gr-pve01 memory pressure (the chronic etcd-cascade root). Full DNS/NPM/e2e done.
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
- **rtr01 syslog source-binding fix (2026-04-22)** (project): IOS-XE F0/0 data-plane ACL logs (fman_fp_image) arrive with no hostname in the syslog header; syslog-ng then falls back to source IP if reverse-DNS fails. Fix = /etc/hosts entry on syslog-ng server. Durable + libc-backed; holistic-health guardrail added.
- **session-thermal-and-gr-unreachable-20260616** (project): "2026-06-16 triage — NL \"thermal\" was stale phantom data; GR site was isolated ~06-15 22:58 → RECOVERED by 2026-06-17 (GR back online, reachable from NL)"
- **txhou01vps01 onboarding complete (2026-05-06)** (project): Third edge VPS at iFog Houston, TX. AS64512 IPv6 transit + 7 IPsec tunnels into the mesh + 9 iBGP peers + HAProxy edge serving 9 IPv6 anycasts + omoikane backends. End-to-end on the live status page (5th country site).
- **VPS DMZ /27 route is now BGP-driven (not static) on both VPSs** (project): Removed `ip route add 10.0.X.X/27 dev xfrm-nl-f/xfrm-nl` lines from /etc/systemd/system/swanctl-loader.service on notrf01vps01 + chzrh01vps01. FRR now installs the /27 via BGP (proto bgp metric 20 via 10.0.X.X). BFD-driven sub-second failover now actually works for DMZ service traffic.
- **VTI Migration + BGP Site Subnet Routing** (project): VTI tunnels (2026-04-09) + full BGP inter-site routing (2026-04-10). No static inter-site routes. 3-tier LP failover: Freedom 200, xs4all 150, FRR transit 100.

*Compiled: 2026-07-03 04:30 UTC*