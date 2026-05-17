-- Migration 012 — 2026-04-20
-- IFRNLLEI01PRD-645 — Preference-iterating prompt patcher.
--
-- Replaces the single-shot prompt-improver flow with a trial/A-B framework
-- that generates N candidate patches per low-scoring (surface, dimension)
-- pair, assigns each future matching session to one arm (incl. a control
-- "no patch" arm) via a deterministic hash, collects per-arm judge scores,
-- and promotes the winner only when it beats baseline by a statistical
-- threshold.
--
-- Two tables:
--   prompt_patch_trial         — one row per trial, holds candidates_json
--   session_trial_assignment   — one row per (session, trial) — records the
--                                 variant_idx assigned at Build Prompt time
--
-- Finalizer (scripts/finalize-prompt-trials.py) walks active trials, joins
-- assignments to session_judgment for the target dimension, computes arm
-- means + t-test vs baseline, promotes or aborts.

CREATE TABLE IF NOT EXISTS prompt_patch_trial (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  surface            TEXT NOT NULL,         -- which prompt surface (e.g. 'infra-triage', 'build-prompt')
  dimension          TEXT NOT NULL,         -- judged dimension ('investigation_quality', ...)
  generated_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
  trial_ends_at      DATETIME,              -- abort if trial still active after this
  status             TEXT NOT NULL DEFAULT 'active',  -- active | completed | aborted_no_winner | aborted_timeout
  baseline_mean      REAL NOT NULL,         -- dim score before the trial started
  baseline_samples   INTEGER NOT NULL DEFAULT 0,
  candidates_json    TEXT NOT NULL,         -- [{idx, label, instruction, category}, ...]
  min_samples_per_arm INTEGER NOT NULL DEFAULT 15,
  min_lift           REAL NOT NULL DEFAULT 0.05,
  winner_idx         INTEGER,               -- set on finalize; -1 = control kept (no patch)
  winner_mean        REAL,
  winner_p_value     REAL,
  finalized_at       DATETIME,
  note               TEXT DEFAULT '',
  schema_version     INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_status    ON prompt_patch_trial(status);
CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_surface   ON prompt_patch_trial(surface);
CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_ends_at   ON prompt_patch_trial(trial_ends_at);
CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_schema_v  ON prompt_patch_trial(schema_version);

-- Ensures we never run two active trials for the same (surface, dimension)
-- simultaneously — otherwise Build Prompt assignments would need to choose
-- between them and arm counts stop being comparable.
CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_patch_trial_active
  ON prompt_patch_trial(surface, dimension)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS session_trial_assignment (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id         TEXT NOT NULL,
  session_id       TEXT DEFAULT '',
  trial_id         INTEGER NOT NULL REFERENCES prompt_patch_trial(id),
  variant_idx      INTEGER NOT NULL,   -- -1 = control (no patch); 0..N-1 = candidates_json[idx]
  assigned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version   INTEGER DEFAULT 1,
  UNIQUE(issue_id, trial_id)
);

CREATE INDEX IF NOT EXISTS idx_session_trial_assignment_issue    ON session_trial_assignment(issue_id);
CREATE INDEX IF NOT EXISTS idx_session_trial_assignment_trial    ON session_trial_assignment(trial_id);
CREATE INDEX IF NOT EXISTS idx_session_trial_assignment_schema_v ON session_trial_assignment(schema_version);
