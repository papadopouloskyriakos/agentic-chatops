# Agentic Benchmark Synthesis — provenance-tagged to-A backlog (2026-06-26)

Cross-map of the two **separate, source-pure** scorecards (`docs/scorecard-anthropic-2026-06-26.md` = IFRNLLEI01PRD-1422, `docs/scorecard-openai-2026-06-26.md` = IFRNLLEI01PRD-1423). **Every item carries its provenance tag** — `[A·dimN]` = Anthropic dimension N, `[O·dimN]` = OpenAI dimension N, `[BOTH]` = independently flagged by both (= higher confidence). The merge is a labelled join, NOT a blend. Mission: lift every dimension to ≥A (autonomous run, full mandate).

## Scores at a glance

| | Anthropic (-1422) | OpenAI (-1423) |
|---|---|---|
| A | safety/guardrails | when-to-build, tool-design, instruction-quality, orchestration-pattern, iterative-deployment |
| B | pattern-fit, modular, observability, context-mgmt, eval-rigor, resource-econ, future-readiness | single-vs-multi, guardrails-layered, human-intervention |
| C | multi-agent-coordination | optimistic-execution+tripwires |
| D | model-selection | model-selection |

## Ranked to-A backlog (ROI = A-lift / effort)

| # | Item | Provenance | Lifts | Effort | Risk |
|---|---|---|---|---|---|
| 1 | **Model-routing fix** — `priorIncidents` counts pipes not rows → 0 sonnet/haiku across 738 sessions. Count incident ROWS, widen predicate, wire the resume (`Launch Claude Fresh`) path, add a never-downgrade-risky floor (HIGH/MIXED/irreversible → stay Opus), verify sonnet rows appear. | **[BOTH·dim2 D/D]** | 2×D→A; helps A·dim1, A·dim9, A·dim10, O·dim2 | low | med |
| 2 | **Sub-agent dispatch wiring** — delegation block injected to 0/331 dispatched sessions; sub-agents structurally unreachable in the dispatched runtime. Wire so the Haiku researchers actually run + emit `team_charter`/`handoff_log`. | [A·dim6 C] + [O·dim5 B] | C→A, B→A | med | med |
| 3 | **Guardrail layering on the autonomous path** — the rules blocklist (unified-guard) isn't wired to the `--dangerously-skip-permissions` dispatched path; no relevance/moderation/PII/output-validation classifier; the intermediate semantic rail is observe-only/dark. Wire blocklist + add PII + output-validation + activate the rail. | [O·dim7 B] | B→A (+ hardens A·dim8) | med | med |
| 4 | **Human-intervention: page/pause on failure-threshold** — only 1 of 2 OpenAI triggers reaches a human; failure-threshold (cost/tool-call/handoff-depth) annotates but never pages or pauses. Make it page (Twilio) + pause. | [O·dim8 B] | B→A | med | med |
| 5 | **Optimistic async tripwire** — no async guardrail watches the live trajectory and aborts on breach; the poller is read-only with no kill authority. Add a concurrent watcher that can halt a runaway/breaching session. | [O·dim9 C] | C→A | med | med |
| 6 | **Context-mgmt + token ceiling** — handoff-depth/cycle gate DARK (0/75, never bumped, no cron); no per-session/daily token ceiling; response cap scattered. Wire handoff-depth + a hard token ceiling. | [A·dim5 B] + [A·dim9 B resource] | 2×B→A | med | low |
| 7 | **Runner memory + cost gates** — Runner's own Opus sessions `MemoryMax=infinity`; the $25 cost gate let a $361/day spike run 14× over. Cap MemoryMax + enforce the cost gate. | [A·dim9 B] | B→A | low | low |
| 8 | **Observability: OTLP export + snapshot** — OTLP near-dead (15/39K spans), trace-metrics cron missing, per-session retrieval-context snapshot ephemeral. (otel table already revived in the dark-fix.) Fix the OTLP flush + wire the snapshot. | [A·dim4 B] | B→A | low | low |
| 9 | **Eval rigor: dead crons** — eval-flywheel script missing (dead cron), RAGAS exports -1 sentinels, redteam metrics all-zero, weekly jailbreak cron relative-path-fails, 0 prompt-trials ever promoted. | [A·dim7 B] | B→A | med | low |
| 10 | **Modular design: Skill drift** — master Skill is a frozen 13.5KB inline copy in the ~59KB Build Prompt, drifted ~691B from SKILL.md. Single-source + parity guard. | [A·dim3 B] | B→A | med | med |
| 11 | **Tool-design: agents-as-tools descriptions** — the registry regex parser truncates descriptions to a bare agent name; rich `.md` docs don't reach the orchestrating LLM. | [O·dim3 A-gap] | hardens A | low | low |
| 12 | **Future-readiness: un-pin dated models + parity guard** — ~5 scripts pin dated `claude-haiku-4-5-20251001`; provenance-drift guard advisory/uncronned. | [A·dim10 B] | B→A | low | low |

## Notes
- **`orchestrator_dependent` flags from the auditors are treated SKEPTICALLY** — most items (model-routing, dead crons, token ceiling, OTLP, model-pins) are concrete fixes needing NO orchestrator. The genuinely coordination/observability-adjacent ones (#2 sub-agent wiring, #5 tripwire, parts of #3) overlap -1421; per the operator's mandate ("build the minimal bricks now") I build the minimal version inline.
- **Order:** #1 first (both-books D, low effort, highest value), then the wiring/guardrail items (#2–5), then the dark-telemetry/dead-cron sweep (#6–9), then the hardening (#10–12). Each: behind a kill-switch where feasible, QA + audit-invariant after, committed to a clean branch off origin/main, documented.
- When all 20 dimensions are A (re-scored), move to the orchestrator epic **IFRNLLEI01PRD-1421** (which the research says = compose Healthchecks.io + Langfuse + build 3 thin bricks).
