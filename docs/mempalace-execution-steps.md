# MemPalace Integration — Execution Steps

## Phase 1: Foundation

### Issue 1: Schema Migration — Add transcript and diary tables
**Files:** `schema.sql`, `scripts/migrate-mempalace.sh`

1. Add `session_transcripts` table:
   ```sql
   CREATE TABLE IF NOT EXISTS session_transcripts (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     issue_id TEXT NOT NULL,
     session_id TEXT DEFAULT '',
     chunk_index INTEGER DEFAULT 0,
     role TEXT DEFAULT '',        -- 'user' or 'assistant'
     content TEXT NOT NULL,
     embedding TEXT DEFAULT '',   -- JSON array (nomic-embed-text 768-dim)
     created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
     source_file TEXT DEFAULT ''  -- path to original JSONL
   );
   CREATE INDEX IF NOT EXISTS idx_st_issue ON session_transcripts(issue_id);
   CREATE INDEX IF NOT EXISTS idx_st_session ON session_transcripts(session_id);
   ```

2. Add `agent_diary` table:
   ```sql
   CREATE TABLE IF NOT EXISTS agent_diary (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     agent_name TEXT NOT NULL,
     issue_id TEXT DEFAULT '',
     entry TEXT NOT NULL,
     tags TEXT DEFAULT '',
     embedding TEXT DEFAULT '',
     created_at DATETIME DEFAULT CURRENT_TIMESTAMP
   );
   CREATE INDEX IF NOT EXISTS idx_ad_agent ON agent_diary(agent_name);
   ```

3. Add `valid_until` column to `incident_knowledge`:
   ```sql
   ALTER TABLE incident_knowledge ADD COLUMN valid_until DATETIME DEFAULT NULL;
   ```

4. Write migration script `scripts/migrate-mempalace.sh` that applies idempotently.

### Issue 2: Session Transcript Archival
**Files:** `scripts/archive-session-transcript.py`

1. New script reads JSONL from `/tmp/claude-run-<ISSUE>.jsonl`
2. Parse exchange pairs (user message + assistant response = one chunk)
   - Adapted from MemPalace `convo_miner.py` chunking logic
   - Each chunk: role, content, chunk_index
3. Insert chunks into `session_transcripts` table
4. Generate embeddings via nomic-embed-text (same as incident_knowledge)
5. Archive raw JSONL to `~/session-archives/<ISSUE>.jsonl.gz`
6. Called by Session End workflow after "Populate Knowledge" node

### Issue 3: Stop Hook — Auto-Save Every N Messages
**Files:** `scripts/hooks/mempal-session-save.sh`, `.claude/settings.json`

1. Port MemPalace `mempal_save_hook.sh` pattern:
   - Count user messages in active JSONL transcript
   - Track last save point in `/tmp/mempal-state/<SESSION_ID>_last_save`
   - If exchanges_since_save >= 15: block with structured save prompt
   - Infinite-loop prevention via `stop_hook_active` flag
2. Save prompt instructs Claude to extract: decisions made, commands run, findings, confidence
3. Add to `.claude/settings.json` hooks.Stop array
4. State cleanup on session end

### Issue 4: PreCompact Hook — Emergency Save
**Files:** `scripts/hooks/mempal-precompact.sh`, `.claude/settings.json`

1. Port MemPalace `mempal_precompact_hook.sh` pattern:
   - Always block (no state check — compaction always warrants save)
   - Synchronous transcript archival (ensure memories persist before context shrinks)
   - Prompt instructs: save ALL topics, decisions, findings, code changes
2. Add to `.claude/settings.json` hooks.PreCompact array

## Phase 2: Knowledge

### Issue 5: Temporal Validity on incident_knowledge
**Files:** `scripts/kb-semantic-search.py`, Session End workflow

1. Modify `kb-semantic-search.py`:
   - Add `--invalidate` mode: `kb-semantic-search.py invalidate <hostname> <alert_rule>`
   - Sets `valid_until = NOW()` on matching open entries
   - Search queries filter: `WHERE valid_until IS NULL OR valid_until > datetime('now')`
2. Modify Session End "Populate Knowledge" node:
   - Before inserting new incident_knowledge, check for existing open entries with same hostname + alert_rule
   - If found and resolution differs: set valid_until on old entry, then insert new
   - Pattern from MemPalace `knowledge_graph.py`: `UPDATE SET valid_to=? WHERE subject=? AND predicate=? AND valid_to IS NULL`
3. Add `--as-of` flag to search: query facts valid at a specific date

### Issue 6: Agent Diary Persistence
**Files:** `scripts/agent-diary.py`, sub-agent skill files

1. New script `scripts/agent-diary.py` with 3 modes:
   - `write <agent_name> <entry> [--issue <id>] [--tags <tags>]`
   - `read <agent_name> [--last <n>] [--since <date>]`
   - `embed --backfill` (generate embeddings for entries missing them)
2. Modify sub-agent skills to write diary on completion:
   - triage-researcher: writes key finding + hostname + confidence
   - cisco-asa-specialist: writes VPN/tunnel state observations
   - k8s-diagnostician: writes pod/node failure patterns
   - security-analyst: writes vulnerability patterns
3. Modify Build Prompt to inject last 3 diary entries for the relevant agent when delegating
4. Embedding via nomic-embed-text (same pipeline as incident_knowledge)

## Phase 3: Intelligence

### Issue 7: Layered Token Budget (L0-L3)
**Files:** Runner workflow `claude-gateway-runner.json` (Build Prompt node)

1. Refactor Build Prompt into explicit layers:
   - **L0 Identity** (~100 tokens, always): "You are an infrastructure agent for Example Corp Network. 2 sites (NL, GR), 310 devices, 13 K8s nodes."
   - **L1 Critical Rules** (~300 tokens, always): Top operational rules from feedback memories. Data trust hierarchy. Approval requirements.
   - **L2 Incident Context** (~2000 tokens, conditional): RAG results from incident_knowledge + session_transcripts. Agent diary entries. Capped.
   - **L3 Deep Search** (unlimited, on-demand): Only triggered when L2 confidence < threshold or explicit search needed.
2. Add char caps per layer (configurable in Build Prompt code):
   ```javascript
   const L0_CAP = 400;   // ~100 tokens
   const L1_CAP = 1200;  // ~300 tokens
   const L2_CAP = 8000;  // ~2000 tokens
   const L3_CAP = 0;     // unlimited (on-demand only)
   ```
3. Track injection size in session metrics (new field: `prompt_injection_chars`)

### Issue 8: Transcript as 4th RRF Signal
**Files:** `scripts/kb-semantic-search.py`

1. Add transcript signal to hybrid search:
   - Query `session_transcripts` table with same embedding similarity as incident_knowledge
   - Filter by hostname (extracted from transcript chunks via regex)
   - Weight: 0.3 (vs semantic 1.0, keyword 1.0, wiki 0.5)
2. RRF formula becomes:
   ```
   rrf_score = 1/(k+semantic_rank) + 1/(k+keyword_rank) + 1/(k+wiki_rank) + 1/(k+transcript_rank)
   ```
3. Transcript results formatted as: "Previous session [ISSUE-ID] discussed: <chunk>"
4. Dedup: if same issue_id appears in both incident_knowledge and session_transcripts, prefer incident_knowledge (summarized) over raw transcript

### Issue 9: Contradiction Detection
**Files:** `scripts/wiki-compile.py`

1. Add `--contradictions` flag to wiki-compile.py
2. For each host page, cross-check memory claims against NetBox:
   - Memory says "host on pve01" → NetBox query → actual PVE host
   - Memory says "IP 192.168.x.y" → NetBox query → actual primary IP
   - Memory says "VLAN 10" → NetBox query → actual VLAN assignment
3. Report format in staleness-report.md:
   ```
   | high | contradiction | Memory `xyz.md` claims nl-claude01 on pve01, NetBox says pve03 |
   ```
4. Optional: auto-invalidate contradicted facts (with --fix flag)

## Phase 4: QA

### Issue 10: E2E Testing and Benchmarking
**Files:** `scripts/test-mempalace-integration.sh`

1. **Schema test:** Verify all new tables exist with correct columns
2. **Transcript archival test:**
   - Create synthetic JSONL transcript
   - Run archive-session-transcript.py
   - Verify chunks in session_transcripts table
   - Verify embeddings populated
   - Search and find the transcript
3. **Temporal validity test:**
   - Insert incident_knowledge entry
   - Insert newer entry for same host+rule
   - Verify old entry has valid_until set
   - Search with --as-of past date → find old entry
   - Search without --as-of → find only new entry
4. **Agent diary test:**
   - Write diary entry for triage-researcher
   - Read back last 3 entries
   - Verify embedding populated
5. **RRF integration test:**
   - Search query that matches in both incident_knowledge and session_transcripts
   - Verify 4-signal RRF returns results from both sources
   - Verify dedup (same issue_id not double-counted)
6. **Hook test:**
   - Verify hooks exist and are executable
   - Verify settings.json references them
   - Simulate stop hook with test transcript
7. **Contradiction detection test:**
   - Create memory with known-wrong host assignment
   - Run wiki-compile --contradictions
   - Verify contradiction reported
8. **Regression test:**
   - Run existing kb-semantic-search.py search (hybrid mode)
   - Verify results unchanged (no regression from new 4th signal)
9. **Performance benchmark:**
   - Time: transcript archival for 100-chunk session
   - Time: 4-signal RRF search vs 3-signal
   - Memory: session_transcripts table size after 50 sessions
