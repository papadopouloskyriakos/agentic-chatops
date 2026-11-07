-- Migration 009 — 2026-04-20
-- IFRNLLEI01PRD-640 — handoff_log table for T1 -> T2 escalations + sub-agent spawns.
--
-- One row per escalation or sub-agent spawn event. Audits the envelope size
-- (input_history_bytes), whether IFRNLLEI01PRD-641 compaction ran, and the
-- from/to agent names. Read by holistic-health to assert every escalation
-- has a corresponding log row within 5s of the transition.

CREATE TABLE IF NOT EXISTS handoff_log (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id          TEXT DEFAULT '',
  session_id        TEXT DEFAULT '',
  from_agent        TEXT NOT NULL,
  to_agent          TEXT NOT NULL,
  handoff_depth     INTEGER DEFAULT 0,
  input_history_bytes INTEGER DEFAULT 0,
  compaction_applied INTEGER DEFAULT 0,
  compaction_model  TEXT DEFAULT '',
  pre_handoff_count INTEGER DEFAULT 0,
  new_items_count   INTEGER DEFAULT 0,
  reason            TEXT DEFAULT '',
  handoff_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version    INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_handoff_log_issue   ON handoff_log(issue_id);
CREATE INDEX IF NOT EXISTS idx_handoff_log_at      ON handoff_log(handoff_at);
CREATE INDEX IF NOT EXISTS idx_handoff_log_to      ON handoff_log(to_agent);
CREATE INDEX IF NOT EXISTS idx_handoff_log_schema_v ON handoff_log(schema_version);
