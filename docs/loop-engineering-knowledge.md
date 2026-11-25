# Loop Engineering — The Anthropic Playbook: Knowledge Report

**Source artifact:** `Loop-Engineering-IEEE.pdf` (11pp, conference-styled "2026 Working Note on Agentic Software Engineering Practice"). An **independent reformatting** of HuaShu's open *Orange Book* guide — *Loop Engineering: Stop Asking Me What It Is* (v260615, June 2026; huasheng.ai/orange-books). **Not** an official IEEE or Anthropic publication.

**Provenance of the ideas:** the term "loop engineering" surfaced independently in one week of June 2026 from **Addy Osmani** (named it + wrote it up), **Peter Steinberger** (author of OpenClaw — the ~8M-view post: "stop prompting coding agents, start designing the loops that prompt them"), and **Boris Cherny** (Claude Code lead — "my job is to write loops"). The generator/evaluator findings are credited to **Prithvi Rajasekaran** (Anthropic); the enterprise case to **Steve Kaliski** (Stripe's "Minions", 1,300 PRs/week).

---

## Executive Summary

Loop engineering is framed as a **fourth layer** above prompt → context → harness engineering. The earlier three layers teach the practitioner to do the work *better*; loop engineering **removes the practitioner from doing the work at all** — you design the system that prompts the agent and runs itself over and over. The central economic claim: **loops make generation nearly free, so judgment becomes the scarce resource** — and because a loop faithfully *multiplies* whatever its builder brings, the same loop built by two people yields opposite outcomes. The closing imperative: *"build the loop, but build it like someone who intends to stay the engineer."*

---

## 1. The Four-Layer Stack (Table I / Fig. 1)

| Layer | What it minds | Core question |
|---|---|---|
| Prompt eng. | one good prompt | what should I tell the model |
| Context eng. | what's in the window now | what to retrieve, summarize, clear |
| Harness eng. | arming a single run | which tools/actions, what counts as "done" |
| **Loop eng.** | scheduling on the harness | **how to make it run itself over and over** |

Each layer minds something larger than the one below; the loop sits "one floor above the harness." The harness arms *one* run; the loop automates the "waiting for you" away — runs on a timer, spawns sub-agents, and feeds its own output back as the next round's input.

**Key intuition — blast radius scales with layer height:** the cost of a mistake scales with the number of turns it survives before someone catches it. A prompt-layer misread is caught in one exchange; a loop-layer misread is written into the state file, read back the next morning as established fact, and built upon for many turns. *"A loop is, by construction, a machine for maximizing the number of turns."* Everything else in the playbook (evaluator, checkpoint, caps) exists to shorten the distance between a mistake and its discovery.

---

## 2. The Five Moves of One Turn (Table II / Fig. 2)

A single turn of a real loop performs five concrete moves; drop any one and the loop won't turn (or turns in place):

1. **Discovery** — find this turn's work on its own (read CI / issues / commits), via a *skill*, not a wall of cron instructions. Discovery sets the ceiling on the whole loop's quality.
2. **Handoff** — hand the task off to an isolated agent (its own git worktree), so parallel agents don't collide.
3. **Verification** — a *second* agent (different instructions/model) says "no". The agent that wrote the code grades its own homework too softly; a dedicated hole-picker is the "thing that can say no". **The hardest move.**
4. **Persistence** — write state *outside* the conversation (PR + ticket via connector + a state file). A loop's memory cannot live only in the context window.
5. **Scheduling** — a timer/trigger makes one turn into a loop. *"Automations are what make a loop an actual loop and not just one run you did once."*

---

## 3. The Six Parts a Loop Is Built From (Table III)

| Part | What it is | Realizes move |
|---|---|---|
| **Automations** | runs off a schedule/trigger | Scheduling |
| **Worktrees** | isolated dirs for parallel agents | Handoff |
| **Skills** | permanent project knowledge (`SKILL.md`); pays off *intent debt* | Discovery |
| **Connectors** | MCP hookup to external systems | Persistence / Discovery |
| **Sub-agents** | the generator separated from the judge | Verification |
| **Memory** | persistent state on disk | Persistence |

---

## 4. Generator & Evaluator — the crux (Section V, Fig. 3)

- **An agent always praises its own work.** Asked to grade what it just produced, it confidently rates mediocre output highly — not a smarts problem, a *grading-your-own-homework* problem; its context is stuffed with the self-persuasion that led to the output.
- **Tune a skeptic, don't fix a modest author** (Rajasekaran): making a standalone evaluator skeptical is *far more tractable* than making a generator self-critical. The fix is **structural, not wording** — swap in another agent with entirely different instructions that carries none of the self-persuasion. Borrowed from GANs.
- **The evaluator should ACT, not just read.** Reading judges "does this look right"; acting judges "does it *run* right." Hook the evaluator to Playwright MCP so it opens the page, clicks, screenshots, inspects the DOM. A common calibration: **assume the code is broken until proven otherwise — default to doubt, not trust.**
- **In a product:** Claude Code's `/goal` runs until a condition is met, with a **fresh small model** judging whether it holds (maker-checker principle — the entity reviewing a large transfer must differ from the one entering it). *"A loop's floor is its evaluator."*

---

## 5. The Five Ways a Loop Goes Wrong (Section VI, Fig. 4)

Each anti-pattern is exactly one move skipped:

| Anti-pattern | Move skipped | Symptom |
|---|---|---|
| **Nodding loop** | Verification | most common; self-approves plausible mistakes at machine speed; "has never said no across hundreds of turns" |
| **Amnesiac loop** | Persistence | rediscovers/redoes work; each morning starts from the same place |
| **Manual loop** | Scheduling | four good moves but a human runs it by hand and forgets |
| **Blind loop** | Discovery | human still decides each morning *what* to work on (the expensive part) |
| **Tangled loop** | Handoff | parallel agents edit the same dir; merge is unsalvageable |

Failures cluster: a loop missing verification tends to miss persistence too.

---

## 6. The Four Silent Costs + Three Disciplines (Sections VIII–XI, Fig. 6)

**Four costs** (they reinforce each other in a cycle):
1. **Verification debt** — merged-but-unverified output piling up between "runs" and "right".
2. **Comprehension rot** — the codebase grows via writing the human didn't read; the mental map stalls.
3. **Cognitive surrender** — the human stops having an opinion and just takes what's handed back ("no longer want to bother").
4. **Token blowout** — an idle bug spins all night, round after round, burning quota.

**Three operational disciplines** (the defenses):
- **Read a sample, always** — read a regular, genuinely-examined sample of the loop's output and force yourself to explain each change. An inability to explain = your map has fallen behind.
- **Cap before you ship** — set per-run budget, daily budget, max-retry *before* the first unattended run; caps are circuit breakers that convert open-ended risk into a bounded one.
- **Keep one door open** — build at least one checkpoint where the loop pauses for a human; the *existence* of the pause keeps the human in the position of being able to say "no".

---

## 7. The First-Loop Checklist (Table VI) — the benchmark rubric

The paper's own scorecard for "is this a real loop". The first two decide whether the loop can run; the last four decide whether it gets into trouble once it does:

| Element | Ask yourself |
|---|---|
| Discovery source | What does it read on a timer? (CI / issues / commits / inbox) |
| State file | Which disk file holds the cross-round memory? |
| Evaluator | Is there an independent check that can say "no"? |
| Isolation | Does each parallel agent get its own worktree? |
| Token cap | Did you set a spending ceiling? Who stops it if it runs off? |
| Human review | Which step pauses for you, rather than auto-ing all the way through? |

**Claude Code ↔ Codex capability mapping (Table V)** — loop engineering is a *set of capabilities, not a product*: Scheduling = `/loop` worker / Automations tab; Run-until-met = `/goal` / automation rerun+judge; Parallel isolation = `--worktree` / background worktree; Sub-agents = `.claude/agents/` / `.codex/agents/`; External conn = MCP; Explicit skill = `SKILL.md`; Machine-off run = Cloud Routines.

---

## 8. Benchmark dimensions (for the gap-analysis)

Derived from the five moves + generator/evaluator crux + the four cost-defenses:

- **D1 Discovery** — skill-based self-finding work (not a wall of cron instructions)
- **D2 Handoff** — git-worktree isolation for parallel agents
- **D3 Generator/Evaluator separation** — a *separate, skeptical* evaluator (different agent/model), not self-grading *(the move the paper says most systems fail)*
- **D4 Evaluator acts** — verification runs tests/drift-checks/canaries, doesn't just read
- **D5 Persistence** — on-disk memory surviving the context window
- **D6 Scheduling** — automations (local cron/`/loop` + cloud routines)
- **D7 Token-blowout defense** — hard caps/budgets/circuit-breakers before unattended runs
- **D8 Cognitive-surrender defense** — at least one human checkpoint ("keep one door open")
- **D9 Verification-debt defense** — an independent, recurring audit
- **D10 Comprehension-rot defense** — "read a sample, always" / prove-your-work discipline

Each graded A+ (5.0) / A (4.5) / A− (4.0) / B+ (3.5) / B (3.0) / B− (2.5) / C (≤2.0), mirroring the existing 9-source rubric in `docs/benchmark-standards-catalog.md`.

---

## 9. Notable Quotes

- *"What one writes is no longer the words for the agent, but a thing that automatically sends words to the agent."*
- *"The practitioner is no longer inside the loop, but outside it, building the loop."*
- *"A loop without a real check is just an agent nodding at itself."*
- *"Separate generation from judgment structurally, tune the evaluator into a skeptic, make it verify by acting, and hand the final say to a fresh model — those four steps are what it takes to grow a loop's ability to say 'no'."*
- *"The loop is a faithful multiplication sign, and what it multiplies is the person."*
- *"Build the loop, but build it like someone who intends to stay the engineer, not just the one who presses go."*
