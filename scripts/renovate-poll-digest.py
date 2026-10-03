#!/usr/bin/env python3
"""renovate-poll-digest.py — weekly digest of the stalled Renovate POLL queue.

Operator alert-automation directive #8 (2026-07-08): RenovateAutonomyHighPollRate is a
STANDING-condition warning — the lane deliberately routes k8s/helm/tf/Dockerfile/stateful
dependency MRs to POLL (never auto-merges them; that is the designed human circuit-breaker).
Rather than page on every threshold oscillation, the alert now dedups into one rolling YT
issue (alert-yt-autoclose keeps it open) and THIS weekly digest gives the operator the
actionable list to vote on: the deferred-merge queue awaiting review + recent POLL decisions,
each linked to its GitLab MR.

Posts to #infra-nl-prod (best-effort via the bot) and prints to stdout. Exits 0 always
(observability; never blocks). Run weekly Monday (Cronicle).

Env: GATEWAY_DB, MATRIX_HOME_SERVER, MATRIX_ACCESS_TOKEN|MATRIX_CLAUDE_TOKEN(.env),
MATRIX_RENOVATE_DIGEST_ROOM, GITLAB_URL, GITLAB_TOKEN.
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import ssl
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
HS = os.environ.get("MATRIX_HOME_SERVER", "https://matrix.example.net")
GITLAB = os.environ.get("GITLAB_URL", "https://gitlab.example.net").rstrip("/")
# #infra-nl-prod — where the operator already watches infra/Renovate traffic.
ROOM = os.environ.get("MATRIX_RENOVATE_DIGEST_ROOM", "!AOMuEtXGyzGFLgObKN:matrix.example.net")


def _env(name: str) -> str:
    v = os.environ.get(name, "")
    if v:
        return v
    for p in (os.path.join(REPO, ".env"),):
        try:
            for line in open(p, encoding="utf-8"):
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def _q(db, sql, args=()):
    try:
        return db.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


_PROJ_CACHE: dict = {}


def _project_path(pid) -> str:
    if pid in _PROJ_CACHE:
        return _PROJ_CACHE[pid]
    tok = _env("GITLAB_TOKEN")
    path = str(pid)
    if tok:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(f"{GITLAB}/api/v4/projects/{pid}",
                                         headers={"PRIVATE-TOKEN": tok})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as r:
                path = json.loads(r.read()).get("path_with_namespace", str(pid))
        except Exception:  # noqa: BLE001
            pass
    _PROJ_CACHE[pid] = path
    return path


def _mr_link(pid, iid) -> str:
    return f"{GITLAB}/{_project_path(pid)}/-/merge_requests/{iid}"


def build_text() -> str:
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5.0)
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    # Deferred-merge queue awaiting review (the primary actionable list).
    deferred = _q(db, "SELECT project_id, mr_iid, tier, COALESCE(update_type,''), "
                      "COALESCE(package,''), deadline_ts, COALESCE(reason,'') "
                      "FROM renovate_deferred_merges WHERE status='pending' "
                      "ORDER BY deadline_ts ASC LIMIT 25")
    # Recent POLL decisions whose MR has not since been AUTO-merged (still awaiting the vote).
    since = now - 14 * 86400
    poll = _q(db, "SELECT project_id, mr_iid, MAX(mr_title), MAX(tier) "
                  "FROM renovate_autonomy_audit WHERE decision='POLL' AND ts>=? "
                  "GROUP BY project_id, mr_iid "
                  "HAVING NOT EXISTS (SELECT 1 FROM renovate_autonomy_audit a2 "
                  "  WHERE a2.project_id=renovate_autonomy_audit.project_id "
                  "  AND a2.mr_iid=renovate_autonomy_audit.mr_iid AND a2.decision='AUTO') "
                  "ORDER BY MAX(ts) DESC LIMIT 25", (since,))
    poll_total = _q(db, "SELECT COUNT(*) FROM renovate_autonomy_audit WHERE decision='POLL' AND ts>=?",
                    (since,))
    db.close()

    n_poll = poll_total[0][0] if poll_total else 0
    lines = ["🔁 Renovate POLL queue — weekly digest (operator vote needed)",
             f"deferred-merge queue awaiting review: {len(deferred)} | "
             f"distinct POLL MRs (14d): {len(poll)} | POLL decisions (14d): {n_poll}"]
    if deferred:
        lines.append("— Deferred (awaiting review, soonest deadline first):")
        for pid, iid, tier, utype, pkg, ddl, reason in deferred[:12]:
            when = ""
            if ddl:
                try:
                    dh = (int(ddl) - now) / 3600.0
                    when = f" [deadline {'%+.0fh' % dh}]"
                except (TypeError, ValueError):
                    pass
            lbl = pkg or utype or "dep update"
            lines.append(f"  • {_mr_link(pid, iid)} — {lbl} (tier {tier}){when}")
    if poll:
        shown = [p for p in poll if (p[0], p[1]) not in {(d[0], d[1]) for d in deferred}]
        if shown:
            lines.append("— Other recent POLL MRs (no AUTO since):")
            for pid, iid, title, tier in shown[:12]:
                lines.append(f"  • {_mr_link(pid, iid)} — {(title or '')[:60]} (tier {tier})")
    if not deferred and not poll:
        lines.append("✅ POLL queue empty — nothing awaiting your vote this week.")
    lines.append("Vote by reviewing/merging in GitLab; the reconciler picks it up. "
                 "Standing alert dedups to one rolling YT issue (no per-fire pages).")
    return "\n".join(lines)


def post(text: str) -> None:
    tok = _env("MATRIX_ACCESS_TOKEN") or _env("MATRIX_CLAUDE_TOKEN")
    if not tok:
        print("(no Matrix token — digest printed only, not posted)")
        return
    body = json.dumps({"msgtype": "m.text", "body": text}).encode()
    txn = f"rnvpoll-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
    req = urllib.request.Request(
        f"{HS}/_matrix/client/v3/rooms/{ROOM}/send/m.room.message/{txn}",
        data=body, method="PUT",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=8)
        print("(posted to #infra-nl-prod)")
    except Exception as exc:  # noqa: BLE001
        print(f"(post failed: {exc}; digest printed above)")


def main() -> int:
    text = build_text()
    print(text)
    post(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
