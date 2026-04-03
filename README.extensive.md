# agentic-chatops — Comprehensive Technical Reference

Production agentic ChatOps/ChatSecOps/ChatDevOps platform implementing all 21 design patterns from Antonio Gulli's *Agentic Design Patterns* (Springer, 2025). Dual-source audited against [Anthropic's official documentation](https://docs.anthropic.com/) (17 sources) and the [Anthropic Academy](https://academy.anthropic.com/) sub-agent design course.

> **For a concise overview, see [README.md](README.md).**

---

## Table of Contents

1. [Three Agentic Subsystems](#1-three-agentic-subsystems)
2. [The 3-Tier Agent Architecture](#2-the-3-tier-agent-architecture)
3. [Agentic Design Patterns — 21/21](#3-agentic-design-patterns--2121)
4. [Alert Lifecycle (End-to-End)](#4-alert-lifecycle-end-to-end)
5. [n8n Workflows](#5-n8n-workflows-17-400-nodes)
6. [MCP Servers](#6-mcp-servers-10-153-tools)
7. [Sub-Agents](#7-sub-agents-10)
8. [Claude Code Skills & Hooks](#8-claude-code-skills--hooks)
9. [OpenClaw Tier 1 Skills](#9-openclaw-tier-1-skills-14)
10. [ChatSecOps — Security Operations](#10-chatsecops--security-operations)
11. [Data & Intelligence](#11-data--intelligence)
12. [Evaluation System](#12-evaluation-system)
13. [Guardrails & Safety](#13-guardrails--safety)
14. [Inter-Agent Communication](#14-inter-agent-communication-nl-a2av1)
15. [RAG Pipeline](#15-rag-pipeline)
16. [Operating Modes & Commands](#16-operating-modes--commands)
17. [Repository Structure](#17-repository-structure)
18. [Installation](#18-installation)
19. [References](#19-references)

---

## 1. Three Agentic Subsystems

| Subsystem | Scope | Matrix Rooms | Alert Sources | Triage Scripts |
|-----------|-------|-------------|---------------|----------------|
| **ChatOps** | Infrastructure availability, performance, maintenance | `#infra-nl-prod`, `#infra-gr-prod` | LibreNMS, Prometheus, Synology DSM | [infra-triage](openclaw/skills/infra-triage/), [k8s-triage](openclaw/skills/k8s-triage/), [correlated-triage](openclaw/skills/correlated-triage/) |
| **ChatSecOps** | Security: intrusion detection, vulnerability scanning, MITRE ATT&CK | Same rooms (shared) | CrowdSec, vulnerability scanners | [security-triage](openclaw/skills/security-triage/), [baseline-add](openclaw/skills/baseline-add/) |
| **ChatDevOps** | Software development: CI/CD, features, bugs | `#cubeos`, `#meshsat` | GitLab CI | Code analysis via Claude Code + 4 dev sub-agents |

All three share: n8n orchestration (Runner, Bridge, Session End, Poller), Matrix as human-in-the-loop, YouTrack for issue tracking, and the 3-tier agent architecture.

---

## 2. The 3-Tier Agent Architecture

```
LibreNMS/Prometheus/CrowdSec Alert
         |
         v
   +--------------+     +---------------+     +------------------+
   |  n8n          |---->|  OpenClaw      |---->|  Claude Code      |
   |  Orchestrator |     |  (Tier 1)     |     |  (Tier 2)         |
   |  17 workflows |     |  GPT-4o       |     |  Claude Opus 4.6  |
   |  ~400 nodes   |     |  14 skills    |     |  10 sub-agents    |
   +---------+-----+     +---------------+     +---------+---------+
             |                                           |
             v                                           v
   +--------------+                              +---------------+
   |  Matrix       |<-----------------------------|  Human (T3)    |
   |  Chat rooms   |  polls, reactions, replies   |  Approval      |
   +--------------+                              +---------------+
```

- **Tier 1 (OpenClaw / GPT-4o):** Fast triage (7-21s). 14 native skills. Creates YouTrack issues, deduplicates alerts, investigates via SSH/kubectl, outputs confidence scores. Handles 80%+ of alerts without escalation.
- **Tier 2 (Claude Code / Opus 4.6):** Deep analysis (5-15 min). 10 specialized sub-agents (Haiku for research, Opus for security). Reads Tier 1 findings, verifies using ReAct reasoning, proposes remediation via interactive polls, executes after human approval. For complex sessions, delegates research to sub-agents IN PARALLEL.
- **Tier 3 (Human):** Clicks a poll option in Matrix, reacts with thumbs up/down, or types a reply. The system stops and waits — it never makes infrastructure changes autonomously.

---

## 3. Agentic Design Patterns — 21/21

Benchmarked against all 21 patterns from Antonio Gulli's book + dual-source audited against [Anthropic's official documentation](https://docs.anthropic.com/) (17 sources). Full audit: [`docs/agentic-patterns-audit.md`](docs/agentic-patterns-audit.md). Book gap analysis: [`docs/book-gap-analysis.md`](docs/book-gap-analysis.md).

**Score: 17 A/A+ and 4 A-**

| # | Pattern | Grade | Implementation | Book Chapter |
|---|---------|-------|---------------|-------------|
| 1 | **Prompt Chaining** | A | n8n 44-node Runner: lock -> cooldown -> RAG -> Build Prompt -> Launch -> Parse -> Validate -> Post. Sequential with programmatic gates between steps. | Ch1 |
| 2 | **Routing** | A- | Issue prefix -> Matrix room -> session slot. 8 alert categories auto-detected (availability, resource, storage, network, kubernetes, certificate, maintenance, correlated). | Ch2 |
| 3 | **Parallelization** | A- | 5 concurrent session slots (cubeos, meshsat, dev, infra-nl, infra-gr). Async Progress Poller. Sub-agents launched in parallel for complex sessions. | Ch3 |
| 4 | **Reflection** | A- | Cross-tier review: OpenClaw critiques Claude output with 5-step chain-of-verification (REVIEW_JSON: AGREE/DISAGREE/AUGMENT). Self-consistency check detects confidence/reasoning mismatches. | Ch4 |
| 5 | **Tool Use** | A | 10 MCP servers, 153 tools. Custom Proxmox MCP (15 tools). n8n-as-code offline schemas for 537 nodes. `ToolSearch` for deferred tool discovery. | Ch5 |
| 6 | **Planning** | A- | Interactive [POLL] plan selection via MSC3381 Matrix polls. Plan-only mode (`--plan` flag) for multi-file dev tasks and correlated bursts. | Ch6 |
| 7 | **Multi-Agent** | **A+** | 3-tier hierarchy + 10 specialized sub-agents (6 infra + 4 dev) with [Anthropic Academy](https://academy.anthropic.com/) patterns: structured output, obstacle reporting, limited tools, no expert claims, parallel not sequential. Pipeline delegation for complex sessions. | Ch7 |
| 8 | **Memory** | A | CLAUDE.md (<200 lines per Anthropic guidance). 6 path-scoped rules. Auto-memory. SQLite (14 tables). Vector embeddings (nomic-embed-text, 768 dims). Episodic memory (openclaw_memory). Lessons-to-prompt pipeline. | Ch8 |
| 9 | **Learning & Adaptation** | A | A/B prompt testing (react_v1 vs react_v2, deterministic by issue hash). Outcome scoring (approved/rejected/mixed). Lessons-to-prompt pipeline (30d window). Regression detection (6h cron). Metamorphic monitor (auto-variant promotion at 25+ sessions). | Ch9 |
| 10 | **MCP** | A | 10 servers including custom Proxmox MCP (15 tools). mcporter Docker bridge for OpenClaw. Tool search enabled by default. Per-tool allowlisting in settings. | Ch10 |
| 11 | **Goal Setting** | A- | Confidence gating (< 0.5 = STOP, < 0.7 = escalate). Budget enforcement ($5/session warning, $25/day plan-only). Dynamic timeout by complexity (300-600s). Formalized contracts (`CONTRACT:` block in YT description). | Ch11 |
| 12 | **Exception Handling** | A | 5-layer gateway watchdog (n8n health, workflow activation, proactive bounce, error detection, zombie cleanup). `ERROR_CONTEXT` structured propagation (failed step, completed steps, suggested next action). Fallback ladders (AWX -> API -> SSH -> Ping). | Ch12 |
| 13 | **Human-in-the-Loop** | A | MSC3381 polls rendered in Matrix Element client. Thumbs up/down reactions. 15min remind / 30min auto-pause approval timeouts. AUTHORIZED_SENDERS filter. Formalized contracts define acceptance criteria. | Ch13 |
| 14 | **RAG** | A | Vector embeddings (nomic-embed-text on Ollama, 768 dims). 100% embedding coverage. Cosine similarity search with 0.3 threshold + keyword fallback. 3-tier injection (incident_knowledge + lessons_learned + session history). Triage RAG at Step 1.5 in all scripts. Backfill cron every 30min. | Ch14 |
| 15 | **A2A Communication** | A | [NL-A2A/v1 protocol](docs/a2a-protocol.md). Agent cards ([`a2a/agent-cards/`](a2a/agent-cards/)). Message envelope with protocol, messageId, from/to, type, payload. REVIEW_JSON auto-action. Task lifecycle logging. 53 A2A entries. | Ch15 |
| 16 | **Resource Optimization** | **A+** | Haiku/Opus model routing for sub-agents (9:1 cost ratio). JSONL token-based cost tracking from stream-json. Per-category cost prediction. Dynamic timeout. $5/session + $25/day budget. Subsystem-level cost metrics. | Ch16 |
| 17 | **Reasoning** | A | ReAct (THOUGHT/ACTION/OBSERVATION) mandatory for infra. Step-back prompting for recurring alerts. Tree-of-thought (H1/H2 hypotheses) for correlated bursts. Self-consistency check. Chain-of-verification for cross-tier reviews. A/B variant testing. | Ch17 |
| 18 | **Guardrails** | **A+** | 6-layer defense: Claude Code hooks (PreToolUse, deterministic) + safe-exec.sh (code-level blocklist) + exec-approvals.json (36 patterns, no wildcards) + input sanitization (10 injection patterns) + credential scanning (10 regex) + output fact-checking. Zero hardcoded passwords. | Ch18 |
| 19 | **Evaluation** | **A+** | 19-surface [Prompt Scorecard](scripts/grade-prompts.sh) (6 dimensions, daily). [Agent Trajectory Evaluation](scripts/score-trajectory.sh) (8 infra / 4 dev steps from JSONL). [LLM-as-a-Judge](scripts/llm-judge.sh) (Haiku routine + Opus flagged, 5-dimension rubric). Formalized contracts. 54 golden tests. Regression detector. Metamorphic monitor. A/B testing. Confidence calibration. | Ch19 |
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

## 4. Alert Lifecycle (End-to-End)

```
1. LibreNMS detects "Devices up/down" on host X
2. n8n LibreNMS Receiver -> dedup, flap detection, burst detection
3. Posts to Matrix #infra room: "[LibreNMS] ALERT: host X -- Devices up/down"
4. OpenClaw (Tier 1) auto-triages:
   a. Checks YouTrack for existing issues (24h dedup)
   b. Creates issue IFRNLLEI01PRD-XXX
   c. Queries NetBox CMDB for device identity
   d. Queries incident knowledge base (semantic search, Step 1.5)
   e. Investigates via SSH (PVE status, container logs)
   f. Posts findings + CONFIDENCE score to YouTrack + Matrix
   g. If confidence < 0.7 or critical: escalates to Claude Code
5. Claude Code (Tier 2) activates:
   a. Reads YouTrack issue + Tier 1 comments
   b. For complex sessions: delegates research to sub-agents IN PARALLEL
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
9. Session End:
   a. Archives to session_log with cost/duration/confidence
   b. Populates incident_knowledge with vector embedding
   c. Computes 5-dimension quality score
   d. Scores agent trajectory from JSONL (8 steps)
   e. LLM-as-a-Judge evaluates response (Haiku routine, Opus for flagged)
   f. Extracts lessons learned
   g. Posts summary to YouTrack + Matrix
```

**Real incident:** IFRNLLEI01PRD-82 — full L1->L2->L3->approval->fix->recovery cycle. LibreNMS alert -> n8n -> Matrix -> OpenClaw triage (30s) -> Claude Code investigation (8min) -> [POLL] with 3 options -> operator clicks Plan A -> fix applied -> recovery confirmed -> YT closed.

---

## 5. n8n Workflows (17, ~400 nodes)

| Workflow | Nodes | Subsystem | Purpose |
|----------|-------|-----------|---------|
| YouTrack Receiver | 5 | All | Webhook listener, fires Runner async |
| **Claude Runner** | 44 | All | Lock -> cooldown -> RAG -> Build Prompt -> Launch Claude -> Parse -> Validate -> Post |
| Progress Poller | 10 | All | Polls JSONL log every 30s, posts tool activity to Matrix |
| **Matrix Bridge** | 73 | All | Polls /sync, routes commands, manages sessions, handles reactions/polls |
| Session End | 12 | All | Summarize -> archive -> KB -> trajectory score -> LLM judge -> YT comment |
| LibreNMS Receiver (NL) | 26 | ChatOps | Alert dedup, flap detection, burst detection, recovery tracking |
| LibreNMS Receiver (GR) | 26 | ChatOps | Clone for GR site |
| Prometheus Receiver (NL) | 26 | ChatOps | K8s alert processing, fingerprint dedup, escalation cooldown |
| Prometheus Receiver (GR) | 26 | ChatOps | Clone for GR site |
| Security Receiver (NL) | 25 | ChatSecOps | Vulnerability scanner findings, baseline comparison |
| Security Receiver (GR) | 25 | ChatSecOps | Clone for GR site |
| CrowdSec Receiver (NL) | 22 | ChatSecOps | CrowdSec alerts, MITRE mapping, auto-suppression learning |
| CrowdSec Receiver (GR) | 22 | ChatSecOps | Clone for GR site |
| Synology DSM Receiver | 7 | ChatOps | I/O latency, SMART, iSCSI errors |
| WAL Self-Healer (GR) | 18 | ChatOps | Auto-restart Prometheus on WAL corruption |
| CI Failure Receiver | 9 | ChatDevOps | GitLab pipeline webhook -> Matrix + YT comment |
| Doorbell | 6 | — | UniFi Protect -> Mattermost+Matrix+HA+Frigate |

---

## 6. MCP Servers (10, 153 tools)

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

## 7. Sub-Agents (10)

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

## 8. Claude Code Skills & Hooks

### Skills (4 + 1 command)

| Skill | Delegation | Purpose |
|-------|------------|---------|
| `/triage <host> <rule> <sev>` | Forks to triage-researcher | Full infra triage with structured output |
| `/alert-status` | Inline | Show active alerts across NL+GR (6 sources) |
| `/cost-report [days]` | Inline | Session cost/confidence analysis from SQLite |
| `/drift-check [nl\|gr\|all]` | Forks to triage-researcher | IaC vs live infrastructure drift detection |
| `/review` | Inline | Merge request review |

### Hooks (2 PreToolUse)

Deterministic enforcement — fires BEFORE permission checks, cannot be bypassed:

| Hook | Matcher | Purpose |
|------|---------|---------|
| [`audit-bash.sh`](scripts/hooks/audit-bash.sh) | Bash | Logs all commands + blocks 30+ destructive patterns + reverse shells |
| [`protect-files.sh`](scripts/hooks/protect-files.sh) | Edit\|Write | Blocks edits to .env, *.key, *.pem, credentials, passwords |

---

## 9. OpenClaw Tier 1 Skills (14)

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
| [`safe-exec.sh`](openclaw/skills/safe-exec.sh) | Exec enforcement wrapper (30+ blocked patterns, rate limiting) |

---

## 10. ChatSecOps — Security Operations

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

## 11. Data & Intelligence

### SQLite Tables (14)

| Table | Purpose |
|-------|---------|
| `sessions` | Active sessions (issue_id, session_id, cost, confidence, subsystem) |
| `session_log` | Archived sessions with full tracking fields |
| `session_quality` | 5-dimension quality scores (confidence, cost efficiency, completeness, feedback, speed) |
| `session_trajectory` | Per-session agent trajectory scores (8 infra / 4 dev step markers) |
| `session_judgment` | LLM-as-a-Judge results (5-dimension rubric, Haiku or Opus) |
| `session_feedback` | Thumbs up/down reactions linked to issues |
| `incident_knowledge` | Alert resolutions with vector embeddings (nomic-embed-text, 768 dims) |
| `lessons_learned` | Operational insights extracted from sessions |
| `openclaw_memory` | Episodic memory for Tier 1 triage outcomes |
| `a2a_task_log` | Inter-agent message lifecycle tracking |
| `crowdsec_scenario_stats` | CrowdSec learning loop state |
| `prompt_scorecard` | Daily prompt grading (19 surfaces x 6 dimensions) |
| `queue` | Session queue for slot management |

**Backup:** Daily at 02:00 UTC, 7-day retention, integrity checked ([`backup-gateway-db.sh`](scripts/backup-gateway-db.sh)).

### Prometheus Metrics (7 exporters, 23 cron jobs)

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

### Grafana Dashboards (5, 63+ panels)

- **ChatOps Platform Performance** — sessions, queue, locks, API status, costs, quality
- **Infrastructure Overview** — CPU/memory/disk per host, GPU metrics, service availability
- **Infra Alerts & Remediation** — alert rates, triage outcomes, MTTR trends
- **CubeOS Project** — pipeline success, MRs, issue states
- **MeshSat Project** — pipeline success, MRs, issue states

---

## 12. Evaluation System

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
| [Golden test suite](scripts/golden-test-suite.sh) | Biweekly + CI | 54 tests (syntax, schema, guardrails, security, metrics) |
| [Goldset validation](scripts/goldset-validate.sh) | On demand | 9 tests + 10 synthetic scenarios for APE readiness |
| [Regression detector](scripts/regression-detector.sh) | Every 6h | 7d rolling confidence/cost/duration comparison, CrowdSec checks |
| [Metamorphic monitor](scripts/metamorphic-monitor.sh) | Every 6h | Auto-variant promotion, cost-adaptive routing, self-healing rollback |
| A/B testing | Continuous | react_v1 vs react_v2, deterministic by issue hash |

---

## 13. Guardrails & Safety

6-layer defense-in-depth — not just prompt instructions:

| Layer | Mechanism | Level | Cannot be bypassed by |
|-------|-----------|-------|----------------------|
| **Claude Code hooks** | [`audit-bash.sh`](scripts/hooks/audit-bash.sh) blocks 30+ patterns + reverse shells. [`protect-files.sh`](scripts/hooks/protect-files.sh) blocks credential edits. | Deterministic | Anything — fires before permission check |
| **Exec enforcement** | [`safe-exec.sh`](openclaw/skills/safe-exec.sh): 30+ blocked patterns, rate limiting (30/min), exfiltration detection | Code | Prompt injection |
| **exec-approvals.json** | 36 specific skill patterns, no wildcards | Config | Prompt instruction |
| **Input sanitization** | 10 prompt injection patterns stripped from Matrix messages | Code | Direct bypass |
| **Credential scanning** | 10 regex patterns redact tokens/keys before Matrix posting | Code | N/A |
| **Approval gates** | Infrastructure changes require human thumbs-up or poll vote | Workflow | Agent autonomy |

Additional: AUTHORIZED_SENDERS filter, $5/session + $25/day budget ceiling, zero hardcoded passwords (all env vars), confidence gating (< 0.5 = STOP).

---

## 14. Inter-Agent Communication (NL-A2A/v1)

Standardized protocol for all tier-to-tier messages. Spec: [`docs/a2a-protocol.md`](docs/a2a-protocol.md).

- **Agent Cards** — machine-readable capability declarations per tier ([`a2a/agent-cards/`](a2a/agent-cards/))
- **Message Envelope** — protocol, messageId, timestamp, from/to, type, issueId, payload
- **REVIEW_JSON Auto-Action** — AGREE (auto-approve), DISAGREE (pause), AUGMENT (resume with context)
- **Task Lifecycle** — `a2a_task_log` tracks escalation -> in_progress -> completed

---

## 15. RAG Pipeline

| Component | Detail |
|-----------|--------|
| Embedding model | nomic-embed-text (768 dims, F16) on Ollama (RTX 3090 Ti) |
| Coverage | 25/25 entries (100%), backfill cron every 30min |
| Search | Cosine similarity (threshold 0.3) + keyword fallback |
| Triage integration | Step 1.5 in infra-triage, k8s-triage, security-triage |
| Dev integration | Query Knowledge runs semantic search for CUBEOS/MESHSAT |
| Knowledge source | `incident_knowledge` table (alert resolutions with embeddings) |
| Lessons source | `lessons_learned` table (30-day window, limit 5) |
| Health monitoring | `ollama_health` + `incident_knowledge_embedded` Prometheus metrics |

---

## 16. Operating Modes & Commands

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

## 17. Repository Structure

```
.
├── README.md                       # Concise overview (121 lines)
├── README.extensive.md             # This file — full technical reference
├── CLAUDE.md                       # Claude Code project instructions (<200 lines)
├── .claude/
│   ├── agents/                     # 10 sub-agents (Anthropic Academy patterns)
│   ├── skills/                     # 4 Claude Code skills
│   ├── commands/review.md          # /review command
│   ├── settings.json               # Hooks configuration
│   └── rules/                      # 6 path-scoped rule files
├── a2a/agent-cards/                # NL-A2A/v1 capability declarations
├── docs/
│   ├── architecture.md             # Component details (workflows, MCP, sub-agents)
│   ├── installation.md             # Setup guide with cron configuration
│   ├── agentic-patterns-audit.md   # 21/21 pattern scorecard
│   ├── book-gap-analysis.md        # Remaining improvements from Gulli's book
│   ├── a2a-protocol.md             # Inter-agent communication spec
│   └── known-failure-rules.md      # 27 rules from 26 bugs
├── grafana/                        # Dashboard JSON exports (5 dashboards)
├── openclaw/
│   ├── SOUL.md                     # OpenClaw system prompt (623 lines)
│   ├── openclaw.json               # OpenClaw configuration
│   ├── exec-approvals.json         # 36 skill patterns (no wildcards)
│   └── skills/                     # 14 native skills
├── scripts/
│   ├── hooks/                      # 2 Claude Code PreToolUse hooks
│   ├── grade-prompts.sh            # Daily prompt scorecard
│   ├── score-trajectory.sh         # JSONL trajectory scoring
│   ├── llm-judge.sh               # LLM-as-a-Judge (Haiku/Opus)
│   ├── golden-test-suite.sh        # 54-test benchmark
│   ├── regression-detector.sh      # 7d rolling regression
│   ├── metamorphic-monitor.sh      # Self-modification monitor
│   ├── post-reboot-vpn-check.sh    # 12 cross-site subnet probes
│   ├── backup-gateway-db.sh        # Daily SQLite backup
│   ├── kb-semantic-search.py       # Vector similarity search
│   └── ... (24 scripts total)
├── workflows/                      # 17 n8n workflow JSON exports
├── mcp-proxmox/                    # Custom Proxmox MCP server (15 tools)
└── .gitlab-ci.yml                  # CI: validate, test, review, GitHub sync
```

---

## 18. Installation

See [`docs/installation.md`](docs/installation.md) for full setup guide.

**Quick start:**
```bash
git clone https://github.com/papadopouloskyriakos/agentic-chatops.git
cd agentic-chatops
cp .env.example .env   # Add your credentials
```

---

## 19. References

- **[Agentic Design Patterns](https://drive.google.com/file/d/1-5ho2aSZ-z0FcW8W_jMUoFSQ5hTKvJ43/view?usp=drivesdk)** by Antonio Gulli (Springer, 2025) — 21 patterns, all implemented
- **[Anthropic Official Documentation](https://docs.anthropic.com/)** — Claude Code hooks, subagents, skills, MCP security, prompt engineering (17 sources audited)
- **[Anthropic Academy](https://academy.anthropic.com/)** — Sub-agent design: structured output, obstacle reporting, limited tools, decision rule
- **[Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)** — Start simple, add complexity when justified
- **[Writing Tools for Agents](https://www.anthropic.com/engineering/writing-tools-for-agents)** — Tool description best practices, poka-yoke
- **[MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)** — Scope minimization, token validation
- **[n8n](https://n8n.io/)** — Workflow automation engine (self-hosted)
- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Standardized LLM-tool integration

---

## License

Sanitized mirror of a private GitLab repository. Internal hostnames, IP addresses, credentials, and personal identifiers replaced with placeholders (128 replacement patterns + 20 post-scan grep patterns). Provided as-is for educational and reference purposes.

---

*Built by a solo infrastructure operator who got tired of waking up at 3am for alerts that an AI could triage.*
