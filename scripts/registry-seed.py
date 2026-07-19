#!/usr/bin/env python3
"""registry-seed.py — Brick 1 of the agentic orchestrator control-plane (IFRNLLEI01PRD-1421).

Auto-discovers agentic components from the LIVE substrate and emits/merges the declared
manifest config/component-registry.json — the single source of truth the 2026-06-25
dark-component audit lacked (MemPalace hooks, session_quality, otel_spans, the holistic
self-audit ITSELF ran dark for months because nothing owned their liveness as a set).

Discovery sources:
  1. crontab           -> one component per non-comment cron line (script + schedule + cadence)
  2. textfile collector -> one component per *.prom writer (Prometheus liveness via mtime)
  3. n8n workflows      -> one component per workflow (via the API)
  4. gateway DB tables  -> the agentic tables that carry a timestamp column (write-recency liveness)

Hand-authored fields (owner, kill_switch, liveness overrides, `critical`, `expected_cadence_seconds`,
`known_dark`) are PRESERVED across re-seeds — discovery only adds new components + refreshes the
observed fields, never clobbers human metadata. Re-seed is idempotent.

Usage: registry-seed.py [--dry-run] [--manifest PATH]
"""
import json
import os
REDACTED_a7b84d63
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "config" / "component-registry.json"
PROM_DIR = Path(os.environ.get("PROMETHEUS_TEXTFILE_DIR",
                               "/var/lib/node_exporter/textfile_collector"))
DB_PATH = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
# Hand-authored metadata preserved across re-seeds. NOTE: `liveness` is NOT here — it is
# always refreshed from discovery so default-threshold changes take effect; tune a specific
# component via `liveness_override` (a dict merged onto the auto liveness, e.g.
# {"max_stale_seconds": 900} for a high-frequency writer).
HAND_FIELDS = ("owner", "kill_switch", "liveness_override", "critical",
               "expected_cadence_seconds", "known_dark", "notes")

# ── cadence parsing (coarse — enough to bound staleness) ──────────────────────
def _cadence_seconds(schedule: str) -> int | None:
    f = schedule.split()
    if len(f) < 5:
        return None
    minute, hour, dom, mon, dow = f[:5]
    if minute.startswith("*/"):
        try: return int(minute[2:]) * 60
        except ValueError: pass
    if hour.startswith("*/"):
        try: return int(hour[2:]) * 3600
        except ValueError: pass
    if minute != "*" and hour == "*":
        return 3600                      # every hour at :MM
    if minute != "*" and hour != "*" and dom == "*" and dow == "*":
        return 86400                     # daily
    if dow != "*":
        return 604800                    # weekly
    if dom != "*":
        return 2592000                   # monthly
    if minute == "*":
        return 60
    return 86400


def _name_from_cron(cmd: str) -> str:
    m = re.search(r"([A-Za-z0-9_-]+)\.(?:sh|py)", cmd)
    if m:
        return m.group(1)
    m = re.search(r"--?([A-Za-z][A-Za-z0-9_-]+)", cmd)
    return ("cron-" + m.group(1)) if m else "cron-unknown"


def discover_crons() -> list[dict]:
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    comps = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^((?:\S+\s+){5})(.+)$", line)
        if not m:
            continue
        schedule, cmd = m.group(1).strip(), m.group(2).strip()
        comps.append({
            "name": _name_from_cron(cmd),
            "type": "cron",
            "trigger": schedule,
            "observed_cadence_seconds": _cadence_seconds(schedule),
            "command": cmd[:200],
        })
    return comps


def _timing_summary(t: dict) -> str:
    """Compact cron-ish summary of a Cronicle timing object (for the trigger field)."""
    def f(k):
        v = t.get(k)
        return ",".join(map(str, v)) if v else "*"
    return f"{f('minutes')} {f('hours')} {f('days')} {f('months')} {f('weekdays')}"


def _cronicle_cadence(t: dict) -> int:
    """Approx seconds between runs, from the timing object (drives max_stale)."""
    mins, hours = t.get("minutes"), t.get("hours")
    if mins and not hours and len(mins) > 1:
        return max(300, 3600 // len(mins))
    if mins and not hours:
        return 3600
    if hours and len(hours) > 1:
        return max(3600, 86400 // len(hours))
    if hours:
        return 86400
    if t.get("weekdays") or t.get("days"):
        return 604800
    return 86400


def discover_cronicle() -> list[dict]:
    """Each Cronicle event -> one cronicle-job component with per-job liveness keyed to its LAST RUN
    (Cronicle tracks every run's exit code). All 172 crons migrated off crontab 2026-06-26, so this
    is the registry's per-job window into the scheduler — a specific failing job is now named in
    registry_component_dark{name}, not just counted. Best-effort (empty if Cronicle unreachable)."""
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import cronicle as cron_api
    comps, used = [], set()
    for e in cron_api.schedule():
        script = ((e.get("params") or {}).get("script", "") or "")
        cmd = script.split("\n", 1)[-1].strip() if "\n" in script else script.strip()
        # name the same way discover_crons does, so a migrated job REPLACES its old cron component
        # (not lingers as an orphan) — the crons just moved from crontab to Cronicle.
        base = _name_from_cron(cmd) or (e.get("title") or e.get("id") or "job")
        name, i = base, 2
        while name in used:
            name = f"{base}#{i}"
            i += 1
        used.add(name)
        cad = _cronicle_cadence(e.get("timing") or {})
        comps.append({
            "name": name,
            "type": "cronicle-job",
            "trigger": _timing_summary(e.get("timing") or {}),
            "observed_cadence_seconds": cad,
            "command": cmd[:200],
            "cronicle_event_id": e.get("id"),
            "cronicle_category": e.get("category"),
            "known_dark": not e.get("enabled"),
            "liveness": {"kind": "cronicle_job", "ref": e.get("id"),
                         "max_stale_seconds": min(200000, max(1800, 3 * cad))},
        })
    return comps


def discover_prom_writers() -> list[dict]:
    comps = []
    if PROM_DIR.is_dir():
        for p in sorted(PROM_DIR.glob("*.prom")):
            comps.append({
                "name": "prom:" + p.stem,
                "type": "prom-writer",
                # Default threshold = 25h: catches the dark-component CLASS (writers dark for
                # days/weeks/months — the actual failure mode) without false-positiving daily
                # writers. Tighten per-component (liveness.max_stale_seconds) + mark `critical`
                # for high-frequency writers that must be fresh within minutes (watchdog etc.).
                "liveness": {"kind": "prom_file", "ref": p.name, "max_stale_seconds": 90000},
            })
    return comps


def discover_n8n() -> list[dict]:
    key = ""
    for f in (REPO / "scripts" / "holistic-agentic-health.sh",):
        try:
            m = re.search(r'N8N_KEY="(eyJ[^"]+)"', f.read_text())
            if m: key = m.group(1)
        except Exception:
            pass
    if not key:
        return []
    try:
        import urllib.request
        req = urllib.request.Request("https://n8n.example.net/api/v1/workflows?limit=200")
        req.add_header("X-N8N-API-KEY", key)
        import ssl
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        data = json.loads(urllib.request.urlopen(req, timeout=15, context=ctx).read())
    except Exception:
        return []
    comps = []
    for w in data.get("data", []):
        comps.append({
            "name": "n8n:" + w["name"],
            "type": "n8n-workflow",
            "trigger": "webhook/execute",
            "observed_active": w.get("active"),
            "workflow_id": w.get("id"),
        })
    return comps


def discover_db_tables() -> list[dict]:
    import sqlite3
    comps = []
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for t in tables:
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info('{t}')")]
            tscol = next((c for c in ("created_at", "ts", "timestamp", "started_at",
                                      "inserted_at", "recorded_at", "handoff_at") if c in cols), None)
            if not tscol:
                continue
            comps.append({
                "name": "table:" + t,
                "type": "db-table",
                "liveness": {"kind": "db_table", "ref": t, "ts_column": tscol,
                             "max_stale_seconds": 604800},
            })
        conn.close()
    except Exception as e:
        print(f"  db discovery skipped: {e}", file=sys.stderr)
    return comps


def main() -> int:
    dry = "--dry-run" in sys.argv
    manifest_path = MANIFEST
    if "--manifest" in sys.argv:
        manifest_path = Path(sys.argv[sys.argv.index("--manifest") + 1])

    existing = {}
    if manifest_path.exists():
        for c in json.loads(manifest_path.read_text()).get("components", []):
            existing[c["name"]] = c

    discovered = (discover_crons() + discover_cronicle() + discover_prom_writers()
                  + discover_n8n() + discover_db_tables())

    merged = {}
    for c in discovered:
        prev = existing.get(c["name"], {})
        for f in HAND_FIELDS:                       # preserve human metadata
            if f in prev:
                c[f] = prev[f]
        if isinstance(c.get("liveness_override"), dict) and isinstance(c.get("liveness"), dict):
            c["liveness"].update(c["liveness_override"])   # hand-tune onto fresh auto liveness
        merged[c["name"]] = c
    # keep manifest-only (hand-authored) components not auto-discovered, flag them
    for name, c in existing.items():
        if name not in merged:
            c["observed"] = "absent"                # declared but not discovered = orphaned/removed
            merged[name] = c

    out = {
        "_comment": ("Component registry — Brick 1 of the orchestrator control-plane "
                     "(IFRNLLEI01PRD-1421). Auto-seeded by registry-seed.py; hand-authored "
                     "fields (owner/kill_switch/liveness/critical/expected_cadence_seconds/"
                     "known_dark/notes) are preserved. registry-check.py verifies liveness."),
        "components": sorted(merged.values(), key=lambda c: (c["type"], c["name"])),
    }
    by_type = {}
    for c in out["components"]:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    print(f"  discovered {len(out['components'])} components: " +
          ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    if dry:
        print("  (--dry-run: not writing)")
        return 0
    manifest_path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"  wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
