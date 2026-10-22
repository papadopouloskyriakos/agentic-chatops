-- G15: Infragraph — causal infra dependency graph with learned dynamics
-- (IFRNLLEI01PRD-1029 epic / -1031, 2026-06-09; also migration 016)
-- Topology lives on the G10 GraphRAG tables with source_table='infragraph'.
--   New entity_type values: physical_host, pve_node, vm, lxc, service,
--   network_device, tunnel, bgp_session, site.
--   New rel_type values: runs_on, depends_on, routes_via, member_of,
--   backs_up_to, peers_with.
-- Edge direction convention: SOURCE depends on TARGET (vm -runs_on-> pve_node).
-- blast_radius(H) = reverse traversal (who depends on H); deps(H) = forward.

CREATE INDEX IF NOT EXISTS idx_gr_source_type ON graph_relationships(source_id, rel_type);
CREATE INDEX IF NOT EXISTS idx_gr_target_type ON graph_relationships(target_id, rel_type);

-- Sidecar dynamics: exactly one row per infragraph edge. Kept out of
-- graph_relationships.metadata so the GraphRAG writers stay untouched and
-- the eval can index on valid_until / observation_count.
CREATE TABLE IF NOT EXISTS infragraph_dynamics (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  rel_id             INTEGER NOT NULL UNIQUE REFERENCES graph_relationships(id),
  source             TEXT NOT NULL DEFAULT 'declared',  -- declared|chaos|incident|netbox|iac
  expected_alerts    TEXT DEFAULT '[]',   -- JSON [{"rule": str, "side": "source"}]
  samples            TEXT DEFAULT '{}',   -- JSON {"delay_s":[...],"recovery_s":[...]} capped 64 each
  delay_p50_s        REAL,
  delay_p95_s        REAL,
  recovery_p50_s     REAL,
  observation_count  INTEGER DEFAULT 0,
  last_validated     DATETIME,
  valid_until        DATETIME,            -- NULL = open-ended; netbox/iac get now+7d, reseeded daily
  confidence         REAL DEFAULT 0.5,
  updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version     INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_igd_rel ON infragraph_dynamics(rel_id);
CREATE INDEX IF NOT EXISTS idx_igd_valid ON infragraph_dynamics(valid_until);
CREATE INDEX IF NOT EXISTS idx_igd_source ON infragraph_dynamics(source);
CREATE INDEX IF NOT EXISTS idx_infragraph_dynamics_schema_v ON infragraph_dynamics(schema_version);

-- Prediction log. kind='cascade' rows are Phase B shadow predictions (alert →
-- expected symptom set); kind='action' rows are the MANDATORY pre-remediation
-- artifacts of the model-based invariant (operator-mandated 2026-06-09): the
-- n8n Runner commits one per remediation plan BEFORE the approval poll
-- (gate key = plan_hash, joining session_risk_audit.plan_hash), and
-- infragraph-verify.py writes the mechanical verdict after execution.
-- control_* columns hold the degree-preserving shuffled-graph negative
-- control so the eval can FAIL meaningfully.
CREATE TABLE IF NOT EXISTS infragraph_predictions (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
  kind               TEXT NOT NULL DEFAULT 'cascade',  -- cascade | action
  parent_issue_id    TEXT DEFAULT '',
  parent_host        TEXT NOT NULL,
  parent_rule        TEXT NOT NULL,
  action_kind        TEXT DEFAULT '',     -- restart_vm | restart_lxc | restart_service | reboot_host | bounce_tunnel | config_change | ...
  action_target      TEXT DEFAULT '',     -- full site-prefixed hostname / entity name
  plan_hash          TEXT DEFAULT '',     -- non-bypassable-gate key (= session_risk_audit.plan_hash)
  window_seconds     INTEGER NOT NULL,
  predicted          TEXT NOT NULL,       -- JSON [{host, rule, expected_delay_s, confidence}]
  control_predicted  TEXT DEFAULT '[]',
  evaluated_at       DATETIME,
  actual             TEXT,                -- JSON [{host, rule, ts}] from triage.log at eval time
  tp INTEGER, fp INTEGER, fn INTEGER,
  control_tp INTEGER, control_fp INTEGER,
  verdict            TEXT DEFAULT '',     -- '' until verified; match | partial | deviation
  verdict_detail     TEXT DEFAULT '{}',   -- JSON per-alert diff written by infragraph-verify.py
  model_version      INTEGER DEFAULT 1,
  schema_version     INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_igp_eval ON infragraph_predictions(evaluated_at);
CREATE INDEX IF NOT EXISTS idx_igp_parent ON infragraph_predictions(parent_host, parent_rule);
CREATE INDEX IF NOT EXISTS idx_igp_created ON infragraph_predictions(created_at);
CREATE INDEX IF NOT EXISTS idx_igp_plan_hash ON infragraph_predictions(plan_hash);
CREATE INDEX IF NOT EXISTS idx_igp_kind ON infragraph_predictions(kind);
CREATE INDEX IF NOT EXISTS idx_infragraph_predictions_schema_v ON infragraph_predictions(schema_version);
