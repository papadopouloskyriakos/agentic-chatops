#!/usr/bin/env python3
"""
Alertmanager -> Twilio SMS bridge.

Receives Alertmanager webhook JSON, filters for tier-1 critical alerts, and
sends an SMS via Twilio's REST API using API-Key auth (same auth pattern as
scripts/freedom-qos-toggle.sh, proven in production since 2026-04-22).

Listens on :9106. POST /alert with the standard Alertmanager webhook payload.
For each alert with labels.tier == "1" and status == "firing" or "resolved",
fires one SMS. Deduplicates within a short window to avoid spam during a
flapping condition.

Refs IFRNLLEI01PRD-802 (alert escalation rebuild),
     IFRNLLEI01PRD-805 (NFS stale-fh detector),
     incident memory `incident_haha_nfs_stale_fh_20260430.md`.
"""
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

LISTEN_PORT = int(os.environ.get("AM_TWILIO_PORT", "9106"))
DEDUP_WINDOW_S = int(os.environ.get("AM_TWILIO_DEDUP_S", "300"))  # 5 min
ENV_FILE = os.environ.get("AM_TWILIO_ENV", "/app/claude-gateway/.env")


def load_env() -> dict:
    """Read .env-style file (KEY=VALUE per line, comments allowed)."""
    out: dict = {}
    if not os.path.exists(ENV_FILE):
        return out
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip().strip('"').strip("'")
    return out


CFG = load_env()
ACCT = CFG.get("TWILIO_ACCOUNT_SID", "")
KEY_SID = CFG.get("TWILIO_API_KEY_SID", "")
KEY_SECRET = CFG.get("TWILIO_API_KEY_SECRET", "")
FROM = CFG.get("TWILIO_FROM_NUMBER", "")
TO = CFG.get("TWILIO_TO_NUMBER", "")

# Last-fired timestamp per dedup key
_last_sent: dict = {}
_dedup_lock = threading.Lock()


def send_sms(body: str) -> tuple[bool, str]:
    if not (ACCT and KEY_SID and KEY_SECRET and FROM and TO):
        return False, "twilio creds missing"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{ACCT}/Messages.json"
    data = urllib.parse.urlencode({"From": FROM, "To": TO, "Body": body[:1500]}).encode()
    auth = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    auth.add_password(None, url, KEY_SID, KEY_SECRET)
    handler = urllib.request.HTTPBasicAuthHandler(auth)
    opener = urllib.request.build_opener(handler)
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with opener.open(req, timeout=8) as resp:
            return resp.status < 300, f"http {resp.status}"
    except Exception as e:
        return False, f"err {e}"


def should_send(dedup_key: str) -> bool:
    now = time.time()
    with _dedup_lock:
        last = _last_sent.get(dedup_key, 0)
        if now - last < DEDUP_WINDOW_S:
            return False
        _last_sent[dedup_key] = now
    return True


def handle_alertmanager_payload(payload: dict) -> int:
    """Returns count of SMS sent."""
    sent = 0
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        ann = alert.get("annotations", {})
        status = alert.get("status", "")
        tier = labels.get("tier", "")
        severity = labels.get("severity", "")
        alertname = labels.get("alertname", "?")
        instance = labels.get("instance", "")
        if tier != "1":
            continue
        if severity != "critical" and status == "firing":
            continue  # only tier-1 critical for firing; warning still sends if tier=1 by explicit choice — actually skip warnings
        if status not in ("firing", "resolved"):
            continue
        verb = "FIRING" if status == "firing" else "RESOLVED"
        summary = ann.get("summary") or alertname
        msg = f"[{verb}] {alertname} {instance} {summary}"[:1500]
        dedup_key = f"{alertname}|{instance}|{status}"
        if not should_send(dedup_key):
            continue
        ok, info = send_sms(msg)
        sys.stdout.write(f"sms ok={ok} info={info} key={dedup_key}\n")
        sys.stdout.flush()
        if ok:
            sent += 1
    return sent


class AlertHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/alert":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode()
            payload = json.loads(body)
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"bad json: {e}".encode())
            return
        sent = handle_alertmanager_payload(payload)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"sent": sent}).encode())

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        sys.stdout.write(f"http: {format % args}\n")


def main():
    if not ACCT or not KEY_SID or not KEY_SECRET or not FROM or not TO:
        sys.stderr.write(f"WARNING: missing Twilio creds in {ENV_FILE}; bridge starting in dry-run mode (no SMS will be sent)\n")
    else:
        sys.stdout.write(f"alertmanager-twilio-bridge: listening on :{LISTEN_PORT}, dedup={DEDUP_WINDOW_S}s\n")
    httpd = http.server.HTTPServer(("0.0.0.0", LISTEN_PORT), AlertHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
