"""Per-turn session counter + upsert (IFRNLLEI01PRD-638).

Owns writes to the `session_turns` table. Called from the Claude Code
PostToolUse / Stop / SessionEnd hooks via `scripts/emit-turn.py`.

Concurrency: hooks fire serially per session (Claude Code waits for the
PreToolUse hook to return before running the next tool). The `session_id +
turn_id` unique index prevents double-write races even if two hooks collide.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema_version import current as schema_current  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def begin_turn(
    issue_id: str,
    session_id: str,
    turn_id: int,
    db_path: Optional[str] = None,
) -> int:
    """Create a session_turns row with started_at now. Returns row id.

    If a row for (session_id, turn_id) already exists (e.g. a hook re-fired
    after a retry), this is a no-op and returns the existing row id.
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO session_turns
               (issue_id, session_id, turn_id, schema_version)
               VALUES (?, ?, ?, ?)""",
            (issue_id, session_id, turn_id, schema_current("session_turns")),
        )
        row_id = int(cur.lastrowid or -1)
        conn.commit()
        if row_id <= 0:
            # Existing row. Look it up.
            existing = conn.execute(
                "SELECT id FROM session_turns WHERE session_id = ? AND turn_id = ?",
                (session_id, turn_id),
            ).fetchone()
            row_id = int(existing[0]) if existing else -1
        return row_id
    finally:
        conn.close()


def record_tool_call(
    session_id: str,
    turn_id: int,
    *,
    is_error: bool = False,
    db_path: Optional[str] = None,
) -> None:
    """Increment tool_count (and tool_errors if is_error) on the turn row."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE session_turns
               SET tool_count = tool_count + 1,
                   tool_errors = tool_errors + ?
               WHERE session_id = ? AND turn_id = ?""",
            (1 if is_error else 0, session_id, turn_id),
        )
        conn.commit()
    finally:
        conn.close()


def end_turn(
    session_id: str,
    turn_id: int,
    *,
    llm_cost_usd: float = 0.0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    duration_ms: int = -1,
    db_path: Optional[str] = None,
) -> None:
    """Finalise a turn with ended_at + token/cost metrics."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE session_turns SET
                 ended_at          = CURRENT_TIMESTAMP,
                 llm_cost_usd      = llm_cost_usd + ?,
                 input_tokens      = input_tokens + ?,
                 output_tokens     = output_tokens + ?,
                 cache_read_tokens = cache_read_tokens + ?,
                 cache_write_tokens = cache_write_tokens + ?,
                 duration_ms       = ?
               WHERE session_id = ? AND turn_id = ?""",
            (
                float(llm_cost_usd), int(input_tokens), int(output_tokens),
                int(cache_read_tokens), int(cache_write_tokens), int(duration_ms),
                session_id, turn_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _cli() -> int:
    """`python3 -m lib.turn_counter {begin|tool|end}` — called from bash hooks."""
    import argparse, json
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_begin = sub.add_parser("begin")
    p_begin.add_argument("--issue", default="")
    p_begin.add_argument("--session", required=True)
    p_begin.add_argument("--turn", type=int, required=True)

    p_tool = sub.add_parser("tool")
    p_tool.add_argument("--session", required=True)
    p_tool.add_argument("--turn", type=int, required=True)
    p_tool.add_argument("--error", action="store_true")

    p_end = sub.add_parser("end")
    p_end.add_argument("--session", required=True)
    p_end.add_argument("--turn", type=int, required=True)
    p_end.add_argument("--cost", type=float, default=0.0)
    p_end.add_argument("--input-tokens", type=int, default=0)
    p_end.add_argument("--output-tokens", type=int, default=0)
    p_end.add_argument("--cache-read", type=int, default=0)
    p_end.add_argument("--cache-write", type=int, default=0)
    p_end.add_argument("--duration-ms", type=int, default=-1)

    args = ap.parse_args()
    if args.cmd == "begin":
        rid = begin_turn(args.issue, args.session, args.turn)
        print(rid)
        return 0
    if args.cmd == "tool":
        record_tool_call(args.session, args.turn, is_error=args.error)
        return 0
    if args.cmd == "end":
        end_turn(
            args.session, args.turn,
            llm_cost_usd=args.cost,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            cache_read_tokens=args.cache_read,
            cache_write_tokens=args.cache_write,
            duration_ms=args.duration_ms,
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
