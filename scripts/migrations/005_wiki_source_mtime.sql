-- Migration 005 — 2026-04-18
-- Adds:
--   * wiki_articles.source_mtime (REAL) — Unix mtime of the source file when indexed.
--     Enables temporal retrieval filters like "memory files created in the last 48h"
--     (see IFRNLLEI01PRD-609, H50 meta-query failure class).
--
-- compiled_at already exists but records when the compiler ran, not when the
-- underlying memory/doc was last modified. Those diverge: a daily compiler
-- cron sets compiled_at to "today" even for files that haven't changed in
-- weeks, which defeats "created in last N" queries.
--
-- Idempotency: apply.py catches "duplicate column" so re-runs are safe.

ALTER TABLE wiki_articles ADD COLUMN source_mtime REAL DEFAULT 0;

-- Population: re-run the indexer after migration on a fresh restore:
--   python3 scripts/index-memories.py        -- sets source_mtime = os.path.getmtime(fpath)
