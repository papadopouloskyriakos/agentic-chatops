# agentic-chatops

AI agents that triage infrastructure alerts, investigate root causes, and propose fixes — while a solo operator sleeps.

> **Looking for the complete technical reference?** See [README.extensive.md](README.extensive.md) — full architecture, all 21 agentic design patterns, component inventory, evaluation system, and security operations.

![Architecture](architecture.png)

## The Problem

One person. **310 infrastructure objects** across 6 sites. 3 firewalls, 12 Kubernetes nodes, self-hosted everything. When an alert fires at 3am, there's no team to call. There never is.

## The Solution

Three agentic subsystems that handle the detective work:

- **ChatOps** — Infrastructure alerts (LibreNMS, Prometheus) triaged automatically. Remediation plans proposed via interactive polls. Human clicks to approve.
- **ChatSecOps** — CrowdSec intrusion alerts and vulnerability scanner findings mapped to MITRE ATT&CK. 54 scenarios auto-classified.
- **ChatDevOps** — CI/CD failures diagnosed, code changes reviewed with fresh-eyes sub-agents, multi-repo refactoring coordinated.

All three share the same engine: [n8n](https://n8n.io/) orchestration, [Matrix](https://matrix.org/) as the human interface, and a 3-tier agent architecture:

```
Alert → n8n → OpenClaw (GPT-4o, fast triage) → Claude Code (Opus, deep analysis) → Human (approval)
```

The human stays in the loop for every infrastructure change. The system never acts without a thumbs-up or poll vote.

## How It Works

```
1. LibreNMS detects "Device down" on a host
2. n8n deduplicates, detects flapping, checks for correlated burst
3. OpenClaw (Tier 1) investigates in 7-21 seconds:
   - Queries NetBox CMDB for device identity
   - Searches incident knowledge base for similar past alerts
   - SSHes to the host, checks services and logs
   - Posts findings + confidence score to Matrix and YouTrack
4. If confidence < 0.7 or severity is critical → escalates to Claude Code
5. Claude Code (Tier 2) delegates research to specialized sub-agents,
   synthesizes findings, proposes 2-3 remediation plans via [POLL]
6. Operator clicks a poll option in Matrix
7. Claude executes the selected plan
8. Session archived → incident knowledge updated → lessons extracted
```

**Real example:** IFRNLLEI01PRD-82 — LibreNMS alert → OpenClaw triage (30s) → Claude investigation (8min) → [POLL] with 3 options → operator clicks Plan A → fix applied → recovery confirmed.

## Key Numbers

| Metric | Value |
|--------|-------|
| Agentic design patterns implemented | [21/21](docs/agentic-patterns-audit.md) (17 at A/A+) |
| n8n workflows | 17 (~400 nodes) |
| MCP tool integrations | 10 servers, 153 tools |
| Specialized sub-agents | 10 (Haiku for research, Opus for deep analysis) |
| Prompt surfaces evaluated | 19, graded daily on 6 dimensions |
| Golden tests | 54/54 passing |
| Avg session confidence | 0.88 |

## Architecture

| Component | Role |
|-----------|------|
| **[n8n](https://n8n.io/)** | Workflow orchestration — 17 workflows handle alert intake, session management, knowledge population |
| **[OpenClaw](https://openclaw.com/)** (GPT-4o) | Tier 1 — fast triage with 14 native skills (infra, K8s, security, correlated burst analysis) |
| **[Claude Code](https://docs.anthropic.com/)** (Opus 4.6) | Tier 2 — deep analysis with 10 sub-agents, ReAct reasoning, interactive polls |
| **Matrix** (Synapse) | Human-in-the-loop — polls, reactions, replies. The system waits here. |
| **YouTrack** | Issue tracking — webhook triggers, state management, knowledge sink |
| **NetBox** | CMDB — 310 devices, 421 IPs, 39 VLANs |
| **Prometheus + Grafana** | Metrics — 5 dashboards, 63+ panels, 7 metric exporters |
| **Ollama** (RTX 3090 Ti) | Local embeddings — nomic-embed-text for semantic incident search |

## Safety

The system can investigate freely but **never executes infrastructure changes without human approval**:

- **Claude Code hooks** block destructive commands before they run (30+ patterns)
- **safe-exec.sh** enforces a code-level blocklist that prompt injection cannot bypass
- **exec-approvals.json** restricts OpenClaw to 36 specific skill patterns (no wildcards)
- **Confidence gating** stops sessions below 0.5 and escalates below 0.7
- **Budget ceiling** triggers plan-only mode at $25/day
- **Credential scanning** redacts tokens before posting to Matrix

Every session is scored post-completion by an [LLM-as-a-Judge](https://arxiv.org/abs/2306.05685) (Haiku for routine, Opus for flagged sessions) on 5 quality dimensions.

## Documentation

| Document | What it covers |
|----------|---------------|
| [Architecture Details](docs/architecture.md) | Workflows, MCP servers, sub-agents, skills, hooks, inter-agent protocol |
| [Agentic Patterns Audit](docs/agentic-patterns-audit.md) | 21/21 pattern scorecard with implementation evidence |
| [Book Gap Analysis](docs/book-gap-analysis.md) | Remaining improvements from Gulli's book |
| [Installation Guide](docs/installation.md) | Prerequisites, setup steps, cron configuration |
| [A2A Protocol](docs/a2a-protocol.md) | Inter-agent communication specification |
| [Known Failure Rules](docs/known-failure-rules.md) | 27 rules from 26 bugs |

## Quick Start

```bash
git clone https://github.com/papadopouloskyriakos/agentic-chatops.git
cd agentic-chatops
cp .env.example .env   # Add your credentials
```

See the [Installation Guide](docs/installation.md) for full setup.

## References

- [Agentic Design Patterns](https://drive.google.com/file/d/1-5ho2aSZ-z0FcW8W_jMUoFSQ5hTKvJ43/view?usp=drivesdk) by Antonio Gulli (Springer, 2025) — 21 patterns, all implemented
- [Anthropic Official Documentation](https://docs.anthropic.com/) — hooks, sub-agents, skills, MCP security
- [Anthropic Academy](https://academy.anthropic.com/) — sub-agent design patterns
- [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) — start simple, add complexity when justified
- [n8n](https://n8n.io/) — workflow automation
- [Model Context Protocol](https://modelcontextprotocol.io/) — standardized LLM-tool integration

## License

Sanitized mirror of a private GitLab repository. Internal hostnames, IPs, and credentials replaced with placeholders. Provided as-is for educational and reference purposes.

---

*Built by a solo infrastructure operator who got tired of waking up at 3am for alerts that an AI could triage.*
