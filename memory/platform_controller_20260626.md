---
name: platform_controller_20260626
description: Plane-A platform controller — the agentic platform's k8s-style self-healing operator (the orchestrator's ACTUATOR half). Built+e2e-proven+LIVE (dark)+registered-critical+alerted 2026-06-26. Scoped STRICTLY to platform health, NEVER the mission. gateway MR !70 + infra MR !351.
metadata:
  node_type: memory
  type: project
  originSessionId: 446fe240-f009-4fd5-a87c-b8ecb446a101
---

**2026-06-26: built the Plane-A platform controller** — the orchestrator's ACTUATOR half. The 3 bricks (registry/interaction-graph/benchmark) only OBSERVE; the open loop's `act` step routed to a human who's been absent for months (= no loop = the dark-component failure class, one level up). Fix: close the loop with an AGENT controller.

## The Plane-A / Plane-B distinction (operator's sharp correction — load-bearing)
- **Plane A = keep the agentic PLATFORM alive** (its OWN components: crons/Cronicle/bricks/writers/n8n-workflows). The controller does THIS.
- **Plane B = the platform's MISSION** (resize a VM, reboot a host, auto-resolve an incident). The controller NEVER touches this — stays in the autonomy-forward / fail-closed-prediction lane.
- k8s analogy is TIGHT: k8s keeps PODS alive, never decides the APP's logic. Controller keeps platform COMPONENTS alive, never decides the agentic MISSION. (My first draft wrongly widened it to "agent replaces the human for remediation decisions" — operator corrected: the agent's job is keep-it-alive-and-kicking, NOT make task decisions. "human absent for months" = relieve the operator of ADMINISTERING the platform, SMS for emergencies only.)
- WHY the narrow scope is also SAFER: Plane-A heals are idempotent/reversible/low-blast (restart/re-run/reactivate — what k8s auto-does to a pod); Plane-B is irreversible/high-stakes (needs the prediction gate).

## What it is (`scripts/platform-controller.py`, gateway MR !70 `3121e47`)
k8s-style reconcile loop, 3 heal classes: (1) n8n CRITICAL workflows inactive → reactivate (monitors ALL 58); (2) failed SAFE-LIST gateway Cronicle jobs → re-run (covers bricks+metric-writers; SAFE_RERUN_HINTS = idempotent regenerators matched by title OR embedded path; agora/non-safe → escalate, never auto-rerun); (3) Cronicle scheduler down → restart. Uses `lib/cronicle` + `lib/obs_log`. n8n key read from holistic-agentic-health.sh.
- **k8s guardrails:** per-target heal cap=3/hr → CrashLoopBackOff → ESCALATE (`platform_controller_escalations` metric → tier1 alert → SMS). Never thrashes.
- **GATED, ships DARK:** `~/gateway.platform_controller_armed` ABSENT (default) = analysis-only (flags candidates via metric+audit, NO action); PRESENT = heals. Kill: `rm`. (NOT armed yet — operator's call, same as the quarantine.)
- Metrics → `platform_controller.prom`; decisions → OpenObserve `orchestrator` stream; audit → `~/logs/claude-gateway/platform-controller.log`.
- LIVE as a `*/5` Cronicle job. Registered **CRITICAL** (registry-curate `prom:platform_controller`) → its own dead-man via RegistryCriticalDark.

## E2E-PROVEN
A failing safe-list job (title `write-test-metrics.sh`): analysis-only FLAGGED it (no action) → armed re-ran it 3× (heal) → at cap ESCALATED ("will not self-heal → human needed"). Plus all 58 n8n monitored, 0 inactive-critical, 0 failed (platform healthy). Test-fixture bug found+fixed: matched safe-list vs script CONTENT (test job lacked a path) → now matches title OR cmd.

## Alerts (infra MR !351, Atlantis 0-destroy applied, loaded+inactive)
`PlatformControllerEscalation` (escalations>0, tier1 SMS — heal won't take, human needed) + `PlatformControllerStale` (absent-guarded, tier1 SMS — the healer itself is down = nothing self-heals).

## Watchdog consolidation — DONE + ARMED (gateway MR !71 `bec457b`, atomic cutover live 2026-06-26)
- **ARMED:** `touch ~/gateway.platform_controller_armed` (operator said arm it) → `platform_controller_armed 1`, healthy. Now actually self-heals. Kill: `rm`.
- **Consolidated (operator chose CONSOLIDATE):** controller is the SINGLE Plane-A operator. KEY DESIGN — did NOT rewrite the watchdog's battle-tested heals in Python (would risk the dead-man); instead gave `gateway-watchdog.sh` a **`--heals-only`** mode (skips metrics-trap + Layer-1 reactivation) and the controller **calls it as a heal-library** every run (always-on: n8n-restart / Bridge-bounce / zombie+lock cleanup stay in proven bash). Controller OWNS: the dead-man metrics (`gateway_watchdog_heartbeat{host}` + `gateway_n8n_healthy` + `gateway_workflow_active{workflow}` per critical, all in platform_controller.prom) + n8n reactivation + maintenance-honor (suppress heals, keep heartbeat alive via `emit(heartbeat_only=True)`).
- **ATOMIC CUTOVER (no-gap, no-duplicate):** disable watchdog Cronicle job `emqurqydu5t` (set_enabled false) → rm gateway_watchdog.prom → run controller (emits heartbeat solo). VERIFIED: heartbeat fresh in Prom (122s), `node_textfile_scrape_error=0` (NO duplicate), GatewayWatchdogHeartbeatStale + GatewayWorkflowInactive both inactive, registry 0 critical-dark.
- **Latent bug fixed:** registry-curate only ADDED critical, never cleared → a retired component lingered as false critical-dark. Now AUTHORITATIVE (clears critical when removed from the set). prom:gateway_watchdog → known_dark (retired); prom:platform_controller → the critical dead-man.
- **ROLLBACK:** re-enable Cronicle event `emqurqydu5t` + revert MR !71.
- **Orphan DELETED 2026-06-26:** stale pre-consolidation deployed copy `/home/app-user/scripts/gateway-watchdog.sh` removed after verifying 0 Cronicle / crontab / systemd refs to the deployed path (only `.claude` transcripts + memory mention it; the controller + the now-disabled job both use the REPO copy `/app/claude-gateway/scripts/gateway-watchdog.sh`). Backed up to scratchpad; repo copy is canonical in git. **STATE_DIR `~/scripts/watchdog-state/` KEPT** (still used by the live `--heals-only` calls). [[feedback_deployed_copy_not_repo_for_some_crons]]
- **FIRST LIVE self-heal (proof):** right after the delete, the armed controller caught `registry-check.py`'s failed last run (exit 1 from the brief `prom:gateway_watchdog` critical-dark window I caused mid-consolidation) and re-ran it UNPROMPTED → exit 0, 0 failed jobs. Real catch-and-heal, end to end.
- The watchdog Cronicle event `emqurqydu5t` is DISABLED not deleted (= the rollback path).

## DOCUMENTED (gateway MR !72 + !73)
- **Runbook:** [`docs/runbooks/platform-controller.md`](../../docs/runbooks/platform-controller.md) — scope boundary, 3 heal classes + `--heals-only` library, the honest **COMPLETE-oversight / BOUNDED-control** can/can't tables, guardrails, arm/disarm, dead-man, consolidation, alerts, rollback, troubleshooting.
- **CLAUDE.md:** runbook-pointer bullet after the orchestrator control-plane entry (bricks observe; this is the actuator), same honest framing.
- **Honest scope framing (operator asked "complete control?" — DON'T round up):** scheduler OVERSIGHT ≈ complete (per-job history + failure-naming + OpenObserve + alerts); CONTROL deliberately BOUNDED — quarantine / idempotent-safe-re-run / restart only. CANNOT (by design): re-run non-idempotent jobs (agora/alert-senders → escalate), create/delete/reschedule, or fix a job's root-cause bug (re-runs ≤3× → escalates = CrashLoopBackOff). The bound is the Plane-A/B safety line, not a gap.
- **Gotcha:** a python doc-insert anchor matched TWICE in CLAUDE.md → assert refused → !72 silently landed only the runbook, skipped the CLAUDE.md bullet; !73 fixed with the full unique anchor. Lesson: doc-insert anchors must be unique-verified (count==1) before commit. [[feedback_verify_agent_generated_doc_claims]]

[[orchestrator_control_plane_20260626]] [[cronicle_migration_20260626]] [[feedback_operator_out_of_loop_complete_dont_defer]]
