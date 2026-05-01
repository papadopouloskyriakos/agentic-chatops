# ChatOps Platform

> The agentic infrastructure orchestration system. Compiled 2026-04-11 14:13 UTC.

## Architecture

3 subsystems: **ChatOps** (infra alerts), **ChatSecOps** (security alerts), **ChatDevOps** (dev tasks).

Pipeline: External trigger -> n8n webhook -> OpenClaw triage (Tier 1) -> Claude Code (Tier 2) -> Human approval (Tier 3)

### agentic_patterns_21_21

## Status (2026-04-07)
All 21/21 patterns implemented. **Tri-source audited: 11/11 dimensions A+ (100%)**. Three knowledge sources: Gulli book (21 patterns) + Anthropic Cert (sub-agent design) + Industry References (6 sources: Anthropic, OpenAI, LangChain, Microsoft). Score: B+ (84%) → A+ (100%) via 16 YT issues (IFRNLLEI01PRD-357 to 372). See `docs/tri-source-audit.md` and `docs/tri-source-eval-report-2026-04-07.md`.

### Scores
- **A+:** Multi-Agent (7), Memory (8), Learning (9), RAG (14), Res

### Matrix Bridge Architecture

## Matrix Bridge (QGKnHGkw4casiWIU) - 69 nodes

Polls Matrix /sync from 4 rooms (#chatops, #cubeos, #meshsat, #infra-nl-prod), extracts messages, routes via Command Router (Switch node).

### Room Routing
Extract Messages outputs `sourceRoom` from /sync. All Matrix post nodes use `$('Extract Messages').first().json.sourceRoom` for dynamic room. Runner/SessionEnd use `resolveRoom(issueId)`: CUBEOS→#cubeos, MESHSAT→#meshsat, IFRNLLEI01PRD→#infra-nl-prod, default→#chatops.

### Command Ro

### Runner and Poller Workflow Flows

## Runner Flow (qadF2WcaBsIR7SWG) — 47 nodes

### Primary Path
Acquire Lock → Pre Stats → Query Knowledge (hybrid RRF search + budget check + cost prediction + lessons) → Build Prompt (XML-tagged RAG + defensive prompt + NetBox STEP 0 + ReAct + tool profiles + A/B variant + sub-agent delegation) → Launch Claude (dynamic timeout) → Fire Poller + Wait for Claude → Parse Response (cost ceiling + tool call count/limit + token tracking + self-consistency + ReAct compliance) → Validation retry loop (4
