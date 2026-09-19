-- Migration 011 — 2026-04-20
-- IFRNLLEI01PRD-636 — Immutable per-turn session state snapshots.
--
-- One row captured BEFORE each tool execution by the PreToolUse hook.
-- Mirrors OpenAI Agents SDK `RunState` semantics: an immutable, versioned
-- snapshot used for crash-mid-tool rollback.
--
-- Retention: pruned by cron 7 days after session_log.ended_at (see
-- scripts/prune-snapshots.sh).

CREATE TABLE IF NOT EXISTS session_state_snapshot (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id          TEXT NOT NULL,
  session_id        TEXT DEFAULT '',
  turn_id           INTEGER DEFAULT -1,
  snapshot_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
  pending_tool      TEXT DEFAULT '',     -- tool_name about to run
  pending_tool_input TEXT DEFAULT '{}',   -- tool_input JSON blob
  snapshot_data     TEXT NOT NULL,        -- full JSON snapshot of captured fields
  snapshot_bytes    INTEGER DEFAULT 0,
  schema_version    INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_issue   ON session_state_snapshot(issue_id);
CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_session ON session_state_snapshot(session_id);
CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_at      ON session_state_snapshot(snapshot_at);
CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_schema_v ON session_state_snapshot(schema_version);
