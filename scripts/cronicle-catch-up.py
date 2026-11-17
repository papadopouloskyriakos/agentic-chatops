#!/usr/bin/env python3
"""cronicle-catch-up.py — keep Cronicle `catch_up` on the SAFE daily jobs only (IFRNLLEI01PRD-2992).

NL power-loss postmortem item 16: while nl-claude01 was down (2026-11-06) the daily
regenerators missed their slot and five had to be re-run by hand. Cronicle's `catch_up`
("Run All Mode") replays every missed tick when the scheduler comes back. That is only safe
for idempotent jobs, and only for DAILY ones (a */5 job would replay hundreds of ticks).

The list below is the operator decision: the daily members of the platform-controller
SAFE-LIST (SAFE_RERUN_HINTS in scripts/platform-controller.py) plus the five jobs re-run by
hand on 2026-11-07. Never agora/trading, never renovate, never a non-daily job.
max_children=1 is set with it, so a multi-day replay runs the ticks one after another
(proved with a throwaway event 2026-11-07: ticks 13:44 + 13:46 replayed at 13:51:00 and
13:51:25) instead of concurrently.

    cronicle-catch-up.py            # --check (default): print the state of every listed event
    cronicle-catch-up.py --apply    # update_event catch_up=1 + max_children=1 where needed

Exit 1 from --check if any listed event is missing, mismatched, or not caught up.
--apply also sets reset_cursor=now, so turning catch_up on replays nothing from the past.
Caveat: Cronicle also replays the ticks of a period an event spent DISABLED once it is
re-enabled; re-enable a listed event with update_event {"id":…, "enabled":1,
"reset_cursor":<now>} if those runs are not wanted.
Runbook: docs/runbooks/platform-controller.md § Catch-up after scheduler downtime.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

_REPO_ENV = Path(__file__).resolve().parent.parent / ".env"
ENV = Path(os.environ.get("CRONICLE_ENV_FILE") or (
    _REPO_ENV if _REPO_ENV.exists() else Path.home() / "gitlab/n8n/claude-gateway/.env"))

# (event id, exact title, a substring the event's script must contain, why it is safe)
CATCH_UP_EVENTS = [
    ("emqurqy6p4y", "backup-gateway-db.sh", "scripts/backup-gateway-db.sh",
     "online SQLite backup; skips when a backup < 60 min old exists, so N replays = 1 backup"),
    ("emqurqz2v97", "synthetic-incident-canary.sh", "scripts/synthetic-incident-canary.sh",
     "probes the spine against a throwaway mktemp DB; only rewrites its gauge"),
    ("emqurqyfw62", "refresh-rag-metrics-reference.py", "scripts/refresh-rag-metrics-reference.py",
     "regenerates docs/rag-metrics-reference.md (SAFE-LIST member via its log path)"),
    ("emqurqym06x", "infragraph-seed.py", "scripts/infragraph-seed.py --all",
     "idempotent upserts from PVE/NetBox/tunnels/declared; refreshes valid_until"),
    ("emqurqymv71", "infragraph-eval.py", "infragraph-eval.py --scorecard",
     "recomputes the scorecard JSON from the DB (the --pending hourly twin is NOT listed)"),
    ("emqurqz4f9e", "write-audit-metrics.sh", "scripts/write-audit-metrics.sh",
     "read-only audits + gauge rewrite"),
    ("emqurqz5y9l", "registry-seed.py", "scripts/registry-seed.py",
     "re-seed + curate the component manifest; documented idempotent"),
    ("emqurqz669m", "interaction-graph.py", "scripts/interaction-graph.py",
     "static analysis; rewrites config/interaction-graph.json + gauges"),
]
FORBIDDEN_CATEGORIES = {"agora"}
FORBIDDEN_WORDS = ("renovate", "agora", "trading")


def _cfg() -> tuple:
    c = {}
    for line in ENV.read_text().splitlines():
        if line.startswith("CRONICLE_") and "=" in line:
            k, v = line.split("=", 1)
            c[k.strip()] = v.strip().strip("'\"")
    url = c.get("CRONICLE_URL", "http://127.0.0.1:3012").rstrip("/")
    return url, c.get("CRONICLE_API_KEY", "")


def _api(method: str, payload: dict | None = None, query: str = "") -> dict:
    url, key = _cfg()
    req = urllib.request.Request(
        f"{url}/api/app/{method}/v1{query}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    return json.load(urllib.request.urlopen(req, timeout=15))


def is_daily(timing: dict) -> bool:
    return (set(timing or {}) <= {"hours", "minutes"}
            and len((timing or {}).get("hours", [])) == 1
            and len((timing or {}).get("minutes", [])) == 1)


def check_event(eid: str, title: str, must: str) -> tuple:
    """(ok_to_catch_up, event_or_None, problem)."""
    d = _api("get_event", query=f"?id={eid}")
    if d.get("code") != 0:
        return False, None, f"missing ({d.get('description', d.get('code'))})"
    ev = d["event"]
    script = (ev.get("params") or {}).get("script", "")
    if ev.get("title") != title:
        return False, ev, f"title is {ev.get('title')!r}, expected {title!r}"
    if must not in script:
        return False, ev, f"script no longer contains {must!r}"
    if ev.get("category") in FORBIDDEN_CATEGORIES or any(w in (title + script).lower() for w in FORBIDDEN_WORDS):
        return False, ev, "agora/trading/renovate job — never catch up"
    if not is_daily(ev.get("timing")):
        return False, ev, f"not a daily job (timing {ev.get('timing')})"
    return True, ev, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    bad = 0
    for eid, title, must, why in CATCH_UP_EVENTS:
        ok, ev, problem = check_event(eid, title, must)
        if not ok:
            bad += 1
            print(f"FAIL {eid} {title}: {problem}")
            continue
        cur = (int(ev.get("catch_up") or 0), int(ev.get("max_children") or 0))
        if cur == (1, 1):
            print(f"OK   {eid} {title} catch_up=1 max_children=1  ({why})")
            continue
        if args.apply:
            # reset_cursor=now: switching catch_up on must never replay history from a stale cursor
            r = _api("update_event", {"id": eid, "catch_up": 1, "max_children": 1,
                                      "reset_cursor": int(time.time())})
            after = _api("get_event", query=f"?id={eid}")["event"]
            done = (int(after.get("catch_up") or 0), int(after.get("max_children") or 0)) == (1, 1)
            print(f"{'SET ' if r.get('code') == 0 and done else 'FAIL'} {eid} {title} "
                  f"catch_up {cur[0]}->{after.get('catch_up')} max_children {cur[1]}->{after.get('max_children')}")
            bad += 0 if done else 1
        else:
            bad += 1
            print(f"TODO {eid} {title} catch_up={cur[0]} max_children={cur[1]} (run --apply)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
