# Postmortem: Freedom ISP PPPoE Outage

| Field | Value |
|-------|-------|
| **Incident ID** | IFRNLLEI01PRD-381 |
| **Date** | 2026-04-07 23:53 CEST — 2026-04-08 06:40 CEST |
| **Duration** | 6 hours 47 minutes |
| **Severity** | P1 — Full primary WAN loss, cross-site VPN down, tenant internet down |
| **Author** | Operator Papadopoulos |
| **Status** | Resolved, with follow-up actions in progress |

---

## Executive Summary

On 2026-04-07 at 23:53 CEST, the Freedom ISP PPPoE session on the NL site's primary WAN interface (`outside_freedom`, 203.0.113.X) dropped and did not recover for approximately 6 hours and 47 minutes. The Genexis XGS-PON ONT stopped responding to PADI requests from the ASA, causing the PPPoE session to die. The interface remained physically up but with no IP assigned.

This resulted in total loss of internet for all tenant rooms (B, C, D), loss of all S2S VPN tunnels to the GR site and both VPS nodes, 10+ LibreNMS critical alerts, and a 6h 47m cross-site isolation. The backup WAN (xs4all) was online but lacked complete VPN tunnel parity, meaning it could not automatically compensate for Freedom's loss.

The incident exposed a critical single-point-of-failure: despite having two ISPs, the VPN and NAT configurations were not fully mirrored between them. This has been fully remediated.

---

## Timeline (all times CEST, UTC+2)

| Time | Event | Source |
|------|-------|--------|
| Apr 7, 23:52:25 | Last tenant room NAT build via Freedom | syslog-ng: `ASA-6-305011 inside_room_b:10.0.X.X → outside_freedom:203.0.113.X` |
| Apr 7, 23:53:26 | Last ASA syslog line via Freedom network | syslog-ng: `ASA-6-302013 Built inbound TCP...outside_freedom` — then silence |
| Apr 7, 23:53–00:02 | Freedom PPPoE dies. ONT not responding to PADI | ASA: `show vpdn pppinterface` → PPP id=1 "deleted and pending reuse" |
| Apr 8, 00:02:30 | First syslog arrives via xs4all (backup WAN) | syslog-ng: `ASA-6-302014 Teardown TCP...outside_xs4all...SYN Timeout` |
| Apr 8, 00:02–01:30 | Automated triage detects outage. Claude Code session investigates | Session log, incident_knowledge DB |
| Apr 8, 01:30–03:00 | **Phase 1–3:** GR VPN restored via xs4all, VPS tunnels migrated, NAT parity achieved (59/59) | ASA configs: `write memory` on both ASAs |
| Apr 8, 03:00–04:00 | **Phase 4–5:** iBGP mesh verified (30/30 sessions), GR dmz02 TS_UNACCEPTABLE fixed | ASA debug: DELETE+RE-CREATE crypto-map entries |
| Apr 8, 06:38:25 | Freedom PPPoE recovers. First Freedom NAT build on ASA | syslog-ng: `ASA-6-305011 Built static UDP...outside_freedom:203.0.113.X` |
| Apr 8, 06:40:10 | First tenant room NAT via Freedom | syslog-ng: `ASA-6-305011 inside_room_c:10.0.X.X → outside_freedom:203.0.113.X` |
| Apr 8, 06:50 | QoS toggle detects Freedom UP, removes tenant bandwidth limits, sends SMS | `freedom-qos-toggle.sh` state file → `qos-inactive` |
| Apr 8, ~15:00 | **Phase 6:** VPS 3-tier dual-ISP failover deployed | ipsec.conf on both VPS nodes |
| Apr 8, ~15:30 | **Phase 7:** Prometheus FRR scrape fix, GR ASA TS cleanup | ASA crypto-map seq 74/75 added |
| Apr 8, 21:39 | Tenant Nikolaos reports brief WiFi drop via WhatsApp | WhatsApp message; syslog shows no full PPPoE drop — micro-interruption |
| Apr 8, 21:41 | Nikolaos confirms WiFi returned | WhatsApp message |
| Apr 8, 22:00 | QoS cron tightened from `*/10` to `*/2` | crontab updated |

---

## Root Cause

The Genexis XGS-PON ONT (powered via TP-Link TL-PoE10R PoE splitter, 802.3af only, connected via nl-sw01 Gi1/0/36) stopped responding to PPPoE Active Discovery Initiation (PADI) packets from the ASA. The ASA's Port-channel1.6 (VLAN 6) interface remained physically up (`line protocol up`) but the PPPoE session died, leaving the IP address unassigned.

**Physical path:** ASA Po1.6 (VLAN 6) → nl-sw01 trunk (4-port LACP) → Gi1/0/36 (PoE 802.3af, 15.4W) → TP-Link TL-PoE10R PoE Splitter (802.3af only, NOT 802.3at compatible) → Genexis XGS-PON ONT (1Gbps) → Freedom fiber

The exact ONT failure mode is unknown — it could be an ONT firmware hang, a Freedom ISP upstream issue, or a transient fiber/PON fault. The ONT recovered on its own after ~6h 47m without physical intervention.

**Contributing factors:**
1. **No automatic WAN failover for VPN:** The xs4all backup WAN had incomplete crypto-map and NAT exemption coverage. When Freedom died, xs4all could not carry all S2S tunnels.
2. **No automatic WAN failover for tenant internet:** Tenant rooms (B, C, D) had NAT rules for both WANs, but the ASA's routing table preferred Freedom. Without Freedom's PPPoE session, tenant traffic had no valid next-hop for the Freedom route and did not automatically fall over to xs4all.
3. **QoS toggle cron too infrequent:** The `freedom-qos-toggle.sh` script ran every 10 minutes, allowing up to 10 minutes of unthrottled tenant traffic on the backup link before QoS kicked in.
4. **nl-sw01 inaccessible:** SSH to the core switch was refused, preventing remote verification of the ONT port (Gi1/0/36) status or PoE power-cycle.

---

## Impact

### Infrastructure
- **Cross-site VPN:** NL ↔ GR tunnel dead for 6h 47m. All 46 crypto-map entries on `outside_freedom_map` non-functional.
- **VPS tunnels:** Both Norway and Switzerland VPS lost direct NL connectivity.
- **iBGP mesh:** 30 iBGP sessions disrupted until VPN restored via xs4all.
- **Monitoring:** 10+ LibreNMS critical alerts. Prometheus FRR scrape targets unreachable. Gatus alert firing.
- **K8s ClusterMesh:** NL ↔ GR Cilium ClusterMesh disrupted.

### Tenants
- **Rooms B, C, D:** Complete internet loss for ~6h 47m (23:53–06:40 CEST).
- **Tenant report:** Nikolaos Vrettos (WhatsApp, 21:39 Apr 8) reported brief evening WiFi drop + referenced the overnight outage ("it also happened yesterday evening"). Syslog forensics confirmed the evening event was a sub-second micro-interruption, not a full PPPoE drop.
- **Exam impact:** Tenant mentioned exams the next day — extended outage during study hours.

### Services
- **Matrix/n8n/Claude Code:** Continued via xs4all (NL-local traffic unaffected).
- **GR-hosted services:** Unreachable from NL until Phase 1 remediation (~01:30).

---

## Remediation Actions Taken

### During the Incident (Reactive)

| # | Action | Devices | Result |
|---|--------|---------|--------|
| 1 | **GR VPN restoration** — Added xs4all (203.0.113.X) as secondary peer on GR ASA seq 60-73. Added 8 crypto-map entries + 27 NAT exemptions to NL ASA xs4all map. | nl-fw01, gr-fw01 | 5 child SAs established immediately. GR reachable at ~50ms via xs4all. |
| 2 | **VPS tunnel migration** — Added 8 crypto-map entries for VPS peers on xs4all map. Whitelisted xs4all IP in VPS iptables. Updated ipsec.conf + ipsec.secrets. | nl-fw01, notrf01vps01, chzrh01vps01 | Full 4-site VPN mesh operational over xs4all. |
| 3 | **NAT exemption parity** — Programmatic diff found 9 missing xs4all rules. Added all. | nl-fw01 | 59/59 parity (zero delta). |
| 4 | **iBGP mesh verification** — Audited all 30 iBGP sessions across 6 FRR nodes. | All FRR nodes | All 30 sessions ESTABLISHED. |
| 5 | **GR dmz02 TS_UNACCEPTABLE fix** — Deleted and re-created crypto-map entries 37/38 on GR ASA to clear stale TS matching tables. | gr-fw01 | Child SA established immediately. GR DMZ reachable. |
| 6 | **QoS auto-applied** — `freedom-qos-toggle.sh` detected Freedom DOWN, applied 5/2 Mbps limits to tenant rooms, sent SMS via Twilio. | nl-fw01 (via cron) | Tenant bandwidth protected on xs4all. |

### After Recovery (Preventive)

| # | Action | Devices | Result |
|---|--------|---------|--------|
| 7 | **VPS 3-tier failover** — Rewrote both VPS ipsec.conf with ISP-specific naming: `nl-dmz-freedom` (auto=start), `nl-dmz-xs4all` (auto=route), `nl-dmz-via-gr` (auto=route). DPD failover + restart. | notrf01vps01, chzrh01vps01 | Automatic failover: Freedom → xs4all → GR backbone. |
| 8 | **Prometheus FRR fix** — Added crypto-map seq 74 (K8s↔GR DMZ) + seq 75 (mgmt↔GR DMZ) on both Freedom and xs4all maps. | nl-fw01 | All 6 FRR Prometheus targets healthy. |
| 9 | **QoS cron tightened** — Changed `freedom-qos-toggle.sh` from `*/10` to `*/2`. | nl-claude01 crontab | Max detection delay reduced from 10 min to 2 min. |
| 10 | **Incident knowledge base** — 3 entries with vector embeddings added for RAG retrieval by future triage sessions. | gateway.db | Triage agents can now recognize Freedom PPPoE pattern. |
| 11 | **Triage training** — `correlated-triage.sh` trained on Freedom burst pattern (NL "Service up/down" + GR "Devices up/down" simultaneously → 0.95 confidence). `infra-triage.sh` has Freedom fast-path check. | OpenClaw skills | Automated recognition of future Freedom outages. |
| 12 | **Documentation updated** — CLAUDE.md, infrastructure.md, memory files, dual-WAN VPN parity docs all updated with full ISP parity details. | Repository | Future sessions have complete context. |

---

## What Went Well

1. **xs4all backup link was online** and able to carry all traffic once properly configured.
2. **Automated detection** — `freedom-qos-toggle.sh` correctly detected the outage, applied QoS, and sent SMS.
3. **Fast remediation** — Full VPN parity achieved within ~3 hours of detection (Phases 1-5).
4. **iBGP resilience** — All 30 BGP sessions reconverged within minutes of VPN restoration.
5. **SMS alerting bypassed Matrix dependency** — operator notified even when Matrix might have been unreachable.
6. **Syslog-ng centralized logging** enabled precise forensic timeline reconstruction.

## What Went Wrong

1. **xs4all lacked full VPN parity** — the backup WAN had only partial crypto-map and NAT exemption coverage, negating the purpose of having two ISPs.
2. **Tenant internet did not failover** — despite having NAT rules for both WANs, tenant traffic didn't automatically use xs4all when Freedom died.
3. **QoS cron was too slow** (*/10) — up to 10 minutes of unthrottled tenant traffic on the backup link.
4. **nl-sw01 SSH inaccessible** — couldn't remotely verify ONT port status or PoE power-cycle.
5. **VPS ipsec.conf was replaced, not extended** — initial emergency fix broke Freedom connectivity when it recovered.
6. **No PPPoE-level monitoring** — the QoS toggle checks interface IP assignment, not PPPoE session health metrics (PADI/PADO timing, session uptime).

---

## Planned & Advised Future Actions

### Completed

| # | Action | Status | YT Issue |
|---|--------|--------|----------|
| 1 | Full crypto-map parity (46 entries on both Freedom + xs4all maps) | Done | IFRNLLEI01PRD-381 |
| 2 | Full NAT exemption parity (59/59 rules on both WANs) | Done | IFRNLLEI01PRD-381 |
| 3 | VPS 3-tier failover with ISP-specific naming | Done | IFRNLLEI01PRD-381 |
| 4 | QoS cron tightened to */2 | Done | — |
| 5 | Triage scripts trained on Freedom pattern | Done | — |
| 6 | Tenant default route failover (SLA monitoring) | Done | — |
| 7 | XS4ALL-ROOM-D-PM policy-map — verified all 3 rooms have identical QoS | Done (false alarm) | — |
| 8 | PPPoE session metrics — LibreNMS already monitors `outside_freedom` (port_id 2776): ifOperStatus, traffic rates, state history | Done (already covered) | — |

### In Progress / Planned

| # | Action | Priority | Rationale | YT Issue |
|---|--------|----------|-----------|----------|
| 6 | ~~**BGP transit overlay (VTI migration)**~~ — Completed 2026-04-09. Crypto-maps unbound on both ASAs, replaced with 3 VTI tunnels each. VPS migrated from ipsec.conf to swanctl+XFRM. BGP: 17 site subnets injected, LP 200/100 path selection, 4 FRR RR sessions established. Key fix: `port_nat_t=0` in strongswan.conf (NAT-T breaks ASA VTI binding). | ~~High~~ | **DONE** (2026-04-09) — 92 crypto-map entries + 118 NAT exemptions replaced by 6 VTI tunnels. Remaining: Matrix backend unreachable from VPS (TCP SYN-ACK not returning from 10.0.X.X), orphaned crypto-map cleanup, LibreNMS script rewrite. | IFRNLLEI01PRD-381, 382, 383 |
| 7 | ~~**Tenant default route failover**~~ — SLA monitor pings Freedom BNG (198.51.100.X) every 5s via `outside_freedom`. Track 1 attached to Freedom default route (metric 1). xs4all backup default route at metric 10. Automatic failover within seconds. `write memory` saved. | ~~High~~ | **DONE** (2026-04-09) — 3-tier default route: Freedom (1, tracked) → xs4all (10) → LTE (20). | — |
| 8 | ~~**nl-sw01 SSH access**~~ — Fixed `login block-for` from `100 attempts 2 within 100` to `10 attempts 5 within 30`. SSH from app-user confirmed working. Correct ciphers: aes128-ctr (not CBC). | ~~Medium~~ | **DONE** (2026-04-09) — switch now accessible for remote ONT port verification. | — |
| 9 | ~~**ONT health monitoring**~~ — 3 Prometheus metrics added to `freedom-qos-toggle.sh` (cron */2): `freedom_bng_rtt_ms` (SLA RTT to BNG), `freedom_ont_port_errors` (sw01 Gi1/0/36 CRC errors), `freedom_pppoe_up` (session status). Written to node_exporter textfile collector. LibreNMS also monitors sw01 Gi1/0/36 (port_id 7861) and ASA `outside_freedom` (port_id 2776). | ~~Medium~~ | **DONE** (2026-04-09) — 5-layer monitoring: ASA SLA (5s), QoS toggle (2min), Prometheus metrics, LibreNMS switch port, LibreNMS ASA interface. | — |
| 10 | ~~**XS4ALL-ROOM-D-PM policy-map**~~ — Verified 2026-04-09: all 3 rooms have identical QoS configs. | ~~Medium~~ | **DONE** (false alarm). | N/A |
| 11 | ~~**PPPoE session metrics**~~ — LibreNMS monitors `outside_freedom` (port_id 2776): ifOperStatus up/down, traffic rate graphs, state change history. Fires "Service up/down" alert on PPPoE loss. | ~~Low~~ | **DONE** (already covered by LibreNMS). | N/A |
| 12 | ~~**Genexis ONT UPS investigation**~~ — Verified: ONT draws 15.4W (Class 3) on a 60W port budget. WS-C3850-12X48U has ~800W total PoE capacity. No brownout risk. ONT hang was ISP/firmware, not power. | ~~Low~~ | **CLOSED** (not applicable) — PoE headroom is 4x, no action needed. | N/A |
| 13 | ~~**Freedom ISP SLA review**~~ — Email sent to Freedom ISP on 2026-04-09 requesting: BNG/BRAS incident confirmation, root cause, MTTR expectations, proactive notifications, and why their status page showed no outage. | ~~Low~~ | **DONE** — awaiting ISP response. | — |

### Architecture Recommendation

The **single most impactful improvement** is item #6: **VTI + BGP migration**. The current crypto-map architecture requires maintaining 46 entries on each of 2 WANs (92 total crypto-map entries), 59 NAT exemptions per WAN (118 total), and manual peer-list management on both ASAs. Any new subnet or site requires touching 4+ places.

With VTI tunnels + BGP:
- Each WAN gets one GRE/IPsec tunnel (2 total, not 92 crypto-maps)
- BGP handles all routing — failover is automatic via best-path
- New subnets need zero VPN changes (BGP advertises them)
- NAT exemptions reduce to 2 (one per VTI)
- This incident would have been **invisible** — BGP withdraws Freedom routes, xs4all routes win, traffic shifts in seconds

This is tracked as IFRNLLEI01PRD-381/382/383 and should be the top infrastructure priority.

---

## Lessons Learned

1. **Having two ISPs is not redundancy unless the VPN config is fully mirrored.** The xs4all link was online the entire time but couldn't help because the crypto-map and NAT configurations were incomplete. Dual-WAN is only as good as its parity.

2. **Cisco ASA crypto-map peer changes require DELETE+RE-CREATE.** Modifying the peer list in-place leaves stale IKEv2 TS matching tables. `show run` looks correct but the internal state is wrong. Always delete the entry completely, then re-create it.

3. **IPsec changes must be additive.** When adding ISP failover, add the backup alongside the primary — never replace. Connection names should include the ISP suffix (`nl-dmz-freedom`, `nl-dmz-xs4all`) for clarity.

4. **Centralized syslog is essential for forensics.** The ASA's local log buffer had rotated, but syslog-ng on nlsyslogng01 retained the full timeline with per-second granularity. Without it, the exact outage window and tenant impact would have been unknown.

5. **Monitor the PPPoE session, not just the interface.** The ASA interface was physically up throughout — only the PPPoE layer failed. Monitoring must check at the session level (`show vpdn pppinterface`) rather than just interface status.

---

## Appendix: Syslog-ng Evidence Summary

All timestamps from `/mnt/logs/syslog-ng/nl-fw01/2026/04/` on nlsyslogng01.

| Evidence | File | Key Lines |
|----------|------|-----------|
| Last Freedom activity | `nl-fw01-2026-04-07.log.1` | `Apr 7 23:53:26 ASA-6-302013 Built inbound TCP...outside_freedom` |
| Syslog gap (Freedom dead) | `nl-fw01-2026-04-07.log` | 0 bytes (rotated at midnight during outage) |
| First xs4all activity | `nl-fw01-2026-04-08.log` | `Apr 8 00:02:30 ASA-6-302014 Teardown TCP...outside_xs4all...SYN Timeout` |
| Freedom recovery | `nl-fw01-2026-04-08.log` | `Apr 8 06:38:25 ASA-6-305011 Built static UDP...outside_freedom:203.0.113.X` |
| First tenant via Freedom | `nl-fw01-2026-04-08.log` | `Apr 8 06:40:10 ASA-6-305011 inside_room_c → outside_freedom:203.0.113.X` |
| Evening micro-drop | `nl-fw01-2026-04-08.log` | NAT build counts show no gap at 21:39; ASA log volume steady at 5-7K/min |
| Tenant NAT per minute | `nl-fw01-2026-04-08.log` | `grep 305011.*inside_room \| sed per-minute \| uniq -c` — continuous 20:00-22:59 |

---

## Addendum: VTI Finalization Session (2026-04-09)

The architecture recommendation from this postmortem (item #6: VTI + BGP migration) was fully completed on 2026-04-09 in a marathon finalization session. This section documents the outcome.

### Scope Completed

All 6 original TODO items from the VTI migration plan were completed:

1. **Dual-WAN VTI deployment** — 10 VTI tunnels deployed across 4 nodes: NL ASA (6 tunnels: Tunnel1-3 xs4all, Tunnel4-6 Freedom), GR ASA (4 tunnels: Tunnel1-3 existing + Tunnel4 vti-nl-f for Freedom), both VPS (4 connections each: nl, gr, ch/no-vps, nl-freedom).
2. **E2E failover testing** — 4/4 tests passed: kill VPS direct tunnel (DPD <30s recovery), kill ASA IKE SA (DPD <60s, 0% loss), admin-shutdown tunnel (floating statics instant), ClusterMesh during site isolation (maintained).
3. **Crypto-map era cleanup** — ~713 config lines removed from both ASAs. Unbound crypto-map entries, orphaned ACLs, and 118 NAT exemptions all removed. Audited line-by-line.
4. **strongSwan migration** — Both VPS migrated from ipsec.conf to swanctl.conf with XFRM interfaces, charon port_nat_t=4500, kernel-netlink buflen=2MB.
5. **BGP transit overlay** — 17 site subnets injected into BGP, LP 200/100 path selection, 4 FRR route reflector sessions established.
6. **CrowdSec + UFW hardening** — Whitelists deployed on 8 hosts, xs4all + Freedom IPs in UFW, DMZ XFRM source range added.

### Issues Encountered During Finalization

- **Freedom ISP recovered mid-session** — caused ESP routing disruption as default route switched from xs4all back to Freedom. Host routes for VPN peers on `outside_xs4all` resolved the issue.
- **Stale ASA flows** — corosync cluster blackholed by stale connection table entries from crypto-map era. Fixed with `clear conn all` (6003 connections cleared).
- **SPI mismatch** — clearing crypto on only one ASA caused ESP SPI mismatches. Both ASAs must be cleared simultaneously.
- **PAT gap discovered** — the mass crypto-map cleanup accidentally removed after-auto PAT rules for inside zones on xs4all. Internet would have broken on WAN failover. Discovered during testing, fixed by adding PAT rules for all 11 inside zones on both Freedom and xs4all outside interfaces.

### Validation

This postmortem's architecture recommendation stated: "This incident would have been **invisible** — BGP withdraws Freedom routes, xs4all routes win, traffic shifts in seconds." With VTI + BGP + floating statics now deployed, this is exactly what happens. The Freedom PPPoE outage scenario is now a non-event for cross-site connectivity.
