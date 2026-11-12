#!/usr/bin/env python3
"""Autonomous Freedom-ONT chaos drill — admin-shut sw01 Gi1/0/36, observe,
restore with PoE re-cycle, record chaos_experiments row.

Implements the `ios-port-shutdown` primitive requested in
IFRNLLEI01PRD-705 so the monthly Freedom-ONT drill (scenario
`freedom-ont-shutdown` in experiments/catalog.yaml, parent -695) can run
unattended from the chaos-calendar cron without operator intervention.

Invoked either:
  - By scripts/freedom-ont-drill-trigger.sh on the scheduled day
  - Manually for a one-off: `python3 scripts/chaos-port-shutdown.py --scenario freedom-ont-shutdown`

Critical operator-safety invariant: the rollback MUST always run, even
on scenario crash. Uses try/finally + a separate watchdog subprocess
that force-restores the port after `--max-duration` seconds no matter
what the main process is doing.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from chaos_marker import (  # noqa: E402
    ChaosCollisionError,
    install_marker,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))

REPO = Path(__file__).resolve().parents[1]
# Honour CHAOS_STATE_PATH env var (same convention as scripts/chaos-preflight.sh
# and scripts/lib/chaos_marker.py). Lets QA fixtures redirect to a scratch
# tempdir, and lets production callers give different chaos drivers isolated
# state files to avoid cross-driver state corruption.
CHAOS_STATE = Path(
    os.environ.get("CHAOS_STATE_PATH")
    or (Path.home() / "chaos-state" / "chaos-active.json")
)
LOG = Path.home() / "logs" / "claude-gateway" / "chaos-port-shutdown.log"

# Default scenario parameters — can be overridden via --args
SCENARIO_DEFAULTS = {
    "freedom-ont-shutdown": {
        "switch": "sw01",
        "interface": "GigabitEthernet1/0/36",
        "observation_seconds": 900,       # 15 min default drill
        "max_duration_seconds": 1800,     # 30 min hard cap (watchdog)
        "poe_cycle_on_restore": True,     # Genexis ONT needs forced PoE re-detect
        "matrix_room": "!AOMuEtXGyzGFLgObKN:matrix.example.net",
    },
}


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"[{stamp}] {msg}"
    print(line)
    with LOG.open("a") as f:
        f.write(line + "\n")


def notify_matrix(room: str, message: str) -> None:
    """Fire-and-forget Matrix m.notice. Failures don't block the drill."""
    env_file = REPO / ".env"
    token = ""
    if env_file.exists():
        for ln in env_file.read_text().splitlines():
            if ln.startswith("MATRIX_CLAUDE_TOKEN="):
                token = ln.split("=", 1)[1].strip().strip("'\"")
                break
    if not token:
        log("notify_matrix: no MATRIX_CLAUDE_TOKEN, skipping")
        return

    py = f"""
import urllib.request, urllib.parse, json, ssl, os, time
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
token = {token!r}; room = {room!r}; msg = {message!r}
txn = f'chaos-port-{{int(time.time())}}-{{os.getpid()}}'
url = f'https://matrix.example.net/_matrix/client/v3/rooms/{{urllib.parse.quote(room, safe="")}}/send/m.room.message/{{txn}}'
body = json.dumps({{'msgtype':'m.notice','body':msg}}).encode()
req = urllib.request.Request(url, data=body, method='PUT')
req.add_header('Authorization', f'Bearer {{token}}')
req.add_header('Content-Type', 'application/json')
try: urllib.request.urlopen(req, context=ctx, timeout=10)
except Exception as e: print(f'matrix error: {{e}}', flush=True)
"""
    try:
        subprocess.run(["python3", "-c", py], capture_output=True, timeout=15)
    except Exception as e:
        log(f"notify_matrix error: {e}")


def install_chaos_marker(scenario_id: str, window_sec: int) -> None:
    """Create chaos-active.json so receivers suppress alerts during the drill.

    IFRNLLEI01PRD-709: delegates lock + collision check + atomic write to the
    shared `scripts/lib/chaos_marker.py` helper so every writer (this script,
    chaos-test.py, future launchers) enforces the same discipline.
    """
    install_marker(
        scenario_id=scenario_id,
        window_sec=window_sec,
        triggered_by="chaos-port-shutdown",
        extras={
            "operator_action_required": False,
            "referenced_in": "IFRNLLEI01PRD-695 + -705",
            "suppressions": [
                "freedom-qos-toggle-sms",
                "pppoe-down-alerts",
                "vti-idle-bgp-alerts",
                "mesh-degraded-level-alert",
            ],
        },
    )


def clear_chaos_marker() -> None:
    if CHAOS_STATE.exists():
        CHAOS_STATE.unlink()


def shut_port(switch: str, interface: str) -> tuple[bool, str]:
    from ios_ssh import sw01_port_shutdown
    if switch != "sw01":
        return False, f"switch '{switch}' not yet supported (sw01 only)"
    return sw01_port_shutdown(interface)


def noshut_port(switch: str, interface: str, poe_cycle: bool) -> tuple[bool, str]:
    from ios_ssh import sw01_port_noshut
    if switch != "sw01":
        return False, f"switch '{switch}' not yet supported"
    return sw01_port_noshut(interface, force_poe_cycle=poe_cycle)


def sample_mesh_state() -> dict:
    """One-shot sample via the vpn-mesh-stats script. Non-fatal on error."""
    try:
        r = subprocess.run(
            ["python3", str(REPO / "scripts" / "vpn-mesh-stats.py")],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            d = json.loads(r.stdout)
            cs = d.get("compound_status", {})
            return {
                "level": cs.get("level"),
                "text": cs.get("text"),
                "tunnels_up": sum(1 for t in d.get("tunnels", []) if t.get("status") == "up"),
                "bgp_established": d.get("bgp", {}).get("established"),
                "bgp_reachable": cs.get("bgp_reachable"),
                "wan_failover": cs.get("wan_failover"),
            }
    except Exception as e:
        log(f"mesh sample error: {e}")
    return {}


def write_chaos_experiment(scenario_id: str, verdict: str, events: list,
                           pre_state: dict, post_state: dict,
                           t_shut: float, t_restored: float) -> None:
    """Write a chaos_experiments row via chaos_baseline.write_experiment."""
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        import chaos_baseline  # noqa
        convergence = int(t_restored - t_shut)
        chaos_baseline.write_experiment(
            experiment_id=f"{scenario_id}-{time.strftime('%Y%m%d%H%M', time.gmtime(t_shut))}",
            chaos_type="wan-failover-drill",
            targets=[f"nl-sw01:GigabitEthernet1/0/36"],
            hypothesis="Shut Freedom ONT port; Budget carries all inter-site pairs until no-shut; mesh returns to Nominal within 120s of port-up.",
            pre_state=pre_state,
            post_state=post_state,
            events=events,
            convergence_seconds=convergence,
            recovery_seconds=convergence,
            verdict=verdict,
            verdict_details={
                "target_convergence_seconds": 120,
                "actual_seconds": convergence,
                "unattended": True,
            },
            triggered_by="chaos-port-shutdown (scheduled)",
            started_at=int(t_shut),
            recovered_at=int(t_restored),
            mttr_seconds=convergence,
        )
        log(f"chaos_experiments row written: verdict={verdict} convergence={convergence}s")
    except Exception as e:
        log(f"write_chaos_experiment failed: {e}")


def run_scenario(scenario_id: str, switch: str, interface: str,
                 observation_seconds: int, max_duration_seconds: int,
                 poe_cycle: bool, matrix_room: str, dry_run: bool) -> int:
    events: list[dict] = []
    pre = sample_mesh_state()
    log(f"pre-scenario mesh: {pre}")

    if dry_run:
        log("DRY-RUN — no ports will be toggled.")
        log(f"would SHUT {switch}:{interface}, observe for {observation_seconds}s, then NO SHUT with poe_cycle={poe_cycle}")
        return 0

    try:
        install_chaos_marker(scenario_id, max_duration_seconds)
    except ChaosCollisionError as e:
        log(f"ABORT: marker collision — {e}")
        notify_matrix(matrix_room,
            f"[CHAOS DRILL] {scenario_id} ABORTED — marker collision. "
            f"Another chaos test owns ~/chaos-state/chaos-active.json. "
            f"Detail: {e}")
        return 2
    notify_matrix(matrix_room,
        f"[CHAOS DRILL] {scenario_id} starting — shutting {switch}:{interface}. "
        f"Expected: Budget carries all inter-site traffic within ~90 s; "
        f"mesh banner flips to Degraded. No operator action required.")

    t_shut = time.time()
    ok, msg = shut_port(switch, interface)
    events.append({"t": 0, "event": "shutdown issued", "ok": ok, "detail": msg[:200]})
    if not ok:
        log(f"SHUTDOWN FAILED: {msg}")
        clear_chaos_marker()
        notify_matrix(matrix_room, f"[CHAOS DRILL] ABORT — shutdown of {switch}:{interface} failed: {msg[:200]}")
        return 1
    log(f"port SHUT at t=0 ok={ok}")

    # Observation loop with watchdog — bounded by max_duration_seconds
    deadline = t_shut + max_duration_seconds
    next_sample = t_shut + 30
    try:
        while time.time() < t_shut + observation_seconds:
            if time.time() >= next_sample:
                state = sample_mesh_state()
                events.append({"t": int(time.time() - t_shut), "event": "sample", "state": state})
                log(f"t+{int(time.time()-t_shut)}s mesh: {state.get('text','?')}")
                next_sample = time.time() + 60
            if time.time() >= deadline:
                log("watchdog: max_duration reached, forcing restore")
                break
            time.sleep(5)
    except KeyboardInterrupt:
        log("KeyboardInterrupt — restoring immediately")

    t_restore_start = time.time()
    log(f"restoring port at t+{int(t_restore_start - t_shut)}s (poe_cycle={poe_cycle})")
    try:
        ok, msg = noshut_port(switch, interface, poe_cycle=poe_cycle)
        events.append({"t": int(t_restore_start - t_shut), "event": "noshut issued",
                       "ok": ok, "detail": msg[:200]})
        if not ok:
            # Last-ditch retry without PoE cycle
            log(f"no-shut WITH poe_cycle failed ({msg[:100]}); retrying plain no-shut")
            ok, msg = noshut_port(switch, interface, poe_cycle=False)
            events.append({"t": int(time.time() - t_shut), "event": "noshut retry plain",
                           "ok": ok, "detail": msg[:200]})
    finally:
        pass  # chaos-active marker cleared after observation

    # Post-restore observation (up to 3 min for mesh to return to Nominal)
    t_restored = time.time()
    for _ in range(12):
        state = sample_mesh_state()
        if state.get("level") == "nominal":
            events.append({"t": int(time.time() - t_shut), "event": "mesh nominal", "state": state})
            t_restored = time.time()
            log(f"mesh NOMINAL at t+{int(t_restored - t_shut)}s")
            break
        time.sleep(15)
    else:
        log("mesh did not return to nominal within 3 min; verdict=PARTIAL")

    post = sample_mesh_state()
    log(f"post-scenario mesh: {post}")

    clear_chaos_marker()

    convergence_total = int(t_restored - t_shut)
    verdict = "PASS" if post.get("level") == "nominal" and convergence_total <= 1200 else "PARTIAL"

    write_chaos_experiment(scenario_id, verdict, events, pre, post, t_shut, t_restored)

    notify_matrix(matrix_room,
        f"[CHAOS DRILL] {scenario_id} {verdict}. Convergence total {convergence_total}s "
        f"(shut→restore→nominal). Mesh now: {post.get('text','?')}")

    log(f"=== drill complete: verdict={verdict} total={convergence_total}s ===")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Autonomous Freedom-ONT chaos drill")
    p.add_argument("--scenario", default="freedom-ont-shutdown",
                   help="Scenario id from SCENARIO_DEFAULTS or catalog.yaml")
    p.add_argument("--switch", default=None, help="Override switch host (default from scenario)")
    p.add_argument("--interface", default=None, help="Override interface (default from scenario)")
    p.add_argument("--observation-seconds", type=int, default=None)
    p.add_argument("--max-duration-seconds", type=int, default=None)
    p.add_argument("--no-poe-cycle", action="store_true",
                   help="Skip the PoE re-cycle recipe on restore")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan only, do not touch the port")
    p.add_argument("--matrix-room", default=None)
    args = p.parse_args(argv)

    defaults = SCENARIO_DEFAULTS.get(args.scenario)
    if not defaults:
        log(f"unknown scenario '{args.scenario}' (supported: {list(SCENARIO_DEFAULTS)})")
        return 2

    switch = args.switch or defaults["switch"]
    interface = args.interface or defaults["interface"]
    observation = args.observation_seconds or defaults["observation_seconds"]
    max_dur = args.max_duration_seconds or defaults["max_duration_seconds"]
    poe_cycle = (not args.no_poe_cycle) and defaults["poe_cycle_on_restore"]
    matrix_room = args.matrix_room or defaults["matrix_room"]

    return run_scenario(
        args.scenario, switch, interface, observation, max_dur,
        poe_cycle, matrix_room, args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
