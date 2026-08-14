#!/usr/bin/env python3
"""promote-scheduled-reboots.py — daily observe→live promotion + drift + expiry.

For each registered row (status observing|live, kill_switch=0):
  1. SSH the host; read `journalctl --list-boots --utc`; for every boot that
     lands in the row's cron window, record it (record_observation, dedup by
     boot timestamp). This is the BEHAVIORAL confirmation of the declared cron.
  2. PROMOTE: observing rows whose observed_count >= PROMOTION_THRESHOLD (2)
     flip to status='live' (the only state the matcher suppresses on).
  3. DRIFT: re-derive the host's reboot crons; if this row's cron_expr is no
     longer present, disable it — a removed schedule must not silently suppress.
  4. EXPIRY: valid_until < now -> disabled (re-discover or retire).

Safety: promotion is the ONLY transition that lets a row suppress; a wrong
attribution fails to accumulate >=2 in-window boots and stays observing. Drift
and expiry guarantee a removed/expired schedule cannot suppress. This script
itself never suppresses anything. Run daily (Cronicle).

Usage: python3 promote-scheduled-reboots.py [--dry-run] [--lookback-days N]
Env: GATEWAY_DB
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import scheduled_reboots as sr  # noqa: E402

# Reuse the discovery module's host-scan + reboot-cron parser (DRY drift check).
_spec = importlib.util.spec_from_file_location(
    "discover_scheduled_reboots", os.path.join(_HERE, "discover-scheduled-reboots.py"))
_discover = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_discover)
except Exception:
    _discover = None

DB_PATH = os.environ.get("GATEWAY_DB", os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"))


def _ssh(host: str, cmd: str) -> Optional[str]:
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


def _boot_times_utc(host: str, lookback_days: int) -> list[datetime.datetime]:
    # journalctl --list-boots --utc is NOT honored on some builds (it printed
    # local CEST). -o json gives first_entry as epoch-MICROSECONDS (UTC) which is
    # timezone-independent and unambiguous.
    out = _ssh(host, "journalctl --list-boots -o json 2>/dev/null")
    if not out:
        return []
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback_days)
    boots: list[datetime.datetime] = []
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("boots", [])
    for entry in data:
        ts = entry.get("first_entry")
        if not isinstance(ts, (int, float)):
            continue
        try:
            b = datetime.datetime.fromtimestamp(ts / 1_000_000, tz=datetime.timezone.utc)
        except (OSError, OverflowError, ValueError):
            continue
        if b >= cutoff:
            boots.append(b)
    return boots


def run(args) -> int:
    conn = sqlite3.connect(args.db, timeout=10.0)
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    promoted = disabled_drift = disabled_expiry = 0

    rows = conn.execute(
        f"SELECT id, hostname, cron_expr, tz, window_minutes, pre_buffer_minutes, "
        f"status, observed_count, valid_until FROM {sr._TABLE} "
        f"WHERE status IN ('observing','live') AND kill_switch=0"
    ).fetchall()

    print(f"promote: {len(rows)} active row(s) to evaluate")
    for row_id, host, cron_expr, tz, win, pre, status, obs_count, valid_until in rows:
        # 1. Behavioral confirmation: count in-window boots.
        boots = _boot_times_utc(host, args.lookback_days)
        new_obs = 0
        for b in boots:
            if sr.boot_matches_schedule(cron_expr, tz or sr.UNKNOWN_TZ, b, win or 10, pre or 5):
                if sr.record_observation(conn, row_id, b):
                    new_obs += 1
        if new_obs:
            print(f"  {host} {cron_expr}: +{new_obs} in-window boot(s) recorded")

        # 2. Promote observing -> live (>= threshold).
        if status == "observing":
            cnt = conn.execute(f"SELECT observed_count FROM {sr._TABLE} WHERE id=?", (row_id,)).fetchone()
            if cnt and cnt[0] >= sr.PROMOTION_THRESHOLD:
                if not args.dry_run:
                    conn.execute(f"UPDATE {sr._TABLE} SET status='live' WHERE id=?", (row_id,))
                    conn.commit()
                promoted += 1
                print(f"  {host} {cron_expr}: PROMOTED to live ({cnt[0]} confirmed boots)")

        # 3. Drift: re-derive reboot crons; if ours is gone, disable.
        if _discover is not None:
            try:
                current = {e[0] for e in _discover.discover_host(host)}
            except Exception:
                current = None
            if current is not None and cron_expr not in current:
                if not args.dry_run:
                    sr.disable(conn, row_id, f"drift: cron '{cron_expr}' no longer present on {host}")
                disabled_drift += 1
                print(f"  {host} {cron_expr}: DISABLED (drift — cron removed)")

        # 4. Expiry.
        try:
            vu = datetime.datetime.strptime((valid_until or "").replace("Z", ""),
                                             "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            vu = now + datetime.timedelta(days=1)  # unparseable -> don't expire on this pass
        if vu < now:
            if not args.dry_run:
                sr.disable(conn, row_id, f"expired valid_until={valid_until}")
            disabled_expiry += 1
            print(f"  {host} {cron_expr}: DISABLED (valid_until expired)")

    conn.close()
    print(f"promote: done. promoted={promoted} drift_disabled={disabled_drift} "
          f"expiry_disabled={disabled_expiry}{' (dry-run)' if args.dry_run else ''}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lookback-days", type=int, default=14)
    ap.add_argument("--db", default=DB_PATH)
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
