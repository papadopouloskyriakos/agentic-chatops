# Book Gap Analysis — Agentic Design Patterns vs ChatOps Implementation

**Date:** 2026-03-24
**Reference:** Antonio Gulli, "Agentic Design Patterns" (424 pages, 21 chapters, 7 appendices)
**Scope:** Techniques from the book not yet fully implemented in the ChatOps platform

---

## Current Scorecard (21/21 patterns at A or above)

| # | Pattern | Grade |
|---|---------|-------|
| 1 | Prompt Chaining | A |
| 2 | Routing | A- |
| 3 | Parallelization | A- |
| 4 | Reflection | A- |
| 5 | Tool Use | A |
| 6 | Planning | A- |
| 7 | Multi-Agent | A |
| 8 | Memory Management | A- |
| 9 | Learning & Adaptation | A |
| 10 | MCP | A |
| 11 | Goal Setting | A- |
| 12 | Exception Handling | A |
| 13 | Human-in-the-Loop | A |
| 14 | RAG | A- |
| 15 | A2A Communication | A |
| 16 | Resource Optimization | A |
| 17 | Reasoning Techniques | A |
| 18 | Guardrails | A |
| 19 | Evaluation & Monitoring | A |
| 20 | Prioritization | A- |
| 21 | Exploration & Discovery | A- |

---

## Remaining Gaps (Appendix A + Advanced Techniques)

### GAP A: Negative Few-Shot Examples in Build Prompt

**Book reference:** Appendix A — "Providing Negative Examples"
**What the book says:** Alongside positive examples ("here's a good response"), show the model what NOT to do. This helps clarify boundaries and prevent specific types of incorrect responses.

**Current state:** Build Prompt contains a single positive few-shot example (`fewShotInfra`) showing a good THOUGHT/ACTION/OBSERVATION response with [POLL] and CONFIDENCE. SOUL.md has a "WRONG responses" section for OpenClaw. But Claude Code's prompt has NO negative example.

**Recommendation:** Add a short negative example to `fewShotInfra`:
```
--- EXAMPLE OF A BAD INFRASTRUCTURE RESPONSE (DO NOT DO THIS) ---

I checked the host and everything looks fine. The alert might be a false positive.
I'll restart the container to fix it.

CONFIDENCE: 0.9 — Looks healthy.

--- WHY THIS IS BAD ---
- No THOUGHT/ACTION/OBSERVATION structure
- "Looks fine" without evidence
- Restarted without approval
- High confidence with no investigation
- No [POLL] for alternative approaches
```

**Effort:** Low | **Impact:** Low-Medium — prevents lazy/overconfident responses

---

### GAP B: Automated Prompt Engineering (APE)

**Book reference:** Appendix A — "Automatic Prompt Engineering (APE)" + DSPy framework
**What the book says:** Use a meta-model to generate candidate prompts, evaluate them against a goldset with an objective function, and select the best-performing variant automatically. DSPy treats prompts as "programmatic modules" that can be optimized like ML hyperparameters.

**Current state:** We have A/B testing infrastructure (react_v1 vs react_v2, prompt_variant tracking in session_log, Prometheus metrics per variant). But variant design is manual — a human decides what to test. There is no automated mutation, no goldset evaluation, no programmatic selection of the winning variant.

**Recommendation:**
1. Create a goldset of 10 representative alert scenarios with expected triage quality scores
2. Write a script that generates prompt mutations (e.g., vary ReAct structure, change few-shot example, adjust confidence instructions)
3. Run each mutation against the goldset (using Ollama on gpu01 for cheap evaluation, or batch Claude API calls)
4. Score outputs against expected results
5. Automatically select the best-performing variant and update Build Prompt

**Effort:** High | **Impact:** Medium — most valuable when the system processes 100+ sessions/month. Current volume (~80 sessions total) is too low for statistically meaningful optimization.

**Prerequisite:** Need sufficient session volume + quality score data before this is worth building.

---

### GAP C: Operator Context Injection (Persona Pattern)

**Book reference:** Appendix A — "Persona Pattern (User Persona)"
**What the book says:** While role prompting assigns a persona to the *model*, the Persona Pattern describes the *user/audience* to tailor responses in terms of language, complexity, and information density.

**Current state:** SOUL.md describes Operator well ("runs Example Corp, technically sophisticated, does not use cloud when he can avoid it"). But this context is ONLY available to OpenClaw (Tier 1). Claude Code (Tier 2) receives no operator profile — Build Prompt focuses on the issue, not the operator.

**Recommendation:** Add a short operator context block to Build Prompt for infra issues:
```
OPERATOR CONTEXT: Solo infrastructure operator managing 137 devices across 2 sites (NL + GR).
Prefers: minimal human interaction, direct answers, no handholding.
Technical level: Expert (BGP, Proxmox, K8s, Docker Swarm, self-hosted everything).
Constraints: Single person — no team to delegate to. Optimize for autonomous resolution.
```

**Effort:** Low | **Impact:** Low — Claude already behaves well via CLAUDE.md instructions, but explicit operator context could improve response calibration.

---

### GAP D: Factored Cognition / Task Decomposition for Claude Code

**Book reference:** Appendix A — "Factored Cognition / Decomposition"
**What the book says:** For very complex tasks, break the overall goal into smaller sub-tasks and prompt the model separately on each. Combine results for the final outcome.

**Current state:** Triage scripts (Tier 1) decompose well: Step 0→1→1.5→2→3→4. But Claude Code (Tier 2) receives one monolithic prompt and runs as a single session. For complex correlated bursts, this means Claude handles investigation, planning, approval waiting, execution, and verification all in one context window.

**Recommendation:** For correlated bursts or complex issues (predicted complexity = "complex"), decompose into sub-sessions:
1. **Investigation session**: read-only, produce diagnosis + plan
2. **Execution session**: after approval, execute only the approved plan
3. **Verification session**: confirm fix worked, close issues

This is architecturally possible (each sub-session via `claude -p`, chained by n8n) but adds significant workflow complexity.

**Effort:** High | **Impact:** Medium — current single-session approach works well for most issues. Decomposition would help for the rare 10+ turn sessions.

**Prerequisite:** Track which sessions exceed 10 turns or $3 cost. If >20% do, decomposition is worth building.

---

### GAP E: Metamorphic Self-Restructuring (Hypothesis 5)

**Book reference:** Introduction — "Hypothesis 5: The Goal-Driven, Metamorphic Multi-Agent System"
**What the book says:** The ultimate vision — agents that can autonomously modify their own topology. They can spawn new agents, remove underperforming ones, duplicate themselves, and rewrite their own instructions based on performance data.

**Current state:** The infrastructure partially supports this:
- `!mode` switches between 4 frontend/backend configurations
- OpenClaw has fallback models (GPT-4o → GPT-4o-mini → Haiku → devstral → qwen3)
- Lessons pipeline proposes SOUL.md patches
- A/B testing tracks which prompt variant performs better

But no agent can autonomously decide "I should use a different model" or "I should spawn a parallel Claude session for the K8s analysis while I investigate the network part."

**Status:** This is a research-level capability. The book describes it as a future hypothesis, not a current pattern. Not actionable for implementation.

---

## Priority Ranking

| Gap | Effort | Impact | Priority |
|-----|--------|--------|----------|
| A: Negative few-shot | Low | Low-Medium | **DONE** (2026-03-25) — added to Build Prompt |
| C: Operator context | Low | Low | **DONE** (2026-03-25) — injected into all prompts |
| B: Automated Prompt Engineering | High | Medium | P4 — wait for session volume to justify |
| D: Factored Cognition | High | Medium | P4 — partially addressed by plan mode for dev sessions (2026-03-25) |
| E: Metamorphic | Research | N/A | P5 — future vision, not actionable |

---

## What We're NOT Missing

The book's 21 core patterns are comprehensively covered. The Appendix A techniques that ARE implemented:

- Zero/One/Few-Shot Prompting: few-shot example in Build Prompt, zero-shot for dev issues
- System Prompting: SOUL.md (OpenClaw), CLAUDE.md (Claude Code), Build Prompt (gateway)
- Role Prompting: Both agents have explicit roles (Tier 1 triage, Tier 2 deep analysis)
- Context Engineering: Build Prompt dynamically assembles 7+ context layers (knowledge, lessons, budget, category, step-back, ReAct, cost prediction)
- Structured Output: TRIAGE_JSON, REVIEW_JSON, CONFIDENCE, [POLL], NL-A2A/v1 envelopes
- Chain of Thought: ReAct framework (THOUGHT/ACTION/OBSERVATION)
- Self-Consistency: Parse Response detects confidence/reasoning mismatches
- Step-Back Prompting: Auto-triggered for recurring alerts
- Tree of Thoughts: H1/H2 hypothesis exploration for correlated bursts
- ReAct: Mandatory for all infra issues, validated + retried
- RAG: Vector embeddings + keyword fallback, 3-tier injection
- Delimiters: Prompt sections clearly separated with headers and markers
- Iterative Refinement: Validation retry loop (2 attempts with escalating feedback)
