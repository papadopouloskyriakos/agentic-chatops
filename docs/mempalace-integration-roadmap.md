# MemPalace Integration Roadmap

> Porting high-value patterns from MemPalace (milla-jovovich/mempalace) to the claude-gateway ChatOps platform.

## Context

The April 9 system audit identified 5 critical gaps in knowledge persistence. Independently, MemPalace demonstrates patterns that directly address these gaps — specifically verbatim session storage (96.6% LongMemEval recall), auto-save hooks, temporal knowledge graphs, and agent diary persistence. This roadmap ports the patterns that improve our system without introducing unnecessary complexity.

## Design Principles

1. **Store everything, make it findable** — MemPalace's core insight. Our system currently loses session transcripts, intermediate reasoning, and failed attempts. Fix that.
2. **No new infrastructure** — We already have SQLite + nomic-embed-text + Ollama. Use those, not ChromaDB. MemPalace's patterns are portable; its specific dependencies are not needed.
3. **Additive, not disruptive** — Every change must be backward-compatible. Existing workflows, RAG pipeline, and evaluation systems continue working during rollout.
4. **Token budget awareness** — MemPalace's L0-L3 layered loading is elegant. Formalize our injection into explicit layers with caps.

## What We're Porting

| # | MemPalace Pattern | Our Implementation | Source File |
|---|---|---|---|
| 1 | Verbatim transcript storage in ChromaDB | `session_transcripts` SQLite table with embeddings, 4th RRF signal | `convo_miner.py` chunking |
| 2 | Stop hook (auto-save every N messages) | `hooks/mempal-session-save.sh` in `.claude/settings.json` | `hooks/mempal_save_hook.sh` |
| 3 | PreCompact hook (emergency save) | `hooks/mempal-precompact.sh` in `.claude/settings.json` | `hooks/mempal_precompact_hook.sh` |
| 4 | Temporal KG with valid_from/valid_until | `valid_until` column on `incident_knowledge` + invalidation | `knowledge_graph.py` |
| 5 | Agent diaries | `agent_diary` SQLite table + sub-agent read/write | `mcp_server.py` diary tools |
| 6 | Layered memory stack (L0-L3) | Refactored Build Prompt with explicit token caps | `layers.py` |
| 7 | Contradiction detection | NetBox cross-check in wiki-compile --health | `fact_checker.py` concept |

## What We're NOT Porting

| Pattern | Reason |
|---|---|
| ChromaDB | We use SQLite + nomic-embed-text. Adding ChromaDB creates a redundant vector store. |
| AAAK compression | Lossy, regresses recall (84.2% vs 96.6%). Our 1M context window makes compression unnecessary. |
| Palace graph (wings/rooms/halls/tunnels) | Our wiki already provides cross-domain navigation. Adding palace-style navigation is redundant. |
| Room detection | Our hostname + alert_rule filtering achieves the same effect as wing+room metadata filtering. |
| Entity registry | Our NetBox CMDB already serves as the entity registry for infrastructure objects. |
| MCP server (19 tools) | Our n8n workflows handle the orchestration. MCP tools are for personal AI use, not workflow automation. |

## Timeline

| Phase | Issues | Duration | Dependencies |
|---|---|---|---|
| **Phase 1: Foundation** | Schema migration, transcript archival, hooks | 1 session | None |
| **Phase 2: Knowledge** | Temporal validity, agent diaries | 1 session | Phase 1 |
| **Phase 3: Intelligence** | Layered injection, contradiction detection, RRF integration | 1 session | Phase 2 |
| **Phase 4: QA** | E2E testing, benchmarking, bug fixes | 1 session | Phase 3 |

## Success Criteria

- [ ] Session transcripts persisted with embeddings after every session
- [ ] Stop hook fires and captures mid-session knowledge every 15 messages
- [ ] PreCompact hook saves emergency context before compression
- [ ] `valid_until` enables temporal queries on incident_knowledge
- [ ] Sub-agents accumulate knowledge across invocations via diary
- [ ] Build Prompt injection follows explicit L0-L3 layering with token caps
- [ ] Contradiction detection flags memory vs live-device conflicts
- [ ] 4th RRF signal (transcripts) integrated and searchable
- [ ] All 37 scripts pass syntax validation
- [ ] No regression in existing RAG pipeline (kb-semantic-search.py)
- [ ] E2E test: create session → save transcript → search transcript → find result
