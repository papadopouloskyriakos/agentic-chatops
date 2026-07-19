# Gap Analysis — LLM Engineer's Handbook vs the claude-gateway agentic platform

**Date:** 2026-06-16
**Reference:** Paul Iusztin & Maxime Labonne, *LLM Engineer's Handbook* (Packt, 2024) — [overview](llm-engineers-handbook-overview.md) · [source text](llm-engineers-handbook/LLM-Engineers-Handbook.md)
**System side:** [`system-audit-2026-06-16.md`](system-audit-2026-06-16.md)
**Method:** 41-agent fan-out — 10 subsystem readers + 6 chapter-group readers → 12 per-theme benchmarks, **each with an adversarial verifier that re-checked every claimed gap against committed repo state** (confirmed / refuted / overstated) → a completeness critic for cross-cutting gaps and grade calibration. Every gap below carries its verifier verdict.

> **How to read the grades.** This is an *operations* system that consumes off-the-shelf models — it trains, fine-tunes, and quantizes nothing (verified). So the book's training-side themes are graded **N/A by design**, per the book's own "judge by properties, not tools" rule. The applicable themes are graded on the properties the book demands (versioned/observable/reproducible/cost-bounded/skew-free), not on tool adoption.

---

## Scorecard

| # | Theme (book ↔ system) | Grade | Verified gaps |
|---|---|:---:|---|
| 1 | **Architecture** — FTI pipelines ↔ event-driven Runner | **B** | 4 (4 confirmed) |
| 2 | **Tooling stack** — ZenML/Comet/Opik/SageMaker ↔ n8n/SQLite/Prometheus/Ollama | **B** | 5 (4 conf / 1 over) |
| 3 | **Data engineering** — crawlers/ODM/CDC ↔ session-capture/incident-KB ingestion | **B** | 5 (4 conf / 1 over) |
| 4 | **RAG feature pipeline** — embeddings/chunking/vector-DB/advanced-RAG ↔ 5-signal RRF + rerank | **B** | 6 (3 conf / 3 over) |
| 5 | **RAG inference pipeline** — query-expansion/self-query/filtered-search/rerank ↔ rewrite/rerank/LCR | **B** | 8 (5 conf / 3 over) |
| 6 | **Supervised fine-tuning** — instruction datasets / LoRA / PEFT | **N/A** | (correct: closed-weight) |
| 7 | **Preference alignment** — DPO ↔ prompt-patch A/B + risk-approval feedback | **C** | 6 (5 conf / 1 over) |
| 8 | **Evaluation** — general/domain/task/RAG + LLM-judge ↔ judge-cal/hard-eval/RAGAS | **C** | 10 (10 confirmed) |
| 9 | **Inference optimization** — quantization/attention/KV-cache ↔ local Ollama + breakers | **B** | 5 (4 conf / 1 over) |
| 10 | **Deployment** — SageMaker real-time/async/autoscale ↔ n8n bg-launch + SSH + polling | **B/B+** | 4 (1 conf / 3 over) |
| 11 | **MLOps/LLMOps principles** — experiment-tracking/registry/CI-CD ↔ QA-suite/schema-ver | **B → B-/C+** | 8 (6 conf / 2 over) |
| 12 | **Prompt monitoring** — Opik full-trace ↔ OTel/tool_call_log/prompt_scorecard | **B** | 6 (6 confirmed) |

**Aggregate:** no failing themes; the system is a competent, often-sophisticated realization of the book's doctrine for an operations context. The two genuinely weak themes (**Evaluation C**, **Preference-alignment C**) are also the two most rigorously verified (16/16 gaps confirmed). The critic's calibration: Deployment is over-penalized (→ B/B+; `gateway-watchdog.sh` already provides serving-path reliability alerting); MLOps-principles is slightly generous (→ B-/C+; four HIGH gaps together mean there is effectively no automated guardrail between an edit and production).

---

## The cross-cutting story (what the per-theme grades under-count)

The per-theme view fragments a single truth: **the same five root failures recur theme-to-theme, and no theme is charged for the compounding.** The book organizes the LLM lifecycle around exactly the governance layers this system lacks — a versioned model/prompt registry with rollback, an offline eval gate that runs *before* artifacts ship, data/feature lineage, and canary/shadow rollout. The system has impressively rich *machinery* for all of these. In nearly every case the machinery is **built-and-disconnected rather than missing.**

### Cross-cutting gap 1 — "Wired-but-disconnected dead capability" (HIGH, no owner)
Six independent dead-capability instances verified in committed state:
1. `kb-semantic-search.py` has **zero FAISS references** while `faiss-index-sync.py` rebuilds the index every 15 min → retrieval is an O(N) brute-force cosine scan. Counted as a separate gap in **five** themes; it is **one** dead read-path.
2. `eval-flywheel.sh:413` calls `prompt-improver.py --rollback` → exits 1 ("Unknown mode"). The regression safety net is phantom; `--expire` exists but is never scheduled.
3. Build Prompt filters patches with `parsed.filter(p => p.active)` and **never reads `expires_at`** → April-2026 patches inject into every prompt forever.
4. `kb-semantic-search.py:379` sets `REWRITE_MODEL=qwen2.5:7b`, then `:467` re-defines it `llama3.2:1b` → HyDE/RAG-Fusion silently run on the 1B model.
5. `run-qa-suite.sh` (51 suites) appears in **neither** `.gitlab-ci.yml` nor cron → fires nowhere.
6. The Runner launch command carries **no `--model` pin** → the highest-cost component runs the CLI's ambient default.

### Cross-cutting gap 2 — One data-contract corruption with multi-theme blast radius (HIGH)
Runner node 161 computes `costEur = (parsed.cost_usd||0) * 0.92` and writes **EUR into columns named `cost_usd`** (`llm_usage`, `sessions`, `session_log`). The MLOps-tooling theme owns it, but the Deployment budget circuit-breaker (`MAX_SESSION_COST_USD` compares EUR to a USD threshold → 8.7% loose), the Eval theme (`metamorphic-monitor.sh` `HAVING AVG(cost_usd) > $CEILING`), and the cost-ledger reproducibility (MLOps-principles) all inherit a **behavioral** defect. No theme charges the compounding.

### Cross-cutting gap 3 — No offline eval-quality / behavioral-output gate in CI before prompt or Code-node changes ship (HIGH)
The only blocking CI gate (`golden-test-suite.sh`) validates JSON shape + safe-exec guardrails, **not output quality**; the RAGAS golden set is "still manual"; `run-qa-suite.sh` fires nowhere; the post-14h-outage Code-node validator is unenforced human discipline. There is no staging/dev/prod separation.

### Cross-cutting gap 4 — No closed-loop prompt/patch registry with working rollback or honored expiry (HIGH)
The eval-flywheel is a write-once dead pipeline: patches never expire, `score_after` is never re-measured, `--rollback` doesn't exist, and the A/B framework has never promoted a winner. The *capability* (`finalize-prompt-trials.py` promotion machinery, `--expire` mode) is fully built and even cron-wired — it is simply not connected at the read side.

### Cross-cutting gap 5 — Tables and traces outside the schema-version / lineage governance (MEDIUM)
`otel_spans` is defined inline inside `export-otel-traces.py`, invisible to the schema-version registry and `fresh_db` fixtures; the embedding write-path has no `embed_model`/dimension lineage column; `graph_entities`/`graph_relationships`/`ragas_evaluation`/`prompt_scorecard` are unregistered.

### Cross-cutting gap 6 — No canary / shadow / staged rollout; the session agent model is unpinned (MEDIUM)
No `--model` pin on the Runner launch, so the inference half of the FTI "registry" is unmanaged, and `model-provenance.md` asserts a pinning mitigation the runtime does not honor.

### The single most valuable missing thing
> **An offline eval-quality gate that runs in CI before any prompt-patch or n8n Code-node change ships, backed by a versioned prompt/patch registry with a working rollback.** It closes the most confirmed HIGH gaps at once — it gives the dead eval-flywheel a real `--rollback` and enforced expiry; converts `golden-test-suite --set regression` from JSON-shape validation into a behavioral gate (incidentally fixing the regression/holdout self-comparison); makes the n8n Code-node validator mechanical; and supplies the pre-ship gate the book treats as table-stakes. **Every input already exists in-repo** (RAGAS golden set, judge harness, 51 QA suites, the validator) — they are simply not assembled into a blocking pre-merge gate.

---

## Per-theme detail

### 1. Architecture (FTI ↔ event-driven) — **B**
**Book:** FTI decomposition; interface-only coupling through a single versioned feature store (kills train-serve skew); client passes a key, not features; decouple domain logic from orchestrator; config-as-data; human red-button.
**System:** Maps onto FTI cleanly — the `infragraph seed→learn→predict→eval` split is a textbook FTI-shaped pipeline (real ETL stage + falsifiable held-out eval); `lib/` decouples domain logic from the thin n8n layer; `schema_version.py` supplies the versioned-contract guarantee; inference retrieves features by key.
**Gaps:** ① *(confirmed)* split-brain `gateway.db` — the feature-store single-source-of-truth is two diverged files (the literal opposite of FTI's central invariant; a half-completed migration); ② *(confirmed)* orchestrator not cleanly swappable — slot/room map hardcoded in the sandboxed Code node ("MUST stay in sync with slot-config.json"); ③ *(confirmed)* no `--model` pin → the registry half is unmanaged; ④ *(confirmed)* `Check Intermediate Rail` is a permanent no-op (`child_process` sandbox-blocked).
**Top fixes:** collapse the DB split-brain via a `lib.get_db()` factory (med/high); pin `--model` + stamp graph/model hash on each prediction (low/high); load slot config at runtime via an SSH node (med/med).

### 2. Tooling stack — **B**
**Book:** Property-first, anti-lock-in tool selection; registry + experiment-tracking + prompt-monitoring + single cost source-of-truth; pin everything; cost as a first-class NFR.
**System:** A correct reading of the book's anti-dogma rule — n8n (orchestrator), SQLite (artifacts/logical feature store, schema-versioned), `model-provenance.md` (registry analog), OTel GenAI semconv (the Opik analog), local Ollama + Max-OAuth ($0). `llm_usage` is a genuine single cost ledger; version pinning is real.
**Gaps:** ① *(confirmed)* `cost_usd` holds EUR (currency corruption); ② *(confirmed)* no single pricing module — Haiku priced `$0.80/$4` and `$1/$5` in different files (25% divergent, and the cheaper card is stale Haiku-3.5); ③ *(confirmed)* provenance doc drifted from live model set; ④ *(confirmed)* no cost-budget alert despite exported `llm_cost_today{tier}`; ⑤ *(overstated)* cost metrics lack boot sentinels.
**Top fixes:** fix the currency bug end-to-end + correct the HELP text (low/high); extract `scripts/lib/pricing.py` (low/high); add cost-budget Prometheus alerts on the already-exported metric (low/high); auto-generate the provenance registry from `ollama list` + a drift check (med/med).

### 3. Data engineering — **B**
**Book:** Real ETL; group by type not source; pipeline independence via storage contracts; CDC once past tens of thousands of rows; typed ODM/OVM; two snapshots; vector DB over standalone index.
**System:** `infragraph-seed.py` is a genuine 5-source ETL (per-source isolation + rollback + loud exit) with correct group-by-type binning; transcript ingestion is event-driven via Stop/PreCompact hooks with a raw-gzip second snapshot; asymmetric embedding discipline is correct.
**Gaps:** ① *(confirmed)* no vector index — O(N) JSON-text brute-force cosine over ~16,797 rows per query-variant (the standalone-index failure mode the book rejects); ② *(confirmed)* no CDC — `index-memories.py` computes `content_hash` but never compares it → full re-embed every run (yet `wiki-compile.py` does proper SHA-256 incremental — uneven application); ③ *(confirmed)* falsified data contract (registry says BLOB float32, code stores JSON text); ④ *(overstated)* hard truncation, no overlap (chunking *does* exist; the real defect is truncation-with-data-loss); ⑤ *(confirmed)* no cleaned-for-training snapshot (largely N/A — no FT consumer). **Verifier-added:** no embedding-dimension/model guard on the **write** path → silent-corruption risk on a model swap.
**Top fixes:** wire FAISS (or `sqlite-vec`) into the read path (med/high — most scaffolding exists); make `index-memories.py` incremental via the existing `content_hash` (low/med); reconcile the embedding contract (packed float32 BLOB) + add a model/dim stamp (med/med).

### 4. RAG feature pipeline — **B**
**Book:** Asymmetric/consistent embeddings; deliberate chunking with overlap; vector DB with ANN index; advanced RAG at 3 stages; weights chosen by RAG-eval not by hand; version prompt templates.
**System:** A sophisticated, textbook-aligned stack (bi-encoder → RAG-Fusion → 5-signal RRF → cross-encoder rerank → multi-chunk synthesis → LongContextReorder); correct prefixes; 4 tuned circuit breakers; graceful degradation; RAGAS-measured.
**Gaps:** dead FAISS read-path; hard truncation / no overlap; bare-literal thresholds scattered (0.3/0.4/0.55/0.70/0.8); no model-id/dim on stored vectors; `embed_query` lru-caches failures; the `0.3/0.7` synthesis blend is hardcoded. (3 confirmed / 3 overstated — the overstated ones are real-but-narrower than framed.)
**Top fixes:** ANN read path (high/high); fix the `REWRITE_MODEL` shadow (low/high); single-source the RAG thresholds into `rag_config.py` (low/med).

### 5. RAG inference pipeline — **B**
**Book (Ch 9):** Most advanced-RAG code lives in retrieval — query expansion (multi-query), **self-querying** (→ metadata filters), **filtered vector search** (pre-filter before scoring = the biggest lever), cross-encoder rerank; same embedder both sides; modular singletons.
**System:** Has multi-query RAG-Fusion + cross-encoder rerank + LCR — the post-retrieval half is strong.
**Gaps:** ① *(confirmed)* **self-querying absent** (only temporal-window extraction exists); ② *(confirmed-ish)* filtered vector search does **not** pre-filter by metadata before scoring — it scans the full date-windowed table then cosines; ③ *(overstated)* no ANN read path (FAISS built but never read); ④ *(confirmed)* `REWRITE_MODEL` shadowing degrades HyDE to a 1B model; ⑤ Build-Prompt L2 is a second keyword-only retrieval surface bypassing the whole pipeline; ⑥ hard truncation; ⑦ *(confirmed)* `cosine_similarity` has no dimension guard (`zip` truncates silently); ⑧ synthesized answers injected at position 0 with fabricated confidence 0.95 / similarity 1.000 (no provenance flag).
**Top fixes:** metadata pre-filtering into the SQL WHERE (med/high); delete the `REWRITE_MODEL:467` shadow (low/high); wire FAISS read path (high/high); a lightweight self-query extractor (host/site/category) (med/med); unify L2 onto the main RRF path (med/med); flag synthesized answers as composed + add the cosine dim guard (low/med).

### 6. Supervised fine-tuning — **N/A** (correct)
**Book (Ch 5):** Curate accuracy/diversity/complexity; dedup; **decontaminate against eval sets**; LoRA/QLoRA; structured output.
**System:** Trains nothing — base model is closed-weight Claude (verified: zero LoRA/PEFT/DPO/TRL/SageMaker training code). The book's own gate (prompt-engineering + RAG first; fine-tune only if eval fails *and* data exists) is satisfied by *not* fine-tuning. **The substitute** for behavioral adaptation is prompt-policy iteration — and that loop is currently broken (see theme 7).
**Top fixes:** write a one-paragraph "no fine-tuning" ADR in `model-provenance.md` tied to the book's decision gate (low/med); a `docs/book-applicability-map.md` marking Ch 5–6 + QAT N/A-by-design (low/low).

### 7. Preference alignment — **C**
**Book (Ch 6):** Accumulate (chosen, rejected) preference data; DPO; pairwise-over-absolute judging with explicit bias mitigation.
**System:** The DPO analog is the prompt-patch A/B framework + risk-approval feedback — genuinely statistically disciplined scaffolding (deterministic arm assignment, SQL-enforced one-live-trial-per-dimension, timeout safety).
**Gaps (5 confirmed / 1 overstated):** ① expired patches still injected (`p.active` filter, `expires_at` ignored); ② `score_after` never auto-updated (the only effectiveness signal is dead); ③ phantom `--rollback`; ④ *(overstated)* A/B has never promoted a winner (machinery exists + is cron-wired; just never reached significance — at this session volume `min_samples_per_arm` is rarely hit); ⑤ single-judge, absolute scoring, no bias mitigation, stale calibration; ⑥ no human-preference dataset accumulation.
**Top fixes:** honor `expires_at` (one-line) + cron `--expire` (low/high); cron `--report` for `score_after` + a real revert (low/high); proper t-distribution p-value + multiple-comparison correction + volume-aware sample floor (med/med); harden the judge (drift alert + bias mitigation + fix the dead `feedback_type` column) (med/med).

### 8. Evaluation — **C** (most rigorously verified: 10/10 gaps confirmed)
**Book (Ch 7):** Triangulate benchmarks; metrics-driven development; LLM-judge pairwise + bias-mitigated + ~80% human agreement; evaluate RAG as a whole system; decontaminate; save intermediate artifacts.
**System:** Sophisticated for a homelab (LLM-judge + dual-judge calibration + TPR/TNR vs human labels + full RAGAS + 3-set discovery/regression/holdout model + reproducibility hygiene).
**Gaps (all confirmed):** ① judge-vs-human calibration doubly dead (wrong column `feedback` vs `feedback_type`, + no cron); ② overfit detector compares the regression set to itself; ③ golden-test "eval" validates JSON shape, not behavior (T1–T30 never execute scenarios); ④ RAGAS golden run is a near-tautology (`answer = ground_truth`); ⑤ single judge / absolute / no jury / no bias mitigation; ⑥ calibration frozen at the 85% "do-not-chart-together" boundary; ⑦ `answer_relevance` 0.65 never surfaced; ⑧ pervasive silent-failure wrapping hides eval breakage; ⑨ judge JSON regex can't parse nested braces; ⑩ no decontamination / near-duplicate check.
**Top fixes:** fix the dead-column bugs + the self-comparing flywheel (low/high); make `golden-test-suite` execute scenario assertions (high/high); feed the agent's *real* answer into RAGAS + surface `answer_relevance` (med/high); add pairwise + a 2-model jury + cron'd calibration (high/med); replace `|| true` with loud `chatops_eval_step_failed{step}` metrics (low/med).

### 9. Inference optimization — **B**
**Book (Ch 8):** Decompose latency into TTFT/TBT/TPS/TPOT (output streams); stack KV-cache + continuous batching + speculative decoding + FlashAttention/PagedAttention; quantization as a deliberate tier.
**System:** Off-the-shelf, so QAT/attention-kernel work is N/A; the analog is local Ollama quantized models + 4 circuit breakers + a RAG latency budget (`SEARCH_BUDGET_S=10`, `RAGLatencyP95High`). KV-cache `num_ctx` sizing is correct.
**Gaps (4 confirmed / 1 overstated):** ① no TTFT/TBT/TPS/TPOT anywhere; ② *(overstated)* no latency SLO on the agent (Anthropic) path (there *is* a per-session process-kill budget + `chatops_session_duration` metric, just no alert); ③ FAISS warm index never read; ④ single-stream serving (4 rerank POSTs not batched; no `OLLAMA_NUM_PARALLEL`); ⑤ local quantization tier undocumented/unpinned (no GGUF `Qx_K_M` provenance).
**Top fixes:** emit session TTFT from the stream-json init→first-assistant delta (low/med); wire the FAISS index (med/med); pin + document the GGUF quantization tier per model (low/med).

### 10. Deployment — **B / B+** (critic: over-penalized)
**Book (Ch 10):** Choose topology by four pillars; reliability + latency (not accuracy) decide success; monitor over sliding windows with threshold alerts; least-privilege IAM.
**System:** n8n background-launch + SSH dispatch + 30s progress polling + a Wait-for-PID loop — a coherent async-serving topology. `gateway-watchdog.sh` (5-min cron) already alerts on n8n-down / dead workflows / zombie executions / stale locks with auto-heal.
**Gaps (1 confirmed / 3 overstated):** ① *(overstated)* no serving-path alerting — `gateway-watchdog.sh` covers most of it; the true residue is no Prometheus failure-rate alert on the Runner; ② *(confirmed)* single-host SPOF with non-durable `/tmp` state (PID/inject/JSONL lost on LXC restart); ③ *(overstated)* `--dangerously-skip-permissions` on every launch (mitigated by PreToolUse hooks); ④ *(overstated)* no latency decomposition.
**Top fixes:** Prometheus alert on `n8n_workflow_execution_failures_total{workflow='NL - Claude Gateway Runner'}` (low/high); persist `(issue,PID,session_id,slot)` into the live DB at launch for restart recovery (med/high); track session TTFT + wall-clock as an SLO (med/med).

### 11. MLOps / LLMOps principles — **B → B-/C+** (critic: slightly generous)
**Book (Ch 11):** Version code/model/data independently; 6 test types; CI/CD with a behavioral gate; reproducibility via versioned inputs + seeding; staging→prod.
**System:** A genuinely MLOps-grade schema-version registry; a targeted post-incident Code-node validator; a real merge-blocking `eval-regression` job; a 51-suite QA harness with timeout guards.
**Gaps (6 confirmed / 2 overstated):** ① Code-node validator unenforced (pure human discipline — the exact gap behind the 14h outage); ② *(overstated)* the only blocking gate validates eval-set shape, not behavior; ③ 51-suite QA harness in neither CI nor cron; ④ no staging/prod separation + no Runner failure alert; ⑤ *(overstated)* infragraph topology tables outside `schema_version`; ⑥ unpinned session model; ⑦ `cost_usd` currency corruption; ⑧ two fresh-restore tables exist only in migrations, not `schema.sql`.
**Top fixes:** wire the Code-node validator into a blocking CI job + pre-push hook (low/high); make `eval-regression` behavioral, not a shape check (med/high); cron the 51-suite QA + a CI smoke subset (low/high); install the Runner failure alert + a minimal replay/staging gate (med/high).

### 12. Prompt monitoring & observability — **B**
**Book (Ch 11/App):** Full-trace prompt monitoring (user input + prompt template + version + retrieved docs + answer) is the core LLMOps primitive; monitoring ≠ observability (alarm + diagnose); version prompt templates.
**System:** OTel GenAI-semconv spans → OpenObserve + `otel_spans`/`tool_call_log`/`session_transcripts`/`prompt_scorecard`; `parse-tool-calls.py` computes per-tool durations.
**Gaps (all confirmed):** ① traces capture **skeleton, not content** — no query / RAG-enriched prompt / retrieved-doc ids / answer in any span; ② **zero alerting** on the entire trace/tool/scorecard surface (monitoring without alarms); ③ OTel tool spans have no measured duration (`endTime=''`), no TTFT/TBT/TPOT; ④ `trace_id = md5(issue_id)` collides on re-triage (one trace per issue); ⑤ **hardcoded OpenObserve credential committed** to git (and mirrored public); ⑥ prompt templates not versioned as artifacts tied to traces.
**Top fixes:** add a CONTENT trace (query + enriched prompt + retrieved-doc ids + answer as a linked span set) — the single highest-value chapter gap-closer (med/high); alert on the trace/prompt surface + exporter-stale dead-man (low/high); populate tool-span durations from `tool_call_log` (med/med); make `trace_id` collision-safe (issue_id + session_id) (low/med); move the OpenObserve credential to `.env` + rotate (low/med).

---

## Prioritized roadmap

Ordered by the critic's "closes the most confirmed HIGH gaps at once" logic. Everything in P0–P1 reuses machinery that already exists in-repo.

### P0 — close-the-loop (low effort, high value, fixes the most gaps)
1. **Honor `expires_at` in Build Prompt** (one-line filter change) + cron `prompt-improver.py --expire`/`--report` + replace the phantom `--rollback` with a real revert. *(fixes theme 7 ①②③, theme 8 ②, cross-cutting 1+4)*
2. **Fix the `cost_usd` currency bug end-to-end** (store true USD or rename + EUR view; correct the Prometheus HELP) + extract one `scripts/lib/pricing.py`. *(fixes theme 2 ①②, theme 11 ⑦, cross-cutting 2)*
3. **Wire `validate-n8n-code-nodes.sh` into a blocking CI job + pre-push hook.** *(fixes theme 11 ①, the 14h-outage class)*
4. **Delete the `REWRITE_MODEL:467` shadow line.** *(fixes theme 5 ④ / theme 4)*
5. **Move the committed OpenObserve credential to `.env` + rotate.** *(fixes theme 12 ⑤)*

### P1 — the pre-ship gate + the dead read-path (medium effort, high value)
6. **Stand up the offline eval-quality CI gate** — run a behavioral subset of `run-qa-suite.sh` + the RAGAS golden set as pass/fail (not JSON-shape), fix the regression/holdout self-comparison, and make T1–T30 execute scenario assertions. *(the single most valuable item; fixes theme 8 ②③, theme 11 ②③, cross-cutting 3)*
7. **Wire the FAISS (or `sqlite-vec`) read path into `kb-semantic-search.py`.** *(fixes the O(N) scan across themes 3/4/5/9; the ~13s p95; cross-cutting 1)*
8. **Collapse the `gateway.db` split-brain** via a one-time merge + a `scripts/lib.get_db()` connection factory all writers import. *(fixes theme 1 ①, the broken Bridge resume/lock path)*
9. **Add a CONTENT trace** (query + enriched prompt + retrieved-doc ids + answer) + alerts on the trace/prompt surface. *(fixes theme 12 ①②③)*

### P2 — registry, lineage, reliability (medium, medium-high value)
10. Pin the session agent `--model` + stamp model-id/graph-hash on each `infragraph_predictions` row. *(themes 1③/6/11; cross-cutting 6)*
11. Make `index-memories.py` incremental via `content_hash` + add an embedding model/dim stamp + a write-path dimension guard. *(theme 3 ②, theme 4; cross-cutting 5)*
12. Register the JSON-payload tables (`otel_spans`, `graph_*`, `ragas_evaluation`, `prompt_scorecard`, `llm_usage`) in `schema_version`. *(cross-cutting 5)*
13. Add metadata pre-filtering + a lightweight self-query extractor to the retriever. *(theme 5 ①②)*
14. Prometheus alert on Runner execution failures + persist session state for restart recovery + cost-budget alert. *(themes 2④/10①②; SPOF)*
15. Add judge-bias mitigation (pairwise + 2-model jury + cron'd calibration) and feed RAGAS the agent's real answer. *(theme 8 ④⑤⑦)*

### P3 — documentation honesty
16. "No fine-tuning" ADR + `book-applicability-map.md` (Ch 5–6/QAT N/A-by-design); auto-generate the provenance registry from live state + a drift check; reconcile the RAG/DLI/provenance docs with live code.

---

## Methodology & honesty notes

- Grades reflect **adherence to the book's properties for an operations system**, not feature parity with the LLM-Twin reference project. Training-side themes are N/A by design and say so.
- Every gap was adversarially re-verified against committed repo state; verdicts (`confirmed`/`refuted`/`overstated`) are shown inline. **Zero gaps were refuted** — the strongest signal that the findings are real — but several were `overstated` (real-but-narrower), and the per-theme grades were calibrated by the critic accordingly (Deployment up, MLOps-principles down).
- The deepest finding is structural, not a bug list: this platform's engineering instincts are *excellent* — it builds the right machinery (FTI-shaped pipelines, a falsifiable causal world-model, RRF+rerank retrieval, RAGAS, schema-versioning, OTel traces). Its gap to the book is almost entirely in **connecting the joints**: honoring expiry, reading the index, enforcing the validator, gating before ship. The fixes are disproportionately cheap relative to their value precisely because the hard parts are already built.
