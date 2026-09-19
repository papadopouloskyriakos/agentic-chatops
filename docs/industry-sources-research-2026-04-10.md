# Industry Sources Research — Agentic Systems Engineering

> Research conducted 2026-04-10. Sources: Anthropic (8 articles), Google Cloud/DeepMind (3), OpenAI (3), LangChain (3), Microsoft (2), academic papers (2), industry reports (4).

---

## Source Inventory

### Tier 1 — Official Engineering Guides (Primary Sources)

| # | Source | Publisher | URL | Relevance |
|---|--------|-----------|-----|-----------|
| 1 | **Effective Context Engineering for AI Agents** | Anthropic | [Link](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Context window management, prompt layering, memory strategies |
| 2 | **Effective Harnesses for Long-Running Agents** | Anthropic | [Link](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) | Session persistence, checkpoint/resume, multi-session coherence |
| 3 | **Building Agents with the Claude Agent SDK** | Anthropic | [Link](https://claude.com/blog/building-agents-with-the-claude-agent-sdk) | Agent loop (gather→act→verify→iterate), sub-agent patterns, MCP |
| 4 | **Writing Effective Tools for AI Agents** | Anthropic | [Link](https://www.anthropic.com/engineering/writing-tools-for-agents) | ACI design, tool naming, eval-driven tool improvement |
| 5 | **Equipping Agents with Agent Skills** | Anthropic | [Link](https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills) | Progressive disclosure, skill composition, code bundling |
| 6 | **Code Execution with MCP** | Anthropic | [Link](https://www.anthropic.com/engineering/code-execution-with-mcp) | Code-as-tool-orchestrator, 98.7% token savings, scaling MCP |
| 7 | **Advanced Tool Use (Tool Search, Programmatic)** | Anthropic | [Link](https://www.anthropic.com/engineering/advanced-tool-use) | Deferred tool loading (85% token reduction), parallel execution |
| 8 | **A Practical Guide to Building Agents** | OpenAI | [PDF](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) | End-to-end agent design, orchestration, guardrails, eval |
| 9 | **Choose Agentic AI Architecture Components** | Google Cloud | [Link](https://docs.cloud.google.com/architecture/choose-agentic-ai-architecture-components) | Memory systems, model routing, runtime selection, design patterns |
| 10 | **Agent2Agent (A2A) Protocol** | Google | [Spec](https://github.com/google-a2a/A2A/blob/main/docs/specification.md) / [Intro](https://adk.dev/a2a/intro/) | Agent interoperability, Agent Cards, task lifecycle |

### Tier 2 — Industry Reports & Frameworks

| # | Source | Publisher | URL | Relevance |
|---|--------|-----------|-----|-----------|
| 11 | **State of Agent Engineering 2026** | LangChain | [Link](https://www.langchain.com/state-of-agent-engineering) | 57% production adoption, quality as #1 blocker, eval patterns |
| 12 | **AI Agent Trends 2026** | Google Cloud | [Link](https://cloud.google.com/resources/content/ai-agent-trends-2026) | Enterprise adoption, atomic transactions, undo stacks |
| 13 | **Microsoft Agent Framework 1.0** | Microsoft | [Link](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/) | Multi-agent orchestration patterns, streaming, checkpointing |
| 14 | **LangGraph Platform GA** | LangChain | [Link](https://blog.langchain.com/langgraph-platform-ga/) | Durable state, human-in-the-loop, orchestrator-worker |
| 15 | **Agentic RAG Survey** | arXiv 2501.09136 | [Link](https://arxiv.org/abs/2501.09136) | RAG taxonomy, Self-RAG, CRAG, agent cardinality |

---

## Gap Analysis: Our Platform vs. Industry Best Practices

### Already Implemented (Strengths)

| Practice | Industry Source | Our Implementation |
|----------|----------------|-------------------|
| Multi-tier agent architecture | OpenAI, Anthropic, Google | 3-tier (OpenClaw → Claude Code → Human) |
| Human-in-the-loop | All sources | MSC3381 polls, reactions, approval timeouts |
| Sub-agent delegation | Anthropic Academy, SDK | 10 sub-agents, Haiku/Opus routing |
| Tool search / deferred loading | Anthropic Advanced Tool Use | ToolSearch in Claude Code settings |
| Structured note-taking | Anthropic Context Engineering | NOTES.md pattern, progress tracking |
| Defense-in-depth guardrails | All sources | 7-layer system (hooks → exec → approvals → sanitization → scanning → approval → budget) |
| LLM-as-a-Judge evaluation | LangChain, OpenAI | Haiku/Opus judge, 5-dimension rubric |
| Hybrid RAG (multi-signal) | Agentic RAG Survey | 4-signal RRF (semantic + keyword + wiki + transcripts) |
| Agent Cards / A2A | Google A2A | NL-A2A/v1 protocol with agent cards |
| Memory persistence | Google Cloud, Anthropic | SQLite (18 tables), vector embeddings, session transcripts |
| Cost-adaptive routing | OpenAI, Anthropic | Haiku/Opus model routing, $10/session + $25/day ceiling |
| Eval flywheel | LangChain State of Agents | Monthly eval, regression detector, golden tests, CI gate |

### Gaps — Candidate Improvements

#### HIGH PRIORITY (Direct applicability, proven patterns)

| # | Gap | Source | What It Is | How to Apply |
|---|-----|--------|-----------|--------------|
| **G1** | **Code-as-tool-orchestrator** | Anthropic [Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) | Instead of exposing MCP tools directly, expose them as code APIs. Agent writes code to orchestrate tools → 98.7% token savings, data filtering before model sees it. | Expose our 153 MCP tools as callable Python/TS functions in a `servers/` directory. Claude writes code to chain them instead of sequential tool calls. Would dramatically reduce token costs on complex investigations. |
| **G2** | **Programmatic tool calling** | Anthropic [Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use) | Parallel tool execution via `asyncio.gather()` in sandboxed code. 37% token reduction on complex tasks. 20+ queries simultaneously instead of sequential. | Our Runner currently does sequential tool calls. Could batch NetBox + KB + CLAUDE.md lookups in parallel via code execution. |
| **G3** | **Context compaction with recall optimization** | Anthropic [Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | "Start by maximizing recall...then iterate to improve precision." Structured compaction that preserves architectural decisions and unresolved issues. | Our PreCompact hook saves transcripts but doesn't do intelligent compaction. Could implement recall-optimized summarization before context window overflow. |
| **G4** | **Self-correcting RAG (Self-RAG / CRAG)** | [Agentic RAG Survey](https://arxiv.org/abs/2501.09136) | Agent critiques its own retrieved results, decides if retrieval quality is sufficient, and re-retrieves if not. Self-RAG adds reflection tokens; CRAG adds a "knowledge refinement" step. | Our RAG pipeline returns results but doesn't self-evaluate. Agent could assess retrieval quality and re-query with reformulated queries if confidence is low. |
| **G5** | **Agent Skills with progressive disclosure** | Anthropic [Agent Skills](https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills) | 3-level loading: L1 (name/description only) → L2 (full SKILL.md) → L3 (referenced files). Reduces token cost by loading context only when needed. | Our 5 skills load fully. Could restructure to progressive disclosure — only load skill content when triggered, keep descriptions minimal in system prompt. |
| **G6** | **Google A2A protocol upgrade** | Google [A2A Protocol](https://adk.dev/a2a/intro/) | Our NL-A2A/v1 predates Google's official A2A. The official spec adds: gRPC support, signed security cards, standardized task lifecycle (submitted→working→done), streaming via SSE, and cross-framework interop. | Upgrade NL-A2A/v1 to align with Google A2A spec. Would enable future interop with external agent systems. Agent Cards already exist — add JSON-RPC 2.0 transport + task state machine. |

#### MEDIUM PRIORITY (Significant improvement, requires more work)

| # | Gap | Source | What It Is | How to Apply |
|---|-----|--------|-----------|--------------|
| **G7** | **Atomic transactions / undo stacks** | Google Cloud [AI Agent Trends 2026](https://cloud.google.com/resources/content/ai-agent-trends-2026) | "Agent undo stacks" and transaction coordinators that encapsulate complex logic into atomic, reversible units using idempotent tools and checkpointing. | Our agents can execute infrastructure changes but can't roll back cleanly if a multi-step plan fails partway. Could implement checkpoint/rollback for SSH commands (capture state before, revert on failure). |
| **G8** | **Structured observability (OpenTelemetry)** | LangChain [State of Agents](https://www.langchain.com/state-of-agent-engineering), Industry reports | 94% of production agents have observability, 71.5% have full tracing. OpenTelemetry-based spans for every tool call, LLM invocation, and decision point. | We have Prometheus metrics + JSONL logs but no structured tracing with spans. Could add OTel spans to Runner workflow steps and sub-agent calls for end-to-end trace visualization. |
| **G9** | **Parallel guardrail execution** | Industry guardrails guides | Run independent guardrail checks simultaneously (toxicity + PII + jailbreak) → 70ms vs 200ms serial. | Our guardrails run sequentially (PreToolUse hooks). Could parallelize the audit-bash + protect-files checks, and run credential scanning + input sanitization concurrently in the Runner. |
| **G10** | **GraphRAG** | [Agentic RAG Survey](https://arxiv.org/abs/2501.09136) | Entity-relation graphs from corpora for holistic understanding. "Rapidly evolving into a mainstream RAG paradigm." | Our RAG is document-level. Could build a knowledge graph from incident_knowledge + lessons_learned + host relationships (already in NetBox) for graph-based retrieval alongside vector search. |
| **G11** | **Model routing by task complexity** | Google Cloud [Architecture](https://docs.cloud.google.com/architecture/choose-agentic-ai-architecture-components) | Dynamic model selection — route simple tasks to SLMs, reserve powerful models for complex reasoning. Adjustable "thinking budget." | We route Haiku vs Opus for sub-agents but not for the main session. Could add complexity classification before Launch Claude — simple alerts get Sonnet, complex get Opus. |

#### LOWER PRIORITY (Research-stage or niche)

| # | Gap | Source | What It Is | How to Apply |
|---|-----|--------|-----------|--------------|
| **G12** | **HyDE (Hypothetical Document Embeddings)** | Agentic RAG research | Generate a hypothetical answer first, embed that, then search for similar real documents. Improves sparse query recall. | Could add to kb-semantic-search.py as a fallback when initial retrieval confidence is low. |
| **G13** | **Agent-generated tool improvement** | Anthropic [Writing Tools](https://www.anthropic.com/engineering/writing-tools-for-agents) | Have agents analyze their own tool-call transcripts to identify description gaps and suggest improvements. | Run monthly analysis of Runner JSONL logs — find tool calls that failed or required retries, auto-suggest tool description improvements. |
| **G14** | **Short-lived credentials for agent actions** | Industry security guides | Policy-based access control with short-lived tokens, not persistent credentials. Every access generates a log. | Our agents use persistent SSH keys and API tokens. Could rotate to short-lived tokens via OpenBao for sensitive operations (ASA access, K8s admin). |

---

## Recommended Implementation Order

### Phase 1: Quick Wins (1-2 days each)
1. **G5** — Progressive skill disclosure (restructure existing 5 skills)
2. **G9** — Parallel guardrail execution (small code change)
3. **G11** — Model routing for main sessions (add complexity classifier to Build Prompt)

### Phase 2: High-Impact (3-5 days each)
4. **G3** — Context compaction optimization (enhance PreCompact hook)
5. **G4** — Self-correcting RAG (add retrieval quality check to kb-semantic-search.py)
6. **G1** — Code-as-tool-orchestrator (expose MCP tools as code APIs — biggest token savings)

### Phase 3: Architectural (1-2 weeks each)
7. **G6** — A2A protocol upgrade to Google spec
8. **G8** — OpenTelemetry structured tracing
9. **G7** — Atomic transactions / undo stacks
10. **G2** — Programmatic tool calling (depends on Claude API code execution)

### Phase 4: Research (ongoing)
11. **G10** — GraphRAG knowledge graph
12. **G12** — HyDE fallback retrieval
13. **G13** — Agent-generated tool improvement loop
14. **G14** — Short-lived credential rotation

---

## Sources

### Anthropic Engineering
- [Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Building Agents with the Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)
- [Writing Effective Tools for AI Agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Equipping Agents with Agent Skills](https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills)
- [Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)

### Google Cloud / DeepMind
- [Choose Agentic AI Architecture Components](https://docs.cloud.google.com/architecture/choose-agentic-ai-architecture-components)
- [AI Agent Trends 2026](https://cloud.google.com/resources/content/ai-agent-trends-2026)
- [A2A Protocol Introduction](https://adk.dev/a2a/intro/)
- [A2A Protocol Specification](https://github.com/google-a2a/A2A/blob/main/docs/specification.md)

### OpenAI
- [A Practical Guide to Building Agents (PDF)](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)
- [Building Agents Track](https://developers.openai.com/tracks/building-agents)
- [Agents SDK](https://developers.openai.com/api/docs/guides/agents-sdk)

### LangChain
- [State of Agent Engineering 2026](https://www.langchain.com/state-of-agent-engineering)
- [LangGraph Platform GA](https://blog.langchain.com/langgraph-platform-ga/)
- [Building LangGraph from First Principles](https://blog.langchain.com/building-langgraph/)

### Microsoft
- [Microsoft Agent Framework 1.0](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/)
- [AutoGen to Agent Framework Migration](https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/)

### Academic
- [Agentic RAG Survey (arXiv 2501.09136)](https://arxiv.org/abs/2501.09136)
- [A-RAG: Scaling via Hierarchical Retrieval (arXiv 2602.03442)](https://arxiv.org/abs/2602.03442)
