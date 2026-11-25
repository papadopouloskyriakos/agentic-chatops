#!/usr/bin/env python3
"""freedom-ont-heal.py — capped auto-heal for a wedged Freedom ONT on nl-sw01 Gi1/0/36.

IFRNLLEI01PRD-2992 (NL house power-loss postmortem, MR !284). After the 2026-11-06 power
loss the Genexis XGS-PON ONT (PoE-powered from nl-sw01 Gi1/0/36, "Connection to
Freedom Internet") sat `notconnect` with PoE on (15.4 W) for 8 h: powered but not
training. The proven fix (2026-11-07 11:59 NL) was a PoE cycle + link bounce:

    interface GigabitEthernet1/0/36
     power inline never            -> wait 15 s ->
     power inline auto / shutdown / no shutdown

Link up in 10 s, PPPoE + nl-fw01 Track 1 Up ~98 s later. This script detects that
exact signature and applies that exact recipe, capped. All Cisco access is netmiko
(ios_ssh.sw01_poe_cycle / ssh_sw01_command, asa_ssh.ssh_nl_asa_netmiko_command).

Signature ("wedged"): Gi1/0/36 status `notconnect` AND `show power inline` Admin=auto,
Oper=on AND the description still names Freedom AND nl-fw01 Track 1 confirmed Down
(Track Up while the port is down = wrong port -> never act; Track unreadable ->
'unconfirmed': reported via the wedged metric/FreedomOntWedged, never acted on).

Gates, in order (Cronicle */2): flock singleton -> signature on >= MIN_DOWN_RUNS runs
spanning >= MIN_DOWN_SECONDS (default 2 runs / 240 s), and >= MIN_DOWN_RUNS of them with
every gate open (no instant act when a gate lifts) -> a real maintenance window / chaos
marker (the master-switch marker {"master_switch": true} does NOT block, 2026-11-07) -> MUTATIONS=OFF shadow unless the lane sentinel
~/gateway.mutations_freedom_ont_allow is present (every admitted actuation audited) ->
arming sentinel ~/gateway.freedom_ont_autoheal_armed -> cap: max MAX_ATTEMPTS (3) per
24 h with exponential backoff (10 min, 20 min) -> escalate once per episode (Matrix
m.notice + escalations counter -> FreedomOntAutohealEscalated).

Observation and metrics (freedom_ont_autoheal.prom) run on EVERY run, gated or not, so
FreedomOntWedged fires even while the heal is disarmed.

Invocation:
  (no flag)            one cycle against the live devices. The Cronicle path.
  --dry-run            probe + decide, never actuate / save state / write metrics / post.
  --snapshot-file F    use a parsed snapshot (JSON) instead of probing (QA, fixtures).
  --drill-force        SUPERVISED live test: PoE-cycle the port now, bypassing streak/gates/
                       cap (never the port-identity check), verify, report. Interactive TTY
                       only, so no scheduler or agent can run it. Freedom drops ~2 min.

Kill switches: rm ~/gateway.freedom_ont_autoheal_armed (this heal) or
rm ~/gateway.mutations_freedom_ont_allow (the lane, while global shadow is on).
Runbook: docs/runbooks/freedom-ont-autoheal.md.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

_LIB = Path(__file__).resolve().parent / "lib"
sys.path.insert(0, str(_LIB))

try:
    import mutation_mode  # noqa: E402 — MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:
    mutation_mode = None

# ── Paths / config (env-overridable; GATEWAY_HOME keeps QA hermetic) ────────
_GWHOME = Path(os.environ.get("GATEWAY_HOME", str(Path.home())))
LANE = "freedom_ont"
ARMED_SENTINEL = _GWHOME / "gateway.freedom_ont_autoheal_armed"
EXEMPT_SENTINEL = _GWHOME / f"gateway.mutations_{LANE}_allow"
MAINTENANCE = _GWHOME / "gateway.maintenance"
CHAOS_ACTIVE = _GWHOME / "chaos-state" / "chaos-active.json"
ENV_FILE = Path(os.environ.get("FREEDOM_ONT_ENV_FILE",
                               str(Path(__file__).resolve().parent.parent / ".env")))

STATE_FILE = Path(os.environ.get(
    "FREEDOM_ONT_STATE_FILE", str(Path.home() / "gateway-state" / "freedom-ont-heal.json")))
AUDIT_LOG = Path(os.environ.get(
    "FREEDOM_ONT_AUDIT_LOG", str(Path.home() / "logs" / "claude-gateway" / "freedom-ont-heal.log")))
SHADOW_DIR = Path(os.environ.get(
    "MUTATION_SHADOW_LOG_DIR", str(_GWHOME / "logs" / "claude-gateway" / "mutation-shadow")))
PROM_DIR = Path(os.environ.get(
    "PROMETHEUS_TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector"))
PROM_FILE = PROM_DIR / "freedom_ont_autoheal.prom"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


MIN_DOWN_RUNS = _int_env("FREEDOM_ONT_MIN_DOWN_RUNS", 2)
MIN_DOWN_SECONDS = _int_env("FREEDOM_ONT_MIN_DOWN_SECONDS", 240)
MAX_ATTEMPTS = _int_env("FREEDOM_ONT_MAX_ATTEMPTS", 3)
WINDOW = _int_env("FREEDOM_ONT_WINDOW_SECONDS", 86400)
BACKOFF_BASE = _int_env("FREEDOM_ONT_BACKOFF_BASE", 600)
BACKOFF_MAX = _int_env("FREEDOM_ONT_BACKOFF_MAX", 7200)
POE_OFF_SECONDS = _int_env("FREEDOM_ONT_POE_OFF_SECONDS", 15)
LINK_WAIT = _int_env("FREEDOM_ONT_LINK_WAIT", 90)
LINK_POLL = _int_env("FREEDOM_ONT_LINK_POLL", 10)
TRACK_WAIT = _int_env("FREEDOM_ONT_TRACK_WAIT", 240)
TRACK_POLL = _int_env("FREEDOM_ONT_TRACK_POLL", 20)

SWITCH = "nl-sw01"
FIREWALL = "nl-fw01"
IFACE = "GigabitEthernet1/0/36"
IFACE_SHORT = "Gi1/0/36"
IDENTITY_TOKEN = "freedom"          # the port description must still name Freedom
PORT_STATUSES = ("connected", "notconnect", "disabled", "err-disabled", "inactive",
                 "suspended", "monitoring", "sfpAbsent", "xcvrAbsent", "noOperMem")
POE_ADMIN = ("auto", "static", "off", "never")
POE_OPER = ("on", "off", "faulty", "power-deny", "err-disable")
MATRIX_ROOM_DEFAULT = "!AOMuEtXGyzGFLgObKN:matrix.example.net"   # #infra-nl-prod


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [freedom-ont-heal] {msg}"
    print(line, flush=True)
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _forbid_device_guard() -> None:
    """QA hermeticity: any live device call under FREEDOM_ONT_FORBID_DEVICE is a bug."""
    if os.environ.get("FREEDOM_ONT_FORBID_DEVICE"):
        raise RuntimeError("device call reached under FREEDOM_ONT_FORBID_DEVICE (QA)")


def _env(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    try:
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return ""


# ── State ────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    """A MISSING file is a fresh start. A file that exists but cannot be read/parsed is marked
    _unreadable: the cycle then refuses to actuate (it would otherwise reset the 24 h cap)."""
    try:
        s = json.loads(STATE_FILE.read_text())
        if not isinstance(s, dict):
            raise ValueError("state is not a JSON object")
    except FileNotFoundError:
        s = {}
    except Exception as e:
        log(f"WARN: state file {STATE_FILE} unreadable ({e}) — actuation refused until fixed")
        s = {"_unreadable": str(e)[:200]}
    s.setdefault("down_streak", 0)
    s.setdefault("first_seen", 0)
    s.setdefault("attempts", [])
    s.setdefault("counters", {"attempts": 0, "success": 0, "escalations": 0})
    return s


def save_state(state: dict) -> None:
    if state.get("_unreadable"):
        return          # never overwrite a state file we could not read (keeps the evidence + cap)
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, indent=1))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"WARN: state save failed: {e}")


# ── Pure parsers (unit-tested by scripts/qa/suites/test-freedom-ont-heal.sh) ──

def _iface_lines(text: str) -> list:
    return [ln.split() for ln in (text or "").splitlines()
            if ln.split() and ln.split()[0] in (IFACE_SHORT, IFACE)]


def parse_port_status(text: str) -> str | None:
    """`show interfaces Gi1/0/36 status` -> connected|notconnect|disabled|... (None = not found)."""
    for toks in _iface_lines(text):
        for t in toks[1:]:
            if t in PORT_STATUSES:
                return t
    return None


def parse_poe(text: str) -> dict:
    """`show power inline Gi1/0/36` -> {admin, oper, watts} (values None when not found)."""
    for toks in _iface_lines(text):
        if len(toks) >= 4 and toks[1] in POE_ADMIN and toks[2] in POE_OPER:
            try:
                watts = float(toks[3])
            except ValueError:
                watts = None
            return {"admin": toks[1], "oper": toks[2], "watts": watts}
    return {"admin": None, "oper": None, "watts": None}


def parse_description(text: str) -> str | None:
    """`show interfaces Gi1/0/36 description` -> the description text (None = not found)."""
    for toks in _iface_lines(text):
        if len(toks) >= 3 and toks[1] in ("up", "down", "admin"):
            rest = toks[3:] if toks[1] != "admin" else toks[4:]
            return " ".join(rest)
    return None


def parse_switch(text: str) -> dict:
    poe = parse_poe(text)
    return {"ok": True, "status": parse_port_status(text), "poe_admin": poe["admin"],
            "poe_oper": poe["oper"], "poe_watts": poe["watts"],
            "description": parse_description(text)}


def parse_track(text: str) -> bool | None:
    """`show track 1` -> True (Up) / False (Down) / None (not found)."""
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln.startswith("Reachability is"):
            return ln.split()[-1].lower() == "up"
        if ln.startswith("State is"):              # boolean/list track object
            return ln.split()[-1].lower() == "up"
    return None


def parse_asa_ip(text: str) -> str | None:
    """`show ip address outside_freedom` -> the CURRENT address, or None if unassigned/absent."""
    current = False
    for ln in (text or "").splitlines():
        if ln.strip().startswith("Current IP Address"):
            current = True
            continue
        if current and "outside_freedom" in ln:
            toks = ln.split()
            idx = toks.index("outside_freedom") if "outside_freedom" in toks else -1
            ip = toks[idx + 1] if 0 <= idx < len(toks) - 1 else ""
            return ip if ip.count(".") == 3 and ip[0].isdigit() else None
    return None


def classify(snap: dict) -> tuple:
    """(state, reason). state: healthy | wedged | unconfirmed | unknown | contradiction |
    admin-down | poe-not-on | identity-mismatch | other. Only 'wedged' can lead to an actuation;
    'unconfirmed' (switch signature holds, Track 1 unreadable) is reported but holds the streak."""
    sw = snap.get("switch") or {}
    asa = snap.get("asa") or {}
    if not sw.get("ok") or not sw.get("status"):
        return "unknown", f"{SWITCH} probe failed or {IFACE_SHORT} not found"
    st = sw["status"]
    if st == "connected":
        return "healthy", "link connected"
    if st == "disabled":
        return "admin-down", "port administratively shut (drill or manual) — not this heal's class"
    if st != "notconnect":
        return "other", f"port status {st} — not the proven notconnect class"
    if sw.get("poe_admin") != "auto" or sw.get("poe_oper") != "on":
        return "poe-not-on", (f"notconnect but PoE admin={sw.get('poe_admin')} "
                              f"oper={sw.get('poe_oper')} — not the proven powered-but-dark class")
    if IDENTITY_TOKEN not in (sw.get("description") or "").lower():
        return "identity-mismatch", f"{IFACE_SHORT} description no longer names Freedom — never act"
    if asa.get("ok") and asa.get("track_up") is True:
        return "contradiction", f"{FIREWALL} Track 1 Up while {IFACE_SHORT} is notconnect — wrong port?"
    if not asa.get("ok") or asa.get("track_up") is None:
        return "unconfirmed", (f"notconnect + PoE on ({sw.get('poe_watts')} W) but {FIREWALL} Track 1 "
                               f"not confirmed Down (probe failed) — detected, never acted on")
    return "wedged", f"notconnect + PoE on ({sw.get('poe_watts')} W); {FIREWALL} Track 1 Down"


def attempts_in_window(state: dict, now: float) -> list:
    hist = [t for t in state.get("attempts", []) if t > now - WINDOW]
    state["attempts"] = hist
    return hist


def heal_decision(state: dict, now: float) -> str:
    """'heal' | 'backoff' | 'escalate' — max MAX_ATTEMPTS per WINDOW, exponential backoff."""
    hist = attempts_in_window(state, now)
    n = len(hist)
    if n >= MAX_ATTEMPTS:
        return "escalate"
    if n == 0:
        return "heal"
    cooldown = min(BACKOFF_BASE * 2 ** (n - 1), BACKOFF_MAX)
    return "heal" if now - max(hist) >= cooldown else "backoff"


def failure_open(state: dict) -> bool:
    """True while the last REAL attempt did not restore Freedom and it has not been seen
    healthy (link connected + Track 1 Up) since."""
    return (state.get("last_result") in ("failed", "link_only")
            and float(state.get("last_service_ok_ts", 0) or 0)
            < float(state.get("last_attempt_ts", 0) or 0))


def is_shadow() -> bool:
    """MUTATIONS=OFF shadow. If mutation_mode failed to import, decide from the same env var +
    sentinel it uses — never fail open into 'not shadow'."""
    if mutation_mode is not None:
        try:
            return bool(mutation_mode.is_shadow())
        except Exception:
            pass
    env = os.environ.get("MUTATIONS_OFF")
    if env is not None:
        return env.strip().lower() in ("1", "true", "yes", "on")
    return (_GWHOME / "gateway.mutations_off").exists()


def maintenance_kind() -> str:
    """'none' | 'master_switch' | 'maintenance'.

    ~/gateway.maintenance is written by two things: a real maintenance window, and the
    gateway master switch ({"master_switch": true}, on since 2026-08-26 when TG became
    primary). Only a real window blocks this heal (operator decision 2026-11-07,
    IFRNLLEI01PRD-2992): the hung-ONT class is a physical edge fault no other actor heals,
    and the lane/arming/cap guards still bound it. Fail closed: a file that is not a JSON
    object with master_switch == true counts as a real window."""
    if not MAINTENANCE.exists():
        return "none"
    try:
        d = json.loads(MAINTENANCE.read_text())
    except Exception:
        return "maintenance"
    return "master_switch" if isinstance(d, dict) and d.get("master_switch") is True else "maintenance"


def gate_status() -> dict:
    shadow = is_shadow()
    mk = maintenance_kind()
    g = {"maintenance": mk == "maintenance", "master_switch": mk == "master_switch",
         "chaos": CHAOS_ACTIVE.exists(),
         "mutation_shadow": shadow, "lane_exempt": EXEMPT_SENTINEL.exists(),
         "armed": ARMED_SENTINEL.exists()}
    g["blocking"] = [name for name, hit in (
        ("maintenance", g["maintenance"]), ("chaos", g["chaos"]),
        ("mutation_shadow", shadow and not g["lane_exempt"]),
        ("unarmed", not g["armed"])) if hit]
    g["suppressed"] = bool(g["blocking"])
    return g


# ── Device access (netmiko only) ─────────────────────────────────────────────

def probe_switch() -> dict:
    _forbid_device_guard()
    from ios_ssh import ssh_sw01_command
    ok, out = ssh_sw01_command([f"show interfaces {IFACE} status",
                                f"show power inline {IFACE}",
                                f"show interfaces {IFACE} description"])
    if not ok:
        return {"ok": False, "error": str(out)[:200]}
    return parse_switch(out)


def probe_asa() -> dict:
    _forbid_device_guard()
    from asa_ssh import ssh_nl_asa_netmiko_command
    out = ssh_nl_asa_netmiko_command(["show track 1", "show ip address outside_freedom"])
    if out.startswith("ERROR:"):
        return {"ok": False, "error": out[:200]}
    return {"ok": True, "track_up": parse_track(out), "ip": parse_asa_ip(out)}


def probe() -> dict:
    return {"ts": time.time(), "switch": probe_switch(), "asa": probe_asa()}


def poe_cycle() -> tuple:
    _forbid_device_guard()
    from ios_ssh import sw01_poe_cycle
    return sw01_poe_cycle(IFACE, off_seconds=POE_OFF_SECONDS)


def verify() -> dict:
    """Poll for link (switch) then Track 1 (ASA). Returns {link, track, poe_admin}."""
    res = {"link": False, "track": False, "poe_admin": None}
    deadline = time.time() + LINK_WAIT
    while time.time() < deadline:
        time.sleep(LINK_POLL)
        sw = probe_switch()
        res["poe_admin"] = sw.get("poe_admin")
        if sw.get("ok") and sw.get("status") == "connected":
            res["link"] = True
            break
    if not res["link"]:
        return res
    deadline = time.time() + TRACK_WAIT
    while time.time() < deadline:
        time.sleep(TRACK_POLL)
        if probe_asa().get("track_up") is True:
            res["track"] = True
            break
    return res


# ── Reporting ────────────────────────────────────────────────────────────────

def matrix_notice(body: str) -> None:
    if os.environ.get("FREEDOM_ONT_NO_MATRIX"):
        log(f"(matrix suppressed by FREEDOM_ONT_NO_MATRIX) {body}")
        return
    tok = _env("MATRIX_CLAUDE_TOKEN")
    if not tok:
        try:
            tok = (Path.home() / ".matrix-claude-token").read_text().strip()
        except Exception:
            log("WARN: no Matrix token — notice not posted")
            return
    room = os.environ.get("MATRIX_ROOM_INFRA", MATRIX_ROOM_DEFAULT)
    hs = os.environ.get("MATRIX_HOMESERVER", "https://matrix.example.net")
    url = (f"{hs}/_matrix/client/v3/rooms/{urllib.parse.quote(room)}"
           f"/send/m.room.message/freedom-ont-heal-{int(time.time() * 1000)}")
    req = urllib.request.Request(
        url, data=json.dumps({"msgtype": "m.notice", "body": body}).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        method="PUT")
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f"WARN: matrix post failed: {e}")


def exempt_audit(msg: str) -> None:
    try:
        SHADOW_DIR.mkdir(parents=True, exist_ok=True)
        with open(SHADOW_DIR / f"{LANE}-exempt-allows.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} lane={LANE} "
                    f"source={Path(__file__).name} {msg}\n")
    except Exception:
        pass


def escalate(state: dict, reason: str) -> None:
    c = state.setdefault("counters", {})
    c["escalations"] = int(c.get("escalations", 0)) + 1
    state["escalated_for"] = state.get("first_seen", 0)
    log(f"ESCALATE: {reason} — human needed")
    matrix_notice(f"[freedom-ont-heal] ESCALATE: {reason}. {SWITCH} {IFACE_SHORT} (Freedom ONT). "
                  f"The auto-heal will not retry — runbook docs/runbooks/freedom-ont-autoheal.md "
                  f"(IFRNLLEI01PRD-2992).")


def write_prom(state: dict, snap: dict, st: str, now: float) -> None:
    try:
        g = gate_status()
        sw = snap.get("switch") or {}
        asa = snap.get("asa") or {}
        c = state.get("counters", {})
        p = "freedom_ont_autoheal"
        L = [f"# HELP {p}_armed 1 if ~/gateway.freedom_ont_autoheal_armed is present",
             f"# TYPE {p}_armed gauge", f"{p}_armed {1 if g['armed'] else 0}",
             f"# HELP {p}_lane_exempt 1 if ~/gateway.mutations_{LANE}_allow is present",
             f"# TYPE {p}_lane_exempt gauge", f"{p}_lane_exempt {1 if g['lane_exempt'] else 0}",
             f"# HELP {p}_gate_active 1 if this gate would block a heal right now",
             f"# TYPE {p}_gate_active gauge"]
        for gate in ("maintenance", "chaos", "mutation_shadow", "unarmed"):
            L.append(f'{p}_gate_active{{gate="{gate}"}} {1 if gate in g["blocking"] else 0}')
        L += [f"# HELP {p}_master_switch_exempt 1 if the gateway master switch is on and this heal runs past it",
              f"# TYPE {p}_master_switch_exempt gauge", f"{p}_master_switch_exempt {1 if g.get('master_switch') else 0}"]
        L += [f"# HELP {p}_suppressed 1 if any gate blocks a heal right now (detection still runs)",
              f"# TYPE {p}_suppressed gauge", f"{p}_suppressed {1 if g['suppressed'] else 0}",
              f"# HELP {p}_probe_ok 1 if the device answered this run",
              f"# TYPE {p}_probe_ok gauge",
              f'{p}_probe_ok{{device="{SWITCH}"}} {1 if sw.get("ok") else 0}',
              f'{p}_probe_ok{{device="{FIREWALL}"}} {1 if asa.get("ok") else 0}',
              f"# HELP {p}_state_info Classification of this run (value always 1)",
              f"# TYPE {p}_state_info gauge", f'{p}_state_info{{state="{st}"}} 1']
        if sw.get("ok") and sw.get("status"):
            L += [f"# HELP {p}_link_down 1 if {IFACE_SHORT} is not connected (absent = unknown)",
                  f"# TYPE {p}_link_down gauge",
                  f"{p}_link_down {0 if sw['status'] == 'connected' else 1}",
                  f"# HELP {p}_wedged 1 if the powered-but-dark signature holds (notconnect + PoE on, Freedom port, Track 1 not Up; incl. Track 1 unreadable)",
                  f"# TYPE {p}_wedged gauge", f"{p}_wedged {1 if st in ('wedged', 'unconfirmed') else 0}"]
        if sw.get("poe_oper"):
            L += [f"# HELP {p}_poe_oper_on 1 if PoE Oper=on on {IFACE_SHORT}",
                  f"# TYPE {p}_poe_oper_on gauge", f"{p}_poe_oper_on {1 if sw['poe_oper'] == 'on' else 0}"]
        if sw.get("poe_watts") is not None:
            L += [f"# HELP {p}_poe_watts PoE draw on {IFACE_SHORT}",
                  f"# TYPE {p}_poe_watts gauge", f"{p}_poe_watts {sw['poe_watts']}"]
        if asa.get("ok") and asa.get("track_up") is not None:
            L += [f"# HELP {p}_asa_track_up 1 if {FIREWALL} Track 1 (Freedom SLA) is Up",
                  f"# TYPE {p}_asa_track_up gauge", f"{p}_asa_track_up {1 if asa['track_up'] else 0}"]
        streak = int(state.get("down_streak", 0))
        L += [f"# HELP {p}_down_streak Consecutive runs the wedged signature has held",
              f"# TYPE {p}_down_streak gauge", f"{p}_down_streak {streak}",
              f"# HELP {p}_down_seconds Seconds the wedged signature has held (0 if not wedged)",
              f"# TYPE {p}_down_seconds gauge",
              f"{p}_down_seconds {int(now - state['first_seen']) if streak and state.get('first_seen') else 0}",
              f"# HELP {p}_attempts_total Real heal attempts (PoE cycles started)",
              f"# TYPE {p}_attempts_total counter", f"{p}_attempts_total {int(c.get('attempts', 0))}",
              f"# HELP {p}_success_total Attempts that restored link + Track 1",
              f"# TYPE {p}_success_total counter", f"{p}_success_total {int(c.get('success', 0))}",
              f"# HELP {p}_drills_total Supervised --drill-force PoE cycles (outside the 24 h cap)",
              f"# TYPE {p}_drills_total counter", f"{p}_drills_total {int(c.get('drills', 0))}",
              f"# HELP {p}_escalations_total Escalations (cap reached or PoE restore failed)",
              f"# TYPE {p}_escalations_total counter", f"{p}_escalations_total {int(c.get('escalations', 0))}",
              f"# HELP {p}_attempts_24h Attempts inside the rolling cap window",
              f"# TYPE {p}_attempts_24h gauge",
              f"{p}_attempts_24h {len([t for t in state.get('attempts', []) if t > now - WINDOW])}"]
        lr = state.get("last_result")
        if lr in ("success", "failed", "link_only"):        # set only by a real attempt
            L += [f"# HELP {p}_last_result 1 if the last real attempt restored link + Track 1, else 0",
                  f"# TYPE {p}_last_result gauge", f"{p}_last_result {1 if lr == 'success' else 0}",
                  f"# HELP {p}_last_link_restored 1 if the last real attempt brought the link up",
                  f"# TYPE {p}_last_link_restored gauge",
                  f"{p}_last_link_restored {1 if lr in ('success', 'link_only') else 0}",
                  f"# HELP {p}_last_attempt_timestamp Unix ts of the last real attempt",
                  f"# TYPE {p}_last_attempt_timestamp gauge",
                  f"{p}_last_attempt_timestamp {int(float(state.get('last_attempt_ts', 0) or 0))}"]
        L += [f"# HELP {p}_failure_open 1 while the last real attempt did not restore Freedom and it has not been seen healthy since",
              f"# TYPE {p}_failure_open gauge", f"{p}_failure_open {1 if failure_open(state) else 0}",
              f"# HELP {p}_last_run_timestamp Unix ts of the last run",
              f"# TYPE {p}_last_run_timestamp gauge", f"{p}_last_run_timestamp {int(time.time())}"]
        PROM_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PROM_FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text("\n".join(L) + "\n")
        os.replace(tmp, PROM_FILE)
    except Exception as e:
        log(f"WARN: prom write failed: {e}")


# ── Actuation ────────────────────────────────────────────────────────────────

def heal(state: dict, now: float, drill: bool = False) -> str:
    """PoE cycle + verify. Returns success | link_only | failed. Updates state/counters.
    A drill is a real actuation (sets last_result) but does not consume the 24 h cap."""
    c = state.setdefault("counters", {})
    if drill:
        c["drills"] = int(c.get("drills", 0)) + 1
    else:
        c["attempts"] = int(c.get("attempts", 0)) + 1
        state["attempts"] = state.get("attempts", []) + [now]
    state["last_attempt_ts"] = now
    n = len(attempts_in_window(state, now))
    tag = "DRILL" if drill else "HEAL"
    log(f"{tag} attempt {n}/{MAX_ATTEMPTS} (24 h): PoE cycle {IFACE_SHORT} on {SWITCH} "
        f"(never -> {POE_OFF_SECONDS}s -> auto + shut/no shut, netmiko)")
    save_state(state)   # persist the attempt BEFORE actuating: a crash later can never bypass the cap/backoff
    if is_shadow():
        exempt_audit(f"action=poe-cycle iface={IFACE} attempt={n} (allowed by lane sentinel)")
    ok, detail = poe_cycle()
    log(f"HEAL actuation ok={ok}: {detail}")
    if not ok and str(detail).startswith("POE-LEFT-OFF"):
        state["last_result"] = "failed"
        escalate(state, f"PoE restore FAILED — {IFACE_SHORT} may be left with PoE OFF (ONT unpowered). "
                        f"Run on {SWITCH}: interface {IFACE} / power inline auto")
        return "failed"
    res = {"link": False, "track": False, "poe_admin": None}
    if ok:
        try:
            res = verify()
        except Exception as e:                   # verification must never abort the bookkeeping
            log(f"WARN: verify raised {e!r} — treating as not verified")
    if ok and not res.get("link") and res.get("poe_admin") != "auto":
        state["last_result"] = "failed"
        escalate(state, f"after the cycle {IFACE_SHORT} is still dark and PoE admin reads "
                        f"{res.get('poe_admin')!r} (expected 'auto') — the port may be unpowered. "
                        f"Run on {SWITCH}: interface {IFACE} / power inline auto")
        return "failed"
    result = "success" if res["link"] and res["track"] else ("link_only" if res["link"] else "failed")
    state["last_result"] = result
    if result == "success":
        c["success"] = int(c.get("success", 0)) + 1
        state["last_service_ok_ts"] = time.time()
        log("HEAL VERIFIED: link connected + Track 1 Up")
        matrix_notice(f"[freedom-ont-heal] Freedom ONT was powered but dark ({IFACE_SHORT} notconnect, PoE on); "
                      f"PoE-cycled it on {SWITCH} — link + {FIREWALL} Track 1 back Up, verified "
                      f"(attempt {n}/{MAX_ATTEMPTS} in 24 h).")
    elif result == "link_only":
        log(f"HEAL PARTIAL: link connected but Track 1 not Up within {TRACK_WAIT}s")
        matrix_notice(f"[freedom-ont-heal] PoE-cycled the Freedom ONT ({IFACE_SHORT}): link is back but "
                      f"{FIREWALL} Track 1 / PPPoE did not come Up within {TRACK_WAIT}s — check PPPoE/BRAS "
                      f"(attempt {n}/{MAX_ATTEMPTS}).")
    else:
        log(f"HEAL NOT VERIFIED: link still down after {LINK_WAIT}s (actuation ok={ok})")
        matrix_notice(f"[freedom-ont-heal] PoE cycle of the Freedom ONT ({IFACE_SHORT}) did NOT bring the "
                      f"link back (attempt {n}/{MAX_ATTEMPTS} in 24 h; actuation ok={ok}). Will back off "
                      f"and retry within the cap.")
    return result


# ── Cycle logic ──────────────────────────────────────────────────────────────

def run_cycle(snap: dict, now: float | None = None, dry_run: bool = False) -> dict:
    """One cycle over a probe snapshot. Returns {state, reason, decision}."""
    now = time.time() if now is None else now
    state = load_state()
    st, reason = classify(snap)
    asa = snap.get("asa") or {}

    if st == "wedged":
        if int(state.get("down_streak", 0)) == 0:
            state["first_seen"] = now
        state["down_streak"] = int(state.get("down_streak", 0)) + 1
    elif st not in ("unknown", "unconfirmed"):   # a failed probe holds the streak: never judge on it
        if state.get("down_streak"):
            log(f"signature cleared ({st}: {reason}); streak {state['down_streak']} -> 0")
        state["down_streak"] = 0
        state["first_seen"] = 0
        state["open_runs"] = 0
        if st == "healthy":
            state["last_healthy_ts"] = now
            if asa.get("ok") and asa.get("track_up") is True:
                if failure_open(state):
                    log("Freedom healthy again (link + Track 1) after a failed attempt — failure closed")
                state["last_service_ok_ts"] = now

    decision = "no action"
    if st == "wedged":
        if not state.get("first_seen"):          # never act on a missing clock: restart it
            state["first_seen"] = now
        g = gate_status()
        # open_runs = consecutive wedged runs with every gate open. After any gate lifts
        # (maintenance ends, lane/arming sentinel appears) the heal needs MIN_DOWN_RUNS fresh
        # un-gated observations, never an instant act on a streak built up while gated.
        state["open_runs"] = 0 if g["suppressed"] else int(state.get("open_runs", 0)) + 1
        streak, held = state["down_streak"], now - float(state["first_seen"])
        if streak < MIN_DOWN_RUNS or held < MIN_DOWN_SECONDS:
            decision = (f"wait (streak {streak}/{MIN_DOWN_RUNS}, held {int(held)}s/{MIN_DOWN_SECONDS}s)")
        else:
            if state.get("_unreadable"):
                decision = "refused (state file unreadable — cap/backoff unknown)"
            elif g["maintenance"] or g["chaos"]:
                decision = "suppressed (maintenance window/chaos)"
            elif g["mutation_shadow"] and not g["lane_exempt"]:
                decision = f"shadow (no ~/gateway.mutations_{LANE}_allow) — logged not run"
                if mutation_mode and state.get("shadow_logged_for") != state.get("first_seen") and not dry_run:
                    mutation_mode.log_wouldve("freedom-ont-poe-cycle",
                                              rationale=f"would PoE-cycle {IFACE} ({reason})", iface=IFACE)
                    state["shadow_logged_for"] = state.get("first_seen")
            elif not g["armed"]:
                decision = "analysis-only (arming sentinel absent)"
            elif state["open_runs"] < MIN_DOWN_RUNS:
                decision = f"wait (gates just opened: {state['open_runs']}/{MIN_DOWN_RUNS} un-gated runs)"
            else:
                hd = heal_decision(state, now)
                if hd == "backoff":
                    decision = "backoff (recent attempt, cooling down)"
                elif hd == "escalate":
                    if state.get("escalated_for") == state.get("first_seen"):
                        decision = "escalated (already notified this episode)"
                    else:
                        decision = f"escalate ({MAX_ATTEMPTS} attempts in 24 h, still wedged)"
                        if not dry_run:
                            escalate(state, f"{MAX_ATTEMPTS} PoE cycles in 24 h and the ONT is still "
                                            f"powered but dark ({reason})")
                elif dry_run:
                    decision = "WOULD HEAL (dry-run: no actuation)"
                else:
                    decision = f"healed: {heal(state, now)}"
    elif st in ("unknown", "unconfirmed"):
        decision = f"no action ({st}: probe failed — not judging)"
    else:
        decision = f"no action ({st})"

    if st != "healthy":          # healthy runs stay quiet; the metrics carry their heartbeat
        log(f"state={st} ({reason}) -> {decision}")
    if not dry_run:
        save_state(state)
        write_prom(state, snap, st, now)
    return {"state": st, "reason": reason, "decision": decision,
            "down_streak": state.get("down_streak", 0), "gates": gate_status(),
            "attempts_24h": len([t for t in state.get("attempts", []) if t > now - WINDOW])}


def drill_force() -> int:
    if not sys.stdin.isatty() or os.environ.get("FREEDOM_ONT_DRILL_REFUSE"):
        log("DRILL refused: --drill-force must be run interactively by a human (no TTY)")
        return 2
    snap = probe()
    sw = snap.get("switch") or {}
    if not sw.get("ok") or sw.get("status") not in ("connected", "notconnect"):
        log(f"DRILL abort: {SWITCH} {IFACE_SHORT} not in a drillable state: {sw}")
        return 1
    if IDENTITY_TOKEN not in (sw.get("description") or "").lower():
        log(f"DRILL abort: {IFACE_SHORT} description no longer names Freedom: {sw.get('description')}")
        return 1
    log(f"DRILL --drill-force (supervised; streak/gates/cap bypassed). Before: {sw.get('status')}, "
        f"PoE {sw.get('poe_oper')} {sw.get('poe_watts')} W, Track 1 {(snap.get('asa') or {}).get('track_up')}")
    state = load_state()
    now = time.time()
    t0 = time.time()
    result = heal(state, now, drill=True)
    save_state(state)
    post = probe()
    write_prom(state, post, classify(post)[0], time.time())
    log(f"DRILL result={result} in {int(time.time() - t0)}s")
    print(json.dumps({"drill": True, "result": result, "seconds": int(time.time() - t0)}, indent=1))
    return 0 if result == "success" else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true",
                   help="probe + decide; never actuate, save state, write metrics or post")
    p.add_argument("--snapshot-file", help="parsed snapshot JSON instead of live probes (QA)")
    p.add_argument("--drill-force", action="store_true",
                   help="SUPERVISED live test: PoE-cycle now (interactive TTY only)")
    args = p.parse_args()
    if args.drill_force and (args.dry_run or args.snapshot_file):
        p.error("--drill-force probes and acts on the live port; it takes no other flag")

    lock_path = STATE_FILE.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another freedom-ont-heal instance holds the lock — exiting")
        return 3 if args.drill_force else 0

    if args.drill_force:
        return drill_force()

    if args.snapshot_file:
        try:
            snap = json.loads(Path(args.snapshot_file).read_text())
        except Exception as e:
            log(f"ERROR: bad snapshot file: {e}")
            return 1
    else:
        snap = probe()
    out = run_cycle(snap, dry_run=args.dry_run)
    out["host"] = socket.gethostname()
    out["dry_run"] = args.dry_run
    out["snapshot"] = snap
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
