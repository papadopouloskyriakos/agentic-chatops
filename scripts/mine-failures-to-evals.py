#!/usr/bin/env python3
"""mine-failures-to-evals.py — close the self-improvement loop back INTO the eval flywheel.

The super-architect step (IFRNLLEI01PRD-1267, D16): confirmed recurrent failures — the
(host, rule) alert patterns that recur >=N times in the trailing window in triage.log (the
same signal the governance auto-demote uses) — are mined into NEW discovery eval cases. The
eval flywheel then permanently guards against the patterns the system keeps tripping on.

Dry-run by default (prints what it WOULD add); --apply writes to scripts/eval-sets/discovery.json.
Dedup: a (host, rule) already represented in discovery.json is skipped. Capped per run.

Usage:
  mine-failures-to-evals.py                 # dry-run, show candidates
  mine-failures-to-evals.py --apply         # append new discovery cases
  mine-failures-to-evals.py --min-count 3 --window-days 30 --max-add 5 --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
DISCOVERY = Path(os.environ.get("EVAL_DISCOVERY_FILE", str(HERE / "eval-sets" / "discovery.json")))

ROOM = {"nl": "#infra-nl-prod", "gr": "#infra-gr-prod"}
PROJECT = {"nl": "IFRNLLEI01PRD", "gr": "IFRGRSKG01PRD"}


def _category(rule: str) -> str:
    r = rule.lower()
    if any(k in r for k in ("crowdsec", "ban", "intrusion", "scan", "vuln", "tls", "cve")):
        return "security"
    if any(k in r for k in ("device", "service", "port", "down", "icmp", "ping", "target")):
        return "availability"
    return "generic"


def _alert_type(rule: str) -> str:
    r = rule.lower()
    if "crowdsec" in r:
        return "crowdsec"
    if any(k in r for k in ("device", "service", "port", "icmp", "sensor")):
        return "librenms"
    return "prometheus"


def mine(min_count: int, window_days: int, max_add: int) -> tuple[list[dict], list[str]]:
    from lib.infragraph import parse_triage_log
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    events = parse_triage_log(since=since)
    counts = Counter((e["host"], e["rule"], e["site"]) for e in events
                     if e.get("host") and e.get("rule"))
    recurrent = [(h, r, s, n) for (h, r, s), n in counts.items() if n >= min_count]
    recurrent.sort(key=lambda x: -x[3])

    try:
        discovery = json.loads(DISCOVERY.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        discovery = []
    existing = {(c.get("payload", {}).get("hostname"), c.get("payload", {}).get("alert_rule"))
                for c in discovery}

    new_cases: list[dict] = []
    notes: list[str] = []
    mined_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_seq = len([c for c in discovery if str(c.get("id", "")).startswith("DSM-")])
    for host, rule, site, n in recurrent:
        if (host, rule) in existing:
            notes.append(f"skip (already in discovery): {host} / {rule}")
            continue
        if len(new_cases) >= max_add:
            notes.append(f"cap reached ({max_add}); {len(recurrent)} recurrent patterns total — rest deferred")
            break
        n_seq += 1
        site = (site or "nl").lower()
        site = site if site in ROOM else "nl"
        new_cases.append({
            "id": f"DSM-{n_seq:02d}",
            "name": f"{rule} on {host} (mined recurrence x{n}/{window_days}d)",
            "category": _category(rule),
            "site": site,
            "payload": {
                "alert_type": _alert_type(rule),
                "hostname": host,
                "alert_rule": rule,
                "severity": "critical",
                "state": "alert",
            },
            "expected": {
                "issue_created": True,
                "yt_project": PROJECT[site],
                "matrix_room": ROOM[site],
                "triage_must_contain": [host],
                "confidence_range": [0.3, 0.95],
                "must_have_react": True,
                "must_have_approval_gate": True,
            },
            "provenance": {
                "mined_from": "triage.log recurrence",
                "recurrence_count": n,
                "window_days": window_days,
                "mined_at": mined_at,
            },
        })
    return new_cases, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write new cases to discovery.json")
    ap.add_argument("--min-count", type=int, default=3)
    ap.add_argument("--window-days", type=int, default=30)
    ap.add_argument("--max-add", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    new_cases, notes = mine(args.min_count, args.window_days, args.max_add)
    if args.apply and new_cases:
        discovery = json.loads(DISCOVERY.read_text()) if DISCOVERY.exists() else []
        discovery.extend(new_cases)
        DISCOVERY.write_text(json.dumps(discovery, indent=2) + "\n")

    report = {
        "min_count": args.min_count, "window_days": args.window_days,
        "would_add" if not args.apply else "added": [c["id"] + ":" + c["payload"]["hostname"]
                                                     + "/" + c["payload"]["alert_rule"] for c in new_cases],
        "count": len(new_cases), "applied": args.apply, "notes": notes,
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'Added' if args.apply else 'Would add'} {len(new_cases)} discovery case(s):")
        for c in new_cases:
            print(f"  {c['id']}  {c['payload']['hostname']} / {c['payload']['alert_rule']} "
                  f"(x{c['provenance']['recurrence_count']})")
        for nt in notes:
            print(f"  - {nt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
