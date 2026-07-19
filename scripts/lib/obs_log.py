"""Ship structured logs to self-hosted OpenObserve — the unified agentic log sink (2026-06-26).

One searchable, retained place for the scheduler's per-job runs/logs + the orchestrator's decisions,
instead of the previous scatter (local .log files + Cronicle storage + Prometheus + the gateway DB).
Best-effort — NEVER raises (logging must not break the caller). Auth = Basic base64(USER:TOKEN) from
.env (OPENOBSERVE_USER + OPENOBSERVE_TOKEN). Each record gets a microsecond _timestamp.

Streams used: `cronicle_runs` (scheduler per-job runs + failure logs), `orchestrator` (registry/
remediation decisions). Query in OpenObserve at http://10.0.181.X:5080.
"""
import base64
import json
import time
import urllib.request
from pathlib import Path

_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


def _cfg():
    e = {}
    try:
        for line in _ENV.read_text().splitlines():
            if line.startswith("OPENOBSERVE_") and "=" in line:
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip()
    except Exception:
        return None
    host = (e.get("OPENOBSERVE_URL") or "http://10.0.181.X:5080").rstrip("/")
    user, tok = e.get("OPENOBSERVE_USER"), e.get("OPENOBSERVE_TOKEN")
    org = e.get("OPENOBSERVE_ORG") or "default"
    if not (user and tok):
        return None
    return host, org, "Basic " + base64.b64encode(f"{user}:{tok}".encode()).decode()


def ship(stream, records):
    """records: list of dicts -> OpenObserve `stream`. Returns True on success (best-effort)."""
    c = _cfg()
    if not c or not records:
        return False
    host, org, auth = c
    now = int(time.time() * 1_000_000)
    for r in records:
        r.setdefault("_timestamp", now)
    try:
        req = urllib.request.Request(
            f"{host}/api/{org}/{stream}/_json",
            data=json.dumps(records).encode(),
            headers={"Content-Type": "application/json", "Authorization": auth})
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception:
        return False


def event(stream, **fields):
    """Ship one structured event."""
    return ship(stream, [fields])
