# EU AI Act Risk Assessment -- claude-gateway Agentic Platform

**Document ID:** GOV-EUAIA-001
**Version:** 1.0
**Date:** 2026-04-15
**Next Review:** 2026-07-15
**Author:** Example Corp Network -- Infrastructure Team
**Classification:** Internal

---

## 1. System Description

**System Name:** claude-gateway
**Operator/Deployer:** Example Corp Network (solo operator)
**Purpose:** Internal infrastructure management (ChatOps) and development automation (ChatDevOps) across 2 sites (NL, GR) managing 310 devices/VMs.
**Architecture:** 3-tier agentic AI platform -- 26 n8n workflows (~470 nodes), 10 MCP servers (153 tools), 10 sub-agents, 19 OpenClaw skills. Backed by Claude Code (Tier 2) and OpenClaw/GPT-5.1 (Tier 1) with human oversight (Tier 3) via Matrix chat.
**Users:** Single operator (deployer = user = provider for internal systems).
**Deployment:** On-premises, internal network only. No public-facing inference endpoints. No external users.

---

## 2. Risk Classification Under EU AI Act

### 2.1 Annex III High-Risk Assessment

The EU AI Act (Regulation 2024/1689) classifies AI systems as high-risk under Article 6(2) if they fall within the categories listed in Annex III. Each category is evaluated below.

| Annex III Category | Applicable | Rationale |
|----|----|----|
| 1. Biometrics | No | System does not process biometric data. No facial recognition, emotion detection, or biometric categorization. |
| 2. Critical infrastructure | No | System manages IT infrastructure (servers, VMs, network devices), not critical infrastructure as defined by the Act (energy, water, transport, digital infrastructure serving the public). Internal-only network management for a private organization. |
| 3. Education and vocational training | No | Not used for educational assessment, admission, or training evaluation. |
| 4. Employment, workers management | No | Not used for recruitment, hiring, task allocation to human workers, or performance monitoring of employees. |
| 5. Access to essential services | No | Not used for credit scoring, insurance, social benefits, or emergency services dispatch. |
| 6. Law enforcement | No | Not used for crime prediction, evidence evaluation, profiling, or polygraph assessment. |
| 7. Migration, asylum, border control | No | Not applicable. |
| 8. Administration of justice | No | Not used for legal research, case outcome prediction, or judicial decision support. |

### 2.2 Prohibited Practices (Article 5)

| Prohibited Practice | Applicable | Rationale |
|----|----|----|
| Subliminal manipulation | No | System interacts only with the operator who deploys it. No manipulation vector. |
| Exploitation of vulnerabilities | No | Single operator, no vulnerable groups involved. |
| Social scoring | No | No scoring of natural persons for social behavior. |
| Real-time remote biometric identification | No | No biometric processing of any kind. |

### 2.3 General-Purpose AI Model (GPAI) Considerations

claude-gateway uses third-party GPAI models (Anthropic Claude, OpenAI GPT-5.1) as components. Under Article 25, the obligations for GPAI model providers (Anthropic, OpenAI) are separate from the obligations of deployers. As a deployer of these models in a non-high-risk application, claude-gateway is not subject to GPAI-specific requirements beyond standard transparency obligations.

### 2.4 Risk Classification Conclusion

**Classification: Limited Risk (Article 6(2) not triggered)**

claude-gateway does not fall within any Annex III high-risk category. It is an internal infrastructure management tool operated by a single technical operator on a private network. No decisions affecting natural persons' rights, safety, or access to services are made by the system.

The system is subject to:
- Article 50 transparency obligations (addressed in Section 4.8)
- Voluntary adoption of high-risk controls as best practice (addressed in Section 3)

---

## 3. Control Mapping to EU AI Act Articles

Although classified as limited risk, claude-gateway voluntarily implements controls aligned with the high-risk requirements of Chapter III, Section 2. This mapping documents existing controls against each article.

### 3.1 Article 9 -- Risk Management System

**Requirement:** Establish, implement, document, and maintain a risk management system throughout the AI system lifecycle.

| Control | Implementation | Evidence |
|----|----|----|
| Continuous monitoring | `holistic-agentic-health.sh` -- 138 checks across 31 sections, run daily. Covers functional correctness, end-to-end integration, trending analysis, and infrastructure health. | Script at `scripts/holistic-agentic-health.sh`. Results in Matrix #alerts. |
| Regression detection | `regression-detector.sh` -- 6-hour rolling window analysis comparing current session quality against historical baselines. Alerts on statistically significant degradation. | Script at `scripts/regression-detector.sh`. Cron every 6h. |
| Predictive risk analysis | `predictive-alerts.py` -- trend-based alerting using session quality trajectories, cost anomalies, and infrastructure health indicators. | Script at `scripts/predictive-alerts.py`. |
| Cost ceiling enforcement | Hard limit of $10/session warning, $25/day plan-only ceiling. Cost tracked per-model in `llm_usage` table with 4 independent writers. | Enforced in Runner workflow. Budget in CLAUDE.md. |
| Chaos engineering | 18 baseline chaos experiments (15 PASS, 2 DEGRADED, 1 FAIL). Weekly automated chaos runs (daily 10:00 UTC, self-selecting). Safety calculator prevents unsafe concurrent kills. | `chaos_exercises` SQLite table. Scripts in `scripts/chaos-*.py`. |
| Tool call limits | 75 tool calls per session hard limit prevents runaway agent behavior. | Enforced in Runner workflow node configuration. |

**Assessment:** Substantially implemented. Risk management is continuous, automated, and covers functional, performance, cost, and resilience dimensions.

### 3.2 Article 10 -- Data and Data Governance

**Requirement:** Training, validation, and testing datasets shall be subject to appropriate data governance and management practices.

| Control | Implementation | Evidence |
|----|----|----|
| Data trust hierarchy | Enforced 4-tier hierarchy: (1) Live device running config, (2) LibreNMS active monitoring, (3) NetBox CMDB, (4) Supplementary docs. Injected into every agent prompt. | Documented in CLAUDE.md. Enforced via XML-tagged knowledge boundaries. |
| Temporal validity | `incident_knowledge` table uses `valid_until` timestamps. Expired entries excluded from RAG retrieval. Prevents stale knowledge from influencing decisions. | Column in `incident_knowledge` schema. Filter in `kb-semantic-search.py`. |
| Embedding quality gates | `RETRIEVAL_QUALITY` metadata emitted on every search (quality_score, count, avg_similarity, max_similarity). Low-confidence note injected when quality < 0.4. | Implemented in `kb-semantic-search.py`. Consumed by Build Prompt node. |
| RAG faithfulness | 4-signal Reciprocal Rank Fusion (semantic + keyword + wiki + session transcripts). HyDE fallback for zero-result queries. Quality gate prevents hallucination from poor retrievals. | `kb-semantic-search.py` pipeline. |
| PII handling | 16 PII detection patterns. No personal data of external individuals processed -- system handles only infrastructure telemetry and operator commands. | Pattern list in gateway configuration. |

**Assessment:** Substantially implemented. Data governance is particularly strong given the system processes infrastructure telemetry rather than personal data.

### 3.3 Article 12 -- Record-Keeping (Logging)

**Requirement:** AI systems shall technically allow for the automatic recording of events (logs) throughout the lifetime of the system.

| Log Source | Content | Volume | Retention |
|----|----|----|----|
| `session_log` | Complete session records: issue_id, model, token counts, cost, quality scores, timestamps | All sessions since deployment | Indefinite |
| `tool_call_log` | Every tool invocation: tool name, arguments, result, duration, session_id | 88K+ entries | 1 year |
| `execution_log` | Workflow execution records: workflow_id, status, duration, error details | 18K+ entries | 1 year |
| `a2a_task_log` | Agent-to-agent delegation records: source agent, target agent, task, result | Cross-tier delegation audit trail | Indefinite |
| `otel_spans` | OpenTelemetry spans: distributed tracing across workflow nodes | 39K+ spans | 90 days |
| `session_transcripts` | Verbatim exchange-pair chunks with embeddings (MemPalace) | All sessions | Indefinite |
| `agent_diary` | Persistent per-agent memory entries | Continuous | Indefinite |
| JSONL session files | Raw Claude Code output: every tool call, reasoning step, token count | Per-session files in `~/.claude/projects/` | Indefinite |
| Syslog-ng | Terminal session logging from all hosts, centralized per site | All hosts, both sites | Per syslog rotation policy |

**Assessment:** Fully implemented. Logging is comprehensive, multi-layered, and provides complete traceability from user command through agent reasoning to infrastructure action.

### 3.4 Article 13 -- Transparency and Provision of Information

**Requirement:** AI systems shall be designed and developed in such a way that their operation is sufficiently transparent to enable deployers to interpret the system's output and use it appropriately.

| Control | Implementation | Evidence |
|----|----|----|
| Confidence scoring | Every agent output includes a mandatory CONFIDENCE score (0.0-1.0). Scores below 0.6 trigger escalation to human operator. | Enforced in prompt templates. Validated by LLM-as-Judge. |
| Retrieval quality metadata | `RETRIEVAL_QUALITY` block emitted with every RAG-augmented response: quality_score, result_count, average_similarity, max_similarity. | `kb-semantic-search.py` output format. |
| ReAct reasoning | Structured Reasoning-Action-Observation chains visible in session logs. Agent reasoning is not opaque -- each step is logged with tool calls and intermediate results. | JSONL session files. Poller workflow posts tool activity to Matrix in real-time. |
| Progress visibility | Poller workflow reads JSONL every 30s during long-running sessions and posts tool activity to Matrix as `m.notice`. Operator sees what the agent is doing in real-time. | Poller workflow (`uRRkYbRfWuPXrv3b`). |
| Model identification | All outputs identify the model used (Claude Opus/Sonnet, GPT-5.1). Model routing decisions logged with complexity classification. | Session metadata in `session_log`. |

**Assessment:** Fully implemented. The system provides substantially more transparency than required for limited-risk classification.

### 3.5 Article 14 -- Human Oversight

**Requirement:** AI systems shall be designed and developed in such a way that they can be effectively overseen by natural persons during the period in which they are in use.

| Control | Implementation | Evidence |
|----|----|----|
| Matrix approval gates | Destructive or high-impact actions require explicit operator approval via Matrix. Agent pauses and waits for response. | `[POLL]` blocks in agent output. Matrix Bridge workflow handles approval flow. |
| Timed escalation | 15-minute reminder if no operator response. 30-minute auto-pause if still no response. Prevents indefinite autonomous operation without oversight. | Timer logic in Runner workflow. |
| Bang command overrides | Operator can issue `!session done`, `!session pause`, `!session list` at any time to terminate, pause, or inspect active sessions. Immediate effect, no confirmation required. | Matrix Bridge command routing. |
| PreToolUse hooks | 2 PreToolUse hooks block 81 destructive patterns before execution. Blocked actions include force pushes, production deployments, credential deletion, and infrastructure teardown. | Hook configuration in `.claude/settings.json`. |
| Stop hooks | Auto-save session transcripts every 15 messages. Emergency save on context compaction. Ensures no session data is lost even on unexpected termination. | Stop hook + PreCompact hook configuration. |
| Maintenance mode | `gateway.maintenance` file suppresses all automated alert processing. 15-minute post-maintenance cooldown. Prevents agent interference during planned maintenance. | Maintenance companion workflow. |
| Mode switching | `!mode` command switches between 4 operating modes (oc-cc, oc-oc, cc-cc, cc-oc). Operator controls which AI backend processes requests. | Mode file at `~/gateway.mode`. |

**Assessment:** Fully implemented. Human oversight is multi-layered with both proactive gates and reactive override mechanisms.

### 3.6 Article 15 -- Accuracy, Robustness, and Cybersecurity

**Requirement:** AI systems shall achieve an appropriate level of accuracy, robustness, and cybersecurity throughout their lifecycle.

| Control | Implementation | Evidence |
|----|----|----|
| Test coverage | 98 test scenarios in 3-set model (regression, discovery, holdout). CI eval gate blocks MR merge on regression. | `eval-regression` CI stage. Test definitions in evaluation framework. |
| LLM-as-Judge | 5-dimension quality assessment (relevance, accuracy, completeness, safety, formatting) using calibrated Haiku/Opus judges. Score trajectory tracked per session. | Judge invoked by Session End workflow. Scores in `session_log`. |
| Eval flywheel | Monthly evaluation cycle: (1) Collect session data, (2) Score and analyze, (3) Improve prompts/tools, (4) Validate improvements. Continuous quality improvement. | `eval-flywheel.sh`. Schedule documented in QMS. |
| Prompt scoring | `grade-prompts.sh` scores 19 prompt surfaces daily for clarity, specificity, and instruction adherence. | Daily cron. Results tracked for trending. |
| Security audit | Chaos + portfolio security audit: 22 findings fixed, 9.52/10 security score. Shell injection eliminated, rate limiting enforced, API authentication validated. | Audit report at `docs/chaos-engineering-audit-2026-04-14.md`. |
| Rate limiting | OpenClaw Tier 1: 30 commands/minute rate limit. Tool call limit: 75 per session. Cost ceiling: $25/day. | Enforced at multiple layers. |
| Exec-safety hooks | 36 approved execution patterns (no wildcards). Every SSH command validated against allowlist before execution. | OpenClaw exec-approvals configuration. |

**Assessment:** Substantially implemented. Testing, evaluation, and security controls exceed typical requirements for limited-risk systems.

### 3.7 Article 17 -- Quality Management System

**Requirement:** Providers of high-risk AI systems shall put in place a quality management system.

Although not required for limited-risk classification, a QMS has been established as a voluntary best practice measure. See companion document: `docs/quality-management-system.md` (GOV-QMS-001).

**Assessment:** Voluntarily implemented.

### 3.8 Article 50 -- Transparency Obligations for Certain AI Systems

**Requirement:** Deployers of AI systems that interact with natural persons shall inform those persons that they are interacting with an AI system.

| Consideration | Status |
|----|-----|
| System is internal-only | The operator who deploys the system is also the sole user. There are no external users or members of the public interacting with the system. |
| AI identification | All Matrix messages from the system are sent by `@claude:matrix.example.net` or `@openclaw:matrix.example.net` -- clearly identified as AI agents. |
| No generated content presented as human | System outputs are always attributed to the AI agent that produced them. No outputs are presented to third parties as human-generated. |

**Assessment:** Fully compliant. Transparency obligation is inherently satisfied by the system's internal-only deployment model with a single technically sophisticated operator.

---

## 4. General-Purpose AI Model (GPAI) Usage

claude-gateway integrates the following GPAI models as components:

| Model | Provider | Role | GPAI Provider Obligations |
|----|----|----|----|
| Claude Opus/Sonnet/Haiku | Anthropic | Tier 2 agent (implementation, analysis) | Anthropic's responsibility per Art. 53 |
| GPT-5.1 | OpenAI | Tier 1 agent (triage, investigation) | OpenAI's responsibility per Art. 53 |
| Ollama qwen3:4b | Local | Query rewriting, HyDE generation | Local deployment, no GPAI provider obligations |
| nomic-embed-text | Local | Embedding generation for RAG | Local deployment, no GPAI provider obligations |

As a downstream deployer using these models via API, claude-gateway's obligations are limited to:
- Using the models in accordance with their terms of service
- Not using models for prohibited practices (Article 5) -- confirmed not applicable
- Maintaining appropriate oversight of model outputs -- implemented via controls in Section 3

---

## 5. Compliance Summary

| Article | Requirement | Status | Notes |
|----|----|----|-----|
| Art. 5 | Prohibited practices | Not applicable | No prohibited use cases |
| Art. 6(2) | High-risk classification | Not triggered | No Annex III categories apply |
| Art. 9 | Risk management | Substantially implemented | Voluntary; 138 automated checks |
| Art. 10 | Data governance | Substantially implemented | Voluntary; 4-tier trust hierarchy |
| Art. 12 | Record-keeping | Fully implemented | Voluntary; 9 log sources, complete traceability |
| Art. 13 | Transparency | Fully implemented | Voluntary; confidence scores, ReAct reasoning |
| Art. 14 | Human oversight | Fully implemented | Voluntary; approval gates, overrides, maintenance mode |
| Art. 15 | Accuracy/Robustness | Substantially implemented | Voluntary; 98 tests, LLM-as-Judge, security audit |
| Art. 17 | Quality management | Voluntarily implemented | See GOV-QMS-001 |
| Art. 50 | Transparency to users | Fully compliant | Internal-only, operator = deployer |

**Overall Compliance Status:** Substantially compliant for limited-risk classification. No Annex III high-risk triggers identified. Voluntary adoption of high-risk controls provides defense-in-depth and prepares for potential regulatory evolution.

---

## 6. Review and Maintenance

| Item | Detail |
|----|-----|
| Document owner | Example Corp Network -- Infrastructure Team |
| Review cadence | Quarterly |
| Next scheduled review | 2026-07-15 |
| Trigger for ad-hoc review | Material change in system scope, new GPAI model integration, regulatory guidance update |
| Version history | v1.0 (2026-04-15): Initial assessment |
