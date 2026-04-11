# RAG Pipeline

> 3-channel hybrid retrieval. Compiled 2026-04-09 06:19 UTC.

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

### Pattern impact
Memory (8): A→A+, Learning (9): A→A+, RAG (14): A→A+ (2 channels: semantic + deterministic hostname-routed).

### Key paths on openclaw01
- Repos: `/root/gitlab/` (23 repos, mirrors app-user)
- Memories: `/root/.claude-memory/{infrastructure-nl,infrastructure-gr,gateway}/`
- DB replica: `/root/.claude-data/gateway.db`
- Sync script: `/root/openclaw-repo-sync.sh`
- Sync log: `/tmp/openclaw-repo-sync.log`
- Cron: `*/30 * * * * /root/openclaw-repo-sync.sh`
