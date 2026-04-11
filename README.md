# agentic-chatops

AI agents that triage infrastructure alerts, investigate root causes, and propose fixes — while a solo operator sleeps.

> **For the complete technical reference, see [README.extensive.md](README.extensive.md).**

![Architecture](docs/architecture-diagram-v2.drawio.png)

## The Problem

One person. **310+ infrastructure objects** across 6 sites. 3 firewalls, 12 Kubernetes nodes, self-hosted everything. When an alert fires at 3am, there's no team to call. There never is.

## The Solution

Three agentic subsystems that handle the detective work — **ChatOps** (infrastructure), **ChatSecOps** (security), **ChatDevOps** (CI/CD) — built on [n8n](https://n8n.io/) orchestration, [Matrix](https://matrix.org/) as the human interface, and a 3-tier agent architecture. The human stays in the loop for every infrastructure change. The system never acts without a thumbs-up or poll vote.

---

## What Makes This Different

### Self-Improving Prompts (nobody else does this)

The system evaluates its own performance and auto-patches its prompts. Every session is scored by an [LLM-as-a-Judge](https://arxiv.org/abs/2306.05685) on 5 quality dimensions. When a dimension averages below threshold over 30 days, a targeted instruction patch is generated and injected into the next session's prompt. Patches auto-expire after 30 days and are re-evaluated by the monthly [eval flywheel](scripts/eval-flywheel.sh).

```
Session → LLM Judge (5 dims) → prompt-improver.py detects low score
  → generates patch → config/prompt-patches.json → Build Prompt reads it
  → next session gets improved instructions → re-scored → loop closes
```

### AI Planner Wired to Proven Ansible Playbooks

Before Claude Code investigates, a Haiku planner generates a 3-5 step investigation plan. The planner queries AWX for matching Ansible playbooks from **41 proven templates** (maintenance, cert sync, K8s drain, PVE updates, DMZ deployments). Plans naturally include "Run AWX Template 64 with dry_run=true" as remediation steps — bridging AI reasoning with proven automation.

### Predictive Alerting

Instead of only reacting after alerts fire, the system queries LibreNMS API daily for **trending risk** across both sites. Devices are scored on disk usage trends, alert frequency, and health signals. A daily top-10 risk report posts to Matrix before problems become incidents.

### 4-Signal RAG + GraphRAG + Staleness Warnings

Retrieval uses [Reciprocal Rank Fusion](docs/industry-agentic-references.md#5-rag--retrieval-optimization) across 4 signals (semantic embeddings + keyword match + [compiled wiki](wiki/index.md) + [MemPalace](https://github.com/milla-jovovich/mempalace) session transcripts), plus a **GraphRAG knowledge graph** (263 entities, 127 relationships) for incident-host-alert traversal. Results older than 7 days get age-proportional staleness warnings injected into the prompt.

### Karpathy-Style Compiled Knowledge Base

Following [Andrej Karpathy's LLM Knowledge Bases pattern](https://x.com/karpathy/status/2039805659525644595): raw data from 7+ sources (74 memory files, 55 CLAUDE.md files, 33 incidents, 27 lessons, 101 OpenClaw memories, 15 skills, ~5,200 lab docs) is compiled into a browsable [45-article wiki](wiki/index.md) with auto-maintained indexes, daily SHA-256 incremental recompilation, and contradiction detection. All articles embedded into RAG as the 3rd fusion signal.

### Full Observability Stack with OTel

88,448 tool calls instrumented across 108 tool types with per-tool error rates and latency percentiles. 39K OTel spans across 94 traces exported to OpenObserve (OTLP). 9 Grafana dashboards (127 panels) covering ChatOps, ChatSecOps, ChatDevOps, and trace analysis. 18,220 infrastructure commands logged across 232 devices.

### Formal Evaluation Pipeline

98 test scenarios across [3 eval sets](docs/evaluation-process.md) (regression/discovery/holdout) + 18 node-level tests + 12 negative controls. [Prompt Scorecard](scripts/grade-prompts.sh) grades 19 surfaces daily on 6 dimensions. [Agent Trajectory](scripts/score-trajectory.sh) scoring on 8 infra / 4 dev steps. A/B variant testing (react_v1 vs react_v2). CI eval gate blocks bad merges. Monthly eval flywheel cycle.

---

## Architecture

```
Alert → n8n → OpenClaw (GPT-5.1, 7-21s) → Haiku Planner (+AWX) → Claude Code (Opus 4.6, 5-15min) → Human (Matrix)
```

| Component | Role |
|-----------|------|
| **[n8n](https://n8n.io/)** | 25 workflows (~425 nodes) — alert intake, session management, knowledge population |
| **[OpenClaw](https://openclaw.com/)** (GPT-5.1) | Tier 1 — fast triage with 15 skills, handles 80%+ without escalation |
| **[Claude Code](https://docs.anthropic.com/)** (Opus 4.6) | Tier 2 — 10 sub-agents, ReAct reasoning, interactive [POLL] approval |
| **[AWX](https://www.ansible.com/awx)** | 41 Ansible playbooks wired into AI planner |
| **Matrix** (Synapse) | Human-in-the-loop — polls, reactions, replies |
| **Prometheus + Grafana** | 9 dashboards, 127 panels, 10 metric exporters |
| **OpenObserve** | OTel tracing — 39K spans, OTLP export |
| **Ollama** (RTX 3090 Ti) | Local embeddings — nomic-embed-text, query rewriting |
| **[Compiled Wiki](wiki/index.md)** | 45 articles from 7+ sources, daily recompilation |

## Safety — 7 Layers

The system investigates freely but **never executes infrastructure changes without human approval**:

1. **Claude Code hooks** — 42 injection patterns + 30 destructive command patterns blocked deterministically
2. **safe-exec.sh** — code-level blocklist that prompt injection cannot bypass
3. **exec-approvals.json** — 36 specific skill patterns (no wildcards)
4. **Evaluator-Optimizer** — Haiku screens high-stakes responses before posting
5. **Confidence gating** — < 0.5 stops, < 0.7 escalates
6. **Budget ceilings** — $10/session warning, $25/day plan-only mode
7. **Credential scanning** — 16 PII patterns redacted, 39 credentials tracked with rotation

## Key Numbers

| Metric | Value |
|--------|-------|
| Operational activation audit | [A (91.8%)](docs/operational-activation-audit-2026-04-10.md) — 23 tables populated, 148K+ rows |
| Agentic design patterns | [21/21](docs/agentic-patterns-audit.md) at A+ ([tri-source audit](docs/tri-source-audit.md): 11/11 dimensions) |
| AWX/Ansible runbooks | 41 playbooks wired into Plan-and-Execute |
| Tool call instrumentation | 88,448 calls across 108 types, per-tool error rates + latency p50/p95 |
| OTel tracing | 39K spans → OpenObserve + Prometheus metrics |
| GraphRAG knowledge graph | 263 entities, 127 relationships |
| Self-improving prompt patches | 5 active (auto-generated from eval scores) |
| Predictive risk scoring | 123 devices scanned daily, 23 at elevated risk |
| Holistic health check | [99%](scripts/holistic-agentic-health.sh) — 138 checks across 37 sections (functional + e2e + cross-site) |

## Documentation

| Document | What it covers |
|----------|---------------|
| [Operational Activation Audit](docs/operational-activation-audit-2026-04-10.md) | Scores data activation — 21/21 tables, 109K rows |
| [Tri-Source Audit](docs/tri-source-audit.md) | 11/11 dimensions A+ (Gulli + Anthropic + industry) |
| [External Source Mapping](docs/external-source-implementation-mapping-2026-04-11.md) | atlas-agents + claude-code-from-source techniques applied |
| [Agentic Patterns Audit](docs/agentic-patterns-audit.md) | 21/21 pattern scorecard |
| [Evaluation Process](docs/evaluation-process.md) | 3-set eval, flywheel, CI gate |
| [ACI Tool Audit](docs/aci-tool-audit.md) | 10 MCP tools against 8-point checklist |
| [Compiled Wiki](wiki/index.md) | 45 auto-compiled articles |
| [Installation Guide](docs/installation.md) | Setup steps + cron configuration |

## Quick Start

```bash
git clone https://github.com/papadopouloskyriakos/agentic-chatops.git
cd agentic-chatops
cp .env.example .env   # Add your credentials
```

See the [Installation Guide](docs/installation.md) for full setup.

## References

1. **[Agentic Design Patterns](https://drive.google.com/file/d/1-5ho2aSZ-z0FcW8W_jMUoFSQ5hTKvJ43/view?usp=drivesdk)** by Antonio Gulli (Springer, 2025) — 21 patterns, all implemented
2. **[Claude Certified Architect – Foundations](docs/Claude+Certified+Architect+–+Foundations+Certification+Exam+Guide.pdf)** (Anthropic) — sub-agent design
3. **[Industry References](docs/industry-agentic-references.md)** — Anthropic, OpenAI, LangChain, Microsoft
4. **[atlas-agents](https://github.com/agulli/atlas-agents)** + **[claude-code-from-source](https://github.com/alejandrobalderas/claude-code-from-source)** — external techniques applied

## License

Sanitized mirror of a private GitLab repository. Provided as-is for educational and reference purposes.

---

*Built by a solo infrastructure operator who got tired of waking up at 3am for alerts that an AI could triage.*
