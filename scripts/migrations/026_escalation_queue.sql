-- 026: escalation_queue — accepted escalations must never be silently dropped.
--
-- Two producers (2026-07-08 defect trio, session on nl-claude01):
--   * 'slot-locked'  — the Runner's "Is Locked?" TRUE branch used to terminate the
--     workflow with no queue/retry (2026-06-30 nl-pve01 power-cycle burst: 31
--     accepted escalations -> 1 session). The new "Queue Dropped Escalation" SSH
--     node writes here via scripts/queue-escalation.sh.
--   * 'poll-recheck' — reconcile-completed-sessions.py schedules a delayed re-check
--     when it archives a POLL_PAUSE session as orphaned-poll (IFRNLLEI01PRD-1536
--     went 90-95% -> 100% disk with no re-escalation).
-- One consumer: scripts/requeue-escalations.py (Cronicle */10) re-fires the normal
-- n8n youtrack-webhook (so cooldown/risk-classifier/prediction gates all still
-- apply) and never bypasses the fail-closed lane.
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
