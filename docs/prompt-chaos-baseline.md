# Chaos Engineering Baseline Implementation

## Resume prompt for next Claude Code session

You are continuing work on the chaos engineering system in `/app/claude-gateway`. A prior session audited the chaos system, fixed 9 security/reliability findings, removed dead code, and created 13 YouTrack issues (IFRNLLEI01PRD-468 through -480) for establishing quantitative baselines. Your job is to implement all of them and run real E2E baseline tests.

## What was already done (don't redo)

- `scripts/lib/asa_ssh.py` — shared ASA SSH module (get_asa_password, ssh_nl/gr_asa_command/config, ssh_vps_swanctl, ssh_host_reachable, ssh_oob_reachable)
- `scripts/chaos-test.py` — refactored: imports shared module, state in `~/chaos-state/` (0700/0600), dead-man PID tracking + _kill_deadman() + _deadman_alive(), post-recovery verification, pre-flight SSH check, maintenance mode block, Prometheus chaos_test.prom metrics. SCENARIOS dict removed (frontend uses toggle-dot free-form selection only).
- `scripts/chaos-logs.py`, `scripts/vpn-mesh-stats.py` — refactored to use shared module
- `scripts/chaos-orphan-recovery.sh` — @reboot cron for orphaned state recovery
- Shell scripts — hardcoded passwords removed from freedom-qos-toggle.sh, vti-freedom-recovery.sh, holistic-agentic-health.sh
- Website repo (`/app/websites/papadopoulos.tech/kyriakos`) — DMZ link auto-selects child service dots, chaos star background transition, dead scenario code removed from chaos.js

## Implementation order (13 issues, 5 phases)

### Phase 1: Harness (build before testing) — IFRNLLEI01PRD-468, -469, -470, -477

**-468: Steady-state snapshot script.** Create `scripts/chaos-baseline.py` with `snapshot_steady_state()` that captures in parallel (ThreadPoolExecutor):
- VPN: tunnel count + status from mesh-stats API, BGP peer count from ASA `show bgp summary`
- Latency: cross-site ping per pair from ASA ping via VTI endpoints
- HTTP: 200 response + latency for 5 domains (portfolio, cubeos, meshsat, mulecube, hub.meshsat.net) via curl from nl-claude01
- Containers: running count per DMZ host via `docker ps` SSH
- Monitoring: active LibreNMS alert count (both NL+GR APIs), Prometheus target health
- BGP: route count from ASA `show bgp rib-count`
Output: JSON dict with timestamp + all metrics. Must complete within 30s. Must be importable (`from chaos_baseline import snapshot_steady_state`).

**-469: Experiment journal schema.** Create `chaos_experiments` table in gateway.db (`~/gitlab/products/cubeos/claude-context/gateway.db`):
```sql
CREATE TABLE chaos_experiments (
  id INTEGER PRIMARY KEY,
  experiment_id TEXT UNIQUE,           -- chaos-YYYY-MM-DD-NNN
  chaos_type TEXT,                     -- tunnel, dmz, combined
  targets TEXT,                        -- JSON: tunnels + containers killed
  hypothesis TEXT,                     -- what we expect to happen
  pre_state TEXT,                      -- JSON: snapshot_steady_state() before
  post_state TEXT,                     -- JSON: snapshot_steady_state() after
  events TEXT,                         -- JSON: timestamped event log
  expected_alerts TEXT,                -- JSON: alerts we expect to fire
  unexpected_alerts TEXT,              -- JSON: alerts that fired but weren't expected
  convergence_seconds REAL,            -- measured failover time
  recovery_seconds REAL,              -- measured recovery time
  verdict TEXT,                        -- PASS/FAIL/DEGRADED
  verdict_details TEXT,                -- JSON: per-metric pass/fail breakdown
  error_budget_consumed_pct REAL,      -- SLO impact
  triggered_by TEXT,                   -- visitor/baseline/scheduled
  started_at TEXT,
  recovered_at TEXT,
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
```

**-470: Alert suppression protocol.** Three layers:
1. Prometheus: before chaos start, POST to Alertmanager silence API (http://10.0.X.X:9093/api/v2/silences) with matchers for the specific tunnel/host. Store silence IDs in chaos-active.json. Delete on recovery.
2. LibreNMS: call `PUT /api/v0/devices/{hostname}/maintenance` on affected devices (nl-fw01, gr-fw01, DMZ hosts). Uses existing API keys in vpn-mesh-stats.py (LIBRENMS_NL_KEY, LIBRENMS_GR_KEY).
3. n8n receivers: add chaos state check at the top of all 4 alert receiver workflows (LibreNMS NL/GR, Prometheus NL/GR). If `~/chaos-state/chaos-active.json` exists, compare alert source against killed targets — suppress expected, pass through unexpected with `chaos-induced` tag.

For layer 3, read the receiver workflows first to understand the exact node structure. The check should go right after the webhook trigger, before any triage logic.

**-477: Wire into chaos-test.py.** Modify `cmd_start` to call `snapshot_steady_state()` before killing, store as `pre_state` in chaos-active.json. Modify `cmd_recover` to call `snapshot_steady_state()` after recovery, compare against pre_state, compute verdict (per-metric pass/fail), write experiment journal row to SQLite. Add `hypothesis` field derived from targets (e.g., "Killing NL↔GR xs4all: expect BGP failover via Freedom VTI within 30s, zero HTTP 5xx on all domains"). The hypothesis text and expected convergence times come from the baseline data once established — initially use conservative defaults (90s tunnel, 300s DNS, 30s recovery).

### Phase 2: Single-target baselines (run real tests) — IFRNLLEI01PRD-471, -472, -473

**IMPORTANT: These are real infrastructure tests. Run them one at a time with at least 15 minutes between tests (rate limit + BGP convergence buffer). Run during European daytime hours only.**

**-471: 5 tunnel baselines.** For each of the 5 CHAOS_TUNNELS entries, run:
1. Snapshot pre-state
2. Create Prometheus silence + LibreNMS maintenance
3. Kill tunnel via chaos-test.py (use CHAOS_SKIP_TURNSTILE=true, or call _cmd_start_locked directly)
4. Measure: continuous ping through alternate path (1s interval), BGP peer state polling (5s interval), HTTP checks on all 5 domains (5s interval)
5. Wait for dead-man recovery (use 120s duration, not 600s — baseline tests should be short)
6. Snapshot post-state
7. Record: detection_time (when ping loss started), convergence_time (when alternate path established), recovery_time (tunnel back up), domain_impact (any HTTP failures?)
8. Write journal entry to chaos_experiments table
9. Delete Prometheus silence + LibreNMS maintenance

Expected results to validate:
- A1 (NL↔GR xs4all): Freedom backup must be UP. Failover < 30s. Zero domain impact.
- A2 (NL↔NO xs4all): Freedom backup. Failover < 30s. NO VPS services unaffected.
- A3 (NL↔CH xs4all): Freedom backup. Failover < 30s. CH VPS services unaffected.
- A4 (GR↔NO inalan): NL transit. Failover < 45s (longer — transit path).
- A5 (GR↔CH inalan): NL transit. Failover < 45s.

**-472: 2 DMZ link-kill baselines.** For each DMZ host:
1. Same pre/post snapshot protocol as -471
2. NIC disconnect via Proxmox `qm set link_down=1`
3. Measure: HTTP checks on all 4 domains from external perspective (curl from nl-claude01 AND from a VPS if possible), DNS resolution timing
4. Key question: does DNS failover actually work? Or do both A records point to both sites with no health check?
5. Record: time to first HTTP failure, time to DNS failover (if any), time to full recovery after NIC reconnect

**-473: 8 service container baselines.** For each of the 4 containers on each of the 2 DMZ hosts:
1. `docker compose stop {container}` on one host
2. Measure: HTTP check on that domain from both sites
3. Record: does the other site serve traffic immediately? Or is there a gap?
4. `docker compose start {container}` to recover

### Phase 3: Multi-target baselines — IFRNLLEI01PRD-474, -475

**-474: 6 tunnel combinations.** The valid pairs (from safety calculator):
1. NL↔NO + GR↔NO (isolate NO via CH)
2. NL↔CH + GR↔CH (isolate CH via NO)
3. NL↔GR + GR↔NO (GR via CH transit)
4. NL↔GR + GR↔CH (GR via NO transit)
5. NL↔NO + NL↔CH (NL loses transit, keeps GR direct)
6. GR↔NO + GR↔CH (GR loses transit, keeps NL direct)

**-475: 2 combined tests.** Tunnel kill + DMZ NIC disconnect simultaneously. Worst-case scenarios.

### Phase 4: Validation — IFRNLLEI01PRD-476, -478

**-476: Alert pipeline validation.** After running baseline tests, verify:
- Expected alerts were suppressed (check LibreNMS + Prometheus history)
- No false YT issues created during chaos tests
- Unexpected alerts (if any) were passed through correctly

**-478: Portfolio frontend update.** With baseline data established:
- When visitor hovers a toggle dot, show expected behavior: "NL↔GR kill: BGP failover via Freedom VTI, ~25s convergence, zero domain impact"
- After test completes, summary panel shows: "Expected: 30s failover. Actual: 22s. PASS."
- Update the portfolio website repo chaos.js to fetch baseline data from a new API endpoint

### Phase 5: SLO maturity — IFRNLLEI01PRD-479, -480

**-479: SLOs.** Define per-domain availability SLOs (e.g., 99.9% monthly). After each experiment, calculate error budget consumed. Store in chaos_experiments table.

**-480: Grafana dashboard.** Query chaos_experiments table. Panels: experiment history timeline, convergence time trends per target, pass/fail ratio, error budget burn-down, unexpected findings log.

## Key technical references

- Shared ASA SSH module: `scripts/lib/asa_ssh.py` (import get_asa_password, ssh_nl_asa_command, etc.)
- Chaos state: `~/chaos-state/chaos-active.json` (0600 perms)
- Gateway DB: `~/gitlab/products/cubeos/claude-context/gateway.db`
- Mesh stats API: `scripts/vpn-mesh-stats.py` (Prometheus at http://10.0.X.X:30090, LibreNMS NL/GR APIs)
- Prometheus Alertmanager: http://10.0.X.X:9093 (silence API: POST /api/v2/silences)
- LibreNMS NL API key: REDACTED_LIBRENMS_NL_KEY
- LibreNMS GR API key: REDACTED_LIBRENMS_GR_KEY
- Alert receivers: LibreNMS NL (Ids38SbH48q4JdLN), GR (HI9UkcxNDxx6MEFD), Prometheus NL (CqrN7hNiJsATcJGE), GR (bdAYIiLh5vVyMDW7)
- DMZ hosts: nl-dmz01 (NL, VMID VMID_REDACTED on nl-pve01), gr-dmz01 (GR, VMID 201121301 on gr-pve01)
- Website repo: `/app/websites/papadopoulos.tech/kyriakos` (push to main, CI deploys)
- NEVER modify OOB systems without explicit approval
- NEVER clear bgp or restart FRR on VPS
- ALL K8s changes via OpenTofu + Atlantis MR
- Push directly to main on claude-gateway and website repos

## Industry context (from research)

This work moves the chaos system from Netflix CMM Level 2 (Moderate) to Level 3 (Advanced). The key gaps being closed: automated steady-state hypothesis, pre/post metric comparison, experiment journaling, alert suppression, and SLO integration. Reference: principlesofchaos.org, Google DiRT, Shopify BFCM Readiness pattern, ChaosEater (NTT ASE 2025).

## Verification

After all phases complete:
1. `chaos_experiments` table has 21+ rows with real baseline data
2. Every experiment has pre_state, post_state, convergence_seconds, verdict
3. Prometheus silences created/deleted cleanly during tests
4. No false YT issues or Matrix alerts during baseline tests
5. Portfolio frontend shows expected behavior per selection
6. Grafana dashboard renders experiment history
7. `grep -rn` for the ASA password in `scripts/` still returns zero (no credential regression)
