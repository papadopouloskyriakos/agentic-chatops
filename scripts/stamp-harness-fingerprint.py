#!/usr/bin/env python3
"""Copy harness fingerprints from session_harness onto sessions / session_log (R3).

The hook (scripts/hooks/harness-fingerprint.sh) writes one session_harness row per
session_id at session start. The sessions / session_log rows are upserted later by
the Runner and the reconciler, so the fingerprint is joined onto them here, by
session_id first and by issue_id as a fallback (a session that was resumed with
`claude -r` keeps its original session_id, so the first stamp wins).

Also reports the unstamped remainder so the flywheel identity check (R6) can see it.

Usage: stamp-harness-fingerprint.py [--db PATH] [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))


def run(db_path: str, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    out = {"updated": {}, "unstamped": {}, "skipped": []}
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_harness'"
        ).fetchone():
            out["skipped"].append("session_harness table absent (migration 029 not applied)")
            return out
        for table in ("sessions", "session_log", "llm_usage"):
            if not _has_column(conn, table, "harness_fp"):
                out["skipped"].append(f"{table}.harness_fp absent (migration 029/030 not applied)")
                continue
            has_sid = _has_column(conn, table, "session_id")
            by_session = (
                f"UPDATE {table} SET harness_fp = (SELECT h.harness_fp FROM session_harness h "
                f"WHERE h.session_id = {table}.session_id) "
                f"WHERE harness_fp IS NULL AND session_id IS NOT NULL AND session_id != '' "
                f"AND EXISTS (SELECT 1 FROM session_harness h WHERE h.session_id = {table}.session_id)"
            )
            by_issue = (
                f"UPDATE {table} SET harness_fp = (SELECT h.harness_fp FROM session_harness h "
                f"WHERE h.issue_id = {table}.issue_id ORDER BY h.stamped_at ASC LIMIT 1) "
                f"WHERE harness_fp IS NULL AND issue_id IS NOT NULL "
                f"AND EXISTS (SELECT 1 FROM session_harness h WHERE h.issue_id = {table}.issue_id)"
            )
            n = 0
            for sql in ((by_session, by_issue) if has_sid else (by_issue,)):
                cur = conn.execute(sql)
                n += cur.rowcount if cur.rowcount is not None and cur.rowcount > 0 else 0
            out["updated"][table] = n
            out["unstamped"][table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE harness_fp IS NULL"
            ).fetchone()[0]
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        out = run(args.db, args.dry_run)
    except sqlite3.Error as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    if args.json:
        print(json.dumps(out, sort_keys=True))
    else:
        for t, n in out["updated"].items():
            print(f"{t}: stamped {n}, still unstamped {out['unstamped'].get(t)}")
        for s in out["skipped"]:
            print(f"skipped: {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
