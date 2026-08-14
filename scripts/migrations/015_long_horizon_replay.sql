-- Migration 015 — 2026-04-29
-- IFRNLLEI01PRD-748 — Long-horizon reasoning replay eval (G1 / P0.1).
--
-- Adds the long_horizon_replay_results table for the weekly cron that
-- replays the 30 longest historical sessions and scores each on four
-- dimensions: trace_coherence, tool_efficiency, poll_correctness,
-- cost_per_turn_z. A composite_score (unweighted mean) feeds the
-- chatops_long_horizon_replay_score{session_id, dimension} metric.
--
-- Source: closes NVIDIA-DLI dim #9 (data flywheel — long-horizon
-- evaluation pillar, A- → A) per docs/nvidia-dli-cross-audit-2026-04-29.md.
--
-- Reads: sessions, session_transcripts, tool_call_log, session_risk_audit.
-- Writes: this table.

CREATE TABLE IF NOT EXISTS long_horizon_replay_results (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id              TEXT NOT NULL,                          -- replay-<YYYY-MM-DD-HH>
  session_id          TEXT NOT NULL,
  issue_id            TEXT,
  num_turns           INTEGER,
  duration_seconds    INTEGER,
  trace_coherence     REAL,                                   -- 0.0-1.0, Jaccard of adjacent assistant turns
  tool_efficiency     REAL,                                   -- 0.0-1.0, unique / total tool calls
  poll_correctness    REAL,                                   -- 0.0 or 1.0 vs session_risk_audit.risk_level
  cost_per_turn_z     REAL,                                   -- z-score vs historical mean
  composite_score     REAL,                                   -- unweighted mean of above 4
  replayed_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version      INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_lhrr_run         ON long_horizon_replay_results(run_id);
CREATE INDEX IF NOT EXISTS idx_lhrr_session     ON long_horizon_replay_results(session_id, replayed_at);
CREATE INDEX IF NOT EXISTS idx_lhrr_schema_v    ON long_horizon_replay_results(schema_version);
