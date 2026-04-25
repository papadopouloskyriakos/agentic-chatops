-- Migration 004 — 2026-04-18
-- Adds:
--   * wiki_articles.content_preview (TEXT) — first 1200 chars of the source file,
--     used by the cross-encoder reranker to score actual content instead of title-only
--   * chaos_experiments.embedding (TEXT) — JSON-serialized nomic-embed-text vector
--
-- Applied live via ALTER TABLE this session (2026-04-17/18). This file codifies
-- the schema so a DB restore from backup picks up the columns.
--
-- Idempotency: the apply.py runner catches sqlite3.OperationalError for
-- "duplicate column" so re-running is safe.

ALTER TABLE wiki_articles ADD COLUMN content_preview TEXT DEFAULT '';
ALTER TABLE chaos_experiments ADD COLUMN embedding TEXT DEFAULT '';

-- Population (run after this migration on a fresh restore):
--   python3 scripts/index-memories.py                                       -- wiki_articles.content_preview
--   python3 scripts/migrate-embeddings.py --table chaos_experiments --apply -- chaos_experiments.embedding
