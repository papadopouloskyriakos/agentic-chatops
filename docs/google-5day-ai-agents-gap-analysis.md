# Google 5-Day AI Agents Course — Codebase Gap Analysis, Scorecard & Roadmap

> **Source #10** of the claude-gateway Master Scorecard. Slots alongside the existing 9-source aggregate (**A+ 4.79/5.0**, `docs/agentic-platform-state-2026-04-29.md`). All scores below are adversarially-corrected per-dimension audits; the aggregate is the arithmetic mean of the 16 corrected dimension scores.

---

## 1. Executive Summary

The Google 5-Day AI Agents course is the **hardest benchmark yet applied** to claude-gateway, and it is the only source so far to score the system materially below A. Where the existing 9 sources (Anthropic, Karpathy, Gulli, MemPalace, OpenAI SDK, Industry Research, NVIDIA DLI, …) largely reward *patterns the system has adopted*, this course rewards **deterministic, host-enforced production-security guarantees** and **spec-as-source-of-truth discipline** — two areas where the system is honest-to-a-fault scaffolded but not yet *lived*.

**Overall grade for Source #10: `B+` — 3.61/5.0** (mean of 16 corrected dimensions).

This sits **−1.18 below the 9-source aggregate (4.79)** and would, if folded in, pull the Master Scorecard's mean from 4.79 toward ~4.68 across 10 sources. That gap is **diagnostic, not a regression** — it is concentrated in exactly the places the prior sources did not probe:

- **The single lowest dimension is D10 (Deterministic Blast-Radius Containment) at `C-` 2/5.** The production Tier-2 agent runs `claude -p --dangerously-skip-permissions` directly in a live git workspace on the nl-claude01 LXC, with full ambient credentials, no ephemeral/network-isolated sandbox, and — a finding the audit surfaced that the system's own docs had not — **the one genuine deterministic guard (`unified-guard.sh`) does not even cover the production path** (it is scoped to the `claude-gateway` repo's `.claude/settings.json`, but the Runner launches from `products/cubeos`). This is the system's most consequential and most actionable gap.
- **D2 (Spec-Driven Development), D9 (Continuous Effective Trust), D11 (Supply-Chain Provenance), D13 (FinOps), and D14 (Open-Protocol Interop) all land at `B-`/`B` (3/5)** — each a faithful, well-built *scaffold* that is dormant, unwired, or un-exercised against the course's *lived-discipline* mastery bar.

**Where the system genuinely shines:** **D3 (Structured Grounding / Knowledge Graph) at `A` 5/5** — the Infragraph causal KG with its fail-CLOSED `plan_hash`-keyed prediction gate, shuffled-graph falsifiable control (`control_ratio ≤ 0.5`, backtest 0.367), and mechanical match/partial/deviation verdicts is *exactly* the course's "structured grounding over dumped context, side-effect simulation before you write a line" thesis, and it is production-wired. Eight further dimensions (D1, D4, D5, D6, D7, D8, D12, D15) land at `A-`/`B+` (4/5), reflecting genuinely strong harness engineering, skill discipline, trajectory evaluation, and a risk-tiered human-as-circuit-breaker model.

**The through-line of every gap:** the system over-invests in *the brain* (graph grounding, prompt evolution, eval rigor, governance circuit-breakers) and under-invests in *the cage* (sandbox, JIT credentials, egress control) and *the contract* (a versioned behavioral spec that the running system is regenerable from). Closing D10 first, then wiring the already-built-but-dormant assets (OpenBao JIT, bi-temporal invalidation, `modelHint`→`SESSION_MODEL`, the spec validator into CI), is the fastest path to lifting this source toward A.

---

## 2. Dimension-by-Dimension Scorecard

| ID | Dimension | Score | Letter | One-line verdict |
|----|-----------|:-----:|:------:|------------------|
| **D1** | Harness Engineering over Model Reliance | 4/5 | A− | ~90% harness, swappable model, deterministic hooks — but no sandbox/JIT/egress and `modelHint` swap dead-ends. |
| **D2** | Spec-Driven Development | 3/5 | B− | Complete EARS+Gherkin+contract bootstrap-pack — but greenfield-only, never run, no spec for the gateway itself. |
| **D3** | Structured Grounding (Knowledge Graph) | 5/5 | A | Infragraph causal KG + fail-CLOSED prediction gate + falsifiable shuffled-control. The standout dimension. |
| **D4** | Skills, Progressive Disclosure & Procedural Memory | 4/5 | A− | 7 governed SKILL.md folders, real progressive disclosure, Prometheus-wired prereqs — no semantic router / selection evals. |
| **D5** | Clean Capability Boundaries (Skill/MCP/Tool) | 4/5 | A− | Sub-agent boundaries are A+; ~153-tool main session + no library-level collision eval cap it. |
| **D6** | Off-Prompt State & DAG Orchestration | 4/5 | B+ | Pointer-clean live hot path (`claude -r`) + SQLite controller — but no capability-profile hard-reset on version swap. |
| **D7** | Trajectory- & Plan-Aware Evaluation | 4/5 | A− | OTel + plan generation + fail-CLOSED prediction gate + mechanical verdict — but no plan-vs-request critic, no tool-sequence check. |
| **D8** | Evaluation Rigor (de-correlated judges, pass@k) | 4/5 | A− | Real de-correlated jury, sealed-holdout decontam, overfit detector — but no true pass@k, no library-level skill-collision eval. |
| **D9** | Continuous Effective Trust & Drift Detection | 3/5 | B− | Runtime+context drift via infragraph deviation + governance demote — no supply-chain/identity trust, no fused score, no AGBOM. |
| **D10** | Deterministic Blast-Radius Containment | 2/5 | C− | **Lowest.** No sandbox, full ambient creds, no egress control, and the one real guard doesn't cover the production path. |
| **D11** | Supply-Chain & Skill/Dependency Provenance | 3/5 | B− | Skill cards + model provenance + SBOM + host guard — but no skill/dep vuln scan, no inbound secret gate, no continuous monitoring. |
| **D12** | Human as Risk-Tiered Circuit-Breaker | 4/5 | A− | Strong 3-band model + mechanical floor + kill-switch — no vibe/semantic diff, no batched middle tier, no injection-escalation. |
| **D13** | FinOps / Token Economics & Hard Cost Controls | 3/5 | B | Real daily kill-switch + deterministic bypass — but right-sizing is computed-then-discarded; every Tier-2 session runs Opus. |
| **D14** | Open-Protocol Interoperability (MCP/A2A/A2UI) | 3/5 | B | Google-A2A-aligned envelope + per-agent MCP RBAC — but static discovery, bespoke transport, no A2UI/commerce, cards decorative. |
| **D15** | Microagent Architecture for Long-Horizon Tasks | 4/5 | A− | Real microagent fleet + worktree workers + merge leash — but the decomposition brain is a `NotImplementedError` stub, default-off. |
| **D16** | Closed-Loop Self-Improvement & Failure Mining | 3.75/5 | B | Live A/B prompt loop + 3-set eval flywheel + governance circuit-breaker — but no super-architect feeding spec, no human checkpoint on the live loop. |
| | **AGGREGATE (16 dims, mean)** | **3.61/5** | **B+** | **Source #10. −1.18 vs the 9-source A+ 4.79 aggregate. Gap concentrated in the cage (D10) and the contract (D2).** |

---

## 3. Per-Dimension Detail

### D1 — Harness Engineering over Model Reliance · 4/5 · A−
**Similarities (file-grounded):**
- Harness carries the bulk of complexity (~90% harness): a single `claude -p` wrapped by classifier, fail-closed gate, RAG, breakers, hooks, jailbreak detector, rail, schema versioning, ~37 tables, self-audit crons — `workflows/claude-gateway-runner.json`, `scripts/lib/`.
- Deterministic non-bypassable PreToolUse hooks (allow/reject_content/deny) — `scripts/hooks/unified-guard.sh`, `.claude/settings.json` (matcher `Bash|Edit|Write`).
- Model swappable at the harness layer: `--model ${SESSION_MODEL:-opus}`; multi-tier registry + drift script — `docs/model-provenance.md`, `scripts/check-model-provenance-drift.py`.
- Three-state circuit breakers SQLite-persisted (`CLOSED/OPEN/HALF_OPEN`) — `scripts/lib/circuit_breaker.py`.
- 11 restricted-tool sub-agents (10 haiku, 1 opus), separate-context `code-reviewer`, deterministic `team_formation` roster — `.claude/agents/`, `scripts/lib/team_formation.py`.
- Model-independent safety primitives: fail-CLOSED gate, pure-regex jailbreak detector (incl. Greek), DARK-FIRST rail, handoff POLL≥5/halt≥10 — `scripts/classify-session-risk.py`, `scripts/lib/{jailbreak_detector,intermediate_rail,handoff_depth}.py`.

**Gaps:** No network-isolated ephemeral sandbox (course names the sandbox the most important component); no JIT/zero-ambient-authority credentials (`openbao-token.sh` is unreferenced Phase-4 research); no egress control (only a regex exfil guard); no self-tooling/runtime tool synthesis; no dynamic graduated trust score (discrete bands + binary kill-switches only).

**Technical debt:** `modelHint` computed in Build Prompt but **never assigned to `SESSION_MODEL`** → per-task right-sizing dead-ends to `${SESSION_MODEL:-opus}`; reliability partly rides on model output shapes (`[AUTO-RESOLVE]`/`[POLL]` markers, parsePoll's 8 fixes, judge calibration dated 2026-04-19); sub-agent verification opt-in not enforced; `systemd-run --user --scope` is cgroup accounting only (risk of over-crediting it as a sandbox).

---

### D2 — Spec-Driven Development · 3/5 · B−
**Similarities:** A complete Day-5 spec stack exists as `bootstrap-pack/` (IFRNLLEI01PRD-929) — 5 canonical EARS regexes keyed on `REQ-NNN` (`bootstrap-pack/scripts/validate-project-spec.py`), first-class Gherkin/BDD with strict link-checking (`check_gherkin_parseable`), contract-first OpenAPI/AsyncAPI/JSON-Schema mandated via `PROJECT.json#surfaces` with `$ref` reuse (`bootstrap-pack/.claude/agents/architect.md`), a 7-article reviewed constitution (Test-First / Library-First / Contract-Before-Code), dedicated spec-enforcing agents + a `/bootstrap` meta-skill, a deterministic **17-check** DoD gate (Kahn-DAG, weasel-word ban, risk-score human-review flag), and `tasks.json` as a files-owned-non-overlapping DAG with `planner-decompose.py` (311 LOC) + `tasks-to-epic.py` (161 LOC).

**Gaps:** The production gateway has **no `PROJECT.json`, `constitution.md`, or `spec/` tree of its own** — its code is the source of truth, inverting the course thesis. The pack has **never been run on a real project** (3-commit history; `products/cubeos` has neither). No `AGENTS.md`/`GEMINI.md`/`/specs` hierarchy; no `CHANGELOG`; no super-prompt/hook enforcing spec+test+doc lockstep. The ~37 SQLite tables / 27 workflows / `schema.sql` are not linked to any behavioral spec. The validator is **not wired into CI, the QA suite, or holistic-health**.

**Technical debt:** `check_gherkin_parseable` is substring-matching, not a real parser (its own TODO prefers `cucumber-js --dry-run`); C06/C07 shell out to `npx swagger-cli`/`@asyncapi/cli` (env-fragile; C08 uses Python `jsonschema` and is unaffected); `bootstrap-pack/tests/` has only input fixtures with **no committed test runner**; legacy `*-SPEC.md` files are free-prose "copy-paste this as the initial prompt" specs with zero REQ/EARS/Gherkin.

---

### D3 — Structured Grounding (Knowledge Graph) · 5/5 · A
**Similarities:** Genuine causal infra KG (Infragraph, ~356 nodes/414 edges) over `graph_entities UNIQUE(entity_type,name)` + `graph_relationships` + `infragraph_dynamics` sidecar — `scripts/lib/infragraph.py`, `scripts/migrations/016_infragraph.sql`, `schema.sql`. Frozen query contract (`blast-radius/deps/cascade/explain/health`) with path-product-confidence, cycle-safe, `DEPTH_CAP=5` — `scripts/infragraph-query.py`. **Pre-poll Commit Prediction** commits a `plan_hash`-keyed prediction before approval; Prepare Result **fails CLOSED** (unpredicted → `[POLL-WITHHELD:NO-PREDICTION]` → ANALYSIS-ONLY) — `scripts/infragraph-predict-plan.py`, `workflows/claude-gateway-runner.json`. Verbatim `INFRAGRAPH DEPENDENCY CONTEXT (machine-computed, advisory)` prompt injection — `scripts/classify-session-risk.py`. Layered seed truth (pve 0.95 → librenms 0.90 → netbox 0.85–0.90 → declared 0.85). Open Knowledge Format: 32 host cards + topology/services (73 `.md`) auto-compiled and embedded as an RRF signal — `wiki/hosts/`, `scripts/wiki-compile.py`. Multi-signal RRF + bge-reranker cross-encoder (0.5/0.5 blend) — `scripts/kb-semantic-search.py`. Falsifiable shuffled-graph control (`max_control_ratio ≤ 0.5`, backtest 0.367) + mechanical verdicts — `scripts/infragraph-eval.py`, `scripts/infragraph-verify.py`. Bi-temporal infra (migration 019) + codegraph MCP for CubeOS/MeshSat.

**Gaps:** Bi-temporal self-invalidation is **built but unwired** (`invalidate_edge` only behind `INFRAGRAPH_BITEMPORAL_INVALIDATE`, default shadow/off; decay reporting-only). The code-graph does **not** cover the harness's own code (CubeOS/MeshSat only). `precision_conf08` is honestly empty (best exact hit-rate ~0.36) so the high-confidence subset can't yet drive auto-decisions. No unified GQL/Cypher+vector+FTS surface (Spanner-Graph-style) — approximated by two separate tools.

**Technical debt:** Two parallel grounding stores (Infragraph vs wiki) not cross-validated. **Schema drift:** `incident_knowledge.valid_until` is live-DB-only, absent from `schema.sql` and migrations. Cascade precision noisy (0.054→0.097), `InfragraphPrecisionDrop` hand-suppressed via `incident_knowledge` row 1452 (a stale-row landmine). `rule_family()` is a hand-maintained taxonomy whose change invalidates learned cascade stats.

---

### D4 — Skills, Progressive Disclosure & Procedural Memory · 4/5 · A−
**Similarities:** 7 self-contained SKILL.md folders with full YAML frontmatter — `.claude/skills/{triage,drift-check,alert-status,cost-report,team-formation,wiki-compile,chatops-workflow}/SKILL.md`. Real progressive disclosure (thin body → `CHECKS.md`/`COMMANDS.md`/`QUERIES.sql` on demand). Procedural memory as a versioned 273-line `chatops-workflow` skill. Shift-intelligence-left (`team_formation.py`: "Pure-rule, no LLM, deterministic"). Library-level anti-collision ("Do NOT use for X — use /other"). Governed semver + `audit-skill-versions.sh` + `audit-skill-requires.sh`. Freshness-guarded auto-index (`render-skill-index.py` + `test-656`). Prereqs feed Prometheus (`SkillPrereqMissing`/`SkillMetricsExporterStale`). Context-window-is-not-a-database respected (off-prompt SQLite/RAG/73-article wiki).

**Gaps:** No semantic/hierarchical skill **router** (selection is prose + human directive; `kb-semantic-search.py` has zero skill references). No library-level skill-selection evals / pass@k. Small library (7) with heavyweight procedures still living as plain `docs/runbooks/`. Two parallel "skill" systems collide — `.claude/skills/` (active) vs dormant `openclaw/skills/<name>.sh`, the latter still embedded in live receiver JSON.

**Technical debt:** Force-loading the 273-line `chatops-workflow` every session is mild on-demand-loading tension. `CLAUDE.md` (323 lines) carries an ever-growing dated changelog despite its own anti-regrowth table. Versioning governance is soft (`audit-skill-versions.sh` defaults to exit 0). Semver barely exercised (6/7 at 1.0.0).

---

### D5 — Clean Capability Boundaries · 4/5 · A−
**Similarities:** Skills delegate the capability to deterministic scripts/CLIs and pass the delete test by construction (`team-formation`→`team_formation.py`, `drift-check`→`CHECKS.md`, `cost-report`→`QUERIES.sql`). Real progressive disclosure. MCP scoped per sub-agent (verified by enumeration): `dependency-analyst`/`code-explorer`=codegraph-only, `storage-specialist`=proxmox+netbox, `k8s-diagnostician`=kubernetes+netbox, `cisco-asa-specialist`=no MCP (netmiko-over-Bash). Negative-routing on every skill+agent; uniform minimal `Read/Grep/Glob/Bash`. Advisory pure-rule charter (`team_charter` event). Versioned with prereq audits.

**Gaps:** The delete test is documented only as an imported standard (`docs/google-5day-ai-agents-course-knowledge.md`), not used as a repo-internal acceptance gate. No skill-library collision/ambiguity eval. Main session tool surface **~153** far exceeds the ~15–20 comfort band; a per-category `TOOL_PROFILES` prefer/avoid map IS injected (`config/tool-profiles.json`) but does **not** reduce the surface — no hierarchical router. Per-boundary cost/forcing-factor justification is qualitative, not measured.

**Technical debt:** `cisco-asa-specialist` reach is an unscoped Bash verb (host-enforced, not in the boundary model). `team-formation/SKILL.md:36` self-grades "Audit dim #5 stays at A+" (drift risk). `docs/tri-source-audit.md` records open consolidation gaps (partially uplifted at line 263).

---

### D6 — Off-Prompt State & DAG Orchestration · 4/5 · B+
**Similarities:** Off-prompt file message bus with byte-cursor (`workflows/claude-gateway-progress-poller.json`). Cross-turn continuity by **pointer** via `claude -r session-id` on the live hot path (never re-concatenation). SQLite `gateway.db` as inspectable controller state; large answers stored once as `last_response_b64` and dereferenced on demand. Controller-owned multi-hop guard (`handoff_depth`/`handoff_chain`, atomic immediate txn, POLL@5/halt@10). Structured graph query contract over on-disk SQLite. Re-runnable trajectories (`session-replay` validates the `session_id` pointer). Immutable per-turn snapshot infra exists (`scripts/lib/snapshot.py`).

**Gaps:** **No capability-profile + hard-reset on version swap** (course requires unload/flush/load on a SKILL.md bump; versioning is advisory only). No content-addressed/schema-referenced bus owned by a DAG engine (ad-hoc per-issue tmp files). Snapshot capture **not wired live** (`.claude/settings.json` registers only `unified-guard.sh`). No DAG-controller pointer-on-bus model for sub-agent fan-out. The in-flight trajectory bus is ephemeral (tmp jsonl deleted post-run).

**Technical debt:** `scripts/lib/handoff.py` serialises full `input_history` into the child prompt — but is wired only into QA-only `agent_as_tool.py`, so the anti-pattern is on a dormant surface (live path is pointer-clean). Cross-node state leans on positional node references + regex-scraped sentinels. Skill versioning is decorative for orchestration. The jsonl bus is per-issue, not namespaced by `session_id` (re-trigger race). `snapshot.py` rollback restores only the row, prunes after 7 days, capture hook not registered.

---

### D7 — Trajectory- & Plan-Aware Evaluation · 4/5 · A−
**Similarities:** Full trajectories exported as OTel spans with GenAI conventions + per-tool spans, OTLP→OpenObserve + SQLite fallback + salted trace_ids — `scripts/export-otel-traces.py`. A genuine structured **plan** generated BEFORE execution (`build-investigation-plan.sh`, Haiku, temp=0, hypothesis/steps/tools/plan_confidence). A pre-execution checkpoint ON the plan (`Check Intermediate Rail`, `intermediate_rail.py`, DARK-FIRST). Mandatory `plan_hash`-keyed prediction gate (fail-CLOSED, QA-asserted parity — `test-1044`). Mechanical match/partial/deviation verdicts (`action_verdict`, deviation never auto-resolves). Per-trajectory scoring (`score-trajectory.sh`→`session_trajectory`). Policy-based cost+latency metrics + 2-model conservative jury (`judge_jury_blend.py`). Long-horizon-replay flywheel (consumes `tool_call_log`).

**Gaps:** The pre-code checkpoint is **not a plan-vs-original-request LLM critic** (rail only assesses in-distribution-ness, never blocks). Right-answer-via-wrong-tool-**sequence** is unpenalized (`session_trajectory` is an unordered presence sum; `action_verdict` gates on consequence not path). The LLM judge grades the **final response**, not the trajectory (capture and judging are disjoint). No reward-hacking detector / pass@k on the eval path. OTel export is lossy as a substrate (approximated durations; tool responses/reasoning not captured).

**Technical debt:** `score-trajectory.sh` is a grep-heuristic proxy that advertises "sequence" but sums presence. Three independent JSONL parsers (export-otel / score-trajectory / llm-judge) instead of one canonical trajectory. The plan-stage rail is permanently DARK with no enforcement path. OTLP silently degrades to local-only. (Corrected: the `(purpose not catalogued)` cron annotation is a global auto-gen placeholder, not score-trajectory-specific.)

---

### D8 — Evaluation Rigor · 4/5 · A−
**Similarities:** Production judge de-correlated from generator (separate model + rubric + temp 0) — `scripts/llm-judge.sh`. Live 2-model jury, most-conservative action — `scripts/lib/judge_jury_blend.py`. Stronger-vs-cheaper calibration over 60 fixed queries — `scripts/judge-calibration.py`. Sealed-holdout decontamination gate (id + sha256) — `scripts/check-eval-set-integrity.py`. Clever-Hans overfit detector (reg>95% & hold<80%, or gap>20pts) — `scripts/eval-flywheel.sh`. AI-authored prompts are explicit drafts (GEPA GENERATE-ONLY + DORMANT, Welch t-test sole gate). Reward-hack guard (contamination-free held-out set, `<2026-05-01` cutoff). Adversarial near-miss evals (`run-hard-eval.py`). Falsifiable shuffled-control infragraph eval. RAGAS weighted precision@k. Eval-verified A/B promotion (Welch, min 15/arm, ≥0.05 lift, p<0.1). **Partial:** the action-guard IS eval'd against a red-team corpus (G33–G52) → `redteam_metrics.prom`.

**Gaps:** No true **pass@k / self-consistency / best-of-n** (precision@k is rank-at-k, a different meaning). No library-level skill-collision optimization. Guard layers eval'd for block-rate but **not for value-over-baseline** (no ablation, no rail eval, no gate admitting a model-authored skill to action-tier only after red-teaming + sustained access). Trajectory/plan-level judging absent from the rubric. Manual golden-dataset spot-check of AI-authored skills is informal.

**Technical debt:** Overfit detector reads `golden-test.prom` (every 2 weeks) and silently skips on `REGRESSION_TOTAL=0`. GEPA held-out set built but not wired into finalize as a 2nd gate. Default jury is two **same-family local** models (true de-correlation only on opt-in Opus path). Small eval sets (regression 22 / discovery 20 / holdout 16 / hard-retrieval-v2 50 / hard-kg 10 / ragas 33).

---

### D9 — Continuous Effective Trust & Drift Detection · 3/5 · B−
**Similarities:** Runtime+context trust quadrant is real — 3-band gate, infragraph deviation drift, governance demote-escalate, deterministic backstops, weekly audit, inline jailbreak — `scripts/classify-session-risk.py` + infragraph + governance.

**Gaps:** No supply-chain trust dimension. Identity continuous-trust unmet (only dormant JIT). No fused effective-trust score. No quarantine-then-patch loop before kill. Recalibration ignores self-repair-quality / iteration / latency / cost. No AGBOM boundary / Agent Behavioral Analytics. Drift detection is infra-remediation-scoped only.

**Technical debt:** Auto-demote is **default-ON and self-modifying with no manual review**. Recurrence depends on a flat `triage.log` (silent zero on parse drift). Predictor mid-calibration with `PrecisionDrop` suppressed (row 1452). Trust logic is spread across files with no owning module. HOME-sentinel can silently turn autonomy OFF. OpenBao JIT unwired.

---

### D10 — Deterministic Blast-Radius Containment · 2/5 · C− *(lowest)*
**Similarities:** A genuine deterministic, model-independent PreToolUse guard exists — denies `rm -rf /`/`mkfs`/`systemctl stop`/`kubectl delete namespace|node`/reverse-shell/exfil (`/dev/tcp`, `nc -e`, `curl|bash`, `base64-d|bash`) and reject_content-blocks `.env`/`*.key`/`id_rsa`/`shadow` edits — `scripts/hooks/unified-guard.sh`, `.claude/settings.json`. Resource-blast-radius containment via `systemd-run --user --scope --slice=app.slice` + `timeout` on every launch (8 sites). JIT-credential **intent** correctly scaffolded (`openbao-token.sh` does AppRole auth + revoke-self). An n8n Code-node isolation boundary + mandatory validator.

**Gaps:** **No ephemeral, network-isolated sandbox** for generated code — the Runner launches `claude -p --dangerously-skip-permissions` with no `--allowedTools` allowlist directly in the live git workspace; verified ZERO isolation on the `systemd-run` scope. **The one real guard does not cover the production agent** — it is scoped to the `claude-gateway` repo's settings, but the Runner launches from `products/cubeos`; `~/.claude/settings.json` has no PreToolUse hook → automated Tier-2 sessions run with the guard ABSENT. **Zero-ambient-authority is the opposite of true** — persistent `.env` (ANTHROPIC/YOUTRACK/NETBOX/MATRIX/CISCO tokens) + SSH keys, classic confused-deputy. OpenBao JIT is unbuilt, not dormant (`credential_usage_log` table absent from schema → silent no-op). No egress/NAT-to-approved-URLs perimeter. AI guardrails NOT bound by deterministic ones (jailbreak detector nightly-only; intermediate rail DARK + broken by the n8n `child_process` block). Guard misses the **Read** path (matcher `Bash|Edit|Write` only). No clean-baseline + automatic-stop bound to a sandbox.

**Technical debt:** `credential_usage_log` writes are silent no-ops (`INSERT … || true`). Three overlapping/drifted blocklists (`unified-guard.sh` vs legacy `audit-bash.sh`/`protect-files.sh`) with stale docs still naming the legacy guards as active. Brittle substring matching (`docker exec` broad-blocked while obfuscated equivalents bypass). The dead `Check Intermediate Rail` `execFileSync` node. `systemd-run --scope` risks being mistaken for a sandbox.

---

### D11 — Supply-Chain & Skill/Dependency Provenance · 3/5 · B−
**Similarities:** Machine-readable skill cards (YAML frontmatter: name/version/allowed-tools/requires) across all SKILL.md + agent .md. `audit-skill-requires.sh` + `audit-skill-versions.sh` wired into holistic-health §37. Formal model-provenance chain (pinned IDs, OWASP LLM03/LLM04, trust levels, TLS+SHA-256, quarterly review) — `docs/model-provenance.md`. Automated provenance-drift gate — `scripts/check-model-provenance-drift.py`. CycloneDX SBOM in CI (npm+python, spec 1.6). NIST AG-MP.1 tool-risk classification of 153 tools. gitleaks multi-pass redaction before public mirror. **Broad host guard** (denies destructive + exfil + injection). Prompt-injection detector library. Agent decommissioning doc.

**Gaps:** No **inbound** secret scanning (gitleaks egress-only; no pre-commit/MR gate). No treatment of skills/MCP servers as **untrusted dependencies** scanned for vulns/phone-home/injection. No model-level skill verification. No slop-squatting/`pip|npm|apt install` interception or registry-pin (the guard DOES block `curl|bash`). No NVIDIA-Verify-style skill inspector / signing. No skill trust-tier taxonomy. No continuous dependency monitoring (Dependabot/Snyk/osv/grype/trivy) — SBOM is one-shot.

**Technical debt:** Sole npm dep is a mutable `github:` ref in `package.json` (lockfile DOES pin a commit SHA but has no integrity/SRI hash). SBOM job soft-fails (`|| echo … non-fatal`). `model-provenance.md` partly stale (retired qwen3/devstral in hash example; OpenAI-key internal inconsistency). The repo's OWN benchmark self-scores supply chain 3.5/Managed (LLM03/LLM04 PARTIAL). gitleaks binary downloaded with no checksum verification. MCP documented at capability layer, not artifact layer.

---

### D12 — Human as Risk-Tiered Circuit-Breaker · 4/5 · A−
**Similarities:** Deterministic 3-band model (AUTO / AUTO_NOTICE+SMS / POLL_PAUSE) from mutation/category/blast-radius — `scripts/classify-session-risk.py`. Human-as-circuit-breaker (SMS critical-only). `/alert-session` SMS at classify time, non-blocking. Inline jailbreak forces `high` (fail-closed). `IRREVERSIBLE_PATTERNS` pin destroy/mkfs/zpool/dropdb to the floor. Mechanical safety floor (auto-resolve keys on the fail-CLOSED prediction gate; `infragraph-verify.py` sole verdict writer; deviation never auto-resolves). Auto-resolve posts plain-language `m.notice` (partial vibe-diff). Band-aware weekly auditor with `rm`-kill remediation. Cross-tier `REVIEW_JSON` + DARK-FIRST rail. Evidence-first guard (CONFIDENCE≥0.8 without fence → POLL). Sentinel kill-switch + override.

**Gaps:** No **vibe/semantic/behavioral diff** for non-coder sign-off (zero hits outside the course doc). The **batched-digest middle tier is missing** (bands are effectively binary). Humans review LLM prose, not behavioral assertions. Inbound prompt-injection is **sanitized-and-continues**, not escalated. HITL woven at essentially one transition (no spec-sign-off / log-review checkpoint).

**Technical debt:** `holistic-agentic-health.sh:939` still enforces the LEGACY non-band-aware invariant (false-FAILs reversible-MIXED auto-resolves). `risk-based-auto-approval.md` marks live wiring as "(pending)" though it is LIVE. The HITL middle path is DARK by operator behavior (~0 votes; `timed_out` dominant). 19 outbound scrub regexes (incl. PII) but redact-and-continue, no short-circuit-escalate. `POLL_PROCEED` is a reserved-but-unassigned half-built band.

---

### D13 — FinOps / Token Economics & Hard Cost Controls · 3/5 · B
**Similarities:** Hard daily-budget kill-switch wired (`SUM(cost_usd)` 24h > $25 → `BUDGET_EXCEEDED` → `--plan`) — `workflows/claude-gateway-runner.json`. Per-session soft governor. Strong deterministic LLM-bypass, fail-open — `scripts/lib/tier1_suppression.py`. Wall-clock cap (300/600s `timeout`). Handoff-depth cap + cycle detection; `agent_as_tool.py` passes `--max-turns 15`. Local-first judge (gemma3:12b/qwen2.5:7b, $0). Single-source rate card with cache multipliers — `scripts/lib/pricing.py`. End-to-end metering + `ChatOpsCostBudgetHigh` @ $20. Cost-regression detector (6h, >1.5×). Deliberate kill switches + QA $10 ceiling. **Embedding batching IS implemented** (`memory-audit.py`, `kb-semantic-search.py`).

**Gaps:** No hard turn cap on the **primary** Tier-2 launch (only on the sub-agent path). No proactive prompt-cache engineering (`cache_control`/ephemeral breakpoints absent on the stable Build Prompt preamble — measured, not designed). Daily gate is blunt all-or-nothing (no per-project/tier sub-budgets, no cost-judge). Anomaly tracking WARNs but never KILLs. I-U-S cost-sustainability documented, not gated. Batching limited to embeddings (no judge/synth Message Batches API).

**Technical debt:** **Primary-agent right-sizing is DEAD** — `modelHint` computed then discarded; every Tier-2 session runs Opus. `ChatOpsCostBudgetHigh` annotation says "sessions are refused" but behavior is plan-only. USD/EUR units inconsistency across three framings of the per-session ceiling. Tier-2 being $0 (Max sub) structurally de-prioritised the expensive Opus path. `regression-detector.sh` under-documented in `crontab-reference.md`.

---

### D14 — Open-Protocol Interoperability · 3/5 · B
**Similarities:** NL-A2A v2 aligned to Google A2A (JSON-RPC 2.0 envelope, AgentCard schema, TaskState lifecycle) — `docs/a2a-protocol.md`. Machine-readable agent cards for all 3 tiers. Strong real per-sub-agent MCP RBAC (scoped `mcpServers`; `teacher-agent` excludes Edit/Write+MCP). Protocol-level MCP write safety (NIST classification, read-only NetBox token, `PVE_ALLOW_LIFECYCLE` default off). Agent lifecycle/registry-analog with runtime `INSERT INTO a2a_task_log`. Local registry-and-invoker (`agent_as_tool.py`). The D14 course standard captured verbatim.

**Gaps:** No live A2A discovery (static cards, no `/.well-known/agent.json`, routing hardcoded). No A2UI/component-catalog. No UCP/AP2 commerce mandates. Bespoke transport (`ssh://`/`matrix://`, not A2A HTTP/SSE). No DB read-replica/SELECT-only viewer MCP for the writable gateway.db. O(N×M)→O(N+M) debt never quantified in-repo. Single-org/single-operator network.

**Technical debt:** Card/protocol provenance drift (T2 card `opus-4-6`, protocol prose `GPT-5.1` — though `openclaw-t1.json` is current). A2A path partly dormant in default cc-cc mode (OpenClaw stopped, `onboot=0`). proxmox MCP defaults to root-scoped `root@pam!mcp`. Routing duplicated; cards decorative (read only by test/health, not at runtime). Custom `_nla2a` envelope, not the upstream SDK. `a2a_task_log` absent from `schema.sql` (live/doc-only drift).

---

### D15 — Microagent Architecture for Long-Horizon Tasks · 4/5 · A−
**Similarities:** Fleet of 11 tightly-scoped, domain-aware microagents (read-only-leaning allowlists, model tiers, maxTurns, requires) — `.claude/agents/`. A task-breakdown subsystem with a REAL Kahn-DAG + file-overlap validator + per-worktree real `claude -p` workers — `scripts/parallel-dev/{planner-decompose.py,distribute-workers.sh,allocate-worktree.sh}`. Continual run/test verification leash on the dev path (`merge-coordinator.sh` STOPs on conflict/lint/test red, exit 7/8/9). Anti-runaway guards (`handoff_depth.py` POLL@5/halt@10 + cycle detection; `agent_as_tool.py`). Inspectable, wired roster (`team_formation`, 2 refs in Runner). KG grounding in the live triage hot path (fail-open, 5s timeout). Phased Phase 0→6 delegation with confidence<0.5 escalation. Cheap right-sized plan step (`build-investigation-plan.sh`, ~$0.008).

**Gaps:** The **LLM decomposition itself is a stub** (`planner-decompose.py::run_decomposition()` raises `NotImplementedError`; both copies). The clearest graph-grounded microagent network (parallel-dev) is **default-INACTIVE**, dev-only, not the live infra path. The course's grounded chain is two separate subsystems (infragraph feeds *triage*, not *decomposition*). On the live path the executor is one session that *may* delegate advisorily; `agent_as_tool.py` is referenced in **zero workflows**. Factored Cognition is P4/deferred. The hard mid-run leash exists only for parallel-dev.

**Technical debt:** `agent_as_tool.py` unwired/dormant. `merge-coordinator` LLM-assist reconcile is a TODO (conflicts hard-fail); `PROJECT_ID=27` hardcoded. `team_formation` is observational-only (no eval feedback). Predictor mid-calibration (PrecisionDrop suppressed). Two divergent `gateway.db` path conventions across subsystems. The missing `run_decomposition()` gates the whole flow.

---

### D16 — Closed-Loop Self-Improvement & Failure Mining · 3.75/5 · B
**Similarities:** Real architecture-execution separation scaffold (Kahn-DAG validation, file-ownership, LOC/wall bounds). Sandboxed coders fill blanks (worktree + real `claude -p` + lint/test merge leash). Risk-tiered human-as-circuit-breaker at the MR boundary (`classify-feature-risk.py`, auto_merge only ≤0.7 + zero high-risk/failed). A **LIVE** closed-loop prompt self-improvement loop (judge-graded dims → A/B trials → Welch t-test → `config/prompt-patches.json` with real fired promotions). GEPA reflective generation (GENERATE-ONLY, DORMANT, held-out guard). 3-set eval flywheel with contamination discipline (regression grows, holdout never promotes). Multiple post-deploy log loops as crons. Governance failure-mining circuit-breaker (≥3×/30d repeat-offender → analysis_only, reversible 30d). **A real Gherkin/BDD+EARS spec scaffold exists** (`bootstrap-pack/` — 7-article constitution, 17-check validator).

**Gaps:** The architect's decomposition is **NotImplementedError in BOTH lanes**. The parallel-dev planner workflow is inactive (`triggerCount:0`). **No super-architect closes the loop back into the spec** (self-improvement edits only prompt instructions + suppression rows, never architecture/spec; no `/bootstrap` skill in-repo). Failure clustering is shallow + single-operator (no cross-user root-cause/impact×frequency). `merge-coordinator` LLM-assist is a TODO; `PROJECT_ID=27` hardcoded. **The one fully-LIVE self-modifying loop (prompt-patch) has no human checkpoint** and no pre-promotion holdout re-validation.

**Technical debt:** Both `planner-decompose.py` copies carry `NotImplementedError`; parallel-dev is effectively dead code (high bit-rot risk). Two divergent hardcoded `gateway.db` paths (symlink-reconciled). `crontab-reference.md` self-metadata stale. Prompt-patch auto-promotion lacks a holdout re-run guard (metric-gaming risk). `GOVERNANCE_AUTODEMOTE` default-ON self-modifies the RAG base with no log-review checkpoint, AND the docstring + MEMORY.md still say "default OFF" (stale-doc hazard contradicting live code).

---

## 4. Strengths the System Already Exceeds the Course On

These are areas where claude-gateway is at or beyond the course's mastery bar — worth defending against regression:

1. **Falsifiable, mechanically-adjudicated prediction (D3/D7/D12).** The fail-CLOSED `plan_hash`-keyed prediction gate + shuffled-graph negative control (`control_ratio ≤ 0.5`, backtest 0.367) + mechanical match/partial/deviation verdicts where **the LLM never judges its own outcome** is *stronger* than the course's "evaluate the plan" framing — it is a pre-execution machine prediction that the model cannot bypass and cannot grade.
2. **Genuine causal infrastructure knowledge graph in the live hot path (D3).** Most "graph RAG" systems retrieve; this one *predicts blast radius and gates remediation on it*. The 5/5 here is the highest of any dimension and exceeds the course's structured-grounding bar.
3. **Operator-honest self-assessment culture (cross-cutting).** The repo's own `industry-benchmark` self-scores supply chain at 3.5/Managed and lists gaps verbatim; the system documents its own DARK/dormant/stubbed surfaces rather than over-claiming. This meta-discipline (AI-authored artifacts as drafts, golden-set decontamination, honest `precision_conf08` emptiness) is itself a D8 strength.
4. **Reversible, instantly-revertible governance (D9/D12/D16).** Sentinel-file kill-switches that revert to byte-identical legacy, 30-day-expiring auto-demote, `INFRAGRAPH_DISABLED`/`PROMPT_GEPA_ENABLED` flags — the "circuit-breaker = metric + audit + expiry, no manual review" pattern is a mature operational stance.
5. **Five-signal RRF + cross-encoder rerank with circuit breakers (D3/D8).** Beyond flat keyword RAG, with named breakers and Prometheus-observable retrieval health — exceeds the course's "don't rely on monolithic RAG" bar.

---

## 5. Prioritized Roadmap

Ordered to lift the Source #10 score fastest. Each item is a shippable YT-style issue with the dimensions it closes, effort (S/M/L), and priority (P0–P3). **Phase A delivers the largest score lift per unit effort** (it attacks the 2/5 and the wired-but-dead assets).

### Phase A — Close the cage (highest score-lift; mostly wiring already-built assets)
1. **`[P0/M]` fix(security): scope `unified-guard.sh` PreToolUse hook to the production agent path** — move the hook to `~/.claude/settings.json` (or launch with an explicit `--settings`), add the **Read** matcher so `.env`/`id_rsa`/`shadow` reads are blocked, and reconcile/retire the drifted legacy `audit-bash.sh`/`protect-files.sh` + stale docs. *Closes: D10, D9, D11.* *The single highest-ROI fix — turns the one real guard from repo-scoped-decorative into production-enforcing.*
2. **`[P0/L]` feat(security): ephemeral network-isolated sandbox for the Tier-2 launch** — wrap `claude -p` in gVisor/firejail/nsjail (or a per-session container) with `--allowedTools`/egress NAT-to-approved-URLs, IDE-as-proxy, and clean-baseline + automatic-stop. *Closes: D10, D1, D9.* *The course's #1 security component; biggest absolute gap.*
3. **`[P0/M]` feat(security): wire OpenBao JIT downscoped credentials into the Runner** — activate `openbao-token.sh` on the launch path, add the missing `credential_usage_log` table to `schema.sql`+migration, bind token lifetime to the session, retire the persistent `.env` ambient grant. *Closes: D10, D9, D11.* *Asset already 80% built (cluster deployed, script exists) — finish the last mile.*

### Phase B — Right-size and re-enforce the cheap wins
4. **`[P1/S]` fix(finops): wire `modelHint` → `SESSION_MODEL` on the primary launch** — assign the already-computed hint so simple categories run Sonnet, not Opus; add a primary-launch `--max-turns` cap and per-category sub-budgets. *Closes: D13, D1.* *One-line-ish change that flips dead right-sizing live and is the dominant token-economics defect.*
5. **`[P1/M]` feat(infragraph): wire bi-temporal `invalidate_edge` to the cascade-refutation trigger** — flip the dormant migration-019 self-invalidation on (cascade-refutation from -1118, NOT the FP-prone wiki-IP-contradiction path), with decay still reporting-only behind a flag. *Closes: D3, D9.* *Built and tested; just needs the right live trigger.*
6. **`[P1/S]` fix(governance): reconcile auto-demote default-ON docs + add a log-review checkpoint** — align the `write-governance-metrics.py` docstring + MEMORY.md with live `GOVERNANCE_AUTODEMOTE=1`, and route the self-modifying RAG-base write through a batched human-review digest. *Closes: D16, D9, D12.*

### Phase C — Trust & evaluation depth
7. **`[P2/M]` feat(eval): trajectory-aware judging + ordered tool-sequence check + plan-vs-request critic** — make the LLM judge consume `tool_call_log`/OTel spans, add an ordered-sequence-vs-plan correctness check to `score-trajectory.sh`, and add a blocking plan-vs-original-request critic before token spend. *Closes: D7, D8.*
8. **`[P2/M]` feat(trust): fused continuous effective-trust score + AGBOM boundary + quarantine-then-patch** — replace discrete bands with a dynamic score from drift-velocity/self-repair-quality/iteration/latency/cost; define expected-behavior boundaries (Agent BOM) and a fixer-quarantine path before kill. *Closes: D9, D12.*
9. **`[P2/M]` feat(eval): true pass@k / self-consistency + library-level skill-collision eval** — add per-task k-sampling consistency and a skill/agent routing-ambiguity eval over the 7 skills + 11 agents; gate model-authored skills to action-tier only after red-teaming + sustained access. *Closes: D8, D4, D5.*

### Phase D — Supply chain, spec discipline, interop
10. **`[P2/M]` feat(supply-chain): inbound secret pre-commit gate + skill/dep vuln scanner + continuous monitoring** — add a pre-commit/MR gitleaks gate (block, don't just redact-at-egress), a skill-inspector scanning SKILL.md/MCP code for injection/phone-home, a skill trust-tier taxonomy, and osv/grype consuming the existing SBOM. *Closes: D11, D9.*
11. **`[P3/L]` feat(spec): retroactively spec the gateway + wire `validate-project-spec.py` into CI** — author a `PROJECT.json`/`constitution.md`/`spec/` tree (EARS+Gherkin) for at least one live surface, add an `AGENTS.md`/`/specs` hierarchy + `CHANGELOG`, run the bootstrap-pack on a real consuming project, and wire the validator into QA + holistic-health. *Closes: D2, D16.* *Largest effort; lifts the most under-lived dimension.*
12. **`[P3/M]` feat(microagent): implement `planner-decompose.run_decomposition()` + activate the parallel-dev loop + super-architect spec-feedback** — replace the `NotImplementedError` with real LLM decomposition, activate the planner workflow, derive `PROJECT_ID`, and add a super-architect that feeds mined failures back into the spec under a human checkpoint. *Closes: D15, D16, D2.*
13. **`[P3/M]` feat(interop): live A2A discovery + protocol-level transport + read-replica MCP** — serve `/.well-known/agent.json`, make routing read cards at runtime, add HTTP/SSE A2A transport, a SELECT-only viewer MCP for gateway.db, and downscope the proxmox MCP token off root. *Closes: D14, D11.*

---

## 6. Re-Grade Trigger Conditions

Re-run the relevant dimension audit (and recompute the Source #10 aggregate) when ANY of the following fire:

- **D10 / D1 / D9 — Containment changes:** the Tier-2 launch gains (or loses) a sandbox, egress control, or `--allowedTools` allowlist; `unified-guard.sh` scope changes (moves to user settings, gains/loses the Read matcher, or the production launch cwd changes); OpenBao JIT becomes wired (`credential_usage_log` lands in `schema.sql` + the script is called on the launch path). **→ re-grade D10, D1, D9.**
- **D13 / D1 — Right-sizing wiring:** `SESSION_MODEL` becomes assigned from `modelHint` (any `export SESSION_MODEL=` / `SESSION_MODEL=` setter appears in `claude-gateway-runner.json`), or a primary-launch `--max-turns` / per-category budget lands, or prompt-cache `cache_control` breakpoints are added. **→ re-grade D13, D1.**
- **D3 / D9 — Graph self-correction:** bi-temporal `invalidate_edge` gets a live (non-shadow) caller, OR `compute_confidence_with_decay` begins feeding predictions, OR codegraph indexes the gateway's own code, OR a unified GQL+vector+FTS surface ships. **→ re-grade D3, D9.**
- **D2 / D16 — Spec goes live:** a `PROJECT.json`/`constitution.md`/`spec/` tree or `AGENTS.md`/`/specs` hierarchy appears at the gateway root; `validate-project-spec.py` is wired into CI/QA/holistic-health; the bootstrap-pack is run on a real consuming project; OR a super-architect feeds learnings back into a spec. **→ re-grade D2, D16.**
- **D15 / D16 — Decomposition implemented:** `planner-decompose.run_decomposition()` stops raising `NotImplementedError`, OR the parallel-dev planner workflow flips to `active=true` (`triggerCount` > 0), OR `agent_as_tool.py` becomes referenced in a workflow. **→ re-grade D15, D16.**
- **D7 / D8 — Eval depth:** the LLM judge begins consuming trajectory/`tool_call_log` data; an ordered tool-sequence check or a blocking plan-vs-request critic lands; true pass@k / self-consistency / library-level skill-collision eval is added; the intermediate rail moves from DARK to enforcing. **→ re-grade D7, D8.**
- **D11 / D9 — Supply chain:** an inbound pre-commit/MR secret gate, a skill/dependency vuln scanner, a skill trust-tier taxonomy, model-level skill verification, or continuous dependency monitoring (Dependabot/osv/grype consuming the SBOM) is added. **→ re-grade D11, D9.**
- **D12 — Review tiers:** a vibe/semantic/behavioral diff for non-coder sign-off, a batched-digest middle review tier, behavioral-assertion review, or injection-escalation-to-human is added; OR the legacy non-band-aware invariant in `holistic-agentic-health.sh:939` is fixed. **→ re-grade D12.**
- **D14 — Interop:** live A2A discovery (`/.well-known/agent.json`), runtime card-driven routing, protocol-level HTTP/SSE transport, a read-replica/SELECT-only viewer MCP, A2UI, or commerce mandates land. **→ re-grade D14.**
- **Source-level:** any change that moves ≥3 dimension scores, OR the course knowledge doc (`docs/google-5day-ai-agents-course-knowledge.md`) is updated with new mastery criteria → recompute the full 16-dimension aggregate and refresh the Master Scorecard row for Source #10.
