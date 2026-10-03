# Quality Management System -- claude-gateway Agentic Platform

**Document ID:** GOV-QMS-001
**Version:** 1.0
**Date:** 2026-04-15
**Next Review:** 2026-07-15
**Author:** Example Corp Network -- Infrastructure Team
**Classification:** Internal
**Reference:** EU AI Act Article 17 (voluntary adoption for limited-risk system)

---

## 1. Scope

This Quality Management System (QMS) covers the claude-gateway agentic platform, comprising:

- **26 n8n workflows** (~470 nodes) orchestrating ChatOps, ChatSecOps, and ChatDevOps subsystems
- **10 MCP servers** providing 153 tools (NetBox, GitLab, YouTrack, Proxmox, n8n, CodeGraph, OpenTofu, tfmcp, Kubernetes, Ollama)
- **10 sub-agents** (6 infrastructure + 4 development)
- **19 OpenClaw skills** (15 triage + 4 always-on protocol)
- **24 SQLite tables** storing operational state, session data, knowledge base, and telemetry
- **3 portfolio statistics APIs** serving live data to the public website
- **RAG pipeline** with 4-signal Reciprocal Rank Fusion and compiled knowledge base (45 wiki articles)

**Deployment scope:** Internal-only, 2 sites (NL: nl, GR: gr), 310 managed devices/VMs, single operator.

---

## 2. Quality Objectives

### 2.1 Session Quality

| Metric | Target | Measurement | Frequency |
|----|----|----|----|
| LLM-as-Judge composite score | >= 3.5 / 5.0 | 5-dimension assessment (relevance, accuracy, completeness, safety, formatting) via calibrated Haiku/Opus judges | Every session (Session End workflow) |
| Score trajectory | Non-declining 30-day rolling average | `session_log` quality_score column, analyzed by `regression-detector.sh` | Every 6 hours |
| Confidence calibration | Confidence scores correlate with actual accuracy | Manual spot-check during quarterly review | Quarterly |

### 2.2 RAG Faithfulness

| Metric | Target | Measurement | Frequency |
|----|----|----|----|
| Retrieval quality score | >= 0.80 average across sessions | `RETRIEVAL_QUALITY` metadata (quality_score field) from `kb-semantic-search.py` | Every RAG query |
| Zero-result rate | < 5% of queries | HyDE fallback trigger count vs total query count | Weekly (holistic health) |
| Knowledge freshness | No expired entries served | `valid_until` filter enforcement in RAG pipeline | Continuous |

### 2.3 Incident Resolution

| Metric | Target | Measurement | Frequency |
|----|----|----|----|
| Critical MTTR | < 30 minutes | Time from alert receipt to resolution confirmation | Per incident |
| High MTTR | < 2 hours | Time from alert receipt to resolution confirmation | Per incident |
| Triage accuracy | >= 90% correct root cause identification on first attempt | Manual review of triage outcomes during quarterly assessment | Quarterly |

### 2.4 System Reliability

| Metric | Target | Measurement | Frequency |
|----|----|----|----|
| Holistic health score | >= 95% (131/138 checks passing) | `holistic-agentic-health.sh` composite score | Daily |
| Workflow error rate | < 1% of executions | `execution_log` error count / total count | Weekly |
| Session completion rate | >= 95% (sessions reaching Session End without crash) | `session_log` completion status | Weekly |

---

## 3. Design and Development Controls

### 3.1 CI/CD Pipeline

All code changes pass through the GitLab CI/CD pipeline (`.gitlab-ci.yml`) with the following stages:

| Stage | Purpose | Gate Behavior |
|----|----|----|
| `validate` | JSON schema validation for workflow exports, YAML lint, shellcheck for scripts | Blocks MR on failure |
| `test` | Unit tests, integration tests, hook validation | Blocks MR on failure |
| `eval` | `eval-regression` -- runs evaluation scenarios against current and proposed versions, compares quality scores | Blocks MR merge if regression detected |
| `review` | Automated code review checks | Advisory |
| `sync` | Deploys validated changes to n8n instance and synchronizes workflow exports | Runs on main branch only |

### 3.2 Workflow Development Standards

- All workflows prefixed with `"NL - "` for namespace isolation
- Workflow JSON exported after every change via n8n-mcp and committed to `workflows/` directory
- n8n node schemas consulted before any node configuration (`npx n8n-as-code schema <node>`)
- Switch V3.2 nodes always include `conditions.options` block (documented known issue)
- Webhook listeners reloaded via deactivate/activate cycle after API updates

### 3.3 Prompt Engineering Controls

- 55 CLAUDE.md files providing deterministic knowledge injection at both tiers
- 74 feedback memories encoding operational lessons learned
- XML-tagged knowledge boundaries preventing cross-domain contamination
- `grade-prompts.sh` scores 19 prompt surfaces daily for quality
- Prompt Scorecard tracks 19 surfaces across clarity, specificity, and instruction adherence dimensions

### 3.4 Change Management

- All changes tracked in Git (gitlab.example.net/n8n/claude-gateway)
- MR-gated workflow: branch, commit, review, merge
- Direct push to main permitted for claude-gateway repo (operational efficiency for solo operator)
- Infrastructure changes require explicit operator approval (feedback memory: `feedback_ask_before_changing.md`)
- Kubernetes changes exclusively via OpenTofu + Atlantis MR (feedback memory: `feedback_k8s_strict_gitops.md`)

---

## 4. Post-Market Monitoring Plan

### 4.1 Automated Monitoring

| Monitor | Scope | Schedule | Alert Channel |
|----|----|----|----|
| `holistic-agentic-health.sh` | 138 checks across 31 sections: functional correctness, end-to-end integration, trending analysis, infrastructure health, database integrity, cron health, security controls | Daily | Matrix #alerts |
| `regression-detector.sh` | 6-hour rolling window: session quality trends, cost anomalies, error rate spikes | Every 6 hours | Matrix #alerts |
| `grade-prompts.sh` | 19 prompt surfaces: instruction clarity, knowledge injection completeness, guardrail presence | Daily | Matrix #alerts on degradation |
| `predictive-alerts.py` | Trend-based prediction: quality trajectory, cost projection, capacity indicators | Continuous | Matrix #alerts |
| Dead-man watchdog | Confirms monitoring pipeline itself is operational. Fires every minute; alert if missed. | Every minute (*/1 cron) | Matrix #alerts (absence = alarm) |
| `write-chaos-metrics.sh` | Chaos engineering exercise results: pass rate, recovery time, safety violations | After each chaos run | Prometheus metrics |

### 4.2 Periodic Assessment

| Assessment | Scope | Schedule | Output |
|----|----|----|----|
| Eval flywheel | Full evaluation cycle: collect, score, improve, validate | Monthly | Evaluation report, prompt improvements |
| Quarterly benchmark | Industry benchmark comparison, holistic health trending, compliance review | Quarterly (next: 2026-07-15) | Benchmark report (e.g., `docs/industry-benchmark-2026-04-15.md`) |
| Chaos engineering | Automated weekly chaos runs with self-selecting scenarios, preflight safety gates | Weekly (daily 10:00 UTC) | `chaos_exercises` table, Matrix notifications |
| Wiki compilation | Knowledge base refresh from 7+ sources | Daily (04:30 UTC cron) + on-demand | `wiki_articles` table (45 articles) |

### 4.3 Quality Trending

Historical quality data is retained in:
- `session_log`: Per-session quality scores, cost, token counts (indefinite retention)
- `chaos_exercises`: Chaos experiment results, pass/fail, recovery times (indefinite retention)
- `llm_usage`: Per-model token and cost tracking across 3 tiers (indefinite retention)

Trending analysis performed by `regression-detector.sh` (automated) and during quarterly benchmark assessment (manual review).

---

## 5. Serious Incident Definition and Reporting

### 5.1 Serious Incident Classification

A serious incident is any event where the AI system causes or contributes to:

| Category | Definition | Severity |
|----|----|----|
| Unauthorized access | Agent accesses data or systems outside its authorized scope, or credentials are exposed | Critical |
| Scope violation | Agent performs actions not sanctioned by its tier-level permissions or outside the boundaries defined in the oversight framework | Critical |
| Cost overrun | Single session cost exceeds $100 (4x the $25/day ceiling) | Critical |
| Approval bypass | Agent executes a destructive or high-impact action without required human approval | Critical |
| Data loss | Agent action results in unrecoverable deletion or corruption of production data | Critical |
| Infrastructure outage | Agent action causes unplanned service disruption lasting more than 30 minutes | High |
| Safety control failure | PreToolUse hooks, cost ceiling, rate limits, or exec-approval checks fail to prevent a blocked action | High |
| Incorrect triage | Agent misidentifies root cause leading to incorrect remediation that worsens the incident | High |

### 5.2 Reporting Procedure

1. **Immediate notification** (within 15 minutes for Critical, 1 hour for High):
   - Matrix message to #alerts room with incident details
   - YouTrack issue created with priority matching severity

2. **Investigation** (within 24 hours):
   - Full session transcript review from `session_transcripts` and JSONL logs
   - Tool call audit from `tool_call_log`
   - Root cause analysis documented in YouTrack issue

3. **Corrective action** (within 72 hours):
   - Fix deployed and validated
   - `incident_knowledge` entry created for RAG pipeline (prevents recurrence)
   - Feedback memory created if operational lesson identified
   - Test scenario added to evaluation suite if gap identified

4. **Post-incident review** (within 1 week):
   - Postmortem document published (e.g., `docs/postmortem-*.md`)
   - QMS updated if process gap identified
   - Oversight boundary framework updated if scope definition insufficient

### 5.3 Response SLAs

| Severity | Notification | Investigation Start | Corrective Action | Review |
|----|----|----|----|----|
| Critical | 15 minutes | Immediate | 24 hours | 72 hours |
| High | 1 hour | 4 hours | 72 hours | 1 week |

---

## 6. Document Control

### 6.1 Document Repository

All QMS documents are stored in Git at `gitlab.example.net/n8n/claude-gateway`, under the `docs/` directory. Version history is maintained by Git commit log. Documents are subject to the same change management process as code (Section 3.4).

### 6.2 Governance Document Inventory

| Document ID | Title | Path |
|----|----|----|
| GOV-EUAIA-001 | EU AI Act Risk Assessment | `docs/eu-ai-act-assessment.md` |
| GOV-QMS-001 | Quality Management System (this document) | `docs/quality-management-system.md` |
| GOV-OBF-001 | Oversight Boundary Framework | `docs/oversight-boundary-framework.md` |

### 6.3 Related Operational Documents

| Document | Path | Purpose |
|----|----|----|
| Architecture documentation | `docs/architecture.md` | System architecture description |
| Evaluation process | `docs/evaluation-process.md` | Evaluation methodology and scenarios |
| Deployment guide | `docs/deployment-guide.md` | Installation and configuration procedures |
| Known failure rules | `docs/known-failure-rules.md` | Documented known issues and workarounds |
| LLM usage tracking | `docs/llm-usage-tracking.md` | Token/cost tracking methodology |
| MemPalace details | `docs/mempalace-details.md` | Memory and knowledge persistence architecture |
| Compiled wiki details | `docs/compiled-wiki-details.md` | Knowledge base compilation methodology |

---

## 7. Internal Audit

### 7.1 Audit Schedule

| Audit Type | Frequency | Next Scheduled | Scope |
|----|----|----|----|
| Quarterly benchmark assessment | Quarterly | 2026-07-15 | Full system evaluation against industry benchmarks, compliance review, quality trending |
| Holistic health review | Monthly | 2026-05-15 | Review of daily holistic-agentic-health.sh trends, identify persistent failures |
| Chaos engineering review | Monthly | 2026-05-15 | Review of weekly chaos results, update safety calculator, assess recovery patterns |
| Eval flywheel cycle | Monthly | 2026-05-15 | Collect-Score-Improve-Validate cycle on session quality |

### 7.2 Audit Methodology

Quarterly benchmark assessments follow the methodology established in `docs/industry-benchmark-2026-04-15.md`:
- Compare system capabilities against published industry frameworks
- Score each dimension (risk management, human oversight, transparency, robustness, etc.)
- Identify gaps and create YouTrack issues for remediation
- Track improvement trajectory across quarters

### 7.3 Previous Audits

| Date | Type | Outcome | Reference |
|----|----|----|----|
| 2026-04-07 | Tri-source audit | 11/11 dimensions A+ (100%) | `docs/tri-source-audit.md` |
| 2026-04-09 | Audit remediation | 5 FAIL + 8 WARN fixed | `docs/audit-remediation-report-2026-04-09.md` |
| 2026-04-10 | Operational activation | 21/21 tables active (100%) | `docs/operational-activation-audit-2026-04-10.md` |
| 2026-04-11 | Chaos + security | 22 findings fixed, 9.52/10 score | Memory: `chaos_audit_20260411.md` |
| 2026-04-14 | Comprehensive chaos | 72% compliance, CMM L2+ | `docs/chaos-engineering-audit-2026-04-14.md` |
| 2026-04-15 | Industry benchmark | Current benchmark | `docs/industry-benchmark-2026-04-15.md` |

---

## 8. Corrective and Preventive Actions

### 8.1 Corrective Action Process

The eval flywheel (Phase 3: Improve) is the primary corrective action mechanism:

1. **Detection:** Regression detected by `regression-detector.sh`, holistic health check, or LLM-as-Judge score decline
2. **Analysis:** Root cause identified via session transcript review, tool call audit, or RAG quality analysis
3. **Correction:** Fix implemented (prompt update, workflow change, knowledge base entry, hook addition)
4. **Validation:** Fix validated via eval regression tests before deployment
5. **Learning:** `incident_knowledge` entry created, feedback memory saved, wiki article updated if applicable

### 8.2 Preventive Action Mechanisms

| Mechanism | How It Prevents Issues |
|----|-----|
| PreToolUse hooks | Block 81 destructive patterns before they execute |
| Cost ceiling | Prevents runaway spend before it occurs |
| Chaos engineering | Identifies resilience gaps before production incidents |
| Predictive alerts | Flags degradation trends before they become failures |
| Knowledge compilation | Keeps RAG pipeline current, preventing stale-knowledge errors |
| Exec-approval allowlist | Prevents unauthorized command execution by design |

---

## 9. Management Review

### 9.1 Review Inputs

- Holistic health trending data (daily scores over review period)
- Session quality scores and trajectories
- Serious incident reports (if any)
- Chaos engineering results and recovery time trends
- Cost tracking and budget adherence
- Audit findings and corrective action status
- Regulatory or framework updates

### 9.2 Review Outputs

- Updated quality objectives (if warranted)
- Resource allocation decisions
- Process improvement directives
- Updated risk assessment (EU AI Act review)
- Updated oversight boundaries (NIST framework review)

### 9.3 Review Schedule

Management review is conducted as part of the quarterly benchmark assessment. Next review: 2026-07-15.

---

## 10. Version History

| Version | Date | Changes |
|----|----|----|
| 1.0 | 2026-04-15 | Initial QMS document |
