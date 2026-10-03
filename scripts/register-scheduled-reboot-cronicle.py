#!/usr/bin/env python3
"""register-scheduled-reboot-cronicle.py — register the feature's periodic jobs
in the native Cronicle scheduler (the platform scheduler since 2026-06-26).

Idempotent: GETs the schedule first and skips any job whose title already exists.
Mirrors the exact event shape the 2026-06-26 migration used (plugin=shellplug,
category=gateway, target=maingrp, timing={minutes,hours,weekdays} arrays). Auth
via CRONICLE_API_KEY (admin:1, in .env) — POST /api/app/create_event.

GOTCHA (migration memory): create_event REJECTS '<'/'>' in the notes field
(returns a generic {"code":"api"} error). Notes here are plain text only.

Usage:
  python3 register-scheduled-reboot-cronicle.py --dry-run   # print payloads, create nothing
  python3 register-scheduled-reboot-cronicle.py             # create (idempotent)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import cronicle as c  # noqa: E402

REPO = "/app/claude-gateway"
LOG = "/home/app-user/logs/claude-gateway"

# cron-expr -> Cronicle timing object (arrays; absent field = every). Times in UTC.
#   discover: weekly Sun 05:17 UTC | promote: daily 06:30 UTC
#   metrics: every 5 min          | digest: weekly Mon 05:00 UTC | audit: weekly Mon 05:30 UTC
JOBS = [
    {"title": "scheduled-reboot-discover", "timing": {"minutes": [17], "hours": [5], "weekdays": [0]},
     "cmd": f"python3 {REPO}/scripts/discover-scheduled-reboots.py >> {LOG}/discover-scheduled-reboots.log 2>&1",
     "notes": "Weekly scheduled-reboot discovery sweep - registers observing rows for hosts with reboot crons."},
    {"title": "scheduled-reboot-promote", "timing": {"minutes": [30], "hours": [6]},
     "cmd": f"python3 {REPO}/scripts/promote-scheduled-reboots.py >> {LOG}/promote-scheduled-reboots.log 2>&1",
     "notes": "Daily observe-to-live promotion (2+ in-window boots) + drift + expiry for the scheduled-reboot registry."},
    {"title": "scheduled-reboot-metrics", "timing": {"minutes": [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]},
     "cmd": f"bash {REPO}/scripts/write-scheduled-reboot-metrics.sh",
     "notes": "Every-5min Prometheus metrics for the scheduled-reboot registry + two-phase verify accumulators."},
    {"title": "scheduled-reboot-digest", "timing": {"minutes": [0], "hours": [5], "weekdays": [1]},
     "cmd": f"python3 {REPO}/scripts/scheduled-reboot-digest.py >> {LOG}/scheduled-reboot-digest.log 2>&1",
     "notes": "Weekly #alerts digest of the scheduled-reboot registry (new live rows, drift, misclassifications)."},
    {"title": "scheduled-reboot-audit", "timing": {"minutes": [30], "hours": [5], "weekdays": [1]},
     "cmd": f"bash {REPO}/scripts/audit-scheduled-reboot-suppressions.sh >> {LOG}/scheduled-reboot-audit.log 2>&1",
     "notes": "Weekly reconcile invariant - every phaseSR suppression got a two-phase verify."},
]


def _existing_titles() -> set[str]:
    try:
        return {e.get("title", "") for e in (c.schedule() or [])}
    except Exception:
        return set()


def _payload(job: dict) -> dict:
    return {
        "title": job["title"],
        "enabled": 1,
        "category": "gateway",
        "plugin": "shellplug",
        "target": "maingrp",
        "timezone": "UTC",
        "timing": job["timing"],
        "params": {"script": f"#!/bin/sh\n{job['cmd']}", "annotate": 1, "json": 1},
        "notes": job["notes"],  # no <> allowed (create_event rejects HTML metachars)
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    url, key = c.cfg()
    if not url or not key:
        print("FAIL: CRONICLE_URL / CRONICLE_API_KEY not configured (cronicle.cfg)")
        return 1

    existing = _existing_titles()
    print(f"cronicle: {len(existing)} existing events; {len(JOBS)} jobs to register; dry_run={args.dry_run}")

    created = skipped = 0
    for job in JOBS:
        if job["title"] in existing:
            print(f"  SKIP {job['title']} (already exists)")
            skipped += 1
            continue
        payload = _payload(job)
        if args.dry_run:
            print(f"  [dry-run] CREATE {job['title']}: {json.dumps(payload)}")
            continue
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{url}/api/app/create_event?api_key={key}", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            resp = json.load(urllib.request.urlopen(req, timeout=10))
            if resp.get("code") == 0:
                print(f"  CREATED {job['title']} (event id {resp.get('id', '?')})")
                created += 1
            else:
                print(f"  FAIL {job['title']}: {resp}")
        except Exception as exc:
            print(f"  ERROR {job['title']}: {exc}")

    if args.dry_run:
        print(f"dry-run: would create {sum(1 for j in JOBS if j['title'] not in existing)} (skip {skipped} existing)")
    else:
        print(f"done: created={created} skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
