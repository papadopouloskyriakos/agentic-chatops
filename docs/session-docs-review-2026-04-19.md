# Docs vs Session Work — Audit (2026-04-19)

Cross-check of **README.md**, **README.extensive.md**, and the public portfolio page at
<https://kyriakos.papadopoulos.tech/projects/agentic-chatops/> against the 18 YT
agentic issues closed in the 2026-04-18 session and the current live system.

## Doc inventory

| Doc | Size | Last major edit | Freshness |
|---|---|---|---|
| README.md | 147 lines | pre-session | stable overview, numbers mildly stale |
| README.extensive.md | 839 lines | pre-session | comprehensive but pre-dates the 9 session closures |
| Portfolio page (`/projects/agentic-chatops/`) | — | Publication date: 2026-04-07 | **12 days stale**, several counts from an earlier snapshot |

## Live-counter reality check

| Metric | README.md | README.extensive.md | Portfolio | **Live (now)** | Drift |
|---|---|---|---|---|---|
| wiki_articles | 44 | 44 | 45 | **970 rows** (many section chunks) | all stale; drift is mainly chunking |
| session_transcripts | 837 (G7 text) | 834 | 834 | **838** | +1-4, trivial |
| incident_knowledge | — | 51 | — | **54** | +3 from 615 backfill |
| chaos_experiments | — | 47 | 47 | **70** | +23 since portfolio |
| graph_entities | 263 | 263 | 263 | **360** | +97 |
| graph_relationships | 127 | 127 | 127 | **193** | +66 |
| tool_call_log | 88,448 | 88K+ | 88,448 | **88,474** | trivial |
| otel_spans | 39K | 39K | 39K | **39,075** | — |
| ragas_evaluation | 17 | 18 | — | **136** | huge drift |
| agent_diary | — | 55 | — | **64** | +9 |
| SQLite tables | — | 31 | 23 | **31** | portfolio inconsistent |
| RAGAS golden set size | — | — | — | **33** (15 hard) | not documented anywhere |
| Hard-eval v2 size | — | — | — | **50 queries** | not documented anywhere |

The absolute tool_call and otel counts are within noise and match well — those are live-updated by crons that don't care about doc sync. The graph and chaos counts drifted because ingestion continued after docs were frozen.

## Session work (2026-04-18) — coverage in docs

### ✅ Already claimed before session (audits validated, state-closed)

| YT | Claim location | Verdict |
|---|---|---|
| 597 G1 cross-encoder rerank | README §"4-Signal RAG" + README.extensive §Pattern 14 | **accurate** |
| 598 G2 RAG Fusion | README §"4-Signal RAG" + README.extensive §Pattern 14 | **accurate** |
| 599 G3 LongContextReorder | README.extensive §Pattern 14 | **claim vs impl divergence** — docstring says "highest at edges, lowest in middle"; code reorders but puts highest in CENTER with extremes at edges. Not introduced this session — pre-existing from G3 merge. Noted but out of scope. |
| 600 G4 Map-Reduce/Refine | README.extensive §Pattern 14 | **accurate** (`scripts/doc-chain.py` present) |
| 601 G5 KG traversal | README + README.extensive §Pattern 14 | **accurate but enhanced** — pre-session implementation existed; 613 added 3-tier progressive widening |
| 602 G6+G8 FAISS | README.extensive §Pattern 14 | **stale** — claims "all 4 tables" but pre-session only 3/4 had .faiss; 612 added chaos_experiments.faiss |
| 603 G7 asymmetric embed | README §"4-Signal RAG" | **accurate** (838/838 transcripts embedded) |
| 604 DLI epic | Epic aggregate | **closed** |

### ❌ Not reflected in docs (session-delivered, undocumented)

| YT | What shipped | Doc mention needed |
|---|---|---|
| 607 | RAGLatencyP95High threshold 6s→12s | Add to README §Observability or alerts section. IaC-level reconciliation noted in commit, not visible in narrative. |
| 609 | Hard-eval diagnostic mode + temporal window filter on `wiki_articles.source_mtime` | README.extensive §3 RAG Pipeline should mention the temporal filter. New `source_mtime` column not in any table docs. |
| 610 | RAGAS golden set 18→33 queries with 15 hard-eval tagged | README.extensive §RAGAS block cites "18 evaluations" — should say 33 total / 15 hard. |
| 611 | Qwen3→Qwen2.5 JSON/rewrite migration (100% first-try reliability) | README.extensive §Pattern 14 + §10 still mention qwen3 in places. Should consolidate to qwen2.5:7b as single `JSON_MODEL`/`REWRITE_MODEL`. |
| 612 | FAISS chaos_experiments indexed (4/4 tables) | README.extensive §3 RAG Pipeline should say 4/4 not 3/4. |
| 613 | G5 3-tier progressive widening | Not in docs; worth a one-liner under Pattern 14. |
| 614 | Weekly eval cron first-fire + 2 silent-failure fixes (awk, chmod 644) | Baseline doc `docs/weekly-eval-baseline-2026-04-20.md` exists but READMEs don't mention the cron is now actually producing metrics (was silently broken). |
| 615 | pve01 incident backfill (566/567/589) | `scripts/backfill/` dir introduced. Not in docs. |
| 616 | **New feature**: list-recent CLI + mtime-sort intent detector | Major undocumented capability. README.extensive should add a section under §3 RAG Pipeline for "mtime-sort queries". |
| 617 | 3 new absent-metric alerts (KBWeeklyEval/ContentRefresh/OpenClawSync MetricAbsent) | README.extensive §Observability doesn't list these; catches a gap class the existing `Stale` alerts couldn't. |
| bonus | unified-guard Bash word-boundary precision fix | README.extensive §Pattern 18 Guardrails should mention this — pre-session it was 9 false-blocks on prose. |
| bonus | 5-mode Haiku synth failure injection (411/timeout/auth/network) | Not docs-relevant but affects reliability story. |

### Portfolio-page-specific staleness

| Portfolio claim | Reality post-session |
|---|---|
| "98 test scenarios" | Now 58 eval scenarios + 54 adversarial + 23 holistic E2E + 9 KG traverse + 22 security hook + 22 mempalace + 5 synth fallback + 20 qwen-json = **161+ total** tests/scenarios |
| "99% health pass rate" | README says 96%; holistic E2E is 100% (23/23); docs disagree with each other |
| "45 wiki articles" | 970 wiki_articles rows — the 45 is article-count; should be clarified |
| "47 chaos experiments" | Now 70 |
| "Injection Patterns Blocked 42" | Hook harness now catches 22 word-boundary + original — counts in different axes |
| "23 tables" | 31 tables |
| "148K+ rows" | README already says 150K+ — portfolio older snapshot |
| **absent**: Self-improving prompts flow | Portfolio mentions it but not that it's been through one full cycle |
| **absent**: L02 Haiku synth (pre-session) | Not in portfolio despite being live |
| **absent**: Hard-eval set / RAGAS hardening | Major quality signal not mentioned |

## Recommendations (priority-ranked)

### P0 — safety / accuracy
1. **Portfolio page**: update core counts + publication date; the 2026-04-07 stamp makes everything else look less reliable. The portfolio is the externally-visible artifact so freshness matters most.
2. **README.extensive.md §10 / §Pattern 14** — flip remaining qwen3 references to qwen2.5:7b per YT-611, or explicitly note qwen3 as legacy/fallback only. Inconsistency here is confusing.

### P1 — completeness
3. **README.extensive.md §3 RAG Pipeline** — add:
   - `wiki_articles.source_mtime` column + temporal window filter (609)
   - `list-recent` CLI subcommand + mtime-sort intent detector (616)
   - 4/4 FAISS tables (612)
   - 33-query RAGAS set w/ 15 hard-eval split (610)
4. **README.extensive.md §Observability** — add the 3 new absent-metric alerts (617) + the weekly-eval bug-fix post-mortem (614).
5. **README.md "Key Numbers" table** — update: graph_entities 263→360, graph_relationships 127→193, chaos_experiments 47→70. Add a row for "RAGAS golden set: 33 queries (15 hard-eval)".

### P2 — polish
6. **docs/session-docs-audit-2026-04-19.md** (this file) — commit so future doc-sync jobs have a history of drift.
7. Long-term: add a single `docs/live-counts.md` auto-refreshed daily with the canonical numbers; point both READMEs + portfolio build at it. Kills this drift class.

## What's accurate / still holds up

The architectural narrative in both READMEs is **substantially correct**. The 3-tier model (OpenClaw → Haiku planner → Claude Code → human), 7-layer safety, 21/21 pattern scorecard, OTel tracing, GraphRAG, compiled wiki, MCP tool surface area, and the alert-lifecycle walkthrough all match how the system works today. The drift is in numeric counts (not narrative) and in capabilities added post-publication.

The portfolio page (2026-04-07) pre-dates most of April 2026, so every week of work since is invisible there. That's the biggest externally-facing gap.

## Summary table: session deliverables vs documentation

| YT | Shipped | README.md | README.extensive | Portfolio |
|---|---|---|---|---|
| 597 | verified | ✅ | ✅ | ✅ |
| 598 | verified | ✅ | ✅ | ✅ |
| 599 | verified | ✅ | ⚠ (docstring drift) | ✅ |
| 600 | verified | ✅ | ✅ | ✅ |
| 601 | verified | ✅ | ✅ | ✅ |
| 602 | verified | ✅ | ⚠ (says 3/4 implicitly) | ✅ |
| 603 | verified | ✅ | ✅ | ✅ |
| 604 | epic closed | ✅ | ✅ | ✅ |
| 607 | cluster alert threshold | ❌ | ❌ | ❌ |
| 609 | hard-eval diag + temporal filter | ❌ | ❌ | ❌ |
| 610 | RAGAS 18→33 queries | ❌ | ❌ (still cites 18) | ❌ |
| 611 | qwen2.5 consolidation | ❌ | ⚠ (mixed) | ❌ |
| 612 | FAISS chaos table | ❌ | ⚠ (implies 3/4) | ❌ |
| 613 | G5 progressive widening | ❌ | ❌ | ❌ |
| 614 | weekly eval fixes + baseline | ❌ | ❌ | ❌ |
| 615 | pve01 backfill | ❌ | ❌ | ❌ |
| 616 | **new** list-recent / mtime-sort | ❌ | ❌ | ❌ |
| 617 | 3 new absent-metric alerts | ❌ | ❌ | ❌ |

**10 of 18 session deliverables unreflected in any doc.** One of them (616) is a new user-facing feature.
