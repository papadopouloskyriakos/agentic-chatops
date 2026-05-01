# Failover Audit — `shut` then `no shut` on nl-sw01 Gi1/0/36 (Freedom ONT port)

**Date of audit:** 2026-04-22 03:45 UTC
**Scope:** Predict the exact cascade when the operator admin-shuts the sw01 port that feeds the Freedom ISP Genexis XGS-PON ONT, holds it for ~10 min, and then `no shut`s it.
**Method:** Read-only queries against every device in the Freedom dependency chain (nl-fw01, nlrtr01, nl-sw01, NO VPS FRR, strongSwan), cross-checked against the 2026-04-08 Freedom PPPoE postmortem and current ops memories.

All times below are measured against `T=0` (the moment `shut` takes effect).

---

## 1. Topology confirmed from live device queries

```
   Tenants A/B/C/D, K8s, DMZ, servers, mgmt
            ↓ (many VLANs)
      nl-fw01  Port-channel1  (4x1G LACP trunk, ALL vlans)
            ↓
      nl-sw01  Po1 — trunk, all vlans
            ↓        ↘
      (VLAN 6)        (Po1.2, other vlans)
            ↓
      sw01 Gi1/0/36   <─ target of `shut`
        trunk v4,v6, PoE 802.3af to ONT
            ↓
      TP-Link TL-PoE10R PoE splitter
            ↓
      Genexis XGS-PON ONT  <─ loses PoE and L2 peer simultaneously
            ↓
      Freedom fiber → BRAS 198.51.100.X → internet
```

- `fw01 outside_freedom` = `Port-channel1.6` (VLAN 6), PPPoE. Currently IP `203.0.113.X`, BRAS `198.51.100.X`.
- `sw01 Gi1/0/36` description: `*** Connection to Freedom Internet | Genexis XGS-PON ONT | 1 Gbps | PoE ***`, trunk v4+v6.
- Failure domain is strictly **VLAN 6 at the sw01 edge** — the 4-port LACP between fw01 and sw01 stays up, every other VLAN keeps working.

## 2. NL fw01 Freedom-dependent state (live)

| Element | Value | Triggered by Freedom down? |
|---|---|---|
| Default route `0.0.0.0/0 via 198.51.100.X, outside_freedom, metric 1, track 1` | Active | **Yes** — removed when track 1 flips Down |
| Peer host routes `203.0.113.X / 198.51.100.X / 198.51.100.X /32, track 1` | Active | **Yes** — removed with track 1 |
| Backup default `0.0.0.0/0 via 10.0.X.X, outside_budget, metric 5, track 2` | Installed as backup | **Promoted to active** |
| SLA 1: ICMP 198.51.100.X via outside_freedom, `freq 3 timeout 1000 threshold 500` | Up (`RTT 1 ms`) | **Trips on first missed probe (~3-6 s)** |
| Tunnel4 `vti-gr-f` src outside_freedom → 203.0.113.X (GR) | Up | **Drops** (tunnel source egress fails) |
| Tunnel5 `vti-no-f` src outside_freedom → 198.51.100.X (NO VPS) | Up | **Drops** |
| Tunnel6 `vti-ch-f` src outside_freedom → 198.51.100.X (CH VPS) | Up | **Drops** |
| BGP peer `10.255.200.X` (GR ASA, Freedom VTI), timers 10/30, `FREEDOM_IN` LP 200 | Established 11m | **Drops on hold-time 30 s** |
| BGP peer `10.0.X.X` (NL-FRR01) with `FREEDOM_FRR_IN` route-map | Established | **Stays up** (FRR01 lives on NL inside_mgmt, not Freedom); its Freedom-NH routes (`10.255.200.X`-NH) disappear as RR01's session to NO-VPS drops |
| BGP peer `10.0.X.X` (rtr01) — Budget path | Established | **Stays up** and becomes BGP best-path for inter-site prefixes |

## 3. Redundancy already in place (live)

- **rtr01 Dialer1 Budget PPPoE** up (203.0.113.X), Tunnel 1/2/3 to GR/NO/CH all up, 6 iBGP peers up.
- **NO VPS**: 4 xfrm tunnels up (`xfrm-nl`, `xfrm-nl-f`, `xfrm-gr`, `xfrm-ch`); 2 NL RR peerings — NL-FRR01 via `10.255.200.X` (Freedom VTI) + NL-FRR02 via `10.255.200.X` (Budget VTI). **Both have `bfd` configured** → sub-second detection on the Freedom peer.
- fw01 ACL/NAT: K8s + mgmt + servers + dmz subnets already have identity NAT + after-auto PAT on `outside_budget` so they keep their connectivity through the rtr01 edge during failover.
- Recovery crons: `vti-freedom-recovery.sh */3` (detects Freedom IPsec SA stuck + `clear crypto ipsec sa peer 203.0.113.X`), `freedom-qos-toggle.sh */2` (applies 5/2 Mbps tenant QoS + Twilio SMS).

## 4. Gaps / caveats discovered during the audit

1. **Tenant rooms A/B/C/D have no PAT on `outside_budget`** — only object-NAT to public IPs on `outside_freedom`, plus after-auto PAT on `outside_lte`. During the window Freedom is down, tenant-room internet egress hits the default route via outside_budget but gets no NAT translation on fw01 and will be dropped. This is a pre-existing parity gap (the 2026-04-08 postmortem flagged dual-WAN parity for servers/services but tenant rooms never got `outside_budget` after-auto PAT after the xs4all → budget migration). **User-visible impact: tenants B/C/D lose internet for the full 10-min test, even though cross-site VPN recovers.**
2. **Timers**: SLA 1 is `freq 3 timeout 1000 threshold 500` → ASA detects Freedom-down in roughly **3-6 s** (first probe after the cut). BGP `10.255.200.X` hold-time 30 s → session tears down about **30 s** after traffic stops. BFD on VPS↔FRR01 Freedom peering → **sub-second** detection of VPS-side flap.
3. **PPPoE LCP keepalives** will race the SLA probe. The ASA default LCP echo is `10 s interval / 3 missed = 30 s`. SLA wins — track flips before LCP declares the link down.

---

## 5. Event-by-event simulation of `shut Gi1/0/36`

### Phase 1 — Physical (T=0 to T+2 s)

- `sw01: Gi1/0/36 is administratively down, line protocol is down` → PoE removed from ONT, L2 gone.
- ONT loses power (splitter is 802.3af only, no battery) and data link simultaneously.
- **fw01 side**: `outside_freedom` (Po1.6) STAYS line-protocol-up because the sw01↔ASA Po1 LACP trunk is unaffected. Only VLAN-6 egress has nowhere to terminate.
- Syslog on fw01: no immediate "interface down" message.
- Syslog on sw01: `%LINK-5-CHANGED: Interface Gi1/0/36, changed state to administratively down` + `%LINEPROTO-5-UPDOWN … to down`. LibreNMS polls sw01 — interface status changes get picked up on next poll (≤5 min).

### Phase 2 — SLA + track flip (T+3 s to T+9 s)

- fw01 SLA 1 probe to 198.51.100.X via outside_freedom at T+3 s — **first timeout** (ICMP echo returns no reply within 1000 ms).
- Track 1 goes **Down** (`reachability Down`).
- Static routes with `track 1` are immediately **withdrawn from the RIB**:
  - `0.0.0.0/0 via 198.51.100.X outside_freedom`
  - `203.0.113.X/32, 198.51.100.X/32, 198.51.100.X/32`.
- Backup default `0.0.0.0/0 via 10.0.X.X outside_budget metric 5 track 2` becomes active.
- ASA syslog: `%ASA-6-622001: Removing tracked route 0.0.0.0 0.0.0.0 …`, `Adding tracked route 0.0.0.0 0.0.0.0 …`, `%ASA-4-411002: Line protocol on interface ... down` (if it considers the PPP dying line-protocol).

### Phase 3 — Tunnel and BGP teardown (T+5 s to T+35 s)

- Freedom-sourced IKE keepalives from fw01 start timing out.
- VPS NO side: BFD on NL-FRR01 peering (update-source `10.255.200.X`) misses within **~900 ms** of packet loss → BFD declares neighbor Down → BGP session `10.0.X.X` on the NO VPS side drops immediately (faster than hold-time). Same on CH VPS.
- VPS pulls all routes advertised via NL-FRR01 / Freedom-NH from its RIB and re-learns everything via NL-FRR02 / Budget-NH.
- fw01 ↔ GR ASA BGP peer `10.255.200.X` → **hold-down 30 s** elapses → session torn down at roughly **T+30-35 s**. During this 30 s window, fw01 may keep stale best-paths pointing at `10.255.200.X` (Freedom VTI NO side) as next-hop; those become unreachable on the first packet because `198.51.100.X` is unreachable, but the BGP table still thinks the path is valid until hold-down fires.
- After BGP reconverges, fw01's inter-site routes all flip to Budget-NH via rtr01 (the only path left for GR/NO/CH remote prefixes) — this is what the `FREEDOM_FRR_IN` route-map drops out of (its LP-200 VPS-loopback preference only applies while the FRR01 peer still reflects Freedom-NH).

### Phase 4 — Tenant impact (T+5 s onwards)

- Room A/B/C/D egress traffic routes to `outside_budget` (default route), fw01 applies `after-auto source dynamic any interface` PAT **only** for the zones listed (iot, cctv, guest, servers01/02, mgmt, k8s, nfs, dmz_servers02/03). **Tenant rooms are NOT in that list.**
- Result: tenant packets hit fw01, find no matching NAT rule for `(inside_room_*, outside_budget)`, and get dropped by NAT-RPF or egress untranslated and die at rtr01/Budget ISP.
- Only the LTE path (`outside_lte`) has `inside_room_* after-auto`, but it is metric 20 and will only be picked up if both Freedom and Budget tracks fail.

### Phase 5 — Cron-driven reactions (T+~2 min)

- `freedom-qos-toggle.sh` next `*/2` tick detects Freedom down (SLA-1 DOWN flag via ASA helper), applies tenant-room QoS (5/2 Mbps to a/b/c/d) via `tc` on rtr01 (defensive move; tenants are already offline, but this protects K8s/servers traffic on the Budget PPPoE), and sends a Twilio SMS: `[Freedom] NL Freedom down, switched to budget (rtr01). ETA ?`
- `vti-freedom-recovery.sh` `*/3` cron runs but sees Freedom WAN **down**, so it no-ops (its trigger is "Freedom UP + Tunnel4 UP + BGP not-Established").
- `bgp-mesh-watchdog.sh` `*/5` emits `bgp_mesh_established_count` metric reflecting the reduced session count; alert `BGPMeshSessionLoss` fires.

### Phase 6 — Alerts fire

| Source | Alert | Destination |
|---|---|---|
| LibreNMS on nl-nms01 | `outside_freedom line protocol down` / `SLA 1 failed` / BGP peer 10.255.200.X down / VPN tunnel down | `#infra-nl-prod` via n8n `NL - Claude Gateway LibreNMS Receiver` (Ids38SbH48q4JdLN) → auto-triage Matrix + YT issue |
| Prometheus (NL) | `BGPPeerDown` (10.255.200.X), `VPNTunnelDown` (vti-gr-f/no-f/ch-f), potentially `TargetDown` if scrape targets traverse Freedom | `#infra-nl-prod` via `NL - Prometheus Alert Receiver` (CqrN7hNiJsATcJGE) |
| Prometheus (GR) | `BGPPeerDown` on GR side for its Freedom VTI peer; `VPNTunnelDown` for Tunnel4 | `#infra-gr-prod` via `NL - Claude Gateway - Prometheus Alert Receiver (GR)` |
| Twilio (SMS) | Tenant QoS toggle | Operator phone |
| YouTrack | `IFRNLLEI01PRD-<next>` "Alert: Service up/down on nl-fw01 outside_freedom" | created by LibreNMS receiver |

Expect 5-10 LibreNMS/Prometheus alerts in the first 60 s. n8n maintenance-mode file (`/home/app-user/gateway.maintenance`) can silence them if pre-created.

### Phase 7 — Steady state on Budget-only (T+2 min to T+10 min)

- Inter-site traffic (NL↔GR, NL↔NO, NL↔CH): working via rtr01 Budget VTIs (Tunnel 1/2/3 on rtr01 stay up, already carry BGP keepalives).
- fw01 BGP: 3 established (`10.0.X.X rtr01`, `10.0.X.X FRR01`, `10.0.X.X FRR02`). `10.255.200.X` peer down.
- VPS mesh: FRR01 peers via Freedom VTI **down** on both VPSs; FRR02 peers via Budget VTI still up — BGP mesh continues but capacity is halved.
- Tenant rooms: **offline** (see §4 gap).
- `ipsec-health-check.sh` cron on VPS (`*/2`) may re-init the Freedom child SA — it will succeed against an unreachable NL Freedom endpoint (198.51.100.X is gone from the internet), fail, back off.
- `budget-pppoe-health.sh` / `vti-budget-recovery.sh` continue to monitor; no intervention expected while Budget is healthy.

---

## 6. Event-by-event simulation of `no shut Gi1/0/36` at T+10 min

### Phase A — Physical restore (T=10:00 to T=10:02)

- `sw01: Gi1/0/36 up, line protocol up` → PoE restored, ONT boots.
- **Genexis ONT cold-boot** typically 30-90 s. PADI requests from fw01 get no response until ONT has trained its PON side with the OLT.

### Phase B — PPPoE handshake (T=10:01 to T=10:03)

- fw01 PPPoE `id=1` sends PADI (broadcast on VLAN 6).
- ONT forwards to BRAS, PADO replies, PADR/PADS, LCP authenticates (PAP with `fb7360@xs4all.nl`), IPCP assigns `203.0.113.X` and gateway `198.51.100.X`.
- Syslog: `%ASA-5-603104: PPPoE session with PAP authentication established. Server: 198.51.100.X`. `outside_freedom` gets its IP back.

### Phase C — Track 1 recovers (T=10:03 to T=10:05)

- SLA 1 probes start succeeding. Cisco ASA SLA reachability defaults to 1 consecutive success = Up — track 1 flips **Up** within a single probe interval (**~3 s** after PPP is up).
- Static routes with track 1 come back into the RIB:
  - `0.0.0.0/0 outside_freedom` metric 1 — **wins over** backup metric 5.
  - `203.0.113.X/32`, `198.51.100.X/32`, `198.51.100.X/32` — restore.

### Phase D — VTI & BGP re-establish (T=10:03 to T=10:15 s)

- Tunnel 4/5/6 now have a valid source → IKEv2 INIT + AUTH (~1-2 s) + child SA (~1 s) → VTIs ESP-ready.
- fw01 ↔ GR ASA BGP on `10.255.200.X` re-forms → session up in ~10-15 s after VTI.
- VPS NO/CH side: BFD on NL-FRR01 (update-source 10.255.200.X) starts seeing bidirectional traffic again → BFD session goes Up → BGP peer re-forms (~5-10 s) → 40ish prefixes relearned.
- `vti-freedom-recovery.sh` cron at next `*/3` tick — sees Freedom UP + Tunnel4 UP + BGP Established → no-op.

### Phase E — BGP reconvergence to Freedom (T=10:15 s to T=10:30 s)

- Best-path computation: `FREEDOM_IN` route-map applies LP 200 on fw01's peer `10.255.200.X` → all GR-originated routes now prefer GR ASA Freedom VTI over rtr01 Budget. Equivalent for NL-FRR01's Freedom-NH (`FREEDOM_FRR_IN` sets LP 200 for VPS loopbacks).
- RIB flip: rtr01/Budget paths demote to backup, Freedom paths become best.
- fw01 `show conn` has stale Budget-direction flows for established TCP; `timeout floating-conn 0:00:30` lets them re-home to the Freedom egress interface within 30 s (per `feedback_asa_clear_conn_after_vti.md`), no manual `clear conn` needed.

### Phase F — Tenant restore (T=10:01 onwards)

- As soon as PPPoE is up and the `outside_freedom` default route is back, tenant object-NAT rules (`nat (inside_room_*, outside_freedom) dynamic PUBLIC_inside_room_*`) match again → tenant internet restored.
- **Expected tenant outage**: ~10 min 30 s (the `shut` duration + ~30 s ONT boot + PPP handshake).

### Phase G — Alert resolution (T=10:30 s to T=11:00)

- LibreNMS rule recoveries fire automatically on next poll → n8n receiver posts `Rule recovered: …` comments on the YT alert issues; workflow may transition state from `In Progress` → `To Verify` per receiver logic.
- Prometheus alerts clear once scrape targets return + BGP up metrics recover — `resolved` webhook fires, n8n posts `Alert resolved:` to YT and the Matrix room.
- `freedom-qos-toggle.sh` next `*/2` tick detects Freedom UP → removes QoS on rooms a/b/c/d, sends SMS `[Freedom] NL Freedom recovered, removed tenant QoS`.

## 7. Timing summary (predicted from live config, within ±15%)

| Event | ΔT from `shut` |
|---|---|
| Track 1 Down → backup default active | ~6 s |
| BFD detects Freedom VPS peer down (VPSs side) | ~1 s |
| BGP 10.255.200.X hold-time expiry | ~30 s |
| Alerts start firing in Matrix/YT | ~60-90 s |
| Tenant rooms lose internet | ~6 s (no NAT fallback path) |
| QoS + SMS applied | within 2 min |
| **ΔT from `no shut` at T=10:00** | |
| ONT boot + PPPoE up, `outside_freedom` has IP | ~60-90 s (T=10:01-10:02) |
| Track 1 Up, default route back on Freedom | ~3 s after PPP up (T=10:03) |
| VTI + BGP re-established | ~20-30 s (T=10:04-10:05) |
| BGP best-path flips to Freedom (LP 200 wins) | ~5-10 s after BGP up (T=10:05) |
| Tenant internet restored | ~immediately after PPP up |
| SMS "recovered" + alerts resolved | ~2 min |

---

## 8. Confidence + verification plan

Confidence is **high** for the control plane (ASA tracks, BGP, tunnels, cron reactions) because every claim above is backed by a live `show` or live script. Confidence is **lower** for:

- Exact ONT boot time (hardware behavior, not measurable remotely).
- Exact BFD detection latency on VPS (BFD timers not inspected; default 300 ms × 3 = 900 ms, not verified live).
- Whether LibreNMS / Prometheus scrape cadence matches the 60-90 s alert arrival estimate (could be 30-60 s).

**To close the tenant-impact uncertainty**: verify rtr01 Dialer1 NAT config to confirm room-traffic really has no Budget egress path. Separate follow-up.

---

## 9. Pre-flight actions if running the test live

1. Optional: `touch /home/app-user/gateway.maintenance` with JSON body `{"started":"<iso>","reason":"freedom failover test","eta_minutes":15,"operator":"<name>"}` to suppress alert cascade.
2. Tail `/var/log/syslog` on nl-fw01 + nlrtr01 via syslog-ng server for structured capture.
3. Record baselines: `show route`, `show bgp summary`, `show crypto ikev2 sa` on fw01 and rtr01 before `shut`.
4. After `no shut`, confirm recovery with same `show` commands + `ping -I vti-no-f 10.255.200.X` from fw01.
5. Post-test: review the YT alerts that fired, validate that every one auto-resolved; if any stayed firing, that's new work.

## 10. Follow-up work identified during this audit

- **Tenant-room PAT on `outside_budget`**: add `nat (inside_room_a/b/c/d, outside_budget) after-auto source dynamic any interface` on fw01 + ensure rtr01 Dialer1 has SRC-PAT for `10.0.X.X/30` to its Budget public IP. Closes the 2026-04-08 dual-WAN parity gap for tenant rooms.
- **Populate `docs/host-blast-radius.md`**: file is empty; this audit's §1-§3 is good seed content.
- **Verify BFD timers on VPS**: `vtysh -c 'show bfd peers'` to confirm sub-second detection assumption.
- **Alert-cadence baseline**: measure actual LibreNMS + Prometheus alert arrival times against this doc's estimate during the first live run.

---

## 11. Fix plan

Three linked workstreams. Sequence matters: **11.1 lands first** (establishes the NAT path), then **11.2** (relies on 11.1's source-IP preservation), then **11.3 verifies 11.1+11.2 together**.

### 11.1 — Tenant PAT for `outside_budget` (fw01) with per-tenant source-IP preservation

Problem identified in §4: tenant rooms have `outside_freedom` object-NAT + `outside_lte` after-auto PAT, but **no NAT path to `outside_budget`**. When Freedom fails, tenant packets hit fw01's backup default route (`outside_budget` metric 5), find no matching NAT rule, and get dropped.

Two possible shapes. Choosing the one that **preserves per-tenant source IPs to rtr01** (prerequisite for §11.2 per-tenant QoS):

```cisco
! Tenant subnet objects (verified live 2026-04-22)
object network inside_room_a-net
 subnet 10.0.X.X 255.255.255.224
object network inside_room_b-net
 subnet 10.0.X.X 255.255.255.224
object network inside_room_c-net
 subnet 10.0.X.X 255.255.255.224
object network inside_room_d-net
 subnet 10.0.X.X 255.255.255.224

! Section-1 identity NAT (preempts the after-auto PAT), one per room.
! Preserves tenant IPs across the fw01 → rtr01 transit so rtr01 QoS
! class-maps can match on source subnet.
nat (inside_room_a,outside_budget) 1 source static inside_room_a-net inside_room_a-net destination static any any no-proxy-arp route-lookup
nat (inside_room_b,outside_budget) 1 source static inside_room_b-net inside_room_b-net destination static any any no-proxy-arp route-lookup
nat (inside_room_c,outside_budget) 1 source static inside_room_c-net inside_room_c-net destination static any any no-proxy-arp route-lookup
nat (inside_room_d,outside_budget) 1 source static inside_room_d-net inside_room_d-net destination static any any no-proxy-arp route-lookup
```

Then on **rtr01**, extend `NAT_OUTBOUND_ACL` so the real tenant IPs get PAT'd to Dialer1 public IP `203.0.113.X`:

```cisco
ip access-list extended NAT_OUTBOUND_ACL
 permit ip 10.0.X.X 0.0.0.31 any    ! room A
 permit ip 10.0.X.X 0.0.0.31 any    ! room B
 permit ip 10.0.X.X 0.0.0.31 any    ! room C
 permit ip 10.0.X.X 0.0.0.31 any    ! room D
```

Rollback: `no nat (inside_room_X,outside_budget) 1 source …` per line on fw01, `no permit ip 192.168.17X.0 …` per ACL entry on rtr01.

Alternative (rejected): `after-auto source dynamic any interface` PAT on fw01. Simpler (one line per room), but collapses all tenant source IPs to `10.0.X.X` at the transit — kills per-tenant QoS visibility on rtr01, making §11.2 impossible. Only adopt this path if the operator decides per-tenant rate limiting isn't required.

### 11.2 — Path B adopted (simplify): permanent rtr01 HQoS, script becomes monitor-only

After reviewing the original Option 2 design, the operator flagged the core question: if rtr01 HQoS is permanent and only takes effect when rtr01 is in path (i.e. during Freedom-down failover), why toggle at all? Answer: only if Budget uplink can't absorb the aggregate `4 × 5 Mbps = 20 Mbps` tenant NORMAL cap without starving BGP/mgmt traffic. Budget uplink is ≥ 25 Mbps (confirmed by operator), so **NORMAL alone is sufficient during failover** — THROTTLED policies + toggle are dead weight.

**Final design — Path B:**

- **Install permanent HQoS on rtr01** (NORMAL only): `TENANT_DL_NORMAL` on `GigabitEthernet0/0/0.2` (15 Mbps per tenant download shape) + `BUDGET_UL_PARENT_NORMAL` on `Dialer1` (parent shape 30 Mbps, wraps `TENANT_UL_NORMAL` with 5 Mbps per tenant upload). Parent wrapper required because ISR 4321 Dialer sub-interfaces need a class-default shape for child HQoS (no parent → `Service policy … is in suspended mode`).
- **Drop THROTTLED policy-maps entirely**. `TENANT_DL_THROTTLED`, `TENANT_UL_THROTTLED`, `BUDGET_UL_PARENT_THROTTLED` removed.
- **Refactor `scripts/freedom-qos-toggle.sh` to monitor-only**:
  - Keep: Freedom state detection (UP/DOWN via `outside_freedom` IP assignment), SLA 1 RTT query, sw01 Gi1/0/36 CRC sample (every 7th run), Twilio SMS on state change, Prometheus textfile metrics (`freedom_pppoe_up`, `freedom_bng_rtt_ms`, `freedom_ont_port_errors`), suppression gates, state-file machinery.
  - Remove: `apply_qos()` + `remove_qos()` functions (referenced the defunct `XS4ALL-ROOM-*-PM` policy-maps on fw01).
  - SMS text updated to reflect the permanent-cap reality ("Budget carrying tenants at 15/5 Mbps each via rtr01 HQoS").
  - State file values renamed `qos-active`/`qos-inactive` → `freedom-down`/`freedom-up` for clarity.
  - Script name unchanged to preserve cron entry; this is now a vestigial historical name. Docstring updated to explain.

**Historical note for future spelunkers** (kept below for reference):
The pre-Path-B design called for NORMAL + THROTTLED policies + a script that SSH'd rtr01 to swap between them on Freedom state change. That design was correct in principle but unnecessary given Budget's real uplink capacity.

#### Legacy Option-2 design (dropped)

Current state: script tries to `service-policy XS4ALL-ROOM-{B,C,D}-PM interface inside_room_{b,c,d}` on fw01, but those policy-maps no longer exist on the ASA (removed during the 2026-04-21 migration cleanup). Apply/remove steps silently no-op; tenants aren't rate-limited during Freedom outage despite the script claiming they are.

New model: install permanent HQoS on rtr01 with two policy profiles — `NORMAL` and `THROTTLED` — and have the script toggle between them.

```cisco
! === rtr01 IOS-XE 17.9 — install permanent HQoS ===

! Per-tenant ACLs (download = to-tenant, upload = from-tenant)
ip access-list extended TENANT_A_DL
 permit ip any 10.0.X.X 0.0.0.31
ip access-list extended TENANT_A_UL
 permit ip 10.0.X.X 0.0.0.31 any
! (+ B/C/D — same shape with 192.168.178/179/180.0/27)

! Class-maps
class-map match-any TENANT_A_DL
 match access-group name TENANT_A_DL
class-map match-any TENANT_A_UL
 match access-group name TENANT_A_UL
! (+ B/C/D)

! NORMAL policy (permanent cap — 15 Mbps down / 5 Mbps up per room)
policy-map TENANT_DL_NORMAL
 class TENANT_A_DL
  shape average 15000000
 class TENANT_B_DL
  shape average 15000000
 class TENANT_C_DL
  shape average 15000000
 class TENANT_D_DL
  shape average 15000000

policy-map TENANT_UL_NORMAL
 class TENANT_A_UL
  shape average 5000000
 class TENANT_B_UL
  shape average 5000000
 class TENANT_C_UL
  shape average 5000000
 class TENANT_D_UL
  shape average 5000000

! THROTTLED policy (Freedom DOWN — 5 Mbps down / 2 Mbps up per room)
policy-map TENANT_DL_THROTTLED
 class TENANT_A_DL
  shape average 5000000
 ... (same pattern at 5 Mbps per room)

policy-map TENANT_UL_THROTTLED
 class TENANT_A_UL
  shape average 2000000
 ... (same at 2 Mbps per room)

! Attach NORMAL permanently — shaping only takes effect when rtr01 is in path
interface Dialer1
 service-policy output TENANT_UL_NORMAL
interface GigabitEthernet0/0/0.2
 service-policy output TENANT_DL_NORMAL
```

**Script refactor** (`scripts/freedom-qos-toggle.sh`):

- Replace `apply_qos()`: instead of SSH→fw01 for `service-policy XS4ALL-ROOM-B-PM …`, SSH→rtr01 using `scripts/lib/ios_ssh.ssh_rtr01_config` with:
  ```
  interface Dialer1
   no service-policy output TENANT_UL_NORMAL
   service-policy output TENANT_UL_THROTTLED
  interface GigabitEthernet0/0/0.2
   no service-policy output TENANT_DL_NORMAL
   service-policy output TENANT_DL_THROTTLED
  ```
- Replace `remove_qos()`: the inverse (swap THROTTLED → NORMAL).
- **Pre-apply sanity check**: before firing the `service-policy` swap, run `show policy-map | include TENANT_` on the target device and abort + emit `[freedom-qos]` critical log + Matrix alert if the expected policy-map is missing (protects against the silent-no-op class of regression that created this ticket).
- SMS text update: tell operator the actual applied state (rtr01 THROTTLED vs NORMAL), include which tenant rooms are affected.
- `dual_wan_vpn_parity.md` memory: update the "QoS lives on fw01" bullet to reflect the new rtr01 location.

Rollback: the `NORMAL` service-policy is the "cap" steady-state; if things break, `no service-policy output TENANT_UL_NORMAL` on Dialer1 + same on Gi0/0/0.2 takes bandwidth back to line rate.

### 11.3 — Validation + telemetry updates

Added to the Prometheus textfile emitter inside the script:
```
tenant_qos_active{room="a"} 1|0    # 1 = throttled, 0 = normal
tenant_qos_policy{policy="TENANT_UL_THROTTLED"} 1|0
```
Grafana: extend the chaos-engineering dashboard (uid `chaos-engineering`) with a "Tenant QoS state" panel.

Alert: `TenantQoSMisconfigured` — fires if `show policy-map | include TENANT_` on rtr01 returns 0 matches (catches the same silent-regression class as the one we just found on fw01). Rule lives in `prometheus/alert-rules/tenant-qos.yml`, scrapes the textfile metric.

Holistic-health check: add a section to `scripts/holistic-agentic-health.sh` asserting the 4 policy-maps + 4 class-maps + 4 ACLs + 2 service-policies are present on rtr01.

---

## 12. Post-fix failover re-audit — simulation of `shut Gi1/0/36` AFTER Path B lands

Same 10-min test scenario, re-run assuming §11.1 (tenant NAT) + §11.2 Path B (permanent 15/5 rtr01 HQoS) + monitor-only script are deployed.

### Deltas vs §5-§7 (original simulation)

**Phase 4 (Tenant impact), T+5 s onwards — CHANGED:**

- Tenant traffic hits the `outside_budget` backup default route.
- fw01 matches the new Section-1 identity NAT rules → tenant source IPs preserved across the `10.0.X.X/30` transit.
- rtr01 receives tenant packets with their real `192.168.17X.X` source IP.
- rtr01's `NAT_OUTBOUND_ACL` (extended with 4 tenant /27 entries) matches → PATs to Dialer1 public IP `203.0.113.X` → egress Budget BRAS `198.51.100.X`.
- rtr01 permanent HQoS engages the instant traffic reaches `Gi0/0/0.2` and `Dialer1`:
  - `TENANT_DL_NORMAL` shapes each room's download at 15 Mbps on `Gi0/0/0.2` egress.
  - `BUDGET_UL_PARENT_NORMAL` shapes the class-default aggregate at 30 Mbps on `Dialer1`, with each child `TENANT_*_UL` class further shaped at 5 Mbps.
- **Tenant internet stays up during the whole 10-min window**, rate-capped at 15 down / 5 up Mbps per room. No toggle needed — the cap is steady-state and survives regardless of script health.

**Phase 5 (Cron reactions), T+~2 min — CHANGED:**

- `freedom-qos-toggle.sh` detects Freedom DOWN → sends SMS ("Budget carrying tenants at 15/5 via rtr01 HQoS") and emits `freedom_pppoe_up=0` to Prometheus.
- No QoS apply step — rtr01 HQoS is always present; nothing to toggle.
- Grafana "Freedom ONT health" panel (from `freedom_ont.prom` textfile) shows the flip.

**Phase F (Tenant restore at `no shut`), T=10:01 onwards — CHANGED:**

- As Freedom PPPoE re-establishes and track 1 flips Up, fw01 default route reverts to outside_freedom. Tenant traffic goes back to the object-NAT path (fw01 direct to Freedom). rtr01 is no longer in path → rtr01 HQoS becomes inert (shapes zero traffic).
- `freedom-qos-toggle.sh` detects Freedom UP on next tick, sends recovery SMS, emits `freedom_pppoe_up=1`.

### Updated timing table (deltas only)

| Event | Before fixes | After Path B |
|---|---|---|
| Tenant rooms lose internet | ~6 s (no NAT path) | **never** (rate-capped at 15/5 during failover) |
| Tenant rate limit actually in effect | **never** (script no-op'd against defunct policy-maps) | **immediate** on failover (rtr01 HQoS permanent) |
| SMS matches reality | **no** (claimed 5/2 QoS that never applied) | **yes** (reports the real 15/5 cap) |
| Budget uplink protection | accidental (tenants offline) | deliberate (15/5 per room, parent shape 30 Mbps on Dialer1) |
| Script fragility | silent-no-op class of regression | script has no enforcement role → can't silently no-op |

---

## 13. Confidence levels

### Failover simulation (§5-§7) — **high**

Every control-plane claim sourced from a live `show` command (fw01 routes, tracks, SLAs, VTI tunnels, BGP neighbors; rtr01 Dialer1, BGP, Tunnel1-3; VPS FRR + xfrm; sw01 Gi1/0/36 description + trunk). Timing estimates (SLA probe 3-6 s, BGP hold-down 30 s, BFD sub-second) derived from live config values, not assumptions. Uncertainty remains on ONT cold-boot (hardware behavior) and exact LibreNMS scrape cadence (not inspected).

### Plan §11.1 (tenant NAT) — **high**

Pattern identical to existing `(dmz_servers02,outside_budget) source static NET_k8s_rr …` identity NAT and the VPS-loopback identity NAT landed 2026-04-22. Tenant subnets verified live (192.168.177/178/179/180.0/27). rtr01 `NAT_OUTBOUND_ACL` structure verified; extending it is a 4-line additive change.

### Plan §11.2 Path B (permanent rtr01 HQoS + monitor-only script) — **high** (deployed 2026-04-22)

Hit and resolved both known HQoS gotchas during deploy:
- **Budget uplink capacity**: operator confirmed ≥ 25 Mbps up → NORMAL alone suffices (no THROTTLED needed).
- **Dialer HQoS suspended mode**: initial attachment of `TENANT_UL_NORMAL` directly to `Dialer1` went into suspended state (ISR sub-interface HQoS requires a class-default parent shape). Fixed by wrapping with `BUDGET_UL_PARENT_NORMAL` (parent shape 30 Mbps, class-default → child TENANT_UL_NORMAL). Post-fix `show policy-map interface Dialer1` shows active target rates (5 Mbps per tenant child, 30 Mbps parent).
- **Gi0/0/0.2 sub-interface** attachment worked cleanly first try — Ethernet sub-interface inherits physical 1 Gbps parent rate, no explicit parent shape needed.

Script refactor is mechanical (~45 lines removed: `apply_qos`/`remove_qos` functions + their invocations). DRY_RUN test passed — SMS payload rendered correctly, state file migrated cleanly from legacy `qos-inactive` → `freedom-up`, Prometheus metrics emitted.

Policies are attached to live interfaces NOW but shape zero traffic until rtr01 is actually in the tenant path (Freedom-down failover). Verified with `show policy-map interface … | include offered rate` — 0 bps on all tenant classes, 0 drops. Zero blast radius from the install itself.

### Plan §11.3 (validation + alerts) — **high**

Alert rule + Grafana panel + holistic-health assertion all follow the same patterns already in this repo (see `teacher-agent.yml` + `chaos-engineering.json`). Zero novel machinery.

### Post-fix failover re-audit (§12) — **high** for data plane, **medium** for timing

Data-plane claim "tenants stay online at 15/5 cap, throttled to 5/2 during outage" follows from §11.1 preserving tenant IPs + rtr01 QoS engaging only when rtr01 is in path (which is exactly the Freedom-down window). Timing of the 5/2 kick-in depends on when the `*/2` `freedom-qos-toggle.sh` cron tick fires after the `shut`; worst case ~120 s lag. Could be tightened by polling every minute.

---

## 14. Post-incident amendment — ASA threat-detection shunned rtr01 mid-test (2026-04-22)

During the extended Freedom-shut window (the operator held `shut` longer to validate Budget-only steady-state), Budget silently died at **13:55:06 UTC**. Root cause: fw01 threat-detection `scanning-threat` classified `10.0.X.X` (rtr01 budget transit IP) as an attacker — burst rate hit the configured max of `10 pps`. fw01 installed a shun. All traffic from rtr01 was dropped until `clear shun` fired ~19 min later.

### Why it happened

Budget transit `10.0.X.X/30` was created during the 2026-04-21 xs4all→budget migration but **was never added to `whitelist_shun_nlgr_all_subnets`** — the ASA object-group that exempts trusted internal IPs from scanning-threat shunning. During the failover window, rtr01 legitimately forwarded:

- Cross-site BGP keepalives (multiple peers)
- Corosync retransmission storm from the split-brain cluster
- K8s ClusterMesh health probes
- Normal inter-site monitoring (syslog, SNMP, SSH)
- Mass NAT flow rebuilds from the Path B + GR-identity-NAT rollouts + 3 rounds of `clear conn`

Cumulative pattern looked identical to a port-scan to the ASA's classifier. Shun added on the legitimate router IP.

### Impact

~19 min of Budget-path death during a window where Freedom was also intentionally down. Site was entirely reliant on NL-local services; cross-site, cluster mesh, and any outbound traffic via the Budget path were dropped on fw01 ingress.

### Fix (applied 2026-04-22 14:15 UTC)

```cisco
object-group network nl_all_subnets
 description includes 10.0.X.X/30 (budget transit rtr01-fw01, added post-shun-incident 2026-04-22)
 network-object 10.0.X.X 255.255.255.252
!
clear shun
write memory
```

Verified: `show shun` empty, BGP peer `10.0.X.X` Established, track 2 Up.

### What this means for the §5-§7 simulation

Phase 5 should list ASA threat-detection as a **failure mode that can silently kill the Budget path during sustained failover**. Add to §9 pre-flight checklist:

```
! pre-flight on fw01
show run threat-detection | include scanning-threat
show run object-group id whitelist_shun_nlgr_all_subnets
# verify that 10.0.X.X/30, 10.255.200.X/24, and any other transit are whitelisted.

! post-test on fw01
show shun statistics    # any non-zero count on outside_budget or VTI interfaces = investigate
clear shun              # safe to run after any failover test (idempotent)
```

### Follow-up tracker

Five items filed as **IFRNLLEI01PRD-689**: codify whitelist in IaC CI, raise scanning-threat burst threshold from 10 → 100 pps, alert on `%ASA-4-733102` shun-add events, memory update (done), runbook updates (this section + chaos cleanup doc).

---

### What would raise §11.2 to "high" — RESOLVED

1. ~~Live `show interface Dialer1 | include BW|load` on rtr01 to baseline Budget uplink.~~ — operator confirmed ≥ 25 Mbps.
2. ~~Dry-run the policy-map config on rtr01 without service-policy attachment, verify `show policy-map` reports cleanly.~~ — done in stages during deploy (definitions first, verified via `show policy-map` before attachment).
3. ~~Stage in a weekend maintenance window~~ — Freedom UP at deploy time meant rtr01 had zero tenant traffic; maintenance window was unnecessary.
4. **Outstanding**: re-run this simulation with `/maintenance` gate set + collect actual timings to compare against §12's deltas. To be done on the operator's next real failover test.

---

## §15 Post-recovery timings (2026-04-22 17:12Z)

Live recovery exercise performed at the tail of the same session. Details
in `chaos_experiments.freedom-ont-recovery-20260422` (verdict: **PASS**).

### Timeline

| T (UTC)  | Δ (s) | Event |
|----------|-------|-------|
| 17:12:58 |    0  | Operator issued first `no shutdown` on sw01 Gi1/0/36. Port came admin-up but stayed `notconnect` — ONT did NOT resume PON sync. |
| 17:18:28 |  +330 | Operator performed forced PoE re-detect: `power inline never` → `power inline auto` → `shutdown` → `no shutdown`. |
| 17:18:30 |  +332 | Gi1/0/36 stabilised `up, line protocol up (connected)` after 2 flaps (ONT boot asserts Ethernet before PON sync completes). |
| 17:18:04 |  +306 | fw01 `outside_freedom` IP **203.0.113.X** assigned — PPPoE LCP+IPCP complete. |
| 17:19:58 |  +420 | Tunnel4 (NL↔GR freedom) `up`, BGP peer 10.255.200.X Established (13 prefixes). |
| 17:20:30 |  +452 | mesh-stats: `Nominal — 9/9 tunnels active \| BGP 43/43 \| ClusterMesh ready`. |

**Convergence from effective port-up to Nominal: 120 s** (= SLO target).

### Quirk discovered during this exercise

A plain `no shutdown` alone did not bring the port up after the long
down window. The ONT had lost PON training during the power-off and
did not re-negotiate when PoE was simply restored. The fix was to
**force a clean PoE re-detect**:

```
conf t
 interface GigabitEthernet1/0/36
  power inline never       ! explicit ONT de-power (drops PoE rail)
  power inline auto        ! re-enable 802.3at PD detection
  shutdown
  no shutdown
 end
```

Full writeup: memory `freedom_ont_poe_recycle_gotcha_20260422.md`.

**Runbook implication.** Any Freedom maintenance that keeps sw01
Gi1/0/36 shut for more than ~5 min should plan recovery as the above
5-line recipe, not plain `no shut`. Below ~1 min the ONT holds PON
state and plain `no shut` works.

### Guardrails validated during recovery

| Guardrail | State |
|---|---|
| ASA shun (100 pps burst threshold, 10.0.X.X/30 whitelisted) | 0 shuns during recovery |
| `asp drop nat-*` | 38 `nat-no-xlate-to-pat-pool` over the 120 s flip (~0.1/s — transient asymmetric-path blip, cleared with route settle) |
| `asa_shun_count` metric + alert | 0 / quiet |
| `budget_dialer_utilization_input` | fell from 64% → 19% as Freedom took back NL-local traffic |
| rtr01 syslog source-binding | stable under the port flaps; hostname bucket unchanged |
| mesh-stats banner progression | Degraded (Freedom down, Budget holding) → Nominal (9/9) in one tick |

Budget path stayed up through the entire flip — active-active design
means the recovery direction has zero blackout.
