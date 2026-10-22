#!/usr/bin/env python3
"""discover-scheduled-reboots.py — weekly scheduled-reboot discovery sweep.

Proactively finds deterministic reboot schedules across the estate and registers
them (status='observing') so the promoter can later flip them to 'live' after
>=2 confirmed on-schedule boots. This is the PROACTIVE arm; the REACTIVE
(self-learning) arm is scripts/classify-reboot-alert.py (Increment C).

Coverage (per reachable host):
  * 5-field cron reboot/shutdown lines in root crontab, /etc/crontab, /etc/cron.d/*
  * unattended-upgrades Automatic-Reboot-Time (converted to a daily cron)
  * host tz via timedatectl (so the matcher is DST-correct)
systemd OnCalendar reboot timers are noted as a follow-up (rare on this estate).

Reuses the PVE_NODES SSH map + qm/pct guest enumeration pattern from
scripts/refresh-host-blast-radius.py. Idempotent upsert (ON CONFLICT preserves
status/observed_count/kill_switch — a re-discovery never silently (re)observes a
host that promoted to live or clears a kill_switch).

Safety: discovery only WRITES observing rows; observing rows NEVER suppress
(matcher reads status='live' only). So this script cannot darken any alert.

Usage:
  python3 discover-scheduled-reboots.py [--dry-run] [--limit N] [--host NAME]
Env: GATEWAY_DB (canonical gateway.db path; defaults via lib.get_db)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
REDACTED_a7b84d63
import subprocess
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))   # scripts/lib  -> scheduled_reboots, get_db
sys.path.insert(0, _HERE)                         # scripts      -> lib.get_db
import scheduled_reboots as sr  # noqa: E402
try:
    from lib.get_db import CANONICAL_DB_PATH  # type: ignore
except Exception:
    try:
        from get_db import CANONICAL_DB_PATH  # type: ignore
    except Exception:
        CANONICAL_DB_PATH = os.environ.get(
            "GATEWAY_DB", os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"))

# PVE_NODES mirrors scripts/refresh-host-blast-radius.py (source of truth there).
# NL PVE use id_ed25519; GR PVE use one_key. All root@.
PVE_NODES = {
    "nl-pve01": "~/.ssh/id_ed25519",
    "nl-pve02": "~/.ssh/id_ed25519",
    "nl-pve03": "~/.ssh/id_ed25519",
    "nlpve04": "~/.ssh/id_ed25519",
    "gr-pve01": "~/.ssh/one_key",
    "gr-pve02": "~/.ssh/one_key",
}

REBOOT_CMD_RE = re.compile(r"(^|[\s/])(shutdown\b.*-r|reboot\b|systemctl\b[^|]*\breboot)", re.I)
NAMED_CRON = {"@hourly": "0 * * * *", "@daily": "0 0 * * *",
              "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *"}
SSH_KEYS = ["~/.ssh/one_key", "~/.ssh/id_ed25519", "~/.ssh/id_rsa"]


def _ssh(host: str, cmd: str, key: str) -> Optional[str]:
    try:
        r = subprocess.run(
            ["ssh", "-i", os.path.expanduser(key), "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"root@{host}", cmd],
            capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def _ssh_anykey(host: str, cmd: str) -> Optional[str]:
    for k in SSH_KEYS:
        out = _ssh(host, cmd, k)
        if out is not None:
            return out
    return None


def _valid_cron(expr: str) -> bool:
    try:
        from croniter import croniter  # vendored via scheduled_reboots' sys.path
        croniter(expr, datetime.datetime.now(datetime.timezone.utc))
        return True
    except Exception:
        return False


def _parse_reboot_crons(blob: str) -> list[tuple[str, str]]:
    """From a blob of cron lines, return [(cron_expr, full_line)] for reboot lines."""
    out = []
    for line in blob.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if not REBOOT_CMD_RE.search(s):
            continue
        fields = s.split()
        if not fields:
            continue
        if fields[0].startswith("@") and fields[0] in NAMED_CRON:
            out.append((NAMED_CRON[fields[0]], s))
            continue
        if len(fields) >= 5:
            expr = " ".join(fields[:5])
            if _valid_cron(expr):
                out.append((expr, s))
    return out


def discover_host(host: str) -> list[tuple[str, str, str, str]]:
    """Return [(cron_expr, tz, reboot_kind, rationale)] for the host's reboot schedules."""
    found = []
    # Gather cron sources + tz + unattended in ONE ssh round-trip.
    blob = _ssh_anykey(host, (
        "echo '===ROOTCRON==='; crontab -l 2>/dev/null; "
        "echo '===CRONTAB==='; cat /etc/crontab 2>/dev/null; "
        "echo '===CROND==='; cat /etc/cron.d/* 2>/dev/null; "
        "echo '===TZ==='; (timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null | head -1); "
        "echo '===UNATTENDED==='; grep -riE 'Automatic-Reboot\"|Automatic-Reboot-Time' /etc/apt/apt.conf.d/ 2>/dev/null"
    ))
    if blob is None:
        return found
    # Split the single-round-trip output by markers into sections.
    parts = re.split(r"^===ROOTCRON===|^===CRONTAB===|^===CROND===|^===TZ===|^===UNATTENDED===$",
                     blob, flags=re.MULTILINE)
    # parts == ['', rootcron, crontab, crond, tz, unattended]
    if len(parts) < 6:
        cron_blob, tz, unattended = blob, sr.UNKNOWN_TZ, ""
    else:
        cron_blob = parts[1] + "\n" + parts[2] + "\n" + parts[3]
        tz_raw = (parts[4] or "").strip()
        tz = tz_raw.splitlines()[-1].strip() if tz_raw else sr.UNKNOWN_TZ
        if not tz or " " in tz:
            tz = sr.UNKNOWN_TZ
        unattended = parts[5]
    for expr, line in _parse_reboot_crons(cron_blob):
        found.append((expr, tz, "cron", line.strip()))
    # unattended-upgrades: only if a NON-commented Automatic-Reboot "true" AND a
    # non-commented Automatic-Reboot-Time are both set. Ubuntu ships both lines
    # commented-out by default (//Automatic-Reboot "false"; //Automatic-Reboot-Time
    # "02:00";) — those must NOT register as a schedule.
    unatt_active = [l for l in unattended.splitlines()
                    if l.strip() and not l.strip().startswith(("/", "#"))]
    reboot_on = any(re.search(r'Automatic-Reboot\s*"true"', l, re.I) for l in unatt_active)
    if reboot_on:
        for l in unatt_active:
            m = re.search(r'Automatic-Reboot-Time\s*"(\d{1,2}):(\d{2})"', l)
            if m:
                hh, mm = int(m.group(1)), int(m.group(2))
                found.append((f"{mm} {hh} * * *", tz, "unattended-upgrade",
                              f"unattended-upgrades Automatic-Reboot-Time {m.group(1)}:{m.group(2)}"))
    return found


def enumerate_hosts(limit: Optional[int] = None) -> list[str]:
    hosts = list(PVE_NODES.keys())  # include the PVE nodes themselves
    for node, key in PVE_NODES.items():
        for cmd in ("qm list 2>/dev/null | awk 'NR>1 {print $2}'",
                    "pct list 2>/dev/null | awk 'NR>1 {print $2}'"):
            out = _ssh(node, cmd, key)
            if out:
                for h in out.splitlines():
                    h = h.strip()
                    if h and h not in hosts:
                        hosts.append(h)
        if limit and len(hosts) >= limit:
            break
    return hosts[:limit] if limit else hosts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--host", default=None, help="scan a single host only")
    ap.add_argument("--db", default=CANONICAL_DB_PATH)
    args = ap.parse_args(argv)

    import sqlite3
    targets = [args.host] if args.host else enumerate_hosts(args.limit)
    print(f"discovery: {len(targets)} host(s) to scan; dry_run={args.dry_run}")

    registered = 0
    for host in targets:
        schedules = discover_host(host)
        if not schedules:
            continue
        if args.dry_run:
            for expr, tz, kind, rat in schedules:
                print(f"  [dry-run] {host}: {kind} {expr} ({tz}) — {rat}")
            continue
        conn = sqlite3.connect(args.db, timeout=10.0)
        try:
            for expr, tz, kind, rat in schedules:
                rc = sr.upsert_observing(conn, host, expr, kind, tz=tz, source="discovery", rationale=rat)
                if rc:
                    registered += 1
                    print(f"  registered {host}: {kind} {expr} ({tz})")
        finally:
            conn.close()
    print(f"discovery: done. {'(dry-run, no writes)' if args.dry_run else str(registered)+' row(s) written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
