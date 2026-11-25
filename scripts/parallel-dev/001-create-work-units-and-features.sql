-- Migration: work_units + features tables for parallel-dev architecture
-- Applied to /home/app-user/gateway-state/gateway.db 2026-05-17 (IFRNLLEI01PRD-924)
-- Idempotent: uses CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS

CREATE TABLE IF NOT EXISTS work_units (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  title TEXT,
  files_owned TEXT NOT NULL,           -- JSON array of paths
  prompt TEXT NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending','in_progress','completed','failed','timeout','skipped')),
  worker_slot INTEGER,
  acceptance_test TEXT,
  dependencies TEXT,                    -- JSON array of task_ids
  parallelizable INTEGER DEFAULT 1,
  bounded_context TEXT,
  risk_score REAL DEFAULT 0.5,
  complexity INTEGER DEFAULT 5,
  max_wall_clock_minutes INTEGER DEFAULT 30,
  max_loc_delta INTEGER DEFAULT 500,
  diff_blob BLOB,
  test_report TEXT,                     -- JSON
  failure_reason TEXT,
  created_at INTEGER DEFAULT (strftime('%s','now')),
  started_at INTEGER,
  completed_at INTEGER,
  UNIQUE (feature_id, task_id)
);

CREATE INDEX IF NOT EXISTS idx_work_units_feature_status ON work_units (feature_id, status);
CREATE INDEX IF NOT EXISTS idx_work_units_status ON work_units (status);

CREATE TABLE IF NOT EXISTS features (
  feature_id TEXT PRIMARY KEY,
  repo_slug TEXT NOT NULL,
  title TEXT,
  status TEXT DEFAULT 'planning' CHECK (status IN ('planning','dispatching','in_progress','merging','done','failed','aborted')),
  source_issue_id TEXT,
  planner_session_id TEXT,
  total_work_units INTEGER DEFAULT 0,
  feature_risk_score REAL DEFAULT 0.5,
  mr_iid INTEGER,
  mr_url TEXT,
  created_at INTEGER DEFAULT (strftime('%s','now')),
  completed_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_features_status ON features (status);

-- Phase 5 (IFRNLLEI01PRD-927): pipeline_events → worker_resume mapping
-- Applied 2026-05-17. session_id is captured by distribute-workers.sh when launching
-- claude -p (parsed from JSONL); pipeline_id is set when a worker pushes a commit
-- and GitLab kicks off a pipeline for the parallel-dev/<feature>/<task> branch.
ALTER TABLE work_units ADD COLUMN session_id TEXT DEFAULT '';
ALTER TABLE work_units ADD COLUMN pipeline_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_work_units_pipeline ON work_units (pipeline_id);
CREATE INDEX IF NOT EXISTS idx_work_units_session ON work_units (session_id);
