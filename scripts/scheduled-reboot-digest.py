#!/usr/bin/env python3
"""scheduled-reboot-digest.py — weekly digest of the self-learning registry.

Posts a one-shot summary to #alerts (best-effort via the bot API) and prints it
to stdout. Covers the last 7 days: newly-promoted live schedules, drift/expiry
disables, and two-phase-verify misclassifications. Decision 3 (digest-only): no
per-host YouTrack control issues are created.

Env: GATEWAY_DB, MATRIX_HOME_SERVER, MATRIX_ACCESS_TOKEN. Exits 0 always
(observability; never blocks). Run weekly (Cronicle).
"""
from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
import urllib.request

DB = os.environ.get("GATEWAY_DB", os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"))
COUNTERS = "/home/app-user/gateway-state/scheduled-reboot-verify-counters.json"
ALERTS_ROOM = os.environ.get("MATRIX_ALERTS_ROOM", "!xeNxtpScJWCmaFjeCL:matrix.example.net")
HS = os.environ.get("MATRIX_HOME_SERVER", "https://matrix.example.net")
TOK = os.environ.get("MATRIX_ACCESS_TOKEN", "")


def _q(db, sql, args=()):
    try:
        return db.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def build_text() -> str:
    db = sqlite3.connect(DB, timeout=5.0)
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    live = _q(db, "SELECT hostname, cron_expr, tz, reboot_kind FROM discovered_scheduled_reboots "
                  "WHERE status='live' ORDER BY hostname")
    new_live = _q(db, "SELECT hostname, cron_expr FROM discovered_scheduled_reboots "
                      "WHERE status='live' AND last_match_at >= ?", (since,))
    disabled = _q(db, "SELECT hostname, cron_expr, rationale FROM discovered_scheduled_reboots "
                      "WHERE status='disabled' ORDER BY id DESC LIMIT 10")
    observing = _q(db, "SELECT COUNT(*) FROM discovered_scheduled_reboots WHERE status='observing'")
    db.close()

    miscls = 0
    try:
        miscls = int(json.load(open(COUNTERS)).get("misclassified", 0))
    except Exception:
        pass

    lines = ["📋 Scheduled-reboot registry — weekly digest",
             f"live schedules: {len(live)} | observing: {observing[0][0] if observing else 0} "
             f"| two-phase misclassifications (cumulative): {miscls}"]
    if new_live:
        lines.append(f"newly active (matched in last 7d): {len(new_live)} — " +
                     ", ".join(f"{h}({c})" for h, c in new_live))
    else:
        lines.append("no schedules matched a real reboot in the last 7d (all dark or pre-promotion)")
    if disabled:
        lines.append("recently disabled (drift/expiry): " +
                     "; ".join(f"{h} {c} [{(r or '')[:40]}]" for h, c, r in disabled[:5]))
    lines.append("Full table: sqlite3 $GATEWAY_DB 'SELECT hostname,cron_expr,status FROM discovered_scheduled_reboots;'")
    return "\n".join(lines)


def post(text: str) -> None:
    if not TOK:
        print("(MATRIX_ACCESS_TOKEN unset — digest printed only, not posted)")
        return
    body = json.dumps({"msgtype": "m.text", "body": text}).encode()
    txn = f"srdigest-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
    req = urllib.request.Request(
        f"{HS}/_matrix/client/v3/rooms/{ALERTS_ROOM}/send/m.room.message/{txn}",
        data=body, method="PUT",
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=8)
        print("(posted to #alerts)")
    except Exception as exc:
        print(f"(post failed: {exc}; digest printed above)")


def main() -> int:
    text = build_text()
    print(text)
    post(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
