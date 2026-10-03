#!/usr/bin/env python3
"""interaction-graph.py — Brick 2 of the orchestrator control-plane (IFRNLLEI01PRD-1421).

The brick NO off-the-shelf tool gives you, because the overlaps/gaps are specific to THIS
substrate: who reads/writes which SQLite table, who holds which lock, who occupies which cron
time-slot, who writes which .prom. Static-analyzes every registered cron component's source
and reconciles declared-vs-observed to surface, mechanically:

  CONFLICT   — a table written by >=2 components (shared-write race risk; e.g. the double-flock
               and auto-resolve-dedup classes).
  GAP        — a table READ by >=1 component but WRITTEN by none (orphan consumer) OR whose only
               writers are dark/removed. This is the Session-End -> reconcile hole that silently
               darkened 4 analytics tables: a handoff where neither side owned the side-effect.
  CRON-CLASH — >=2 crons firing the same exact minute (resource-spike contention).
  LOCK-SHARE — >=2 components flocking the same path (intended cross-process serialization, but
               surfaced so it's a known interaction, not a discovered-when-it-breaks one).

Reads the registry manifest (config/component-registry.json) for the component->script mapping.
Emits config/interaction-graph.json + Prometheus metrics + a report. Copies Dagster's asset-graph
model (data dependencies) in ~hundreds of lines instead of running the Dagster daemon.

Usage: interaction-graph.py [--no-metrics] [--quiet] [--json-only]
"""
import json
import os
REDACTED_a7b84d63
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "config" / "component-registry.json"
GRAPH_OUT = REPO / "config" / "interaction-graph.json"
PROM_DIR = Path(os.environ.get("PROMETHEUS_TEXTFILE_DIR",
                               "/var/lib/node_exporter/textfile_collector"))
OUT_PROM = PROM_DIR / "interaction_graph.prom"

# SQL surface (approximate — catches the common static SQL; dynamic SQL is best-effort).
RE_WRITE = [
    re.compile(r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+[`'\"]?(\w+)", re.I),
    re.compile(r"REPLACE\s+INTO\s+[`'\"]?(\w+)", re.I),
    re.compile(r"UPDATE\s+[`'\"]?(\w+)[`'\"]?\s+SET", re.I),
    re.compile(r"DELETE\s+FROM\s+[`'\"]?(\w+)", re.I),
]
RE_READ = re.compile(r"(?<!DELETE )(?<!DELETE  )FROM\s+[`'\"]?(\w+)|JOIN\s+[`'\"]?(\w+)", re.I)
RE_PROM = re.compile(r"textfile_collector/([\w.-]+)\.prom|node-exporter/([\w.-]+)\.prom|/([\w.-]+)\.prom\b")
RE_FLOCK = re.compile(r"flock\b[^\n]*?([/\$][\w./${}-]+\.lock|\b\w+\.lock)|LOCK=[\"']?([/\$][\w./${}-]+)")
# noise: SQLite pragma/internal + common false table tokens
NOISE = {"sqlite_master", "pragma_table_info", "dual", "select", "where", "values", "set"}


def _script_path(cmd: str) -> Path | None:
    m = re.search(r"(\S+/)?((?:scripts|openclaw)[\w./-]*\.(?:sh|py))", cmd)
    if not m:
        m = re.search(r"([\w./-]+\.(?:sh|py))", cmd)
    if not m:
        return None
    cand = m.group(0)
    for base in (REPO, Path("/")):
        p = (base / cand) if not cand.startswith("/") else Path(cand)
        if p.exists():
            return p
    # bare scripts/X.sh
    p = REPO / cand.lstrip("/")
    return p if p.exists() else None


def analyze_script(p: Path) -> dict:
    try:
        txt = p.read_text(errors="ignore")
    except Exception:
        return {"writes": [], "reads": [], "proms": [], "locks": []}
    writes, reads, proms, locks = set(), set(), set(), set()
    for rx in RE_WRITE:
        writes.update(t.lower() for t in rx.findall(txt))
    # Dynamic table names: `TRACE_TABLE = "otel_spans"` used in `INSERT INTO {TRACE_TABLE}` /
    # `... + TRACE_TABLE` / f-strings. Resolve the var->table binding so these aren't false gaps.
    for var, tbl in re.findall(r"(\w*(?:[Tt]able|TABLE)\w*)\s*=\s*['\"](\w+)['\"]", txt):
        if re.search(r"(?:INSERT|REPLACE)\s+(?:OR\s+\w+\s+)?INTO\s+[{(\"'+ ]*" + re.escape(var) + r"\b", txt) \
                or re.search(r"UPDATE\s+[{(\"'+ ]*" + re.escape(var) + r"\b", txt):
            writes.add(tbl.lower())
    for a, b in RE_READ.findall(txt):
        t = (a or b).lower()
        if t:
            reads.add(t)
    for g in RE_PROM.findall(txt):
        proms.add(next(x for x in g if x))
    for a, b in RE_FLOCK.findall(txt):
        if a or b:
            locks.add((a or b).strip())
    clean = lambda s: sorted(t for t in s if t and t not in NOISE and not t.isdigit())
    return {"writes": clean(writes), "reads": clean(reads),
            "proms": sorted(proms), "locks": sorted(locks)}


def main() -> int:
    comps = json.loads(MANIFEST.read_text())["components"]
    known_tables = {c["name"].split(":", 1)[1] for c in comps if c["type"] == "db-table"}
    known_dark_tables = {c["name"].split(":", 1)[1] for c in comps
                         if c["type"] == "db-table" and c.get("known_dark")}

    # Analyse EVERY repo script (not just cron entry-points): a table written by a sub-script
    # that a cron calls (e.g. session_quality <- compute-quality-score.sh, invoked by reconcile)
    # is a real writer. Excluding qa/tests avoids test-fixture write noise.
    writers, readers, prom_writers, lockers = {}, {}, {}, {}
    nodes = {}
    script_files = []
    for pat in ("scripts/**/*.sh", "scripts/**/*.py", "openclaw/**/*.sh", "openclaw/**/*.py"):
        script_files += [p for p in REPO.glob(pat)
                         if "/qa/" not in str(p) and "/tests/" not in str(p)]
    for sp in sorted(set(script_files)):
        rel = str(sp.relative_to(REPO))
        info = analyze_script(sp)
        if not any(info[k] for k in ("writes", "reads", "proms", "locks")):
            continue
        nodes[rel] = info
        for t in info["writes"]:
            writers.setdefault(t, []).append(rel)
        for t in info["reads"]:
            readers.setdefault(t, []).append(rel)
        for pr in info["proms"]:
            prom_writers.setdefault(pr, []).append(rel)
        for lk in info["locks"]:
            lockers.setdefault(lk, []).append(rel)

    # cron-slot clashes come from the manifest's declared triggers (the scheduling layer).
    cron_min = {}
    for c in comps:
        if c["type"] != "cron":
            continue
        trig = (c.get("trigger") or "").split()
        if len(trig) >= 2:
            cron_min.setdefault(f"{trig[0]} {trig[1]}", []).append(c["name"])

    # detections
    conflicts = [{"table": t, "writers": w} for t, w in sorted(writers.items()) if len(set(w)) >= 2]
    prom_conflicts = [{"prom": p, "writers": w} for p, w in sorted(prom_writers.items()) if len(set(w)) >= 2]
    gaps = [{"table": t, "readers": r}
            for t, r in sorted(readers.items())
            if t in known_tables and t not in writers and t not in known_dark_tables]
    cron_clashes = [{"slot": s, "crons": c} for s, c in sorted(cron_min.items())
                    if len(c) >= 2 and not s.startswith("*")]
    lock_shares = [{"lock": lk, "components": comps_} for lk, comps_ in sorted(lockers.items())
                   if len(set(comps_)) >= 2]

    graph = {
        "_comment": ("Interaction graph — Brick 2 of the orchestrator control-plane "
                     "(IFRNLLEI01PRD-1421). Static-analyzed from registered cron components; "
                     "regenerate with interaction-graph.py. CONFLICT/GAP/CRON-CLASH are the "
                     "mechanically-detected overlaps the federation lacked."),
        "generated_unix": None,
        "summary": {"analyzed_scripts": len(nodes), "conflicts": len(conflicts),
                    "prom_conflicts": len(prom_conflicts), "gaps": len(gaps),
                    "cron_clashes": len(cron_clashes), "lock_shares": len(lock_shares)},
        "conflicts": conflicts, "prom_conflicts": prom_conflicts, "gaps": gaps,
        "cron_clashes": cron_clashes, "lock_shares": lock_shares, "nodes": nodes,
    }
    if "--json-only" not in sys.argv:
        GRAPH_OUT.write_text(json.dumps(graph, indent=2) + "\n")

    # Unified logging: ship the interaction-graph findings to OpenObserve (orchestrator stream).
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        import obs_log
        recs = ([{"source": "interaction-graph", "kind": "conflict", "table": c["table"],
                  "writers": ",".join(c["writers"]), "level": "warn"} for c in conflicts]
                + [{"source": "interaction-graph", "kind": "gap", "table": g["table"],
                   "readers": ",".join(g["readers"]), "level": "error"} for g in gaps]
                + [{"source": "interaction-graph", "kind": "cron_clash", "slot": cc["slot"],
                   "crons": ",".join(cc["crons"]), "level": "info"} for cc in cron_clashes])
        if recs:
            obs_log.ship("orchestrator", recs)
    except Exception:
        pass

    if "--no-metrics" not in sys.argv:
        try:
            lines = [
                "# HELP interaction_graph_conflicts_total Tables with >=2 writers (shared-write race).",
                "# TYPE interaction_graph_conflicts_total gauge",
                f"interaction_graph_conflicts_total {len(conflicts)}",
                "# HELP interaction_graph_gaps_total Tables read but written by no live component.",
                "# TYPE interaction_graph_gaps_total gauge",
                f"interaction_graph_gaps_total {len(gaps)}",
                "# HELP interaction_graph_cron_clashes_total Cron slots with >=2 jobs.",
                "# TYPE interaction_graph_cron_clashes_total gauge",
                f"interaction_graph_cron_clashes_total {len(cron_clashes)}",
                "# HELP interaction_graph_last_run_timestamp_seconds Unix ts of last analysis.",
                "# TYPE interaction_graph_last_run_timestamp_seconds gauge",
                f"interaction_graph_last_run_timestamp_seconds {int(time.time())}",
            ]
            tmp = OUT_PROM.with_suffix(".prom.tmp")
            tmp.write_text("\n".join(lines) + "\n")
            tmp.rename(OUT_PROM)
        except Exception as e:
            print(f"  metric write failed: {e}", file=sys.stderr)

    if "--quiet" not in sys.argv and "--json-only" not in sys.argv:
        s = graph["summary"]
        print(f"  analyzed {s['analyzed_scripts']} scripts | "
              f"conflicts={s['conflicts']} prom_conflicts={s['prom_conflicts']} "
              f"gaps={s['gaps']} cron_clashes={s['cron_clashes']} lock_shares={s['lock_shares']}")
        for g in gaps:
            print(f"  GAP: table '{g['table']}' is read by {g['readers']} but written by NO live component")
        for c in conflicts:
            print(f"  CONFLICT: table '{c['table']}' written by {sorted(set(c['writers']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
