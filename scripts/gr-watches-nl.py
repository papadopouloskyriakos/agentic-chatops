#!/usr/bin/env python3
"""gr-watches-nl: the GR site watches NL and pages when NL is degraded.

IFRNLLEI01PRD-2992 (NL power-loss postmortem, MR !284), operator decision B.
During the 2026-11-06/07 house power loss the GR paging bridge paged once when the
NL ntfy server died (21:26 NL) and saw it recover (03:48 NL), but nothing watched NL
itself: 03:30 -> 11:09 NL passed silently while 46 guests were still down.

Runs on grclaude01 every minute (systemd gr-watches-nl.timer -> --once). Probes
key NL services from GR and raises `NLSiteDegraded` through the LOCAL GR paging
bridge (scripts/paging-bridge.py, POST /alert, Alertmanager webhook format):

  degraded   any CRITICAL check failing, OR >= 2 counted checks failing
  page       degraded for GRWATCH_DEGRADED_AFTER (5) consecutive runs (~5 min)
  re-notify  every GRWATCH_RENOTIFY_S (3600 s) while still degraded. Each notification
             carries its own episode key (instance ...#n), so the cadence is owned
             here and does not depend on the bridge's own re-page policy.
  recovery   one resolved push after GRWATCH_RECOVER_AFTER (3) consecutive
             not-degraded runs, only if the episode was paged.

Channels are decided by the bridge: labels tier=1 + severity=critical and NO
page="sms" label -> ntfy push first; when ntfy is unreachable the bridge's capped SMS
fail-over (PAGING_SMS_FAILOVER_CAP_PER_H=3) carries it. NL site loss / isolation is in
the operator's ULTRA SMS class, so that fail-over SMS is within policy.

Observer self-check: when GR itself has no internet (1.1.1.1 / 9.9.9.9 / 8.8.8.8 :443
all fail), the run is skipped and the state frozen. That is GR isolation, which
gr-inalan-wan-monitor already pages; it must not also read as "NL degraded".

Fallback: if the bridge is not listening (or lost a paged episode across a restart),
the checker publishes the push directly to ntfy with the bridge's own ntfy settings.
It never sends SMS itself.

Modes: --once (the timer) | --status | --check-bridge (side-effect-free check of the
live bridge) | --test (fake failing checks against a SANDBOX bridge that has no Twilio
credentials: exactly one TEST push, no SMS possible) | --mute 2h | --unmute.

Runbook: docs/runbooks/gr-watches-nl.md
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import fcntl
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


BRIDGE_URL = _env("GRWATCH_BRIDGE_URL", "http://127.0.0.1:9106")
BRIDGE_ENV = _env("GRWATCH_BRIDGE_ENV", "/home/app-user/.config/am-twilio/env")
STATE_DIR = _env("GRWATCH_STATE_DIR", "/var/lib/gr-watches-nl")
DEGRADED_AFTER = int(_env("GRWATCH_DEGRADED_AFTER", "5"))
RECOVER_AFTER = int(_env("GRWATCH_RECOVER_AFTER", "3"))
RENOTIFY_S = int(_env("GRWATCH_RENOTIFY_S", "3600"))
TIMEOUT_S = float(_env("GRWATCH_TIMEOUT_S", "5"))
ATTEMPTS = int(_env("GRWATCH_ATTEMPTS", "2"))
BRIDGE_POST_TIMEOUT_S = 30   # the bridge can spend 2x8 s on ntfy + 8 s on a fail-over SMS
MAX_MUTE_S = 24 * 3600
OBSERVER_REFS = [("1.1.1.1", 443), ("9.9.9.9", 443), ("8.8.8.8", 443)]
ALERTNAME = "NLSiteDegraded"
RUNBOOK = "docs/runbooks/gr-watches-nl.md"

# role: critical = one failure is enough (the NL alerting chain itself);
#       normal   = counts toward the ">= 2 failing" rule;
#       info     = reported in the message, never counted.
DEFAULT_TARGETS = [
    {"name": "TG intake", "role": "critical", "type": "http",
     "url": "http://10.0.181.X:8080/api/healthz", "expect": "ok",
     "why": "nltg01 territory-grounder, the primary NL alert intake"},
    {"name": "NL Prometheus+Alertmanager", "role": "critical", "type": "prom",
     "nodes": ["10.0.X.X", "10.0.X.X", "10.0.X.X", "10.0.X.X"],
     "port": 30090, "why": "NL k8s Prometheus NodePort; ready + >=1 active Alertmanager"},
    {"name": "nl-claude01", "role": "critical", "type": "tcp",
     "host": "10.0.181.X", "port": 22, "expect": "SSH-",
     "why": "NL paging bridge + gateway host; SSH banner (a storage-dead host dies at the banner)"},
    {"name": "n8n", "role": "normal", "type": "http",
     "url": "https://n8n.example.net/healthz", "expect": '"ok"'},
    {"name": "Home Assistant", "role": "normal", "type": "http",
     "url": "http://10.0.181.X:8123/manifest.json", "expect": "Home automation",
     "why": "HAHA VIP"},
    {"name": "Nextcloud", "role": "normal", "type": "http",
     "url": "https://nextcloud.example.net/status.php", "expect": '"maintenance":false'},
    {"name": "public edge (ntfy on nl-matrix01 via matrix.example.net)",
     "role": "info", "type": "http",
     "url": "https://matrix.example.net/ntfy/v1/health", "expect": '"healthy":true',
     "why": "reached over the VPS edge, not the NL-GR tunnels: tells a partition from a site loss"},
]

TEST_TARGETS = [
    {"name": "TEST fake unroutable 192.0.2.1:9 (TEST-NET-1)", "role": "critical", "type": "http",
     "url": "http://192.0.2.1:9/", "expect": ""},
    {"name": "TEST fake refused 127.0.0.1:1", "role": "normal", "type": "tcp",
     "host": "127.0.0.1", "port": 1, "expect": ""},
]

_CTX = ssl.create_default_context()


def log(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ── time helpers ───────────────────────────────────────────────────────────────
def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y%m%dT%H%MZ")


def _nl_time(ts: float) -> str:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(ts, ZoneInfo("Europe/Amsterdam")).strftime("%H:%M NL")
    except Exception:  # noqa: BLE001 - no tzdata: fall back to UTC
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%H:%MZ")


def _dur(seconds: float) -> str:
    m = max(0, int(seconds // 60))
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


# ── probes ─────────────────────────────────────────────────────────────────────
def _short_err(e: Exception) -> str:
    reason = getattr(e, "reason", None)
    if isinstance(e, (socket.timeout, TimeoutError)) or isinstance(reason, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(e, ConnectionRefusedError) or isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    text = str(reason if reason is not None else e)
    return f"{type(e).__name__}: {text}"[:140]


def _http_once(url: str, expect: str, timeout: float) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "gr-watches-nl/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            body = resp.read(16384).decode("utf-8", "replace")
            if resp.status != 200:
                return False, f"http {resp.status}"
            if expect and expect not in body:
                return False, f"http 200 but the body lacks {expect!r}"
            return True, "http 200"
    except urllib.error.HTTPError as e:
        return False, f"http {e.code}"
    except Exception as e:  # noqa: BLE001 - a probe never raises
        return False, _short_err(e)


def _tcp_once(host: str, port: int, expect: str, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            if not expect:
                return True, "tcp open"
            s.settimeout(timeout)
            data = s.recv(64).decode("latin-1", "replace")
            if data.startswith(expect):
                return True, f"banner {data.strip()[:24]}"
            return False, f"no {expect!r} banner (got {data.strip()[:24]!r})"
    except Exception as e:  # noqa: BLE001
        return False, _short_err(e)


def _prom_once(t: dict, timeout: float) -> tuple[bool, str]:
    errs = []
    for node in t["nodes"]:
        base = f"http://{node}:{t.get('port', 30090)}"
        ok, info = _http_once(base + "/-/ready", "Ready", timeout)
        if not ok:
            errs.append(f"{node} {info}")
            continue
        try:
            with urllib.request.urlopen(base + "/api/v1/alertmanagers", timeout=timeout) as resp:
                data = json.loads(resp.read(262144))
            n = len(data.get("data", {}).get("activeAlertmanagers", []))
        except Exception as e:  # noqa: BLE001
            return False, f"Prometheus ready on {node} but the Alertmanager query failed: {_short_err(e)}"
        if n == 0:
            return False, f"Prometheus ready on {node} but 0 active Alertmanagers"
        return True, f"ready on {node}, {n} Alertmanagers"
    return False, "Prometheus not ready on any node (" + "; ".join(errs) + ")"


def probe(t: dict, timeout: float = TIMEOUT_S, attempts: int = ATTEMPTS) -> dict:
    kind = t["type"]
    if kind == "prom":
        attempts = 1   # several nodes already give redundancy; keeps the worst case < 25 s
    info = "unprobed"
    for i in range(max(1, attempts)):
        if kind == "http":
            ok, info = _http_once(t["url"], t.get("expect", ""), timeout)
        elif kind == "tcp":
            ok, info = _tcp_once(t["host"], t["port"], t.get("expect", ""), timeout)
        elif kind == "prom":
            ok, info = _prom_once(t, timeout)
        else:
            ok, info = False, f"unknown probe type {kind}"
        if ok:
            return {"name": t["name"], "role": t["role"], "ok": True, "info": info}
        if i + 1 < attempts:
            time.sleep(1.5)
    return {"name": t["name"], "role": t["role"], "ok": False, "info": info}


def probe_all(targets: list, timeout: float = TIMEOUT_S, attempts: int = ATTEMPTS) -> list:
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
        return list(pool.map(lambda t: probe(t, timeout, attempts), targets))


def observer_ok(refs=None, timeout: float = 3.0) -> bool:
    for host, port in (refs or OBSERVER_REFS):
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def evaluate(results: list) -> tuple[bool, list, list]:
    """degraded = any critical failing, or >= 2 counted (non-info) failing."""
    counted = [r for r in results if r["role"] != "info"]
    failing = [r for r in counted if not r["ok"]]
    crit = [r for r in failing if r["role"] == "critical"]
    return (bool(crit) or len(failing) >= 2), failing, crit


# ── bridge + direct ntfy ───────────────────────────────────────────────────────
def read_env_file(path: str) -> dict:
    """Same KEY=VALUE parsing as paging-bridge.load_env()."""
    out: dict = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def bridge_post(base_url: str, path: str, payload: dict,
                timeout: float = BRIDGE_POST_TIMEOUT_S) -> tuple[str, dict]:
    """Returns (status, response). status: ok | refused | timeout | error."""
    req = urllib.request.Request(base_url.rstrip("/") + path, data=json.dumps(payload).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return "ok", json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return "error", {"http": e.code}
    except Exception as e:  # noqa: BLE001
        err = _short_err(e)
        if err == "timeout":
            return "timeout", {}
        if err == "connection refused":
            return "refused", {}
        return "error", {"err": err}


def direct_push(title: str, body: str, priority: int, tags: str, env_path: str = BRIDGE_ENV) -> bool:
    """Publish straight to ntfy with the bridge's own ntfy settings. Never SMS."""
    try:
        from lib.ntfy import publish
    except Exception as e:  # noqa: BLE001
        log(f"direct-push unavailable: {e}")
        return False
    cfg = read_env_file(env_path)
    ok, info = publish(cfg.get("NTFY_URL", ""), cfg.get("NTFY_TOPIC_TIER1", "alrt-tier1"),
                       cfg.get("NTFY_TOKEN", ""), title, body, priority=priority, tags=tags)
    log(f"direct-push ok={ok} info={info}")
    return ok


# ── mute (GR-local, always time-boxed) ─────────────────────────────────────────
def parse_duration(text: str) -> int:
    text = text.strip().lower()
    mult = {"m": 60, "h": 3600, "d": 86400}
    if text and text[-1] in mult:
        return int(float(text[:-1]) * mult[text[-1]])
    return int(text)


def mute_until(path: str, now: float) -> float:
    try:
        with open(path) as f:
            until = float(json.load(f).get("until", 0))
    except Exception:  # noqa: BLE001 - absent or unreadable = not muted
        return 0.0
    return until if until > now else 0.0


# ── the state machine ──────────────────────────────────────────────────────────
class Watcher:
    def __init__(self, targets: list, state_path: str, mute_path: str | None = None,
                 site_label: str = "nl", instance_prefix: str = "nl-from-gr",
                 summary_prefix: str = "", bridge_url: str = BRIDGE_URL,
                 timeout: float = TIMEOUT_S, attempts: int = ATTEMPTS,
                 probe_fn=None, post_fn=None, direct_fn=None, observer_fn=None,
                 now_fn=time.time):
        self.targets = targets
        self.state_path = state_path
        self.mute_path = mute_path
        self.site_label = site_label
        self.instance_prefix = instance_prefix
        self.summary_prefix = summary_prefix
        self.probe_fn = probe_fn or (lambda ts: probe_all(ts, timeout, attempts))
        self.post_fn = post_fn or (lambda path, payload: bridge_post(bridge_url, path, payload))
        self.direct_fn = direct_fn or direct_push
        self.observer_fn = observer_fn or observer_ok
        self.now_fn = now_fn

    # state
    def load(self) -> dict:
        try:
            with open(self.state_path) as f:
                st = json.load(f)
        except FileNotFoundError:
            st = {}
        except Exception as e:  # noqa: BLE001 - corrupt state: start clean, say so
            log(f"state unreadable ({e}); starting clean")
            st = {}
        st.setdefault("cd", 0)            # consecutive degraded runs
        st.setdefault("ch", 0)            # consecutive not-degraded runs
        st.setdefault("streak_start", None)
        st.setdefault("episode", None)
        return st

    def save(self, st: dict) -> None:
        d = os.path.dirname(self.state_path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".state.")
        with os.fdopen(fd, "w") as f:
            json.dump(st, f, indent=1, sort_keys=True)
        os.replace(tmp, self.state_path)

    # message building
    def _labels(self, instance: str) -> dict:
        return {"alertname": ALERTNAME, "instance": instance, "site": self.site_label,
                "observer": "gr", "source": "gr-watches-nl", "tier": "1", "severity": "critical"}

    def _detail(self, results: list, failing: list, crit: list, start: float) -> str:
        counted = [r for r in results if r["role"] != "info"]
        lines = [f"{len(failing)}/{len(counted)} NL checks failing ({len(crit)} critical) "
                 f"since {_nl_time(start)} ({_iso(start)})."]
        for r in failing:
            lines.append(f"FAIL {r['name']} [{r['role']}]: {r['info']}")
        ok_names = [r["name"] for r in counted if r["ok"]]
        if ok_names:
            lines.append("OK: " + ", ".join(ok_names))
        for r in results:
            if r["role"] != "info":
                continue
            if not r["ok"]:
                lines.append(f"{r['name']}: DOWN too ({r['info']}) - NL looks down as a whole.")
            elif len(failing) == len(counted):
                lines.append(f"{r['name']}: OK - NL still answers over the public edge, so suspect the "
                             f"NL-GR path (partition) rather than an NL site loss.")
            else:
                lines.append(f"{r['name']}: OK")
        lines.append(f"Rule: a critical check failing or >= 2 checks failing for {DEGRADED_AFTER} "
                     f"consecutive 1-min runs. Re-notify every {RENOTIFY_S // 60}m while degraded; "
                     f"one recovery push when healthy. Runbook: {RUNBOOK}")
        return "\n".join(lines)

    def _alert(self, status: str, instance: str, summary: str, desc: str, start: float,
               end: float | None = None) -> dict:
        a = {"status": status, "labels": self._labels(instance),
             "annotations": {"summary": summary, "description": desc},
             "startsAt": _iso(start), "generatorURL": ""}
        if end is not None:
            a["endsAt"] = _iso(end)
        return a

    def _send(self, alert: dict) -> tuple[str, dict]:
        payload = {"version": "4", "status": alert["status"], "receiver": "gr-watches-nl",
                   "groupLabels": {"alertname": ALERTNAME}, "commonLabels": alert["labels"],
                   "alerts": [alert]}
        return self.post_fn("/alert", payload)

    def _page(self, ep: dict, results: list, failing: list, crit: list, now: float) -> bool:
        n = ep["n"] + 1
        instance = f"{self.instance_prefix}@{_compact(ep['start'])}#{n}"
        names = ", ".join(r["name"] for r in failing)
        still = "STILL degraded" if n > 1 else "degraded"
        summary = f"{self.summary_prefix}NL {still} (seen from GR) for {_dur(now - ep['start'])}: {names} down"
        desc = self._detail(results, failing, crit, ep["start"])
        status, resp = self._send(self._alert("firing", instance, summary, desc, ep["start"]))
        if status == "ok":
            if resp.get("pushed", 0) >= 1:
                log(f"page #{n} delivered: bridge pushed to ntfy (instance={instance})")
            elif resp.get("deduped", 0) >= 1:
                log(f"page #{n}: bridge deduped instance={instance} (unexpected key reuse)")
            else:
                log(f"page #{n}: bridge ntfy push FAILED -> bridge SMS fail-over path "
                    f"(capped) instance={instance} resp={resp}")
        elif status == "timeout":
            log(f"page #{n}: bridge POST timed out; assuming the bridge handled it "
                f"(no retry: a retry could double an SMS) instance={instance}")
        else:
            log(f"page #{n}: bridge unreachable ({status} {resp}); direct ntfy push fallback")
            if not self.direct_fn(f"[{self.site_label}] {ALERTNAME}", f"{summary}\n{desc}", 5,
                                  "rotating_light,gr"):
                return False
        ep.update(n=n, paged=True, last_page=now, last_instance=instance, last_summary=summary)
        return True

    def _recover(self, ep: dict, results: list, now: float) -> bool:
        counted = [r for r in results if r["role"] != "info"]
        still = [r for r in counted if not r["ok"]]
        summary = (f"{self.summary_prefix}NL healthy again (seen from GR) after "
                   f"{_dur(now - ep['start'])}, {ep['n']} notification(s)")
        if still:
            desc = ("Below the degraded rule now, but still failing: "
                    + "; ".join(f"{r['name']}: {r['info']}" for r in still))
        else:
            desc = f"All {len(counted)} NL checks pass."
        status, resp = self._send(self._alert("resolved", ep["last_instance"], summary, desc,
                                              ep["start"], end=now))
        if status == "ok" and resp.get("resolved", 0) >= 1:
            log(f"recovery delivered via bridge (instance={ep['last_instance']})")
            return True
        if status == "timeout":
            log("recovery: bridge POST timed out; assuming delivered")
            return True
        why = "bridge has no record of the episode (restarted?)" if status == "ok" else f"bridge {status}"
        log(f"recovery: {why}; direct ntfy push fallback")
        return self.direct_fn(f"[{self.site_label}] {ALERTNAME} resolved", f"{summary}\n{desc}", 3,
                              "white_check_mark,gr")

    def run_once(self) -> int:
        now = self.now_fn()
        st = self.load()
        if not self.observer_fn():
            st["last_run"] = now
            st["last_observer_isolated"] = now
            self.save(st)
            log("run skipped: GR has no internet path (observer isolated); state frozen")
            return 0
        results = self.probe_fn(self.targets)
        degraded, failing, crit = evaluate(results)
        if degraded:
            if st["cd"] == 0:
                st["streak_start"] = now
            st["cd"] += 1
            st["ch"] = 0
        else:
            st["ch"] += 1
            st["cd"] = 0
            st["streak_start"] = None
        ep = st.get("episode")
        action, rc = "none", 0
        muted = mute_until(self.mute_path, now) if self.mute_path else 0.0
        if degraded:
            if ep is None and st["cd"] >= DEGRADED_AFTER:
                ep = {"start": st["streak_start"] or now, "paged": False, "n": 0,
                      "last_page": 0.0, "last_instance": None}
                st["episode"] = ep
            if ep is not None and ((not ep["paged"]) or now - ep["last_page"] >= RENOTIFY_S):
                if muted:
                    action = f"muted-until-{_iso(muted)}"
                elif self._page(ep, results, failing, crit, now):
                    action = f"paged#{ep['n']}"
                else:
                    action, rc = "page-failed", 1
        elif ep is not None and st["ch"] >= RECOVER_AFTER:
            if not ep["paged"]:
                action = "episode-closed-unpaged"
                st["episode"] = None
            elif self._recover(ep, results, now):
                action = "recovered"
                st["episode"] = None
            else:
                action, rc = "recovery-failed", 1
        st["last_run"] = now
        st["last_failing"] = [r["name"] for r in failing]
        self.save(st)
        ep = st.get("episode")
        log(f"run degraded={degraded} failing={len(failing)}/"
            f"{len([r for r in results if r['role'] != 'info'])} cd={st['cd']} ch={st['ch']} "
            f"episode={'none' if ep is None else ('paged#%d' % ep['n'] if ep['paged'] else 'pending')} "
            f"action={action}"
            + ("" if not failing else " | " + "; ".join(f"{r['name']}: {r['info']}" for r in failing)))
        return rc


# ── modes ──────────────────────────────────────────────────────────────────────
def _paths() -> tuple[str, str, str]:
    return (os.path.join(STATE_DIR, "state.json"), os.path.join(STATE_DIR, "mute.json"),
            os.path.join(STATE_DIR, "lock"))


def cmd_once(targets: list) -> int:
    state_path, mute_path, lock_path = _paths()
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(lock_path, "w") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log("another run holds the lock; skipping")
            return 0
        return Watcher(targets, state_path, mute_path).run_once()


def cmd_status() -> int:
    state_path, mute_path, _ = _paths()
    now = time.time()
    st = Watcher([], state_path).load()
    last = st.get("last_run")
    print(json.dumps(st, indent=1, sort_keys=True))
    print(f"last_run_age_s={int(now - last) if last else 'never'}")
    m = mute_until(mute_path, now)
    print(f"muted_until={_iso(m) if m else 'no'}")
    return 0


def cmd_mute(duration: str, reason: str) -> int:
    _, mute_path, _ = _paths()
    secs = parse_duration(duration)
    if secs <= 0 or secs > MAX_MUTE_S:
        log(f"mute must be between 1s and {MAX_MUTE_S // 3600}h")
        return 2
    os.makedirs(STATE_DIR, exist_ok=True)
    until = time.time() + secs
    with open(mute_path, "w") as f:
        json.dump({"until": until, "reason": reason, "by": os.environ.get("USER", "?"),
                   "set_at": _iso(time.time())}, f)
    log(f"muted until {_iso(until)} ({reason}); probing continues, pages are held")
    return 0


def cmd_unmute() -> int:
    _, mute_path, _ = _paths()
    try:
        os.unlink(mute_path)
        log("unmuted")
    except FileNotFoundError:
        log("was not muted")
    return 0


def cmd_check_bridge(bridge_url: str) -> int:
    """GET /health + POST a resolved alert for a never-paged key. The bridge answers
    'skip' for it: proves it parses this payload with ZERO pushes and ZERO SMS."""
    try:
        with urllib.request.urlopen(bridge_url.rstrip("/") + "/health", timeout=5) as resp:
            health = resp.read().decode().strip()
    except Exception as e:  # noqa: BLE001
        log(f"bridge /health FAILED: {_short_err(e)}")
        return 1
    now = time.time()
    w = Watcher([], "/dev/null", site_label="gr", instance_prefix="gr-watches-nl-bridge-check",
                bridge_url=bridge_url)
    alert = w._alert("resolved", f"gr-watches-nl-bridge-check@{_compact(now)}#never-paged",
                     "bridge check (resolved for a never-paged key: no push, no SMS)", "", now, end=now)
    status, resp = w._send(alert)
    zero = status == "ok" and all(resp.get(k, 0) == 0 for k in ("pushed", "sms", "deduped", "resolved"))
    log(f"bridge /health={health!r} POST /alert status={status} resp={resp} -> "
        f"{'OK (parsed, nothing sent)' if zero else 'UNEXPECTED'}")
    return 0 if zero else 1


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cmd_test(bridge_script: str, interval: float) -> int:
    """Fake failing checks -> a SANDBOX bridge (the deployed paging-bridge.py, started
    with an env file that holds ONLY the ntfy keys: no Twilio credentials, fail-over
    off) -> exactly one real ntfy push titled [TEST]. No SMS is possible on this path."""
    real = read_env_file(BRIDGE_ENV)
    keep = {k: real[k] for k in ("NTFY_URL", "NTFY_TOPIC_TIER1", "NTFY_TOKEN", "NTFY_HEALTH_URL")
            if real.get(k)}
    if not (keep.get("NTFY_URL") and keep.get("NTFY_TOKEN")):
        log(f"TEST ABORT: no NTFY_URL/NTFY_TOKEN in {BRIDGE_ENV}")
        return 2
    if any(k.startswith("TWILIO") for k in keep):
        log("TEST ABORT: sandbox env would carry Twilio keys")
        return 2
    tmpdir = tempfile.mkdtemp(prefix="grwatch-test-")
    envfile = os.path.join(tmpdir, "sandbox-bridge.env")
    fd = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("".join(f"{k}={v}\n" for k, v in keep.items()))
    port = _free_port()
    benv = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmpdir,
            "AM_TWILIO_ENV": envfile, "AM_TWILIO_PORT": str(port), "PAGING_SITE": "gr",
            "PAGING_DRY_RUN": "0", "PAGING_SMS_FAILOVER": "0",
            "PAGING_TEXTFILE": os.path.join(tmpdir, "no-collector", "paging_bridge.prom"),
            "PYTHONUNBUFFERED": "1"}
    bridge_log = os.path.join(tmpdir, "sandbox-bridge.log")
    log(f"TEST: sandbox bridge {bridge_script} on 127.0.0.1:{port}; env keys={sorted(keep)} "
        f"(no TWILIO_*), PAGING_SMS_FAILOVER=0 -> SMS impossible")
    posts: list = []
    rc = 1
    with open(bridge_log, "w") as lf:
        proc = subprocess.Popen([sys.executable, bridge_script], env=benv, stdout=lf,
                                stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(50):
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as resp:
                        if resp.status == 200:
                            break
                except Exception:  # noqa: BLE001
                    time.sleep(0.2)
            else:
                log("TEST ABORT: sandbox bridge did not come up")
                return 2

            def post_fn(path, payload):
                res = bridge_post(base, path, payload)
                posts.append((payload, res))
                return res

            def no_direct(*_a):
                log("TEST: direct-push fallback is disabled in test mode")
                return False

            w = Watcher(TEST_TARGETS, os.path.join(tmpdir, "state.json"), mute_path=None,
                        site_label="TEST", instance_prefix="TEST-nl-from-gr",
                        summary_prefix="TEST (ignore): ", timeout=1.5, attempts=1,
                        post_fn=post_fn, direct_fn=no_direct)
            cycles = DEGRADED_AFTER + 3
            for i in range(cycles):
                log(f"TEST cycle {i + 1}/{cycles}")
                w.run_once()
                if i + 1 < cycles:
                    time.sleep(interval)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    os.unlink(envfile)  # the token copy goes first
    with open(bridge_log) as f:
        blog = f.read()
    shutil.rmtree(tmpdir, ignore_errors=True)
    firing = [(p, r) for p, r in posts if p["status"] == "firing"]
    pushed = sum(r[1].get("pushed", 0) for _, r in firing if r[0] == "ok")
    sms_resp = sum(r[1].get("sms", 0) for _, r in posts if r[0] == "ok")
    page_lines = [ln for ln in blog.splitlines() if ln.startswith("page ntfy ok=True")]
    sms_lines = [ln for ln in blog.splitlines()
                 if ("sms" in ln.lower()) and not ln.startswith("WARNING: missing Twilio creds")]
    titles = [f"[{p['alerts'][0]['labels']['site']}] {p['alerts'][0]['labels']['alertname']}"
              for p, _ in firing]
    checks = {
        "exactly_one_firing_post": len(firing) == 1,
        "bridge_pushed_exactly_one": pushed == 1,
        "bridge_log_one_ntfy_ok": len(page_lines) == 1,
        "title_marked_TEST": bool(titles) and all(t.startswith("[TEST]") for t in titles),
        "zero_sms_in_responses": sms_resp == 0,
        "zero_sms_lines_in_bridge_log": not sms_lines,
        "sandbox_had_no_twilio_creds": "missing Twilio creds" in blog,
    }
    log("TEST sandbox bridge log:\n  " + "\n  ".join(blog.strip().splitlines()))
    log(f"TEST push title(s): {titles}")
    for k, v in checks.items():
        log(f"TEST {k}={'PASS' if v else 'FAIL'}")
    rc = 0 if all(checks.values()) else 1
    log(f"TEST RESULT: {'PASS' if rc == 0 else 'FAIL'}")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GR watches NL (IFRNLLEI01PRD-2992)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="one probe run (the timer's mode)")
    g.add_argument("--status", action="store_true")
    g.add_argument("--check-bridge", action="store_true")
    g.add_argument("--test", action="store_true")
    g.add_argument("--mute", metavar="DURATION", help="hold pages, e.g. 90m / 2h (max 24h)")
    g.add_argument("--unmute", action="store_true")
    ap.add_argument("--reason", default="planned NL work")
    ap.add_argument("--targets", help="JSON file overriding the default NL check list")
    ap.add_argument("--bridge-url", default=BRIDGE_URL)
    ap.add_argument("--bridge-script", default=os.path.join(HERE, "paging-bridge.py"))
    ap.add_argument("--test-interval", type=float, default=1.0)
    a = ap.parse_args(argv)
    targets = DEFAULT_TARGETS
    if a.targets:
        with open(a.targets) as f:
            targets = json.load(f)
    if a.status:
        return cmd_status()
    if a.check_bridge:
        return cmd_check_bridge(a.bridge_url)
    if a.test:
        return cmd_test(a.bridge_script, a.test_interval)
    if a.mute:
        return cmd_mute(a.mute, a.reason)
    if a.unmute:
        return cmd_unmute()
    return cmd_once(targets)


if __name__ == "__main__":
    sys.exit(main())
