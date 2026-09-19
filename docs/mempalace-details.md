# MemPalace Integration (2026-04-09)

Ported 8 high-value patterns from [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace). Local clone at `/app/mempalace/`.

## New Tables (gateway.db)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `session_transcripts` | Verbatim JSONL exchange-pair chunks with embeddings | issue_id, session_id, chunk_index, role, content, embedding |
| `agent_diary` | Persistent per-agent knowledge across sessions | agent_name, issue_id, entry, tags, embedding |

Plus `incident_knowledge.valid_until` column for temporal validity (MemPalace KG pattern).

## New Scripts

| Script | Purpose |
|--------|---------|
| `scripts/archive-session-transcript.py` | Parse JSONL, chunk exchange pairs, insert into session_transcripts, archive to gzip |
| `scripts/agent-diary.py` | write/read/embed/inject modes for sub-agent diaries |
| `scripts/build-prompt-layers.py` | L0-L3 layered injection with token caps (L0: 400, L1: 1200, L2: 8000 chars) |
| `scripts/hooks/mempal-session-save.sh` | Stop hook — auto-save every 15 messages (MemPalace blocking pattern) |
| `scripts/hooks/mempal-precompact.sh` | PreCompact hook — emergency save before context compression |
| `scripts/test-mempalace-integration.sh` | 26-test E2E suite |

## Modified Scripts

- `scripts/kb-semantic-search.py` — added `invalidate` command, 4th RRF signal (session transcripts, weight 0.3), `valid_until` filtering on all queries
- `scripts/wiki-compile.py` — added `--contradictions` flag for NetBox cross-check
- `.claude/settings.json` — added Stop + PreCompact hooks

## RAG Pipeline (now 4-signal RRF)

```
RRF = 1/(k+semantic) + 1/(k+keyword) + 1/(k+wiki) + 0.3/(k+transcript)
```

Transcript signal provides verbatim session context. Lower weight (0.3) vs summarized incident_knowledge (1.0) to avoid noise from raw exchanges. Temporal validity: invalidated entries (`valid_until IS NOT NULL AND valid_until <= now`) excluded from all searches.

## What Was NOT Ported

- **ChromaDB** — redundant with our SQLite + nomic-embed-text stack
- **AAAK compression** — lossy, regresses recall (84.2% vs 96.6% raw), unnecessary with 1M context
- **Palace graph** (wings/rooms/halls/tunnels) — our wiki already provides cross-domain navigation
- **Entity registry** — NetBox CMDB serves this role
- **19-tool MCP server** — n8n workflows handle orchestration
