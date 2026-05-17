# Judge Calibration Baseline — 2026-04-19

Dual-scored 60 queries (50 hard-retrieval-v2 + 10 hard-kg) with both **Haiku claude-haiku-4-5-20251001** (reference) and **gemma3:12b** (local, with qwen2.5:7b fallback). Retrieval ran once per query so both judges saw identical top-5 docs.

## Overall

| Metric | Value |
|---|---|
| Cases | 60 |
| Complete (both judged) | 60 |
| **Agreement rate** | **85.0%** |
| False positives (local hit, Haiku miss) | 6 |
| False negatives (local miss, Haiku hit) | 3 |
| Haiku hit rate | 52/60 (86.7%) |
| Local hit rate | 55/60 (91.7%) |
| Δ | +5.0 pp |

## By category

| Category | Agreement |
|---|---|
| abbreviation | 1/1 (100.0%) |
| architecture | 4/4 (100.0%) |
| causal-ambiguity | 1/1 (100.0%) |
| config | 1/1 (100.0%) |
| corroboration | 2/2 (100.0%) |
| cost | 1/1 (100.0%) |
| cross-signal | 0/1 (0.0%) |
| diagnostic | 1/1 (100.0%) |
| hostname-chain | 1/1 (100.0%) |
| hostname-specific | 1/1 (100.0%) |
| kg | 7/10 (70.0%) |
| meta | 3/4 (75.0%) |
| metric-recall | 1/1 (100.0%) |
| monitoring | 1/1 (100.0%) |
| multi-hop | 4/4 (100.0%) |
| negation | 1/1 (100.0%) |
| oblique | 3/3 (100.0%) |
| oblique-phrase | 1/1 (100.0%) |
| obscure | 1/1 (100.0%) |
| operational | 0/1 (0.0%) |
| ops | 1/1 (100.0%) |
| ops-policy | 1/1 (100.0%) |
| policy | 2/3 (66.7%) |
| recency | 2/2 (100.0%) |
| silent-failure | 1/1 (100.0%) |
| similar-hostnames | 1/1 (100.0%) |
| specific-cmd | 2/2 (100.0%) |
| specific-incident | 2/3 (66.7%) |
| specific-value | 0/1 (0.0%) |
| subtle-distinction | 1/1 (100.0%) |
| symptom-to-root | 1/1 (100.0%) |
| synthesis | 1/1 (100.0%) |
| timeboxed | 1/1 (100.0%) |

## Disagreements

### False positives (local says hit, Haiku says miss)

- `H10` (cross-signal)
- `H12` (policy)
- `H22` (specific-incident)
- `H29` (meta)
- `KG03` (kg)
- `KG08` (kg)

### False negatives (local says miss, Haiku says hit)

- `H32` (operational)
- `H47` (specific-value)
- `KG05` (kg)

## How to interpret

- **Agreement rate** is the headline number. ≥95% means the local judge is a safe drop-in; 85-95% means absolute hit-rate numbers are comparable but noisy across week-over-week comparisons; <85% means the two are materially different judges and the local-era and Haiku-era trend lines should not be charted together.
- **FP rate** indicates whether local is looser than Haiku (calls borderline cases 'hit' that Haiku would reject). FP-heavy drift makes hit-rate numbers look artificially high.
- **FN rate** indicates whether local is stricter than Haiku (misses hits Haiku would accept). FN-heavy drift makes the pipeline look worse than it is.

Repeat this calibration annually or after any change to the judge model/prompt/rubric. Results persisted at `judge-calibration-2026-04-19.json`.
