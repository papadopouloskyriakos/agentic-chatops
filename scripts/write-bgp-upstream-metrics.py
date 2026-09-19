#!/usr/bin/env python3
"""
write-bgp-upstream-metrics.py — node_exporter textfile collector for the
public BGP upstream/transit state of AS64512 as visible via RIPE STAT.

Paired alerts (deployed via IaC at
infrastructure/nl/production/k8s/namespaces/monitoring/bgp-upstream-alerts.tf,
mirrored in claude-gateway prometheus/alert-rules/bgp-upstream-health.yml):

  - AS64512UpstreamMissing       per-upstream gauge drops to 0 for 10 min
  - AS64512UpstreamCountLow      < 2 upstreams visible for 5 min  (we're single-homed)
  - AS64512VisibilityLow         v6 prefix visibility < 90 % for 15 min
  - AS64512BGPMetricsExporterStale  this script has not produced fresh metrics for 30 min

The script reuses `get_ripe_bgp()` from `scripts/vpn-mesh-stats.py` so the
metric definition of "upstream" and "transit" matches what the live status
diagram on kyriakos.papadopoulos.tech renders. Both pipelines share a single
RIPE call signature; this script is independent (not coupled to the n8n
webhook), so RIPE hiccups affect the diagram and the alerts identically.

Wired by cron `*/5 * * * *` in app-user's crontab on nl-claude01.

Background: 2026-05-16 root-cause + resolved memory:
claude-gateway memory/status_diagram_upstream_render_gaps_20260516.md.
"""

import importlib.util
import os
import sys
import tempfile
import time

TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
OUT_FILE = os.path.join(TEXTFILE_DIR, "bgp_upstream.prom")

# AS_NAMES mirror of static/js/mesh-graph.js:19 — used for label hygiene
# in alert annotations. Unknown ASNs render as bare "ASxxxxx".
AS_NAMES = {
    214304: "AS64512",
    34927: "iFog",
    56655: "Terrahost",
    6939: "Hurricane Electric",
    9002: "RETN",
    24482: "SG.GS",
    8218: "Zayo",
    58057: "Securebit",
    174: "Cogent",
    1299: "Arelion",
    2914: "NTT",
    3356: "Lumen",
    6830: "Liberty Global",
    12779: "Italtel",
}


def load_ripe_module():
    """Import the get_ripe_bgp() function from vpn-mesh-stats.py.

    Done dynamically because vpn-mesh-stats.py has a non-module-friendly
    name and lives next to this script in scripts/. Reusing it ensures the
    metric-definition of "upstream" and "transit" stays in lockstep with
    the status-diagram payload."""
    here = os.path.dirname(os.path.abspath(__file__))
    vms_path = os.path.join(here, "vpn-mesh-stats.py")
    spec = importlib.util.spec_from_file_location("vpn_mesh_stats", vms_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {vms_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def escape_label(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render(bgp: dict) -> str:
    lines = [
        "# HELP as214304_upstream_visible 1 iff RIPE asn-neighbours reports the ASN as a left-neighbour of AS64512.",
        "# TYPE as214304_upstream_visible gauge",
        "# HELP as214304_upstream_power RIPE-computed visibility-weighted power score for the upstream peering.",
        "# TYPE as214304_upstream_power gauge",
        "# HELP as214304_upstream_count Total distinct upstream peers visible at RIPE for AS64512.",
        "# TYPE as214304_upstream_count gauge",
        "# HELP as214304_visibility_v6_pct Percentage of RIPE RIS peers that currently see the /48 prefix.",
        "# TYPE as214304_visibility_v6_pct gauge",
        "# HELP as214304_ris_peers_seeing RIPE RIS peers currently seeing the /48.",
        "# TYPE as214304_ris_peers_seeing gauge",
        "# HELP as214304_ris_peers_total Total RIPE RIS peers (denominator).",
        "# TYPE as214304_ris_peers_total gauge",
        "# HELP as214304_transit_count_per_upstream Distinct transit ASes observed routing via each upstream (matches diagram).",
        "# TYPE as214304_transit_count_per_upstream gauge",
        "# HELP as214304_transit_path_count_per_upstream RIPE path observations summed across transits for each upstream.",
        "# TYPE as214304_transit_path_count_per_upstream gauge",
        "# HELP as214304_bgp_metrics_last_run_timestamp Unix time of last successful metrics emission.",
        "# TYPE as214304_bgp_metrics_last_run_timestamp gauge",
    ]

    upstreams = bgp.get("upstreams") or []
    top_paths = bgp.get("top_paths") or []

    for u in upstreams:
        asn = int(u.get("asn", 0))
        if not asn:
            continue
        name = escape_label(AS_NAMES.get(asn, f"AS{asn}"))
        power = int(u.get("power", 0) or 0)
        lines.append(
            f'as214304_upstream_visible{{asn="{asn}",name="{name}"}} 1'
        )
        lines.append(
            f'as214304_upstream_power{{asn="{asn}",name="{name}"}} {power}'
        )

    lines.append(f"as214304_upstream_count {len(upstreams)}")

    vis = bgp.get("visibility_v6_pct")
    if vis is not None:
        lines.append(f"as214304_visibility_v6_pct {float(vis)}")

    rps = bgp.get("ris_peers_seeing")
    rpt = bgp.get("ris_peers_total")
    if rps is not None:
        lines.append(f"as214304_ris_peers_seeing {int(rps)}")
    if rpt is not None:
        lines.append(f"as214304_ris_peers_total {int(rpt)}")

    # Per-upstream transit aggregation
    per_upstream_transit_count: dict[int, int] = {}
    per_upstream_path_sum: dict[int, int] = {}
    for p in top_paths:
        parts = (p.get("path") or "").split()
        if len(parts) < 3:
            continue
        try:
            transit_asn = int(parts[0])
            upstream_asn = int(parts[1])
        except ValueError:
            continue
        per_upstream_transit_count[upstream_asn] = (
            per_upstream_transit_count.get(upstream_asn, 0) + 1
        )
        per_upstream_path_sum[upstream_asn] = (
            per_upstream_path_sum.get(upstream_asn, 0) + int(p.get("count", 0) or 0)
        )
        # Suppress the unused transit_asn variable warning while keeping
        # the destructure self-documenting.
        _ = transit_asn

    for upstream_asn, count in per_upstream_transit_count.items():
        name = escape_label(AS_NAMES.get(upstream_asn, f"AS{upstream_asn}"))
        lines.append(
            f'as214304_transit_count_per_upstream{{upstream_asn="{upstream_asn}",upstream_name="{name}"}} {count}'
        )
        psum = per_upstream_path_sum.get(upstream_asn, 0)
        lines.append(
            f'as214304_transit_path_count_per_upstream{{upstream_asn="{upstream_asn}",upstream_name="{name}"}} {psum}'
        )

    lines.append(f"as214304_bgp_metrics_last_run_timestamp {int(time.time())}")
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        mod = load_ripe_module()
        bgp = mod.get_ripe_bgp()
    except Exception as e:
        print(f"warning: failed to call get_ripe_bgp(): {e}", file=sys.stderr)
        return 0

    payload = render(bgp)
    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".bgp_upstream.", suffix=".prom", dir=TEXTFILE_DIR
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.chmod(tmp, 0o644)
        os.replace(tmp, OUT_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
