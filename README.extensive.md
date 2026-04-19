# agentic-chatops — Comprehensive Technical Reference

Production agentic ChatOps/ChatSecOps/ChatDevOps platform implementing all 21 design patterns from Antonio Gulli's *Agentic Design Patterns* (Springer, 2025). Tri-source audited against [Anthropic's official documentation](https://docs.anthropic.com/) (17 sources), the [Anthropic Academy](https://academy.anthropic.com/) sub-agent design course, and [6 industry references](docs/industry-agentic-references.md). Includes a [Karpathy-style compiled knowledge base](wiki/index.md) — 44 articles auto-compiled from 7+ sources with 5-signal RAG integration (semantic + keyword + wiki + [MemPalace](https://github.com/milla-jovovich/mempalace) session transcripts + chaos baselines).

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
10. [n8n Workflows](#10-n8n-workflows-25-424-nodes)
11. [MCP Servers](#11-mcp-servers-10-153-tools)
12. [Sub-Agents](#12-sub-agents-10)
13. [Claude Code Skills & Hooks](#13-claude-code-skills--hooks)
14. [OpenClaw Tier 1 Skills](#14-openclaw-tier-1-skills-15)
15. [ChatSecOps — Security Operations](#15-chatsecops--security-operations)
16. [Guardrails & Safety](#16-guardrails--safety)
17. [Inter-Agent Communication](#17-inter-agent-communication-nl-a2av1)
18. [Operating Modes & Commands](#18-operating-modes--commands)
19. [Repository Structure](#19-repository-structure)
20. [Installation](#20-installation)
21. [References](#21-references)

---

## 1. What Makes This Different

Most agentic ChatOps projects stop at "LLM reads alert, posts summary." This one closes the loop end-to-end:

- **Self-improving prompts** -- An eval flywheel (58 eval scenarios + 54 adversarial tests, LLM-as-a-Judge, monthly cycle) detects weak dimensions, generates prompt patches, and applies them automatically. The system literally rewrites its own instructions based on measured performance.
- **AWX runbook integration** -- 41 Ansible playbooks are queryable at plan time. The planner injects proven AWX templates into investigation plans ("Run Template 69 with dry_run=true"), turning ad-hoc SSH into repeatable automation.
- **Predictive alerting** -- Regression detector (6h cron) and metamorphic monitor catch quality degradation before operators notice. Cost-adaptive routing switches to plan-only mode when category spend exceeds $3 average.
- **GraphRAG** -- 263 entities and 127 relationships (host, alert_rule, incident, lesson) in a knowledge graph. Enables queries like "what alerts does this host trigger?" and "what lessons apply to this alert rule?" beyond flat vector search.
- **OTel tracing** -- 88K+ tool calls instrumented with OpenTelemetry spans (duration, exit code, error type). Exported to OpenObserve for cross-session trace correlation and performance debugging.
- **Karpathy-style compiled wiki** -- 44 articles auto-compiled daily from 7 fragmented knowledge stores (memories, CLAUDE.md files, incidents, lessons, OpenClaw, docs, 03_Lab). Answers "what do we know about host X?" in one lookup instead of five.

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
   +--------------+     +---------------+     +------------------+
   |  n8n          |---->|  OpenClaw      |---->|  Claude Code      |
   |  Orchestrator |     |  (Tier 1)     |     |  (Tier 2)         |
   |  25 workflows |     |  GPT-5.1      |     |  Claude Opus 4.6  |
   |  424 nodes    |     |  17 skills    |     |  10 sub-agents    |
   +---------+-----+     +---------------+     +---------+---------+
             |                                           |
             v                                           v
   +--------------+                              +---------------+
   |  Matrix       |<-----------------------------|  Human (T3)    |
   |  Chat rooms   |  polls, reactions, replies   |  Approval      |
   +--------------+                              +---------------+
```
</details>

- **Tier 1 (OpenClaw v2026.4.11 / GPT-5.1):** Fast triage (7-21s). 17 native skills + Active Memory plugin. Creates YouTrack issues, deduplicates alerts, extracts procedural knowledge from CLAUDE.md files + operational memory rules, investigates via SSH/kubectl, runs semantic search locally (Ollama on same subnet), outputs confidence scores. Handles 80%+ of alerts without escalation.
- **Tier 2 (Claude Code / Opus 4.6):** Deep analysis (5-15 min). 10 specialized sub-agents (Haiku for research, Opus for security). Receives targeted CLAUDE.md file paths + auto-retrieved operational memories in Build Prompt. Reads Tier 1 findings (now enriched with CLAUDE.md context), verifies using ReAct reasoning, proposes remediation via interactive polls, executes after human approval. For complex sessions, delegates research to sub-agents IN PARALLEL.
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
| 5 | **Tool Use** | A | 10 MCP servers, 153 tools. Custom Proxmox MCP (15 tools). n8n-as-code offline schemas for 537 nodes. `ToolSearch` for deferred tool discovery. | Ch5 |
| 6 | **Planning** | A- | Interactive [POLL] plan selection via MSC3381 Matrix polls. Plan-only mode (`--plan` flag) for multi-file dev tasks and correlated bursts. | Ch6 |
| 7 | **Multi-Agent** | **A+** | 3-tier hierarchy + 10 specialized sub-agents (6 infra + 4 dev) with [Anthropic Academy](https://academy.anthropic.com/) patterns: structured output, obstacle reporting, limited tools, no expert claims, parallel not sequential. Pipeline delegation for complex sessions. | Ch7 |
| 8 | **Memory** | **A+** | All 3 memory types (semantic, episodic, procedural) active across both tiers. 55 CLAUDE.md files auto-routed by hostname to triage. 117 feedback memory files synced across both agent hosts. Procedural rules ("NEVER do X") injected into Tier 1 triage output and Tier 2 Build Prompt. SQLite (31 tables, 150K+ rows incl. `session_transcripts`, `agent_diary`, `otel_spans`, `tool_call_log`). Vector embeddings (nomic-embed-text, 768 dims). Lessons-to-prompt pipeline. **[Karpathy-style compiled wiki](wiki/index.md)** — 44 articles synthesizing all memory types into organized, browsable knowledge with health checks. | Ch8 |
| 9 | **Learning & Adaptation** | **A+** | Closed-loop: session creates feedback memory → next triage auto-surfaces it → agent acts on it. A/B prompt testing (react_v1 vs react_v2). Outcome scoring. Lessons-to-prompt pipeline (30d). Regression detection (6h cron). Metamorphic monitor (auto-variant promotion at 25+ sessions). | Ch9 |
| 10 | **MCP** | A | 10 servers including custom Proxmox MCP (15 tools). mcporter Docker bridge for OpenClaw. Tool search enabled by default. Per-tool allowlisting in settings. | Ch10 |
| 11 | **Goal Setting** | A- | Confidence gating (< 0.5 = STOP, < 0.7 = escalate). Budget enforcement ($5/session warning, $25/day plan-only). Dynamic timeout by complexity (300-600s). Formalized contracts (`CONTRACT:` block in YT description). | Ch11 |
| 12 | **Exception Handling** | A | 5-layer gateway watchdog (n8n health, workflow activation, proactive bounce, error detection, zombie cleanup). `ERROR_CONTEXT` structured propagation (failed step, completed steps, suggested next action). Fallback ladders (AWX -> API -> SSH -> Ping). | Ch12 |
| 13 | **Human-in-the-Loop** | A | MSC3381 polls rendered in Matrix Element client. Thumbs up/down reactions. 15min remind / 30min auto-pause approval timeouts. AUTHORIZED_SENDERS filter. Formalized contracts define acceptance criteria. | Ch13 |
| 14 | **RAG** | **A+** | **5-signal hybrid RRF:** (1) semantic — vector embeddings (nomic-embed-text, 768 dims) with cosine similarity and `search_query:` / `search_document:` asymmetric prefixes; (2) keyword — SQL LIKE on hostname/alert/resolution; (3) **wiki articles** — 44 compiled knowledge base articles (970 section-rows indexed with `source_mtime`); (4) **session transcripts** — verbatim exchange-pair chunks ([MemPalace](https://github.com/milla-jovovich/mempalace), weight 0.4); (5) **chaos baselines** — chaos experiment results by hostname (weight 0.35). All fused via Reciprocal Rank Fusion. **G1 cross-encoder rerank** via dedicated bge-reranker-v2-m3 service on gpu01:11436. **G2 RAG Fusion** via `rewrite_query_multi` (4 variants, batch-embedded). **G3 LongContextReorder** (`long_context_reorder()` + `LCR_ENABLED=1`). **G5 KG traversal** with 3-tier progressive widening (strict → filters OR'd → entity_type dropped → embedding fallback). **Temporal window filter** on `wiki_articles.source_mtime` for "last 48h" queries. **mtime-sort intent detector** bypasses semantic retrieval for "name three memory files created in the last 48h" class queries. **Haiku synth** (Anthropic API, `SYNTH_BACKEND=auto`) composes cross-chunk answers when top rerank < 0.4. **4/4 FAISS HNSW indexes** pre-synced at `/var/claude-gateway/vector-indexes/` as migration-ready parallel write path. All JSON callers unified on `JSON_MODEL=qwen2.5:7b` (100% first-try JSON reliability, 20-query test). Plus deterministic channel: hostname-routed CLAUDE.md extraction (55 files, category-aware grep). Triage RAG at Step 1.5 (semantic) + Step 2-kb (CLAUDE.md + memory). 3-tier injection for Tier 2. Backfill cron every 30min. Wiki recompiled daily. | Ch14 |
| 15 | **A2A Communication** | A | [NL-A2A/v1 protocol](docs/a2a-protocol.md). Agent cards ([`a2a/agent-cards/`](a2a/agent-cards/)). Message envelope with protocol, messageId, from/to, type, payload. REVIEW_JSON auto-action. Task lifecycle logging. 53 A2A entries. | Ch15 |
| 16 | **Resource Optimization** | **A+** | Haiku/Opus model routing for sub-agents (9:1 cost ratio). JSONL token-based cost tracking from stream-json. Per-category cost prediction. Dynamic timeout. $5/session + $25/day budget. Subsystem-level cost metrics. | Ch16 |
| 17 | **Reasoning** | A | ReAct (THOUGHT/ACTION/OBSERVATION) mandatory for infra. Step-back prompting for recurring alerts. Tree-of-thought (H1/H2 hypotheses) for correlated bursts. Self-consistency check. Chain-of-verification for cross-tier reviews. A/B variant testing. | Ch17 |
| 18 | **Guardrails** | **A+** | 7-layer defense: [`unified-guard.sh`](scripts/hooks/unified-guard.sh) — 78 blocked patterns (37 destructive + 22 exfil + 7 injection) + 12 protected file patterns + **word-boundary precision** on single-word commands (passwd/useradd/shutdown/halt/mkfs) that distinguishes command invocation (blocked) from prose mention (allowed) via `(^|[;&\|])\s*(sudo\s+)?WORD(\s|$|--)`; 22-check harness validates both block and allow cases. Plus safe-exec.sh + exec-approvals.json (36 patterns) + input sanitization (42 injection patterns) + credential/PII scanning (16 regex) + output fact-checking + **Evaluator-Optimizer** (Haiku screening for high-stakes responses, 3 nodes). Per-source token caps on injected knowledge. Tool call limit (75). Zero hardcoded passwords. | Ch18 |
| 19 | **Evaluation** | **A+** | 19-surface [Prompt Scorecard](scripts/grade-prompts.sh) (6 dimensions, daily). [Agent Trajectory](scripts/score-trajectory.sh) (8 infra / 4 dev steps). [LLM-as-a-Judge](scripts/llm-judge.sh) (Haiku/Opus, 5 dimensions, [calibrated](scripts/judge-calibrate.sh)). **58 test scenarios** (22+20+16) across [3 eval sets](docs/evaluation-process.md) (regression/discovery/holdout) + 54 adversarial tests + 18 node-level tests + 12 negative controls. [CI eval gate](.gitlab-ci.yml). [Eval flywheel](scripts/eval-flywheel.sh) (monthly). Reproducibility (temp=0, seed=42). | Ch19 |
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

[`scripts/holistic-agentic-health.sh`](scripts/holistic-agentic-health.sh) — **142 automated checks** across 37 sections that verify every feature claimed in this README actually works in production. Not just "does the file exist?" — functional tests, cross-site verification, and e2e smoke tests.

**Latest score: 96%** (quick mode) in 18 seconds.

```bash
./scripts/holistic-agentic-health.sh            # Full run (142 checks, ~18s)
./scripts/holistic-agentic-health.sh --quick     # Skip SSH/kubectl (~8s, 96%)
./scripts/holistic-agentic-health.sh --smoke     # Include e2e synthetic alert test
./scripts/holistic-agentic-health.sh --json      # Machine-readable output
```

### What It Tests

| Section | Checks | What's Verified |
|---------|--------|-----------------|
| n8n Workflows | 9 | 26 active, 7 critical workflows, execution error rate (<10%) |
| SQLite Tables | 12 | 31 tables, 150K+ rows, 8 staleness thresholds (per-table freshness) |
| MCP Servers | 1 | Process count for all 10 MCP servers |
| RAG Pipeline | 5 | Semantic search, wiki articles, transcripts, GraphRAG, **functional search test** (known incident) |
| Session End Pipeline | 7 | 18 nodes, all 6 critical nodes present (Score Trajectory → Populate Graph) |
| OpenClaw Tier 1 | 2 | 29 skills, container running |
| Claude Code | 3 | 10 agents, 5 skills, 3 hook events |
| Eval Pipeline | 12 | 58 eval scenarios (3 sets) + 54 adversarial, 5 scripts, judgments, **functional trajectory test** |
| Safety Guardrails | 3 | 42 injection patterns, 89 blocked patterns, exec-approvals |
| Observability | 5 | 39K OTel spans, 88K tool calls, 3 Grafana datasources, 28 dashboards, **139/139 Prometheus targets UP** |
| Crons | 1 | 38 active cron entries |
| Self-Improving Prompts | 2 | 5 prompt patches, prompt-improver executable |
| Predictive Alerting | 2 | Script + daily cron configured |
| Compiled Wiki | 3 | 44 articles, daily cron, compile freshness (<48h) |
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
| Gateway Mode | 2 | Valid mode (oc-cc), no maintenance lock |
| Session Continuity | 1 | Last session_id queryable |
| Runner Build Prompt | 5 | 48 nodes, 4 critical nodes (Build Prompt, Query Knowledge, Build Plan, Evaluator) |
| External Services | 5 | YouTrack API, **NetBox CMDB (307 objects)**, Matrix POST, GitHub mirror (<72h), OpenClaw LLM reachable |
| Infra Health | 6 | **7/7 K8s nodes**, PVE quorum, **7 BGP peers**, GPU 46°C, Thanos query, DNS |
| Data Integrity | 5 | Embeddings (33/33), queue depth, DB backup (<26h), JSONL poller, token caps in Build Prompt |
| Security | 4 | Scanner NL (<26h), scanner GR (<26h), MITRE Navigator, CrowdSec bans |
| Cross-Site Sync | 3 | OpenClaw memories, GR claude host, **syslog-ng (NL: 18, GR: 184K lines/day)** |
| Operational | 6 | Freedom WAN SLA UP, Docker containers, n8n-as-code, **19/19 scorecard surfaces**, watchdog, **4 VPS SAs** |
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
5. Build Plan (Haiku) generates 3-5 step investigation plan:
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
   b. **LLM-as-a-Judge** evaluates response (Haiku routine, Opus for flagged)
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

## 10. n8n Workflows (25, 424 nodes)

| Workflow | Nodes | Subsystem | Purpose |
|----------|-------|-----------|---------|
| YouTrack Receiver | 5 | All | Webhook listener, fires Runner async |
| **Claude Runner** | 48 | All | Lock -> cooldown -> RAG -> Build Prompt (per-source token caps) -> Launch Claude -> Parse -> Validate -> **Screen (Evaluator-Optimizer)** -> Post |
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

## 11. MCP Servers (10, 153 tools)

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

## 12. Sub-Agents (10)

Designed with [Anthropic Academy](https://academy.anthropic.com/) patterns:
- **Structured output** — numbered sections with natural stopping points
- **Obstacle reporting** — every agent has an "Obstacles Encountered" section
- **Limited tool access** — read-only for researchers (no Edit/Write)
- **Specific descriptions** — shape the input prompts the main agent writes
- **Decision rule** — "Only delegate when you need the RESULT, not the journey"
- **Anti-patterns avoided** — no expert claims, no sequential pipelines, no test runners

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

**Pipeline integration:** Build Prompt detects complex sessions (timeout >= 600, correlated, kubernetes, multi-file dev) and injects `SUB-AGENT DELEGATION` instructions. Claude launches relevant sub-agents IN PARALLEL for research, then synthesizes. Saves 40-60% cost by routing research to Haiku ($1/M) vs Opus ($15/M).

---

## 13. Claude Code Skills & Hooks

### Skills (5 + 1 command)

| Skill | Delegation | Purpose |
|-------|------------|---------|
| `/triage <host> <rule> <sev>` | Forks to triage-researcher | Full infra triage with structured output |
| `/alert-status` | Inline | Show active alerts across NL+GR (6 sources) |
| `/cost-report [days]` | Inline | Session cost/confidence analysis from SQLite |
| `/drift-check [nl\|gr\|all]` | Forks to triage-researcher | IaC vs live infrastructure drift detection |
| `/wiki-compile [--full\|--health]` | Inline | Compile/refresh the [Karpathy-style knowledge base](wiki/index.md) |
| `/review` | Inline | Merge request review |

### Hooks (2 PreToolUse + 1 Stop + 1 PreCompact)

Deterministic enforcement — fires BEFORE permission checks, cannot be bypassed:

| Hook | Event | Purpose |
|------|-------|---------|
| [`unified-guard.sh`](scripts/hooks/unified-guard.sh) | PreToolUse (Bash, Edit, Write) | Merged guardrail: 78 blocked patterns (destructive + exfil + injection) + 12 protected file patterns |
| [`audit-bash.sh`](scripts/hooks/audit-bash.sh) | — | (reference, superseded by unified-guard.sh) |
| [`protect-files.sh`](scripts/hooks/protect-files.sh) | — | (reference, superseded by unified-guard.sh) |
| [`mempal-session-save.sh`](scripts/hooks/mempal-session-save.sh) | Stop | Auto-saves session transcript every 15 messages ([MemPalace](https://github.com/milla-jovovich/mempalace) pattern) |
| [`mempal-precompact.sh`](scripts/hooks/mempal-precompact.sh) | PreCompact | Emergency transcript save before context compression |

---

## 14. OpenClaw Tier 1 Skills (17)

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

### SQLite Tables (31, 150K+ rows)

| Table | Rows | Purpose |
|-------|------|---------|
| `sessions` | 62 | Active sessions (issue_id, session_id, cost, confidence, trace_id) |
| `session_log` | 239 | Archived sessions with full tracking fields |
| `session_quality` | 34 | 5-dimension quality scores (confidence, cost efficiency, completeness, feedback, speed) |
| `session_trajectory` | 86 | Per-session agent trajectory scores (8 infra / 4 dev step markers) |
| `session_judgment` | 46 | LLM-as-a-Judge results (5-dimension rubric, Haiku/Opus + dev rubric) |
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
| `graph_entities` | 360 | GraphRAG entities (host, alert_rule, incident, lesson) |
| `graph_relationships` | 193 | GraphRAG relationships (triggers, affects, resolves, depends_on) |
| `credential_usage_log` | 39 | Credential rotation tracking with 90-day policy |
| `otel_spans` | 39K | OpenTelemetry spans (local storage + OTLP export to OpenObserve) |
| `chaos_experiments` | 70 | Chaos experiment results (scenario, target, outcome, recovery_time); embeddings indexed in FAISS (4/4 tables migration-ready) |
| `chaos_exercises` | 1 | Scheduled chaos exercise records |
| `chaos_retrospectives` | 34 | Post-chaos exercise retrospectives |
| `chaos_findings` | 29 | Improvement findings from chaos exercises |
| `ragas_evaluation` | 136 | RAGAS metrics (faithfulness, precision, recall per query); hardened golden set = 33 queries (15 hard-eval tagged) across multi-hop / temporal / negation / meta / cross-corpus |
| `health_check_detail` | 1,675 | Per-check results for health trending |
| `queue` | — | Session queue for slot management |

**Backup:** Daily at 02:00 UTC, 7-day retention, integrity checked ([`backup-gateway-db.sh`](scripts/backup-gateway-db.sh)).

### Prometheus Metrics (10 exporters, 38 cron jobs)

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

### Grafana Dashboards (10, 64+ panels)

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

External quality assessment via Claude API:
- **Haiku (low effort):** ALL sessions. ~$0.01/session. Routine quality check.
- **Opus (max effort):** Flagged sessions (confidence < 0.7, duration > 5min, thumbs-down). ~$0.05/session.

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
| **Approval gates** | Infrastructure changes require human thumbs-up or poll vote | Workflow | Agent autonomy |
| **Evaluator-Optimizer** | Haiku screening for high-stakes responses (3 nodes in Runner). Rewrites or escalates before posting. | Workflow | Agent self-approval |

Additional: AUTHORIZED_SENDERS filter, **EUR 5/session cost warning + $25/day plan-only** budget ceiling, zero hardcoded passwords (all env vars sourced from `.env`), confidence gating (< 0.5 = STOP).

### Adversarial Red-Team Program

54 test cases (32 baseline + 22 adversarial) in [`test-hook-blocks.py`](scripts/test-hook-blocks.py). Tests prompt injection bypass (unicode homoglyphs, base64 encoding, variable expansion), tool chaining misuse (wget+execute, python os.system, curl POST exfil), indirect exfiltration (DNS, log injection, /proc), and cross-tier escalation (docker exec, pct exec, kubectl exec). Quarterly schedule via chaos-calendar.sh. 12 bypass vectors hardened; 8 remaining tracked for follow-up.

### RAGAS RAG Quality Metrics

[`ragas-eval.py`](scripts/ragas-eval.py) evaluates RAG quality using Claude Haiku as judge (pure Python, no external deps):
- Faithfulness: 0.88 (claim decomposition + NLI verification)
- Context Precision: 0.86 (weighted precision@k)
- Context Recall: 0.88 (reference coverage)

Golden set hardened April 2026 from 18 saturated queries (couldn't measure pipeline lifts — all configs scored 0.88+) to **33 queries with 15 hard-eval tagged** across 5 categories: multi-hop (requires ≥2 docs to answer), temporal ("last N days"), negation ("which do NOT"), meta (self-referential), cross-corpus (wiki + incident + transcript corroboration). Easy-vs-hard queries now show **10× faithfulness differential** (1.00 vs 0.10 on a 5-query sample), so retrieval changes are measurable again. Runner flags: `--limit N` and `--only-category hard-eval` for targeted runs. Prometheus metrics via [`write-ragas-metrics.sh`](scripts/write-ragas-metrics.sh).

### Weekly Hard-Retrieval Cron

[`weekly-eval-cron.sh`](scripts/weekly-eval-cron.sh) (Monday 05:00 UTC) runs [`run-hard-eval.py`](scripts/run-hard-eval.py) on the 50-query `hard-retrieval-v2` set + 10-query `hard-kg` set, emits 6 Prometheus metrics (`kb_hard_eval_hit_rate`, `kb_hard_eval_coverage_rate`, `kb_hard_eval_kg_coverage`, `kb_hard_eval_latency_p50_seconds`, `kb_hard_eval_latency_p95_seconds`, `kb_hard_eval_last_run_timestamp_seconds`). Manual baseline captured 2026-04-18: **judge_hit@5 = 0.90** (45/50), KG coverage 0.70 (7/10), p50 5.7s, p95 13.6s. Diagnostic flags: `--only-ids H06,H08,H12 --verbose --skip-kg` for per-query investigation with full retrieval chain + judge rationale.

### Chaos Engineering

47 experiments across 11 unique scenarios. 6-layer safety architecture (rate limiting, graph validation, Turnstile auth, dead-man switch, abort threshold, preflight gates). Weekly baseline, monthly tunnel sweep, quarterly DMZ drill, semi-annual game day. 1s measurement resolution. Declarative catalog (25 experiments defined). Prometheus metrics + retrospective pipeline.

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
| Compiler | [`wiki-compile.py`](scripts/wiki-compile.py) — reads 7+ sources, compiles 44 articles |
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
| **Synth threshold** | Top rerank score < 0.4 | Calls **Haiku synth** via Anthropic API. On HTTP 429 / 401 / timeout / network error / forced-empty (all 5 modes injected via `SYNTH_HAIKU_FORCE_FAIL`), falls back to local qwen2.5 synth without breaking the response chain. |

CLI: `python3 scripts/kb-semantic-search.py list-recent --hours 48 --path-prefix memory/ --limit 10` returns an mtime-ranked listing directly, bypassing the RRF pipeline.

---

## 4. Compiled Knowledge Base (Karpathy-Style Wiki)

Following [Andrej Karpathy's LLM Knowledge Bases pattern](https://x.com/karpathy/status/2039805659525644595): raw data from 7+ fragmented knowledge stores is compiled into a unified, browsable markdown wiki with auto-maintained indexes and health checks.

### Why

The system accumulated knowledge across 7+ independent stores — each with its own access mechanism:
- 117 memory files (grep by keyword)
- 55 CLAUDE.md files (hostname pattern routing)
- 28 incident_knowledge rows (semantic vector search)
- 27 lessons_learned (SQL query)
- 94 openclaw_memory entries (key-value lookup)
- ~5,200 03_Lab reference files (Syncthing + lab-lookup.py)
- 51 docs (manual reading)

To answer "what do we know about nl-fw01?" required 5 separate lookups across 3 different mechanisms. No unified view existed.

### How It Works

[`scripts/wiki-compile.py`](scripts/wiki-compile.py) reads all sources, compiles them into 44 markdown articles organized by category:

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

**RAG integration:** All 44 articles are chunked by heading and embedded via nomic-embed-text. They appear as a 3rd ranking signal in the existing Reciprocal Rank Fusion search — alongside semantic (incident_knowledge) and keyword matches.

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
| Knowledge articles | 0 | **44** |
| Lookups to answer "what do we know about host X?" | 5 | **1** |

---

## 18. Operating Modes & Commands

### Modes

| Mode | Frontend | Backend | Use Case |
|------|----------|---------|----------|
| `oc-cc` | OpenClaw | Claude Code | **Default** — full 3-tier pipeline |
| `oc-oc` | OpenClaw | OpenClaw (self-contained) | Quick lookups |
| `cc-cc` | n8n/Claude | Claude Code | Direct Claude access (legacy) |
| `cc-oc` | n8n | OpenClaw as backend | Testing |

Switch with `!mode <mode>` in any Matrix room.

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
│   ├── agents/                     # 10 sub-agents (Anthropic Academy patterns)
│   ├── skills/                     # 5 Claude Code skills (incl. wiki-compile)
│   ├── commands/review.md          # /review command
│   ├── settings.json               # Hooks configuration (2 PreToolUse + 1 Stop + 1 PreCompact)
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
├── grafana/                        # Dashboard JSON exports (10 dashboards, 64+ panels)
├── openclaw/
│   ├── SOUL.md                     # OpenClaw system prompt (623 lines)
│   ├── openclaw.json               # OpenClaw configuration
│   ├── exec-approvals.json         # 36 skill patterns (no wildcards)
│   ├── claude-knowledge-lookup.sh   # CLAUDE.md + memory knowledge extraction
│   └── skills/                     # 17 native skills (incl. 4 always-on protocol skills)
├── scripts/
│   ├── hooks/                      # 4 Claude Code hooks (2 PreToolUse + 1 Stop + 1 PreCompact)
│   ├── openclaw-repo-sync.sh       # */30 cron: git pull 23 repos + memory + DB sync to openclaw01
│   ├── grade-prompts.sh            # Daily prompt scorecard
│   ├── score-trajectory.sh         # JSONL trajectory scoring
│   ├── llm-judge.sh               # LLM-as-a-Judge (Haiku/Opus)
│   ├── golden-test-suite.sh        # 64-test benchmark
│   ├── regression-detector.sh      # 7d rolling regression
│   ├── metamorphic-monitor.sh      # Self-modification monitor
│   ├── post-reboot-vpn-check.sh    # 12 cross-site subnet probes
│   ├── backup-gateway-db.sh        # Daily SQLite backup
│   ├── kb-semantic-search.py       # 5-signal RRF search (semantic + keyword + wiki + transcripts + chaos baselines)
│   ├── wiki-compile.py             # Karpathy-style wiki compiler (7+ sources → 44 articles)
│   ├── archive-session-transcript.py  # MemPalace: JSONL → exchange-pair chunks → embeddings
│   ├── agent-diary.py              # MemPalace: persistent per-agent memory (write/read/inject)
│   ├── build-prompt-layers.py      # MemPalace: L0-L3 layered injection with token caps
│   └── ... (50 scripts total)
├── wiki/                           # Compiled knowledge base (44 auto-generated articles)
│   ├── index.md                    # Master index with categorized links
│   ├── operations/                 # Operational rules, runbooks, emergency procedures
│   ├── hosts/                      # Per-host compiled pages (~25 notable hosts)
│   ├── incidents/                  # Chronological timeline + detail pages
│   ├── topology/                   # Network topology (NL, GR, VPN mesh, K8s)
│   ├── services/                   # Service architecture (ChatOps, OpenClaw, RAG, security)
│   ├── lab/                        # 03_Lab file manifest
│   └── health/                     # Staleness report + coverage matrix
├── workflows/                      # 25 n8n workflow JSON exports
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

## License

Sanitized mirror of a private GitLab repository. Internal hostnames, IP addresses, credentials, and personal identifiers replaced with placeholders (128 replacement patterns + 20 post-scan grep patterns). Provided as-is for educational and reference purposes.

---

*Built by a solo infrastructure operator who got tired of waking up at 3am for alerts that an AI could triage.*
