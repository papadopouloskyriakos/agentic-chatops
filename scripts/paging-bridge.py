#!/usr/bin/env python3
"""
Paging bridge: Alertmanager -> ntfy phone push (+ Twilio SMS for the ULTRA-urgent
allowlist only). Successor of alertmanager-twilio-bridge.py (renamed 2026-08-25;
operator decision: "wire tier-1 alerts to ntfy, keep SMS ONLY for ULTRA-urgent").

POST /alert          Alertmanager webhook (route: tier=1 & severity=critical).
                     Every accepted alert -> ntfy urgent push (edge-triggered:
                     one push per firing episode, one quiet push on resolve).
                     SMS additionally IFF the alert carries labels.page == "sms"
                     (declared on the PrometheusRule = the ULTRA allowlist).
                     ntfy publish failure -> SMS fail-over, hard-capped.
POST /heartbeat      Alertmanager `Watchdog` route (repeat 2m). Tracks per-site
                     liveness; silence > PAGING_WATCHDOG_TIMEOUT_S pages
                     PrometheusHeartbeatLost (ntfy always; SMS only for the
                     bridge's OWN site - a remote site's heartbeat rides the
                     overlay and must not double-page beside the partition SMS).
POST /alert-session  Legacy session->SMS path (IFRNLLEI01PRD-1105). RETIRED
                     2026-07-09: returns outcome=suppressed unless the
                     ~/gateway.autonomy_session_sms sentinel returns. Kept
                     verbatim so the 4 relay callers stay compatible.
GET  /health         liveness (SAFE probe - never test with a real SMS).
GET  /metrics        legacy in-memory counters (session_sms_total + paging_*).

Background threads: ntfy health probe (PagingPushDown SMS on 3 consecutive
failures, edge-triggered), watchdog checker, textfile metrics writer
(/var/lib/node_exporter/textfile_collector/paging_bridge.prom, atomic).

Config precedence: process env > .env file (AM_TWILIO_ENV, kept name - the GR
system unit depends on it) > defaults. PAGING_DRY_RUN=1 logs instead of sending
on BOTH channels (QA + maintenance windows).

Kill switches: PAGING_SMS_FAILOVER=0 (no SMS fail-over) - `systemctl --user stop
paging-bridge` (Matrix/YT triage via webhook-n8n is a separate Alertmanager
sibling and unaffected) - revoke the ntfy token.

Runbook: docs/runbooks/paging-ntfy.md
Refs IFRNLLEI01PRD-802/-805 (original bridge), operator plan 2026-08-25.
"""
import collections
import http.server
import json
import os
REDACTED_a7b84d63
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.ntfy import publish as ntfy_publish  # noqa: E402

LISTEN_PORT = int(os.environ.get("AM_TWILIO_PORT", "9106"))
ENV_FILE = os.environ.get("AM_TWILIO_ENV", "/app/claude-gateway/.env")
# Session path: dedup by ROOT-CAUSE CLUSTER (host-site + alert family), not issue_id.
# (See alertmanager-twilio-bridge history / sms_alert_fatigue_dedup_20260623.)
SESSION_DEDUP_WINDOW_S = int(os.environ.get("AM_TWILIO_SESSION_DEDUP_S", "21600"))  # 6h re-arm
SESSION_CLUSTER = os.environ.get("AM_TWILIO_SESSION_CLUSTER", "1") not in ("0", "false", "False", "no", "NO")


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


def cfg(name: str, default: str = "") -> str:
    """Process env wins; .env file second; default last."""
    v = os.environ.get(name)
    if v is not None:
        return v
    return CFG.get(name, default)


# ── Twilio (SMS) ────────────────────────────────────────────────────────────────
ACCT = CFG.get("TWILIO_ACCOUNT_SID", "")
KEY_SID = CFG.get("TWILIO_API_KEY_SID", "")
KEY_SECRET = CFG.get("TWILIO_API_KEY_SECRET", "")
FROM = CFG.get("TWILIO_FROM_NUMBER", "")
TO = CFG.get("TWILIO_TO_NUMBER", "")

# ── ntfy + paging policy ────────────────────────────────────────────────────────
NTFY_URL = cfg("NTFY_URL")                      # NL: http://10.0.X.X:8880 (LAN); GR: public URL
NTFY_TOPIC = cfg("NTFY_TOPIC_TIER1", "alrt-tier1")
NTFY_TOKEN = cfg("NTFY_TOKEN")
# Health probe URL. Default works for a DIRECT ntfy (LAN). Through the public
# matrix.example.net route the root /v1/health lands on element-web
# (only /alrt-*, /up*, /ntfy/ proxy to ntfy) -> set NTFY_HEALTH_URL to
# https://matrix.example.net/ntfy/v1/health there (GR bridge env).
# Caught live 2026-08-26: the GR bridge false-fired one PagingPushDown SMS.
NTFY_HEALTH_URL = cfg("NTFY_HEALTH_URL", "")
SITE = cfg("PAGING_SITE", "nl")
DRY_RUN = cfg("PAGING_DRY_RUN", "0") not in ("", "0", "false", "False", "no", "NO")
SMS_LABEL = cfg("PAGING_SMS_LABEL", "page")     # PrometheusRule label that opts an alert into SMS
SMS_LABEL_VALUE = cfg("PAGING_SMS_LABEL_VALUE", "sms")
SMS_FAILOVER = cfg("PAGING_SMS_FAILOVER", "1") not in ("", "0", "false", "False", "no", "NO")
SMS_FAILOVER_CAP_PER_H = int(cfg("PAGING_SMS_FAILOVER_CAP_PER_H", "3"))
REPAGE_S = int(cfg("PAGING_REPAGE_S", "21600"))          # quiet-gap before the same alert re-pages
PROBE_S = int(cfg("PAGING_NTFY_PROBE_S", "60"))
DOWN_AFTER = int(cfg("PAGING_NTFY_DOWN_AFTER", "3"))
WATCHDOG_TIMEOUT_S = int(cfg("PAGING_WATCHDOG_TIMEOUT_S", "900"))
TEXTFILE = cfg("PAGING_TEXTFILE", "/var/lib/node_exporter/textfile_collector/paging_bridge.prom")
CLICK_URL = cfg("PAGING_CLICK_URL", "https://grafana.example.net/alerting/list")
# Alertmanager's generatorURL points at the IN-CLUSTER Prometheus
# (monitoring-kube-prometheus-prometheus.monitoring:9090, its externalUrl) — a
# dead link from a phone. Default: always click through to Grafana's alert list
# filtered on the alertname; set PAGING_USE_GENERATOR_URL=1 only if Prometheus
# ever gets a public externalUrl. Found 2026-08-26 on the operator's first page.
USE_GENERATOR_URL = cfg("PAGING_USE_GENERATOR_URL", "0") not in ("", "0", "false", "False", "no", "NO")


def _click_for(alertname: str, generator_url: str) -> str:
    if USE_GENERATOR_URL and generator_url:
        return generator_url
    sep = "&" if "?" in CLICK_URL else "?"
    return f"{CLICK_URL}{sep}search={urllib.parse.quote(alertname or '')}"

# ── State ───────────────────────────────────────────────────────────────────────
_last_sent: dict = {}            # legacy (unused by /alert now, kept for compat)
_session_last_seen: dict = {}
_dedup_lock = threading.Lock()

# /alert episodes: key -> {last_page, last_seen, resolved_sent}
_episodes: dict = {}
_episode_lock = threading.Lock()

# SMS fail-over cap (rolling 1h) + suppression notice
_failover_times: collections.deque = collections.deque()
_failover_notice_at = 0.0
_failover_lock = threading.Lock()

# ntfy health
_ntfy_up = True
_ntfy_fail_streak = 0
_ntfy_down_paged = False
_ntfy_lock = threading.Lock()

# Watchdog (Prometheus dead-man): site -> {"last": ts, "alarmed": bool}
_watchdog: dict = {}
_watchdog_lock = threading.Lock()

# Counters for /metrics + textfile: (channel, outcome) -> n
_events: dict = collections.defaultdict(int)
_events_lock = threading.Lock()


def _count(channel: str, outcome: str) -> None:
    with _events_lock:
        _events[(channel, outcome)] += 1


def send_sms(body: str) -> tuple[bool, str]:
    if DRY_RUN:
        sys.stdout.write(f"DRY-RUN sms: {body[:160]}\n")
        sys.stdout.flush()
        return True, "dry-run"
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
            ok = resp.status < 300
            _count("sms", "sent" if ok else "failed")
            return ok, f"http {resp.status}"
    except Exception as e:
        _count("sms", "failed")
        return False, f"err {e}"


def send_push(title: str, message: str, priority: int = 5, tags: str = "",
              click: str = "") -> tuple[bool, str]:
    if DRY_RUN:
        sys.stdout.write(f"DRY-RUN ntfy p={priority}: {title} | {message[:120]}\n")
        sys.stdout.flush()
        return True, "dry-run"
    ok, info = ntfy_publish(NTFY_URL, NTFY_TOPIC, NTFY_TOKEN, title, message,
                            priority=priority, tags=tags, click=click or CLICK_URL)
    _count("ntfy", "sent" if ok else "failed")
    return ok, info


def _sms_failover(body: str) -> None:
    """SMS fallback when ntfy publish fails. Rolling cap; one notice at the cap."""
    global _failover_notice_at
    if not SMS_FAILOVER:
        _count("sms", "failover_disabled")
        return
    now = time.time()
    with _failover_lock:
        while _failover_times and now - _failover_times[0] > 3600:
            _failover_times.popleft()
        if len(_failover_times) >= SMS_FAILOVER_CAP_PER_H:
            _count("sms", "capped")
            if now - _failover_notice_at > 3600:
                _failover_notice_at = now
                send_sms(f"[PUSH-DOWN] fail-over cap reached ({SMS_FAILOVER_CAP_PER_H}/h); "
                         f"further tier-1 pages suppressed on SMS. Matrix/YouTrack unaffected.")
            return
        _failover_times.append(now)
    ok, info = send_sms(f"[PUSH-DOWN] {body}")
    sys.stdout.write(f"sms-failover ok={ok} info={info}\n")
    sys.stdout.flush()


# ── /alert: Alertmanager tier-1 → ntfy (+SMS allowlist) ────────────────────────
def _alert_channels(labels: dict) -> dict:
    return {"ntfy": True, "sms": labels.get(SMS_LABEL, "") == SMS_LABEL_VALUE}


def _episode_decision(key: str, status: str) -> str:
    """Edge-triggered episode dedup. Returns one of: page, dedup, resolve, skip.
    - firing: page on the leading edge; while the same alert keeps firing (or
      flapping) within REPAGE_S of the last page, suppress. Re-arms only after a
      REPAGE_S quiet gap since the last page.
    - resolved: one quiet notification per paged episode, only if we paged it."""
    now = time.time()
    with _episode_lock:
        ep = _episodes.get(key)
        if status == "firing":
            if ep is None or (now - ep["last_page"]) >= REPAGE_S:
                _episodes[key] = {"last_page": now, "last_seen": now, "resolved_sent": False}
                return "page"
            ep["last_seen"] = now
            return "dedup"
        # resolved
        if ep is None or ep["resolved_sent"]:
            return "skip"
        ep["resolved_sent"] = True
        ep["last_seen"] = now
        return "resolve"


def _fmt_alert(alert: dict) -> tuple[str, str, str]:
    labels = alert.get("labels", {})
    ann = alert.get("annotations", {})
    alertname = labels.get("alertname", "?")
    instance = labels.get("instance", "")
    asite = labels.get("site", "") or SITE
    summary = ann.get("summary") or alertname
    desc = ann.get("description", "")
    title = f"[{asite}] {alertname}"
    body_parts = [summary]
    if desc and desc != summary:
        body_parts.append(desc)
    if instance:
        body_parts.append(f"instance: {instance}")
    started = alert.get("startsAt", "")
    if started:
        body_parts.append(f"since: {started[:19]}Z")
    return title, "\n".join(body_parts)[:3800], instance


def handle_alertmanager_payload(payload: dict) -> dict:
    """Returns {pushed, sms, deduped, resolved}."""
    out = {"pushed": 0, "sms": 0, "deduped": 0, "resolved": 0}
    for alert in payload.get("alerts", []):
        labels = alert.get("labels", {})
        status = alert.get("status", "")
        tier = labels.get("tier", "")
        severity = labels.get("severity", "")
        alertname = labels.get("alertname", "?")
        instance = labels.get("instance", "")
        if tier != "1":       # string compare on purpose: Alertmanager labels are strings
            continue
        if severity != "critical" and status == "firing":
            continue          # firing must be critical; a resolved non-critical tier-1 still clears
        if status not in ("firing", "resolved"):
            continue
        key = f"{alertname}|{instance}"
        decision = _episode_decision(key, status)
        title, body, _ = _fmt_alert(alert)
        click = _click_for(alertname, alert.get("generatorURL", ""))
        if decision == "dedup":
            out["deduped"] += 1
            _count("ntfy", "deduped")
            continue
        if decision == "skip":
            continue
        if decision == "resolve":
            ok, info = send_push(f"{title} resolved", body, priority=3,
                                 tags="white_check_mark," + SITE, click=click)
            sys.stdout.write(f"page resolved ntfy ok={ok} info={info} key={key}\n")
            out["resolved"] += 1
            continue
        # decision == "page"
        channels = _alert_channels(labels)
        ok, info = send_push(title, body, priority=5,
                             tags="rotating_light," + SITE, click=click)
        sys.stdout.write(f"page ntfy ok={ok} info={info} key={key}\n")
        if ok:
            out["pushed"] += 1
        else:
            _sms_failover(f"[FIRING] {alertname} {instance} "
                          f"{alert.get('annotations', {}).get('summary', alertname)}")
        if channels["sms"]:
            sok, sinfo = send_sms(f"[FIRING] {alertname} {instance} "
                                  f"{alert.get('annotations', {}).get('summary', alertname)}"[:1500])
            sys.stdout.write(f"page sms(ultra) ok={sok} info={sinfo} key={key}\n")
            if sok:
                out["sms"] += 1
        sys.stdout.flush()
    return out


# ── /heartbeat: Prometheus dead-man per site ────────────────────────────────────
def handle_heartbeat_payload(payload: dict) -> dict:
    sites = set()
    for alert in payload.get("alerts", []):
        s = alert.get("labels", {}).get("site", "")
        if s:
            sites.add(s)
    if not sites:
        s = payload.get("commonLabels", {}).get("site", "")
        if s:
            sites.add(s)
    now = time.time()
    recovered = []
    with _watchdog_lock:
        for s in sites:
            st = _watchdog.setdefault(s, {"last": 0.0, "alarmed": False})
            st["last"] = now
            if st["alarmed"]:
                st["alarmed"] = False
                recovered.append(s)
    for s in recovered:
        send_push(f"[{s}] Prometheus heartbeat restored",
                  f"Watchdog from site={s} is flowing again.", priority=3,
                  tags="white_check_mark," + s)
        sys.stdout.write(f"heartbeat recovered site={s}\n")
    if sites:
        sys.stdout.write(f"heartbeat sites={','.join(sorted(sites))}\n")
        sys.stdout.flush()
    return {"sites": sorted(sites)}


def _watchdog_check() -> None:
    now = time.time()
    stale = []
    with _watchdog_lock:
        for s, st in _watchdog.items():
            if st["last"] and not st["alarmed"] and (now - st["last"]) > WATCHDOG_TIMEOUT_S:
                st["alarmed"] = True
                stale.append((s, now - st["last"]))
    for s, age in stale:
        body = (f"No Alertmanager Watchdog from site={s} for {int(age)}s "
                f"(threshold {WATCHDOG_TIMEOUT_S}s). Prometheus/Alertmanager at that "
                f"site may be dead - alerts are NOT flowing.")
        send_push(f"[{s}] PrometheusHeartbeatLost", body, priority=5,
                  tags="rotating_light,skull," + s)
        if s == SITE:  # SMS only for our own site; remote sites ride the overlay
            ok, info = send_sms(f"[{SITE.upper()}-ULTRA] PrometheusHeartbeatLost site={s}: {body}"[:1500])
            sys.stdout.write(f"watchdog-lost sms ok={ok} info={info} site={s}\n")
        sys.stdout.write(f"watchdog-lost site={s} age={int(age)}s\n")
        sys.stdout.flush()


# ── ntfy health probe (PagingPushDown) ─────────────────────────────────────────
def _probe_ntfy() -> None:
    global _ntfy_up, _ntfy_fail_streak, _ntfy_down_paged
    ok = False
    try:
        hurl = NTFY_HEALTH_URL or f"{NTFY_URL.rstrip('/')}/v1/health"
        with urllib.request.urlopen(hurl, timeout=5) as resp:
            ok = resp.status == 200
    except Exception:
        ok = False
    with _ntfy_lock:
        if ok:
            _ntfy_fail_streak = 0
            was_down = not _ntfy_up
            _ntfy_up = True
            paged = _ntfy_down_paged
            _ntfy_down_paged = False
        else:
            _ntfy_fail_streak += 1
            was_down = False
            if _ntfy_fail_streak >= DOWN_AFTER:
                _ntfy_up = False
            paged = False
    if ok and was_down:
        send_push(f"[{SITE}] paging push channel restored",
                  "ntfy is reachable again; pages resume on this channel.",
                  priority=3, tags="white_check_mark," + SITE)
        sys.stdout.write("ntfy-health recovered\n")
        sys.stdout.flush()
    if not ok:
        with _ntfy_lock:
            should_page = (not _ntfy_up) and (not _ntfy_down_paged)
            if should_page:
                _ntfy_down_paged = True
        if should_page:
            ok2, info = send_sms(f"[{SITE.upper()}-ULTRA] PagingPushDown site={SITE}: ntfy at "
                                 f"{NTFY_URL} unreachable ({_ntfy_fail_streak} consecutive probe "
                                 f"failures). Tier-1 pushes are NOT being delivered; SMS fail-over "
                                 f"active (cap {SMS_FAILOVER_CAP_PER_H}/h). Matrix/YT unaffected.")
            sys.stdout.write(f"ntfy-health DOWN paged sms ok={ok2} info={info}\n")
            sys.stdout.flush()


# ── Textfile metrics ────────────────────────────────────────────────────────────
def _write_metrics() -> None:
    try:
        now = time.time()
        lines = [
            "# HELP paging_bridge_heartbeat_timestamp_seconds Bridge metrics-loop liveness.",
            "# TYPE paging_bridge_heartbeat_timestamp_seconds gauge",
            f'paging_bridge_heartbeat_timestamp_seconds{{site="{SITE}"}} {now:.0f}',
            "# HELP paging_ntfy_up 1 if the ntfy health probe is passing.",
            "# TYPE paging_ntfy_up gauge",
        ]
        with _ntfy_lock:
            lines.append(f'paging_ntfy_up{{site="{SITE}"}} {1 if _ntfy_up else 0}')
        lines += ["# HELP paging_events_total Paging events by channel and outcome.",
                  "# TYPE paging_events_total counter"]
        with _events_lock:
            for (channel, outcome), n in sorted(_events.items()):
                lines.append(f'paging_events_total{{site="{SITE}",channel="{channel}",outcome="{outcome}"}} {n}')
        lines += ["# HELP paging_watchdog_last_seen_timestamp_seconds Last Alertmanager Watchdog per site.",
                  "# TYPE paging_watchdog_last_seen_timestamp_seconds gauge"]
        with _watchdog_lock:
            for s, st in sorted(_watchdog.items()):
                lines.append(f'paging_watchdog_last_seen_timestamp_seconds{{site="{s}"}} {st["last"]:.0f}')
        blob = "\n".join(lines) + "\n"
        d = os.path.dirname(TEXTFILE)
        if not os.path.isdir(d):
            return  # host without a textfile collector (e.g. GR until scraped)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".paging_bridge.")
        with os.fdopen(fd, "w") as f:
            f.write(blob)
        os.chmod(tmp, 0o644)
        os.replace(tmp, TEXTFILE)
    except Exception as e:  # metrics must never kill the bridge
        sys.stderr.write(f"metrics write failed: {e}\n")


def _background_loop() -> None:
    while True:
        try:
            _probe_ntfy()
            _watchdog_check()
            _write_metrics()
        except Exception as e:
            sys.stderr.write(f"background loop error: {e}\n")
        time.sleep(PROBE_S)


def should_send(dedup_key: str, window: int = 300) -> bool:
    """Legacy fixed-window dedup (kept for compatibility with older callers)."""
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
# RETIRED 2026-07-09 (daily Matrix HITL digest replaced it): the sentinel is
# absent, so this returns outcome=suppressed. Kept verbatim for the 4 relay
# callers; do not extend. DEPRECATED.
def _session_sms_enabled() -> bool:
    v = os.environ.get("AUTONOMY_SESSION_SMS")
    if v is not None:
        return v not in ("", "0", "false", "False", "no", "NO")
    return os.path.exists(os.path.expanduser("~/gateway.autonomy_session_sms"))


_session_sms_counts: dict = {"sent": 0, "deduped": 0, "suppressed": 0, "gated": 0, "error": 0}


def _session_reason_is_critical(payload: dict) -> bool:
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
    body = f"[NL-CRIT] {issue_id} {host} {risk}/{band}: {summary}. Veto: Matrix !session abort {issue_id}"
    ok, info = send_sms(body)
    _session_sms_counts["sent" if ok else "error"] += 1
    sys.stdout.write(f"session-sms ok={ok} info={info} issue={issue_id} band={band}\n")
    sys.stdout.flush()
    return {"outcome": "sent" if ok else "error", "issue_id": issue_id, "info": info}


class AlertHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path not in ("/alert", "/alert-session", "/heartbeat"):
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
        elif self.path == "/heartbeat":
            result = handle_heartbeat_payload(payload)
        else:
            result = handle_alertmanager_payload(payload)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        if self.path == "/metrics":
            lines = [
                "# HELP session_sms_total Session->SMS outcomes (IFRNLLEI01PRD-1105, retired path)",
                "# TYPE session_sms_total counter",
            ]
            for outcome, n in _session_sms_counts.items():
                lines.append(f'session_sms_total{{outcome="{outcome}"}} {n}')
            lines += ["# HELP paging_events_total Paging events by channel and outcome.",
                      "# TYPE paging_events_total counter"]
            with _events_lock:
                for (channel, outcome), n in sorted(_events.items()):
                    lines.append(f'paging_events_total{{channel="{channel}",outcome="{outcome}"}} {n}')
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
        sys.stderr.write(f"WARNING: missing Twilio creds in {ENV_FILE}; SMS channel in dry-run\n")
    if not NTFY_URL or not NTFY_TOKEN:
        sys.stderr.write(f"WARNING: NTFY_URL/NTFY_TOKEN missing in {ENV_FILE}; ntfy channel dead — "
                         f"tier-1 pages will fail over to SMS (capped)\n")
    sys.stdout.write(f"paging-bridge: :{LISTEN_PORT} site={SITE} ntfy={NTFY_URL}/{NTFY_TOPIC} "
                     f"repage={REPAGE_S}s failover_cap={SMS_FAILOVER_CAP_PER_H}/h dry_run={DRY_RUN}\n")
    sys.stdout.flush()
    t = threading.Thread(target=_background_loop, daemon=True, name="paging-background")
    t.start()
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), AlertHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
