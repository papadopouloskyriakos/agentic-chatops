# The book of Gulli — Agentic Design Patterns (overview)

> **Book:** *Agentic Design Patterns — A Hands-On Guide to Building Intelligent Systems*
> **Author:** Antonio Gulli
> **Length:** 424 pages, 21 chapters, 7 appendices
> **Purchase:** [Amazon — Agentic-Design-Patterns-Hands-Intelligent](https://www.amazon.com/Agentic-Design-Patterns-Hands-Intelligent/dp/3032014018/)
> **Source PDF (internal):** [`docs/Agentic_Design_Patterns.pdf`](Agentic_Design_Patterns.pdf)
> **Per-chapter text (internal):** [`docs/gulli-book/`](gulli-book/)

This file exists so that queries like *"the book of Gulli"*, *"Antonio Gulli's book"*, *"Agentic Design Patterns book"*, *"ELI5 the book"*, or *"summarize the book"* retrieve the right content. Until 2026-04-23 those queries landed on [`book-gap-analysis.md`](book-gap-analysis.md) instead, because that was the only file whose title contained the word "book."

## What the book is

Antonio Gulli's *Agentic Design Patterns* catalogues 21 reusable patterns for building LLM-powered agent systems, each written as a hands-on chapter with runnable Python code. It is the canonical source we audit our own ChatOps/ChatSecOps/ChatDevOps agent platform against. Every pattern in Gulli's book has been scored for "is it implemented here, and how well?" — that audit lives at [`docs/agentic-patterns-audit.md`](agentic-patterns-audit.md) and the per-pattern status files are at [`wiki/patterns/gulli-01-prompt-chaining.md`](../wiki/patterns/gulli-01-prompt-chaining.md) through [`wiki/patterns/gulli-21-exploration-discovery.md`](../wiki/patterns/gulli-21-exploration-discovery.md).

## The 21 patterns at a glance

### Part One — Foundational Agent Patterns (Chapters 1-7)

| # | Pattern | One-line definition | Our per-pattern page |
|---|---------|---------------------|----------------------|
| 1 | **Prompt Chaining** | Sequence LLM calls so each step's output becomes the next step's input, enabling structured multi-stage reasoning. | [gulli-01](../wiki/patterns/gulli-01-prompt-chaining.md) |
| 2 | **Routing** | Use an LLM or classifier to dispatch a request to the right downstream handler based on its content. | [gulli-02](../wiki/patterns/gulli-02-routing.md) |
| 3 | **Parallelization** | Fan out independent sub-tasks concurrently and merge their results, reducing wall-clock time. | [gulli-03](../wiki/patterns/gulli-03-parallelization.md) |
| 4 | **Reflection** | Have the agent (or a second LLM call) critique and revise its own output before returning it. | [gulli-04](../wiki/patterns/gulli-04-reflection.md) |
| 5 | **Tool Use** | Expose external functions/APIs to the LLM as callable tools; the model chooses when and how to invoke them. | [gulli-05](../wiki/patterns/gulli-05-tool-use.md) |
| 6 | **Planning** | Produce an explicit, step-ordered plan before execution so the agent commits to an intent and can be validated. | [gulli-06](../wiki/patterns/gulli-06-planning.md) |
| 7 | **Multi-Agent** | Coordinate multiple specialised agents (hierarchical, peer, or market-style) on a shared task. | [gulli-07](../wiki/patterns/gulli-07-multi-agent.md) |

### Part Two — State and Learning (Chapters 8-11)

| # | Pattern | One-line definition | Our per-pattern page |
|---|---------|---------------------|----------------------|
| 8 | **Memory Management** | Persist short-term (turn) and long-term (cross-session) context so agents remember facts, prefs, and outcomes. | [gulli-08](../wiki/patterns/gulli-08-memory.md) |
| 9 | **Learning and Adaptation** | Update agent behaviour from experience — preference capture, policy iteration, feedback loops. | [gulli-09](../wiki/patterns/gulli-09-learning-adaptation.md) |
| 10 | **Model Context Protocol (MCP)** | Anthropic's standard for exposing tools/resources to LLMs over a uniform JSON-RPC interface. | [gulli-10](../wiki/patterns/gulli-10-mcp.md) |
| 11 | **Goal Setting and Monitoring** | Make agent objectives explicit, trackable, and introspectable so drift and success can be measured. | [gulli-11](../wiki/patterns/gulli-11-goal-setting-monitoring.md) |

### Part Three — Robustness and Integration (Chapters 12-14)

| # | Pattern | One-line definition | Our per-pattern page |
|---|---------|---------------------|----------------------|
| 12 | **Exception Handling and Recovery** | Detect, contain, and recover from tool errors and model failures without hanging or silent data loss. | [gulli-12](../wiki/patterns/gulli-12-exception-handling.md) |
| 13 | **Human-in-the-Loop** | Surface approval gates, clarifying questions, and escalations to a human at the right decision boundary. | [gulli-13](../wiki/patterns/gulli-13-human-in-the-loop.md) |
| 14 | **Knowledge Retrieval (RAG)** | Retrieve external facts at inference time to ground generation — chunking, embeddings, rerank, hybrid search. | [gulli-14](../wiki/patterns/gulli-14-rag.md) |

### Part Four — Scaling and Safety (Chapters 15-21)

| # | Pattern | One-line definition | Our per-pattern page |
|---|---------|---------------------|----------------------|
| 15 | **Inter-Agent Communication (A2A)** | Define protocols, envelopes, and discovery for how agents negotiate and hand off work to one another. | [gulli-15](../wiki/patterns/gulli-15-inter-agent-communication.md) |
| 16 | **Resource-Aware Optimization** | Balance latency, cost, and quality by picking the right model/tool/depth for each decision. | [gulli-16](../wiki/patterns/gulli-16-resource-aware-optimization.md) |
| 17 | **Reasoning Techniques** | Chain-of-Thought, Tree-of-Thought, Self-Consistency, ReAct — structured prompts that improve problem-solving. | [gulli-17](../wiki/patterns/gulli-17-reasoning-techniques.md) |
| 18 | **Guardrails and Safety** | Input filters, output validators, tool allowlists, and refusal policies that bound agent behaviour. | [gulli-18](../wiki/patterns/gulli-18-guardrails-safety.md) |
| 19 | **Evaluation and Monitoring** | Offline eval sets, online quality signals, and golden-path tests to catch regressions and drift. | [gulli-19](../wiki/patterns/gulli-19-evaluation-monitoring.md) |
| 20 | **Prioritization** | Schedule and preempt agent work based on urgency, impact, and cost budgets. | [gulli-20](../wiki/patterns/gulli-20-prioritization.md) |
| 21 | **Exploration and Discovery** | Let agents proactively search for useful information, tools, or opportunities beyond the explicit task. | [gulli-21](../wiki/patterns/gulli-21-exploration-discovery.md) |

## The 7 appendices

Appendix A (Advanced Prompting), B (GUI → real-world environments), C (Agentic Frameworks), D (AgentSpace), E (AI Agents on the CLI), F (Under the Hood: reasoning engines), G (Coding Agents). Full chapter text for each is available at [`docs/gulli-book/`](gulli-book/).

## How to get deeper

- **"What does Gulli say about pattern N?"** → read the corresponding `docs/gulli-book/chapter-NN-<slug>.md` file for the verbatim chapter text, OR the per-pattern audit page under `wiki/patterns/gulli-NN-*.md` for our implementation status.
- **"How does our platform implement pattern N?"** → start at [`docs/agentic-patterns-audit.md`](agentic-patterns-audit.md), then follow the links into the codebase.
- **"What's missing vs Gulli's book?"** → [`docs/book-gap-analysis.md`](book-gap-analysis.md) is the prioritized gap list.
