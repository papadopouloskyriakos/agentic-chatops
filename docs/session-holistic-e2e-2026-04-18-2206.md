# Session Holistic E2E Report — 2026-04-18-2206

Runtime: 157s. Total tests: 23. Skipped: 0.

## Summary

| Metric | Value |
|---|---|
| Pass | 23 |
| Fail | 0 |
| Warn | 0 |
| Skip | 0 |
| Pass rate (of executed) | 100.0% |

## Per-test results

| Test | Category | Name | Status | Before | After | YT |
|---|---|---|---|---|---|---|
| T1 | retrieval | rerank /health | **PASS** | service-absent-pre-session | ok | 597 |
| T1 | retrieval | rerank /rerank returns scores | **PASS** | none | scores-returned | 597 |
| T2 | retrieval | RAG Fusion ≥3 variants | **PASS** | D-rated (single-query) | 4-variants | 598 |
| T3 | retrieval | LCR reorders input (length+members preserved) | **PASS** | F-rated (no reorder) | reorder-confirmed | 599 |
| T4 | retrieval | doc-chain.py CLI responds | **PASS** | absent-pre-session | CLI-ok | 600 |
| T5 | retrieval | KG traverse harness 9/9 | **PASS** | fallback-only-pre-613 | 9-pass | 601,613 |
| T6 | data | FAISS indexes 4/4 present | **PASS** | 3/4 (chaos missing) | 4/4 | 602,612 |
| T6 | data | FAISS row-count parity | **PASS** | not-measurable-pre-612 | all-tables-match | 602,612 |
| T7 | retrieval | embed_query != embed_document | **PASS** | B-rated (unprefixed) | vectors-differ | 603 |
| T7 | data | all transcripts embedded (838/838) | **PASS** | 837/0 unembedded | 838/838 | 603 |
| T8 | retrieval | DLI E2E hybrid search returns rows | **PASS** | baseline-0.86-precision | rows-returned | 604 |
| T9 | observability | RAGLatencyP95High threshold = >12 | **PASS** | > 6 (firing) | >12 (inactive) | 607 |
| T11 | quality | RAGAS set 33+ total, 15+ hard-eval | **PASS** | 18 total, 0 hard | 33 total, 15 hard | 610 |
| T13 | observability | kb_hard_eval_* metrics ≥6 | **PASS** | 0 (cron broken) | 6 metrics | 614 |
| T14 | data | 3 pve01 incidents backfilled + embedded | **PASS** | 0 rows | 3/3 | 615 |
| T15 | retrieval | mtime-sort intent 4/4 | **PASS** | no-intent-detector | 4/4 cases | 616 |
| T15 | retrieval | list-recent CLI returns rows | **PASS** | CLI-absent | 3-rows | 616 |
| T16 | observability | 3 absent-metric alerts in cluster | **PASS** | staleness-alerts-blind-to-absence | 3/3 | 617 |
| T17 | security | unified-guard precision 22/22 | **PASS** | 9 false-blocks on prose | 22-pass | bonus |
| T19 | integration | mempalace 22/22 | **PASS** | not-filed-as-tracked-suite | 22-pass | bonus |
| T10 | quality | hard-eval 7q judge_hit@5 ≥ 0.85 | **PASS** | 0.571 (4/7) | 0.857 | 609 |
| T12 | reliability | qwen2.5 JSON ≥ 98% | **PASS** | 87.5% qwen3 first-try | 100.0% | 611 |
| T18 | reliability | synth fallback 17/17 | **PASS** | 1 mode (empty only) | 17-pass | bonus |

## By category

| Category | Pass/Total |
|---|---|
| data | 4/4 |
| integration | 1/1 |
| observability | 3/3 |
| quality | 2/2 |
| reliability | 2/2 |
| retrieval | 10/10 |
| security | 1/1 |

## YT coverage

Every issue closed this session (9 verification + 9 filed-and-closed = 18) has at least one test row above. Issue→test map:

- 597 G1 rerank → T1
- 598 G2 RAG Fusion → T2
- 599 G3 LCR → T3
- 600 G4 doc chains → T4
- 601 G5 KG traversal → T5
- 602 G6+G8 FAISS benchmark → T6
- 603 G7 asymmetric embed → T7
- 604 DLI epic → T8
- 607 RAGLatencyP95High threshold → T9
- 609 hard-eval misses → T10
- 610 RAGAS hardening → T11
- 611 Qwen3→Qwen2.5 migration → T12
- 612 FAISS chaos table → T6
- 613 G5 plan-path widening → T5
- 614 weekly eval first-fire → T13
- 615 pve01 backfill → T14
- 616 H50 list-recent → T15
- 617 absent-metric alerts → T16

## Regressions

**None.** Every test that was expected to pass, passed.
