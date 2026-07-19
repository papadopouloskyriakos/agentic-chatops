# Orchestrator / Controller-Plane Benchmark — claude-gateway Agentic System

**Date:** 2026-06-26
**Scope:** The control/orchestration plane governing the claude-gateway agentic federation (~100+ crons / Cronicle jobs, 56–58 n8n workflows, hooks, RAG/infragraph/teacher/chaos subsystems, the platform-controller self-healing operator, and the 3 orchestrator bricks) measured against current industry standards for production agentic control planes.
**Method:** 11 dimensions, each scored against a named A-grade industry standard, then **adversarially re-verified** file-by-file and live-query-by-live-query. The authoritative per-dimension number is `verdict.adjusted_score_0_5`. Overall = unweighted mean of the 11 adjusted scores.

---

## Overall

| | |
|---|---|
| **Overall grade** | **B+** |
| **Overall score** | **3.48 / 5.0** (mean of 11 adjusted dimensions) |
| **Shape** | Best-in-class SAFETY/SUPERVISION spine on a lagging TELEMETRY/IDENTITY foundation |

The system is at or near the A-grade frontier on the four hardest, rarest control-plane problems — least-agency self-healing, reversibility-keyed human gating, independent mechanical verification, and silent-monitor-death meta-monitoring — and materially behind on three plumbing problems: trace delivery, per-agent identity, and model routing. The grade is an honest average of genuine A-grade halves with genuine C/D-grade halves, not a flat middling system.

---

## Scorecard

| Dimension | Score / 5 | Grade | One-line verdict |
|---|---|---|---|
| Liveness & Self-Healing (Reconciliation Plane) | 4.0 | A- | Genuine k8s-faithful reconcile loop with CrashLoopBackOff→SMS, live-proven; one gap is flat rate-limit vs exponential backoff. |
| Separation of Concerns (Control vs Mission Plane) | 4.5 | A | Most k8s-faithful element; actuator structurally refuses the mission lane, weekly compositional test; capped only by no hard runtime sandbox. |
| Orchestration & Coordination Topology | 3.0 | B | Handoff-vs-tools chosen intentionally, but no named swappable topology set and the multi-agent path is unreachable in production. |
| Durability, State & Recovery | 3.0 | B | Solid checkpoint tier + live per-turn snapshots, but no effectively-once and the recovery loop is OPEN (snapshots never used to resume). |
| Failure Handling & Resilience | 3.5 | B+ | A-grade circuit breakers + irreversible floor, but the trajectory tripwire is not enforced in the committed path and no exponential backoff/idempotency keys. |
| Supervision, Termination & Verification (MAST) | 4.3 | A- | Near best-in-class independent verification + layered termination; below A for missing named-supervisor pattern + soft role contract. |
| Human-in-the-Loop & Reversibility Guardrails | 4.6 | A | The architecture's spine: 3-band gate, fail-CLOSED withholding, durable pause/resume, separate screening model. |
| Observability & Distributed Tracing | 2.5 | C+ | Right intent, partial scaffolding, but OTLP delivers 0.1% of spans, traces 1.1% of sessions, went dark ~2 months. |
| Evaluation & Benchmarking | 3.9 | B+ | Real two-cadence/three-altitude regime + two blocking CI gates; docked for LLM-vs-LLM judge calibration and a non-functional model router. |
| Governance, Auditability & Regulatory | 3.0 | B- | Rich trail + EU AI Act assessment, but NOT tamper-evident (no hash-chain) and OWASP Agentic-2026 ASI01-10 not red-teamed. |
| Security & Least-Agency (Identity, Meta-Monitoring) | 3.0 | B- | World-class meta-monitoring averaged with a C-grade identity half (one shared SSH id, skip-permissions, no sandbox/mTLS). |

---

## Per-Dimension Detail

### 1. Liveness & Self-Healing (Reconciliation Plane) — 4.0 / A-

**Industry standard.** The Kubernetes operator/controller pattern: many small single-responsibility level-based loops that tolerate perpetual change (never require a static end-state), driven by health probes with a `failureThreshold` debounce, restarts on **exponential backoff capped at a ceiling** (10s→20s→…→300s, reset after a clean run) with a terminal CrashLoopBackOff state that stops auto-restarting and surfaces for a human, heals capped per interval so the human becomes the circuit-breaker on breach, and self-healing that restarts infrastructure but never reaches into application/mission logic.

**How this system measures up.** `scripts/platform-controller.py` (278 LOC, a `*/5` Cronicle job, verified ARMED with a fresh heartbeat) is a genuine level-based loop: it reads observed state from authoritative substrates (n8n API for 58 workflows, Cronicle `event_failure_stats`/`schedule`, `cronicle_metrics.prom`), compares against a small declared desired set (8 `CRITICAL_WF` + `SAFE_RERUN_HINTS`), and actuates bounded heals via four single-responsibility sub-reconcilers (`reconcile_n8n` / `reconcile_cronicle_jobs` / `reconcile_cronicle_service` / `reconcile_watchdog_heals`). The CrashLoopBackOff analog is **live-proven** — the audit log shows the literal sequence `3x HEALED write-test-metrics.sh → ESCALATE "heal cap hit → human needed"`, routing to a tier-1 Twilio SMS. Who-watches-the-watcher is closed: `prom:platform_controller critical=true` in the 320-component registry → `RegistryCriticalDark` (tier-1) pages if the healer dies, plus a dead-man heartbeat with an `absent()` clause, and maintenance mode keeps the heartbeat alive while suppressing heals.

**Score: 4.0 / A- (verdict: uphold, evidence strong).**

**Strengths.** Plane-A/Plane-B boundary enforced in code; live-proven terminal-escalate state; who-watches-the-watcher closed three ways; change-tolerant single-responsibility reconcilers; ships dark with a reversible kill switch.

**Concrete gaps.** The backoff is a **flat sliding 3/hr rate-limit** (`PLATFORM_HEAL_CAP`), not exponential-with-cap; no explicit clean-run reset (`_act()` records every attempt regardless of outcome); the loop is cron-driven (5-minute blind window) not an always-resident daemon; failure-threshold debounce is coarse (single inactive read triggers reactivation); heal coverage is narrow by design (n8n + Cronicle + watchdog library only — RAG/Ollama/DB observed-only).

> **Citation note (does not move the score):** evidence cites `PlatformControllerEscalation`/`PlatformControllerStale` at `agentic-health.yml:206-235,375-390`, but those lines are actually `GatewayWatchdogHeartbeatStale` and `RegistryCriticalDark`; the PlatformController-named alerts live in the infra repo (MR !351) and were unverifiable here. The escalation→SMS guarantee still holds substantively through the verified `prom:platform_controller critical=true → RegistryCriticalDark` path.

---

### 2. Separation of Concerns (Control Plane vs Mission Plane) — 4.5 / A

**Industry standard.** A bright line separates Plane-A (keep the platform alive) from Plane-B (the mission). Mirrors the Kubernetes boundary — the platform keeps agents alive and maintains replica counts but does not decide application behavior; deterministic 'self-healing infrastructure' (safe) is kept categorically distinct from probabilistic 'self-healing application logic' (dangerous); the topology is explicitly named and each specialist's responsibility is narrow and non-overlapping.

**How this system measures up.** The boundary is real in code. `platform-controller.py`'s only reference to any mission verb is a docstring **disclaiming** them (`grep -niE 'resize|reboot|qm set|pvesh|auto-resolve|kubectl delete|claude -p|ssh|dispatch'` returns only that line). Its entire actuation surface is four idempotent, reversible, low-blast-radius ops. The mission is a categorically separate 1106-line module (`classify-session-risk.py`) with a hard `IRREVERSIBLE_PATTERNS` floor (mkfs/wipefs/dd-of-dev, zpool/zfs destroy, dropdb, kubectl delete pvc/pv/ns/secret, docker volume prune → forced high → can never reach AUTO). The two modules have **zero cross-references in either direction** (verified bidirectionally). The topology is explicitly named and non-overlapping: 3 bricks OBSERVE, the controller ACTS, the mission gate DECIDES. `orchestration-benchmark.py`'s I1 invariant replays 5 destructive incidents weekly against an isolated tmp DB + tmp HOME and hard-fails if any irreversible op is auto-resolved.

**Score: 4.5 / A (verdict: uphold, evidence strong).** Registry counts match the score exactly (320 components / 12 critical), and the score honestly corrected the stale 239 in the memory index rather than rounding to a familiar number.

**Strengths.** Line enforced in code not docs; mission plane physically separate with hard floor; boundary mechanically tested across the composition weekly; who-watches-the-watcher closed; faithful k8s analogy in actuation guardrails; explicit deterministic-infra-vs-probabilistic-application distinction in the runbook.

**Concrete gaps.** No hard runtime sandbox prevents a future edit from adding a Plane-B verb to the controller binary (I1 guards the classifier spine, not the controller); the 'single Plane-A operator' claim is mid-transition (controller runs alongside the watchdog heal-library; careful watchdog retirement is still OPEN); `SAFE_RERUN_HINTS` is substring-matched on title-or-path (a heuristic allowlist, not an author-declared idempotency contract); a doc-vs-memory maturity inconsistency on arming/consolidation state (concerns state, not the cleanliness of the line).

---

### 3. Orchestration & Coordination Topology — 3.0 / B

**Industry standard.** The control plane selects a deliberate named coordination topology (Sequential / Concurrent / Group-Chat / dynamic Handoff / Supervisor-Magentic) exposed through a unified swappable `invoke` interface, chooses handoff (transfer of ownership) vs agents-as-tools (manager retains ownership) intentionally, and defaults to the least-autonomous design that works (single agent / workflow; splitting is a justified evidence-backed step).

**How this system measures up.** The system makes **one** topology distinction at A-grade and intentionally — Manager (agents-as-tools) vs Decentralized (handoff) — and chose Manager, structurally enforced: all 11 `.claude/agents/*.md` exclude Edit/Write/MultiEdit (transfer-of-control is impossible), and `agent_as_tool.py:19-21` explicitly scopes itself as ADDITIONAL to the deterministic Task path. Default-to-least-autonomous is real (`isComplexSession` keeps simple alerts single-agent; GEPA ships dark; single `claude -p` per alert with proper exit conditions). **But** the core A-grade markers are absent: no named topology selector (`grep` for `select_topology`/`OrchestrationPattern` returns nothing — `team_formation.py` selects rosters, the 'who', never topologies, the 'how'), no unified swappable invoke interface, no Magentic/task-ledger, and the one multi-agent topology is **unreachable on the dispatched path** (dispatched cwds have no `.claude/agents`; the system's own data shows 0 Task tool_use across 331 sessions and 0 `team_charter` across 818).

**Score: 3.0 / B (verdict: uphold, evidence strong).** The standout work (the Plane-A/B k8s reconcile loop, interaction-graph CONFLICT/GAP/CRON-CLASH detection) is genuine but correctly NOT credited toward this dimension — it is an operator/actuator boundary, not task-coordination topology.

**Strengths.** Handoff-vs-tools made intentionally and correctly (Manager pattern A-grade, structurally enforced); defaults to least-autonomous; the control-plane topology itself is best-in-class; the bricks give the plane a mechanical structural self-model; pattern cataloging is mature and honestly self-graded (multi-agent = C).

**Concrete gaps.** No named topology pattern set / unified invoke; no Magentic supervisor-router with a task ledger; the defined multi-agent topology is documented-but-uninvokable in production; coordination telemetry is dark (`team_charter` emit is advisory/comment-only, `handoff_log`=0, `bump()` never called by a production hook).

---

### 4. Durability, State & Recovery — 3.0 / B

**Industry standard.** Two schools: the **replay/event-sourcing** school (Temporal, Dapr) journals an append-only Event History with deterministic workflow code for effectively-once execution; the **checkpoint/snapshot** school (LangGraph, OpenAI Sessions, ADK) keys state to a stable id and supports resume + time-travel. A-grade is durable-by-default for anything long-running, with the documented caveat that LLM-state checkpoints are weaker than true durable execution.

**How this system measures up.** The system sits firmly in the checkpoint/snapshot school and is honest about it. State is keyed to a stable id (`sessions` PRIMARY KEY = issue_id, session_id persisted, resume via `claude -r "$SID"`) — the LangGraph/OpenAI-Sessions tier exactly. Per-turn immutable snapshots (`scripts/lib/snapshot.py`, docstring 'Mirrors OpenAI Agents SDK RunState') are write-once, captured BEFORE each mutating tool, wired into PreToolUse, and **live** (350 rows today across 26 sessions). Long-term memory is correctly externalized (MemPalace). Crash hygiene is solid (JSONL on ZFS not tmpfs survives a crash; SQLite WAL; idempotent reconciler; zombie/lock cleanup).

**Score: 3.0 / B (verdict: uphold, evidence strong).**

**Strengths.** Genuine stable-id-keyed resume; live per-turn immutable snapshots consciously modeled on RunState; long-term memory externalized; the weaker-than-durable-execution caveat documented in code itself; solid crash hygiene.

**Concrete gaps.** No effectively-once / no deterministic replay of side-effects (a tool that ran then crashed before recording can be re-run on resume); **the recovery loop is OPEN** — `rollback_to()`/`latest()` are invoked only by the e2e test, never by a production path; a crashed session is archived as 'abandoned' (idle>2h), not resumed from its last snapshot; no per-turn durable progress (the Poller writes only Matrix m.notice, not DB progress); snapshot capture is coarse (a sessions-row mirror, not a full conversational checkpoint). **Closing the recovery loop is the single highest-value upgrade here.**

---

### 5. Failure Handling & Resilience — 3.5 / B+

**Industry standard.** Side-effecting calls retry with **Temporal-style declarative policy** (initial interval, 2.0 exponential backoff, capped max interval, bounded max attempts, non-retryable classification) plus idempotency tokens for effectively-once; every flaky dependency is wrapped in a closed/open/half-open circuit breaker logging every transition; agent-specific controls add runaway-loop detection, cost-velocity thresholds, and step/spend/input-hash ceilings — the missing-guard set behind the canonical $47K/$4,200 runaway post-mortems.

**How this system measures up.** Circuit breakers are A-grade: `scripts/lib/circuit_breaker.py` is a textbook Fowler/Hystrix CLOSED/OPEN/HALF_OPEN machine with a half-open canary, SQLite cross-process state, every transition persisted AND logged to stderr, a Prometheus exporter, wired into all 4 RAG external calls with fallbacks, alerted by `CircuitBreakerOpen`. Actuator containment is strong (per-target 3/hr heal cap → escalate → SMS; idempotency by construction). The mission-lane bounded-loop floor is robust (`IRREVERSIBLE_PATTERNS`, fail-CLOSED prediction gate, handoff POLL@5/HALT@10 + cycle detection, weekly I1).

**Score: 3.5 / B+ (verdict: uphold, evidence strong).**

**Strengths.** A-grade circuit breakers; k8s-shaped actuator containment; idempotency handled honestly by construction; strong mission-lane runaway protections; clean blast-radius isolation via Plane-A/B.

**Concrete gaps.** The **agent-trajectory tripwire — the single most important agent-specific control (the $47K-runaway guard) — is NOT enforced in the committed repo**: `session-tripwire.sh` exists but the exported Progress Poller node does only passive `kill -0`, and the system's own OpenAI scorecard grades this C ('poller is read-only with no kill authority'); no exponential backoff anywhere (fixed 2000ms / fixed 60s / linear); no non-retryable error classification; no idempotency tokens on retried Matrix/YouTrack POSTs (a maxTries:3 retry after partial success can double-post); breaker coverage is RAG-only (the `claude -p` dispatch, SSH path, and DB are not breaker-wrapped).

---

### 6. Supervision, Termination & Verification (MAST-Aware) — 4.3 / A-

**Industry standard.** Informed by the Berkeley MAST taxonomy (14 failure modes across specification ~42% / inter-agent misalignment ~37% / verification-termination ~21%): a designated supervisor plans/delegates/consolidates with routing→full-orchestration fallback, loops carry max-iteration caps escalating to a human on non-convergence, and **outcome verdicts are produced by a mechanical evaluator independent of the acting agent** (the agent never grades itself).

**How this system measures up.** Verification is the centerpiece and near best-in-class: `infragraph.action_verdict()` set-compares predicted vs observed alerts → match/partial/deviation, and `infragraph-verify.py` states verbatim it is "the ONLY verdict author" with "no write path" for the LLM. The R0 reconcile gate consumes this and fails CLOSED. Termination is layered (handoff POLL@5/HALT@10 + cycle detection; the 3-band POLL_PAUSE 'no-vote ⇒ PAUSE' floor; `[POLL]`×92 / `[AUTO-RESOLVE]`×24 stop markers). The irreversible-never-auto-resolved invariant is verified **compositionally** weekly (I1). All bricks + controller + reconcile gate are confirmed LIVE in Cronicle.

**Score: 4.3 / A- (verdict: uphold, evidence strong).**

**Strengths.** Independent mechanical verification correctly enforced (kills the MAST 'verification' failure class); explicit layered termination; compositional safety-invariant verification; inspectable specialist roster; everything live and self-monitored with k8s-style anti-thrash escalation.

**Concrete gaps.** No explicit MAST mapping in the codebase (`arxiv 2503.13657` / the word MAST appear nowhere — controls are MAST-shaped by convergent design, no audit artifact for all 14 modes); no designated single LLM supervisor performing plan→delegate→consolidate (coordination is distributed); inter-agent communication is advisory ('honor or override'), not an enforced protocol; HITL non-convergence escalation is a passive Matrix poll-pause (SMS only on high-risk bands, so a quiet POLL_PAUSE can sit unactioned); handoff caps live on the sub-agent/hook path, not the top-level n8n turn loop.

---

### 7. Human-in-the-Loop & Reversibility-Keyed Guardrails — 4.6 / A

**Industry standard.** Every action is rated low/medium/high by reversibility/blast-radius/financial-impact; the rating mechanically routes it (low-reversible → autonomous; irreversible/high-impact → hard pause-and-approve). Guardrails are a layered defense at input/tool-call/tool-response/output with a dedicated screening model separate from the acting model; gates are HARD (out-of-band/async push-approval), state is persisted so a paused run resumes without replay, and **never gate on a single LLM confidence score**.

**How this system measures up.** Reversibility-keyed routing is the architecture's spine and is LIVE (sentinels on disk). `classify-session-risk.py` rates every planned action via deterministic regex rule-validators into a 3-band gate (AUTO / AUTO_NOTICE+SMS / POLL_PAUSE+SMS). The irreversible-never-auto floor is enforced in depth: the Runner's Prepare Result node **mechanically rewrites** any unpredicted `[POLL]`/`[AUTO-RESOLVE]` to a `[…-WITHHELD:NO-PREDICTION]` marker (real JS, failing CLOSED), the band-aware weekly audit FAILS on any unsafe auto-approval AND asserts the gate exists in the live export, and I1 re-proves it weekly. Pause/resume is genuine durable state (`UPDATE sessions SET paused=1` + `lastResponseB64`, resume via `claude -r SID`). Defense is layered with a SEPARATE screening model (`screen-response.sh` = claude-haiku-4-5 vs acting Opus). Hard out-of-band SMS fires at classify-time; async Matrix-reaction approval resumes the run. LLM confidence is correctly NOT the gate.

**Score: 4.6 / A (verdict: uphold, evidence strong).**

**Strengths.** Reversibility-keyed routing is the spine, not a bolt-on; genuine fail-CLOSED gate with structural audit enforcement; true durable pause/resume; layered multi-boundary defense with a separate screening model; correctly refuses to gate on confidence alone; hard out-of-band escalation; guardrail explicitly not a substitute for access control; continuous mechanical verification of the floor.

**Concrete gaps.** One of four layers (`Check Intermediate Rail`) is DARK-FIRST observe-only and 'Never blocks'; the resume primitive depends on the Claude CLI's own session persistence — on session expiry it degrades to a context-seeded replay (so 'resume without replay' holds on the happy path only); the autonomy signal is still an LLM-authored marker in free-text (the surrounding gate does heavy lifting over historically-fragile parsing); I1 exercises a fixed 10-incident synthetic stream, not a sampled live slice; no explicit financial-impact axis (a literal gap vs the full OpenAI low/medium/high rubric).

> **Phrasing nit (does not move the grade):** an evidence row calls confidence a '≤15%-weight tripwire', but the code implements no confidence weight — it is a binary code-fence forcing-rule. This still satisfies the standard's intent (never gate primarily on an LLM score).

---

### 8. Observability & Distributed Tracing — 2.5 / C+

**Industry standard.** Instrument the control plane with **OpenTelemetry GenAI semantic conventions**: typed spans keyed on `gen_ai.operation.name` (create_agent/invoke_agent/chat/execute_tool/embeddings), the canonical `gen_ai.*` attribute vocabulary, standard metrics (`gen_ai.client.operation.duration`, `gen_ai.client.token.usage`), opt-in privacy-gated content capture, MCP tracing with W3C trace-context propagation, `gen_ai.evaluation.result` events, default-on tracing, and explicitly traceable routing/decision points. Backend swappable (Langfuse / Phoenix / LangSmith).

**How this system measures up.** A hand-rolled OTel-flavored exporter (`scripts/export-otel-traces.py`) re-parses Claude Code JSONL into a session-lifecycle root span + per-tool spans, emits a partial `gen_ai.*` set, and has dual self-hostable backends (OpenObserve OTLP + Langfuse v2). Per-tool granularity is genuinely good (individually-named MCP/Agent spans; `tool_call_log` fresh at 290,892 rows through today). **But** against the standard the implementation is shallow-and-mostly-dark — and every cited live query verifies exactly:

- **OTLP backend functionally dead:** `otel_spans exported_to_otlp → 1|37, 2|39274` (37 of 39,311 ever delivered = **99.9% loss**); a 4h local-expiry cutoff races the ~5h OpenObserve ingest window so the `*/5` cron structurally cannot win.
- **Not default-on:** `session_log → 826 total, 9 traced` (**1.1%**).
- No `gen_ai.operation.name` taxonomy (all spans hardcoded `kind:INTERNAL`); no `gen_ai.client.*` metrics; no cache/reasoning tokens, no `tool.call.id/arguments/result`, no `gen_ai.evaluation.result`; no W3C trace-context propagation into MCP; content capture always-on (not privacy-gated); routing/gate decisions have no RoutingClassifierTrace-equivalent span; Langfuse carries cost but **zero token usage**; the whole path went dark for ~2 months (April 2026).

**Score: 2.5 / C+ (verdict: uphold, evidence strong).** Correct intent and partial scaffolding, but a control plane whose primary backend delivers 0.1% of spans, traces 1.1% of sessions, and went dark for ~2 months is barely passing against a default-on, typed-span, real-time A-bar.

**Strengths.** Real exporter with W3C-valid 32/16-hex IDs and deterministic salted trace IDs; partial-but-correct `gen_ai.*` namespace; rich per-tool granularity; genuinely swappable self-hosted backends; out-of-band aggregate Prometheus visibility; failures logged not swallowed and dark-history honestly documented in code.

**Concrete gaps.** Fix the ingest-window race / push on session-end (don't expire your own backlog); make tracing default-on and guaranteed-async; adopt the `gen_ai.operation.name` taxonomy + CLIENT kind; add the standard metrics + missing attributes + evaluation events; propagate W3C trace-context into MCP; invert content capture to opt-in; emit a routing-decision span; move to a real OTel SDK in the session wrapper (live timing, not post-hoc reconstruction); populate Langfuse token usage.

---

### 9. Evaluation & Benchmarking — 3.9 / B+

**Industry standard.** Two cadences (offline regression CI gate + online continuous sampling that never blocks), three altitudes (final-response black-box / trajectory glass-box / single-step white-box), LLM-as-judge calibrated against **≥100 human labels** emitting categorical scores, guardrail (blocking) evals distinct from monitoring (flagging), drift detection + feedback loops, and disciplined model selection (baseline → strongest model → downgrade only where eval proves quality holds, never blind).

**How this system measures up.** The regime is real and substantial. Two BLOCKING CI gates (`eval-regression` `allow_failure:false` + `eval_set_integrity` sha256 sealed-holdout decontamination). Async online eval (`llm-judge.sh --recent` every 2h via `LEFT JOIN session_judgment`, categorical `approve|improve|reject`, never blocking). All three altitudes present (5-dim judge / `score-trajectory.sh` glass-box / `run-hard-eval.py` + `ragas-eval.py` white-box). Guardrail-vs-monitoring split is mechanical (I1+I4 hard-gate at `orchestration-benchmark.py:193` vs Prometheus warning alerts). A monthly flywheel with an overfit detector + auto-rollback closes the loop.

**Score: 3.9 / B+ (verdict: ADJUSTED DOWN from 4.3/A-, evidence strong).** Two named A-grade elements are missing/broken:
1. **Judge calibration is LLM-vs-LLM** — Haiku-reference / 60 cases / 0.85 agreement, with no human-label ingestion path anywhere. The clearest miss vs the explicit '≥100 human labels' bar.
2. **Model selection is BROKEN, not satisfied** — the score credited a 'guarded Sonnet downgrade with never-downgrade-risky floor' as a strength, but the committed runner still contains `var priorIncidents = (kbRaw.match(/\|/g)||[]).length` (counts pipe CHARACTERS, not incident rows), making the Sonnet branch structurally unreachable. The system's own same-date scorecards grade this D (818/818 Opus, 0 Sonnet across 738 real sessions; listed as the #1 outstanding action). Model selection is an explicit A-grade element of THIS dimension — crediting design-as-implementation was an inflation, corrected here.

**Strengths.** Genuinely covers all three altitudes (most systems stop at final-response); a truly blocking offline gate + sealed-holdout decontamination; clean guardrail-vs-monitoring separation; real online continuous eval with categorical verdicts feeding a flywheel with an overfit detector + auto-rollback; drift detection with action.

**Concrete gaps.** No human-label judge calibration anywhere; the blocking CI gate runs only the structural/regression set (quality `hit@5` is a 7-day Prometheus WARNING, not a merge-blocker — a quality regression can merge and surface a week later); the live judge defaults to local gemma3:12b carrying known 0.85-agreement looseness with nothing gating on it; no human sampled-review of judge verdicts at any cadence; RAGAS golden set is weekly+manual and not a gate; the only persisted calibration baseline is 2026-04-19 (>2 months stale).

---

### 10. Governance, Auditability & Regulatory Traceability — 3.0 / B-

**Industry standard.** An **append-only, tamper-evident** store (hash-chained SHA-256 over the prior hash, optionally signed) where each entry captures timestamp + agent identity + model/version/config at decision time + decision context + every tool call with params AND results + which governance rules were evaluated + data lineage + the human-intervention point + correlation IDs; access to the log is itself controlled and logged. Red-teamed against **OWASP Top 10 for Agentic Applications 2026 (ASI01-ASI10)** + LLM Top 10, with MAESTRO + NIST AI RMF GOVERN/MEASURE, kill-switches via credential revocation on goal drift, and EU AI Act Article 12 answerable for any decision (≥6-month retention, enforced Aug 2 2026).

**How this system measures up.** The trail is rich and effectively-immutable (session_risk_audit, 17 typed event types, a2a_task_log, session_log, immutable snapshots) at indefinite retention on the core tables — exceeding the Art.12 ≥6-month bar. A formal EU AI Act assessment (GOV-EUAIA-001) maps Art.12/13/14; a fail-CLOSED classifier + band-aware mechanical audit invariant + NIST 5-signal behavioral-drift telemetry + a 39-fixture jailbreak corpus (with Greek) + sentinel kill-switches + 3 self-monitoring bricks are all present. **But the single defining A-grade control is absent:** there is **NO hash-chaining** (no `prev_hash`/SHA-256-over-prior/signature) on any decision table — `session_risk_audit` is a plain mutable SQLite table, the platform-controller audit is plain append-text, and Git versions the docs/code, not the runtime rows. Per-entry provenance is fragmented (the decision row does NOT carry model/version-at-decision-time — that lives in a separate Langfuse/llm_usage store). And the named **OWASP Agentic 2026 (ASI01-10) is NOT red-teamed** — it appears only in a 'WATCH/not adopted' catalog row.

**Score: 3.0 / B- (verdict: uphold, evidence strong).** The gap to A is narrow in surface area but load-bearing.

**Strengths.** Effectively-immutable multi-table trail at indefinite retention; mechanical fail-CLOSED governance; genuine regulatory paperwork (EU AI Act assessment + QMS + OWASP LLM Top 10 2025 scoring); NIST behavioral-drift telemetry + jailbreak corpus; layered kill-switches + self-monitoring bricks; strict Plane-A/B with a committed plan_hash machine artifact for every approved action.

**Concrete gaps.** No tamper-evidence anywhere (the defining control); fragmented per-entry provenance; OWASP Agentic 2026 ASI01-10 not red-teamed; log access not itself access-controlled-and-logged; kill-switch on goal-drift is sentinel-file disable, not centralized credential revocation, and no watchdog for rogue/collusive *agent semantic* behavior (bricks watch liveness); the EU AI Act assessment (2026-04-15) pre-dates the orchestrator control-plane and the Aug-2-2026 enforcement reality.

---

### 11. Security & Least-Agency (Identity, Scoped Credentials, Meta-Monitoring) — 3.0 / B-

**Industry standard.** Each agent runs under its own bounded non-human identity with short-lived, task-scoped, least-privilege credentials and sandboxed tools with egress allowlists, so a compromise cannot move laterally; autonomy is earned not default; inter-agent channels use mTLS with integrity checks (OWASP ASI02/03/05/07) and MCP supply chains are vetted (ASI04). The control plane that watches everything is itself watched by an **independent out-of-band dead-man's-switch** — an always-firing watchdog heartbeat plus an external snitch alerting on the ABSENCE of the heartbeat, on different infrastructure, paging out-of-band.

**How this system measures up.** This dimension splits cleanly into two halves and the system is best-in-class on one, behind on the other.

- **Meta-monitoring (A-grade):** the watchdog heartbeat fires on EVERY exit path via `trap emit_metrics EXIT`; `GatewayWatchdogHeartbeatStale` carries an explicit `absent()` clause + tier=1 → Twilio SMS while its own Matrix alerts are muted (quis-custodiet). The same `absent()`+tier1 shape recurs across SyntheticCanary/RegistryCheck/Holistic/RiskAudit/OrchestrationBenchmark. The Registry brick mechanizes the dark-component class and registers itself. Alerts deploy as in-cluster PrometheusRules (separate infrastructure). This closes the rarest, hardest sub-pillar — silent-monitor-death.
- **Identity/least-agency (~C-grade):** the dispatched session launches `claude -p … --dangerously-skip-permissions` under a SINGLE shared `app-user` SSH identity (credential `REDACTED_SSH_CRED`, used across all SSH nodes); secrets are long-lived static `.env` tokens; the OpenBao short-lived-token path is a dormant Phase-4 research stub (0 `.env` refs, in no cron); no egress allowlist / firejail / nsjail / NetworkPolicy; the `MemoryMax=12G` cap claimed in CLAUDE.md is absent from the actual launch line; inter-agent channels are plaintext Matrix + SSH with `StrictHostKeyChecking=no` (no mTLS). The mission gate governs autonomy, not identity blast-radius — a borrowed-cred lateral compromise is not contained by it.

**Score: 3.0 / B- (verdict: uphold, evidence strong).** An honest average of a verified A half with a verified C half, neither rounded to flatter the system.

**Strengths.** Best-in-class meta-monitoring (trap-EXIT always-firing + absent() out-of-band SMS); true infrastructure independence (in-cluster PrometheusRules, muted self-alerts); who-watches-the-watcher closed both ways; least-agency correctly applied to the actuator; autonomy earned-not-default on the mission lane; visible honesty culture (analysis-only-by-default, follow-ups flagged not overclaimed).

**Concrete gaps.** No per-agent non-human identity (one shared SSH cred → lateral movement); no short-lived task-scoped credentials (OpenBao dormant); tools not least-privilege at launch (`--dangerously-skip-permissions`); no hardened sandbox / egress allowlist (and the claimed MemoryMax is absent); no mTLS/integrity between agents (ASI03/05); the genuinely-external Healthchecks.io snitch is incompletely wired (creds in `.env` but `registry-check.py` never pings it); MCP/third-party supply-chain vetting (ASI04) not evidenced as a gated control.

---

## Top Strengths (system-wide)

1. **Kubernetes-faithful Plane-A/Plane-B separation enforced in code** — the self-healing controller does ONLY idempotent reversible platform ops; a grep for any mission verb in its body returns nothing, and the mission lane is a physically separate module with zero cross-references. The system's signature achievement.
2. **Reversibility-keyed HITL guardrails with a genuine fail-CLOSED gate (A)** — deterministic 3-band routing, mechanical withholding of unpredicted auto-resolve markers, durable pause/resume of the same session, and a separate screening model.
3. **Independent mechanical outcome verification (A-)** — the acting LLM has NO write path to its own match/partial/deviation verdict, and the auto-resolve lane fails CLOSED on anything not verified match. Directly kills the MAST 'agent grades itself' failure class.
4. **Meta-monitoring that closes silent-monitor-death out-of-band** — trap-EXIT always-firing heartbeat + an explicit `absent()` clause + tier-1 SMS, with the Registry brick mechanizing the dark-component audit and registering itself.
5. **Demonstrated honesty culture** — the system's own scorecards grade their weak halves C/D rather than inflating, code comments document dark-component history, and stale counts were corrected to live values. A credibility signal that survived adversarial verification.

## Top Gaps / Prioritized Recommendations

1. **Fix observability delivery (highest leverage).** Push spans immediately on session-end (drop the deferred cron that expires its own backlog), fix the 4h-expiry-vs-5h-ingest race, and make tracing default-on. Today the OTLP backend delivers 0.1% of spans and traces 1.1% of sessions — runaway behavior is undetectable on the trace plane before the bill.
2. **Re-enable model routing.** Land the documented fix for the pipe-counting `priorIncidents` bug (the committed/deployed workflow still has it — repo-vs-deploy drift) so simple low-risk categories actually route to Sonnet with the never-downgrade-risky floor intact. This drags Evaluation to 3.9 and leaves routing dead.
3. **Add per-agent identity + least-privilege.** Wire the dormant OpenBao short-lived-token path, scope per-task `allowedTools`, add a hardened non-root sandbox with an egress allowlist, replace `--dangerously-skip-permissions`, and finish the external Healthchecks.io snitch. One shared SSH identity = lateral movement on a single compromise.
4. **Add tamper-evidence + the named red-team.** Hash-chain (SHA-256-over-prior) the decision rows, unify per-entry provenance (model/version-at-decision-time alongside tool-calls-and-results in one append-only entry), and run an OWASP Agentic 2026 ASI01-10 assessment.
5. **Close the recovery loop and enforce the trajectory tripwire.** Wire auto-resume-from-snapshot (snapshots are captured live but never used to resume — crashed sessions are archived, not resumed), and move `session-tripwire.sh` (the canonical $47K-runaway guard) from the read-only Poller into an enforcing kill path in the committed workflow so it survives a repo→n8n redeploy.

---

## Sources

**Control-plane / reliability standards**
- Kubernetes — Controllers; Self-Healing; Liveness/Readiness/Startup Probes; Pod Lifecycle (CrashLoopBackOff, exponential backoff 10s→300s, 10-min reset). https://kubernetes.io/docs/concepts/architecture/controller/ · https://kubernetes.io/docs/concepts/architecture/self-healing/ · https://kubernetes.io/docs/concepts/workloads/pods/probes/ · https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/
- Martin Fowler — Circuit Breaker (closed/open/half-open, log state changes, fail fast). https://martinfowler.com/bliki/CircuitBreaker.html
- PromLabs — End-to-end Watchdog / metrics-based meta-monitoring. https://training.promlabs.com/training/monitoring-and-debugging-prometheus/metrics-based-meta-monitoring/end-to-end-watchdog-alerts/
- Securing Your Monitoring Stack with a Dead Man Switch. https://seifrajhi.github.io/blog/securing-monitoring-stack-dead-man-switch/
- Quis custodiet ipsos custodes? https://en.wikipedia.org/wiki/Quis_custodiet_ipsos_custodes
- Google SRE — Eliminating Toil; Embracing Risk; Monitoring Distributed Systems (four golden signals, symptom-based actionable alerting). https://sre.google/workbook/eliminating-toil/ · https://sre.google/sre-book/embracing-risk/ · https://sre.google/sre-book/monitoring-distributed-systems/

**Orchestration, durable execution & coordination**
- Temporal — Workflow Execution overview; Retry Policies; Understanding Temporal (Event History, effectively-once, determinism). https://docs.temporal.io/workflow-execution · https://docs.temporal.io/encyclopedia/retry-policies · https://docs.temporal.io/evaluate/understanding-temporal
- LangGraph — Durable Execution (checkpointers, thread_id, resume/time-travel). https://docs.langchain.com/oss/python/langgraph/durable-execution
- Dapr Agents — core concepts + introduction (DurableAgent, LLMOrchestrator, circuit breakers). https://docs.dapr.io/developing-ai/dapr-agents/dapr-agents-core-concepts/ · https://docs.dapr.io/developing-ai/dapr-agents/dapr-agents-introduction/
- CrewAI — Flows (@persist, @human_feedback). https://docs.crewai.com/concepts/flows
- Diagrid — Why Checkpoints Aren't Durable Execution. https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short-for-production-agent-workflows
- Microsoft — Semantic Kernel Agent Orchestration (canonical five patterns); Agent Framework 1.0 (sequential/concurrent/handoff/group-chat/Magentic). https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/ · https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/
- Azure Architecture Center — AI agent orchestration patterns. https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns
- OpenAI Agents SDK — Orchestration/handoffs; Running agents (max_turns); Guardrails & human review (needs_approval, interruptions); Tracing (default-on). https://developers.openai.com/api/docs/guides/agents/orchestration · https://openai.github.io/openai-agents-python/running_agents/ · https://developers.openai.com/api/docs/guides/agents/guardrails-approvals · https://github.com/openai/openai-agents-python/blob/main/docs/tracing.md
- AWS Bedrock — Multi-agent collaboration (supervisor + routing fallback); trace events (RoutingClassifierTrace). https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html · https://docs.aws.amazon.com/bedrock/latest/userguide/trace-events.html
- Google ADK / Vertex AI Agent Engine. https://cloud.google.com/agent-builder/agent-development-kit/overview · https://google.github.io/adk-docs/

**Vendor / research guidance**
- Anthropic — Building Effective AI Agents. https://www.anthropic.com/engineering/building-effective-agents
- OpenAI — A Practical Guide to Building Agents. https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- Google — Agents whitepaper (Wiesinger, Marlow, Vuskovic, 2024). https://ia800601.us.archive.org/15/items/google-ai-agents-whitepaper/Newwhitepaper_Agents.pdf
- LangChain — The Agent Development Lifecycle. https://www.langchain.com/blog/the-agent-development-lifecycle
- 12-Factor Agents (HumanLayer). https://github.com/humanlayer/12-factor-agents · https://www.humanlayer.dev/blog/12-factor-agents
- Berkeley — Why Do Multi-Agent LLM Systems Fail? (MAST, arXiv 2503.13657). https://arxiv.org/abs/2503.13657 · https://arxiv.org/html/2503.13657v2

**Observability & evaluation**
- OpenTelemetry — GenAI agent spans; client spans; GenAI attribute registry; GenAI observability blog. https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ · https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/ · https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/ · https://opentelemetry.io/blog/2026/genai-observability/
- Greptime — How OpenTelemetry Traces LLM Calls, Agent Reasoning, and MCP Tools. https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
- Digital Applied — Agent Observability: LangSmith, Langfuse, Arize (2026). https://www.digitalapplied.com/blog/agent-observability-platforms-langsmith-langfuse-arize-2026
- Arize — The Definitive Guide to LLM Evaluation. https://arize.com/llm-evaluation/
- Langfuse — How to Evaluate LLM Agents. https://langfuse.com/guides/cookbook/example_pydantic_ai_mcp_agent_evaluation
- Evaluation-Driven Development and Operations of LLM Agents (arXiv 2411.13768). https://arxiv.org/pdf/2411.13768

**Security, governance & failure post-mortems**
- OWASP Gen AI Security — Top 10 for Agentic Applications 2026 (ASI01-ASI10). https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- OWASP Top 10 for LLM Applications (2025). https://aembit.io/blog/owasp-top-10-llm-risks-explained/
- Auth0 — Lessons from OWASP Top 10 for Agentic Applications. https://auth0.com/blog/owasp-top-10-agentic-applications-lessons/
- Teleport — OWASP Top 10 for Agentic Applications. https://goteleport.com/blog/owasp-top-10-agentic-applications/
- AI Governance Frameworks: NIST, OWASP, MAESTRO, ISO 42001. https://alice.io/blog/ai-risk-management-frameworks-nist-owasp-mitre-maestro-iso
- DEV Community — Your AI Agents and the Audit Trail; AI Agent Circuit Breakers. https://dev.to/waxell/your-ai-agents-and-the-audit-trail-what-compliance-actually-needs-33i5 · https://dev.to/waxell/ai-agent-circuit-breakers-the-reliability-pattern-production-teams-are-missing-5bpg
- Galileo — AI Agent Compliance & Governance. https://galileo.ai/blog/ai-agent-compliance-governance-audit-trails-risk-management
- Runaway-loop post-mortems — The Agent That Spent $47K on Itself; The Agent That Burned $4,200 in 63 Hours. https://dev.to/gabrielanhaia/the-agent-that-spent-47k-on-itself-an-autonomous-loop-postmortem-3313 · https://medium.com/@sattyamjain96/the-agent-that-burned-4-200-in-63-hours-a-production-ai-postmortem-d38fd9586a85

---

*Report generated 2026-06-26 from 11 adversarially-verified dimensions. Every load-bearing claim was re-checked against live files and live queries; per-dimension `evidence_quality` was "strong" across all 11. Overall score = unweighted mean of adjusted scores (38.3 / 11 = 3.48).*
