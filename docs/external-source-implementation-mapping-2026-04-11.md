# External Source Advice vs Implementation — Mapping Report

**Date:** 2026-04-11
**Sources:** github.com/agulli/atlas-agents + github.com/alejandrobalderas/claude-code-from-source
**Scope:** 16 techniques identified, mapped against all implementations from this session

---

## Source 1: atlas-agents (Gulli)

| # | Advice | Status | What Was Implemented | Evidence |
|---|--------|--------|---------------------|----------|
| A1 | Declarative Skills as Execution Templates | Not implemented | Remains procedural scripts | Deferred — architectural change |
| A2 | Multi-Persona Router (cheap classifier) | Not implemented | Routing remains prefix-based | Deferred — Runner restructuring |
| A3 | Plan-and-Execute 3-Phase | Not implemented | Would reduce context by 30-40% | Deferred — significant arch change |
| **A4** | **Prompt Injection Detection (Regex-First)** | **Implemented** | 7 injection pattern groups in unified-guard.sh | Encoding, role confusion, delimiters, social eng, exfiltration |
| A5 | Chain of Density Prompting | Not implemented | Session End still single-density | Deferred |
| **A6** | **Structural A/B Testing Harness** | **Partial** | prompt_scorecard 302 rows, eval-flywheel Phase 3 | Automated weekly promotion missing |

## Source 2: claude-code-from-source (Balderas)

| # | Advice | Status | What Was Implemented | Evidence |
|---|--------|--------|---------------------|----------|
| B1 | Four-Layer Context Compression | Not implemented | No token budgeting in Build Prompt | Deferred |
| B2 | Fork Agents for Cache Sharing | Not implemented | Sub-agents spawned independently | Requires SDK changes |
| B3 | Sticky Latches for Cache Stability | Not implemented | No session-level latches | Deferred |
| B4 | Slot Reservation (8K/64K) | Not implemented | No --max-tokens flag | Deferred |
| **B5** | **14-Step Tool Execution Pipeline** | **Partial** | PreToolUse hooks (steps 7-8) + tool_call_log (88K rows, steps 10-12) | PostToolUse hooks missing |
| B6 | Self-Describing Tools | Not implemented | tool-profiles.json exists but tools don't self-describe | Deferred |
| **B7** | **Staleness Warnings on Memory** | **Implemented** | staleness_warning() in kb-semantic-search.py, 3 output paths | >7d verify, >30d outdated warning |
| B8 | BoundedUUIDSet for Dedup | Not implemented | TTL-based file persistence dedup still used | Optimization |
| B9 | Failure-Type-Proportional Reconnection | Not implemented | Bridge uses uniform maxTries:3 | Deferred |
| B10 | AsyncGenerator Loop | Not implemented | SSH fire-and-poll pattern | Fundamental arch change |

## Score: 2 fully + 2 partially = 4/16 (25%)

## Implementations Influenced By (Not Direct)

| Implementation | Inspired By | Relationship |
|---------------|-------------|-------------|
| GraphRAG query_graph() | B6 | Structured metadata querying |
| Quality-based RRF weighting | B1 | Quality-aware signal weighting |
| Dev judgment rubric | A6 | Variant evaluation rubrics |
| Agent diary backfill (55 entries) | A1 | Per-agent knowledge capture |
| Tool error Prometheus metrics | B5 | Retroactive tool observability |
| trace_id on sessions | B10 | First step toward state visibility |
| Credential rotation tracking | B5 | Credential lifecycle awareness |

## Remaining High-Impact (Recommended Next)

1. **A2** Multi-Persona Router — content-based routing
2. **A3** Plan-and-Execute — 30-40% context savings
3. **B4** Slot Reservation — simplest win, 12-28% context recovery
4. **B1** Context Compression — token budgeting in Build Prompt
