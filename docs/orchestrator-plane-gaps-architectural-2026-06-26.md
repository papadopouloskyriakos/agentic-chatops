# Orchestrator / Control-Plane — Architectural Gaps & Recommendations

**Date:** 2026-06-26
**Scope:** The three *architectural* (vs. plumbing) gaps the [11-dimension orchestrator-plane benchmark](orchestrator-plane-benchmark-2026-06-26.md) flagged at **B / B / A−**. This document is a **decision record with an implementation path**, not a build order. Nothing here should be built speculatively right now — each section ends with an explicit *build now / build later / accept* recommendation and the evidence behind it.

These three gaps share a theme the benchmark named directly: the system is best-in-class on **safety, supervision, and verification** (the rare/hard half) and lagging on **coordination topology, durable recovery, and identity** (the plumbing half). All three gaps below are in that lagging half. None is a safety regression — the fail-CLOSED prediction gate, the irreversible floor, and the independent mechanical verdict all sit *underneath* every path discussed here and are unaffected by closing (or not closing) any of these.

**Cross-cutting honesty note.** The multi-agent surfaces these gaps concern (`scripts/agent_as_tool.py`, `scripts/lib/team_formation.py`, `scripts/lib/handoff_depth.py`, `scripts/lib/handoff.py`) are **built, tested, and correct** — but the benchmark's own live queries show they are **unreached in production**: **0 `Task` tool_use across 331 sessions**, **0 `team_charter` events across 818**, `handoff_log` empty, `bump()` never called by a production hook. So for all three gaps the cheapest "fix" is frequently *wire the thing that already exists into the dispatched path*, not *build new machinery*. That distinction drives every effort estimate below.

---

## Gap 1 — Orchestration & Coordination Topology (benchmark 3.0 / B)

### (a) Industry standard / what A-grade looks like

The A-bar (Microsoft Semantic Kernel / Agent Framework 1.0, Azure AI agent design-patterns, AutoGen → **Magentic-One**, OpenAI Agents SDK) is:

1. **A named, swappable topology set** — Sequential / Concurrent / Group-Chat / dynamic Handoff / **Supervisor-Magentic** — exposed behind one uniform `invoke` interface so the control plane *selects* a topology per task rather than hard-coding one.
2. **An intentional handoff-vs-agents-as-tools choice** — handoff = *transfer of ownership*; agents-as-tools = *manager retains ownership*. (This system already makes this choice correctly — Manager pattern, structurally enforced by excluding Edit/Write from every `.claude/agents/*.md`.)
3. **A Magentic-style supervisor-router with a task ledger** — the orchestrator maintains an explicit ledger of facts / plan / progress / who-owns-what, re-plans on stall, and routes the next step to a worker. This is the single element that turns "a bag of sub-agents" into an *orchestration topology*.
4. **Default to the least-autonomous design that works** — single agent / linear workflow first; splitting into a multi-agent topology is a justified, evidence-backed step (Anthropic *Building Effective Agents*). This system already does this well.

### (b) How the orchestrator does it today (file evidence)

- **One topology distinction, made correctly and intentionally:** Manager (agents-as-tools) vs. Decentralized (handoff). Enforced in `.claude/agents/*.md` (11 agents, all read-only — Edit/Write/MultiEdit excluded → transfer-of-control is structurally impossible) and stated explicitly in `scripts/agent_as_tool.py:19-21`: *"Does NOT replace the deterministic `Task(subagent_type=...)` path … It's an ADDITIONAL surface for the ambiguous-risk band."*
- **Default-to-least-autonomous is real:** single `claude -p` per alert with proper exit conditions; GEPA ships dark; `isComplexSession` keeps simple alerts single-agent.
- **But the A-grade markers are absent:**
  - **No named topology selector.** `grep -rln "select_topology\|OrchestrationPattern\|task_ledger\|Magentic" scripts/` returns **nothing**. `scripts/lib/team_formation.py::propose_team()` selects a *roster* (the "who"), never a *topology* (the "how").
  - **No task ledger / Magentic supervisor-router.** There is no module that holds facts/plan/progress and re-routes on stall. The Runner is a turn loop, not a ledger-driven planner.
  - **No unified swappable invoke interface.** `agent_as_tool.py` and the deterministic `Task()` path are two parallel surfaces, not one dispatcher.
  - **The one multi-agent topology is unreachable on the dispatched path.** Dispatched sessions launch `claude -p` from a cwd with **no `.claude/agents/`** (the agents live in this repo, not in the cubeos workspace the session runs in). The system's own data: **0 `Task` tool_use / 331 sessions**, **0 `team_charter` / 818**. `team_formation.propose_team()` is library-complete but has **no production emit site** (`grep` for `propose_team` in `workflows/` is empty).

### (c) Concrete minimal implementation path (smallest change that moves the needle)

The needle here is **reachability**, not a new framework. Two minimal increments, in order:

1. **Make the existing multi-agent topology reachable on the dispatched path (≈ the whole grade gap).** Symlink or `--add-dir` the repo's `.claude/agents/` into the dispatched session's agent search path (the same trick already used for sub-agent discoverability per `memory/autonomous_benchmark_mission_20260625.md` — `~/.claude/agents` symlink). Then wire `team_formation.propose_team()` into the Build Prompt node so each session emits its `team_charter` event. **Net effect:** the documented topology stops being documented-but-uninvokable, and coordination telemetry (`team_charter`, `Task` tool_use) goes from 0 to live — which is what the benchmark docked.
2. **Name the topologies you actually have, in one thin selector.** Add `scripts/lib/topology.py` with a single function `select_topology(category, risk_level, complexity) -> {"SINGLE","MANAGER_WORKERS","SEQUENTIAL"}` and a dataclass enum. This is ~80 LOC: it does not implement new execution machinery — it *names* the choice the Runner already makes implicitly (`isComplexSession` → single vs. multi) and records it as an event. That alone satisfies the "named, swappable topology set" marker for the topologies the system genuinely uses.

**Explicitly NOT in the minimal path:** a Magentic task-ledger supervisor-router. That is a genuine new subsystem (a planner module + a ledger table + a re-plan-on-stall loop) and would be a multi-week build. It is the only part of this gap that is *new architecture* rather than *wiring*.

### (d) Risk + effort

| Increment | Effort | Risk |
|---|---|---|
| 1. Reachability (agents symlink + `team_charter` emit) | **S** (~½ day) | **Low** — additive; the Manager pattern's read-only floor is unchanged, so a reachable sub-agent still cannot mutate. Main risk is prompt-bloat / token cost from the charter section (cap it). |
| 2. Named topology selector (`topology.py`) | **S–M** (~1 day) | **Low** — pure classification + an event; no execution change. |
| 3. Magentic task-ledger supervisor | **L** (multi-week) | **Medium** — new planner = new failure surface; must inherit the same fail-CLOSED prediction gate and handoff caps, or it becomes an unbounded-loop vector (the $47K-runaway class). |

### (e) Recommendation

- **Increment 1 (reachability): BUILD LATER, near-term.** It is cheap and it is the *honest* fix — the benchmark's core complaint is "documented but uninvokable," and this closes exactly that. But it is not urgent: today's single-agent dispatch is correct and safe, and 0/331 Task-calls is a *latent-capability* gap, not a live failure. Schedule it when sub-agent fan-out is actually wanted for a real incident class (e.g., multi-host cascades).
- **Increment 2 (named selector): BUILD LATER, bundled with 1.** Only worth doing once topologies are reachable — naming a topology nobody can invoke is theatre.
- **Increment 3 (Magentic ledger): ACCEPT (do not build now).** The system's incidents are short-horizon (single `claude -p`, proper exit conditions); a task-ledger supervisor solves long-horizon multi-worker planning the workload does not yet exhibit. Building it now is speculative gold-plating against the explicit "default to least-autonomous" principle. Revisit only if/when real incidents routinely exceed the handoff-depth POLL threshold (≥5) — at which point the data justifies the split.

---

## Gap 2 — Supervision, Termination & Verification (benchmark 4.3 / A−)

> This is already an **A−**; the two items below are what stands between it and A. Treat this section as "polish the strongest dimension," not "fix a hole."

### (a) Industry standard / what A-grade looks like

Informed by the Berkeley **MAST** taxonomy (arXiv 2503.13657 — 14 failure modes across specification / inter-agent misalignment / verification-termination):

1. **A designated, NAMED supervisor pattern** — one component that performs *plan → delegate → consolidate* with a routing→full-orchestration fallback (AWS Bedrock multi-agent collaboration; OpenAI Agents SDK manager pattern). The supervisor is an identifiable artifact, not an emergent property.
2. **An ENFORCED inter-agent role contract** — sub-agents communicate over a protocol the system *enforces*, not one they may "honor or override."
3. **Independent mechanical verification** — outcome verdicts produced by an evaluator the acting agent *cannot write to*. (This system is best-in-class here — see below.)
4. **Layered termination** — max-iteration caps escalating to a human on non-convergence.

### (b) How the orchestrator does it today (file evidence)

- **Verification is genuinely near best-in-class.** `infragraph.action_verdict()` set-compares predicted vs. observed alerts → match/partial/deviation; `infragraph-verify.py` is "the ONLY verdict author" with no LLM write path; the R0 reconcile gate in `reconcile-completed-sessions.py:331-361` consumes it and **fails CLOSED** (auto-resolve only on `verdict == "match"`; deviation/partial/unevaluated → demote to "To Verify" + deviation SMS). This directly kills the MAST "agent grades itself" class.
- **Termination is layered.** Handoff caps live in `scripts/lib/handoff_depth.py`: POLL at depth ≥5, hard-HALT at ≥10 (`HandoffDepthExceeded`), plus cycle detection (`HandoffCycleDetected` when an agent name repeats in the chain). The 3-band `POLL_PAUSE` "no-vote ⇒ PAUSE" floor and the `[POLL]`/`[AUTO-RESOLVE]` stop markers add more layers. `orchestration-benchmark.py` re-proves the irreversible-never-auto-resolved invariant (I1) weekly.
- **The two A-blockers:**
  1. **No canonical NAMED supervisor.** Coordination is *distributed* — the Runner turn loop + the reconcile gate + the bricks each own a slice; no single module is "the supervisor performing plan→delegate→consolidate." There is also **no explicit MAST mapping** in the codebase (`grep` for `MAST` / `2503.13657` → nothing); the controls are MAST-*shaped* by convergent design, with no audit artifact covering all 14 modes.
  2. **The inter-agent role contract is soft/advisory.** `handoff.py`'s `HandoffInputData` envelope is *opt-in* (docstring: "The envelope is opt-in: the parent decides when to include it"), payload shapes are deliberately unenforced ("we don't enforce a schema here … soft parsing downstream"), and the termination caps in `handoff_depth.py` live on the **sub-agent / hook path**, not the top-level n8n turn loop. So the protocol is "honor or override," not enforced.

### (c) Concrete minimal implementation path

1. **For the named-supervisor gap — DOCUMENT, don't build.** The cheapest move that satisfies the marker is a one-page artifact, `docs/mast-failure-mode-mapping.md`, that (i) names the *de facto* supervisor as the composition `Runner-turn-loop + R0-reconcile-gate` and (ii) maps each of MAST's 14 failure modes to the existing control that covers it (or marks it "uncovered / accepted"). This converts "MAST-shaped by accident" into "MAST-mapped on purpose" — which is what the benchmark actually docks — without inventing a new orchestrator component. It also surfaces any genuinely-uncovered mode honestly.
2. **For the soft role-contract — make the envelope mandatory *only once handoffs are live*.** The minimal hardening: when Gap 1's sub-agent path becomes reachable, flip `handoff.py` from opt-in to required *for spawns that occur via that path* — i.e., `agent_as_tool.py` should refuse to spawn without a valid `HandoffInputData` envelope and a successful `bump_depth()` (it already imports `bump as bump_depth`). That makes the depth cap + envelope an *enforced precondition of spawning*, not an advisory the parent may skip. ~20 LOC of guard in `agent_as_tool.py`, plus a QA case.

### (d) Risk + effort

| Item | Effort | Risk |
|---|---|---|
| MAST mapping doc | **S** (~½ day) | **None** — a document; the only "risk" is discovering an uncovered mode, which is the point. |
| Mandatory envelope + enforced depth-cap on the spawn path | **S** (~½ day, *after* Gap 1) | **Low** — fails CLOSED (refuse to spawn) which is the safe direction; cannot weaken any existing control. |

### (e) Recommendation

- **MAST mapping doc: BUILD NOW (it is a doc, and this document's mandate is documentation).** It is the single highest-value, lowest-risk item across all three gaps: half a day, zero runtime risk, and it both (a) earns the named-supervisor / MAST-audit marker and (b) may reveal a real uncovered failure mode worth a follow-up. Recommend authoring it alongside this file.
- **Mandatory envelope / enforced spawn-time depth-cap: BUILD LATER, strictly after Gap 1 increment 1.** Enforcing a contract on a path nobody travels (0 Task-calls) is pointless; it becomes valuable the moment handoffs are live, and then it is cheap. Do not build it before the path is reachable.
- **A new dedicated supervisor *component*: ACCEPT.** Distributed coordination with a fail-CLOSED gate is a legitimate A−-grade design; a single supervisor module is *one* valid topology, not a requirement. Building one purely to claim the marker would add a failure surface for no behavioral gain. The doc (item 1) closes the *audit* gap without the *build*.

---

## Gap 3 — Durability, State & Recovery (benchmark 3.0 / B)

> The benchmark called this out as **"the single highest-value upgrade here."** Of the three gaps, this is the one with a concrete, bounded, safe build that closes a real (if rare) failure: a crashed session is currently archived as "abandoned," never resumed — even though everything needed to resume it is already captured.

### (a) Industry standard / what A-grade looks like

Two recognized schools:

- **Replay / event-sourcing (Temporal, Dapr):** append-only Event History + deterministic workflow code → **effectively-once** execution; a side-effect that ran-then-crashed is *not* re-run on replay.
- **Checkpoint / snapshot (LangGraph, OpenAI Sessions, Google ADK):** state keyed to a stable id, supporting **resume** + time-travel. Weaker than true durable execution (Diagrid: "checkpoints aren't durable execution"), but the documented, accepted tier for LLM agents.

A-grade for an LLM agent system is: **durable-by-default for anything long-running**, sitting honestly in the checkpoint school, **with the resume loop actually closed** (a crash resumes from the last checkpoint).

### (b) How the orchestrator does it today (file evidence)

- **Sits correctly in the checkpoint school and is honest about it.** State keyed to a stable id (`sessions` PRIMARY KEY = issue_id; `session_id` persisted; resume via `claude -r "$SID"`). Per-turn immutable snapshots in `scripts/lib/snapshot.py` (docstring: *"Mirrors OpenAI Agents SDK RunState … captured BEFORE each tool executes"*), wired into `PreToolUse` via `scripts/hooks/snapshot-pre-tool.sh` — and **live** (benchmark: ~350 rows across 26 sessions today). Long-term memory externalized (MemPalace). Solid crash hygiene (JSONL on ZFS not tmpfs; SQLite WAL; idempotent reconciler; zombie/lock cleanup).
- **The recovery loop is OPEN — this is the gap.** `snapshot.py` exposes `latest()` and `rollback_to()`, but the **only** caller of either is the e2e test (`scripts/qa/e2e/test-e2e-crash-rollback.sh`) plus the lib/prune paths. `scripts/hooks/snapshot-pre-tool.sh` **only `capture`s** — it never reads a snapshot back. Verified: `grep -rn "rollback_to\|\.latest(" scripts/` finds no production resume caller. So snapshots are written every turn and **never used to resume.**
- **What happens to a crashed session instead:** `reconcile-completed-sessions.py:388-393` selects sessions idle > 2h (`is_current=1` but `last_active` stale) and `classify_session()` (`:316-327`) **archives them as `outcome="abandoned"`** — it does not consult `snapshot.latest()` to resume the unfinished work. A session that died mid-turn is closed out, not continued.
- **No effectively-once.** A side-effecting tool that ran then crashed *before its result was recorded* would be re-run on any resume (there is no idempotency token / dedup on the tool-execution path). The snapshot is captured *before* the tool, so it cannot tell "ran" from "didn't."

### (c) Concrete minimal implementation path

The minimal, safe move closes the *checkpoint-school* resume loop — it does **not** attempt effectively-once (that needs deterministic replay the Claude CLI does not give us).

1. **Add a resume decision to the reconcile loop, gated and conservative.** Before `classify_session()` archives an idle-but-`is_current=1` session as "abandoned," call `snapshot.latest(issue_id)`. If a snapshot exists **and** the session's last band was **AUTO/AUTO_NOTICE** (i.e., already safe to act autonomously) **and** the pending tool in the snapshot is **read-only** (no mutation captured as `pending_tool` / `pending_tool_input`), resume via `claude -r "$SID"` with a one-line "you were interrupted before `<pending_tool>`; re-verify state before acting" preamble. Otherwise — any mutation pending, any POLL/POLL_PAUSE band, any deviation — **do exactly what it does today: archive + (if a mutation was pending) fire the deviation SMS.** This is the smallest change that turns "crashed → abandoned" into "crashed → resume-if-provably-safe, else escalate," reusing the *existing* fail-CLOSED machinery rather than adding a new one.
2. **(Stretch, optional) Mark the snapshot "tool started" vs "tool completed"** so a future resume can skip a side-effect that already ran. This is a real step toward effectively-once but needs a second hook (`PostToolUse` writing a completion marker keyed to the snapshot id). Bounded but a genuine new capture path — keep it out of the minimal build.

### (d) Risk + effort

| Item | Effort | Risk |
|---|---|---|
| 1. Gated resume-from-snapshot in reconcile (read-only-pending + AUTO-band only) | **M** (~1–2 days incl. QA) | **Medium**, but bounded: the *resume* branch is strictly narrower than today's *auto-resolve* branch (it requires an already-AUTO band AND a read-only pending tool), so it can never auto-act on something that wouldn't already auto-resolve. The real risk is double-execution if a mutation *did* run before the crash — explicitly excluded by gating on read-only-pending only. Must reuse `claude -r` resume (degrades to context-seeded replay on session expiry — acceptable). |
| 2. PostToolUse completion marker (toward effectively-once) | **M–L** | **Medium** — new hook on the hot path; adds per-tool write latency; must be best-effort (never block the tool). |

### (e) Recommendation

- **Item 1 (gated resume-from-snapshot): BUILD NOW — this is the build worth scheduling.** Rationale: (i) the benchmark explicitly named it the highest-value upgrade; (ii) the capture half is *already live and paid for* — leaving it write-only is pure waste; (iii) the minimal version reuses the existing fail-CLOSED band/verdict gates, so it adds capability without adding a new safety surface; (iv) it converts a real (if infrequent) silent loss — a crashed mid-investigation session getting archived — into recovered work or an honest escalation. Scope it tightly (read-only-pending + AUTO-band only) and gate it behind a sentinel (`~/gateway.resume_from_snapshot`) for a dark-first rollout, matching the platform's established pattern. This is the one place across all three gaps where new runtime code is clearly justified by the evidence.
- **Item 2 (effectively-once / completion markers): BUILD LATER.** Worth doing once item 1 proves resume is exercised in practice; premature otherwise. It is the correct *next* step, not the *first* one.
- **Adopting Temporal/Dapr for true durable execution: ACCEPT (do not adopt).** Consistent with the orchestrator's foundational decision (`docs/orchestration-governance-research-2026-06-25.md`: compose, don't adopt-a-platform). A full durable-execution engine is a rewrite the workload does not justify; the checkpoint school with a *closed* resume loop is the right tier for LLM-agent state, and item 1 gets us there.

---

## Summary table

| Gap | Bench | Minimal move | Effort | Recommendation |
|---|---|---|---|---|
| **1. Topology** — no named/swappable set; multi-agent path unreachable (0 Task/331) | 3.0 B | Make existing agents reachable on dispatch + emit `team_charter`; then name topologies in ~80-LOC selector | S → S–M | **BUILD LATER** (reachability near-term); Magentic ledger **ACCEPT** |
| **2. Supervision** — no named supervisor; soft role contract | 4.3 A− | Author `mast-failure-mode-mapping.md`; make handoff envelope + depth-cap mandatory *once handoffs are live* | S | MAST doc **BUILD NOW**; mandatory envelope **BUILD LATER** (after Gap 1); supervisor component **ACCEPT** |
| **3. Durability** — recovery loop OPEN (snapshots captured, never resumed) | 3.0 B | Gated resume-from-snapshot in reconcile (read-only-pending + AUTO-band only, sentinel-dark) | M | **BUILD NOW** (the one justified new-code build); effectively-once **BUILD LATER**; Temporal **ACCEPT** |

**Net of the three:** exactly **two** items warrant building before more benchmark data accrues — the **MAST mapping doc** (Gap 2, half a day, zero runtime risk) and the **gated resume-from-snapshot** (Gap 3, ~1–2 days, reuses existing fail-CLOSED gates, closes a named highest-value gap). Everything else is correctly **deferred until the dispatched multi-agent path is actually exercised** (Gap 1 wiring + Gap 2 contract enforcement) or **accepted as a deliberate design choice** (Magentic ledger, dedicated supervisor component, Temporal-style durable execution) consistent with the orchestrator's compose-don't-adopt foundation and the default-to-least-autonomous principle.

---

## Sources

- Microsoft — Semantic Kernel Agent Orchestration (five named patterns); Agent Framework 1.0 (sequential/concurrent/handoff/group-chat/**Magentic**). https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-orchestration/ · https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/
- Azure Architecture Center — AI agent orchestration patterns. https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns
- AutoGen / **Magentic-One** — supervisor-router + task ledger. https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/
- OpenAI Agents SDK — Orchestration & handoffs; Running agents (max_turns); RunState. https://developers.openai.com/api/docs/guides/agents/orchestration · https://openai.github.io/openai-agents-python/running_agents/
- AWS Bedrock — Multi-agent collaboration (supervisor + routing fallback). https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html
- Berkeley — Why Do Multi-Agent LLM Systems Fail? (**MAST**, arXiv 2503.13657). https://arxiv.org/abs/2503.13657
- Temporal — Understanding Temporal (Event History, effectively-once, determinism). https://docs.temporal.io/evaluate/understanding-temporal
- LangGraph — Durable Execution (checkpointers, thread_id, resume/time-travel). https://docs.langchain.com/oss/python/langgraph/durable-execution
- Diagrid — Why Checkpoints Aren't Durable Execution. https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short-for-production-agent-workflows
- Anthropic — Building Effective AI Agents (default to the least-autonomous design that works). https://www.anthropic.com/engineering/building-effective-agents

*Companion to [`orchestrator-plane-benchmark-2026-06-26.md`](orchestrator-plane-benchmark-2026-06-26.md). All "how it does it today" claims were re-verified against live files on 2026-06-26: `scripts/agent_as_tool.py`, `scripts/lib/team_formation.py`, `scripts/lib/handoff_depth.py`, `scripts/lib/handoff.py`, `scripts/lib/snapshot.py`, `scripts/hooks/snapshot-pre-tool.sh`, `scripts/reconcile-completed-sessions.py`, `scripts/classify-session-risk.py`, `scripts/orchestration-benchmark.py`, and the `.claude/agents/` roster.*
