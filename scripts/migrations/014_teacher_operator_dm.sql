-- Migration 014 — 2026-04-20
-- IFRNLLEI01PRD-653 — Teacher-agent interface tier.
--
-- Adds the operator-DM mapping table used by the multi-user classroom design:
-- members of #learning room are authorised; the bot DMs each operator
-- individually for lessons / quizzes / private progress. public_sharing flag
-- is per-operator opt-in; default off so progress stays private.

CREATE TABLE IF NOT EXISTS teacher_operator_dm (
  operator_mxid     TEXT PRIMARY KEY,        -- e.g. @kyriakos:matrix.example.net
  dm_room_id        TEXT NOT NULL,           -- !xxxxxx:matrix.example.net
  display_name      TEXT DEFAULT '',
  public_sharing    INTEGER DEFAULT 0,       -- opt-in for !progress-public / leaderboard
  first_seen        DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_active       DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version    INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_tod_last_active ON teacher_operator_dm(last_active);
CREATE INDEX IF NOT EXISTS idx_tod_public      ON teacher_operator_dm(public_sharing);
CREATE INDEX IF NOT EXISTS idx_tod_schema_v    ON teacher_operator_dm(schema_version);
