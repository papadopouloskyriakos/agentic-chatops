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
  model         TEXT DEFAULT ''
);

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
  model         TEXT DEFAULT ''
);

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
  notes         TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS wiki_articles (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  path          TEXT NOT NULL UNIQUE,
  title         TEXT NOT NULL,
  section       TEXT DEFAULT '',
  content_hash  TEXT NOT NULL,
  embedding     TEXT DEFAULT '',
  compiled_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  source_files  TEXT DEFAULT ''
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
  source_file   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_st_issue ON session_transcripts(issue_id);
CREATE INDEX IF NOT EXISTS idx_st_session ON session_transcripts(session_id);

CREATE TABLE IF NOT EXISTS agent_diary (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_name    TEXT NOT NULL,
  issue_id      TEXT DEFAULT '',
  entry         TEXT NOT NULL,
  tags          TEXT DEFAULT '',
  embedding     TEXT DEFAULT '',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ad_agent ON agent_diary(agent_name);
CREATE INDEX IF NOT EXISTS idx_ad_created ON agent_diary(created_at);

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
  recommended_action TEXT DEFAULT ''
);

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
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tcl_tool ON tool_call_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_tcl_session ON tool_call_log(session_id);
CREATE INDEX IF NOT EXISTS idx_tcl_created ON tool_call_log(created_at);

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
  created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_el_session ON execution_log(session_id);
CREATE INDEX IF NOT EXISTS idx_el_issue ON execution_log(issue_id);
CREATE INDEX IF NOT EXISTS idx_el_device ON execution_log(device);

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
