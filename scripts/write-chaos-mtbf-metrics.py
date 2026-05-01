#!/usr/bin/env python3
"""write-chaos-mtbf-metrics.py — Chaos MTBF + reliability Prometheus metrics.

Closes IFRNLLEI01PRD-695's "MTBF pipeline" half. Reads chaos_experiments
and produces per-chaos-type metrics for Grafana / Prometheus:

  chaos_mtbf_seconds{chaos_type}            — mean time between FAIL/DEGRADED verdicts
  chaos_last_failure_ago_seconds{chaos_type} — seconds since the most recent failure
  chaos_success_streak{chaos_type}          — consecutive PASS count since the last failure
  chaos_failure_count{chaos_type,window}    — FAIL+DEGRADED count in {7d,30d,90d} windows
  chaos_availability_ratio{chaos_type,window} — PASS / total in each window
  chaos_mtbf_last_run_timestamp_seconds    — self-heartbeat for cron alert

Intended cron: */5 * * * * (cheap read-only SELECTs + atomic textfile write).
Output: /var/lib/node_exporter/textfile_collector/chaos_mtbf.prom

Fail-soft: missing DB, empty table, or DB-lock timeout → emit only the
heartbeat metric and exit 0. Alerts will see the stale heartbeat.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OUT_PATH = os.environ.get(
    "CHAOS_MTBF_METRICS",
    "/var/lib/node_exporter/textfile_collector/chaos_mtbf.prom",
)
FALLBACK_OUT = "/tmp/chaos_mtbf.prom"
FAILURE_VERDICTS = ("FAIL", "DEGRADED")
WINDOWS = {"7d": 7, "30d": 30, "90d": 90}


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sanitize_label(val: str) -> str:
    """Quote-safe Prometheus label value. Restrict to a conservative charset."""
    if not val:
        return "unknown"
    return "".join(c if c.isalnum() or c in "_-:." else "_" for c in val)[:64]


def load_experiments() -> list[tuple[str, datetime, str]]:
    """Return [(chaos_type, started_at_dt, verdict)] ordered ascending by time."""
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    except sqlite3.OperationalError as e:
        print(f"WARN: cannot open DB: {e}", file=sys.stderr)
        return []
    try:
        rows = conn.execute(
            "SELECT chaos_type, started_at, verdict FROM chaos_experiments "
            "WHERE started_at IS NOT NULL "
            "ORDER BY started_at ASC"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"WARN: query failed: {e}", file=sys.stderr)
        rows = []
    conn.close()
    out = []
    for chaos_type, started_at, verdict in rows:
        dt = _parse_iso(started_at or "")
        if not dt:
            continue
        out.append((chaos_type or "unknown", dt, (verdict or "UNKNOWN").upper()))
    return out


def compute_mtbf(by_type: dict[str, list[tuple[datetime, str]]]) -> dict[str, dict[str, float]]:
    """For each chaos_type return a dict of metric values."""
    now = datetime.now(timezone.utc)
    result: dict[str, dict[str, float]] = {}
    for chaos_type, events in by_type.items():
        failures = [dt for dt, v in events if v in FAILURE_VERDICTS]
        gaps_seconds: list[float] = []
        for a, b in zip(failures, failures[1:]):
            gap = (b - a).total_seconds()
            if gap > 0:
                gaps_seconds.append(gap)
        mtbf = sum(gaps_seconds) / len(gaps_seconds) if gaps_seconds else -1.0
        last_failure_ago = (now - failures[-1]).total_seconds() if failures else -1.0
        # Success streak = consecutive PASS since last failure
        streak = 0
        for dt, v in reversed(events):
            if v in FAILURE_VERDICTS:
                break
            if v == "PASS":
                streak += 1
        # Window counts
        window_stats = {}
        for w_label, days in WINDOWS.items():
            cutoff = now - timedelta(days=days)
            w_events = [(dt, v) for dt, v in events if dt >= cutoff]
            total = len(w_events)
            fail_ct = sum(1 for _, v in w_events if v in FAILURE_VERDICTS)
            pass_ct = sum(1 for _, v in w_events if v == "PASS")
            avail = (pass_ct / total) if total else -1.0
            window_stats[w_label] = {"total": total, "fail": fail_ct, "avail": avail}
        result[chaos_type] = {
            "mtbf": mtbf,
            "last_failure_ago": last_failure_ago,
            "streak": float(streak),
            "windows": window_stats,
        }
    return result


def render_metrics(stats: dict[str, dict[str, float]]) -> str:
    lines: list[str] = []

    def h(help_, type_):
        lines.append(f"# HELP {help_}")
        lines.append(f"# TYPE {type_}")

    h("chaos_mtbf_seconds Mean time between chaos FAIL/DEGRADED verdicts per scenario (-1 if fewer than 2 failures)",
      "chaos_mtbf_seconds gauge")
    for chaos_type, s in stats.items():
        lines.append(f'chaos_mtbf_seconds{{chaos_type="{_sanitize_label(chaos_type)}"}} {s["mtbf"]}')

    h("chaos_last_failure_ago_seconds Seconds since the most recent FAIL/DEGRADED for this scenario (-1 if never)",
      "chaos_last_failure_ago_seconds gauge")
    for chaos_type, s in stats.items():
        lines.append(f'chaos_last_failure_ago_seconds{{chaos_type="{_sanitize_label(chaos_type)}"}} {s["last_failure_ago"]}')

    h("chaos_success_streak Consecutive PASS count since the last FAIL/DEGRADED",
      "chaos_success_streak gauge")
    for chaos_type, s in stats.items():
        lines.append(f'chaos_success_streak{{chaos_type="{_sanitize_label(chaos_type)}"}} {s["streak"]}')

    h("chaos_failure_count FAIL+DEGRADED counts per scenario per rolling window",
      "chaos_failure_count gauge")
    for chaos_type, s in stats.items():
        for w, ws in s["windows"].items():
            lines.append(
                f'chaos_failure_count{{chaos_type="{_sanitize_label(chaos_type)}",window="{w}"}} {ws["fail"]}'
            )

    h("chaos_availability_ratio PASS/total ratio in rolling window (-1 if window has no experiments)",
      "chaos_availability_ratio gauge")
    for chaos_type, s in stats.items():
        for w, ws in s["windows"].items():
            lines.append(
                f'chaos_availability_ratio{{chaos_type="{_sanitize_label(chaos_type)}",window="{w}"}} {ws["avail"]}'
            )

    h("chaos_mtbf_last_run_timestamp_seconds Unix time of last successful write-chaos-mtbf-metrics run",
      "chaos_mtbf_last_run_timestamp_seconds gauge")
    lines.append(f"chaos_mtbf_last_run_timestamp_seconds {int(time.time())}")
    return "\n".join(lines) + "\n"


def atomic_write(path: str, content: str) -> str:
    """Write atomically via tmpfile + os.replace. Returns actual path written.
    Falls back to FALLBACK_OUT if the textfile dir is unavailable."""
    for candidate in (path, FALLBACK_OUT):
        try:
            Path(candidate).parent.mkdir(parents=True, exist_ok=True)
            tmp = candidate + ".tmp"
            with open(tmp, "w") as f:
                f.write(content)
            os.replace(tmp, candidate)
            return candidate
        except OSError:
            continue
    return ""


def main() -> int:
    events = load_experiments()
    by_type: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for chaos_type, dt, verdict in events:
        by_type[chaos_type].append((dt, verdict))
    stats = compute_mtbf(by_type)
    # Always emit at least the heartbeat even on empty DB
    if not stats:
        stats = {}
    body = render_metrics(stats)
    written = atomic_write(OUT_PATH, body)
    if written:
        print(f"wrote {len(stats)} chaos_type rows to {written}")
        return 0
    print("ERROR: could not write metrics anywhere", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
