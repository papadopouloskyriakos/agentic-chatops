#!/usr/bin/env python3
"""Close stale open quiz sessions.

A learning_sessions row with session_type='quiz' and completed_at IS NULL
represents a quiz the operator started but never answered. cmd_grade(sid=0)
routes free-text DM replies to the MOST RECENT such row, so older ones
don't actively block anything — but they clutter the session log and skew
the Prometheus learning_weekly_sessions_total metric (which counts open
sessions in its window).

This script closes any quiz/chat session that's been open for more than
`--max-age-days` days (default 7). On close, `completed_at` is set to now
and a `judge_feedback` note records the auto-closure so a human reader
knows it wasn't a real operator action.

Daily cron:
  0 4 * * * python3 scripts/close-stale-learning-sessions.py

Safe to run on an empty DB. Idempotent.
"""
from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get(
        "GATEWAY_DB",
        os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
    ))
    ap.add_argument("--max-age-days", type=int, default=7,
                    help="Sessions older than this many days get closed (default 7)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 0  # not an error — DB may not exist on fresh hosts

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        # Pick stale open sessions
        rows = conn.execute(
            "SELECT id, operator, topic, session_type, started_at "
            "FROM learning_sessions "
            "WHERE completed_at IS NULL "
            "  AND session_type IN ('quiz', 'chat') "
            "  AND started_at < datetime('now', ?)",
            (f"-{args.max_age_days} days",),
        ).fetchall()
        if not rows:
            print(f"[close-stale] nothing to close (>{args.max_age_days}d)")
            return 0

        print(f"[close-stale] found {len(rows)} stale session(s):")
        for r in rows:
            print(f"  #{r['id']:<6d} {r['session_type']:<5s} {r['operator']}  {r['topic']}  started={r['started_at']}")

        if args.dry_run:
            print("[close-stale] --dry-run: not closing")
            return 0

        close_note = (f"auto-closed by close-stale-learning-sessions.py at "
                      f"{datetime.datetime.utcnow().isoformat()}Z — session was "
                      f"open >{args.max_age_days}d with no completion")
        ids = [r["id"] for r in rows]
        conn.executemany(
            "UPDATE learning_sessions SET completed_at=CURRENT_TIMESTAMP, "
            "judge_feedback=COALESCE(judge_feedback, '') || ? "
            "WHERE id=?",
            [(close_note, i) for i in ids],
        )
        conn.commit()
        print(f"[close-stale] closed {len(ids)} session(s)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
