#!/usr/bin/env python3
"""Ship Cronicle per-job run history (+ the captured log for FAILED runs) to OpenObserve, so the
scheduler that now runs all 172 jobs is searchable in one place (2026-06-26). Runs */10 as a Cronicle
job. A watermark file avoids re-shipping runs. For a failed run the captured stdout/stderr is fetched,
gunzipped, and shipped too — so a failure is fully debuggable from OpenObserve without opening the UI.
Best-effort; never raises.
"""
import gzip
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import cronicle as cron_api  # noqa: E402
import obs_log  # noqa: E402

WATERMARK = Path.home() / "gateway-state" / "cronicle-ship.watermark"


def _watermark():
    try:
        return float(WATERMARK.read_text().strip())
    except Exception:
        return time.time() - 3600  # first run: just the last hour


def _failed(code):
    return code not in (0, "0", None)


def main():
    url, key = cron_api.cfg()
    if not url:
        print("  no Cronicle config")
        return
    try:
        d = json.load(urllib.request.urlopen(
            f"{url}/api/app/get_history?api_key={key}&limit=2000", timeout=10))
        rows = d.get("rows", []) if d.get("code") == 0 else []
    except Exception:
        print("  history fetch failed")
        return

    last = _watermark()
    new = [r for r in rows if (r.get("time_start") or 0) > last]
    sid = cron_api.login() if any(_failed(r.get("code")) for r in new) else ""

    recs = []
    for r in new:
        rec = {
            "_timestamp": int((r.get("time_start") or time.time()) * 1_000_000),
            "source": "cronicle",
            "job": r.get("event_title"),
            "event_id": r.get("event"),
            "code": r.get("code"),
            "elapsed": r.get("elapsed"),
            "level": "error" if _failed(r.get("code")) else "info",
        }
        if _failed(r.get("code")) and sid:
            try:
                raw = urllib.request.urlopen(
                    f"{url}/api/app/get_job_log?id={r['id']}&session_id={sid}", timeout=8).read()
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
                rec["log_tail"] = raw[-2000:].decode("utf-8", "replace")
            except Exception:
                pass
        recs.append(rec)

    if recs:
        obs_log.ship("cronicle_runs", recs)
    if rows:
        try:
            WATERMARK.parent.mkdir(parents=True, exist_ok=True)
            WATERMARK.write_text(str(max((r.get("time_start") or 0) for r in rows)))
        except Exception:
            pass
    print(f"  shipped {len(recs)} run(s) to OpenObserve (stream cronicle_runs)")


if __name__ == "__main__":
    main()
