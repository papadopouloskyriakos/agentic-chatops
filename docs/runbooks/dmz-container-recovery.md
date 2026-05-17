# Runbook: DMZ Container Recovery

**Runbook ID:** RB-DMZ-001
**Last Updated:** 2026-04-14
**Exercise Program Reference:** docs/exercise-program.md
**Automation:** scripts/chaos_baseline.py dmz-test

---

## 1. Overview

This runbook covers procedures for DMZ container recovery chaos exercises. Each DMZ host (nl-dmz01, gr-dmz01) runs 4 LXC containers serving web applications. Exercises validate that containers restart and HTTP endpoints recover within the 120-second SLO.

**DMZ Containers per host:**
- portfolio (Example Corp website)
- cubeos (CubeOS application)
- meshsat (MeshSat dashboard)
- mulecube (MuleCube service)

---

## 2. Trigger Conditions

This runbook is used when:
- Quarterly DMZ drill (Q1/Q2/Q3/Q4 15th 10:00 UTC)
- Combined game day DMZ component
- Ad-hoc validation after DMZ infrastructure changes
- Post-incident validation of container recovery

---

## 3. Scenarios

### 3.1 Single Container Kill -- Portfolio

**Target:** Portfolio container on nl-dmz01
**Impact:** Example Corp website temporarily unavailable
**Recovery:** Proxmox auto-restart or manual `pct start`

#### Pre-checks

1. Verify all 4 containers are running on target host:
   ```
   ssh -i ~/.ssh/one_key operator@nl-dmz01 pct list
   ```
2. Verify HTTP baseline for portfolio endpoint
3. Verify SSH access to DMZ host
4. Note container VMID for portfolio

#### Injection

```
# On nl-dmz01:
pct stop <portfolio-vmid>
```

#### Expected Behavior

1. **0-5s:** Container stops, HTTP returns 502/503
2. **5-30s:** Proxmox onboot or watchdog detects stopped container
3. **30-90s:** Container restarts, services initialize
4. **60-120s:** HTTP endpoint returns 200

#### Validation

<!-- VALIDATE: http_ok >= 4 within 120s -->
Verify HTTP reachability to all 4 DMZ endpoints returns 200 within 120 seconds. The killed container's endpoint must recover; the other 3 must remain unaffected.

<!-- VALIDATE: container_count >= 4 within 60s -->
Verify all 4 containers show "running" status within 60 seconds of the restart trigger.

#### Recovery

If auto-restart fails:
```
pct start <portfolio-vmid>
```

Verify container is running:
```
pct status <portfolio-vmid>
```

---

### 3.2 Single Container Kill -- CubeOS

**Target:** CubeOS container on nl-dmz01
**Impact:** CubeOS application temporarily unavailable
**Recovery:** Same as portfolio

#### Pre-checks

Same as 3.1.

#### Injection

```
pct stop <cubeos-vmid>
```

#### Expected Behavior

Same timeline as 3.1. CubeOS may have a longer startup time due to application initialization.

#### Validation

<!-- VALIDATE: http_ok >= 4 within 120s -->
All 4 endpoints recover within 120 seconds.

<!-- VALIDATE: container_count >= 4 within 60s -->
All 4 containers running within 60 seconds.

---

### 3.3 Single Container Kill -- MeshSat

**Target:** MeshSat container on nl-dmz01
**Impact:** MeshSat dashboard temporarily unavailable

**CRITICAL WARNING:** This exercises the MeshSat DMZ container only. NEVER kill or inject faults into hub.meshsat.net -- the Galera MariaDB cluster is fragile and not designed for chaos testing.

#### Pre-checks

Same as 3.1.

#### Injection

```
pct stop <meshsat-vmid>
```

#### Expected Behavior

Same timeline as 3.1.

#### Validation

<!-- VALIDATE: http_ok >= 4 within 120s -->
All 4 endpoints recover within 120 seconds.

<!-- VALIDATE: container_count >= 4 within 60s -->
All 4 containers running within 60 seconds.

---

### 3.4 Single Container Kill -- MuleCube

**Target:** MuleCube container on nl-dmz01
**Impact:** MuleCube service temporarily unavailable

#### Pre-checks

Same as 3.1.

#### Injection

```
pct stop <mulecube-vmid>
```

#### Expected Behavior

Same timeline as 3.1.

#### Validation

<!-- VALIDATE: http_ok >= 4 within 120s -->
All 4 endpoints recover within 120 seconds.

<!-- VALIDATE: container_count >= 4 within 60s -->
All 4 containers running within 60 seconds.

---

### 3.5 Full Host Kill -- All 4 Containers (NL)

**Target:** All containers on nl-dmz01
**Impact:** All NL DMZ services temporarily unavailable
**Risk Level:** High -- validates full-host recovery

#### Pre-checks

1. Verify all 4 containers running on nl-dmz01
2. Verify GR DMZ (gr-dmz01) is healthy and serving traffic (provides partial redundancy)
3. Verify HTTP baseline for all endpoints
4. Verify SSH access

#### Injection

```
# On nl-dmz01 -- stop all containers in sequence:
for vmid in $(pct list | tail -n +2 | awk '{print $1}'); do
    pct stop $vmid
done
```

#### Expected Behavior

1. **0-5s:** All containers stop, all HTTP endpoints return errors
2. **5-30s:** Proxmox watchdog detects all containers stopped
3. **30-90s:** Containers restart in sequence (onboot order)
4. **60-120s:** Containers initialize services
5. **90-120s:** All HTTP endpoints return 200

#### Validation

<!-- VALIDATE: http_ok >= 4 within 120s -->
All 4 DMZ endpoints return HTTP 200 within 120 seconds of injection.

<!-- VALIDATE: container_count >= 4 within 60s -->
All 4 containers reach "running" state within 60 seconds of restart.

---

### 3.6 Full Host Kill -- All 4 Containers (GR)

**Target:** All containers on gr-dmz01
**Impact:** All GR DMZ services temporarily unavailable

#### Pre-checks

1. Verify all 4 containers running on gr-dmz01
2. Verify NL DMZ (nl-dmz01) is healthy
3. Verify HTTP baseline
4. Verify SSH access (direct via VPN, not OOB stepstone)

#### Injection

```
# On gr-dmz01:
for vmid in $(pct list | tail -n +2 | awk '{print $1}'); do
    pct stop $vmid
done
```

#### Expected Behavior

Same timeline as 3.5 but on GR infrastructure.

#### Validation

<!-- VALIDATE: http_ok >= 4 within 120s -->
All GR DMZ endpoints return HTTP 200 within 120 seconds.

<!-- VALIDATE: container_count >= 4 within 60s -->
All 4 GR containers running within 60 seconds.

---

## 4. Emergency Abort Procedure

If containers fail to restart:

1. **Manual restart:** SSH to DMZ host and `pct start <vmid>` for each container
2. **Host-level issue:** If the Proxmox host itself is unresponsive, escalate to PVE cluster recovery
3. **Network issue:** Verify VPN tunnels are UP -- DMZ hosts may be unreachable if the inter-site path is also down
4. **Dead-man switch:** The chaos framework auto-recovers via `pct start` if the dead-man timer expires

**Constraint:** At most 1 DMZ link (NL or GR) may be disrupted at a time. Never kill containers on both DMZ hosts simultaneously.

---

## 5. Post-Exercise Checklist

1. All 4 containers running on the target host
2. All HTTP endpoints returning 200
3. No orphaned processes from stopped containers
4. Container logs show clean startup (no crash loops)
5. Prometheus metrics show container_up = 1 for all targets
6. LibreNMS shows no alerts for DMZ hosts
7. Alert suppression removed (if applied)

---

## 6. Appendix: DMZ Container Inventory

| Host | Container | Service | HTTP Endpoint |
|------|-----------|---------|---------------|
| nl-dmz01 | portfolio | Example Corp website | https://example.net |
| nl-dmz01 | cubeos | CubeOS application | https://cubeos.example.net |
| nl-dmz01 | meshsat | MeshSat dashboard | https://meshsat.example.net |
| nl-dmz01 | mulecube | MuleCube service | https://mulecube.example.net |
| gr-dmz01 | portfolio | Example Corp website (GR) | GR endpoint |
| gr-dmz01 | cubeos | CubeOS application (GR) | GR endpoint |
| gr-dmz01 | meshsat | MeshSat dashboard (GR) | GR endpoint |
| gr-dmz01 | mulecube | MuleCube service (GR) | GR endpoint |
