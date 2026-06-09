-- Migration 013 — 2026-04-20
-- IFRNLLEI01PRD-651 — Teacher-agent foundation.
--
-- Adds two tables for the introspective learning module that teaches the
-- operator about agentic systems theory and this system's practice,
-- tracks progress via spaced repetition (SuperMemo-2), and verifies
-- mastery through Bloom's-taxonomy-progressive questioning.
--
--   learning_progress   — per (operator, topic) SM-2 + mastery state
--   learning_sessions   — append-only audit of every lesson / quiz / review
--
-- Reads wiki_articles, docs/system-as-abstract-agent.md, docs/agentic-patterns-
-- audit.md, memory files (no schema change there — curriculum just points at
-- source paths via config/curriculum.json).

CREATE TABLE IF NOT EXISTS learning_progress (
  id                        INTEGER PRIMARY KEY AUTOINCREMENT,
  operator                  TEXT NOT NULL,
  topic                     TEXT NOT NULL,
  mastery_score             REAL DEFAULT 0.0,            -- 0.0 - 1.0
  easiness_factor           REAL DEFAULT 2.5,            -- SM-2, clamped [1.3, 2.8]
  interval_days             INTEGER DEFAULT 1,           -- SM-2
  repetition_count          INTEGER DEFAULT 0,           -- SM-2
  highest_bloom_reached     TEXT DEFAULT 'recall',       -- recall|recognition|explanation|application|analysis|evaluation|teaching_back
  last_reviewed             DATETIME,
  next_due                  DATETIME DEFAULT CURRENT_TIMESTAMP,
  quiz_history              TEXT DEFAULT '[]',           -- JSON [{session_id, score, ts}]
  paused                    INTEGER DEFAULT 0,           -- !learn pause toggle
  needs_review              INTEGER DEFAULT 0,           -- source hash mismatch → flagged
  source_hash               TEXT DEFAULT '',             -- BLAKE2b of concatenated sources at mastery time
  created_at                DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version            INTEGER DEFAULT 1,
  UNIQUE(operator, topic)
);

CREATE INDEX IF NOT EXISTS idx_lp_next_due         ON learning_progress(operator, next_due);
CREATE INDEX IF NOT EXISTS idx_lp_mastery          ON learning_progress(operator, mastery_score);
CREATE INDEX IF NOT EXISTS idx_lp_schema_v         ON learning_progress(schema_version);

CREATE TABLE IF NOT EXISTS learning_sessions (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  operator          TEXT NOT NULL,
  topic             TEXT NOT NULL,
  session_type      TEXT NOT NULL,                       -- lesson|quiz|review|teaching_back
  bloom_level       TEXT,                                -- set for quiz/review/teaching_back
  started_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at      DATETIME,
  quiz_score        REAL,                                -- 0.0-1.0, null until graded
  question_payload  TEXT,                                -- JSON {question_text, source_snippets[], rubric}
  answer_payload    TEXT,                                -- JSON {answer_text, submitted_at}
  judge_feedback    TEXT,                                -- grader prose feedback
  citation_flag     INTEGER DEFAULT 0,                   -- answer referenced non-source material
  schema_version    INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_ls_operator   ON learning_sessions(operator, topic);
CREATE INDEX IF NOT EXISTS idx_ls_started    ON learning_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_ls_schema_v   ON learning_sessions(schema_version);
