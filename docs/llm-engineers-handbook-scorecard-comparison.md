# Scorecard Comparison — current vs. projected (LLM Engineer's Handbook benchmark)

**Date:** 2026-06-16
**Companion to:** [`llm-engineers-handbook-gap-analysis.md`](llm-engineers-handbook-gap-analysis.md) · [`system-audit-2026-06-16.md`](system-audit-2026-06-16.md)
**Verification of these claims against the live codebase:** [`llm-engineers-handbook-claims-verification-2026-06-16.md`](llm-engineers-handbook-claims-verification-2026-06-16.md)

Letter grades are the benchmark scores. "After" assumes the P0–P2 roadmap lands — realistic targets, not perfection (single-host SPOF and low A/B-trial volume cap a few at A‑).

## Per-theme: before vs. after

| Theme | Now (ELI5) | After (ELI5) | Now | → After |
|---|---|---|:--:|:--:|
| **Architecture** (FTI ↔ Runner) | Two databases that disagree; unpinned model | One DB, pinned model, config loaded not hardcoded | **B** | **A‑** |
| **Tooling stack** | "Dollars" column holds euros; 2 price lists | True USD, one price list, cost alarms | **B** | **A‑** |
| **Data engineering** | Re-reads/re-embeds everything every run | Incremental (changed-only), real index | **B** | **A‑** |
| **RAG feature pipeline** | Fast index built but ignored; 1B-model typo | Reads the index; right model; one threshold source | **B** | **A‑** |
| **RAG inference pipeline** | Searches all, then filters; no self-query | Filters first + extracts filters from the query | **B** | **A‑** |
| **Supervised fine-tuning** | Uses off-the-shelf Claude (correct, undocumented) | Same, with a written "why no fine-tune" decision | **N/A** | **N/A** |
| **Preference alignment** | Expired patches stuck on; undo button does nothing | Expiry honored; real undo; effectiveness measured | **C** | **B+** |
| **Evaluation** | Grades its own homework; answer = answer key | Real held-out test, real answers, judge jury | **C** | **B+** |
| **Inference optimization** | No "how fast is the first word" metric | Tracks TTFT/latency; index read; quant tier pinned | **B** | **B+** |
| **Deployment** | One machine; lose work on restart; no failure alarm | Durable state, restart-safe, failure alarm | **B/B+** | **A‑** |
| **MLOps/LLMOps** | No automatic gate between an edit and production | Validator + behavioral gate run automatically | **B (B‑/C+)** | **B+** |
| **Prompt monitoring** | Logs *that* it happened, not *what*; no alarms; leaked secret | Full query→answer traces, alarms, secret rotated | **B** | **A‑** |
| **OVERALL** | Right machinery, wires disconnected | Same machinery, wires connected | **B‑/B** | **A‑** |

## Per-finding: before vs. after (ELI5)

| Area | Now 🔴 | After the fix 🟢 |
|---|---|---|
| Vector search (FAISS) | Builds a fast index every 15 min, then ignores it and reads every row by hand → ~13 s | Actually reads the index → fast lookups, p95 drops |
| Prompt patch expiry | Sticky notes that "expired" 36 days ago are still taped to every prompt | Expired notes auto-fall-off; only live ones apply |
| Patch rollback | The "undo" button is wired to nothing | Real undo — a bad patch can be reverted |
| Rewrite model | Quietly using a tiny 1B brain for query rewriting (typo bug) | Uses the intended 7B brain → better retrieval |
| Cost ledger | The "dollars" column secretly holds euros | Real dollars everywhere; budgets/alerts trust the number |
| Price list | Two different price tags for the same model in different files | One shared price list; change it once |
| QA test suite (51 tests) | The big test pack runs nowhere unless a human remembers | Runs automatically on every change + nightly |
| Code-node validator | The 14-hour-outage fix only works if someone remembers to run it | Runs automatically before any deploy |
| CI quality gate | Checks the form is filled out, not whether the answer is good | Checks the agent's actual answer quality before shipping |
| Eval honesty | Grades its own homework (test == answer key) | Real held-out test + real answers → trustworthy scores |
| LLM judge | One judge, 1–5, never checked vs humans (broken column) | A 2-judge jury, calibrated vs human thumbs-up/down |
| Database | Two copies of the "single" database that disagree | One database everyone reads/writes |
| Where it runs | One machine holds everything; a hiccup loses work | State saved durably; survives restart + failure alarm |
| Trace logging | Records *that* steps happened, not *what* was in them; nobody paged | Full query/prompt/answer + alarms on problems |
| Secret in code | An admin password is hardcoded and pushed to public GitHub | Moved to `.env` and rotated |
| Model pinning | Runs whatever model the CLI defaults to (unversioned) | Pinned model id → reproducible + traceable |
| RAG retrieval smarts | Searches everything, then filters | Filters first (host/category) + self-extracts filters |
| Fine-tuning | N/A — uses off-the-shelf Claude (correct) | unchanged (documented as a deliberate decision) |

**Takeaway:** the platform already *built* almost everything the book asks for — the work is **connecting the wires**, not buying new parts. Every P0 fix reuses code that already exists in the repo.
