#!/usr/bin/env python3
"""Long-horizon reasoning replay (IFRNLLEI01PRD-748 / G1.P0.1).

Replays the longest historical sessions from gateway.db and scores each on four
text-only dimensions. No live Claude calls; reads only `sessions`,
`session_transcripts`, `tool_call_log`, `session_risk_audit`. Writes one row per
replayed session into `long_horizon_replay_results`.

Closes NVIDIA-DLI dim #9 (data flywheel evaluation pillar — long-horizon component)
per docs/nvidia-dli-cross-audit-2026-04-29.md Part F P0.1.

Usage:

    python3 scripts/long-horizon-replay.py --limit 30
    python3 scripts/long-horizon-replay.py --dry-run --limit 1     # smoke
    python3 scripts/long-horizon-replay.py --since 2026-04-22      # window
    python3 scripts/long-horizon-replay.py --json                  # machine-readable summary

Cron: `0 5 * * 1` (Mondays 05:00 UTC).
"""
from __future__ import annotations

import argparse
import json
import os
REDACTED_a7b84d63
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("GATEWAY_DB", str(Path.home() / "gitlab/products/cubeos/claude-context/gateway.db"))
DEFAULT_LIMIT = 30
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,}")


# ── Scoring primitives (text-only, deterministic) ────────────────────────────


def _word_set(text: str) -> set[str]:
    return set(w.lower() for w in WORD_RE.findall(text or ""))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def trace_coherence(conn: sqlite3.Connection, session_id: str) -> float:
    """Average Jaccard similarity between consecutive assistant-turn word sets."""
    cur = conn.execute(
        "SELECT content FROM session_transcripts "
        "WHERE session_id = ? AND role = 'assistant' "
        "ORDER BY chunk_index ASC",
        (session_id,),
    )
    chunks = [_word_set(r[0]) for r in cur.fetchall()]
    if len(chunks) < 2:
        return 0.0
    pairs = [_jaccard(chunks[i], chunks[i + 1]) for i in range(len(chunks) - 1)]
    return round(statistics.mean(pairs), 4)


def tool_efficiency(conn: sqlite3.Connection, session_id: str) -> float:
    """Unique tool-call signature count / total tool calls."""
    cur = conn.execute(
        "SELECT tool_name, COALESCE(operation, '') FROM tool_call_log WHERE session_id = ?",
        (session_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return 0.0
    total = len(rows)
    unique = len(set(rows))
    return round(unique / total, 4)


def poll_correctness(conn: sqlite3.Connection, session_id: str, issue_id: str | None) -> float:
    """1.0 if final disposition aligns with session_risk_audit.risk_level, else 0.0."""
    cur = conn.execute(
        "SELECT risk_level, auto_approved FROM session_risk_audit "
        "WHERE issue_id = ? ORDER BY id DESC LIMIT 1",
        (issue_id or "",),
    )
    row = cur.fetchone()
    if not row:
        return 0.0  # no audit row — undetermined; counts as 0
    risk_level, auto_ok = row[0], int(row[1] or 0)
    expected_auto = 1 if risk_level == "low" else 0
    return 1.0 if expected_auto == auto_ok else 0.0


def cost_per_turn_z(cost: float, turns: int, baseline_mean: float, baseline_std: float) -> float:
    """Z-score of this session's cost-per-turn vs historical mean. Negative = cheaper."""
    if not turns or baseline_std == 0:
        return 0.0
    cpt = cost / turns
    return round((cpt - baseline_mean) / baseline_std, 4)


# ── Core replay loop ─────────────────────────────────────────────────────────


def historical_cpt_baseline(conn: sqlite3.Connection) -> tuple[float, float]:
    """Return (mean, std) of cost-per-turn across all sessions with num_turns>0."""
    cur = conn.execute(
        "SELECT cost_usd / num_turns FROM sessions "
        "WHERE num_turns IS NOT NULL AND num_turns > 0 AND cost_usd IS NOT NULL"
    )
    series = [float(r[0]) for r in cur.fetchall()]
    if not series:
        return 0.0, 0.0
    mean = statistics.mean(series)
    std = statistics.pstdev(series) if len(series) > 1 else 0.0
    return mean, std


def candidate_sessions(conn: sqlite3.Connection, limit: int, since: str | None) -> list[dict]:
    """Pick the longest historical sessions by num_turns. session_id NOT NULL."""
    sql = (
        "SELECT issue_id, session_id, num_turns, duration_seconds, cost_usd "
        "FROM sessions WHERE session_id IS NOT NULL AND num_turns IS NOT NULL "
    )
    args: list = []
    if since:
        sql += "AND last_active >= ? "
        args.append(since)
    sql += "ORDER BY num_turns DESC LIMIT ?"
    args.append(int(limit))
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def score_session(conn: sqlite3.Connection, sess: dict, baseline: tuple[float, float]) -> dict:
    sid, iid = sess["session_id"], sess.get("issue_id")
    tc = trace_coherence(conn, sid)
    te = tool_efficiency(conn, sid)
    pc = poll_correctness(conn, sid, iid)
    cpt_z = cost_per_turn_z(
        float(sess.get("cost_usd") or 0.0),
        int(sess.get("num_turns") or 0),
        baseline[0],
        baseline[1],
    )
    # cost_per_turn z-score is mapped to a 0-1 health score: <0 (cheaper) → 1.0,
    # 0 (at mean) → 0.5, >2 std (much pricier) → 0.0.
    cost_health = max(0.0, min(1.0, 0.5 - (cpt_z / 4.0)))
    composite = round(statistics.mean([tc, te, pc, cost_health]), 4)
    return {
        "session_id": sid,
        "issue_id": iid,
        "num_turns": sess["num_turns"],
        "duration_seconds": sess.get("duration_seconds"),
        "trace_coherence": tc,
        "tool_efficiency": te,
        "poll_correctness": pc,
        "cost_per_turn_z": cpt_z,
        "composite_score": composite,
    }


def write_results(conn: sqlite3.Connection, run_id: str, scored: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO long_horizon_replay_results "
        "(run_id, session_id, issue_id, num_turns, duration_seconds, "
        " trace_coherence, tool_efficiency, poll_correctness, "
        " cost_per_turn_z, composite_score, schema_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
        [
            (
                run_id,
                s["session_id"],
                s["issue_id"],
                s["num_turns"],
                s["duration_seconds"],
                s["trace_coherence"],
                s["tool_efficiency"],
                s["poll_correctness"],
                s["cost_per_turn_z"],
                s["composite_score"],
            )
            for s in scored
        ],
    )
    conn.commit()


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--since", default=None, help="last_active >= this ISO date")
    p.add_argument("--dry-run", action="store_true", help="don't write to DB")
    p.add_argument("--json", action="store_true", help="emit JSON summary on stdout")
    p.add_argument("--db", default=DB_PATH)
    args = p.parse_args(argv)

    if not Path(args.db).exists():
        print(f"long-horizon-replay: db not found at {args.db}", file=sys.stderr)
        return 2

    run_id = "replay-" + datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")
    t0 = time.time()
    conn = sqlite3.connect(args.db, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        baseline = historical_cpt_baseline(conn)
        sessions = candidate_sessions(conn, args.limit, args.since)
        scored = [score_session(conn, s, baseline) for s in sessions]
        if not args.dry_run and scored:
            write_results(conn, run_id, scored)
    finally:
        conn.close()

    elapsed_ms = int((time.time() - t0) * 1000)
    summary = {
        "run_id": run_id,
        "db": args.db,
        "limit": args.limit,
        "since": args.since,
        "dry_run": bool(args.dry_run),
        "scored_count": len(scored),
        "baseline_cpt_mean": round(baseline[0], 6),
        "baseline_cpt_std": round(baseline[1], 6),
        "mean_composite": round(statistics.mean([s["composite_score"] for s in scored]), 4) if scored else None,
        "elapsed_ms": elapsed_ms,
    }
    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"long-horizon-replay {run_id}: scored {len(scored)} sessions, mean composite "
              f"{summary['mean_composite']}, took {elapsed_ms} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
