# Compiled Knowledge Base (Karpathy-Style Wiki)

[Karpathy-style](https://x.com/karpathy/status/2039805659525644595) LLM-compiled wiki at `wiki/` — 45 articles auto-compiled from 7+ fragmented knowledge sources into a unified, browsable markdown knowledge base.

## Compiler

`scripts/wiki-compile.py` — reads all sources, compiles articles, uses SHA-256 checksums for incremental recompilation. Daily cron at 04:30 UTC + on-demand via `/wiki-compile` skill.

## Sources → Articles

| Source | Count | Compiled Into |
|--------|-------|---------------|
| Memory files (feedback) | 24 | `wiki/operations/operational-rules.md` (categorized by domain) |
| Memory files (project) | 45+ | `wiki/decisions/index.md` + cross-referenced in host pages |
| CLAUDE.md files | 37 | `wiki/topology/` + `wiki/hosts/` (per-host pages merge 5+ sources) |
| incident_knowledge | 28 | `wiki/incidents/index.md` (chronological timeline) |
| lessons_learned | 7 | Linked in incident timeline + host pages |
| openclaw_memory | 88 | `wiki/services/openclaw.md` (categorized entries) |
| OpenClaw skills | 15 | `wiki/operations/runbooks.md` (usage + docstrings) |
| docs/*.md | 23 | Linked from relevant articles |
| 03_Lab | ~5,200 | `wiki/lab/index.md` (manifest only, no content copied) |
| Grafana dashboards | 5 | `wiki/health/coverage-matrix.md` |

## RAG Integration

All 45 articles embedded via nomic-embed-text into `wiki_articles` SQLite table. Serves as 3rd signal in `kb-semantic-search.py` Reciprocal Rank Fusion (semantic + keyword + wiki). Embeddings auto-refreshed after each compilation.

## Health Checks

`wiki-compile.py --health` detects staleness (memory files with rotated line-number references) and coverage gaps (incidents without lessons_learned entries).

## CLI

```bash
wiki-compile.py                              # Incremental (only changed sources)
wiki-compile.py --full                       # Force full recompilation
wiki-compile.py --article hosts/nl-fw01.md  # Single article
wiki-compile.py --health                     # Health report only
wiki-compile.py --dry-run                    # Show what would compile
```
