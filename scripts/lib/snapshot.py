"""Immutable per-turn session state snapshots (IFRNLLEI01PRD-636).

Mirrors OpenAI Agents SDK `RunState` — a write-once, append-only record of
session state captured BEFORE each tool executes. If the tool crashes the
caller (OOM, kill, network drop) we can replay from the last snapshot rather
than relying on Claude Code's JSONL tail.

Snapshot payload:
  {
    "issue_id":       "IFRNLLEI01PRD-123",
    "session_id":     "sess-abc",
    "turn_id":        5,
    "pending_tool":   "Bash",
    "pending_tool_input": {"command": "kubectl get pods"},
    "sessions_row":   { ... mirror of the sessions row fields ... },
    "usage":          { ... llm_usage sum to-date ... },
    "last_response_b64": "..."
  }

Python API:
    from snapshot import capture, latest, rollback_to
    sid = capture(issue_id, session_id, turn_id, tool_name, tool_input)
    snap = latest("IFRNLLEI01PRD-123")
    row_id, snap = rollback_to(sid)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema_version import current as schema_current  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

RETENTION_DAYS = int(os.environ.get("SNAPSHOT_RETENTION_DAYS", "7"))


@dataclass
class Snapshot:
    id: int
    issue_id: str
    session_id: str
    turn_id: int
    snapshot_at: str
    pending_tool: str
    pending_tool_input: dict[str, Any]
    snapshot_data: dict[str, Any]
    snapshot_bytes: int

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> "Snapshot":
        return cls(
            id=int(row[0]),
            issue_id=row[1] or "",
            session_id=row[2] or "",
            turn_id=int(row[3] or -1),
            snapshot_at=row[4] or "",
            pending_tool=row[5] or "",
            pending_tool_input=_safe_json(row[6], {}),
            snapshot_data=_safe_json(row[7], {}),
            snapshot_bytes=int(row[8] or 0),
        )


def _safe_json(s: Any, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _build_snapshot_data(conn: sqlite3.Connection, issue_id: str, session_id: str) -> dict[str, Any]:
    """Gather the mirrorable session state into a dict.

    Captures the sessions row + recent llm_usage total + last_response_b64 —
    the minimum a resume-after-crash replay needs.
    """
    out: dict[str, Any] = {}
    cur = conn.execute(
        "SELECT * FROM sessions WHERE issue_id = ?",
        (issue_id,),
    )
    row = cur.fetchone()
    if row is not None:
        cols = [d[0] for d in cur.description or ()]
        out["sessions_row"] = dict(zip(cols, row))
    totals = conn.execute(
        "SELECT COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), COALESCE(SUM(cost_usd),0) "
        "FROM llm_usage WHERE issue_id = ?",
        (issue_id,),
    ).fetchone()
    if totals:
        out["usage"] = {
            "input_tokens": int(totals[0]),
            "output_tokens": int(totals[1]),
            "cost_usd": float(totals[2]),
        }
    return out


def capture(
    issue_id: str,
    session_id: str,
    turn_id: int,
    pending_tool: str,
    pending_tool_input: Any,
    *,
    db_path: Optional[str] = None,
) -> int:
    """Write a snapshot row. Returns the new row id, or -1 on soft error."""
    conn = _connect(db_path)
    try:
        data = _build_snapshot_data(conn, issue_id, session_id)
        data_json = json.dumps(data, default=str, sort_keys=True)
        tool_input_json = json.dumps(pending_tool_input, default=str)
        cur = conn.execute(
            """INSERT INTO session_state_snapshot
                 (issue_id, session_id, turn_id, pending_tool,
                  pending_tool_input, snapshot_data, snapshot_bytes, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue_id, session_id, int(turn_id), pending_tool,
                tool_input_json, data_json, len(data_json),
                schema_current("session_state_snapshot"),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or -1)
    except sqlite3.Error as e:
        print(f"[snapshot] capture failed: {e}", file=sys.stderr)
        return -1
    finally:
        conn.close()


def latest(issue_id: str, db_path: Optional[str] = None) -> Optional[Snapshot]:
    """Return the most recent snapshot for `issue_id`, or None if absent."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """SELECT id, issue_id, session_id, turn_id, snapshot_at,
                      pending_tool, pending_tool_input, snapshot_data,
                      snapshot_bytes
               FROM session_state_snapshot
               WHERE issue_id = ?
               ORDER BY id DESC
               LIMIT 1""",
            (issue_id,),
        ).fetchone()
    finally:
        conn.close()
    return Snapshot.from_row(row) if row else None


def get(snapshot_id: int, db_path: Optional[str] = None) -> Optional[Snapshot]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """SELECT id, issue_id, session_id, turn_id, snapshot_at,
                      pending_tool, pending_tool_input, snapshot_data,
                      snapshot_bytes
               FROM session_state_snapshot WHERE id = ?""",
            (snapshot_id,),
        ).fetchone()
    finally:
        conn.close()
    return Snapshot.from_row(row) if row else None


def rollback_to(snapshot_id: int, db_path: Optional[str] = None) -> Optional[Snapshot]:
    """Restore the `sessions` row from a snapshot.

    Does NOT replay tool calls or side-effects — that's the caller's job. The
    snapshot is a pure data record. After rollback_to(), the caller should:

      1. Delete any queue rows written after snapshot_at.
      2. Re-read the snapshot's sessions_row to know what state to present.
      3. Optionally re-run the pending tool if it was idempotent.

    Returns the Snapshot that was rolled back to, or None if snapshot_id
    doesn't exist.
    """
    snap = get(snapshot_id, db_path)
    if snap is None:
        return None
    sessions_row = snap.snapshot_data.get("sessions_row") or {}
    if not sessions_row:
        return snap  # nothing mirrorable
    conn = _connect(db_path)
    try:
        # Narrow the update to known columns — keeps us safe if the snapshot
        # was captured with a newer/older schema than our current code.
        cur = conn.execute("PRAGMA table_info(sessions)")
        live_cols = {row[1] for row in cur.fetchall()}
        restorable = {k: v for k, v in sessions_row.items() if k in live_cols and k != "issue_id"}
        if not restorable:
            return snap
        set_clause = ", ".join(f"{col} = ?" for col in restorable)
        conn.execute(
            f"UPDATE sessions SET {set_clause} WHERE issue_id = ?",
            (*restorable.values(), snap.issue_id),
        )
        conn.commit()
    finally:
        conn.close()
    return snap


def prune(older_than_days: int = RETENTION_DAYS, db_path: Optional[str] = None) -> int:
    """Delete snapshots older than `older_than_days`. Returns rows deleted."""
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "DELETE FROM session_state_snapshot WHERE snapshot_at < datetime('now', ?)",
            (f"-{int(older_than_days)} days",),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _cli() -> int:
    """`python3 -m lib.snapshot {capture|latest|rollback|prune}` for shell."""
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cap = sub.add_parser("capture")
    p_cap.add_argument("--issue", required=True)
    p_cap.add_argument("--session", default="")
    p_cap.add_argument("--turn", type=int, default=-1)
    p_cap.add_argument("--tool", default="")
    p_cap.add_argument("--tool-input-json", default="{}")

    p_latest = sub.add_parser("latest")
    p_latest.add_argument("--issue", required=True)

    p_rb = sub.add_parser("rollback")
    p_rb.add_argument("--id", type=int, required=True)

    p_prune = sub.add_parser("prune")
    p_prune.add_argument("--days", type=int, default=RETENTION_DAYS)

    args = ap.parse_args()

    if args.cmd == "capture":
        try:
            tool_input = json.loads(args.tool_input_json)
        except ValueError:
            tool_input = {}
        rid = capture(args.issue, args.session, args.turn, args.tool, tool_input)
        print(rid)
        return 0 if rid > 0 else 1

    if args.cmd == "latest":
        snap = latest(args.issue)
        if snap is None:
            print("null")
            return 1
        json.dump({
            "id": snap.id, "issue_id": snap.issue_id, "session_id": snap.session_id,
            "turn_id": snap.turn_id, "snapshot_at": snap.snapshot_at,
            "pending_tool": snap.pending_tool,
            "pending_tool_input": snap.pending_tool_input,
            "snapshot_bytes": snap.snapshot_bytes,
            "snapshot_data": snap.snapshot_data,
        }, sys.stdout, indent=2, sort_keys=True, default=str)
        sys.stdout.write("\n")
        return 0

    if args.cmd == "rollback":
        snap = rollback_to(args.id)
        if snap is None:
            print(f"snapshot {args.id} not found", file=sys.stderr)
            return 1
        print(f"rolled back to snapshot {snap.id} (issue={snap.issue_id}, turn={snap.turn_id})")
        return 0

    if args.cmd == "prune":
        n = prune(args.days)
        print(f"pruned {n} snapshot(s) older than {args.days}d")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(_cli())
