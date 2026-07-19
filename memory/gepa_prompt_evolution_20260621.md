---
name: gepa_prompt_evolution_20260621
description: I8/IFRNLLEI01PRD-1159 — GEPA reflective prompt-variant generator (claude -p), dormant-by-default; shipped 2026-06-21
metadata:
  type: project
---

IFRNLLEI01PRD-1159 (roadmap Stage-0 "I8"), shipped 2026-06-21 **DORMANT** (PROMPT_GEPA_ENABLED=0 default → existing hand-authored behavior, byte-identical legacy).

**What it is:** GEPA layered on the A/B patcher (-645) as the variant GENERATOR only. `scripts/lib/gepa_generator.py::evolve_candidates(dim, seed, n)` asks `claude -p` (NOT dspy, NOT the Anthropic SDK / API key — operator decision: "use claude -p as usual") to reflect on a seed instruction and propose N diverse mutated instruction lines (lenses: concise/detailed/worked-examples/formalize/caveats), parsed into Candidate objects. Wired into `prompt-patch-trial.py::candidates_for_dim()` (new) — used by cmd_start instead of `candidates_for` when the flag is on.

**Invariants (why safe to land):**
- GENERATE-ONLY: the Welch t-test + control arm in `finalize-prompt-trials.py` stays the SOLE promotion gate (unchanged; QA asserts it). GEPA never promotes — a bad variant just loses the A/B test.
- DORMANT: flag-off → `candidates_for_dim` returns the hand-authored 3 (QA-verified byte-identical).
- FAIL-SAFE: any failure (claude -p missing/timeout/garbled/thin output, <n diverse variants) → `evolve_candidates` returns None → caller falls back to hand-authored. QA stubs `_run_claude→None` and confirms fallback.
- No new deps, no API key.

**Reward-hacking guard:** `scripts/build-gepa-eval-set.py` extracts the contamination-free held-out set (sessions started < 2026-05-01) to `scripts/eval-sets/gepa-task-eval.jsonl`; enforces ≥20 before GEPA should be enabled. Live run found **194 eligible entries** (guard satisfied). The jsonl is a regenerable host artifact (not committed).

**QA test-1159 8/8; existing test-645 (patcher) still green.** Enable later via `PROMPT_GEPA_ENABLED=1` after wiring the held-out eval into finalize as an additional anti-hack check (follow-up; today the live Welch t-test on real sessions is the gate). Diversity scoring via nomic-embed (nl-gpu01) is a noted enhancement; current dedupe is normalized-text. Part of roadmap batch — final item. See [[bitemporal_invalidation_20260621]], [[synthetic_canary_20260621]], [[governance_metrics_20260621]], [[watchdog_deadman_20260621]].
