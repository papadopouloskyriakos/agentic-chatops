-- 023_session_trajectory_dedupe.sql — one grade row per issue_id (IFRNLLEI01PRD-1571 #3)
--
-- session_trajectory had NO uniqueness on issue_id, so every re-grade of a session appended a new row
-- (live: 1162 rows / 741 distinct issue_id → ~421 stale duplicate grades; session_id is unused so
-- issue_id is the natural key). A stale duplicate already clobbered a downstream read. Fix:
--   1) collapse to the LATEST grade per issue_id (max id = most-recently inserted = newest grade),
--   2) add a UNIQUE index so re-grades UPSERT instead of appending (score-trajectory.sh now uses
--      INSERT OR REPLACE).
-- Both statements are idempotent: after the first run there are no dupes (DELETE is a no-op) and the
-- index is IF NOT EXISTS. The DELETE MUST precede the unique index (a still-duplicated table would
-- reject the constraint).
DELETE FROM session_trajectory
 WHERE id NOT IN (SELECT MAX(id) FROM session_trajectory GROUP BY issue_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_session_trajectory_issue ON session_trajectory(issue_id);
