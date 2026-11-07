#!/usr/bin/env python3
"""
mutation-mode.py — operator control for global MUTATIONS=OFF (shadow) mode (IFRNLLEI01PRD-1824).

  mutation-mode.py status [--json] [--emit-metrics]
  mutation-mode.py off  [--reason "..."] [--operator who]   # MUTATIONS=OFF: shadow / log-only
  mutation-mode.py on   [--reason "..."] [--operator who]   # MUTATIONS=ON:  normal / actuates

MUTATIONS=OFF (shadow): the agentic system runs fully (triage, reasoning, session dispatch) but the
mutation-shadow-gate PreToolUse hook hard-blocks every actuation by a dispatched session, and the
cron actuators + autonomy gate log-instead-of-act. Reads, Matrix posts, YouTrack comments, and the
system's own gateway.db bookkeeping stay allowed. Everything is logged to
~/logs/claude-gateway/mutation-shadow/.

MUTATIONS=ON (normal): removes the sentinel; the system actuates as usual.

The single source of truth is the sentinel file ~/gateway.mutations_off (present = shadow).
Toggling is instant; every transition is appended to the mode log + the master-switch-style prom.
"""
import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import mutation_mode  # noqa: E402

HOME = Path(os.environ.get("GATEWAY_HOME", str(Path.home())))
SENTINEL = HOME / "gateway.mutations_off"
MODE_LOG = Path(os.environ.get("MUTATION_MODE_LOG",
                               str(HOME / "logs" / "claude-gateway" / "mutation-mode.log")))
PROM = os.environ.get("MUTATION_MODE_PROM",
                      "/var/lib/node_exporter/textfile_collector/mutation_mode.prom")


def _log_transition(action, operator, reason):
    MODE_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": int(time.time()), "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "host": socket.gethostname(), "action": action, "operator": operator, "reason": reason}
    with open(MODE_LOG, "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def _count_today():
    d = mutation_mode._LOG_DIR / f"shadow-{time.strftime('%Y-%m-%d', time.gmtime())}.jsonl"
    try:
        return sum(1 for _ in open(d))
    except OSError:
        return 0


def write_prom():
    shadow = mutation_mode.is_shadow()
    now = int(time.time())
    lines = [
        "# HELP gateway_mutations_shadow_active 1 = MUTATIONS=OFF shadow/log-only mode active, 0 = normal (actuating).",
        "# TYPE gateway_mutations_shadow_active gauge",
        f"gateway_mutations_shadow_active {1 if shadow else 0}",
        "# HELP gateway_mutations_shadow_blocked_today Would-have-actuated decisions logged in the current UTC day.",
        "# TYPE gateway_mutations_shadow_blocked_today gauge",
        f"gateway_mutations_shadow_blocked_today {_count_today()}",
        "# HELP gateway_mutations_mode_last_run_timestamp_seconds Unix ts of the last mutation-mode metric emit.",
        "# TYPE gateway_mutations_mode_last_run_timestamp_seconds gauge",
        f"gateway_mutations_mode_last_run_timestamp_seconds {now}",
    ]
    tmp = PROM + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o644)  # node_exporter runs non-root; 0600 = silently absent metric
        os.replace(tmp, PROM)
    except OSError as e:
        print(f"WARN: prom write failed: {e}", file=sys.stderr)


def cmd_off(a):
    if SENTINEL.exists():
        print("Already MUTATIONS=OFF (shadow mode active).")
    else:
        SENTINEL.write_text(json.dumps({
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": a.reason, "operator": a.operator}) + "\n")
        _log_transition("off", a.operator, a.reason)
        print("MUTATIONS=OFF — shadow / log-only mode ACTIVE. The system runs fully but actuations "
              "are blocked + logged to ~/logs/claude-gateway/mutation-shadow/.")
    write_prom()
    return 0


def cmd_on(a):
    if not SENTINEL.exists():
        print("Already MUTATIONS=ON (normal — the system actuates).")
    else:
        SENTINEL.unlink()
        _log_transition("on", a.operator, a.reason)
        print("MUTATIONS=ON — normal mode. The system actuates as usual.")
    write_prom()
    return 0


def cmd_status(a):
    shadow = mutation_mode.is_shadow()
    st = {"mutations": "OFF (shadow)" if shadow else "ON (normal)",
          "shadow_active": shadow, "sentinel": str(SENTINEL), "sentinel_present": SENTINEL.exists(),
          "env_override": os.environ.get("MUTATIONS_OFF"),
          "blocked_today": _count_today(), "log_dir": str(mutation_mode._LOG_DIR)}
    if a.emit_metrics:
        write_prom()
    if a.json:
        print(json.dumps(st, indent=2))
    else:
        print(f"MUTATIONS: {st['mutations']}")
        print(f"  sentinel        : {'present' if st['sentinel_present'] else 'absent'} ({SENTINEL})")
        if st["env_override"] is not None:
            print(f"  env override    : MUTATIONS_OFF={st['env_override']}")
        print(f"  blocked today   : {st['blocked_today']}  (shadow-log: {st['log_dir']})")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("off", "on"):
        p = sub.add_parser(name)
        p.add_argument("--reason", default="")
        p.add_argument("--operator", default=os.environ.get("USER", "operator"))
    ps = sub.add_parser("status")
    ps.add_argument("--json", action="store_true")
    ps.add_argument("--emit-metrics", action="store_true")
    a = ap.parse_args()
    return {"off": cmd_off, "on": cmd_on, "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
