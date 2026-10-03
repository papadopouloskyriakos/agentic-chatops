---
name: synthetic_canary_20260621
description: I3/IFRNLLEI01PRD-1154 — synthetic-incident canary probing the classify→predict spine via an isolated DB; live 2026-06-21
metadata:
  type: project
---

IFRNLLEI01PRD-1154 (roadmap Stage-0 "I3"), LIVE 2026-06-21 on nl-claude01 (cron `37 2 * * *`, enabled after proving zero side-effects).

**Shipped:** `scripts/synthetic-incident-canary.sh` runs the autonomy spine — `classify-session-risk.py` → `infragraph-predict-plan.py` — and asserts each stage emits its artifact (classify: band + plan_hash + a session_risk_audit row; predict: plan_hash + gate; verify: coherent plan_hash across both). Emits `synthetic_incident_canary_stage_ok{stage}`, `_stages_passed` (0-3), `_live_db_leak`, `_last_run_timestamp`. holistic-health §38 `synthetic-canary` guard. QA `test-1154` 5/5. Runbook `docs/runbooks/synthetic-incident-canary.md`. 4 Prometheus alerts folded into IaC MR !336 (`SyntheticCanaryLeak` tier1-SMS, `SyntheticCanaryFailing`/`SyntheticCanaryStale` warning, + `GovernanceMetricsStale` for I2).

**The safety design (the synthesis's #1 risk was prod-pollution / tripping real remediation):** the map proposed a 600-line script POSTing synthetic alerts THROUGH n8n — rejected. Instead the spine runs against an **isolated throwaway DB** (`GATEWAY_DB=$(mktemp)` seeded from schema.sql, `trap cleanup EXIT`). This structurally kills all three top risks: can't write the real session_risk_audit/infragraph_predictions (pollution), can't collide plan_hash with a real in-flight session's fail-closed gate (the temp db is private), can't trigger real remediation (no n8n, read-only plan with no awx_templates). Verified live: **3/3 stages pass, live session_risk_audit unchanged 56→56, 0 canary rows, 0 leftover temp dbs.** A belt-and-suspenders `_live_db_leak` gauge + tier1-SMS `SyntheticCanaryLeak` alert page if isolation ever regresses.

**Interfaces used:** classify-session-risk.py `--plan <file>`/stdin + `--issue-id` + honors `GATEWAY_DB`; emits `{plan_hash,band,risk_level,...}` (line 786). infragraph-predict-plan.py reads plan via stdin + `--db` + `--issue`; always emits `{plan_hash, gate,...}` (gate=`not-applicable-readonly` for a read-only plan). plan fields classify reads: hostname/summary/steps/tools_needed/awx_templates/draft_reply.

**Coverage note:** this probes the SCRIPT spine (where empty-plan/no-band/gate-logic bugs live), not the n8n-node layer (lost expr-mode, Buffer-in-sandbox) — that's covered by [[watchdog_deadman_20260621]] (I1, workflows-active) + real alert volume. Part of roadmap batch. Cancelled I5/I7, deferred I4. Remaining: I6/-1158, I8/-1159.
