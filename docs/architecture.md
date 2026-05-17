# Architecture Details

## Three Subsystems

| Subsystem | Scope | Matrix Rooms | Alert Sources | Triage Scripts |
|-----------|-------|-------------|---------------|----------------|
| **ChatOps** | Infrastructure availability, performance, maintenance | `#infra-nl-prod`, `#infra-gr-prod` | LibreNMS, Prometheus, Synology DSM | infra-triage, k8s-triage, correlated-triage |
| **ChatSecOps** | Security: intrusion detection, vulnerability scanning, MITRE ATT&CK | Same as ChatOps (shared rooms) | CrowdSec, vulnerability scanners | security-triage, baseline-add |
| **ChatDevOps** | Software development: CI/CD, features, bugs | `#cubeos`, `#meshsat` | GitLab CI (failure receiver) | Code analysis via Claude Code |

## n8n Workflows (17, ~400 nodes)

| Workflow | Nodes | Purpose |
|----------|-------|---------|
| **YouTrack Receiver** | 5 | Webhook listener, fires Runner async |
| **Claude Runner** | 44 | Lock/cooldown -> RAG -> Build Prompt -> Launch Claude -> Parse -> Validate -> Post |
| **Progress Poller** | 10 | Polls JSONL log every 30s, posts tool activity to Matrix |
| **Matrix Bridge** | 73 | Polls /sync, routes commands, manages sessions, handles reactions/polls |
| **Session End** | 12 | Summarize -> archive -> populate KB -> trajectory score -> LLM judge -> YT comment |
| **LibreNMS Receiver (NL)** | 26 | Alert dedup, flap detection, burst detection, recovery tracking |
| **LibreNMS Receiver (GR)** | 26 | Clone of NL for second site |
| **Prometheus Receiver (NL)** | 26 | K8s alert processing, fingerprint dedup, escalation cooldown |
| **Prometheus Receiver (GR)** | 26 | Clone of NL for second site |
| **Security Receiver (NL)** | 25 | Vulnerability scanner findings, baseline comparison |
| **Security Receiver (GR)** | 25 | Clone of NL for second site |
| **CrowdSec Receiver (NL)** | 22 | CrowdSec alerts, MITRE mapping, auto-suppression learning |
| **CrowdSec Receiver (GR)** | 22 | Clone of NL for second site |
| **Synology DSM Receiver** | 7 | I/O latency, SMART, iSCSI errors (beyond SNMP) |
| **WAL Self-Healer (GR)** | 18 | Auto-restart Prometheus on WAL corruption |
| **CI Failure Receiver** | 9 | GitLab pipeline webhook -> Matrix notification + YT comment |
| **Doorbell** | 6 | UniFi Protect -> Mattermost+Matrix+HA+Frigate fan-out |

## MCP Servers (10, 153 tools)

| MCP | Tools | Purpose |
|-----|-------|---------|
| `netbox` | ~20 | CMDB: 310 devices/VMs, 421 IPs, 39 VLANs across 6 sites |
| `n8n-mcp` | 21 | Build, update, test n8n workflows programmatically |
| `youtrack` | 47 | Issue management, custom fields, state transitions |
| `proxmox` | 15 | VM/LXC lifecycle, node status, storage (custom MCP) |
| `kubernetes` | 19 | kubectl operations, helm, port-forward, node management |
| `gitlab-mcp` | -- | MRs, pipelines, commits |
| `codegraph` | 12 | Code graph database (KuzuDB), call chain analysis, dead code |
| `opentofu` | 4 | Registry provider/resource/module docs |
| `tfmcp` | 29 | Terraform module analysis, state, plan, security |

## Sub-Agents (10)

Designed with [Anthropic Academy](https://academy.anthropic.com/) patterns: structured output, obstacle reporting, limited tool access, specific descriptions that shape input prompts.

### Infrastructure (6)

| Agent | Model | Purpose | MCP Access |
|-------|-------|---------|------------|
| **triage-researcher** | Haiku | Fast device lookup, incident history, 03_Lab reference | NetBox + K8s |
| **k8s-diagnostician** | Haiku | Pod/node/event diagnostics, Cilium, PVC checks | K8s + NetBox |
| **cisco-asa-specialist** | Haiku | ASA firewall diagnostics, VPN tunnels, ACL analysis | None (legacy SSH) |
| **storage-specialist** | Haiku | iSCSI, ZFS, NFS, SeaweedFS diagnostics | Proxmox + NetBox |
| **security-analyst** | Opus | Deep CVE/MITRE/CTI analysis, evidence collection | NetBox + K8s + WebSearch |
| **workflow-validator** | Haiku | n8n workflow JSON validation, known issue detection | n8n-mcp |

### Development (4)

| Agent | Model | Purpose | MCP Access |
|-------|-------|---------|------------|
| **code-explorer** | Haiku | Codebase research, call chain tracing, file mapping | CodeGraph |
| **code-reviewer** | Haiku | Fresh-eyes code review (separate context, no bias) | None |
| **ci-debugger** | Haiku | CI pipeline failure diagnosis, log parsing | None |
| **dependency-analyst** | Haiku | Cross-repo impact analysis for refactoring | CodeGraph |

**Anti-patterns avoided** (per Anthropic Academy): no "expert" personas, no sequential pipelines, no test runners as sub-agents.

## Claude Code Skills (4 + 1 command)

| Skill | Delegation | Purpose |
|-------|------------|---------|
| `/triage <host> <rule> <sev>` | Forks to triage-researcher | Full infra triage with structured output |
| `/alert-status` | Inline | Show active alerts across NL+GR (6 sources) |
| `/cost-report [days]` | Inline | Session cost/confidence analysis from SQLite |
| `/drift-check [nl\|gr\|all]` | Forks to triage-researcher | IaC vs live infrastructure drift detection |
| `/review` | Inline (legacy) | Merge request review |

## Claude Code Hooks (2 PreToolUse)

| Hook | Matcher | Purpose |
|------|---------|---------|
| `audit-bash.sh` | Bash | Logs all commands + blocks 30+ destructive patterns + reverse shells |
| `protect-files.sh` | Edit\|Write | Blocks edits to .env, *.key, *.pem, credentials, passwords |

## OpenClaw Skills (14)

| Skill | Purpose |
|-------|---------|
| `infra-triage` | L1+L2 infra alert triage (YT dedup -> investigate -> escalate) |
| `k8s-triage` | Kubernetes alert triage (control plane deep investigation) |
| `correlated-triage` | Multi-host burst analysis (master + child issues) |
| `security-triage` | Vulnerability triage with MITRE ATT&CK mapping (54 scenarios) |
| `escalate-to-claude` | Tier 2 escalation via n8n webhook |
| `youtrack-lookup` | Issue CRUD operations |
| `netbox-lookup` | CMDB device/VM/IP/VLAN lookup |
| `playbook-lookup` | Query incident knowledge base for past resolutions |
| `memory-recall` | Episodic memory: past triage outcomes by host/alert |
| `codegraph-lookup` | Code relationship analysis |
| `lab-lookup` | 03_Lab reference library queries |
| `baseline-add` | Security baseline management (90d expiry) |
| `proactive-scan` | Daily health + security discovery checks |
| `safe-exec.sh` | Exec enforcement wrapper (30+ blocked patterns) |

## Inter-Agent Communication (NL-A2A/v1)

See [`a2a-protocol.md`](a2a-protocol.md).

- **Agent Cards** — machine-readable capability declarations per tier
- **Message Envelope** — standard wrapper with protocol, messageId, from/to, type, payload
- **REVIEW_JSON Auto-Action** — AGREE->auto-approve, DISAGREE->pause, AUGMENT->resume with context
- **Task Lifecycle** — `a2a_task_log` table tracks escalation->in_progress->completed

## Operating Modes

| Mode | Frontend | Backend | Use Case |
|------|----------|---------|----------|
| `oc-cc` | OpenClaw | Claude Code | **Default** — full 3-tier pipeline |
| `oc-oc` | OpenClaw | OpenClaw (self-contained) | Quick lookups |
| `cc-cc` | n8n/Claude | Claude Code | Direct Claude access (legacy) |
| `cc-oc` | n8n | OpenClaw as backend | Testing |

Switch with `!mode <mode>` in any Matrix room.

## Matrix Commands

| Command | Description |
|---------|-------------|
| `!session current/list/done/cancel/pause/resume` | Session management |
| `!issue status/info/start/stop/verify/done/close` | Issue lifecycle |
| `!pipeline status/logs/retry` | GitLab CI pipelines |
| `!mode status/oc-cc/oc-oc/cc-cc/cc-oc` | Operating mode switching |
| `!system status/processes` | System health |
| `!gateway offline/online/status` | Gateway control |
| `!debug` | Dump lock, sessions, queue, cooldown state |

## SQLite Tables (14)

| Table | Purpose |
|-------|---------|
| `sessions` | Active sessions |
| `session_log` | Archived sessions with cost/duration/confidence/resolution |
| `session_quality` | 5-dimension quality scores |
| `session_feedback` | Thumbs up/down reactions |
| `session_trajectory` | Per-session agent trajectory scores |
| `session_judgment` | LLM-as-a-Judge results |
| `incident_knowledge` | Alert resolutions with vector embeddings |
| `lessons_learned` | Operational insights |
| `openclaw_memory` | Tier 1 episodic memory |
| `a2a_task_log` | Inter-agent message lifecycle |
| `crowdsec_scenario_stats` | CrowdSec learning loop |
| `prompt_scorecard` | Daily prompt grading (19 surfaces x 6 dimensions) |
| `queue` | Session queue |

## Repository Structure

```
.
├── CLAUDE.md                       # Technical reference (<200 lines)
├── .claude/
│   ├── agents/                     # 10 sub-agents (Anthropic Academy patterns)
│   ├── skills/                     # 4 Claude Code skills
│   ├── commands/review.md          # /review command
│   ├── settings.json               # Hooks configuration
│   └── rules/                      # 6 path-scoped rule files
├── a2a/agent-cards/                # NL-A2A/v1 capability declarations
├── docs/                           # Architecture, audit, protocol docs
├── grafana/                        # Dashboard JSON exports (5 dashboards)
├── openclaw/
│   ├── SOUL.md                     # OpenClaw system prompt
│   ├── openclaw.json               # OpenClaw configuration
│   ├── exec-approvals.json         # 36 skill patterns (no wildcards)
│   └── skills/                     # 14 native skills
├── scripts/                        # 24 automation scripts + 2 hooks
├── workflows/                      # 17 n8n workflow JSON exports
├── mcp-proxmox/                    # Custom Proxmox MCP server (15 tools)
└── .gitlab-ci.yml                  # CI: validate, test, review, GitHub sync
```
