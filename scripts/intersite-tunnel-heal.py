#!/usr/bin/env python3
"""intersite-tunnel-heal.py — Layer-2 auto-heal for wedged NL<->GR IPsec legs.

IFRNLLEI01PRD-1833. The wedged-SA class partitioned the sites 5 times
(latest 2026-08-14); the light per-device healers (vti-freedom-recovery.sh /
vti-budget-recovery.sh, Layer 0) and the on-device rtr01 EEM applet
(Layer 1) fix the common child-SA-desync variant within minutes. THIS
script is the escalation layer: when an inter-site leg has been down for
>=2 consecutive bgp-mesh-watchdog runs (>=10 min — i.e. Layers 0/1 already
failed), it verifies the wedge signature and executes the FULL both-ends
runbook re-key exactly as documented in
infrastructure/nl/production/edge/CLAUDE.md § "Total NL<->GR partition":

  GR ASA  : vpn-sessiondb logoff tunnel-group <leg peer> noconfirm
            clear crypto ipsec sa peer <leg peer>        (via :2222 stone)
  NL side : nl-fw01 logoff+clear 203.0.113.X (freedom leg)
            nlrtr01 clear crypto session remote 203.0.113.X (budget leg)

All device access is netmiko (operator directive 2026-08-14; the GR hop
uses asa_ssh.ssh_gr_asa_exec which runs netmiko on the stepping stone).

Invocation:
  --from-watchdog   stdin = bgp-mesh-watchdog.sh's collected JSON (the hook
                    at the end of that script). The normal cron path.
  --check [--live]  evaluate + print the decision, never actuate.
  --heal LEG        gated heal (same gates as cron path, skips streak).
  --drill-force LEG manual drill: bypasses gates (NOT the GR-pingable
                    sanity), actuates, verifies, reports. LEG: freedom|budget|both.

Gates, in order (cron path): flock singleton -> down-streak >= 2 ->
maintenance/chaos -> mutation shadow + exemption sentinel
(~/gateway.mutations_intersite_allow, audited per actuation) -> arming
sentinel (~/gateway.intersite_autoheal_armed) -> exponential backoff /
3-strike escalate (platform-controller pattern) -> wedge signature
(GR public answers plain-internet ping AND decaps frozen or no SA data).

Kill switches: rm ~/gateway.intersite_autoheal_armed (this layer) or
rm ~/gateway.mutations_intersite_allow (whole lane while global shadow on).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
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
ARMED_SENTINEL = _GWHOME / "gateway.intersite_autoheal_armed"
EXEMPT_SENTINEL = _GWHOME / "gateway.mutations_intersite_allow"
MAINTENANCE = _GWHOME / "gateway.maintenance"
CHAOS_ACTIVE = _GWHOME / "chaos-state" / "chaos-active.json"

STATE_FILE = Path(os.environ.get(
    "INTERSITE_STATE_FILE", str(Path.home() / "gateway-state" / "intersite-heal.json")))
AUDIT_LOG = Path(os.environ.get(
    "INTERSITE_AUDIT_LOG", str(Path.home() / "logs" / "claude-gateway" / "intersite-heal.log")))
SHADOW_DIR = Path(os.environ.get(
    "MUTATION_SHADOW_LOG_DIR", str(_GWHOME / "logs" / "claude-gateway" / "mutation-shadow")))
PROM_DIR = Path(os.environ.get(
    "PROMETHEUS_TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector"))
PROM_FILE = PROM_DIR / "intersite_autoheal.prom"

BACKOFF_BASE = int(os.environ.get("INTERSITE_BACKOFF_BASE", "600"))
BACKOFF_MAX = int(os.environ.get("INTERSITE_BACKOFF_MAX", "3600"))
ESCALATE_AFTER = int(os.environ.get("INTERSITE_ESCALATE_AFTER", "3"))
MIN_DOWN_RUNS = int(os.environ.get("INTERSITE_MIN_DOWN_RUNS", "2"))
VERIFY_TRIES = int(os.environ.get("INTERSITE_VERIFY_TRIES", "3"))
VERIFY_WAIT = int(os.environ.get("INTERSITE_VERIFY_WAIT", "45"))
SAMPLE_GAP = int(os.environ.get("INTERSITE_SAMPLE_GAP", "20"))

GR_PUBLIC = "203.0.113.X"
NL_ASA_HOST = "10.0.181.X"
ASA_USER = "operator"

# leg -> topology facts. neighbor = the NL-side BGP series the watchdog +
# IntersiteBGPLegDown key on; gr_tg = the GR ASA tunnel-group for THIS leg
# (surgical: a single-leg heal never touches the healthy leg's tunnel-group).
LEGS = {
    "freedom": {"local_host": "nl-fw01", "neighbor": "10.255.200.X",
                "gr_tg": "203.0.113.X"},
    "budget": {"local_host": "nlrtr01", "neighbor": "10.255.200.X",
               "gr_tg": "203.0.113.X"},
}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [intersite-heal] {msg}"
    print(line, flush=True)
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _forbid_device_guard() -> None:
    """QA hermeticity: any live device call under INTERSITE_FORBID_DEVICE is a bug."""
    if os.environ.get("INTERSITE_FORBID_DEVICE"):
        raise RuntimeError("device call reached under INTERSITE_FORBID_DEVICE (QA)")


# ── State (platform-controller-style JSON under gateway-state) ──────────────

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=1))
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        log(f"WARN: state save failed: {e}")


def _leg_state(state: dict, leg: str) -> dict:
    return state.setdefault("legs", {}).setdefault(
        leg, {"down_streak": 0, "heals": [], "last_result": "", "last_heal_ts": 0})


# ── Pure decision helpers (unit-tested by scripts/qa/suites/test-intersite-autoheal.sh) ──

def legs_down_from_watchdog(data: dict) -> dict:
    """Map watchdog JSON -> {leg: True(down)|False(up)|None(unknown/unreachable)}."""
    out = {}
    for leg, cfg in LEGS.items():
        dev = (data.get("devices") or {}).get(cfg["local_host"]) or {}
        if dev.get("unreachable"):
            out[leg] = None
            continue
        sess = (dev.get("sessions") or {}).get(cfg["neighbor"])
        if sess is None:
            out[leg] = None
        else:
            out[leg] = (int(sess.get("established", 0)) != 1)
    return out


def parse_decaps(text: str) -> list:
    """Extract '#pkts decaps: N' counter values from ASA/IOS 'show crypto ipsec sa' output."""
    vals = []
    for line in (text or "").splitlines():
        if "decaps" in line:
            for tok in line.replace(",", " ").split():
                if tok.isdigit():
                    vals.append(int(tok))
                    break
    return vals


def wedge_from_samples(sample1: str, sample2: str) -> tuple:
    """(is_wedge, reason). Frozen decaps or no SA data = wedge; rising = healthy path."""
    v1, v2 = parse_decaps(sample1), parse_decaps(sample2)
    if not v1 and not v2:
        return True, "no_sa_data"          # 08-08 variant: IKE READY, zero child SAs
    if sum(v2) > sum(v1):
        return False, "decaps_moving"
    if sum(v2) < sum(v1):
        return False, "counters_reset"     # fresh SAs mid-diagnosis = something already healed it
    return True, f"decaps_frozen_at_{sum(v2)}"


def heal_decision(state: dict, leg: str, now: float) -> str:
    """'heal' | 'backoff' | 'escalate' — exponential backoff + 3-strike (platform-controller)."""
    ls = _leg_state(state, leg)
    hist = [t for t in ls.get("heals", []) if t > now - 3 * BACKOFF_MAX]
    ls["heals"] = hist
    n = len(hist)
    if n >= ESCALATE_AFTER:
        return "escalate"
    if n == 0:
        return "heal"
    cooldown = min(BACKOFF_BASE * 2 ** (n - 1), BACKOFF_MAX)
    return "heal" if now - max(hist) >= cooldown else "backoff"


# ── Device access (netmiko everywhere; GR via the stone lib) ────────────────

def _asa_password() -> str:
    from asa_ssh import get_asa_password
    return get_asa_password()


def _nl_asa_connect():
    _forbid_device_guard()
    from netmiko import ConnectHandler
    pw = _asa_password()
    if not pw:
        raise RuntimeError("CISCO_ASA_PASSWORD not available")
    return ConnectHandler(device_type="cisco_asa", host=NL_ASA_HOST,
                          username=ASA_USER, password=pw, secret=pw,
                          conn_timeout=15, read_timeout_override=30)


def nl_asa_show(cmd: str) -> str:
    try:
        with _nl_asa_connect() as c:
            return c.send_command(cmd, read_timeout=20)
    except Exception as e:
        return f"ERROR: {e}"


def nl_asa_exec(cmds: list) -> tuple:
    try:
        with _nl_asa_connect() as c:
            out = []
            for cmd in cmds:
                out.append(c.send_command_timing(cmd, read_timeout=30))
            return True, "\n".join(out)
    except Exception as e:
        return False, f"ERROR: {e}"


def rtr01_show(cmd: str) -> str:
    _forbid_device_guard()
    from ios_ssh import ssh_rtr01_command
    return ssh_rtr01_command([cmd])


def rtr01_exec(cmds: list) -> tuple:
    _forbid_device_guard()
    from ios_ssh import ssh_rtr01_exec
    return ssh_rtr01_exec(cmds)


def gr_asa_exec(cmds: list) -> tuple:
    _forbid_device_guard()
    from asa_ssh import ssh_gr_asa_exec
    return ssh_gr_asa_exec(cmds)


def gr_public_pingable() -> bool:
    _forbid_device_guard()
    r = subprocess.run(["ping", "-c", "3", "-W", "2", GR_PUBLIC],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def leg_counter_sample(leg: str) -> str:
    cmd = f"show crypto ipsec sa peer {GR_PUBLIC} | include pkts decaps"
    return nl_asa_show(cmd) if leg == "freedom" else rtr01_show(cmd)


def leg_bgp_established(leg: str) -> bool:
    cfg = LEGS[leg]
    if leg == "freedom":
        out = nl_asa_show(f"show bgp summary | include {cfg['neighbor']}")
    else:
        out = rtr01_show(f"show ip bgp summary | include {cfg['neighbor']} ")
    for line in (out or "").splitlines():
        if cfg["neighbor"] in line:
            toks = line.split()
            return bool(toks) and toks[-1].isdigit()
    return False


# ── Reporting ────────────────────────────────────────────────────────────────

def matrix_notice(body: str) -> None:
    if os.environ.get("INTERSITE_NO_MATRIX"):
        return
    tok = os.environ.get("MATRIX_CLAUDE_TOKEN", "")
    if not tok:
        try:
            tok = (Path.home() / ".matrix-claude-token").read_text().strip()
        except Exception:
            return
    room = os.environ.get("MATRIX_ROOM_INFRA",
                          "!AOMuEtXGyzGFLgObKN:matrix.example.net")
    hs = os.environ.get("MATRIX_HOMESERVER", "https://matrix.example.net")
    url = (f"{hs}/_matrix/client/v3/rooms/{urllib.parse.quote(room)}"
           f"/send/m.room.message/intersite-heal-{int(time.time() * 1000)}")
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
        with open(SHADOW_DIR / "intersite-exempt-allows.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} lane=intersite {msg}\n")
    except Exception:
        pass


def write_prom(state: dict) -> None:
    try:
        counters = state.setdefault("counters", {})
        attempts = counters.setdefault("attempts", {})
        success = counters.setdefault("success", {})
        lines = [
            "# HELP intersite_autoheal_armed 1 if the arming sentinel is present",
            "# TYPE intersite_autoheal_armed gauge",
            f"intersite_autoheal_armed {1 if ARMED_SENTINEL.exists() else 0}",
            "# HELP intersite_autoheal_attempts_total Heal attempts per leg",
            "# TYPE intersite_autoheal_attempts_total counter",
            "# HELP intersite_autoheal_success_total Verified successful heals per leg",
            "# TYPE intersite_autoheal_success_total counter",
            "# HELP intersite_autoheal_last_result 1 if the last heal on this leg verified OK, 0 if it failed",
            "# TYPE intersite_autoheal_last_result gauge",
        ]
        for leg in LEGS:
            lines.append(f'intersite_autoheal_attempts_total{{leg="{leg}"}} {int(attempts.get(leg, 0))}')
            lines.append(f'intersite_autoheal_success_total{{leg="{leg}"}} {int(success.get(leg, 0))}')
            lr = _leg_state(state, leg).get("last_result")
            if lr in ("success", "failed"):
                lines.append(f'intersite_autoheal_last_result{{leg="{leg}"}} {1 if lr == "success" else 0}')
        lines += [
            "# HELP intersite_autoheal_escalations_total Escalations (heal cap reached or site-unreachable)",
            "# TYPE intersite_autoheal_escalations_total counter",
            f"intersite_autoheal_escalations_total {int(counters.get('escalations', 0))}",
            "# HELP intersite_autoheal_last_run_timestamp Unix ts of the last consumer run",
            "# TYPE intersite_autoheal_last_run_timestamp gauge",
            f"intersite_autoheal_last_run_timestamp {int(time.time())}",
        ]
        PROM_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PROM_FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text("\n".join(lines) + "\n")
        os.replace(tmp, PROM_FILE)
    except Exception as e:
        log(f"WARN: prom write failed: {e}")


def escalate(state: dict, leg: str, reason: str) -> None:
    state.setdefault("counters", {})["escalations"] = \
        int(state.get("counters", {}).get("escalations", 0)) + 1
    log(f"ESCALATE leg={leg}: {reason} — human needed")
    matrix_notice(f"[intersite-heal] ESCALATE {leg} leg: {reason}. "
                  f"Auto-heal will not retry (see IFRNLLEI01PRD-1833 runbook).")


# ── Actuation ────────────────────────────────────────────────────────────────

def actuate(leg: str) -> tuple:
    """Full both-ends runbook re-key for one leg (or both). Returns (ok, detail)."""
    detail = []
    legs = ["freedom", "budget"] if leg == "both" else [leg]
    gr_cmds = []
    for l in legs:
        tg = LEGS[l]["gr_tg"]
        gr_cmds += [f"vpn-sessiondb logoff tunnel-group {tg} noconfirm",
                    f"clear crypto ipsec sa peer {tg}"]
    ok_gr, out_gr = gr_asa_exec(gr_cmds)
    detail.append(f"gr-fw01 ok={ok_gr}: {str(out_gr)[:300]}")
    if "freedom" in legs:
        ok_nl, out_nl = nl_asa_exec(
            [f"vpn-sessiondb logoff tunnel-group {GR_PUBLIC} noconfirm",
             f"clear crypto ipsec sa peer {GR_PUBLIC}"])
        detail.append(f"nl-fw01 ok={ok_nl}: {str(out_nl)[:300]}")
    if "budget" in legs:
        ok_rt, out_rt = rtr01_exec([f"clear crypto session remote {GR_PUBLIC}"])
        detail.append(f"nlrtr01 ok={ok_rt}: {str(out_rt)[:300]}")
    # GR-side failure alone is not fatal — the one-sided NL clear still forces a
    # fresh IKE_SA_INIT + INITIAL_CONTACT which flushes GR's stale SAs.
    return True, " | ".join(detail)


def heal_leg(state: dict, leg: str, drill: bool = False) -> bool:
    """Actuate + verify one leg (or both). Updates state/counters. Returns verified-ok."""
    counters = state.setdefault("counters", {})
    for l in (["freedom", "budget"] if leg == "both" else [leg]):
        counters.setdefault("attempts", {})[l] = int(counters.get("attempts", {}).get(l, 0)) + 1
        ls = _leg_state(state, l)
        ls["heals"] = ls.get("heals", []) + [time.time()]
        ls["last_heal_ts"] = time.time()
    tag = "DRILL" if drill else "HEAL"
    log(f"{tag} leg={leg}: executing full both-ends re-key (netmiko)")
    ok, detail = actuate(leg)
    log(f"{tag} leg={leg}: actuation done: {detail}")
    if mutation_mode and mutation_mode.is_shadow():
        exempt_audit(f"action=re-key leg={leg} drill={drill} (allowed by exemption sentinel)")

    verified = False
    for i in range(VERIFY_TRIES):
        time.sleep(VERIFY_WAIT)
        checks = [leg_bgp_established(l) for l in (["freedom", "budget"] if leg == "both" else [leg])]
        if all(checks):
            verified = True
            break
        log(f"{tag} leg={leg}: verify try {i + 1}/{VERIFY_TRIES}: {checks}")

    for l in (["freedom", "budget"] if leg == "both" else [leg]):
        ls = _leg_state(state, l)
        ls["last_result"] = "success" if verified else "failed"
        if verified:
            counters.setdefault("success", {})[l] = int(counters.get("success", {}).get(l, 0)) + 1
    if verified:
        log(f"{tag} leg={leg}: VERIFIED — BGP Established")
        matrix_notice(f"[intersite-heal] {'Drill: ' if drill else ''}re-keyed the {leg} "
                      f"NL<->GR leg (wedged-SA runbook, netmiko) — BGP re-Established, verified.")
    else:
        log(f"{tag} leg={leg}: NOT VERIFIED after {VERIFY_TRIES} tries")
        matrix_notice(f"[intersite-heal] {'Drill: ' if drill else ''}re-key of the {leg} leg "
                      f"did NOT verify — leg still down. Human needed (IFRNLLEI01PRD-1833).")
    return verified


# ── Cycle logic ──────────────────────────────────────────────────────────────

def run_cycle(data: dict, check_only: bool = False) -> dict:
    """Consume one watchdog snapshot. Returns the decision map (for --check)."""
    decisions = {}
    state = load_state()
    now = time.time()
    down_map = legs_down_from_watchdog(data)

    for leg, down in down_map.items():
        ls = _leg_state(state, leg)
        if down is None:
            decisions[leg] = "unknown (device unreachable — not judging)"
            continue
        if not down:
            if ls.get("down_streak"):
                log(f"leg={leg}: recovered (streak {ls['down_streak']} -> 0)")
            ls["down_streak"] = 0
            decisions[leg] = "healthy"
            continue

        ls["down_streak"] = int(ls.get("down_streak", 0)) + 1
        if ls["down_streak"] < MIN_DOWN_RUNS:
            decisions[leg] = f"down_streak={ls['down_streak']} < {MIN_DOWN_RUNS} (L0/L1 window)"
            log(f"leg={leg}: {decisions[leg]}")
            continue

        # Gates
        if MAINTENANCE.exists() or CHAOS_ACTIVE.exists():
            decisions[leg] = "suppressed (maintenance/chaos)"
            log(f"leg={leg}: {decisions[leg]}")
            continue
        shadow = bool(mutation_mode and mutation_mode.is_shadow())
        if shadow and not EXEMPT_SENTINEL.exists():
            decisions[leg] = "shadow (no intersite exemption sentinel) — logged not run"
            log(f"leg={leg}: {decisions[leg]}")
            if mutation_mode:
                mutation_mode.log_wouldve(
                    "intersite-heal",
                    rationale=f"would re-key wedged {leg} leg (streak {ls['down_streak']})",
                    leg=leg)
            continue
        if not ARMED_SENTINEL.exists():
            decisions[leg] = "analysis-only (arming sentinel absent)"
            log(f"leg={leg}: {decisions[leg]}")
            continue
        decision = heal_decision(state, leg, now)
        if decision == "backoff":
            decisions[leg] = "backoff (recent heal, cooling down)"
            log(f"leg={leg}: {decisions[leg]}")
            continue
        if decision == "escalate":
            decisions[leg] = "escalate (3+ heals without lasting recovery)"
            if not check_only:
                escalate(state, leg, "3+ heals in window without lasting recovery")
            continue

        if check_only:
            decisions[leg] = "WOULD HEAL (gates passed; signature not evaluated in --check)"
            continue

        # Wedge signature
        if not gr_public_pingable():
            decisions[leg] = "site-unreachable (GR public dead — outage, not a wedge)"
            escalate(state, leg, "GR public IP unreachable over plain internet")
            continue
        s1 = leg_counter_sample(leg)
        time.sleep(SAMPLE_GAP)
        s2 = leg_counter_sample(leg)
        is_wedge, reason = wedge_from_samples(s1, s2)
        log(f"leg={leg}: signature={reason}")
        if not is_wedge:
            decisions[leg] = f"not-wedged ({reason}) — no action"
            continue

        decisions[leg] = "healed" if heal_leg(state, leg) else "heal-failed"

    if not check_only:
        save_state(state)
        write_prom(state)
    return decisions


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--from-watchdog", action="store_true")
    m.add_argument("--check", action="store_true")
    m.add_argument("--heal", choices=["freedom", "budget", "both"])
    m.add_argument("--drill-force", choices=["freedom", "budget", "both"])
    p.add_argument("--live", action="store_true",
                   help="with --check: probe the two NL devices instead of reading stdin")
    args = p.parse_args()

    # Singleton: overlapping watchdog runs must not double-heal.
    lock_path = STATE_FILE.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = open(lock_path, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("another intersite-heal instance holds the lock — exiting")
        return 0

    if args.drill_force:
        log(f"DRILL --drill-force {args.drill_force} (manual; gates bypassed)")
        if not gr_public_pingable():
            log("DRILL abort: GR public IP not pingable — refusing to drill into an outage")
            return 1
        state = load_state()
        ok = heal_leg(state, args.drill_force, drill=True)
        save_state(state)
        write_prom(state)
        return 0 if ok else 1

    if (args.check or args.heal) and args.live:
        data = {"devices": {}}
        for leg, cfg in LEGS.items():
            up = leg_bgp_established(leg)
            data["devices"][cfg["local_host"]] = {
                "unreachable": False,
                "sessions": {cfg["neighbor"]: {"state": "established" if up else "probe",
                                               "established": 1 if up else 0}}}
    else:
        raw = sys.stdin.read()
        try:
            data = json.loads(raw)
        except Exception as e:
            log(f"ERROR: bad watchdog JSON on stdin: {e} (len={len(raw)})")
            return 0 if args.from_watchdog else 1

    if args.heal:
        # gated single-leg heal: mark the leg down at threshold and run the cycle
        state = load_state()
        _leg_state(state, args.heal)["down_streak"] = MIN_DOWN_RUNS - 1
        save_state(state)
        for leg_cfg in ([LEGS[args.heal]] if args.heal != "both" else LEGS.values()):
            dev = data.setdefault("devices", {}).setdefault(
                leg_cfg["local_host"], {"unreachable": False, "sessions": {}})
            dev["sessions"][leg_cfg["neighbor"]] = {"state": "forced", "established": 0}

    decisions = run_cycle(data, check_only=args.check)
    print(json.dumps({"decisions": decisions}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
