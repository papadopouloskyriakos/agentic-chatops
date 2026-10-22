-- Migration 010 — 2026-04-20
-- IFRNLLEI01PRD-638 — Per-turn session metrics table.
--
-- One row per Claude turn. Populated in real time by the PostToolUse /
-- Stop / SessionEnd hooks. Enables per-turn cost tracking, latency
-- histograms, and early cost-ceiling enforcement without re-parsing JSONL.

CREATE TABLE IF NOT EXISTS session_turns (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id          TEXT DEFAULT '',
  session_id        TEXT DEFAULT '',
  turn_id           INTEGER NOT NULL,
  started_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at          DATETIME,
  llm_cost_usd      REAL DEFAULT 0,
  input_tokens      INTEGER DEFAULT 0,
  output_tokens     INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  tool_count        INTEGER DEFAULT 0,
  tool_errors       INTEGER DEFAULT 0,
  duration_ms       INTEGER DEFAULT -1,
  schema_version    INTEGER DEFAULT 1,
  UNIQUE(session_id, turn_id)
);

CREATE INDEX IF NOT EXISTS idx_session_turns_issue    ON session_turns(issue_id);
CREATE INDEX IF NOT EXISTS idx_session_turns_session  ON session_turns(session_id);
CREATE INDEX IF NOT EXISTS idx_session_turns_started  ON session_turns(started_at);
CREATE INDEX IF NOT EXISTS idx_session_turns_schema_v ON session_turns(schema_version);
