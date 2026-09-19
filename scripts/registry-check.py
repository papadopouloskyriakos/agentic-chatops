#!/usr/bin/env python3
"""registry-check.py — Brick 1 liveness verifier (IFRNLLEI01PRD-1421).

Reads the declared manifest (config/component-registry.json) and verifies each component's
liveness against the live substrate, so a component going dark/orphaned is detected
MECHANICALLY — the thing the 2026-06-25 dark-component audit had to do by hand.

Liveness per component type:
  prom-writer  -> the *.prom file mtime is within max_stale_seconds
  db-table     -> the table's newest timestamp row is within max_stale_seconds
  cron         -> still present in crontab (re-seed drops removed ones; this flags manifest drift)
  n8n-workflow -> observed_active is True
A component with hand-field `known_dark: true` is EXPECTED dark (dormant by design) and excluded
from the dark count. Only `critical: true` components failing liveness make this exit non-zero.

Emits Prometheus metrics to the textfile collector + a human report. Cron this (the registry is
itself a component — it registers itself). Exit 1 if any CRITICAL component is dark.

Usage: registry-check.py [--manifest PATH] [--no-metrics] [--quiet]
"""
import json
import os
REDACTED_a7b84d63
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "config" / "component-registry.json"
PROM_DIR = Path(os.environ.get("PROMETHEUS_TEXTFILE_DIR",
                               "/var/lib/node_exporter/textfile_collector"))
DB_PATH = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
OUT_PROM = PROM_DIR / "registry_check.prom"


def _now() -> int:
    return int(time.time())


def _crontab_text() -> str:
    try:
        return subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def _parse_iso_or_epoch(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)                                  # epoch
    except ValueError:
        pass
    s2 = s.replace("T", " ").replace("Z", "").split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            import datetime
            return datetime.datetime.strptime(s2, fmt).replace(
                tzinfo=datetime.timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def check_component(c: dict, cron_text: str, db, cronicle_runs: dict) -> tuple[bool, str]:
    """Return (is_dark, reason)."""
    if c.get("observed") == "absent":
        return True, "declared but no longer discovered (removed/orphaned)"
    lv = c.get("liveness") or {}
    kind = lv.get("kind")
    now = _now()

    if kind == "prom_file":
        p = PROM_DIR / lv["ref"]
        if not p.exists():
            return True, f"{lv['ref']} missing"
        age = now - int(p.stat().st_mtime)
        return (age > lv.get("max_stale_seconds", 1800),
                f"{lv['ref']} age={age}s (max {lv.get('max_stale_seconds', 1800)})")

    if kind == "db_table" and db is not None:
        tcol = lv.get("ts_column", "created_at")
        try:
            row = db.execute(f"SELECT MAX({tcol}) FROM '{lv['ref']}'").fetchone()
        except Exception as e:
            return True, f"query failed: {e}"
        last = _parse_iso_or_epoch(row[0]) if row else None
        if last is None:
            return True, "empty / no parseable timestamp"
        age = int(now - last)
        return (age > lv.get("max_stale_seconds", 604800),
                f"last write {age}s ago (max {lv.get('max_stale_seconds', 604800)})")

    if kind == "cronicle_job":
        run = cronicle_runs.get(lv.get("ref"))
        if run is None:
            # no run in the history window — infrequent or newly added; not dark (avoids false +ve)
            return False, "no run in Cronicle history window (infrequent/new)"
        age, code = run
        if code not in (0, "0", None):
            return True, f"last Cronicle run FAILED (code={code}, {age}s ago)"
        return (age > lv.get("max_stale_seconds", 90000),
                f"last run ok {age}s ago (max {lv.get('max_stale_seconds', 90000)})")

    if c["type"] == "cron":
        cmd = (c.get("command") or "")[:60]
        present = bool(cmd) and cmd.split()[0] in cron_text and c["name"] in cron_text.replace(".sh", "").replace(".py", "")
        # robust presence: match on the script name token
        token = c["name"]
        present = token in cron_text
        return (not present, "not found in crontab" if not present else "present")

    if c["type"] == "n8n-workflow":
        active = c.get("observed_active")
        return (active is False, f"active={active}")

    return False, "no liveness rule (informational)"


def main() -> int:
    manifest_path = MANIFEST
    if "--manifest" in sys.argv:
        manifest_path = Path(sys.argv[sys.argv.index("--manifest") + 1])
    comps = json.loads(manifest_path.read_text()).get("components", [])
    cron_text = _crontab_text()
    db = None
    try:
        import sqlite3
        db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    except Exception:
        pass

    cronicle_runs = {}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        import cronicle as cron_api
        cronicle_runs = cron_api.last_runs()
    except Exception:
        pass

    results = []
    for c in comps:
        is_dark, reason = check_component(c, cron_text, db, cronicle_runs)
        results.append({"name": c["name"], "type": c["type"],
                        "critical": bool(c.get("critical")),
                        "known_dark": bool(c.get("known_dark")),
                        "dark": is_dark, "reason": reason})
    if db:
        db.close()

    total = len(results)
    dark = [r for r in results if r["dark"] and not r["known_dark"]]
    critical_dark = [r for r in dark if r["critical"]]

    # Unified logging: ship the dark-component decisions to OpenObserve (one searchable place).
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        import obs_log
        if dark:
            obs_log.ship("orchestrator", [{"source": "registry-check", "component": r["name"],
                "comp_type": r["type"], "critical": r["critical"], "reason": r["reason"],
                "level": "error" if r["critical"] else "warn"} for r in dark])
    except Exception:
        pass

    if "--no-metrics" not in sys.argv:
        try:
            lines = [
                "# HELP registry_components_total Declared components in the registry manifest.",
                "# TYPE registry_components_total gauge",
                f"registry_components_total {total}",
                "# HELP registry_dark_total Components failing liveness (excl. known_dark).",
                "# TYPE registry_dark_total gauge",
                f"registry_dark_total {len(dark)}",
                "# HELP registry_critical_dark_total CRITICAL components failing liveness.",
                "# TYPE registry_critical_dark_total gauge",
                f"registry_critical_dark_total {len(critical_dark)}",
                "# HELP registry_check_last_run_timestamp_seconds Unix ts of the last registry check.",
                "# TYPE registry_check_last_run_timestamp_seconds gauge",
                f"registry_check_last_run_timestamp_seconds {_now()}",
                "# HELP registry_component_dark 1 if a critical component is dark, labelled.",
                "# TYPE registry_component_dark gauge",
            ]
            for r in critical_dark:
                safe = re.sub(r'[^A-Za-z0-9:_-]', '_', r["name"])
                lines.append(f'registry_component_dark{{name="{safe}",type="{r["type"]}"}} 1')
            tmp = OUT_PROM.with_suffix(".prom.tmp")
            tmp.write_text("\n".join(lines) + "\n")
            tmp.rename(OUT_PROM)
        except Exception as e:
            print(f"  metric write failed: {e}", file=sys.stderr)

    if "--quiet" not in sys.argv:
        print(f"  registry: {total} components | {len(dark)} dark | {len(critical_dark)} CRITICAL-dark")
        by_type = {}
        for r in results:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        print("  by type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
        if critical_dark:
            print("  CRITICAL DARK:")
            for r in critical_dark:
                print(f"    !! {r['name']} ({r['type']}): {r['reason']}")
        if dark and not critical_dark:
            print(f"  (informational dark: {len(dark)} non-critical — tune `critical`/`known_dark` in the manifest)")

    return 1 if critical_dark else 0


if __name__ == "__main__":
    sys.exit(main())
