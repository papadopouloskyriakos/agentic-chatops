#!/usr/bin/env python3
"""Flywheel identity check (R6) — the Harness² budget-ledger idea turned into a
dead-pipeline detector for the eval flywheel.

Harness² asserts after every task that exactly R=4k rollouts and P=3k improver
sessions were recorded, with no duplicate labels, so a stage that silently did not
run is caught at once. Our analogue: for every dispatched session that ENDED in the
window [now-26h, now-2h] (the judge/archive crons have had >= 2h), each downstream
stage must have produced its artefact:

  judged      session_judgment row for the issue with overall_score >= 0
  archived    session_transcripts row for the issue (non-CLI)
  outcome     session_log row for the issue with a resolution_type
  reflected   lessons_learned row for the issue (an entry OR a NO_ENTRY row)
  stamped     session_harness row for the session_id (R3 fingerprint)

and no (issue_id, session_id) may carry more than one judgment.

Exit codes: 0 identity holds, 1 identity broken, 3 idle (no eligible session in the
window — the lane may simply be quiet; the 30-day started/closed counters tell the
difference between "quiet" and "sessions start but never close").

Writes node_exporter textfile metrics when --out is given (gateway_flywheel_*).
Read-only on the gateway DB.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
DEFAULT_OUT = "/var/lib/node_exporter/textfile_collector/flywheel_identity.prom"
MIN_RATIO = float(os.environ.get("FLYWHEEL_MIN_RATIO", "0.8"))
STAGES = ("judged", "archived", "outcome", "reflected", "stamped")

# Synthetic / non-dispatched ids never count toward the identity.
EXCLUDE_LIKE = ("cli-%", "SYN%", "TEST-%", "CANARY%", "CHAOS%", "REPLAY%")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _excluded(issue_id: str) -> bool:
    iid = issue_id or ""
    for pat in EXCLUDE_LIKE:
        p = pat.rstrip("%")
        if iid.startswith(p):
            return True
    return False


def eligible_sessions(conn: sqlite3.Connection, lag_h: int, window_h: int) -> list[dict]:
    """(issue_id, session_id) for sessions that ended between now-window_h and now-lag_h."""
    rows: dict[tuple[str, str], dict] = {}
    older = f"datetime('now','-{window_h} hours')"
    newer = f"datetime('now','-{lag_h} hours')"
    if _table_exists(conn, "session_log"):
        for issue, sid in conn.execute(
            f"SELECT issue_id, COALESCE(session_id,'') FROM session_log "
            f"WHERE ended_at >= {older} AND ended_at < {newer}"
        ):
            if not _excluded(issue):
                rows[(issue, sid)] = {"issue_id": issue, "session_id": sid}
    if _table_exists(conn, "sessions"):
        for issue, sid, model in conn.execute(
            f"SELECT issue_id, COALESCE(session_id,''), COALESCE(model,'') FROM sessions "
            f"WHERE last_active >= {older} AND last_active < {newer} AND COALESCE(paused,0)=0"
        ):
            if model == "<synthetic>" or _excluded(issue):
                continue
            rows.setdefault((issue, sid), {"issue_id": issue, "session_id": sid})
    return list(rows.values())


def stage_hits(conn: sqlite3.Connection, sessions: list[dict]) -> dict[str, int]:
    hits = {s: 0 for s in STAGES}
    have = {t: _table_exists(conn, t) for t in
            ("session_judgment", "session_transcripts", "session_log", "lessons_learned", "session_harness")}
    for s in sessions:
        issue, sid = s["issue_id"], s["session_id"]
        if have["session_judgment"] and conn.execute(
            "SELECT 1 FROM session_judgment WHERE issue_id=? AND COALESCE(overall_score,-1) >= 0 LIMIT 1",
            (issue,),
        ).fetchone():
            hits["judged"] += 1
        if have["session_transcripts"] and conn.execute(
            "SELECT 1 FROM session_transcripts WHERE issue_id=? LIMIT 1", (issue,)
        ).fetchone():
            hits["archived"] += 1
        if have["session_log"] and conn.execute(
            "SELECT 1 FROM session_log WHERE issue_id=? AND resolution_type IS NOT NULL "
            "AND resolution_type != '' LIMIT 1", (issue,)
        ).fetchone():
            hits["outcome"] += 1
        if have["lessons_learned"] and conn.execute(
            "SELECT 1 FROM lessons_learned WHERE issue_id=? LIMIT 1", (issue,)
        ).fetchone():
            hits["reflected"] += 1
        if have["session_harness"] and sid and conn.execute(
            "SELECT 1 FROM session_harness WHERE session_id=? LIMIT 1", (sid,)
        ).fetchone():
            hits["stamped"] += 1
    return hits


def duplicate_judgments(conn: sqlite3.Connection, lag_h: int, window_h: int) -> int:
    if not _table_exists(conn, "session_judgment"):
        return 0
    return conn.execute(
        f"SELECT COUNT(*) FROM (SELECT issue_id, COALESCE(session_id,'') s, COUNT(*) c "
        f"FROM session_judgment WHERE judged_at >= datetime('now','-{window_h} hours') "
        f"GROUP BY issue_id, s HAVING c > 1)"
    ).fetchone()[0]


def thirty_day_counters(conn: sqlite3.Connection) -> dict[str, int]:
    out = {"started_30d": 0, "closed_30d": 0, "judged_30d": 0}
    if _table_exists(conn, "sessions"):
        out["started_30d"] = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE started_at >= datetime('now','-30 days') "
            "AND COALESCE(model,'') != '<synthetic>'"
        ).fetchone()[0]
    if _table_exists(conn, "session_log"):
        out["closed_30d"] = conn.execute(
            "SELECT COUNT(*) FROM session_log WHERE ended_at >= datetime('now','-30 days')"
        ).fetchone()[0]
        out["started_30d"] += conn.execute(
            "SELECT COUNT(*) FROM session_log WHERE started_at >= datetime('now','-30 days')"
        ).fetchone()[0]
    if _table_exists(conn, "session_judgment"):
        out["judged_30d"] = conn.execute(
            "SELECT COUNT(*) FROM session_judgment WHERE judged_at >= datetime('now','-30 days')"
        ).fetchone()[0]
    return out


def check(db_path: str, lag_h: int = 2, window_h: int = 26, min_ratio: float = MIN_RATIO) -> dict:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        sessions = eligible_sessions(conn, lag_h, window_h)
        hits = stage_hits(conn, sessions)
        dups = duplicate_judgments(conn, lag_h, window_h)
        counters = thirty_day_counters(conn)
    finally:
        conn.close()
    n = len(sessions)
    ratios = {s: (hits[s] / n if n else None) for s in STAGES}
    broken = [s for s in STAGES if n and ratios[s] is not None and ratios[s] < min_ratio]
    if dups:
        broken.append("duplicate_judgments")
    status = "idle" if n == 0 else ("broken" if broken else "ok")
    return {
        "status": status,
        "eligible": n,
        "window_hours": window_h,
        "lag_hours": lag_h,
        "min_ratio": min_ratio,
        "hits": hits,
        "ratios": ratios,
        "duplicate_judgments": dups,
        "broken_stages": broken,
        **counters,
        "checked_at": int(time.time()),
    }


def render_prom(res: dict) -> str:
    ok = 1 if res["status"] != "broken" else 0
    idle = 1 if res["status"] == "idle" else 0
    lines = [
        "# HELP gateway_flywheel_identity_ok 1 when every ended session reached every flywheel stage (R6).",
        "# TYPE gateway_flywheel_identity_ok gauge",
        f"gateway_flywheel_identity_ok {ok}",
        "# TYPE gateway_flywheel_idle gauge",
        f"gateway_flywheel_idle {idle}",
        "# TYPE gateway_flywheel_eligible_sessions gauge",
        f"gateway_flywheel_eligible_sessions {res['eligible']}",
        "# TYPE gateway_flywheel_duplicate_judgments gauge",
        f"gateway_flywheel_duplicate_judgments {res['duplicate_judgments']}",
        "# TYPE gateway_flywheel_stage_ratio gauge",
    ]
    for s in STAGES:
        r = res["ratios"][s]
        lines.append(f'gateway_flywheel_stage_ratio{{stage="{s}"}} {-1 if r is None else round(r, 4)}')
        lines.append(f'gateway_flywheel_stage_count{{stage="{s}"}} {res["hits"][s]}')
    lines += [
        "# TYPE gateway_flywheel_sessions_started_30d gauge",
        f"gateway_flywheel_sessions_started_30d {res['started_30d']}",
        "# TYPE gateway_flywheel_sessions_closed_30d gauge",
        f"gateway_flywheel_sessions_closed_30d {res['closed_30d']}",
        "# TYPE gateway_flywheel_sessions_judged_30d gauge",
        f"gateway_flywheel_sessions_judged_30d {res['judged_30d']}",
        "# TYPE gateway_flywheel_last_run_timestamp_seconds gauge",
        f"gateway_flywheel_last_run_timestamp_seconds {res['checked_at']}",
    ]
    return "\n".join(lines) + "\n"


def write_prom(res: dict, out: str) -> None:
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(render_prom(res))
    os.replace(tmp, out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--lag-hours", type=int, default=2)
    ap.add_argument("--window-hours", type=int, default=26)
    ap.add_argument("--min-ratio", type=float, default=MIN_RATIO)
    ap.add_argument("--out", nargs="?", const=DEFAULT_OUT, default=None,
                    help="write node_exporter textfile metrics (default path when bare)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        res = check(args.db, args.lag_hours, args.window_hours, args.min_ratio)
    except sqlite3.Error as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    if args.out:
        try:
            write_prom(res, args.out)
        except OSError as exc:
            print(f"metrics not written: {exc}", file=sys.stderr)
    if args.json:
        print(json.dumps(res, sort_keys=True))
    else:
        print(f"flywheel identity: {res['status']} (eligible={res['eligible']}, "
              f"started_30d={res['started_30d']}, closed_30d={res['closed_30d']}, "
              f"judged_30d={res['judged_30d']})")
        for s in STAGES:
            r = res["ratios"][s]
            print(f"  {s:<10} {res['hits'][s]:>4} / {res['eligible']:<4} "
                  f"{'-' if r is None else f'{r:.2f}'}")
        if res["duplicate_judgments"]:
            print(f"  duplicate judgments: {res['duplicate_judgments']}")
        if res["broken_stages"]:
            print(f"  BROKEN: {', '.join(res['broken_stages'])}")
    return {"ok": 0, "broken": 1, "idle": 3}[res["status"]]


if __name__ == "__main__":
    sys.exit(main())
