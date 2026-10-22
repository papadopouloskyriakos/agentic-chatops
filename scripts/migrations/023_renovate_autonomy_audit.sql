-- 023_renovate_autonomy_audit.sql
-- Renovate MR Autonomy lane (IFRNLLEI01PRD-1645, 2026-07-06): per-MR triage decision audit.
-- One row per renovate-mr-gate.sh evaluation (SKIP / AUTO / POLL), including shadow-mode runs.
-- Idempotent — renovate-mr-gate.sh also CREATE TABLE IF NOT EXISTS on first run so it works
-- against an isolated mktemp test DB.
CREATE TABLE IF NOT EXISTS renovate_autonomy_audit (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  ts                INTEGER,
  project_id        TEXT,
  mr_iid            TEXT,
  mr_title          TEXT,
  package_update    TEXT,     -- "<package>:<update_type>"
  tier              TEXT,     -- routine | elevated | critical
  snapshot_required TEXT,     -- "true" | "false"
  ci_status         TEXT,     -- GitLab pipeline status of the MR head
  review_verdict    TEXT,     -- APPROVE | REQUEST_CHANGES | NEEDS_DISCUSSION | UNKNOWN
  review_confidence REAL,
  decision          TEXT,     -- SKIP | AUTO | POLL
  reason            TEXT,     -- skip reason, when decision=SKIP
  mode              TEXT,     -- shadow | live
  gates_json        TEXT,     -- {ci_green, review_approve, snapshot_verified, ...}
  schema_version    INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_renovate_audit_mr ON renovate_autonomy_audit(project_id, mr_iid);
CREATE INDEX IF NOT EXISTS idx_renovate_audit_ts ON renovate_autonomy_audit(ts);
