# Resume Prompt: Inject Site Subnets into iBGP for Freedom-Primary VPN Failover

**STATUS: DONE (2026-04-10).** All static inter-site routes removed from both ASAs. BGP handles all inter-site routing via direct ASA-to-ASA peering over VTI interfaces. Three-tier LP failover: Freedom VTI (200) > xs4all VTI (150) > FRR transit (100). Freedom ESP confirmed working. Failover test passed.

## Objective

Replace static VTI routes on both ASAs with BGP-learned routes, so the iBGP mesh (AS 65000) with FRR route reflectors handles VPN path selection and failover automatically. Freedom VTI tunnels are primary (LP 200), xs4all VTI tunnels are backup (LP 150).

## Why

Currently all inter-site routing uses static routes with metrics:
- NL ASA: 9 GR subnets via `vti-gr-f` (Freedom, metric 1) + backup via `vti-gr` (xs4all, metric 10)
- GR ASA: 8 NL subnets via `vti-nl-f` (Freedom, metric 1) + backup via `vti-nl` (xs4all, metric 10)
- VPS: 3 NL subnets hardcoded to `xfrm-nl-f` in `swanctl-loader.service`

Static routes don't react to tunnel health — if the Freedom VTI IKE stays up but ESP fails, traffic blackholes. BGP with DPD-driven session teardown provides automatic convergence.

## Current Architecture

### BGP Topology (AS 65000 iBGP, AS 65001 Cilium eBGP)

```
                    NL-FRR01 (10.0.X.X) ──── NL-FRR02 (10.0.X.X)
                     │ RR-client: all           │ RR-client: all
                     │                          │
    NL ASA (10.0.X.X) ─── iBGP ─── VPS-NO (10.255.X.X) ─── VPS-CH (10.255.X.X)
                                                 │                   │
                    GR-FRR01 (10.0.X.X) ──── GR-FRR02 (10.0.X.X)
                     │ (no ASA peer currently)
    GR ASA (10.0.58.X) ─── peers GR-FRR01/02 + Cilium workers
```

### What BGP Currently Carries
- NL ASA `network` statements: 8 NL subnets (10.0.X.X, 87.0/29, 88.0/27, 177.0/27, 181.0, 183.0/28, 191.0/27, 192.0/27)
- GR ASA `network` statements: 9 GR subnets (10.0.X.X, 6.0/27, 7.0/28, 9.0/27, 10.0/27, 15.0/27, 58.0, 187.0/29, 188.0/27)
- Cilium workers (AS 65001): /32 pod CIDRs
- `BLOCK_SITE_TO_CILIUM` route-map prevents site subnets leaking to Cilium eBGP peers

### What BGP Does NOT Currently Do
- ASAs advertise their subnets but **no other iBGP peer re-advertises them** — the FRR route reflectors reflect them but the ASAs don't install them because they already have static routes (admin distance 1 beats iBGP distance 200)
- No LP differentiation between Freedom and xs4all paths
- VPS nodes don't peer with ASAs — they only peer with FRR route reflectors
- GR ASA does NOT peer with NL FRR RRs (no cross-site BGP peering on ASA)

### Existing Route-Maps
- NL-FRR01 has `LOCAL_PREF_HIGH` (LP 200) applied to NL ASA inbound — so NL ASA's routes get LP 200 on the RR
- NL-FRR01 has `VPS_TRANSIT_FOR_ASA` outbound to NL ASA — sets GR next-hops to VPS IP (10.255.200.X) for VPS transit
- `BLOCK_SITE_TO_CILIUM` on both ASAs — denies site subnets to Cilium workers

### Current VTI Tunnel Inventory (18 total, 12 active + 6 warm standby)

**NL ASA (6 tunnels):**
| Tunnel | Nameif | Source | Peer | VTI IP | Role |
|--------|--------|--------|------|--------|------|
| Tunnel1 | vti-gr | outside_xs4all | 203.0.113.X | 10.255.200.X/31 | xs4all backup |
| Tunnel2 | vti-no | outside_xs4all | 198.51.100.X | 10.255.200.X/31 | xs4all backup |
| Tunnel3 | vti-ch | outside_xs4all | 198.51.100.X | 10.255.200.X/31 | xs4all backup |
| Tunnel4 | vti-gr-f | outside_freedom | 203.0.113.X | 10.255.200.X/31 | **Freedom primary** |
| Tunnel5 | vti-no-f | outside_freedom | 198.51.100.X | 10.255.200.X/31 | **Freedom primary** |
| Tunnel6 | vti-ch-f | outside_freedom | 198.51.100.X | 10.255.200.X/31 | **Freedom primary** |

**GR ASA (4 tunnels):**
| Tunnel | Nameif | Peer | VTI IP | Role |
|--------|--------|------|--------|------|
| Tunnel1 | vti-nl | 203.0.113.X (NL xs4all) | 10.255.200.X/31 | xs4all backup |
| Tunnel2 | vti-no | 198.51.100.X | 10.255.200.X/31 | active |
| Tunnel3 | vti-ch | 198.51.100.X | 10.255.200.X/31 | active |
| Tunnel4 | vti-nl-f | 203.0.113.X (NL Freedom) | 10.255.200.X/31 | **Freedom primary** |

**VPS (4 XFRM each):** xfrm-nl (if_id 1, xs4all backup), xfrm-gr (if_id 2), xfrm-ch/no (if_id 3), xfrm-nl-f (if_id 4, Freedom primary)

### Current Static Routes to Remove (after BGP takes over)

**NL ASA (18 static routes):**
```
route vti-gr-f 10.0.X.X 255.255.255.0 10.255.200.X 1
route vti-gr 10.0.X.X 255.255.255.0 10.255.200.X 10
... (9 GR subnets × 2 routes each = 18)
```

**GR ASA (16 static routes):**
```
route vti-nl-f 10.0.X.X 255.255.255.0 10.255.200.X 1
route vti-nl 10.0.X.X 255.255.255.0 10.255.200.X 10
... (8 NL subnets × 2 routes each = 16)
```

**VPS swanctl-loader.service routes:**
```
ip route add 10.0.X.X/27 dev xfrm-nl-f  (NL subnets, 3 routes per VPS)
```

### VPN Peer Host Routes (keep — these route the outer ESP)
```
! NL ASA — route outer ESP to correct ISP
route outside_freedom 203.0.113.X 255.255.255.255 198.51.100.X 1 track 1
route outside_xs4all 203.0.113.X 255.255.255.255 198.51.100.X 10
route outside_freedom 198.51.100.X 255.255.255.255 198.51.100.X 1 track 1
route outside_xs4all 198.51.100.X 255.255.255.255 198.51.100.X 10
route outside_freedom 198.51.100.X 255.255.255.255 198.51.100.X 1 track 1
route outside_xs4all 198.51.100.X 255.255.255.255 198.51.100.X 10
```
These are for OUTER ESP packet routing, not inner traffic. They MUST remain static (BGP can't control which physical interface ESP exits on).

### Key Constraints

1. **RPF disabled on NL outside_freedom** — `no ip verify reverse-path interface outside_freedom` (was the root cause of IFRNLLEI01PRD-440, fixed 2026-04-10)
2. **VPS Freedom tunnels use NAT-T** — `encap = yes` in swanctl.conf on both VPS (Freedom ISP path requires UDP encapsulation for ESP)
3. **ASA admin distance**: connected=0, static=1, eBGP=20, iBGP=200 — static routes MUST be removed for BGP routes to install
4. **Both ASAs already advertise site subnets** via `network` statements — the routes are in the BGP table, just not being preferred anywhere
5. **No BGP peering between ASAs** — they peer only with local FRR RRs. Cross-site routes arrive via RR reflection.
6. **`BLOCK_SITE_TO_CILIUM`** route-map must remain — prevents site subnets leaking to K8s eBGP

### SSH Access

- NL ASA: `ssh -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa operator@10.0.181.X` (password: `REDACTED_PASSWORD`, same for enable)
- GR ASA: via grclaude01 stepstone: `ssh -i ~/.ssh/one_key -p 2222 app-user@203.0.113.X`, then netmiko to 10.0.X.X
- NL FRR01: `ssh nl-pve01` then `pct exec VMID_REDACTED -- vtysh`
- NL FRR02: `ssh nl-pve03` then `pct exec VMID_REDACTED -- vtysh`
- GR FRR01/02: via grclaude01 stepstone
- NO VPS: `ssh -i ~/.ssh/one_key operator@198.51.100.X` (sudo password: `REDACTED_PASSWORD`)
- CH VPS: `ssh -i ~/.ssh/one_key operator@198.51.100.X` (sudo password: `REDACTED_PASSWORD`)

## Implementation Plan

### Phase 1: Configure LP Differentiation on FRR Route Reflectors

The RRs need to set different LP for routes learned from Freedom VTI peers vs xs4all VTI peers. Since ASAs peer with the local RRs (not directly with remote ASAs), the RRs control the LP.

**On NL-FRR01 and NL-FRR02:**
- Routes from NL ASA (10.0.X.X) = NL site subnets → LP 200 (already done via `LOCAL_PREF_HIGH`)
- Routes from GR-FRR01/02 = GR site subnets reflected via RR → these arrive with whatever LP the GR RR set
- The NL ASA needs to receive GR subnets with LP 200 for Freedom path and LP 100 for xs4all path

**The challenge:** Both paths arrive at the NL RR as reflected routes from the GR side. The NL RR can't distinguish "this came via Freedom" vs "this came via xs4all" because both come from the same GR RR peer.

**Solution:** Add the ASAs as direct iBGP peers on the RRs (they already are). The ASAs should advertise their subnets with different next-hops for Freedom vs xs4all VTI interfaces. The RR then sets LP based on the next-hop:
- Next-hop via Freedom VTI IPs (10.255.200.X-15) → LP 200
- Next-hop via xs4all VTI IPs (10.255.200.X-5) → LP 100

But ASAs use `next-hop-self` when peering with RRs, so the next-hop is always the ASA's DMZ IP. We need a different approach.

**Better solution:** Peer the ASAs directly with BOTH Freedom and xs4all VTI tunnel IPs as BGP neighbors on the RRs. The ASA would have two BGP sessions to the same RR — one via Freedom VTI, one via xs4all VTI. Each session carries the same subnets but the RR applies different LP.

**Simplest solution:** Don't change BGP at all for path selection. Instead:
1. Keep static routes on ASAs for inter-site subnets (Freedom primary metric 1, xs4all backup metric 10)
2. Use BGP only for K8s pod CIDRs (current behavior)
3. Add BFD (Bidirectional Forwarding Detection) on the VTI interfaces to detect tunnel failures in <1 second
4. Use SLA tracking + floating statics for failover (current approach, already working)

### Recommended Approach: BFD + Floating Statics (Pragmatic)

Given the complexity of dual-next-hop BGP on ASA, the most reliable approach is:

1. **Add BFD on VTI interfaces** — ASA 9.16 supports BFD. Configure BFD between each VTI tunnel endpoint pair. BFD detects dataplane failures in ~1 second (vs DPD's 30-60 seconds).
2. **Track BFD state in static routes** — `route vti-gr-f 10.0.X.X 255.255.255.0 10.255.200.X 1 track <bfd-track-id>`. When BFD detects Freedom tunnel is dead, the tracked route is removed and xs4all backup activates.
3. **This replaces SLA tracking** for VPN failover with sub-second detection.

### Alternative Approach: Full BGP (Complex but Clean)

If full BGP is desired despite the complexity:

1. **Add VTI loopback BGP sessions** — each ASA peers with the RR via both Freedom VTI IP and xs4all VTI IP
2. **RR applies LP based on peer IP** — Freedom peer → LP 200, xs4all peer → LP 100
3. **Remove all static inter-site routes** from both ASAs
4. **Update VPS FRR** to advertise site subnets with appropriate LP
5. **Test failover** by shutting down Freedom VTI and verifying BGP reconverges to xs4all

This requires careful cutover planning:
- Step A: Add new BGP sessions (both ASAs + all RRs) — non-disruptive
- Step B: Verify BGP routes appear in RIB alongside statics — non-disruptive
- Step C: Remove static routes one subnet at a time — BGP takes over
- Step D: Test Freedom failure → verify xs4all BGP routes activate
- Step E: Save configs on all devices

### Devices to Modify

| Device | Changes |
|--------|---------|
| NL ASA (nl-fw01) | Add BGP sessions via VTI IPs, or add BFD, remove static inter-site routes |
| GR ASA (gr-fw01) | Same |
| NL-FRR01 (LXC VMID_REDACTED on nl-pve01) | Add LP route-maps for Freedom vs xs4all VTI peers |
| NL-FRR02 (LXC VMID_REDACTED on nl-pve03) | Same |
| GR-FRR01 (LXC on gr-pve01) | Same |
| GR-FRR02 (LXC on gr-pve01) | Same |
| NO VPS (198.51.100.X) | Update FRR + swanctl-loader routes |
| CH VPS (198.51.100.X) | Same |

### Rollback

If BGP failover doesn't work:
1. Re-add the static routes (saved in this document above)
2. `clear bgp * soft` to reset BGP without tearing sessions
3. Static routes (AD 1) will override BGP (AD 200) immediately

### Verification Checklist

- [ ] All 12 paths still operational (ping mesh test)
- [ ] Cluster 5/5 quorate
- [ ] Shut Freedom VTI on NL ASA (`interface Tunnel4/5/6 shutdown`) → verify xs4all routes install via BGP within seconds
- [ ] Restore Freedom VTI → verify Freedom routes re-install with higher LP
- [ ] Check `show route bgp` on both ASAs — site subnets appear
- [ ] Check `show bgp ipv4 unicast` — both Freedom and xs4all paths visible with correct LP
