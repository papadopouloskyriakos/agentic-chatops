-- claude-gateway SQLite schema
-- Initialize: sqlite3 gateway.db < schema.sql
-- All tables are also auto-created by n8n workflows on first run.

CREATE TABLE IF NOT EXISTS sessions (
  issue_id      TEXT PRIMARY KEY,
  issue_title   TEXT,
  session_id    TEXT,
  trace_id      TEXT DEFAULT '',
  started_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_active   DATETIME DEFAULT CURRENT_TIMESTAMP,
  message_count INTEGER DEFAULT 0,
  paused        INTEGER DEFAULT 0,
  is_current    INTEGER DEFAULT 0,
  last_response_b64 TEXT DEFAULT '',
  cost_usd      REAL DEFAULT 0,
  num_turns     INTEGER DEFAULT 0,
  duration_seconds INTEGER DEFAULT 0,
  confidence    REAL DEFAULT -1,
  prompt_variant TEXT DEFAULT '',
  alert_category TEXT DEFAULT '',
  retry_count   INTEGER DEFAULT 0,
  retry_improved BOOLEAN DEFAULT 0,
  prompt_surface TEXT DEFAULT 'build_prompt',
  subsystem     TEXT DEFAULT '',
  model         TEXT DEFAULT '',
  handoff_depth INTEGER DEFAULT 0,
  handoff_chain TEXT DEFAULT '[]',
  schema_version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_sessions_schema_v ON sessions(schema_version);
CREATE INDEX IF NOT EXISTS idx_sessions_handoff_depth ON sessions(handoff_depth);

CREATE TABLE IF NOT EXISTS queue (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT NOT NULL,
  message       TEXT NOT NULL,
  queued_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT,
  issue_title   TEXT,
  session_id    TEXT,
  trace_id      TEXT DEFAULT '',
  started_at    DATETIME,
  ended_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  message_count INTEGER DEFAULT 0,
  outcome       TEXT,
  cost_usd      REAL DEFAULT 0,
  num_turns     INTEGER DEFAULT 0,
  duration_seconds INTEGER DEFAULT 0,
  confidence    REAL DEFAULT -1,
  resolution_type TEXT DEFAULT 'unknown',
  prompt_variant TEXT DEFAULT '',
  alert_category TEXT DEFAULT '',
  model         TEXT DEFAULT '',
  schema_version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_session_log_schema_v ON session_log(schema_version);

CREATE TABLE IF NOT EXISTS llm_usage (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  tier              INTEGER NOT NULL,
  model             TEXT NOT NULL,
  issue_id          TEXT DEFAULT '',
  input_tokens      INTEGER DEFAULT 0,
  output_tokens     INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  cost_usd          REAL DEFAULT 0,
  recorded_at       DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lu_model ON llm_usage(model);
CREATE INDEX IF NOT EXISTS idx_lu_recorded ON llm_usage(recorded_at);
CREATE INDEX IF NOT EXISTS idx_lu_tier ON llm_usage(tier);

CREATE TABLE IF NOT EXISTS incident_knowledge (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  alert_rule    TEXT NOT NULL DEFAULT '',
  hostname      TEXT DEFAULT '',
  site          TEXT DEFAULT '',
  root_cause    TEXT DEFAULT '',
  resolution    TEXT DEFAULT '',
  confidence    REAL DEFAULT -1,
  duration_seconds INTEGER DEFAULT 0,
  cost_usd      REAL DEFAULT 0,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  session_id    TEXT DEFAULT '',
  issue_id      TEXT DEFAULT '',
  tags          TEXT DEFAULT '',
  embedding     TEXT DEFAULT '',
  project       TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ik_alert ON incident_knowledge(alert_rule);
CREATE INDEX IF NOT EXISTS idx_ik_host ON incident_knowledge(hostname);

CREATE TABLE IF NOT EXISTS lessons_learned (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT DEFAULT '',
  lesson        TEXT NOT NULL,
  source        TEXT DEFAULT '',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ll_created ON lessons_learned(created_at);

CREATE TABLE IF NOT EXISTS openclaw_memory (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  category      TEXT NOT NULL DEFAULT 'triage',
  key           TEXT NOT NULL,
  value         TEXT NOT NULL,
  issue_id      TEXT DEFAULT '',
  updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_om_key ON openclaw_memory(key);
CREATE INDEX IF NOT EXISTS idx_om_cat ON openclaw_memory(category);

CREATE TABLE IF NOT EXISTS session_feedback (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT NOT NULL,
  session_id    TEXT DEFAULT '',
  feedback_type TEXT NOT NULL,
  message_snippet TEXT DEFAULT '',
  confidence    REAL DEFAULT -1,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sf_issue ON session_feedback(issue_id);
CREATE INDEX IF NOT EXISTS idx_sf_created ON session_feedback(created_at);

CREATE TABLE IF NOT EXISTS a2a_task_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id    TEXT NOT NULL,
  issue_id      TEXT NOT NULL,
  from_tier     INTEGER NOT NULL,
  from_agent    TEXT NOT NULL,
  to_tier       INTEGER NOT NULL,
  to_agent      TEXT NOT NULL,
  message_type  TEXT NOT NULL,
  state         TEXT DEFAULT 'created',
  payload_summary TEXT DEFAULT '',
  confidence    REAL DEFAULT -1,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_a2a_issue ON a2a_task_log(issue_id);
CREATE INDEX IF NOT EXISTS idx_a2a_type ON a2a_task_log(message_type);
CREATE INDEX IF NOT EXISTS idx_a2a_created ON a2a_task_log(created_at);

CREATE TABLE IF NOT EXISTS session_quality (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT NOT NULL,
  session_id    TEXT DEFAULT '',
  confidence_score INTEGER DEFAULT -1,
  cost_efficiency INTEGER DEFAULT -1,
  response_completeness INTEGER DEFAULT -1,
  feedback_score INTEGER DEFAULT -1,
  resolution_speed INTEGER DEFAULT -1,
  quality_score INTEGER DEFAULT -1,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sq_issue ON session_quality(issue_id);
CREATE INDEX IF NOT EXISTS idx_sq_created ON session_quality(created_at);

CREATE TABLE IF NOT EXISTS crowdsec_scenario_stats (
  scenario      TEXT NOT NULL,
  host          TEXT NOT NULL,
  total_count   INTEGER DEFAULT 0,
  suppressed_count INTEGER DEFAULT 0,
  escalated_count INTEGER DEFAULT 0,
  yt_issues_created INTEGER DEFAULT 0,
  last_seen     DATETIME,
  last_escalated DATETIME,
  auto_suppressed BOOLEAN DEFAULT 0,
  PRIMARY KEY (scenario, host)
);

CREATE TABLE IF NOT EXISTS prompt_scorecard (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  prompt_surface TEXT NOT NULL,
  window        TEXT NOT NULL,
  graded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  effectiveness INTEGER DEFAULT -1,
  efficiency    INTEGER DEFAULT -1,
  completeness  INTEGER DEFAULT -1,
  consistency   INTEGER DEFAULT -1,
  feedback      INTEGER DEFAULT -1,
  retry_rate    INTEGER DEFAULT -1,
  composite     INTEGER DEFAULT -1,
  n_samples     INTEGER DEFAULT 0,
  notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS session_trajectory (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT NOT NULL,
  session_id    TEXT DEFAULT '',
  graded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  has_netbox_lookup INTEGER DEFAULT 0,
  has_incident_kb_query INTEGER DEFAULT 0,
  has_react_structure INTEGER DEFAULT 0,
  has_poll_or_approval INTEGER DEFAULT 0,
  has_confidence INTEGER DEFAULT 0,
  has_evidence_commands INTEGER DEFAULT 0,
  has_ssh_investigation INTEGER DEFAULT 0,
  has_yt_comment INTEGER DEFAULT 0,
  steps_completed INTEGER DEFAULT 0,
  steps_expected INTEGER DEFAULT 0,
  trajectory_score INTEGER DEFAULT -1,
  tool_calls    INTEGER DEFAULT 0,
  turns         INTEGER DEFAULT 0,
  notes         TEXT DEFAULT '',
  schema_version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_session_trajectory_schema_v ON session_trajectory(schema_version);
-- one grade row per issue_id: re-grades UPSERT (migration 023, IFRNLLEI01PRD-1571 #3)
CREATE UNIQUE INDEX IF NOT EXISTS ux_session_trajectory_issue ON session_trajectory(issue_id);

CREATE TABLE IF NOT EXISTS wiki_articles (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  path             TEXT NOT NULL UNIQUE,
  title            TEXT NOT NULL,
  section          TEXT DEFAULT '',
  content_hash     TEXT NOT NULL,
  embedding        TEXT DEFAULT '',
  compiled_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  source_files     TEXT DEFAULT '',
  -- Added by migration 004 (2026-04-18); codified here so fresh_db()
  -- fixture has the column without running the migration (which it
  -- marks as already-applied). See scripts/migrations/004_* for detail.
  content_preview  TEXT DEFAULT '',
  -- Added by migration 005 (2026-04-18) for source-mtime stamp.
  source_mtime     REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_wa_path ON wiki_articles(path);

-- MemPalace integration (2026-04-09): verbatim session transcripts + agent diaries
CREATE TABLE IF NOT EXISTS session_transcripts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT NOT NULL,
  session_id    TEXT DEFAULT '',
  chunk_index   INTEGER DEFAULT 0,
  role          TEXT DEFAULT '',
  content       TEXT NOT NULL,
  embedding     TEXT DEFAULT '',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  source_file   TEXT DEFAULT '',
  schema_version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_st_issue ON session_transcripts(issue_id);
CREATE INDEX IF NOT EXISTS idx_st_session ON session_transcripts(session_id);
CREATE INDEX IF NOT EXISTS idx_session_transcripts_schema_v ON session_transcripts(schema_version);

CREATE TABLE IF NOT EXISTS agent_diary (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_name    TEXT NOT NULL,
  issue_id      TEXT DEFAULT '',
  entry         TEXT NOT NULL,
  tags          TEXT DEFAULT '',
  embedding     TEXT DEFAULT '',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_ad_agent ON agent_diary(agent_name);
CREATE INDEX IF NOT EXISTS idx_ad_created ON agent_diary(created_at);
CREATE INDEX IF NOT EXISTS idx_agent_diary_schema_v ON agent_diary(schema_version);

CREATE TABLE IF NOT EXISTS session_judgment (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id      TEXT NOT NULL,
  session_id    TEXT DEFAULT '',
  judged_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  judge_model   TEXT DEFAULT '',
  judge_effort  TEXT DEFAULT 'low',
  investigation_quality INTEGER DEFAULT -1,
  evidence_based INTEGER DEFAULT -1,
  actionability INTEGER DEFAULT -1,
  safety_compliance INTEGER DEFAULT -1,
  completeness  INTEGER DEFAULT -1,
  overall_score INTEGER DEFAULT -1,
  rationale     TEXT DEFAULT '',
  concerns      TEXT DEFAULT '',
  recommended_action TEXT DEFAULT '',
  schema_version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_session_judgment_schema_v ON session_judgment(schema_version);

-- G13: Tool call logging for agent-generated tool improvement
CREATE TABLE IF NOT EXISTS tool_call_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id    TEXT,
  issue_id      TEXT,
  tool_name     TEXT NOT NULL,
  operation     TEXT DEFAULT '',
  duration_ms   INTEGER DEFAULT 0,
  exit_code     INTEGER DEFAULT 0,
  error_type    TEXT DEFAULT '',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_tcl_tool ON tool_call_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_tcl_session ON tool_call_log(session_id);
CREATE INDEX IF NOT EXISTS idx_tcl_created ON tool_call_log(created_at);
CREATE INDEX IF NOT EXISTS idx_tool_call_log_schema_v ON tool_call_log(schema_version);

-- G10: GraphRAG entity-relation knowledge graph
CREATE TABLE IF NOT EXISTS graph_entities (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type   TEXT NOT NULL,  -- device, service, alert_rule, incident, host, vlan
  name          TEXT NOT NULL,
  source_table  TEXT DEFAULT '',
  source_id     TEXT DEFAULT '',
  attributes    TEXT DEFAULT '{}',  -- JSON
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(entity_type, name)
);
CREATE INDEX IF NOT EXISTS idx_ge_type ON graph_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_ge_name ON graph_entities(name);

CREATE TABLE IF NOT EXISTS graph_relationships (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id     INTEGER NOT NULL REFERENCES graph_entities(id),
  target_id     INTEGER NOT NULL REFERENCES graph_entities(id),
  rel_type      TEXT NOT NULL,  -- triggers, caused_by, depends_on, resolves, hosts, belongs_to
  confidence    REAL DEFAULT 1.0,
  metadata      TEXT DEFAULT '{}',  -- JSON
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_gr_source ON graph_relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_gr_target ON graph_relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_gr_type ON graph_relationships(rel_type);

-- G7: Atomic transactions / undo stacks — execution log with pre/post state
CREATE TABLE IF NOT EXISTS execution_log (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id        TEXT,
  issue_id          TEXT,
  step_index        INTEGER DEFAULT 0,
  device            TEXT NOT NULL,
  command           TEXT NOT NULL,
  pre_state         TEXT DEFAULT '',
  post_state        TEXT DEFAULT '',
  exit_code         INTEGER DEFAULT -1,
  rolled_back       BOOLEAN DEFAULT 0,
  rollback_command  TEXT DEFAULT '',
  duration_ms       INTEGER DEFAULT 0,
  created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version    INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_el_session ON execution_log(session_id);
CREATE INDEX IF NOT EXISTS idx_el_issue ON execution_log(issue_id);
CREATE INDEX IF NOT EXISTS idx_el_device ON execution_log(device);
CREATE INDEX IF NOT EXISTS idx_execution_log_schema_v ON execution_log(schema_version);

-- event_log (IFRNLLEI01PRD-637) — canonical definition; also applied via
-- migration 007 for existing installs.
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
CREATE INDEX IF NOT EXISTS idx_event_log_session_emitted ON event_log(session_id, emitted_at);

-- handoff_log (IFRNLLEI01PRD-640) — canonical definition; also applied via
-- migration 009 for existing installs.
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

-- session_state_snapshot (IFRNLLEI01PRD-636) — canonical definition.
CREATE TABLE IF NOT EXISTS session_state_snapshot (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id          TEXT NOT NULL,
  session_id        TEXT DEFAULT '',
  turn_id           INTEGER DEFAULT -1,
  snapshot_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
  pending_tool      TEXT DEFAULT '',
  pending_tool_input TEXT DEFAULT '{}',
  snapshot_data     TEXT NOT NULL,
  snapshot_bytes    INTEGER DEFAULT 0,
  schema_version    INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_issue   ON session_state_snapshot(issue_id);
CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_session ON session_state_snapshot(session_id);
CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_at      ON session_state_snapshot(snapshot_at);
CREATE INDEX IF NOT EXISTS idx_session_state_snapshot_schema_v ON session_state_snapshot(schema_version);

-- session_turns (IFRNLLEI01PRD-638) — canonical definition.
CREATE TABLE IF NOT EXISTS session_turns (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id          TEXT DEFAULT '',
  session_id        TEXT DEFAULT '',
  turn_id           INTEGER NOT NULL,
  started_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at          DATETIME,
  llm_cost_usd      REAL DEFAULT 0,
  input_tokens      INTEGER DEFAULT 0,
  output_tokens     INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  tool_count        INTEGER DEFAULT 0,
  tool_errors       INTEGER DEFAULT 0,
  duration_ms       INTEGER DEFAULT -1,
  schema_version    INTEGER DEFAULT 1,
  UNIQUE(session_id, turn_id)
);
CREATE INDEX IF NOT EXISTS idx_session_turns_issue    ON session_turns(issue_id);
CREATE INDEX IF NOT EXISTS idx_session_turns_session  ON session_turns(session_id);
CREATE INDEX IF NOT EXISTS idx_session_turns_started  ON session_turns(started_at);
CREATE INDEX IF NOT EXISTS idx_session_turns_schema_v ON session_turns(schema_version);

-- prompt_patch_trial + session_trial_assignment (IFRNLLEI01PRD-645) —
-- preference iteration for auto-generated prompt patches. See migration 012.
CREATE TABLE IF NOT EXISTS prompt_patch_trial (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  surface            TEXT NOT NULL,
  dimension          TEXT NOT NULL,
  generated_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
  trial_ends_at      DATETIME,
  status             TEXT NOT NULL DEFAULT 'active',
  baseline_mean      REAL NOT NULL,
  baseline_samples   INTEGER NOT NULL DEFAULT 0,
  candidates_json    TEXT NOT NULL,
  min_samples_per_arm INTEGER NOT NULL DEFAULT 15,
  min_lift           REAL NOT NULL DEFAULT 0.05,
  winner_idx         INTEGER,
  winner_mean        REAL,
  winner_p_value     REAL,
  finalized_at       DATETIME,
  note               TEXT DEFAULT '',
  schema_version     INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_status   ON prompt_patch_trial(status);
CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_surface  ON prompt_patch_trial(surface);
CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_ends_at  ON prompt_patch_trial(trial_ends_at);
CREATE INDEX IF NOT EXISTS idx_prompt_patch_trial_schema_v ON prompt_patch_trial(schema_version);
CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_patch_trial_active
  ON prompt_patch_trial(surface, dimension) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS session_trial_assignment (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id         TEXT NOT NULL,
  session_id       TEXT DEFAULT '',
  trial_id         INTEGER NOT NULL REFERENCES prompt_patch_trial(id),
  variant_idx      INTEGER NOT NULL,
  assigned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version   INTEGER DEFAULT 1,
  UNIQUE(issue_id, trial_id)
);
CREATE INDEX IF NOT EXISTS idx_sta_issue    ON session_trial_assignment(issue_id);
CREATE INDEX IF NOT EXISTS idx_sta_trial    ON session_trial_assignment(trial_id);
CREATE INDEX IF NOT EXISTS idx_sta_schema_v ON session_trial_assignment(schema_version);

-- learning_progress + learning_sessions (IFRNLLEI01PRD-651) — teacher-agent
-- foundation tables. One row per (operator, topic) in learning_progress for
-- SM-2 + Bloom state; append-only learning_sessions audits every lesson /
-- quiz / review / teaching_back interaction.
CREATE TABLE IF NOT EXISTS learning_progress (
  id                        INTEGER PRIMARY KEY AUTOINCREMENT,
  operator                  TEXT NOT NULL,
  topic                     TEXT NOT NULL,
  mastery_score             REAL DEFAULT 0.0,
  easiness_factor           REAL DEFAULT 2.5,
  interval_days             INTEGER DEFAULT 1,
  repetition_count          INTEGER DEFAULT 0,
  highest_bloom_reached     TEXT DEFAULT 'recall',
  last_reviewed             DATETIME,
  next_due                  DATETIME DEFAULT CURRENT_TIMESTAMP,
  quiz_history              TEXT DEFAULT '[]',
  paused                    INTEGER DEFAULT 0,
  needs_review              INTEGER DEFAULT 0,
  source_hash               TEXT DEFAULT '',
  created_at                DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version            INTEGER DEFAULT 1,
  UNIQUE(operator, topic)
);
CREATE INDEX IF NOT EXISTS idx_lp_next_due  ON learning_progress(operator, next_due);
CREATE INDEX IF NOT EXISTS idx_lp_mastery   ON learning_progress(operator, mastery_score);
CREATE INDEX IF NOT EXISTS idx_lp_schema_v  ON learning_progress(schema_version);

CREATE TABLE IF NOT EXISTS learning_sessions (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  operator          TEXT NOT NULL,
  topic             TEXT NOT NULL,
  session_type      TEXT NOT NULL,
  bloom_level       TEXT,
  started_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at      DATETIME,
  quiz_score        REAL,
  question_payload  TEXT,
  answer_payload    TEXT,
  judge_feedback    TEXT,
  citation_flag     INTEGER DEFAULT 0,
  schema_version    INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_ls_operator  ON learning_sessions(operator, topic);
CREATE INDEX IF NOT EXISTS idx_ls_started   ON learning_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_ls_schema_v  ON learning_sessions(schema_version);

-- session_risk_audit (IFRNLLEI01PRD-632) — canonicalised here as part of
-- IFRNLLEI01PRD-635 schema versioning. The table is also lazy-created by
-- scripts/classify-session-risk.py and scripts/audit-risk-decisions.sh for
-- backwards-compat with fresh installs that run the script before applying
-- migrations. Keep the column list in sync across all three definitions.
CREATE TABLE IF NOT EXISTS session_risk_audit (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id          TEXT NOT NULL,
  classified_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  alert_category    TEXT,
  risk_level        TEXT NOT NULL,
  auto_approved     INTEGER NOT NULL DEFAULT 0,
  signals_json      TEXT,
  plan_hash         TEXT,
  operator_override TEXT,
  schema_version    INTEGER DEFAULT 1,
  -- IFRNLLEI01PRD-1108 (autonomy-forward gate, schema v2): the band assigned by
  -- classify-session-risk.py under AUTONOMY_FORWARD, plus the two derived flags.
  -- NULL on legacy rows (flag off / pre-migration). The classifier ALSO adds
  -- these via ALTER TABLE for fresh installs that run the script before this DDL.
  band                    TEXT,     -- AUTO | AUTO_NOTICE | POLL_PROCEED | POLL_PAUSE
  auto_proceed_on_timeout INTEGER,  -- 1 = no-vote => proceed (reversible, prediction-backed)
  sms_required            INTEGER   -- 1 = page the operator (HIGH, or P0 auto-proceed)
);
CREATE INDEX IF NOT EXISTS idx_session_risk_audit_issue ON session_risk_audit(issue_id);
CREATE INDEX IF NOT EXISTS idx_session_risk_audit_time ON session_risk_audit(classified_at);
CREATE INDEX IF NOT EXISTS idx_session_risk_audit_schema_v ON session_risk_audit(schema_version);

-- G14: Credential usage logging for rotation tracking
CREATE TABLE IF NOT EXISTS credential_usage_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  credential_name TEXT NOT NULL,
  source          TEXT DEFAULT 'env',  -- env, openbao, ssh-agent
  session_id      TEXT DEFAULT '',
  issue_id        TEXT DEFAULT '',
  ttl_seconds     INTEGER DEFAULT 0,  -- 0 = persistent (no rotation)
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at      DATETIME,
  revoked_at      DATETIME
);
CREATE INDEX IF NOT EXISTS idx_cul_cred ON credential_usage_log(credential_name);
CREATE INDEX IF NOT EXISTS idx_cul_created ON credential_usage_log(created_at);

-- RAGAS evaluation pipeline (2026-04-15): RAG quality metrics via LLM-as-judge
CREATE TABLE IF NOT EXISTS ragas_evaluation (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  query             TEXT NOT NULL,
  retrieved_docs    TEXT DEFAULT '[]',
  answer            TEXT DEFAULT '',
  ground_truth      TEXT DEFAULT '',
  faithfulness      REAL DEFAULT -1,
  context_precision REAL DEFAULT -1,
  context_recall    REAL DEFAULT -1,
  answer_relevance  REAL DEFAULT -1,
  semantic_quality  REAL DEFAULT -1,
  num_retrieved     INTEGER DEFAULT 0,
  eval_model        TEXT DEFAULT 'claude-haiku-4-5-20251001',
  created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  issue_id          TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_re_created ON ragas_evaluation(created_at);
CREATE INDEX IF NOT EXISTS idx_re_issue ON ragas_evaluation(issue_id);

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

-- Cascade-probability gating stats (IFRNLLEI01PRD-1118, migration 017). Learned
-- per-(parent rule-family -> child) hit-rates that gate cascade over-prediction
-- and set per-item confidence. Mirrors scripts/migrations/017_infragraph_cascade_stats.sql.
CREATE TABLE IF NOT EXISTS infragraph_cascade_stats (
  scope          TEXT NOT NULL,            -- 'family' | 'exact'
  parent_family  TEXT NOT NULL,
  child_host     TEXT NOT NULL,
  child_key      TEXT NOT NULL,            -- rule-family (family scope) | rule (exact scope)
  seen           INTEGER NOT NULL DEFAULT 0,
  fired          INTEGER NOT NULL DEFAULT 0,
  updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version INTEGER DEFAULT 1,
  PRIMARY KEY (scope, parent_family, child_host, child_key)
);
CREATE INDEX IF NOT EXISTS idx_igcs_lookup ON infragraph_cascade_stats(scope, parent_family, child_host, child_key);

-- OTel local span store (IFRNLLEI01PRD-1093, 2026-06-16). Previously defined
-- inline ONLY in scripts/export-otel-traces.py:store_spans_locally(), so a fresh
-- `sqlite3 gateway.db < schema.sql` did not create it and it was invisible to the
-- schema-version registry + fresh_db fixtures. Definition mirrors the exporter.
CREATE TABLE IF NOT EXISTS otel_spans (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id         TEXT NOT NULL,
  span_id          TEXT NOT NULL,
  parent_span_id   TEXT DEFAULT '',
  operation_name   TEXT NOT NULL,
  issue_id         TEXT DEFAULT '',
  start_time       TEXT DEFAULT '',
  end_time         TEXT DEFAULT '',
  attributes       TEXT DEFAULT '{}',
  exported_to_otlp BOOLEAN DEFAULT 0,
  created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(trace_id, span_id)
);
CREATE INDEX IF NOT EXISTS idx_otel_spans_export ON otel_spans(exported_to_otlp);
CREATE INDEX IF NOT EXISTS idx_otel_spans_issue ON otel_spans(issue_id);

-- ---------------------------------------------------------------------------
-- Code-created tables (reconciled into schema.sql 2026-06-26). These were created
-- directly by application code (chaos_baseline.py, lib/circuit_breaker.py,
-- holistic-agentic-health.sh, parallel-dev/*) via CREATE TABLE IF NOT EXISTS and were
-- never captured here, so a from-scratch rebuild (schema.sql + migrations) failed when a
-- later migration ALTERed one (e.g. 004 -> chaos_experiments). Definitions below are the
-- live canonical schema (normalized to IF NOT EXISTS).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chaos_exercises (
            id INTEGER PRIMARY KEY,
            exercise_id TEXT UNIQUE,
            exercise_type TEXT,
            started_at TEXT,
            completed_at TEXT,
            experiment_ids TEXT,
            total_count INTEGER DEFAULT 0,
            pass_count INTEGER DEFAULT 0,
            degraded_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            error_budget_consumed_pct REAL DEFAULT 0,
            preflight_passed INTEGER,
            triggered_by TEXT DEFAULT 'cron',
            summary TEXT
        );

CREATE TABLE IF NOT EXISTS chaos_experiments (
            id INTEGER PRIMARY KEY,
            experiment_id TEXT UNIQUE,
            chaos_type TEXT,
            targets TEXT,
            hypothesis TEXT,
            pre_state TEXT,
            post_state TEXT,
            events TEXT,
            expected_alerts TEXT,
            unexpected_alerts TEXT,
            convergence_seconds REAL,
            recovery_seconds REAL,
            verdict TEXT,
            verdict_details TEXT,
            error_budget_consumed_pct REAL,
            triggered_by TEXT,
            started_at TEXT,
            recovered_at TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        , mttd_seconds REAL, mttr_seconds REAL, mttd_haproxy_seconds REAL, mttd_user_seconds REAL, detection_perspective TEXT, statistical_summary TEXT, source_ip TEXT, embedding TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS chaos_findings (
            id INTEGER PRIMARY KEY,
            finding_id TEXT UNIQUE,
            experiment_id TEXT,
            retrospective_id INTEGER,
            finding TEXT,
            severity TEXT,
            category TEXT,
            improvement_action TEXT,
            youtrack_issue TEXT,
            status TEXT DEFAULT 'open',
            due_date TEXT,
            verified_at TEXT,
            verified_by TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

CREATE TABLE IF NOT EXISTS chaos_retrospectives (
            id INTEGER PRIMARY KEY,
            experiment_id TEXT,
            exercise_type TEXT,
            findings TEXT,
            gaps_identified TEXT,
            improvement_actions TEXT,
            runbook_validated TEXT,
            alert_correlation TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );

CREATE TABLE IF NOT EXISTS circuit_breakers (
                    name TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    opened_at REAL,
                    half_open_successes INTEGER NOT NULL DEFAULT 0,
                    last_transition_at REAL,
                    last_updated REAL NOT NULL
                );

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

CREATE TABLE IF NOT EXISTS health_check_detail (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER REFERENCES health_check_results(id),
  status TEXT, name TEXT, detail TEXT
);

CREATE TABLE IF NOT EXISTS health_check_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  score INTEGER, pass INTEGER, fail INTEGER, warn INTEGER, skip INTEGER,
  duration_s REAL, mode TEXT DEFAULT 'full'
);

CREATE TABLE IF NOT EXISTS work_units (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  title TEXT,
  files_owned TEXT NOT NULL,
  prompt TEXT NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending','in_progress','completed','failed','timeout','skipped')),
  worker_slot INTEGER,
  acceptance_test TEXT,
  dependencies TEXT,
  parallelizable INTEGER DEFAULT 1,
  bounded_context TEXT,
  risk_score REAL DEFAULT 0.5,
  complexity INTEGER DEFAULT 5,
  max_wall_clock_minutes INTEGER DEFAULT 30,
  max_loc_delta INTEGER DEFAULT 500,
  diff_blob BLOB,
  test_report TEXT,
  failure_reason TEXT,
  created_at INTEGER DEFAULT (strftime('%s','now')),
  started_at INTEGER,
  completed_at INTEGER, session_id TEXT DEFAULT '', pipeline_id INTEGER,
  UNIQUE (feature_id, task_id)
);

-- Self-learning scheduled-reboot registry (migration 022). One row per
-- (host, deterministic reboot schedule, kind). The Tier 1 matcher reads ONLY
-- status='live' AND kill_switch=0 AND valid_until>now rows. See migration 022.
CREATE TABLE IF NOT EXISTS discovered_scheduled_reboots (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  hostname               TEXT    NOT NULL,
  site                   TEXT    NOT NULL DEFAULT '',
  cron_expr              TEXT    NOT NULL,
  tz                     TEXT    NOT NULL DEFAULT 'Europe/Amsterdam',
  reboot_kind            TEXT    NOT NULL CHECK (reboot_kind IN
                           ('cron','systemd-timer','unattended-upgrade','eem_watchdog')),
  source                 TEXT    NOT NULL DEFAULT 'discovery',
  window_minutes         INTEGER NOT NULL DEFAULT 10,
  pre_buffer_minutes     INTEGER NOT NULL DEFAULT 5,
  status                 TEXT    NOT NULL DEFAULT 'observing'
                           CHECK (status IN ('observing','live','disabled')),
  observed_count         INTEGER NOT NULL DEFAULT 0,
  in_window_observations TEXT    NOT NULL DEFAULT '[]',
  last_reboot_at         DATETIME,
  last_match_at          DATETIME,
  valid_until            DATETIME NOT NULL,
  kill_switch            INTEGER NOT NULL DEFAULT 0,
  rationale              TEXT    NOT NULL DEFAULT '',
  discovered_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  schema_version         INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_dsr_match ON discovered_scheduled_reboots(hostname, cron_expr)
  WHERE status = 'live' AND kill_switch = 0;
CREATE INDEX IF NOT EXISTS idx_dsr_status      ON discovered_scheduled_reboots(status);
CREATE INDEX IF NOT EXISTS idx_dsr_valid_until ON discovered_scheduled_reboots(valid_until);
CREATE INDEX IF NOT EXISTS idx_dsr_host        ON discovered_scheduled_reboots(hostname);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dsr_host_expr_kind
  ON discovered_scheduled_reboots(hostname, cron_expr, reboot_kind);

-- escalation_queue — dropped-escalation requeue lane (migration 026, IFRNLLEI01PRD-1709,
-- 2026-07-08). Producers: scripts/queue-escalation.sh (Runner "Is Locked?" TRUE branch)
-- + reconcile-completed-sessions.py (orphaned-poll delayed re-check). Consumer:
-- scripts/requeue-escalations.py (re-fires the normal n8n webhook; never bypasses gates).
CREATE TABLE IF NOT EXISTS escalation_queue (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id       TEXT NOT NULL,
  summary        TEXT NOT NULL DEFAULT '',
  kind           TEXT NOT NULL DEFAULT 'slot-locked',  -- slot-locked | poll-recheck
  reason         TEXT NOT NULL DEFAULT '',
  lock_file      TEXT NOT NULL DEFAULT '',             -- slot lock file name at queue time
  queued_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  eligible_at    DATETIME DEFAULT CURRENT_TIMESTAMP,   -- poll-recheck: archive time + recheck delay
  attempts       INTEGER NOT NULL DEFAULT 0,
  status         TEXT NOT NULL DEFAULT 'pending',      -- pending | fired | dropped | recovered
  last_note      TEXT NOT NULL DEFAULT '',
  updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_escq_pending ON escalation_queue(status, eligible_at);
CREATE INDEX IF NOT EXISTS idx_escq_issue   ON escalation_queue(issue_id, kind);
CREATE INDEX IF NOT EXISTS idx_escq_schema_v ON escalation_queue(schema_version);

-- disk_grow_log — auto-disk-grow actuator audit + rate-cap ledger (migration 027,
-- operator directive #3, 2026-07-08). One row per grow/refusal/escalation.
CREATE TABLE IF NOT EXISTS disk_grow_log (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  hostname           TEXT NOT NULL,
  vmid               INTEGER NOT NULL,
  node               TEXT NOT NULL,
  guest_type         TEXT NOT NULL DEFAULT '',
  disk_key           TEXT NOT NULL DEFAULT '',
  storage            TEXT NOT NULL DEFAULT '',
  before_size_g      REAL NOT NULL DEFAULT 0,
  grow_g             REAL NOT NULL DEFAULT 0,
  after_size_g       REAL NOT NULL DEFAULT 0,
  fs_pct_before      INTEGER NOT NULL DEFAULT -1,
  fs_pct_after       INTEGER NOT NULL DEFAULT -1,
  pool_free_pct_after REAL NOT NULL DEFAULT -1,
  cleanup_reclaimed_g REAL NOT NULL DEFAULT 0,
  outcome            TEXT NOT NULL DEFAULT '',
  detail             TEXT NOT NULL DEFAULT '',
  grown_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_diskgrow_vmid ON disk_grow_log(vmid, grown_at);
CREATE INDEX IF NOT EXISTS idx_diskgrow_schema_v ON disk_grow_log(schema_version);

-- master_switch_log — master power-switch transition ledger (migration 028,
-- IFRNLLEI01PRD-1823, 2026-07-17). One hash-chained row per power-off/power-on of the
-- complete agentic system. Writer/verifier: scripts/lib/master_switch_audit.py (COLS lockstep).
CREATE TABLE IF NOT EXISTS master_switch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  action TEXT,
  mode TEXT,
  operator TEXT,
  reason TEXT,
  hostname TEXT,
  sentinels_json TEXT,
  cronicle_json TEXT,
  n8n_json TEXT,
  sessions_json TEXT,
  maintenance_action TEXT,
  partial INTEGER,
  details_json TEXT,
  schema_version INTEGER NOT NULL DEFAULT 1,
  prev_hash TEXT,
  row_hash TEXT
);
CREATE INDEX IF NOT EXISTS idx_master_switch_log_ts ON master_switch_log(ts);
CREATE INDEX IF NOT EXISTS idx_master_switch_log_schema_v ON master_switch_log(schema_version);
