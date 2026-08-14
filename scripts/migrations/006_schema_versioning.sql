-- Migration 006 — 2026-04-20
-- IFRNLLEI01PRD-635 — Schema versioning on SQLite session tables.
--
-- Adds a per-row schema_version INTEGER stamp to the 9 session-and-audit tables
-- that take structured payloads (session_transcripts.content, execution_log.pre_state,
-- agent_diary.entry, session_trajectory.*, session_judgment.*, etc.).
--
-- Reference: OpenAI Agents SDK `src/agents/run_state.py:131`
--   CURRENT_SCHEMA_VERSION = "1.9" + SCHEMA_VERSION_SUMMARIES dict — forward-compat
--   fail-fast on unknown versions. We adopt the same discipline so writer/reader
--   shape drift is caught instead of silently corrupting session replay.
--
-- Canonical registry: scripts/lib/schema_version.py (CURRENT_SCHEMA_VERSION dict).
-- Every writer must stamp schema_version=CURRENT on INSERT; readers fail-fast on
-- row.schema_version > CURRENT (the row was written by a newer writer than us).
--
-- Idempotency: apply.py catches "duplicate column" so re-runs are safe. The
-- session_risk_audit table is lazy-created by scripts/classify-session-risk.py
-- and scripts/audit-risk-decisions.sh — their CREATE TABLE statements are also
-- updated in the same change set so fresh installs get the column natively.

ALTER TABLE sessions            ADD COLUMN schema_version INTEGER DEFAULT 1;
ALTER TABLE session_log         ADD COLUMN schema_version INTEGER DEFAULT 1;
ALTER TABLE session_transcripts ADD COLUMN schema_version INTEGER DEFAULT 1;
ALTER TABLE execution_log       ADD COLUMN schema_version INTEGER DEFAULT 1;
ALTER TABLE tool_call_log       ADD COLUMN schema_version INTEGER DEFAULT 1;
ALTER TABLE agent_diary         ADD COLUMN schema_version INTEGER DEFAULT 1;
ALTER TABLE session_trajectory  ADD COLUMN schema_version INTEGER DEFAULT 1;
ALTER TABLE session_judgment    ADD COLUMN schema_version INTEGER DEFAULT 1;

-- session_risk_audit is lazy-created by classify-session-risk.py on first run.
-- If this migration runs before the first classification (e.g. fresh restore),
-- the ALTER would fail with "no such table". We ensure the table exists first,
-- then add the column. Both are idempotent.

CREATE TABLE IF NOT EXISTS session_risk_audit (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id          TEXT NOT NULL,
    classified_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    alert_category    TEXT,
    risk_level        TEXT NOT NULL,
    auto_approved     INTEGER NOT NULL DEFAULT 0,
    signals_json      TEXT,
    plan_hash         TEXT,
    operator_override TEXT
);

ALTER TABLE session_risk_audit ADD COLUMN schema_version INTEGER DEFAULT 1;

-- Indices for holistic-health assertion queries. Keeps "COUNT rows with
-- schema_version IS NULL" scans cheap even as tables grow.
CREATE INDEX IF NOT EXISTS idx_sessions_schema_v            ON sessions(schema_version);
CREATE INDEX IF NOT EXISTS idx_session_log_schema_v         ON session_log(schema_version);
CREATE INDEX IF NOT EXISTS idx_session_transcripts_schema_v ON session_transcripts(schema_version);
CREATE INDEX IF NOT EXISTS idx_execution_log_schema_v       ON execution_log(schema_version);
CREATE INDEX IF NOT EXISTS idx_tool_call_log_schema_v       ON tool_call_log(schema_version);
CREATE INDEX IF NOT EXISTS idx_agent_diary_schema_v         ON agent_diary(schema_version);
CREATE INDEX IF NOT EXISTS idx_session_trajectory_schema_v  ON session_trajectory(schema_version);
CREATE INDEX IF NOT EXISTS idx_session_judgment_schema_v    ON session_judgment(schema_version);
CREATE INDEX IF NOT EXISTS idx_session_risk_audit_schema_v  ON session_risk_audit(schema_version);

-- Backfill existing rows: DEFAULT 1 only applies to new rows on some older
-- SQLite builds when adding NOT NULL columns. We left the column NULL-able
-- with DEFAULT 1 so existing rows auto-fill to 1 on SELECT. The UPDATE below
-- makes that explicit so readers don't have to handle NULL.
UPDATE sessions            SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE session_log         SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE session_transcripts SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE execution_log       SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE tool_call_log       SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE agent_diary         SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE session_trajectory  SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE session_judgment    SET schema_version = 1 WHERE schema_version IS NULL;
UPDATE session_risk_audit  SET schema_version = 1 WHERE schema_version IS NULL;
