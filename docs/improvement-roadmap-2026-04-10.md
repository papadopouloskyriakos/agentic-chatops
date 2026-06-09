# Improvement Roadmap — 14 Industry Best Practice Gaps

> Created 2026-04-10. Based on [industry sources research](industry-sources-research-2026-04-10.md).

## Phase 1: Quick Wins (implementable now, 1-2 hours each)

### G5 — Progressive Skill Disclosure
**Current:** 5 skills load fully into context. **Target:** 3-level progressive loading (name → SKILL.md → referenced files).
- **Files:** `.claude/skills/*/SKILL.md` (5 files)
- **Change:** Restructure skills to keep frontmatter lean, split verbose content into sub-files
- **Impact:** Token savings on every session that doesn't use a skill

### G9 — Parallel Guardrail Execution
**Current:** PreToolUse hooks run sequentially (~100ms). **Target:** Parallel execution (~50ms).
- **Files:** `scripts/hooks/audit-bash.sh`, `scripts/hooks/protect-files.sh`
- **Change:** Create `scripts/hooks/parallel-guard.sh` wrapper that spawns both checks concurrently
- **Impact:** ~50ms savings per tool call (matters at 75 tool calls/session = 3.75s total)
- **Note:** Claude Code hooks are inherently sequential per matcher. Parallelism only possible within a single hook script that checks multiple patterns.

### G11 — Model Routing for Main Sessions
**Current:** All sessions use Opus 4.6. **Target:** Route simple alerts to Sonnet, complex to Opus.
- **Files:** `workflows/claude-gateway-runner.json` (Build Prompt + Launch Claude nodes)
- **Change:** Add complexity classifier in Build Prompt, pass model hint to Launch Claude
- **Impact:** ~60% cost reduction on simple alerts (Sonnet vs Opus pricing)

## Phase 2: High Impact (3-5 hours each)

### G3 — Context Compaction with Recall Optimization
**Current:** PreCompact hook blocks and prompts user. **Target:** Auto-generate structured summary.
- **Files:** `scripts/hooks/mempal-precompact.sh`, new `scripts/compact-session-summary.py`
- **Change:** On PreCompact, generate recall-optimized summary (key decisions, unresolved issues, state snapshots)
- **Impact:** Multi-hour session coherence without manual intervention

### G4 — Self-Correcting RAG (Retrieval Quality Gate)
**Current:** RAG returns results with no quality assessment. **Target:** Agent evaluates retrieval quality, re-queries if low.
- **Files:** `scripts/kb-semantic-search.py`, `workflows/claude-gateway-runner.json` (Build Prompt)
- **Change:** Add quality score to search output, inject retrieval confidence note into prompt
- **Impact:** Prevents low-quality RAG from misleading investigations

### G1 — Code-as-Tool-Orchestrator
**Current:** 153 MCP tools exposed directly. **Target:** Tools exposed as callable code APIs.
- **Files:** New `servers/` directory structure, runner workflow changes
- **Change:** Wrap MCP tool calls as Python functions, let Claude write code to chain them
- **Impact:** Up to 98.7% token savings on complex multi-tool operations
- **Dependency:** Requires Claude Code to support code execution context (available in SDK)

## Phase 3: Architectural (1-2 weeks each)

### G6 — A2A Protocol Upgrade to Google Spec
**Current:** NL-A2A/v1 (custom). **Target:** Align with Google A2A (JSON-RPC 2.0, signed cards, gRPC).
- **Impact:** Future interoperability with external agent systems

### G8 — OpenTelemetry Structured Tracing
**Current:** Prometheus metrics only. **Target:** OTel spans for every tool call, LLM invocation, decision.
- **Dependency:** Requires Jaeger or OTel collector deployment

### G7 — Atomic Transactions / Undo Stacks
**Current:** No rollback on failed multi-step operations. **Target:** Pre-state snapshots + undo log.
- **Impact:** Safer infrastructure changes with automatic rollback

### G2 — Programmatic Tool Calling
**Current:** CLI-based invocation. **Target:** Direct API with parallel tool execution.
- **Dependency:** Requires Anthropic API code execution tool (available in API, not CLI)

## Phase 4: Research (ongoing)

### G10 — GraphRAG Knowledge Graph
**Current:** Document-level RAG. **Target:** Entity-relation graphs from incidents + NetBox.
- **New tables:** `entities`, `relationships`, `entity_attributes`

### G12 — HyDE Fallback Retrieval
**Current:** Query rewriting via qwen3:4b. **Target:** Generate hypothetical matching docs for sparse queries.

### G13 — Agent-Generated Tool Improvement Loop
**Current:** No per-tool metrics. **Target:** Tool call logging + success rates + auto-improvement suggestions.
- **New table:** `tool_call_log`

### G14 — Short-Lived Credential Rotation
**Current:** Persistent .env secrets. **Target:** OpenBao integration for session-scoped tokens.
- **Dependency:** OpenBao cluster already deployed but not integrated with n8n/Claude Code
