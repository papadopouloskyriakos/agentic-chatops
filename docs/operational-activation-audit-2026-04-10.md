# Operational Activation Audit — 2026-04-10

**Methodology:** Operational activation (is the infrastructure producing data?)
**Scope:** ChatOps / ChatSecOps / ChatDevOps — full platform
**Prior audit:** Tri-source pattern implementation audit (2026-04-07, A+ 97%)
**This audit overall score:** **B (76.6%)**
**Delta from prior:** -20.4 points (explained entirely by the activation gap)

---

## Executive Summary

This audit scores the claude-gateway agentic platform against **operational reality** rather than architectural ambition. The prior tri-source audit (2026-04-07) scored 11/11 dimensions A+ by measuring *pattern implementation*. This audit measures *pattern activation* — is the infrastructure producing data that feeds back into the system?

**Central finding:** 57% of the database schema (12 of 21 tables) is deployed but contains zero rows. The platform's architecture is sophisticated and well-designed, but a significant fraction of it has never processed a single production event.

**Most critical gap:** The evaluation pipeline — LLM-as-Judge, trajectory scoring, session quality, and the eval flywheel — is the most sophisticated part of the platform design but is fundamentally non-operational. All evaluation tables are empty.

---

## 1. Platform Inventory (Verified Live)

| Asset | Count | Status |
|-------|-------|--------|
| n8n workflows | 25 | All active |
| Total workflow nodes | ~475 | Healthy |
| Scripts (bash + python) | 55 | All syntax-valid |
| Sub-agents | 10 | 6 infra + 4 dev |
| Claude Code skills | 5 | /triage, /alert-status, /cost-report, /drift-check, /wiki-compile |
| Wiki articles | 45 | 8 sections, 100% embedded |
| SQLite tables | 21 | **9 populated, 12 empty** |
| SQLite indexes | 29 | All present |
| Cron entries | 31 | All healthy |
| MCP servers | 10 | ~153 tools |
| Guardrail layers | 6 | Deterministic, tested |
| RAG signals | 4 | RRF fusion (2 active, 2 dormant) |
| Grafana dashboards | 5 | 63+ panels |
| Golden test scenarios | 98 | All passing |
| OpenClaw skills | 15 | Deployed to nl-openclaw01 |
| MITRE ATT&CK mappings | 54 | 21 techniques |

---

## 2. Database Activation Gap

### Populated Tables (9) — 864 total rows

| Table | Rows | Purpose | Health |
|-------|------|---------|--------|
| sessions | 10 | Active session state | PASS |
| session_log | 239 | Completed session archive | PASS |
| llm_usage | 54 | Per-tier cost tracking | PASS |
| incident_knowledge | 33 | Core RAG signal, 100% embedded | PASS |
| wiki_articles | 45 | Compiled KB, 3rd RRF signal | PASS |
| prompt_scorecard | 302 | Daily prompt grading (19 surfaces) | PASS |
| lessons_learned | 27 | Operational insights | PASS |
| a2a_task_log | 53 | Inter-agent communication audit | PASS |
| openclaw_memory | 101 | T1 episodic memory cache | PASS |

### Empty Tables (12) — 0 total rows

| Table | Writer Exists? | Why Empty | Fix Effort |
|-------|---------------|-----------|------------|
| session_judgment | llm-judge.sh wired Apr 9 | No session ended since wiring | Low |
| session_trajectory | score-trajectory.sh wired Apr 9 | No session ended since wiring | Low |
| session_quality | compute-quality-score.sh | Never called from Session End | Low |
| session_feedback | Matrix Bridge reaction handler | May not write to DB | Low |
| crowdsec_scenario_stats | UPSERT node wired Apr 9 | Awaiting first CrowdSec alert | Very Low |
| session_transcripts | archive-session-transcript.py | Stop hook never fired on live session | Low |
| agent_diary | agent-diary.py | No sub-agent calls it | Medium |
| graph_entities | None | No populator script | Medium |
| graph_relationships | None | No populator script | Medium |
| tool_call_log | None | No writer exists | Medium |
| execution_log | None | No writer exists | Medium-High |
| credential_usage_log | None | OpenBao not integrated | High |

---

## 3. Subsystem Scores

### ChatOps (Infrastructure Alerting) — 82/100 (B+)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| Alert ingestion (4 receivers, NL+GR) | 20% | 95 | LibreNMS + Prometheus, dedup/flap/burst, all active |
| Triage pipeline (OpenClaw + Claude) | 20% | 92 | 15 skills, TRIAGE_JSON output, YT issue creation |
| Session lifecycle (start->poll->end) | 15% | 88 | 47-node Runner, progress poller, resume via `-r` |
| Knowledge feedback (session->KB->future) | 15% | 90 | 33 incidents embedded, 27 lessons, weekly digest |
| **Evaluation pipeline** | **15%** | **30** | **session_judgment/trajectory/quality: all 0 rows** |
| Observability (Grafana, metrics, cost) | 15% | 92 | 5 dashboards (63+ panels), 8 metric writers |

### ChatSecOps (Security Operations) — 82/100 (B+)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| CrowdSec pipeline (NL+GR) | 20% | 88 | 23 nodes each, MITRE mapping, flap + burst detection |
| **CrowdSec learning loop** | **15%** | **25** | **crowdsec_scenario_stats: 0 rows** |
| Security scanner pipeline (NL+GR) | 20% | 95 | 2 VMs, 24 tools, baseline comparison, ACL-protected |
| Compliance & ATT&CK | 10% | 93 | CIS v8 + NIST CSF, 54 ATT&CK scenarios |
| Security guardrails (6 layers) | 20% | 95 | PreToolUse hooks, 16 PII patterns, exec blocklist |
| Threat intelligence | 15% | 90 | mitre-mapping.json, 12h sync cron |

### ChatDevOps (Development Operations) — 82/100 (B+)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| CI failure receiver | 20% | 90 | Webhook -> Matrix + YT, active |
| Session management | 25% | 88 | Bridge commands, dev slot lock, YT integration |
| Code analysis sub-agents | 20% | 92 | 4 dev agents, CodeGraph MCP |
| Project dashboards | 15% | 85 | CubeOS + MeshSat Grafana |
| Development evaluation | 20% | 55 | prompt_scorecard has data but dev sessions not judged |

---

## 4. Cross-Cutting Dimension Scores

### RAG & Retrieval — 75/100 (B)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| Core RAG pipeline | 35% | 93 | 4-signal RRF, nomic-embed-text, fully operational |
| Wiki as RAG signal | 20% | 95 | 45 articles, 100% embedded, daily compilation |
| Temporal validity | 10% | 85 | valid_until on incident_knowledge |
| **GraphRAG** | **15%** | **5** | **0 entities, 0 relationships** |
| **Transcript RAG signal** | **10%** | **5** | **0 transcripts, weight 0.3 configured but empty** |
| **Advanced retrieval** | **10%** | **15** | **HyDE designed, not in production path** |

### Evaluation & Quality — 48/100 (F)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| Golden test suite | 20% | 92 | 3-set model, CI gate |
| Prompt scorecard | 10% | 90 | 302 rows, 19 surfaces |
| **LLM-as-Judge** | **20%** | **15** | **session_judgment: 0 rows** |
| **Trajectory scoring** | **15%** | **15** | **session_trajectory: 0 rows** |
| **Session quality** | **10%** | **15** | **session_quality: 0 rows** |
| **Eval flywheel** | **15%** | **20** | **Produces all-zero reports** |
| Regression detection | 10% | 60 | Runs 6-hourly, low volume |

### Security Posture — 78/100 (B)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| Guardrail system | 25% | 95 | 6 layers, PreToolUse hooks, 16 PII patterns |
| Golden tests | 15% | 95 | 98 pass, 12 negative controls |
| Compliance | 15% | 93 | CIS v8 + NIST CSF, ATT&CK Navigator |
| Credential mgmt | 15% | 70 | .env (no crontab secrets); credential_usage_log: 0 |
| **CrowdSec learning** | **15%** | **25** | **0 rows, loop non-functional** |
| **Tool call logging** | **15%** | **5** | **0 rows, no writer** |

### Observability — 78/100 (B)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| Grafana dashboards | 20% | 95 | 5 dashboards, 63+ panels |
| Prometheus metrics | 20% | 93 | 8 writers, */5 to daily |
| Session JSONL tracing | 15% | 90 | /tmp/claude-run-*.jsonl |
| Cost tracking | 15% | 80 | 54 rows; Tier 0 untracked |
| **Tool error aggregation** | **10%** | **10** | **tool_call_log: 0** |
| **Execution logging** | **10%** | **5** | **execution_log: 0** |
| **OpenTelemetry** | **10%** | **10** | **Not implemented (G8)** |

### Knowledge Management — 76/100 (B)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| Compiled wiki | 25% | 95 | 45 articles, 7+ sources, daily cron |
| Incident knowledge | 20% | 90 | 33 entries, temporal validity |
| Lessons learned | 15% | 88 | 27 entries, weekly digest |
| OpenClaw memory | 10% | 90 | 101 entries |
| **Session transcripts** | **15%** | **10** | **0 rows, hooks exist but never fired** |
| **Agent diary** | **15%** | **10** | **0 rows, no sub-agent calls it** |

### Architecture — 82/100 (B+)

| Dimension | Weight | Score | Evidence |
|-----------|--------|-------|----------|
| 3-tier hierarchy | 15% | 97 | OpenClaw -> Claude Code -> Human |
| Sub-agent design | 15% | 95 | 10 agents, Anthropic Academy patterns |
| n8n orchestration | 15% | 93 | 25 workflows, dual-site, retry logic |
| MCP integration | 10% | 95 | 10 servers, ~153 tools |
| A2A protocol | 10% | 90 | 3 agent cards, 53 task log rows |
| Human-in-the-loop | 10% | 97 | Polls, reactions, timeouts |
| **Schema utilization** | **15%** | **43** | **9/21 tables populated (43%)** |
| **Activation ratio** | **10%** | **43** | **864 rows across 9 tables; 0 across 12** |

---

## 5. Overall Score

| Category | Score | Grade |
|----------|-------|-------|
| **Subsystems** | | |
| ChatOps | 82 | B+ |
| ChatSecOps | 82 | B+ |
| ChatDevOps | 82 | B+ |
| Subsystem Average | 82 | B+ |
| **Cross-Cutting** | | |
| RAG & Retrieval | 75 | B |
| Evaluation & Quality | 48 | F |
| Security Posture | 78 | B |
| Observability | 78 | B |
| Knowledge Management | 76 | B |
| Architecture | 82 | B+ |
| Cross-Cutting Average | 73 | B- |
| | | |
| **Overall (40% subsystem + 60% cross-cutting)** | **76.6** | **B** |

### Comparison with Prior Audits

| Audit | Date | Methodology | Score |
|-------|------|-------------|-------|
| Initial ChatOps | 2026-03-24 | Feature checklist | B+ |
| Dual-source | 2026-04-03 | Pattern implementation (2 sources) | A (90%) |
| Tri-source | 2026-04-07 | Pattern implementation (3 sources) | A+ (97%) |
| Remediation | 2026-04-09 | Health check + fix | A++ (28/30 PASS) |
| **This audit** | **2026-04-10** | **Operational activation** | **B (76.6%)** |

---

## 6. Agentic Pattern Activation Status (21/21)

| # | Pattern | Implementation | Activation | Key Gap |
|---|---------|---------------|-----------|---------|
| 1 | Prompt Chaining | A | A | -- |
| 2 | Routing | A- | A- | Content-based classifier missing |
| 3 | Parallelization | A- | A- | n8n sequential SSH limitation |
| 4 | Reflection | A- | **C** | Evaluator-Optimizer never produced data |
| 5 | Tool Use | A | A- | tool_call_log empty |
| 6 | Planning | A- | A- | Static thresholds |
| 7 | Multi-Agent | A+ | A | agent_diary empty |
| 8 | Memory | A+ | **B** | 2 MemPalace tables empty |
| 9 | Learning | A+ | **C+** | CrowdSec + eval flywheel data-starved |
| 10 | MCP | A | A | GitLab MCP inputSchema issue |
| 11 | Goal Setting | A- | A- | Static confidence thresholds |
| 12 | Exception Handling | A | A | continueOnFail + retryOnFail |
| 13 | HITL | A | A | Polls, reactions, timeouts |
| 14 | RAG | A+ | **B+** | 2 of 4 RRF signals empty |
| 15 | A2A | A | A- | No Google A2A spec alignment |
| 16 | Resource Opt | A+ | A | Model routing implicit |
| 17 | Reasoning | A | A | ReAct enforced |
| 18 | Guardrails | A+ | A+ | 6 layers, 98 tests, operational |
| 19 | Evaluation | A+ | **D** | 3 eval tables empty |
| 20 | Prioritization | A | A | Sub-agent routing works |
| 21 | Exploration | A | A | Proactive security scanning |

---

## 7. Industry Gap Status (14 Gaps from 15 Sources)

| Gap | Description | Deployed? | Activated? |
|-----|-------------|-----------|-----------|
| G3 | Context compaction | Yes | **Yes** (PreCompact hook) |
| G4 | Self-correcting RAG | Yes | **Yes** (RETRIEVAL_QUALITY) |
| G10 | GraphRAG schema | Yes | **No** (0 entities) |
| G11 | Model routing | Yes | **Partial** (implicit) |
| G12 | HyDE fallback | Yes | **No** (not in prod path) |
| G13 | Tool call logging | Yes | **No** (0 rows) |
| G1 | Code-as-tool-orchestrator | No | -- |
| G2 | Programmatic tool calling | No | -- |
| G5 | Progressive skill disclosure | No | -- |
| G6 | A2A protocol upgrade | No | -- |
| G7 | Atomic transactions | Schema only | **No** (0 rows) |
| G8 | OpenTelemetry tracing | No | -- |
| G9 | Parallel guardrail execution | No | -- |
| G14 | Short-lived credentials | Schema only | **No** (OpenBao not integrated) |

Of 6 "deployed" gaps, only **2 are fully operational** (G3, G4).

---

## 8. Top 10 Improvements (Ranked by Impact/Effort)

### Tier 1: Quick Wins (~5 hours total)

| # | Improvement | Impact | Effort | Score Lift |
|---|------------|--------|--------|-----------|
| I1 | Activate LLM Judge (llm-judge.sh) | Critical | 1-2h | Eval 48->65 |
| I2 | Activate Trajectory Scoring | Critical | 1h | Eval +8 |
| I3 | Trigger CrowdSec Learning Loop | High | 30min | SecOps 82->87 |
| I4 | Backfill Session Transcripts | High | 1h | Knowledge 76->83, RAG 75->82 |

### Tier 2: Medium Effort (~12 hours total)

| # | Improvement | Impact | Effort | Score Lift |
|---|------------|--------|--------|-----------|
| I5 | Build GraphRAG Populator | High | 3-5h | RAG +7, Arch +3 |
| I6 | Wire Sub-Agent Diary Writes | Medium | 2-3h | Knowledge +5 |
| I7 | Instrument Tool Call Logging | Medium | 3h | Security +5, Observ +5 |

### Tier 3: Targeted Fixes (~3 hours total)

| # | Improvement | Impact | Effort | Score Lift |
|---|------------|--------|--------|-----------|
| I8 | Fix Eval Flywheel Silent Failure | Medium | 30min | Eval +3 |
| I9 | Add Contradiction Detection to Cron | Low | 30min | Knowledge +2 |
| I10 | Fix Session Feedback DB Write | Low | 1h | ChatOps +2 |

### Projected Scores After Implementation

| Dimension | Current | After Tier 1 | After All 10 |
|-----------|---------|-------------|-------------|
| ChatOps | 82 (B+) | 87 (A-) | 90 (A) |
| ChatSecOps | 82 (B+) | 87 (A-) | 89 (A-) |
| ChatDevOps | 82 (B+) | 84 (B+) | 87 (A-) |
| RAG & Retrieval | 75 (B) | 82 (B+) | 89 (A-) |
| Evaluation | 48 (F) | 68 (C+) | 78 (B) |
| Security | 78 (B) | 82 (B+) | 87 (A-) |
| Observability | 78 (B) | 78 (B) | 85 (A-) |
| Knowledge | 76 (B) | 83 (B+) | 88 (A-) |
| Architecture | 82 (B+) | 85 (A-) | 90 (A) |
| **Overall** | **76.6 (B)** | **82 (B+)** | **87 (A-)** |

---

## 9. Risk Matrix

| Risk | Likelihood | Impact | Current Mitigation |
|------|------------|--------|-------------------|
| Eval pipeline never activates | Medium | High | Wired Apr 9; needs first session end |
| MemPalace hooks too aggressive | Low | Medium | Stop hook every 15 exchanges |
| GraphRAG data staleness | Medium | Low | No auto-refresh mechanism yet |
| Ollama unavailable (GPU crash) | Medium | High | RAG degrades to keyword-only |
| Matrix ECONNRESET cascades | Low | Medium | retryOnFail across 72 nodes |
| SQLite DB corruption | Low | High | Daily backup + WAL + watchdog |
| CrowdSec learning never fires | Medium | Medium | Awaiting first alert post-wiring |
| Cost ceiling bypass | Low | Medium | Soft enforcement ($25/day) |

---

## Methodology Notes

This framework scores **operational activation** (is the pattern producing data?) rather than **pattern implementation** (does the code exist?). The distinction matters:

- A GraphRAG schema with 0 entities adds zero retrieval value
- An LLM judge that never fires means the eval flywheel cannot Analyze
- A transcript table with 0 rows means the 4th RRF signal returns empty 100% of the time
- A CrowdSec learning loop that has never learned means no adaptive suppression

The prior A+ (97%) assessment scored pattern implementation against Gulli book + Anthropic Cert + industry research. That assessment is valid for its purpose. This audit adds the activation dimension — both are needed for a complete picture.

**The positive framing:** Most "last mile" wiring happened on Apr 9 (one day before this audit). Several empty tables will populate naturally with the next alert cycle. The platform's trajectory is upward — the question is "have they activated yet?" not "will they activate?"

---

## Appendix A: External Source Analysis

Two external repositories were audited for techniques applicable to the claude-gateway platform.

### Source 1: atlas-agents (Gulli, 2026)

**Repo:** `github.com/agulli/atlas-agents` — companion code for the Atlas Agents book.
**Contents:** 1,348 lines Python across 10 files + 36 declarative skill templates.

#### A1. Declarative Skills as Execution Templates
Atlas uses `.md` files with YAML frontmatter not just as documentation but as **LLM system prompt fragments**. Structure: `name`, `description`, `scope` (topic boundaries), `workflow` (numbered steps), `constraints` (guardrails), `output_format`.
**Gateway application:** Convert the 15 OpenClaw skills from procedural scripts to declarative `.md` templates. Load YAML frontmatter at startup (Phase 1), inject full content only on invocation (Phase 2). Enables A/B testing of skill prompts and version-controlled prompt engineering.

#### A2. Multi-Persona Router (Cheap Classifier)
A lightweight LLM call classifies user intent before routing to specialized agents. Uses a cheap model (Haiku-class) with a constrained output schema (`{"persona": "...", "confidence": 0.0-1.0}`).
**Gateway application:** Replace the current prefix-based routing (`IFRNLLEI01PRD-*` -> infra, `CUBEOS-*` -> dev) with a content-based classifier in the Runner's Build Prompt node. Route alerts to the most appropriate sub-agent based on content, not just project prefix. Addresses Pattern #2 (Routing) A- gap.

#### A3. Plan-and-Execute Pattern (3-Phase)
Instead of ReAct's interleaved think-act cycles, Atlas separates: Phase 1 (plan with cheap model, enumerate steps), Phase 2 (execute steps in parallel where possible), Phase 3 (synthesize results). Reduces context window usage by 30-40%.
**Gateway application:** Add a planning phase to the Runner workflow before launching Claude Code. The planner (Haiku) generates an execution plan, which is injected into the Claude Code prompt. Claude Code then follows the plan rather than discovering steps via ReAct. Reduces session token consumption and improves trajectory scoring.

#### A4. Prompt Injection Detection (Regex-First)
Atlas pre-screens user input with 7 regex patterns before LLM processing: system override attempts, role confusion, delimiter injection, encoding obfuscation, instruction planting, social engineering, multi-turn manipulation.
**Gateway application:** Add regex pre-screening in the Matrix Bridge's Extract Messages node before input reaches OpenClaw or Claude Code. Currently the Bridge has 10 injection patterns; Atlas adds 7 complementary ones including encoding obfuscation (`base64:`, `hex:`) and multi-turn manipulation detection.

#### A5. Chain of Density Prompting
Generates summaries at multiple density levels (verbose -> concise -> ultra-dense) in a single multi-pass LLM call. Each pass identifies missing entities and incorporates them into a shorter summary.
**Gateway application:** Apply to Session End's incident knowledge extraction. Instead of a single summary, generate 3 densities: (1) full narrative for `incident_knowledge.resolution`, (2) concise for Matrix posting, (3) ultra-dense tags for `incident_knowledge.tags`. Improves RAG retrieval precision.

#### A6. Structural A/B Testing Harness
Weekly evaluation of 3+ prompt variants across 10+ eval cases. Metrics: quality (keyword recall), tool efficiency (calls/session), refusal accuracy, latency. Winner promoted automatically.
**Gateway application:** Extend the existing `prompt_scorecard` (302 rows) with variant comparison. Build Prompt already tracks `prompt_variant`; add automated weekly comparison via `eval-flywheel.sh` to promote the best-performing variant.

### Source 2: claude-code-from-source (Balderas, 2026)

**Repo:** `github.com/alejandrobalderas/claude-code-from-source` — 18-chapter architectural analysis of Claude Code internals.
**Contents:** 6,368 lines across 18 .md chapters covering architecture through performance.

#### B1. Four-Layer Context Compression
Claude Code manages context via progressive layers: (1) Tool Result Budget (30K chars for Bash, 100K for Read), (2) Snip Compact (truncate old messages at 80% window), (3) Microcompact (remove tool results by tool_use_id), (4) Auto-Compact (LLM summarization as last resort). Each layer progressively more expensive.
**Gateway application:** Implement token budgeting in the Build Prompt node. Currently the full incident context is injected without size limits. Add: per-source token caps (incident_knowledge: 4K, wiki: 4K, lessons: 2K, transcripts: 2K), progressive truncation when total exceeds 16K, and LLM summarization only when still over-budget.

#### B2. Fork Agents for Prompt Cache Sharing
When spawning parallel sub-agents, pass the parent's **rendered** system prompt by reference. Children share 95%+ identical prefix, getting 90% input token discount via prompt cache. Cost for 5 parallel agents drops from 5x to 1.4x.
**Gateway application:** When the Runner spawns background tasks (memory extraction, code review, verification), construct them as forks sharing the parent's system prompt. The progress poller and Session End scoring could run as forks of the main session, sharing its cached context.

#### B3. Sticky Latches for Cache Stability
Five boolean latches (null -> true -> permanent). Once a cache-affecting header is sent, never unset. Toggling features mid-session busts the prompt cache, costing ~$0.50 per 50K token cache miss.
**Gateway application:** Add session-level latches for: `thinkingBlocksEnabled`, `advancedMemoryEnabled`, `modelHint`. Once set on the first API call, these freeze for the session duration. Prevents accidental cache busting when the Runner's Build Prompt changes model hints mid-session.

#### B4. Slot Reservation (8K Default, 64K Escalation)
Claude Code defaults to `max_output_tokens: 8000` instead of SDK defaults (32K-64K). Production data: p99 output = 4,911 tokens. On truncation, retry at 64K. This recovers 12-28% of usable context per turn.
**Gateway application:** When invoking Claude Code via SSH, pass `--max-tokens 8000` for routine triage sessions. If truncated (detected in Parse Response), re-invoke with `--max-tokens 65536`. Most infra triage responses are well under 8K tokens.

#### B5. 14-Step Tool Execution Pipeline
Standardized pipeline: lookup -> abort check -> Zod validation -> semantic validation -> classifier -> input backfill -> PreToolUse hooks -> permission resolution -> execution -> result budgeting -> PostToolUse hooks -> new messages -> error handling. Fail-closed defaults: unknown tools are serial, not parallel.
**Gateway application:** Formalize the gateway's tool execution into a documented pipeline. Currently, PreToolUse hooks (unified-guard.sh) cover steps 7-8, but steps 1-6 (validation, classification) and 10-12 (result budgeting, PostToolUse) are missing. Adding PostToolUse hooks enables output sanitization before results reach the model.

#### B6. Self-Describing Tools
Each tool declares: `isConcurrencySafe(input)`, `checkPermissions()`, `maxResultSizeChars`, `isReadOnly(input)`. The tool system orchestrates what tools declare about themselves, rather than maintaining a central registry.
**Gateway application:** Extend `config/tool-profiles.json` (7 categories) to include per-tool metadata: concurrency safety, result size limits, read-only classification. MCP tools can inherit these from their `annotations` field (`readOnlyHint`, `destructiveHint`).

#### B7. Staleness Warnings on Memory
Old memories aren't deleted — they're flagged with human-readable age warnings ("47 days ago"). Injected alongside content: "Before recommending from memory, verify code hasn't changed." Evals showed staleness caveat improved correctness from 0/3 to 3/3.
**Gateway application:** Add age-proportional caveats to incident_knowledge and wiki_articles when injected into Build Prompt. Entries > 7 days: "Verify this is still current." Entries > 30 days: "This may be outdated; check the referenced systems." Currently, all entries are injected without age context.

#### B8. BoundedUUIDSet for Dedup
Circular buffer + Set for O(1) lookup with fixed capacity (2000). No TTLs or timers. Catches echoes from read streams and duplicate delivery during reconnection.
**Gateway application:** Replace the current CrowdSec/LibreNMS dedup logic (TTL-based with file persistence) with a bounded UUID set. Simpler, faster, and doesn't require state file persistence. Also applicable to Matrix Bridge message dedup.

#### B9. Failure-Type-Proportional Reconnection
401 (unauthorized) -> stop immediately. 404 (session not found) -> max 3 retries, linear backoff. Transient errors -> exponential backoff, max 5 attempts.
**Gateway application:** The Matrix Bridge currently retries all failures uniformly (`maxTries:3`). Differentiate: auth failures (stop, alert), rate limits (backoff), transient (retry). This prevents exhausting token quota by retrying expired credentials.

#### B10. AsyncGenerator Loop
Claude Code's core `query()` is an async generator yielding discriminated union states (10 terminal + 7 continue). Natural backpressure, clean cancellation, typed state machine.
**Gateway application:** Wrap the SSH-based Claude invocation in an event-emitting interface. Instead of polling PID every 5s (current progress poller pattern), stream JSONL events through a generator that yields: `streaming_tokens`, `tool_execution`, `permission_requested`, `compaction_needed`. Enables mid-session intervention and graceful cancellation.

---

## Appendix B: Consolidated Improvement Catalog

Merging the original 10 improvements (I1-I10) with the 16 external source findings (A1-A6, B1-B10), grouped by priority and gateway component.

### Activation Fixes (I1-I4, immediate)
These activate existing infrastructure. No new code needed — just validate and run existing scripts.

### Architecture Improvements (B1, B3, B4, B5, B6, B10)
These enhance the platform's core runtime. Moderate effort, significant quality/cost impact.

### Intelligence Improvements (A2, A3, A5, A6, B7)
These improve decision-making quality. Content-based routing, plan-before-execute, density summarization, staleness awareness, A/B testing.

### Security Hardening (A4, B8, B9)
Regex injection pre-screening, bounded dedup, failure-proportional reconnection.

### Cost Optimization (B2, B4)
Fork agents for cache sharing, slot reservation for output tokens.

### Observability & Evaluation (I5-I10, A1)
GraphRAG populator, tool call logging, eval flywheel fixes, declarative skills.
