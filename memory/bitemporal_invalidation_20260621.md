---
name: bitemporal_invalidation_20260621
description: I6/IFRNLLEI01PRD-1158 — bi-temporal edge invalidation infrastructure on infragraph; shadow-safe, live 2026-06-21
metadata:
  type: project
---

IFRNLLEI01PRD-1158 (roadmap Stage-0 "I6"), infrastructure LIVE 2026-06-21 (migration applied, metrics emitting). **Shadow-safe: zero behavior change to the prediction/suppression path.**

**Shipped:** migration **019** (infragraph_dynamics += invalid_at, superseded_by, last_confirmation + idx_igd_invalid — note: 018 was taken by I2, so I6 is 019 not the map's "018"). lib/infragraph.py: `invalidate_edge()` (single invalid_at, first-writer-wins, records reason in openclaw_memory), `compute_confidence_with_decay()` (REPORTING-ONLY, 0.01/day, parses both _utcnow 'T..Z' and SQLite '.. ..'), `find_supersession_chain()` (cycle-safe + SUPERSEDE_MAX_DEPTH=5), `_temporal_health()` → health() now returns invalid_edges + decay_at_risk. write-infragraph-metrics.py: `infragraph_invalidated_edges` + `infragraph_decay_at_risk`. QA test-1158 6/6; all 6 existing infragraph suites still green.

**Two key design calls:**
1. **Decay is reporting-only** — it flags edges for RE-RATIFICATION (decay_at_risk count), never alters the confidence predictions/suppression use. QA has a guard asserting `compute_confidence_with_decay` is NOT referenced in expected_cascade/predict_action/apply_cascade_gating. Matches the issue's "decayed edges drop toward re-ratification, not auto-suppress." Live decay_at_risk=0 (daily reseed keeps last_validated fresh via the COALESCE fallback — no false-alarm flood).
2. **Did NOT wire the wiki-compile memory-vs-NetBox IP/site contradiction → invalidate_edge** (the map proposed it). A stale IP in a memory file is a weak, FP-prone signal for invalidating a dependency edge (e.g. "nl-claude01 runs_on nl-pve03"). `invalidate_edge()` ships ready, but the RIGHT trigger is cascade-refutation from -1118 learning (an edge whose predicted cascade never fires across N chaos runs), which composes with the cascade-stats work — left as a follow-up, NOT auto-wired. So invalid_edges stays 0 until a sound trigger is added.

**Deferred (operator-gated):** the auto-invalidation trigger + an `INFRAGRAPH_BITEMPORAL_INVALIDATE`-gated path; last_confirmation explicit stamping in stamp_seed/learn (currently COALESCEs to last_validated, which is sufficient). Part of roadmap batch — see [[watchdog_deadman_20260621]], [[governance_metrics_20260621]], [[synthetic_canary_20260621]]. Remaining: I8/-1159 GEPA.
