# Orchestration Control-Plane — First Governance Report (2026-06-26)

The 3-brick orchestrator (IFRNLLEI01PRD-1421) is built, deployed, and alerting live. This is its
**first governance output** — the agentic federation seen through the control-plane lens. All
figures are mechanically derived (re-run the bricks to refresh); nothing here is hand-counted.

## The federation, inventoried (Brick 1 — `config/component-registry.json`)

**233 components**: 97 cron · 56 n8n-workflow · 53 prom-writer · 27 db-table.
- **9 critical** (must be fresh; all currently fresh = 0 false-fire): the self-audit tier
  (holistic_health, self_audit), the dead-man's watchdog, the Runner + Poller, and the core
  session-analytics writers (session_metrics, agent_metrics, handoff_depth) + the registry itself.
- **35 known_dark** (dormant by design): inactive n8n workflows, retired tables (a2a_task_log,
  credential_usage_log, execution_log, features, work_units), and event-driven chaos outputs.
- **2 genuinely stale, informational**: `prom:chaos_exercise` (event-driven, idle), `prom:kb_rag_eval`
  (3.9 d — a periodic eval, worth confirming its cadence is intentional).

`RegistryCriticalDark` (tier1) + `RegistryCheckStale` (absent-guarded) now fire if any of this
drifts — the dark-component failure class is mechanically caught, not found by quarterly audit.

## The interactions, mapped (Brick 2 — `config/interaction-graph.json`)

Static analysis of **238 scripts** (following sub-script + dynamic-table writes):

- **0 GAPs.** No registered table is read by a component but written by none. The Session-End→
  reconcile hole class (which silently darkened 4 analytics tables) is currently closed.
  `InteractionGraphGap` fires if one re-appears.
- **6 CRON-CLASHes** (same-minute slots; `0 4` has 5 jobs) — and **cross-referencing them against
  the write-map proves they are BENIGN**: same-minute crons write *disjoint* tables, so the clashes
  are resource-spike contention only, NOT a concurrent-write data race.
- **22 multi-writer CONFLICTs**, classified:
  - **7 append-only fan-in (safe)** — each writer inserts its own rows: `llm_usage` (12 writers, the
    documented 6-tier usage fan-in), `event_log`, `session_risk_audit`, `wiki_articles`,
    `lessons_learned`, `execution_log`, `graph_relationships`.
  - **15 update-in-place (coordination-review backlog)** — a writer does `UPDATE` on a shared table,
    so a same-key concurrent update *could* race in principle: `incident_knowledge` (8),
    `openclaw_memory` (6), `sessions` (4), `work_units` (4), `infragraph_predictions` (3),
    `agent_diary`/`crowdsec_scenario_stats`/`features`/`session_transcripts` (3 each), + 6 two-writer
    tables. **Actual race risk is low** (the cron-clash check shows no same-minute writers, and the
    `sessions` writers — hooks during a session vs reconcile after the PID exits — don't overlap),
    but these are the rows to give an explicit upsert/lock contract as the federation grows.

## The orchestration, scored (Brick 3 — `config/orchestration-scorecard.json`)

Replaying a 10-incident stream through the isolated spine — **score 1.0, invariants 4/4**:
- **I1 safety-composition PASS** — all 5 irreversible/destructive scenarios (mkfs, zpool destroy,
  dropdb, rm -rf, terraform destroy) were classified `POLL_PAUSE`, never `AUTO`. The never-auto floor
  holds across the *whole stream*, not just case-by-case. `OrchestrationSafetyFailure` (tier1) fires
  if it ever doesn't.
- **I2 determinism PASS** · **I3 completeness PASS** (every incident reaches a valid band + a
  prediction artifact) · **I4 structural-integrity PASS** (interaction-graph gaps == 0).

## Actionable backlog (for the operator)

1. Merge gateway MR !57 (the 3 bricks) — infra MRs !347/!348 already merged + verified in-cluster.
2. Confirm `kb_rag_eval`'s cadence is intentional (the one non-event-driven stale writer).
3. The 15 update-in-place tables: give the highest-fan-in ones (`incident_knowledge`, `openclaw_memory`,
   `sessions`) an explicit upsert/transaction contract — low urgency (no current race), but it
   removes the *possibility* before scale introduces it.
4. **Incremental brick growth** (research-recommended next): adopt self-hosted **Healthchecks.io**
   (Brick 1 ping-based "never ran" detection — the one `absent()` can still miss) and **Langfuse**
   (Brick 2 LLM/agent trace edges); grow the Brick 3 scenario catalog + add a full-pipeline (real LLM
   session) replay tier. These are service deploys — flagged for your awareness, not done unattended.
