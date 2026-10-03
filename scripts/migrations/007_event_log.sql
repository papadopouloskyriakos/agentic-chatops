-- Migration 007 — 2026-04-20
-- IFRNLLEI01PRD-637 — Typed session event taxonomy + event_log table.
--
-- Creates the event_log table that backs `scripts/lib/session_events.py`.
-- Replaces free-form Matrix progress strings with a typed stream that
-- Grafana can aggregate by event_type + session + turn.
--
-- Reference: OpenAI Agents SDK `src/agents/stream_events.py` —
--   11 typed RunItemStreamEvent subtypes (tool_called, tool_output,
--   handoff_requested, reasoning_item_created, mcp_approval_*, …).
--
-- Idempotency: apply.py catches "already exists" on the CREATE TABLE.

CREATE TABLE IF NOT EXISTS event_log (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  emitted_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
  issue_id         TEXT DEFAULT '',
  session_id       TEXT DEFAULT '',
  turn_id          INTEGER DEFAULT -1,
  agent_name       TEXT DEFAULT '',
  event_type       TEXT NOT NULL,
  payload_json     TEXT NOT NULL DEFAULT '{}',
  duration_ms      INTEGER DEFAULT -1,
  exit_code        INTEGER DEFAULT 0,
  schema_version   INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_event_log_issue     ON event_log(issue_id);
CREATE INDEX IF NOT EXISTS idx_event_log_session   ON event_log(session_id);
CREATE INDEX IF NOT EXISTS idx_event_log_type      ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_log_emitted   ON event_log(emitted_at);
CREATE INDEX IF NOT EXISTS idx_event_log_schema_v  ON event_log(schema_version);

-- Composite index for "all events for this session, in order" — the common
-- Grafana query pattern when drilling into a single session timeline.
CREATE INDEX IF NOT EXISTS idx_event_log_session_emitted ON event_log(session_id, emitted_at);
