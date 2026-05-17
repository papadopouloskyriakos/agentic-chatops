# agentic-chatops

AI agents that triage infrastructure alerts, investigate root causes, and propose fixes — while a solo operator sleeps.

> **For the complete technical reference, see [README.extensive.md](README.extensive.md).**

![Architecture](docs/agentic-chatops.png)

## The Problem

One person. **310+ infrastructure objects** across 6 sites. 3 firewalls, 12 Kubernetes nodes, self-hosted everything. When an alert fires at 3am, there's no team to call. There never is.

## The Solution

Three agentic subsystems that handle the detective work — **ChatOps** (infrastructure), **ChatSecOps** (security), **ChatDevOps** (CI/CD) — built on [n8n](https://n8n.io/) orchestration, [Matrix](https://matrix.org/) as the human interface, and a 3-tier agent architecture. The human stays in the loop for every infrastructure change. The system never acts without a thumbs-up or poll vote.

---

## What Makes This Different

### Self-Improving Prompts — now with A/B trials (nobody else does this)

The system evaluates its own performance and auto-patches its prompts. Every session is scored by an [LLM-as-a-Judge](https://arxiv.org/abs/2306.05685) on 5 quality dimensions (`gemma3:12b` local-first since 2026-04-19, Haiku for calibration). When a dimension averages below threshold over 30 days, the **preference-iterating patcher** ([IFRNLLEI01PRD-645](docs/runbooks/prompt-patch-trials.md), 2026-04-20) generates **3 candidate instruction variants** (concise / detailed / examples) and assigns each future matching session to one arm via deterministic BLAKE2b hash — plus a no-patch control. A daily cron runs a one-sided Welch t-test once every arm reaches 15 samples; the winner is promoted only if it beats control by ≥ 0.05 points with `p < 0.1`. Otherwise the trial is aborted. Prompt-level policy iteration — no model weights are ever fine-tuned.

```
Session → LLM Judge (5 dims) → dimension trending below threshold
  → prompt-patch-trial.py generates 3 candidate variants + 1 control
  → future sessions hash-routed to arms → Welch t-test at 15+ samples/arm
  → winner promoted to config/prompt-patches.json (source: "trial:N:idx=I")
  → next eval cycle scores the new patch → loop continues
```

### AI Planner Wired to Proven Ansible Playbooks

Before Claude Code investigates, a Haiku planner generates a 3-5 step investigation plan. The planner queries AWX for matching Ansible playbooks from **41 proven templates** (maintenance, cert sync, K8s drain, PVE updates, DMZ deployments). Plans naturally include "Run AWX Template 64 with dry_run=true" as remediation steps — bridging AI reasoning with proven automation.

### Predictive Alerting

Instead of only reacting after alerts fire, the system queries LibreNMS API daily for **trending risk** across both sites. Devices are scored on disk usage trends, alert frequency, and health signals. A daily top-10 risk report posts to Matrix before problems become incidents.

### 5-Signal RAG + GraphRAG + Staleness + Temporal Filter + mtime-Sort

Retrieval uses [Reciprocal Rank Fusion](docs/industry-agentic-references.md#5-rag--retrieval-optimization) across **5 signals** (semantic + keyword + [compiled wiki](wiki/index.md) + [MemPalace](https://github.com/milla-jovovich/mempalace) transcripts + chaos baselines), plus a **GraphRAG knowledge graph** (360 entities, 193 relationships). Retrieval short-circuits via two intent detectors: **temporal window** ("last 48h", "72 hours ending YYYY-MM-DD") filters wiki on `source_mtime`, and **mtime-sort intent** ("name any three memory files created in the last 48h") bypasses semantic retrieval entirely and returns an mtime-ranked window. Results older than 7 days get age-proportional staleness warnings. A **Haiku synth step** composes cross-chunk answers when top rerank < threshold (3-4× faster p95 than the Ollama ensemble). `SYNTH_HAIKU_FORCE_FAIL` env supports 5 failure modes (429 / auth / timeout / network / empty) that all fall back cleanly to local qwen2.5.

### Karpathy-Style Compiled Knowledge Base

Following [Andrej Karpathy's LLM Knowledge Bases pattern](https://x.com/karpathy/status/2039805659525644595): raw data from 7+ sources (117 memory files, 55 CLAUDE.md files, 33 incidents, 27 lessons, 101 OpenClaw memories, 17 skills, ~5,200 lab docs) is compiled into a browsable [44-article wiki](wiki/index.md) with auto-maintained indexes, daily SHA-256 incremental recompilation, and contradiction detection. All articles embedded into RAG as the 3rd fusion signal.

### Full Observability Stack with OTel

88,448 tool calls instrumented across 108 tool types with per-tool error rates and latency percentiles. 39K OTel spans across 94 traces exported to OpenObserve (OTLP). 10 Grafana dashboards (64+ panels) covering ChatOps, ChatSecOps, ChatDevOps, and trace analysis. 18,220 infrastructure commands logged across 232 devices.

### Formal Evaluation Pipeline

58 scenarios across [3 eval sets](docs/evaluation-process.md) (22 regression + 20 discovery + 16 holdout) + 54 adversarial red-team tests. [Prompt Scorecard](scripts/grade-prompts.sh) grades 19 surfaces daily on 6 dimensions. [Agent Trajectory](scripts/score-trajectory.sh) scoring on 8 infra / 4 dev steps. A/B variant testing (react_v1 vs react_v2). CI eval gate blocks bad merges. Monthly eval flywheel cycle.

### Structured Agentic Substrate — 9 adoptions from the OpenAI Agents SDK

The 2026-04-20 audit of [openai/openai-agents-python](https://github.com/openai/openai-agents-python) flagged 11 gaps; 9 were implemented (issues [IFRNLLEI01PRD-635..643](docs/runbooks/)). The system now has a versioned, typed, recoverable substrate the old string-based Matrix pipeline couldn't offer:

- **Schema versioning** on 9 session/audit tables + a central registry ([`scripts/lib/schema_version.py`](scripts/lib/schema_version.py)) mirroring the SDK's `RunState.CURRENT_SCHEMA_VERSION` / `SCHEMA_VERSION_SUMMARIES` pattern. Writers stamp `schema_version=CURRENT`; readers `check_row()` fail-fast on future versions.
- **13 typed events** ([`session_events.py`](scripts/lib/session_events.py)) in a new `event_log` table — `tool_started/ended`, `handoff_requested/completed/cycle_detected/compaction`, `reasoning_item_created`, `mcp_approval_*`, `agent_updated`, `message_output_created`, `tool_guardrail_rejection`, `agent_as_tool_call`. Replaces free-form Matrix strings with Grafana-queryable structured telemetry.
- **Per-turn lifecycle hooks** — `session-start.sh`, `post-tool-use.sh`, `user-prompt-submit.sh`, `session-end.sh` (new — the `on_final_output` equivalent) feeding a `session_turns` table with per-turn cost, tokens, duration, tool count.
- **3-behavior tool-guardrail taxonomy** (`allow` / `reject_content` / `deny`) in [`unified-guard.sh`](scripts/hooks/unified-guard.sh) + `audit-bash.sh` + `protect-files.sh`. `reject_content` sends Claude a retry hint instead of a wall; `deny` hard-halts. Every rejection is a typed event.
- **`HandoffInputData` envelope** ([`scripts/lib/handoff.py`](scripts/lib/handoff.py)) — zlib-compressed base64 payload carrying `input_history`, `pre_handoff_items`, `new_items`, `run_context`. 176 KB history → **752 B on the wire (0.43% ratio)**. Eliminates the "re-derive context via RAG" cost on escalation.
- **Transcript compaction** ([`scripts/compact-handoff-history.py`](scripts/compact-handoff-history.py)) — opt-in per escalation. Local `gemma3:12b` with Haiku fallback; circuit-breaker aware.
- **Agent-as-tool wrapper** ([`scripts/agent_as_tool.py`](scripts/agent_as_tool.py)) — wraps the 10 sub-agent definitions as callable tools so the orchestrator LLM can conditionally invoke them in the ambiguous-risk (0.4–0.6) band, complementing our deterministic routing.
- **Handoff depth counter + cycle detection** ([`scripts/lib/handoff_depth.py`](scripts/lib/handoff_depth.py)) — `handoff_depth >= 5` forces `[POLL]`; `>= 10` hard-halts; any agent twice in the chain is refused and logged as `handoff_cycle_detected`.
- **Immutable per-turn snapshots** ([`scripts/lib/snapshot.py`](scripts/lib/snapshot.py)) — a snapshot is captured BEFORE each mutating tool call (`Bash`, `Edit`, `Write`, `Task`; read-only tools skipped); `rollback_to(id)` restores any prior `sessions` row. 7-day retention.

Four new SQLite tables (`event_log`, `handoff_log`, `session_state_snapshot`, `session_turns`) bring the total to 35. Migrations 006–011 apply idempotently on both fresh and legacy DBs. Two follow-ups since then — the A/B prompt patcher ([IFRNLLEI01PRD-645](docs/runbooks/prompt-patch-trials.md), `prompt_patch_trial` + `session_trial_assignment`) and the CLI-session RAG capture pipeline ([-646](docs/runbooks/cli-session-rag-capture.md)/[-647](docs/runbooks/cli-session-rag-capture.md)/[-648](docs/runbooks/cli-session-rag-capture.md), no new tables; chunks + tool calls + knowledge rows tagged `issue_id='cli-<uuid>'` on the existing schema) — bring the live total to **39**.

### CLI-Session RAG Capture — interactive `claude` sessions flow into RAG too (2026-04-20)

Before this, only YT-backed Runner sessions had their transcripts/tool-calls/extracted knowledge written into the shared RAG tables. Interactive `claude` CLI sessions (human-in-the-loop dev work) were only captured by `poll-claude-usage.sh` for cost/tokens — their *content* was lost to retrieval.

A 3-tier pipeline ([IFRNLLEI01PRD-646/-647/-648](docs/runbooks/cli-session-rag-capture.md)) closes the gap. A single cron line chains three idempotent steps over every CLI JSONL:

1. `archive-session-transcript.py` chunks exchange pairs → `session_transcripts` + `nomic-embed-text` embeddings + doc-chain refined summary at `chunk_index=-1` (sessions ≥ 5000 assistant chars).
2. `parse-tool-calls.py` extracts `tool_use` / `tool_result` pairs → `tool_call_log` (issue_id resolves to `cli-<uuid>` via patched path inference).
3. `extract-cli-knowledge.py` runs `gemma3:12b` in strict-JSON mode over the summary rows → `incident_knowledge` with `project='chatops-cli'`, embedded for retrieval.

Retrieval weights `chatops-cli` rows at `CLI_INCIDENT_WEIGHT=0.75` by default so real infra incidents still win close ties. Byte-offset watermark skips unchanged files. Soak test (10 files): 12 chunks + 245 tool-call rows + 4 knowledge extractions — gemma correctly classified one sample as `subsystem=sqlite-schema, tags=[schema, migration, versioning, data]` at 0.95 confidence.

### Skill Authoring Uplift — 6 dimensions closed vs `google/agents-cli` (2026-04-23)

A deep audit against [`google/agents-cli`](https://github.com/google/agents-cli) flagged 6 skill-authoring dimensions where we trailed (phase-gate choreography, discoverability, anti-guidance, inline behavioral anti-patterns, governance/versioning, skill index). An 11-commit uplift ([IFRNLLEI01PRD-712](docs/scorecard-post-agents-cli-adoption.md) umbrella, Phases A→J) closed every gap. 0 reverts.

- **Master phase-gate skill** — new [`.claude/skills/chatops-workflow/SKILL.md`](.claude/skills/chatops-workflow/SKILL.md) codifies the Phase 0→6 incident lifecycle (triage → drift-check → context → propose → approve → execute → post-incident). Force-injected into every Runner session's Build Prompt (marker-delimited for surgical removal; rollback anchor preserved at `/tmp/runner-pre-IMMUTABLE.json`).
- **Auto-generated skill index** — [`scripts/render-skill-index.py`](scripts/render-skill-index.py) emits a drift-gated [`docs/skills-index.md`](docs/skills-index.md) from all SKILL.md + agent frontmatter. Guarded by `test-656-skill-index-fresh.sh`, refreshed as a pre-step of the daily 04:30 UTC wiki-compile cron.
- **Versioned + audited skills** — every SKILL.md + agent frontmatter now carries `version: 1.x.0` + `requires: {bins, env}`. [`scripts/audit-skill-requires.sh`](scripts/audit-skill-requires.sh) + a Prometheus exporter feed two new alerts (`SkillPrereqMissing`, `SkillMetricsExporterStale`). [`scripts/audit-skill-versions.sh`](scripts/audit-skill-versions.sh) walks git history for body-changed-without-bump cases; semver convention at [`docs/runbooks/skill-versioning.md`](docs/runbooks/skill-versioning.md).
- **Anti-guidance trailing clauses** — every primary skill/agent description now ends with "Do NOT use for X (use /other-skill instead)". Measurably reduces over-routing to adjacent-sounding agents.
- **Shortcuts-to-Resist tables** inlined on 11 agents (46 rows drawn from `memory/feedback_*.md` with source citations) — behavioral inoculation at the surface where the model is about to act.
- **Proving-Your-Work directive** — new `check_evidence()` in [`scripts/classify-session-risk.py`](scripts/classify-session-risk.py) emits an `evidence_missing` risk signal that forces `[POLL]` when CONFIDENCE ≥ 0.8 but the reply carries no tool output / code fence. Mirrored in the Runner's Prepare Result node to strip unearned `[AUTO-RESOLVE]` markers and prepend a `GUARDRAIL EVIDENCE-MISSING:` banner.
- **User-vocabulary map** — [`config/user-vocabulary.json`](config/user-vocabulary.json) (20 entries: `"the firewall"` → `nl-fw01;gr-fw01`, `"xs4all"` → `"budget"` post-2026-04-21 rename, etc.) scanned by the prompt-submit hook; every match emits a typed `vocabulary` event to `event_log`.

**Scorecard delta:** 3.94 → **4.94** average; **13/16 dimensions at 5/5** (was 9/16). Full memo: [`docs/scorecard-post-agents-cli-adoption.md`](docs/scorecard-post-agents-cli-adoption.md). E2E hardened in the same batch via a J1–J5 pass: live `vocabulary` event captured by firing the real prompt-submit hook, `promtool test rules` executed inside the live Prometheus pod, force-injection proven by a real Runner session whose first tool call grepped for `Phase 0` in the injected skill body.

### NVIDIA DLI Cross-Audit + P0+P1 Implementation (2026-04-29)

The 19-transcript NVIDIA Deep Learning Institute *Agentic AI Systems* course (Vadim Kudlai) was the last major agentic-AI source not yet evaluated against this platform. The 12-dimension cross-audit on 2026-04-29 initially graded the system **A (4.4/5.0)** — the lowest of any of the 9 sources audited. A same-day implementation of all 7 P0+P1 items lifted it to **A+ (4.83/5.0)**, putting the system at A+ across all 9 sources (aggregate A+ 4.79).

Shipped in 4 commits (G1–G4) under YouTrack umbrella [IFRNLLEI01PRD-747](docs/agentic-platform-state-2026-04-29.md) with children -748..-751. Six commits direct-pushed to main, zero reverts. **57/57 new QA tests pass.**

- **G1 — Long-horizon reasoning replay eval** ([`scripts/long-horizon-replay.py`](scripts/long-horizon-replay.py)) replays the 30 longest historical sessions weekly (Mon 05:00 UTC), scoring trace_coherence, tool_efficiency, poll_correctness, cost_per_turn_z. New `long_horizon_replay_results` table; `LongHorizonReplayStale` alert.
- **G1 — Jailbreak corpus + Greek extension** — 39 fixtures across the 5 NVIDIA-DLI-08 vectors (asterisk-obfuscation, persona-shift, retroactive-history-edit, context-injection, lost-in-middle-bait), including **8 Greek operator-language fixtures**. Pure-regex [`scripts/lib/jailbreak_detector.py`](scripts/lib/jailbreak_detector.py); weekly regression cron (Wed 05:00 UTC); `JailbreakBypassDetected` alert on any miss.
- **G2 — Intermediate semantic rail (DARK-FIRST)** — [`scripts/lib/intermediate_rail.py`](scripts/lib/intermediate_rail.py) (heuristic + Ollama dual-backend) inserted as a `Check Intermediate Rail` Code node between Build Plan and Classify Risk in the Runner workflow (now **50 nodes**). Emits `intermediate_rail_check` event per session; `IntermediateRailDriftHigh` alert at >20% out-of-dist over 24h. Observe-only — does NOT block; soft-gate evaluation deferred ≥7 days post-data.
- **G2 — Grammar-constrained decoding** — JSON Schemas at [`scripts/lib/grammars/`](scripts/lib/grammars/) passed to Ollama via the `format` field when `OLLAMA_USE_GRAMMAR=1` (default on). Falls back to `format=json` on schema rejection. Circuit-breaker semantics preserved.
- **G3 — Team-formation skill** ([`.claude/skills/team-formation/SKILL.md`](.claude/skills/team-formation/SKILL.md) v1.0.0) + [`scripts/lib/team_formation.py`](scripts/lib/team_formation.py) propose a sub-agent roster per `(alert_category, risk_level, hostname)`. Build Prompt injects a `## Team Charter (advisory)` section; same JSON emitted as `team_charter` event_log row. KNOWN_AGENTS inventory enforced against `.claude/agents/*.md`.
- **G3 — Inference-Time-Scaling explicit budget** — `EXTENDED_THINKING_BUDGET_S` env var (+ optional per-category override) drives a `## Reasoning Budget` Build Prompt section; `its_budget_consumed` event captures observed turns/thinking_chars at session end.
- **G4 — Server-side session-replay endpoint** — new workflow [`claude-gateway-session-replay.json`](workflows/claude-gateway-session-replay.json) (id `lJEGboDYLmx25kBo`) ACTIVE. POST `/session-replay` accepts `{session_id, prompt}`, validates format, sqlite3-checks session existence inside the SSH command (the n8n task-runner sandbox blocks `child_process` in Code nodes), runs `claude -r`, returns JSON. HTTP 404 on unknown session, HTTP 400 on malformed input. `session_replay_invoked` event.

`event_log` schema bumped 1 → 4 (13 → **17** event types). 18 → 19 schema-versioned tables. 5 cron entries installed. 5 YouTrack issues all moved to Done via direct REST POST (the `tonyzorin/youtrack-mcp:latest` container's `update_issue_state` omits the `$type: "StateBundleElement"` discriminator — bug documented in `memory/feedback_youtrack_mcp_state_bug.md`).

Full state-of-the-platform reference: [`docs/agentic-platform-state-2026-04-29.md`](docs/agentic-platform-state-2026-04-29.md).

### QA Suite — 411/0 PASS (99.52%), 44 suite files

[`scripts/qa/run-qa-suite.sh`](scripts/qa/run-qa-suite.sh) runs **44 suite files** (~3–5 min) with JSON scorecard + summary output, guarded by a per-suite `QA_PER_SUITE_TIMEOUT` wrapper ([IFRNLLEI01PRD-724](docs/scorecard-post-agents-cli-adoption.md)) that caps any slow/wedged suite at 120 s and emits a synthetic FAIL record so the orchestrator never hangs silently:

- **Per-issue suites** — sanity + QA + integration for every adoption, plus 16 tests for the preference-iterating patcher ([-645](docs/runbooks/prompt-patch-trials.md)) and **12 tests for the CLI-session RAG pipeline** ([-646/-647/-648](docs/runbooks/cli-session-rag-capture.md)).
- **Writer coverage** — every script that `INSERT`s into a versioned table is asserted to stamp `schema_version=1`; same for all 5 n8n-workflow INSERT sites.
- **Pattern-by-pattern coverage** — 53 deny-pattern tests + 32 reject-pattern tests.
- **Payload shape** — every one of the 13 event types round-trips through the CLI + Python paths.
- **Concurrent-bump fuzz** — 8 parallel `handoff_depth.bump()` calls with no-lost-updates assertion. Surfaced and fixed a real race condition.
- **Mock HTTP server** ([`scripts/qa/lib/mock_http.py`](scripts/qa/lib/mock_http.py)) — stdlib-only fake ollama/anthropic endpoints for testing successful compaction offline.
- **6 e2e scenarios** — happy path (all 9 adoptions in one flow), cycle prevention, crash + rollback, schema forward-compat, envelope-to-subagent, compaction in handoff.
- **Benchmarks** — p95 latencies for event emit (111 ms), handoff bump (108 ms), envelope encode (76 ms), snapshot capture (86 ms), unified-guard hook (198 ms), migration on a 10K-row legacy DB (~200 ms).

---

## Architecture

```
Alert → n8n → OpenClaw (GPT-5.1, 7-21s) → Haiku Planner (+AWX) → Claude Code (Opus 4.6, 5-15min) → Human (Matrix)
```

| Component | Role |
|-----------|------|
| **[n8n](https://n8n.io/)** | 27 workflows — alert intake, session management, knowledge population, teacher-agent runner, server-side session-replay |
| **[OpenClaw](https://openclaw.com/)** v2026.4.11 (GPT-5.1) | Tier 1 — fast triage with 17 skills + Active Memory, handles 80%+ without escalation |
| **[Claude Code](https://docs.anthropic.com/)** (Opus 4.6) | Tier 2 — 11 sub-agents + master `chatops-workflow` phase-gate skill, ReAct reasoning, interactive [POLL] approval |
| **[AWX](https://www.ansible.com/awx)** | 41 Ansible playbooks wired into AI planner |
| **Matrix** (Synapse) | Human-in-the-loop — polls, reactions, replies |
| **Prometheus + Grafana** | 11 dashboards, 64+ panels, 16+ metric exporters, 4 alert-rule files |
| **OpenObserve** | OTel tracing — 39K spans, OTLP export |
| **Ollama** (RTX 3090 Ti) | Local embeddings — nomic-embed-text, query rewriting |
| **[Compiled Wiki](wiki/index.md)** | 44 articles from 7+ sources, daily recompilation |

## Safety — 7 Layers

The system investigates freely but **never executes infrastructure changes without human approval**:

1. **Claude Code hooks** — 7 injection detection groups + 59 destructive/exfiltration patterns blocked deterministically. Now emits the **3-behavior taxonomy** (`allow` / `reject_content` / `deny`) — recoverable patterns get a retry hint instead of a wall. Every rejection lands in `event_log` as a typed `tool_guardrail_rejection` event. The `evidence_missing` risk signal ([IFRNLLEI01PRD-718](docs/scorecard-post-agents-cli-adoption.md)) fires in-band when `CONFIDENCE ≥ 0.8` is claimed without a visible tool output block, forcing `[POLL]` and stripping unearned `[AUTO-RESOLVE]` markers.
2. **safe-exec.sh** — code-level blocklist that prompt injection cannot bypass
3. **exec-approvals.json** — 36 specific skill patterns (no wildcards)
4. **Evaluator-Optimizer** — Haiku screens high-stakes responses before posting
5. **Confidence gating** — < 0.5 stops, < 0.7 escalates
6. **Budget ceilings** — EUR 5/session warning, $25/day plan-only mode
7. **Credential scanning** — 16 PII patterns redacted, 39 credentials tracked with rotation

**Plus:** handoff depth counter forces `[POLL]` at depth ≥ 5 / hard-halts at ≥ 10, and any agent cycling back into its own chain is refused. An `audit-risk-decisions.sh` weekly invariant check rejects any `reject_content` event with an empty message (would blind the agent).

## Key Numbers

| Metric | Value |
|--------|-------|
| Operational activation audit | [A (91.8%)](docs/operational-activation-audit-2026-04-10.md) — 23 tables populated, 148K+ rows |
| Agentic design patterns | [21/21](docs/agentic-patterns-audit.md) at A+ ([tri-source audit](docs/tri-source-audit.md): 11/11 dimensions) |
| OpenAI Agents SDK adoption batch | **9/9 implemented** (issues 635–643), 45 files changed, 6 migrations, 4 new tables |
| Preference-iterating prompt patcher | **Live** (issue 645) — N-candidate A/B trials, Welch t-test, auto-promote |
| CLI-session RAG capture | **Live** (issues 646/647/648) — transcripts + tool-calls + knowledge extraction |
| QA suite | **468/0 PASS (99.57%)**, 2 benign skips, across **51 suite files** — ~3–5 min run, JSON scorecard, per-suite timeout guard. (411 baseline + 57 new NVIDIA G1-G4 tests across 7 suites.) |
| Skill-authoring scorecard vs `google/agents-cli` | [**4.94 / 5.00**](docs/scorecard-post-agents-cli-adoption.md) (was 3.94) — 13/16 dimensions at 5/5; 6 targeted gap dimensions closed |
| **NVIDIA DLI 12-dim scorecard** | [**A+ (4.83 / 5.0)**](docs/agentic-platform-state-2026-04-29.md) — was A (4.4) before 2026-04-29; 9/12 dimensions at A+, 1 at B (multi-tenant, intentional single-operator design); 9-source aggregate **A+ (4.79)** |
| Handoff envelope compression | **0.43% ratio** (176 KB input_history → 752 B on the wire, zlib+b64) |
| AWX/Ansible runbooks | 41 playbooks wired into Plan-and-Execute |
| Tool call instrumentation | 88,448 calls across 108 types, per-tool error rates + latency p50/p95 |
| OTel tracing | 39K spans → OpenObserve + Prometheus metrics |
| Typed session events | **17** event classes, queryable `event_log` table + Prom exporter (`event_log` schema_version=4) |
| GraphRAG knowledge graph | 360 entities, 193 relationships |
| Self-improving prompt patches | 5 active (auto-generated from eval scores) |
| Predictive risk scoring | 123 devices scanned daily, 23 at elevated risk |
| Holistic health check | [96%+](scripts/holistic-agentic-health.sh) — 142 checks (functional + e2e + cross-site) |
| Session-holistic E2E | **100% (23/23)** — covers 18 YT issues with before/after scoring |
| SQLite tables | **43** (42 + `long_horizon_replay_results` [-748]); 19 schema-versioned via the central `CURRENT_SCHEMA_VERSION` registry |
| Industry benchmark | [4.10/5.00 (82%)](docs/industry-benchmark-2026-04-15.md) -- 15 dimensions, 23 industry sources, E2E certified (39/39) |
| RAGAS golden set | 33 queries (15 hard-eval tagged) — multi-hop / temporal / negation / meta / cross-corpus |
| Weekly hard-eval (50-q) | judge-graded hit@5 = 0.90, p50 5.7s, p95 13.6s |
| RAGAS RAG quality | Faithfulness 0.88, Precision 0.86, Recall 0.88 (18 evaluations via Claude Haiku) |
| NIST behavioral telemetry | 5/5 AG-MS.1 signals active (action velocity, permission escalation, cross-boundary, delegation depth, exception rate) |
| Adversarial red-team | 54 tests (32 baseline + 22 adversarial), quarterly schedule, 12 bypass vectors hardened |
| Governance compliance | EU AI Act limited-risk assessment, QMS (Art. 17), NIST oversight boundary framework |
| Supply chain security | CycloneDX SBOM in CI, model provenance chain, agent decommissioning procedure |

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
| [Industry Benchmark](docs/industry-benchmark-2026-04-15.md) | 15-dimension scored assessment against 23 industry sources |
| [Skill-Authoring Scorecard](docs/scorecard-post-agents-cli-adoption.md) | 16-dimension scorecard vs `google/agents-cli` — 3.94 → 4.94, 6 gap dimensions closed |
| [Skill Versioning Runbook](docs/runbooks/skill-versioning.md) | Per-skill semver convention (patch/minor/MAJOR tied to the SKILL contract) + `audit-skill-versions.sh` |
| [Skills Index](docs/skills-index.md) | Auto-generated from all SKILL.md + agent frontmatter; drift-gated by `test-656` |
| [Agentic Platform State](docs/agentic-platform-state-2026-04-29.md) | Single source-of-record describing the post-NVIDIA-batch platform; merges the audit + cert + rescored docs into one canonical "where the system is right now" reference |
| [NVIDIA DLI Cross-Audit (source)](docs/nvidia-dli-cross-audit-2026-04-29.md) | Original 12-dimension cross-audit + 9-source master scorecard + P0/P1/P2 gap-closure roadmap |
| [NVIDIA P0+P1 Certification](docs/nvidia-p0-p1-certification-2026-04-29.md) | E2E certification: 57/57 G1-G4 tests, integration audits, live smoke fires, schema-bump trace, operator-gate closure |
| [NVIDIA DLI Cross-Audit (re-scored)](docs/nvidia-dli-cross-audit-rescored-2026-04-29.md) | Per-dimension delta after implementation — A (4.4) → A+ (4.83) |
| [EU AI Act Assessment](docs/eu-ai-act-assessment.md) | Risk classification + article mapping |
| [Tool Risk Classification](docs/tool-risk-classification.md) | 153 MCP tools classified (NIST AG-MP.1) |
| [Agent Decommissioning](docs/agent-decommissioning.md) | Per-tier lifecycle procedures |
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
5. **[google/agents-cli](https://github.com/google/agents-cli)** — reference implementation of skill-authoring discipline (phase-gate master skill, auto-generated skills index, "Do NOT use for X" anti-guidance, Shortcuts-to-Resist, Proving-Your-Work). Six gap dimensions adopted 2026-04-23 under [IFRNLLEI01PRD-712](docs/scorecard-post-agents-cli-adoption.md).

## License

Sanitized mirror of a private GitLab repository. Provided as-is for educational and reference purposes.

---

*Built by a solo infrastructure operator who got tired of waking up at 3am for alerts that an AI could triage.*
