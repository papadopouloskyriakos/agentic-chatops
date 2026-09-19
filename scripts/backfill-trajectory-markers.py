#!/usr/bin/env python3
"""backfill-trajectory-markers.py — retroactively correct trajectory-scorer false-negatives
(IFRNLLEI01PRD-1713, 2026-07-08).

The trajectory scorer historically detected investigation only from literal CLI strings in the
ephemeral JSONL ('ssh ', 'kubectl '), missing MCP-tool investigation and going blind once the JSONL
was GC'd — so real infra sessions scored < 75 ('structurally thin') and branded the judge 'fooled'
for correctly approving them. score-trajectory.sh is now fixed forward (tool_call_log enrichment);
this applies the SAME correction to EXISTING session_trajectory rows, which cannot be re-scored the
normal way (their sessions rows are archived).

EVIDENCE-BASED and RAISE-ONLY: a marker is set to 1 only when tool_call_log (persistent, structured)
or the row's own stored tool_calls count PROVES the investigation the original grep missed. A
genuinely-thin session (few tool calls, no investigation tools) is never raised. Never lowers a
marker or a score.

  backfill-trajectory-markers.py --dry-run        # show what would change
  backfill-trajectory-markers.py                  # apply (only rows with trajectory_score < 75)
  backfill-trajectory-markers.py --issue <id>     # one issue
"""
from __future__ import annotations

import argparse
import os
REDACTED_a7b84d63
import sqlite3
import sys

DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
COARSE_TOOLCALLS = int(os.environ.get("TRAJ_COARSE_TOOLCALLS", "5"))

EVID = re.compile(r"kubernetes|proxmox|kubectl|exec_in_pod|^Bash$|ios_|asa_|codegraph", re.I)
NETBOX = re.compile(r"netbox", re.I)
YT = re.compile(r"youtrack.*(add_comment|update_issue)|yt.?post.?comment", re.I)
KB = re.compile(r"ToolSearch|codegraph|semantic|kb.?search|incident", re.I)


def enriched_markers(conn, issue_id, cur):
    """Return the possibly-raised (netbox, kb, evidence, ssh, yt) markers for an issue, from
    tool_call_log + the stored tool_calls coarse fallback. `cur` = current marker dict."""
    n, kb, ev, ssh, yt = (cur["has_netbox_lookup"], cur["has_incident_kb_query"],
                          cur["has_evidence_commands"], cur["has_ssh_investigation"], cur["has_yt_comment"])
    tools = [r[0] for r in conn.execute(
        "SELECT DISTINCT tool_name FROM tool_call_log WHERE issue_id=?", (issue_id,)).fetchall() if r[0]]
    blob = "\n".join(tools)
    if blob:
        if NETBOX.search(blob):
            n = 1
        if EVID.search(blob):
            ev = ssh = 1
        if YT.search(blob):
            yt = 1
        if KB.search(blob):
            kb = 1
    # coarse: substantial real activity is investigation even if no tool_call_log rows survive
    if int(cur["tool_calls"] or 0) >= COARSE_TOOLCALLS:
        ev = ssh = 1
    # KB/incident context is AUTO-INJECTED into every infra session's prompt (5-signal RRF) — the
    # session never 'queries' it, so has_incident_kb_query is a structural false-negative. Credit it
    # for an infra session (steps_expected=8) that actually investigated (has evidence). A thin
    # session with no investigation stays uncredited.
    if ev:
        kb = 1
    return n, kb, ev, ssh, yt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--issue", default="")
    ap.add_argument("--all-scores", action="store_true",
                    help="consider all rows, not just trajectory_score < 75")
    args = ap.parse_args()

    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    where = "WHERE steps_expected=8"
    params = []
    if not args.all_scores:
        where += " AND trajectory_score < 75"
    if args.issue:
        where += " AND issue_id=?"
        params.append(args.issue)
    # latest trajectory row per issue
    rows = conn.execute(
        f"SELECT * FROM session_trajectory {where} AND graded_at=("
        f"  SELECT MAX(graded_at) FROM session_trajectory t2 WHERE t2.issue_id=session_trajectory.issue_id)"
        f" ORDER BY trajectory_score", params).fetchall()

    changed = 0
    for r in rows:
        cur = dict(r)
        n, kb, ev, ssh, yt = enriched_markers(conn, r["issue_id"], cur)
        new = {"has_netbox_lookup": n, "has_incident_kb_query": kb, "has_evidence_commands": ev,
               "has_ssh_investigation": ssh, "has_yt_comment": yt}
        # RAISE-ONLY guard
        new = {k: max(int(cur[k] or 0), v) for k, v in new.items()}
        steps = (new["has_netbox_lookup"] + new["has_incident_kb_query"] + int(cur["has_react_structure"] or 0)
                 + int(cur["has_poll_or_approval"] or 0) + int(cur["has_confidence"] or 0)
                 + new["has_evidence_commands"] + new["has_ssh_investigation"] + new["has_yt_comment"])
        score = min(100, steps * 100 // 8)
        if score <= int(cur["trajectory_score"] or 0) and all(new[k] == int(cur[k] or 0) for k in new):
            continue  # nothing to raise
        delta = f"{cur['issue_id']}: score {cur['trajectory_score']}->{score} steps ->{steps}/8 " \
                f"(netbox{cur['has_netbox_lookup']}->{new['has_netbox_lookup']} kb{cur['has_incident_kb_query']}->{new['has_incident_kb_query']} " \
                f"evid{cur['has_evidence_commands']}->{new['has_evidence_commands']} ssh{cur['has_ssh_investigation']}->{new['has_ssh_investigation']} " \
                f"yt{cur['has_yt_comment']}->{new['has_yt_comment']}) tool_calls={cur['tool_calls']}"
        print(("DRY " if args.dry_run else "SET ") + delta)
        if not args.dry_run:
            conn.execute(
                "UPDATE session_trajectory SET has_netbox_lookup=?, has_incident_kb_query=?, "
                "has_evidence_commands=?, has_ssh_investigation=?, has_yt_comment=?, "
                "steps_completed=?, trajectory_score=?, notes=COALESCE(notes,'')||' [markers-backfilled-1713]' "
                "WHERE id=?",
                (new["has_netbox_lookup"], new["has_incident_kb_query"], new["has_evidence_commands"],
                 new["has_ssh_investigation"], new["has_yt_comment"], steps, score, r["id"]))
        changed += 1
    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"{'would change' if args.dry_run else 'changed'} {changed} trajectory row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
