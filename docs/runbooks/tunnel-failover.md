# Runbook: VPN Tunnel Failover

**Runbook ID:** RB-TUN-001
**Last Updated:** 2026-04-14
**Exercise Program Reference:** docs/exercise-program.md
**Automation:** scripts/chaos_baseline.py baseline-test

---

## 1. Overview

This runbook covers the procedures for VPN tunnel failover chaos exercises. Each scenario kills a specific IPsec/VTI tunnel and validates that BGP re-converges through backup paths within the 30-second SLO.

The Example Corp Network operates 9 VTI tunnels across 3 ISPs (Freedom, xs4all, Inalan). BGP local preference tiers ensure deterministic failover: Freedom LP 200, xs4all LP 150, FRR transit LP 100.

---

## 2. Trigger Conditions

This runbook is used when:
- Weekly baseline exercise (Wednesday 10:00 UTC)
- Monthly tunnel sweep (1st of month)
- Combined game day tunnel component
- Ad-hoc resilience validation after infrastructure changes
- Post-incident validation of tunnel recovery mechanisms

---

## 3. Scenarios

### 3.1 NL-GR Freedom Tunnel

**Tunnel:** NL (nlasa01) to GR (grasa01) via Freedom ISP
**VTI Interface:** vti-nl-gr-freedom
**BGP Impact:** Primary inter-site path (LP 200), failover to xs4all (LP 150) then FRR transit (LP 100)

#### Pre-checks

1. Verify backup tunnels are UP:
   - NL-GR xs4all tunnel: `show interface vti-nl-gr-xs4all` -- must show UP/UP
   - FRR transit path: verify BGP peer with VPS route reflectors
2. Verify SSH access to nlasa01:
   ```
   ssh operator@10.0.181.X
   show vpn-sessiondb l2l
   ```
3. Verify current BGP peer count >= 22:
   ```
   ssh -i ~/.ssh/one_key operator@198.51.100.X sudo vtysh -c "show bgp summary"
   ```
4. Verify baseline HTTP reachability to all endpoints

#### Injection

```
# On nlasa01:
interface vti-nl-gr-freedom
 shutdown
```

Automated: `chaos_baseline.py baseline-test --tunnel "NL ↔ GR" --wan freedom --duration 120`

#### Expected Behavior

1. **0-5s:** IKE SA timeout detected, BGP hold timer starts counting down
2. **5-15s:** BGP withdraws routes learned via Freedom VTI
3. **10-25s:** BGP selects xs4all path (LP 150) as best route
4. **15-30s:** Traffic converges to xs4all tunnel, HTTP endpoints recover
5. **30-60s:** Full convergence, all BGP peers re-established via backup paths

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 30s -->
Verify BGP peer count recovers to at least 20 established peers within 30 seconds of fault injection.

<!-- VALIDATE: http_ok >= 4 within 60s -->
Verify HTTP reachability to at least 4 of the monitored endpoints returns 200 within 60 seconds.

<!-- VALIDATE: vti_ping reachable within 45s -->
Verify ping across the backup VTI tunnel (xs4all) succeeds within 45 seconds.

#### Recovery

1. Restore the tunnel interface:
   ```
   interface vti-nl-gr-freedom
    no shutdown
   ```
2. Clear any ASA shun entries caused by threat detection:
   ```
   clear shun
   ```
3. If IKE SA does not re-establish within 60 seconds, reload swanctl on the VPS:
   ```
   ssh -i ~/.ssh/one_key operator@198.51.100.X sudo swanctl --load-all
   ```
4. Wait for BGP to converge back to Freedom as primary (LP 200)

#### Post-Recovery Validation

<!-- VALIDATE: tunnel_up == true within 120s -->
Verify the Freedom VTI tunnel returns to UP/UP state within 120 seconds of recovery.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Verify BGP peer count returns to full mesh (>= 22 peers) within 90 seconds of recovery.

---

### 3.2 NL-NO Freedom Tunnel

**Tunnel:** NL (nlasa01) to NO VPS (198.51.100.X) via Freedom ISP
**VTI Interface:** vti-nl-no-freedom
**BGP Impact:** Route reflector 1 path via Freedom, failover to xs4all peer

#### Pre-checks

1. Verify NL-NO xs4all tunnel is UP
2. Verify SSH access to nlasa01
3. Verify BGP peer count >= 22
4. Verify HTTP baseline

#### Injection

```
# On nlasa01:
interface vti-nl-no-freedom
 shutdown
```

Automated: `chaos_baseline.py baseline-test --tunnel "NL ↔ NO" --wan freedom --duration 120`

#### Expected Behavior

1. **0-5s:** IKE SA timeout, BGP hold timer begins
2. **5-20s:** BGP withdraws NL-NO Freedom routes
3. **10-30s:** Traffic shifts to NL-NO xs4all path (LP 150) or via GR transit (LP 100)
4. **15-30s:** Full convergence via backup path

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 30s -->
BGP peers recover to at least 20 within 30 seconds.

<!-- VALIDATE: http_ok >= 4 within 60s -->
HTTP endpoints reachable within 60 seconds.

<!-- VALIDATE: vti_ping reachable within 45s -->
Backup VTI tunnel responds to ping within 45 seconds.

#### Recovery

1. `no shutdown` on vti-nl-no-freedom
2. `clear shun` on nlasa01
3. Reload swanctl on VPS if IKE SA stalls
4. Verify Freedom path resumes as preferred (LP 200)

#### Post-Recovery Validation

<!-- VALIDATE: tunnel_up == true within 120s -->
Freedom tunnel returns to UP/UP within 120 seconds.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Full BGP mesh restored within 90 seconds.

---

### 3.3 NL-CH Freedom Tunnel

**Tunnel:** NL (nlasa01) to CH VPS (198.51.100.X) via Freedom ISP
**VTI Interface:** vti-nl-ch-freedom
**BGP Impact:** Route reflector 2 path via Freedom, failover to xs4all peer

#### Pre-checks

1. Verify NL-CH xs4all tunnel is UP
2. Verify SSH access to nlasa01
3. Verify BGP peer count >= 22
4. Verify HTTP baseline

#### Injection

```
# On nlasa01:
interface vti-nl-ch-freedom
 shutdown
```

Automated: `chaos_baseline.py baseline-test --tunnel "NL ↔ CH" --wan freedom --duration 120`

#### Expected Behavior

1. **0-5s:** IKE SA timeout
2. **5-20s:** BGP withdraws NL-CH Freedom routes
3. **10-30s:** Traffic fails over to NL-CH xs4all (LP 150) or transit
4. **15-30s:** Convergence complete

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 30s -->
BGP recovery to >= 20 peers within 30 seconds.

<!-- VALIDATE: http_ok >= 4 within 60s -->
HTTP endpoints respond within 60 seconds.

<!-- VALIDATE: vti_ping reachable within 45s -->
Backup path reachable within 45 seconds.

#### Recovery

1. `no shutdown` on vti-nl-ch-freedom
2. `clear shun` on nlasa01
3. Reload swanctl on CH VPS if needed
4. Verify Freedom path preferred again

#### Post-Recovery Validation

<!-- VALIDATE: tunnel_up == true within 120s -->
Tunnel UP within 120 seconds.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Full mesh within 90 seconds.

---

### 3.4 GR-NO Inalan Tunnel

**Tunnel:** GR (grasa01) to NO VPS (198.51.100.X) via Inalan ISP
**VTI Interface:** vti-gr-no-inalan
**BGP Impact:** GR route reflector 1 path, failover via NL transit

#### Pre-checks

1. Verify GR-CH Inalan tunnel is UP (backup GR exit)
2. Verify SSH access to grasa01 (via gr-pve01 stepstone)
3. Verify BGP peer count >= 22
4. Verify HTTP baseline

#### Injection

```
# On grasa01 (via stepstone):
interface vti-gr-no-inalan
 shutdown
```

Automated: `chaos_baseline.py baseline-test --tunnel "GR ↔ NO" --wan inalan --duration 120`

#### Expected Behavior

1. **0-5s:** IKE SA timeout on GR ASA
2. **5-20s:** BGP withdraws GR-NO Inalan routes
3. **10-30s:** GR traffic routes via GR-CH Inalan or NL transit (LP 100)
4. **15-30s:** Convergence via backup path

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 30s -->
BGP peers >= 20 within 30 seconds.

<!-- VALIDATE: http_ok >= 4 within 60s -->
HTTP reachable within 60 seconds.

<!-- VALIDATE: vti_ping reachable within 45s -->
Alternate path reachable within 45 seconds.

#### Recovery

1. `no shutdown` on vti-gr-no-inalan
2. `clear shun` on grasa01
3. Reload swanctl on NO VPS if needed

#### Post-Recovery Validation

<!-- VALIDATE: tunnel_up == true within 120s -->
Inalan tunnel UP within 120 seconds.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Full mesh within 90 seconds.

---

### 3.5 GR-CH Inalan Tunnel

**Tunnel:** GR (grasa01) to CH VPS (198.51.100.X) via Inalan ISP
**VTI Interface:** vti-gr-ch-inalan
**BGP Impact:** GR route reflector 2 path, failover via NL transit

#### Pre-checks

1. Verify GR-NO Inalan tunnel is UP
2. Verify SSH access to grasa01 (via gr-pve01 stepstone)
3. Verify BGP peer count >= 22
4. Verify HTTP baseline

#### Injection

```
# On grasa01 (via stepstone):
interface vti-gr-ch-inalan
 shutdown
```

Automated: `chaos_baseline.py baseline-test --tunnel "GR ↔ CH" --wan inalan --duration 120`

#### Expected Behavior

1. **0-5s:** IKE SA timeout on GR ASA
2. **5-20s:** BGP withdraws GR-CH Inalan routes
3. **10-30s:** Traffic shifts to GR-NO Inalan or NL transit
4. **15-30s:** Convergence

#### Validation

<!-- VALIDATE: bgp_established >= 20 within 30s -->
BGP peers >= 20 within 30 seconds.

<!-- VALIDATE: http_ok >= 4 within 60s -->
HTTP endpoints within 60 seconds.

<!-- VALIDATE: vti_ping reachable within 45s -->
Backup path within 45 seconds.

#### Recovery

1. `no shutdown` on vti-gr-ch-inalan
2. `clear shun` on grasa01
3. Reload swanctl on CH VPS if needed

#### Post-Recovery Validation

<!-- VALIDATE: tunnel_up == true within 120s -->
Tunnel UP within 120 seconds.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Full mesh within 90 seconds.

---

## 4. Emergency Abort Procedure

If any scenario goes wrong during execution:

1. **Dead-man switch:** If the chaos framework's dead-man timer expires (default 300s), all faults are automatically rolled back.
2. **Manual abort:** Write `recover` to the chaos state file or create `~/gateway.maintenance` to halt the exercise.
3. **Immediate recovery:** Run `no shutdown` on all affected VTI interfaces. Run `clear shun` on both ASAs. Run `swanctl --load-all` on both VPS hosts.
4. **Verification:** Wait 120 seconds, then validate all 9 tunnels are UP via `vpn-mesh-stats.py`.

**CRITICAL:** NEVER run `clear bgp *` or restart FRR on VPS hosts. This would tear down real AS64512 upstream BGP peering and cause a production internet outage.

---

## 5. Appendix: Tunnel Inventory

| Tunnel | ASA | VTI Interface | ISP | LP | Backup Path |
|--------|-----|---------------|-----|----|----|
| NL-GR Freedom | nlasa01 | vti-nl-gr-freedom | Freedom | 200 | xs4all (150), FRR (100) |
| NL-NO Freedom | nlasa01 | vti-nl-no-freedom | Freedom | 200 | xs4all (150) |
| NL-CH Freedom | nlasa01 | vti-nl-ch-freedom | Freedom | 200 | xs4all (150) |
| NL-GR xs4all | nlasa01 | vti-nl-gr-xs4all | xs4all | 150 | Freedom (200), FRR (100) |
| NL-NO xs4all | nlasa01 | vti-nl-no-xs4all | xs4all | 150 | Freedom (200) |
| NL-CH xs4all | nlasa01 | vti-nl-ch-xs4all | xs4all | 150 | Freedom (200) |
| GR-NO Inalan | grasa01 | vti-gr-no-inalan | Inalan | 200 | NL transit (100) |
| GR-CH Inalan | grasa01 | vti-gr-ch-inalan | Inalan | 200 | NL transit (100) |
| NL-GR FRR | FRR transit | vti-nl-gr-frr | Transit | 100 | Freedom (200), xs4all (150) |
