#!/usr/bin/env python3
"""alert-yt-autoclose.py — close YouTrack issues auto-created from alerts once the alert recovers.

PROBLEM: the alert receivers (n8n) auto-CREATE a YT issue on every alert, but nothing closes them
when the alert clears -> alert-flap issues accrue (NL -1462/-1463, GR-270/271, ...). The
2026-06-27 triage flagged this as the systemic "alert->create but never ->close" gap.

This script finds OPEN alert-gen issues, checks whether the underlying alert has RECOVERED
(Prometheus via Thanos for "K8s Alert:" issues; LibreNMS device status for "Alert: <host> - Device
Down" issues), and — only when aged >= ALERT_AUTOCLOSE_AGE_H and ARMED — closes them (State Done +
a comment). SHADOW-FIRST by default (reports candidates; closes nothing). Arm with
`touch ~/gateway.alert_yt_autoclose_armed`; kill with `rm`.

Conservative: if recovery cannot be determined (query fails / unparseable title), the issue is LEFT
OPEN — never close on uncertainty. Mirrors the system's shadow-first pattern (autonomy-forward,
governance-autodemote, egress-guard). If the alert re-fires after a close, the receiver creates a
fresh issue (so closing a recovered issue loses no future signal).

Cron: hourly. Metrics: alert_yt_autoclose_candidates / _closed / _unparseable.
Usage: alert-yt-autoclose.py            # shadow (report only)
"""
import json
import os
REDACTED_a7b84d63
import sys
import time
import urllib.parse
import urllib.request

def _env_secret(name: str) -> str:
    """Env first, then the gateway .env — the hourly Cronicle job carries no secrets,
    so every ARMED run 401'd against YouTrack (and silently skipped the LibreNMS
    device checks) from arming 2026-07-04 until 2026-07-08. Same fallback pattern
    as reconcile-completed-sessions.py::_yt_token."""
    val = os.environ.get(name, "")
    if val:
        return val
    for p in (os.path.expanduser("~/gitlab/n8n/claude-gateway/.env"),
              "/app/claude-gateway/.env"):
        try:
            for line in open(p, encoding="utf-8"):
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


YT_URL = os.environ.get("YOUTRACK_URL", "https://youtrack.example.net").rstrip("/")
YT_TOKEN = _env_secret("YOUTRACK_API_TOKEN")
THANOS = os.environ.get("THANOS_URL", "https://nl-thanos.example.net").rstrip("/")
PROJECTS = ["IFRNLLEI01PRD", "IFRGRSKG01PRD"]
ALERT_AGE_H = int(os.environ.get("ALERT_AUTOCLOSE_AGE_H", "2"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    import mutation_mode  # MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:  # noqa: BLE001
    mutation_mode = None

ARMED = os.path.exists(os.path.expanduser("~/gateway.alert_yt_autoclose_armed"))
# Second, narrower sentinel (2026-07-08 alert-automation directives #1/#2/#7): also close
# TO-VERIFY issues, but ONLY the read-only-recovered subset. Independently killable from the
# Open-path close above. See _toverify_closeable().
TOVERIFY_ARMED = os.path.exists(os.path.expanduser("~/gateway.autoclose_toverify_readonly"))
GATEWAY_DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
# Hardware-bound control-plane hosts whose brief self-cleared flaps are known noise (#7).
CTRLPLANE_RE = re.compile(r"(nl|grskg0[12])k8s-(ctrlr|node)\d+")
# Standing-condition Prometheus alerts (directive #8): these oscillate around their
# threshold for weeks and must NOT be auto-closed on a momentary non-firing dip — that
# would spawn a fresh issue on the next fire. Keeping the issue open lets k8s-triage Step 0
# dedup all re-fires into ONE rolling issue; the actionable queue goes out via the weekly
# renovate-poll-digest.py instead. (ComposedEvalJudgeFooled is handled by its own
# auto-calibration actuator but is also rolling here.)
STANDING_CONDITION_ALERTS = {
    a for a in os.environ.get(
        "AUTOCLOSE_STANDING_ALERTS",
        "RenovateAutonomyHighPollRate,ComposedEvalJudgeFooled").split(",") if a}
METRIC_OUT = os.environ.get(
    "ALERT_AUTOCLOSE_METRICS_OUT",
    "/var/lib/node_exporter/textfile_collector/alert_yt_autoclose.prom")
***REMOVED*** for device-down recovery checks (NL + GR).
LN = {"IFRNLLEI01PRD": (os.environ.get("LIBRENMS_NL_URL", "https://nl-nms01.example.net"),
                        _env_secret("LIBRENMS_API_KEY")),
      "IFRGRSKG01PRD": (os.environ.get("LIBRENMS_GR_URL", "https://gr-nms01.example.net"),
                        _env_secret("LIBRENMS_GR_API_KEY"))}


_INSECURE_CTX = None


def _insecure_ctx():
    """TLS context for the self-signed LibreNMS instances (estate-wide `curl -sk` practice).
    YouTrack/Thanos keep full verification. Without this, every LibreNMS call raised
    SSLCertVerificationError -> swallowed to None -> conservative skip, so the ln recovery
    path NEVER worked (third stacked defect after the missing token and the blind parser)."""
    global _INSECURE_CTX
    if _INSECURE_CTX is None:
        import ssl
        _INSECURE_CTX = ssl.create_default_context()
        _INSECURE_CTX.check_hostname = False
        _INSECURE_CTX.verify_mode = ssl.CERT_NONE
    return _INSECURE_CTX


def _get(url, headers=None, timeout=15, insecure=False):
    req = urllib.request.Request(url, headers=headers or {})
    if insecure:
        with urllib.request.urlopen(req, timeout=timeout, context=_insecure_ctx()) as r:
            return json.loads(r.read().decode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _norm_ts(v):
    """YouTrack created/updated may be epoch seconds or ms; normalise to seconds."""
    if not v:
        return 0
    return v / 1000.0 if v > 1e11 else float(v)


def open_alert_issues(project):
    q = urllib.parse.quote(f"project: {project} #Unresolved")
    url = (f"{YT_URL}/api/issues?fields=idReadable,summary,description,created,updated,"
           f"customFields(name,value(name))&$top=100&query={q}")
    try:
        rows = _get(url, headers={"Authorization": f"Bearer {YT_TOKEN}", "Accept": "application/json"})
    except Exception as e:
        print(f"[{project}] fetch failed: {e}", file=sys.stderr)
        return []
    out = []
    for r in rows:
        s = (r.get("summary") or "")
        if not s.startswith(("K8s Alert:", "Alert:", "Correlated alert burst:")):
            continue
        # 'To Verify' means a completed session is deliberately parked for HUMAN review
        # (infragraph deviation verdict / territory-gate unacked / reconcile two-phase).
        # State=Open closes on the standard recovered-path. State='To Verify' closes ONLY
        # via the read-only-recovered carve-out in main() (a risk=low session executed
        # nothing, so the never-auto-resolve-on-deviation floor — which is about EXECUTED
        # mutations — never applied). Any other state stays with the operator.
        state = next((cf.get("value", {}).get("name", "") for cf in r.get("customFields", [])
                      if cf.get("name") == "State" and isinstance(cf.get("value"), dict)), "")
        if state not in ("Open", "To Verify"):
            continue
        r["_state"] = state
        out.append(r)
    return out


def _readonly_low_auto(issue_id):
    """(closeable, why) for a TO-VERIFY issue, from the classifier's OWN ground truth.

    risk_level=='low' means the classifier matched ZERO mutation signals — a purely
    read-only diagnostic session (band=AUTO, auto_approved). Such a session executed
    nothing, so an infragraph DEVIATION verdict on it is cascade-prediction noise and the
    territory-gate (which only guards writes) never applied — the issue was parked purely
    because the operator stopped voting. Closing it when the alert is independently verified
    recovered is safe. A 'mixed'/'high' parked session (a real reversible/write action) is
    NOT closeable here and stays with the operator.

    No risk-audit row + a hardware-bound control-plane host = a brief flap that self-cleared
    before any session was dispatched (#7); closeable when live-recovered.
    Returns (False, reason) to leave it parked."""
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{GATEWAY_DB}?mode=ro", uri=True, timeout=10)
        row = conn.execute(
            "SELECT risk_level, band, auto_approved FROM session_risk_audit "
            "WHERE issue_id=? ORDER BY rowid DESC LIMIT 1", (issue_id,)).fetchone()
        conn.close()
    except Exception as e:  # noqa: BLE001 — DB trouble => conservative skip
        return (False, f"db-error:{type(e).__name__}")
    if row is None:
        return (None, "no-session")  # decided by caller against the ctrl-plane host pattern
    risk, band, appr = row
    if risk == "low" and band == "AUTO" and int(appr or 0) == 1:
        return (True, "readonly-low-auto")
    return (False, f"not-readonly:{risk}/{band}")


# Hostnames this estate uses in alert summaries/descriptions (site-prefixed, per CLAUDE.md P0).
_HOST_RE = re.compile(r"\b((?:nl|grskg0[12])[a-z0-9-]+)(?:\.[a-z0-9.-]+)?\b")


def parse_issue(summary):
    """Map an alert-issue summary to a recovery-check kind.

    Returns ('prom', ALERTNAME) | ('ln', HOST) | ('burst', None) | ('unknown', None).
    Shapes covered (extended 2026-07-08, IFRNLLEI01PRD-1709 follow-up — the old parser only
    knew the first two, so the whole NL-LibreNMS class piled up Open forever):
      K8s Alert: <Name> ...                             -> prom
      Alert: <host> - Device ...                        -> ln   (legacy NL shape)
      Alert: -- ALERT -- <host> - <anything>            -> ln   (GR LibreNMS shape)
      Alert: <rule text> on <host>[.domain]             -> ln   (NL LibreNMS shape: Devices
              up/down / Device Down! / Service up/down / Port status / Space on / / Memory /
              Device rebooted ...)
      Correlated alert burst: ...                       -> burst (hosts parsed from description)
    """
    m = re.match(r"K8s Alert:\s*([A-Za-z0-9_]+)", summary)
    if m:
        return ("prom", m.group(1))
    m = re.match(r"Alert:\s*([A-Za-z0-9-]+)\s*-\s*Device", summary)
    if m and m.group(1) != "--":
        return ("ln", m.group(1))
    m = re.match(r"Alert:\s*--\s*ALERT\s*--\s*([A-Za-z0-9-]+)\s*-", summary)
    if m:
        return ("ln", m.group(1))
    if summary.startswith("Correlated alert burst:"):
        return ("burst", None)
    if summary.startswith("Alert:"):
        m = re.search(r"\son\s+([A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9])\s*$", summary.strip())
        if m:
            hm = _HOST_RE.match(m.group(1))
            if hm:
                return ("ln", hm.group(1))
    return ("unknown", None)


def prom_recovered(alertname):
    """True if the Prometheus alert is NOT currently firing (recovered). None if unknown."""
    try:
        q = urllib.parse.quote(f'ALERTS{{alertname="{alertname}",alertstate="firing"}}')
        d = _get(f"{THANOS}/api/v1/query?query={q}", timeout=10)
        return len(d.get("data", {}).get("result", [])) == 0
    except Exception:
        return None


# LibreNMS registers some devices by FQDN (e.g. nlpdu01.example.net) and others by
# short name. An alert summary carries the short name, so a bare /devices/<short> lookup 404s for
# FQDN-registered devices -> the recovery check returns unknown and the issue never closes
# (IFRNLLEI01PRD-1472). Try the short name, then the FQDN, then the domain-stripped short.
_LN_DOMAINS = [s for s in os.environ.get("LIBRENMS_DEVICE_DOMAINS",
               "example.net,sec.example.net").split(",") if s]


def _ln_device(base, key, host):
    """Return the LibreNMS device dict for `host`, trying short + FQDN forms. None if not found
    under ANY form (unknown -> conservative skip, NOT treated as down)."""
    short = host.split(".")[0]
    forms = [host, short] + [f"{short}.{d}" for d in _LN_DOMAINS]
    seen = set()
    for name in forms:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            d = _get(f"{base}/api/v0/devices/{urllib.parse.quote(name)}",
                     headers={"X-Auth-Token": key}, timeout=10, insecure=True)
        except Exception:
            continue
        devs = d.get("devices")
        if devs and str(d.get("status", "")).lower() != "error":
            return devs[0]
    return None


def librenms_device_up(project, host):
    """True if the LibreNMS device is currently UP. None if unknown."""
    base, key = LN.get(project, ("", ""))
    if not base or not key:
        return None
    dev = _ln_device(base, key, host)
    if dev is None:
        return None
    return int(dev.get("status", 0)) == 1  # 1 = up


_ALERTING_DEVICE_IDS: dict = {}  # project -> set(device_id) with an active alert, or None


def _alerting_device_ids(project):
    """device_ids with ANY active (state=1) LibreNMS alert — cached once per run per site."""
    if project not in _ALERTING_DEVICE_IDS:
        base, key = LN.get(project, ("", ""))
        if not base or not key:
            _ALERTING_DEVICE_IDS[project] = None
        else:
            try:
                d = _get(f"{base}/api/v0/alerts?state=1", headers={"X-Auth-Token": key}, timeout=10, insecure=True)
                _ALERTING_DEVICE_IDS[project] = {str(a.get("device_id")) for a in d.get("alerts") or []}
            except Exception:
                _ALERTING_DEVICE_IDS[project] = None
    return _ALERTING_DEVICE_IDS[project]


def librenms_host_clean(project, host):
    """True only if the device is UP *and* has ZERO active LibreNMS alerts — stronger than
    device-up so service/port/disk/memory rule issues never close while anything on that
    host is still alerting. None if undeterminable (conservative skip)."""
    base, key = LN.get(project, ("", ""))
    if not base or not key:
        return None
    alerting = _alerting_device_ids(project)
    if alerting is None:
        return None
    dev = _ln_device(base, key, host)
    if dev is None:
        return None  # not found under short or FQDN -> unknown, skip (don't treat as down)
    if int(dev.get("status", 0)) != 1:
        return False
    return str(dev.get("device_id")) not in alerting


def burst_recovered(project, description):
    """Correlated-burst umbrellas name their hosts only in the description. Recovered iff
    at least one site host is named and EVERY named host is up + alert-clean."""
    hosts = sorted(set(_HOST_RE.findall(description or "")))
    if not hosts:
        return None, None
    for h in hosts:
        r = librenms_host_clean(project, h)
        if r is not True:
            return r, hosts  # False = a host is down/still alerting; None = undeterminable
    return True, hosts


def close(issue_id, comment):
    if mutation_mode and mutation_mode.is_shadow():
        mutation_mode.log_wouldve("yt-close", rationale="would set State Done", issue=issue_id)
        return False  # MUTATIONS=OFF shadow: never change YouTrack state — logged, not run
    body = {"query": "State Done", "comment": comment, "issues": [{"idReadable": issue_id}]}
    try:
        req = urllib.request.Request(
            f"{YT_URL}/api/commands", data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {YT_TOKEN}", "Content-Type": "application/json",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20):
            return True
    except Exception as e:
        print(f"  close failed {issue_id}: {e}", file=sys.stderr)
        return False


def main():
    now = time.time()
    cands, closed, unknown, tv_closed = [], 0, 0, 0
    for proj in PROJECTS:
        for iss in open_alert_issues(proj):
            iid = iss["idReadable"]
            summary = iss.get("summary", "")
            state = iss.get("_state", "Open")
            age_h = (now - _norm_ts(iss.get("updated") or iss.get("created"))) / 3600.0
            kind, target = parse_issue(summary)
            if kind == "prom" and target in STANDING_CONDITION_ALERTS:
                continue  # rolling standing-condition issue — never auto-close (directive #8)
            if kind == "prom":
                recovered, how = prom_recovered(target), f"prom:{target}"
            elif kind == "ln":
                recovered, how = librenms_host_clean(proj, target), f"ln-clean:{target}"
            elif kind == "burst":
                recovered, hosts = burst_recovered(proj, iss.get("description") or "")
                how = f"ln-burst:{','.join(hosts or [])[:120]}"
            else:
                unknown += 1
                continue
            if recovered is not True:          # None=unknown or False=still-firing -> leave open
                continue
            if age_h < ALERT_AGE_H:            # too fresh — let flaps settle
                continue

            if state == "Open":
                cands.append((proj, iid, summary, f"open/{how}", round(age_h, 1)))
                if ARMED and close(
                        iid, f"auto-closed by alert-yt-autoclose.py: underlying alert recovered ({how})."):
                    closed += 1
                continue

            # state == 'To Verify' — read-only-recovered carve-out (directives #1/#2/#7).
            ok, why = _readonly_low_auto(iid)
            if ok is None:  # no session at all — only the self-cleared ctrl-plane flap class (#7)
                ok = bool(CTRLPLANE_RE.search(target or ""))
                why = "self-cleared-ctrlplane" if ok else "no-session-non-ctrlplane"
            if not ok:
                continue  # a mixed/high (real-action) parked session — stays with the operator
            cands.append((proj, iid, summary, f"toverify/{why}/{how}", round(age_h, 1)))
            if TOVERIFY_ARMED and ARMED and close(
                    iid,
                    f"auto-closed by alert-yt-autoclose.py (To-Verify read-only carve-out, "
                    f"operator directive 2026-07-08): the parked session was risk=low/band=AUTO "
                    f"({why}) — it executed no remediation, so the never-auto-resolve-on-deviation "
                    f"floor never applied — and the alert is independently verified recovered "
                    f"({how})."):
                tv_closed += 1
                closed += 1
    mode = "ARMED" if ARMED else "SHADOW (touch ~/gateway.alert_yt_autoclose_armed to enable close)"
    tv = "ON" if TOVERIFY_ARMED else "OFF (touch ~/gateway.autoclose_toverify_readonly)"
    print(f"alert-yt-autoclose [{mode}] toverify-readonly={tv}: {len(cands)} candidate(s) "
          f"(recovered + aged>={ALERT_AGE_H}h), {closed} closed ({tv_closed} To-Verify), "
          f"{unknown} unparseable.")
    for proj, iid, summary, how, age in cands:
        print(f"  [{proj}] {iid} ({age}h, {how}) {summary[:72]}")
    try:
        with open(METRIC_OUT + ".tmp", "w") as f:
            f.write("# HELP alert_yt_autoclose_candidates Open alert-gen YT issues whose alert recovered + aged.\n"
                    "# TYPE alert_yt_autoclose_candidates gauge\n"
                    f"alert_yt_autoclose_candidates {len(cands)}\n"
                    "# HELP alert_yt_autoclose_closed Issues closed this run (armed only).\n"
                    "# TYPE alert_yt_autoclose_closed gauge\n"
                    f"alert_yt_autoclose_closed {closed}\n"
                    "# HELP alert_yt_autoclose_toverify_closed To-Verify read-only issues closed this run.\n"
                    "# TYPE alert_yt_autoclose_toverify_closed gauge\n"
                    f"alert_yt_autoclose_toverify_closed {tv_closed}\n"
                    "# HELP alert_yt_autoclose_unparseable Alert-gen issues whose alert could not be mapped.\n"
                    "# TYPE alert_yt_autoclose_unparseable gauge\n"
                    f"alert_yt_autoclose_unparseable {unknown}\n")
        os.replace(METRIC_OUT + ".tmp", METRIC_OUT)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
