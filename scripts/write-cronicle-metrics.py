#!/usr/bin/env python3
"""Cronicle health -> Prometheus textfile collector.

The orchestrator's window into the new scheduler (migrated from crontab 2026-06-26): total/enabled
jobs, recent run FAILURES (the per-job-death signal raw cron could never surface), and scheduler
liveness. Reads CRONICLE_URL + CRONICLE_API_KEY from the gateway .env. Fails safe: if Cronicle is
unreachable, emits cronicle_scheduler_up 0 (which an alert pages on — who-watches-the-scheduler).
"""
import json
import os
import time
import urllib.request
from pathlib import Path

OUT = "/var/lib/node_exporter/textfile_collector/cronicle_metrics.prom"
ENV = Path("/app/claude-gateway/.env")


def _env():
    e = {}
    try:
        for line in ENV.read_text().splitlines():
            if line.startswith("CRONICLE_") and "=" in line:
                k, v = line.split("=", 1)
                e[k] = v.strip()
    except Exception:
        pass
    return e


def _get(url):
    return json.load(urllib.request.urlopen(url, timeout=10))


def main():
    e = _env()
    base, key = e.get("CRONICLE_URL"), e.get("CRONICLE_API_KEY")
    up = total = enabled = runs = fails = 0
    cats, failed_events = {}, set()
    try:
        sched = _get(f"{base}/api/app/get_schedule?api_key={key}&limit=2000")
        if sched.get("code") == 0:
            up = 1
            rows = sched["rows"]
            total = len(rows)
            enabled = sum(1 for r in rows if r.get("enabled"))
            for r in rows:
                c = r.get("category", "unknown")
                cats[c] = cats.get(c, 0) + 1
        hist = _get(f"{base}/api/app/get_history?api_key={key}&limit=300")
        if hist.get("code") == 0:
            for j in hist["rows"]:
                runs += 1
                if j.get("code") not in (0, "0", None):
                    fails += 1
                    failed_events.add(j.get("event") or j.get("event_title") or "?")
    except Exception:
        up = 0

    lines = [
        "# HELP cronicle_scheduler_up Cronicle scheduler reachable (1) or down (0)",
        "# TYPE cronicle_scheduler_up gauge",
        f"cronicle_scheduler_up {up}",
        "# HELP cronicle_jobs_total Total scheduled jobs in Cronicle",
        "# TYPE cronicle_jobs_total gauge",
        f"cronicle_jobs_total {total}",
        "# HELP cronicle_jobs_enabled Enabled scheduled jobs",
        "# TYPE cronicle_jobs_enabled gauge",
        f"cronicle_jobs_enabled {enabled}",
        "# HELP cronicle_runs_recent_total Recent job runs in the history window",
        "# TYPE cronicle_runs_recent_total gauge",
        f"cronicle_runs_recent_total {runs}",
        "# HELP cronicle_runs_recent_failed Recent runs that exited non-zero",
        "# TYPE cronicle_runs_recent_failed gauge",
        f"cronicle_runs_recent_failed {fails}",
        "# HELP cronicle_jobs_failed_recently Distinct jobs with a recent failed run (the per-job-death gap)",
        "# TYPE cronicle_jobs_failed_recently gauge",
        f"cronicle_jobs_failed_recently {len(failed_events)}",
        "# HELP cronicle_metrics_last_run_timestamp_seconds Last export time",
        "# TYPE cronicle_metrics_last_run_timestamp_seconds gauge",
        f"cronicle_metrics_last_run_timestamp_seconds {int(time.time())}",
        "# HELP cronicle_jobs_by_category Jobs per category",
        "# TYPE cronicle_jobs_by_category gauge",
    ]
    for c, n in sorted(cats.items()):
        lines.append(f'cronicle_jobs_by_category{{category="{c}"}} {n}')

    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, OUT)


if __name__ == "__main__":
    main()
