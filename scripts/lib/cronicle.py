"""Shared Cronicle API helpers for the orchestrator (registry-seed/check + metrics).

Reads CRONICLE_URL + CRONICLE_API_KEY from the gateway .env. All calls are best-effort — they
return empty on any failure, so the orchestrator never breaks because the scheduler API is briefly
unreachable (the absent()-guarded CronicleSchedulerDown alert catches a real outage). Cronicle was
adopted as the platform scheduler 2026-06-26 (all 172 crons migrated off crontab); these helpers are
how the registry inventories + verifies each job individually.
"""
import json
import time
import urllib.request
from pathlib import Path

_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


def cfg():
    """(url, api_key) from .env, or (None, None) if unconfigured."""
    c = {}
    try:
        for line in _ENV.read_text().splitlines():
            if line.startswith("CRONICLE_") and "=" in line:
                k, v = line.split("=", 1)
                c[k.strip()] = v.strip()
    except Exception:
        pass
    url, key = c.get("CRONICLE_URL"), c.get("CRONICLE_API_KEY")
    return (url, key) if (url and key) else (None, None)


def _get(url):
    return json.load(urllib.request.urlopen(url, timeout=10))


def schedule():
    """List of Cronicle events (jobs), or [] on failure."""
    url, key = cfg()
    if not url:
        return []
    try:
        d = _get(f"{url}/api/app/get_schedule?api_key={key}&limit=2000")
        return d.get("rows", []) if d.get("code") == 0 else []
    except Exception:
        return []


def last_runs(limit=1000):
    """Map {event_id -> (age_seconds, last_code)} from the MOST RECENT run per event.

    last_code: 0 = success, non-zero = the job exited non-zero (the per-job-death signal). An event
    with no run in the history window is simply absent from the map (treated as not-dark by callers —
    avoids false positives for infrequent jobs).
    """
    url, key = cfg()
    if not url:
        return {}
    try:
        d = _get(f"{url}/api/app/get_history?api_key={key}&limit={limit}")
        rows = d.get("rows", []) if d.get("code") == 0 else []
    except Exception:
        return {}
    rows.sort(key=lambda j: j.get("time_start", 0), reverse=True)
    now = time.time()
    out = {}
    for j in rows:
        eid = j.get("event")
        if not eid or eid in out:
            continue
        out[eid] = (int(now - (j.get("time_start") or now)), j.get("code"))
    return out


def event_failure_stats(limit=1000):
    """{event_id -> {fails, total, last_code, title, enabled}} over the history window — for the
    control path (cronicle-remediate.py) to find chronic-failing jobs."""
    url, key = cfg()
    if not url:
        return {}
    sched = {e["id"]: e for e in schedule()}
    try:
        d = _get(f"{url}/api/app/get_history?api_key={key}&limit={limit}")
        rows = d.get("rows", []) if d.get("code") == 0 else []
    except Exception:
        return {}
    rows.sort(key=lambda j: j.get("time_start", 0), reverse=True)
    out = {}
    for j in rows:
        eid = j.get("event")
        if not eid:
            continue
        s = out.setdefault(eid, {"fails": 0, "total": 0, "last_code": None,
                                 "title": (sched.get(eid) or {}).get("title", eid),
                                 "enabled": bool((sched.get(eid) or {}).get("enabled"))})
        s["total"] += 1
        if s["last_code"] is None:
            s["last_code"] = j.get("code")
        if j.get("code") not in (0, "0", None):
            s["fails"] += 1
    return out


def set_enabled(event_id, enabled, session_id):
    """Enable/disable an event (the control path). Requires a session_id (admin login). Returns the
    API code (0 = ok). Used by cronicle-remediate.py to quarantine a chronic-failing job."""
    url, _ = cfg()
    if not url:
        return -1
    try:
        body = json.dumps({"session_id": session_id, "id": event_id,
                           "enabled": 1 if enabled else 0}).encode()
        req = urllib.request.Request(f"{url}/api/app/update_event", data=body,
                                     headers={"Content-Type": "application/json"})
        return _get_post(req).get("code", -1)
    except Exception:
        return -1


def run_now(event_id, session_id):
    """Trigger an event immediately (the control path — re-run a missed/failed job)."""
    url, _ = cfg()
    if not url:
        return -1
    try:
        body = json.dumps({"session_id": session_id, "id": event_id}).encode()
        req = urllib.request.Request(f"{url}/api/app/run_event", data=body,
                                     headers={"Content-Type": "application/json"})
        return _get_post(req).get("code", -1)
    except Exception:
        return -1


def login():
    """Admin session_id for control actions (read paths use the api_key). Returns '' on failure."""
    url, _ = cfg()
    if not url:
        return ""
    try:
        body = json.dumps({"username": "admin", "password": _admin_pw()}).encode()
        req = urllib.request.Request(f"{url}/api/user/login", data=body,
                                     headers={"Content-Type": "application/json"})
        return _get_post(req).get("session_id", "")
    except Exception:
        return ""


def _admin_pw():
    c = {}
    try:
        for line in _ENV.read_text().splitlines():
            if line.startswith("CRONICLE_ADMIN_PASSWORD=") and "=" in line:
                c["pw"] = line.split("=", 1)[1].strip()
    except Exception:
        pass
    return c.get("pw", "admin")


def _get_post(req):
    return json.load(urllib.request.urlopen(req, timeout=10))
