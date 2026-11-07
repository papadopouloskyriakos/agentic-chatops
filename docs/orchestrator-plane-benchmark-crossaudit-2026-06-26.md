>**Verification note (added 2026-06-26 after the audit, per the verify-agent-claims rule):** Two findings were re-checked against the canonical `main` branch and revised. **U2's "git-untracked config" is a governance-branch artifact** — `component-registry.json`, `interaction-graph.json`, and `orchestration-scorecard.json` are all TRACKED on `main`; the audit's `git status` ran on a diverged working branch. The real U2 residual is only the missing config-validation gate (the admin/admin Cronicle password is an accepted operator decision). **U5's "zero lineage" is overstated** — per-brick run lineage IS emitted via the Prometheus `*_last_run_timestamp_seconds` metrics; the JSON's `generated_unix: null` is deliberate to keep the committed artifacts diff-stable. The genuinely actionable cross-audit gaps are **U4** (brick self-resource-caps) and **U6** (open-loop heal → exponential backoff), addressed in follow-up commits.

# Orchestrator / Control-Plane Benchmark — Cross-Audit Addendum (Unsurfaced Dimensions)

**Date:** 2026-06-26
**Companion to:** [`docs/orchestrator-plane-benchmark-2026-06-26.md`](orchestrator-plane-benchmark-2026-06-26.md) (the primary 11-dimension control-plane benchmark, overall **B+ / 3.48**)
**Method:** Re-read the six prior **underlying-system** benchmark artifacts, extracted the ~50 distinct evaluation dimensions they used, and asked one question of each: *does this dimension also apply to the orchestrator/control plane — and was it covered by the new 11?* This addendum scores only the dimensions that (a) genuinely apply to the control plane and (b) were **NOT** among the 11. Every assessment is grounded in the control-plane code (`scripts/platform-controller.py`, the three orchestrator bricks, `scripts/lib/cronicle.py`, `scripts/write-cronicle-metrics.py`, `scripts/write-governance-metrics.py`, `scripts/classify-session-risk.py`), not in prose.

> **Why an addendum exists.** The primary benchmark scored the control plane against *agentic-control-plane* standards (k8s operators, Temporal, MAST, OTel-GenAI, OWASP-Agentic). The six prior scorecards scored the *underlying system* against *agent-engineering / LLM-engineering / MLOps* standards. Several of those latter dimensions are **operational-plane** properties — scheduling correctness, config-as-data, cost/FinOps, capacity self-containment, artifact lineage, the controller's own self-improvement loop — that apply squarely to an orchestrator yet fall *between* the 11 control-plane dimensions. Those are the gaps below. This team grades its weak halves C/D; the addendum is mostly C/D because these are the genuinely under-built operational seams, not the safety spine the 11 already credit at A.

---

## Provenance of the dimension inventory

| Source benchmark | Dimensions it used (count) |
|---|---|
| `scorecard-anthropic-2026-06-26.md` | 10 (pattern-fit, model-selection, modular-design, observability, context-mgmt, multi-agent, eval-rigor, safety, **resource/token economics**, future-readiness) |
| `scorecard-openai-2026-06-26.md` | 10 (when-to-build, model-selection, tool-design, instruction-quality, single-vs-multi, orchestration-pattern, guardrails-layered, human-intervention, optimistic-tripwires, iterative-deployment) |
| `benchmark-synthesis-2026-06-26.md` | provenance-tagged join of the above 20 |
| `book-gap-analysis.md` (Gulli, 21 patterns) | incl. **Resource Optimization**, Prioritization, Exploration & Discovery, Exception Handling |
| `llm-engineers-handbook-gap-analysis.md` (12 themes) | incl. **Architecture/FTI (config-as-data)**, **Tooling-stack (single cost source-of-truth, pin-everything)**, **Deployment (topology/reliability, sliding-window alerting, IAM)**, **MLOps (versioning/lineage/staging)**, **Inference-optimization (capacity, batching, latency decomposition)** |
| `nvidia_dli_cross_audit_20260429` (12 dims) | incl. **Server-side patterns**, **State management / concurrency**, **Data flywheel**, looping/inference-time-scaling, production observability |

**Already covered by the 11 (excluded here):** liveness/self-healing, separation-of-concerns, coordination-topology, durability/state-recovery, failure-handling/resilience, supervision/termination/verification, HITL/reversibility, distributed-tracing observability, evaluation/benchmarking, governance/auditability, security/identity/meta-monitoring. The prior-source dimensions that map cleanly onto these 11 (e.g. NVIDIA "guardrails" → HITL #7; Handbook "prompt-monitoring" → observability #8; Anthropic "safety" → HITL #7 + supervision #6) are **not** re-scored.

---

## Scorecard — Unsurfaced Control-Plane Dimensions

| # | Unsurfaced dimension | Score / 5 | Grade | One-line verdict |
|---|---|---|---|---|
| U1 | Scheduling Correctness & Timing Reliability (the scheduler *as* a control surface) | 2.5 | C+ | Cronicle gives per-job-death visibility raw cron lacked + clash detection, but no missed-run catch-up, no schedule-drift/skew handling, and the heal path re-runs blindly without an idempotency contract. |
| U2 | Configuration Management & Config-as-Data | 1.5 | D | The control plane's entire declarative state (registry / interaction-graph / scorecard, 200KB) is **git-untracked**, Cronicle still ships **admin/admin**, and there is no config validation/test-before-apply gate. |
| U3 | Cost / FinOps of the Control Plane Itself | 3.5 | B | Structurally near-free (fully deterministic, zero LLM tokens — the correct design) and per-mission cost is gated; but the control plane's own compute/API footprint is **unmetered** and there is no orchestrator-level budget envelope. |
| U4 | Capacity Planning & Resource Self-Containment | 2.0 | C- | Every brick has subprocess `timeout` guards, but none caps its **own** memory/CPU; `interaction-graph.py` does an unbounded full-repo glob-and-read each run; the whole plane is single-host with no capacity headroom model. |
| U5 | Control-Plane State Lineage & Versioning | 2.0 | C- | The bricks' own JSON artifacts sit **outside** the `schema_version` registry, carry no `generated_unix`/provenance stamp when written, and have no migration/rollback story — the exact lineage gap the Handbook audit flagged, now recurring one layer up. |
| U6 | Control-Plane Self-Improvement / Data Flywheel | 2.0 | C- | The bricks **observe and report** (registry/graph/benchmark) but the *actuator* never learns from its own history: flat 3/hr rate-limit, no backoff tuning, no clean-run reset, no closed loop from escalation outcomes back into heal policy. |

**Addendum mean: 2.25 / 5 (C).** This is *lower* than the primary benchmark's 3.48 by design — the 11 dimensions front-loaded the system's genuine A-grade halves (safety, verification, meta-monitoring); the operational seams the prior sources cared about are exactly where this control plane is youngest (the Cronicle migration, the registry, and the platform-controller are all **2026-06-26**, days old).

---

## Per-Dimension Detail

### U1. Scheduling Correctness & Timing Reliability — 2.5 / C+

**Why it applies to the control plane.** The scheduler *is* a control surface: it decides *when* every cron/brick/metric-writer fires. The NVIDIA "server-side patterns" and Handbook "Deployment" dimensions both judge whether scheduling/serving is *reliable over sliding windows with threshold alerting*. An orchestrator that can't tell a job *failed* from a job that *never ran* has a blind control surface — precisely the dark-component class the registry was built to close. This is distinct from the 11's "liveness/self-healing" (#1, which is about reconciling *desired vs observed state*) — U1 is about the *temporal correctness of the firing itself*.

**Evidence (read the code).** The 2026-06-26 Cronicle migration is a real upgrade: `write-cronicle-metrics.py` surfaces `cronicle_jobs_failed_recently` ("the per-job-death gap raw cron could never surface") and `cronicle_scheduler_up`, fail-safe to `0` on unreachable. `interaction-graph.py` mechanically detects `CRON-CLASH` (≥2 jobs at the same explicit minute) — a genuine resource-contention guard cron never had. `cronicle.py:run_now()` lets the controller re-fire a failed job. **But the gaps are real:** (a) **no missed-run catch-up** — `cronicle.py:run_now` is invoked only *reactively* by `platform-controller.reconcile_cronicle_jobs()` after a non-zero exit; a job that simply *didn't fire* (host asleep, scheduler restart window) is not backfilled — `grep` for `catch.?up|missed|backfill|drift|skew` returns only the `run_now` docstring. (b) **No schedule-drift / clock-skew handling** — staleness is judged purely on wall-clock mtime/`time_start` deltas with hardcoded thresholds; an NTP slip or a DST-equivalent edge is undetected. (c) **The re-run heal is blind to idempotency** — `SAFE_RERUN_HINTS` is a substring allowlist on title-or-path (`"-metrics."`, `"registry-seed"`, …), *not* an author-declared idempotency contract, so the controller's safety here is a heuristic, not a guarantee.

**Concrete gap.** Add a missed-run detector (expected-cadence vs last-`time_start` → backfill or alert), an NTP/skew check on the scheduler host, and replace the substring `SAFE_RERUN_HINTS` with a declared `idempotent: true` field per Cronicle job. **Score 2.5 / C+** — the migration genuinely improved visibility (the hard part), but timing *correctness* (catch-up, skew, declared idempotency) is unbuilt.

---

### U2. Configuration Management & Config-as-Data — 1.5 / D

**Why it applies to the control plane.** The Handbook "Architecture/FTI" dimension explicitly demands **config-as-data** and **pin/version everything**; the primary benchmark's own Governance dimension (#10) notes "Git versions the docs/code, not the runtime rows." The control plane's *declarative manifest* (which components exist, which are critical, which are known-dark) is the single most load-bearing config in the whole orchestrator — `registry-check.py` exits non-zero (→ tier-1 SMS) based entirely on it. If that config is unmanaged, the control plane's own behavior is unreproducible and silently mutable.

**Evidence (verified on disk).** The three orchestrator config artifacts are **git-untracked** — `git status` shows `?? config/component-registry.json` (133 KB), `?? config/interaction-graph.json` (65 KB), `?? config/orchestration-scorecard.json` (3 KB), and `git check-ignore` confirms they are *not* even deliberately `.gitignore`d — they are simply outside version control. The registry's hand-authored fields (`owner`, `kill_switch`, `critical`, `known_dark`) — the human judgement that decides what pages a human at 3am — live **only** on the live LXC's filesystem with no history, no review, no rollback. Separately, `cronicle.py:_admin_pw()` falls back to the literal `"admin"` (no `CRONICLE_ADMIN_PASSWORD` in `.env`), matching the memory note that **admin/admin is still set** on the scheduler that now owns all 172 jobs — an unmanaged credential on the control surface. There is **no config validation / test-before-apply gate**: `registry-seed.py` merges discovery into the manifest with no schema check, and `platform-controller.py` reads `CRITICAL_WF` / `SAFE_RERUN_HINTS` as **hardcoded module constants**, not loaded-and-validated config.

**Concrete gap.** Commit the three artifacts (or a reviewed seed of them) under version control with a CI schema-validation gate; change the Cronicle admin credential off `admin/admin`; externalize `CRITICAL_WF`/`SAFE_RERUN_HINTS` into the versioned registry and load-with-validation. **Score 1.5 / D** — the lowest in the addendum: the control plane's own brain-state is unversioned and one credential is default. (Caveat softening it off a flat 1.0: the *discovery* is idempotent and the manifest *self-heals* its observed fields on re-seed, so drift in the auto-discovered half is bounded; the un-governed half is the hand-authored judgement + the credential.)

---

### U3. Cost / FinOps of the Control Plane Itself — 3.5 / B

**Why it applies.** Anthropic "Resource/token economics", Gulli "Resource Optimization", and both books' model-selection dimensions all judge cost discipline. Applied to the *control* plane specifically, the question is: does the layer that watches everything add a runaway-cost surface of its own? An orchestrator that spends LLM tokens to decide when to restart a workflow would be a new $47K-runaway vector.

**Evidence.** The control plane is **structurally near-free, and that is the correct design** — a `grep` for `claude -p|ollama|anthropic|llm_usage|model` across all seven control-plane scripts returns *nothing* (the one `interaction-graph.py` hit is the word "model" in a Dagster-asset-model comment). Every brick is pure-deterministic Python over SQLite/HTTP — zero LLM tokens, $0 marginal. The mission-lane runaway guards the prior scorecards demanded (per-session/daily cost gate, the `session-tripwire.sh` kill on token/cost breach, `MemoryMax=12G`) are credited elsewhere. **The gap is metering, not spend:** the control plane's own footprint (n8n API polls every 5 min over 250 workflows, the full-repo glob scan, the Cronicle history pulls at `limit=2000`/`limit=300`) is **unmetered** — there is no `control_plane_compute_seconds` or API-call-budget metric, so a future brick that quietly starts doing expensive work (or an LLM call sneaking into a brick) would be invisible on the cost plane until it bit. There is also no orchestrator-level budget *envelope* (the $25/day gate is on the mission lane).

**Concrete gap.** Emit a control-plane self-cost metric (CPU-seconds + API-call count per brick) and an assertion/alert that the control plane stays LLM-free (the "no `claude -p` in a brick" invariant, mechanically checked). **Score 3.5 / B** — high because the *design* is right (deterministic, $0); docked because the plane doesn't *measure* its own footprint, so the no-runaway property is true-by-construction-today but unguarded against tomorrow.

---

### U4. Capacity Planning & Resource Self-Containment — 2.0 / C-

**Why it applies.** Handbook "Inference-optimization" and "Deployment" judge capacity, batching, and resource bounds; the primary benchmark itself docked the *mission* launcher for `MemoryMax`-absent and noted the whole gateway is single-host. The same lens on the *control* plane: does the watcher contain its own resource use so a heavy brick run can't starve the very platform it guards?

**Evidence.** Containment of *children* is good — `platform-controller.py` wraps every actuation in a `timeout` (15s n8n, 60s service restart, 180s watchdog-heals), and the bricks `timeout`-guard their subprocesses. **But no brick caps its OWN footprint:** `grep` for `MemoryMax|CPUQuota|systemd-run|nice|ionice` in `registry-seed.py` / `interaction-graph.py` / `orchestration-benchmark.py` / `platform-controller.py` returns only the subprocess `timeout=` calls — none runs under a `systemd-run --scope -p MemoryMax` slice (unlike the mission launcher, which now does, and unlike finops-agora's batch slice). `interaction-graph.py` does an **unbounded full-repo glob-and-read** (`scripts/**/*.{sh,py}` + `openclaw/**`, every file `read_text()` into memory) on a daily cron — fine at 238 scripts, but it has no ceiling and shares the LXC with the n8n pipeline that has a documented OOM history (the 2026-06-25 claude01 LXC OOM that wedged pve04). The dead-man heartbeat itself is single-host: `_HOST = socket.gethostname()` — there is **no second independent timesource/host** for the heartbeat (the primary benchmark credits the `absent()` snitch but the snitch and the heartbeat-emitter are co-resident).

**Concrete gap.** Run the bricks under a bounded `systemd-run --user --scope -p MemoryMax=<N>` slice (mirror the mission launcher fix), put a file-count/size ceiling on the interaction-graph scan, and move the dead-man's external snitch (Healthchecks.io, already provisioned) onto genuinely separate infrastructure. **Score 2.0 / C-** — child-containment is solid, self-containment and capacity-headroom are absent, and the watcher shares fate with the watched on one host.

---

### U5. Control-Plane State Lineage & Versioning — 2.0 / C-

**Why it applies.** Handbook MLOps cross-cutting gap #5 ("Tables and traces outside the schema-version / lineage governance") and the FTI "versioned-contract" property judge whether every artifact carries provenance and lives under a versioning regime. The control plane *produces* governance artifacts (the registry, the interaction graph, the orchestration scorecard, the governance metrics) — if those carry no lineage, the governance record is itself ungoverned.

**Evidence.** The brick artifacts are written as bare JSON with **no provenance stamp populated**: `interaction-graph.py` and `orchestration-benchmark.py` both literally write `"generated_unix": None` into their output cards (the field exists but is never filled with `time.time()`), so a reader cannot tell *when* a given graph/scorecard was generated from the file alone. None of `component-registry` / `interaction-graph` / `orchestration-scorecard` is registered in `scripts/lib/schema_version.py` (confirmed — they are JSON files, deliberately outside the table registry, but that means they also escape the schema-version *discipline* entirely: no version field, no migration, no `check_row`-equivalent). The same `valid_until`-style schema-drift the Handbook audit flagged for `incident_knowledge` recurs here one layer up: the control plane's own state has no lineage column, no model/threshold-at-generation-time stamp, and no rollback path (the only "version" is git — and per U2 these files aren't even *in* git).

**Concrete gap.** Populate `generated_unix` on write (trivial — the field is already there); add a `schema_version` + generator-version stamp to each brick artifact; bring them under either the schema-version registry's discipline or a documented config-versioning regime with rollback. **Score 2.0 / C-** — the artifacts are honest and mechanically regenerable, but they carry zero self-describing lineage and sit outside every versioning regime the system otherwise prides itself on.

---

### U6. Control-Plane Self-Improvement / Data Flywheel — 2.0 / C-

**Why it applies.** NVIDIA "data flywheel" and Anthropic "evals-as-flywheel" judge whether the system *learns from its own production history*. The primary benchmark credits the *mission* lane's flywheel (judge → trials → infragraph learn) under Evaluation (#9), and credits the *reconciliation* loop's correctness under Liveness (#1). U6 is the orphaned third thing: does the **actuator** (`platform-controller.py`) improve its *own heal policy* from the outcomes of its past heals? An operator that escalates the same flapping component identically forever, never tuning, is a static controller.

**Evidence.** The bricks are **observe-and-report**, not learn-and-adapt: `registry-check`, `interaction-graph`, and `orchestration-benchmark` emit metrics + reports and the governance writer (`write-governance-metrics.py`) even feeds an **auto-demote** loop on the *mission* lane (≥3×/30d repeat-offender → `analysis_only`) — a genuine flywheel, but that's mission governance, credited under #1/#10. The **controller's own** heal policy is *static*: `HEAL_CAP_PER_HOUR` is a flat `3`, the backoff is "a flat sliding 3/hr rate-limit" (the primary benchmark's own dock on #1), `_act()` records every attempt regardless of outcome with **no clean-run reset**, and **nothing feeds escalation outcomes back into the policy** — if `write-test-metrics.sh` flaps and escalates every single day, the cap stays 3, the backoff never lengthens, and the controller never proposes "this component is chronically unhealable, raise a structural ticket." There is no `platform_controller` equivalent of the governance auto-demote: the actuator has a circuit-breaker (escalate-on-cap) but no *learning* on top of it.

**Concrete gap.** Give the controller the flywheel its sibling governance loop already has: exponential-backoff-with-clean-run-reset (replacing the flat cap), and a history-driven escalation that converts a chronically-unhealable target into a durable ticket rather than a daily identical SMS. **Score 2.0 / C-** — the *observation* bricks are excellent and the *mission* lane has a real flywheel, but the actuator's own policy is open-loop.

---

## Honesty notes

- **These are deliberately the weak halves.** The 11 primary dimensions captured the system's A-grade safety/verification/meta-monitoring spine. This addendum is the operational underbelly the prior agent-engineering and LLM-engineering sources cared about — and it is young: Cronicle, the registry, and the platform-controller all landed **2026-06-26**, so a C/D here is "days-old seam," not "rotted core."
- **No double-counting.** Dimensions that map onto the 11 (NVIDIA-guardrails→#7, Handbook-prompt-monitoring→#8, Anthropic-safety→#6/#7, the mission-lane cost/runaway guards→#5/#9, the reconciliation loop→#1) were excluded. U3's near-free design and U6's mission-lane flywheel are explicitly *credited to the 11* and only their *control-plane-specific* residue is scored here.
- **U2 (D) is the single highest-leverage fix:** version-control the registry/graph/scorecard + rotate the Cronicle admin credential. It is low-effort, closes a reproducibility-and-credential gap on the most load-bearing config in the orchestrator, and unblocks U5 (lineage) for free.

---

## Sources (dimension provenance only — full standard citations in the primary benchmark)

- `docs/scorecard-anthropic-2026-06-26.md`, `docs/scorecard-openai-2026-06-26.md`, `docs/benchmark-synthesis-2026-06-26.md`
- `docs/book-gap-analysis.md` (Gulli, *Agentic Design Patterns*)
- `docs/llm-engineers-handbook-gap-analysis.md` (Iusztin & Labonne, *LLM Engineer's Handbook*)
- `memory/autonomous_benchmark_mission_20260625.md`, `memory/nvidia_dli_cross_audit_20260429.md`
- Control-plane code: `scripts/platform-controller.py`, `scripts/registry-{seed,check}.py`, `scripts/interaction-graph.py`, `scripts/orchestration-benchmark.py`, `scripts/lib/cronicle.py`, `scripts/write-cronicle-metrics.py`, `scripts/write-governance-metrics.py`, `scripts/classify-session-risk.py`

*Addendum generated 2026-06-26. Every concrete claim (untracked config, admin/admin, zero-LLM control plane, flat heal cap, `generated_unix: None`, no MemoryMax on the bricks) was verified against live files/`git status` at audit time, not inferred from the prose.*
