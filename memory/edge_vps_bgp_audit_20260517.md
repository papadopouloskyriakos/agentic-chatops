---
name: edge-vps-bgp-audit-20260517
description: "2026-05-17 audit of AS64512 external BGP across CH/NO/TX VPS — RESOLVED same day. Infrastructure: MR infrastructure/nl/production!305 (merge commit e378876), pipeline #31849 ✅ 75s. Status-diagram: kyriakos:4e6f279 (cache-buster v=44), pipeline #31843 ✅ 179s. D1+D2 BGP-drift fixed live on all 4 FRR RRs; CLAUDE.md FRR versions corrected; IaC snapshots re-pulled; status-page diagram now wires all 3 VPS to correct upstreams."
metadata: 
  node_type: memory
  type: project
  originSessionId: 2c49090b-e103-4bd4-b7cb-94d58cc3fecc
---

# Edge VPS BGP audit — 2026-05-17

Live-verified `2a0c:9a40:8e20::/48` announce + iBGP RR mesh across chzrh01vps01, notrf01vps01, txhou01vps01 by direct `sudo vtysh` on each + on grk8s-frr01/02 and nlk8s-frr01/02 (operator + sudo via `REDACTED_PASSWORD`; vtysh requires sudo on these hosts, operator is not in `frrvty`).

## Green facts (don't re-audit unless something flaps)
- **External visibility**: 100% (322/322 RIPE RIS v6 full-table peers seeing /48). RIPEstat asn-neighbours returns 2 upstreams: AS34927 iFog power=243, AS56655 Terrahost power=31. Matches `as214304_upstream_count=2` textfile metric + 7+2 transit baseline from the 2026-05-16 status-diagram fix.
- **/48 advertised from all 3 VPS** (confirmed via `show bgp ipv6 unicast 2a0c:9a40:8e20::/48` — Advertised-to-peers list).
- **All 9 anycast /128s** (::1..::9) bound on every VPS loopback. Next free is `::a` per CLAUDE.md.
- **eBGP sessions all Established ≥9 d**: CH 3 peers (FogIXP RS1 + RS2 + iFog) 1w5d13h, NO 2 peers (Terrahost dual) 1w5d14h, TX 1 peer (iFog) 1w2d00h.
- **IPsec mesh fully up**: 7 SAs ESTABLISHED on every VPS including `nl-freedom` (confirms 2026-05-13 PPPoE recovery held).
- **Kernel DFZ counts** consistent: CH 250k, NO 480k (×2 because dual Terrahost), TX 243k.
- **FRR version is 10.6.1 on all 3 VPS** (CLAUDE.md still says CH=10.5.1, NO=10.5.0 — stale, fix when convenient).

## Deploy record

| Artefact | Value |
|---|---|
| IaC commit | `c2f0882` chore(edge/frr): fix iBGP RR drift to VPS peers + snapshot live state |
| Branch | `fix/bgp-upstream-alerts` (deleted on merge) |
| MR | [`infrastructure/nl/production!305`](https://gitlab.example.net/infrastructure/nl/production/-/merge_requests/305) |
| Merge commit | `e378876` Merge branch 'fix/bgp-upstream-alerts' into 'main' |
| CI pipeline | [`#31849`](https://gitlab.example.net/infrastructure/nl/production/-/pipelines/31849) ✅ success in 75s |
| CI jobs run | `deploy/sync_to_github` (auto, 75s). All other jobs are `manual` (openbao-jwt-auth tests + 5 drift-detection jobs) — not triggered. |
| Status-diagram commit | `kyriakos:4e6f279` fix(status-page): wire all 3 VPS to their actual upstreams (TX line + CH/NO swap) |
| Status-diagram branch | `main` (direct push, no MR — single-author web repo) |
| Status-diagram cache-buster | `v=43` → `v=44` in `layouts/shortcodes/mesh-health.html` |
| Status-diagram CI pipeline | [`#31843`](https://gitlab.example.net/websites/papadopoulos.tech/kyriakos/-/pipelines/31843) ✅ success in 179s (fetch-status 57s → build 14s → docker 17s → deploy 92s) |
| Status-diagram production verify | v=44 served at t≈140s after push; Playwright confirmed 3 upstream links non-withdrawn (CH→AS34927, TX→AS34927, NO→AS56655) on both initial render and post-`updateData()` tick |

## Drift items — RESOLVED same day (IaC commit `c2f0882` on `fix/bgp-upstream-alerts`)

### D1 — GR-FRR01 + GR-FRR02 missing `addpath-tx-all-paths` on TX peer — **FIXED**
Was: TX received 47 best-path prefixes from each GR FRR while CH/NO received 146 multipath. Fix applied live via `vtysh` + `write memory` on each RR. After fix: PfxSnt to .44 went 47 → 146 on both GR FRRs. VPS-side: TX `PfxRcd` from GR-FRR01/02 went 46 → 140.

### D2 — NL-FRR1/2 RR-client asymmetry — **FIXED**
Made symmetric with GR pattern: added `route-reflector-client` to CH (.15/.5) and NO (.13/.3) peers, plus `addpath-tx-all-paths` to all 3 VPS peers (CH/NO/TX) on both NL FRRs. After fix: all 3 VPS receive identical 130-prefix views from NL FRRs (was 45/45/46). The pre-fix state turned out to be the same onboarding-miss pattern as D1, not an intentional design — confirmed by behavioral symmetry post-fix and absence of any failure mode after the change.

### D3 — Recent iBGP session resets — **observed, no action**
Was informational. Sessions all came back up post-fix as expected; flap-storm pattern check deferred.

### D4 — BFD ghost sessions — **left as-is**
Cleanup-only. `clear bfd peers` on a single peer doesn't reach the stale entries; full bfdd restart would briefly disrupt active BFD. Not worth the risk for cosmetic gain. Each VPS still has 4 `Down/unknown` entries alongside 4 working ones. No functional impact; flagged for next FRR-version upgrade window.

### CLAUDE.md FRR-version drift — **FIXED**
edge/CLAUDE.md updated: chzrh01vps01 FRR 10.5.1 → 10.6.1, notrf01vps01 FRR 10.5.0 → 10.6.1. TX line was already correct at 10.6.1.

## Post-fix verification (2026-05-17 ~13:25 UTC)
- All 3 VPS now receive symmetric `PfxRcd`: 140 from each GR FRR, 130 from each NL FRR.
- All eBGP sessions to upstreams Established and unchanged.
- `/48` still advertised externally from all 3 VPS.
- External RIPE visibility unchanged at 100% (322/322 v6 full-table peers).
- IPsec mesh untouched (all 7 SAs ESTABLISHED on each VPS).
- iBGP sessions briefly re-negotiated (00:00:00–00:00:09 reset window per peer) due to addpath capability change, recovered immediately.
- IaC snapshots: edge/frr/<host>/frr.conf re-pulled live for all 4 RRs. Diff was 272 insertions / 72 deletions because the repo also missed the 2026-05-06 TX onboarding additions entirely — those are now captured too.

## Confidence
- **HIGH** on D1: ran `show running-config` AND `show ip bgp neighbor 10.255.200.X advertised-routes` on both GR FRRs — 47 vs 146 delta is exact and explained by single config line.
- **HIGH** on D3/D4: direct observation from `show bfd peers` and BGP summary uptime columns.
- **MEDIUM** on D2 (config delta confirmed, but intentionality is the unresolved part).

## Commands worth keeping
```bash
# Per-VPS deep BGP dump (operator + sudo via .env SCANNER_SUDO_PASS=REDACTED_PASSWORD):
ssh -i ~/.ssh/one_key operator@<vps> 'bash -s' << 'EOF'
echo 'REDACTED_PASSWORD' | sudo -S -v 2>/dev/null
sudo -n vtysh -c "show bgp ipv6 unicast summary"
sudo -n vtysh -c "show bgp ipv6 unicast 2a0c:9a40:8e20::/48"
sudo -n vtysh -c "show running-config" | sed -n '/^router bgp/,/^!$/p'
EOF

# Per-FRR-RR check of advertised-routes by overlay-mesh IP (not the /11 lo IP):
ssh -i ~/.ssh/one_key root@grk8s-frr01 \
  'vtysh -c "show ip bgp neighbor 10.255.200.X advertised-routes"'
```

## Diagnostic recipe — when a VPS reports fewer iBGP prefixes than its peers
1. Compare PfxSnt column on the RR side (`vtysh -c "show ip bgp summary"`) rather than PfxRcd on the client side.
2. Diff the RR's running-config for `addpath-tx-all-paths` and `route-reflector-client` between the suspect peer and a healthy sibling.
3. Reachability is the same as long as `route-reflector-client` is set; addpath only affects path diversity.
