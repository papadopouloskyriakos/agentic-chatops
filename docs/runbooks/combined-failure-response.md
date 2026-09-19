# Runbook: Combined Failure Response

**Runbook ID:** RB-CMB-001
**Last Updated:** 2026-04-14
**Exercise Program Reference:** docs/exercise-program.md
**Automation:** scripts/chaos-calendar.sh (combined-game-day)

---

## 1. Overview

This runbook covers procedures for multi-fault chaos exercises that combine tunnel failures with DMZ outages or simulate full site isolation. These are the most complex exercises in the program and run during the semi-annual combined game day (June/December) and annual site isolation drill (September).

Combined exercises validate that the system degrades gracefully under multiple simultaneous faults and that recovery procedures work correctly when multiple subsystems need attention.

---

## 2. Trigger Conditions

This runbook is used when:
- Semi-annual combined game day (Jun 15 / Dec 15 10:00 UTC)
- Annual site isolation drill (Sep 15 10:00 UTC)
- Ad-hoc multi-fault validation after major infrastructure changes

---

## 3. Scenarios

### 3.1 Combined Tunnel + DMZ Failure

**Faults:** NL-GR Freedom tunnel killed AND nl-dmz01 containers stopped
**Impact:** Inter-site connectivity degraded to backup paths AND NL DMZ services temporarily unavailable
**Duration:** Each fault injected sequentially with 610s cooldown between phases

#### Pre-checks

1. Verify all 9 VPN tunnels are UP:
   ```
   python3 scripts/vpn-mesh-stats.py
   ```
2. Verify all DMZ containers running on both hosts
3. Verify BGP peer count >= 22
4. Verify HTTP baseline for all endpoints
5. Verify SSH access to nlasa01 and nl-dmz01
6. Verify GR DMZ (gr-dmz01) is healthy -- it provides redundancy during NL DMZ outage
7. Verify backup tunnels (xs4all, FRR transit) are UP

#### Phase 1: Tunnel Kill

**Injection:**
```
# On nlasa01:
interface vti-nl-gr-freedom
 shutdown
```

**Expected Behavior:**
1. **0-30s:** BGP reconverges via xs4all (LP 150) or FRR transit (LP 100)
2. **30-60s:** HTTP endpoints recover via backup path

**Phase 1 Validation:**

<!-- VALIDATE: bgp_established >= 20 within 30s -->
BGP peers recover to >= 20 within 30 seconds of tunnel kill.

<!-- VALIDATE: http_ok >= 4 within 60s -->
HTTP endpoints reachable within 60 seconds via backup tunnel.

**Cooldown:** 610 seconds before Phase 2.

#### Phase 2: DMZ Container Kill

While the Freedom tunnel is still down, kill all NL DMZ containers.

**Injection:**
```
# On nl-dmz01:
for vmid in $(pct list | tail -n +2 | awk '{print $1}'); do
    pct stop $vmid
done
```

**Expected Behavior:**
1. **0-5s:** All NL DMZ HTTP endpoints fail
2. **5-60s:** Containers begin restarting
3. **60-120s:** Containers recover, HTTP returns 200
4. Traffic to NL DMZ flows via the backup tunnel (xs4all/FRR) -- recovery may be slightly slower due to increased latency on backup path

**Phase 2 Validation:**

<!-- VALIDATE: http_ok >= 4 within 120s -->
All 4 NL DMZ endpoints return HTTP 200 within 120 seconds, despite traffic flowing via backup tunnel.

<!-- VALIDATE: container_count >= 4 within 60s -->
All 4 containers reach "running" state within 60 seconds.

**Cooldown:** 610 seconds before Phase 3.

#### Phase 3: Recovery

1. Restore Freedom tunnel:
   ```
   interface vti-nl-gr-freedom
    no shutdown
   ```
2. Clear ASA shun entries:
   ```
   clear shun
   ```
3. Verify all containers are running
4. Wait for BGP to prefer Freedom path again (LP 200)

**Phase 3 Validation:**

<!-- VALIDATE: tunnel_up == true within 120s -->
Freedom tunnel returns to UP/UP within 120 seconds.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Full BGP mesh restored (>= 22 peers) within 90 seconds.

<!-- VALIDATE: http_ok >= 4 within 60s -->
All HTTP endpoints healthy within 60 seconds of full recovery.

---

### 3.2 Full Site Isolation -- GR

**Faults:** All tunnels from GR site killed (GR-NO Inalan, GR-CH Inalan, NL-GR Freedom, NL-GR xs4all, NL-GR FRR)
**Impact:** GR site completely isolated from NL and VPS. GR services only reachable via Inalan ISP direct internet.
**Duration:** Up to 30 minutes of isolation, then phased recovery
**Schedule:** Annual, Sep 15 10:00 UTC

**CRITICAL:** This is a manual exercise. The operator must be actively monitoring throughout. Do not run this unattended.

#### Pre-checks

1. Verify all tunnels UP
2. Verify GR site internal services healthy (PVE cluster, storage, networking)
3. Verify GR DMZ containers running
4. Verify GR LibreNMS (gr-nms01) is operational and can alert independently
5. Verify operator has direct SSH access to GR via Inalan internet path (not via VPN)
6. Create maintenance mode file:
   ```
   echo '{"started":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","reason":"Annual site isolation drill","eta_minutes":360,"operator":"kyriakos"}' > ~/gateway.maintenance
   ```
7. Notify Matrix `#infra-gr-prod`: `[CHAOS] Annual site isolation drill starting -- GR will be isolated for up to 30 minutes`

#### Phase 1: Isolate GR

**Injection sequence (on nlasa01):**
```
interface vti-nl-gr-freedom
 shutdown
interface vti-nl-gr-xs4all
 shutdown
```

**Injection sequence (on grasa01, via Inalan direct):**
```
interface vti-gr-no-inalan
 shutdown
interface vti-gr-ch-inalan
 shutdown
```

**Expected Behavior:**
1. **0-30s:** All BGP paths to/from GR withdraw
2. **30-60s:** GR site is fully isolated -- no VPN connectivity
3. **60s+:** GR internal services continue operating (PVE cluster, local storage, local networking)
4. NL site continues operating via Freedom/xs4all to VPS

**Phase 1 Validation:**

<!-- VALIDATE: bgp_established >= 12 within 30s -->
NL-side BGP peer count drops but NL-to-VPS paths remain (>= 12 peers expected without GR).

<!-- VALIDATE: http_ok >= 4 within 60s -->
NL DMZ endpoints remain reachable. GR DMZ endpoints become unreachable via VPN (but may remain reachable via Inalan direct internet).

#### Phase 2: GR Autonomous Operation (Observation)

During isolation, verify GR site operates independently:
1. GR PVE cluster is healthy (Corosync may lose quorum if < 3 nodes -- verify behavior)
2. GR LibreNMS continues monitoring GR-local devices
3. GR DMZ services respond via Inalan direct path
4. GR iSCSI storage continues serving local clients

Duration: 15-30 minutes of observation.

#### Phase 3: Phased Recovery

Restore tunnels in priority order:

1. **First:** NL-GR Freedom (primary inter-site path):
   ```
   # On nlasa01:
   interface vti-nl-gr-freedom
    no shutdown
   ```

2. **Wait 120s** for BGP to converge via Freedom.

3. **Second:** GR-NO Inalan (GR to VPS RR1):
   ```
   # On grasa01:
   interface vti-gr-no-inalan
    no shutdown
   ```

4. **Wait 120s** for additional BGP paths.

5. **Third:** Remaining tunnels:
   ```
   # nlasa01:
   interface vti-nl-gr-xs4all
    no shutdown
   
   # grasa01:
   interface vti-gr-ch-inalan
    no shutdown
   ```

6. Clear shun on both ASAs:
   ```
   # nlasa01:
   clear shun
   
   # grasa01:
   clear shun
   ```

7. Reload swanctl on both VPS if any IKE SA stalls:
   ```
   ssh -i ~/.ssh/one_key operator@198.51.100.X sudo swanctl --load-all
   ssh -i ~/.ssh/one_key operator@198.51.100.X sudo swanctl --load-all
   ```

**Phase 3 Validation:**

<!-- VALIDATE: tunnel_up == true within 120s -->
All 9 tunnels return to UP state within 120 seconds of the final recovery command.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Full BGP mesh (>= 22 peers) re-established within 90 seconds.

<!-- VALIDATE: http_ok >= 4 within 60s -->
All HTTP endpoints from both sites healthy within 60 seconds.

#### Phase 4: Cleanup

1. Remove maintenance mode:
   ```
   rm ~/gateway.maintenance
   ```
2. Wait 15 minutes for post-maintenance cooldown (alerts tagged as recovery)
3. Verify no lingering alerts in LibreNMS or Prometheus
4. Notify Matrix `#infra-gr-prod`: `[CHAOS] Site isolation drill complete -- all services restored`

---

## 4. Emergency Abort Procedure

### For Combined Tunnel + DMZ (3.1)

1. Immediately restore the killed tunnel: `no shutdown`
2. Immediately restart any stopped containers: `pct start <vmid>`
3. Clear shun on both ASAs
4. Verify all services recover within 120 seconds

### For Site Isolation (3.2)

1. Immediately `no shutdown` on ALL killed interfaces (both ASAs)
2. Clear shun on both ASAs
3. Reload swanctl on both VPS
4. Remove maintenance mode file
5. Wait 120 seconds for full convergence
6. Verify all 9 tunnels UP and BGP peer count >= 22

**CRITICAL:** NEVER clear BGP or restart FRR on VPS hosts. Tunnels will re-establish automatically once interfaces are brought back up.

---

## 5. Post-Exercise Review

Combined exercises and site isolation drills require a post-mortem review:

1. **Timeline:** Document exact times for each phase (injection, detection, recovery)
2. **SLO compliance:** Did each phase meet its individual SLO?
3. **Unexpected behavior:** Document any surprises (e.g., Corosync quorum issues, ASA shun, stale connections)
4. **Runbook accuracy:** Update runbooks if procedures need adjustment
5. **Improvement items:** Create YouTrack issues for any infrastructure improvements identified

Review is conducted within 48 hours and results are stored in `incident_knowledge` for RAG retrieval.

---

## 6. Blast Radius Summary

| Scenario | Max Tunnels Down | Max DMZ Down | Max Duration | Operator Required |
|----------|-----------------|-------------|--------------|-------------------|
| Combined Tunnel + DMZ | 1 | 1 site (4 containers) | 45 min | No (automated) |
| Site Isolation (GR) | 5 (all GR paths) | 0 (GR DMZ stays up locally) | 6 hours | Yes (manual) |
