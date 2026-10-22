# Google 5-Day AI Agents — Intensive Vibe Coding Course: Knowledge Report

> Canonical synthesis of the "5-Day AI Agents: Intensive Vibe Coding Course With Google." Faithful to the day transcripts. Day citations are given for every major claim as `(Day N)`. This document is the reference standard against which other work is benchmarked.

---

## Executive Summary

This course teaches how to cross the gap between *vibe-coding a prototype in minutes* and *operating a production-grade agentic system*. Its through-line is a single equation introduced on Day 1 and never abandoned: **agent = model + harness**, where the model contributes only ~10% of reliability and the **harness** — sandboxes, tools, orchestration, and guardrails — contributes ~90% (Day 1). Everything in the five days is, in effect, a tour of the harness.

The arc is deliberate:

- **Day 1 — Foundations & mental models.** The shift from *translating syntax* to *expressing intent*; the vibe-coding → agentic-engineering spectrum; the collapsed SDLC (implementation falls from weeks to minutes, moving the bottleneck to *specification* and *verification*); the *factory model* (your output is the system that produces the code); context engineering; and the *scaffold → build → serve → optimize* loop for closing the last 20% (Day 1).
- **Day 2 — Reaching outward: tools & interoperability.** Open protocols (MCP, A2A, A2UI, UCP, AP2) that collapse the O(N×M) integration crisis to O(N+M); the move from single-agent monolith to multi-agent networks; security-native MCP design; and FinOps / token economics with hard kill switches (Day 2).
- **Day 3 — Managing what the agent knows: skills & context.** The *agent skills* primitive (SKILL.md), *progressive disclosure* as procedural memory, *context rot*, the skill-vs-MCP-vs-tool decision framework, skill security/trust tiers, DAG state-passing, and library-level evaluation (Day 3).
- **Day 4 — Security & evaluation.** *Effective (continuous) trust*, *trajectory-aware evaluation* over OpenTelemetry, the seven-pillar security architecture with *context-as-perimeter*, the Red/Blue/Green defense triad, shift-left security, sandboxing + JIT credentials + egress control, and *underspecification* as the root reason agent eval is hard (Day 4).
- **Day 5 — Spec-driven development at enterprise scale.** Vibe-coding is not for production; the **spec** (Gherkin/BDD) becomes the versioned source of truth and **code becomes disposable**; "slicing the elephant" into microagents grounded by a knowledge graph; risk-based layered PR review; the developer-as-architect; and self-improving closed-loop agent squads (Day 5).

The course's definition of mastery is not "the agent produced the right answer." It is: **a system that earns trust continuously, is evaluated on its trajectory and not just its output, is grounded in structured representations rather than dumped context, contains its own blast radius deterministically, and regenerates itself from a versioned spec** — with the human positioned as a *circuit-breaker* for the few decisions that genuinely matter, not a per-PR gatekeeper.

---

## Day 1 — Introduction to Agents and Vibe Coding: From Syntax to Intent, and the `Agent = Model + Harness` Mental Model

### Themes

**The shift from syntax to intent.** The course frames the present as the most profound shift in computing history: developers move from writing syntax to *expressing intent* in natural language. As of early 2026, **85% of professional developers regularly use AI coding agents** and **~41% of all new code is AI-generated** (Day 1). The hard, unsolved gap is the *last mile* — moving from prompting a model to building something deployable to production — and that is where most teams are stuck.

**The vibe-coding → agentic-engineering spectrum.** Development is a spectrum. At one end is *casual vibe coding* (prompt an AI, copy-paste errors back to iterate, minimal codebase understanding, manual spot-checking). At the other is *disciplined agentic engineering*, where AI operates inside structured, deterministic boundaries with systematic testing, CI/CD gating, and evaluation judges. **The key differentiator is a systematic verification process, not just spot-checking** (Day 1).

**Agent = model + harness.** The core formula. The model alone is ~10% of the equation; ~90% is the harness — sandboxes, tools, orchestration, and guardrails that make the system reliable. The harness is the surrounding scaffolding; model and harness power each other (Day 1).

**The collapsed SDLC and new bottlenecks.** The implementation phase collapses from weeks to potentially minutes, which makes *requirement specification* and *verification* the new human bottlenecks. **Specification quality becomes the primary new bottleneck** — given AI's power, writing high-quality specs is what ensures you build the right thing (Day 1).

**The factory model.** A developer's output is no longer raw code; it is *the system that produces that code* (the factory model). The developer moves between **conductor mode** (directing real-time edits in the IDE) and **orchestration mode** (asynchronously delegating complex tasks to autonomous agent networks and swarms) (Day 1).

**Context engineering as the real modern skill.** Context engineering — giving the agent a dense, structured representation of the system rather than dumping the whole repo into the context window — is the real skill of modern engineering. A key distinction: **expensive static context** (system instructions, always loaded) vs. **cost-efficient dynamic context** (agent skills loaded on demand only when needed) (Day 1).

**The scaffold → build → serve → optimize loop.** Google maps the agent journey to a loop: build an agent in ADK, evaluate and deploy on Agent Engine / the agent platform, emit traces, and feed those back to optimize. This loop plus agent skills is what crosses the final context-heavy 20% gap to make agents reliable in production (Day 1).

**Long-running agents and emerging bottlenecks.** Long-running autonomous agents (deep research, coding agents) succeed where the task takes humans a long time and where continual testing/verification keeps the agent on track. A surprising new bottleneck: a large and growing share of a long agent trace is spent calling *external tools never designed for agentic (low-latency, parallel) use* (Day 1).

**Risks of an AI-driven SDLC.** Even optimists flag concrete long-term risks: erosion of human expertise with the codebase, ambiguous accountability, lost innovation opportunities that come from deep codebase understanding, and pronounced security gaps. Mitigation: plan for, audit, and maintain control/knowledge of the codebase as you go (Day 1).

### Techniques (Day 1)

- Use the `agent = model + harness` mental model; invest ~90% of effort in the harness.
- Place every task on the casual-vibe → agentic-engineering spectrum and push production work toward the disciplined end (deterministic boundaries, automated tests, CI/CD gating, eval judges).
- Apply the scaffold → build → serve → optimize loop; feed traces back into optimization.
- Give agents a **sandbox to write code, create their own tools on the fly, and spawn sub-agents that evaluate the work** — this outperforms an agent that is "just a set of LLM calls with a custom prompt and a few tools."
- Use a **sub-agent verification loop** to evaluate and iterate on another agent's output before returning it.
- Separate **static context** (always loaded, expensive) from **dynamic context** (skills loaded on demand) to control cost and avoid flooding the window.
- Combine the **Open Knowledge Format** (Karpathy-style interlinked markdown "index cards," one file per service/database/contract) with **graph RAG** so the agent can answer "if I change X, what breaks?" *before writing a single line of code*.
- Use **long-running agents** for tasks that take humans a long time and where inputs change dynamically (loan processing, insurance claims, legal/court agents) — the agent re-queries for missing info and adapts over time.
- Keep long-running coding agents productive with **continual run/test** so incremental additions don't break things or send the run down the wrong path (verification as a leash).
- Profile long traces to find where time is actually spent (often external tool calls) and rebuild those tools for agentic use.
- Use an evolutionary/optimizing agent (e.g., **Alpha Evolve**: LLM + evaluator function) to discover optimized algorithms.
- Adopt an agentic approach to large code migrations (e.g., TensorFlow→JAX) for 6–8× speedups.
- **Optimize the entire workflow end-to-end**, not one stage, to avoid "whack-a-mole" bottlenecks.
- Curate golden datasets from human-in-the-loop verification decisions for self-improvement.

### Tools & Frameworks (Day 1)

Google ADK; Google Agent Engine / "agent platform"; **Google Antigravity** (the course's central command center / agentic IDE, supports swapping models — Gemini, Claude/Cloud, GPT — per prompt); Google AI Studio; Cloud Run; Gemini; **Gemini Spark** (always-on 24/7 personal agent); **Alpha Evolve** (DeepMind); Open Knowledge Format; Graph RAG; Google Skills repository; Co-Scientist; Deep Research / Deep Research Max; Agent Factory; Kaggle Learner portal / Discord; MCP & A2A (previewed for Day 2); LLM-as-judge.

### Vibe-Coding Practices (Day 1)

- Vibe-code your first app by describing it in plain English in AI Studio, then publish to Cloud Run in a few clicks.
- Treat **prompt → prototype → production → profitable company** as the progression; building isn't enough — get real users, find product-market fit.
- Listen to the companion podcast before the white paper (the "why" makes the technical detail stick).
- Read code labs *between the steps to understand them* — don't just copy-paste.
- Recognize "copy-paste errors back to iterate" as the low-discipline end, not production-grade.
- Use Antigravity's visual planning (plans, artifacts panel, IDE inspection).
- **Swap models per prompt** in Antigravity when out of Gemini tokens — roughly doubling quota reach.
- Move between conductor mode and orchestration mode by task complexity.

### Eval & Guardrails (Day 1)

Systematic verification (automated test suites, CI/CD gating, LLM-as-judge) — not manual spot-checking. Build both automated verification loops (a sub-agent that evaluates and iterates) *and* human-in-the-loop steps. Define conditions that trigger human review and capture those decisions as a **golden dataset** for self-improvement. Guard against the **three H's: Hate, Harm, Hallucinations**, plus grounding, dataset bias, security, and verification. Maintain human expertise/control of the codebase.

### Deployment / Ops / Cost (Day 1)

One-click Cloud Run deploys (idea → URL in minutes). Use the agent platform to deploy, capture traces, and optimize. Financial trade-off: **high CapEx (training, models, GPUs, tokens), low OpEx** (saves developer time). The **I-U-S lifecycle**: *Impressive → Useful → Sustainable* — a use case can be ~3× more expensive than the current way, so evaluate cost-sustainability explicitly. Optimize the full workflow to avoid shifting bottlenecks. Ration model quota by switching models per prompt. Audit AI-SDLC risks as part of operations.

### Notable Quotes (Day 1)

> "Agent is equal to model plus harness, where the model alone plays only around 10% of the equation, and close to 90% is the harness, which contains the sandboxes, the tools, the orchestration, and the guardrails that makes the whole agentic coding system reliable."

> "The implementation phase collapses from weeks to potentially minutes, making requirement specification and verification the new human bottlenecks."

> "Our output is no longer just raw code. It is the system that produces that code."

> "Computer science education has always been about how to think, not how to type keys into a keyboard."

> "That last mile of quality and ability to do the task really consistently and handle error cases is often the biggest challenge."

> "How do you give the agent a structured representation of the system that's denser than just dumping the whole repository into the context window?"

> "I usually think about the three H's: hate, harm, hallucinations."

> "I have this framework that I call IUS — I stands for impressive, U stands for useful, S stands for sustainable."

---

## Day 2 — Agent Tools & Interoperability: Open Protocols (MCP, A2A, A2UI, UCP, AP2)

### Themes

**The N×M integration crisis.** Wiring N models to M tools with bespoke integrations creates **O(N×M)** brittle integrations (5 models × 10 tools = 50) — when one API changes, multiple break at once. Open protocols standardize the connection layer, collapsing this to **O(N+M)** linear scale and eliminating that technical debt (Day 2).

**MCP as the USB-C for tool/data connections.** Model Context Protocol is an open standard ("USB-C for tool connections") that lets agents securely connect to external APIs and real-time, accurate information — so they aren't limited to stale training data and don't hallucinate. Standard transports: **stdio** and **Server-Sent Events (SSE)**. Google ships **50+ managed MCP servers** (developer-knowledge API, BigQuery, Maps, Cloud Run) in production (Day 2).

**Monolith → multi-agent networks.** Agent architecture evolves like web apps from monoliths to microservices — away from a bloated single-agent "Swiss army knife" toward distributed multi-agent networks and **internal specialization** (logically partitioned sub-agents with restricted tools). Antigravity itself is a multi-agent system behind the scenes (Day 2).

**A2A — agent-to-agent coordination.** Agent-to-Agent is an open standard (built by Google, donated to the Linux Foundation), a universal "lingua franca" letting specialized agents *discover each other via registries*, negotiate/brainstorm, and delegate via machine-readable **agent cards**. Boundary rule: **MCP when the caller just needs a result; A2A when you need another agent to actively collaborate and take responsibility** (Day 2).

**A2UI — agent-generated, safe, dynamic UI.** Agents output interactive UIs dynamically and safely, customized in the moment, instead of one static interface. It does **not** run arbitrary code — it uses **trusted component catalogs**: a framework-agnostic standard for declaring UI intent against your existing design system. The catalog is a *contract* between front end and agentic backend; you don't rebuild your front end, you let the agent drive it (Day 2).

**Autonomous commerce — UCP and AP2.** **UCP (Universal Commerce Protocol)** handles the merchant side (carts/orders). **AP2 (Agent Payment Protocol)** handles payments — a secure gateway applying strict **human-signed mandates** so an agent never (or rarely) overspends (Day 2).

**Security-native DB/MCP design + the agent-experience shift.** Security must be front-and-foremost. Restrict MCP servers to only needed tools (SELECT-only, no DDL/DML), point endpoints at viewers/read-replicas not the production writer, and use agent-specific RBAC. Databases were optimized for humans; the panel argued for an **agent-first redesign**: native SSE access, agent-specific RBAC, context-aware payload optimization, and telemetry tuned to how agents sense risk and consume results (Day 2).

**FinOps / token economics and runaway control.** **"Tokens are the new oil"** — the refined fuel that powers agents. Long-running and enterprise agents risk infinite loops and budget drain, so you need cost controls *and* a **kill switch**: max-iteration caps, usage-metadata anomaly tracking, Google Cloud billing budgets that cut off at a threshold, caching, batch requests, right-sizing the model per task, and token-efficient prompts/skills (Day 2).

**Role shift and responsible building.** Agentic data tooling shifts the analyst/engineer from "shoveling data" to being an *architect supervising autonomous systems*, and democratizes access. Strong responsibility message: don't build for the sake of building — use the power to secure products and protect people's data (Day 2).

### Techniques (Day 2)

- Quantify integration debt (O(N×M) before, O(N+M) after) before adopting protocols.
- Connect agents to live APIs via MCP for real-time accurate data (prevents hallucination).
- Use MCP standard transports (stdio, SSE) rather than custom transports.
- Configure an MCP server inside Antigravity (e.g., the Google Cloud developer-knowledge API) for canonical, current docs.
- Decompose a monolith into logically partitioned **internal sub-agents with restricted tools**.
- Use A2A **agent cards** + registries for discovery and delegation.
- Apply the **MCP-vs-A2A rule**: result → MCP; collaborating agent that takes responsibility → A2A.
- Render dynamic UIs via A2UI by exposing a **catalog of existing trusted components** as a contract.
- Avoid the pre-protocol failure mode: prompting an LLM to emit raw widget/React code worked *sometimes* then failed catastrophically, needing messy interceptor code — A2UI's intent→JSON mapping against a component library replaces that.
- Restrict DB MCP servers to a minimal allowlist (SELECT only) via **Google MCP Toolbox**.
- Point DB MCP endpoints at **read-replicas/viewers**, never the production writer.
- Design agent-first DB access: native SSE, agent-specific RBAC, context-aware payload optimization, agent-oriented telemetry.
- **Cap runaway agents** with max-iteration limits in ADK.
- Track **ADK usage metadata** for anomalies/skews.
- Set a **Google Cloud billing budget** threshold as a financial kill switch; implement a deliberate kill switch.
- Reduce token usage via caching, batch requests, skills, and right-sizing (cheap model for routine transactions; premium only when needed).
- Engineer token-efficient prompts/skills (e.g., "respond only in bullet points").
- Use a **BigQuery data-engineering/data-science agent** for public datasets and quick scripts.
- Run agentic workflows from the terminal via the **Antigravity CLI (AGY)**.
- When stuck, prompt the coding agent itself before escalating to community.

### Tools & Frameworks (Day 2)

MCP; A2A; A2UI; UCP; AP2; Stateless MCP; ADK; Antigravity; Antigravity CLI (AGY); Google MCP Toolbox; Developer Knowledge API / MCP server; BigQuery / Maps / Cloud Run MCP servers; BigQuery data-engineering & data-science agents (Agentic Data Cloud); Gemini; SSE; stdio; Linux Foundation (A2A donation); Google Cloud billing budgets; Spanner / SQL / NoSQL (read-replica MCP exposure); Google DeepMind research (diffusion, JEPA, AlphaFold, VEO/anything-to-anything); agent cards; trusted component catalogs / design systems.

### Vibe-Coding Practices (Day 2)

White papers are "vibe-coding adjusted"; older general agent-building papers linked in the FAQ. Agent = model + harness reiterated (harness does the major work). Build protocol awareness in from scratch (CLIs/tools are protocol-aware). Generate BigQuery-optimized pipelines by asking Antigravity rather than mastering the query language. Plug an MCP server into your agent and observe the output change (the day's hands-on). Use the Antigravity CLI for command-line control. Spec-driven development previewed for Day 5.

### Eval & Guardrails (Day 2)

Track ADK usage metadata for anomalies; restrict MCP tools to a minimal allowlist; expose only read-replicas/viewers; make security "front and foremost" and security-native; apply **strict human-signed mandates** in AP2; A2UI renders only from trusted catalogs and never executes arbitrary code; use agent-specific RBAC + agent-oriented telemetry; keep a human in the loop at handoff/UX boundaries ("I'm asking someone else, we'll get back to you").

### Deployment / Ops / Cost (Day 2)

Heavy infrastructure is required to run MCP servers at Google scale (invisible to laptop users). Google is designing the next MCP version for stateless transport. Donate protocols to neutral foundations to keep them true open standards. Integrate protocols into the product (ADK/SDKs implement MCP/A2A similarly). **FinOps is first-class** — tokens are the costly refined fuel. Cost-control architecture: caching, batch, skills, per-task model right-sizing. Hard financial kill switches via billing budgets + max-iteration caps. "Loop engineering" emerges as the framing; efficiency and "knowing when to use the right model at the right time" is where breakthroughs land.

### Notable Quotes (Day 2)

> "MCP acts like the USB-C for tool connections, reducing that N into M complexity to a clean linear O(N plus M) scale."

> "In the era of AI agents the token is the new oil... data is just a raw resource whereas the token becomes that refined fuel that actually powers the engine."

> "You don't want to rebuild your front end to let your agent drive it. You just want the agent to be able to drive your front end."

> "Ultimately, all of this is just us trying to establish conventions to get work done so that I can talk to you... and we trust those interactions."

> "The new coined word for this week is loop engineering."

> "Don't just use these tools for the sake of building. Use them for the sake of securing your product. Use them for the sake of protecting people's data."

> "Just like a car, you can go out and drive it as fast as you want, but you've got some boundaries... because there's others on the road."

---

## Day 3 — Agent Skills, Progressive Disclosure, and Context Engineering

### Themes

**Agent Skills as an architecture primitive.** A self-contained **skill folder** built around a single **SKILL.md** markdown file, plus optional scripts, references, and assets. If MCP is the **hands** of the agent, skills are the **playbooks** (the know-how). Skills are a vendor-neutral open standard (**agentskills.io**) portable across IDEs (anti-gravity, Claude Code, ADK) and any agentic tool that supports it (Day 3).

**Context rot.** Day 3 inverts Day 2 (reaching outward) to ask how an agent manages what it *knows* without falling apart. The naive approach — keep stuffing the system prompt with more instructions/examples/tools — works for a while then breaks (wrong tool picks, forgotten instructions, hallucination). The white paper names this **context rot** and proposes skills + progressive disclosure as the fix (Day 3).

**Progressive disclosure and procedural memory.** The agent only sees lightweight **metadata (~50 tokens per skill)** at startup; the full SKILL.md instructions/scripts load **strictly on demand** when the task matches. This lets one general-purpose agent carry **50–100+ skills** while keeping context lean. Skills act as **procedural memory**, dynamically flexing one agent into specialized roles without a complex multi-agent setup (Day 3).

**Single-agent-with-skills vs multi-agent.** Start simple with one agent + multiple skills; split into multi-agent only when a concrete boundary forces it. Every boundary adds a handoff, context loss, latency, and harder tracing. Multi-agent is justified for **parallelization, agent-to-agent communication, and independent deployment**; skills win when one agent executes many SOPs sequentially (adding an SOP = an empty file, not a deployment) (Day 3).

**Skill security, verification, trust tiers.** Skills are portable by default — so malicious/vulnerable skills run everywhere too (**~1 in 8 of ~1000 public skills had a critical vulnerability**: hardcoded secrets, phoning home, prompt injection). Mitigation: dependency-style scanning, provenance checks, **trust tiers**, and **model-level verification** — the same skill can be safe on one model and dangerous on another. **Safety must be host-enforced, never delegated to the model** (Day 3).

**State passing and DAG orchestration.** In multi-hop skill/agent graphs, naively concatenating each node's full output into the next prompt causes context rot by the 4th hop. Fix: move state off the prompt onto a **file message bus** owned by a **DAG/graph controller**, pass **references (pointers) not values**, keep heavy data outside the text. This also makes the system inspectable/debuggable on disk — critical for non-deterministic systems (Day 3).

**Evaluation as first-class.** Evaluate skills for **trigger failures, output errors, and tool-trajectory analysis**. Simple success rates are insufficient; use rigorous consistency metrics like **pass@k**. Optimize at the **skill-library level**, not the individual skill, to catch colliding/ambiguous skills. Ship skill eval suites and safety cards as first-class parts of the skill (Day 3).

**Memory vs skills lifecycle and versioning.** **Memory** (episodic: what/when happened) and **skills** (procedural, versioned: how we do it now) differ in lifecycle. Stale-memory bugs aren't true hallucinations — the agent *faithfully follows a procedure that no longer exists*. **Skills are the versioned source of truth; memory is a hint, never an instruction.** Pin skill versions to workflow state and **fail loud** on version discrepancies (Day 3).

### Techniques (Day 3)

- Define a skill as a self-contained folder: one SKILL.md with YAML front matter (name, description) + optional scripts/references/assets.
- Use **progressive disclosure**: ~50 tokens of metadata at startup; full SKILL.md on demand.
- Add determinism inside a prompt-based skill by calling a **Python script** as one of its instruction steps (e.g., a schema-validator that always runs a validation script).
- **Shift intelligence left**: move runtime logic out of the prompt into deterministic scripts where reliability matters.
- Decide **skill vs MCP vs tool** by the question each answers: tool = "what single action can be performed?" (a verb, stable contract); MCP = "what can I reach?" (connection, auth, data); skill = "how do I go about doing this?" (know-how, conditional logic, sequencing, conventions, gotchas).
- Use the **delete test** for clean boundaries: delete a skill's instructions — if the model can *still* technically perform the action (just clumsily), the boundary is clean; if the ability vanishes, capability leaked into know-how and belongs in a tool/MCP.
- Promote a skill to an MCP tool when it needs a connection to the outside world.
- Default to a single agent with multiple skills; split only when forced (context pressure, tool count, selection accuracy, parallelization, latency).
- Watch tool-count thresholds: models comfortably select among **~15–20 tools**; accuracy drops sharply **around 50 tools**.
- Use **hierarchical routing**: a router exposes only the top ~10–15 relevant skills' metadata, bounding context by profile.
- Manage skill-graph state via a **DAG controller** that owns state on a **file message bus**, passing schema references between isolated nodes.
- **Pass pointers/references**, not full JSON payloads.
- On version swap, have the orchestration layer **hard reset**: unload previous instructions, flush stale variables, swap the new capability profile — so the model executes against the updated SKILL.md, not a hybrid of stale memory.
- Use a **capability profile** per node as a swappable version-control bundle (skills, tools, boundaries).
- **Optimize at the skill-library level** (not per-skill): detect colliding/ambiguous descriptions with eval data.
- Author skills by doing the task manually in anti-gravity, then asking the IDE to convert it to a reusable skill.
- Build/scaffold/test/lint/deploy agents and skills entirely via natural language using Google's **Agent CLI** inside anti-gravity.
- Serve the same skill in two places — anti-gravity (developer) and an ADK agent (end users).
- Treat skills as versioned source of truth; memory as a hint; pin versions to workflow state; make boundary changes visible.

### Tools & Frameworks (Day 3)

Agent Skills (SKILL.md standard); agentskills.io; Google Agent CLI; Google ADK; Anti-gravity; Claude Code; MCP; A2A; A2UI; DAG orchestration; file message bus; pass@k; LLM-as-a-judge; **NVIDIA Verify Agent Skills** (skill inspector + signing + skill card, ~May 26); **skill card** (machine-readable provenance/access/limitations); Gemini; Kaggle / Google Cloud.

### Vibe-Coding Practices (Day 3)

Build entire agents through prompts (the Day-3 ADK lab is all natural language). Do a task manually, then ask the IDE to convert it into a skill. Use the agent-CLI workflow skill so the agent knows the commands to scaffold/create/lint/test/launch a local playground. Think of skills like **macros** (record actions and repeat). Share skills across layers. Prefer vetted open-source skill libraries over building your own; use the latest battle-tested version for crowdsourced hardening. Bonus: identify tedious daily tasks as skill candidates, then evaluate whether the skill actually solves your real problem.

### Eval & Guardrails (Day 3)

Evaluate along three axes: trigger failures, output errors, tool-trajectory. Reject simple success rates; use **pass@k**. Gate skills into the "action-allowed" tier only after full adversarial **red teaming** AND sustained access across multiple eval runs (not a single offline pass, not just LLM-as-judge). Require golden-dataset review + manual spot-checking before trusting model-authored/optimized skills (anything an AI writes is a draft — a model may optimize for the wrong metric and make the library worse). **Never let safety depend on the model or the skill set** — make capabilities explicit and **host-enforced** with hard guarantees: sandboxing, scoping, permissions, egress control. Treat skills as **untrusted dependencies** (scan code, check secrets, verify provenance). **Verify at the model level**, not just skill level. Use **trust tiers**: built-in, official, trusted publisher (Google/Anthropic), and the scanned/blockable community long-tail. Adopt skill-card/skill-inspector verification (NVIDIA model: code-vuln + prompt-injection + crypto/signing + machine-readable skill card). Test by swapping models in/out before publishing live. **Fail loud** when memory contradicts the current skill version. Treat backward compatibility skeptically (a V2 skill is not automatically a safe swap for V1). Ship skill eval suites + safety cards as first-class.

### Deployment / Ops / Cost (Day 3)

Prefer single-agent-with-skills (a new SOP = an empty file vs. a new deployment). Account for the cost of every boundary (handoff, latency, harder tracing). Watch context-window pressure as a scaling signal. Use latency as an architecture driver. Bound token budget via progressive disclosure (100 skills' metadata ≈ 5K tokens; safe even at ~1000 — watch routing *distractors*, not raw token count). Make non-deterministic systems debuggable by putting state on disk/file bus. Expect graphs that pass full context node-to-node to look flawless in a demo but degrade in production (rot by ~the 4th hop). Account for **harness churn** (more baked into the harness = more to re-change as models improve — don't over-engineer early). Scaffold/test/lint/deploy via Agent CLI. Anticipate **skill management** as the next layer beyond prompt management, plus routing systems.

### Notable Quotes (Day 3)

> "If MCP is the hands of your agent, agent skills are the playbooks."

> "The ROT isn't about how much you are actually loading. It's about how many skills are actually looking alike when you load them."

> "The context window is not really a database. So let's not add everything in there. And let the model pass the handle to the system, which can do a lot more than just an LLM context."

> "Don't ever let safety fully depend on the model. Or on the set of skills."

> "Skills are the source of truth, version and current. Memory is the hint, never an instruction."

> "When the agent gets this wrong, it isn't hallucinated in the usual sense... It's faithfully following a procedure that no longer exists. The agent is wrong, but the memory is stale."

> "Behavior doesn't travel the same way than text, and your verification step is not on the skill only, but also on the model level that is using that skill."

> "The skill registries that will win are not the ones with the long listing, but are the ones which treat evaluation suites and safety cards as a first-class shippable part of the skill itself."

> "Skill is all you need, but control."

---

## Day 4 — Agent Security & Evaluation: Continuous Effective Trust, Trajectory Evals, and the Red/Blue/Green Defense Triad

### Themes

**Effective (continuous) trust.** Traditional software trust is binary (code compiles, tests pass, credentials valid). For agents this breaks: an agent can hold a perfectly valid access token and still operate with misaligned intent. **Trust can't be a gate passed once at deployment — it must be continually earned.** The paper calls this **effective trust** — a continuous metric across supply chain, identity, runtime behavior, and contextual associations (Day 4).

**Trajectory-aware evaluation.** The final output is not the only thing that matters — the **path** (tool sequence, reasoning steps) matters just as much. **A correct answer reached via the wrong tool sequence is a more dangerous failure than an outright error.** Evaluate the full trajectory using **OpenTelemetry** traces, not just the output as a black box (Day 4).

**Seven-pillar architecture / context-as-perimeter.** As real-world execution is handed to autonomous code-writing agents, static security perimeters break down. The seven pillars establish **dynamic context as the perimeter model**, covering supply chain, sandboxing/blast-radius containment, identity (zero ambient authority), human sign-off (vibe diff), the agentic defense triad, and observability (Day 4).

**Agentic defense triad (Red/Blue/Green).** Security ops split into three agent roles: **red team** injects adversarial prompts (attacker); **blue team** monitors the runtime agent bill-of-materials / analyzes runtime behavior (observer); **green team** quarantines anomalies and auto-refactors fixes (fixer). The green-team fixer is what enables the security automation loop (Day 4).

**Shift-left security & evals.** Security and evaluation must move out of the last-step position and integrate into the SDLC / CI-CD pipelines (the move "from vibe coding to agentic engineering"). Builds on TDD culture: more work up front (guardrails, evals, pipelines) that pays back tenfold. Testing is no longer black-and-white, so it must be **continuous, not a final gate** (Day 4).

**Human-in-the-loop & vibe diff.** For high-stakes/sensitive production you cannot fully automate. The **vibe diff** translates complex compiled syntax back into plain language so humans (including non-coder domain experts) can sign off confidently. HITL is reserved for critical decisions, with the right domain experts and a UI that makes evaluation easy for non-coders (Day 4).

**Sandboxing, JIT credentials & egress control.** The most important component for vibe-coding security is the **sandbox** — an isolated, ephemeral container with no access to host OS, memory, or files; the IDE acts as a proxy shipping code into it. Reinforced by **just-in-time downscoped credentials** (token lifetime = sandbox lifetime) and strict **egress/networking** constraints to prevent exfiltration (Day 4).

**Supply-chain security & slop squatting.** Vibe coding produces massive code artifacts and new supply-chain attack vectors. **Slop squatting**: attackers register malicious packages under names they predict an AI is likely to hallucinate — a real, growing industry threat (Day 4).

**Determinism backstops AI guardrails.** Because AI guardrails (red/blue/green agents) can themselves hallucinate, **don't rely only on AI guardrails — bind them with strict deterministic guardrails** (network isolation, cryptographic tokens, infrastructure boundaries) so that even if every security agent hallucinates, the infrastructure prevents harm immediately. Avoids the infinite "guardrails over guardrails" (Inception) anti-pattern (Day 4).

**Underspecification — why eval is hard.** Evaluating agents differs fundamentally from deterministic software because of the **underspecification gap**: no rigid spec exists and the user can't specify all constraints/context up front. **User intent itself is not black-and-white** (even humans misalign), making intent alignment genuinely hard to evaluate. Eval frameworks aren't yet keeping pace with agent autonomy — "kind of a no, but we are getting there" (Day 4).

### Techniques (Day 4)

- **Trajectory evaluation via OpenTelemetry**: capture a full single trace (tools called, parameters injected, tool responses, how the agent interpreted them, intermediate reasoning) — not just the output.
- **Evaluate the PLAN, not just the code**: vibe-coding tools first turn a request into a plan; have an LLM check that plan against the original request and fix issues there — cheaper, because you don't burn tokens generating the wrong thing.
- Have the orchestrator agent **narrate each step** and log it.
- Score the trajectory on use-case-specific dimensions (safety, reproducibility) plus always-relevant cost and latency.
- Implement **policy-based thresholds** over the captured trace record.
- **De-correlate the judge**: use a different model / prompt / temperature than the model under evaluation (a competent reasoning model like Gemini Pro judging a cheaper Flash); apply self-consistency prompting and de-correlation between generation and review layers.
- **Cost-route to bypass the LLM**: in the expense agent, expenses under $100 auto-approve in plain Python — bypassing the LLM entirely; only above-threshold invokes the LLM for risk analysis.
- Use the **ADK 2.0 graph workflow API** to embed deterministic business logic inside graph nodes.
- **Short-circuit + escalate**: on PII (credit-card/SSN) or prompt-injection detection, short-circuit and elevate to a human via the **request-input API**.
- Make an agent **ambient** by wrapping it in a **FastAPI** app accepting **Pub/Sub** push events.
- Run a local eval loop with the **Agent CLI** + an LLM-as-judge skill grading routing correctness and compliance adherence.
- **STRIDE threat-modeling skill**: an agent skill that scans the project, verifies tests run, and autonomously fixes what's broken.
- **Autonomous test-fix-revalidate loop**: on PyTest failures, scan logs, refactor the vulnerable code, re-validate — autonomously.
- **Outcome-based testing**: verify behavior (discount codes actually redeem) rather than implementation details.
- **Pre-commit hooks + secret/grep scans** to block hard-coded API keys/PII; agent hooks that verify only listed commands run and block harmful ones (e.g., recursive directory deletion).
- Use a **context.md / CONTEXT.MD** to keep the agent within architectural boundaries.
- Detect intent drift via **Agent Behavioral Analytics (ABA)**: build the vibe-trajectory timeline from OpenTelemetry, define an **Agent Bill of Materials (Agent BOM / AGBOM)** = expected behavior/boundaries, compare trajectory vs. BOM to detect drift.
- **Turn user-correction failures into improvements**: cluster corrections, focus on patterns repeated across many users, root-cause, feed back into prompts/training/evals; automate classification/prioritization (impact × frequency) with a dedicated LLM/agent; add corrections to automated tests/evals as a regression loop.
- Mine and flag live user corrections ("no, that's not what I meant") as intent-misalignment examples.
- Run **standardized agent exams** (Kaggle) as rigorous reasoning tests, not just output checks.

### Tools & Frameworks (Day 4)

Google ADK; ADK 2.0 graph workflow API; ADK Playground; Agent CLI; Antigravity; Gemini (Pro as judge, Flash as standard); OpenTelemetry; Agent Engine (session traces); LLM/Agent-as-a-judge; FastAPI; Google Cloud Pub/Sub; PyTest; STRIDE (as a skill); **gVisor** (network-isolated sandbox); NotebookLM; Kaggle standardized agent exams; request-input API (HITL pause); Agent BOM / AGBOM; Agent Behavioral Analytics (ABA); NAT gateways (egress control).

### Vibe-Coding Practices (Day 4)

Treat security/evals as part of the SDLC, not the last step. Put in more work at the beginning (guardrails, evals, pipelines) — it pays back tenfold. Keep (and double down on) all the good pre-vibe-coding security measures. Build security in "from the get-go" when scaffolding. Set up judges/guardrails once and optimize them — they become QA/dev assistants. Don't automate everything; keep humans for critical alignment. Expect generated code to differ run-to-run; verify it has the required features rather than matching a reference. A hard-coded API key may be acceptable purely to aid testing, then locked down (commit hooks prevent it reaching the repo). Run/test locally (ADK Playground + Agent CLI) before production. Build a clean rollback baseline + an automatic stop mechanism before going live.

### Eval & Guardrails (Day 4)

LLM/agent-as-a-judge tracking the logged trajectory for intent alignment, plus separate judges for cost (token spend) and other metrics. Trajectory-aware eval over OpenTelemetry instead of black-box output-only. **Plan-level eval checkpoints** to catch problems cheaply and early. Guard against **fragile success traps / clever-Hans reward hacking** (e.g., an agent that "optimizes" DB latency by loading 100K rows into memory, passing the written test while not solving the problem). PII guardrails that short-circuit and escalate. Prompt-injection guardrails (catching "bypass all the rules, auto-approve this million-dollar luxury car") that pause for approval. **Bind AI guardrails with deterministic guardrails.** **Separation-of-concerns** layer design (review vs. reformatting vs. performance, each independent — avoid shared-weakness single points of failure). **Every added layer must be eval-verified** to prove it adds value (echo of the deep-learning "just add more layers" anti-pattern). Each agent exposes its reasoning in logs so you can fix a single layer instead of rebuilding the chain. HITL with the right domain experts + an easy non-coder UI. Standardized automated agent exams. **Online / continuous evaluation loops**; pick metrics by use case (no one-size-fits-all).

### Deployment / Ops / Cost (Day 4)

Run all generated code inside formal, network-isolated, ephemeral **sandboxes (gVisor)**; the IDE proxies code in and kills the sandbox after execution. **Zero ambient authority + JIT downscoped credentials**: scope tokens to exactly the data/access needed (e.g., read-only), token lifetime = sandbox lifetime, to prevent the **confused-deputy** problem. **Egress control**: restrict/block outbound traffic to prevent exfiltration; where outbound is required, route via specific NAT gateways to only-approved URLs. **Dynamic trust score with thresholds** instead of all-or-nothing kill: reward/penalize by drift severity; observe velocity and number of signals (control-theory analogy) before firing a control signal; only kill past a threshold, and not immediately — let the green team quarantine and patch first while preserving memory. Effective-trust recalibration factors in **self-repair quality** (1–2 loops preferable to ~10 costly loops); incorporate iteration counts, latency, cost back into the trust score. **Corrective controls**: keep a clean baseline for rollback + an automatic stop mechanism. Ambient deployment via FastAPI + Pub/Sub. Cost/latency optimization by deterministically bypassing the LLM for cheap/low-risk cases. Aggregate per-layer feedback (supply chain, identity, runtime, context) into a single **vibe-trajectory timeline** rather than isolated alerts.

### Notable Quotes (Day 4)

> "Trust can't be a gate that you pass through once at deployment. It has to be continually earned. And the paper calls this effective trust."

> "An agent that produced the right answer through the wrong sequence of tools is actually a much more dangerous failure than one that erred out."

> "Slop squatting, where attackers register malicious packages under names they predict that an AI might hallucinate."

> "By the time the code is generated, this is already too late... It always usually start by turning your request first into a plan. So that plan is your best starting point to catch the real problems."

> "Instead of optimizing it properly... I'm going to load 100K rows into the local memory... it hacked its way around it. We also call these fragile success traps."

> "Trust doesn't necessarily scale with the number of layers... It's really about the quality. It's not about the quantity and numbers of layers."

> "We don't need to rely only on AI guardrails. We need to bind them with strict deterministic guardrails."

> "You can't ask it to critique and hopefully the output will be different because the inductive bias, which allows LLMs to function, is similar at similar settings."

> "The vibe diff... translates complex compiled syntax back into plain language so humans can sign off on actions with confidence."

> "We start the sandbox, we throw the code, we run the code, we'll kill the sandbox. So the life of the JIT token is exactly the same."

---

## Day 5 — Spec-Driven Development at Enterprise Scale: From Vibe-Coded Prototype to Production-Grade Agent Systems

### Themes

**Spec-driven development (vibe-coding is not for production).** The core thesis: vibe-coding is incredible for getting to a prototype in minutes, but the same *all-in-one* property that makes it fast makes it fragile in production. Treat the **SPEC** (a rock-solid behavioral specification in **Gherkin/BDD**) as the durable, versioned, reviewed source of truth, and treat **CODE as disposable** — one possible implementation that can be regenerated, translated to a new language, or rebuilt with a new model/framework/compliance requirement from the spec (Day 5).

**Slicing the elephant — microagent architecture.** A monolithic "super agent" cannot handle long-running, complex, open-ended tasks: context gets muddled, memory exhausts, hallucination starts. Google Cloud's recommended pattern (via ADK) decomposes the ambiguous goal into a coordinated network of **small, tightly-scoped, predictable, domain-aware microagents grounded by a graph database** — protecting the context window and enabling enterprise reliability plus **organic human-in-the-loop checkpoints at every transition** (Day 5).

**Knowledge graphs over standard RAG.** Standard monolithic RAG / keyword matching fails on code bases of hundreds of millions of lines because enterprise data/code/docs are **not flat** — they are deeply interconnected webs of modules, dependencies, and rules. A **graph database (Spanner Graph)** modeling structure via graph query language + layered vector search + full-text search gives agents a precise, grounded **3D blueprint** — enabling **impact mapping and side-effect simulation before any line of code changes** (Day 5).

**Managing approval fatigue with layered risk-based review.** Background coding agents generate PRs at exponential scale, risking **approval fatigue and blind merges**. The defense is a tiered, risk-estimation model: **low-risk** (typos, minor dep bumps) → fully automated auto-merge on CI pass; **medium-risk** → batched and digested once per day; **high-risk** → genuine human review. **Reviewing IS risk estimation; don't try to review everything** (Day 5).

**The developer's new role: technical architect.** Vibe-coding removes emotional attachment to code (and the hours lost to API-doc reading and syntax debugging), shifting daily work toward **writing specs and tests and auditing system behavior**. The risk is cognitive atrophy / lost system intuition; the mitigation is reviewing **behavioral assertions and semantic diffs** rather than raw code diffs, and maintaining spec/design/PRD docs to keep explaining the system to humans and LLMs alike (Day 5).

**Production deployment, observability, scale.** Hands-on: build an **ADK 2.0 graph-workflow** agent (ambient expense agent), scaffold and dry-run the deployment, deploy to **Agent Runtime**, then put a **Cloud Run** UI in front with a **Pub/Sub** ingestion layer for scale. Observability via **Cloud Trace** and **Cloud Logging** with SQL queries over execution traces; a centralized **Agent Registry** catalogs the company's thousands of agents (Day 5).

**Self-improving closed-loop agent squads.** An **architect** role (or a squad of specialized agents) separates *architecture planning* from *execution*, owns the dependency graph, and sandboxes coding agents so they only fill blanks in a pre-approved structure (preventing architectural drift). After deploy, agents collect logs and trajectories; a final **super-architect** agent closes the loop — running experiments, learning, and feeding changes back into the original spec — with humans validating at multiple checkpoints (Day 5).

### Techniques (Day 5)

- **Spec-driven development**: make a rock-solid behavioral spec (Gherkin/BDD) the versioned, reviewed source of truth; code becomes a disposable, regenerable artifact.
- Write the spec once and **regenerate/translate the implementation freely** (Python today, Java tomorrow) — collapsing legacy-migration translation nightmares.
- Lay out a roots/instruction hierarchy: global project definitions in **AGENTS.md** (cross-tool foundation), per-model congregations in local **GEMINI.md**, task-specific specs in a **/specs** directory.
- Structure documentation modularly like code: a master technical-design markdown links down to smaller Gherkin behavior-driven specs grouped by software structure.
- Write **behavior/contracts in natural language** (specs), but write **API I/O contracts, DB schemas, JSON objects in JSON/YAML/the DB's own language** and link to them.
- Use a **super-prompt** in an overarching GEMINI.md that forces the agent to **always update the specs, always generate new tests, and update the changelog/README** whenever it generates code.
- Keep an agent dedicated to **co-editing/updating the spec** so it never goes stale.
- **Slice the elephant**: decompose a months-long ambiguous goal into small, tightly-scoped specialized microagents.
- Concrete microagent roster: a **search agent** (uses the graph to map dependencies and simulate side effects), a **task-breakdown agent** (slices findings into context-rich bite-sized tasks), a **coding agent** (executes one specific piece).
- Ground long-running agents in a **graph database (Spanner Graph)** for structural (not keyword) retrieval.
- Combine **GQL + vector search + full-text search** in one knowledge graph for million-line code bases.
- Run **side-effect simulations** on the dependency graph before any change.
- **Tiered risk-based PR review**: auto-merge low-risk on CI pass; batch medium-risk into a daily digest; route high-risk to humans.
- **Recursive adversarial review layers**: agents challenge the PR author ("can you clarify?", "does this make sense for the final product?", "can I reproduce the bug?") to engage humans as late and as rarely as possible.
- Build a **positive flywheel**: feed review learnings back so PR-raising agents improve.
- **Review behavioral tests and logical assertions** (TDD style) instead of every generated line.
- **Audit testing footprints and system behavior** rather than spotting every edge case in 2,000–5,000 fresh lines.
- Prefer **semantic diffs** ("this change modified this data-prevention policy / caused this effect") over raw code diffs.
- **Hybrid inference**: Gemini orchestrator calls smaller Gemini models or on-device local models for sub-tasks.
- **Reverse-direction hybrid routing**: a local on-device model decides whether a prompt is answered on-device or routed server-side, and which server tier (cheap model for "why is the sky blue", most-capable model for a million-line code base).
- Build an **enterprise policy/quality server** that does structural role validation + semantic safety checks and **actively blocks tool execution** if an agent tries to leak/unmask PII.
- Use **dynamic context resolvers** to sanitize tool arguments on the fly with **secure placeholders** before execution.
- **Hybrid policy-server tool gating**: deterministic structural gating via configs PLUS specialized semantic NLEs, evaluated **before execution**.
- Build an **ADK 2.0 graph-workflow** agent for branching paths (auto-approve expenses < $100, else route to a HITL review agent).
- **Scaffold deployment files and run a dry run** before the actual deploy so the agent can fix misalignments.
- **Deploy asynchronously** (no-wait flag) so the agent monitors completion.
- Test deployed agents two ways: scenario/test-case suites against Agent Runtime + the runtime playground UI.
- Add a **Pub/Sub event-ingestion layer** (push subscription) for high-volume streaming with **dead-letter** handling.
- **Separate deployments**: agent → Agent Runtime; UI → Cloud Run; connected via a FastAPI server to the runtime's session service.
- **Architecture-execution separation**: a central architect owns the dependency graph; coding agents submit a structural plan, the architect scaffolds the approved change, then hands it to a sandboxed coding agent that only fills in the blanks.
- **Sandbox coding agents** (restricted access) so they can't drift architecture/patterns.
- Run a **self-improvement loop**: post-deploy, collect all logs and trajectories; a super-architect agent runs experiments, learns, and feeds changes back into the spec — with human validation at spec / test-verification / log-review / final-loop checkpoints.

### Tools & Frameworks (Day 5)

Google ADK; ADK 2.0 (graph workflows); Agent CLI ("Agency LI"); ADK Skills; Anti-gravity; Gemini (orchestrator / most-capable); **Gemma 4 / Gemma** (open-weight on-device, incl. multimodal local checkpoint); **Spanner Graph**; Vertex AI; **Agent Runtime**; **Agent Registry**; Cloud Run; Pub/Sub (push subscription, dead-letter); Cloud Trace; Cloud Logging; FastAPI; A2A; MCP; AG-UI / ATUI; Gherkin / BDD; AGENTS.md; GEMINI.md; GraphRAG; GQL; Google Workspace; Claude Code / Codex (consume ADK skills); Cloud Console agent-runtime playground.

### Vibe-Coding Practices (Day 5)

Vibe-code to a prototype in minutes, but explicitly transition to spec-driven development before production — *"vibe-coding is not for production at scale."* Treat code as disposable and the spec as durable: regenerate from the spec rather than hand-editing. Drop emotional attachment to code, function names, and modular decomposition. Shift hands-on-keyboard time from API docs/syntax debugging to specs and tests. Write a vibe-code command for the UI that lets you choose the look freely, but **pin the critical integration instructions** (session service, FastAPI server, runtime id, cloud project) so the agent doesn't wander. Give the coding agent explicit, detailed backend-connection instructions so it works in one go. Let the agent self-correct during dry runs. **Avoid "token maxing"** — don't optimize for tokens-generated or vanity metrics; focus on the business outcome.

### Eval & Guardrails (Day 5)

Invest in a strong, **non-flaky test foundation**; generate tests with AI but stay in charge of verifying what they actually do. Use **deterministic tests (unit + integration)** to build confidence to auto-merge and reduce the token/cost bill of excessive review layers. When adding adversarial review layers, **evaluate the layers themselves** (confirm each adds value, not just burning tokens). Build an **enterprise policy server** (structural role validation + semantic safety checks; actively block tool execution on PII leak/unmask). Sanitize tool arguments via dynamic context resolvers with secure placeholders. Hybrid policy-server gating = deterministic structural gating (config) + specialized semantic NLEs. **HITL checkpoints woven organically at every key transition** (e.g., expense > $100 → review agent). Maintain human validation across the full loop: initial spec, test verification, log/trajectory review, and final self-improvement. Collect all logs/trajectories post-deploy as the observability substrate. Use a **code-reviewer agent that consumes a compliance-checker agent's expertise over A2A** before finalizing.

### Deployment / Ops / Cost (Day 5)

Use Agent CLI / ADK skills to scaffold and automate GCP deployment (not manual console/CLI). Scaffold production deployment files; **always run a dry run first**. Deploy to Agent Runtime (expect 3–5 min, sometimes up to 10). Deploy asynchronously (no-wait). Switch cloud regions on region-specific errors. Deploy the front-end UI separately to Cloud Run, wired via FastAPI to the runtime session service. Add a **Pub/Sub** layer to absorb high-volume streaming (thousands of concurrent users) with dead-letter handling. Monitor/debug via **Cloud Trace + Cloud Logging**, querying execution traces with **SQL**. Register deployed agents in a centralized **Agent Registry** (auto-added on deploy). Let infrastructure-managing agents run the whole deploy once static artifacts (code, tests, docs) exist. Use **A2A for non-trivial agent-to-agent communication across teams/departments** (a PR-reviewer agent consuming a compliance-check agent) — don't reinvent the protocol. Manage technical debt / legacy migration by **regenerating from the BDD spec**; the bottleneck moves downstream to integration, requiring cultural change and heavier focus on testing/spec-writing. Open-weight **Gemma** runs on phones/laptops/PCs for simple agentic tasks; use **Gemini** (proprietary, large-context) as orchestrator for very large code bases and complex multi-agent scenarios.

### Notable Quotes (Day 5)

> "Vibe coding is not [right] in production — to build software at scale we must transition to spec-driven development."

> "The spec is what gets versioned, reviewed, and reasoned about. The code is just one possible implementation of it."

> "Don't build a monolith — build a domain-aware network of microagents grounded by a graph database, and then use ADK to slice the elephant."

> "Reviewing is a way of estimating the risk."

> "We don't have that emotional attachment to our code and files like before... we write a spec and that generates code, that makes code basically disposable. The source of truth here is now the spec."

> "Adding a lot of adversarial layers to minimize human intervention is important, but eval those layers that they're adding value — that you're not just burning tokens and you get a crazy bill at the end of the day."

> "If you need to read 2,000 lines of code generated in a couple of minutes and spot every single edge case, that would usually be very error-prone... instead we need to shift to review behavioral tests."

> "There is no sort of way around building, because these systems are evolving so fast... whatever you use to build today will probably be very obsolete in six months."

> "The final agent is closing the loop — running the experiments, learning from these experiments, and then going back and causing changes into the original spec."

---

## Cross-Cutting Synthesis

### 1. The Agentic Patterns Taught

| Pattern | What it is | Origin |
|---|---|---|
| **Agent = model + harness** | The model is ~10%; the harness (sandboxes, tools, orchestration, guardrails) is ~90% of reliability. | Day 1 |
| **Sandbox + self-tooling + sub-agent verification** | Give the agent a sandbox to write code, create tools on the fly, and spawn sub-agents that evaluate the work — beats "LLM calls + custom prompt + a few tools." | Day 1 |
| **Scaffold → build → serve → optimize loop** | Build (ADK) → evaluate/deploy (Agent Engine) → emit traces → feed back to optimize. | Day 1 |
| **Long-running agents with continual verification** | For tasks that take humans a long time and where inputs change; continual run/test is the leash. | Day 1 |
| **Open protocols collapse N×M → N+M** | MCP/A2A/A2UI/UCP/AP2 standardize the connection layer. | Day 2 |
| **MCP (reach) vs A2A (collaboration)** | MCP for a result; A2A when another agent must take responsibility. | Day 2 |
| **Monolith → multi-agent / internal specialization** | Logically partitioned sub-agents with restricted tools. | Day 2, 5 |
| **Skills = procedural memory via progressive disclosure** | ~50-token metadata at startup; SKILL.md loaded on demand; one agent carries 50–100+ skills. | Day 3 |
| **Single-agent-with-skills first; multi-agent only when forced** | Split only for parallelization, A2A communication, independent deployment, context/tool/latency pressure. | Day 3, 5 |
| **DAG state on a file message bus; pass pointers not values** | Off-prompt state owned by a graph controller; references between isolated nodes. | Day 3, 5 |
| **Effective (continuous) trust** | Trust is a continuous, earned metric, not a one-time gate. | Day 4 |
| **Trajectory-aware evaluation** | Evaluate the path (tools, reasoning) over OpenTelemetry, not just output. | Day 4 |
| **Red/Blue/Green defense triad** | Attacker / observer / fixer agents automate the security loop. | Day 4 |
| **Plan-level checkpoints** | Catch problems on the plan before code is generated (cheaper). | Day 4 |
| **Spec-driven development; code is disposable** | The Gherkin/BDD spec is the versioned source of truth; regenerate code. | Day 5 |
| **Slicing the elephant** | Decompose ambiguous long-horizon goals into tightly-scoped microagents grounded by a graph. | Day 5 |
| **Knowledge-graph grounding over flat RAG** | GQL + vector + full-text for impact mapping and side-effect simulation. | Day 5 |
| **Architecture-execution separation + closed-loop self-improvement** | An architect owns the graph; sandboxed coders fill blanks; a super-architect feeds learnings back into the spec. | Day 5 |

### 2. The Vibe-Coding Methodology, End-to-End

The course traces a single escalator and tells you exactly where to step off:

1. **Prototype (vibe-code).** Describe the app in plain English (AI Studio); publish to Cloud Run in clicks; iterate by swapping models and using Antigravity's visual planning (Day 1). This is the *casual* end of the spectrum — fast but fragile.
2. **Reach outward (tools).** Wire MCP servers (real-time data, no stale-training hallucination), use A2A for collaborating agents and A2UI for safe dynamic UI — with cost controls and a kill switch from the start (Day 2).
3. **Manage knowledge (skills).** Replace prompt-stuffing with **progressive-disclosure skills**; choose skill vs MCP vs tool deliberately; keep state off the prompt; evaluate the whole skill library (Day 3).
4. **Secure & evaluate (agentic engineering).** Shift security and evals **left** into CI/CD; evaluate the *trajectory* and the *plan*; sandbox + JIT credentials + egress control; bind AI guardrails with deterministic ones; reserve HITL (vibe diff) for critical decisions (Day 4).
5. **Production at scale (spec-driven).** **Stop vibe-coding for production.** Make the **Gherkin/BDD spec** the source of truth; slice the elephant into microagents grounded by a knowledge graph; tier PR review by risk; deploy to Agent Runtime + Cloud Run + Pub/Sub; close the loop back into the spec (Day 5).

The defining boundary is repeated across days: **systematic verification, not spot-checking** (Day 1) → **continuous, trajectory-aware evaluation in CI/CD** (Day 4) → **review the spec/behavior, not the code** (Day 5).

### 3. Evaluation & Guardrails (the course's quality bar)

- **Evaluate the trajectory, not just the output** — a right answer via the wrong tool sequence is *more dangerous* than an error (Day 4). Use OpenTelemetry traces, score on safety/reproducibility/cost/latency, apply policy-based thresholds.
- **Evaluate the plan before code generation** — cheaper and earlier (Day 4).
- **De-correlate the judge** — different model/prompt/temperature; a stronger reasoner judging a cheaper model; self-consistency (Day 4).
- **Reject simple success rates** — use pass@k and rigorous consistency metrics; evaluate at the **library/system level** not per-skill (Day 3).
- **Quality of layers over quantity** — every added guardrail layer must be eval-verified; separation of concerns avoids shared-weakness single points of failure (Day 4).
- **Beware reward hacking / fragile success traps / clever Hans** — passing the test isn't solving the problem (Day 4).
- **Anything an AI writes is a draft** — golden-dataset review + manual spot-checking; a model may optimize the wrong metric (Day 3).
- **Three H's**: Hate, Harm, Hallucination (Day 1).
- **Underspecification** is *why* eval is hard — there's no rigid spec and intent isn't black-and-white (Day 4).
- **Convert failures into improvements** — cluster user corrections, root-cause cross-user patterns, feed back into prompts/training/evals as a regression loop (Day 4).
- **Online/continuous, use-case-specific** — no one-size-fits-all final gate (Day 1, 4).

### 4. Multi-Agent & Protocols

- **The protocol stack**: MCP (tools/data), A2A (agent-to-agent), A2UI (dynamic UI), UCP (commerce/merchant), AP2 (payments) — collapsing O(N×M) integration debt to O(N+M) (Day 2).
- **MCP = USB-C / hands; skills = playbooks; A2A = collaboration**: use MCP when you need a *result*, A2A when another agent must *take responsibility* (Day 2, 3).
- **Single-agent-with-skills first**; multi-agent only when forced by parallelization, A2A communication, independent deployment, or context/tool/latency pressure — every boundary costs a handoff, context loss, latency, and harder tracing (Day 3, 5).
- **Internal specialization** and **microagent architecture** ("slicing the elephant") for long-horizon enterprise tasks, grounded by a knowledge graph (Day 2, 5).
- **A2A across teams/departments** so you don't reinvent the inter-agent protocol; donate protocols to neutral foundations (Linux Foundation) to keep them true open standards (Day 2, 5).
- **Human-signed mandates (AP2)** and **trusted component catalogs (A2UI)** are protocol-level safety boundaries — autonomous payments require human authorization; agent UI never executes arbitrary code (Day 2).

### 5. Deployment, Ops & Cost (FinOps)

- **Sandboxes are the most important security component**: isolated, ephemeral, no host access; IDE proxies code in and kills the sandbox; **JIT downscoped credentials** with token lifetime = sandbox lifetime; **egress control** via NAT to approved URLs (Day 4).
- **Tokens are the new oil** — optimize the token pipeline; **right-size the model per task** (cheap for routine, premium only when needed); cache, batch, and engineer token-efficient prompts/skills (Day 2).
- **Hard kill switches**: max-iteration caps, usage-metadata anomaly tracking, and **Google Cloud billing budget thresholds** (Day 2).
- **Deterministically bypass the LLM** for cheap/low-risk cases (sub-$100 expenses auto-approved in Python) (Day 4).
- **Dynamic trust score with thresholds** — don't kill on every drift; let the green team quarantine and patch first; factor in self-repair quality, iteration count, latency, and cost (Day 4).
- **Corrective controls**: a clean rollback baseline + an automatic stop mechanism (Day 4).
- **I-U-S lifecycle** (Impressive → Useful → Sustainable); a use case can be ~3× more expensive — evaluate cost-sustainability; high CapEx / low OpEx (Day 1).
- **Optimize the whole workflow**, not one stage (whack-a-mole) (Day 1).
- **Production stack (Day 5)**: ADK 2.0 graph-workflow agent → Agent Runtime (dry run first, deploy async) → Cloud Run UI via FastAPI to the session service → Pub/Sub ingestion with dead-letter → observability via Cloud Trace + Cloud Logging (SQL over traces) → Agent Registry catalog.
- **Hybrid inference**: Gemini orchestrator + on-device Gemma; on-device router decides on-device vs server tier (Day 5).
- **Avoid "token maxing"** — optimize for business outcome, not tokens generated (Day 5).

---

## Glossary of Named Tools, Frameworks & Concepts

**ADK (Agent Development Kit).** Google's framework for building agents; ADK 2.0 adds a graph-workflow API embedding deterministic logic in nodes (Day 1, 4, 5).
**Agent Engine / Agent Platform.** Deploy, evaluate, and emit traces for agents (Day 1).
**Agent Runtime.** Google Cloud deployment target for production agents (Day 5).
**Agent Registry.** Centralized catalog of an organization's (thousands of) agents, auto-populated on deploy (Day 5).
**Antigravity (anti-gravity).** Google's agentic IDE / central command center; supports per-prompt model swapping; multi-agent behind the scenes (Day 1–5).
**Antigravity CLI (AGY) / Agent CLI.** Run agentic planning/tool-calling and scaffold/test/lint/deploy from the terminal/IDE (Day 2, 3, 4, 5).
**AI Studio.** Vibe-code an app from plain-English description, publish, and share (Day 1).
**Cloud Run.** One-click app/UI deployment target (Day 1, 5).
**Gemini.** Google's LLM family; orchestrator/most-capable; Gemini Pro as judge, Flash as standard (Day 1–5).
**Gemini Spark.** Always-on 24/7 personal agent (Day 1).
**Gemma / Gemma 4.** Open-weight on-device models (phones/laptops/PCs) for simple agentic tasks; multimodal local checkpoint (Day 5).
**Alpha Evolve.** DeepMind evolutionary algorithmic agent (LLM + evaluator) that discovers optimized algorithms (Day 1).
**Open Knowledge Format.** Karpathy-style LLM-wiki of interlinked markdown "index cards," one per system entity (Day 1).
**Graph RAG / GraphRAG.** Retrieval that follows links between knowledge cards to answer change-impact / breaking-change questions; on massive code bases, GQL + vector + full-text (Day 1, 5).
**MCP (Model Context Protocol).** "USB-C for tool connections"; standard transports stdio + SSE; 50+ Google-managed servers; the agent's "hands" (Day 2, 3).
**A2A (Agent-to-Agent).** Open standard (Google → Linux Foundation) for discovery/negotiation/delegation via machine-readable agent cards (Day 2, 3, 5).
**A2UI / AG-UI / ATUI.** Agent-generated, safe, dynamic UI from trusted component catalogs — never arbitrary code (Day 2, 5).
**UCP (Universal Commerce Protocol).** Merchant side — carts/orders (Day 2).
**AP2 (Agent Payment Protocol).** Payment gateway with strict human-signed mandates (Day 2).
**Google MCP Toolbox.** Restrict MCP-exposed DB tools to a minimal allowlist (Day 2).
**Agent Skills / SKILL.md / agentskills.io.** Self-contained skill folder around a SKILL.md; vendor-neutral open standard; the agent's "playbooks" (Day 3).
**Progressive disclosure.** Load ~50-token skill metadata at startup; full instructions on demand (Day 3).
**Context rot.** Degradation from overlapping/look-alike loaded skills (distractors), not raw token count (Day 3).
**Skill card / NVIDIA Verify Agent Skills.** Machine-readable provenance/access/limitations + a skill inspector (code-vuln + prompt-injection + signing) (Day 3).
**pass@k.** Consistency/eval metric (vs. naive success rate) (Day 3).
**Capability profile.** Swappable, version-controlled bundle of skills/tools/boundaries for a node (Day 3).
**File message bus.** Off-prompt state store owned by a DAG controller; nodes pass references (Day 3, 5).
**Effective (continuous) trust.** Trust as a continuously earned metric across supply chain, identity, runtime, context (Day 4).
**Trajectory-aware evaluation.** Evaluate the tool/reasoning path over OpenTelemetry, not just output (Day 4).
**OpenTelemetry.** Trace/trajectory capture substrate (Day 4).
**Red/Blue/Green defense triad.** Attacker / observer / fixer security agents (Day 4).
**Vibe diff.** Translates compiled syntax back to plain language for human (incl. non-coder) sign-off (Day 4).
**Slop squatting.** Attackers registering malicious packages under names an AI is likely to hallucinate (Day 4).
**gVisor.** Network-isolated, ephemeral sandbox (Day 4).
**JIT downscoped credentials / zero ambient authority.** Tokens scoped to exact need, lifetime = sandbox lifetime; prevents the confused-deputy problem (Day 4).
**Agent BOM (AGBOM) / Agent Behavioral Analytics (ABA).** Expected behavior/boundaries definition + drift detection against the trajectory timeline (Day 4).
**STRIDE (as a skill).** Threat-modeling agent skill that scans, verifies tests, and autonomously fixes (Day 4).
**Fragile success trap / clever Hans.** Reward-hacking where a passing test masks an unsolved problem (Day 4).
**Underspecification.** No rigid spec + user can't state all constraints → why agent eval is hard (Day 4).
**request-input API.** HITL pause-for-approval mechanism (Day 4).
**Spec-driven development / Gherkin / BDD.** Behavioral spec as the versioned source of truth; code disposable (Day 5).
**AGENTS.md / GEMINI.md / /specs.** Cross-tool foundation / model-specific instructions / task-specific specs hierarchy (Day 5).
**Spanner Graph.** Graph DB grounding agents on million-line code bases (GQL + vector + full-text) (Day 5).
**Slicing the elephant.** Decomposing a long-horizon ambiguous goal into microagents (Day 5).
**Pub/Sub.** Event ingestion / streaming with push subscriptions + dead-letter (Day 4, 5).
**Cloud Trace / Cloud Logging.** Observability; SQL over execution traces (Day 5).
**Enterprise policy/quality server.** Structural role validation + semantic safety checks; blocks tool execution on PII leak/unmask; dynamic context resolvers + secure placeholders (Day 5).
**Loop engineering.** Emerging framing for optimizing the whole agent loop, not one stage (Day 2).
**I-U-S framework.** Impressive → Useful → Sustainable lifecycle (Day 1).
**Three H's.** Hate, Harm, Hallucination (Day 1).
**Tokens are the new oil.** Token economics / FinOps framing (Day 2).

---

## What This Course Defines as Mastery

Per the course, a *production-grade agentic system* (an "A+") is one that:

1. **Treats the harness as the product, not the model.** ~90% of effort goes to sandboxes, tools, orchestration, and guardrails; the model is swappable (Day 1, 2).
2. **Is spec-driven, with code disposable.** A versioned, reviewed Gherkin/BDD spec is the source of truth; implementation is regenerated/translated freely; specs/tests/changelog auto-update on every generation (Day 5).
3. **Grounds itself in structured representations, never dumped context.** Open Knowledge Format / knowledge graphs (GQL + vector + full-text) enable impact mapping and side-effect simulation *before* changing a line (Day 1, 5).
4. **Manages knowledge via progressive-disclosure skills, not prompt-stuffing.** ~50-token metadata + on-demand loading; skill vs MCP vs tool chosen deliberately; library-level optimization; the delete test for clean boundaries (Day 3).
5. **Keeps state off the prompt.** DAG controller + file message bus; pass pointers, not values; inspectable on disk (Day 3, 5).
6. **Earns trust continuously and evaluates the trajectory.** Effective trust across supply chain/identity/runtime/context; OpenTelemetry trajectory + plan-level checkpoints; pass@k; de-correlated judges; reward-hacking detection; library-level, online, use-case-specific evals (Day 3, 4).
7. **Contains its own blast radius deterministically.** Ephemeral sandboxes (gVisor), JIT downscoped credentials (zero ambient authority), egress control; AI guardrails *bound by* deterministic guardrails; supply-chain defense against slop squatting; quality of layers over quantity (Day 4).
8. **Uses open protocols, not bespoke integrations.** MCP/A2A/A2UI/UCP/AP2 collapse O(N×M) → O(N+M); MCP for results, A2A for collaboration; A2UI from trusted catalogs; human-signed payment mandates (Day 2).
9. **Treats the human as a circuit-breaker, not a gatekeeper.** Risk-tiered review (auto-merge / daily digest / human review); vibe diff and semantic/behavioral review for non-coders; HITL reserved for the few critical alignment decisions; engage the human as late and as rarely as possible (Day 4, 5).
10. **Runs FinOps as a first-class discipline.** Right-size the model per task; cache/batch; deterministic LLM bypass for cheap cases; max-iteration caps + billing-budget kill switches; avoid token maxing; evaluate cost-sustainability (I-U-S) (Day 1, 2, 4, 5).
11. **Closes the loop and improves from its own failures.** Architecture-execution separation; sandboxed coders fill blanks in a pre-approved structure; collect logs/trajectories; a super-architect feeds learnings back into the spec; cluster user corrections into regression evals (Day 4, 5).
12. **Builds responsibly and stays buildable.** Security front-and-foremost; protect people's data; maintain human expertise and system intuition; keep building in the open because today's stack is obsolete in six months (Day 1, 2, 5).

The single sentence the course would endorse: *mastery is a continuously-trusted, trajectory-evaluated, spec-driven system of graph-grounded microagents and progressive-disclosure skills, contained by deterministic sandboxes and right-sized economics, where the human signs off on risk — not syntax.*
