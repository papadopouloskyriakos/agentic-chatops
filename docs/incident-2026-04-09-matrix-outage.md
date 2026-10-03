# Incident Report: Matrix Homeserver Outage + VTI Tunnel Instability

**Date:** 2026-04-09 / 2026-04-10
**Duration:** ~20 hours (2026-04-09 15:12 UTC → 2026-04-10 11:56 UTC)
**Severity:** High — all Matrix-based alert delivery silently failed
**Authored:** 2026-04-10 by Claude Code (automated investigation)

---

## Executive Summary

The Matrix homeserver (nl-matrix01) became unresponsive for approximately 20 hours, causing all ChatOps alert delivery to silently fail. Concurrently, the Freedom ISP VTI tunnels experienced an ESP dataplane failure, disrupting cross-site connectivity between the NL and GR sites. Internet connectivity (both WAN links) remained operational throughout — this was **not** an ISP outage.

---

## Timeline (all times UTC)

### Pre-incident: VTI Tunnel Instability

| Time | Event |
|------|-------|
| **Apr 8 23:17** | First cross-site connectivity failure detected. gr-pve02 cannot reach nlinfluxdb01:8086 (connection timeout). PVE scheduler loses corosync quorum. |
| **Apr 8 23:18** | IFRNLLEI01PRD-387 — Service up/down on nl-pve03 (Critical). LibreNMS alert delivered to Matrix successfully. |
| **Apr 8 23:22** | IFRGRSKG01PRD-168 — gr-pve02 Device Down (SNMP unreachable). Root cause: VTI tunnel disruption. |
| **Apr 8 23:40** | gr-pve02 SNMP recovers (~18 min outage). xs4all tunnels provide failover. |
| **Apr 9 07:35** | Corosync service killed (SIGTERM) on nl-pve01 — PVE cluster communication degraded. |
| **Apr 9 07:42** | First alert wave subsides. Sporadic service up/down flapping through morning. |

### Matrix Outage Begins

| Time | Event |
|------|-------|
| **Apr 9 14:02** | **Second VTI disruption wave.** IFRNLLEI01PRD-396/397/398 — Service up/down on all 3 NL PVE hosts simultaneously. IFRGRSKG01PRD-172 — gr-pve02 also affected. Cross-site metrics delivery failing (influxdb timeouts, PBS connection timeouts). |
| **Apr 9 15:08** | Last successful GR LibreNMS alert delivery via Matrix (execution 147955). |
| **Apr 9 15:12** | **Matrix rate-limits the bot** — HTTP 429 Too Many Requests (execution 148008). The burst of alerts from the 14:02 wave likely overwhelmed Synapse. |
| **Apr 9 15:52** | Last successful NL LibreNMS alert delivery (execution 148421). |
| **Apr 9 ~16:00** | **Matrix becomes completely unreachable.** All subsequent alert workflow executions fail at "Post Alert to Matrix" with ECONNRESET / "socket hang up". |
| **Apr 9 16:00 → Apr 10 09:38** | **~18-hour silent period.** No NL LibreNMS webhook executions recorded. Alerts continue firing in LibreNMS but are never delivered. |

### Concurrent Cluster Instability (Evening Apr 9)

| Time | Event |
|------|-------|
| **Apr 9 20:33** | Corosync retransmit list appears (1 packet). |
| **Apr 9 21:10** | Retransmit list grows to **17 packets** — significant cluster communication failure between PVE nodes. |
| **Apr 9 21:21–23:53** | Retransmit lists continue at 10–30 minute intervals, indicating ongoing cross-site tunnel instability. |

### Recovery

| Time | Event |
|------|-------|
| **Apr 10 09:38** | NL LibreNMS alert webhooks resume reaching n8n. Alerts still fail at Matrix delivery (ECONNRESET). |
| **Apr 10 09:38–11:54** | **Error storm:** ~2 NL executions every 2 minutes + ~1 GR execution every 6 minutes, all failing at Matrix POST. |
| **Apr 10 11:56** | **Matrix recovers.** NL LibreNMS alerts begin delivering successfully (execution 151892+). |
| **Apr 10 11:58** | GR LibreNMS alerts also recovering (execution 151930+). |
| **Apr 10 11:56** | Third VTI disruption wave — IFRNLLEI01PRD-438/439, IFRGRSKG01PRD-173. Service up/down alerts fire and are now delivered successfully. gr-pve02 alert count reaches 44+ (firing every ~6 min). |
| **Apr 10 12:32** | IFRNLLEI01PRD-440 created — formally tracking Freedom VTI ESP dataplane issue. |

### Concurrent: Freedom PPPoE Outage + Stale QoS (34-hour SMS gap)

| Time | Event |
|------|-------|
| **Apr 8 23:08** | Freedom PPPoE session drops. `freedom-qos-toggle.sh` detects `outside_freedom` IP unassigned, sends **DOWN SMS** (received Thu 01:08 CEST), applies 5/2 Mbps tenant QoS. |
| **Apr 9 ~06:00** | Freedom PPPoE **recovers**. ASA syslog shows `Built` NAT translations via `outside_freedom` resume at full volume (~41,000/hour, up from ~1,500 during outage). |
| **Apr 9 06:00 → Apr 10 09:31** | **freedom-qos-toggle.sh bug:** `check_freedom()` fails silently on every 2-minute cron run (~810 executions). SSH to ASA returns empty string (not "UP", not "DOWN"). State file stays at `qos-active`. Tenants throttled to 5/2 Mbps for **27 extra hours** despite Freedom being operational. |
| **Apr 10 09:31** | NL ASA weekly EEM reboot. Fresh ASA accepts SSH. |
| **Apr 10 09:34** | `check_freedom()` succeeds. **RECOVERED SMS** sent (received Fri 11:34 CEST). QoS removed. |

**Root cause of 27-hour SMS gap:** When `check_freedom()` SSH fails, it returns empty string. The main logic only matches `"DOWN"` or `"UP"` — empty triggers neither branch. State stays stale indefinitely. Fixed by adding a ping fallback to the Freedom BNG (198.51.100.X) when SSH fails.

---

## Root Cause Analysis

### Primary: Matrix Synapse Process Freeze (~20 hours)

The Synapse homeserver (Docker container on nl-matrix01, LXC VMID_REDACTED on nl-pve01) became unresponsive while the container itself continued running.

**Evidence:**
- Synapse Docker container never restarted (started 2026-04-07T02:02:06, continuously "Up 3 days")
- **Docker logs are completely empty** for the entire outage period — Synapse produced zero output
- No OOM kills recorded in PVE01 host syslog
- No container restart events in PVE01 syslog
- Current resource usage is moderate: Synapse 173MB/1.5GB (11%), Postgres 237MB/512MB (46%), disk 41%
- The HTTP 429 rate-limiting error at 15:12 UTC was the first sign — a burst of alerts overwhelmed Synapse's rate limiter, and the process subsequently froze

**Probable mechanism:** Synapse entered a deadlock or connection pool exhaustion state. The burst of 6+ simultaneous "Service up/down" alerts from the 14:02 VTI wave saturated Synapse's request pipeline. Once rate-limited, the bot retried, creating a feedback loop. Synapse's event processing stalled, leading to a full process freeze. The container kept running, health checks (if any) passed at the Docker level, but no TCP connections were being accepted.

**Recovery:** Self-resolved at ~11:56 UTC on Apr 10 — likely an internal timeout or watchdog cleared the stuck state. No manual intervention was observed (no terminal session logs on the Matrix host or PVE01).

### Secondary: Freedom VTI ESP Dataplane Failure (IFRNLLEI01PRD-440)

The 3 Freedom-sourced VTI tunnels on nl-fw01 (Tunnel4/5/6) negotiate IKEv2 SAs successfully but the ESP dataplane does not pass traffic.

**Evidence:**
- Cross-site connectivity failures starting Apr 8 23:17
- Recurring cascading effects: PVE metric delivery timeouts to nlinfluxdb01, PBS connection failures to grpbs02, corosync quorum loss
- Three distinct waves of "Service up/down" alerts (Apr 8 23:18, Apr 9 14:02, Apr 10 11:56)
- xs4all backup tunnels provide partial failover but are insufficient for full cross-site traffic

**Resolved (2026-04-10).** Freedom ESP self-healed after ASA reboot + SA renegotiation. RPF on `outside_xs4all` also fixed. Additionally, VPS FRR `update-source` for NL RR peers changed from loopback to VTI /31 tunnel IPs to fix ASA BGP next-hop resolution — VPS loopback IPs (10.255.X.X, 10.255.X.X) now fully routable. IFRNLLEI01PRD-440 closed.

### Contributing: Alert Delivery Has No Retry/Queue

When Matrix is unreachable, alert workflow executions fail at the "Post Alert to Matrix" node and the alert is **silently dropped**. There is no:
- Retry queue with exponential backoff
- Alternative notification channel (e.g., email, Mattermost, ntfy)
- Dead-letter log of failed deliveries
- Health check that detects Matrix is down and activates fallback

This turned a 20-hour Matrix outage into a 20-hour **blind spot** where 50+ alerts fired but zero were visible to the operator.

---

## Impact

| Category | Impact |
|----------|--------|
| **Alert delivery** | ~20 hours of silent alert drops. Estimated 50+ alerts fired but never delivered. |
| **Cross-site connectivity** | Intermittent (3 waves). PBS backups, InfluxDB metrics, corosync cluster communication affected. |
| **Operator visibility** | Complete loss of visibility into infrastructure state from Apr 9 ~16:00 to Apr 10 ~11:56. |
| **Data loss** | None. Alerts were logged in LibreNMS/YouTrack. SNMP/metrics collection continued. |
| **Service availability** | All services remained operational. Matrix was the only user-facing service affected. |

---

## What Went Well

1. **Internet connectivity never failed** — both Freedom and xs4all WAN links remained operational throughout. The SLA failover mechanism was not needed.
2. **xs4all VTI tunnels** provided automatic failover when Freedom tunnels dropped.
3. **LibreNMS continued polling** — no monitoring gaps. Alert history is complete.
4. **YouTrack issues were created** for all alert waves, preserving the audit trail.
5. **Matrix self-recovered** without manual intervention.
6. **Freedom PPPoE SMS alert fired correctly** on the DOWN transition (Thu 01:08 CEST).

## What Went Poorly

1. **20 hours of silent alert drops** — no operator knew alerts were not being delivered.
2. **No Matrix health monitoring** — no alert fires when the Matrix homeserver is unreachable.
3. **No fallback notification channel** — Matrix is a single point of failure for operator notifications.
4. **Synapse produced zero diagnostic output** during the freeze — made post-mortem analysis difficult.
5. **Corosync instability went unnoticed** due to Matrix being down when it happened.
6. **Freedom QoS toggle stuck for 27 hours** — SSH failure in `check_freedom()` returned empty string, silently skipping both UP and DOWN branches. Tenants throttled unnecessarily.
7. **ASA weekly reboot compounded the outage** — the EEM reboot at 09:31 UTC triggered a third alert wave and broke cross-site tunnels (4/5 subnet pairs failed post-reboot VPN check).

---

## Corrective Actions

### Immediate (P1)

| # | Action | Status |
|---|--------|--------|
| 1 | Investigate and resolve Freedom VTI ESP dataplane issue (IFRNLLEI01PRD-440) | **Done** (2026-04-10) — ESP self-healed, VPS iBGP update-source fixed |
| 2 | Fix Prometheus receiver code bug (`Cannot access 'now' before initialization`) — currently blocking all Prometheus alert delivery | Open |
| 3 | Disable ASA weekly EEM reboot on both ASAs — causes more disruption than it prevents | **Done** (2026-04-10) |
| 4 | Fix `freedom-qos-toggle.sh` silent SSH failure — add ping fallback to BNG when SSH fails | **Done** (2026-04-10) |

### Short-term (P2)

| # | Action | Status |
|---|--------|--------|
| 5 | Add Matrix health check to alert workflows — pre-flight HTTP GET before posting, with fallback to ntfy or Mattermost | Proposed |
| 6 | Add retry logic with exponential backoff to "Post Alert to Matrix" node | Proposed |
| 7 | Add a dead-letter table/log for failed alert deliveries | Proposed |
| 8 | Configure Synapse Docker container health check that validates TCP connections, not just container status | Proposed |

### Medium-term (P3)

| # | Action | Status |
|---|--------|--------|
| 9 | Investigate Synapse process freeze — check for known deadlock bugs, connection pool limits, and rate limiter configuration | Proposed |
| 10 | Set up Matrix homeserver monitoring in LibreNMS (HTTPS service check on port 443) | Proposed |
| 11 | Add a "watchdog" workflow that periodically posts a heartbeat to Matrix and alerts via alternative channel if delivery fails | Proposed |

---

## Appendix: Key Evidence

### Firewall Syslog (No WAN Issues)
- NL firewall (nl-fw01) Apr 9 log: 1,793,779,265 bytes of normal traffic. No interface state changes, PPPoE drops, or SLA failover events.
- GR firewall (gr-fw01) Apr 9 log: 2,068,840,436 bytes of normal traffic. Same — no WAN disruptions.
- Both outside_freedom and outside_xs4all show continuous NAT translations throughout the period.

### Matrix Container State
- Synapse started: 2026-04-07T02:02:06 (never restarted)
- Postgres started: 2026-04-07T02:02:06 (never restarted)
- Element-web started: 2026-04-07T14:18:27 (restarted ~12h after others, unrelated)
- Current Synapse memory: 173MB / 1.5GB (11%)
- Current Postgres memory: 237MB / 512MB (46%)
- Disk: 12GB used / 30GB total (41%)
- matrix-hookshot block I/O: 10.9GB read — notably high, potential contributor to resource contention

### n8n Workflow Execution Pattern
- Last successful NL delivery: execution 148421 @ ~15:52 UTC Apr 9
- Last successful GR delivery: execution 147955 @ ~15:08 UTC Apr 9
- First failure: execution 148008 @ ~15:12 UTC Apr 9 (HTTP 429)
- All subsequent failures: ECONNRESET / "socket hang up"
- First successful post-recovery: execution 151892 @ ~11:56 UTC Apr 10

### Freedom PPPoE Traffic Analysis (Apr 9, `Built` connections via outside_freedom per hour)
```
00: 95,463 (Freedom drops mid-hour ~23:08 UTC Apr 8)
01:  6,421 (sharp drop — PPPoE down)
02:  1,615 (minimal — ASA SLA probes only)
03:  1,623   04: 1,468   05: 1,610
06: 41,705 (FREEDOM RECOVERS — real traffic resumes)
07: 26,752   08: 19,333   ... normal through end of day
```
Freedom was down ~7 hours (23:08 UTC Apr 8 → ~06:00 UTC Apr 9). Recovery SMS was 27 hours late due to `check_freedom()` SSH failure bug.

### ASA Weekly Reboot (Removed)
- NL ASA EEM watchdog (`event timer watchdog time 604800`) rebooted at ~09:31 UTC Apr 10
- Post-reboot VPN check: 4/5 subnet pairs FAILED (3 attempts, could not SSH to ASA)
- Only xs4all tunnels recovered; Freedom tunnels stayed broken (IFRNLLEI01PRD-440)
- **Corrective action:** EEM `weekly-reboot` applet removed from both ASAs. `asa-reboot-watch.sh` cron disabled.

### YouTrack Issues Created During Incident
- IFRNLLEI01PRD-387, 396, 397, 398, 438, 439, 440
- IFRGRSKG01PRD-168, 172, 173
