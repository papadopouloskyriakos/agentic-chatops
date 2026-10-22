#!/usr/bin/env python3
"""classify-reboot-alert.py — self-learning reboot classifier (the reactive arm).

Invoked at triage (infra-triage.sh Step 2) when a reboot-class alert was NOT
suppressed by the matcher (off-schedule, or host not yet registered). It RCAs the
reboot deterministically and, if the root cause is a deterministic schedule AND
the reboot was a clean shutdown, registers the host as 'observing' so the
promoter can later confirm + promote it. This closes the loop the operator asked
for: "when it finds a cron job, automatically add the system to the registry."

Safety: registers ONLY observing rows (never suppress); only on a CLEAN boot
(reactive reboots — OOM/watchdog/self-heal — are symptoms, never registered);
idempotent (ON CONFLICT preserves status/observed_count/kill_switch). Reuses
discover-scheduled-reboots.discover_host() for the cron/timer/unattended scan.

Usage: python3 classify-reboot-alert.py <hostname> [rule_name] [--register]
       Without --register it classifies + prints JSON only (dry/observe).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
REDACTED_a7b84d63
import sqlite3
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import scheduled_reboots as sr  # noqa: E402

_discover_spec = importlib.util.spec_from_file_location(
    "discover_scheduled_reboots", os.path.join(_HERE, "discover-scheduled-reboots.py"))
_discover = importlib.util.module_from_spec(_discover_spec)
try:
    _discover_spec.loader.exec_module(_discover)
except Exception:
    _discover = None

DB_PATH = os.environ.get("GATEWAY_DB", os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"))
CLEAN_RE = re.compile(r"reached target reboot\.target|systemd-reboot\.service|systemd-shutdown\[1\]|syncing filesystems", re.I)
REACTIVE_RE = re.compile(r"oom-kill|out of memory|invoked oom|kernel panic|watchdog|hung_task|emergency|selfheal|self-heal|nvml|thermal", re.I)


def _ssh(host: str, cmd: str):
    for key in ("~/.ssh/one_key", "~/.ssh/id_ed25519", "~/.ssh/id_rsa"):
        try:
            r = subprocess.run(
                ["ssh", "-i", os.path.expanduser(key), "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"root@{host}", cmd],
                capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                return r.stdout
        except Exception:
            continue
    return None


def classify(host: str) -> dict:
    schedules = _discover.discover_host(host) if _discover else []
    prev = _ssh(host, "journalctl -b -1 -n 80 --no-pager 2>/dev/null") or ""
    if CLEAN_RE.search(prev):
        boot_clean = True
    elif REACTIVE_RE.search(prev):
        boot_clean = False
    else:
        boot_clean = False  # unknown -> treat as not-a-clean-schedule (don't register)
    deterministic = bool(schedules) and boot_clean
    return {
        "hostname": host,
        "schedules_found": [{"cron": c, "tz": t, "kind": k, "rationale": r} for (c, t, k, r) in schedules],
        "boot_clean": boot_clean,
        "deterministic": deterministic,
        "would_register": deterministic,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("hostname")
    ap.add_argument("rule_name", nargs="?", default="")
    ap.add_argument("--register", action="store_true", help="actually upsert observing rows (default: classify only)")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args(argv)

    res = classify(args.hostname)
    if args.register and res["deterministic"]:
        conn = sqlite3.connect(args.db, timeout=10.0)
        try:
            registered = 0
            for c, t, k, r in (_discover.discover_host(args.hostname) if _discover else []):
                rc = sr.upsert_observing(conn, args.hostname, c, k, tz=t, source="classifier", rationale=r)
                registered += 1 if rc else 0
        finally:
            conn.close()
        res["registered"] = registered
    else:
        res["registered"] = 0
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
