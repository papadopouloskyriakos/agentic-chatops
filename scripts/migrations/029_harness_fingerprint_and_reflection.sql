-- 029_harness_fingerprint_and_reflection.sql — Harness² reuse batch (R3 + R5)
--
-- R3 harness fingerprint: every dispatched session is stamped with a digest of the
-- editable harness it ran under (CLAUDE.md + .claude/rules + skills + agents +
-- active prompt patches + dispatched-session hooks + the Runner Build Prompt code),
-- mirroring harness2/core/runmark.py::fingerprint. Outcome tables can then be
-- grouped by harness version instead of by an issue-hash bucket, and the trial
-- finalizer can refuse to compare arms produced under different harnesses.
--
--   harness_fingerprints : the dictionary — what each fp covered (components_json)
--   session_harness      : one row per session_id, written by the UserPromptSubmit /
--                          SessionEnd hook (scripts/hooks/harness-fingerprint.sh);
--                          copied onto sessions/session_log by
--                          scripts/stamp-harness-fingerprint.py
--
-- R5 structured reflection: lessons_learned grows the Harness² EXPERIENCE record
-- ({cue, lesson, evidence, confidence} + per-component edit rows + a domain key).
-- A row with verdict='no_entry' means reflection RAN and found nothing supported —
-- that is a valid answer (NO_ENTRY), counted by the flywheel identity check (R6).

CREATE TABLE IF NOT EXISTS harness_fingerprints (
  fp              TEXT PRIMARY KEY,                       -- 16 hex chars
  computed_at     TEXT NOT NULL DEFAULT (datetime('now')),
  repo            TEXT,                                   -- workspace the session ran in
  git_rev         TEXT,                                   -- gateway repo HEAD at compute time
  components_json TEXT NOT NULL,                          -- {component: sha1} dictionary
  schema_version  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS session_harness (
  session_id      TEXT PRIMARY KEY,
  issue_id        TEXT,
  harness_fp      TEXT NOT NULL,
  repo            TEXT,
  stamped_at      TEXT NOT NULL DEFAULT (datetime('now')),
  schema_version  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_session_harness_issue ON session_harness(issue_id);

ALTER TABLE sessions    ADD COLUMN harness_fp TEXT;
ALTER TABLE session_log ADD COLUMN harness_fp TEXT;

ALTER TABLE lessons_learned ADD COLUMN cue TEXT;
ALTER TABLE lessons_learned ADD COLUMN evidence TEXT;
ALTER TABLE lessons_learned ADD COLUMN confidence TEXT;
ALTER TABLE lessons_learned ADD COLUMN verdict TEXT;
ALTER TABLE lessons_learned ADD COLUMN domain TEXT;
ALTER TABLE lessons_learned ADD COLUMN harness_fp TEXT;
ALTER TABLE lessons_learned ADD COLUMN edits_json TEXT;
ALTER TABLE lessons_learned ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_lessons_domain ON lessons_learned(domain, created_at);
