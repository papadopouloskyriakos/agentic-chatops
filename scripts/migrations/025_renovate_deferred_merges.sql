-- 025_renovate_deferred_merges.sql
-- Renovate MR Autonomy — timeout-to-auto (2026-07-07): the operator is not reachable via Matrix/SMS,
-- so a POLL on a REVERSIBLE (minor/digest) stateful bump must not stall forever. Instead it is HELD for
-- a grace window; if not vetoed and the safety preconditions still hold, it auto-merges via the SAME
-- gate path (tested snapshot + independent floor + sha-pin + post-merge auto-rollback). never_auto
-- (secret stores) and MAJOR data-migrating bumps are NEVER timeout-auto'd — they stay parked.
-- This table is NOT hash-chained (it is a scheduling queue, not the tamper-evident decision ledger;
-- the actual merge is still recorded in renovate_autonomy_audit). Idempotent; the gate + processor also
-- CREATE TABLE IF NOT EXISTS so it works against an isolated mktemp test DB.
CREATE TABLE IF NOT EXISTS renovate_deferred_merges (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     TEXT    NOT NULL,
    mr_iid         TEXT    NOT NULL,
    head_sha       TEXT    NOT NULL,
    tier           TEXT,
    update_type    TEXT,
    package        TEXT,
    created_ts     INTEGER NOT NULL,
    deadline_ts    INTEGER NOT NULL,
    -- pending | merged | vetoed | superseded | expired | ineligible
    status         TEXT    NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    resolved_ts    INTEGER,
    reason         TEXT,
    schema_version INTEGER DEFAULT 1
);
-- One live scheduling row per (MR, commit): a new commit supersedes the old grace window.
CREATE UNIQUE INDEX IF NOT EXISTS ux_renovate_deferred_mr_sha
    ON renovate_deferred_merges (project_id, mr_iid, head_sha);
CREATE INDEX IF NOT EXISTS ix_renovate_deferred_status_deadline
    ON renovate_deferred_merges (status, deadline_ts);
