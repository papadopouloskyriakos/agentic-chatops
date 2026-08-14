# Plane-A Platform Controller — the orchestrator's self-healing operator

**Status:** LIVE + ARMED (2026-06-26). `scripts/platform-controller.py`, a `*/5` Cronicle job.
**Lineage:** IFRNLLEI01PRD-1421 extension. Gateway MRs !70 (build) + !71 (watchdog consolidation), infra MR !351 (alerts).
**Build narrative / decisions:** [`memory/platform_controller_20260626.md`](../../memory/platform_controller_20260626.md).

The orchestrator control-plane has two halves. The **3 bricks** (registry / interaction-graph / orchestration-benchmark) **observe**. This controller **acts** — it is the actuator. A k8s-style reconcile loop that keeps the agentic platform alive and self-healing, so a human no longer has to administer it.

---

## The load-bearing scope boundary: Plane A vs Plane B

| | Plane A — what the controller does | Plane B — what it NEVER touches |
|---|---|---|
| Meaning | Keep the **platform's own components** alive (crons/Cronicle, the bricks, metric-writers, n8n workflows) | The platform's **mission** (resize a VM, reboot a host, auto-resolve an incident) |
| Owner | This controller | The autonomy-forward gate + the fail-closed infragraph prediction gate (+ a human for irreversibles) |

The k8s analogy is exact: **Kubernetes keeps your pods alive; it never decides your app's business logic.** Same here. The moment "healing" would mean replaying a non-idempotent job or making an infra decision, that is Plane B and the controller hands off (escalates) rather than reaches in.

---

## What it heals

**3 native heal classes** (reconciled every run):
1. **n8n critical workflow inactive → reactivate.** Monitors **all 58** workflows; reactivates only the 8 critical pipeline workflows if found inactive (non-critical active-state is operator intent — left alone).
2. **Failed SAFE-LIST gateway Cronicle job → re-run.** Only idempotent regenerators (`SAFE_RERUN_HINTS`: metric-writers `*-metrics.*` + the orchestrator bricks). Matched by job title OR embedded script path. **Never** agora/trading jobs or non-safe gateway jobs (idempotency unknown → those escalate).
3. **Cronicle scheduler down → restart** the service.

**Plus the watchdog heal-library** (always-on): the controller calls `gateway-watchdog.sh --heals-only`, which runs the proven, battle-tested heals — **n8n auto-restart** (SSH `pct exec` to the n8n LXC, 15-min backoff), **Matrix-Bridge bounce** (every 6h + on recent error), **zombie-execution cleanup** (>1h queued/running), **stale per-slot lock cleanup**. These were kept in bash rather than risk a Python rewrite of load-bearing logic.

---

## Oversight vs control over the scheduler — the honest boundary

**Oversight — effectively complete:** per-job run history + exit codes for all ~176 Cronicle jobs, a **failed job is named** (`registry_component_dark{name=…}`), every run + its failure logs ship to OpenObserve (searchable), plus the scheduler's own liveness alerts (`CronicleSchedulerDown` / `JobsFailing` / `MetricsStale`) and a dead-man.

**Control — substantial but deliberately bounded (NOT "complete"):**

| The controller CAN | The controller deliberately CANNOT |
|---|---|
| Quarantine a chronic-failer (disable a job failing ≥3× — via `cronicle-remediate.py`) | Re-run arbitrary / non-idempotent jobs (agora, alert-senders) → **escalates** instead |
| Re-run a failed **idempotent safe-list** job | Create / delete / reschedule jobs or change timing |
| Restart the scheduler if down | Fix a job's **root-cause bug** — it re-runs ≤3× then **escalates to a human** (CrashLoopBackOff) |

The bound is the safety design (idempotency + the Plane-A/B line), **not** a missing feature. "Complete oversight + bounded, safe, self-escalating control" is the accurate description.

---

## Guardrails (k8s-style)

- **Heal cap → CrashLoopBackOff → escalate.** Per-target cap `PLATFORM_HEAL_CAP` (default **3/hour**). On the 4th attempt the controller stops healing that target and raises `platform_controller_escalations` → a tier-1 alert → **SMS**. It never thrashes.
- **Maintenance mode.** When `~/gateway.maintenance` exists, all heals are suppressed (don't fight a planned change) but the **dead-man heartbeat is still emitted** (`emit(heartbeat_only=True)`), so the platform-dark alert can't false-fire.

---

## Arming / killing (ships dark)

```bash
touch ~/gateway.platform_controller_armed   # ARM — actually heal (currently ARMED)
rm    ~/gateway.platform_controller_armed   # KILL — instant analysis-only (flags candidates, takes no action)
```

Default (sentinel absent) = **analysis-only**: it monitors and flags `platform_controller_candidates` + audits what it *would* heal, but takes no action.

---

## The dead-man (consolidated from gateway-watchdog)

The controller **is** the platform's dead-man's-switch (the watchdog was consolidated into it — see below). It emits, in `platform_controller.prom`:

| Metric | Meaning |
|---|---|
| `gateway_watchdog_heartbeat_timestamp_seconds{host}` | heartbeat (IFRNLLEI01PRD-1152 guarantee, taken over from the watchdog) |
| `gateway_n8n_healthy` | 1 if the n8n API answered |
| `gateway_workflow_active{workflow}` | per critical workflow, 1 active / 0 inactive |
| `platform_controller_{armed,candidates,healed_total,escalations,n8n_workflows_total,last_run_timestamp_seconds}` | the controller's own state |

It is registered **`prom:platform_controller` = CRITICAL**, so if the healer itself goes dark, `RegistryCriticalDark` pages.

---

## Watchdog consolidation (one operator, not two)

The controller is the **single Plane-A operator**. The cutover (gateway MR !71, done atomically + live-verified):

- `gateway-watchdog.sh` gained a **`--heals-only`** mode (skips its metrics-trap + Layer-1 reactivation, which the controller now owns). The controller calls it as a heal-library every run.
- The watchdog's **standalone Cronicle job `emqurqydu5t` is DISABLED** (not deleted — that IS the rollback path).
- The dead-man metrics moved to the controller with **no duplicate** (`node_textfile_scrape_error=0`) and **no gap** (heartbeat stayed fresh; `GatewayWatchdogHeartbeatStale` + `GatewayWorkflowInactive` stayed inactive).
- `prom:gateway_watchdog` retired (known-dark); `registry-curate`'s critical flag is now authoritative (clears on removal, so a retired component can't linger as a false critical-dark).
- The orphaned deployed copy `/home/app-user/scripts/gateway-watchdog.sh` was deleted; its `watchdog-state/` dir is **kept** (the live `--heals-only` calls use it).

---

## Alerts (infra MR !351)

- **`PlatformControllerEscalation`** (`platform_controller_escalations > 0`, tier-1 → SMS) — a heal won't take; a human is needed (the exception to "relieves you of admin").
- **`PlatformControllerStale`** (absent-guarded, tier-1 → SMS) — the healer itself is down ⇒ nothing self-heals.
- Plus the dead-man via `RegistryCriticalDark` on `prom:platform_controller`.

---

## Where to look

| | |
|---|---|
| Audit log | `~/logs/claude-gateway/platform-controller.log` |
| Decisions (structured) | OpenObserve `orchestrator` stream, `source=platform-controller` |
| Heal-cap state | `~/gateway-state/platform-controller-heals.json` |
| Metrics | `/var/lib/node_exporter/textfile_collector/platform_controller.prom` |

---

## Rollback

- **Disarm only:** `rm ~/gateway.platform_controller_armed` → analysis-only (keeps monitoring + the dead-man, stops acting).
- **Full revert of the consolidation:** re-enable Cronicle event `emqurqydu5t` (`gateway-watchdog.sh` resumes standalone) **and** revert gateway MR !71.

---

## Troubleshooting

- **A job keeps escalating (SMS):** it's failing >3×/hr and the controller can't fix the root cause — that's by design. Find the job in the audit log (`grep ESCALATE`), fix the underlying bug, and the escalation stops. Re-running is symptom-level only.
- **`PlatformControllerStale` / dead-man SMS:** the controller hasn't run in 30m+. Check the `platform-controller.py` Cronicle event is enabled and `systemctl status cronicle`.
- **Duplicate `gateway_watchdog_heartbeat` / `node_textfile_scrape_error=1`:** something re-enabled the watchdog standalone job (`emqurqydu5t`) while the controller also emits the heartbeat. Disable the watchdog job again — only one emitter is allowed.
- **An idempotent writer stays dark but isn't re-run:** confirm its title/path matches `SAFE_RERUN_HINTS`; only safe-list jobs are auto-re-run by design.
