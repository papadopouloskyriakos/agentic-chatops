-- Migration 008 — 2026-04-20
-- IFRNLLEI01PRD-643 — Handoff depth counter + cycle detection.
--
-- Adds handoff_depth (INT) and handoff_chain (TEXT JSON array) columns to
-- sessions, so the Build Prompt node can enforce:
--   * handoff_depth >= 5   -> force [POLL] regardless of risk level
--   * handoff_depth >= 10  -> hard-halt with HandoffDepthExceeded
--   * any agent appears twice in handoff_chain -> HandoffCycleDetectedEvent
--
-- Reference: OpenAI Agents SDK run_internal/run_loop.py MaxTurnsExceeded.
-- Idempotent via apply.py.

ALTER TABLE sessions ADD COLUMN handoff_depth INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN handoff_chain TEXT DEFAULT '[]';

CREATE INDEX IF NOT EXISTS idx_sessions_handoff_depth ON sessions(handoff_depth);
