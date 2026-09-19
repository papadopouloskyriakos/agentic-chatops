# Oversight Boundary Framework -- claude-gateway Agentic Platform

**Document ID:** GOV-OBF-001
**Version:** 1.0
**Date:** 2026-04-15
**Next Review:** 2026-07-15
**Author:** Example Corp Network -- Infrastructure Team
**Classification:** Internal
**Reference:** NIST AI RMF 1.0, Agentic Profile AG-GV.2 (Oversight Boundaries)

---

## 1. Purpose

This document defines the oversight boundary framework for the claude-gateway agentic platform per NIST AI Risk Management Framework (AI RMF 1.0) guidance on agentic AI governance. It establishes:

- Autonomy tier classifications and their boundaries
- Authorized and prohibited actions per tier
- Escalation conditions and delegation authority
- Accountability lineage and audit trail requirements
- Review cadence and update procedures

The framework applies to all agents operating within the claude-gateway platform across both sites (NL: nl, GR: gr).

---

## 2. Autonomy Tier Classification

**Overall classification: Tier 2 (Constrained Autonomy) with Tier 3 monitoring.**

The system operates with constrained autonomy -- agents can execute pre-approved actions within defined boundaries without per-action human approval, but destructive, high-impact, or ambiguous actions require explicit human authorization. All actions are logged and subject to real-time monitoring by the human operator (Tier 3).

### 2.1 Tier Definitions

| Tier | Name | Actor | Autonomy Level |
|----|----|----|-----|
| Tier 1 | Investigation | OpenClaw / GPT-5.1 | Read-only with constrained execution. Can investigate, triage, and recommend. Cannot modify infrastructure state. |
| Tier 2 | Implementation | Claude Code | Read-write with guardrails. Can implement changes, execute SSH commands, invoke MCP tools. Bounded by hooks, cost ceilings, and approval gates. |
| Tier 3 | Authority | Human Operator | Unrestricted. Final decision authority over all agent actions. Can override, terminate, or reconfigure any agent at any time. |

---

## 3. Authorized Actions Per Tier

### 3.1 Tier 1 -- Investigation (OpenClaw / GPT-5.1)

**Host:** nl-openclaw01
**Model:** GPT-5.1
**Operating mode:** Self-contained triage and investigation with constrained command execution.

#### Authorized Actions

| Category | Permitted Actions |
|----|-----|
| Investigation | Query NetBox (devices, IPs, VLANs), query LibreNMS (alerts, device status), read incident_knowledge, search compiled wiki, query CodeGraph |
| Triage | Run 15 native triage skills (interface-triage, bgp-triage, storage-triage, etc.), cross-reference data trust hierarchy, generate CONFIDENCE-scored diagnosis |
| Cross-tier review | Execute `cross-tier-review` protocol to validate Tier 2 agent outputs, flag inconsistencies |
| Lookup | SSH read-only commands via 36 exec-approved patterns (e.g., `show run`, `ip a`, `pct config`, `kubectl get`, `cat /var/log/*`) |
| Communication | Post triage results to Matrix rooms, request Tier 2 delegation via `a2a_task_log` |

#### Constraints

| Constraint | Enforcement |
|----|-----|
| 36 exec-approved patterns | Allowlist in OpenClaw exec-approvals configuration. No wildcard patterns. Commands not matching an approved pattern are rejected. |
| 30 commands/minute rate limit | Enforced by OpenClaw runtime. Prevents command flooding. |
| No infrastructure modification | Write commands (restart, reload, delete, create, modify) are not in the approved pattern list and are rejected at the exec-approval layer. |
| No code deployment | Git push, deploy, release commands are not approved. |
| No data deletion | rm, truncate, drop, delete commands are not approved. |
| No credential access | Credential files, environment variables containing secrets, and key material are excluded from read patterns. |

#### Always-On Protocols

4 protocols run continuously at Tier 1:
1. **exec-safety** -- validates every command against the approved pattern list before execution
2. **error-propagation** -- ensures errors from sub-commands bubble up correctly to the triage output
3. **cross-tier-review** -- validates Tier 2 outputs when requested
4. **operational-kb** -- maintains operational context across triage sessions

### 3.2 Tier 2 -- Implementation (Claude Code)

**Host:** nl-claude01 (NL), grclaude01 (GR -- oversight role)
**Model:** Claude Opus / Sonnet (complexity-routed)
**Operating mode:** Implementation, refactoring, infrastructure automation within guardrailed boundaries.

#### Authorized Actions

| Category | Permitted Actions |
|----|-----|
| Code changes | Edit files, create branches, commit code, create MRs in gitlab.example.net |
| SSH execution | Run commands on managed hosts via SSH (subject to PreToolUse hook filtering) |
| MCP tool invocation | Invoke any of 153 tools across 10 MCP servers (NetBox, GitLab, YouTrack, Proxmox, n8n, CodeGraph, OpenTofu, tfmcp, Kubernetes, Ollama) |
| Workflow management | Create, update, test, and activate n8n workflows via n8n-mcp |
| Knowledge management | Write to incident_knowledge, session_transcripts, agent_diary, wiki_articles |
| Sub-agent delegation | Delegate tasks to 10 sub-agents (6 infra + 4 dev) with appropriate context |
| Chaos engineering | Execute pre-approved chaos scenarios with safety calculator validation |

#### Constraints

| Constraint | Enforcement |
|----|-----|
| PreToolUse hooks | 2 hooks block 81 destructive patterns. Patterns include: `git push --force`, `rm -rf /`, `kubectl delete namespace`, `terraform destroy`, `DROP TABLE`, production credential modification, firewall rule deletion. Hook exits silently on allow, blocks with plain text on deny. |
| Cost ceiling | $10/session warning threshold. $25/day hard limit (plan-only). Enforced by Runner workflow. Session terminated if ceiling exceeded. |
| Tool call limit | 75 tool calls per session. Prevents runaway loops. Enforced by Runner workflow. |
| Approval gates | Destructive or high-impact actions generate `[POLL]` blocks in Matrix. Agent pauses until operator responds. 15-minute reminder, 30-minute auto-pause. |
| K8s GitOps only | All Kubernetes changes exclusively via OpenTofu + Atlantis MR. Direct kubectl apply/delete/patch prohibited. |
| No OOB modification | Out-of-band management systems (iDRAC, PiKVM, UPS) cannot be modified without explicit operator approval. |
| No credential creation | Cannot create new SSH keys, API tokens, or service accounts. Can use existing credentials only. |
| Session isolation | Each session has a unique session_id. Sessions cannot access or modify other sessions' state. |

#### Prohibited Actions (Hard Blocks)

The following actions are blocked by PreToolUse hooks and cannot be performed under any circumstance without Tier 3 override:

- Force push to any repository
- Push to production branches without MR review
- Delete production databases or tables
- Modify firewall rules on ASA devices
- Restart critical network services (BGP, OSPF, IPsec) on production devices
- Clear BGP sessions on VPS nodes (drops real AS64512 upstream BGP)
- Add static routes (all routing is BGP-managed)
- Mass-delete operations based on pattern matching
- Modify syslog-ng central logging configuration
- Access or modify backup encryption keys

### 3.3 Tier 3 -- Authority (Human Operator)

**Interface:** Matrix chat rooms (#chatops, #cubeos, #meshsat, #infra-nl-prod, #infra-gr-prod, #alerts)
**Identity:** Solo operator (deployer = user = administrator)

#### Authorized Actions

| Category | Permitted Actions |
|----|-----|
| Session control | `!session done` (terminate), `!session pause` (pause), `!session list` (inspect active sessions). Immediate effect. |
| Mode control | `!mode <oc-cc|oc-oc|cc-cc|cc-oc>` switches operating mode. Controls which AI frontend/backend pair is active. |
| Approval/Rejection | Respond to `[POLL]` blocks with approval or rejection. Approval triggers agent to proceed; rejection triggers agent to abort and explain. |
| Policy override | Override any agent decision by direct instruction in Matrix. Agent must comply with explicit operator directives. |
| Emergency shutdown | Terminate any agent session immediately. Kill background processes. Revoke MCP credentials. |
| Maintenance mode | Create/remove `gateway.maintenance` file to suppress all automated processing during planned maintenance. |
| Agent deployment | Authorize deployment of new agents, skills, or MCP servers. Only Tier 3 can expand the system's capability envelope. |
| Credential management | Create, rotate, or revoke API tokens, SSH keys, and service accounts. |
| Infrastructure override | Execute any infrastructure command directly, bypassing all agent guardrails. |

#### Tier 3 Obligations

The human operator is responsible for:
- Reviewing agent outputs for correctness before approving high-impact actions
- Monitoring Matrix #alerts for serious incident notifications
- Conducting quarterly benchmark assessments
- Maintaining the oversight boundary framework (this document)
- Responding to approval requests within the defined SLA (15 minutes for Critical, 30 minutes for standard)

---

## 4. Escalation Conditions

An agent must escalate to the next tier when any of the following conditions are met:

### 4.1 Tier 1 to Tier 2 Escalation

| Condition | Trigger | Mechanism |
|----|----|----|
| Implementation required | Triage identifies a fix that requires code changes or infrastructure modification | `a2a_task_log` entry with task description and context |
| Investigation exceeds scope | Issue requires SSH commands not in the 36 approved patterns | Delegation request to Tier 2 with specific command needs |
| Multi-system correlation | Issue spans multiple devices/services requiring coordinated investigation beyond triage skill scope | `a2a_task_log` entry flagging cross-system nature |

### 4.2 Tier 2 to Tier 3 Escalation

| Condition | Trigger | Mechanism |
|----|----|----|
| Low confidence | Agent CONFIDENCE score < 0.6 on proposed action | `[POLL]` block in Matrix with confidence score and reasoning |
| Cost threshold | Session cost exceeds $5 (50% of $10 warning threshold) | Cost warning posted to Matrix, agent requests guidance |
| Destructive action detected | PreToolUse hook identifies action matching destructive pattern list | Hook blocks action, agent reports blocked action to Matrix and requests Tier 3 approval |
| Approval timeout | No operator response to `[POLL]` block within 30 minutes | Session auto-paused, notification sent to #alerts |
| Cross-tier disagreement | Tier 1 cross-tier-review flags inconsistency in Tier 2 output | Disagreement report posted to Matrix for Tier 3 adjudication |
| Scope ambiguity | Requested action is not clearly within or outside authorized boundaries | Agent asks for explicit permission before proceeding |
| Unfamiliar scenario | No relevant entries in incident_knowledge, wiki, or chaos baselines | Agent reports knowledge gap and requests human guidance |
| Safety calculator rejection | Chaos scenario fails preflight safety check | Scenario aborted, operator notified with safety calculator reasoning |

### 4.3 Emergency Escalation (Any Tier to Tier 3)

| Condition | Trigger | Mechanism |
|----|----|----|
| Service outage detected | Monitoring indicates unplanned outage correlated with agent action | Immediate Matrix #alerts notification. All agent sessions paused. |
| Cost anomaly | Spending rate exceeds 3x normal for session type | Cost alert to #alerts. Session paused pending review. |
| Security event | CrowdSec or vulnerability scanner triggers alert related to agent activity | Security alert workflow triggers. Agent sessions quarantined. |

---

## 5. Delegation Authority

### 5.1 Delegation Matrix

| From | To | Permitted | Mechanism | Audit |
|----|----|----|----|-----|
| Tier 1 | Tier 2 | Request implementation of identified fix | `a2a_task_log` entry with task, context, and triage findings | Logged with source_agent, target_agent, task_id |
| Tier 2 | Sub-agents (10) | Delegate scoped subtasks within session | Sub-agent invocation within Claude Code session | Tool calls logged in `tool_call_log` |
| Tier 2 | Tier 1 | Request additional triage or cross-tier review | `a2a_task_log` entry with review request | Logged with task_id and review_type |
| Tier 3 | Tier 1 or Tier 2 | Assign any task within tier capabilities | Matrix message or YouTrack issue creation | Session_id linked to issue_id |
| Any | New agent | NOT PERMITTED without Tier 3 | Only Tier 3 can authorize new agent deployment | -- |

### 5.2 Sub-Agent Roster

Tier 2 can delegate to the following sub-agents:

| Sub-Agent | Domain | Scope |
|----|----|----|
| infra-network | Network troubleshooting | BGP, VPN, firewall, routing |
| infra-storage | Storage analysis | ZFS, iSCSI, SeaweedFS, NFS |
| infra-compute | Compute management | Proxmox VMs/LXC, resource allocation |
| infra-monitoring | Monitoring analysis | LibreNMS, Prometheus, Grafana, Gatus |
| infra-security | Security investigation | CrowdSec, vulnerability scanning, ACL audit |
| infra-backup | Backup verification | PBS, Proxmox backup, replication |
| dev-frontend | Frontend development | Hugo, HTML/CSS/JS, portfolio website |
| dev-backend | Backend development | Python, Node.js, API development |
| dev-cicd | CI/CD pipeline | GitLab CI, deployment automation |
| dev-docs | Documentation | Technical writing, wiki compilation |

Sub-agents inherit the constraints of their parent Tier 2 session. They cannot exceed Tier 2 boundaries.

### 5.3 Delegation Constraints

- Sub-agents cannot delegate to other sub-agents (no delegation chains beyond depth 1)
- Tier 1 cannot delegate to Tier 1 (no lateral delegation at same tier)
- All delegation creates an audit trail in `a2a_task_log` with: timestamp, source_agent, target_agent, task_description, result, duration
- Delegated tasks inherit the cost ceiling of the parent session

---

## 6. Accountability Lineage

### 6.1 Traceability Chain

Every agent action is traceable through the following chain:

```
User command (Matrix message)
    |
    v
session_id (unique per conversation session)
    |
    v
issue_id (YouTrack issue that triggered the session, if applicable)
    |
    v
tool_call_log (every tool invocation: tool name, arguments, result, duration)
    |
    v
execution_log (workflow execution record: workflow_id, status, duration)
    |
    v
a2a_task_log (cross-tier delegation: source_agent, target_agent, task, result)
    |
    v
otel_spans (distributed tracing across workflow nodes)
    |
    v
session_transcripts (verbatim exchange-pair chunks for full context reconstruction)
    |
    v
JSONL session files (raw Claude Code output: every reasoning step, tool call, token count)
    |
    v
syslog-ng (terminal session logging: every SSH command executed on target hosts)
```

### 6.2 Audit Query Patterns

| Question | Data Source | Query Method |
|----|----|----|
| What did the agent do during session X? | `tool_call_log` | `SELECT * FROM tool_call_log WHERE session_id = 'X' ORDER BY timestamp` |
| What was the full conversation? | `session_transcripts` | `SELECT * FROM session_transcripts WHERE session_id = 'X' ORDER BY chunk_index` |
| Did the agent delegate to another tier? | `a2a_task_log` | `SELECT * FROM a2a_task_log WHERE session_id = 'X'` |
| What SSH commands were executed on a host? | syslog-ng | `grep 'terminal-session:' /mnt/logs/syslog-ng/<hostname>/<date>.log` |
| What was the quality score? | `session_log` | `SELECT quality_score, judge_scores FROM session_log WHERE session_id = 'X'` |
| How much did the session cost? | `llm_usage` | `SELECT SUM(cost) FROM llm_usage WHERE session_id = 'X'` |
| Was any action blocked by hooks? | JSONL session file | Search for hook deny events in `/tmp/claude-run-<ISSUE>.jsonl` |

### 6.3 Audit Retention Policy

| Data Source | Retention Period | Rationale |
|----|----|----|
| `session_log` | Indefinite | Core audit record. Lightweight (one row per session). |
| `session_transcripts` | Indefinite | Full conversation reconstruction capability. MemPalace pattern. |
| `tool_call_log` | 1 year | Detailed tool invocation audit. Volume managed by annual rotation. |
| `execution_log` | 1 year | Workflow execution records. Volume managed by annual rotation. |
| `a2a_task_log` | Indefinite | Cross-tier delegation audit. Low volume, high audit value. |
| `otel_spans` | 90 days | Distributed tracing. High volume, primarily for operational debugging. |
| `agent_diary` | Indefinite | Persistent agent memory. Low volume. |
| `incident_knowledge` | Indefinite (with `valid_until`) | Knowledge base with temporal validity. Expired entries retained but filtered from queries. |
| JSONL session files | 90 days | Raw session output. High volume. Archived after `poll-claude-usage.sh` extraction. |
| syslog-ng terminal logs | Per syslog rotation policy | Host-level command audit. Managed by syslog-ng retention configuration. |

---

## 7. Boundary Violation Response

### 7.1 Automated Response

| Violation Type | Automated Response | Notification |
|----|----|----|
| PreToolUse hook block | Action prevented. Agent receives denial message. Agent must choose alternative approach or escalate. | Logged in JSONL. Visible in session transcript. |
| Cost ceiling exceeded | Session terminated. No further tool calls permitted. | Matrix #alerts notification with session cost breakdown. |
| Tool call limit reached | Session terminated. Agent instructed to summarize findings and request new session if needed. | Matrix notification to operator. |
| Rate limit exceeded (Tier 1) | Command rejected. Agent must wait before retrying. | Logged in OpenClaw execution log. |
| Approval timeout (30 min) | Session auto-paused. All pending actions suspended. | Matrix #alerts notification. Session can be resumed by operator. |

### 7.2 Manual Response Procedures

For boundary violations not caught by automated controls:

1. **Operator detects violation** via Matrix monitoring or alert notification
2. **Immediate containment:** `!session done` to terminate the offending session
3. **Assessment:** Review `tool_call_log` and `session_transcripts` to determine scope of violation
4. **Remediation:** Undo any unauthorized changes (infrastructure rollback, git revert, etc.)
5. **Root cause analysis:** Determine whether the violation was due to prompt injection, guardrail gap, or model behavior change
6. **Corrective action:** Update hooks, prompts, or oversight boundaries to prevent recurrence
7. **Documentation:** Serious incident report per QMS Section 5 (GOV-QMS-001)

---

## 8. Framework Governance

### 8.1 Review Cadence

| Review Type | Frequency | Trigger |
|----|----|----|
| Scheduled review | Quarterly (aligned with benchmark assessment) | Calendar (next: 2026-07-15) |
| Post-incident review | After any serious incident | Incident occurrence |
| Capability change review | When adding new agents, tools, or MCP servers | Capability expansion |
| Model change review | When updating or replacing AI models | Model version change |
| Regulatory update review | When NIST AI RMF or EU AI Act guidance is updated | Regulatory publication |

### 8.2 Change Authority

| Change Type | Authority | Process |
|----|----|----|
| Add new authorized action to existing tier | Tier 3 (operator) | Update this document, commit to Git, validate with holistic health check |
| Add new prohibited action | Tier 3 (operator) | Update PreToolUse hooks + this document, validate hook enforcement |
| Modify escalation conditions | Tier 3 (operator) | Update this document + workflow configuration, test escalation paths |
| Change tier classification of existing agent | Tier 3 (operator) | Update this document, reconfigure agent permissions, full regression test |
| Deploy new agent | Tier 3 (operator) | Capability assessment, tier assignment, hook configuration, update this document |
| Modify retention policy | Tier 3 (operator) | Update this document, implement technical changes, verify audit completeness |

### 8.3 NIST AI RMF Mapping

This framework addresses the following NIST AI RMF functions and categories:

| Function | Category | This Framework |
|----|----|----|
| GOVERN | GV-1 (Policies) | Tier definitions, authorized/prohibited actions, escalation rules |
| GOVERN | GV-2 (Accountability) | Accountability lineage, audit retention, traceability chain |
| GOVERN | GV-3 (Workforce) | Single operator model, Tier 3 obligations |
| MAP | MP-3 (Benefits/Costs) | Cost ceilings, token tracking, budget adherence |
| MEASURE | MS-1 (Metrics) | Quality objectives (QMS), health checks, regression detection |
| MEASURE | MS-2 (Monitoring) | Real-time monitoring, progress poller, dead-man watchdog |
| MANAGE | MG-1 (Risk response) | Escalation conditions, boundary violation response |
| MANAGE | MG-2 (Risk tolerance) | Autonomy tier boundaries, approval gates, hard blocks |
| MANAGE | MG-3 (Incident response) | Serious incident definition (QMS), response SLAs, corrective actions |

---

## 9. Version History

| Version | Date | Changes |
|----|----|----|
| 1.0 | 2026-04-15 | Initial oversight boundary framework |
