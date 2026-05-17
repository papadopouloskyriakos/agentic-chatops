# Runbook — CLI-session RAG capture

**YT:** [IFRNLLEI01PRD-646](https://youtrack.example.net/issue/IFRNLLEI01PRD-646)
(Tier 1), [-647](https://youtrack.example.net/issue/IFRNLLEI01PRD-647)
(Tier 2), [-648](https://youtrack.example.net/issue/IFRNLLEI01PRD-648)
(Tier 3).
**Status:** Code on `nl-claude01` since 2026-04-20. **Cron not yet installed
— see "Enable" below.**

## What it is

The agentic Session End workflow writes every YT-backed Claude session into
`session_transcripts`, `tool_call_log`, and `incident_knowledge`. Interactive
**Claude Code CLI** sessions (no YT issue, no n8n webhook trigger) historically
only had cost/token capture via `poll-claude-usage.sh` — their content never
reached RAG.

This pipeline closes that gap. All three tiers share one cron line.

```
┌───────────────────────────────────┐
│  ~/.claude/projects/**/*.jsonl    │  ← Claude Code CLI session files
│  (UUID-named, each = one session) │
└────────────────┬──────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────────────┐
│  scripts/backfill-cli-transcripts.sh  (cron 04:30 UTC daily)   │
│  ├── find JSONLs > 10 KB, minus watermarked unchanged files    │
│  ├── archive-session-transcript.py  (Tier 1, -646)             │
│  │     chunks into exchange pairs → session_transcripts        │
│  │     + doc-chain refine → chunk_index=-1 summary rows        │
│  │     + nomic-embed-text embeddings                           │
│  ├── parse-tool-calls.py            (Tier 3, -648)             │
│  │     extracts tool_use/tool_result pairs → tool_call_log     │
│  │     issue_id = cli-<uuid>, matches session_transcripts      │
│  └── extract-cli-knowledge.py       (Tier 2, -647)             │
│        reads chunk_index=-1 summaries → gemma3:12b strict-JSON │
│        extraction → incident_knowledge with project='chatops-  │
│        cli', embedded via nomic-embed-text                     │
└────────────────────────────────────────────────────────────────┘
                 │
                 ▼
         kb-semantic-search.py retrieves all 3 alongside wiki/infra rows.
         CLI_INCIDENT_WEIGHT (default 0.75) discounts chatops-cli rows so
         real infra incidents still win ranking ties.
```

## Enable

Add the cron line on `nl-claude01` as `app-user`:

```cron
# CLI-session RAG capture (IFRNLLEI01PRD-646/-647/-648).
30 4 * * * /app/claude-gateway/scripts/backfill-cli-transcripts.sh --embed --oldest-first --limit 50 >> /home/app-user/logs/claude-gateway/cli-transcript-backfill.log 2>&1
```

Why 04:30: the gateway DB backup runs at 02:00 UTC and usually finishes in
under 5 minutes. `poll-claude-usage.sh` runs at :00 and :30 past every hour;
04:30 avoids overlapping with it so the two-process SQLite contention stays
bounded.

The initial backlog is ~2,300 CLI JSONLs. At 50/night it drains in ~46 days.
To drain faster, raise `--limit` or temporarily run the script by hand with
higher caps.

## Observe

```bash
# Drain progress
sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db "
  SELECT 'distinct_cli_sessions', COUNT(DISTINCT issue_id) FROM session_transcripts WHERE issue_id LIKE 'cli-%'
  UNION ALL SELECT 'cli_chunks',         COUNT(*)          FROM session_transcripts WHERE issue_id LIKE 'cli-%'
  UNION ALL SELECT 'cli_summaries',      COUNT(*)          FROM session_transcripts WHERE issue_id LIKE 'cli-%' AND chunk_index=-1
  UNION ALL SELECT 'cli_tool_calls',     COUNT(*)          FROM tool_call_log       WHERE issue_id LIKE 'cli-%'
  UNION ALL SELECT 'cli_incident_rows',  COUNT(*)          FROM incident_knowledge  WHERE project='chatops-cli';"

# Parse-tool-calls global stats (includes CLI sessions):
cd scripts && python3 parse-tool-calls.py --stats

# Run-log tail (last drain):
tail -80 ~/logs/claude-gateway/cli-transcript-backfill.log
```

## Run by hand

```bash
# Drain up to N files, embed, oldest-first (cron-equivalent):
scripts/backfill-cli-transcripts.sh --embed --oldest-first --limit 50

# Fast dev iteration (no embed, no tool-calls, no Tier 2, newest first):
scripts/backfill-cli-transcripts.sh --no-embed --no-toolcalls --newest-first --limit 5

# Force re-process (ignore watermark) — useful after changing the chunker:
scripts/backfill-cli-transcripts.sh --no-watermark --limit 20
```

## Tuning

| Env / flag | Default | Effect |
|---|---|---|
| `CLI_INCIDENT_WEIGHT` | `0.75` | Multiplicative discount on chatops-cli rows at retrieval time. `1.0` = no discount, `0.0` = suppress. |
| `CLI_KB_MODEL` | `gemma3:12b` | Local Ollama model for extraction. Set to `qwen2.5:14b-instruct` to try heavier reasoning. |
| `--limit N` | 50 | Max files touched per run. Raise to drain backlog faster. |
| `HANDOFF_COMPACT_MODEL` | `gemma3:12b` | Unrelated — lives here because both use the same Ollama backend. |

## Rollback

If CLI rows start polluting retrieval despite the discount, stop the cron and
mark existing CLI knowledge inactive without deleting audit trail:

```bash
# 1. Disable the cron (comment the line in `crontab -e`).

# 2. Suppress chatops-cli rows from retrieval entirely:
export CLI_INCIDENT_WEIGHT=0.0
# or permanently in /home/app-user/.env for the scripts that read it.

# 3. Hard-delete if really needed (session_transcripts stays as audit):
sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db "
  DELETE FROM incident_knowledge WHERE project='chatops-cli';"
```

## Troubleshooting

**`[archive] database is locked`**
Another SQLite writer is long-running. The archive step holds a write lock
for a few seconds while inserting chunks. Common culprits:
```bash
ps -eo pid,etime,comm,args | grep -E 'gateway|archive-session|classify-session|write-session' | grep -v grep
```
If you see a stuck `archive-session-transcript.py` that's been running for
hours (usually embedding a 100 MB+ JSONL), `kill -9` it and retry the backfill.
The chunker is idempotent on `chunk_index` so restarts don't double-insert.

**`[extract] rag_synth_ollama breaker OPEN — skipping run`**
gemma3:12b at `nl-gpu01:11434` failed 4 times in a row. The breaker
probes every 120s. Wait, or force reset:
```bash
cd scripts && python3 -m lib.circuit_breaker reset rag_synth_ollama
```

**`[summary] session ... too short — skip refine`**
The assistant-only content was under 5000 chars; doc-chain refine is skipped.
Those sessions have no chunk_index=-1 summary, so Tier 2 won't produce an
`incident_knowledge` row for them. This is intentional — short sessions
rarely carry reusable knowledge.

**Gemma extraction returns `confidence: 0.5, subsystem: ''` a lot**
The summary itself was thin. Compare `LENGTH(content)` in session_transcripts
for the affected issue_id — if < 200 chars, the session wasn't substantive
enough. Don't manually edit extracted rows; let the confidence field do its
job (retrieval already factors it in).

**Retrieval is missing chatops-cli rows even though they exist**
Check `CLI_INCIDENT_WEIGHT` isn't set to 0. Also verify the row has an
embedding:
```bash
sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db "
  SELECT issue_id, LENGTH(embedding) FROM incident_knowledge
  WHERE project='chatops-cli' ORDER BY id DESC LIMIT 5;"
```
Length should be ~10260 (768-dim float32 JSON). Zero means the embed step
failed — usually transient Ollama stall. Re-running `extract-cli-knowledge.py`
(without `--issue`) will leave existing rows alone; delete the affected row
and re-extract if needed.

## Related

- Memory: [`cli_session_rag_capture.md`](../../.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory/cli_session_rag_capture.md).
- QA suite: [`scripts/qa/suites/test-646-cli-session-rag-capture.sh`](../../scripts/qa/suites/test-646-cli-session-rag-capture.sh)
  — 12 tests, all PASS.
- Tier 2 uses the same local-first synth backend as the rest of the RAG
  stack. See [`docs/judge-calibration-2026-04-19.md`](../judge-calibration-2026-04-19.md).
