# github/gh-aw — Pattern Analysis for claude-gateway

**URL:** https://github.com/github/gh-aw
**Date:** 2026-04-07
**Purpose:** Extract patterns from GitHub's Agentic Workflows that can improve our platform

---

## What gh-aw Is

A CLI tool enabling natural language markdown workflows executed in GitHub Actions with built-in safety guardrails. Orchestrates AI agents (Copilot, Claude, Codex) to automate repository tasks. 22 skills, markdown-based DSL, security-first design.

---

## Patterns Already Aligned (Validation)

| gh-aw Pattern | Our Equivalent | Notes |
|---------------|----------------|-------|
| Human approval gates before state changes | [POLL] + reaction-based approval + confidence gates | Strong match |
| Read-only default, explicit write gates | SSH investigation free, remediation gated via poll | Aligned |
| Tool allowlisting | `.claude/settings.local.json` + exec-approvals.json (36 patterns) | Aligned |
| Sandboxed execution | PreToolUse hooks: audit-bash.sh (30+ blocks) + protect-files.sh | Aligned |
| Session/task lifecycle tracking | SQLite 14 tables + JSONL stream + Progress Poller | Aligned |
| MCP server integration | 10 MCP servers, 153 tools, namespaced | Aligned |
| Markdown-based skill definitions (YAML frontmatter) | `.claude/agents/*.md` + OpenClaw `SKILL.md` files | Same pattern |
| Tool call logging for transparency | JSONL stream + Poller posts tool activity every 30s to Matrix | Aligned |
| Task description quality standards | Formalized contracts + few-shot examples (good + bad) in Build Prompt | Aligned |
| SHA-pinned dependencies | Not applicable (we don't use npm in workflows) | N/A |

---

## Patterns to Adopt

### 1. Toolset-Based Access (instead of individual tool allowlisting)

**gh-aw approach:** Uses `toolsets:` groups (`repos`, `issues`, `pull_requests`) instead of per-tool allowlists. "Tool names may change between versions, but toolsets provide a stable API."

**Our current state:** 30+ individual tool permissions in settings.local.json. `config/tool-profiles.json` defines 7 task-type profiles but isn't wired into actual permissions — only prompt-level guidance.

**Recommendation:** Formalize tool profiles into named toolsets that map to permission groups. When Claude Code supports per-session tool filtering, wire toolsets into the launch command. Until then, prompt-level guidance (already implemented) is the interim solution.

**Effort:** Low (design) / Medium (implementation when CC supports it)
**Impact:** Medium — reduces tool selection confusion, prevents irrelevant tool calls

### 2. Circuit Breaker Pattern for Retries

**gh-aw approach:** `error-recovery-patterns` skill defines "maximum retry limits (standard: 3 attempts)" with exponential backoff and fail-fast for non-transient errors. Reduced retry loops from 23% to under 10%.

**Our current state:** Validation retry loop does 2 attempts with escalating feedback but no exponential backoff. SSH nodes use `continueOnFail: true` but no circuit breaker. No error classification (transient vs non-transient).

**Recommendation:**
- Classify errors in Parse Response: HTTP 502/503/504 + SSH timeout = transient (retry with backoff). Validation errors + permission denied = non-transient (fail-fast).
- Add exponential backoff to validation retry: attempt 1 immediate, attempt 2 after 5s delay.
- Track retry rate in Prometheus: `chatops_retry_total{type="transient|non_transient"}`.

**Effort:** Medium
**Impact:** Medium — reduces wasted retries, faster failure for non-recoverable errors

### 3. Compile-Time Workflow Validation

**gh-aw approach:** Validates workflow configs before execution. Catches configuration errors early.

**Our current state:** CI validates JSON syntax and bash syntax. `test-workflow-validate` checks basic structure. But no validation of: Build Prompt logic correctness, tool profile JSON schema, connection integrity between nodes, or credential reference validity.

**Recommendation:** Extend the CI `eval-regression` job to include:
- JSON schema validation for tool-profiles.json and eval-sets/*.json
- Build Prompt code linting (check all `$('NodeName')` references exist)
- Connection integrity check (every node output has a valid target)

**Effort:** Medium
**Impact:** Low-Medium — catches config drift before deployment

### 4. Error Classification (Transient vs Non-Transient)

**gh-aw approach:** Explicitly classifies errors:
- Transient: HTTP 502/503/504, rate limits, network timeouts → retry with backoff
- Non-transient: validation errors, auth failures, missing resources → fail-fast
- Anti-patterns: retrying validation errors (won't self-correct), missing backoff, unlogged retries

**Our current state:** All errors go through the same `continueOnFail` path. No classification. Parse Response treats all validation warnings the same way.

**Recommendation:** In Parse Response, add error classification:
```javascript
const isTransient = /timeout|ECONNREFUSED|502|503|504|rate.limit/i.test(errorMsg);
const isValidation = /missing_confidence|missing_react|inconsistent/i.test(warningType);
// Only retry transient errors; fail-fast on validation after 2 attempts
```

**Effort:** Low
**Impact:** Medium — stops wasteful retries, faster resolution

### 5. Instrumented Debug Logging (Zero-Overhead When Disabled)

**gh-aw approach:** Uses DEBUG environment variables with structured category naming (`pkg:filename`). Zero overhead when disabled.

**Our current state:** Scripts use `echo` to stderr for debug output. No structured categories. No way to enable/disable debug per component.

**Recommendation:** Add `DEBUG` env var support to key scripts:
```bash
debug() { [[ -n "${DEBUG:-}" ]] && echo "[DEBUG:$(basename "$0")] $*" >&2; }
```

**Effort:** Low
**Impact:** Low — quality-of-life for debugging production issues

---

## gh-aw Skill Inventory (22 Skills)

| Skill | Relevance to Us |
|-------|-----------------|
| `custom-agents` | Validates our `.claude/agents/*.md` approach |
| `error-recovery-patterns` | **High** — circuit breaker + backoff patterns |
| `error-pattern-safety` | Medium — safe error handling |
| `gh-agent-session` | Validates our session management approach |
| `gh-agent-task` | Similar to our YT issue-driven task model |
| `github-mcp-server` | **High** — toolset-based access pattern |
| `github-issue-query` / `github-pr-query` | Similar to our YT MCP integration |
| `reporting` | Similar to our eval report generation |
| `console-rendering` | Low — CLI-specific |
| `messages` | Medium — message formatting patterns |
| Others (dictation, javascript-refactoring, etc.) | Low — domain-specific |

---

## Key Quotes from gh-aw Documentation

> "Using agentic workflows in your repository requires careful attention to security considerations and careful human supervision, and even then things can still go wrong."

> "Tool names may change between GitHub MCP server versions, but toolsets provide a stable API."

> "Maximum retry limits (standard: 3 attempts) with exponential backoff and fail-fast behavior for non-transient errors."

> "Guardrails, safety and security are foundational."

---

## Summary

Our platform already implements the **core architectural patterns** that GitHub built their agentic workflow system on: human-in-loop approval, tool sandboxing, session lifecycle tracking, MCP integration, markdown-based agent definitions, and transparency via tool call logging.

The main additions from gh-aw are **operational refinements**: circuit breakers for retries, toolset-based permissions, error classification (transient vs non-transient), and compile-time config validation. These are incremental improvements, not fundamental gaps.

**Next review:** Re-check this repo in 3 months for new skills and patterns as gh-aw evolves.
