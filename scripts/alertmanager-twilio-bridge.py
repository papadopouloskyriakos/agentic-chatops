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
REDACTED_a7b84d63
import sys
import threading
import time
import urllib.parse
import urllib.request

LISTEN_PORT = int(os.environ.get("AM_TWILIO_PORT", "9106"))
DEDUP_WINDOW_S = int(os.environ.get("AM_TWILIO_DEDUP_S", "300"))  # 5 min (alert path)
# Session path: dedup by ROOT-CAUSE CLUSTER (host-site + alert family), not issue_id.
# A cascade (etcd slow -> Gatus crash -> apiserver budget) spawns many NEW YouTrack
# issues; issue_id-keying NEVER collapsed them, so one sick control plane paged the
# operator dozens of times (91 SMS/7d, ~82% one cascade). Cluster-keying + a longer
# fold window pages once per family per window. AM_TWILIO_SESSION_CLUSTER=0 reverts to
# legacy issue_id keying; AM_TWILIO_SESSION_DEDUP_S tunes the fold window.
SESSION_DEDUP_WINDOW_S = int(os.environ.get("AM_TWILIO_SESSION_DEDUP_S", "21600"))  # 6h re-arm
SESSION_CLUSTER = os.environ.get("AM_TWILIO_SESSION_CLUSTER", "1") not in ("0", "false", "False", "no", "NO")
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

# Last-fired timestamp per dedup key (alert path); last-SEEN per cluster (session path)
_last_sent: dict = {}
_session_last_seen: dict = {}
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


def should_send(dedup_key: str, window: int = DEDUP_WINDOW_S) -> bool:
    now = time.time()
    with _dedup_lock:
        last = _last_sent.get(dedup_key, 0)
        if now - last < window:
            return False
        _last_sent[dedup_key] = now
    return True


# ── Root-cause cluster key for the session->SMS path (page once per family/window) ──
_SESSION_FAMILIES = (
    ("etcd",          ("etcd", "fsync", "commit duration", "i/o contention", "disk i/o",
                       "lease renewal", "leader election")),
    ("gatus",         ("gatus",)),
    ("apiserver",     ("api server", "apiserver", "api-server", "error budget")),
    ("csi",           ("democratic-csi", "csi pod", " csi ")),
    ("awx",           ("awx",)),
    ("restart-storm", ("restart storm", "crashloopbackoff", "crash-loop", "crashloop")),
    ("storage",       ("nfs", "synology", " syno", " ups ", "backup", "pbs", "nospace", "disk space")),
    ("network",       ("unreachable", "bgp", "tunnel", " vpn", " wan")),
)
_STOP = {"the", "and", "due", "with", "from", "that", "this", "have", "has", "are", "for",
         "pod", "node", "nodes", "cluster", "k8s", "kubernetes", "high", "poll", "pause",
         "indicates", "causing", "experiencing", "repeated", "running", "deployment"}


def _site_of(host: str, issue_id: str) -> str:
    h = (host or "").lower()
    if h.startswith("grskg") or issue_id.upper().startswith("IFRGRSKG"):
        return "gr"
    if h.startswith("nllei") or issue_id.upper().startswith("IFRNLLEI"):
        return "nl"
    return "x"


def _session_cluster_key(payload: dict) -> str:
    issue_id = str(payload.get("issue_id", "")).strip() or "unknown"
    if not SESSION_CLUSTER:
        return f"session|{issue_id}"  # legacy issue_id keying (kill-switch)
    text = f"{payload.get('summary', '')} {payload.get('reason', '')}".lower()
    site = _site_of(str(payload.get("host", "")), issue_id)
    for fam, kws in _SESSION_FAMILIES:
        if any(k in text for k in kws):
            return f"session|{site}|{fam}"
    # unknown alert: fold on a content fingerprint so repeats still collapse
    toks = sorted({t for t in re.findall(r"[a-z]{4,}", text) if t not in _STOP})[:5]
    return f"session|{site}|" + ("-".join(toks) or "misc")


def _session_should_page(key: str, window: int) -> bool:
    """Edge-triggered: page on the LEADING edge of a storm, then stay silent while the
    same cluster keeps firing (every repeat refreshes last-seen). Re-arms — so the next
    alert pages — only after the cluster has been QUIET for `window` (i.e. it resolved
    and recurred). Collapses a chronic family to one page per incident, not per flap.
    A genuinely new problem is a different cluster key and pages immediately."""
    now = time.time()
    with _dedup_lock:
        last = _session_last_seen.get(key)
        _session_last_seen[key] = now  # always refresh, even when suppressing
        return last is None or (now - last) >= window


# ── Session -> SMS path (IFRNLLEI01PRD-1105, autonomy-forward gate -1102) ───────
# The ONLY way a Runner *session* (not an Alertmanager alert) can page the
# operator. Dedup is keyed on issue_id so a session escalating across tiers pages
# ONCE, not 3x. Master switch AUTONOMY_SESSION_SMS (default OFF) lets the wiring
# deploy dark — endpoint returns 200 + outcome=suppressed until flipped on.
def _session_sms_enabled() -> bool:
    # Enabled if the env var is set truthy, OR (env unset) a sentinel file
    # exists. `touch ~/gateway.autonomy_session_sms` to enable, `rm` to disable
    # — instant kill-switch, no service restart. An explicit env var wins.
    v = os.environ.get("AUTONOMY_SESSION_SMS")
    if v is not None:
        return v not in ("", "0", "false", "False", "no", "NO")
    return os.path.exists(os.path.expanduser("~/gateway.autonomy_session_sms"))


_session_sms_counts: dict = {"sent": 0, "deduped": 0, "suppressed": 0, "gated": 0, "error": 0}


def _session_reason_is_critical(payload: dict) -> bool:
    """Defense-in-depth gate. Even though the caller (Runner/bridge) already
    decided sms_required, re-check that the reason genuinely qualifies under the
    locked policy: Q2 'HIGH-risk only' + the Q4 P0 auto-proceed page (band
    AUTO_NOTICE) + an Infragraph deviation. A non-critical caller is dropped."""
    risk = str(payload.get("risk_level", "")).lower()
    band = str(payload.get("band", ""))
    reason = str(payload.get("reason", "")).lower()
    return risk == "high" or band == "AUTO_NOTICE" or "deviation" in reason


def handle_session_payload(payload: dict) -> dict:
    """POST /alert-session body: {issue_id, summary, band, host, risk_level, reason}."""
    issue_id = str(payload.get("issue_id", "")).strip() or "unknown"
    if not _session_sms_enabled():
        _session_sms_counts["suppressed"] += 1
        return {"outcome": "suppressed", "issue_id": issue_id, "info": "AUTONOMY_SESSION_SMS off"}
    if not _session_reason_is_critical(payload):
        _session_sms_counts["gated"] += 1
        return {"outcome": "gated", "issue_id": issue_id, "info": "reason not critical under policy"}
    cluster = _session_cluster_key(payload)
    if not _session_should_page(cluster, SESSION_DEDUP_WINDOW_S):
        _session_sms_counts["deduped"] += 1
        return {"outcome": "deduped", "issue_id": issue_id,
                "info": f"folded into {cluster} (quiet-gap < {SESSION_DEDUP_WINDOW_S}s)"}
    host = str(payload.get("host", "")).strip()
    risk = str(payload.get("risk_level", "")).strip() or "?"
    band = str(payload.get("band", "")).strip()
    summary = str(payload.get("summary", "")).strip()[:80]
    # No inbound ACK loop yet (documented limitation) — veto is out-of-band via Matrix.
    body = f"[NL-CRIT] {issue_id} {host} {risk}/{band}: {summary}. Veto: Matrix !session abort {issue_id}"
    ok, info = send_sms(body)
    _session_sms_counts["sent" if ok else "error"] += 1
    sys.stdout.write(f"session-sms ok={ok} info={info} issue={issue_id} band={band}\n")
    sys.stdout.flush()
    return {"outcome": "sent" if ok else "error", "issue_id": issue_id, "info": info}


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
        if self.path not in ("/alert", "/alert-session"):
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
        if self.path == "/alert-session":
            result = handle_session_payload(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
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
        if self.path == "/metrics":
            lines = [
                "# HELP session_sms_total Session->SMS outcomes (IFRNLLEI01PRD-1105)",
                "# TYPE session_sms_total counter",
            ]
            for outcome, n in _session_sms_counts.items():
                lines.append(f'session_sms_total{{outcome="{outcome}"}} {n}')
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(("\n".join(lines) + "\n").encode())
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
