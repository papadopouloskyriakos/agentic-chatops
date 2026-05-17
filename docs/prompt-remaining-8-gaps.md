# Resume Prompt — Remaining 8 Industry Best Practice Gaps

> Use this prompt to start a new Claude Code session that continues the improvement roadmap.

---

## Prompt

```
Read docs/industry-sources-research-2026-04-10.md and docs/improvement-roadmap-2026-04-10.md for full context.

8 of 14 industry best-practice gaps remain from the agentic systems research (2026-04-10). 6 were implemented and deployed (G3, G4, G10, G11, G12, G13). The remaining 8 have YT issues created but need implementation:

### Phase 1 — Quick Wins (implement first)

**G5: Progressive skill disclosure** (IFRNLLEI01PRD-424)
- Current: 5 skills in .claude/skills/*/SKILL.md load fully into context
- Target: Restructure to 3-level progressive loading per Anthropic's Agent Skills pattern
- Keep SKILL.md frontmatter lean (name + description + argument-hint only)
- Move verbose instructions into sub-files (e.g., INSTRUCTIONS.md, EXAMPLES.md)
- Claude loads L1 (frontmatter) by default, L2 (SKILL.md body) when triggered, L3 (sub-files) on demand
- Files: .claude/skills/triage/SKILL.md, alert-status/SKILL.md, drift-check/SKILL.md, cost-report/SKILL.md, wiki-compile/SKILL.md
- Source: https://claude.com/blog/equipping-agents-for-the-real-world-with-agent-skills

**G9: Parallel guardrail execution** (IFRNLLEI01PRD-425)
- Current: 2 PreToolUse hooks run sequentially (~100ms total per tool call)
- Problem: Claude Code hooks are sequential per matcher — can't truly parallelize separate hooks
- Solution: Merge audit-bash.sh and protect-files.sh into a single optimized hook that handles BOTH Bash and Edit|Write matchers in one script, reducing overhead from 2 process spawns to 1
- Alternative: Create a unified hook-executor.sh that checks tool type and runs the appropriate checks in a single invocation
- Files: scripts/hooks/audit-bash.sh, scripts/hooks/protect-files.sh, .claude/settings.json
- Source: Industry guardrails guides (2026)

### Phase 2 — High Impact

**G1: Code-as-tool-orchestrator** (IFRNLLEI01PRD-429)
- Current: 153 MCP tools exposed directly to Claude, each tool call = full context round-trip
- Target: Expose MCP tools as callable Python functions in a servers/ directory. Claude writes code to chain tools instead of sequential tool calls
- Architecture: Create servers/{netbox,proxmox,kubernetes,youtrack}/ directories with Python wrappers around MCP tool calls. Claude discovers by listing servers/, reads the function signatures, writes code to orchestrate
- Key insight from Anthropic: "Processing a transcript retrieval and Salesforce update was reduced from 150,000 tokens to 2,000 tokens — 98.7% savings"
- Constraint: Requires Claude Code code execution context (sandbox). Test if Claude can already import and call Python functions that wrap MCP calls
- Files: New servers/ directory structure, CLAUDE.md update to document the pattern
- Source: https://www.anthropic.com/engineering/code-execution-with-mcp

### Phase 3 — Architectural

**G6: A2A protocol upgrade to Google spec** (IFRNLLEI01PRD-430)
- Current: NL-A2A/v1 (custom protocol in docs/a2a-protocol.md) with agent cards in a2a/agent-cards/
- Target: Align with Google A2A (JSON-RPC 2.0 over HTTP, signed security cards, SSE streaming, standardized task lifecycle)
- Key changes: (1) Add JSON-RPC 2.0 message envelope alongside existing format, (2) Update agent cards to match Google AgentCard schema, (3) Add task state machine (submitted→working→input-needed→done), (4) Auto-populate a2a_task_log table on every inter-agent message
- NOT required: gRPC (overkill for our scale), full A2A server deployment
- Files: docs/a2a-protocol.md, a2a/agent-cards/*.json, workflows/claude-gateway-runner.json (Parse Response envelope validation)
- Source: https://adk.dev/a2a/intro/ and https://github.com/google-a2a/A2A/blob/main/docs/specification.md

**G8: OpenTelemetry structured tracing** (IFRNLLEI01PRD-431)
- Current: Prometheus metrics only (7 exporters, 31 cron jobs). JSONL logs have no trace context.
- Target: Add W3C Trace Context to session JSONL events. Instrument 6 key spans: session.init, tool.build_prompt, tool.launch_claude, tool.wait_for_result, tool.eval, session.end
- Approach: (1) Generate trace_id at session start (UUID4), store in sessions table, (2) Add trace_id + span_id to each JSONL event, (3) Create scripts/export-otel-traces.py that reads JSONL and exports OTLP proto to collector, (4) Deploy Jaeger as Docker container on nl-claude01 (OTLP receiver :4318, UI :16686)
- Lightweight version: Just add trace_id to JSONL + sessions table WITHOUT deploying Jaeger. The trace structure enables future collector integration.
- Files: schema.sql (add trace_id to sessions), workflows/claude-gateway-runner.json (Wait for Claude JSONL parsing), new scripts/export-otel-traces.py
- Source: LangChain State of Agents (94% of production agents have observability, 71.5% have full tracing)

**G7: Atomic transactions / undo stacks** (IFRNLLEI01PRD-432)
- Current: SSH commands execute with no rollback. If a multi-step plan fails partway, state is inconsistent.
- Target: Pre-state snapshot before infrastructure changes, undo log table, automatic rollback on failure
- Approach: (1) Add execution_log table (session_id, step_index, command, pre_state_snapshot, post_state_snapshot, exit_code, rolled_back), (2) Create scripts/capture-pre-state.sh that snapshots relevant device state before exec (show run, kubectl get, pct config), (3) Add rollback logic to safe-exec.sh — on failure, replay pre_state_snapshot commands, (4) Start with ASA config changes (show run before/after) and K8s operations (kubectl get before/after)
- NOT required: Full transaction coordinator (overkill). Just capture + log + manual rollback assistance.
- Files: schema.sql, openclaw/skills/safe-exec.sh, new scripts/capture-pre-state.sh
- Source: Google Cloud AI Agent Trends 2026

**G2: Programmatic tool calling** (IFRNLLEI01PRD-433)
- Current: Claude invoked via CLI (claude -p). All tool calls are sequential through the agent loop.
- Target: Direct Anthropic API calls with parallel tool execution via asyncio.gather()
- Reality check: This is the HARDEST gap. The entire Runner workflow is built around SSH → claude CLI. Migrating to direct API would require rewriting Launch Claude, Wait for Claude, Parse Response, and all retry logic. 
- Pragmatic approach: DON'T migrate away from CLI. Instead, optimize within the CLI by (1) using Claude Code's built-in parallel tool calls (it already supports this), (2) adding tool_choice hints in Build Prompt to guide efficient tool selection, (3) documenting that G1 (code-as-tool-orchestrator) achieves the same token savings without API migration
- Files: workflows/claude-gateway-runner.json (Build Prompt tool guidance section)
- Source: https://www.anthropic.com/engineering/advanced-tool-use

### Phase 4 — Research

**G14: Short-lived credential rotation** (IFRNLLEI01PRD-437)
- Current: 22 persistent secrets in .env, SSH key ~/.ssh/one_key never rotated
- Target: OpenBao integration for session-scoped tokens
- OpenBao cluster already deployed (3 nodes on pve01/pve02/pve03) but only integrated with K8s via ExternalSecrets
- Approach: (1) Enable AppRole auth in OpenBao for app-user, (2) Create scripts/openbao-token.sh that fetches short-lived tokens, (3) Add credential_usage_log table, (4) Start with ANTHROPIC_API_KEY rotation (least risk), expand to SSH keys later
- Constraint: NEVER modify OOB systems without explicit user approval (feedback memory)
- Files: .env, schema.sql, new scripts/openbao-token.sh, new scripts/rotate-credentials.sh
- Source: Industry security guides (2026)

### Implementation order
1. G5 (skill restructure — quick, no dependencies)
2. G9 (hook optimization — quick, no dependencies)
3. G1 (code-as-tool-orchestrator — highest token savings)
4. G2 (pragmatic: tool guidance, not API migration)
5. G6 (A2A upgrade — spec alignment, backward compatible)
6. G8 (OTel — lightweight version first, Jaeger later)
7. G7 (undo stacks — start with execution_log table + capture script)
8. G14 (credentials — start with ANTHROPIC_API_KEY only)

### Key files to read first
- docs/industry-sources-research-2026-04-10.md — full research with source URLs
- docs/improvement-roadmap-2026-04-10.md — gap analysis with file locations
- CLAUDE.md — project context (197 lines, recently trimmed)
- .claude/settings.json — current hook configuration
- .claude/skills/*/SKILL.md — current skill format (5 skills)
- a2a/agent-cards/*.json — current A2A agent card format
- schema.sql — current 21-table schema

### After implementation
- Run scripts syntax check: bash -n scripts/*.sh && python3 -m py_compile scripts/*.py
- Run RAG test: python3 scripts/kb-semantic-search.py search "device down" --limit 3
- Run eval scripts: ./scripts/score-trajectory.sh --recent && ./scripts/llm-judge.sh --recent
- Verify SQLite: sqlite3 gateway.db ".tables"
- Update READMEs with new counts/features
- Commit and push to main (direct push per user preference)
- Update YT issues to Done
```
