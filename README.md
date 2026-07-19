# agentic-chatops

AI agents that triage infrastructure alerts, investigate root causes, and propose fixes — while a solo operator sleeps.

> **For the complete technical reference, see [README.extensive.md](README.extensive.md).**

![Architecture](docs/agentic-chatops.png)

## The Problem

One person. **310+ infrastructure objects** across 6 sites. 3 firewalls, 12 Kubernetes nodes, self-hosted everything. When an alert fires at 3am, there's no team to call. There never is.

## The Solution

Three agentic subsystems that handle the detective work — **ChatOps** (infrastructure), **ChatSecOps** (security), **ChatDevOps** (CI/CD) — built on [n8n](https://n8n.io/) orchestration, [Matrix](https://matrix.org/) as the human interface, and a tiered agent architecture (deterministic triage scripts → Claude Code → human). The human stays in the loop for every infrastructure change: the system never acts without a thumbs-up or poll vote, and since 2026-06-09 a remediation proposal **cannot even reach the approval poll** without a machine-computed consequence prediction attached (see Infragraph below).

---

## What Makes This Different

### Self-Improving Prompts — now with A/B trials (nobody else does this)

The system evaluates its own performance and auto-patches its prompts. Every session is scored by an [LLM-as-a-Judge](https://arxiv.org/abs/2306.05685) on 5 quality dimensions (`gemma3:12b` local-first since 2026-04-19; max-effort calibration via `gw-mistral-large` on the shared LiteLLM). When a dimension averages below threshold over 30 days, the **preference-iterating patcher** ([IFRNLLEI01PRD-645](docs/runbooks/prompt-patch-trials.md), 2026-04-20) generates **3 candidate instruction variants** (concise / detailed / examples) and assigns each future matching session to one arm via deterministic BLAKE2b hash — plus a no-patch control. A daily cron runs a one-sided Welch t-test once every arm reaches 15 samples; the winner is promoted only if it beats control by ≥ 0.05 points with `p < 0.1`. Otherwise the trial is aborted. Prompt-level policy iteration — no model weights are ever fine-tuned.

```
Session → LLM Judge (5 dims) → dimension trending below threshold
  → prompt-patch-trial.py generates 3 candidate variants + 1 control
  → future sessions hash-routed to arms → Welch t-test at 15+ samples/arm
  → winner promoted to config/prompt-patches.json (source: "trial:N:idx=I")
  → next eval cycle scores the new patch → loop continues
```

### Infragraph — a Causal World Model with a Non-Bypassable Prediction Gate (2026-06-09)

The system maintains a **causal dependency graph of the entire infrastructure** (361 nodes / 468 edges in the causal layer; 721 entities / 661 relationships in the combined GraphRAG+infragraph knowledge graph) seeded daily from five truth layers — live Proxmox cluster API (0.95 confidence), LibreNMS dependency parents (0.90), NetBox devices + physical cables (0.85–0.90), operator-declared edges, and a statistical incident-co-occurrence miner deliberately capped at 0.75 — with per-edge dynamics (expected alert cascades, propagation delays, recovery times) learned from 159 chaos experiments and the full triage history. This is a genuine **model-free → model-based shift enforced in control flow, not data**:

1. **Prediction is computed outside the LLM** — deterministic graph traversal (`infragraph-query.py`), called by the n8n orchestrator, never at the model's discretion.
2. **Prediction is mandatory** — the Runner commits a plan-hash-keyed prediction artifact *before* any approval poll; a remediation proposal without one is rewritten to `[POLL-WITHHELD:NO-PREDICTION]` and demoted to analysis-only. The kill-switch (`INFRAGRAPH_DISABLED=1`) fails the remediation lane **closed**.
3. **Verification is mechanical** — after execution, code (never the LLM that proposed the action) diffs observed alerts against the prediction and writes a `match / partial / deviation` verdict; deviation = surprise = never auto-resolve.

The eval is falsifiable by design: a degree-preserving **shuffled-graph negative control** runs alongside every prediction. The 2026-05-11 cascade backtest passed the criterion (control ratio 0.367 ≤ 0.5×) only after four honest iteration rounds, each driven by what the misses revealed. Suppression authority is granted **per rule by the operator** — the system proposes (control YouTrack issue with evidence table), the human approves, and closing the control issue instantly revokes. Runbook: [`docs/runbooks/infragraph.md`](docs/runbooks/infragraph.md).

### Autonomy-Forward Gate — Human as Circuit-Breaker, not Gatekeeper (2026-06-16)

Most "human-in-the-loop" systems assume the human is watching. Ours measured that the operator had voted on **almost none** of the approval polls in the prior two months — so the loop was a dead-end: reversible work stalled on a 30-min pause and genuinely-critical work paged no one. The fix is a 3-band risk gate (`classify-session-risk.py`): reversible, **Infragraph-prediction-backed** changes **auto-resolve**; a tightly-scoped critical set (HIGH-risk, P0-host blast, irreversible, model deviation) is the *only* thing that pages the operator by **SMS**. The safety floor is mechanical and non-configurable, and the whole gate flips on/off with a single `touch`/`rm` of a sentinel file — no workflow edit, instant kill-switch. Runbook: [`docs/runbooks/risk-based-auto-approval.md`](docs/runbooks/risk-based-auto-approval.md).

### Self-Verifying Reliability Layer — the system watches *itself* (2026-06-21)

The defining failure mode here was never a crash — it was **months of silent darkness** (the auto-resolve pipeline dead across 5 layers, scanners dark 5 weeks, an apiserver crash-looping 27 days) where nothing alerted because standard alerting treats *no data* as *no problem*. So the autonomy loop is now a continuously-verified subsystem:

- **Control-plane dead-man's-switch** — `gateway-watchdog.sh` emits a heartbeat every 5 min via a `trap … EXIT`; a Prometheus alert with an **`absent()` clause** pages by **SMS** if the heartbeat goes stale *or vanishes* (node_exporter/host down). It watches the thing that watches the pipeline.
- **Synthetic-incident canary** — a daily probe drives the real classify→predict spine end-to-end against an **isolated throwaway DB**, so it proves the spine is alive (3 stages + plan-hash coherence) while structurally being unable to pollute production, collide a real fail-closed gate, or trigger remediation. A tier-1 SMS fires if it ever leaks a row into the live DB.
- **False-auto-resolve governance** — the system measures its *own* root-cause discipline: a pattern it auto-resolved that recurs within 24h is a false-auto-resolve, and a repeat offender (≥3×/30d) is **auto-demoted** so the gate **escalates** it instead of auto-closing it again — automatically, reversibly (30-day expiry), with no human review (human-as-circuit-breaker, not gatekeeper). Intentionally-suppressed flappy alerts are excluded so it never re-introduces suppressed noise.
- **Bi-temporal knowledge** — infragraph edges and compiled-wiki facts carry a contradiction/supersession axis with time-since-confirmation decay (reporting-only — it flags edges for re-ratification, never silently changes a prediction).
- **Self-learning scheduled-reboot suppression (2026-06-29)** — hosts with a *discovered and promoted* reboot schedule (observe-≥2-boots-before-live, strict DST-correct cron windows) get their on-schedule reboot alerts suppressed before any session spawns, with a **two-phase verify** that reopens + pages if the boot wasn't a clean `systemd-reboot`. Safety floor: critical-never, allowlisted rules only, sentinel kill-switch, fail-open. Runbook: [`docs/runbooks/scheduled-reboot-suppression.md`](docs/runbooks/scheduled-reboot-suppression.md).

### Orchestrator Control-Plane — the system governs *itself* (2026-06-26)

The agentic federation grew to ~10 subsystems and **363 components** (320 at the 2026-06-26 landing) — Cronicle jobs, 57 n8n workflows, hooks, and the RAG / infragraph / teacher / chaos subsystems — coordinated only by convention, a shared SQLite, and the Prometheus textfile bus. Nothing *owned* their liveness as a set, and a 2026-06-25 audit proved the cost: MemPalace hooks, the OTel span sink, the tool-call log, and even the self-audit *itself* had run dark for weeks-to-months, each invisible because standard alerting reads *no data* as *no problem*. The fix is a thin **governing layer** ([IFRNLLEI01PRD-1421](docs/orchestration-findings-2026-06-26.md)) — three bricks built on the *existing* Prometheus + SQLite substrate, no platform rewrite (the [research](docs/orchestration-governance-research-2026-06-25.md) explicitly rejected adopting LangGraph / Temporal / Airflow / Dagster / Backstage):

- **Component Registry** ([`scripts/registry-check.py`](scripts/registry-check.py)) auto-discovers all **363 components** (199 cronicle-job + 77 prom-writer + 57 n8n-workflow + 28 db-table + 2 cron, as of 2026-07-08), each with a declared liveness expectation — **15 critical**, **0 critical-dark**, ~10 known-dark-by-design. The dark-component failure class is now caught **mechanically** (`RegistryCriticalDark`, tier-1 SMS) instead of by a manual quarterly sweep.
- **Interaction Graph** ([`scripts/interaction-graph.py`](scripts/interaction-graph.py)) static-analyzes **313 scripts** into a read/write asset graph (Dagster's model in ~250 lines): currently **0 GAPs** (the Session-End → reconcile orphan-consumer hole that silently darkened 4 analytics tables is closed), **0 cron-clashes**, and 23 multi-writer conflicts surfaced for review.
- **Orchestration Benchmark** ([`scripts/orchestration-benchmark.py`](scripts/orchestration-benchmark.py)) replays a synthetic incident stream through the isolated classify→predict spine and scores 4 orchestration invariants — score **1.0, 4/4**, including *safety-composition*: an irreversible incident is **never** auto-resolved, verified across the whole stream rather than case-by-case (`OrchestrationSafetyFailure`, tier-1).

All five rules are live in-cluster (infra MRs !347 + !348), and a **fault-injection drill proved the alerts actually fire**, not merely evaluate. The control-plane monitors its own three bricks — the who-watches-the-watcher gap is fully closed.

**Plane-A self-healing platform controller — the actuator half (2026-06-26).** The bricks *detect*; a Kubernetes-style **self-healing operator** ([`scripts/platform-controller.py`](scripts/platform-controller.py), `*/5`, armed) *acts* — closing the loop the absent human left open. It heals only **idempotent platform operations**: reactivate an inactive critical n8n workflow (it monitors all 57), re-run a failed safe-list Cronicle job, restart Cronicle, plus a consolidated watchdog heal-library. Heals are rate-limited by **exponential heal-backoff → CrashLoopBackOff → SMS escalation**, exactly as a k8s controller would. Crucially it draws the same Plane-A / Plane-B line k8s does between keeping pods alive and deciding app logic: **Plane-A keeps the *platform* alive (crons, Cronicle, bricks, writers, n8n); Plane-B is the *mission* (resize a VM, reboot a host, resolve an incident) — the controller NEVER touches B.** That stays the autonomy-forward lane's job. It consolidated the standalone watchdog into one operator, and carries its own dead-man.

**Cronicle scheduler — every job has run-history now (2026-06-26).** All cron jobs (180 at migration: 107 gateway + 72 agora-quant; **199 registered as of 2026-07-08**) migrated off raw crontab to a native **[Cronicle](https://github.com/jhuckaby/Cronicle)** scheduler: per-job run history, **per-job-death alerting** (the gap a flat crontab can't see — a crontab line that silently stopped firing looks identical to one that never existed), a REST API the registry seeds from, and auto-quarantine of a repeatedly-failing job.

A single **realtime control-plane dashboard** ([`grafana/orchestrator-control-plane.json`](grafana/orchestrator-control-plane.json), live at **[grafana.example.net/d/orchestrator-ctrl-plane](https://grafana.example.net/d/orchestrator-ctrl-plane)**) puts the whole thing on one pane of glass — the three bricks, the self-healing actuator, the scheduler, the decision plane, and the integrity / dead-man guarantees — **31 panels across 6 sections, refreshed every 30s**.

The decision log itself is now **tamper-evident**: every governance decision (830 logged, 78% auto-approved, as of 2026-07-08) is chained by **SHA-256** so any retroactive edit breaks the chain and pages by SMS (`GovernanceChainBroken`, tier-1). Observability is unified end-to-end — logging to self-hosted **OpenObserve**, **Langfuse** traces, and a fresh OTLP push — across **~1,700 metric series / 77 textfile writers / 74 in-repo alert rules**, backed by the dead-man heartbeat, the synthetic-incident canary, and a deploy-drift guard.

Benchmarked against industry orchestration standards, the control-plane scores **B+ (3.48 / 5)** across 11 dimensions — strongest on the things almost nobody enforces: **Plane-A / Plane-B separation enforced in code** (not policy), **reversibility-keyed human-in-the-loop**, and **independent mechanical verification** of every outcome.

The whole layer governs roughly **10 subsystems · 363 components · 199 jobs · 57 n8n workflows · 53 DB tables · ~97K LOC across 433 scripts** (2026-07-08) — and watches every one of them.

### Benchmarked Against the Anthropic + OpenAI Agent Guides — 12/14 dimensions at A (2026-06-26)

The platform was scored as two **separate, source-pure, adversarially-verified** scorecards against Anthropic's *Building Effective AI Agents* ([IFRNLLEI01PRD-1422](docs/scorecard-anthropic-2026-06-26.md)) and OpenAI's *A Practical Guide to Building Agents* ([-1423](docs/scorecard-openai-2026-06-26.md)), then improved against what the misses revealed. **12 of 14 dimensions now sit at A** ([synthesis](docs/benchmark-synthesis-2026-06-26.md)); the 2 remaining at B are **deliberate operator decisions, not gaps** — the rules blocklist is kept *off* the dispatched autonomous path, and the failure-threshold tripwire is a passive Matrix warning rather than an SMS page. Notable fixes shipped on the way: a model-router bug that counted markdown-table pipes instead of incident rows (pinning all 818 sessions to Opus — now low-risk alerts route to Sonnet behind a never-downgrade-risky floor), an OTLP trace export dead since ~March (a stale auth env shadowing the creds), a `MemoryMax` cgroup cap on dispatched sessions (the uncapped runaway class that wedged a host), and a concurrent-session tripwire that can now actually *kill* a runaway session on a token / cost / tool-call breach. **LLM/agent traces** now flow to a self-hosted **[Langfuse](docs/orchestration-governance-research-2026-06-25.md)** and **dead-man "job never ran" liveness** to a self-hosted **Healthchecks.io** — both composed alongside the bricks rather than replacing them.

### Model Orchestration — centralized provider/model selection, the easy way (2026-06-28)

Which model runs on which component is centralized, not scattered across hardcoded IDs — and flippable with one command. Two planes ([`docs/model-provenance.md`](docs/model-provenance.md), MRs !116–!120):

- **Claude Code (subscription, flat-rate):** every `claude` invocation — dispatched remediation, `agent_as_tool`, `mr-review`, `parallel-dev`, interactive — is routed by a single switch, [`scripts/claude-provider.sh`](scripts/claude-provider.sh) `{zai|anthropic|status}`, which edits `~/.claude/settings.json`. Two providers: **Z.ai** (`glm-5.2` Opus-equivalent for `--model opus`, `glm-4.7` Sonnet-equivalent) and **Anthropic Max** (OAuth subscription). `status` is authoritative for the live toggle — the operator flips it, so no document should claim a permanent default. Subscription auth can't proxy through a gateway, hence the direct route.
- **Eval layer (per-token API):** the LLM judge, RAGAS, and the frontier cross-check route through the **shared [LiteLLM](https://github.com/BerriAI/litellm)** proxy to **Mistral** (`mistral-large-latest`) + **DeepSeek** (`deepseek-v4-pro`), with local-Ollama fallback (never Anthropic). Per-component spend is tracked via LiteLLM tags. Per the operator directive, **Mistral + DeepSeek are the only paid per-token APIs** — **zero Anthropic per-token spend**.
- **Local ($0):** judge / RAG synth-rewrite / embeddings / rerank / teacher on Ollama (`gemma3:12b`, `qwen2.5:7b`, `nomic-embed-text`, `bge-reranker-v2-m3`).

The single source of truth is [`config/model-routing.json`](config/model-routing.json) (resolved by [`scripts/lib/model_routing.py`](scripts/lib/model_routing.py)); the LiteLLM models+key are provisioned idempotently by [`scripts/litellm-gateway-setup.sh`](scripts/litellm-gateway-setup.sh). To see "which model on which component now": `python3 scripts/lib/model_routing.py --list` for the intended-default catalog, plus `bash scripts/claude-provider.sh status` for the **live** Claude-Code provider (authoritative — the registry shows the intended default, `status` reflects the active `settings.json` toggle). This supersedes the old `cc-cc`/`oc-*` frontend/backend-pairing modes (OpenClaw retired).

### Renovate MR Autonomy Lane — hands-off dependency updates with per-class gates (2026-07-06)

A self-hosted [Renovate CE](https://github.com/mend/renovate-ce-ee) instance opens dependency-update MRs across the IaC estate; a dedicated n8n lane classifies each MR (`classify-renovate-mr.py` + a stateful-services manifest) and **auto-merges + deploys + post-merge-verifies routine docker digest/patch bumps** end-to-end — deterministic structural review, hard CI-green gate, snapshot-before-merge for stateful services, and a `*/15` reconciler. Anything consequential (Kubernetes, Helm, Terraform, OpenBao, Dockerfiles, majors) goes to a `[POLL]` + operator SMS instead — never auto-applied blind. Post-merge verification is 3-way: healthy / confirmed-bad → revert / **inconclusive → escalate, never auto-revert**. Armed via the `~/gateway.renovate_autonomy` sentinel; first hands-off merges ran 2026-07-07. Runbook: [`docs/runbooks/renovate-mr-autonomy.md`](docs/runbooks/renovate-mr-autonomy.md).

### AI Planner Wired to Proven Ansible Playbooks

Before Claude Code investigates, a fast-tier planner (sonnet-tier, resolved by the centralized Model Orchestration layer) generates a 3-5 step investigation plan. The planner queries AWX for matching Ansible playbooks from **41 proven templates** (maintenance, cert sync, K8s drain, PVE updates, DMZ deployments). Plans naturally include "Run AWX Template 64 with dry_run=true" as remediation steps — bridging AI reasoning with proven automation.

### Predictive Alerting

Instead of only reacting after alerts fire, the system queries LibreNMS API daily for **trending risk** across both sites. Devices are scored on disk usage trends, alert frequency, and health signals. A daily top-10 risk report posts to Matrix before problems become incidents.

### 5-Signal RAG + GraphRAG + Staleness + Temporal Filter + mtime-Sort

Retrieval uses [Reciprocal Rank Fusion](docs/industry-agentic-references.md#5-rag--retrieval-optimization) across **5 signals** (semantic + keyword + [compiled wiki](wiki/index.md) + [MemPalace](https://github.com/milla-jovovich/mempalace) transcripts + chaos baselines), plus a **GraphRAG + infragraph knowledge graph** (721 entities, 661 relationships). Retrieval short-circuits via two intent detectors: **temporal window** ("last 48h", "72 hours ending YYYY-MM-DD") filters wiki on `source_mtime`, and **mtime-sort intent** ("name any three memory files created in the last 48h") bypasses semantic retrieval entirely and returns an mtime-ranked window. Results older than 7 days get age-proportional staleness warnings. A **local `qwen2.5:7b` synth step** composes cross-chunk answers when top rerank < threshold (rag-synth → Ollama under the centralized Model Orchestration layer). `SYNTH_HAIKU_FORCE_FAIL` env is retained for the failure-mode fallback path (429 / auth / timeout / network / empty).

### Karpathy-Style Compiled Knowledge Base

Following [Andrej Karpathy's LLM Knowledge Bases pattern](https://x.com/karpathy/status/2039805659525644595): raw data from 7+ sources (575 memory files, 35 CLAUDE.md files, ~2,500 incidents, 107 docs, 22 skills, ~5,200 lab docs, as of 2026-07-08) is compiled into a browsable [88-article wiki](wiki/index.md) with auto-maintained indexes, daily SHA-256 incremental recompilation, and contradiction detection. All articles embedded into RAG as the 3rd fusion signal.

### Full Observability Stack with OTel

333K+ tool calls instrumented across 159 tool types with per-tool error rates and latency percentiles (2026-07-08). OTel spans exported to OpenObserve (OTLP; ~14K retained locally in SQLite). 13 Grafana dashboards (90+ panels, incl. the realtime orchestrator control-plane overview) covering ChatOps, ChatSecOps, ChatDevOps, and trace analysis. Infrastructure commands logged per-device in `execution_log`.

### Formal Evaluation Pipeline

58 scenarios across [3 eval sets](docs/evaluation-process.md) (22 regression + 20 discovery + 16 holdout) + 54 adversarial red-team tests. [Prompt Scorecard](scripts/grade-prompts.sh) grades 19 surfaces daily on 6 dimensions. [Agent Trajectory](scripts/score-trajectory.sh) scoring on 8 infra / 4 dev steps. A/B variant testing (react_v1 vs react_v2). CI eval gate blocks bad merges. Monthly eval flywheel cycle.

### Structured Agentic Substrate — 9 adoptions from the OpenAI Agents SDK

The 2026-04-20 audit of [openai/openai-agents-python](https://github.com/openai/openai-agents-python) flagged 11 gaps; 9 were implemented (issues [IFRNLLEI01PRD-635..643](docs/runbooks/)). The system now has a versioned, typed, recoverable substrate the old string-based Matrix pipeline couldn't offer:

- **Schema versioning** on 9 session/audit tables + a central registry ([`scripts/lib/schema_version.py`](scripts/lib/schema_version.py)) mirroring the SDK's `RunState.CURRENT_SCHEMA_VERSION` / `SCHEMA_VERSION_SUMMARIES` pattern. Writers stamp `schema_version=CURRENT`; readers `check_row()` fail-fast on future versions.
- **13 typed events** ([`session_events.py`](scripts/lib/session_events.py)) in a new `event_log` table — `tool_started/ended`, `handoff_requested/completed/cycle_detected/compaction`, `reasoning_item_created`, `mcp_approval_*`, `agent_updated`, `message_output_created`, `tool_guardrail_rejection`, `agent_as_tool_call`. Replaces free-form Matrix strings with Grafana-queryable structured telemetry.
- **Per-turn lifecycle hooks** — `session-start.sh`, `post-tool-use.sh`, `user-prompt-submit.sh`, `session-end.sh` (new — the `on_final_output` equivalent) feeding a `session_turns` table with per-turn cost, tokens, duration, tool count.
- **3-behavior tool-guardrail taxonomy** (`allow` / `reject_content` / `deny`) in [`unified-guard.sh`](scripts/hooks/unified-guard.sh) + `audit-bash.sh` + `protect-files.sh`. `reject_content` sends Claude a retry hint instead of a wall; `deny` hard-halts. Every rejection is a typed event.
- **`HandoffInputData` envelope** ([`scripts/lib/handoff.py`](scripts/lib/handoff.py)) — zlib-compressed base64 payload carrying `input_history`, `pre_handoff_items`, `new_items`, `run_context`. 176 KB history → **752 B on the wire (0.43% ratio)**. Eliminates the "re-derive context via RAG" cost on escalation.
- **Transcript compaction** ([`scripts/compact-handoff-history.py`](scripts/compact-handoff-history.py)) — opt-in per escalation. Local `gemma3:12b` (fast-tier fallback routed via the Claude-Code plane); circuit-breaker aware.
- **Agent-as-tool wrapper** ([`scripts/agent_as_tool.py`](scripts/agent_as_tool.py)) — wraps the 11 sub-agent definitions as callable tools so the orchestrator LLM can conditionally invoke them in the ambiguous-risk (0.4–0.6) band, complementing our deterministic routing.
- **Handoff depth counter + cycle detection** ([`scripts/lib/handoff_depth.py`](scripts/lib/handoff_depth.py)) — `handoff_depth >= 5` forces `[POLL]`; `>= 10` hard-halts; any agent twice in the chain is refused and logged as `handoff_cycle_detected`.
- **Immutable per-turn snapshots** ([`scripts/lib/snapshot.py`](scripts/lib/snapshot.py)) — a snapshot is captured BEFORE each mutating tool call (`Bash`, `Edit`, `Write`, `Task`; read-only tools skipped); `rollback_to(id)` restores any prior `sessions` row. 7-day retention.

Four new SQLite tables (`event_log`, `handoff_log`, `session_state_snapshot`, `session_turns`) bring the total to 35. Migrations 006–011 apply idempotently on both fresh and legacy DBs. Two follow-ups since then — the A/B prompt patcher ([IFRNLLEI01PRD-645](docs/runbooks/prompt-patch-trials.md), `prompt_patch_trial` + `session_trial_assignment`) and the CLI-session RAG capture pipeline ([-646](docs/runbooks/cli-session-rag-capture.md)/[-647](docs/runbooks/cli-session-rag-capture.md)/[-648](docs/runbooks/cli-session-rag-capture.md), no new tables; chunks + tool calls + knowledge rows tagged `issue_id='cli-<uuid>'` on the existing schema) — the live total is now **53** tables / **31** schema-versioned (2026-07-08).

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

### QA Suite — 834 known-passing tests, 85 suite files

[`scripts/qa/run-qa-suite.sh`](scripts/qa/run-qa-suite.sh) runs **85 suite files** (78 suites + 7 e2e, ~7 min under full load; last full run 2026-07-08: **834 pass / 0 fail / 2 skip**) with JSON scorecard + summary output, guarded by a per-suite `QA_PER_SUITE_TIMEOUT` wrapper ([IFRNLLEI01PRD-724](docs/scorecard-post-agents-cli-adoption.md)) that caps any slow/wedged suite at 120 s (a suite may declare a raise-only `# QA_SUITE_TIMEOUT: <n>` header for load headroom) and emits a synthetic FAIL record so the orchestrator never hangs silently:

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
Alert → n8n receiver → Tier-1 deterministic triage (suppression + infragraph context, seconds)
      → Fast-tier Planner (+AWX) → Infragraph predict gate → Claude Code (5-15min) → Human (Matrix)
```

*(cc-cc mode, default and only live mode since 2026-04-29: receivers dispatch directly to Claude Code on the runner host; the earlier OpenClaw tier was retired 2026-04-29 and its LXC (VMID_REDACTED) destroyed — it is not a dormant fallback and cannot be restored without rebuilding from scratch.)*

| Component | Role |
|-----------|------|
| **[n8n](https://n8n.io/)** | 57 active workflows on the instance (27 exported in-repo) — alert intake, session management, knowledge population, teacher-agent runner, server-side session-replay, Renovate MR autonomy |
| **Tier-1 triage scripts** | Deterministic suppression (dedup → blast-radius fold → known-pattern → active-memory) + NetBox/infragraph/chaos context assembly — runs in seconds, no LLM. Per-incident auto-resolve baseline: 41.6% (30d, frozen 2026-06-09) |
| **[Claude Code](https://docs.anthropic.com/)** | Tier 2 — 11 sub-agents + master `chatops-workflow` phase-gate skill, ReAct reasoning, interactive [POLL] approval gated on committed infragraph predictions |
| **[AWX](https://www.ansible.com/awx)** | 41 Ansible playbooks wired into AI planner |
| **Matrix** (Synapse) | Human-in-the-loop — polls, reactions, replies |
| **Prometheus + Grafana** | 13 dashboards, 90+ panels, 77 textfile metric writers, 6 alert-rule files (74 rules) |
| **OpenObserve** | OTel tracing (OTLP export) + unified logging; Healthchecks.io + Langfuse on the same host |
| **Ollama** (RTX 3090 Ti) | Local embeddings — nomic-embed-text, query rewriting |
| **[Compiled Wiki](wiki/index.md)** | 88 articles from 7+ sources, daily recompilation |

## Safety — 7 Layers

The system investigates freely. As of 2026-06-16 (the **autonomy-forward gate**, [IFRNLLEI01PRD-1102](docs/runbooks/risk-based-auto-approval.md)) it **auto-resolves reversible, prediction-backed changes** — the operator is a *circuit-breaker*, not a gatekeeper, paged by SMS only for genuinely critical cases — but **never auto-executes an irreversible, destructive, or unpredicted change**; those always require a human. The bands: **AUTO** (low / reversible+predicted → `[AUTO-RESOLVE]`), **AUTO_NOTICE** (reversible on a P0 host or wide blast → auto **+ parallel SMS**), **POLL_PAUSE** (HIGH / irreversible / deviation / no-prediction / jailbreak → poll + pause + SMS). Enabled via `~/gateway.autonomy_forward` + `~/gateway.autonomy_session_sms` sentinels; `rm` reverts to byte-identical legacy instantly. The layers below still apply:

1. **Claude Code hooks** — 7 injection detection groups + 59 destructive/exfiltration patterns blocked deterministically. Now emits the **3-behavior taxonomy** (`allow` / `reject_content` / `deny`) — recoverable patterns get a retry hint instead of a wall. Every rejection lands in `event_log` as a typed `tool_guardrail_rejection` event. The `evidence_missing` risk signal ([IFRNLLEI01PRD-718](docs/scorecard-post-agents-cli-adoption.md)) fires in-band when `CONFIDENCE ≥ 0.8` is claimed without a visible tool output block, forcing `[POLL]` and stripping unearned `[AUTO-RESOLVE]` markers.
2. **safe-exec.sh** — code-level blocklist that prompt injection cannot bypass
3. **exec-approvals.json** — 36 specific skill patterns (no wildcards)
4. **Evaluator-Optimizer** — a fast-tier model screens high-stakes responses before posting (Sonnet-equivalent `glm-4.7` via the Z.ai Claude-Code plane)
5. **Confidence gating** — < 0.5 stops, < 0.7 escalates
6. **Budget ceilings** — EUR 5/session warning, $25/day plan-only mode
7. **Credential scanning** — 16 PII patterns redacted, 39 credentials tracked with rotation

**Plus (2026-06-16, the autonomy-forward gate, IFRNLLEI01PRD-1102):** the binary "auto only if `risk==low`" gate is now a 3-band model so reversible+prediction-backed remediation auto-resolves (the operator stopped voting on the Matrix polls, so the old gate stranded ~56% of sessions on a 30-min pause and paged no one). The safety floor is **non-configurable**: Infragraph deviation, irreversible-destructive ops (re-tagging closed real gaps — `terraform destroy` was MIXED, `mkfs`/`zpool destroy`/`dropdb` were unmatched), no-committed-prediction, partial verdict, jailbreak, and P0-reboot all stay `[POLL]`+pause+SMS. Auto-resolve keys on the fail-CLOSED prediction gate, not the fail-OPEN advisory; the weekly `audit-risk-decisions.sh` invariant is band-aware and prints the `rm ~/gateway.autonomy_forward` kill-switch on any violation.

**Plus (2026-06-09, the model-based invariant):** a remediation proposal cannot reach the approval poll without a committed machine prediction (`[POLL-WITHHELD:NO-PREDICTION]` demotion otherwise — fail-closed, enforced in the live Runner, in bypass-attempt QA driven against the deployed workflow export, and in the weekly audit), and post-execution outcomes are adjudicated by code, not by the session that proposed them (`match / partial / deviation` verdicts; deviation never auto-resolves). Handoff depth counter forces `[POLL]` at depth ≥ 5 / hard-halts at ≥ 10, and any agent cycling back into its own chain is refused. The `audit-risk-decisions.sh` weekly invariant check also rejects any `reject_content` event with an empty message (would blind the agent).

## Key Numbers

*Volatile counts below verified as of 2026-07-08; audit/scorecard rows reference their dated reports.*

| Metric | Value |
|--------|-------|
| Operational activation audit | [A (91.8%)](docs/operational-activation-audit-2026-04-10.md) — 23 tables populated, 148K+ rows |
| Agentic design patterns | [21/21](docs/agentic-patterns-audit.md) at A+ ([tri-source audit](docs/tri-source-audit.md): 11/11 dimensions) |
| OpenAI Agents SDK adoption batch | **9/9 implemented** (issues 635–643), 45 files changed, 6 migrations, 4 new tables |
| Preference-iterating prompt patcher | **Live** (issue 645) — N-candidate A/B trials, Welch t-test, auto-promote |
| CLI-session RAG capture | **Live** (issues 646/647/648) — transcripts + tool-calls + knowledge extraction |
| QA suite | **834 pass / 0 fail / 2 skip** across **85 suite files** (78 suites + 7 e2e; full run 2026-07-08) — ~7 min run, JSON scorecard, per-suite timeout guard with raise-only per-suite override |
| Skill-authoring scorecard vs `google/agents-cli` | [**4.94 / 5.00**](docs/scorecard-post-agents-cli-adoption.md) (was 3.94) — 13/16 dimensions at 5/5; 6 targeted gap dimensions closed |
| **NVIDIA DLI 12-dim scorecard** | [**A+ (4.83 / 5.0)**](docs/agentic-platform-state-2026-04-29.md) — was A (4.4) before 2026-04-29; 9/12 dimensions at A+, 1 at B (multi-tenant, intentional single-operator design); 9-source aggregate **A+ (4.79)** |
| **Infragraph backtest (2026-05-11 cascade)** | 34.5% alert / **38.2% escalation coverage**, shuffled-control ratio **0.367 ≤ 0.5×** — falsifiable criterion PASSED |
| **Per-incident auto-resolve baseline** | **41.6%** (30d, frozen 2026-06-09 — counting incidents, not events) |
| Infragraph prediction gate | Live in the Runner: 0 paths to an approval poll without a committed plan-hash-keyed prediction; first operator-approved suppression rule active |
| **Autonomy-forward gate (2026-06-16)** | **Live + enabled** (issue 1102) — 3 bands (AUTO / AUTO_NOTICE+SMS / POLL_PAUSE+SMS); reversible+predicted auto-resolves, critical-only SMS; sentinel kill-switch; band-aware audit invariant; 14/14 QA |
| Handoff envelope compression | **0.43% ratio** (176 KB input_history → 752 B on the wire, zlib+b64) |
| AWX/Ansible runbooks | 41 playbooks wired into Plan-and-Execute |
| Tool call instrumentation | 333K+ calls across 159 types, per-tool error rates + latency p50/p95 |
| OTel tracing | OTLP export to OpenObserve (~14K spans retained locally) + Langfuse per-session traces |
| Typed session events | **17** event classes, queryable `event_log` table + Prom exporter (`event_log` schema_version=4) |
| GraphRAG + infragraph knowledge graph | 721 entities, 661 relationships (5 truth layers + learned dynamics); infragraph causal layer 361 nodes / 468 edges |
| Self-improving prompt patches | 2 active trials (Global-Workspace directives, headroom dims) + 1 promoted patch; the original 5 aborted with no data (pre-MR!155/156 issue_id bug) |
| Predictive risk scoring | 123 devices scanned daily, 23 at elevated risk |
| Holistic health check | [98% on 2026-07-08](scripts/holistic-agentic-health.sh) — 172 checks across 43 sections, 0 fail (functional + e2e + cross-site; run `--json` for the live number) |
| Session-holistic E2E | **100% (23/23)** — covers 18 YT issues with before/after scoring |
| SQLite tables | **53**; **31** schema-versioned via the central `CURRENT_SCHEMA_VERSION` registry |
| Industry benchmark | [4.10/5.00 (82%)](docs/industry-benchmark-2026-04-15.md) -- 15 dimensions, 23 industry sources, E2E certified (39/39) |
| RAGAS golden set | 33 queries (15 hard-eval tagged) — multi-hop / temporal / negation / meta / cross-corpus |
| Weekly hard-eval (50-q) | judge-graded hit@5 = 0.90, p50 5.7s, p95 13.6s |
| RAGAS RAG quality | Faithfulness 0.88, Precision 0.86, Recall 0.88 (18 evaluations via `gw-deepseek` through the shared LiteLLM) |
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
| [Compiled Wiki](wiki/index.md) | 78 auto-compiled articles |
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
| [Infragraph Runbook](docs/runbooks/infragraph.md) | Causal dependency graph: query cheatsheet, reseed, alert response, per-phase rollback |
| [Risk-Based Auto-Approval / Autonomy-Forward Gate](docs/runbooks/risk-based-auto-approval.md) | The 3-band gate (AUTO / AUTO_NOTICE / POLL_PAUSE), safety floor, sentinel enable/kill-switch, session→SMS path, band-aware audit invariant |
| [Gateway Watchdog Dead-Man's-Switch](docs/runbooks/gateway-watchdog-deadman.md) | Heartbeat metrics + `absent()`-clause SMS alerts that page when the control-plane watchdog itself goes dark (-1152) |
| [Synthetic-Incident Canary](docs/runbooks/synthetic-incident-canary.md) | Isolated-DB end-to-end spine probe (classify→predict), leak guard, alert response, kill switch (-1154) |
| [Infragraph Plan of Record](docs/plans/infragraph-implementation-plan.md) | The model-based invariant, eval thresholds, phased rollout design |
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
