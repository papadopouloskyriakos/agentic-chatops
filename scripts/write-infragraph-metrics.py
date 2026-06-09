#!/usr/bin/env python3
"""Prometheus textfile exporter for infragraph health (IFRNLLEI01PRD-1037).

Cron: */5 * * * * on nl-claude01 → /var/lib/node_exporter/textfile_collector/infragraph.prom
Alerts consuming these series live in prometheus/alert-rules/agentic-health.yml
(InfragraphMetricsExporterStale, InfragraphSeedStale, InfragraphPrecisionDrop).
"""
from __future__ import annotations

import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import infragraph  # noqa: E402

PROM_DIR = os.environ.get("TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector")
OUT = os.path.join(PROM_DIR, "infragraph.prom")


def _seed_epoch(value: str) -> float:
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (ValueError, TypeError):
        return 0.0


def main() -> int:
    conn = infragraph.get_db()
    try:
        h = infragraph.health(conn)
    finally:
        conn.close()

    lines = [
        "# HELP infragraph_nodes_total Infragraph entity count by type",
        "# TYPE infragraph_nodes_total gauge",
    ]
    for t, n in sorted((h.get("nodes_by_type") or {}).items()):
        lines.append(f'infragraph_nodes_total{{type="{t}"}} {n}')
    lines += [
        "# HELP infragraph_edges_total Infragraph edge count by rel_type",
        "# TYPE infragraph_edges_total gauge",
    ]
    for r, n in sorted((h.get("edges_by_rel") or {}).items()):
        lines.append(f'infragraph_edges_total{{rel="{r}"}} {n}')
    lines += [
        "# HELP infragraph_edges_by_source Infragraph edge count by provenance",
        "# TYPE infragraph_edges_by_source gauge",
    ]
    for s, n in sorted((h.get("edges_by_source") or {}).items()):
        lines.append(f'infragraph_edges_by_source{{source="{s}"}} {n}')
    lines += [
        "# HELP infragraph_stale_edges Edges past their valid_until expiry",
        "# TYPE infragraph_stale_edges gauge",
        f"infragraph_stale_edges {h.get('stale_edges', 0)}",
        "# HELP infragraph_dynamics_coverage Fraction of edges carrying learned/declared dynamics",
        "# TYPE infragraph_dynamics_coverage gauge",
        f"infragraph_dynamics_coverage {h.get('dynamics_coverage', 0)}",
        "# HELP infragraph_last_seed_timestamp Unix time of last successful seed per source",
        "# TYPE infragraph_last_seed_timestamp gauge",
    ]
    for src, ts in sorted((h.get("last_seed") or {}).items()):
        lines.append(f'infragraph_last_seed_timestamp{{source="{src}"}} {_seed_epoch(ts):.0f}')
    preds = h.get("predictions") or {}
    lines += [
        "# HELP infragraph_predictions_total Recorded shadow predictions",
        "# TYPE infragraph_predictions_total gauge",
        f"infragraph_predictions_total {preds.get('total', 0)}",
        "# HELP infragraph_predictions_evaluated_total Evaluated shadow predictions",
        "# TYPE infragraph_predictions_evaluated_total gauge",
        f"infragraph_predictions_evaluated_total {preds.get('evaluated', 0)}",
    ]
    for k in ("precision_30d", "recall_30d"):
        v = preds.get(k)
        if v is not None:
            lines += [
                f"# HELP infragraph_{k} 30d {k.split('_', 1)[0]} of evaluated predictions",
                f"# TYPE infragraph_{k} gauge",
                f"infragraph_{k} {v}",
            ]
    lines += [
        "# HELP infragraph_exporter_last_run_timestamp Unix time this exporter last ran",
        "# TYPE infragraph_exporter_last_run_timestamp gauge",
        f"infragraph_exporter_last_run_timestamp {int(time.time())}",
        "",
    ]

    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    os.replace(tmp, OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
