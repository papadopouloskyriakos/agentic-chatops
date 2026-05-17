# RAG Pipeline

> 3-channel hybrid retrieval. Compiled 2026-05-06 00:48 UTC.

## Channels

1. **Hybrid Semantic Search (RRF)** — nomic-embed-text 768 dims + keyword LIKE, blended via Reciprocal Rank Fusion
2. **Deterministic Hostname Routing** — claude-knowledge-lookup.sh pattern-matches hostname to CLAUDE.md files
3. **XML-Tagged Injection** — `<incident_knowledge>`, `<lessons_learned>`, `<operational_memory>` tags

### CLI-session RAG capture pipeline

IFRNLLEI01PRD-646/-647/-648 ship a 3-tier pipeline that routes interactive
Claude Code CLI sessions (no YT webhook, no Runner workflow) into the same
RAG tables that agentic Session End populates.

**Tier 1 (-646):** `scripts/backfill-cli-transcripts.sh` — cron-safe wrapper
around `archive-session-transcript.py`. Raised defaults: `--limit 50`,
`--embed`, byte-offset watermark at
`~/gitlab/products/cubeos/claude-context/.cli-transcript-watermark.json`,
`--oldest-first` drains the ~2,300-file backlog oldest-first so everything
eventually lands. Each JSONL becomes `issue_id='cli-<uuid>'` in
`session_transcripts`; sessions with >5000 assistant chars also get a
doc-chain refined summary row at `chunk_index=-1`.

**Tier 2 (-647):** `scripts/extract-cli-knowledge.py` — reads the
`chunk_index=-1` summaries, POSTs each to gemma3:12b (Ollama) with
`format=json` asking for `{root_cause, resolution, subsystem, tags,
confidence}`, inserts into `incident_knowledge` with `project='chatops-cli'`
and a nomic-embed-text embedding. Idempotent via a LEFT-JOIN / NOT-EXISTS
query. Breaker-aware via `rag_synth_ollama`. Zero external cost.

**Tier 3 (-648):** `scripts/parse-tool-calls.py` — `extract_issue_id_from_path()`
gained a CLI fallback: files under `~/.claude/projects/` now resolve to
`issue_id='cli-<uuid>'` so `tool_call_log` rows join back to
`session_transcripts` cleanly. The backfill chains `parse-tool-calls.py`
after archive for each file.

**Retrieval weighting:** `kb-semantic-search.py` has new constant
`CLI_INCIDENT_WEIGHT` (default `0.75`, env override). The main RRF semantic
ranker multiplies sim by this value for rows where `project='chatops-cli'`,
so real infra incidents still win tie-breakers against CLI-extracted
knowledge.

**Cron INSTALLED** (verified 2026-04-24 on `nl-claude01`):
```
30 4 * * * /app/claude-gateway/scripts/backfill-cli-transcripts.sh --embed --oldest-first --limit 50 >> /home/app-user/logs/claude-gateway/cli-transcript-backfill.log 2>&1
```
Firing nightly. 2026-04-24 04:30 UTC run processed 50 files → 255 transcript chunks + 2831 tool-call rows + 25 incident_knowledge extractions (25 inserted, 1 skipped, 1 failed, elapsed 258s).

**QA:** `scripts/qa/suites/test-646-cli-session-rag-capture.sh` — 12/12
PASS in isolation. Covers backfill flags, watermark roundtrip, parse-tool
CLI path inference, extractor tag sanitizer, fetch_pending idempotency, and
CLI_INCIDENT_WEIGHT guards.

**Soak-test run (2026-04-20):** 10 files processed, 12 transcript chunks
+ 245 tool-call rows + 4 summaries + 4 incident_knowledge rows extracted.
Gemma correctly classified the extractions: one summary of *this* session
came back as `subsystem=sqlite-schema` with
`tags=[schema,migration,versioning,data,script,reasoning]` and confidence
0.95.

**Runbook:** [`docs/runbooks/cli-session-rag-capture.md`](../../../../gitlab/n8n/claude-gateway/docs/runbooks/cli-session-rag-capture.md).

### DLI RAG Course Slides

NVIDIA DLI course deck "Building RAG Agents with LLMs" (188 slides, 46 MB) lives at `docs/DLI-RAG-Slides.pptx` (moved from `/tmp/` on 2026-04-17).

Course structure — useful when reasoning about this project's own RAG pipeline:

- Part 1: Environment (Docker microservices, Gradio frontend)
- Part 2: LLM Services (NGC / OpenAI gateway, `ChatNVIDIA` vs `ChatOpenAI`, `integrate.api.nvidia.com`, `api.nvcf.nvidia.com/v2/nvcf`)
- Part 3: LangChain LCEL (`prompt | llm | StrOutputParser()`, `.invoke` vs `.stream`)
- Part 4: Running State Chain (`RunnableAssign` / `RunnableBranch` / `RunnableLambda`, airline chatbot pattern, four paradigms: Unstructured Generation / Structured Retrieval / Guided Generation / Tool Choice)
- Part 5: Documents (chunking, stuffing, map-reduce, refinement, knowledge graph construction + traversal, LangGraph tangent)
- Part 6: Embeddings (asymmetric query/doc model `nvolve-29k`, bi-encoder vs cross-encoder, symmetric vs asymmetric)
- Part 6.4: Semantic guardrails (classifier + branch in embedding space)
- Part 7: Vector DBs (FAISS -> Milvus standalone -> Milvus K8s cluster, Reranker, LongContextReorder, Query Augmentation, **RAG Fusion**, Tool-Selection Agent)
- Part 8: Evaluation (synthetic Q/A generation, pairwise LLM-as-a-judge, **RAGAS** `RagasEvaluatorChain` -- faithfulness metric, already in use in this project)

Overlap with this project:
- Our **5-signal RRF RAG** covers Part 7's "RAG Fusion" with added wiki + transcript + chaos signals.
- Our **RAGAS evaluation** (faithfulness 0.88, precision 0.86, recall 0.88) is the same framework linked in slide 182-184.
- Our **semantic guardrails** via `unified-guard.sh` mirror Part 6.4's classifier/branch pattern.
- Our **HyDE fallback** in `kb-semantic-search.py` is the "Rephrase as Hypothesis" pattern from slide 165.

Consult this deck when extending the RAG stack or explaining RAG concepts to stakeholders.

### knowledge_injection

## CLAUDE.md + Memory Knowledge Injection (2026-04-06)

Both ChatOps/ChatSecOps tiers now aware of procedural knowledge from repos and Claude memory files.

### What was added
- **claude-knowledge-lookup.sh** — hostname→CLAUDE.md routing (pve/, docker/, network/, k8s/, native/, edge/) + feedback memory extraction. Memories output first (survive 2000-char truncation). Called at Step 2-kb in infra-triage, k8s-triage, correlated-triage.
- **Build Prompt enrichment** — `claudeMdGuidance` (targeted CLAUDE.md file paths per hostname) + `memorySection` (auto-retrieved feedback rules). Query Knowledge extracts `MEMORY_START/END` block.
- **openclaw-repo-sync.sh** — `*/30` cron on nl-openclaw01. Pulls 23 repos + syncs 51 feedback memories (SSH+tar) + gateway.db read replica (scp).

### Architecture
- All CLAUDE.md reads are LOCAL on both hosts (repos synced by cron, max 30min staleness).
- Semantic search (kb-semantic-search.py) runs LOCAL on OpenClaw — Ollama on nl-gpu01 reachable on same VLAN 181 subnet. No SSH for reads.
- SSH to app-user only for WRITES (SQLite inserts, triage.log appends, CodeGraph).
- Docker compose on openclaw01 has bind mounts: `/root/.claude-memory:/home/node/.claude-memory:ro` + `/root/.claude-data:/home/node/.claude-data:ro`.

### Compiled Wiki KB (2026-04-09)
- **wiki-compile.py** — compiles 7+ sources (70 memories, 37 CLAUDE.md, 28 incidents, 7 lessons, 88 openclaw_memory, 23 docs, 15 skills, 5 dashboards, ~5,200 lab files) into 45 wiki articles at `wiki/`.
- **3-signal RRF** — wiki articles embedded in `wiki_articles` SQLite table (45 rows, nomic-embed-text 768 dims). 3rd ranking signal in `kb-semantic-search.py` hybrid search alongside semantic + keyword.
- **Health checks** — `--health` mode detects staleness (line-number rot in memories) + coverage gaps (incidents without lessons).
- **Cadence** — daily 04:30 UTC cron + on-demand `/wiki-compile` skill. Incremental via SHA-256 checksums.
- **Auto-propagation** — wiki/ is in claude-gateway repo → `openclaw-repo-sync.sh` picks it up on OpenClaw within 30min.

### Pattern impact
Memory (8): A→A+ (compiled wiki = organized semantic memory). Learning (9): A→A+ (health checks surface knowledge gaps). RAG (14): A→A+ (3-signal RRF: semantic + keyword + wiki articles).

### Key paths on openclaw01
- Repos: `/root/gitlab/` (23 repos, mirrors app-user)
- Memories: `/root/.claude-memory/{infrastructure-nl,infrastructure-gr,gateway}/`
- DB replica: `/root/.claude-data/gateway.db`
- Sync script: `/root/openclaw-repo-sync.sh`
- Sync log: `/tmp/openclaw-repo-sync.log`
- Cron: `*/30 * * * * /root/openclaw-repo-sync.sh`

### rag_circuit_breakers

## Library

`scripts/lib/circuit_breaker.py` — three-state breaker (CLOSED / OPEN / HALF_OPEN) per Netflix Hystrix pattern. Thread-safe within process, SQLite-backed state shared across processes via `circuit_breakers` table in `gateway.db`. Decorator API (`@cb.wrap(fallback=...)`) + imperative API (`if not cb.allow(): ...; record_success/record_failure`). Persist-on-init writes a baseline row so the Prometheus exporter sees every breaker even before the first failure.

## Active breakers (2026-04-19)

All wired in `scripts/kb-semantic-search.py`:

| Name | Wraps | Threshold | Cooldown | Fallback |
|---|---|---|---|---|
| `rag_rerank_crossencoder` | `_rerank_via_crossencoder` (bge-reranker-v2-m3 at nl-gpu01:11436) | 3 | 90s | `None` → caller drops to Ollama rerank |
| `rag_embed_ollama` | `_embed_raw` (nomic-embed-text) | 5 | 120s | `None`-vectors → caller handles gracefully |
| `rag_synth_haiku` | `_call_haiku_synth` (Anthropic /v1/messages) | 3 | 180s | empty string → caller degrades to qwen |
| `rag_synth_ollama` | `_call_qwen` in `synthesize_answer` (qwen2.5:7b) | 4 | 120s | empty string |

Pattern is always imperative, not decorator — preserves each call site's existing return-on-failure contract (critical for `ex.map()` pipelines that would propagate exceptions).

## Observability

- `scripts/write-circuit-breaker-metrics.sh` cron `*/5` writes to `/var/lib/node_exporter/textfile_collector/circuit_breaker_metrics.prom`
- Three gauges: `circuit_breaker_state` (0=closed, 1=half_open, 2=open), `circuit_breaker_failure_count`, `circuit_breaker_opened_timestamp_seconds`
- Prometheus alerts in `prometheus/alert-rules/rag-health.yml`:
  - `CircuitBreakerOpen` — fires after a breaker has been OPEN for ≥10 min
  - `CircuitBreakerMetricAbsent` — absent-guard (fires if metric disappears for 2 h)
- CLI: `cd scripts && python3 -m lib.circuit_breaker list` (shows all breakers + state + age). Reset with `... reset <name>`.

## Not wrapped (deliberately)

- `rewrite_query` / `rewrite_query_multi` (L349, L447 in kb-semantic-search.py) — cheap, empty-list fallback already graceful, low operational value.
- Ollama yes/no rerank inside `rerank_candidates` (L601) — is itself the fallback for `rag_rerank_crossencoder`; wrapping it would put two breakers in series, circular.

## How to apply

- When adding a new external API call, wrap it: declare a CircuitBreaker at module top, call `allow()` before the request, `record_success()` on 2xx, `record_failure(exc)` in the `except`. Match the imperative pattern already used; avoid the decorator form in places where exceptions must be swallowed for caller compatibility (most RAG sites).
- When a breaker trips in production, the fast check is `python3 -m lib.circuit_breaker list` to see current state + age. `reset <name>` clears it if the upstream has recovered and you don't want to wait for the cooldown probe.
- The quote-balance heuristic was tried and removed from `validate-n8n-code-nodes.sh` — escaped quotes in strings produce false positives. `node --check` + `new Function()` parse are the authoritative checks; rely on those.

## Commits

Gateway repo main:
- `d6e4e76` library + first wrap (rerank service)
- `6d10b0b` 3 more wraps (embed, haiku synth, ollama synth)

### Q2 cross-chunk synthesis in RAG pipeline

## What

`synthesize_answer()` in `scripts/kb-semantic-search.py` — activated when cross-encoder rerank max score falls below `SYNTH_THRESHOLD` (default 0.7). Produces a direct 2–3 sentence answer with `[N]` citations, prepended to output as `source=synthesis` row.

## Why

Meta-queries ("how many RRF signals?", "current RAG scores?", "EUR cost cap?") need information spread across 3+ chunks. No single doc answers them, so cross-encoder max score is <0.7. Before Q2 these were consistent misses (5 of the hardest 20 queries).

## Key design choices

1. **Fresh candidates** — bypass fusion pool because llama3.2:1b rewrite sometimes hallucinates (observed "RFM" substituted for "RRF"), polluting candidates. `_synth_fresh_candidates()` re-probes `wiki_articles` + `incident_knowledge` using raw query embedding only.
2. **Trigger threshold 0.7** (not 0.3): many relevant-but-indirect matches score ~0.5; at 0.3 we rarely synthesized.
3. **qwen2.5:7b** at `num_ctx=4096` (not 1024) so it can fit 10 chunks × 500 chars + instructions. Takes ~2s warm.
4. **NO_ANSWER escape hatch**: if chunks truly don't contain an answer, model returns `NO_ANSWER` and we skip rather than fabricating.
5. **Prepend, don't replace**: raw retrieved rows still returned after the synthesis row. Downstream consumers (and judge) can cross-check citations.

## Measured impact

50-query hard eval, 3 deterministic runs:
- judge hit@5: 48% → 61% (+13 points)
- substr hit@5: 30% → 44% (synthesis often contains exact strings)
- p50 latency: 3.0s → 3.6s
- p95 latency: 4.0s → 5.1s

## Env controls

- `SYNTH_ENABLED=1` (default on)
- `SYNTH_THRESHOLD=0.7` (cross-encoder max below → trigger)
- `SYNTH_MODEL=qwen2.5:7b` (swap to `haiku` via extension for higher quality at cost)

## How to disable

Set `SYNTH_ENABLED=0`. Pipeline falls back to plain rerank.

## Verified 2026-04-18

H16 ("current RAG scores") — pre-Q2: MISS. Post-Q2: synthesis produced "Faithfulness: 1.000 [3] — Context Precision: 0.964 [3] — Context Recall: 0.995 [3]", judge hit.

### Unified Knowledge Base Wiki

Compiled wiki at `wiki/` in claude-gateway repo (2026-04-09). 45 articles across 8 categories compiled from 7+ knowledge sources.

**Compiler:** `scripts/wiki-compile.py` — source readers for memory files (69), CLAUDE.md (37), SQLite tables (incident_knowledge 28, lessons_learned 7, openclaw_memory 87), docs (22), OpenClaw skills (15), Grafana dashboards (5), 03_Lab manifest (~5,200 files).

**Key features:**
- Incremental compilation via SHA-256 checksums in `wiki/.compile-state.json`
- Health checks: `--health` flag detects staleness (line number refs) + coverage gaps (incidents without lessons)
- RAG integration: wiki articles embedded in `wiki_articles` table (45 rows), 3rd signal in RRF fusion in `kb-semantic-search.py`
- On-demand: `/wiki-compile` skill
- Daily cron: 04:30 UTC (between 04:00 golden-test and 06:03 proactive-scan)

**Highest-value article:** `wiki/operations/operational-rules.md` — all 24 feedback memories compiled by domain (Config Safety, ASA/VPN, K8s, Deployment, Infra Ops, Data Integrity, General).

**Why:** No unified view of knowledge previously existed across 7+ fragmented stores. Inspired by Karpathy's LLM Knowledge Bases pattern.
