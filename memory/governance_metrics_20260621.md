---
name: governance_metrics_20260621
description: I2/IFRNLLEI01PRD-1153 — false-auto-resolve + repeat-incident governance metrics; live 2026-06-21
metadata:
  type: project
---

IFRNLLEI01PRD-1153 (roadmap Stage-0 "I2"), core LIVE 2026-06-21 on nl-claude01.

**Shipped:** migration **018** (incident_knowledge += suppression_status/demotion_reason/demotion_at, idempotent ALTERs, applied live) + `scripts/write-governance-metrics.py` (cron `*/17`) emitting `chatops_false_auto_resolve_total{window="30d"}`, `chatops_repeat_incident_classes`, `chatops_governance_demote_candidates`, `chatops_governance_demoted_patterns_total`, `chatops_governance_metrics_last_run_timestamp`. holistic-health §38 `governance-metrics` freshness guard. QA `test-1153` 5/5 (incl. a deterministic recurrence-logic fixture).

**The non-obvious finding (data source):** recurrence is NOT computable from session_log (no host/rule) or incident_knowledge (only ~1/33 auto-resolves link by issue_id; auto-resolves are hostname='*' platform patterns like InfragraphPrecisionDrop). The alert-event source-of-truth is **triage.log** (`ts|host|rule|site|outcome|conf|dur|issue` at `~/gitlab/products/cubeos/claude-context/triage.log`), parsed via shared `lib.infragraph.parse_triage_log()`. Live read: **19 false-auto-resolves / 51 repeat classes / 45 demote-candidates (30d)**. Definition: auto-resolve outcome (resolved/-knownpattern/-active-memory, NOT dedup/escalated) whose (host,rule) recurs within 24h.

**Auto-demote is now DEFAULT-ON (autonomy-forward upgrade, same day).** Operator pushback: "why is reviewing 45 candidates + flipping a flag manual? — that's the gatekeeper anti-pattern this system rejects." Correct. Reworked to human-as-circuit-breaker: `GOVERNANCE_AUTODEMOTE` defaults `1`; a >=3x/30d genuine false-resolve (host,rule) is auto-demoted to `analysis_only` (reversible: 30-day valid_until expiry). Made safe-by-design:
- **Consumer wired** (`tier1_suppression.check_phase2_knownpattern`): a demoted (host,rule) returns `outcome=escalate` (governance_demoted signal) — STOP auto-resolving the repeat-offender, escalate for root-cause. Safe-direction only (never causes suppression). Live-verified: nl-pve03/Service up/down → escalate.
- **Excludes intentional known-transients** (the critical bug caught pre-merge): a deliberately-suppressed flappy pattern (e.g. ContainerOOMKilled, confidence 0.78, tag `transient,flap,self-resolved`) recurs BY DESIGN — demoting it would re-introduce suppressed noise. `is_intentionally_suppressed()` reuses tier1's `KNOWN_TRANSIENT_KEYWORDS`/`MIN_CONFIDENCE` to skip them. Live: 45 raw candidates → 6 transients excluded → **39 genuine demoted**.
- **RAG-safe**: demote rows are `project='chatops-governance'` + `confidence=-1` (invisible to tier1's transient matcher), and `kb-semantic-search` excludes that project from embed-backfill + retrieval (`COALESCE(project,'') != 'chatops-governance'`, 3 queries) → zero RAG pollution.
- **Circuit-breaker = the metric + weekly audit + 30-day auto-expiry, NOT manual review.** `GOVERNANCE_AUTODEMOTE=0` falls back to shadow (log candidates, don't act).
Lesson: [[feedback_operator_does_not_watch_matrix_polls]] applies to AUTO-RESOLVE governance too — don't put a manual gate on a reversible, safe-direction action.

**Schema-drift note caught here:** `incident_knowledge.valid_until` is LIVE-only (present in prod, absent from schema.sql + every migration — added out-of-band by the auto-resolve work). Production queries work; QA fixtures must ALTER-ADD it. Pre-existing; flagged for a future schema.sql reconciliation.

**DB-path landmine (resolved):** `~/gateway-state/gateway.db` is a symlink → `~/gitlab/products/cubeos/claude-context/gateway.db` (realpath confirms; identical schema_migrations 004-018). ONE db despite the `stat` inode confusion. apply.py + all writers use the cubeos path.

**Remaining (operator-gated / follow-up):** Grafana governance panel; a `GovernanceMetricsStale` Prometheus alert (IaC); flip `GOVERNANCE_AUTODEMOTE=1` after reviewing the 45 candidates; weekly audit-risk-decisions.sh surfacing of false-resolve count. Part of roadmap batch — see [[watchdog_deadman_20260621]] (I1).
