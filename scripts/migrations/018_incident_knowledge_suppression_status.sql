-- 018_incident_knowledge_suppression_status.sql — IFRNLLEI01PRD-1153
-- Governance: explicit suppression lifecycle on incident_knowledge so a pattern
-- demoted to analysis-only (recurs >=3x in 30d, or a confirmed false-auto-resolve)
-- is recorded as STATE, not inferred from valid_until. Mirrors the manual
-- InfragraphPrecisionDrop row-1452 demotion. Additive / backwards-compatible;
-- apply.py tolerates the duplicate-column ALTER on re-run (idempotent).
ALTER TABLE incident_knowledge ADD COLUMN suppression_status TEXT DEFAULT 'open';
ALTER TABLE incident_knowledge ADD COLUMN demotion_reason TEXT DEFAULT '';
ALTER TABLE incident_knowledge ADD COLUMN demotion_at DATETIME;
