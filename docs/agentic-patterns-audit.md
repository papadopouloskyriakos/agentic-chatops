# ChatOps Platform Audit vs. Agentic Design Patterns

**Date:** 2026-03-23
**Reference:** Antonio Gulli, "Agentic Design Patterns" (21 chapters, 21 patterns)
**Scope:** Full ChatOps solution — n8n workflows, CLAUDE.md, SOUL.md, SQLite DB, memory files, OpenClaw skills, Grafana dashboards, CI/CD pipeline

---

## Pattern-by-Pattern Assessment

### Well-Implemented (Strong alignment)

| # | Pattern | Your Implementation | Grade |
|---|---------|-------------------|-------|
| 1 | **Tool Use** | 9 MCP servers (netbox, n8n-mcp, youtrack, proxmox, codegraph, opentofu, tfmcp, kubernetes, gitlab-mcp). Both tiers have rich tool access. | A |
| 2 | **Multi-Agent Collaboration** | 3-tier architecture (OpenClaw T1 → Claude Code T2 → Human T3). Clear role separation, escalation protocol. | A |
| 3 | **Parallelization** | 3 per-slot locks (`dev`, `infra-nl`, `infra-gr`). Concurrent sessions across projects. | A- |
| 4 | **Human-in-the-Loop** | Reaction-based approval, interactive polls (MSC3381), approval timeout escalation (15min→30min), confidence-gated stops. | A |
| 5 | **Exception Handling** | `ERROR_CONTEXT:` structured propagation, `continueOnFail`, watchdog (5 layers), empty response fallback, validation retry loop. | A- |
| 6 | **Memory** | Short-term: SQLite sessions + `last_response_b64`. Long-term: `incident_knowledge` table + Claude Code memory files + OpenClaw playbook-lookup. | B+ |
| 7 | **RAG** | `incident_knowledge` table queried by triage scripts (Step 1.5) and Runner Build Prompt. 3-tier RAG (T1 script, T1 playbook-lookup, T2 prompt injection). | B |
| 8 | **Learning & Adaptation** | Incident KB auto-populated on session end. Past resolutions injected into future triage. Known failure rules document. | B |
| 9 | **Reflection** | Cross-tier review protocol (AGREE/DISAGREE/AUGMENT). OpenClaw reviews Claude's output when confidence < 0.7. | B+ |
| 10 | **Goal Setting & Monitoring** | Grafana dashboards (63+ panels), Prometheus metrics, session cost/duration/confidence tracking. | B |
| 11 | **Evaluation & Monitoring** | Per-tier KPIs via `write-agent-metrics.sh`, `write-session-metrics.sh`. Resolution type tracking. | B |
| 12 | **MCP** | Exemplary. 9 MCP servers, custom Proxmox MCP, mcporter for OpenClaw Docker-based MCP. | A |
| 13 | **Exploration & Discovery** | Proactive scan (daily cron via OpenClaw): disk, certs, stale issues, VPN. | B |
| 14 | **Prioritization** | Slot-based priority (dev/infra-nl/infra-gr), cooldown guards, burst detection (3+ hosts = correlated-triage). | B+ |
| 15 | **Resource-Aware Optimization** | `cost_usd`, `num_turns`, `duration_seconds` tracked per session. Session log archives costs. | B |

---

## Identified Gaps & Actionable Recommendations

### GAP 1: RAG is keyword-only, no semantic search
**Pattern:** Ch.14 (Knowledge Retrieval/RAG) strongly recommends **vector embeddings + semantic similarity** for knowledge retrieval. Current `incident_knowledge` uses SQLite `LIKE '%keyword%'` matching.

**Impact:** "etcd WAL latency" won't match "disk I/O causing etcd timeout" even though they're the same root cause. As the KB grows, keyword misses will increase.

**Recommendation:**
- Add an **embeddings column** to `incident_knowledge` using a lightweight local embedding model (e.g., `nomic-embed-text` via Ollama on gpu01)
- Create a small Python script that embeds `root_cause || resolution || tags` on insert
- Query with cosine similarity instead of `LIKE`. SQLite can do this with the `sqlite-vss` extension, or use a simple Python search script
- **Effort:** Medium | **Impact:** High — single biggest quality improvement to the learning loop

**KPI:** Measure KB hit rate (queries that return relevant results) before and after. Target: >80% hit rate on known incident types.

### GAP 2: No procedural memory / self-updating instructions
**Pattern:** Ch.8 (Memory) describes **Procedural Memory** — agents that modify their own system prompt based on reflection. Ch.9 (Learning & Adaptation) describes SICA's self-improvement loop.

**Current state:** SOUL.md and CLAUDE.md are manually maintained. Known failure rules are a static document. Neither agent proposes updates to its own instructions based on what it learned.

**Recommendation:**
- Add a **post-session reflection step** in the Session End workflow: after archiving to `session_log`, have Claude Code generate a 1-line "lesson learned" if the session involved a novel failure mode
- Store these in a `lessons_learned` table (separate from `incident_knowledge` which is per-incident)
- Periodically (weekly cron), summarize new lessons and propose SOUL.md/CLAUDE.md patches for human review via a Matrix message
- **Effort:** Medium | **Impact:** Medium — closes the loop between operational experience and agent instructions

**KPI:** Track number of instruction updates generated per month and their acceptance rate. Target: 2-4 accepted updates/month.

### GAP 3: No guardrails / safety boundary enforcement
**Pattern:** Ch.16 (Guardrails) covers input/output validation, content filtering, and boundary enforcement. The book emphasizes that agents operating in production need explicit guardrails beyond what the LLM naturally provides.

**Current state:** AUTHORIZED_SENDERS filter and read-only constraint in SOUL.md exist, but:
- No **output validation** on Claude Code responses before posting to Matrix (e.g., checking for leaked credentials, overly long responses, or hallucinated commands)
- No **input sanitization** on Matrix messages before they reach the LLM (potential prompt injection via other room members, even if AUTHORIZED_SENDERS filters senders)
- OpenClaw has `sandbox.mode: off` and wildcard exec approvals — no blast radius control

**Recommendation:**
- Add a **pre-post guardrail** in the Runner's "Prepare Result" node: regex scan for common credential patterns (API keys, tokens, passwords) before posting to Matrix
- Add a **response length cap** — if Claude returns >10K chars, summarize rather than truncate (current smart truncation is good but doesn't catch hallucination spirals)
- For OpenClaw: create a **negative exec allowlist** — commands that should NEVER execute regardless of context (e.g., `rm -rf /`, `reboot`, `shutdown`, anything with `| curl` to external hosts)
- **Effort:** Low-Medium | **Impact:** High for production safety

**KPI:** Track guardrail trigger count per week (credential matches blocked, oversized responses caught). Target: 0 credential leaks, <5% response truncations.

### GAP 4: No structured inter-agent communication protocol
**Pattern:** Ch.15 (Inter-Agent Communication / A2A) describes standardized agent-to-agent communication with Agent Cards, structured task delegation, and typed message passing.

**Current state:** OpenClaw → Claude Code communication is via:
1. A webhook POST with a text string (escalation)
2. Matrix messages with informal text conventions (`REVIEW REQUEST:`, `CONFIDENCE:`)
3. `ERROR_CONTEXT:` blocks as unstructured text

**Recommendation:**
- Define a **structured JSON schema** for inter-tier messages:
  ```json
  {"tier": 1, "action": "escalate", "issue_id": "IFRNLLEI01PRD-123",
   "confidence": 0.4, "completed_steps": ["dedup", "issue_create", "investigate"],
   "findings_summary": "...", "suggested_action": "..."}
  ```
- Parse this in the Runner instead of regex-matching `CONFIDENCE: 0.X` from free text
- This makes the review protocol machine-parseable and enables future automation (e.g., auto-accept AGREE reviews, auto-escalate DISAGREE)
- **Effort:** Medium | **Impact:** Medium — reduces parsing fragility and enables richer automation

**KPI:** Track parsing failure rate (failed CONFIDENCE extraction, malformed ERROR_CONTEXT). Target: <2% parsing failures.

### GAP 5: No cost budget / resource ceiling enforcement
**Pattern:** Ch.18 (Resource-Aware Optimization) emphasizes not just tracking costs but **enforcing budgets** — agents should have resource ceilings and adapt behavior when approaching limits.

**Current state:** `cost_usd` tracked per session with Prometheus metrics, but:
- No **per-session cost ceiling** — a runaway Claude session could burn $50+ without being stopped
- No **daily/weekly budget** across all sessions
- No **adaptive behavior** when approaching limits (e.g., switching to plan-only mode instead of executing)

**Recommendation:**
- Add a `MAX_SESSION_COST_USD` env var (suggest: $5) checked in the Wait-for-Claude loop. If cost exceeds threshold, inject a "wrap up" message via `-r`
- Add a daily cost counter in SQLite. If daily total exceeds $25, switch new sessions to plan-only mode (`--plan`) and post a budget warning to `#alerts`
- **Effort:** Low | **Impact:** Medium — prevents runaway costs from a single bad session

**KPI:** Track cost per session (p50, p95, max). Track daily total cost. Target: p95 < $3, daily total < $20.

### GAP 6: Weak episodic memory for OpenClaw (Tier 1)
**Pattern:** Ch.8 (Memory) describes **Episodic Memory** — remembering past experiences to inform current actions. Claude Code has rich episodic memory (CLAUDE.md memory files, incident_knowledge). OpenClaw has almost none.

**Current state:** OpenClaw is stateless between conversations. It has `playbook-lookup` for past incidents but no memory of:
- Its own past mistakes (e.g., wrong triage conclusions)
- User preferences expressed in previous conversations
- Context from earlier in the same day

**Recommendation:**
- Add a lightweight **`openclaw_memory` SQLite table** (key, value, updated_at) that triage scripts write to on completion
- Inject the last 3-5 relevant entries into SOUL.md at runtime (via a shell wrapper that prepends recent context)
- Track OpenClaw review outcomes: when it says AGREE but human overrides, record that as negative feedback
- **Effort:** Medium | **Impact:** Medium — makes Tier 1 smarter over time

**KPI:** Track OpenClaw triage accuracy (correct root cause identification rate). Target: improve from current baseline by 15% within 3 months.

### GAP 7: No formal evaluation benchmarks
**Pattern:** Ch.17 (Evaluation & Monitoring) describes establishing **benchmark test suites** and **automated evaluation** to measure agent performance over time.

**Current state:** E2E test suites exist (13/13 GPT-4o, 24/24 Progress, etc.) but these are one-time validation, not recurring regression tests. There's no automated way to detect if a SOUL.md change degrades triage quality.

**Recommendation:**
- Create a **golden test set**: 10 representative alert scenarios with known-correct triage outputs
- Run these monthly via a cron job that feeds synthetic alerts through the pipeline and compares outputs against expected results
- Track pass/fail rate over time as a Grafana panel
- **Effort:** Medium | **Impact:** High — catches regressions before they affect real incidents

**KPI:** Golden test pass rate. Target: 100% pass rate on golden set after any config change. Track over time.

### GAP 8: No dynamic routing / agent selection
**Pattern:** Ch.6 (Routing) describes agents dynamically selecting which sub-agent or tool to use based on the nature of the input.

**Current state:** Routing is static: issue prefix → room → slot. All infra alerts go through the same triage script regardless of alert type.

**Recommendation:**
- Add **alert-type-aware routing** in the triage scripts: network alerts could skip PVE checks and go straight to switch/firewall diagnostics; storage alerts could check Synology first
- In the Runner's Build Prompt, add **dynamic context selection** — only inject K8s-related knowledge for K8s alerts, not all incident_knowledge entries
- **Effort:** Low | **Impact:** Low-Medium — reduces noise in prompts and speeds up triage

**KPI:** Track average triage duration by alert type. Target: 20% reduction in triage time for specialized alert types.

---

## Summary Scorecard

| Category | Score | Key Gap |
|----------|-------|---------|
| Tool Use & MCP | **A** | Excellent — 9 MCPs, custom Proxmox server |
| Multi-Agent Collaboration | **A-** | Strong 3-tier design, NL-A2A/v1 protocol |
| A2A Communication | **A** | Agent cards, envelope format, REVIEW_JSON auto-action, task lifecycle logging |
| Memory (Short+Long) | **A-** | All 4 types: short/long/episodic/procedural |
| Learning & Adaptation | **A** | A/B testing, outcome scoring, regression detection, lessons pipeline |
| Reasoning Techniques | **A** | ReAct, step-back prompting, chain-of-verification, self-consistency, tree-of-thought |
| Human-in-the-Loop | **A** | Polls, reactions, timeouts — very strong |
| Exception Handling | **A-** | 5-layer watchdog, ERROR_CONTEXT, output guardrails |
| RAG | **A-** | Vector embeddings + keyword fallback |
| Evaluation | **B+** | Golden tests + regression detection + variant metrics |
| Guardrails | **A** | Code-level exec enforcement, input sanitization, output fact-checking, schema validation, rate limiting |
| Resource Optimization | **A** | Category-aware cost prediction, dynamic timeout, per-category metrics, budget enforcement |

---

## Updates (2026-03-24)

### Reasoning Techniques (B -> A)
- **ReAct framework** in Build Prompt: THOUGHT/ACTION/OBSERVATION loop mandatory for infra issues
- **Step-back prompting**: auto-detected recurring alerts get meta-analysis instructions
- **Chain-of-verification**: OpenClaw cross-tier review now requires 5-step verification checklist
- **Self-consistency check**: Parse Response detects confidence/reasoning mismatches (hedging + high confidence, or actions + low confidence)
- **Tree-of-thought**: correlated bursts require H1/H2 hypotheses before investigation
- **A/B variant testing**: react_v1 vs react_v2 (adds chain-of-verification), deterministic by issue hash

### Learning & Adaptation (B+ -> A)
- **session_feedback table**: records thumbs_up/thumbs_down reactions linked to issue IDs
- **Outcome scoring**: Session End auto-classifies resolution_type from feedback (approved/rejected/mixed/unscored)
- **Lessons-to-prompt pipeline**: Query Knowledge fetches recent lessons, Build Prompt injects them
- **Prompt variant tracking**: prompt_variant column in session_log, Prometheus metrics per variant
- **Regression detection**: `regression-detector.sh` (6h cron) compares 7d rolling windows, alerts on drops
- **Metrics**: feedback counts, variant comparison, lessons total in write-session-metrics.sh

---

## QA Levels for Changes

When implementing any of the above recommendations, apply the following QA levels:

### Level 1 — Config Change (e.g., cost ceiling env var, exec negative-list)
- [ ] Syntax validation (bash -n, JSON lint)
- [ ] Manual smoke test in `#chatops`
- [ ] Verify in Grafana dashboard within 1h

### Level 2 — Workflow Change (e.g., guardrail node in Runner, routing logic)
- [ ] Export workflow JSON to `workflows/`
- [ ] Run CI pipeline (validate + test stages)
- [ ] E2E test with synthetic alert
- [ ] Monitor first 3 real incidents post-change
- [ ] Check for parsing regressions (CONFIDENCE extraction, POLL detection)

### Level 3 — Architecture Change (e.g., vector embeddings, A2A protocol, OpenClaw memory)
- [ ] Design doc / plan in Matrix thread before implementation
- [ ] Update CLAUDE.md and/or SOUL.md
- [ ] Full golden test suite pass
- [ ] 48h burn-in period with monitoring
- [ ] Update Grafana dashboards with new KPI panels
- [ ] Update this audit document with new scores
