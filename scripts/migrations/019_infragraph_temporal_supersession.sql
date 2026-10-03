-- 019_infragraph_temporal_supersession.sql — IFRNLLEI01PRD-1158
-- Bi-temporal edge invalidation on infragraph_dynamics (Zep/Graphiti pattern).
-- valid_until (already present) = TTL expiry of seeded edges. These add the
-- contradiction/supersession axis:
--   invalid_at        — a NEWER observation/contradiction superseded this edge
--                       (NULL = still valid). Distinct from TTL expiry.
--   superseded_by     — rel_id of the edge that replaced this one (chain root).
--   last_confirmation — last time an incident/chaos run re-confirmed the edge;
--                       drives REPORTING-ONLY decay (decayed edges are flagged for
--                       re-ratification, never auto-suppressed). NULL = use
--                       last_validated/updated_at.
-- Additive / backwards-compatible; apply.py tolerates the duplicate-column ALTER.
ALTER TABLE infragraph_dynamics ADD COLUMN invalid_at DATETIME;
ALTER TABLE infragraph_dynamics ADD COLUMN superseded_by INTEGER;
ALTER TABLE infragraph_dynamics ADD COLUMN last_confirmation DATETIME;
CREATE INDEX IF NOT EXISTS idx_igd_invalid ON infragraph_dynamics(invalid_at);
