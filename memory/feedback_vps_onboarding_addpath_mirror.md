---
name: feedback-vps-onboarding-addpath-mirror
description: "When adding a new VPS RR-client to an FRR route reflector, also mirror addpath-tx-all-paths from a sibling VPS peer — otherwise the new VPS silently becomes a best-path-only iBGP citizen."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 2c49090b-e103-4bd4-b7cb-94d58cc3fecc
---

When onboarding a new VPS as `route-reflector-client` on an FRR route reflector, ALWAYS check that the new peer has the same `addpath-tx-all-paths` setting as a sibling VPS peer in the same address-family. If the sibling has it and the new peer doesn't, the new VPS receives only best-path (1 path per destination) while siblings receive multipath (N paths). Reachability is unaffected but multipath diversity isn't.

**Why:** The 2026-05-06 txhou01vps01 onboarding added `route-reflector-client` + `next-hop-self force` on `neighbor 10.255.200.X` in both `grk8s-frr01` and `grk8s-frr02` but missed the `addpath-tx-all-paths` line that Zurich (`.9`) and Norway (`.7`) peers have. Discovered 2026-05-17 — TX was receiving 47 prefixes from each GR FRR vs CH/NO receiving 146. See [[edge-vps-bgp-audit-20260517]] §D1.

**How to apply:**
1. After adding the new peer, diff its config against a sibling: `vtysh -c "show running-config" | grep -A20 "neighbor <new-ip>"` vs `... "neighbor <sibling-ip>"`.
2. Specifically check the four lines that commonly drift: `route-reflector-client`, `next-hop-self force`, `next-hop-self`, `addpath-tx-all-paths`.
3. Mirror anything missing under `address-family ipv4 unicast` (and `ipv6 unicast` if used for iBGP overlay).
4. Apply with `clear ip bgp <new-ip> soft out` (no session reset needed for outbound policy change).
5. Update the onboarding checklist (referenced as `reference_vps_asa_onboarding_checklist.md`) to make this an explicit step rather than implicit.

**Where this rule kicks in:** Every VPS/DMZ host onboarding that joins iBGP AS65000. Not just GR FRRs — NL FRRs have a similar but distinct asymmetry (see [[edge-vps-bgp-audit-20260517]] §D2). Audit BOTH sides of the RR pair.
