#!/usr/bin/env python3
"""GR InAlan primary-WAN / inter-site-mesh isolation detector + out-of-band alerter.

WHY THIS EXISTS
---------------
On 2026-06-15 22:58 UTC the GR site's InAlan primary WAN went down for ~2h. The GR
ASA (gr-fw01) stayed up the entire time and kept the site on its LTE backup, but
the site-to-site IPsec/VTI mesh (every tunnel anchored to the InAlan public IP
203.0.113.X) dropped -- so from NL the *whole GR site* looked "down / unreachable",
and the 06-16 triage wrongly concluded it needed physical access with "no path in".
It actually self-recovered. Root-cause writeup:
  memory/session_thermal_and_gr_unreachable_20260616.md

The LTE backup cannot carry the mesh: LTE is CGNAT, so no inbound ports / no stable
public endpoint for the static IPsec peers. That gap is structural and accepted. What
we CAN do is detect the isolation correctly and tell the operator the truth, *during*
the outage -- which normal monitoring can't, because the telemetry path (the mesh) is
itself down.

HOW
---
Runs GR-SIDE on grsyslogng01 (has the ASA+switch syslog locally, and keeps
outbound internet via LTE during an InAlan outage). Primary signal is a functional
probe, not log-scraping (track-state lines are sparse):

    mesh reachable            -> ok        (normal)
    mesh DOWN, internet UP     -> isolated  (InAlan WAN down, GR alive on LTE, mesh down)
    mesh DOWN, internet DOWN   -> dark      (GR genuinely down, or this host's uplink dead)

"mesh reachable" = any NL-inside host (reachable ONLY across the VPN mesh) answers.
"internet" = any public anchor answers (works on LTE through CGNAT).

On an ok->isolated transition (after a short confirm window to ignore rekey blips) it
sends an SMS via the Twilio REST API outbound over LTE, attributing the cause from the
local ASA/switch logs (gi7 uplink flaps, ASA track-1 SLA state, outside_inalan DHCP
re-lease). Recovery sends a clear-down SMS with the outage duration. Re-notifies hourly
while isolated.

DEPLOY
------
  /usr/local/bin/gr-inalan-wan-monitor.py   (on grsyslogng01)
  cron: */2 * * * *  /usr/local/bin/gr-inalan-wan-monitor.py
  creds: /etc/gr-inalan-wan-monitor.env  (TWILIO_* keys, root 600 -- NOT in git)
  state: /var/lib/gr-inalan-wan-monitor/state.json
Canonical version-controlled copy: claude-gateway repo scripts/gr-inalan-wan-monitor.py

USAGE
-----
  gr-inalan-wan-monitor.py            # cron mode: classify + alert on transition
  gr-inalan-wan-monitor.py --status   # print classification + signals, never send
  gr-inalan-wan-monitor.py --dry-run  # classify + show the SMS it *would* send
  gr-inalan-wan-monitor.py --test-sms # send one labelled validation SMS and exit
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --- config (overridable via env) ------------------------------------------------
ENV_FILE = os.environ.get("GR_WAN_ENV", "/etc/gr-inalan-wan-monitor.env")
STATE_DIR = os.environ.get("GR_WAN_STATE_DIR", "/var/lib/gr-inalan-wan-monitor")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.environ.get("GR_WAN_LOG", os.path.join(STATE_DIR, "monitor.log"))
SYSLOG_BASE = os.environ.get("GR_SYSLOG_BASE", "/mnt/logs/syslog-ng")

# NL-inside anchors reachable ONLY across the VPN mesh (unreachable => mesh down).
# Spread across distinct NL devices so one host being down can't fake an isolation.
MESH_ANCHORS = os.environ.get(
    "GR_MESH_ANCHORS", "10.0.181.X,10.0.X.X,10.0.181.X"
).split(",")
# Public anchors (answer over LTE through CGNAT). internet up => alerting path works.
INET_ANCHORS = os.environ.get("GR_INET_ANCHORS", "1.1.1.1,8.8.8.8").split(",")

CONFIRM_S = int(os.environ.get("GR_WAN_CONFIRM_S", "180"))     # ride out rekey blips
RENOTIFY_S = int(os.environ.get("GR_WAN_RENOTIFY_S", "3600"))  # remind hourly while down
FLAP_WINDOW_MIN = int(os.environ.get("GR_WAN_FLAP_WINDOW_MIN", "15"))
ASA_HOST = os.environ.get("GR_ASA_HOST", "gr-fw01")
SW_HOST = os.environ.get("GR_SW_HOST", "gr-sw01")
WAN_UPLINK_PORT = os.environ.get("GR_WAN_UPLINK_PORT", "gi7")
INALAN_PUBLIC_IP = os.environ.get("GR_INALAN_PUBLIC_IP", "203.0.113.X")


# --- small helpers ---------------------------------------------------------------
def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}"
    sys.stderr.write(line + "\n")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def load_env(path: str) -> dict:
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def ping(host: str, timeout_s: int = 2) -> bool:
    try:
        return subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_s), host],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_s + 2,
        ).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def any_up(hosts: list[str]) -> tuple[bool, list[str]]:
    """True if any host answers ICMP; also return the list that answered."""
    up = [h for h in (x.strip() for x in hosts if x.strip()) if ping(h)]
    return (len(up) > 0, up)


def send_sms(cfg: dict, body: str) -> tuple[bool, str]:
    acct = cfg.get("TWILIO_ACCOUNT_SID", "")
    key_sid = cfg.get("TWILIO_API_KEY_SID", "")
    key_secret = cfg.get("TWILIO_API_KEY_SECRET", "")
    frm = cfg.get("TWILIO_FROM_NUMBER", "")
    to = cfg.get("TWILIO_TO_NUMBER", "")
    if not (acct and key_sid and key_secret and frm and to):
        return False, "twilio creds missing"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{acct}/Messages.json"
    data = urllib.parse.urlencode({"From": frm, "To": to, "Body": body[:1500]}).encode()
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, url, key_sid, key_secret)
    opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(mgr))
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with opener.open(req, timeout=10) as resp:
            return resp.status < 300, f"http {resp.status}"
    except Exception as e:  # noqa: BLE001 - best-effort OOB path
        return False, f"err {e}"


# --- log-signal attribution (best-effort; the probe is the trigger) --------------
def _today_logs(host: str) -> list[str]:
    now = datetime.now(timezone.utc)
    d = f"{SYSLOG_BASE}/{host}/{now:%Y}/{now:%m}"
    base = f"{d}/{host}-{now:%Y-%m-%d}.log"
    return [p for p in (base, base + ".1") if os.path.exists(p)]


def _tail_bytes(path: str, nbytes: int) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            start = max(0, fh.tell() - nbytes)
            fh.seek(start)
            return fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _within_window(line: str, minutes: int) -> bool:
    # syslog 'Mon DD HH:MM:SS ...' (no year, UTC). Compare to now within `minutes`.
    try:
        ts = " ".join(line.split()[:3])
        now = datetime.now(timezone.utc)
        dt = datetime.strptime(ts, "%b %d %H:%M:%S").replace(
            year=now.year, tzinfo=timezone.utc
        )
        delta = (now - dt).total_seconds()
        if delta < -3600:  # parsed slightly in the future across a day boundary
            dt = dt.replace(year=now.year - 1)
            delta = (now - dt).total_seconds()
        return 0 <= delta <= minutes * 60
    except (ValueError, IndexError):
        return False


def cause_signals() -> dict:
    """Recent InAlan-WAN evidence from local syslog: uplink flaps, track-1, DHCP."""
    sig = {"gi7_flaps": 0, "gi7_last": "", "track1": "", "track1_last": "",
           "inalan_dhcp_relelease": "", "lte_recent": ""}
    # switch log is tiny (link events only) -> read fully
    for p in _today_logs(SW_HOST):
        for line in _tail_bytes(p, 1_000_000):
            if f"%LINK-W-Down:  {WAN_UPLINK_PORT}" in line or \
               (f" {WAN_UPLINK_PORT}" in line and "Down" in line and "LINK" in line):
                if _within_window(line, FLAP_WINDOW_MIN):
                    sig["gi7_flaps"] += 1
                    sig["gi7_last"] = " ".join(line.split()[:3])
    # ASA log is huge -> tail last 1MB and pick the rare WAN-state lines
    for p in _today_logs(ASA_HOST):
        for line in _tail_bytes(p, 1_000_000):
            if "%TRACK-6-STATE" in line and "sla 1" in line:
                # e.g. "...%TRACK-6-STATE: 1 ip sla 1 reachability Down -> Up"
                if "-> Up" in line:
                    sig["track1"] = "up"
                elif "-> Down" in line:
                    sig["track1"] = "down"
                sig["track1_last"] = " ".join(line.split()[:3])
            elif "604101" in line and "outside_inalan" in line and "DHCP client" in line:
                if _within_window(line, 60):
                    sig["inalan_dhcp_relelease"] = " ".join(line.split()[:3])
            elif "%CELLWAN-2-BEARER_UP" in line or \
                    ("Cellular0" in line and "changed state to up" in line):
                if _within_window(line, 60):
                    sig["lte_recent"] = " ".join(line.split()[:3])
    return sig


def cause_summary(sig: dict) -> str:
    bits = []
    if sig["gi7_flaps"]:
        bits.append(f"{WAN_UPLINK_PORT} uplink flapped {sig['gi7_flaps']}x/{FLAP_WINDOW_MIN}m"
                    + (f" (last {sig['gi7_last']})" if sig["gi7_last"] else ""))
    if sig["track1"]:
        bits.append(f"ASA track-1={sig['track1']}"
                    + (f"@{sig['track1_last']}" if sig["track1_last"] else ""))
    if sig["inalan_dhcp_relelease"]:
        bits.append(f"outside_inalan DHCP re-lease @{sig['inalan_dhcp_relelease']}")
    if sig["lte_recent"]:
        bits.append(f"LTE bearer up @{sig['lte_recent']}")
    return "; ".join(bits) if bits else "no InAlan-WAN log signals in window (cause unconfirmed)"


# --- state ----------------------------------------------------------------------
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"state": "ok", "since": time.time(), "isolation_began": None,
                "alert_active": False, "last_alert": 0.0}


def save_state(st: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        log(f"state save failed: {e}")


def fmt_dur(secs: float) -> str:
    secs = int(max(0, secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return (f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s")


# --- main -----------------------------------------------------------------------
def classify() -> tuple[str, dict]:
    mesh_up, mesh_ans = any_up(MESH_ANCHORS)
    inet_up, inet_ans = any_up(INET_ANCHORS)
    if mesh_up:
        state = "ok"
    elif inet_up:
        state = "isolated"
    else:
        state = "dark"
    return state, {"mesh_up": mesh_up, "mesh_ans": mesh_ans,
                   "inet_up": inet_up, "inet_ans": inet_ans}


def run(cfg: dict, dry_run: bool) -> int:
    state, probe = classify()
    st = load_state()
    now = time.time()
    prev = st.get("state", "ok")
    sent = []

    def maybe_sms(body: str, tag: str) -> None:
        nonlocal sent
        if dry_run:
            log(f"[DRY-RUN] would SMS ({tag}): {body}")
            sent.append(tag + ":dry")
            return
        ok, detail = send_sms(cfg, body)
        log(f"SMS ({tag}) -> {ok} {detail}")
        sent.append(f"{tag}:{ok}")

    if state == "ok":
        if st.get("alert_active"):
            began = st.get("isolation_began") or st.get("since") or now
            body = (f"GR mesh RESTORED {datetime.now(timezone.utc):%H:%M}Z. "
                    f"InAlan WAN back, inter-site tunnels re-established "
                    f"(was isolated {fmt_dur(now - began)}). "
                    f"NL<->GR reachable to {','.join(probe['mesh_ans']) or 'NL'}.")
            maybe_sms(body, "recovery")
        st = {"state": "ok", "since": now if prev != "ok" else st.get("since", now),
              "isolation_began": None, "alert_active": False, "last_alert": 0.0}
    else:  # isolated or dark -> mesh is down
        if prev == "ok" or not st.get("isolation_began"):
            st["isolation_began"] = now
        st["state"] = state
        st["since"] = now if prev != state else st.get("since", now)
        began = st["isolation_began"]
        confirmed = (now - began) >= CONFIRM_S
        if confirmed and not st.get("alert_active"):
            sig = cause_signals()
            inet_note = ("internet UP via LTE" if state == "isolated"
                         else "internet ALSO down (GR may be hard-down)")
            body = (f"GR ISOLATED from inter-site mesh since "
                    f"{datetime.fromtimestamp(began, timezone.utc):%H:%M}Z. "
                    f"gr-fw01 {inet_note}; NL unreachable over VPN. "
                    f"Likely InAlan primary-WAN outage -> {cause_summary(sig)}. "
                    f"GR services run on LTE; only the IPsec mesh (anchored to "
                    f"{INALAN_PUBLIC_IP}) is down. No remote-in path (PiKVM bricked). "
                    f"Auto-clears when InAlan returns.")
            maybe_sms(body, "isolation")
            st["alert_active"] = True
            st["last_alert"] = now
        elif st.get("alert_active") and (now - st.get("last_alert", 0)) >= RENOTIFY_S:
            body = (f"GR STILL isolated ({fmt_dur(now - began)}). "
                    f"InAlan WAN still down; GR on LTE. mesh anchors "
                    f"{','.join(MESH_ANCHORS)} all unreachable.")
            maybe_sms(body, "renotify")
            st["last_alert"] = now

    save_state(st)
    log(f"state={state} mesh_up={probe['mesh_up']}({','.join(probe['mesh_ans']) or '-'}) "
        f"inet_up={probe['inet_up']} prev={prev} alert_active={st.get('alert_active')} "
        f"sms={sent or '-'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", action="store_true", help="print classification, never send")
    ap.add_argument("--dry-run", action="store_true", help="classify + show would-be SMS")
    ap.add_argument("--test-sms", action="store_true", help="send one labelled test SMS, exit")
    args = ap.parse_args()
    cfg = load_env(ENV_FILE)

    if args.test_sms:
        ok, detail = send_sms(
            cfg, "GR InAlan WAN monitor: validation SMS (OOB-over-LTE path works). "
                 "You will only get real ones on an actual InAlan outage. -gateway")
        print(f"test-sms sent={ok} {detail}")
        return 0 if ok else 1

    if args.status:
        state, probe = classify()
        sig = cause_signals()
        print(json.dumps({"state": state, **probe, "cause": cause_summary(sig),
                          "signals": sig}, indent=2))
        return 0

    return run(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
