# Infragraph cascade-predictor calibration — closing the -1065 precision gap

**Status:** **P1 (-1118) + P2 (-1119) IMPLEMENTED + LIVE 2026-06-17**. Drives IFRNLLEI01PRD-1065 (InfragraphPrecisionDrop) toward the IFRNLLEI01PRD-1040 Phase B→C gate. Epic: IFRNLLEI01PRD-1029.

## P2 implementation (-1119, shipped)
`lib.infragraph.score_prediction(pred, act, family=True)` is the single source of truth; `rule_family()` maps rules to {host-down, k8s-pod, rag, resource, backup}. `expected_cascade` items carry `rule_family`. The weekly scorecard + `health()` + the Prometheus exporter now report **family** precision/recall alongside exact (`infragraph_precision_family_30d`, `infragraph_recall_family_30d`); the scorecard adds a nested `gate_b_to_c.family` verdict (`all_met_family`) whose conf08 subset gates on the FAMILY confidence (`cascade_prob_family` from -1118), falling back to exact for legacy rows. The exact `all_met` (the live -1040 gate criterion) is **unchanged** — the operator adopts the family unit at the -1040 review.

**Measured (live data):** family scoring lifts recall **0.279 → 0.365** and precision 0.054 → 0.078. **Composed with -1118 gating: family precision 0.054 → 0.171** at the recall-neutral default (higher with τ tuned up). `precision_conf08_family` stays empty honestly — the best family hit-rate is 0.474 (host-down → nl-claude01/k8s-pod, 8/14), so nothing yet reaches the conf≥0.8 subset and both the exact and family gates correctly stay NO-GO; they populate as data accumulates. **Recommendation for the -1040 review:** promote on the family unit (`gate_b_to_c.family.all_met_family`) — exact (host,rule) scoring penalises right-host-wrong-rule cascades, which is the wrong measure for suppression safety.

## P1 implementation (-1118, shipped)
`lib.infragraph.apply_cascade_gating()` gates `expected_cascade` (and the shuffled control, symmetrically) against learned per-(parent-family → child) hit-rates in `infragraph_cascade_stats` (migration 017, learned by `infragraph-learn.py --from-cascades`, hourly cron). Emit-gate by **family** probability ≥ `INFRAGRAPH_CASCADE_MIN_PROB` (default 0.10); per-item confidence set to the **exact-rule** probability (Laplace(1,4)). `model_version=2`. Kill-switch `INFRAGRAPH_CASCADE_GATING=0` (byte-identical legacy); inert until the first learn populates stats. Shadow-only — no change to the fail-CLOSED action lane or what is auto-suppressed.

**Measured on the live data (backtest through the real code):**
- Default τ=0.10 drops only the provably-non-cascading families (e.g. `host-down → claude01/resource`, seen=14 fired=0) → overall precision **0.054 → 0.097 (1.8×) at ZERO recall cost**. Higher τ trades recall (τ=0.15→0.144, τ=0.20→0.153; the shuffled control stays gated symmetrically, ratio ~0.30 ≪ 0.5).
- `precision_conf08` is **honestly empty**: the best exact-rule hit-rate in the window is 0.36 (`TargetDown`, 5/14) — no rule yet fires ≥80% of the time it's predicted, so nothing reaches the conf≥0.8 subset and the -1040 gate correctly stays NO-GO. This populates as data accumulates AND once -1119 lands.
- The remaining cap is the right-host-wrong-rule penalty (-1119): family-scored precision is ~0.5, exact-scored ~0.1–0.4. **-1118 removes the over-prediction; -1119 fixes the granularity — they compose.**

## Problem (measured, not assumed)

The shadow cascade predictor scores **precision 0.056** over the 30d window (sum tp=19 vs **fp=318**). This is *over-prediction*, and it is **not** the declared-edges seed bug (a missing-edges bug lowers recall, not precision; recall is fine at 0.28–0.40; declared edges are 23 of ~420 and were re-seeded after the window). Two roots, from the live `infragraph_predictions` rows:

1. **Cascade over-prediction.** The predictor emits the full structural blast-radius as expected downstream alerts, but most structural dependencies don't actually cascade. Example pred #2: `nlk8s-node03 / Linux High Memory Usage` → predicted 9 downstream (nl-claude01 RAG/Kube alerts, nl-gpu01, nl-pve01/02) → **0 fired**.
2. **Alert-rule granularity.** When a cascade *does* happen (pred #21/#37: `nl-pve03`/`nl-pve02` → `nl-claude01`, correct host), the predictor emits a canned expected-alert set (`RAGLatencyP95High`, `NodeSystemSaturation`, `HighPodRestartRate`) while the rules that actually fire on that host are different (`KubePodNotReady`, `KubeDeploymentReplica`, `PodCrashLoopBackOff`). Exact (host,rule) scoring counts right-host-wrong-rule as a false positive.

## Quantified impact (replay of the 37 evaluated cascade predictions)

| scoring / gate | precision | recall |
|---|---|---|
| baseline (host,rule exact) | 0.056 | 0.279 |
| Fix #2 only — host-level | 0.085 | 0.394 |
| Fix #2 only — (host, rule-family) | 0.081 | 0.365 |
| **Fix #1** cascade-prob gate τ=0.3 (in-sample) | **0.500** | 0.250 |
| Fix #1 gate τ=0.5 (in-sample) | 0.615 | 0.154 |
| Fix #1 gate τ=0.3 — **out-of-sample** (60/40 temporal split) | 0.545 | 0.150 |
| Fix #1 gate τ=0.5 — out-of-sample | 0.667 | 0.150 |

**Conclusion:** Fix #1 (cascade-probability gating) is the dominant lever — ~6–12× precision, and it holds out-of-sample. Fix #2 (granularity) alone is minor but lifts recall and composes with #1. *Caveat:* 37 rows is too few for stable numbers — these are directional; real validation needs the gating wired + a few more weeks of shadow data. Neither fix alone reaches the gate's `precision_conf08 ≥ 0.95`; they move the predictor in the right direction and produce the confidence signal the gate's high-confidence subset needs.

## Fix #1 — cascade-probability gating (P1, the lever)

For each candidate downstream `(parent_rule → child_host, child_rule_family)`, learn `p = P(child fires | parent event)` from incident + prediction history; **only emit downstream where `p ≥ τ`, and surface `p` as the per-prediction confidence** (so high-`p` predictions populate the gate's `precision_conf08` subset). Don't emit the full structural blast-radius.

- **Where:** `infragraph-learn.py` (accumulate per-edge cascade hit-rates into `infragraph_dynamics` or a new `infragraph_cascade_stats` table, with a min-observation floor); `infragraph-predict-plan.py` + `lib/infragraph.py::predict_*` (gate + attach confidence). τ as a tunable env/const.
- **Safety:** shadow-only. This changes what the predictor *records* and its confidence, **not** what is auto-suppressed — the -1040 gate stays the only promotion boundary, and it is NO-GO until precision recovers. Zero change to the fail-CLOSED remediation lane.
- **Acceptance:** `precision_conf08` materially > 0 on a held-out window; backtest reported in the scorecard; in-sample + out-of-sample numbers logged; recall stays ≥ 0.40 lower-bound at the chosen τ.

## Fix #2 — host/rule-family granularity (P2)

Stop emitting a canned per-edge expected-alert list. Either (a) **learn the real expected-alert set per edge** from incident history, or (b) **score/predict at `(host, rule-family)` granularity** via an equivalence-class map (host-down / k8s-pod / rag / resource / backup). Recommend (a) with (b) as fallback.

- **Where:** expected-alert assignment in `lib/infragraph.py` / seed / `infragraph-learn.py`; add family-level scoring alongside exact in `infragraph-eval.py` (keep exact for transparency).
- **Acceptance:** family-scored precision/recall reported next to exact in the scorecard; recall lift demonstrated; composes with #1.

## Out of scope / non-goals
- No change to Phase C activation, the -1040 gate criteria, or any live suppression. This is predictor calibration in shadow mode.
- The declared-edges seed repair (`1195b86`) is orthogonal and already done; it is **not** what moves -1065.
