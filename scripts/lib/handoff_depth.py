"""Handoff depth + cycle-detection primitives (IFRNLLEI01PRD-643).

Shared helpers for:
  * reading the current depth/chain of a session
  * computing the next (depth, chain) when an agent hands off
  * enforcing the two thresholds (POLL at >=5, hard-halt at >=10)
  * detecting cycles (an agent name appearing twice in the chain)

Emits session_events.HandoffCycleDetectedEvent on cycle detection so the
Matrix bridge and Grafana can see it in real time.

Callers: scripts/lib/handoff.py (HandoffInputData), Build Prompt SSH nodes,
and the depth-counter cron (scripts/write-handoff-metrics.sh).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema_version import current as schema_current  # noqa: E402
from session_events import (  # noqa: E402
    HandoffCycleDetectedEvent,
    HandoffRequestedEvent,
    emit,
)

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

# Thresholds — keep in sync with the runbook + CLAUDE.md note.
POLL_DEPTH_THRESHOLD = int(os.environ.get("HANDOFF_POLL_DEPTH", "5"))
HALT_DEPTH_THRESHOLD = int(os.environ.get("HANDOFF_HALT_DEPTH", "10"))


class HandoffDepthExceeded(RuntimeError):
    """Raised when handoff_depth reaches HALT_DEPTH_THRESHOLD.

    Callers should catch this, post a [POLL] or similar operator-facing
    notice, and refuse to spawn further sub-agents until human ack.
    """


class HandoffCycleDetected(RuntimeError):
    """Raised when an agent name appears twice in the same handoff chain."""


@dataclass
class DepthState:
    depth: int = 0
    chain: list[str] = None  # type: ignore[assignment]  # replaced in __post_init__
    should_poll: bool = False
    should_halt: bool = False
    cycle_agent: Optional[str] = None

    def __post_init__(self):
        if self.chain is None:
            self.chain = []


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    # isolation_level=None puts Python's sqlite3 in manual-transaction mode,
    # so our explicit BEGIN IMMEDIATE / COMMIT / ROLLBACK actually drive the
    # transaction. Default mode wraps every statement in its own implicit
    # transaction, which defeats IMMEDIATE and allows lost updates under
    # concurrent bumps (seen in qa/643-concurrent).
    conn = sqlite3.connect(db_path or DB_PATH, timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def read(issue_id: str, db_path: Optional[str] = None) -> DepthState:
    """Read current (depth, chain) for a session and compute threshold flags."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT handoff_depth, handoff_chain FROM sessions WHERE issue_id = ?",
            (issue_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return DepthState(depth=0, chain=[], should_poll=False, should_halt=False)
    depth = int(row[0] or 0)
    try:
        chain = json.loads(row[1] or "[]")
        if not isinstance(chain, list):
            chain = []
    except (TypeError, ValueError):
        chain = []
    return DepthState(
        depth=depth,
        chain=chain,
        should_poll=depth >= POLL_DEPTH_THRESHOLD,
        should_halt=depth >= HALT_DEPTH_THRESHOLD,
    )


def next_state(current: DepthState, to_agent: str) -> DepthState:
    """Compute what the (depth, chain) would be if `to_agent` joined now.

    Does NOT write anything. Use bump() after this if the caller decides to
    proceed. Returns a DepthState; caller checks `cycle_agent` to decide
    whether to raise.
    """
    new_chain = list(current.chain) + [to_agent]
    new_depth = current.depth + 1
    cycle = to_agent if to_agent in current.chain else None
    return DepthState(
        depth=new_depth,
        chain=new_chain,
        should_poll=new_depth >= POLL_DEPTH_THRESHOLD,
        should_halt=new_depth >= HALT_DEPTH_THRESHOLD or cycle is not None,
        cycle_agent=cycle,
    )


def bump(
    issue_id: str,
    from_agent: str,
    to_agent: str,
    *,
    session_id: str = "",
    turn_id: int = -1,
    reason: str = "",
    db_path: Optional[str] = None,
) -> DepthState:
    """Atomically increment depth + append to chain for `issue_id`.

    Emits HandoffRequestedEvent always, HandoffCycleDetectedEvent if the
    new to_agent was already in the chain. Raises HandoffDepthExceeded or
    HandoffCycleDetected so callers stop before actually spawning.

    Thread-safe: uses sqlite immediate transaction so concurrent bumps see
    a consistent before/after view.
    """
    conn = _connect(db_path)
    committed = False
    nxt: Optional[DepthState] = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT handoff_depth, handoff_chain FROM sessions WHERE issue_id = ?",
            (issue_id,),
        ).fetchone()
        if row is None:
            cur = DepthState()
        else:
            try:
                chain = json.loads(row[1] or "[]")
            except (TypeError, ValueError):
                chain = []
            cur = DepthState(depth=int(row[0] or 0), chain=chain)
        nxt = next_state(cur, to_agent)

        if nxt.cycle_agent is None and nxt.depth < HALT_DEPTH_THRESHOLD:
            # Safe to persist.
            if row is None:
                conn.execute(
                    """INSERT INTO sessions (issue_id, handoff_depth, handoff_chain, schema_version)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(issue_id) DO UPDATE SET
                         handoff_depth=excluded.handoff_depth,
                         handoff_chain=excluded.handoff_chain""",
                    (issue_id, nxt.depth, json.dumps(nxt.chain), schema_current("sessions")),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET handoff_depth = ?, handoff_chain = ? WHERE issue_id = ?",
                    (nxt.depth, json.dumps(nxt.chain), issue_id),
                )
            conn.execute("COMMIT")
            committed = True
        else:
            # Refuse: cycle or halt.
            conn.execute("ROLLBACK")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Emit telemetry AFTER the bump transaction releases the write lock.
    # Swallow any emit failure — telemetry should never mask the bump result.
    if nxt is not None:
        try:
            emit(HandoffRequestedEvent(
                issue_id=issue_id,
                session_id=session_id,
                turn_id=turn_id,
                from_agent=from_agent,
                to_agent=to_agent,
                handoff_depth=nxt.depth,
                handoff_chain=nxt.chain,
                reason=reason,
            ), db_path=db_path)
        except Exception:
            pass
        if nxt.cycle_agent is not None:
            try:
                emit(HandoffCycleDetectedEvent(
                    issue_id=issue_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    from_agent=from_agent,
                    to_agent=to_agent,
                    handoff_chain=nxt.chain,
                ), db_path=db_path)
            except Exception:
                pass
            raise HandoffCycleDetected(
                f"handoff cycle: {to_agent!r} already in chain {nxt.chain[:-1]}"
            )
        if nxt.depth >= HALT_DEPTH_THRESHOLD and not committed:
            raise HandoffDepthExceeded(
                f"handoff_depth={nxt.depth} >= {HALT_DEPTH_THRESHOLD} (hard halt)"
            )
    return nxt  # type: ignore[return-value]


def _cli() -> int:
    """`python3 -m lib.handoff_depth <issue_id>` prints current state as JSON."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("issue_id")
    ap.add_argument("--bump-to", help="simulate / perform a bump to this agent name")
    ap.add_argument("--from", dest="from_agent", default="", help="parent agent")
    ap.add_argument("--dry-run", action="store_true", help="don't write, just show next")
    args = ap.parse_args()

    cur = read(args.issue_id)
    if not args.bump_to:
        print(json.dumps({
            "issue_id": args.issue_id,
            "depth": cur.depth,
            "chain": cur.chain,
            "should_poll": cur.should_poll,
            "should_halt": cur.should_halt,
        }, indent=2))
        return 0

    if args.dry_run:
        nxt = next_state(cur, args.bump_to)
        print(json.dumps({
            "would_depth": nxt.depth,
            "would_chain": nxt.chain,
            "would_poll": nxt.should_poll,
            "would_halt": nxt.should_halt,
            "cycle_agent": nxt.cycle_agent,
        }, indent=2))
        return 0

    try:
        nxt = bump(args.issue_id, args.from_agent or "unknown", args.bump_to)
    except HandoffCycleDetected as e:
        print(json.dumps({"error": "cycle", "detail": str(e)}))
        return 3
    except HandoffDepthExceeded as e:
        print(json.dumps({"error": "halt", "detail": str(e)}))
        return 4
    print(json.dumps({
        "depth": nxt.depth,
        "chain": nxt.chain,
        "should_poll": nxt.should_poll,
        "should_halt": nxt.should_halt,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
