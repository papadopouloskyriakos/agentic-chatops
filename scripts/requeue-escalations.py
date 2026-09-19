#!/usr/bin/env python3
"""Requeue dropped escalations — the consumer for escalation_queue.

WHY THIS EXISTS (2026-07-08 defect trio)
----------------------------------------
1. slot-locked: the Runner's "Is Locked?" TRUE branch used to TERMINATE the workflow —
   an accepted escalation that lost the slot race vanished (2026-06-30 nl-pve01
   power-cycle burst: 31 accepted escalations, 1 session, ~30 orphaned-Open issues).
   The Runner now queues those via scripts/queue-escalation.sh; this job re-fires them
   when the slot lock is free.
2. poll-recheck: reconcile-completed-sessions.py archives an unanswered POLL_PAUSE
   session as orphaned-poll and used to stop there — IFRNLLEI01PRD-1536 went from the
   alerted 90-95% disk band to 100% FULL with no re-escalation. The reconciler now
   schedules a delayed re-check row; this job re-escalates (webhook + SMS) only if the
   underlying condition is verifiably still active, and marks it 'recovered' otherwise
   (closing recovered issues stays alert-yt-autoclose.py's job).

SAFETY MODEL
------------
* Re-fires go through the NORMAL n8n youtrack-webhook, so cooldown, risk classifier,
  autonomy bands and the fail-closed prediction gate all still apply. This job never
  launches Claude directly and never bypasses a gate.
* One fire per slot lock_file per run (a slot can only run one session anyway) —
  a queued burst drains serially at the job cadence.
* attempts >= --max-attempts, rows older than --max-age-h, and resolved YT issues are
  dropped with an audit note. poll-recheck re-escalation is capped by the number of
  prior poll_unanswered archives for the issue (--recheck-cap) to prevent an
  SMS ping-pong loop; the cap posts a YT comment asking for a human instead.
* Unknown alert state at poll-recheck time counts as STILL ACTIVE (fail toward
  re-escalation; the caps bound the noise).

  Cronicle (nl-claude01):  */10 * * * *  scripts/requeue-escalations.py
  scripts/requeue-escalations.py --dry-run     # decide + log, change nothing

Env overrides (QA): GATEWAY_DB, GATEWAY_STATE_DIR, N8N_WEBHOOK_URL, YOUTRACK_URL,
AUTONOMY_SMS_URL, THANOS_URL, LIBRENMS_NL_URL, LIBRENMS_GR_URL, REQUEUE_METRICS_OUT.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
REDACTED_a7b84d63
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DB_PATH = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
GW_DIR = os.environ.get("GATEWAY_STATE_DIR", "/home/app-user/gateway-state")
WEBHOOK = os.environ.get("N8N_WEBHOOK_URL",
                         "https://n8n.example.net/webhook/youtrack-webhook")
YT_URL = os.environ.get("YOUTRACK_URL", "https://youtrack.example.net").rstrip("/")
SMS_URL = os.environ.get("AUTONOMY_SMS_URL", "http://127.0.0.1:9106/alert-session")
THANOS = os.environ.get("THANOS_URL", "https://nl-thanos.example.net").rstrip("/")
LN = {"IFRNLLEI01PRD": (os.environ.get("LIBRENMS_NL_URL", "https://nl-nms01.example.net"),
                        "LIBRENMS_API_KEY"),
      "IFRGRSKG01PRD": (os.environ.get("LIBRENMS_GR_URL", "https://gr-nms01.example.net"),
                        "LIBRENMS_GR_API_KEY")}
METRIC_OUT = os.environ.get(
    "REQUEUE_METRICS_OUT",
    "/var/lib/node_exporter/textfile_collector/escalation_requeue.prom")
DBG_LOG = os.environ.get("GATEWAY_DEBUG_LOG",
                         "/home/app-user/logs/claude-gateway/pipeline-debug.log")
ENV_FILES = (os.path.expanduser("~/gitlab/n8n/claude-gateway/.env"),
             "/app/claude-gateway/.env")


def _env_secret(name: str) -> str:
    """Env first, then the gateway .env — same fallback pattern as
    reconcile-completed-sessions.py::_yt_token (Cronicle jobs carry no secrets)."""
    val = os.environ.get(name, "")
    if val:
        return val
    for p in ENV_FILES:
        try:
            for line in open(p, encoding="utf-8"):
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _dbg(event: str, **fields) -> None:
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "script": "requeue-escalations", "pid": os.getpid(), "event": event, **fields}
        os.makedirs(os.path.dirname(DBG_LOG), exist_ok=True)
        with open(DBG_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


_INSECURE_CTX = None


def _insecure_ctx():
    """TLS context for the self-signed LibreNMS instances (estate-wide `curl -sk` practice)."""
    global _INSECURE_CTX
    if _INSECURE_CTX is None:
        import ssl
        _INSECURE_CTX = ssl.create_default_context()
        _INSECURE_CTX.check_hostname = False
        _INSECURE_CTX.verify_mode = ssl.CERT_NONE
    return _INSECURE_CTX


def _get(url: str, headers=None, timeout=10, insecure=False):
    req = urllib.request.Request(url, headers=headers or {})
    ctx = _insecure_ctx() if insecure else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read().decode())


def _post_json(url: str, payload: dict, headers=None, timeout=15) -> int:
    data = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def yt_resolved(issue_id: str) -> bool | None:
    """True/False, or None on lookup failure (leave the row pending)."""
    tok = _env_secret("YOUTRACK_API_TOKEN")
    if not tok:
        return None
    try:
        d = _get(f"{YT_URL}/api/issues/{issue_id}?fields=resolved",
                 headers={"Authorization": f"Bearer {tok}"})
        return d.get("resolved") is not None
    except Exception:  # noqa: BLE001
        return None


def yt_comment(issue_id: str, text: str) -> bool:
    tok = _env_secret("YOUTRACK_API_TOKEN")
    if not tok:
        return False
    try:
        _post_json(f"{YT_URL}/api/issues/{issue_id}/comments?fields=id", {"text": text},
                   headers={"Authorization": f"Bearer {tok}"})
        return True
    except Exception:  # noqa: BLE001
        return False


def slot_locked(lock_file: str) -> bool:
    """Mirror of the Runner's Check Lock: file exists and is younger than 600s."""
    if not lock_file or "/" in lock_file:
        return False
    p = os.path.join(GW_DIR, lock_file)
    try:
        return (time.time() - os.stat(p).st_mtime) < 600
    except OSError:
        return False


# --- alert-still-active checks (same sources alert-yt-autoclose.py uses) ---------

K8S_RE = re.compile(r"K8s Alert:\s*(\w+)")
HOST_RE = re.compile(r"\bon\s+([a-z][a-z0-9.-]*[a-z0-9])\s*$", re.IGNORECASE)


def prom_alert_firing(alertname: str) -> bool | None:
    try:
        q = urllib.parse.quote(f'ALERTS{{alertname="{alertname}",alertstate="firing"}}')
        d = _get(f"{THANOS}/api/v1/query?query={q}")
        return len(d.get("data", {}).get("result", [])) > 0
    except Exception:  # noqa: BLE001
        return None


def librenms_host_alerting(project: str, host: str) -> bool | None:
    base, key_name = LN.get(project, ("", ""))
    key = _env_secret(key_name) if key_name else ""
    if not base or not key:
        return None
    try:
        dev = _get(f"{base}/api/v0/devices/{urllib.parse.quote(host)}",
                   headers={"X-Auth-Token": key}, insecure=True)
        d = (dev.get("devices") or [{}])[0]
        if int(d.get("status", 1)) == 0:
            return True  # device down = still active
        device_id = d.get("device_id")
        alerts = _get(f"{base}/api/v0/alerts?state=1", headers={"X-Auth-Token": key}, insecure=True)
        for a in alerts.get("alerts") or []:
            if str(a.get("device_id")) == str(device_id):
                return True
        return False
    except Exception:  # noqa: BLE001
        return None


def condition_still_active(issue_id: str, summary: str) -> tuple[bool, str]:
    """(still_active, how). Unknown counts as still-active (fail toward re-escalation)."""
    m = K8S_RE.search(summary)
    if m:
        r = prom_alert_firing(m.group(1))
        if r is not None:
            return r, f"prometheus:{m.group(1)}={'firing' if r else 'resolved'}"
    m = HOST_RE.search(summary.strip())
    if m:
        host = m.group(1).split(".")[0]
        project = issue_id.rsplit("-", 1)[0]
        r = librenms_host_alerting(project, host)
        if r is not None:
            return r, f"librenms:{host}={'alerting' if r else 'clear'}"
    return True, "unknown-state:fail-toward-reescalate"


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    import mutation_mode  # MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:  # noqa: BLE001
    mutation_mode = None


def fire_webhook(issue_id: str, summary: str, dry: bool) -> bool:
    if mutation_mode and mutation_mode.is_shadow():
        mutation_mode.log_wouldve("requeue-webhook", rationale="would re-dispatch a session via n8n",
                                  issue=issue_id)
        return True  # MUTATIONS=OFF shadow: never re-fire the dispatch webhook — logged, not run
    if dry:
        return True
    try:
        status = _post_json(WEBHOOK, {"issueId": issue_id, "summary": summary,
                                      "updatedBy": "requeue-escalations"})
        return 200 <= status < 300
    except Exception:  # noqa: BLE001
        return False


def fire_sms(issue_id: str, summary: str, host: str, dry: bool) -> None:
    if dry or (mutation_mode and mutation_mode.is_shadow()):
        return
    try:
        _post_json(SMS_URL, {"issue_id": issue_id,
                             "summary": f"orphaned-poll re-check: still active — {summary[:120]}",
                             "band": "POLL_PAUSE", "host": host, "risk_level": "high",
                             "reason": "orphaned-poll-recheck"}, timeout=4)
    except Exception:  # noqa: BLE001 — paging must never block the requeue
        pass


def write_metrics(conn: sqlite3.Connection) -> None:
    try:
        rows = conn.execute(
            "SELECT kind, status, COUNT(*) FROM escalation_queue GROUP BY kind, status").fetchall()
        lines = [
            "# HELP escalation_requeue_rows escalation_queue rows by kind/status",
            "# TYPE escalation_requeue_rows gauge",
        ]
        for kind, status, n in rows:
            lines.append(f'escalation_requeue_rows{{kind="{kind}",status="{status}"}} {n}')
        lines += ["# HELP escalation_requeue_last_run_timestamp_seconds unix ts of last run",
                  "# TYPE escalation_requeue_last_run_timestamp_seconds gauge",
                  f"escalation_requeue_last_run_timestamp_seconds {int(time.time())}", ""]
        tmp = METRIC_OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        os.chmod(tmp, 0o644)  # containerized node_exporter can't read 0600 (standing rule)
        os.replace(tmp, METRIC_OUT)
    except Exception as e:  # noqa: BLE001
        _dbg("metrics_write_failed", error=str(e))


def _update(conn, row_id: int, dry: bool, **cols) -> None:
    if dry:
        return
    sets = ", ".join(f"{k}=?" for k in cols) + ", updated_at=CURRENT_TIMESTAMP"
    conn.execute(f"UPDATE escalation_queue SET {sets} WHERE id=?",  # noqa: S608 — fixed col names
                 (*cols.values(), row_id))
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="decide + log, change nothing")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--max-age-h", type=float, default=24.0,
                    help="slot-locked rows older than this are dropped (alert re-fires on its own)")
    ap.add_argument("--recheck-cap", type=int, default=2,
                    help="max poll_unanswered archives per issue before giving up to a human")
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args()

    lock_fh = open("/tmp/requeue-escalations.lock", "w", encoding="utf-8")  # noqa: SIM115
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"skipped": "already-running"}))
        return 0

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM escalation_queue WHERE status='pending' "
        "AND eligible_at <= datetime('now') ORDER BY queued_at ASC LIMIT ?",
        (args.batch,)).fetchall()
    _dbg("requeue_start", candidates=len(rows), dry=args.dry_run)

    fired_locks: set[str] = set()
    summary = {"fired": 0, "dropped": 0, "recovered": 0, "held": 0}
    for row in rows:
        rid, issue, kind = row["id"], row["issue_id"], row["kind"]
        note = ""
        try:
            age_h = (time.time() - time.mktime(time.strptime(
                row["queued_at"], "%Y-%m-%d %H:%M:%S"))) / 3600.0
        except (ValueError, TypeError):
            age_h = 0.0

        if row["attempts"] >= args.max_attempts:
            _update(conn, rid, args.dry_run, status="dropped", last_note="max-attempts")
            summary["dropped"] += 1
            _dbg("requeue_drop", issue_id=issue, kind=kind, reason="max-attempts")
            continue
        if kind == "slot-locked" and age_h > args.max_age_h:
            _update(conn, rid, args.dry_run, status="dropped", last_note=f"expired {age_h:.1f}h")
            summary["dropped"] += 1
            _dbg("requeue_drop", issue_id=issue, kind=kind, reason=f"expired-{age_h:.1f}h")
            continue

        resolved = yt_resolved(issue)
        if resolved is True:
            _update(conn, rid, args.dry_run, status="dropped", last_note="issue-resolved")
            summary["dropped"] += 1
            _dbg("requeue_drop", issue_id=issue, kind=kind, reason="issue-resolved")
            continue
        if resolved is None:
            summary["held"] += 1
            _dbg("requeue_hold", issue_id=issue, kind=kind, reason="yt-lookup-failed")
            continue
        if conn.execute("SELECT 1 FROM sessions WHERE issue_id=?", (issue,)).fetchone():
            summary["held"] += 1
            _dbg("requeue_hold", issue_id=issue, kind=kind, reason="session-active")
            continue

        if kind == "slot-locked":
            lf = row["lock_file"]
            if lf in fired_locks or slot_locked(lf):
                summary["held"] += 1
                _dbg("requeue_hold", issue_id=issue, kind=kind,
                     reason="slot-locked" if slot_locked(lf) else "one-per-slot-per-run")
                continue
            ok = fire_webhook(issue, row["summary"], args.dry_run)
            if ok:
                fired_locks.add(lf)
                _update(conn, rid, args.dry_run, status="fired",
                        attempts=row["attempts"] + 1, last_note="webhook re-fired")
                summary["fired"] += 1
            else:
                _update(conn, rid, args.dry_run, attempts=row["attempts"] + 1,
                        last_note="webhook failed")
                summary["held"] += 1
            _dbg("requeue_fire", issue_id=issue, kind=kind, ok=ok, dry=args.dry_run)
            continue

        # kind == 'poll-recheck'
        prior = conn.execute(
            "SELECT COUNT(*) FROM session_log WHERE issue_id=? AND resolution_type='poll_unanswered'",
            (issue,)).fetchone()[0]
        if prior >= args.recheck_cap:
            if not args.dry_run:
                yt_comment(issue, f"orphaned-poll re-check cap reached ({prior} unanswered polls) — "
                                  "the gateway is standing down on this issue; needs a human.")
            _update(conn, rid, args.dry_run, status="dropped", last_note=f"recheck-cap:{prior}")
            summary["dropped"] += 1
            _dbg("requeue_drop", issue_id=issue, kind=kind, reason=f"recheck-cap-{prior}")
            continue
        active, how = condition_still_active(issue, row["summary"])
        if not active:
            _update(conn, rid, args.dry_run, status="recovered", last_note=how)
            summary["recovered"] += 1
            _dbg("requeue_recovered", issue_id=issue, how=how)
            continue
        host_m = HOST_RE.search(row["summary"].strip())
        ok = fire_webhook(issue, row["summary"], args.dry_run)
        if ok:
            fire_sms(issue, row["summary"], host_m.group(1) if host_m else "", args.dry_run)
            _update(conn, rid, args.dry_run, status="fired",
                    attempts=row["attempts"] + 1, last_note=f"re-escalated ({how})")
            summary["fired"] += 1
        else:
            _update(conn, rid, args.dry_run, attempts=row["attempts"] + 1,
                    last_note="webhook failed")
            summary["held"] += 1
        _dbg("requeue_fire", issue_id=issue, kind=kind, ok=ok, how=how, dry=args.dry_run)

    write_metrics(conn)
    conn.close()
    _dbg("requeue_done", **summary)
    print(json.dumps({"candidates": len(rows), "dry_run": args.dry_run, **summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
