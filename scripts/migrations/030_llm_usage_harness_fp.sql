-- 030_llm_usage_harness_fp.sql — Harness² reuse R3 follow-up
--
-- llm_usage rows (per-session token/cost accounting) get the same harness_fp
-- as sessions / session_log so cost can be grouped by harness version. The
-- column is filled by scripts/stamp-harness-fingerprint.py (by issue_id, the
-- table has no session_id); rows written before 2026-10-22 stay NULL.
-- Numbered 030: 023..029 are taken in schema_migrations (see
-- feedback_migration_prefix_collision_verify_schema).

ALTER TABLE llm_usage ADD COLUMN harness_fp TEXT;
CREATE INDEX IF NOT EXISTS idx_llm_usage_harness_fp ON llm_usage(harness_fp);
