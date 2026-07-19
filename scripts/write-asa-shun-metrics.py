#!/usr/bin/env python3
"""ASA shun-table metrics exporter.

Emits Prometheus textfile metrics for the threat-detection shun table on both
ASAs so operators get paged when an IP is shunned. Written after the
2026-04-22 incident where rtr01 (10.0.X.X) was auto-shunned during the
Freedom-shut failover test — no alert fired because nothing was watching the
shun table. The `ASAShunInstalled` alert (prometheus/alert-rules/
infrastructure-integrity.yml) fires on `asa_shun_count > 0 for 2m`.

Cron: */5 * * * * /app/claude-gateway/scripts/write-asa-shun-metrics.sh
"""
from __future__ import annotations

import os
import pathlib
REDACTED_a7b84d63
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/lib")

PROM_DEFAULT = "/var/lib/node_exporter/textfile_collector/asa_shun.prom"

# `show shun` emits one line per active shun, formatted:
#   "shun (<interface>) <src_ip> <dst_ip> <src_port> <dst_port> <proto>"
# `show shun statistics` emits a per-interface state block AND a per-IP
# summary line at the bottom:
#   "<interface>=<ON|OFF>, cnt=<N>"              (per-interface hit counts)
#   "Shun <src_ip> cnt=<N>, time=(hh:mm:ss)"     (per-IP summary, capital S)
SHUN_ACTIVE_RE = re.compile(r"^shun\s+\(([^)]+)\)\s+(\S+)\s+(\S+)")
SHUN_STATS_IP_RE = re.compile(r"^Shun\s+(\S+)\s+cnt=(\d+)")
SHUN_STATS_IFACE_RE = re.compile(r"^(\S+?)=(ON|OFF),\s+cnt=(\d+)")


def parse_shun_output(raw: str) -> list[str]:
    """Return list of shunned source IPs from `show shun` output."""
    if not raw or raw.startswith("ERROR"):
        return []
    ips = []
    for line in raw.splitlines():
        m = SHUN_ACTIVE_RE.match(line.strip())
        if m:
            ips.append(m.group(2))
    return ips


def parse_stats_output(raw: str) -> dict:
    """Parse `show shun statistics` output.

    Returns dict with:
        ip_hits: {src_ip: total_hits}   — from per-IP "Shun <ip> cnt=N" lines
        iface:   {iface: hits}          — from "<iface>=ON|OFF, cnt=N" lines
                                          (only ON interfaces are reported)
    """
    stats = {"ip_hits": {}, "iface": {}}
    if not raw or raw.startswith("ERROR"):
        return stats
    for line in raw.splitlines():
        s = line.strip()
        m = SHUN_STATS_IP_RE.match(s)
        if m:
            stats["ip_hits"][m.group(1)] = int(m.group(2))
            continue
        m = SHUN_STATS_IFACE_RE.match(s)
        if m and m.group(2) == "ON":
            stats["iface"][m.group(1)] = int(m.group(3))
    return stats


def fetch_nl() -> tuple[list[str], dict]:
    from asa_ssh import ssh_nl_asa_command
    shun_out = ssh_nl_asa_command(["show shun", "show shun statistics"])
    # Split at the second command's boundary — both concatenated in output
    if "show shun statistics" in shun_out:
        idx = shun_out.index("show shun statistics")
        shun_part, stats_part = shun_out[:idx], shun_out[idx:]
    else:
        shun_part, stats_part = shun_out, ""
    return parse_shun_output(shun_part), parse_stats_output(stats_part)


def fetch_gr() -> tuple[list[str], dict]:
    from asa_ssh import ssh_gr_asa_command
    shun_out = ssh_gr_asa_command(["show shun", "show shun statistics"])
    if "show shun statistics" in shun_out:
        idx = shun_out.index("show shun statistics")
        shun_part, stats_part = shun_out[:idx], shun_out[idx:]
    else:
        shun_part, stats_part = shun_out, ""
    return parse_shun_output(shun_part), parse_stats_output(stats_part)


def emit_prom(results: dict, path: str) -> None:
    tmp = pathlib.Path(path + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    lines += [
        "# HELP asa_shun_count Number of IPs currently in the ASA threat-detection shun table",
        "# TYPE asa_shun_count gauge",
    ]
    for asa, (ips, _stats) in results.items():
        lines.append(f'asa_shun_count{{device="{asa}"}} {len(ips)}')

    lines += [
        "# HELP asa_shun_hits_total Total packet hits against shun entries per-interface since last clear",
        "# TYPE asa_shun_hits_total gauge",
    ]
    for asa, (_ips, stats) in results.items():
        for iface, cnt in stats.get("iface", {}).items():
            lines.append(f'asa_shun_hits_total{{device="{asa}",interface="{iface}"}} {cnt}')

    lines += [
        "# HELP asa_shun_ip_hits Per-shunned-IP hit counter since last clear",
        "# TYPE asa_shun_ip_hits gauge",
    ]
    for asa, (_ips, stats) in results.items():
        for ip, cnt in stats.get("ip_hits", {}).items():
            lines.append(f'asa_shun_ip_hits{{device="{asa}",ip="{ip}"}} {cnt}')

    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)


def main() -> int:
    prom_path = os.environ.get("PROM_PATH", PROM_DEFAULT)
    try:
        nl_ips, nl_stats = fetch_nl()
    except Exception as e:
        print(f"ERROR querying nl-fw01: {e}", file=sys.stderr)
        nl_ips, nl_stats = [], {}
    try:
        gr_ips, gr_stats = fetch_gr()
    except Exception as e:
        print(f"ERROR querying gr-fw01: {e}", file=sys.stderr)
        gr_ips, gr_stats = [], {}

    results = {
        "nl-fw01": (nl_ips, nl_stats),
        "gr-fw01": (gr_ips, gr_stats),
    }

    if prom_path:
        emit_prom(results, prom_path)

    # Stdout summary so cron log catches state
    for asa, (ips, _stats) in results.items():
        status = f"{len(ips)} shunned" if ips else "clean"
        print(f"{asa}: {status} ({', '.join(ips) if ips else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
