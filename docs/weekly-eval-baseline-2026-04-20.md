# Weekly Hard-Eval Baseline (First Run)

First real measurement of the weekly hard-retrieval + KG eval pipeline.
The cron is scheduled `0 5 * * 1` (Monday 05:00 UTC, first scheduled fire
2026-04-20); this entry captures the value from a manual fire on
**2026-04-18 22:59 UTC** while closing IFRNLLEI01PRD-614.

## Measurement

| Metric | Value | Notes |
|---|---|---|
| `kb_hard_eval_hit_rate` | **0.90** | 45/50 on hard-retrieval-v2 (judge-graded hit@5). |
| `kb_hard_eval_coverage_rate` | 0.30 | Mean coverage@5 (avg fraction of top-5 that are relevant). |
| `kb_hard_eval_kg_coverage` | 0.70 | 7/10 on hard-kg (judge coverage@5). |
| `kb_hard_eval_latency_p50_seconds` | 5.68 | — |
| `kb_hard_eval_latency_p95_seconds` | 13.64 | Slightly over the 12s RAGLatencyP95High threshold; driven by Haiku synth RTT on synth-eligible queries. |
| `kb_hard_eval_last_run_timestamp_seconds` | VMID_REDACTED7 | 2026-04-18 22:59:17 UTC. |

## Alert state after emit

| Alert | Threshold | State |
|---|---|---|
| `RAGHardEvalRegression` | `kb_hard_eval_hit_rate < 0.7` for 7d | `inactive` (0.90 is well above 0.70) |
| `KBWeeklyEvalStale` | `time() - kb_hard_eval_last_run_timestamp_seconds > 691200` for 1h | `inactive` (fresh timestamp) |

## Bugs discovered + fixed during the manual fire

Two silent failures that would have hit the real Monday 05:00 UTC run:

1. **`awk -F': '` regex never matched** — `scripts/weekly-eval-cron.sh` extracted the results JSON path with `awk -F': ' '/Results written to/ {print $2}'`, but the print line is `Results written to <path>` (no colon), so `RESULTS_PATH` came back empty and the cron aborted with `no results file — aborting metric emit` every time. Fixed by switching to `awk '/Results written to/ {print $NF}'`.
2. **Textfile `mktemp` permissions were 0600** — node-exporter runs as `nobody` and can't read owner-only files, so Prometheus scraped zero samples even after the file existed. Fixed by `chmod 644` after the atomic `mv`.

Both fixes are in the same commit as this doc (IFRNLLEI01PRD-614).

## Expectations for the Monday 2026-04-20 05:00 UTC fire

- First scheduled cron run (before today this had never fired).
- Expected `kb_hard_eval_hit_rate`: ~0.90 (this manual baseline). Drift beyond ±0.05 w/w should be investigated.
- Expected `kb_hard_eval_latency_p50`: ~5-6s. Drift above 10s would indicate gpu01 / rerank service pressure.
- `KBWeeklyEvalStale` should clear each Monday around 05:02-05:05 UTC as the new timestamp propagates through Prometheus scrape + rule eval.

## Known follow-up debt (not blocking this closeout)

- `KBWeeklyEvalStale` currently evaluates to `inactive` when the metric is absent (rather than firing). If the cron silently breaks again for weeks, we won't get paged. The alert expression should use an `absent()` wrapper or a `vector(0)` fallback to fire on disappearance — filing separately.
- H36 / H50 hard-eval misses remain (IFRNLLEI01PRD-615 / 616), but they don't drag the aggregate below the 0.70 alert threshold.
