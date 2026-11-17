-- 017_infragraph_cascade_stats.sql — IFRNLLEI01PRD-1118
-- Learned per-(parent rule-family -> child) cascade hit-rates, derived from
-- evaluated shadow predictions (infragraph-learn.py --from-cascades). Drives
-- cascade-probability gating in lib.infragraph.expected_cascade():
--   * emit-gate  by (child_host, child rule-FAMILY) probability  -> drops the
--     structural blast-radius that never actually cascades (over-prediction).
--   * per-item confidence  by (child_host, child rule-EXACT) probability  ->
--     the signal the precision_conf08 Phase B->C gate (-1040) consumes.
-- Shadow-only: changes what the predictor RECORDS + its confidence, not what is
-- auto-suppressed. Idempotent full-recompute table.
CREATE TABLE IF NOT EXISTS infragraph_cascade_stats (
  scope          TEXT NOT NULL,            -- 'family' | 'exact'
  parent_family  TEXT NOT NULL,            -- rule-family of the parent alert
  child_host     TEXT NOT NULL,            -- full site-prefixed hostname
  child_key      TEXT NOT NULL,            -- rule-family (family scope) | rule (exact scope)
  seen           INTEGER NOT NULL DEFAULT 0,
  fired          INTEGER NOT NULL DEFAULT 0,
  updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version INTEGER DEFAULT 1,
  PRIMARY KEY (scope, parent_family, child_host, child_key)
);
CREATE INDEX IF NOT EXISTS idx_igcs_lookup
  ON infragraph_cascade_stats(scope, parent_family, child_host, child_key);
