#!/usr/bin/env python3
"""renovate_deferred.py — the timeout-to-auto scheduling queue for the Renovate MR Autonomy lane.

WHY: the operator is not reachable via Matrix/SMS, so a POLL on a REVERSIBLE stateful bump would stall
forever (the exact anti-pattern the autonomy-forward gate killed on the incident side). Instead the gate
records a deferred entry with a grace deadline; `renovate-deferred-merge-processor.py` (cron) re-invokes
the gate with RENOVATE_DEFERRED_ELAPSED=1 once the window elapses, and — if not vetoed and every safety
gate still passes — the merge happens through the SAME path (tested snapshot + independent floor + sha-pin
+ post-merge auto-rollback). The human is a break-glass (veto label / close the MR), not the bottleneck.

ELIGIBILITY (single source of truth): a bump is timeout-auto-eligible iff it is
  - NOT a never_auto engine (openbao / vault — secret stores, near-irreversible), AND
  - tier is 'critical' or 'elevated' (routine already auto-merges at canary; this is for the tiers the
    rollout stage POLLs), AND
  - update_type is REVERSIBLE (minor/patch/digest/lockfile — reverting the tag restores; a MAJOR is a
    potential one-way on-disk migration and is NEVER timeout-auto'd).

This table is a scheduling queue, NOT the tamper-evident decision ledger — the actual merge is still
recorded in renovate_autonomy_audit via the hash chain.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time

SCHEMA_VERSION = 1
DEFAULT_DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")

# Reverting the image TAG is a restore path for these — no one-way data migration.
REVERSIBLE_UPDATE_TYPES = {"minor_patch", "minor", "patch", "digest", "lockfile"}
# Tiers the rollout stage POLLs (routine auto-merges already; these are the held stateful/breaking ones).
DEFERRABLE_TIERS = {"critical", "elevated"}
STATUSES = {"pending", "merged", "vetoed", "superseded", "expired", "ineligible"}


def eligible(tier: str, update_type: str, never_auto) -> bool:
    na = never_auto in (True, "true", "1", 1)
    return (not na) and (tier in DEFERRABLE_TIERS) and (update_type in REVERSIBLE_UPDATE_TYPES)


def _conn(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    return c


def ensure_table(db: str) -> None:
    with _conn(db) as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS renovate_deferred_merges (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, mr_iid TEXT NOT NULL,
                 head_sha TEXT NOT NULL, tier TEXT, update_type TEXT, package TEXT,
                 created_ts INTEGER NOT NULL, deadline_ts INTEGER NOT NULL,
                 status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                 resolved_ts INTEGER, reason TEXT, schema_version INTEGER DEFAULT 1)"""
        )
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_renovate_deferred_mr_sha "
            "ON renovate_deferred_merges(project_id, mr_iid, head_sha)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS ix_renovate_deferred_status_deadline "
            "ON renovate_deferred_merges(status, deadline_ts)"
        )


def record(db, project_id, mr_iid, head_sha, tier, update_type, package, grace_hours, now=None) -> int:
    """Upsert a PENDING deferred entry for (project, iid, sha). Returns the deadline_ts. Re-recording the
    same (project,iid,sha) keeps the ORIGINAL deadline (idempotent across repeated gate runs on the same
    commit — the grace window does not slide forward every time Renovate re-touches the MR)."""
    now = int(now if now is not None else time.time())
    deadline = now + int(grace_hours) * 3600
    ensure_table(db)
    with _conn(db) as c:
        row = c.execute(
            "SELECT deadline_ts, status FROM renovate_deferred_merges "
            "WHERE project_id=? AND mr_iid=? AND head_sha=?",
            (str(project_id), str(mr_iid), str(head_sha)),
        ).fetchone()
        if row and row[1] == "pending":
            return int(row[0])  # keep original deadline
        c.execute(
            """INSERT INTO renovate_deferred_merges
                 (project_id, mr_iid, head_sha, tier, update_type, package, created_ts, deadline_ts,
                  status, attempts, schema_version)
               VALUES (?,?,?,?,?,?,?,?, 'pending', 0, ?)
               ON CONFLICT(project_id, mr_iid, head_sha) DO UPDATE SET
                 status='pending', tier=excluded.tier, update_type=excluded.update_type,
                 package=excluded.package, resolved_ts=NULL, reason=NULL""",
            (str(project_id), str(mr_iid), str(head_sha), tier, update_type, package, now, deadline,
             SCHEMA_VERSION),
        )
    return deadline


def mark(db, project_id, mr_iid, head_sha, status, reason=None, now=None) -> None:
    now = int(now if now is not None else time.time())
    ensure_table(db)
    with _conn(db) as c:
        c.execute(
            "UPDATE renovate_deferred_merges SET status=?, reason=?, resolved_ts=? "
            "WHERE project_id=? AND mr_iid=? AND head_sha=?",
            (status, reason, (None if status == "pending" else now), str(project_id), str(mr_iid),
             str(head_sha)),
        )


def bump_attempt(db, project_id, mr_iid, head_sha) -> None:
    ensure_table(db)
    with _conn(db) as c:
        c.execute(
            "UPDATE renovate_deferred_merges SET attempts=attempts+1 "
            "WHERE project_id=? AND mr_iid=? AND head_sha=?",
            (str(project_id), str(mr_iid), str(head_sha)),
        )


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def list_due(db, now=None):
    """PENDING entries whose grace window has elapsed — ready for the processor to attempt."""
    now = int(now if now is not None else time.time())
    ensure_table(db)
    with _conn(db) as c:
        return _rows(c.execute(
            "SELECT * FROM renovate_deferred_merges WHERE status='pending' AND deadline_ts<=? "
            "ORDER BY deadline_ts", (now,)))


def list_pending(db):
    ensure_table(db)
    with _conn(db) as c:
        return _rows(c.execute(
            "SELECT * FROM renovate_deferred_merges WHERE status='pending' ORDER BY deadline_ts"))


def count_merged_today(db, now=None) -> int:
    now = int(now if now is not None else time.time())
    start = now - (now % 86400)
    ensure_table(db)
    with _conn(db) as c:
        return c.execute(
            "SELECT COUNT(*) FROM renovate_deferred_merges WHERE status='merged' AND resolved_ts>=?",
            (start,)).fetchone()[0]


def main() -> int:
    import argparse
    import json

    common = argparse.ArgumentParser(add_help=False)      # so --db works before OR after the subcommand
    common.add_argument("--db", default=DEFAULT_DB)
    ap = argparse.ArgumentParser(description=__doc__, parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("record", parents=[common])
    for a in ("project", "iid", "sha", "tier", "update-type", "package"):
        p.add_argument("--" + a, required=a in ("project", "iid", "sha"))
    p.add_argument("--grace-hours", type=float, default=48)
    p.add_argument("--now", type=int)
    m = sub.add_parser("mark", parents=[common])
    for a in ("project", "iid", "sha", "status"):
        m.add_argument("--" + a, required=True)
    m.add_argument("--reason")
    m.add_argument("--now", type=int)
    sub.add_parser("list-due", parents=[common]).add_argument("--now", type=int)
    sub.add_parser("list-pending", parents=[common])
    sub.add_parser("count-merged-today", parents=[common]).add_argument("--now", type=int)
    el = sub.add_parser("eligible", parents=[common])
    el.add_argument("--tier", required=True)
    el.add_argument("--update-type", required=True)
    el.add_argument("--never-auto", default="false")
    a = ap.parse_args()

    if a.cmd == "record":
        d = record(a.db, a.project, a.iid, a.sha, a.tier, a.update_type, a.package, a.grace_hours, a.now)
        print(d)
    elif a.cmd == "mark":
        mark(a.db, a.project, a.iid, a.sha, a.status, a.reason, a.now)
    elif a.cmd == "list-due":
        print(json.dumps(list_due(a.db, a.now)))
    elif a.cmd == "list-pending":
        print(json.dumps(list_pending(a.db)))
    elif a.cmd == "count-merged-today":
        print(count_merged_today(a.db, a.now))
    elif a.cmd == "eligible":
        print("1" if eligible(a.tier, a.update_type, a.never_auto) else "0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
