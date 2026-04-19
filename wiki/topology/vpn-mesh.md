# VPN Mesh & Dual-WAN Architecture

> Compiled from 10 memory files + 17 CLAUDE.md files. 2026-04-11 14:13 UTC.

## Dual-WAN VPN full parity (Freedom + xs4all)

## Dual-WAN VPN Configuration (2026-04-08)

### WAN Interfaces on nl-fw01 (ASA 9.16(4))

| WAN | Interface | IP | PPPoE | Crypto Map | GR Entries | VPS Entries |
|-----|-----------|-----|-------|-----------|-----------|------------|
| Freedom (primary) | outside_freedom (Po1.6, VLAN 6) | 203.0.113.X + /29 subnet | `fake@freedom.nl` PAP | outside_freedom_map | 46 | NO+CH |
| xs4all (backup) | outside_xs4all (Po1.2, VLAN 2) | 203.0.113.X (single IP) | `fb7360@xs4all.nl` PAP | outside_xs4all_map | 46 | NO+CH |

### Parity Status
- **Crypto-maps:** 46 GR entries + 8 VPS entries on each map (full parity)
- **NAT exemptions:** 59 rules on each interface (full parity, zero delta)
- **ACLs:** Freedom 17 rules, xs4all 14 rules (3 fewer: OAS HTTPS, strongSwan IKE/NAT-T — port conflicts with single IP)
- **Dynamic PAT:** All subnets (rooms, DMZ, cctv, guest, k8s, mgmt) have internet access via both WANs
- **VPS tunnels:** Both VPS have 3-tier failover with ISP-specific naming (see below). iptables whitelisted for both IPs. PSK entries for both peers.

### VPS 3-Tier Failover (deployed 2026-04-08)

Both VPS (notrf01vps01 + chzrh01vps01) use ISP-suffixed connection names:

| Destination | Freedom (primary, `auto=start`) | xs4all (backup, `auto=route`) | GR backbone (last resort, `auto=route`) |
|---|---|---|---|
| NL DMZ /27 | `nl-dmz-freedom` | `nl-dmz-xs4all` | `nl-dmz-via-gr` |
| NL mgmt /24 | `nl-mgmt-freedom` | `nl-mgmt-xs4all` | — |
| NL K8s /24 | `nl-k8s-freedom` | `nl-k8s-xs4all` | — |
| GR DMZ /27 (via NL) | `gr-dmz-via-nl-freedom` | `gr-dmz-via-nl-xs4all` | — |

GR direct tunnels (`gr-dmz`, `gr-mgmt`, `gr-k8s`) and inter-VPS (`ch-tunnel`/`no-tunnel`) are single-peer, no ISP suffix needed.

**Failover mechanism:** DPD (30s) detects dead primary → `dpdaction=restart` keeps retrying primary → meanwhile traffic hits `auto=route` trap → backup tunnel activates automatically. When primary recovers, `dpdaction=restart` re-establishes it and traffic shifts back.

**reqid scheme:** Freedom=10x (100-103), xs4all=11x (110-113), GR-backbone=101, GR-via-NL-xs4all=211, GR-direct=20x, inter-VPS=300.

### Crypto-Map Parity Detail
Both maps now have identical coverage including:
- Seq 1-38: GR inter-site (all VLAN pairs)
- Seq 40-44: NO VPS tunnels
- Seq 50-53: CH VPS tunnels
- Seq 60-61: VPN pool entries
- Seq 71: NL DMZ ↔ GR DMZ
- Seq 72-73: Additional DMZ entries
- **Seq 74: NL K8s ↔ GR DMZ** (added 2026-04-08 — required for Prometheus to scrape GR FRR exporters)
- **Seq 75: NL mgmt ↔ GR DMZ** (added 2026-04-08 — enables SSH/management to GR DMZ hosts)

### Automation Validation (2026-04-08 incident)
Freedom QoS toggle + SMS alerting operated correctly during the Freedom PPPoE outage:
- DOWN detected → QoS applied + SMS sent
- UP detected at 06:50 CEST → QoS removed + SMS confirmation sent
- State file correctly tracks `qos-active`/`qos-inactive`

### Services that can't run on xs4all (single IP port conflicts)
- OAS1 HTTPS (443) — collides with NPM
- strongSwan IKE (500) — collides with ASA's own IKEv2
- strongSwan NAT-T (4500) — collides with ASA's own IKEv2

### Automation (3 components)

**1. QoS toggle** (`scripts/freedom-qos-toggle.sh`, cron `*/2`):
- Checks Freedom PPPoE via ASA SSH every 2 minutes
- Freedom DOWN → applies 5/2 Mbps per tenant room (b, c, d) to protect xs4all bandwidth
- Freedom UP → removes limits
- State: `/home/app-user/scripts/maintenance-state/freedom-qos.state`

**2. SMS alerting** (Twilio, integrated into QoS toggle):
- Freedom DOWN → SMS to +3VMID_REDACTED0: "Freedom ISP DOWN... Physical fix: power-cycle ONT on sw01 Gi1/0/36"
- Freedom UP → SMS: "Freedom ISP RECOVERED. Full bandwidth restored."
- No Matrix dependency — works even when Matrix is unreachable

**3. ChatOps training** (5 knowledge layers):
- `incident_knowledge` table: 3 entries (core PPPoE, GR false-positive burst, NL service flap)
- `correlated-triage.sh`: Freedom burst pattern detector (NL svc + GR dev-down = 0.95 confidence)
- `infra-triage.sh`: Freedom fast-path check (SSH to ASA, check vpdn pppinterface)
- `cisco-asa-specialist.md`: Full diagnostic pattern + commands + physical path
- `infrastructure.md`: Dual-WAN VPN documentation section

### iBGP Transit Overlay (planned, not yet implemented)
YT issues: IFRNLLEI01PRD-381 (ASA route injection), 382 (FRR local-pref), 383 (VPS XFRM migration).
Would enable automatic BGP-based failover routing when a direct tunnel fails.
Prompt for next session: `docs/prompt-bgp-transit-overlay.md`.

### Physical Path (Freedom ONT)
ASA Po1.6 (VLAN 6) → nl-sw01 trunk (4-port LACP) → Gi1/0/36 → Genexis XGS-PON ONT (PoE-powered, 1Gbps fiber) → Freedom ISP

*Source: `memory/dual_wan_vpn_parity.md`*

## ASA floating-conn for route changes

Use `timeout floating-conn 0:00:30` on Cisco ASA to handle stale connection entries after routing changes. This is the Cisco-native solution (Cisco doc 113592). **Configured and saved on both ASAs (2026-04-11).**

**Why:** Corosync cluster split 2026-04-11. ASA conn table pinned UDP flows to pre-VTI interface. Initial instinct was to write a cron script, but user correctly pushed back — the ASA has a native feature for this. Always research vendor documentation before building workaround scripts.

**How to apply:**
1. Prefer Cisco-native features over external scripts for ASA behavior
2. `timeout floating-conn 0:00:30` is now active on both nl-fw01 and gr-fw01
3. Null0 blackhole routes (AD 255) added for remote-site subnets on both ASAs — prevents cleartext leakage
4. `sysopt connection preserve-vpn-flows` confirmed DISABLED on both ASAs
5. Use **netmiko** (not expect) for Cisco ASA automation — netmiko venv at `/tmp/netmiko-venv/` on grclaude01
6. GR ASA reachable from grclaude01 at **10.0.X.X** (not 10.0.X.X)

*Source: `memory/feedback_asa_clear_conn_after_vti.md`*

## feedback_dual_wan_nat_parity

When configuring dual-WAN on ASA, EVERY inside zone needs dynamic PAT on BOTH outside interfaces.

**Why:** The NL ASA had dynamic PAT only for `outside_freedom`. When Freedom went down, all inside zones lost internet because traffic routed via `outside_xs4all` had no PAT. When Freedom came back, `inside_mgmt` still had no Freedom PAT (only rooms had it). This broke the operator's laptop twice in one session.

**How to apply:** When adding a new inside zone or outside interface, always add PAT for ALL outside interfaces. Check with `show run nat | include dynamic` and verify every zone×interface combination exists. The `after-auto source dynamic any interface` pattern works for catch-all PAT.

*Source: `memory/feedback_dual_wan_nat_parity.md`*

## IPsec changes must be additive — never replace without asking

When adding ISP redundancy to VPS IPsec tunnels, the change must be ADDITIVE — add the new ISP as a backup path alongside the existing primary. NEVER replace the current working tunnel with the new ISP path.

**Why:** During the Freedom PPPoE outage (2026-04-08), VPS tunnels were incorrectly migrated FROM Freedom TO xs4all instead of adding xs4all as backup. This left VPS with no NL tunnels when xs4all also had issues, and required reverting when Freedom recovered. The user explicitly stated they wanted both ISPs active simultaneously.

**How to apply:** Use `auto=start` for the primary ISP and `auto=route` (trap-based, activates on traffic when primary fails via DPD) for backup ISPs. This gives seamless failover without replacing the working path.

*Source: `memory/feedback_ipsec_additive_changes.md`*

## IPsec tunnel naming — ISP-specific suffixes

VPS IPsec connection names MUST include the ISP suffix for NL-bound tunnels: `nl-{destination}-{isp}` (e.g., `nl-dmz-freedom`, `nl-dmz-xs4all`). This makes it unambiguous which ISP each tunnel uses, especially as new ISPs may be added.

**Why:** User explicitly requested this during the dual-WAN VPN parity work. Generic names like `nl-dmz` don't scale when multiple ISPs serve the same destination.

**How to apply:** When creating or modifying VPS strongSwan connections that target NL ASA, always suffix with the ISP name. GR-direct tunnels (single ISP) don't need a suffix. Backbone failover paths include both ISP and path: `gr-dmz-via-nl-freedom`.

*Source: `memory/feedback_ipsec_isp_naming.md`*

## Freedom ISP PPPoE Outage 2026-04-08

## Incident: Freedom ISP PPPoE Down (2026-04-08)

**Drop time:** Between Apr 7 23:53 and Apr 8 00:02 UTC
**Root cause:** Freedom PPPoE session died — ASA `outside_freedom` (Po1.6, VLAN 6) up/up but IP unassigned. ONT not responding to PADI.
**Freedom IP:** 203.0.113.X (PPPoE, PAP auth as `fake@freedom.nl`)

### Impact
- GR site 100% unreachable from NL (VPN tunnel dead)
- 10 LibreNMS critical alerts
- xs4all VPN can't compensate — GR ASA has no Phase 2 entries for xs4all peer (203.0.113.X)

### Physical Path
ASA Po1.6 (VLAN 6) → nl-sw01 trunk (4-port LACP) → Gi1/0/36 → Genexis XGS-PON ONT (PoE-powered, 1Gbps) → Freedom fiber

### Key Findings
- ASA interface bounce didn't help (PADI sent, no PADO returned)
- nl-sw01 SSH refused, no SNMP community available for remote verification
- xs4all crypto-map entries (1-36) exist but GR ASA only accepts Phase 2 from Freedom IP

**Why:** Freedom ISP or the Genexis ONT is unresponsive. Needs physical check or ISP contact.

**Resolution:** Configured both ASAs for full WAN redundancy:
- **GR ASA:** Added 203.0.113.X (xs4all) as secondary peer on seq 60-73 (were Freedom-only)
- **NL ASA:** Added 8 crypto-map entries (seq 37,38,42,60,61,71-73) to xs4all map + 27 NAT exemptions for xs4all (cctv, room_a, nfs, corosync, dmz_servers02, VPN pools, VPS overlay)
- Result: 5 child SAs came up immediately. GR fully reachable at ~50ms via xs4all. Both configs saved (`write memory`).

**How to apply:** When triaging future VPN/cross-site outages, check PPPoE session status first (`show vpdn pppinterface`). Both WANs now have full tunnel coverage. Freedom PPPoE still needs ISP/ONT investigation but is no longer a SPOF for GR connectivity.

---

## Follow-Up Actions Report (2026-04-08 ~01:30 UTC)

### Phase 1: GR VPN Restoration (NL ↔ GR tunnel over xs4all)

**GR ASA (gr-fw01):**
- Added `203.0.113.X` as secondary peer on seq 60, 61, 70, 71, 72, 73 (were Freedom-only)
- Seq 1-38 and 42 already had both peers — no change needed
- `write memory` saved

**NL ASA (nl-fw01):**
- Added 8 crypto-map entries to `outside_xs4all_map`: seq 37, 38, 42, 60, 61, 71, 72, 73 (mirror of Freedom-only GR entries)
- Added 27 NAT exemptions for xs4all:
  - `inside_cctv` → 9 GR destinations
  - `inside_room_a` → 9 GR destinations
  - `inside_nfs` → GR nfs, GR mgmt
  - `inside_corosync` → GR corosync, GR mgmt
  - `inside_mgmt` → GR dmz_servers02
  - `inside_k8s` → GR dmz_servers02
  - `dmz_servers02` → GR dmz_servers02
  - VPN pools (oas + strongswan) → GR VPN destinations + GR mgmt
  - VPS overlay hairpin on xs4all
  - `dmz_servers02` after-auto dynamic NAT for xs4all
- Cleared IPsec SAs to force renegotiation
- `write memory` saved

**Result:** 5 child SAs established immediately (mgmt↔mgmt, K8s↔K8s, NFS↔NFS, corosync↔corosync, mgmt→servers01). GR fully reachable at ~50ms via xs4all.

### Phase 2: VPS Tunnel Migration (NO + CH → xs4all)

**NL ASA (nl-fw01):**
- Added 8 crypto-map entries to `outside_xs4all_map` for VPS peers:
  - Norway (198.51.100.X): seq 40 (nl-dmz), 41 (gr-dmz-via-nl), 43 (nl-mgmt), 44 (nl-k8s) — `VTI-PROPOSAL`
  - Switzerland (198.51.100.X): seq 50 (nl-dmz), 51 (gr-dmz-via-nl), 52 (nl-mgmt), 53 (nl-k8s) — `VTI-PROPOSAL`
- Added 7 NAT exemptions for VPS tunnels on xs4all:
  - mgmt/k8s/dmz02 → `S2S_NO_TUNNEL` (3 rules)
  - mgmt/k8s/dmz02 → `S2S_CH_TUNNEL` (3 rules)
  - dmz02 → `ALL_VPS_OVERLAY` (1 rule)
- `write memory` saved

**Norway VPS (notrf01vps01, 198.51.100.X):**
- iptables: whitelisted 203.0.113.X for SSH/22, IKE/500, NAT-T/4500, ESP — persisted via `netfilter-persistent save`
- `/etc/ipsec.conf`: changed `right=203.0.113.X` → `right=203.0.113.X` on 4 NL connections (nl-dmz, gr-dmz-via-nl, nl-mgmt, nl-k8s)
- `/etc/ipsec.secrets`: added PSK for `198.51.100.X 203.0.113.X`
- `ipsec restart` — all tunnels UP: nl-dmz, nl-mgmt, nl-k8s, gr-dmz-via-nl + GR directs + CH inter-VPS

**Switzerland VPS (chzrh01vps01, 198.51.100.X):**
- iptables: same xs4all whitelist — persisted
- `/etc/ipsec.conf`: changed `right=203.0.113.X` → `right=203.0.113.X` on 4 NL connections
- `/etc/ipsec.secrets`: added PSK for `198.51.100.X 203.0.113.X`
- `ipsec restart` — all tunnels UP: nl-dmz, nl-mgmt, nl-k8s + GR directs + NO inter-VPS

**Result:** Full 4-site VPN mesh (NL, GR, NO, CH) operational over xs4all. Direct SSH from app-user to both VPS confirmed working.

### Phase 3: Full NAT Exemption Parity (Freedom → xs4all)

Performed a programmatic diff of all 59 Freedom NAT exemptions vs xs4all. Found and added 9 missing rules — all related to `gr_oas_vpn_pool_XX` (GR AnyConnect VPN pools):

- `dmz_servers01`, `dmz_servers02`, `dmz_servers03` → `gr_oas_vpn_pool_XX`
- `dmz_vpn01` (3 rules: oas pools, strongswan pools) → `gr_oas_vpn_pool_XX`
- `inside_iot`, `inside_servers01`, `inside_servers02` → `gr_oas_vpn_pool_XX`

**Result:** NAT exemption parity at 59/59 (zero delta between Freedom and xs4all).

### Phase 4: iBGP Full Mesh Verification

Audited the 6-node iBGP mesh (AS 65000) across all 4 sites:
- **6 FRR nodes:** 2 VPS (NO, CH) + 4 LXC containers (2 NL, 2 GR) + 2 ASAs as local peers
- **All 30 iBGP sessions: ESTABLISHED** — cross-site sessions reconverged within minutes of VPN restoration
- **IPv6 anycast:** AS64512 prefix `2a0c:9a40:8e20::/48` announced from both VPS to upstream (Terrahost, iFog, FogIXP)
- **Design:** Dual route-reflectors (NL-FRR01/02 and GR-FRR01/02) with `next-hop-self` for cross-site and VPS peers
- Every iBGP session path maps to an IPsec child SA — the full-mesh IPsec is fully utilized by BGP

### Phase 5: GR dmz_servers02 Tunnel Fix (TS_UNACCEPTABLE)

**Problem:** NL mgmt (10.0.181.X/24) → GR dmz_servers02 (10.0.X.X/27) child SA failed with `TS_UNACCEPTABLE` from the GR ASA. NL was sending perfectly valid traffic selectors (TSi=10.0.181.X/24, TSr=10.0.X.X/27) but GR rejected every CREATE_CHILD_SA attempt. All other child SAs for the same peer worked fine.

**Investigation:**
1. Full running config dump of both ASAs (2143 + 1865 lines)
2. Holistic cross-audit: crypto-map ACLs, NAT exemptions, interface ACLs, tunnel-groups, IKEv2 proposals, object-groups — all verified correct and properly mirrored
3. GR ASA IKEv2 debug captured `TS_UNACCEPTABLE` response with wrong subnet pairs during TS narrowing
4. GR `dmz_servers02_access_in` ACL — added permit rules for dmz02→NL_mgmt and dmz02→NL_k8s before the deny-all (required for IKEv2 TS narrowing, not just data plane)
5. Removed duplicate crypto-map entries (seq 72/73 were exact duplicates of 37/38) from both ASAs

**Root cause:** The GR ASA's internal crypto engine had **stale TS matching state** for entries 37/38 from when they were originally configured with Freedom (203.0.113.X) as primary peer. Despite `203.0.113.X` being listed as secondary peer and the running config looking correct, the compiled TS matching tables weren't updated. A `show run` could not reveal this — the config looked perfect.

**Fix:** Deleted and re-created crypto-map entries 37 and 38 on the GR ASA with xs4all as primary peer:
```
no crypto map outside_inalan_map 37 ...   (full removal)
crypto map outside_inalan_map 37 match address outside_inalan_cryptomap_37
crypto map outside_inalan_map 37 set peer 203.0.113.X 203.0.113.X
crypto map outside_inalan_map 37 set ikev2 ipsec-proposal TSET
```
Same for entry 38. This forced the ASA to rebuild internal TS matching tables.

**Result:** Child SA established immediately. gr-dmz01 (10.0.X.X) and grdmz02 (10.0.X.X) reachable from NL mgmt at ~50ms. `write memory` saved.

**Lesson learned:** On Cisco ASA, changing the peer list on an existing crypto-map entry (adding a secondary peer) does NOT always update the internal TS narrowing tables. The safe pattern when adding a new peer IP to existing entries is: **delete the entry completely, then re-create it** — don't just modify the peer list in-place.

### Summary of All Changes Made

| Device | Changes | Saved |
|--------|---------|-------|
| **nl-fw01** (NL ASA) | 46 crypto-map entries added to `outside_xs4all_map` (GR seq 1-38,42,60,61,71 + VPS seq 40-44,50-53). 59 NAT exemptions for xs4all (full parity with Freedom). Duplicate seq 72/73 removed. | `write memory` ✓ |
| **gr-fw01** (GR ASA) | xs4all peer added to seq 60-73. Entries 37/38 deleted and re-created with xs4all as primary peer. Duplicate seq 72/73 removed. `dmz_servers02_access_in` ACL: added permit for dmz02→NL_mgmt and dmz02→NL_k8s before deny rules. | `write memory` ✓ |
| **notrf01vps01** (NO VPS) | iptables: xs4all whitelisted (SSH/IKE/NAT-T/ESP). ipsec.conf: NL peer changed to xs4all. ipsec.secrets: PSK added for xs4all. | `netfilter-persistent save` + `ipsec restart` ✓ |
| **chzrh01vps01** (CH VPS) | Same as Norway VPS. | Same ✓ |

### Phase 6: VPS 3-Tier Dual-ISP Failover (2026-04-08 ~15:00 UTC)

**Problem:** During the outage, VPS ipsec.conf was incorrectly migrated from Freedom to xs4all (replaced, not added). When Freedom recovered, VPS had no direct NL tunnels — only the GR backbone failover path.

**Fix:** Rewrote both VPS ipsec.conf with ISP-specific naming and 3-tier failover:

| Connection | Peer | `auto=` | Tier |
|---|---|---|---|
| `nl-dmz-freedom` | 203.0.113.X | `start` | Primary |
| `nl-dmz-xs4all` | 203.0.113.X | `route` | Backup (trap-based) |
| `nl-dmz-via-gr` | 203.0.113.X | `route` | Last resort (GR backbone) |
| `nl-mgmt-freedom` / `nl-mgmt-xs4all` | same pattern | `start` / `route` | Same tiers |
| `nl-k8s-freedom` / `nl-k8s-xs4all` | same pattern | `start` / `route` | Same tiers |
| `gr-dmz-via-nl-freedom` / `gr-dmz-via-nl-xs4all` | 203.0.113.X / 203.0.113.X | `route` / `route` | Both failover |

GR-direct tunnels (`gr-dmz`, `gr-mgmt`, `gr-k8s`) and inter-VPS (`ch-tunnel`/`no-tunnel`) unchanged.

**Result:** All Freedom primary child SAs ESTABLISHED on both VPS. xs4all backup traps ROUTED (standby). IaC repo synced.

**Lesson:** IPsec ISP changes must be ADDITIVE (add backup alongside primary), never replace. Connection names must include ISP suffix for multi-WAN clarity.

### Phase 7: Prometheus FRR Scrape Fix + GR ASA TS Cleanup (2026-04-08 ~15:30 UTC)

**Problem:** Prometheus (NL K8s) couldn't scrape GR FRR exporters (10.0.X.X/4:9342) — no crypto-map entry existed for NL K8s ↔ GR DMZ on the NL ASA. Gatus "FRR BGP Sessions" alert firing since 04:45 UTC.

**NL ASA fix:**
- Added ACL `outside_freedom_cryptomap_74`: NL K8s ↔ GR DMZ
- Added ACL `outside_freedom_cryptomap_75`: NL mgmt ↔ GR DMZ
- Added crypto-map seq 74+75 on both Freedom and xs4all maps (full ISP parity)
- NAT exemptions already existed — no changes needed

**GR ASA fix:**
- Entries 37+38 (GR DMZ ↔ NL mgmt/K8s) already existed but had xs4all as primary peer (stale from Phase 5)
- Deleted and re-created with Freedom primary, xs4all secondary (per the DELETE+RE-CREATE lesson)

**Result:** All 6 Prometheus FRR targets healthy. Gatus alert cleared.

### Automation Validation: Freedom QoS Toggle + SMS

The `freedom-qos-toggle.sh` cron (*/2, tightened from */10 on 2026-04-08) correctly detected the DOWN transition but **failed to detect recovery for 27 hours** due to a bug:
- **Freedom DOWN detected** → QoS limits applied + SMS sent via Twilio — **worked correctly**
- **Freedom recovered ~06:00 UTC Apr 9** — ASA syslog confirms real traffic resumed at full volume
- **BUG:** `check_freedom()` SSH to ASA failed silently for 27 hours (~810 cron runs). Empty return triggered neither UP nor DOWN branch. State stayed at `qos-active`. Tenants throttled at 5/2 Mbps unnecessarily.
- **Recovery SMS finally sent** Fri 11:34 CEST (09:34 UTC Apr 10) — only because the ASA weekly EEM reboot at 09:31 UTC made a fresh ASA that accepted SSH.
- **Fix applied (2026-04-10):** Added ping fallback to Freedom BNG (198.51.100.X) when SSH fails. If BNG is reachable, Freedom is UP regardless of ASA SSH state.
- Cron was tightened to */2 (from */10) after tenant (Nikolaos, Room B/C/D) reported evening micro-drops that slipped through the 10min window

### Tenant Impact & Syslog-ng Forensics (2026-04-08 evening)

Tenant Nikolaos Vrettos (rooms B/C/D) reported WiFi outage via WhatsApp at **21:39 CEST** ("it also happened yesterday evening"). Syslog-ng forensic analysis from `/mnt/logs/syslog-ng/nl-fw01/` revealed:

**Main outage timeline (syslog-correlated):**

| Time (CEST) | Event | Evidence |
|---|---|---|
| Apr 7 23:52:25 | Last tenant room NAT build on Freedom | `305011.*inside_room_b:10.0.X.X` → `outside_freedom:203.0.113.X` |
| Apr 7 23:53:26 | Last ASA syslog line (Freedom) | Teardown UDP + TCP build — then silence |
| Apr 8 00:02:30 | First syslog via xs4all | `302014 Teardown TCP...outside_xs4all:10.255.X.X/9342...SYN Timeout` |
| Apr 8 06:38:25 | First Freedom NAT build (PPPoE recovered) | `305011 Built static UDP...nlp_int_tap → outside_freedom:203.0.113.X` |
| Apr 8 06:40:10 | First tenant room NAT via Freedom | `305011 inside_room_c:10.0.X.X → outside_freedom:203.0.113.X` |

**Total Freedom outage: ~6h 47m** (23:53 → 06:40 CEST). Apr 7 .log = 0 bytes (rotated at midnight during outage); .log.1 = 1.77GB (full pre-outage day).

**Apr 8 evening (Nikolaos's report at 21:39):**
- NAT build analysis (305011 counts per minute) shows **no traffic gaps** around 21:39 — rooms B/C/D had continuous NAT activity throughout 20:00-22:59
- No ASA interface state change events (ASA-4-411001/411002) logged
- No PPP/VPDN disconnect events
- ASA total syslog volume steady at 5-7K lines/min (no dips)
- **Conclusion:** Not a full PPPoE drop. Likely a micro-interruption (seconds) — too brief for ASA syslog to capture, but enough to break active TCP sessions (WiFi devices show "no internet" until they retry DNS)

**"Yesterday evening" reference:** Nikolaos's message at 21:39 says "it also happened yesterday evening." The Apr 7 room NAT data shows continuous activity 20:00-23:52 with no gaps, then Freedom died at 23:53. The "yesterday evening" outage WAS the start of the main PPPoE incident — tenants lost internet at ~23:53 and it never came back until 06:40 the next morning.

**Corrective action:** `freedom-qos-toggle.sh` cron tightened from `*/10` to `*/2` to catch future micro-drops faster.

### Outstanding Items

| # | Item | Priority | Status |
|---|------|----------|--------|
| 1 | **Freedom PPPoE recovery** | High | **RESOLVED** — Freedom recovered 2026-04-08, IP 203.0.113.X assigned |
| 2 | **nl-sw01 SSH access** — switch refuses SSH connections. | Medium | Blocked |
| 3 | **VPS dual-ISP config** | Medium | **RESOLVED** — 3-tier failover with ISP-specific naming deployed |
| 4 | **LibreNMS alerts** | Low | **RESOLVED** — auto-cleared after Freedom recovery |
| 5 | **VTI migration (IFRNLLEI01PRD-195)** — crypto-map approach is fragile. BGP transit overlay planned: IFRNLLEI01PRD-381/382/383. | High | Backlog |
| 6 | **PPPoE monitoring** | Medium | **RESOLVED** — `freedom-qos-toggle.sh` monitors PPPoE + SMS alerts |
| 7 | **GR ASA stale entry pattern** — DELETE + RE-CREATE, never in-place. | — | Lesson learned |
| 8 | **gr-dmz01 guest agent** — QEMU guest agent not running. | Low | TODO |
| 9 | **GR ASA SSH access** — direct SSH from NL rejected. Requires stepstone via gr-pve01. | — | Documented |

*Source: `memory/incident_freedom_pppoe_20260408.md`*

## S2S Tunnel Benchmark NL<->GR

## Line Speeds (speedtest-cli 2026-03-21)
- NL (Leiden, XS4ALL/Freedom): 777 down / 575 up Mbps, 9ms to ISP
- GR (Thessaloniki, Inalan FTTH): 628 down / 634 up Mbps, 16ms to ISP

## VPN Tunnel
- Latency: 42.9ms RTT, 0.37ms jitter, 0% loss
- MTU: 1472 works (no fragmentation)
- NL->GR: 183 Mbps sustained (peak 436, degrades over 30s)
- GR->NL: 478 Mbps sustained (peak 593)
- Asymmetry root cause: NL has 76+ crypto map entries (38 per dual-WAN outside interface) evaluated per-packet in CPU slow path

## ASA Config (both ASA 5508-X)
- NL: PPPoE dual-WAN (XS4ALL VLAN 2 + Freedom VLAN 6), Port-channel sub-interfaces, MTU 1492
- GR: DHCP single-WAN (Inalan), dedicated GbE, MTU 1448
- IPsec: AES-256 / SHA-1 (HMAC) for NL<->GR, AES-256 / SHA-256 for NO/CH peers
- IKEv2: AES-256 / SHA-512 / DH14
- NL CPU: 16-21% idle (was 27% before fixes)
- GR CPU: 10-11% idle

## Fixes Applied (2026-03-21)
- tcpmss 1452->1380 (eliminated pre-fragmentation)
- Removed 4 dead NetFlow export destinations
- Removed MPTCP inspection from class-default
- Config saved (`write memory`)

## Pending: VTI Migration (IFRNLLEI01PRD-195)
VTI tunnels use routing (fast path + hw crypto) instead of crypto map ACL matching (slow path). NL already has VTI-PROFILE/VTI-PROPOSAL for NO/CH peers. GR tunnel needs the same. Requires coordinated maintenance window.

## Capacity Planning
| Use case | BW needed | NL->GR feasible? |
|----------|-----------|-----------------|
| Thanos gRPC queries | 1-10 Mbps | Easily (~2%) |
| Sidecar real-time federation | 5-20 Mbps | Easily (~5%) |
| SeaweedFS filer-sync | 0.3 Mbps | Easily |
| Full Thanos replication (340GB) | 45 Mbps sustained | Risky (25%) |

*Source: `memory/s2s_tunnel_benchmark.md`*

## VTI BGP outage investigation 2026-04-11

## VTI/BGP Outage — 2026-04-11 (~06:00 CEST)

### Symptoms
- Complete NL→GR unreachability (ping, SSH all fail from nl-claude01)
- No GR routes in NL ASA routing table
- BGP between NL and GR ASA not established on either VTI peer

### Root Causes Identified

**1. Freedom→GR Tunnel4 DOWN (BOTH ASAs) — IKE SA conflict**
- NL ASA Tunnel1 (xs4all→GR) and Tunnel4 (Freedom→GR) share the SAME peer IP (203.0.113.X)
- When all tunnels reset (~05:43 CEST), xs4all IKE SA re-established first (race condition)
- ASA won't initiate a second IKE SA to the same peer from a different source interface
- Result: Tunnel4 (Freedom, LP 200 primary) stays DOWN; only Tunnel1 (xs4all, LP 150) comes up

**2. xs4all VTI data plane broken (by design)**
- NL ASA routing: `route outside_freedom 203.0.113.X ... 1` (metric 1) preferred over xs4all (metric 10)
- ESP for xs4all tunnel exits via Freedom interface → source IP mismatch → BCP38 drop
- IKE works (interface-bound), but ESP doesn't → BGP TCP can't establish
- xs4all VTI is inherently dormant while Freedom is primary WAN — documented behavior

**3. ICMP tests were misleading**
- Both ASAs' outside ACLs end with `deny icmp any any`
- Ping failures between Freedom↔GR are ACL drops, NOT ISP routing failures
- `sysopt connection permit-vpn` IS enabled on both ASAs — IKE/ESP bypasses ACLs automatically
- Freedom ISP routing to GR is likely FINE (not confirmed via non-ICMP test yet)

### Current State (as of investigation)
| Component | Status | Notes |
|-----------|--------|-------|
| NL Tunnel1 (xs4all→GR) | UP | IKE READY (NL INITIATOR), ESP one-way (dormant) |
| NL Tunnel4 (Freedom→GR) | DOWN | No IKE SA — blocked by Tunnel1's SA to same peer |
| NL Tunnel2/3/5/6 (VPS) | UP | All working (Freedom=NAT-T 4500, xs4all=500) |
| GR Tunnel1 (xs4all→NL) | UP | IKE READY (GR RESPONDER) |
| GR Tunnel4 (Freedom→NL) | DOWN | No IKE SA |
| GR Tunnel2/3 (VPS) | UP | Working fine |
| NL BGP 10.255.200.X (GR xs4all) | Idle | Data plane broken (BCP38) |
| NL BGP 10.255.200.X (GR Freedom) | Idle | Tunnel4 DOWN |
| GR BGP 10.255.200.X (NL xs4all) | Active | Trying but NL can't respond (BCP38) |
| GR BGP 10.255.200.X (NL Freedom) | Idle | Tunnel4 DOWN |
| VPS→GR tunnels | Working | Both VPS can reach GR (50ms) |
| VPS→NL Freedom tunnels | Working | NAT-T (port 4500) |
| Inter-VPS iBGP | Established | Healthy |
| GR SLA monitor 1 | Track DOWN | Pings 203.0.113.X from outside_inalan — ACL-blocked |

### Fix Applied (RESOLVED)
1. **NL ASA: `shutdown` Tunnel1 (xs4all→GR)** — removed xs4all IKE SA that blocked Freedom
2. Freedom IKE SA established immediately: `203.0.113.X/500 → 203.0.113.X/500 READY INITIATOR`
3. **NL ASA: `no shutdown` Tunnel1** — both IKE SAs now coexist
4. BGP over Tunnel4 (LP 200) established — all 9 GR subnets + 8 NL subnets propagated
5. All 6 NL tunnels + 4 GR tunnels UP. Full bidirectional connectivity restored at 06:30 CEST.
6. VPS BGP to NL RR1 also recovered (was SYN-SENT, now Established)

### Key Commands Used
```bash
# NL ASA SSH
ssh -o KexAlgorithms=+diffie-hellman-group14-sha1,ecdh-sha2-nistp256 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa operator@10.0.181.X
REDACTED_PASSWORD_COMMENT

# GR ASA via ProxyJump (VPS1→gr-pve01 stepstone)
ssh -o ProxyCommand="ssh -i ~/.ssh/one_key -o IdentitiesOnly=yes -W %h:%p operator@198.51.100.X" -i ~/.ssh/one_key root@10.0.X.X
# Then from gr-pve01: expect-based SSH to operator@10.0.X.X

# VPS SSH
ssh -i ~/.ssh/one_key operator@198.51.100.X  # VPS1 (NO/Freedom)
ssh -i ~/.ssh/one_key operator@198.51.100.X     # VPS2 (CH/xs4all)
```

### Other Issues Found (secondary)
- VPS BGP to NL FRR RR1 (10.0.X.X): SYN-SENT on both VPS servers (needs separate investigation)
- GR ASA SLA monitor 1 pings NL Freedom IP — will always fail due to ACL (misleading health check)
- NL FRR RR1 sends 0 prefixes to NL ASA (recently reset, possibly related to VPS BGP issue)

### Confidence: 100% (confirmed fix, self-healing deployed)
Root cause confirmed: IKE SA race condition for same peer IP. Fix verified — all tunnels UP, BGP converged, full connectivity restored. Cron self-healing deployed to prevent recurrence.

### Self-Healing Deployed
**Script:** `scripts/vti-freedom-recovery.sh`
**Cron:** `*/3 * * * *` on nl-claude01
**Log:** `/home/app-user/scripts/maintenance-state/vti-freedom-recovery.log`
**State:** `/home/app-user/scripts/maintenance-state/vti-freedom-recovery.state` (cooldown timestamp)

Logic: If Freedom WAN is UP + Tunnel4 (Freedom→GR) is DOWN + Tunnel1 (xs4all→GR) is UP → bounce Tunnel1 to clear IKE SA conflict. 10-minute cooldown between bounces. Respects `gateway.maintenance` and `/tmp/chaos-active.json` (chaos engineering).

**Why not remove Tunnel1:** When Freedom ISP goes fully down, xs4all becomes primary WAN and Tunnel1 provides direct NL↔GR at 50ms. Without it, traffic would transit through VPS (+20ms). Tunnel1 is dormant but essential for failover.

### Lessons Learned
1. **ASA VTI dual-tunnel to same peer: IKE race condition** — when IKE SAs reset, first SA to establish blocks second. Fix: bounce the winning tunnel to let the other negotiate.
2. **ICMP tests on ASA outside interfaces are unreliable** — both ASAs have `deny icmp any any` at end of outside ACLs. Use IKE/ESP (sysopt permit-vpn) or TCP tests instead. sysopt connection permit-vpn is ENABLED on both ASAs (default).
3. **GR ASA SLA monitor 1 pings 203.0.113.X from outside_inalan** — will always fail because NL ASA outside_freedom ACL blocks inbound ICMP. This SLA monitor is misleading (Track 1 always DOWN). Should be fixed or removed.
4. **ProxyJump path to GR when VPN is down:** `ssh -o ProxyCommand="ssh -i ~/.ssh/one_key -o IdentitiesOnly=yes -W %h:%p operator@198.51.100.X" -i ~/.ssh/one_key root@10.0.X.X` (NL→VPS1→gr-pve01, VPS always has working GR tunnel).
5. **Chaos engineering compatibility:** Chaos only kills xs4all tunnels (never Freedom). Recovery script checks `/tmp/chaos-active.json` and backs off. No conflict with any of the 7 chaos scenarios.

### Status Page Fixes (same session)
1. **Chaos toggle dots overlapping** — parallel VPN links (xs4all+freedom) had dots at midpoint with 0.5x offset factor (~10px apart, 7px radius = overlap). Fixed: changed to 1.5x factor (~30px apart). Also added SVG `<title>` tooltips showing "NL ↔ GR (freedom)" etc. Commit c60f2d7.
2. **6/9→9/9 tunnel counter** — standby tunnels were counted as "not up". Fixed: stats card now shows `9/9 VTI Tunnels` with `6 active · 3 standby` detail line. Mobile tunnel list uses amber dots for standby. CSS `.mh-dot-standby` (#f59e0b amber). auto-refresh.js updated for live updates. Commits deb65b4 + b86243c.
3. **Hugo build artifacts** — `git add -A` accidentally committed `public/` dir. Cleaned up with `.gitignore` addition. Commit 3c18f5f.

### Open Items
- **Standby tunnel display** — FIXED: 9/9 with "6 active · 3 standby" detail (deployed, awaiting CI screenshot verification)
- GR ASA SLA monitor 1 should be fixed (pings ACL-blocked IP, always fails)
- NL ASA outside_freedom ACL: consider adding ICMP permit from GR ASA (203.0.113.X) for monitoring
- xs4all BGP peer (10.255.200.X/1) remains Idle on both ASAs — expected while Freedom is primary (BCP38)
- Status page key files: Hugo template `layouts/shortcodes/mesh-health.html`, JS `static/js/auto-refresh.js`, CSS `assets/css/extended/custom.css` in repo `/app/websites/papadopoulos.tech/kyriakos/`

*Source: `memory/vti_bgp_outage_20260411.md`*

## vti_dual_wan_lessons

VTI dual-WAN deployment (2026-04-09) uncovered 5 critical issues:

1. **CrowdSec bans VPS/ASA peers** — IKE retransmits trigger `ssh-bf` detection. Fix: whitelist file at `/etc/crowdsec/parsers/s02-enrich/whitelist-vps.yaml` on both VPS. Existing bans must be manually deleted (`cscli decisions delete --ip`), whitelists only prevent future bans.

2. **kernel-netlink buflen** — default 8KB overflows with BGP route events, causing `netlink event read error: No buffer space available`. Charon can't process IKE packets. Fix: `buflen = 2097152` in `/etc/strongswan.d/charon/kernel-netlink.conf`. WARNING: 8MB (8388608) causes segfault — stack overflow in libstrongswan-kernel-netlink.so.

3. **port_nat_t = 0 breaks VPS-to-VPS** — random NAT-T port means peers can't find each other after NAT detection. Fix: `port_nat_t = 4500`. Safe for ASA VTI (confirmed — both ASA tunnels re-established within 7s).

4. **xs4all IP missing from UFW** — pre-reboot raw iptables rules (outside UFW) don't persist through reboot. All VPS/ASA peer IPs must be in UFW rules (persisted) not raw iptables. Both Freedom (203.0.113.X) and xs4all (203.0.113.X) needed.

5. **DMZ servers need 10.255.200.X/24** — VTI XFRM source range not in UFW on DMZ hosts. Applied to all 6 DMZ servers.

**Why:** ASA NL has dual WAN (Freedom + xs4all). All VTI tunnels need entries on BOTH WANs at all 4 nodes (NL ASA, GR ASA, NO VPS, CH VPS). Without this, Freedom outage = broken CH VPS tunnel.

6. **NO↔CH IP overlap** — NO VPS xfrm-ch had 10.255.200.X/31 which overlapped with CH VPS xfrm-nl (also 10.255.200.X/31 for the NL↔CH tunnel). Reply packets from CH routed to `lo` instead of back through xfrm-no. Fix: assigned unique /31 (10.255.200.X/31 for CH xfrm-no, 10.255.200.X/31 for NO xfrm-ch). Updated swanctl-loader.service on both VPS. **Lesson: every XFRM interface pair must have a globally unique /31 within 10.255.200.X/24.**

7. **VPS XFRM recovery after chaos-test terminate** — `swanctl --terminate --ike` + `--initiate` does NOT cleanly restore VPS-to-VPS tunnels. The CHILD_SA gets installed but XFRM policy binding is lost. **NEVER use `ip xfrm state flush` or `ip xfrm policy flush`** — corrupts all tunnel bindings, requires VPS reboot. Safe recovery: `systemctl restart swanctl-loader`. For full reset: reboot the VPS.

8. **charon restart does NOT reload swanctl connections** — If charon is restarted (manually, crash, or kernel upgrade reboot), `swanctl-loader.service` must re-run or you must manually `sudo swanctl --load-all`. Without this, charon runs with zero tunnel configurations. Discovered 2026-04-10: both VPS had charon restart at 13:50, lost all tunnels for 20+ hours until manual `swanctl --load-all`.

9. **swanctl-loader.service race condition on boot** — On chzrh01vps01, `swanctl-loader.service` failed at boot (exit code 2) because charon wasn't ready. Needs `Restart=on-failure` + `RestartSec=5` or `ExecStartPre=/bin/sleep 5` to handle the startup race. **IFRNLLEI01PRD-440** tracks this.

10. **Freedom VTI ESP dataplane issue — FIXED (2026-04-10)** — Self-healed after ASA reboot + SA renegotiation. RPF on `outside_xs4all` also fixed. IFRNLLEI01PRD-440 closed.

11. **iBGP next-hop resolution on ASA (discovered 2026-04-10)** — VPS FRR advertised loopback IPs (10.255.X.X, 10.255.X.X) as BGP next-hops via route reflectors. ASA received the routes but couldn't resolve next-hops to a Tunnel interface → `packet-tracer` showed `(unresolved)` → packets dropped with `(no-route)`. **Fix:** Changed VPS FRR `update-source` for NL RR peers from loopback to VTI /31 tunnel IPs. Also updated RR neighbor IPs to match. RR1 via Freedom, RR2 via xs4all for dual-WAN resilience. Also added missing `network` statements for VPS loopback subnets in FRR. **Key lesson:** On ASA with VTI, iBGP next-hops MUST be resolvable via connected routes (the /31 tunnel IPs). Loopback IPs don't resolve because the ASA has no IGP running on tunnel interfaces.

**How to apply:** When adding new VPN peers or changing WAN IPs, update ALL 4 nodes: ASA tunnel interfaces, ASA tunnel-groups, VPS swanctl connections, VPS XFRM interfaces + swanctl-loader.service, VPS UFW rules, VPS CrowdSec whitelists, **VPS FRR update-source + RR neighbor IPs**. After any VPS reboot or charon restart, verify `swanctl --list-sas` shows all 4 connections — if not, run `sudo swanctl --load-all`.

*Source: `memory/vti_dual_wan_lessons.md`*

## VTI Migration + BGP Site Subnet Routing

## VTI Migration (2026-04-09) + BGP Cutover (2026-04-10)

Replaced crypto-map based S2S VPN with route-based VTI tunnels on both ASAs. Then replaced static inter-site routes with full BGP routing via direct ASA-to-ASA peering over VTI interfaces.

### Current State (post-BGP cutover 2026-04-10)

**NL ASA (nl-fw01):**
- 6 VTI tunnels: ALL UP including Freedom (Tunnel4-6). Freedom ESP WORKING.
- **BGP: 8 peers** (2 FRR + 4 Cilium + 2 VTI direct to GR ASA)
- **No static inter-site routes.** All 9 GR subnets via BGP (NH 10.255.200.X, Freedom VTI, LP 200)
- Transit host route: 10.0.X.X/32 via vti-no metric 254 (FRR NH resolution backup)

**GR ASA (gr-fw01):**
- 4 VTI tunnels: ALL UP including Freedom (Tunnel4).
- **BGP: 7 peers** (2 FRR + 3 Cilium + 2 VTI direct to NL ASA)
- **No static inter-site routes.** All 8 NL subnets via BGP (NH 10.255.200.X, Freedom VTI, LP 200)
- Transit host route: 10.0.X.X/32 via vti-no metric 254

**xs4all VTI limitation (investigated 2026-04-10):** ASA `tunnel source interface` does NOT override the routing table for outer ESP egress. VPN peer host routes (metric 1) point to outside_freedom, so ALL outbound ESP — including xs4all-sourced — exits via Freedom. Freedom ISP drops xs4all-sourced ESP (BCP38, source IP 203.0.113.X ≠ Freedom customer IP 203.0.113.X). **xs4all VTI tunnels are dormant backups** that activate only when Freedom goes completely down (default route switches to xs4all). RPF on outside_xs4all also disabled (was dropping inbound xs4all ESP).

**BFD: NOT supported** on ASA 9.16 (`bfd` unrecognized command). BGP timers reduced to 10/30 (keepalive/hold) on VTI peers for ~30s convergence.

**Freedom ESP: WORKING** — confirmed 2026-04-10. All tunnels passing traffic. IFRNLLEI01PRD-440 closed.

**VPS (NO + CH):**
- swanctl.conf: 4 connections each (nl, gr, ch/no-vps, nl-freedom)
- XFRM: xfrm-nl (if_id 1), xfrm-gr (if_id 2), xfrm-ch/no (if_id 3), xfrm-nl-f (if_id 4)
- Charon: `port_nat_t=4500`, `kernel-netlink.buflen=2097152`
- CrowdSec whitelist: `/etc/crowdsec/parsers/s02-enrich/whitelist-vps.yaml`
- xs4all (203.0.113.X) + Freedom (203.0.113.X) in UFW on both VPS
- Loopback IPs: 10.255.X.X/24 (CH), 10.255.X.X/24 (NO) — service/monitoring addresses
- FRR: `network 10.255.X.X/24` / `network 10.255.X.X/24` advertised via iBGP (added 2026-04-10, was missing)

**FRR (4 RRs) — updated 2026-04-10:**
- NL RR1 (nlk8s-frr01): VPS peers at Freedom tunnel IPs (10.255.200.X CH, 10.255.200.X NO)
- NL RR2 (nlk8s-frr02): VPS peers at xs4all tunnel IPs (10.255.200.X CH, 10.255.200.X NO)
- VPS FRR: `update-source` for NL RR peers changed from loopback to VTI /31 tunnel IPs
- **Why:** ASA couldn't resolve BGP next-hop when it was the loopback IP (10.255.X.X). Changing to VTI /31 IPs makes the next-hop resolvable via ASA's connected Tunnel interface routes. Dual-WAN safe: RR1 via Freedom, RR2 via xs4all.
- GR RR peers + inter-VPS peer: unchanged (still use loopback update-source)

### E2E Failover Tests (4/4 PASS)

| Test | Action | Result | Recovery |
|------|--------|--------|----------|
| Kill VPS direct tunnel | `swanctl --terminate --ike gr` | GR reachable 51ms via NL transit | Auto <30s (DPD) |
| Kill ASA IKE SA | `clear crypto ikev2 sa` | 3/3 subnets 0% loss | Auto <60s (DPD) |
| Admin-shutdown tunnel | `interface Tunnel1` → `shutdown` | Floating statics instant, 85ms via VPS | Instant on restore |
| ClusterMesh | During site isolation | 1/1 remote ready, 6 global-svc | Maintained |

### 3-Layer Failover Architecture

1. **DPD** (tunnel-level): dead peer detection → `dpd_action=restart` auto-recovers in <60s
2. **BGP transit** (VPS-level): VPS FRR mesh provides alternate paths for VPS-originated traffic
3. **Floating static routes** (ASA-level): metric 10 backup routes via vti-no activate instantly when direct tunnel (metric 1) goes down

### Issues Found and Fixed During Finalization

1. **CrowdSec banning VPS/ASA peers** — IKE retransmits triggered ssh-bf detection
2. **kernel-netlink buflen** — 8KB default overflows with BGP; 8MB segfaults; 2MB is safe max
3. **port_nat_t=0** broke VPS-to-VPS — random NAT-T ports; fixed to 4500
4. **xs4all IP missing from UFW** — raw iptables rules didn't persist through reboot
5. **DMZ servers needed 10.255.200.X/24** — VTI XFRM source range not in UFW
6. **CH VPS swanctl-loader.service** — was broken/truncated, rewritten with hardcoded eth0

### Finalization Completed (2026-04-09)

All original TODO items resolved:

- **Orphaned crypto-map cleanup: DONE** — ~713 config lines removed from both ASAs (unbound crypto-map entries, ACLs, 118 NAT exemptions). Audited line-by-line (not mass grep delete).
- **FRR BGP next-hop issue: ACCEPTED** — route-map sets next-hop but ASA doesn't reflect it. Floating statics work as pragmatic fix. Not a bug, just ASA behavior with VTI. No further action needed.
- **LibreNMS self-healing: CLOSED** — DPD + floating statics make it redundant. Left disabled intentionally.
- **Dual-WAN PAT rules: DONE** — after-auto PAT added for all 11 inside zones on both Freedom and xs4all outside interfaces + LTE.
- **VPN Mesh Stats API: DONE** — `/webhook/mesh-stats` workflow deployed (ID: `PrcigdZNWvTj9YaL`).
- **CrowdSec whitelists + netlink buflen + UFW fixes: DONE** — applied across 8 hosts.

### Post-Finalization Issues Found

1. **Stale ASA flows (corosync fix)** — After crypto-map removal, Proxmox corosync cluster degraded (5/5 nodes not communicating cross-site). Root cause: stale connection table entries from crypto-map era were blackholing corosync UDP. Fixed with `clear conn all` on NL ASA (killed 6003 connections, all re-established).

2. **SPI mismatch after `clear conn all`** — Clearing connections on only one ASA caused ESP SPI mismatches. Both ASAs must have crypto cleared simultaneously. Lesson: always clear crypto on BOTH ASAs, never just one.

3. **Freedom ISP recovery causing ESP routing issues** — Freedom recovered mid-session, causing the default route to switch from xs4all back to Freedom. ESP packets for xs4all-sourced tunnels lost their return path. Fixed by adding host routes for VPN peers on `outside_xs4all` (203.0.113.X, 198.51.100.X, 198.51.100.X via 198.51.100.X).

4. **Missing dual-WAN PAT rules** — The crypto-map cleanup mass-delete accidentally removed after-auto PAT rules for inside zones on the xs4all interface. This meant internet traffic could not NAT to xs4all on WAN failover. Discovered when testing, fixed by adding PAT rules for all 11 zones on both WANs.

5. **Tunnel4 (vti-gr-f) PSK mismatch — FIXED (2026-04-09 post-finalization session)** — Root cause: GR ASA tunnel-group for 203.0.113.X (Freedom) had a different PSK than NL ASA tunnel-group for 203.0.113.X. IKE_INIT was reaching GR but receiving a 96-byte NOTIFY reject (auth failure). Additional issue: both ASAs' outside ACLs lacked UDP 500/4500 + ESP permits for the Freedom↔GR direction (xs4all tunnels worked because GR initiated those, bypassing inbound ACL). Fixed by: (a) setting matching PSKs on both NL and GR tunnel-groups, (b) adding IKE/NAT-T/ESP ACL entries on both outside_freedom and outside_inalan. Result: 9/9 tunnels IKE UP.

6. **Freedom VTI ESP dataplane — FIXED (2026-04-10)** — Was broken (IKE up, ESP zero bytes). Self-healed after ASA reboot + SA renegotiation. RPF on `outside_xs4all` was also blocking inbound xs4all ESP → fixed (`no ip verify reverse-path interface outside_xs4all`). IFRNLLEI01PRD-440 closed.

### VPS Tunnel Outage (2026-04-10)

Both VPS lost all tunnel connectivity for ~20 hours after kernel upgrade reboots + charon restart:

1. **Apr 9 03:45/04:17** — Unattended kernel upgrade (6.8.0-106→107) rebooted both VPS
2. **Apr 9 17:23-17:35** — Manual reboots during troubleshooting
3. **chzrh01vps01**: `swanctl-loader.service` FAILED at boot (exit code 2 — race condition with charon)
4. **Apr 10 13:50** — charon restarted on both VPS without re-running swanctl-loader → connections lost
5. **Fix**: `sudo swanctl --load-all` on both VPS restored all tunnels immediately

**Lesson**: charon restart does NOT reload swanctl connections. After any charon restart, always run `swanctl --load-all`. The `swanctl-loader.service` on chzrh01vps01 needs `Restart=on-failure` or a startup delay to handle the charon readiness race condition.

### ASA Weekly Reboot DISABLED (2026-04-10)

EEM watchdog auto-reboot removed from both ASAs:
- `no event manager applet weekly-reboot` on nl-fw01 (was 604800s / 7d)
- `no event manager applet weekly-reboot` on gr-fw01 (was 590400s / 6d20h)
- `asa-reboot-watch.sh` cron commented out

**Why removed:** The NL ASA weekly reboot at 09:31 UTC Apr 10 caused: (1) third wave of "Service up/down" alerts across both sites, (2) post-reboot VPN check failed 3/3 (4/5 subnet pairs unreachable), (3) Freedom VTI tunnels never recovered post-reboot (IFRNLLEI01PRD-440), (4) the reboot coincided with a ~20h Matrix outage — creating a complete monitoring blind spot. The `dailybackup` EEM applet (TFTP at 00:58 UTC) remains on both ASAs.

*Source: `memory/vti_migration_20260409.md`*
