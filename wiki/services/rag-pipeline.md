# RAG Pipeline

> 3-channel hybrid retrieval. Compiled 2026-04-11 14:13 UTC.

## Channels

1. **Hybrid Semantic Search (RRF)** — nomic-embed-text 768 dims + keyword LIKE, blended via Reciprocal Rank Fusion
2. **Deterministic Hostname Routing** — claude-knowledge-lookup.sh pattern-matches hostname to CLAUDE.md files
3. **XML-Tagged Injection** — `<incident_knowledge>`, `<lessons_learned>`, `<operational_memory>` tags

### knowledge_injection

## CLAUDE.md + Memory Knowledge Injection (2026-04-06)

Both ChatOps/ChatSecOps tiers now aware of procedural knowledge from repos and Claude memory files.

### What was added
- **claude-knowledge-lookup.sh** — hostname→CLAUDE.md routing (pve/, docker/, network/, k8s/, native/, edge/) + feedback memory extraction. Memories output first (survive 2000-char truncation). Called at Step 2-kb in infra-triage, k8s-triage, correlated-triage.
- **Build Prompt enrichment** — `claudeMdGuidance` (targeted CLAUDE.md file paths per hostname) + `memorySection` (auto-retrieved feedback rules). Query Knowledge extracts `MEMORY_START/END` block.
- **openclaw-repo-sync.sh** — `*/30` cron on nl-openclaw01. Pulls 23 repos + syncs 51 feedback memories (SSH+tar) + gateway.db read replica (scp).

### Architecture
- All CLAUDE.md reads are LOCAL on both hosts (repos synced by cron, max 30min staleness).
- Semantic search (kb-semantic-search.py) runs LOCAL on OpenClaw — Ollama on nl-gpu01 reachable on same VLAN 181 subnet. No SSH for reads.
- SSH to app-user only for WRITES (SQLite inserts, triage.log appends, CodeGraph).
- Docker compose on openclaw01 has bind mounts: `/root/.claude-memory:/home/node/.claude-memory:ro` + `/root/.claude-data:/home/node/.claude-data:ro`.

### Compiled Wiki KB (2026-04-09)
- **wiki-compile.py** — compiles 7+ sources (70 memories, 37 CLAUDE.md, 28 incidents, 7 lessons, 88 openclaw_memory, 23 docs, 19 skills, 5 dashboards, ~5,200 lab files) into 45 wiki articles at `wiki/`.
- **3-signal RRF** — wiki articles embedded in `wiki_articles` SQLite table (45 rows, nomic-embed-text 768 dims). 3rd ranking signal in `kb-semantic-search.py` hybrid search alongside semantic + keyword.
- **Health checks** — `--health` mode detects staleness (line-number rot in memories) + coverage gaps (incidents without lessons).
- **Cadence** — daily 04:30 UTC cron + on-demand `/wiki-compile` skill. Incremental via SHA-256 checksums.
- **Auto-propagation** — wiki/ is in claude-gateway repo → `openclaw-repo-sync.sh` picks it up on OpenClaw within 30min.

### Pattern impact
Memory (8): A→A+ (compiled wiki = organized semantic memory). Learning (9): A→A+ (health checks surface knowledge gaps). RAG (14): A→A+ (3-signal RRF: semantic + keyword + wiki articles).

### Key paths on openclaw01
- Repos: `/root/gitlab/` (23 repos, mirrors app-user)
- Memories: `/root/.claude-memory/{infrastructure-nl,infrastructure-gr,gateway}/`
- DB replica: `/root/.claude-data/gateway.db`
- Sync script: `/root/openclaw-repo-sync.sh`
- Sync log: `/tmp/openclaw-repo-sync.log`
- Cron: `*/30 * * * * /root/openclaw-repo-sync.sh`

### Unified Knowledge Base Wiki

Compiled wiki at `wiki/` in claude-gateway repo (2026-04-09). 45 articles across 8 categories compiled from 7+ knowledge sources.

**Compiler:** `scripts/wiki-compile.py` — source readers for memory files (69), CLAUDE.md (37), SQLite tables (incident_knowledge 28, lessons_learned 7, openclaw_memory 87), docs (22), OpenClaw skills (15), Grafana dashboards (5), 03_Lab manifest (~5,200 files).

**Key features:**
- Incremental compilation via SHA-256 checksums in `wiki/.compile-state.json`
- Health checks: `--health` flag detects staleness (line number refs) + coverage gaps (incidents without lessons)
- RAG integration: wiki articles embedded in `wiki_articles` table (45 rows), 3rd signal in RRF fusion in `kb-semantic-search.py`
- On-demand: `/wiki-compile` skill
- Daily cron: 04:30 UTC (between 04:00 golden-test and 06:03 proactive-scan)

**Highest-value article:** `wiki/operations/operational-rules.md` — all 24 feedback memories compiled by domain (Config Safety, ASA/VPN, K8s, Deployment, Infra Ops, Data Integrity, General).

**Why:** No unified view of knowledge previously existed across 7+ fragmented stores. Inspired by Karpathy's LLM Knowledge Bases pattern.
