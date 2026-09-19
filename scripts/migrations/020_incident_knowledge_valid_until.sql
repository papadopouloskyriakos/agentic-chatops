-- 020_incident_knowledge_valid_until.sql — schema-drift repair
-- incident_knowledge.valid_until is read/written on the LIVE db as the temporal-KG
-- supersession axis (NULL = still valid; a non-NULL timestamp = this knowledge row was
-- invalidated/superseded and should be excluded from RAG retrieval — see the bi-temporal
-- invalidation work, IFRNLLEI01PRD-1158, and CLAUDE.md "Temporal KG via
-- incident_knowledge.valid_until"). The column was added to the live db directly and was
-- never captured in schema.sql or any migration, so a db rebuilt from schema.sql + the
-- migration chain would LACK it (drift found by the 2026-06-26 orchestrator/dark-component +
-- bi-temporal audits). This migration closes that drift so a fresh rebuild matches live.
-- Additive / backwards-compatible; apply.py tolerates the duplicate-column ALTER on the
-- already-migrated live db.
ALTER TABLE incident_knowledge ADD COLUMN valid_until DATETIME;
CREATE INDEX IF NOT EXISTS idx_ik_valid_until ON incident_knowledge(valid_until);
