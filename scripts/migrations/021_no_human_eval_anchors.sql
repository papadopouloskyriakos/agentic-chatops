-- 021_no_human_eval_anchors.sql — IFRNLLEI01PRD-1451 (no-human ground-truth anchors)
--
-- Two automated ground-truth anchors that calibrate the LLM judge (session_judgment)
-- WITHOUT any operator involvement (the operator is deliberately absent — autonomy-forward;
-- a human-label table would just sit empty + fire a stale alert = a new dark component).
-- See memory/feedback_no_human_anchor_for_absent_operator.md.
--
--  (1) judge_crosscheck    — frontier-model (Opus) re-judges a sample vs the local gemma judge;
--                            divergence = the local judge drifted. Catches the dead-judge class
--                            (Opus scores 4.5 while local returns -1 -> huge divergence -> alert).
--  (2) autoresolve_outcome — did an auto-resolved session's fix actually HOLD (the incident's
--                            alert cleared AND did not re-fire within a window)? Real-world outcome
--                            truth: a session that "resolved" something which re-fired is a
--                            false-resolve regardless of what the judge said.

CREATE TABLE IF NOT EXISTS judge_crosscheck (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id        TEXT NOT NULL,
  checked_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  local_model     TEXT DEFAULT '',     -- the local judge model under test (e.g. gemma3:12b)
  local_score     INTEGER DEFAULT -1,  -- local judge overall_score (1-5; -1 = unscored, the dead-judge signal)
  local_action    TEXT DEFAULT '',     -- local recommended_action: approve|improve|reject
  frontier_model  TEXT DEFAULT '',     -- the frontier reference model (e.g. claude-opus-4-8)
  frontier_score  INTEGER DEFAULT -1,  -- frontier overall_score (1-5; -1 = frontier itself failed)
  frontier_action TEXT DEFAULT '',     -- frontier recommended_action
  score_delta     INTEGER DEFAULT -999,-- frontier_score - local_score (-999 = not computable)
  action_agree    INTEGER DEFAULT -1,  -- 1 if local_action == frontier_action, 0 if not, -1 = n/a
  schema_version  INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_jcc_issue   ON judge_crosscheck(issue_id);
CREATE INDEX IF NOT EXISTS idx_jcc_checked ON judge_crosscheck(checked_at);

CREATE TABLE IF NOT EXISTS autoresolve_outcome (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id            TEXT NOT NULL,
  resolution_type     TEXT DEFAULT '',     -- e.g. auto_resolved
  resolved_at         DATETIME,            -- when the session ended/resolved
  evaluated_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  held                INTEGER DEFAULT -1,  -- 1 = fix held (no re-fire), 0 = re-fired (false-resolve), -1 = pending (window not elapsed)
  refire_issue_id     TEXT DEFAULT '',     -- the re-fire session id when held=0
  refire_within_hours REAL DEFAULT -1,     -- hours between resolve and the re-fire (-1 = n/a)
  judge_score         INTEGER DEFAULT -1,  -- the judge's overall_score for this session (for calibration)
  judge_action        TEXT DEFAULT '',     -- the judge's recommended_action (for calibration)
  schema_version      INTEGER DEFAULT 1,
  UNIQUE(issue_id)
);
CREATE INDEX IF NOT EXISTS idx_aro_issue     ON autoresolve_outcome(issue_id);
CREATE INDEX IF NOT EXISTS idx_aro_evaluated ON autoresolve_outcome(evaluated_at);
CREATE INDEX IF NOT EXISTS idx_aro_held      ON autoresolve_outcome(held);
