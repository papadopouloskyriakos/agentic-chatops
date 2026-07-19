# agentic-chatops — Comprehensive Technical Reference

Production agentic ChatOps/ChatSecOps/ChatDevOps platform implementing all 21 design patterns from Antonio Gulli's *Agentic Design Patterns* (Springer, 2025). Tri-source audited against [Anthropic's official documentation](https://docs.anthropic.com/) (17 sources), the [Anthropic Academy](https://academy.anthropic.com/) sub-agent design course, and [6 industry references](docs/industry-agentic-references.md). Includes a [Karpathy-style compiled knowledge base](wiki/index.md) — 88 articles auto-compiled from 7+ sources with 5-signal RAG integration (semantic + keyword + wiki + [MemPalace](https://github.com/milla-jovovich/mempalace) session transcripts + chaos baselines).

> **For a concise overview, see [README.md](README.md).**

---

## Table of Contents

1. [What Makes This Different](#1-what-makes-this-different)
2. [Evaluation System](#2-evaluation-system)
3. [RAG Pipeline](#3-rag-pipeline)
4. [Compiled Knowledge Base (Karpathy-Style Wiki)](#4-compiled-knowledge-base-karpathy-style-wiki)
5. [Data & Intelligence](#5-data--intelligence)
6. [The 3-Tier Agent Architecture](#6-the-3-tier-agent-architecture)
7. [Alert Lifecycle (End-to-End)](#7-alert-lifecycle-end-to-end)
8. [Three Agentic Subsystems](#8-three-agentic-subsystems)
9. [Agentic Design Patterns — 21/21](#9-agentic-design-patterns--2121)
10. [n8n Workflows](#10-n8n-workflows-27-exported--57-active)
11. [MCP Servers](#11-mcp-servers-9-configured-167-tools)
12. [Sub-Agents](#12-sub-agents-11)
13. [Claude Code Skills & Hooks](#13-claude-code-skills--hooks)
14. [OpenClaw Tier 1 Skills](#14-openclaw-tier-1-skills-17)
15. [ChatSecOps — Security Operations](#15-chatsecops--security-operations)
16. [Guardrails & Safety](#16-guardrails--safety)
17. [Inter-Agent Communication](#17-inter-agent-communication-nl-a2av1)
18. [Operating Modes & Commands](#18-operating-modes--commands)
19. [Repository Structure](#19-repository-structure)
20. [Installation](#20-installation)
21. [References](#21-references)
22. [OpenAI Agents SDK Adoption Batch](#22-openai-agents-sdk-adoption-batch)
23. [QA Suite](#23-qa-suite)
24. [Preference-Iterating Prompt Patcher](#24-preference-iterating-prompt-patcher)
25. [CLI-Session RAG Capture](#25-cli-session-rag-capture)
26. [Skill Authoring Uplift (agents-cli audit, 2026-04-23)](#26-skill-authoring-uplift-agents-cli-audit-2026-04-23)
27. [NVIDIA DLI Cross-Audit + P0+P1 Implementation (2026-04-29)](#27-nvidia-dli-cross-audit--p0p1-implementation-2026-04-29)
28. [Infragraph — Causal World Model + Model-Based Control (2026-06-09)](#28-infragraph--causal-world-model--model-based-control-2026-06-09)
29. [Autonomy-Forward Gate — Human as Circuit-Breaker (2026-06-16)](#29-autonomy-forward-gate--human-as-circuit-breaker-2026-06-16)
30. [Self-Verifying Reliability Layer (2026-06-21)](#30-self-verifying-reliability-layer-2026-06-21)
31. [Orchestrator Control-Plane (IFRNLLEI01PRD-1421)](#31-orchestrator-control-plane-ifrnlprd-1421)
32. [Agent-Guide Benchmark — Anthropic + OpenAI (2026-06-26)](#32-agent-guide-benchmark--anthropic--openai-2026-06-26)
33. [Model Orchestration — Centralized Provider/Model Selection (2026-06-28)](#33-model-orchestration--centralized-providermodel-selection-2026-06-28)
34. [Scheduled-Reboot Suppression — self-learning (2026-06-29)](#34-scheduled-reboot-suppression--self-learning-2026-06-29)
35. [Renovate MR Autonomy Lane (2026-07-06)](#35-renovate-mr-autonomy-lane-2026-07-06)

---

## 1. What Makes This Different

Most agentic ChatOps projects stop at "LLM reads alert, posts summary." This one closes the loop end-to-end:

- **Model-based control with a non-bypassable prediction gate (2026-06-09)** -- A causal infrastructure dependency graph predicts the consequences of every proposed remediation BEFORE it can reach the approval poll, and code (never the proposing LLM) adjudicates observed-vs-predicted afterwards. Genuine model-free → model-based shift enforced in control flow. Full section: [§28](#28-infragraph--causal-world-model--model-based-control-2026-06-09).

- **Self-improving prompts with A/B trials** -- An eval flywheel (58 eval scenarios + 54 adversarial tests, LLM-as-a-Judge, monthly cycle) detects weak dimensions. The newer **preference-iterating patcher** ([IFRNLLEI01PRD-645](#24-preference-iterating-prompt-patcher), 2026-04-20) generates 3 candidate variants and a control arm per low-scoring dimension, routes future sessions deterministically via BLAKE2b hash, and promotes winners via a one-sided Welch t-test. Prompt-level policy iteration — no model weights ever fine-tuned.
- **AWX runbook integration** -- 41 Ansible playbooks are queryable at plan time. The planner injects proven AWX templates into investigation plans ("Run Template 69 with dry_run=true"), turning ad-hoc SSH into repeatable automation.
- **Predictive alerting** -- Regression detector (6h cron) and metamorphic monitor catch quality degradation before operators notice. Cost-adaptive routing switches to plan-only mode when category spend exceeds $3 average.
- **GraphRAG + infragraph** -- 721 entities and 661 relationships in one knowledge graph (2026-07-08): GraphRAG entities (host, alert_rule, incident, lesson) plus the infragraph causal dependency layer (361 nodes / 468 edges) (physical hosts, VMs/LXCs, network devices, tunnels, sites) with learned per-edge dynamics. Enables "what alerts does this host trigger?", "who is affected if this host fails?", and machine-computed consequence prediction (§28).
- **OTel tracing** -- 333K+ tool calls instrumented with OpenTelemetry spans (duration, exit code, error type). Exported to OpenObserve for cross-session trace correlation and performance debugging.
- **Karpathy-style compiled wiki** -- 88 articles auto-compiled daily from 7 fragmented knowledge stores (memories, CLAUDE.md files, incidents, lessons, OpenClaw, docs, 03_Lab). Answers "what do we know about host X?" in one lookup instead of five.
- **CLI sessions flow into RAG** -- Interactive `claude` CLI sessions (no YT webhook, no Runner workflow) used to produce knowledge that only cost/tokens were captured. The [CLI-session RAG capture pipeline](#25-cli-session-rag-capture) ([-646/-647/-648](#25-cli-session-rag-capture), 2026-04-20) threads every JSONL through archive → tool-call parse → `gemma3:12b` knowledge extraction → `incident_knowledge` with `project='chatops-cli'`. Retrieval weights CLI rows at 0.75× so real incidents still win ties. Idempotent, watermarked, breaker-aware.
- **Skill authoring discipline matched to `google/agents-cli`** -- A 2026-04-23 audit against [`google/agents-cli`](https://github.com/google/agents-cli) flagged six skill-authoring dimensions where we trailed (phase-gate choreography, discoverability, anti-guidance, inline behavioral anti-patterns, governance/versioning, skill index). An 11-commit uplift ([#26](#26-skill-authoring-uplift-agents-cli-audit-2026-04-23), Phases A→J) closed every gap: master `chatops-workflow` phase-gate skill (force-injected into every Runner session), auto-generated drift-guarded `docs/skills-index.md`, `version:` + `requires:` frontmatter on every skill, 46 Shortcuts-to-Resist rows inline on 11 agents, `evidence_missing` risk signal, `config/user-vocabulary.json` — scorecard 3.94 → **4.94**.

---

## 8. Three Agentic Subsystems

| Subsystem | Scope | Matrix Rooms | Alert Sources | Triage Scripts |
|-----------|-------|-------------|---------------|----------------|
| **ChatOps** | Infrastructure availability, performance, maintenance | `#infra-nl-prod`, `#infra-gr-prod` | LibreNMS, Prometheus, Synology DSM | [infra-triage](openclaw/skills/infra-triage/), [k8s-triage](openclaw/skills/k8s-triage/), [correlated-triage](openclaw/skills/correlated-triage/) |
| **ChatSecOps** | Security: intrusion detection, vulnerability scanning, MITRE ATT&CK | Same rooms (shared) | CrowdSec, vulnerability scanners | [security-triage](openclaw/skills/security-triage/), [baseline-add](openclaw/skills/baseline-add/) |
| **ChatDevOps** | Software development: CI/CD, features, bugs | `#cubeos`, `#meshsat` | GitLab CI | Code analysis via Claude Code + 4 dev sub-agents |

All three share: n8n orchestration (Runner, Bridge, Session End, Poller), Matrix as human-in-the-loop, YouTrack for issue tracking, and the 3-tier agent architecture.

---

## 6. The 3-Tier Agent Architecture

![Platform Architecture](docs/architecture-diagram-v2.drawio.png)

<details>
<summary>ASCII fallback</summary>

```
LibreNMS/Prometheus/CrowdSec Alert
         |
         v
   +---------------+     +--------------------+     +---------------------+
   |  n8n           |---->|  Tier-1 triage      |---->|  Claude Code         |
   |  Orchestrator  | SSH |  (deterministic)   |     |  (Tier 2)            |
   |  57 active     |     |  suppression 3-ph  |     |  11 sub-agents       |
   |                |     |  + infragraph ctx  |     |  predict-gated polls |
   +---------+------+     +--------------------+     +----------+----------+
             |                                                  |
             v                                                  v
   +---------------+                                   +---------------+
   |  Matrix        |<-----------------------------------|  Human (T3)   |
   |  Chat rooms    |  polls (+prediction summaries),    |  Approval     |
   +---------------+   reactions, replies                +---------------+
```

*(cc-cc mode, default since 2026-04-29 and the only live mode. The earlier OpenClaw Tier-1 is retired — its LXC (VMID_REDACTED / nl-openclaw01) was destroyed 2026-04-29 and is not restorable without a rebuild; see §18.)*
</details>

- **Tier 1 (deterministic triage scripts, cc-cc since 2026-04-29):** Receivers SSH directly to the runner host and invoke `scripts/run-triage.sh`. Three-phase suppression (dedup → blast-radius fold → known-pattern → active-memory) runs in code before any LLM; the triage script then assembles NetBox identity, infragraph dependency context (blast radius + expected cascade), chaos baselines, and CLAUDE.md/memory knowledge, posts findings + CONFIDENCE to YouTrack/Matrix, and escalates to Tier 2 when warranted. Per-incident auto-resolve baseline: 41.6% (30d, frozen 2026-06-09).
- **Tier 2 (Claude Code):** Deep analysis (5-15 min). 11 specialized sub-agents (fast-tier for research, opus-tier for security; both resolved to GLM via the centralized Model Orchestration layer). Receives targeted CLAUDE.md file paths + auto-retrieved operational memories in Build Prompt. Reads Tier 1 findings (now enriched with CLAUDE.md context), verifies using ReAct reasoning, proposes remediation via interactive polls, executes after human approval. For complex sessions, delegates research to sub-agents IN PARALLEL.
- **Tier 3 (Human):** Clicks a poll option in Matrix, reacts with thumbs up/down, or types a reply. The system stops and waits — it never makes infrastructure changes autonomously.

---

## 9. Agentic Design Patterns — 21/21

Benchmarked against all 21 patterns from Antonio Gulli's book + dual-source audited against [Anthropic's official documentation](https://docs.anthropic.com/) (17 sources). Full audit: [`docs/agentic-patterns-audit.md`](docs/agentic-patterns-audit.md). Book gap analysis: [`docs/book-gap-analysis.md`](docs/book-gap-analysis.md). Industry references: [`docs/industry-agentic-references.md`](docs/industry-agentic-references.md).

**Score: 16 A/A+ (7 at A+) and 5 A-**

| # | Pattern | Grade | Implementation | Book Chapter |
|---|---------|-------|---------------|-------------|
| 1 | **Prompt Chaining** | A | n8n 44-node Runner: lock -> cooldown -> RAG -> Build Prompt -> Launch -> Parse -> Validate -> Post. Sequential with programmatic gates between steps. | Ch1 |
| 2 | **Routing** | A- | Issue prefix -> Matrix room -> session slot. 8 alert categories auto-detected (availability, resource, storage, network, kubernetes, certificate, maintenance, correlated). | Ch2 |
| 3 | **Parallelization** | A- | 5 concurrent session slots (cubeos, meshsat, dev, infra-nl, infra-gr). Async Progress Poller. Sub-agents launched in parallel for complex sessions. | Ch3 |
| 4 | **Reflection** | A- | Cross-tier review: OpenClaw critiques Claude output with 5-step chain-of-verification (REVIEW_JSON: AGREE/DISAGREE/AUGMENT). Self-consistency check detects confidence/reasoning mismatches. | Ch4 |
| 5 | **Tool Use** | A | 9 MCP servers, ~167 tools. Custom Proxmox MCP (15 tools). n8n-as-code offline schemas for 537 nodes. `ToolSearch` for deferred tool discovery. | Ch5 |
| 6 | **Planning** | A- | Interactive [POLL] plan selection via MSC3381 Matrix polls. Plan-only mode (`--plan` flag) for multi-file dev tasks and correlated bursts. | Ch6 |
| 7 | **Multi-Agent** | **A+** | 3-tier hierarchy + 11 specialized sub-agents with [Anthropic Academy](https://academy.anthropic.com/) patterns: structured output, obstacle reporting, limited tools, no expert claims, parallel not sequential. Pipeline delegation for complex sessions. | Ch7 |
| 8 | **Memory** | **A+** | All 3 memory types (semantic, episodic, procedural) active across both tiers. 55 CLAUDE.md files auto-routed by hostname to triage. 117 feedback memory files synced across both agent hosts. Procedural rules ("NEVER do X") injected into Tier 1 triage output and Tier 2 Build Prompt. SQLite (53 tables, 450K+ rows incl. `session_transcripts`, `agent_diary`, `otel_spans`, `tool_call_log`). Vector embeddings (nomic-embed-text, 768 dims). Lessons-to-prompt pipeline. **[Karpathy-style compiled wiki](wiki/index.md)** — 88 articles synthesizing all memory types into organized, browsable knowledge with health checks. | Ch8 |
| 9 | **Learning & Adaptation** | **A+** | Closed-loop: session creates feedback memory → next triage auto-surfaces it → agent acts on it. A/B prompt testing (react_v1 vs react_v2). Outcome scoring. Lessons-to-prompt pipeline (30d). Regression detection (6h cron). Metamorphic monitor (auto-variant promotion at 25+ sessions). | Ch9 |
| 10 | **MCP** | A | 9 servers including custom Proxmox MCP (15 tools). Tool search enabled by default. Per-tool allowlisting in settings. | Ch10 |
| 11 | **Goal Setting** | A- | Confidence gating (< 0.5 = STOP, < 0.7 = escalate). Budget enforcement ($5/session warning, $25/day plan-only). Dynamic timeout by complexity (300-600s). Formalized contracts (`CONTRACT:` block in YT description). | Ch11 |
| 12 | **Exception Handling** | A | 5-layer gateway watchdog (n8n health, workflow activation, proactive bounce, error detection, zombie cleanup). `ERROR_CONTEXT` structured propagation (failed step, completed steps, suggested next action). Fallback ladders (AWX -> API -> SSH -> Ping). | Ch12 |
| 13 | **Human-in-the-Loop** | A | MSC3381 polls rendered in Matrix Element client. Thumbs up/down reactions. 15min remind / 30min auto-pause approval timeouts. AUTHORIZED_SENDERS filter. Formalized contracts define acceptance criteria. | Ch13 |
| 14 | **RAG** | **A+** | **5-signal hybrid RRF:** (1) semantic — vector embeddings (nomic-embed-text, 768 dims) with cosine similarity and `search_query:` / `search_document:` asymmetric prefixes; (2) keyword — SQL LIKE on hostname/alert/resolution; (3) **wiki articles** — 88 compiled knowledge base articles (~3,300 section-rows indexed with `source_mtime`); (4) **session transcripts** — verbatim exchange-pair chunks ([MemPalace](https://github.com/milla-jovovich/mempalace), weight 0.4); (5) **chaos baselines** — chaos experiment results by hostname (weight 0.35). All fused via Reciprocal Rank Fusion. **G1 cross-encoder rerank** via dedicated bge-reranker-v2-m3 service on nl-gpu01:11436. **G2 RAG Fusion** via `rewrite_query_multi` (4 variants, batch-embedded). **G3 LongContextReorder** (`long_context_reorder()` + `LCR_ENABLED=1`). **G5 KG traversal** with 3-tier progressive widening (strict → filters OR'd → entity_type dropped → embedding fallback). **Temporal window filter** on `wiki_articles.source_mtime` for "last 48h" queries. **mtime-sort intent detector** bypasses semantic retrieval for "name three memory files created in the last 48h" class queries. **Local qwen2.5 synth** (Ollama `qwen2.5:7b`, routed by the centralized Model Orchestration layer — Anthropic per-token spend = 0) composes cross-chunk answers when top rerank < 0.4. **4/4 FAISS HNSW indexes** pre-synced at `/var/claude-gateway/vector-indexes/` as migration-ready parallel write path. All JSON callers unified on `JSON_MODEL=qwen2.5:7b` (100% first-try JSON reliability, 20-query test). Plus deterministic channel: hostname-routed CLAUDE.md extraction (55 files, category-aware grep). Triage RAG at Step 1.5 (semantic) + Step 2-kb (CLAUDE.md + memory). 3-tier injection for Tier 2. Backfill cron every 30min. Wiki recompiled daily. | Ch14 |
| 15 | **A2A Communication** | A | [NL-A2A/v1 protocol](docs/a2a-protocol.md). Agent cards ([`a2a/agent-cards/`](a2a/agent-cards/)). Message envelope with protocol, messageId, from/to, type, payload. REVIEW_JSON auto-action. Task lifecycle logging. 53 A2A entries. | Ch15 |
| 16 | **Resource Optimization** | **A+** | Centralized Model Orchestration for sub-agents (opus-tier→glm-5.2, haiku-tier→glm-4.7 on the Z.ai Claude-Code plane; see CLAUDE.md §Model Orchestration). JSONL token-based cost tracking from stream-json. Per-category cost prediction. Dynamic timeout. $5/session + $25/day budget. Subsystem-level cost metrics. | Ch16 |
| 17 | **Reasoning** | A | ReAct (THOUGHT/ACTION/OBSERVATION) mandatory for infra. Step-back prompting for recurring alerts. Tree-of-thought (H1/H2 hypotheses) for correlated bursts. Self-consistency check. Chain-of-verification for cross-tier reviews. A/B variant testing. | Ch17 |
| 18 | **Guardrails** | **A+** | 7-layer defense: [`unified-guard.sh`](scripts/hooks/unified-guard.sh) — 78 blocked patterns (37 destructive + 22 exfil + 7 injection) + 12 protected file patterns + **word-boundary precision** on single-word commands (passwd/useradd/shutdown/halt/mkfs) that distinguishes command invocation (blocked) from prose mention (allowed) via `(^|[;&\|])\s*(sudo\s+)?WORD(\s|$|--)`; 22-check harness validates both block and allow cases. Plus safe-exec.sh + exec-approvals.json (36 patterns) + input sanitization (42 injection patterns) + credential/PII scanning (16 regex) + output fact-checking + **Evaluator-Optimizer** (Haiku-tier screening — routes to glm-4.7 via the centralized layer — for high-stakes responses, 3 nodes). Per-source token caps on injected knowledge. Tool call limit (75). Zero hardcoded passwords. | Ch18 |
| 19 | **Evaluation** | **A+** | 19-surface [Prompt Scorecard](scripts/grade-prompts.sh) (6 dimensions, daily). [Agent Trajectory](scripts/score-trajectory.sh) (8 infra / 4 dev steps). [LLM-as-a-Judge](scripts/llm-judge.sh) (routine on local `gemma3:12b`, max-effort on `gw-mistral-large` via LiteLLM; 5 dimensions, [calibrated](scripts/judge-calibrate.sh)). **58 test scenarios** (22+20+16) across [3 eval sets](docs/evaluation-process.md) (regression/discovery/holdout) + 54 adversarial tests + 18 node-level tests + 12 negative controls. [CI eval gate](.gitlab-ci.yml). [Eval flywheel](scripts/eval-flywheel.sh) (monthly). Reproducibility (temp=0, seed=42). | Ch19 |
| 20 | **Prioritization** | A | Sub-agent routing by session complexity. Burst detection (3+ hosts = correlated triage). Flap escalation (2+ cycles). Cost-adaptive plan mode ($3+ category average). Dynamic timeout by complexity. | Ch20 |
| 21 | **Exploration** | A | Daily [proactive health scan](openclaw/skills/proactive-scan/) (disk, certs, stale issues, VPN). Security discovery (expired baselines, unscanned VMs, CrowdSec blocklist freshness, scanner VM health). CrowdSec learning loop (auto-suppression with feedback). | Ch21 |

### Appendix A Techniques (from Book)

| Technique | Status | Implementation |
|-----------|--------|---------------|
| Negative few-shot | Done | Bad response example in Build Prompt |
| Operator context (Persona Pattern) | Done | Solo admin profile injected |
| APE (Automated Prompt Engineering) | Prerequisites done | A/B active, goldset built, blocked on 200+ labeled sessions |
| Factored cognition | Monitoring | Goldset T8 tracks % complex sessions, triggers at 20% |
| Metamorphic self-restructuring | Lite | 4 self-mod monitors (variant promotion, cost-adaptive, rollback, topology signals) |

---

## Holistic Platform Health Check

[`scripts/holistic-agentic-health.sh`](scripts/holistic-agentic-health.sh) — **~172 automated checks** across 43 sections that verify every feature claimed in this README actually works in production. Not just "does the file exist?" — functional tests, cross-site verification, and e2e smoke tests.

**Latest score: 98% (2026-07-08 — 164 pass / 0 fail / 2 warn / 6 skip, ~60s).** The table below is a dated snapshot of what each section verifies; run `--json` for live values.

```bash
./scripts/holistic-agentic-health.sh            # Full run (~168 checks, ~55s)
./scripts/holistic-agentic-health.sh --quick     # Skip SSH/kubectl (~171 checks, ~94%)
./scripts/holistic-agentic-health.sh --smoke     # Include e2e synthetic alert test
./scripts/holistic-agentic-health.sh --json      # Machine-readable output
```

### What It Tests

| Section | Checks | What's Verified |
|---------|--------|-----------------|
| n8n Workflows | 9 | 26 active, 7 critical workflows, execution error rate (<10%) |
| SQLite Tables | 12 | 50 tables, 150K+ rows, 8 staleness thresholds (per-table freshness) |
| MCP Servers | 1 | Process count for all 9 MCP servers |
| RAG Pipeline | 5 | Semantic search, wiki articles, transcripts, GraphRAG, **functional search test** (known incident) |
| Session End Pipeline | 7 | 18 nodes, all 6 critical nodes present (Score Trajectory → Populate Graph) |
| OpenClaw Tier 1 | 2 | 29 skills in-repo (LXC destroyed, not running) |
| Claude Code | 3 | 11 agents, 9 skills, 3 hook events |
| Eval Pipeline | 12 | 58 eval scenarios (3 sets) + 54 adversarial, 5 scripts, judgments, **functional trajectory test** |
| Safety Guardrails | 3 | 42 injection patterns, 89 blocked patterns, exec-approvals |
| Observability | 5 | OTel spans (OTLP export), 333K+ tool calls, 3 Grafana datasources, 13 Grafana dashboards, **Prometheus targets UP** |
| Crons | 1 | ~3 legacy crontab entries (180 jobs migrated to Cronicle 2026-06-26) |
| Self-Improving Prompts | 2 | 8 prompt-patch entries + Welch-gated A/B trials, prompt-improver executable |
| Predictive Alerting | 2 | Script + daily cron configured |
| Compiled Wiki | 3 | 88 articles, daily cron, compile freshness (<48h) |
| A2A Protocol | 2 | 3 agent cards, 53 task log entries |
| AWX Runbooks | 3 | Plan-and-execute scripts, **live AWX API query** |
| Ollama | 3 | 20 models, nomic-embed-text, **768-dim embedding generated** |
| LibreNMS | 2 | 123 NL devices, 19 GR alert rules |
| Key Scripts | 16 | All 16 production scripts exist and are executable |
| Knowledge Injection | 2 | 55 CLAUDE.md files, 117 memory files |
| Credential Rotation | 1 | No overdue credentials |
| VTI Tunnels | 2 | **6/6 IKEv2 SAs READY** (SSH to ASA), cross-site ping 42ms |
| Matrix Bot | 2 | @claude in 7 rooms, **message POST to #alerts** |
| Prompt Patches TTL | 1 | No expired-but-active patches |
| CrowdSec Stats | 1 | 5 scenarios tracked |
| OpenObserve | 1 | healthz 200 |
| Webhook Functional | 1 | agentic-stats API returns valid JSON |
| Gateway Mode | 2 | Valid mode (cc-cc since the 2026-07-03 sentinel correction), no maintenance lock |
| Session Continuity | 1 | Last session_id queryable |
| Runner Build Prompt | 5 | 48 nodes, 4 critical nodes (Build Prompt, Query Knowledge, Build Plan, Evaluator) |
| External Services | 5 | YouTrack API, **NetBox CMDB (307 objects)**, Matrix POST, GitHub mirror (<72h), OpenClaw LLM reachable |
| Infra Health | 6 | **7/7 K8s nodes**, PVE quorum, **7 BGP peers**, GPU 46°C, Thanos query, DNS |
| Data Integrity | 5 | Embeddings (33/33), queue depth, DB backup (<26h), JSONL poller, token caps in Build Prompt |
| Security | 4 | Scanner NL (<26h), scanner GR (<26h), MITRE Navigator, CrowdSec bans |
| Cross-Site Sync | 3 | OpenClaw memories, GR claude host, **syslog-ng (NL: 18, GR: 184K lines/day)** |
| Operational | 6 | Freedom WAN SLA UP, Docker containers, n8n-as-code, **19/19 scorecard surfaces**, watchdog, **4 VPS SAs** |
| **Infragraph (§39)** | 6 | Graph populated (≥100 nodes/edges), 0 stale edges, dynamics coverage, seed + learn crons present, triage Step 2-graph wiring + kill-switch intact |
| **Orchestrator Control-Plane ([§31](#31-orchestrator-control-plane-ifrnlprd-1421))** | — | Component registry seeded (363 components, 0 critical-dark), `registry-check` + interaction-graph + orchestration-benchmark + platform-controller jobs present, 0 interaction GAPs, orchestration score ≥ I1 safety-composition, governance hash-chain intact |
| Smoke (--smoke) | 3 | Synthetic LibreNMS alert → YT issue created → cleanup |

### Historical Trending

Each run stores results in `health_check_results` and `health_check_detail` SQLite tables. The trend line shows score progression across runs. Prometheus metrics exported to `/var/lib/node_exporter/textfile_collector/holistic_health.prom`.

---

## 7. Alert Lifecycle (End-to-End)

```
1. LibreNMS detects "Devices up/down" on host X
2. n8n LibreNMS Receiver -> dedup, flap detection, burst detection
3. Posts to Matrix #infra room: "[LibreNMS] ALERT: host X -- Devices up/down"
4. OpenClaw (Tier 1) auto-triages:
   a. Checks YouTrack for existing issues (24h dedup)
   b. Creates issue IFRNLLEI01PRD-XXX
   c. Queries NetBox CMDB for device identity
   d. Queries incident knowledge base (semantic search via local Ollama, Step 1.5)
   e. Extracts CLAUDE.md procedural knowledge + operational memory rules (Step 2-kb)
   f. Investigates via SSH (PVE status, container logs)
   g. Posts findings + CONFIDENCE score to YouTrack + Matrix
   h. If confidence < 0.7 or critical: escalates to Claude Code
5. Build Plan (fast-tier planner) generates 3-5 step investigation plan:
   a. Queries AWX API for matching Ansible playbooks (41 templates across maintenance, certs, K8s, updates)
   b. Injects proven AWX runbooks into the plan — planner references "Run AWX Template {ID} with dry_run=true"
   c. Falls back to ad-hoc investigation steps when no matching playbook exists
6. Claude Code (Tier 2) activates:
   a. Reads YouTrack issue + Tier 1 comments (now includes CLAUDE.md context)
   b. Follows the investigation plan, can launch AWX jobs via API (dry_run first, full run after [POLL] approval)
   c. Receives targeted CLAUDE.md file paths + operational memories + staleness warnings in Build Prompt
   d. For complex sessions: delegates research to sub-agents IN PARALLEL
      - triage-researcher (Haiku) for device context + incident history
      - k8s-diagnostician (Haiku) for K8s alerts
      - cisco-asa-specialist (Haiku) for firewall alerts
      - storage-specialist (Haiku) for iSCSI/ZFS alerts
   c. Synthesizes sub-agent findings
   d. Uses ReAct reasoning: THOUGHT -> ACTION -> OBSERVATION loop
   e. Proposes 2-3 remediation plans via [POLL]
6. Matrix renders interactive poll -- operator clicks preferred plan
7. Claude Code executes selected plan
8. Reports results, moves issue to "To Verify"
9. Session End (18-node pipeline):
   a. **Scores agent trajectory** from JSONL (8 infra / 4 dev steps)
   b. **LLM-as-a-Judge** evaluates response (routine on local gemma3:12b, max-effort on gw-mistral-large)
   c. **Archives session transcript** (MemPalace: exchange-pair chunks → embeddings → 4th RAG signal)
   d. **Exports OTel traces** to OpenObserve (OTLP)
   e. **Parses tool calls** from JSONL → tool_call_log (per-tool error rates, latency)
   f. Cleans up JSONL, locks, cooldown files
   g. Populates incident_knowledge with vector embedding + extracts lessons
   h. **Populates GraphRAG** (incremental entity/relationship extraction per issue)
   i. Posts summary to YouTrack + Matrix
```

**Real incident:** IFRNLLEI01PRD-82 — full L1->L2->L3->approval->fix->recovery cycle. LibreNMS alert -> n8n -> Matrix -> OpenClaw triage (30s) -> Claude Code investigation (8min) -> [POLL] with 3 options -> operator clicks Plan A -> fix applied -> recovery confirmed -> YT closed.

---

## 10. n8n Workflows (27 exported / 57 active)

| Workflow | Nodes | Subsystem | Purpose |
|----------|-------|-----------|---------|
| YouTrack Receiver | 5 | All | Webhook listener, fires Runner async |
| **Claude Runner** | 51 | All | Lock -> cooldown -> RAG -> Classify Risk -> **Commit Prediction (infragraph)** -> Build Prompt -> Launch Claude -> Parse -> Validate -> **Screen (Evaluator-Optimizer)** -> **Prediction gate (Prepare Result)** -> Post |
| Progress Poller | 10 | All | Polls JSONL log every 30s, posts tool activity to Matrix |
| **Matrix Bridge** | 73 | All | Polls /sync, routes commands, manages sessions, handles reactions/polls |
| **Session End** | 18 | All | Summarize -> **Score Trajectory** -> **Judge Session** -> **Archive Transcript** -> **Export Traces** -> **Parse Tool Calls** -> Cleanup -> KB -> **Populate Graph** -> YT comment |
| LibreNMS Receiver (NL) | 26 | ChatOps | Alert dedup, flap detection, burst detection, recovery tracking |
| LibreNMS Receiver (GR) | 26 | ChatOps | Clone for GR site |
| Prometheus Receiver (NL) | 26 | ChatOps | K8s alert processing, fingerprint dedup, escalation cooldown |
| Prometheus Receiver (GR) | 26 | ChatOps | Clone for GR site |
| Security Receiver (NL) | 25 | ChatSecOps | Vulnerability scanner findings, baseline comparison |
| Security Receiver (GR) | 25 | ChatSecOps | Clone for GR site |
| CrowdSec Receiver (NL) | 23 | ChatSecOps | CrowdSec alerts, MITRE mapping, **scenario stats UPSERT**, auto-suppression learning |
| CrowdSec Receiver (GR) | 23 | ChatSecOps | Clone for GR site |
| Synology DSM Receiver | 7 | ChatOps | I/O latency, SMART, iSCSI errors |
| WAL Self-Healer (GR) | 18 | ChatOps | Auto-restart Prometheus on WAL corruption |
| CI Failure Receiver | 9 | ChatDevOps | GitLab pipeline webhook -> Matrix + YT comment |
| Agentic Stats API | 3 | — | Live LLM usage data for Hugo portfolio (`/webhook/agentic-stats`) |
| Lab Stats API | 3 | — | Live NetBox/K8s/ZFS data for Hugo portfolio (`/webhook/lab-stats`) |
| VPN Mesh Stats API | 3 | — | Live VPN tunnel/BGP/latency data for Hugo portfolio (`/webhook/mesh-stats`) |
| Service Health API | 3 | — | Service availability endpoint for chaos testing |
| Chaos Test Start | 3 | — | Chaos engineering: inject failure scenarios |
| Chaos Test Status | 3 | — | Chaos engineering: check active test status |
| Chaos Test Recover | 3 | — | Chaos engineering: trigger recovery |
| Chaos Logs API | 3 | — | Chaos engineering: retrieve test logs |
| Doorbell | 6 | — | UniFi Protect -> Mattermost+Matrix+HA+Frigate |

---

## 11. MCP Servers (9 configured, ~167 tools)

| MCP | Tools | Purpose |
|-----|-------|---------|
| `netbox` | ~20 | CMDB: 310 devices/VMs, 421 IPs, 39 VLANs across 6 sites |
| `n8n-mcp` | 21 | Workflow management (create, update, test, validate) |
| `youtrack` | 47 | Issue CRUD, custom fields, state transitions, search |
| `proxmox` | 15 | VM/LXC lifecycle, node status, storage (custom-built MCP) |
| `kubernetes` | 19 | kubectl get/describe/apply, logs, exec, helm, node management |
| `gitlab-mcp` | -- | MRs, pipelines, commits |
| `codegraph` | 12 | Code graph (KuzuDB), call chains, dead code, complexity |
| `opentofu` | 4 | Registry provider/resource/module docs |
| `tfmcp` | 29 | Terraform plan/apply/state, module health, security analysis |

---

## 12. Sub-Agents (11)

Designed with [Anthropic Academy](https://academy.anthropic.com/) patterns:
- **Structured output** — numbered sections with natural stopping points
- **Obstacle reporting** — every agent has an "Obstacles Encountered" section
- **Limited tool access** — read-only for researchers (no Edit/Write)
- **Specific descriptions** — shape the input prompts the main agent writes
- **Decision rule** — "Only delegate when you need the RESULT, not the journey"
- **Anti-patterns avoided** — no expert claims, no sequential pipelines, no test runners

> **Model routing (2026-06-28):** the per-agent `Model` column below reflects the requested *tier* (Haiku/Opus); under the centralized Model Orchestration layer these resolve to whatever the Claude-Code plane's live provider serves (Z.ai GLM equivalents — haiku-tier→`glm-4.7`, opus-tier→`glm-5.2` — or native Anthropic models when the toggle is on `anthropic`). See CLAUDE.md §Model Orchestration; `claude-provider.sh status` is authoritative.

### Infrastructure Sub-Agents (6)

| Agent | Model | MCP | Turns | Purpose |
|-------|-------|-----|-------|---------|
| [triage-researcher](.claude/agents/triage-researcher.md) | Haiku | netbox, k8s | 15 | Fast device lookup, incident history, 03_Lab reference |
| [k8s-diagnostician](.claude/agents/k8s-diagnostician.md) | Haiku | k8s, netbox | 18 | Pod/node/event diagnostics, Cilium, PVC checks |
| [cisco-asa-specialist](.claude/agents/cisco-asa-specialist.md) | Haiku | — | 15 | ASA firewall diagnostics, VPN tunnels, ACL analysis |
| [storage-specialist](.claude/agents/storage-specialist.md) | Haiku | proxmox, netbox | 15 | iSCSI, ZFS, NFS, SeaweedFS diagnostics |
| [security-analyst](.claude/agents/security-analyst.md) | **Opus** | netbox, k8s | 25 | Deep CVE/MITRE/CTI analysis, evidence collection |
| [workflow-validator](.claude/agents/workflow-validator.md) | Haiku | n8n-mcp | 12 | n8n workflow JSON validation |

### Development Sub-Agents (4)

| Agent | Model | MCP | Turns | Purpose |
|-------|-------|-----|-------|---------|
| [code-explorer](.claude/agents/code-explorer.md) | Haiku | codegraph | 15 | Codebase research, call chain tracing, file mapping |
| [code-reviewer](.claude/agents/code-reviewer.md) | Haiku | — | 12 | Fresh-eyes code review (separate context, no implementation bias) |
| [ci-debugger](.claude/agents/ci-debugger.md) | Haiku | — | 12 | CI pipeline failure diagnosis, log parsing |
| [dependency-analyst](.claude/agents/dependency-analyst.md) | Haiku | codegraph | 15 | Cross-repo impact analysis for refactoring |

### Learning Sub-Agent (1)

| Agent | Model | MCP | Turns | Purpose |
|-------|-------|-----|-------|---------|
| [teacher-agent](.claude/agents/teacher-agent.md) | Haiku | — | 15 | Socratic teacher over internal docs; SM-2 scheduling + Bloom progression + low-confidence clarifier. Read-only tool allowlist (no Edit/Write). Landed 2026-04-20 under IFRNLLEI01PRD-651..-655. Details in the [teacher-agent runbook](docs/runbooks/teacher-agent.md). |

**Anti-guidance (Phase A, 2026-04-23):** every agent description now ends with an explicit "Do NOT use for X (use /other-skill instead)" trailing clause — see [`docs/skills-index.md`](docs/skills-index.md) for the auto-generated single source of truth. **Shortcuts-to-Resist (Phase E):** each of the 11 agents carries an inline table (3–5 rows) drawn from `memory/feedback_*.md` — behavioral inoculation at the surface where the model is about to act.

**Pipeline integration:** Build Prompt detects complex sessions (timeout >= 600, correlated, kubernetes, multi-file dev) and injects `SUB-AGENT DELEGATION` instructions. Claude launches relevant sub-agents IN PARALLEL for research, then synthesizes. Routes research to the fast tier rather than the opus tier (both resolved via the centralized Model Orchestration layer).

---

## 13. Claude Code Skills & Hooks

### Skills (9 total · 6 user-invocable slash-commands listed below)

| Skill | Delegation | Purpose |
|-------|------------|---------|
| `/triage <host> <rule> <sev>` | Forks to triage-researcher | Full infra triage with structured output |
| `/alert-status` | Inline | Show active alerts across NL+GR (6 sources) |
| `/cost-report [days]` | Inline | Session cost/confidence analysis from SQLite |
| `/drift-check [nl\|gr\|all]` | Forks to triage-researcher | IaC vs live infrastructure drift detection |
| `/wiki-compile [--full\|--health]` | Inline | Compile/refresh the [Karpathy-style knowledge base](wiki/index.md) |
| `/review` | Inline | Merge request review |

### Hooks (full lifecycle coverage after IFRNLLEI01PRD-638/639)

Deterministic enforcement — fires BEFORE permission checks, cannot be bypassed. The **3-behavior rejection taxonomy** (`allow` / `reject_content` / `deny`) mirrors the OpenAI SDK `ToolGuardrailFunctionOutput` but stays within Claude Code's exit-code contract: differentiation lives in the explanatory message + the structured `tool_guardrail_rejection` event emitted to `event_log`.

| Hook | Event | Purpose |
|------|-------|---------|
| [`unified-guard.sh`](scripts/hooks/unified-guard.sh) | PreToolUse (Bash, Edit, Write) | Merged guardrail: 78 blocked patterns (destructive + exfil + injection) + 15 protected file patterns. Deny vs reject_content distinguished by message prefix and `behavior` field in `event_log`. |
| [`audit-bash.sh`](scripts/hooks/audit-bash.sh) | PreToolUse (legacy) | Kept in sync with unified-guard: same 3-behavior taxonomy + `event_log` emission, retained for sites that wire it standalone. |
| [`protect-files.sh`](scripts/hooks/protect-files.sh) | PreToolUse (legacy) | Same: refactored for the reject_content taxonomy; never emits JSON (would fail Claude Code hook validation). |
| [`snapshot-pre-tool.sh`](scripts/hooks/snapshot-pre-tool.sh) | PreToolUse (Bash, Edit, Write, Task) | IFRNLLEI01PRD-636 — writes a `session_state_snapshot` row BEFORE each mutating tool call (read-only tools skipped) for crash-mid-tool rollback. |
| [`session-start.sh`](scripts/hooks/session-start.sh) | SessionStart | IFRNLLEI01PRD-638 — initialises turn 0 in `session_turns`, emits `agent_updated` event. |
| [`post-tool-use.sh`](scripts/hooks/post-tool-use.sh) | PostToolUse | IFRNLLEI01PRD-638 — emits `tool_ended` event, bumps `tool_count` / `tool_errors`. |
| [`user-prompt-submit.sh`](scripts/hooks/user-prompt-submit.sh) | UserPromptSubmit | IFRNLLEI01PRD-638 — advances turn, emits `message_output_created` + detects poll-response (`mcp_approval_response`). |
| [`session-end.sh`](scripts/hooks/session-end.sh) | SessionEnd | IFRNLLEI01PRD-638 — the `on_final_output` equivalent: finalises the last open turn, flips active agent back to operator via an `agent_updated` event. |
| [`mempal-session-save.sh`](scripts/hooks/mempal-session-save.sh) | Stop | Auto-saves session transcript every 15 messages ([MemPalace](https://github.com/milla-jovovich/mempalace) pattern) |
| [`mempal-precompact.sh`](scripts/hooks/mempal-precompact.sh) | PreCompact | Emergency transcript save before context compression |

---

## 14. OpenClaw Tier 1 Skills (17 — retired subsystem)

> OpenClaw was retired 2026-04-29 (LXC destroyed, see §18). The `openclaw/` skill directories below are the artifact set of that retired tier — several scripts (e.g. `site-config.sh` helpers) are still sourced by the cc-cc triage path, but the skills no longer run as an agent tier.

| Skill | Purpose |
|-------|---------|
| [`infra-triage`](openclaw/skills/infra-triage/) | L1+L2 infra alert triage (YT dedup -> NetBox -> investigate -> escalate) |
| [`k8s-triage`](openclaw/skills/k8s-triage/) | Kubernetes alert triage (control plane deep investigation) |
| [`correlated-triage`](openclaw/skills/correlated-triage/) | Multi-host burst analysis (master + child issues) |
| [`security-triage`](openclaw/skills/security-triage/) | Vulnerability triage with MITRE ATT&CK mapping (54 scenarios) |
| `escalate-to-claude` | Tier 2 escalation via n8n webhook |
| [`netbox-lookup`](openclaw/skills/netbox-lookup/) | CMDB device/VM/IP/VLAN lookup |
| `youtrack-lookup` | Issue CRUD operations |
| [`playbook-lookup`](openclaw/skills/playbook-lookup/) | Query incident knowledge base for past resolutions |
| [`memory-recall`](openclaw/skills/memory-recall/) | Episodic memory search by host/alert |
| [`codegraph-lookup`](openclaw/skills/codegraph-lookup/) | Code relationship analysis |
| [`lab-lookup`](openclaw/skills/lab-lookup/) | 03_Lab reference library queries (port-map, nic-config) |
| [`baseline-add`](openclaw/skills/baseline-add/) | Security baseline management (90d expiry) |
| [`proactive-scan`](openclaw/skills/proactive-scan/) | Daily health + security discovery checks |
| [`claude-knowledge-lookup`](openclaw/skills/claude-knowledge-lookup.sh) | CLAUDE.md + memory knowledge extraction (hostname-routed, category-aware) |
| [`safe-exec.sh`](openclaw/skills/safe-exec.sh) | Exec enforcement wrapper (30+ blocked patterns, rate limiting) |

---

## 15. ChatSecOps — Security Operations

### MITRE ATT&CK Coverage

54 CrowdSec scenarios + 6 scanner/infra detections mapped to **19 unique ATT&CK techniques** across 8 tactics. Auto-synced to self-hosted ATT&CK Navigator. Mapping: [`mitre-mapping.json`](openclaw/skills/security-triage/mitre-mapping.json).

### Security Alert Pipeline

```
CrowdSec ban decision -> n8n CrowdSec Receiver -> severity classification
  -> MITRE mapping -> flap detection -> burst correlation -> Matrix + YT
  -> OpenClaw security-triage -> Claude Code security-analyst (if critical)
```

### CrowdSec Learning Loop

Auto-suppression: scenarios with 20+ alerts and 0 escalations in 7d are suppressed. Un-suppressed when escalations appear. Prometheus metrics track per-scenario efficacy.

### Vulnerability Scanner Pipeline

Cross-site design: NL scanner scans GR+VPS, GR scanner scans NL+VPS (prevents single-scanner blind spots). Daily cron at 03:00/03:15 UTC. Baseline comparison with 90d expiry. SLAs: critical 24h, high 7d, medium 30d, low 90d.

---

## 5. Data & Intelligence

### SQLite Tables (53, 450K+ rows)

**31 tables** carry a `schema_version INTEGER DEFAULT 1` column. Canonical definitions in [`schema.sql`](schema.sql); idempotent ALTERs via migrations 006–021. Registry: [`scripts/lib/schema_version.py`](scripts/lib/schema_version.py) (with `SCHEMA_VERSION_SUMMARIES` change notes per table, mirroring OpenAI SDK `run_state.py:131`). Row counts below are an April-2026 snapshot and drift upward; treat as illustrative.

| Table | Rows | Purpose |
|-------|------|---------|
| `sessions` | 62 | Active sessions (issue_id, session_id, cost, confidence, trace_id, **handoff_depth**, **handoff_chain**) |
| `session_log` | 239 | Archived sessions with full tracking fields |
| `session_quality` | 34 | 5-dimension quality scores (confidence, cost efficiency, completeness, feedback, speed) |
| `session_trajectory` | 86 | Per-session agent trajectory scores (8 infra / 4 dev step markers) |
| `session_judgment` | 46 | LLM-as-a-Judge results (5-dimension rubric, gemma3:12b / gw-mistral-large + dev rubric) |
| `session_feedback` | 1 | Thumbs up/down reactions linked to issues |
| `session_transcripts` | 838 | Verbatim JSONL exchange-pair chunks with embeddings (4th RAG signal, [MemPalace](https://github.com/milla-jovovich/mempalace)) |
| `agent_diary` | 64 | Persistent per-agent knowledge across sessions, 10 agent archetypes |
| `incident_knowledge` | 54 | Alert resolutions with vector embeddings (nomic-embed-text, 768 dims) |
| `lessons_learned` | 27 | Operational insights extracted from sessions |
| `openclaw_memory` | 101 | Episodic memory for Tier 1 triage outcomes |
| `a2a_task_log` | 53 | Inter-agent message lifecycle tracking |
| `crowdsec_scenario_stats` | 5 | CrowdSec learning loop state (3 auto-suppressed) |
| `prompt_scorecard` | 302 | Daily prompt grading (19 surfaces x 6 dimensions) |
| `llm_usage` | 112 | Per-request token/cost tracking across 3 tiers |
| `wiki_articles` | 44 | Compiled wiki articles with vector embeddings (3rd RAG signal) |
| `tool_call_log` | 88K | Per-tool invocation tracking: name, duration, exit_code, error_type |
| `execution_log` | 18K | Infrastructure SSH/kubectl commands with device, exit_code, duration |
| `graph_entities` | 716 | GraphRAG + infragraph entities (host, alert_rule, incident, lesson, pve_node, vm, lxc, network_device, tunnel, site) |
| `graph_relationships` | 607 | GraphRAG + infragraph edges (triggers, caused_by, resolves, runs_on, depends_on, routes_via, member_of, backs_up_to) |
| `credential_usage_log` | 39 | Credential rotation tracking with 90-day policy |
| `otel_spans` | 39K | OpenTelemetry spans (local storage + OTLP export to OpenObserve) |
| `chaos_experiments` | 152 | Chaos experiment results (scenario, target, outcome, recovery_time); embeddings indexed in FAISS (4/4 tables migration-ready) |
| `chaos_exercises` | 1 | Scheduled chaos exercise records |
| `chaos_retrospectives` | 34 | Post-chaos exercise retrospectives |
| `chaos_findings` | 29 | Improvement findings from chaos exercises |
| `ragas_evaluation` | 136 | RAGAS metrics (faithfulness, precision, recall per query); hardened golden set = 33 queries (15 hard-eval tagged) across multi-hop / temporal / negation / meta / cross-corpus |
| `health_check_detail` | 1,675 | Per-check results for health trending |
| `queue` | — | Session queue for slot management |
| `event_log` | — | IFRNLLEI01PRD-637 — 17 typed event_types (tool_started/ended, handoff_*, reasoning_item_created, mcp_approval_*, agent_updated, message_output_created, tool_guardrail_rejection, agent_as_tool_call + the 4 NVIDIA-batch types). Indexed by `session_id + emitted_at` for Grafana drill-downs. |
| `handoff_log` | — | IFRNLLEI01PRD-640 — one row per T1→T2 escalation or sub-agent spawn; records `input_history_bytes`, `compaction_applied`, `pre_handoff_count`, `new_items_count`. Holistic-health asserts one row per handoff within 5 s. |
| `session_state_snapshot` | — | IFRNLLEI01PRD-636 — immutable pre-tool snapshots (OpenAI `RunState` equivalent). `snapshot_data` mirrors the `sessions` row + aggregated `llm_usage`. 7-day retention via [`scripts/prune-snapshots.sh`](scripts/prune-snapshots.sh). |
| `session_turns` | — | IFRNLLEI01PRD-638 — one row per turn (`UNIQUE(session_id, turn_id)`). Tracks per-turn `llm_cost_usd`, input/output/cache tokens, `tool_count`, `tool_errors`, `duration_ms`. |
| `infragraph_dynamics` | — | IFRNLLEI01PRD-1031 — per-edge learned dynamics sidecar (source, expected_alerts, delay p50/p95, recovery p50, observation_count, valid_until, confidence). 1:1 with an infragraph edge. |
| `infragraph_predictions` | — | IFRNLLEI01PRD-1031 — cascade (shadow) + action (gate) predictions with shuffled-graph control columns and the mechanical `verdict` (match/partial/deviation) written only by the verifier. |

**Backup:** Daily at 02:00 UTC, 7-day retention, integrity checked ([`backup-gateway-db.sh`](scripts/backup-gateway-db.sh)).

### Prometheus Metrics (77 textfile writers / ~1,700 series; native Cronicle scheduler, 199 registered jobs as of 2026-07-08)

| Category | Metrics |
|----------|---------|
| Session performance | cost, duration, confidence, turns (per-project, 7d/30d rolling) |
| A/B testing | per-variant confidence, cost, session count |
| Cost optimization | per-category avg cost + duration, budget compliance |
| Quality | SLA MTTR avg/p90, confidence calibration per band |
| Security | false positive rate, MITRE coverage, CrowdSec efficacy per scenario |
| Guardrails | exec blocked/allowed counts, injection detection |
| Subsystem | per-subsystem sessions, confidence, cost, prompt score average |
| Prompt scorecard | per-surface per-dimension scores |
| Infrastructure | Ollama health, embedding backlog, knowledge entry count |
| RAG pipeline | `kb_retrieval_latency_seconds{quantile}`, `kb_rerank_service_up`, `kb_embedded_rows{table}`, `kb_migration_trigger_distance`, `kb_qwen_json_failure_total` |
| Hard-eval cron | `kb_hard_eval_hit_rate`, `kb_hard_eval_coverage_rate`, `kb_hard_eval_kg_coverage`, `kb_hard_eval_latency_p50_seconds`, `kb_hard_eval_latency_p95_seconds`, `kb_hard_eval_last_run_timestamp_seconds` |
| Content refresh | `kb_content_refresh_age_seconds{doc}` for all 5 auto-refreshed docs |

### RAG Alert Rules (13 alerts in `rag-pipeline-health` group)

Deployed via Atlantis to the NL K8s cluster ([`k8s/namespaces/monitoring/rag-alerts.tf`](https://gitlab.example.net/infrastructure/nl/production)). Gateway source-of-truth: [`prometheus/alert-rules/rag-health.yml`](prometheus/alert-rules/rag-health.yml).

**Staleness + absent-metric pairs** — every staleness alert has a paired `absent()` guard to catch the failure mode where the metric disappears (silent-breakage detection):

| Staleness alert (fires on old data) | Absent-metric alert (fires on missing data) |
|---|---|
| `KBWeeklyEvalStale` (>8d) | `KBWeeklyEvalMetricAbsent` (2h) |
| `KBContentRefreshStale` (>48h) | `KBContentRefreshMetricAbsent` (2h) |
| `KBOpenClawSyncStale` (>48h) | `KBOpenClawSyncMetricAbsent` (2h) |

Plus: `RAGRerankServiceDown`, `RAGLatencyP95High` (>12s post-L02 Haiku synth rebaseline), `RAGMigrationTriggered`, `RAGQwenJsonSilentFailure`, `RAGEmbeddingStagnant`, `RAGHardEvalRegression`, `KBOpenClawSyncFailing`.

The absent-metric pair pattern was added after IFRNLLEI01PRD-614 caught a live silent-failure: `weekly-eval-cron.sh` had an `awk -F': '` bug that never matched the path-print line (zero colons on it) + the emitted textfile was mode `0600` (node-exporter runs as `nobody`, couldn't read). Both fixed and regression-tested.

### Grafana Dashboards (13, 90+ panels)

- **ChatOps Platform Performance** — sessions, queue, locks, API status, costs, quality
- **Infrastructure Overview** — CPU/memory/disk per host, GPU metrics, service availability
- **Infra Alerts & Remediation** — alert rates, triage outcomes, MTTR trends
- **CubeOS Project** — pipeline success, MRs, issue states
- **MeshSat Project** — pipeline success, MRs, issue states
- **Chaos Engineering** — experiment results, recovery times, safety metrics
- **LLM Usage & Cost** — per-model token tracking, budget compliance, tier breakdown
- **RAG Quality** — retrieval scores, RAGAS metrics, embedding coverage
- **Security Operations** — CrowdSec efficacy, MITRE coverage, vulnerability SLAs
- **BGP & VPN Mesh** — tunnel status, BGP peer state, cross-site latency

### Self-Hosted Observability Services (2026-06-26)

Three observability backends run as Docker services on `nlopenobserve01` (10.0.181.X, LXC VMID_REDACTED on `nl-pve03`, resized 10 → 30 GiB to host them). They complement the Prometheus/SQLite substrate rather than replace it — chosen during the orchestrator-governance research (§31) as the two thin "compose, don't rebuild" picks plus the existing OTLP sink.

| Service | Endpoint | Role | Wiring |
|---------|----------|------|--------|
| **OpenObserve** | `:5080` | Unified log + distributed-tracing OTLP sink (existing) | Every scheduler run + brick decision + completed session is logged here; `otel_spans` push fresh over OTLP at session-end. Was **broken since ~March 2026** — a stale `OTLP_AUTH` env var was shadowing the real credentials so spans silently never shipped — **revived** as part of the agent-guide benchmark batch (§32). |
| **Healthchecks.io** | `:8000` | Ping-based dead-man / "job never ran" detection | BSD-3, self-hostable solo. Catches the scheduling-failure class that a Prometheus `absent()` clause can still miss (a cron that is removed/disabled emits no series at all). The orchestrator's `registry-check` `*/30` cron pings it on every run; a missed ping flags the dead component. Creds in `.env` (`HEALTHCHECKS_*`). |
| **Langfuse v2** | `:3000` | LLM/agent **trace** observability (sessions, model, cost, generations) | Postgres-only deployment. Every completed session traces via [`scripts/lib/langfuse_export.py`](scripts/lib/langfuse_export.py), wired into [`scripts/reconcile-completed-sessions.py`](scripts/reconcile-completed-sessions.py). Surfaces per-session generations, model attribution, and cost for trace-level navigation alongside the SQLite `llm_usage`/`otel_spans` tables. Creds in `.env` (`LANGFUSE_*`). |

These are the "brick-growth" of the orchestrator control-plane (§31): the governance research deliberately chose to **compose** Healthchecks.io + Langfuse onto the existing stack rather than adopt a full orchestration platform.

---

## 2. Evaluation System

### Prompt Scorecard ([`grade-prompts.sh`](scripts/grade-prompts.sh))

Daily grading of 19 prompt surfaces on 6 dimensions (0-100):

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| effectiveness | 30% | Avg confidence, resolution rate |
| efficiency | 15% | Cost/turns relative to median |
| completeness | 25% | Required fields present (CONFIDENCE, [POLL], ReAct) |
| consistency | 10% | Confidence variance (low = good) |
| feedback | 15% | Thumbs up/down rate |
| retry_rate | 5% | % sessions not needing retry |

Prometheus: `chatops_prompt_score{surface,dimension,window}`. Subsystem averages: `chatops_subsystem_prompt_avg{subsystem}`.

### Agent Trajectory Evaluation ([`score-trajectory.sh`](scripts/score-trajectory.sh))

Parses JSONL session transcripts and scores step sequences:
- **Infra sessions (8 steps):** NetBox lookup, incident KB query, ReAct structure, [POLL]/approval, CONFIDENCE, evidence commands, SSH investigation, YT comment
- **Dev sessions (4 steps):** CONFIDENCE, evidence, tool usage, multi-turn engagement

### LLM-as-a-Judge ([`llm-judge.sh`](scripts/llm-judge.sh))

External quality assessment via the centralized Model Orchestration layer (see CLAUDE.md §Model Orchestration; resolver [`scripts/lib/model_routing.py`](scripts/lib/model_routing.py)):
- **Routine (low effort):** ALL sessions on local `gemma3:12b` via Ollama ($0). Routine quality check.
- **Max effort:** Flagged sessions (confidence < 0.7, duration > 5min, thumbs-down) on `gw-mistral-large` (`mistral-large-latest`) via the shared LiteLLM (`nllitellm01:4000`). Anthropic per-token spend = 0.

5-dimension rubric (1-5 each): Investigation Quality, Evidence-Based, Actionability, Safety Compliance, Completeness.

### Formalized Contracts

Structured requirements parsed from YT issue descriptions:
```
CONTRACT:
- Deliverable: Diagnosis only, no changes
- Max cost: $3
- Evidence: show running-config before and after
- Validation: confidence > 0.7
---
```

Build Prompt injects as success criteria. Agent must satisfy all requirements before marking complete.

### Additional Evaluation

| System | Frequency | Purpose |
|--------|-----------|---------|
| [Golden test suite](scripts/golden-test-suite.sh) | Biweekly + CI | 64 tests (incl. --quiet mode for regression gating) |
| [Goldset validation](scripts/goldset-validate.sh) | On demand | 9 tests + 10 synthetic scenarios for APE readiness |
| [Regression detector](scripts/regression-detector.sh) | Every 6h | 7d rolling confidence/cost/duration comparison, CrowdSec checks |
| [Metamorphic monitor](scripts/metamorphic-monitor.sh) | Every 6h | Auto-variant promotion, cost-adaptive routing, self-healing rollback |
| A/B testing | Continuous | react_v1 vs react_v2, deterministic by issue hash |

---

## 16. Guardrails & Safety

7-layer defense-in-depth — not just prompt instructions:

| Layer | Mechanism | Level | Cannot be bypassed by |
|-------|-----------|-------|----------------------|
| **Claude Code hooks** | [`unified-guard.sh`](scripts/hooks/unified-guard.sh): 78 blocked patterns (37 destructive + 22 exfil + 7 injection) + 12 protected file patterns. Merged guardrail for Bash, Edit, Write. | Deterministic | Anything — fires before permission check |
| **Exec enforcement** | [`safe-exec.sh`](openclaw/skills/safe-exec.sh): 30+ blocked patterns, rate limiting (30/min), exfiltration detection | Code | Prompt injection |
| **exec-approvals.json** | 36 specific skill patterns, no wildcards | Config | Prompt instruction |
| **Input sanitization** | 17 prompt injection patterns (encoding obfuscation, role confusion, delimiter injection, social engineering, instruction planting) stripped from inputs | Code | Direct bypass |
| **Credential scanning** | 16 PII/credential regex patterns redact tokens/keys before Matrix posting | Code | N/A |
| **Approval gates** | Autonomy-forward gate (2026-06-16, §29): reversible + prediction-backed changes auto-resolve; irreversible / HIGH / model-deviation / unpredicted changes require a human poll vote + SMS page | Workflow | Agent autonomy (floor is non-configurable) |
| **Evaluator-Optimizer** | Haiku-tier screening (routes to glm-4.7 via the centralized Model Orchestration layer) for high-stakes responses (3 nodes in Runner). Rewrites or escalates before posting. | Workflow | Agent self-approval |

Additional: AUTHORIZED_SENDERS filter, **EUR 5/session cost warning + $25/day plan-only** budget ceiling, zero hardcoded passwords (all env vars sourced from `.env`), confidence gating (< 0.5 = STOP).

### Adversarial Red-Team Program

54 test cases (32 baseline + 22 adversarial) in [`test-hook-blocks.py`](scripts/test-hook-blocks.py). Tests prompt injection bypass (unicode homoglyphs, base64 encoding, variable expansion), tool chaining misuse (wget+execute, python os.system, curl POST exfil), indirect exfiltration (DNS, log injection, /proc), and cross-tier escalation (docker exec, pct exec, kubectl exec). Quarterly schedule via chaos-calendar.sh. 12 bypass vectors hardened; 8 remaining tracked for follow-up.

### RAGAS RAG Quality Metrics

[`ragas-eval.py`](scripts/ragas-eval.py) evaluates RAG quality using `gw-deepseek` (DeepSeek `deepseek-v4-pro`) as judge via the shared LiteLLM, routed by the centralized Model Orchestration layer (pure Python, no external deps; Anthropic per-token spend = 0):
- Faithfulness: 0.88 (claim decomposition + NLI verification)
- Context Precision: 0.86 (weighted precision@k)
- Context Recall: 0.88 (reference coverage)

Golden set hardened April 2026 from 18 saturated queries (couldn't measure pipeline lifts — all configs scored 0.88+) to **33 queries with 15 hard-eval tagged** across 5 categories: multi-hop (requires ≥2 docs to answer), temporal ("last N days"), negation ("which do NOT"), meta (self-referential), cross-corpus (wiki + incident + transcript corroboration). Easy-vs-hard queries now show **10× faithfulness differential** (1.00 vs 0.10 on a 5-query sample), so retrieval changes are measurable again. Runner flags: `--limit N` and `--only-category hard-eval` for targeted runs. Prometheus metrics via [`write-ragas-metrics.sh`](scripts/write-ragas-metrics.sh).

### Weekly Hard-Retrieval Cron

[`weekly-eval-cron.sh`](scripts/weekly-eval-cron.sh) (Monday 05:00 UTC) runs [`run-hard-eval.py`](scripts/run-hard-eval.py) on the 50-query `hard-retrieval-v2` set + 10-query `hard-kg` set, emits 6 Prometheus metrics (`kb_hard_eval_hit_rate`, `kb_hard_eval_coverage_rate`, `kb_hard_eval_kg_coverage`, `kb_hard_eval_latency_p50_seconds`, `kb_hard_eval_latency_p95_seconds`, `kb_hard_eval_last_run_timestamp_seconds`). Manual baseline captured 2026-04-18: **judge_hit@5 = 0.90** (45/50), KG coverage 0.70 (7/10), p50 5.7s, p95 13.6s. Diagnostic flags: `--only-ids H06,H08,H12 --verbose --skip-kg` for per-query investigation with full retrieval chain + judge rationale.

### Chaos Engineering

159 experiments recorded (2026-07-08) across the scenario catalog. 6-layer safety architecture (rate limiting, graph validation, Turnstile auth, dead-man switch, abort threshold, preflight gates). Weekly baseline, monthly tunnel sweep, quarterly DMZ drill, semi-annual game day. 1s measurement resolution. Declarative catalog (25 experiments defined). Prometheus metrics + retrospective pipeline.

Scripts: [`chaos-test.py`](scripts/chaos-test.py), [`chaos_baseline.py`](scripts/chaos_baseline.py), [`chaos-calendar.sh`](scripts/chaos-calendar.sh), [`chaos_catalog.py`](scripts/chaos_catalog.py).

### Industry Benchmark (2026-04-15)

Scored against 23 industry sources (OWASP Top 10 LLM 2025, NIST AI RMF Agentic Profile, EU AI Act, Anthropic, OpenAI, LangChain survey, Microsoft AF 1.0, Gartner AI TRiSM, Gremlin CMM, OTel GenAI conventions, RAGAS). Full report: [`docs/industry-benchmark-2026-04-15.md`](docs/industry-benchmark-2026-04-15.md).

**Score: 4.10 / 5.00 (82%) -- Optimized maturity. E2E certified: 39/39 PASS.**

Key implementations:
- OTel GenAI semantic conventions + OTLP export to OpenObserve (cron */5)
- 5/5 NIST AG-MS.1 behavioral telemetry signals
- RAGAS evaluation pipeline (faithfulness 0.88, precision 0.86, recall 0.88)
- 54-test adversarial red-team program with quarterly schedule
- EU AI Act limited-risk assessment + QMS + NIST oversight boundary framework
- CycloneDX SBOM generation in CI + model provenance chain
- Agent decommissioning procedures + 153-tool risk classification
- Automated prompt refinement with regression gating

### Agent-Guide Benchmark — Anthropic + OpenAI (2026-06-26)

Two further epics scored the platform against the two canonical agent-building ebooks as **separate, source-pure, adversarially-verified scorecards**, then drove the gaps up:

- **IFRNLLEI01PRD-1422** — Anthropic, *Building Effective AI Agents* (+ *Effective Context Engineering for AI Agents* + Claude Agent SDK). [`docs/scorecard-anthropic-2026-06-26.md`](docs/scorecard-anthropic-2026-06-26.md).
- **IFRNLLEI01PRD-1423** — OpenAI, *A Practical Guide to Building Agents*. [`docs/scorecard-openai-2026-06-26.md`](docs/scorecard-openai-2026-06-26.md).
- **Provenance-tagged synthesis** (labelled join, not a blend): [`docs/benchmark-synthesis-2026-06-26.md`](docs/benchmark-synthesis-2026-06-26.md).

**Result: 12 of 14 dimensions at A.** The 2 remaining at B are **deliberate operator decisions** — guardrail layering (unified-guard kept OFF the dispatched path) and the human-intervention failure-threshold (kept as a passive Matrix warning, no SMS-page). Fixes shipped along the way included the model-router pipe-counting bug (818/818 sessions pinned to Opus → Sonnet routing for simple low-risk alerts, with a never-downgrade-risky floor), the revived OTLP export, a `MemoryMax=12G` cap + concurrent-session tripwire, and a clutch of dark-telemetry/parser fixes. Full detail: [§32](#32-agent-guide-benchmark--anthropic--openai-2026-06-26).

### Governance and Compliance

[`eu-ai-act-assessment.md`](docs/eu-ai-act-assessment.md) (limited-risk) | [`quality-management-system.md`](docs/quality-management-system.md) (Art. 17) | [`oversight-boundary-framework.md`](docs/oversight-boundary-framework.md) (NIST AG-GV.2) | [`agent-decommissioning.md`](docs/agent-decommissioning.md) (AG-MG.3) | [`tool-risk-classification.md`](docs/tool-risk-classification.md) (153 tools, AG-MP.1) | [`model-provenance.md`](docs/model-provenance.md) (OWASP LLM03)

---

## 17. Inter-Agent Communication (NL-A2A/v1)

Standardized protocol for all tier-to-tier messages. Spec: [`docs/a2a-protocol.md`](docs/a2a-protocol.md).

- **Agent Cards** — machine-readable capability declarations per tier ([`a2a/agent-cards/`](a2a/agent-cards/))
- **Message Envelope** — protocol, messageId, timestamp, from/to, type, issueId, payload
- **REVIEW_JSON Auto-Action** — AGREE (auto-approve), DISAGREE (pause), AUGMENT (resume with context)
- **Task Lifecycle** — `a2a_task_log` tracks escalation -> in_progress -> completed

---

## 3. RAG Pipeline

Five RAG channels fused via 5-signal Reciprocal Rank Fusion:

### Channel 1: Semantic (vector embeddings)

| Component | Detail |
|-----------|--------|
| Embedding model | nomic-embed-text (768 dims, F16) on Ollama (RTX 3090 Ti) |
| Execution | Local on both agent hosts (Ollama reachable on same subnet, no SSH) |
| Coverage | 25/25 entries (100%), backfill cron every 30min |
| Search | Cosine similarity (threshold 0.3) + keyword fallback |
| Triage integration | Step 1.5 in infra-triage, k8s-triage, security-triage |
| Dev integration | Query Knowledge runs semantic search for CUBEOS/MESHSAT |
| Knowledge source | `incident_knowledge` table (alert resolutions with embeddings) |
| Lessons source | `lessons_learned` table (30-day window, limit 5) |
| Health monitoring | `ollama_health` + `incident_knowledge_embedded` Prometheus metrics |

### Channel 2: Deterministic (hostname-routed CLAUDE.md + memory)

| Component | Detail |
|-----------|--------|
| CLAUDE.md files | 55 across all repos (IaC, products, gateway, RFCs, websites) |
| Routing | Hostname pattern → repo subdirectory (pve/, docker/, network/, k8s/, native/, edge/) |
| Extraction | Title + hostname mentions + "Known Issue"/"Never" sections + category-specific grep |
| Memory files | 117 feedback memories with operational rules ("NEVER do X") |
| Memory sync | `*/30` cron rsyncs feedback files from app-user to openclaw01 |
| Triage integration | Step 2-kb in infra-triage, k8s-triage; Step 1b in correlated-triage |
| Tier 2 integration | Build Prompt injects targeted CLAUDE.md paths + auto-retrieved memories |
| Token budget | ~2000 chars per lookup (memories first to survive truncation) |
| Repo sync | `*/30` cron pulls all 23 repos + gateway.db read replica on openclaw01 |

### Channel 3: Compiled Wiki Articles ([Karpathy-style](https://x.com/karpathy/status/2039805659525644595))

| Component | Detail |
|-----------|--------|
| Compiler | [`wiki-compile.py`](scripts/wiki-compile.py) — reads 7+ sources, compiles 88 articles |
| Articles | Per-host pages, operational rules, incident timeline, topology, services, runbooks, lab manifest |
| Embeddings | All articles chunked by `##` heading, embedded via nomic-embed-text, stored in `wiki_articles` table |
| RRF integration | 3rd signal in `rrf_score()` alongside semantic + keyword (extends [`kb-semantic-search.py`](scripts/kb-semantic-search.py)) |
| Incremental | SHA-256 checksums in `wiki/.compile-state.json` — only recompiles changed sources |
| Health checks | Staleness detection (line-number rot), coverage gaps (incidents without lessons), inconsistency detection |
| Cadence | Daily at 04:30 UTC + on-demand via `/wiki-compile` skill |
| Browsing | Plain markdown in [`wiki/`](wiki/index.md), renderable on GitLab |

### Channel 4: Session Transcripts ([MemPalace](https://github.com/milla-jovovich/mempalace))

| Component | Detail |
|-----------|--------|
| Source | Verbatim JSONL exchange-pair chunks stored in `session_transcripts` table |
| Embeddings | nomic-embed-text (768 dims), same as incident_knowledge |
| RRF weight | 0.4 (lower than summarized incident_knowledge at 1.0 to avoid noise from raw exchanges) |
| Archiver | [`archive-session-transcript.py`](scripts/archive-session-transcript.py) — chunks JSONL into exchange pairs, embeds, gzips original |
| Hooks | Stop hook (auto-save every 15 messages) + PreCompact hook (emergency save before context compression) |
| Temporal | `incident_knowledge.valid_until` column — invalidated entries excluded from all searches |

### Channel 5: Chaos Baselines

| Component | Detail |
|-----------|--------|
| Source | `chaos_experiments` table — verdict/convergence/recovery/MTTD/targets per run |
| Embeddings | nomic-embed-text (768 dims), indexed same as other signals |
| RRF weight | 0.35 |
| Purpose | "What did we learn from killing this tunnel last time?" answered by retrieval, not by running a new chaos test |
| FAISS parity | 70/70 vectors mirrored into `/var/claude-gateway/vector-indexes/chaos_experiments.faiss` (4/4 tables now covered — migration-ready) |

### Retrieval Intent Detectors (IFRNLLEI01PRD-609 / IFRNLLEI01PRD-616)

| Detector | Trigger | Behavior |
|---|---|---|
| **Temporal window** | Regex-matches "last N hours/days", "N hours ending YYYY-MM-DD", "on YYYY-MM-DD" | Filters `wiki_articles` by `source_mtime` column so stale hits are dropped. Adds `SELECT ... WHERE source_mtime BETWEEN since AND until`. |
| **mtime-sort intent** | Temporal window present AND listing verb (name/list/show/three/recent) OR created-in-window phrase | Bypasses semantic retrieval entirely. Returns top-N by `source_mtime DESC` from `wiki_articles`, path-prefix-filterable. Answers the "ls -ltm"-style question semantic search can't. |
| **Synth threshold** | Top rerank score < 0.4 | Calls **local qwen2.5 synth** (Ollama `qwen2.5:7b`, routed by the centralized Model Orchestration layer). On HTTP 429 / 401 / timeout / network error / forced-empty (all 5 modes injected via `SYNTH_HAIKU_FORCE_FAIL`), falls back to local qwen2.5 synth without breaking the response chain. |

CLI: `python3 scripts/kb-semantic-search.py list-recent --hours 48 --path-prefix memory/ --limit 10` returns an mtime-ranked listing directly, bypassing the RRF pipeline.

---

## 4. Compiled Knowledge Base (Karpathy-Style Wiki)

Following [Andrej Karpathy's LLM Knowledge Bases pattern](https://x.com/karpathy/status/2039805659525644595): raw data from 7+ fragmented knowledge stores is compiled into a unified, browsable markdown wiki with auto-maintained indexes and health checks.

### Why

The system accumulated knowledge across 7+ independent stores — each with its own access mechanism:
- 575 memory files (grep by keyword; 117 at the wiki's 2026-04 landing)
- 35 CLAUDE.md files (hostname pattern routing)
- 28 incident_knowledge rows (semantic vector search)
- 27 lessons_learned (SQL query)
- 94 openclaw_memory entries (key-value lookup)
- ~5,200 03_Lab reference files (Syncthing + lab-lookup.py)
- 51 docs (manual reading)

To answer "what do we know about nl-fw01?" required 5 separate lookups across 3 different mechanisms. No unified view existed.

### How It Works

[`scripts/wiki-compile.py`](scripts/wiki-compile.py) reads all sources, compiles them into 78 markdown articles organized by category:

| Category | Articles | Sources Used |
|----------|----------|-------------|
| **operations/** | operational-rules, runbooks, emergency-procedures, data-trust-hierarchy | feedback memories, OpenClaw skills, CLAUDE.md |
| **hosts/** | ~25 per-host pages (nl-fw01, nl-pve01, gr-fw01, ...) | CLAUDE.md + incidents + lessons + memories + 03_Lab refs |
| **incidents/** | chronological timeline + per-incident detail pages | incident_knowledge + postmortems + memories |
| **topology/** | nl-site, gr-site, vpn-mesh, k8s-clusters | CLAUDE.md (network/, edge/, k8s/) + VPN memories |
| **services/** | chatops-platform, openclaw, rag-pipeline, security-ops, seaweedfs | architecture docs + memories + skills |
| **decisions/** | architectural decisions index | project memories + audit docs |
| **lab/** | 03_Lab file manifest, NL/GR physical layer | directory walk + lab-lookup.py |
| **health/** | staleness report, coverage matrix | cross-source analysis |

**Incremental compilation:** SHA-256 checksums detect source changes. Only affected articles are recompiled. A full first compilation takes ~5s; incremental runs are instant when nothing changed.

**RAG integration:** All 88 articles are chunked by heading and embedded via nomic-embed-text. They appear as a 3rd ranking signal in the existing Reciprocal Rank Fusion search — alongside semantic (incident_knowledge) and keyword matches.

**Health checks:** The compiler detects:
- **Staleness** — memory files referencing specific line numbers that may have rotated
- **Coverage gaps** — incidents without lessons_learned, hosts in incidents without wiki pages
- **Knowledge observability** — total counts of sources compiled, gaps remaining

### Impact Assessment

Audited against all 7 benchmark frameworks. Full report: [`docs/wiki-kb-impact-audit.md`](docs/wiki-kb-impact-audit.md).

| Metric | Before | After |
|--------|--------|-------|
| Industry recommendations met | 16/17 (94%) | **17/17 (100%)** |
| Anti-patterns mitigated | 19/20 (95%) | **20/20 (100%)** |
| RAG signals | 2 (semantic + keyword) | **5 (+ wiki + session transcripts + chaos baselines)** |
| Knowledge articles | 0 | **78** |
| Lookups to answer "what do we know about host X?" | 5 | **1** |

---

## 18. Operating Modes & Commands

### Modes

| Mode | Frontend | Backend | Use Case |
|------|----------|---------|----------|
| `cc-cc` | n8n receivers (direct SSH) | Claude Code | **Default since 2026-04-29** — receivers dispatch straight to the runner host via `scripts/run-triage.sh` |
| `oc-cc` | OpenClaw | Claude Code via n8n | **Dead** — OpenClaw LXC (VMID_REDACTED) destroyed 2026-04-29 |
| `oc-oc` | OpenClaw | OpenClaw (self-contained) | **Dead** (LXC destroyed) |
| `cc-oc` | n8n | OpenClaw as backend | **Dead** (LXC destroyed) |

The cc-cc migration was driven by Anthropic's April-2026 OAuth-for-third-party policy + an OpenClaw MCP-bind regression. OpenClaw was retired 2026-04-29 and its LXC (VMID_REDACTED / nl-openclaw01) is destroyed ("not found on any node"); the `oc-*` modes are NOT restorable without rebuilding that LXC from scratch. The in-repo `openclaw/` directory (17 native skill dirs) is the artifact set of a retired subsystem, not a dormant fallback.

The mode abstraction is vestigial (slated for retirement): only `cc-cc` is live, `~/gateway.mode` was corrected to `cc-cc` on 2026-07-03 (it had sat stale at `oc-cc` since March — cosmetic either way, dispatch is hardwired), and switching to `oc-*` via `!mode` is no longer possible since the OpenClaw LXC was destroyed.

### Matrix Commands

| Command | Description |
|---------|-------------|
| `!session current/list/done/cancel/pause/resume` | Session management |
| `!issue status/info/start/stop/verify/done/close` | Issue lifecycle |
| `!pipeline status/logs/retry` | GitLab CI pipelines |
| `!mode status/oc-cc/oc-oc/cc-cc/cc-oc` | Operating mode switching |
| `!system status/processes` | System health |
| `!gateway offline/online/status` | Gateway control |
| `!debug` | Dump lock, sessions, queue, cooldown state |

---

## 19. Repository Structure

```
.
├── README.md                       # Concise overview
├── README.extensive.md             # This file — full technical reference
├── CLAUDE.md                       # Claude Code project instructions (<200 lines)
├── .claude/
│   ├── agents/                     # 11 sub-agents (Anthropic Academy patterns)
│   ├── skills/                     # 9 Claude Code skills (incl. wiki-compile)
│   ├── commands/review.md          # /review command
│   ├── settings.json               # Hooks configuration (full lifecycle: PreToolUse/PostToolUse/Session*/UserPromptSubmit/Stop/PreCompact)
│   └── rules/                      # 6 path-scoped rule files
├── a2a/agent-cards/                # NL-A2A/v1 capability declarations
├── docs/
│   ├── architecture.md             # Component details (workflows, MCP, sub-agents)
│   ├── installation.md             # Setup guide with cron configuration
│   ├── agentic-patterns-audit.md   # 21/21 pattern scorecard
│   ├── book-gap-analysis.md        # Remaining improvements from Gulli's book
│   ├── industry-agentic-references.md  # 6 industry sources → cross-cutting advice (Knowledge Source #3)
│   ├── tri-source-audit.md         # Platform scored against all 3 knowledge sources (11/11 A+)
│   ├── tri-source-eval-report-2026-04-07.md  # E2E test results + before/after scoring
│   ├── aci-tool-audit.md           # 10 MCP tools audited against 8-point ACI checklist
│   ├── evaluation-process.md       # 3-set eval model, flywheel, CI gate, judge calibration
│   ├── a2a-protocol.md             # Inter-agent communication spec
│   ├── known-failure-rules.md      # 27 rules from 26 bugs
│   ├── llm-usage-tracking.md       # LLM cost tracking, Prometheus metrics, portfolio APIs
│   ├── mempalace-details.md        # MemPalace integration: tables, scripts, RAG formula
│   ├── compiled-wiki-details.md    # Wiki compiler: source mapping, CLI usage
│   └── maintenance-mode-details.md # ASA reboot suppression, Freedom ISP, PVE maintenance
├── grafana/                        # Dashboard JSON exports (13 dashboards, 90+ panels)
├── openclaw/
│   ├── SOUL.md                     # OpenClaw system prompt (623 lines)
│   ├── openclaw.json               # OpenClaw configuration
│   ├── exec-approvals.json         # 36 skill patterns (no wildcards)
│   ├── claude-knowledge-lookup.sh   # CLAUDE.md + memory knowledge extraction
│   └── skills/                     # 17 native skills (incl. 4 always-on protocol skills)
├── scripts/
│   ├── hooks/                      # 13 Claude Code hook scripts (PreToolUse/PostToolUse/Session*/UserPromptSubmit/Stop/PreCompact)
│   ├── openclaw-repo-sync.sh       # */30 cron: git pull 23 repos + memory + DB sync to openclaw01
│   ├── grade-prompts.sh            # Daily prompt scorecard
│   ├── score-trajectory.sh         # JSONL trajectory scoring
│   ├── llm-judge.sh               # LLM-as-a-Judge (gemma3:12b local; max-effort via shared LiteLLM gw-mistral-large)
│   ├── golden-test-suite.sh        # 64-test benchmark
│   ├── regression-detector.sh      # 7d rolling regression
│   ├── metamorphic-monitor.sh      # Self-modification monitor
│   ├── post-reboot-vpn-check.sh    # 12 cross-site subnet probes
│   ├── backup-gateway-db.sh        # Daily SQLite backup
│   ├── kb-semantic-search.py       # 5-signal RRF search (semantic + keyword + wiki + transcripts + chaos baselines)
│   ├── wiki-compile.py             # Karpathy-style wiki compiler (7+ sources → 88 articles)
│   ├── archive-session-transcript.py  # MemPalace: JSONL → exchange-pair chunks → embeddings
│   ├── agent-diary.py              # MemPalace: persistent per-agent memory (write/read/inject)
│   ├── build-prompt-layers.py      # MemPalace: L0-L3 layered injection with token caps
│   └── ... (433 scripts total)
├── wiki/                           # Compiled knowledge base (78 auto-generated articles)
│   ├── index.md                    # Master index with categorized links
│   ├── operations/                 # Operational rules, runbooks, emergency procedures
│   ├── hosts/                      # Per-host compiled pages (~25 notable hosts)
│   ├── incidents/                  # Chronological timeline + detail pages
│   ├── topology/                   # Network topology (NL, GR, VPN mesh, K8s)
│   ├── services/                   # Service architecture (ChatOps, OpenClaw, RAG, security)
│   ├── lab/                        # 03_Lab file manifest
│   └── health/                     # Staleness report + coverage matrix
├── workflows/                      # 27 n8n workflow JSON exports
├── mcp-proxmox/                    # Custom Proxmox MCP server (15 tools)
└── .gitlab-ci.yml                  # CI: validate, test, review, GitHub sync
```

---

## 20. Installation

See [`docs/installation.md`](docs/installation.md) for full setup guide.

**Quick start:**
```bash
git clone https://github.com/papadopouloskyriakos/agentic-chatops.git
cd agentic-chatops
cp .env.example .env   # Add your credentials
```

---

## 21. References

### Knowledge Sources
1. **[Agentic Design Patterns](https://drive.google.com/file/d/1-5ho2aSZ-z0FcW8W_jMUoFSQ5hTKvJ43/view?usp=drivesdk)** by Antonio Gulli (Springer, 2025) — 21 patterns, all implemented
2. **[Claude Certified Architect – Foundations Exam Guide](docs/Claude+Certified+Architect+–+Foundations+Certification+Exam+Guide.pdf)** (Anthropic) — Sub-agent design, multi-tier architecture foundations
3. **[Industry Agentic References](docs/industry-agentic-references.md)** — 6 industry sources (Anthropic, OpenAI, LangChain, Microsoft) synthesized into cross-cutting advice: tool design, evals, memory, RAG, guardrails, 17 prioritized recommendations

### Additional References
- **[MemPalace](https://github.com/milla-jovovich/mempalace)** — 8 patterns ported: verbatim transcript storage, temporal KG, agent diaries, 4th RAG signal, L0-L3 layered injection, Stop/PreCompact hooks, contradiction detection. See [`docs/mempalace-details.md`](docs/mempalace-details.md).
- **[Andrej Karpathy — LLM Knowledge Bases](https://x.com/karpathy/status/2039805659525644595)** (Apr 2026) — Pattern for LLM-compiled wikis from raw data sources. Inspired the [compiled knowledge base](wiki/index.md).
- **[Anthropic Official Documentation](https://docs.anthropic.com/)** — Claude Code hooks, subagents, skills, MCP security, prompt engineering (17 sources audited)
- **[Anthropic Academy](https://academy.anthropic.com/)** — Sub-agent design: structured output, obstacle reporting, limited tools, decision rule
- **[MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)** — Scope minimization, token validation
- **[n8n](https://n8n.io/)** — Workflow automation engine (self-hosted)
- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Standardized LLM-tool integration

---

## 22. OpenAI Agents SDK Adoption Batch

On 2026-04-20 the official [openai/openai-agents-python](https://github.com/openai/openai-agents-python) repo was audited (v0.14.2, ~88K LOC) and compared to the claude-gateway substrate. The comparison surfaced 11 gaps — 9 were implemented as YT issues [IFRNLLEI01PRD-635..643](docs/runbooks/), two were explicitly deferred (output guardrails + per-tool guardrails). Net result: the system now has a **versioned, typed, recoverable agentic substrate** that the old string-based Matrix pipeline couldn't offer.

### Summary of adoptions

| # | YT | Adoption | OpenAI reference | Our take |
|---|----|----------|------------------|----------|
| 1 | [IFRNLLEI01PRD-635](docs/runbooks/) | **Schema versioning** on 9 session/audit tables | `src/agents/run_state.py:131` `CURRENT_SCHEMA_VERSION` + `SCHEMA_VERSION_SUMMARIES` | Central registry [`scripts/lib/schema_version.py`](scripts/lib/schema_version.py); every writer stamps `schema_version=1`; readers `check_row()` fail-fast on future versions. |
| 2 | [IFRNLLEI01PRD-636](docs/runbooks/) | **Immutable per-turn snapshots** | `src/agents/run_state.py` `RunState` immutable dataclass | `session_state_snapshot` table + [`scripts/lib/snapshot.py`](scripts/lib/snapshot.py) `capture/latest/rollback_to/prune`. Hook captures BEFORE each mutating tool; 7-day retention. |
| 3 | [IFRNLLEI01PRD-637](docs/runbooks/) | **Typed event taxonomy** — 13 event subtypes | `src/agents/stream_events.py` 11 `RunItemStreamEvent` subtypes | [`scripts/lib/session_events.py`](scripts/lib/session_events.py) dataclasses + `event_log` table + [`scripts/emit-event.py`](scripts/emit-event.py) CLI + [`scripts/write-event-metrics.sh`](scripts/write-event-metrics.sh) Prometheus exporter. |
| 4 | [IFRNLLEI01PRD-638](docs/runbooks/) | **Per-turn lifecycle hooks** | `src/agents/lifecycle.py` `RunHooks` (`on_agent_start/end`, `on_llm_start/end`, `on_tool_start/end`, `on_handoff`, `on_final_output`) | 4 new Claude Code hooks (`session-start.sh`, `post-tool-use.sh`, `user-prompt-submit.sh`, **`session-end.sh`** = `on_final_output` equivalent) + `session_turns` table + [`scripts/lib/turn_counter.py`](scripts/lib/turn_counter.py). |
| 5 | [IFRNLLEI01PRD-639](docs/runbooks/) | **3-behavior rejection taxonomy** | `src/agents/tool_guardrails.py` `ToolGuardrailFunctionOutput` (`allow` / `reject_content` / `raise_exception`) | `unified-guard.sh` + `audit-bash.sh` + `protect-files.sh` refactored; deny vs reject_content differentiated by message prose + `tool_guardrail_rejection` event; audit invariant enforces non-empty messages. |
| 6 | [IFRNLLEI01PRD-640](docs/runbooks/) | **`HandoffInputData` envelope** | `src/agents/handoffs/__init__.py:142` | [`scripts/lib/handoff.py`](scripts/lib/handoff.py) `@dataclass` + zlib+b64 marshal (176 KB → 752 B = **0.43% ratio**) + `handoff_log` audit table. `from_b64()` fails fast on future `envelope_version`. |
| 7 | [IFRNLLEI01PRD-641](docs/runbooks/) | **Optional transcript compaction on handoff** | `src/agents/handoffs/history.py` `nest_handoff_history` | [`scripts/compact-handoff-history.py`](scripts/compact-handoff-history.py) — local `gemma3:12b` first, `rag_synth_ollama` circuit-breaker aware (model selection centralized via the Model Orchestration layer; the legacy in-code Haiku fallback label resolves through the Claude-Code plane rather than direct Anthropic per-token calls). `HANDOFF_COMPACT_MODE=off\|auto\|force`. Emits `handoff_compaction` event with `pre_bytes`, `post_bytes`, `model`, `ratio`. |
| 8 | [IFRNLLEI01PRD-642](docs/runbooks/) | **Agent-as-tool wrapper** for 11 sub-agents | `@function_tool` wraps an agent | [`scripts/agent_as_tool.py`](scripts/agent_as_tool.py) CLI + registry + mocked-Claude-friendly invoker. Designed for the ambiguous-risk band (0.4–0.6), complements — does not replace — our deterministic routing. |
| 9 | [IFRNLLEI01PRD-643](docs/runbooks/) | **Handoff depth counter + cycle detection** | `MaxTurnsExceeded` in `run_internal/run_loop.py` | [`scripts/lib/handoff_depth.py`](scripts/lib/handoff_depth.py) atomic bump with SQLite IMMEDIATE transactions + `PRAGMA busy_timeout=10000`. Depth ≥ 5 forces `[POLL]`, ≥ 10 hard-halts, cycles refused and logged. |

### Explicit divergences from the SDK

- **Tracing:** the SDK auto-exports spans to `api.openai.com/v1/traces/ingest` by default. We do not — our OTel pipeline goes to OpenObserve (OTLP), and event_log is SQLite-local.
- **Strict Pydantic schemas on sub-agent output:** we pass on this. Local gemma/qwen sub-agents hallucinate under strict validation; we keep soft parsing + regex fallback + confidence extraction.
- **Always-on `nest_handoff_history`:** the SDK compacts by default. We made it **opt-in per escalation** because human T1 triage wants visibility into incremental discoveries.
- **`needs_approval: bool | callable` per tool (OpenAI's gap #5):** we already have a richer multi-signal risk classifier at session level. Not adopting.
- **`OutputGuardrail` (OpenAI's gap #6):** genuine gap — **deferred**, tracked as follow-up work.

### What did not change

The outer-facing Matrix UX, OpenClaw Tier-1 skills, RAG pipeline, prompt patches, evaluation flywheel, chaos engine, MITRE mapping — all unchanged. The adoption is a substrate-layer upgrade; operator-visible behaviour only differs when something goes wrong (snapshots → rollback, cycles → refused, rejections → retry hint instead of a wall).

---

## 23. QA Suite

[`scripts/qa/run-qa-suite.sh`](scripts/qa/run-qa-suite.sh) is a pytest-style bash harness that verifies every adoption end-to-end with a JSON scorecard output.

### Scorecard (last full run, 2026-07-08)

```
pass=834  fail=0  skip=2
```

**85 suite files** live (78 in `suites/` + 7 in `e2e/`; 44 at the 2026-04-23 hardened run), ~7 min total runtime under full-suite load, exits 0 iff `fail=0` (drop-in CI). The per-suite timeout guard now honors a raise-only `# QA_SUITE_TIMEOUT: <n>` header declaration (2026-07-08) so a legitimately-slow e2e suite gets load headroom without loosening strict-CI's explicit `QA_PER_SUITE_TIMEOUT` env. Since the initial adoption batch landed:

- **Per-suite timeout guard** ([IFRNLLEI01PRD-724](#26-skill-authoring-uplift-agents-cli-audit-2026-04-23)) — every suite wrapped in `timeout --signal=TERM --kill-after=5 ${QA_PER_SUITE_TIMEOUT:-120}s`. Synthetic FAIL record emitted on timeout so the orchestrator never wedges silently. Validated by `test-724-per-suite-timeout-guard.sh` (5/5).
- **`test-645-prompt-trials.sh`** — 16 tests for the preference-iterating patcher (assignment hash determinism, Welch t-test edges, timeout sweeper, finalize idempotency).
- **`test-646-cli-session-rag-capture.sh`** — 12 tests spanning all three CLI-capture tiers (flag parsing, watermark roundtrip, parse-tool-calls path inference, extractor sanitization + idempotent `fetch_pending`, `CLI_INCIDENT_WEIGHT` guards).
- **`test-651-…-655-teacher-agent-*.sh`** — 62 tests covering the 5 teacher-agent tiers (foundation, intelligence, interface, loop, gate).
- **`test-656-skill-index-fresh.sh`** (6/6) — drift guard for [`docs/skills-index.md`](docs/skills-index.md); fails if `render-skill-index.py` would produce a different output than what is committed.
- **`test-660-user-vocabulary.sh`** (10/10) — schema + semantics of `config/user-vocabulary.json`; every entry is either `ambiguous` with `candidates` or has a `canonical` resolution.
- **`test-718-evidence-missing.sh`** (9/9) — `check_evidence()` + `--check-evidence` CLI mode; CONFIDENCE ≥ 0.8 claims with no code fence → `evidence_missing` signal → `[POLL]` forced.
- **`test-726-prom-alert-rules.sh`** (4/4) — runs `promtool test rules` against `prometheus/alert-rules/agentic-health.test.yml` *inside the live monitoring Prom pod*. Asserts `SkillPrereqMissing` fires at T=31m (30m `for`), clears on recovery; `SkillMetricsExporterStale` fires at T=41m.
- **`test-727-evidence-suppression.sh`** (5/5) — extracts live `jsCode` from the n8n Runner's Prepare Result node and runs 4 behavioural cases to assert `[AUTO-RESOLVE]` markers are stripped and a `GUARDRAIL EVIDENCE-MISSING:` banner is prepended when evidence is absent on high-confidence replies.

### Harness

| File | Role |
|------|------|
| [`scripts/qa/run-qa-suite.sh`](scripts/qa/run-qa-suite.sh) | Orchestrator — writes scorecard JSON + summary to `reports/` |
| [`scripts/qa/lib/assert.sh`](scripts/qa/lib/assert.sh) | Assertion DSL: `assert_eq/ne/gt/lt/contains/exit_code` + `start_test/end_test` |
| [`scripts/qa/lib/fixtures.sh`](scripts/qa/lib/fixtures.sh) | `fresh_db` (loads schema.sql + runs migrations), `make_mock_claude`, `seed_session` |
| [`scripts/qa/lib/bench.sh`](scripts/qa/lib/bench.sh) | `bench_time_ms` with p50/p95 + JSONL emit |
| [`scripts/qa/lib/mock_http.py`](scripts/qa/lib/mock_http.py) | Forking stdlib HTTP mock — ollama-ok / ollama-500 / anthropic-ok behaviors for offline compaction tests |

### Coverage

| Category | Test count |
|---|---|
| Per-issue suites (SDK batch, patcher, CLI-RAG, teacher-agent 5 tiers, agents-cli uplift) | ~35 files |
| E2E cross-cutting scenarios | 6 files — happy path, cycle prevention, crash rollback, forward-compat, envelope-to-subagent, compaction-in-handoff |
| Benchmarks | 2 files — 7 metrics captured as JSONL |
| Skill-index drift guard (-656) | 6 tests — deterministic render + diff against committed `docs/skills-index.md` |
| Skill-requires audit | 17/17 SKILL.md + agent files with `version` + `requires` frontmatter, all prereqs satisfied |
| User-vocabulary semantics (-660) | 10 tests — schema validity + `ambiguous`/`canonical` mutual exclusivity |
| `evidence_missing` signal (-718) | 9 tests — CONFIDENCE ≥ 0.8 with no code fence → signal + `[POLL]` |
| Promtool alert-rule verification (-726) | 4 tests — `SkillPrereqMissing` fires at T=31m inside live Prom pod |
| Evidence-suppression in Runner (-727) | 5 tests — Prepare Result `jsCode` extracted live + 4 behavioural cases |
| Per-suite timeout guard (-724) | 5 tests — `timeout` wrapper fires, synthetic FAIL record emitted |
| Writer stamping | **11 / 11** writers + **5 / 5** n8n workflow INSERT sites |
| Pattern-by-pattern | **53** deny patterns + **32** reject_content / allow patterns |
| Per-event payload shapes | **13 / 13** event classes |
| Concurrent safety | 8 parallel `handoff_depth.bump()` → race condition surfaced + fixed |

### Benchmarks (p95)

| Metric | p50 | p95 | Target |
|---|---|---|---|
| `event_emit_ms` | 100 | 111 | < 500 ms |
| `handoff_bump_ms` | 99 | 108 | < 500 ms |
| `handoff_envelope_encode_ms` | 74 | 76 | < 500 ms |
| `snapshot_capture_ms` | 82 | 86 | < 500 ms |
| `unified_guard_ms` (hook per Bash call) | 190 | 198 | < 500 ms |
| `handoff_compression_ratio` | — | **0.43 %** | < 10 % (beat 23×) |
| `migration_006_on_10k_rows` | — | ~200 ms | < 30 s |

### Code fixes surfaced by the suite

Writing the tests exposed five real issues that were silently present in the production-bound code:

1. **Race condition** in `handoff_depth.py` — Python's sqlite3 default `isolation_level=""` was wrapping each statement in its own implicit transaction, defeating `BEGIN IMMEDIATE` and silently losing updates under concurrent `bump()`. Fixed by switching to `isolation_level=None` + `PRAGMA busy_timeout=10000`.
2. **Legacy hooks** (`audit-bash.sh`, `protect-files.sh`) still emitted `{"decision":"allow"}` JSON — the exact pattern that triggers Claude Code "Hook JSON output validation failed" errors. Refactored to match unified-guard's silent-allow + explanatory-deny contract.
3. **`on_final_output` was simply missing** from the -638 acceptance; there was no `session-end.sh`. Implemented now.
4. **Five writers** (`agent-diary.py`, `archive-session-transcript.py`, `backfill-agent-diary.py`, `capture-execution-log.py`, `parse-tool-calls.py`) hardcoded `~/gitlab/products/.../gateway.db` instead of honouring `GATEWAY_DB`. Fixed — now testable against a temp DB.
5. **`schema.sql` was missing canonical definitions** for `event_log`, `handoff_log`, `session_state_snapshot`, `session_turns`; fresh installs depended entirely on migrations. Added CREATE TABLEs + indices so `sqlite3 gateway.db < schema.sql` now produces a complete schema.

### Running

```bash
scripts/qa/run-qa-suite.sh                    # full suite (~45 s)
scripts/qa/run-qa-suite.sh --verbose          # per-test pass/fail lines
scripts/qa/run-qa-suite.sh --filter=637       # run only 637-* suites
scripts/qa/run-qa-suite.sh --no-bench         # skip benchmarks
```

Reports land in `scripts/qa/reports/` (gitignored): `scorecard-<timestamp>.json` + `summary-<timestamp>.txt`.

---

## 24. Preference-Iterating Prompt Patcher

The original self-improving-prompts pipeline (`prompt-improver.py --apply`) was **single-shot**: when the judge detected a below-threshold dimension it generated *one* instruction patch and wrote it to `config/prompt-patches.json`. That works when the patch is good; it fails silently when the patch is marginal or worse than doing nothing.

[IFRNLLEI01PRD-645](docs/runbooks/prompt-patch-trials.md) replaced it with an **N-candidate A/B trial framework** — policy iteration at the prompt-policy level.

### Flow

```
┌────────────────────────────┐       ┌──────────────────────────────────┐
│ prompt-patch-trial.py      │       │ Runner: Query Knowledge SSH node │
│ --analyze | --start        │       │ emits PROMPT_PATCHES + new       │
│ (manual or cron)           │       │ PROMPT_TRIAL_INSTRUCTIONS lines  │
└───────────────┬────────────┘       └─────────────────┬────────────────┘
                │                                      │
                │ start_trial()                        │ prompt-trial-assign.py
                │ 3 candidates                         │ --issue X --surface S
                ▼                                      ▼
       ┌───────────────────────┐              ┌─────────────────────────┐
       │ prompt_patch_trial    │◀─── record ──│ assign_and_record() via │
       │ (status='active',     │              │ deterministic BLAKE2b   │
       │  candidates_json[])   │              └─────────────────────────┘
       └──────────┬────────────┘                        │
                  │                         ┌───────────────────────────┐
                  │                         │ session_trial_assignment  │
                  │                         │ (issue_id, trial_id,      │
                  │                         │  variant_idx)             │
                  │                         └───────────────────────────┘
                  ▼
       ┌──────────────────────┐             ┌───────────────────────────┐
       │ finalize-prompt-     │◀── Welch ───│ session_judgment          │
       │ trials.py            │   t-test    │ (per-dim scores)          │
       │ (daily cron 03:17)   │             └───────────────────────────┘
       └──────────┬───────────┘
                  │  if lift ≥ 0.05 and p < 0.1
                  └─── promote winner ────▶ config/prompt-patches.json
                                           (source: "trial:N:idx=I:label=L")
```

### Mechanics

- **3 candidate variants per low-scoring dimension:** *concise* / *detailed* / *examples*. Hand-authored in `scripts/prompt-patch-trial.py::CANDIDATE_POOL` (not LLM-generated — keeps the search space deterministic and audit-traceable).
- **Assignment:** `hash(issue_id || trial_id) % (N+1)` via BLAKE2b. Arm `N` is the no-patch control. Near-uniform distribution verified in the QA suite for 400 synthetic issue IDs.
- **Finalize criteria:** each arm must reach `PROMPT_TRIAL_MIN_SAMPLES` (default 15). One-sided Welch t-test with a normal-distribution approximation of the tail probability (avoids a scipy dependency). Winner promoted only if lift ≥ `PROMPT_TRIAL_MIN_LIFT` (0.05) **and** `p < PROMPT_TRIAL_P_THRESHOLD` (0.1). Otherwise → `aborted_no_winner`. Trials older than 14 days → `aborted_timeout` via the sweeper.
- **Race-safety:** `scripts/lib/prompt_patch_trial.py` uses `sqlite3.connect(isolation_level=None)` + `PRAGMA busy_timeout=10000` so concurrent Runner sessions assigning to the same trial don't lose writes. A partial unique index enforces one active trial per `(surface, dimension)`.
- **Opt-in:** creation is gated by `PROMPT_TRIAL_ENABLED=1`. If no trials are active the Runner's Query Knowledge node falls through to the legacy `PROMPT_PATCHES` path — zero-cost when not in use.
- **Observability:** 4 Prometheus metrics via `scripts/write-trial-metrics.sh` — `prompt_trials_active`, `prompt_trials_completed_total`, `prompt_trials_aborted_total`, `prompt_trial_winner_lift`. Grafana "ChatOps Platform Performance" dashboard has a new panel.

### Tables

- **`prompt_patch_trial`** — one row per active/completed trial. `candidates_json` is a JSON array of `{label, instruction}`. `baseline_mean` is the control arm's per-dim score at trial start. On finalize: `status`, `winner_idx`, `winner_mean`, `winner_p_value`, `reason` populated.
- **`session_trial_assignment`** — `(issue_id, trial_id, variant_idx)` audit of every assignment. Retained for rollback traceability even when the trial is closed.

Full runbook: [`docs/runbooks/prompt-patch-trials.md`](docs/runbooks/prompt-patch-trials.md). Migration: `scripts/migrations/012_prompt_patch_trial.sql`. Tests: `scripts/qa/suites/test-645-prompt-trials.sh` — 16/16 PASS.

> **Status (2026-04-20):** library + CLI + finalizer + metrics live. `PROMPT_TRIAL_ENABLED=1`. Build Prompt n8n wiring landed via a validator-gated `n8n_update_partial_workflow` on the same day. First finalize pass after the earliest trial reaches 60+ judged sessions — expect mid-May 2026.

---

## 25. CLI-Session RAG Capture

The agentic Session End workflow populates `session_transcripts`, `tool_call_log`, and `incident_knowledge` for every YT-backed Runner session. Interactive **Claude Code CLI** sessions — typed in a terminal, no webhook, no YT issue — historically only had cost/token capture via `poll-claude-usage.sh`. Their reasoning, tool use, and outcomes never reached RAG.

[IFRNLLEI01PRD-646/-647/-648](docs/runbooks/cli-session-rag-capture.md) close that gap with a **single-cron 3-tier pipeline**:

```
┌───────────────────────────────────┐
│  ~/.claude/projects/**/*.jsonl    │  ← CLI session files (UUID-named)
└────────────────┬──────────────────┘
                 ▼
┌────────────────────────────────────────────────────────────────┐
│  scripts/backfill-cli-transcripts.sh  (cron 04:30 UTC daily)   │
│  ├── Tier 1 (-646)  archive-session-transcript.py              │
│  │     chunks exchange pairs → session_transcripts + embed     │
│  │     doc-chain refine (>5000 assistant chars) → chunk_-1     │
│  ├── Tier 3 (-648)  parse-tool-calls.py  ← per-file chain      │
│  │     tool_use/tool_result pairs → tool_call_log              │
│  │     extract_issue_id_from_path() CLI fallback: cli-<uuid>   │
│  └── Tier 2 (-647)  extract-cli-knowledge.py  ← after all files│
│        gemma3:12b format=json over chunk_-1 summaries          │
│        → incident_knowledge with project='chatops-cli'         │
└────────────────────────────────────────────────────────────────┘
```

### Design decisions

- **Why `issue_id='cli-<uuid>'`:** every row in every table stays joinable by one key. A CLI session now has an `issue_id` even though no YouTrack ticket exists.
- **Why `project='chatops-cli'`:** existing `incident_knowledge` rows have empty project. The new value lets retrieval discount CLI rows without deleting them (see `CLI_INCIDENT_WEIGHT` below).
- **Why gemma3:12b local-only (no Haiku fallback):** CLI sessions are low-priority, retrieval weight is already discounted, and local capacity is adequate. Matches the 2026-04-19 judge/synth local-first flip.
- **Why byte-offset watermark:** a stable JSONL whose size hasn't grown since the last cron run is skipped entirely — no re-chunking wasted work. `~/gitlab/products/cubeos/claude-context/.cli-transcript-watermark.json`.
- **Why idempotent everywhere:** archive checks `session_transcripts(issue_id, chunk_index)` UNIQUE; parse-tool-calls skips already-processed `session_id` rows; extract skips rows with existing `incident_knowledge` via LEFT JOIN. Safe to re-run arbitrarily.

### Retrieval weighting

`kb-semantic-search.py` has a new tunable:

```python
# IFRNLLEI01PRD-647
CLI_INCIDENT_WEIGHT = float(os.environ.get("CLI_INCIDENT_WEIGHT", "0.75"))
```

In the main semantic ranker, `sim *= CLI_INCIDENT_WEIGHT` for rows where `project == 'chatops-cli'`. Real infra incidents with similar cosine similarity now rank higher in close ties. Disable by setting `CLI_INCIDENT_WEIGHT=1.0`; suppress CLI rows entirely with `0.0`.

### Soak-test numbers (2026-04-20, 10 files drained)

| Metric | Value |
|---|---|
| files processed | 10 |
| transcript chunks inserted | 12 |
| tool-call rows inserted | 245 |
| chunk_index=-1 summaries produced | 4 |
| `incident_knowledge` rows extracted | 4 |
| Tier 2 extractor elapsed (warm cache) | 21.4 s / 4 rows |
| representative extraction | `subsystem=sqlite-schema, tags=[schema, migration, versioning, data], confidence=0.95` |

### Cron

```cron
30 4 * * * /app/claude-gateway/scripts/backfill-cli-transcripts.sh --embed --oldest-first --limit 50 >> /home/app-user/logs/claude-gateway/cli-transcript-backfill.log 2>&1
```

At 50 files/night and a ~2300-file backlog, drain completes in ~46 days. Raise `--limit` to drain faster. Cron installed 2026-04-20.

### Files

| File | Role |
|---|---|
| [`scripts/backfill-cli-transcripts.sh`](scripts/backfill-cli-transcripts.sh) | Orchestrator — flag parsing, watermark, per-file chain |
| [`scripts/archive-session-transcript.py`](scripts/archive-session-transcript.py) | Tier 1 — pre-existing, CLI format already handled via `msg_type == 'user'` path (line 98-107) |
| [`scripts/parse-tool-calls.py`](scripts/parse-tool-calls.py) | Tier 3 — patched `extract_issue_id_from_path()` with CLI fallback |
| [`scripts/extract-cli-knowledge.py`](scripts/extract-cli-knowledge.py) | Tier 2 — new; Ollama `format=json`, breaker-aware, local-only |

Full runbook: [`docs/runbooks/cli-session-rag-capture.md`](docs/runbooks/cli-session-rag-capture.md). Tests: `scripts/qa/suites/test-646-cli-session-rag-capture.sh` — 12/12 PASS.

---

## 26. Skill Authoring Uplift (agents-cli audit, 2026-04-23)

A 2026-04-23 `/effort max` audit compared this repo against [`google/agents-cli`](https://github.com/google/agents-cli) v0.1.1 — a pure skill-library + closed-source PyPI-CLI wrapper for Google's ADK (seven markdown-only skills, one MkDocs site, no runtime code in the repo, PRs not accepted). Two parallel `Explore` subagents walked both codebases end-to-end; four ground-truth files were read directly (the agents-cli `workflow` + `eval` SKILL.md, our `.claude/skills/triage/SKILL.md`, and `.claude/settings.json`). Plan at `/home/app-user/.claude/plans/drifting-napping-donut.md`; audit memory at `memory/agents_cli_audit_20260423.md`.

**Headline:** claude-gateway won 9 / 16 dimensions on raw capability (runtime, state, RAG, observability, safety, human-in-the-loop, multi-site, domain breadth) but trailed decisively on the 6 **skill-authoring** dimensions (phase-gate choreography, discoverability, anti-guidance, inline behavioral anti-patterns, governance/versioning, skill index). Those six were closed in an 11-commit umbrella ([IFRNLLEI01PRD-712](docs/scorecard-post-agents-cli-adoption.md), Phases A→J) direct-pushed to main — **0 reverts, 0 hotfixes**.

### Phase-by-phase changelog

| Phase | Issue | Commit | What landed |
|-------|-------|--------|-------------|
| A | -713 | `04a6fe2` | Anti-guidance trailing clauses ("Do NOT use for X") + `## Reference Files` + `## Related Skills` on 16 `.md` files |
| B | -714 | `2d1860a` | New master [`.claude/skills/chatops-workflow/SKILL.md`](.claude/skills/chatops-workflow/SKILL.md) (Phase 0→6 lifecycle, Debugging Protocol, Proving-Your-Work directive, Shortcuts-to-Resist list, vocabulary map); CLAUDE.md shrink 40,093 → 36,319 B |
| C | -715 | `3ca3b29` | `version:` + `requires: {bins, env}` frontmatter on 17 skills/agents; [`scripts/render-skill-index.py`](scripts/render-skill-index.py) → committed [`docs/skills-index.md`](docs/skills-index.md); drift-gated by `test-656-skill-index-fresh.sh` |
| D | -716 | `dc68944` | [`scripts/audit-skill-requires.sh`](scripts/audit-skill-requires.sh) + [`scripts/write-skill-metrics.sh`](scripts/write-skill-metrics.sh) (cron `*/5`); two new alerts `SkillPrereqMissing` + `SkillMetricsExporterStale`; holistic-health §37 |
| E | -717 | `af500fa` | `## Shortcuts to Resist` tables inline on 11 agents — **46 rows** drawn from `memory/feedback_*.md` with source citations |
| F | -718 | `4aee7e5` | `check_evidence()` + `--check-evidence` CLI mode in [`scripts/classify-session-risk.py`](scripts/classify-session-risk.py); new `evidence_missing` signal forces `[POLL]` when `CONFIDENCE ≥ 0.8` but reply has no tool output / code fence |
| G | -719 | `6872841` | [`config/user-vocabulary.json`](config/user-vocabulary.json) (20 entries); prompt-submit hook scan emits typed `vocabulary` events to `event_log` |
| H | -720 | `0527d03` | Final scorecard memo [`docs/scorecard-post-agents-cli-adoption.md`](docs/scorecard-post-agents-cli-adoption.md) |
| I | -722 | `69afd12` | Runner Build-Prompt force-injection of the master skill body; marker-delimited for surgical removal; rollback anchor preserved at `/tmp/runner-pre-IMMUTABLE.json` (chmod 400) |
| (cleanup) | -724 | `0ef09cf`, `734e637` | Per-suite `QA_PER_SUITE_TIMEOUT` guard (synthetic FAIL record on wedge); per-skill semver convention at [`docs/runbooks/skill-versioning.md`](docs/runbooks/skill-versioning.md) + [`scripts/audit-skill-versions.sh`](scripts/audit-skill-versions.sh); `skill-metrics.prom` chmod 0644 fix so node_exporter can scrape |
| J1–J5 | -712 | `6047fe7`, `50d71f4`, `c4a2c46`, `f4efa7d` | E2E hardening proofs: live `vocabulary` event (`event_log` row 34), `promtool test rules` inside live Prom pod, force-injection proven by real Runner session, `check_evidence()` JS mirror in Prepare Result node, 5 pre-existing QA fails closed |

### 16-dimension scorecard (1 = worst, 5 = best-in-class)

| # | Dimension | Before | After | Evidence |
|---|-----------|:------:|:-----:|----------|
| 1 | Runtime orchestration | 5 | 5 | unchanged — 27 n8n workflows active (post-NVIDIA: +session-replay) |
| 2 | State persistence | 5 | 5 | unchanged — 43 SQLite tables (post-NVIDIA: +long_horizon_replay_results) |
| 3 | RAG / knowledge retrieval | 5 | 5 | unchanged — 5-signal RRF |
| 4 | Observability / SLOs | 5 | 5 | +1 Prom exporter (`write-skill-metrics.sh`); 2 new alerts (`SkillPrereqMissing`, `SkillMetricsExporterStale`) |
| 5 | Safety / guardrails | 4 | **5** | `evidence_missing` machine-enforces the evidence-first rule; `check_evidence()` CLI available to any caller |
| 6 | Testing / eval | 4 | **5** | +27 tests (test-656/-660/-718/-724/-726/-727) all PASS |
| 7 | Human-in-the-loop | 5 | 5 | unchanged — `[POLL]` forcing on evidence-missing is additive |
| 8 | Multi-user / multi-site | 5 | 5 | unchanged |
| 9 | **Skill authoring discipline** | **3** | **5** | 17 SKILL.md with `version` + `requires` + anti-guidance + Reference Files + Related Skills + Shortcuts |
| 10 | **Skill discoverability / index** | **2** | **5** | `render-skill-index.py` → drift-gated `docs/skills-index.md`; wired into wiki-compile |
| 11 | **"When NOT to use" anti-guidance** | **2** | **5** | trailing "Do NOT use for X (use /other-skill)" on 16 primary skills/agents |
| 12 | **Phase-gate lifecycle choreography** | **2** | **5** | `chatops-workflow/SKILL.md` (258 LOC) — Phase 0→6, exit criteria per phase, force-injected into every Runner session |
| 13 | **Behavioral anti-patterns baked into skills** | **3** | **5** | 46 Shortcuts-to-Resist rows across 11 agents (3–5 per agent), each citing the source `memory/feedback_*.md` |
| 14 | Docs site / single source of truth | 3 | 4 | auto-generated skill index eliminates CLAUDE.md drift on the skills section |
| 15 | **Governance / versioning of skill content** | **2** | **5** | semver convention + `audit-skill-versions.sh` advisory drift detection; 11 agents + master retroactively bumped `1.0.0 → 1.1.0` for Phase E/F/G additions |
| 16 | Domain breadth / depth | 5 | 5 | unchanged |

**Average:** 3.94 → **4.94** (+1.00). **Dimensions at 5:** 9/16 → **13/16** (+4). All 6 targeted gap dimensions closed (5 at 5/5, 1 at 4/5).

### Explicit non-adoptions

We deliberately did **not** copy six patterns present in agents-cli:

- **Closed-source PyPI CLI wheel** — agents-cli's actual runtime isn't in-repo. Our ops visibility is a feature.
- **MkDocs as skill-authoring surface** — we already have `wiki-site/` + `wiki-compile.py` with Lunr and embeddings.
- **Always-on `nest_handoff_history`** — our compaction is opt-in per escalation (keeps incremental-discovery visibility for T1).
- **Prose-only guardrails** — we enforce via hooks + `audit-bash.sh` + `protect-files.sh`; the agents-cli "STOP — Do NOT write code yet" prose is additive at best.
- **Zero-test repo** — we have 411 passing QA tests.
- **`npx skills add` distribution model** — we aren't a library shipped to external users; our skills are operational.

### J1–J5 hardening proofs (same-day follow-up)

The Phase H umbrella memo initially described the batch as "shipped and unit-tested". An operator audit asked "is this 100% hardened-and-proven e2e?" — the honest answer was *no*. J1–J5 closed the gap with live evidence:

| # | What was proven | How |
|---|-----------------|-----|
| J1 | `user-prompt-submit.sh` vocabulary hook wired end-to-end | Fired with literal "check the firewall" payload; `event_log` row id=34 captured with shape `{kind:vocabulary, match_type:ambiguous, phrase:"the firewall", extra:"nl-fw01;gr-fw01"}` |
| J2 | `SkillPrereqMissing` + `SkillMetricsExporterStale` alert rules fire/clear under real conditions | `test-726-prom-alert-rules.sh` runs `promtool test rules` against `prometheus/alert-rules/agentic-health.test.yml` *inside the live monitoring Prom pod* — SkillPrereqMissing at T=31m (30m `for`), SkillMetricsExporterStale at T=41m |
| J3 | Force-injected master skill body is actually read by Claude | Synthetic payload POSTed to `/webhook/youtrack-webhook`; real Runner → Claude Code pipeline fired; assistant's FIRST tool call was `grep -i "Phase 0" /tmp/claude-run-*.jsonl` and its reply opened *"Phase 0 confirmed in injected master skill body"* |
| J4 | `check_evidence()` fires on real Runner sessions (not just CLI) | Prepare Result node modified via the 11-step safety sequence (per [`docs/runbooks/n8n-code-node-safety.md`](docs/runbooks/n8n-code-node-safety.md)) — JS mirror of the Python `check_evidence()` strips `[AUTO-RESOLVE]` markers on high-confidence no-fence replies and prepends a `GUARDRAIL EVIDENCE-MISSING:` banner. `test-727-evidence-suppression.sh` extracts live jsCode + runs 4 behavioural cases (5/5 PASS) |
| J5 | 5 pre-existing QA fails closed (honest baseline) | schema.sql gained missing `content_preview` + `source_mtime` columns (migration 004/005 columns weren't codified, so fresh DBs broke teacher-agent chat); test-653 stale assertion for a removed node updated; test-637 flake cleared under the new 120 s per-suite timeout |

**Final QA state:** 397/5/2 = 98.27% → **411/0/2 = 99.52%** at the agents-cli batch close. After §27 (NVIDIA P0+P1, 2026-04-29) the suite is **468/0/2 across 51 suite files** with 7 new test files added for the G1-G4 deliverables.

### Files of record

| File | What it is |
|------|-----------|
| [`docs/scorecard-post-agents-cli-adoption.md`](docs/scorecard-post-agents-cli-adoption.md) | Canonical memo — before/after scorecard, validation gates, unit economics, acceptance criteria |
| [`docs/runbooks/skill-versioning.md`](docs/runbooks/skill-versioning.md) | Per-skill semver contract — when to bump patch/minor/MAJOR tied to the SKILL "contract" (name, description, allowed-tools, requires, Output Format) |
| [`.claude/skills/chatops-workflow/SKILL.md`](.claude/skills/chatops-workflow/SKILL.md) | Master phase-gate skill — force-injected into every Runner session |
| [`docs/skills-index.md`](docs/skills-index.md) | Auto-generated skills index, drift-gated by `test-656` |
| [`config/user-vocabulary.json`](config/user-vocabulary.json) | 20-entry operator-vocabulary map; `ambiguous` entries log `vocabulary` events |
| [`scripts/classify-session-risk.py`](scripts/classify-session-risk.py) | Now emits `evidence_missing` signal when CONFIDENCE ≥ 0.8 without a visible tool output block |
| [`scripts/audit-skill-requires.sh`](scripts/audit-skill-requires.sh) + [`scripts/audit-skill-versions.sh`](scripts/audit-skill-versions.sh) | Machine-audits of SKILL.md frontmatter (prereqs + git-history-based version drift) |

### Relationship to the OpenAI Agents SDK batch (§22)

The two batches are complementary, not overlapping. §22 (OpenAI SDK, 2026-04-20) restructured the **runtime substrate** — schema versioning, typed events, handoff envelopes, per-turn snapshots, agent-as-tool. §26 (agents-cli, 2026-04-23) restructured the **authoring discipline around skills and agents** — phase-gate choreography, anti-guidance, discoverability, behavioral inoculation, governance. No files from §22 were revisited; no files from §26 touch the runtime substrate. Both sit in the same repo under the same QA suite; Phase-D skill-metrics lives on the same Prometheus scraper as the typed-event exporter.

---

## 27. NVIDIA DLI Cross-Audit + P0+P1 Implementation (2026-04-29)

The 19-transcript NVIDIA Deep Learning Institute *Agentic AI Systems* course (Vadim Kudlai) was the only major agentic-AI source not yet evaluated against this platform. A 12-dimension cross-audit on 2026-04-29 graded the system at **A (4.4 / 5.0)** — the lowest of any of the 9 sources audited (Anthropic, Karpathy, Gulli, Google A2A + agents-cli, MemPalace, OpenAI Agents SDK, 15-source industry research, ChatSecOps frameworks, NVIDIA DLI). A same-day implementation closed all 7 P0+P1 gaps and lifted the NVIDIA aggregate to **A+ (4.83 / 5.0)** — restoring the platform to A+ across all 9 sources (9-source aggregate: A+ 4.79).

**4 commits (G1–G4) under YouTrack umbrella IFRNLLEI01PRD-747** (children -748..-751), all direct-pushed to main, zero reverts, zero hotfixes. **57 / 57 new QA tests pass.**

### G1 — Long-horizon reasoning replay + Greek-extended jailbreak corpus (IFRNLLEI01PRD-748)

- [`scripts/long-horizon-replay.py`](scripts/long-horizon-replay.py) — replays the 30 longest historical sessions weekly (Mon 05:00 UTC); pure SQLite reads, no live Claude calls. Scores: trace_coherence (Jaccard of adjacent assistant turn word-sets), tool_efficiency (unique / total tool calls), poll_correctness (alignment vs `session_risk_audit`), cost_per_turn_z. Composite is the unweighted mean. New table `long_horizon_replay_results` (migration 015). New alert `LongHorizonReplayStale` (>9 days no run).
- [`scripts/qa/fixtures/jailbreak-corpus.json`](scripts/qa/fixtures/jailbreak-corpus.json) — **39 fixtures** across the 5 NVIDIA-DLI-08 vectors (asterisk-obfuscation, persona-shift, retroactive-history-edit, context-injection, lost-in-middle-bait), including **8 Greek operator-language fixtures** (`αγνόησε προηγούμενες οδηγίες`, `ξέχασε όλα όσα ξέρεις`, `είσαι τώρα`, `παρίστανε ότι`, `παράκαμψε περιορισμούς`, `όπως ήδη συμφωνήσαμε`, `ο χρήστης έχει ήδη εγκρίνει`, `στην προηγούμενη απάντηση`).
- [`scripts/lib/jailbreak_detector.py`](scripts/lib/jailbreak_detector.py) — pure-regex detector with Greek-language regex extension. NamedTuple-based (avoids the Python 3.11 `dataclass(frozen=True)` + `importlib.util` quirk that surfaced during integration). New alert `JailbreakBypassDetected` on any expected-deny that returned allow.

### G2 — Intermediate semantic rail (DARK-FIRST) + Grammar-constrained decoding (IFRNLLEI01PRD-749)

- [`scripts/lib/intermediate_rail.py`](scripts/lib/intermediate_rail.py) — heuristic + Ollama dual-backend topic-rail check. Heuristic fallback (regex keyword buckets per category) runs in <2 ms; Ollama backend (`gemma3:12b`, 3 s budget) runs when available. Inserted as the `Check Intermediate Rail` Code node between `Build Plan` and `Classify Risk` in the Runner workflow (now **50 nodes**). The n8n task-runner sandbox blocks `child_process` in Code nodes — the rail emits via in-process `python3 -m lib.intermediate_rail` invocation. Emits `intermediate_rail_check` event_log row per session. New alert `IntermediateRailDriftHigh` (>20% out-of-distribution rate over 24h, `for: 24h`). **Observe-only** — does NOT block; the soft-gate / hard-gate evaluation is deferred ≥7 days post-data per the audit's recommended posture.
- [`scripts/lib/grammars/`](scripts/lib/grammars/) — JSON Schemas for `quiz-grader`, `quiz-generator`, `risk-classifier`. Passed to Ollama via the `format` field when `OLLAMA_USE_GRAMMAR=1` (default on). Falls back to `format=json` on schema rejection. Circuit-breaker semantics preserved (`rag_synth_ollama`).

### G3 — Team-formation skill + Inference-Time-Scaling explicit budget (IFRNLLEI01PRD-750)

- [`.claude/skills/team-formation/SKILL.md`](.claude/skills/team-formation/SKILL.md) (v1.0.0) + [`scripts/lib/team_formation.py`](scripts/lib/team_formation.py) — pure-rule library mapping `(alert_category, risk_level, hostname)` → `{agents[], rationale}`. KNOWN_AGENTS inventory enforced against `.claude/agents/*.md` (test-750 fails if a roster references a non-existent agent file). Build Prompt synchronously calls `python3 -m lib.team_formation --json` at session start; injects a `## Team Charter (advisory)` section with the proposed roster. Same JSON emitted as `team_charter` event_log row.
- `EXTENDED_THINKING_BUDGET_S` env var (+ optional per-category `EXTENDED_THINKING_BUDGET_BY_CATEGORY_JSON`) drives a `## Reasoning Budget` Build Prompt section. `its_budget_consumed` event captures `(budget_s, observed_turns, observed_thinking_chars, category)` at session end.

### G4 — Server-side session-replay endpoint (IFRNLLEI01PRD-751)

- [`workflows/claude-gateway-session-replay.json`](workflows/claude-gateway-session-replay.json) — new n8n workflow (id `lJEGboDYLmx25kBo`, 7 nodes, **ACTIVE**). Webhook POST `/session-replay` accepts `{session_id, prompt}`. The Validate Input Code node performs format-only validation (the n8n sandbox blocks `child_process`, so the sqlite3 existence check is performed inside the SSH command instead). The SSH Claude Resume node runs a single bash chain: `sqlite3` count → if 0, return `{"is_error":true,"error_type":"unknown_session"}` → else `claude -r <session_id> -p ...`. Returns JSON. **HTTP 404** on unknown session, **HTTP 400** on malformed input. `session_replay_invoked` event captures `{outcome, prompt_chars, cost_usd, num_turns, model}`.

### Schema + observability deltas

| Surface | Before | After |
|---|---|---|
| `event_log.schema_version` | 1 | **4** |
| `event_log` event_types | 13 | **17** (added: `team_charter`, `its_budget_consumed`, `intermediate_rail_check`, `session_replay_invoked`) |
| Schema-versioned tables | 18 | **19** (added: `long_horizon_replay_results`) |
| Total SQLite tables | 42 | **43** |
| n8n workflows | 26 | **27** (added: session-replay) |
| Runner workflow nodes | 49 | **50** (added: Check Intermediate Rail) |
| Skills (`.claude/skills/`) | 6 | **7** (added: team-formation) |
| QA suite files | 44 | **51** (+7 new: test-{long-horizon-replay, jailbreak-corpus, team-formation, its-budget, intermediate-rail, grammar-decoding, session-replay}.sh) |
| QA total tests | 411 | **468** (+57 new) |
| Prometheus alert rules in `agentic-health.yml` | 2 | **5** (added: LongHorizonReplayStale, JailbreakBypassDetected, IntermediateRailDriftHigh) |
| New cron entries | — | **5** (3 metric writers `*/10`/`*/15`/`*/30` + 2 weekly QA fires Mon/Wed 05:00 UTC) |

### Operator gates closed (cert pass 2, same day)

The initial implementation landed with deferred gates (DARK-FIRST rail node insertion, session-replay activation, Greek fixtures, cron installation, YT state transitions). All 5 gates were closed the same day:

1. **Cron entries installed** — operator's crontab updated with 5 NVIDIA entries + `format-crontab-reference.py` regenerated.
2. **Check Intermediate Rail Code node inserted** — Runner workflow now 50 nodes; live-smoked `intermediate_rail_check` event_log row written with `schema_version=4`.
3. **Session-replay workflow activated** — `lJEGboDYLmx25kBo` `active=true`; HTTP 404 + HTTP 400 paths verified live; positive path executes SSH (parse-error on stale session-id is acknowledged).
4. **Greek-language jailbreak fixtures added** — corpus 31 → 39, detector regex extended; 8 / 8 Greek match.
5. **YouTrack issues -747..-751 transitioned to Done** via direct REST POST. The MCP container's `update_issue_state` omits the `$type: "StateBundleElement"` discriminator on the value object, returning a misleading `"Unknown workflow restriction"` error. Workaround captured in `feedback_youtrack_mcp_state_bug.md` (operator memory).

### NVIDIA-rubric scorecard (1 = worst, 5 = best-in-class)

| # | Dimension | Pre | Post | Δ | Evidence |
|---|---|:---:|:---:|:---:|---|
| 1 | Agent foundations & PRA loop | 5 | 5 | — | unchanged |
| 2 | LLM-limitation awareness (jailbreaks, hallucination, fragility) | 4.5 | **5** | +0.5 | 39-fixture corpus + 8 Greek + JailbreakBypassDetected alert + weekly cron |
| 3 | Structured output / constrained decoding | 3.5 | **4.5** | +1.0 | 3 JSON Schemas in `scripts/lib/grammars/`, OLLAMA_USE_GRAMMAR env var with format=json fallback |
| 4 | Tool use & ReAct | 5 | 5 | — | unchanged |
| 5 | Multi-agent orchestration | 5 | 5 | — | unchanged; team-formation makes the implicit graph machine-emitted |
| 6 | State management / concurrency | 3 | 3 | — | UNCHANGED — single-operator design preserved by intent (P2 multi-tenant LangGraph migration is out-of-scope) |
| 7 | Looping / inference-time scaling | 4 | **4.5** | +0.5 | EXTENDED_THINKING_BUDGET_S + its_budget_consumed event |
| 8 | Caching & retrieval (RAG) | 5 | 5 | — | unchanged |
| 9 | Data flywheel | 4 | **4.5** | +0.5 | long-horizon replay closes the long-horizon eval pillar |
| 10 | Guardrails | 4.5 | **5** | +0.5 | intermediate-rail + IntermediateRailDriftHigh alert + DARK-FIRST n8n insertion |
| 11 | Server-side patterns | 4 | **4.5** | +0.5 | session-replay endpoint formalises stored=true semantics |
| 12 | Production observability | 5 | 5 | — | unchanged |

**Aggregate:** 4.4 → **4.83** (+0.43). **Dimensions at 5/5:** 5/12 → **9/12** (+4). **Dimensions below A:** 2/12 (#3, #6) → **1/12 (#6 only — intentional)**.

### Files of record

| File | What it is |
|------|-----------|
| [`docs/agentic-platform-state-2026-04-29.md`](docs/agentic-platform-state-2026-04-29.md) | **Single source-of-record** — merges audit + cert + rescored docs into one canonical "where the platform is right now" reference |
| [`docs/nvidia-dli-cross-audit-2026-04-29.md`](docs/nvidia-dli-cross-audit-2026-04-29.md) | Original 12-dim cross-audit + 9-source master scorecard + P0/P1/P2 gap-closure roadmap |
| [`docs/nvidia-p0-p1-certification-2026-04-29.md`](docs/nvidia-p0-p1-certification-2026-04-29.md) | E2E cert: 57/57 G1-G4 tests, integration audits clean, live smoke fires, schema-bump trace, operator-gate closure |
| [`docs/nvidia-dli-cross-audit-rescored-2026-04-29.md`](docs/nvidia-dli-cross-audit-rescored-2026-04-29.md) | Per-dimension delta after implementation — A (4.4) → A+ (4.83) |

### Relationship to §22 (OpenAI SDK) and §26 (agents-cli)

§22, §26, and §27 are sequenced and complementary. §22 (2026-04-20) restructured the **runtime substrate**. §26 (2026-04-23) restructured the **authoring discipline**. §27 (2026-04-29) closed the **eval + guardrail dimensions** the prior two batches did not directly address: long-horizon evaluation, jailbreak corpus + Greek-language coverage, intermediate-step semantic rails, JSON-Schema-constrained decoding, explicit team-formation, ITS budget, and a stored=true server-side replay endpoint. All three sit on the same QA suite; the new G1-G4 tests bring the orchestrator to 51 suite files / 468 cases.

### Lessons captured during the batch (reusable)

- **`dataclass(frozen=True)` + `importlib.util.spec_from_file_location` is a Python 3.11 trap** — `_is_type` looks up `cls.__module__` which is `None` when the module isn't in `sys.modules`. Use `NamedTuple` instead for any library that downstream tests load via `importlib.util`.
- **n8n task-runner sandbox disallows `child_process`** — any subprocess work in a Code node must go through SSH nodes instead. Caught when the original session-replay validator tried to shell out to sqlite3; fixed by moving the existence check into the SSH command.
- **YouTrack MCP `update_issue_state` bug** — `tonyzorin/youtrack-mcp:latest` omits the `$type: "StateBundleElement"` discriminator. Direct REST POST works. Permanent workaround captured in the operator memory `feedback_youtrack_mcp_state_bug.md`.

---

## 28. Infragraph — Causal World Model + Model-Based Control (2026-06-09)

Built and shipped in a single day across MRs !20–!29 (claude-gateway) + !327 (IaC), epic IFRNLLEI01PRD-1029. The first 13 of 16 child issues are done and deployed; the remaining three (-1040 gate review, -1041 autonomy widening, -1043 closeout verdict) are gated on accumulated evidence and operator sign-off by design.

### What it is

A queryable **causal dependency graph of the entire infrastructure** (361 nodes / 468 edges live as of 2026-07-08; rides the shared GraphRAG tables, 721 entities / 661 relationships combined) with per-edge dynamics, integrated into the alert-triage pipeline as a genuine **model-free → model-based shift enforced in control flow, not data**. The distinction matters: this is not "a new data source the LLM may choose to query." It is a deterministic predictor the orchestrator calls, whose output is mandatory and machine-verified.

### Sources of truth (layered, per-edge provenance)

Every edge carries a `source`, a `confidence`, and (for automated layers) a 7-day `valid_until` so a dead seeder degrades into visible `stale_edges` rather than silently-wrong predictions. In trust order:

| Source | Contributes | Confidence | Freshness |
|---|---|---|---|
| `pve` | vm/lxc → pve_node placement (live cluster API, 188 guests) | 0.95 | daily 04:10, +7d |
| `librenms` | device dependency parents (AP→switch→firewall chains) | 0.90 | daily, +7d |
| `netbox` | device→site membership + physical cable-derived edges | 0.85–0.90 | daily, +7d |
| `declared` | operator edges (`docs/host-blast-radius.md`) + chaos `TUNNEL_GRAPH_EDGE` | 0.85–1.0 | open-ended |
| `incident` | triage.log co-occurrence miner (≥3 obs, ≥3× lift, ≤2 hops) | **capped 0.75** | hourly |

`chaos` upgrades any exercised edge to 0.9 with real delay/recovery numbers (159 experiments as of 2026-07-08). The 0.75 cap on the mined layer is structural: it sits below the 0.8 suppression-eligibility cutoff, so statistical coincidence alone can never propose suppression.

### The three-part invariant

1. **Prediction outside the LLM** — `scripts/infragraph-query.py {blast-radius,deps,cascade,predict,explain,health}` is deterministic graph traversal. The n8n Runner's `Commit Prediction` node (between Classify Risk and Build Prompt) commits a plan-hash-keyed `infragraph_predictions` row before the Claude session starts. The model consumes predictions; it never produces them.
2. **Mandatory + non-bypassable** — the Prepare Result node default-DENIES: any `[POLL]` without a committed prediction matching the classified plan is rewritten to `[POLL-WITHHELD:NO-PREDICTION]` and demoted to analysis-only. `INFRAGRAPH_DISABLED=1` therefore means analysis-only mode — the remediation lane fails **closed**. (The advisory triage/enrichment lane fails open, so alert triage never blocks on infragraph.)
3. **Mechanical verification** — `scripts/infragraph-verify.py` / `lib.action_verdict()` is the only verdict author. After execution it diffs observed alerts against the prediction and writes `match / partial / deviation`; deviation = surprise = never auto-resolve. The LLM that proposed the action has no write path to those columns.

### Falsifiable evaluation

Every prediction is recorded alongside a degree-preserving **shuffled-graph negative control** — if the real graph doesn't beat the shuffle, it encodes nothing and the eval fails. The canonical 2026-05-11 cascade backtest (the n8n-OOM mass-flap that originally dragged auto-resolve to 28%) was iterated openly: 19.5%/0.65 → 26.4%/0.61 → 28.7%/0.52 → **34.5% coverage / 38.2% escalation coverage / control ratio 0.367**, each round driven by what the misses exposed (LibreNMS parents → NetBox cables → common-cause sibling expansion). The frozen per-incident auto-resolve baseline for the eventual closeout verdict is **41.6% (30d)**.

### Earned authority, operator-gated

Suppression authority is granted **per rule by the operator**. `infragraph-propose-blast-radius.py` (`--scan` hourly / `--bootstrap`) emits a control YouTrack issue with an evidence table and a candidate Phase-1b rule; nothing suppresses until `--approve`, which writes the rule keyed to the control issue. Closing the issue instantly revokes it (existing tier-1 Phase-1b semantics, zero hot-path code). The first machine-proposed rule (nlpve04 cascade fold) was approved 2026-06-09 and verified production-exact against the live tier-1 matcher. The weekly scorecard (`test-results/infragraph-scorecard.json`), the `InfragraphPrecisionDrop` alert, and the `audit-risk-decisions.sh` invariant section form the continuous revocation review.

### Surfaces

- **6 crons** on the runner host: seed `10 4`, learn `:25`, metrics exporter `*/5`, eval `:40`, scorecard `Mon 05:10`, propose-scan `:45`.
- **Prometheus**: `infragraph.prom` exporter + 3 alerts (`InfragraphMetricsExporterStale`, `InfragraphSeedStale`, `InfragraphPrecisionDrop`) deployed via IaC, verified in-cluster; holistic-health §39.
- **QA**: 65 tests across 8 suites (schema, query, seed, learn, phase-A, proposal, gate, verify), including bypass attempts driven against the gate code extracted from the live workflow export.
- **Schema**: G15 section in `schema.sql` + migration `016_infragraph.sql`; rides the existing G10 GraphRAG tables (`source_table='infragraph'`) plus the two sidecar tables.

**Live prediction quality (honest numbers, 2026-07-08 scorecard):** 30-day advisory-cascade precision 5.1% / recall 12.6% — low in absolute terms but **8× better than the shuffled-graph control** (control ratio 0.126 ≤ 0.5, the falsifiable criterion still passing). The B→C promotion gate (broad autonomous gating) and the operator's 0.80-precision fold-gate (-1040) are both correctly **not met** (fold-band precision 0.53), so cascade authority stays advisory + per-approved-rule. The fail-closed action lane meanwhile adjudicated 130 plan-hash predictions: 74 match / 23 partial / 33 deviation — every deviation blocked from auto-resolve.

Runbook: [`docs/runbooks/infragraph.md`](docs/runbooks/infragraph.md) (RB-IG-001). Plan of record: [`docs/plans/infragraph-implementation-plan.md`](docs/plans/infragraph-implementation-plan.md).

---

## 29. Autonomy-Forward Gate — Human as Circuit-Breaker (2026-06-16)

**Epic IFRNLLEI01PRD-1102.** The original risk gate (IFRNLLEI01PRD-632, §16) was binary: `auto_approve = (risk == "low")`; everything else posted a Matrix approval poll. But the operator had voted on **almost none** of those polls in the prior two months (notifications off) — so ~56% of sessions escalated, got no vote, and hit the 30-min `shouldPause` (stranded), while genuinely-critical sessions paged **no one** (the only SMS path was Alertmanager tier-1). The gate was a dead-end on both axes. This epic flips the operating model to **human-as-circuit-breaker**: most work auto-resolves; only a tight critical set pages the operator by SMS.

### The 3 bands (`scripts/classify-session-risk.py`, emitted when enabled)

| Band | Trigger | Action | Operator |
|------|---------|--------|----------|
| `AUTO` | `risk==low`, OR reversible + prediction-eligible MIXED (non-P0, blast < `INFRAGRAPH_BLAST_THRESHOLD`) | agent emits `[AUTO-RESOLVE]`; no poll, no SMS | none |
| `AUTO_NOTICE` | reversible MIXED touching a **P0 host** or with **wide blast** | `[AUTO-RESOLVE]` **+ parallel SMS** | out-of-band veto (`!session abort`) |
| `POLL_PAUSE` | HIGH / irreversible / Infragraph deviation / partial verdict / no committed prediction / jailbreak / P0-reboot | `[POLL]`; no-vote **PAUSES**; **SMS at poll-post** | mandatory |

`POLL_PROCEED` is a reserved band, folded into `AUTO_NOTICE` (the bridge timeout-pause only engages the *awaiting-approval text* flow, not the `[POLL]` flow it would use; and the operator watches SMS, not polls).

### Components
- **`classify-session-risk.py`** — band engine (`_assign_bands()`); `IRREVERSIBLE_PATTERNS` re-tagging that *also closed real gaps* (`terraform destroy` was only MIXED; `mkfs`/`dd of=/dev/`/`zpool destroy`/`dropdb` were **unmatched** → could have auto-resolved a wipe); `_P0_HOSTS_BASE` (mirrors `docs/host-blast-radius.md`); `_fire_session_sms()` best-effort POST to `/alert-session` at classify time (earlier than the poll → more reaction time; never blocks classify).
- **`alertmanager-twilio-bridge.py`** — new `POST /alert-session` (the missing session→SMS path), dedup by `issue_id`, critical-gated defense-in-depth, `/metrics` `session_sms_total{outcome}` counter. Systemd `--user` service `alertmanager-twilio-bridge.service`.
- **Runner `Build Prompt`** — band-aware directive (AUTO/AUTO_NOTICE → `[AUTO-RESOLVE]`; POLL_PAUSE → `[POLL]`); backward-compatible (no band → exact legacy text). Validated by the n8n Code-node validator before PUT.
- **`session_risk_audit` v2** — adds `band` / `auto_proceed_on_timeout` / `sms_required`; makes "how often did we AUTO vs pause" a one-line SQL.

### Safety floor (never auto-resolved, NOT operator-configurable)
Infragraph **deviation**; **irreversible**-destructive ops; remediation with **no committed plan_hash prediction** (the fail-CLOSED IFRNLLEI01PRD-1044 gate — §28); **partial** verdict; **jailbreak**; **P0-reboot**. Auto-resolve keys on the fail-CLOSED prediction gate, *not* the fail-OPEN advisory. `scripts/audit-risk-decisions.sh` runs a **band-aware weekly invariant** that FAILS (and prints the kill-switch) if any auto-approved row is outside AUTO/AUTO_NOTICE or carries a floor signal.

### Enable / kill-switch (sentinel files — no n8n edit, instant)
```bash
touch ~/gateway.autonomy_forward ~/gateway.autonomy_session_sms   # ON
rm ~/gateway.autonomy_forward                                     # instant revert to byte-identical legacy
```
An explicitly-set env var (`AUTONOMY_FORWARD` / `AUTONOMY_SESSION_SMS`) overrides the sentinel (tests/CI). Knobs: `AUTONOMY_P0_HOSTS_EXTRA`, `AUTONOMY_SOFT_REVERSIBLE_EXTRA`, `AUTONOMY_P0_REBOOT_AUTO` (default off), `INFRAGRAPH_BLAST_THRESHOLD` (8).

QA: `scripts/qa/suites/test-1103-autonomy-bands.sh` (14 checks — parity, every band, floor-never-auto, P0-doc↔constant drift, schema v2, audit-write). Runbook: [`docs/runbooks/risk-based-auto-approval.md`](docs/runbooks/risk-based-auto-approval.md) § Autonomy-forward gate. Full build memory: [`memory/autonomy_forward_gate_20260616.md`](memory/autonomy_forward_gate_20260616.md).

---

## 30. Self-Verifying Reliability Layer (2026-06-21)

The system's documented #1 failure class is the **months-long silent dark**: the auto-resolve pipeline dead across 5 layers, scanners dark 5 weeks (cron PATH), SeaweedFS stuck 145 days, an apiserver crash-looping 27 days — all invisible because standard alerting treats *absent data* as *no problem*. This batch (roadmap Stage-0/1; MRs !40–!45 + IaC !336) reframes reliability of the autonomy loop itself as a continuously-verified subsystem. All items shipped to `main`, live, and E2E-verified (per-item QA + an adversarial-synthesis pass).

### 30.1 Control-plane dead-man's-switch (IFRNLLEI01PRD-1152)
`gateway-watchdog.sh` (cron `*/5`) already watched the 9 receivers + runner and auto-healed; the gap was that **nothing watched the watchdog**, and its alerts went to muted Matrix. It now emits, via a `trap emit_metrics EXIT` (fires on the maintenance / n8n-down / normal / `set -e`-abort paths alike):
- `gateway_watchdog_heartbeat_timestamp_seconds{host}` — the heartbeat.
- `gateway_n8n_healthy`, `gateway_workflow_active{workflow}` (as-found, pre-reactivation).

Two PrometheusRules (tier=1+critical → `twilio-tier1` **SMS**): `GatewayWatchdogHeartbeatStale` = `(time() - max(hb) > 900) OR absent(hb)` — the **`absent()` clause is the crux** (a plain staleness expr returns no series when node_exporter/host is down → "no data = no alert", the exact gap this kills); and `GatewayWorkflowInactive`. NOT named `Watchdog` (that alertname is null-routed in main.tf). Holistic §38 `watchdog-deadman`. QA `test-1152` (7/7). Runbook `docs/runbooks/gateway-watchdog-deadman.md`.

### 30.2 False-auto-resolve + repeat-incident governance, autonomy-forward (IFRNLLEI01PRD-1153)
Now that the gate auto-resolves real Tier-2 incidents, the cleanest root-cause-discipline signal is **recurrence**. `write-governance-metrics.py` (cron `*/17`) computes it from `triage.log` (the only source carrying host+rule+outcome — `session_log` lacks host/rule; only ~1/33 auto-resolves link to `incident_knowledge` by issue_id). Metrics: `chatops_false_auto_resolve_total`, `chatops_repeat_incident_classes`, `chatops_governance_demote_candidates`, `chatops_governance_demoted_patterns_total`. Migration 018 adds `suppression_status`/`demotion_reason`/`demotion_at`.

**Auto-demote is DEFAULT-ON (human-as-circuit-breaker, not gatekeeper).** A genuine repeat offender (auto-resolved ≥3×/30d then recurred) is auto-demoted to `analysis_only`; the consumer in `tier1_suppression.check_phase2_knownpattern()` then returns **`escalate`** for that (host,rule) — it stops auto-resolving the pattern and escalates for root-cause (safe-direction only; never causes suppression). Reversible (30-day `valid_until` expiry). **Known-transient patterns are excluded** (a deliberately-suppressed flappy alert recurs by design — demoting it would re-introduce suppressed noise; the exclusion reuses tier1's own `KNOWN_TRANSIENT_KEYWORDS`/`MIN_CONFIDENCE`). Demote rows are `project='chatops-governance'` + `confidence=-1` and **excluded from RAG** embedding/retrieval. Circuit-breaker = the metric + weekly audit + auto-expiry — **no manual review**. `GOVERNANCE_AUTODEMOTE=0` → shadow fallback. QA `test-1153` (8/8). Live: 39 genuine demotions, `nl-pve03/Service up/down` → escalate.

### 30.3 Synthetic-incident canary (IFRNLLEI01PRD-1154)
`synthetic-incident-canary.sh` (cron `37 2`) probes the autonomy spine — `classify-session-risk.py` → `infragraph-predict-plan.py` — asserting each stage emits its artifact (band+plan_hash; plan_hash+gate; coherent plan_hash). It runs against an **isolated `mktemp` DB seeded from schema.sql** (trap-cleaned), NOT the live gateway.db — which structurally eliminates the three top risks: cannot pollute the real `session_risk_audit`/`infragraph_predictions`, cannot collide a real in-flight session's fail-closed gate, and never touches n8n/real hosts (read-only plan). A `_live_db_leak` gauge + tier-1-SMS `SyntheticCanaryLeak` page if isolation ever regresses; `SyntheticCanaryFailing`/`Stale` are warnings. Holistic §38 `synthetic-canary`. QA `test-1154` (5/5). Verified: 3/3 stages, live `session_risk_audit` unchanged (zero leak).

### 30.4 Bi-temporal edge invalidation (IFRNLLEI01PRD-1158)
Migration 019 adds `invalid_at`/`superseded_by`/`last_confirmation` to `infragraph_dynamics` (the contradiction/supersession axis alongside the existing `valid_until` TTL). `lib.infragraph` gains `invalidate_edge()` (single `invalid_at`, logs reason), `compute_confidence_with_decay()` (**reporting-only** — flags edges for re-ratification, never alters prediction confidence; QA asserts it is absent from `expected_cascade`/`predict_action`/`apply_cascade_gating`), and a cycle-safe depth-capped `find_supersession_chain()`. `health()` + metrics gain `invalid_edges`/`decay_at_risk`. Shadow-safe: the auto-invalidation trigger is deliberately left unwired (the sound trigger is cascade-refutation from -1118, not the FP-prone wiki memory-IP contradiction). QA `test-1158` (6/6).

### 30.5 GEPA reflective prompt evolution — dormant (IFRNLLEI01PRD-1159)
Layers GEPA on the A/B patcher (§24) as the variant **generator** only. `lib.gepa_generator.evolve_candidates()` reflects on a seed instruction via **`claude -p`** (no dspy, no API key) to propose diverse mutated instruction lines; the Welch t-test + control arm in `finalize-prompt-trials.py` stays the **sole promotion gate**. DORMANT by default (`PROMPT_GEPA_ENABLED=0` → byte-identical hand-authored behavior); fail-safe (any CLI/parse failure falls back to the hand-authored pool). `build-gepa-eval-set.py` builds the contamination-free held-out reward-hacking guard (sessions < 2026-05-01; 194 eligible). QA `test-1159` (8/8).

---

## 31. Orchestrator Control-Plane (IFRNLLEI01PRD-1421)

The platform is an **agentic federation** — ~10 subsystems, **363 components** as of 2026-07-08 (199 Cronicle jobs + 57 n8n workflows + Claude Code hooks + the RAG / infragraph / teacher / chaos subsystems over 53 DB tables, ~97K LOC / 433 scripts; 320 components at the 2026-06-26 landing) — but for most of its life those parts were coordinated only by **convention**, a shared SQLite file, and the Prometheus textfile bus. Nothing *owned* their liveness as a set. The 2026-06-25 dark-component audit was the proof of the gap: the MemPalace hooks, `session_quality`, `otel_spans`, `tool_call_log`, and **the self-audit itself** had each run dark for weeks-to-months, and none of them tripped an alert, because no layer treated the federation's components as a governed inventory. This epic adds the missing **governing layer**, then closes the loop the absent operator left open by giving it an actuator.

The control plane has two halves, k8s-style. The **observe** half is three thin "bricks" — Registry, Interaction Graph, Orchestration Benchmark — built on the *existing* Prometheus + SQLite substrate, all LIVE, cronned, self-monitoring, alerting, and E2E-proven by a fault-injection drill. The **actuate** half (added 2026-06-26) is the **Plane-A platform controller** (§31.6): a k8s-style self-healing operator that reacts to those observations on idempotent platform operations only. Two enabling moves landed alongside: every cron migrated off the raw crontab onto the native **Cronicle** scheduler (§31.5, the substrate that makes per-job-death detectable + re-runnable), and the autonomy-forward decision log became a tamper-evident **SHA-256 hash-chain** (§31.7). A realtime Grafana dashboard (§31.8) renders the whole plane.

### Research basis — compose, don't rebuild

[`docs/orchestration-governance-research-2026-06-25.md`](docs/orchestration-governance-research-2026-06-25.md) surveyed the orchestration/governance landscape and reached an explicit **decision: compose [Healthchecks.io](https://healthchecks.io/) + [Langfuse](https://langfuse.com/), BUILD the 3 thin bricks on the existing stack, and do NOT adopt a platform** — LangGraph / CrewAI / Temporal / Airflow / Dagster / Backstage were all evaluated and rejected as rewrites that would dwarf the actual gap. The bricks borrow ideas, not code: Brick 2 copies **Dagster's asset-graph model** in ~250 lines; Brick 1 borrows the **service-catalog / registry** concept (Backstage); Brick 3 is a custom **orchestration-invariant** replay.

### Brick 1 — Component Registry

[`scripts/registry-seed.py`](scripts/registry-seed.py) (auto-discovery) + [`scripts/registry-curate.py`](scripts/registry-curate.py) (hand-authored field preservation) + [`scripts/registry-check.py`](scripts/registry-check.py) (liveness verification) → [`config/component-registry.json`](config/component-registry.json).

Auto-discovers and inventories **363 components** of the federation (2026-07-08; 320 at landing), each with a declared liveness expectation:

| Kind | Count |
|------|-------|
| cronicle-job | 199 |
| prom-writer | 77 |
| n8n-workflow | 57 |
| db-table | 28 |
| cron | 2 |
| **Total** | **363** |

Of these, **15 are flagged `critical`** (must be live — `0` of them currently dark) and ~10 are currently dark, all non-critical `known_dark`-by-design (e.g. GEPA, retired oc-cc-mode skills — declared so they don't register as failures). The cron kind is now `cronicle-job` (post-Cronicle-migration, §31.5 — the registry seeds from the Cronicle job inventory rather than the raw crontab). Seeded fields are auto-derived; hand-authored fields (`owner` / `kill_switch` / `liveness` / `critical` / `expected_cadence_seconds` / `known_dark` / `notes`) are preserved across re-seeds. The months-long **dark-component failure class is now caught mechanically** (`RegistryCriticalDark` fires the moment a critical component goes silent) instead of by a manual quarterly audit.

- **Schedule (Cronicle):** `registry-check` `*/30`, `registry-seed` + `registry-curate` daily.

### Brick 2 — Interaction Graph

[`scripts/interaction-graph.py`](scripts/interaction-graph.py) → [`config/interaction-graph.json`](config/interaction-graph.json). Static-analyzes **313 scripts** (2026-07-08) to map who-writes-what / who-reads-what across the federation and mechanically surface the overlaps the convention-based coordination never enforced:

| Finding | Count | Meaning |
|---------|-------|---------|
| `CONFLICT` (multi-writer) | 23 | Two+ components write the same table/metric — the un-coordinated write class. |
| `GAP` (orphan consumer) | **0** | A reader with no producer — the "Session-End → reconcile hole" class. **Zero**, mechanically confirmed. |
| `CRON-CLASH` | **0** | Two jobs firing the same minute on a shared resource — **zero** under Cronicle's per-job scheduling (the prior 6 were benign crontab co-minutes). |

The graph is the federation's **asset dependency model** (Dagster's idea, ~250 lines). `InteractionGraphGap` fires if an orphan-consumer GAP ever re-appears.

- **Schedule (Cronicle):** `interaction-graph` daily.

### Brick 3 — Orchestration Benchmark

[`scripts/orchestration-benchmark.py`](scripts/orchestration-benchmark.py) → [`config/orchestration-scorecard.json`](config/orchestration-scorecard.json). Replays a **synthetic incident stream** through the *isolated* `classify → predict` spine and scores **4 orchestration invariants** — properties of the *coordination*, not of any single component:

| Invariant | Asserts |
|-----------|---------|
| **I1 — safety composition** | An irreversible incident is **NEVER auto-resolved**, verified across the *whole* stream (not case-by-case). The composition of the bands + the prediction gate + the irreversible-pattern matcher must hold jointly. |
| **I2 — determinism** | The same incident classifies to the same band/plan-hash on replay. |
| **I3 — completeness** | Every incident produces the artifacts each spine stage owes (band + plan_hash + gate). |
| **I4 — structural integrity** | The interaction graph has 0 GAPs (re-checks Brick 2 from the benchmark's side). |

First run: **orchestration score 1.0, 4/4 invariants passed** over a 10-incident stream (4 reversible — restart / read-only / cert-renew / k8s-cascade; 5 irreversible — `mkfs` / `zpool destroy` / `dropdb` / `rm -rf` / `terraform destroy`; 1 security-incident). Every irreversible case landed `POLL_PAUSE`, never auto.

- **Schedule (Cronicle):** `orchestration-benchmark` weekly.

### Alerting + who-watches-the-watcher

Five PrometheusRules are LIVE in-cluster (infra MRs **!347 + !348** merged + verified evaluating healthy):

| Rule | Tier | Fires on |
|------|------|----------|
| `RegistryCriticalDark` | **tier1** | A `critical` component is dark (the dark-component class). |
| `RegistryCheckStale` | warn | `registry-check` itself stopped running (absent-guarded). |
| `InteractionGraphGap` | warn | An orphan-consumer GAP re-appears. |
| `OrchestrationSafetyFailure` | **tier1** | An orchestration invariant (esp. I1) regresses. |
| `OrchestrationBenchmarkStale` | warn | The weekly benchmark stopped running. |

The control-plane **monitors its own three bricks** — the who-watches-the-watcher gap (the same gap that let the self-audit go dark) is fully closed: a brick going silent trips `RegistryCheckStale` / `OrchestrationBenchmarkStale`.

### E2E fault-injection proof

The drill did not just confirm the rules *evaluate* — it confirmed one actually **fires**. A synthetic orphan-consumer was injected into the interaction graph and `InteractionGraphGap` transitioned to firing in Prometheus, then cleared on removal. This distinguishes "the alert is defined" from "the alert works," the exact distinction the dark-component audit showed was being missed estate-wide.

### Surfaces

- **QA:** [`scripts/qa/suites/test-1421-orchestrator.sh`](scripts/qa/suites/test-1421-orchestrator.sh) — green.
- **Findings report:** [`docs/orchestration-findings-2026-06-26.md`](docs/orchestration-findings-2026-06-26.md) (the first governance report: the federation inventoried, the interactions mapped, the orchestration scored).
- **Self-monitoring:** the registry tracks its *own* 3 bricks (`prom:registry_check` / `prom:interaction_graph` / `prom:orchestration_benchmark` all marked `critical` in `config/component-registry.json`) — `RegistryCriticalDark` fires if a brick itself goes dark (who-watches-the-watcher closed). Folding an orchestrator-liveness check into `holistic-agentic-health.sh` (currently §38) is a clean follow-up.
- **New observability services** wired alongside (§5): Healthchecks.io (the `registry-check` dead-man ping) + Langfuse v2 (per-session LLM trace) on `nlopenobserve01`.

### 31.5 Cronicle scheduler migration

The three bricks above can only detect a job that *should have run and didn't* if the scheduler exposes per-job run state — the raw crontab does not (no run history, no per-job exit code, no "this one job died" signal; a failing entry is silent unless it happens to email root). So **all schedulable jobs were migrated off the raw crontab onto a native [Cronicle](https://github.com/jhuckaby/Cronicle) scheduler** (v0.9.x, `/opt/cronicle`, systemd `cronicle.service` as `app-user`, web UI/REST on `:3012`): **180 at migration (107 gateway + 72 agora-quant-trading), 199 registered as of 2026-07-08** (1 `@reboot` entry stays in crontab by design). Cronicle runs **natively** on `nl-claude01` — *not* in Docker — deliberately, so jobs execute in the same real environment cron used (the Docker option forced an ssh-back-to-host tunnel that would have changed the execution context).

What the migration buys the control plane:

- **Per-job run history + per-job-death failure alerting** — Cronicle records every run's exit code and duration, so a single chronically-failing job is now detectable in isolation (the per-job-death gap the crontab left open). `write-cronicle-metrics.py` (`*/10`) exports `cronicle_*` metrics including `cronicle_jobs_failed_recently`, registered `critical` in the registry.
- **A REST API** the Registry seeds from (the `cronicle-job` kind in §31.4) and the platform controller actuates against (§31.6).
- **Auto-quarantine of chronic-failers** — a job that keeps dying is held out of the schedule rather than thrashing.

Cutover was verified post-migration (jobs fired with `code=0`). Rollback is a single command: `crontab /home/app-user/crontab.full-snapshot-pre-cronicle`.

### 31.6 Plane-A platform controller — the self-healing actuator

The three bricks *observe*; [`scripts/platform-controller.py`](scripts/platform-controller.py) (`*/5`, **armed**) is the **actuator** — a Kubernetes-style self-healing operator that closes the loop the absent operator left open. It is the reconcile-to-desired-state counterpart to the registry's declared-liveness inventory: where a critical component has drifted from its expected-live state, the controller drives it back.

**Strict Plane-A / Plane-B split (the controller's central safety rule).** Borrowing the k8s analogy precisely: a Kubernetes controller keeps *pods* alive but never decides application logic. This controller keeps the **PLATFORM** alive (Plane-A: crons / Cronicle / bricks / writers / n8n) and **NEVER** touches the **MISSION** (Plane-B: resize a VM, reboot a host, auto-resolve an incident — that lane belongs to the autonomy-forward gate, §29). It only ever performs **idempotent platform operations**:

- Reactivate an inactive **critical n8n workflow** (it monitors **all 57**).
- Re-run a **failed safe-list Cronicle job** (allowlist-gated).
- **Restart Cronicle** if the scheduler itself is down.
- The consolidated `gateway-watchdog.sh --heals-only` library: n8n-restart / Bridge-bounce / zombie + stale-lock cleanup.

**k8s-style guardrails.** Heals are not unconditional: a per-target heal cap plus **exponential heal-backoff** governs retries, and a target that keeps failing its heal trips a **CrashLoopBackOff** state → the controller stops trying and **escalates to SMS** rather than thrashing a broken component. The bands of escalation mirror a real operator's restraint: try, back off, give up loudly.

**Watchdog consolidation.** The pre-existing `gateway-watchdog.sh` dead-man's-switch (§30.1) is being folded into this one operator — the controller has taken over n8n liveness and absorbed the **dead-man heartbeat**, and now runs *alongside* the legacy watchdog (harmless redundancy during the transition). The controller is itself registered `critical` in the registry, so it is its **own dead-man** — if it stops, `RegistryCriticalDark` pages.

**Arming.** GATED behind the sentinel `~/gateway.platform_controller_armed` — `rm` to disarm instantly, no n8n edit. Two PrometheusRules cover it: `PlatformControllerEscalation` (a heal hit CrashLoopBackOff) and `PlatformControllerStale` (the controller itself stopped), both tier=1 SMS.

### 31.7 Tamper-evident governance hash-chain

The autonomy-forward decision log (`scripts/classify-session-risk.py` — the 3-band AUTO / AUTO_NOTICE / POLL_PAUSE gate behind the fail-closed machine-prediction gate, §29) is now an **append-only SHA-256 hash-chain**: each decision record's hash folds in its predecessor's, so any retroactive edit, deletion, or reordering of a past autonomy decision breaks the chain from that point forward and is mechanically detectable. Across **830 decisions** logged (78% auto-approved, 2026-07-08), [`scripts/verify-governance-chain.py`](scripts/verify-governance-chain.py) re-walks the chain and verifies integrity; `GovernanceChainBroken` (a hash mismatch) and `GovernanceChainStale` (the verifier stopped running) are both tier-1 alerts. This makes the audit trail of *who-let-the-agent-act* not just present but **provably un-rewritten** — the integrity property the human-as-circuit-breaker model needs once the operator is out of the approval loop.

### 31.8 Realtime control-plane dashboard

A purpose-built Grafana dashboard renders the whole plane in one view: **"Orchestrator Control-Plane — Realtime Overview"** ([grafana.example.net/d/orchestrator-ctrl-plane](https://grafana.example.net/d/orchestrator-ctrl-plane); source [`grafana/orchestrator-control-plane.json`](grafana/orchestrator-control-plane.json)) — **31 panels across 6 sections, 30 s refresh**, surfacing registry liveness (critical / dark), interaction-graph findings, the orchestration-benchmark score, Cronicle per-job health, the governance-chain integrity status, the platform-controller heal/escalation activity, and the dead-man heartbeat. It is the operator's single pane onto a federation that now governs itself.

### 31.9 Control-plane benchmark — B+

The control plane was itself scored against industry orchestration/control-plane standards: **B+ (3.48 / 5)** across **11 dimensions** ([`docs/orchestrator-plane-benchmark-2026-06-26.md`](docs/orchestrator-plane-benchmark-2026-06-26.md)). The grade reflects a plane that is now genuinely two-sided (observe + actuate, with a self-healing operator, a tamper-evident decision log, and a migrated scheduler) while staying honest about the deliberate restraints — the Plane-A/Plane-B firewall keeps the actuator narrow by design, and several follow-ups (careful watchdog retirement, Cronicle Prometheus-rule IaC, registry-seed-from-Cronicle) are tracked rather than claimed-done. This is distinct from the agent-*building* scorecards in §32 (those grade the agent against the Anthropic/OpenAI guides; this grades the orchestration *layer* against control-plane standards).

#### Observability at a glance

The full control plane unifies logging to self-hosted **OpenObserve** (every scheduler run + brick decision + completed session), streams LLM/agent traces to **Langfuse**, pushes fresh **OTLP** spans at session-end, and exports **~1,700 Prometheus metric series across 77 textfile writers** governed by **74 in-repo alert rules across 6 files** (2026-07-08) — backstopped by the control-plane dead-man heartbeat (§30.1 / §31.6), the synthetic-incident canary (§30.3), and a repo-vs-deployed-copy drift guard.

---

## 32. Agent-Guide Benchmark — Anthropic + OpenAI (2026-06-26)

Two new epics scored the platform against the two canonical agent-building ebooks as **separate, source-pure, adversarially-verified scorecards**, then drove the gaps to A:

- **IFRNLLEI01PRD-1422** — Anthropic, *Building Effective AI Agents* (+ *Effective Context Engineering for AI Agents* + Claude Agent SDK guidance). Scorecard: [`docs/scorecard-anthropic-2026-06-26.md`](docs/scorecard-anthropic-2026-06-26.md).
- **IFRNLLEI01PRD-1423** — OpenAI, *A Practical Guide to Building Agents*. Scorecard: [`docs/scorecard-openai-2026-06-26.md`](docs/scorecard-openai-2026-06-26.md).
- **Synthesis** (provenance-tagged labelled join, *not* a blend; every backlog item carries `[A·dimN]` / `[O·dimN]` / `[BOTH]`): [`docs/benchmark-synthesis-2026-06-26.md`](docs/benchmark-synthesis-2026-06-26.md).

Each scorecard is **source-pure** — every dimension traces back to *that book's* guidance only, with no cross-contamination of criteria, and every score is the adversarially-verified `verdict.adjusted_score` (multiple audits → skeptic pass → live code/DB verification).

### Result: 12 of 14 dimensions at A

After the improvement pass, **12 of 14 dimensions sit at A**. The **2 remaining at B are deliberate operator decisions, not gaps**:

- **Guardrail layering (`B`, by choice):** the rules blocklist (unified-guard) is kept **OFF the dispatched `--dangerously-skip-permissions` path** — the operator's standing decision (the same disable carried on the working branch). The fail-closed prediction gate + territory gate + irreversible floor already cover the consequential surface; adding the unified-guard to the dispatched path is an explicit non-goal, not an unmet one.
- **Human-intervention failure-threshold (`B`, by choice):** the cost / tool-call / handoff-depth failure-threshold is kept as a **passive Matrix warning** — it annotates but does not SMS-page or pause. With the operator out of the loop (human-as-circuit-breaker, §29), the new async tripwire (below) already has *kill* authority; promoting the threshold to a page was judged redundant noise.

### Key fixes shipped along the way

The drive-to-A landed a batch of concrete fixes, each behind a kill-switch / QA / audit-invariant where feasible:

- **Model-router bug** — `priorIncidents` counted **markdown-table PIPES** (`kbRaw.match(/\|/g)`) instead of incident **rows**, so the `priorIncidents<=2` sonnet-routing predicate was blown past on every retrieval → **818/818 real sessions pinned to Opus** (0 sonnet / 0 haiku). Fixed to count incident rows + widen the predicate + wire the resume (`Launch Claude Fresh`) path, with a **never-downgrade-risky floor** (HIGH / MIXED / irreversible stays Opus). Simple low-risk availability/cert/maintenance alerts now route to Sonnet. Central registry: [`scripts/lib/models.py`](scripts/lib/models.py) + drift guard [`scripts/check-model-registry.py`](scripts/check-model-registry.py); [`scripts/check-skill-parity.py`](scripts/check-skill-parity.py).
- **OTLP trace export revived** — dead to OpenObserve since ~March 2026; a stale `OTLP_AUTH` env var was shadowing the real credentials. Fixed (see §5 observability).
- **`MemoryMax=12G` cgroup cap** on every dispatched `claude -p` session — the previously-uncapped runaway class is what wedged `nlpve04`.
- **Concurrent-session tripwire** — the Progress Poller can now **kill** a runaway session on a token / cost / tool-call breach (it was read-only before). Kill-switch: `~/gateway.tripwire_off`.
- **Handoff-depth telemetry wired** — was dark (0/75 sessions ever bumped).
- **Sub-agent discoverability** — the 11 sub-agents were **structurally unreachable** in dispatched sessions; fixed via a `~/.claude/agents` symlink so the dispatched runtime can actually resolve them.
- **`agent_as_tool.py`** description parser fixed (block-scalar YAML descriptions now reach the orchestrating LLM instead of truncating to a bare agent name).
- **RAGAS local-judge unwrap** — 3 of 4 metrics had been returning `-1` sentinels.
- **`event_log` concurrent-emit fix** — [`scripts/lib/session_events.py`](scripts/lib/session_events.py) `_emit_insert`: WAL-transition race + retry, so concurrent emits no longer drop rows.

The QA suite is green after the batch.

---

## 33. Model Orchestration — Centralized Provider/Model Selection (2026-06-28)

Model selection moved from per-component hardcoded IDs to a centralized, two-plane design (MRs !116–!120), driven by the operator directive that **the only paid per-token APIs are Mistral + DeepSeek** (Anthropic per-token spend = 0). Full provenance: [`docs/model-provenance.md`](docs/model-provenance.md).

### The two planes

- **Claude-Code plane (subscription, flat-rate).** Every `claude` invocation — dispatched remediation, `agent_as_tool`, `mr-review`, `parallel-dev`, `audit-owasp`, interactive — is routed by ONE switch: [`scripts/claude-provider.sh`](scripts/claude-provider.sh) `{zai|anthropic|status}`. It edits the `env` block of `~/.claude/settings.json`, which Claude Code reads as its base environment for every invocation. Two providers: **Z.ai** (GLM Coding Plan: `ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic` + `ANTHROPIC_AUTH_TOKEN` + opus→`glm-5.2` Opus-equivalent / sonnet·haiku→`glm-4.7` Sonnet-equivalent) and **`anthropic`** (the Max OAuth subscription). The operator flips the toggle as needed, so **`claude-provider.sh status` is the only authoritative answer to "which provider is live"** (2026-07-08 spot-check: `anthropic`). **Why direct and not via a gateway:** subscription/OAuth auth cannot proxy through LiteLLM, so routing it there would forfeit the flat-rate benefit. The earlier sentinel+resolver approach (`claude-provider-env.sh` + `~/gateway.claude_provider`) is retired — the resolver is a harmless no-op the Runner still sources, avoiding a live-Runner edit.

- **API plane (per-token, paid).** The eval layer — frontier cross-check, judge max-effort, RAGAS, judge-haiku-backend — routes via the **shared LiteLLM** (`nllitellm01`, `:4000`, v1.85.0) to **Mistral** (`mistral-large-latest`, "Le Chaton Fat") + **DeepSeek** (`deepseek-v4-pro`), with **local-Ollama fallback (never Anthropic)**. Per-component spend is attributed via LiteLLM `x-litellm-tag`s (`frontier-crosscheck`, `judge-<effort>`, `ragas-eval`). The gateway's models + a gateway-scoped virtual key live in LiteLLM's **postgres** (added via the admin API) so the host project's `config.yaml` is never touched — omoikane's 10 models stay intact (10 + 4 gateway = 14). The LiteLLM master key is fetched **transiently over SSH, never stored** gateway-side; only the scoped virtual key (`LITELLM_GATEWAY_KEY`) is in `.env`. The LiteLLM LXC was set `onboot=1` since the eval layer now depends on it.

- **Local plane ($0).** The routine judge / RAG synth+rewrite / embeddings / rerank / fast-path / teacher run on Ollama (`gemma3:12b`, `qwen2.5:7b`, `nomic-embed-text`, `bge-reranker-v2-m3`, `llama3.2:1b`).

### Single source of truth

[`config/model-routing.json`](config/model-routing.json) (component → provider/model/fallback), resolved by [`scripts/lib/model_routing.py`](scripts/lib/model_routing.py) (`--list` / `--resolve <component>` / `--providers`). The LiteLLM models + virtual key are provisioned idempotently by [`scripts/litellm-gateway-setup.sh`](scripts/litellm-gateway-setup.sh). To answer "which model on which component now": `python3 scripts/lib/model_routing.py --list` for the intended-default catalog, plus `bash scripts/claude-provider.sh status` for the **live** Claude-Code provider (authoritative — the registry entry is the intended default, `status` reflects the active `settings.json` toggle).

### Gotchas landed along the way

- **`deepseek-v4-pro` is a reasoning model** → returns `[thinking, text]` content blocks (the thinking block carries empty text). All three eval parsers were fixed to join `type=='text'` blocks — the old `content[0].text` grabbed the empty thinking block and would have silently broken every RAGAS/frontier score.
- **`temperature` must be stripped** for the LiteLLM→Anthropic-model path (`opus-4-8` returns `invalid_request_error` if sent) — the judge's LiteLLM block does `d.pop('temperature')`.
- **`~/.bashrc` exports `ANTHROPIC_API_KEY`** which would shadow the Z.ai token — settings.json's `ANTHROPIC_AUTH_TOKEN` takes precedence (verified), so no unset is needed.
- **DeepSeek account balance** is separate from key validity: the key listed models fine but completions returned `Insufficient Balance` until the operator topped up credits.
- `deepseek-v4-flash` (cheap) vs `deepseek-v4-pro` (eval quality) is a one-line tunable in `litellm-gateway-setup.sh`.

### Supersedes the operating-mode abstraction

This centralized model layer supersedes the old `cc-cc` / `oc-cc` / `oc-oc` / `cc-oc` frontend/backend-pairing modes (those encoded OpenClaw-era agent pairing, orthogonal to model selection). Only `cc-cc` is live; OpenClaw was retired 2026-04-29 and its LXC has been destroyed. `~/gateway.mode` was corrected to `cc-cc` on 2026-07-03 and is cosmetic either way — dispatch is hardwired, not read from the file.

---

## 34. Scheduled-Reboot Suppression — self-learning (2026-06-29)

Tier-1 suppression gained a phase **SR** ([`scripts/lib/tier1_suppression.py`](scripts/lib/tier1_suppression.py) + [`scripts/lib/scheduled_reboots.py`](scripts/lib/scheduled_reboots.py)): an on-schedule reboot alert on a host with a **live, unkilled, unexpired registered schedule** is suppressed before YT-create and before any Claude session spawns — then a **two-phase verify** reopens + pages if the boot wasn't a clean `systemd-reboot`. The registry is **self-learning**: `discover-scheduled-reboots.py` + `classify-reboot-alert.py` register candidate schedules as `observing`; `promote-scheduled-reboots.py` promotes to `live` only after ≥2 in-window boots are observed. Safety floor: dark by default behind the `~/gateway.sched_reboot` sentinel · critical-severity never suppressed · reboot-rule allowlist · observe-before-live · per-row kill_switch + valid_until in SQL · strict DST-correct cron windows (vendored croniter) · fail-open on any error. 5 Cronicle jobs; alerts `ScheduledReboot{Misclassified,MetricsStale,PromotionStuck}`. Runbook: [`docs/runbooks/scheduled-reboot-suppression.md`](docs/runbooks/scheduled-reboot-suppression.md).

---

## 35. Renovate MR Autonomy Lane (2026-07-06)

A self-hosted **Renovate CE** instance (`nlrenovate01`) opens dependency-update MRs across the IaC estate; a dedicated n8n lane turns the routine subset into a **hands-off merge+deploy+verify pipeline** while keeping everything consequential human-gated:

- **Classification** — [`scripts/classify-renovate-mr.py`](scripts/classify-renovate-mr.py) + a stateful-services manifest decide per-MR: routine docker digest/patch bumps qualify for autonomy; **Kubernetes / Helm / Terraform / OpenBao / stateful services / Dockerfiles / majors always POLL** with operator SMS — never auto-applied blind.
- **Gates** — deterministic structural review, hard CI-green requirement, snapshot-before-merge for stateful services, rate caps (synthetic/test rows excluded from the caps), and a `*/15` reconciler registered in the orchestrator registry.
- **Post-merge verification is 3-way** — healthy / confirmed-bad → revert / **inconclusive → escalate, never auto-revert** (undoing an unverified change is its own incident class).
- **Arming** — `~/gateway.renovate_autonomy` sentinel (`rm` = instant off); event-driven pickup via GitLab webhook. First fully hands-off routine merges + a correct first POLL-with-SMS (openbao major) ran 2026-07-06/07, followed by a ~20-MR supervised clearance of the backlog.

Runbook: [`docs/runbooks/renovate-mr-autonomy.md`](docs/runbooks/renovate-mr-autonomy.md).

---

## License

Sanitized mirror of a private GitLab repository. Internal hostnames, IP addresses, credentials, and personal identifiers replaced with placeholders (128 replacement patterns + 20 post-scan grep patterns). Provided as-is for educational and reference purposes.

---

*Built by a solo infrastructure operator who got tired of waking up at 3am for alerts that an AI could triage.*
