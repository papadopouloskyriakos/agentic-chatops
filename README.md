# agentic-chatops

**Production agentic ChatOps platform implementing all 21 design patterns from [Agentic Design Patterns](https://drive.google.com/file/d/1-5ho2aSZ-z0FcW8W_jMUoFSQ5hTKvJ43/view?usp=drivesdk) by Antonio Gulli — cross-referenced against the [Claude Certified Architect Exam Guide](docs/Claude+Certified+Architect+–+Foundations+Certification+Exam+Guide.pdf) — running on a self-hosted homelab managed by a single operator.**

![Architecture](architecture.png)

---

## Why This Exists

Managing **310 infrastructure objects** — 113 physical devices, 197 virtual machines, 421 IP addresses, 39 VLANs, 653 interfaces across **6 sites** (Netherlands, Greece x2, Switzerland, Norway) and **3 Proxmox clusters** — as a **solo operator** is unsustainable without automation.

That's 3 firewalls, 3 managed switches, 12 Kubernetes nodes with Cilium ClusterMesh, self-hosted everything (Matrix, GitLab, YouTrack, n8n, LibreNMS, Grafana, Nextcloud HA, SeaweedFS, Thanos), and no team to delegate to. When an alert fires at 3am, there's one person on call. Always.

This platform bridges the gap: infrastructure alerts flow in, AI agents triage and investigate, propose remediation plans, and wait for human approval before executing. The human stays in the loop for critical decisions but doesn't have to do the detective work.

### The 3-Tier Architecture

```
LibreNMS/Prometheus Alert
         │
         ▼
   ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
   │  n8n         │────▶│  OpenClaw     │────▶│  Claude Code  │
   │  Orchestrator│     │  (Tier 1)    │     │  (Tier 2)     │
   │  11 workflows│     │  GPT-4o      │     │  Claude Opus  │
   │  ~354 nodes  │     │  L1/L2 triage│     │  Deep analysis│
   └──────┬───────┘     └──────────────┘     └───────┬───────┘
          │                                          │
          ▼                                          ▼
   ┌─────────────┐                            ┌──────────────┐
   │  Matrix      │◀───────────────────────────│  Human (T3)  │
   │  Chat rooms  │  polls, reactions, replies │  Approval    │
   └─────────────┘                            └──────────────┘
```

- **Tier 1 (OpenClaw / GPT-4o):** Fast triage (7-21s). Creates YouTrack issues, deduplicates alerts, investigates via SSH/kubectl, outputs confidence scores. Handles 80%+ of alerts without escalation.
- **Tier 2 (Claude Code / Opus):** Deep analysis (5-15 min). Reads Tier 1 findings, verifies independently using ReAct reasoning, proposes remediation plans via interactive polls, executes after human approval.
- **Tier 3 (Human):** Clicks a poll option in Matrix, reacts with thumbs up/down, or types a reply. The system stops and waits for this — it never makes infrastructure changes autonomously.

---

## Agentic Design Patterns — 21/21 Implemented

After reading Antonio Gulli's *Agentic Design Patterns* (Springer, 2025), we benchmarked this platform against all 21 patterns and upgraded each to A-grade or above. Full audit: [`docs/agentic-patterns-audit.md`](docs/agentic-patterns-audit.md).

| # | Pattern | Implementation | Grade |
|---|---------|---------------|-------|
| 1 | **Prompt Chaining** | n8n 44-node sequential workflow (Runner) | A |
| 2 | **Routing** | Issue prefix → room → slot, alert category detection (8 types) | A- |
| 3 | **Parallelization** | 3 concurrent session slots (dev, infra-nl, infra-gr) | A- |
| 4 | **Reflection** | Cross-tier review: OpenClaw critiques Claude with 5-step chain-of-verification | A- |
| 5 | **Tool Use** | 9 MCP servers, 150+ tools (NetBox, Proxmox, K8s, YouTrack, GitLab, n8n) | A |
| 6 | **Planning** | Interactive [POLL] plan selection via MSC3381 Matrix polls + plan-only mode | A- |
| 7 | **Multi-Agent** | 3-tier production system (GPT-4o → Claude Opus → Human) | A |
| 8 | **Memory** | 4 types: short-term (SQLite sessions), long-term (incident KB), episodic (OpenClaw memory), procedural (SOUL.md/CLAUDE.md) | A- |
| 9 | **Learning & Adaptation** | A/B prompt testing, outcome scoring, lessons-to-prompt pipeline, regression detection | A |
| 10 | **MCP** | 9 servers including custom Proxmox MCP (15 tools), mcporter Docker bridge | A |
| 11 | **Goal Setting** | Confidence gating (< 0.5 = STOP), budget enforcement ($5/session, $25/day) | A- |
| 12 | **Exception Handling** | 5-layer watchdog, ERROR_CONTEXT structured propagation, fallback ladders | A |
| 13 | **Human-in-the-Loop** | MSC3381 polls, thumbs up/down reactions, 15min/30min approval timeouts | A |
| 14 | **RAG** | Vector embeddings (nomic-embed-text via Ollama) + keyword fallback, 3-tier injection | A- |
| 15 | **A2A Communication** | NL-A2A/v1 protocol, agent cards, REVIEW_JSON auto-action, task lifecycle logging | A |
| 16 | **Resource Optimization** | Cost prediction per alert category, dynamic timeout (300-600s), per-type metrics | A |
| 17 | **Reasoning** | ReAct (THOUGHT/ACTION/OBSERVATION), step-back prompting, tree-of-thought, self-consistency check, A/B variants | A |
| 18 | **Guardrails** | Code-level exec enforcement (safe-exec.sh), input sanitization (10 injection patterns), output fact-checking, credential scanning | A |
| 19 | **Evaluation** | Multi-dimensional quality scoring (5 dimensions, 0-100), SLA metrics, CI golden tests, confidence calibration | A |
| 20 | **Prioritization** | Slot-based, burst detection (3+ hosts = correlated triage), flap escalation | A- |
| 21 | **Exploration** | Daily proactive health scan (disk, certs, stale issues, VPN) | A- |

Book gap analysis for remaining polish items: [`docs/book-gap-analysis.md`](docs/book-gap-analysis.md)

---

## How It Works

### Alert Lifecycle (End-to-End)

```
1. LibreNMS detects "Devices up/down" on host X
2. n8n LibreNMS Receiver → dedup, flap detection, burst detection
3. Posts to Matrix #infra room: "[LibreNMS] ALERT: host X — Devices up/down (critical)"
4. OpenClaw (Tier 1) auto-triages:
   a. Checks YouTrack for existing issues (24h dedup)
   b. Creates issue IFRNLLEI01PRD-XXX
   c. Queries NetBox CMDB for device identity
   d. Queries incident knowledge base (semantic search)
   e. Investigates via SSH (PVE status, container logs, etc.)
   f. Posts findings + CONFIDENCE score to YouTrack + Matrix
   g. If confidence < 0.7 or critical: escalates to Claude Code
5. Claude Code (Tier 2) activates:
   a. Reads YouTrack issue + Tier 1 comments
   b. Uses ReAct reasoning: THOUGHT → ACTION → OBSERVATION loop
   c. Checks if recurring alert → step-back analysis
   d. Proposes 2-3 remediation plans via [POLL]
6. Matrix renders interactive poll — operator clicks preferred plan
7. Claude Code executes selected plan
8. Reports results, moves issue to "To Verify"
9. Session End: archives to session_log, populates incident KB,
   computes quality score, extracts lessons learned
```

### Real Incident Example

**IFRNLLEI01PRD-82** — Full L1→L2→L3→approval→fix→recovery cycle:
- LibreNMS alert → n8n → Matrix → OpenClaw triage (30s) → Claude Code investigation (8min) → [POLL] with 3 options → operator clicks Plan A → fix applied → recovery confirmed → YT closed

### Operating Modes

| Mode | Frontend | Backend | Use Case |
|------|----------|---------|----------|
| `oc-cc` | OpenClaw | Claude Code | **Default** — full 3-tier pipeline |
| `oc-oc` | OpenClaw | OpenClaw (self-contained) | Quick lookups, no Claude needed |
| `cc-cc` | n8n/Claude | Claude Code | Direct Claude access (legacy) |
| `cc-oc` | n8n | OpenClaw as backend | Testing OpenClaw capabilities |

Switch with `!mode <mode>` in any Matrix room.

---

## Architecture Components

### n8n Workflows (11 workflows, ~354 nodes)

| Workflow | Nodes | Purpose |
|----------|-------|---------|
| **YouTrack Receiver** | 5 | Webhook listener, fires Runner async |
| **Claude Runner** | 44 | Lock/cooldown → RAG → Build Prompt → Launch Claude → Parse → Validate → Post |
| **Progress Poller** | 10 | Polls JSONL log every 30s, posts tool activity to Matrix |
| **Matrix Bridge** | 73 | Polls /sync, routes commands, manages sessions, handles reactions/polls |
| **Session End** | 12 | Summarize → archive → populate KB → quality score → YT comment |
| **LibreNMS Receiver (NL)** | 26 | Alert dedup, flap detection, burst detection, recovery tracking |
| **LibreNMS Receiver (GR)** | 26 | Clone of NL for second site |
| **Prometheus Receiver (NL)** | 26 | K8s alert processing, fingerprint dedup |
| **Prometheus Receiver (GR)** | 26 | Clone of NL for second site |
| **Synology DSM Receiver** | 7 | I/O latency, SMART, iSCSI errors (beyond SNMP) |
| **WAL Self-Healer (GR)** | 16 | Auto-restart Prometheus on WAL corruption (6h cooldown, recovery verify) |

### MCP Servers (9)

| MCP | Tools | Purpose |
|-----|-------|---------|
| `netbox` | ~20 | CMDB: 310 devices/VMs, 421 IPs, 39 VLANs across 6 sites |
| `n8n-mcp` | 20 | Build, update, test n8n workflows programmatically |
| `youtrack` | 55 | Issue management, custom fields, state transitions |
| `proxmox` | 15 | VM/LXC lifecycle, node status, storage (custom MCP) |
| `kubernetes` | 21 | kubectl operations via MCP |
| `gitlab-mcp` | — | MRs, pipelines, commits |
| `codegraph` | ~15 | Code graph database (KuzuDB), call chain analysis |
| `opentofu` | — | Registry provider/resource docs |
| `tfmcp` | — | Terraform module analysis |

### OpenClaw (v2026.3.23) — 10 native skills

| Skill | Purpose |
|-------|---------|
| `infra-triage` | L1+L2 infra alert triage (YT dedup → investigate → escalate) |
| `k8s-triage` | Kubernetes alert triage (control plane deep investigation) |
| `correlated-triage` | Multi-host burst analysis (master + child issues) |
| `escalate-to-claude` | Tier 2 escalation via n8n webhook |
| `youtrack-lookup` | Issue CRUD operations |
| `netbox-lookup` | CMDB device/VM/IP/VLAN lookup |
| `playbook-lookup` | Query incident knowledge base for past resolutions |
| `memory-recall` | Episodic memory: past triage outcomes by host/alert |
| `proactive-scan` | Daily health checks (disk, certs, stale issues, VPN) |
| `safe-exec.sh` | Exec enforcement wrapper (30+ blocked patterns, rate limiting, exfiltration detection) |

### Inter-Agent Communication (NL-A2A/v1)

Standardized protocol for all tier-to-tier messages. See [`docs/a2a-protocol.md`](docs/a2a-protocol.md).

- **Agent Cards** — machine-readable capability declarations per tier ([`a2a/agent-cards/`](a2a/agent-cards/))
- **Message Envelope** — standard wrapper with protocol, messageId, from/to, type, payload
- **REVIEW_JSON Auto-Action** — Bridge parses OpenClaw reviews: AGREE→auto-approve, DISAGREE→pause, AUGMENT→resume with context
- **Task Lifecycle** — `a2a_task_log` table tracks escalation→in_progress→completed

---

## Data & Intelligence

### SQLite Tables

| Table | Purpose |
|-------|---------|
| `sessions` | Active sessions (issue_id, session_id, cost, confidence) |
| `session_log` | Archived sessions with cost/duration/confidence/resolution/variant/category |
| `session_quality` | 5-dimension quality scores (confidence, cost efficiency, completeness, feedback, speed) |
| `session_feedback` | Thumbs up/down reactions linked to issues |
| `incident_knowledge` | Alert resolutions with vector embeddings (nomic-embed-text, 768 dims) |
| `lessons_learned` | Operational insights extracted from sessions |
| `openclaw_memory` | Episodic memory for Tier 1 triage outcomes |
| `a2a_task_log` | Inter-agent message lifecycle tracking |

### Prometheus Metrics

| Metric | What it tracks |
|--------|---------------|
| Session cost/duration/confidence/turns | Per-project, rolling 7d/30d |
| Quality score (5 dimensions) | Rolling 7d averages, composite score |
| SLA: MTTR avg/p90 | Per-project, per-category |
| Confidence calibration | Predicted vs actual success rate per band |
| Cost per alert category | 8 categories, avg cost + duration |
| A/B variant comparison | Per-variant confidence, cost, session count |
| Feedback (thumbs up/down) | Total + 7d rolling |
| A2A messages | By type (escalation/review/completion) |
| Exec guardrail | Blocked vs allowed commands |
| Golden test results | Pass/fail counts, last run timestamp |

### Grafana Dashboards (5 dashboards, 63+ panels)

- **ChatOps Platform Performance** — sessions, queue, locks, API status, costs, quality, knowledge
- **Infrastructure Overview** — CPU/memory/disk per host, GPU metrics, service availability
- **Infra Alerts & Remediation** — alert rates, triage outcomes, MTTR trends
- **CubeOS Project** / **MeshSat Project** — pipeline success, MRs, issue states

---

## Guardrails & Safety

Defense-in-depth — not just prompt instructions, but code-level enforcement:

| Layer | Mechanism | Level |
|-------|-----------|-------|
| **Exec enforcement** | `safe-exec.sh` — 30+ blocked patterns, rate limiting (30/min), exfiltration detection | Code |
| **Input sanitization** | 10 prompt injection patterns stripped from Matrix messages | Code |
| **Credential scanning** | 10 regex patterns redact tokens/keys before posting to Matrix | Code |
| **Output fact-checking** | Hostname validation, TRIAGE_JSON/REVIEW_JSON schema validation | Code |
| **Self-consistency** | Detects confidence/reasoning mismatches, triggers retry | Code |
| **Exec blocklist** | 15+ forbidden commands in SOUL.md | Prompt |
| **AUTHORIZED_SENDERS** | Only designated operator can interact | Code |
| **Approval gates** | Infrastructure changes require human thumbs-up or poll vote | Workflow |
| **Budget ceiling** | $5/session warning, $25/day → plan-only mode | Code |

---

## Installation

### Prerequisites

- **n8n** (v2.11+) — workflow automation
- **Matrix** (Synapse) — chat server with bot account
- **YouTrack** — issue tracking with webhook support
- **Claude Code** — Anthropic CLI (`~/.local/bin/claude`)
- **OpenClaw** — GPT-4o agent (Docker-based)
- **SQLite3** — session/knowledge storage
- **Python 3.11+** — semantic search script
- **Ollama** (optional) — local embedding model for RAG

### Setup Steps

1. **Clone and configure:**
```bash
git clone https://github.com/papadopouloskyriakos/agentic-chatops.git
cd agentic-chatops
cp .env.example .env  # Edit with your credentials
```

2. **Import n8n workflows:**
```bash
# Via n8n-mcp or manual import
for wf in workflows/*.json; do
  # Import each workflow into your n8n instance
  npx n8n-mcp import "$wf"
done
```

3. **Configure Matrix bot:**
   - Create a bot user on your Matrix server
   - Set Bearer token in n8n credentials
   - Join bot to your rooms

4. **Configure OpenClaw:**
   - Deploy `openclaw/openclaw.json` to your OpenClaw instance
   - Deploy `openclaw/SOUL.md` as system prompt
   - Deploy skills to `/workspace/skills/`

5. **Initialize SQLite:**
```bash
# Tables are auto-created by n8n workflows on first run
# Or manually:
sqlite3 gateway.db < schema.sql
```

6. **Set up crons:**
```bash
# Session + agent metrics (every 5 min)
*/5 * * * * /path/to/scripts/write-session-metrics.sh
*/5 * * * * /path/to/scripts/write-agent-metrics.sh
*/5 * * * * /path/to/scripts/write-sla-metrics.sh

# Watchdog (every 5 min)
*/5 * * * * /path/to/scripts/gateway-watchdog.sh

# Regression detection (every 6 hours)
0 */6 * * * /path/to/scripts/regression-detector.sh

# Weekly lessons digest (Monday 07:00 UTC)
0 7 * * 1 /path/to/scripts/weekly-lessons-digest.sh

# Golden test suite (1st of month 04:00 UTC)
0 4 1 * * /path/to/scripts/golden-test-suite.sh

# Proactive scan (daily 06:03 UTC)
3 6 * * * /path/to/scripts/trigger-proactive-scan.sh
```

7. **Configure alert sources:**
   - LibreNMS: create HTTP transport pointing to `https://your-n8n/webhook/librenms-alert`
   - Prometheus/Alertmanager: add webhook receiver pointing to `https://your-n8n/webhook/prometheus-alert`

---

## Repository Structure

```
.
├── CLAUDE.md                          # Full technical reference (600+ lines)
├── a2a/                               # NL-A2A/v1 inter-agent protocol
│   └── agent-cards/                   # Machine-readable capability declarations
│       ├── openclaw-t1.json           # Tier 1 capabilities + constraints
│       ├── claude-code-t2.json        # Tier 2 capabilities + reasoning config
│       └── human-t3.json              # Tier 3 approval policies
├── docs/
│   ├── a2a-protocol.md                # A2A protocol specification
│   ├── agentic-patterns-audit.md      # 21/21 pattern scorecard
│   ├── book-gap-analysis.md           # Remaining improvements from the book
│   ├── known-failure-rules.md         # 27 rules from 26 bugs
│   └── chatops-audit-2026-03-24.md   # Cross-reference audit (Gulli book + Anthropic exam guide)
├── grafana/                           # Dashboard JSON exports (5 dashboards)
├── openclaw/
│   ├── SOUL.md                        # OpenClaw system prompt (source of truth)
│   ├── openclaw.json                  # OpenClaw configuration
│   ├── escalate-to-claude.sh          # Tier 2 escalation script
│   └── skills/                        # 9 native skills (SKILL.md format)
│       ├── infra-triage/              # L1+L2 infrastructure triage
│       ├── k8s-triage/                # Kubernetes alert triage
│       ├── correlated-triage/         # Multi-host burst analysis
│       ├── safe-exec.sh               # Exec enforcement wrapper
│       └── ...
├── scripts/
│   ├── compute-quality-score.sh       # 5-dimension session quality scoring
│   ├── regression-detector.sh         # 7d rolling regression detection
│   ├── golden-test-suite.sh           # 42-test benchmark suite
│   ├── kb-semantic-search.py          # Vector similarity search (nomic-embed-text)
│   ├── gateway-watchdog.sh            # 5-layer health monitor
│   ├── maintenance-companion.sh       # Planned maintenance lifecycle
│   ├── write-session-metrics.sh       # Prometheus: cost, quality, calibration
│   ├── write-sla-metrics.sh           # Prometheus: MTTR, duration, trends
│   └── ...
├── workflows/                         # n8n workflow JSON exports (11 workflows)
│   ├── claude-gateway-runner.json     # Main orchestration (44 nodes)
│   ├── claude-gateway-matrix-bridge.json  # Matrix integration (73 nodes)
│   └── ...
├── mcp-proxmox/                       # Custom MCP server for Proxmox VE API
│   ├── index.js                       # 15 tools: discovery, config, lifecycle
│   └── package.json
└── .gitlab-ci.yml                     # CI: validate, test, review, GitHub sync
```

---

## Commands

Matrix bang commands (processed by n8n Bridge):

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

## Inspiration & References

- **[Agentic Design Patterns](https://drive.google.com/file/d/1-5ho2aSZ-z0FcW8W_jMUoFSQ5hTKvJ43/view?usp=drivesdk)** by Antonio Gulli (Springer, 2025) — 21 patterns, all implemented. Cross-reference audit: [`docs/chatops-audit-2026-03-24.md`](docs/chatops-audit-2026-03-24.md)
- **[Claude Certified Architect — Foundations Exam Guide](docs/Claude+Certified+Architect+–+Foundations+Certification+Exam+Guide.pdf)** — Exam domains map to this architecture: agentic orchestration, MCP integration, CLAUDE.md configuration, prompt engineering, context management. Full domain mapping in the audit report.
- **[n8n Workflow Template](https://n8n.io/workflows/13943-manage-claude-code-sessions-from-matrix-with-youtrack-and-gitlab/)** — Published on n8n creator portal: "Manage Claude Code sessions from Matrix with YouTrack and GitLab"
- **[n8n](https://n8n.io/)** — Workflow automation engine (self-hosted)
- **[Model Context Protocol](https://modelcontextprotocol.io/)** — Standardized LLM-tool integration

---

## License

This is a sanitized mirror of a private GitLab repository. Internal hostnames, IP addresses, credentials, and personal identifiers have been replaced with placeholders.

The code is provided as-is for educational and reference purposes. See individual components for their respective licenses.

---

*Built by a solo infrastructure operator who got tired of waking up at 3am for alerts that an AI could triage.*
