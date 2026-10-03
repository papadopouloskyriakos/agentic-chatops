# Runbook: Post-Recovery Validation

**Runbook ID:** RB-PRV-001
**Last Updated:** 2026-04-14
**Exercise Program Reference:** docs/exercise-program.md

---

## 1. Overview

This runbook provides the universal post-recovery validation checklist used after every chaos exercise, regardless of type. It ensures that the system has fully returned to its baseline state before the exercise is marked as complete.

Every chaos exercise must conclude with this checklist. An exercise is not considered complete until all applicable checks pass.

---

## 2. Tunnel Status Verification

Verify all 9 VPN tunnels are in UP/UP state.

**Command:**
```bash
python3 scripts/vpn-mesh-stats.py
```

**Manual verification per tunnel:**
```bash
# NL ASA tunnels:
ssh operator@10.0.181.X
show interface vti-nl-gr-freedom
show interface vti-nl-gr-xs4all
show interface vti-nl-no-freedom
show interface vti-nl-no-xs4all
show interface vti-nl-ch-freedom
show interface vti-nl-ch-xs4all

# GR ASA tunnels (via stepstone):
ssh -J root@gr-pve01 operator@<grasa01-ip>
show interface vti-gr-no-inalan
show interface vti-gr-ch-inalan

# FRR transit:
ssh -i ~/.ssh/one_key operator@198.51.100.X sudo vtysh -c "show interface vti-nl-gr-frr"
```

**Expected result:** All 9 tunnels show UP/UP (line protocol up).

<!-- VALIDATE: tunnel_up == true within 120s -->
All tunnels must be UP within 120 seconds of the final recovery action. Any tunnel remaining DOWN triggers investigation.

---

## 3. BGP Peer Count

Verify the full iBGP mesh is established.

**Command:**
```bash
ssh -i ~/.ssh/one_key operator@198.51.100.X sudo vtysh -c "show bgp summary"
ssh -i ~/.ssh/one_key operator@198.51.100.X sudo vtysh -c "show bgp summary"
```

**Expected result:** >= 22 established BGP peers across both route reflectors.

<!-- VALIDATE: bgp_established >= 22 within 90s -->
Full BGP mesh must re-establish within 90 seconds. If peer count is below 22, identify which peers are missing and check their tunnel status.

**Check for stuck peers:**
```bash
# Look for peers in Active, Connect, or OpenSent state:
ssh -i ~/.ssh/one_key operator@198.51.100.X sudo vtysh -c "show bgp summary" | grep -E "Active|Connect|OpenSent"
```

If peers are stuck, the underlying tunnel likely has an IKE SA issue. Check swanctl:
```bash
ssh -i ~/.ssh/one_key operator@198.51.100.X sudo swanctl --list-sas
```

---

## 4. HTTP Reachability

Verify all monitored HTTP endpoints return 200.

**Endpoints to check:**
```bash
# NL DMZ:
curl -sS -o /dev/null -w "%{http_code}" https://example.net
curl -sS -o /dev/null -w "%{http_code}" https://cubeos.example.net
curl -sS -o /dev/null -w "%{http_code}" https://meshsat.example.net
curl -sS -o /dev/null -w "%{http_code}" https://mulecube.example.net

# GR DMZ:
# (equivalent GR endpoints)

# Internal services:
curl -sS -o /dev/null -w "%{http_code}" https://n8n.example.net
curl -sS -o /dev/null -w "%{http_code}" https://grafana.example.net
```

**Expected result:** All endpoints return HTTP 200.

<!-- VALIDATE: http_ok >= 4 within 60s -->
At minimum, the 4 primary DMZ endpoints must return HTTP 200 within 60 seconds of recovery completion.

---

## 5. Container Health

Verify all DMZ containers are running on both hosts.

**NL DMZ:**
```bash
ssh -i ~/.ssh/one_key operator@nl-dmz01 pct list
```

**GR DMZ:**
```bash
ssh -i ~/.ssh/one_key operator@gr-dmz01 pct list
```

**Expected result:** All containers show "running" status. No containers in "stopped" or error state.

<!-- VALIDATE: container_count >= 4 within 60s -->
Each DMZ host must have >= 4 containers in "running" state within 60 seconds. If a container is stuck in "stopped", manually start it with `pct start <vmid>`.

**Check for crash loops:**
```bash
# On the DMZ host, check container logs for repeated restarts:
journalctl -u pve-container@<vmid> --since "1 hour ago" | grep -c "Start"
```

If a container has restarted more than 3 times in the past hour, it may be in a crash loop. Investigate container logs before marking the exercise complete.

---

## 6. Alert Suppression Cleanup

Verify that all chaos-related alert suppression has been removed.

**Check maintenance mode:**
```bash
ls -la ~/gateway.maintenance
# Should NOT exist (unless a longer maintenance window is intentionally active)
```

**Check chaos state:**
```bash
ls -la ~/chaos-state/chaos-active.json
# Should NOT exist after exercise completion
```

**Check n8n maintenance suppression:**
Verify that the 15-minute post-maintenance cooldown is active (alerts tagged `post-maintenance-recovery`) and will expire naturally.

<!-- VALIDATE: maintenance_mode == false within 60s -->
The `gateway.maintenance` file must not exist after exercise completion. The chaos framework should remove it automatically; if it persists, delete it manually.

---

## 7. Prometheus Metrics Normalization

Verify that Prometheus metrics have returned to normal ranges.

**Key metrics to check in Grafana:**

1. **VPN tunnel status:** All tunnel_up gauges = 1
2. **BGP peer count:** bgp_peers_established >= 22
3. **HTTP probe success:** probe_success = 1 for all targets
4. **Container up:** container_up = 1 for all DMZ containers
5. **Latency:** No anomalous latency spikes persisting after exercise

**Command-line check:**
```bash
# Query Prometheus directly:
curl -s 'http://nl-pve01:9090/api/v1/query?query=up' | python3 -m json.tool | grep -c '"1"'
```

<!-- VALIDATE: prometheus_normal == true within 300s -->
All Prometheus metrics must return to baseline within 300 seconds (5 minutes) of recovery. Some metrics (especially rate-based counters) may take a full scrape interval (15-30s) to normalize.

---

## 8. ASA Shun Table Cleanup

Verify that no chaos-related shun entries remain on either ASA.

**NL ASA:**
```bash
ssh operator@10.0.181.X
show shun
```

**GR ASA (via stepstone):**
```bash
ssh -J root@gr-pve01 operator@<grasa01-ip>
show shun
```

**Expected result:** No shun entries for VTI tunnel endpoints or DMZ addresses.

If shun entries exist:
```
clear shun
```

<!-- VALIDATE: shun_count == 0 within 60s -->
Both ASA shun tables must be empty (or contain only pre-existing entries unrelated to the exercise) within 60 seconds of recovery.

---

## 9. LibreNMS Alert Check

Verify that LibreNMS is not reporting any alerts related to the exercise.

**NL LibreNMS:**
```bash
curl -sk -H "X-Auth-Token: $LIBRENMS_NL_TOKEN" \
  https://nl-nms01.example.net/api/v0/alerts?state=1
```

**GR LibreNMS:**
```bash
curl -sk -H "X-Auth-Token: $LIBRENMS_GR_TOKEN" \
  https://gr-nms01.example.net/api/v0/alerts?state=1
```

**Expected result:** No active alerts for devices involved in the exercise. Pre-existing alerts unrelated to the exercise are acceptable.

<!-- VALIDATE: librenms_alerts == 0 within 300s -->
LibreNMS alerts related to exercise targets must clear within 300 seconds. Some alerts may take 1-2 polling cycles (300s each) to auto-resolve.

---

## 10. Corosync Cluster Health

After any exercise that affects inter-site connectivity, verify Corosync cluster health.

**NL PVE cluster:**
```bash
ssh nl-pve01 pvecm status
```

**GR PVE cluster:**
```bash
ssh -i ~/.ssh/one_key root@gr-pve01 pvecm status
```

**Expected result:** All nodes show "Online" status. Quorum is established. No nodes in "OFFLINE" or "unknown" state.

<!-- VALIDATE: cluster_healthy == true within 120s -->
PVE cluster must show all nodes online within 120 seconds. If a node is offline, check if it lost connectivity during the exercise and verify Corosync knet traffic is flowing via the correct interface (not via ASA outside -- see incident_corosync_split_20260411).

---

## 11. VPN Mesh Stats API

Run the mesh stats API to get a comprehensive tunnel status snapshot.

**Command:**
```bash
python3 scripts/vpn-mesh-stats.py
```

**Expected result:** All 9 tunnels show UP status with acceptable latency values. No tunnels in STANDBY or DOWN state.

<!-- VALIDATE: mesh_status == healthy within 120s -->
The mesh stats output must show all tunnels healthy. Standby tunnels are acceptable only if they were intentionally in standby before the exercise.

---

## 12. Final Sign-off Checklist

| Check | Status | Notes |
|-------|--------|-------|
| All 9 VPN tunnels UP | [ ] | |
| BGP peers >= 22 | [ ] | |
| All HTTP endpoints 200 | [ ] | |
| All DMZ containers running | [ ] | |
| Maintenance mode removed | [ ] | |
| Chaos state file removed | [ ] | |
| Prometheus metrics normal | [ ] | |
| ASA shun tables clean | [ ] | |
| LibreNMS alerts clear | [ ] | |
| Corosync clusters healthy | [ ] | |
| Mesh stats healthy | [ ] | |

Once all checks pass, the exercise result (PASS/DEGRADED/FAIL) is recorded in `gateway.db` and a completion notification is posted to the relevant Matrix room.

---

## 13. Troubleshooting Common Issues

### Tunnel stuck DOWN after recovery

1. Check IKE SA: `swanctl --list-sas` on VPS
2. Reload swanctl: `sudo swanctl --load-all` on VPS
3. Check ASA shun table: `show shun` -- VTI endpoints may be shunned
4. Check ASA connection table: stale connections can route traffic incorrectly (see Corosync split incident)
5. If all else fails, use `vti-freedom-recovery.sh` script

### BGP peers not recovering

1. Check underlying tunnel status first -- BGP needs the tunnel
2. Verify next-hop-self force is configured on route reflectors
3. Check BFD status: `show bfd peers` on FRR
4. NEVER clear BGP or restart FRR on VPS

### Containers not restarting

1. Check Proxmox host health: `pveversion`, `pvecm status`
2. Check storage availability: containers need their storage backend
3. Manual start: `pct start <vmid>`
4. Check for resource exhaustion (OOM): `dmesg | tail -20`

### Lingering alerts

1. Wait for full polling cycle (up to 300s for LibreNMS)
2. Check if the alert condition is genuinely resolved
3. Manually acknowledge in LibreNMS if the alert is stale
4. Verify Prometheus targets are being scraped: check `up` metric
