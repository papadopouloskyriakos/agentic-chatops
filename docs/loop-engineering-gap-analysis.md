# Loop Engineering — Codebase Gap Analysis, Scorecard & Roadmap

**Benchmarked artifact:** `Loop-Engineering-IEEE.pdf` (HuaShu *Orange Book* reformatting, June 2026). Framework + rubric: [`docs/loop-engineering-knowledge.md`](loop-engineering-knowledge.md).
**Method:** four parallel evidence-gathering audits (one per move-cluster) → an adversarial "hole-picker" pass challenging the four A+ scores → live `crontab`/code verification of contested claims. Scores are **adversarially calibrated**, not self-assessed — fitting, since separating the generator from a skeptical evaluator is the paper's central thesis.

---

## 1. Executive Summary

**Aggregate: A− (4.00 / 5.0).** The claude-gateway is a genuine, mature loop-engineering system: it runs unattended, discovers its own work through named skills, persists memory across the context window, and — unusually — separates the generator from a *mechanical* evaluator (the infragraph verdict writer, where the LLM has no write path to the verdict columns). It **meets or exceeds** the paper on persistence, scheduling, evaluator-acts, and the human checkpoint.

The score sits deliberately **below** the existing 9-source aggregate (4.79) because this rubric probes the two things the gateway — by being so automation-strong — is most exposed on, and the adversarial + cron-verification passes caught real gaps:
- **Enforcement vs. existence.** Several "guards" are *advisory scripts that exist* rather than *gates that block*: the infragraph outcome-verdict does not demote `[AUTO-RESOLVE]`, and the documented "weekly audit invariant" (`audit-risk-decisions.sh`) is **not actually in crontab**.
- **Human discipline.** "Read a sample, always" and a hard token ceiling rely on operator discipline, not mechanism.

This is exactly the paper's thesis — *"a loop is a faithful multiplication sign… build it like someone who intends to stay the engineer."* The gateway's exposed flank is the **enforcement + human-in-the-loop layer**, not the automation.

---

## 2. Dimension-by-Dimension Scorecard

| Dim | Criterion | Score | Grade |
|---|---|---|---|
| D1 | Discovery — skill-based self-finding work | 4.5 | A | *(↑ from 4.0; self-initiated scan added 2026-06-24)* |
| D2 | Handoff — git-worktree isolation | 3.5 | B+ |
| D3 | **Generator/Evaluator separation** (the paper's crux) | 4.0 | A− |
| D4 | Evaluator *acts* (verify by doing) | 4.5 | A |
| D5 | Persistence — on-disk memory surviving context | 4.5 | A |
| D6 | Scheduling — automations (local + cloud) | 4.5 | A |
| D7 | Token-blowout defense — hard caps | 3.5 | B+ |
| D8 | Human checkpoint — "keep one door open" | 4.5 | A |
| D9 | Verification-debt defense — recurring audit | 3.5 | B+ |
| D10 | Comprehension-rot defense — "read a sample" | 3.5 | B+ |
| | **Aggregate** | **4.10** | **A−** | *(was 4.00 at benchmark; D1 closed 2026-06-24)* |

---

## 3. Per-Dimension Detail

### D1 — Discovery · 4.5 · A *(was 4.0; closed 2026-06-24)*
**Strength:** alerts/YouTrack auto-trigger **named skills** via `scripts/run-triage.sh` (a dispatcher that invokes `triage`/`k8s-triage`/`infra-triage`/`security-triage` by kind — not a wall of prompt pasted into cron), with `incident_knowledge` RAG injected at every tier. Skills are versioned permanent knowledge (`.claude/skills/*/SKILL.md`) — the paper's "intent debt" payoff.
**Gap that was closed (2026-06-24):** the adversarial pass + cron check found discovery was webhook-*reactive*, and the one self-initiated scan (`~/scripts/trigger-proactive-scan.sh`) was **dead** — it messaged `@openclaw`, dormant since the cc-cc migration, so the daily cron had been a silent no-op for ~2 months. **Fix:** `scripts/proactive-discovery-scan.py` + `.claude/skills/proactive-discovery/SKILL.md` — a cc-cc-native self-initiated scan that queries Thanos for **amber-zone** conditions (pending alerts, filesystems 80–93%, memory 10–18%, certs <21d) and surfaces NEW findings to `#infra-nl-prod` for **review** (never auto-acts — preserves D8/D10); deduped via a state file; cron re-pointed to it (03:06 UTC). Proven live: caught `notrf01dmz02` at 92.7% disk + 4 other real pre-alert conditions on first run. **Residual (why not 5.0):** it *surfaces* for review rather than auto-dispatching an investigation session — a deliberate human-discipline choice, not a defect.

### D2 — Handoff (worktree isolation) · 3.5 · B+
**Strength:** per-slot lock files (`gateway.lock.{dev,infra-nl,infra-gr}`, 10-min TTL) + n8n serialization prevent the "tangled loop" for the main triage flow; a `cleanup-daemon-worktrees.sh` cron confirms **worktrees *are* used by a background daemon**, and `--worktree`/`isolation:"worktree"` are available capabilities (used by interactive MR work). **Gap:** the *production* loop isolates by **lock + serialization, not git worktree**; concurrency is largely serial-per-slot, so the paper's specific per-parallel-agent-worktree mechanism is only partially wired.

### D3 — Generator/Evaluator separation · 4.0 · A− *(the crux; was preliminarily A+, lowered on adversarial review)*
**Strength (genuine, exceeds the paper conceptually):** the evaluator is *structurally* separate — `infragraph.action_verdict()` (`scripts/lib/infragraph.py:905-932`) is the **sole** writer of `match`/`partial`/`deviation` verdicts; the LLM session has **no write path** to the verdict columns (`scripts/infragraph-verify.py`). A `plan_hash`-keyed prediction is **committed before** any approval poll, and `Prepare Result` **default-DENIES** unpredicted `[POLL]`s (`RISK_FAIL_CLOSED=1` forces high on any error). The LLM-as-judge is a *different model* (gemma3:12b ≠ the opus generator). **Gap (adversarial catch — valid):** the **post-execution outcome verdict is advisory, not blocking** — no live-workflow gate demotes `[AUTO-RESOLVE]`→`[POLL]` when `verdict != match` (this is the intentional "annotate-not-gate" of IFRNLLEI01PRD-1145, and the −1040 fold-gate cannot graduate per [`infragraph_honest_gate_20260624`]). So: the *pre-execution* prediction gate is enforced fail-CLOSED; the *post-execution* verdict is not. Real separation, partial enforcement.

### D4 — Evaluator acts (verify by doing) · 4.5 · A
The evaluator **runs things**, not just reads: `scripts/validate-n8n-code-nodes.sh` executes `node --check` + `new Function()` parse + return-counting; `scripts/qa/run-qa-suite.sh` runs 44 suites with per-suite timeouts; `infragraph-verify` reads the **live** `triage.log` within the prediction window (not a stale snapshot); the synthetic-incident canary probes the real classify→predict spine nightly against an isolated DB. Short of A+ only because acting-on-the-artifact (the paper's Playwright-MCP ideal) is infra-side, not UI-side.

### D5 — Persistence · 4.5 · A *(adversarial critique was stale — corrected)*
Four persistence layers: SQLite (`schema_version`-stamped) `session_transcripts` + `incident_knowledge` + `agent_diary`; on-disk `active-alerts.json` dedup state; gzip session archives; YouTrack/Matrix as external state. The MemPalace Stop hook saves every 15 messages. **Critically, the operational write→retrieve→synthesize loop was CLOSED this session** (2026-06-24): the MemPalace hooks were fixed (MR !53) and `agent_diary` got a real writer (SubagentStop hook) + a RAG read signal (MR !54) — the skeptic's "agent_diary is inert seed / persistence without retrieval" critique predates these merges. **Residual gap:** `incident_knowledge.valid_until` is a live-only column, **absent from `schema.sql`/migrations** (schema drift) — fix into a migration.

### D6 — Scheduling · 4.5 · A
60+ crons re-run real loop turns (`gateway-watchdog` `*/5`, `wiki-compile`, `write-governance-metrics` `*/17`, `infragraph-eval --scorecard` daily, synthetic-canary `37 2`, chaos drills); n8n webhooks are the event-trigger layer; the `/schedule` cloud-routine capability is live (the 2026-07-01 fold-gate verification is a cloud one-shot). Covers the paper's local + cloud mix (Table IV).

### D7 — Token-blowout defense · 3.5 · B+
**Strength:** 4 named RAG circuit breakers (`scripts/lib/circuit_breaker.py`), `handoff_depth` hard ceilings (POLL at 5, HALT at 10), `SEARCH_BUDGET_S` per-search timeout, `llm_usage` post-hoc tracking. **Gap (paper prescribes per-run + daily + max-retry caps):** there is **no per-session token budget and no daily token ceiling** before unattended dispatch — caps exist on sub-components, not on total spend. An idle-loop "token blowout" is bounded by depth/breakers but not by a spend ceiling.

### D8 — Human checkpoint ("keep one door open") · 4.5 · A
The autonomy-forward 3-band gate (`scripts/classify-session-risk.py:142-322`): AUTO / AUTO_NOTICE (auto + SMS) / **POLL_PAUSE** (hard HITL floor for high/irreversible/deviation/jailbreak) + out-of-band SMS via the Twilio bridge + an instant `~/gateway.autonomy_forward` kill-switch sentinel. This is a textbook "keep one door open" — *more* sophisticated than the paper's single checkpoint. (Watch-item: the system trends toward *more* autonomy — auto-demote default-ON — so the door is deliberately narrow; it relies on the SMS path firing correctly.)

### D9 — Verification-debt defense · 3.5 · B+ *(skeptic's cron claim verified TRUE)*
**Strength:** the governance-metrics cron (`*/17`) + infragraph `--scorecard` (daily) + `--pending` (hourly) fire automatically and feed real invariant checks + the repeat-offender auto-demote. `holistic-agentic-health.sh` *does run* `audit-skill-versions.sh` (not merely check it exists). **Gap (confirmed by `crontab -l`):** the headline **"weekly audit invariant" (`audit-risk-decisions.sh`) is NOT scheduled**, and `holistic-agentic-health.sh` is **not in crontab** either — both are advisory/manual. A broken risk-classification would not be caught automatically until manual review. (Ironically, a small verification-debt of its own.)

### D10 — Comprehension-rot defense ("read a sample, always") · 3.5 · B+
**Strength:** the Proving-Your-Work directive is *mechanically enforced* — `check_evidence()` forces `[POLL]` (human review) when CONFIDENCE ≥ 0.8 is claimed without a visible-evidence code fence (`evidence_missing` signal); Matrix progress-polling streams tool activity live. **Gap:** no **mandatory** standing sampled-review loop ("pick N recent auto-resolves and explain each"); comprehension-rot defense rests on operator discipline — and the operator-stopped-voting history that *motivated* the autonomy-forward redesign shows that discipline is the real soft spot.

---

## 4. Strengths the System Already Exceeds the Paper On

- **Mechanical (not just LLM) evaluator.** The paper's strongest recommendation is a fresh *model* judging via `/goal`. The gateway goes further: a deterministic `action_verdict()` the LLM cannot author, plus commit-before-approve prediction gating — a maker-checker the model literally cannot tamper with.
- **Persistence depth.** Far beyond "write to a markdown file": embedded transcripts + per-agent diary + temporal incident knowledge, with a 6-signal RRF retrieval that now surfaces diary takeaways (wired this session).
- **The human checkpoint is risk-tiered.** Not one door — three bands with out-of-band SMS escalation, a feature the paper would hold up as best-practice.

---

## 5. Prioritized Roadmap

### Phase A — Convert advisory guards into enforcing gates (highest score-lift; closes the D3/D9 enforcement gaps)
1. **Schedule the weekly audit** — add `audit-risk-decisions.sh` (+ `holistic-agentic-health.sh`) to crontab with a Prometheus staleness alert. Closes the ironic "documented-but-unscheduled audit" gap (D9 → A).
2. **Decide the infragraph outcome-verdict's teeth** — either wire `verdict == deviation` to hard-demote `[AUTO-RESOLVE]`→`[POLL]` in the Runner, or document explicitly that it is annotate-only by design (it currently reads as enforcement in the docs but isn't) (D3 → A/A+).

### Phase B — Add the missing hard caps + human-sampling discipline
3. **Per-session + daily token ceiling** — a spend circuit-breaker that halts/pages before the cap, not just post-hoc `llm_usage` tracking (D7 → A).
4. **Mandatory sampled-review loop** — a weekly cron that picks N recent auto-resolves and DMs the operator to confirm/explain each; the *existence* of the ask defends comprehension rot (D10 → A).

### Phase C — Mechanism alignment (lower urgency)
5. **Fix the `incident_knowledge.valid_until` schema drift** into a migration (D5 → A+).
6. **Worktree isolation for the main loop** if/when parallelism grows beyond the 3 serial slots (D2 → A).
7. **Self-initiated discovery** — a scheduled "what's degrading that hasn't alerted yet" deep-dive skill, beyond webhook-reactive triage (D1 → A+).

---

## 6. Adversarial-Verification Note

Preliminary self-scores put four dimensions at A+ (5.0). An adversarial reviewer (defaulting to "too high until proven") + live `crontab`/code checks moved three of them down and corrected one stale critique:
- **D3 5.0 → 4.0** — outcome-verdict is advisory, not a live gate (valid catch).
- **D1 5.0 → 4.0** — discovery is webhook-reactive, not self-initiated (valid catch).
- **D9 5.0 → 3.5** — the headline weekly audit is not in crontab (verified TRUE).
- **D5 5.0 → 4.5** — the skeptic's "inert persistence" was *stale* (the agent_diary loop was merged today); held at A with the `valid_until` drift caveat.

The 1.0-point drop from the un-reviewed self-score is itself the most on-theme evidence in this report: **a generator grading its own loop praised it; a separate skeptic, acting on the code, found the nodding.**
