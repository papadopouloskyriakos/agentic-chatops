-- 028_master_switch_log.sql — hash-chained master power-switch transition ledger
-- (IFRNLLEI01PRD-1823, 2026-07-17)
--
-- One row per master-switch transition (power-off / power-on of the complete agentic system).
-- Tamper-evident: row_hash = sha256(prev_row_hash + '|' + pipe-joined canonical row values in the
-- COLS order of scripts/lib/master_switch_audit.py — writer and verifier stay in lockstep there).
-- Verified on every `gateway-master-switch.py status` run → gateway_master_switch_chain_intact.

CREATE TABLE IF NOT EXISTS master_switch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,                      -- unix epoch of the transition
  action TEXT,                     -- 'off' | 'on'
  mode TEXT,                       -- 'soft' | 'hard'
  operator TEXT,
  reason TEXT,
  hostname TEXT,
  sentinels_json TEXT,             -- removed/restored arming sentinels + guards kept
  cronicle_json TEXT,              -- cronicle jobs disabled/re-enabled (id, title, ok)
  n8n_json TEXT,                   -- n8n workflows deactivated/re-activated (hard mode)
  sessions_json TEXT,              -- in-flight dispatched sessions found/killed
  maintenance_action TEXT,         -- created | preexisting | removed | kept-foreign | absent
  partial INTEGER,                 -- 1 if any step failed (partial transition)
  details_json TEXT,
  schema_version INTEGER NOT NULL DEFAULT 1,
  prev_hash TEXT,
  row_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_master_switch_log_ts ON master_switch_log(ts);
CREATE INDEX IF NOT EXISTS idx_master_switch_log_schema_v ON master_switch_log(schema_version);
