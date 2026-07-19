---
name: watchdog_deadman_20260621
description: I1/IFRNLLEI01PRD-1152 — control-plane dead-man's-switch built by extending gateway-watchdog.sh; live+verified 2026-06-21
metadata:
  type: project
---

IFRNLLEI01PRD-1152 (roadmap Stage-0 "I1"), LIVE + verified 2026-06-21 on nl-claude01.

**What shipped:** the existing `scripts/gateway-watchdog.sh` (cron `*/5`, already watches 9 receivers + runner and auto-heals) now emits, via a `trap emit_metrics EXIT` (fires on *every* path — maintenance / n8n-down / normal / `set -e` abort), to `/var/lib/node_exporter/textfile_collector/gateway_watchdog.prom`:
- `gateway_watchdog_heartbeat_timestamp_seconds{host}` (the heartbeat)
- `gateway_n8n_healthy` (1/0), `gateway_workflow_active{workflow}` (1/0, recorded as-found pre-reactivation).

Two Prometheus alerts, `tier=1 + severity=critical` → **twilio-tier1 SMS** (the watchdog's own Matrix alerts are muted — [[feedback_operator_does_not_watch_matrix_polls]]): `GatewayWatchdogHeartbeatStale` = `(time()-hb>900) OR absent(hb)`, `for 5m`; `GatewayWorkflowInactive` = `min by(workflow)(gateway_workflow_active)==0`, `for 15m`.

**Key design points (why it's not a canary revival):** the retired receiver-canary (commit `2c4af83`) fired synthetic YT issues; this adds zero synthetic load — it passively records that the already-running watchdog executed and pages out-of-band when it stops. The **`absent()` clause is the crux**: a plain staleness expr returns no series when node_exporter/nl-claude01 is down → "no data = no alert" → the exact silent-dark gap I1 exists to kill. Alert must NOT be named `Watchdog` — `main.tf` black-holes `alertname=Watchdog` → `receiver=null`.

**Landmines caught during build (not in the surface map):**
1. The map proposed "write 2 new scripts" — but `gateway-watchdog.sh` already does workflow-liveness + n8n-health + auto-heal. Correct move was extend, not rewrite. The real gap was "who watches the watchdog" + "its alerts go to muted Matrix not SMS".
2. **Live-vs-repo drift, LIVE newer:** the deployed `~/scripts/gateway-watchdog.sh` (372 lines, 2026-04-01) had uncommitted improvements (persistent-zombie→bridge-bounce, maintenance-mode skip) the repo copy (335) lacked. Naively deploying the repo copy would have regressed prod. Reconciled repo←live first (backup `~/scripts/gateway-watchdog.sh.pre-i1-*`), then added the heartbeat on top.

**Deploy reality (two surfaces, two repos):**
- Script: cron runs `~/scripts/gateway-watchdog.sh` (NOT the repo path) — deployed by `cp` after test; repo copy is the committed mirror.
- Alerts: deployed truth is the **IaC repo** `infrastructure/nl/production/k8s/namespaces/monitoring/agentic-health-alerts.tf` (kubernetes_manifest PrometheusRule, Atlantis MR); `prometheus/alert-rules/agentic-health.yml` here is the doc/test copy. n8n API key for the watchdog comes from `~/.claude.json` `.mcpServers["n8n-mcp"].env.N8N_API_KEY` (not `.env`).

**Verified:** QA `test-1152-watchdog-deadman.sh` 7/7; holistic-health §38 `watchdog-deadman` PASS; live cron emitting (heartbeat fresh). Runbook: `docs/runbooks/gateway-watchdog-deadman.md`. Part of the roadmap batch — see also still-open I2/-1153, I3/-1154, I6/-1158, I8/-1159; cancelled I5/-1156, I7/-1157; deferred I4/-1155.
