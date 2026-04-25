#!/usr/bin/env python3
"""Chaos Engineering — safely kill a VPN tunnel and let visitors watch failover.

Called by n8n webhook. Validates Cloudflare Turnstile token, checks safety,
shuts down tunnel, schedules auto-recovery.
State tracked in ~/chaos-state/chaos-active.json. Dead-man switch via detached background process.

Usage:
  chaos-test.py start --tunnel "NL ↔ GR" --wan freedom [--duration 600] --turnstile-token TOKEN
  chaos-test.py status
  chaos-test.py recover
"""
import argparse
import datetime
import fcntl
import json
import os
import pathlib
import secrets
import subprocess
import sys
import urllib.request
import urllib.parse

# Shared ASA SSH module (eliminates duplicated SSH patterns and hardcoded passwords)
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, "lib"))
sys.path.insert(0, _script_dir)
from asa_ssh import (get_asa_password, ssh_nl_asa_command, ssh_nl_asa_config,
                     ssh_gr_asa_command, ssh_gr_asa_config, ssh_vps_swanctl,
                     ssh_host_reachable, ssh_oob_reachable,
                     SSH_OPTS_BASE, ASA_NL_HOST, ASA_USER,
                     GR_OOB_HOST, GR_OOB_PORT, GR_OOB_USER, GR_ASA_HOST)
# 2026-04-22 [IFRNLLEI01PRD-674]: Budget VTIs moved to nlrtr01
from ios_ssh import ssh_rtr01_command, ssh_rtr01_config  # noqa: E402

# Chaos baseline — steady-state snapshots, experiment journal, alert suppression
from chaos_baseline import (snapshot_steady_state, generate_experiment_id,
                            generate_hypothesis, compute_verdict, write_experiment,
                            suppress_alerts_for_chaos, clear_alert_suppression,
                            ensure_chaos_experiments_table)

# Shared chaos-active.json discipline — see scripts/lib/chaos_marker.py
from chaos_marker import (ChaosCollisionError, check_no_cross_drill,
                          atomic_write_marker, marker_lock)  # noqa: E402

STATE_DIR = os.path.expanduser("~/chaos-state")
# Honour CHAOS_STATE_PATH env var (same convention as scripts/chaos-preflight.sh
# and scripts/lib/chaos_marker.py). Lets QA fixtures redirect to a scratch
# tempdir, and lets production crons give different chaos drivers isolated
# state files so a recovery read doesn't race another driver's new write —
# root cause of the 2026-04-23 12:09 "Experiment None completed" duplicates.
STATE_FILE = os.environ.get(
    "CHAOS_STATE_PATH",
    os.path.join(STATE_DIR, "chaos-active.json"),
)
HISTORY_FILE = os.path.join(STATE_DIR, "chaos-history.json")
os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
RATE_LIMIT_SECONDS = 3600  # 1 test per hour
DEFAULT_DURATION = 600  # 10 minutes
MAX_DURATION = 600

# Matrix notification constants (R2: Chaos Toolkit CT-5)
MATRIX_HOMESERVER = "https://matrix.example.net"
INFRA_NL_ROOM = "!AOMuEtXGyzGFLgObKN:matrix.example.net"
_SSL_CTX = None


def _get_ssl_ctx():
    global _SSL_CTX
    if _SSL_CTX is None:
        import ssl
        _SSL_CTX = ssl.create_default_context()
        _SSL_CTX.check_hostname = False
        _SSL_CTX.verify_mode = ssl.CERT_NONE
    return _SSL_CTX


def _get_matrix_token():
    """Load Matrix bot token from .env."""
    env_path = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("MATRIX_CLAUDE_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    return os.environ.get("MATRIX_CLAUDE_TOKEN", "")


_NOTIFY_DEDUP_PATH = os.path.join(STATE_DIR, "chaos-notify-dedup.json")
_NOTIFY_DEDUP_WINDOW_S = 120


def _notify_matrix_is_duplicate(message, now_ts):
    """Return True if identical body was already posted within the dedup window.
    Rebuilds state file on corruption and prunes entries older than 2x window."""
    import hashlib
    h = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
    try:
        with open(_NOTIFY_DEDUP_PATH) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = {}
    cutoff = now_ts - 2 * _NOTIFY_DEDUP_WINDOW_S
    state = {k: v for k, v in state.items() if isinstance(v, (int, float)) and v > cutoff}
    if h in state and (now_ts - state[h]) < _NOTIFY_DEDUP_WINDOW_S:
        return True
    state[h] = now_ts
    try:
        tmp = _NOTIFY_DEDUP_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, _NOTIFY_DEDUP_PATH)
    except OSError:
        pass
    return False


def _notify_matrix(message, room=None):
    """Post a notice to Matrix. Fire-and-forget — never blocks chaos operations.
    Dedupes identical bodies posted within _NOTIFY_DEDUP_WINDOW_S seconds — guards
    against the duplicate-completion race where chaos-test.py + chaos-port-shutdown.py
    both call into the same completion-post path on a shared state file."""
    token = _get_matrix_token()
    if not token:
        return
    room = room or INFRA_NL_ROOM
    import time as _time
    now_ts = _time.time()
    if _notify_matrix_is_duplicate(message, now_ts):
        print(f"INFO: Matrix notify deduped (body already posted within {_NOTIFY_DEDUP_WINDOW_S}s)", file=sys.stderr)
        return
    txn_id = f"chaos-{int(now_ts)}-{os.getpid()}"
    url = (f"{MATRIX_HOMESERVER}/_matrix/client/v3/rooms/"
           f"{urllib.parse.quote(room, safe='')}/send/m.room.message/{txn_id}")
    payload = json.dumps({"msgtype": "m.notice", "body": message}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, context=_get_ssl_ctx(), timeout=10)
    except Exception as e:
        # M10: Log failure but never block chaos operations
        print(f"WARNING: Matrix notification failed: {e}", file=sys.stderr)


def _get_turnstile_secret():
    """Get Cloudflare Turnstile secret key from env or .env file."""
    secret = os.environ.get("CF_TURNSTILE_SECRET", "")
    if secret:
        return secret
    env_path = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("CF_TURNSTILE_SECRET="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    return ""


def verify_turnstile(token):
    """Verify a Cloudflare Turnstile token. Returns True if valid."""
    # Allow skipping for baseline tests and internal automation
    if os.environ.get("CHAOS_SKIP_TURNSTILE", "").lower() == "true":
        return True

    secret = _get_turnstile_secret()
    if not secret:
        print(json.dumps({"error": "Turnstile secret not configured. Set CF_TURNSTILE_SECRET in .env"}),
              file=sys.stderr)
        return False

    if not token:
        return False

    try:
        data = urllib.parse.urlencode({
            "secret": secret,
            "response": token,
        }).encode()
        req = urllib.request.Request(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=data,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            return result.get("success", False)
    except Exception:
        # If Cloudflare is unreachable, deny by default
        return False

# Tunnel → device mapping (tunnels available for chaos testing).
# 2026-04-22 [IFRNLLEI01PRD-674]: post xs4all→budget migration, the 3 Budget
# tunnels moved to nlrtr01 (ISR 4321). Freedom still terminates on fw01.
CHAOS_TUNNELS = {
    # Budget tunnels (active-active with Freedom; terminate on rtr01)
    ("NL ↔ GR", "budget"):   {"asa": "rtr", "interface": "Tunnel1", "failover_via": "Freedom VTI (NL fw01)"},
    ("NL ↔ NO", "budget"):   {"asa": "rtr", "interface": "Tunnel2", "failover_via": "Freedom VTI (NL fw01)"},
    ("NL ↔ CH", "budget"):   {"asa": "rtr", "interface": "Tunnel3", "failover_via": "Freedom VTI (NL fw01)"},
    # Freedom tunnels (terminate on fw01)
    ("NL ↔ GR", "freedom"):  {"asa": "nl", "interface": "Tunnel4", "failover_via": "Budget VTI (NL rtr01)"},
    ("NL ↔ NO", "freedom"):  {"asa": "nl", "interface": "Tunnel5", "failover_via": "Budget VTI (NL rtr01)"},
    ("NL ↔ CH", "freedom"):  {"asa": "nl", "interface": "Tunnel6", "failover_via": "Budget VTI (NL rtr01)"},
    # GR inalan tunnels (only WAN — no dual-WAN on GR)
    ("GR ↔ NO", "inalan"):   {"asa": "gr", "interface": "Tunnel2", "failover_via": "NL transit (GR→NL→NO)"},
    ("GR ↔ CH", "inalan"):   {"asa": "gr", "interface": "Tunnel3", "failover_via": "NL transit (GR→NL→CH)"},
    # NO ↔ CH VPS tunnel — fixed: use swanctl --load-all for recovery (IFRNLLEI01PRD-466)
    ("NO ↔ CH", "vps"):      {"asa": "vps-no", "interface": "ch", "failover_via": "NL/GR transit (NO→NL→GR→CH)"},
}

# Graph connectivity validator — replaces simple SAFETY_DEPS
# The mesh has 4 sites (NL, GR, NO, CH), 9 tunnels, 6 chaosable edges.
# NO↔CH IS chaosable (XFRM issues fixed: IFRNLLEI01PRD-466, swanctl --load-all recovery).
# For websites to survive: each VPS (NO, CH) must reach at least one DMZ site (NL or GR).
#
# Tunnel → graph edge mapping (logical link, not WAN-specific):
TUNNEL_GRAPH_EDGE = {
    ("NL ↔ GR", "budget"):  ("NL", "GR"),
    ("NL ↔ GR", "freedom"): ("NL", "GR"),
    ("NL ↔ NO", "budget"):  ("NL", "NO"),
    ("NL ↔ NO", "freedom"): ("NL", "NO"),
    ("NL ↔ CH", "budget"):  ("NL", "CH"),
    ("NL ↔ CH", "freedom"): ("NL", "CH"),
    ("GR ↔ NO", "inalan"):  ("GR", "NO"),
    ("GR ↔ CH", "inalan"):  ("GR", "CH"),
    ("NO ↔ CH", "vps"):     ("NO", "CH"),
}

# Max 4 tunnels per test (golden ratio: 29 safe combos out of 31)
MAX_TUNNEL_KILLS = 4


def validate_graph_connectivity(tunnel_keys):
    """Check if killing these tunnels keeps both VPS connected to at least one DMZ site.

    Uses BFS on the surviving graph edges. NO↔CH is always UP (transit backbone).
    Returns (safe, reason) tuple.
    """
    if len(tunnel_keys) > MAX_TUNNEL_KILLS:
        return False, f"Max {MAX_TUNNEL_KILLS} tunnels per test (golden ratio limit)"

    # Build surviving edge set
    killed_edges = set()
    for tk in tunnel_keys:
        edge = TUNNEL_GRAPH_EDGE.get(tk)
        if edge:
            killed_edges.add(edge)
            killed_edges.add((edge[1], edge[0]))  # bidirectional

    # All possible edges (from TUNNEL_GRAPH_EDGE, deduplicated)
    all_edges = set()
    for edge in TUNNEL_GRAPH_EDGE.values():
        all_edges.add(edge)
        all_edges.add((edge[1], edge[0]))

    alive_edges = all_edges - killed_edges

    # Build adjacency
    adj = {}
    for a, b in alive_edges:
        adj.setdefault(a, set()).add(b)

    def reachable(start):
        visited = set()
        queue = [start]
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        return visited

    no_reach = reachable("NO")
    ch_reach = reachable("CH")
    no_ok = "NL" in no_reach or "GR" in no_reach
    ch_ok = "NL" in ch_reach or "GR" in ch_reach

    if not no_ok and not ch_ok:
        return False, "Both VPS nodes isolated from all DMZ sites -- total website outage"
    if not no_ok:
        return False, "NO VPS isolated from all DMZ sites -- partial website outage"
    if not ch_ok:
        return False, "CH VPS isolated from all DMZ sites -- partial website outage"
    return True, "Graph connectivity OK"


# Legacy SAFETY_DEPS kept for single-tunnel backward compat.
# 2026-04-22 [IFRNLLEI01PRD-674]: xs4all → budget rename.
SAFETY_DEPS = {
    ("NL ↔ GR", "budget"): [("NL ↔ GR", "freedom")],
    ("NL ↔ NO", "budget"): [("NL ↔ NO", "freedom")],
    ("NL ↔ CH", "budget"): [("NL ↔ CH", "freedom")],
    ("NL ↔ GR", "freedom"): [("NL ↔ GR", "budget")],
    ("NL ↔ NO", "freedom"): [("NL ↔ NO", "budget")],
    ("NL ↔ CH", "freedom"): [("NL ↔ CH", "budget")],
    ("GR ↔ NO", "inalan"): [],
    ("GR ↔ CH", "inalan"): [],
    ("NO ↔ CH", "vps"):   [],
}

# DMZ host → SSH access + Proxmox NIC config for link-level chaos
DMZ_HOSTS = {
    "nl-dmz01": {
        "site": "NL", "ssh": "direct",
        "pve_host": "nl-pve01", "vmid": "VMID_REDACTED",
        "net0": "virtio=BC:24:11:58:5B:CA,bridge=vmbr0,tag=21",
    },
    "gr-dmz01": {
        "site": "GR", "ssh": "direct",
        "pve_host": "gr-pve01", "vmid": "201121301",
        "net0": "virtio=BC:24:11:A9:8D:4A,bridge=vmbr0,tag=12",
    },
}

# Containers available for chaos testing (subset of all containers)
# compose_dir: the /srv/ directory containing docker-compose.yml (may differ from container name)
DMZ_CONTAINERS = {
    "portfolio": {"domain": "kyriakos.papadopoulos.tech", "compose_dir": "portfolio"},
    "cubeos-website": {"domain": "get.cubeos.app", "compose_dir": "cubeos-website"},
    "meshsat-website": {"domain": "meshsat.net", "compose_dir": "meshsat-net"},
    "mulecube": {"domain": "mulecube.com", "compose_dir": "mulecube"},
}

# Constants imported from lib.asa_ssh (ASA_NL_HOST, ASA_USER, GR_OOB_*, etc.)


def asa_config(asa, config_commands):
    """Execute config commands on ASA/router. Dispatches by device type.

    2026-04-22 [IFRNLLEI01PRD-674]: `asa == "rtr"` dispatches to rtr01
    (Cisco ISR 4321, IOS-XE 17.9) via scripts/lib/ios_ssh.py. Budget VTIs
    (Tunnel1/2/3) live on rtr01 post-migration.
    """
    if asa == "nl":
        return ssh_nl_asa_config(config_commands)
    elif asa == "gr":
        return ssh_gr_asa_config(config_commands)
    elif asa == "rtr":
        return ssh_rtr01_config(config_commands)
    elif asa == "vps-no":
        # NO VPS: swanctl terminate + load-all for recovery (IFRNLLEI01PRD-466 fix)
        conn_name = config_commands[0] if config_commands else ""
        pw = get_asa_password()
        if "shutdown" in (config_commands[1] if len(config_commands) > 1 else ""):
            cmd = f"echo '{pw}' | sudo -S swanctl --terminate --ike {conn_name} 2>/dev/null; echo OK"
        else:
            # Single sudo bash -c to avoid password exhaustion across multiple sudo calls
            cmd = (f"echo '{pw}' | sudo -S bash -c '"
                   f"swanctl --load-all 2>/dev/null; "
                   f"sleep 2; "
                   f"swanctl --initiate --ike {conn_name} 2>/dev/null; "
                   f"sleep 2; "
                   f"swanctl --initiate --child {conn_name} 2>/dev/null; "
                   f"echo OK'")
        try:
            result = subprocess.run(
                ["ssh"] + SSH_OPTS_BASE +
                ["-i", os.path.expanduser("~/.ssh/one_key"),
                 "operator@198.51.100.X", cmd],
                capture_output=True, text=True, timeout=30,
            )
            return "OK" in result.stdout
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return False


def pve_nic_disconnect(host):
    """Disconnect VM NIC via Proxmox — simulates real network failure."""
    info = DMZ_HOSTS.get(host)
    if not info or "pve_host" not in info:
        return "ERROR: No PVE config for " + host
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
             "-i", os.path.expanduser("~/.ssh/one_key"),
             f"root@{info['pve_host']}",
             f"qm set {info['vmid']} -net0 {info['net0']},link_down=1"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"ERROR: {e}"


def pve_nic_reconnect(host):
    """Reconnect VM NIC via Proxmox — restores network."""
    info = DMZ_HOSTS.get(host)
    if not info or "pve_host" not in info:
        return "ERROR: No PVE config for " + host
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
             "-i", os.path.expanduser("~/.ssh/one_key"),
             f"root@{info['pve_host']}",
             f"qm set {info['vmid']} -net0 {info['net0']}"],
            capture_output=True, text=True, timeout=15,
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"ERROR: {e}"


def ssh_dmz_docker(host, docker_cmd):
    """SSH to a DMZ host and execute a Docker command. Returns stdout.

    NL DMZ: direct SSH (same LAN).
    GR DMZ: tries direct first, falls back to OOB ProxyJump
    (203.0.113.X:2222 → grclaude01 → gr-dmz01) so recovery
    works even when NL↔GR VPN tunnel is killed during combined chaos tests.
    """
    info = DMZ_HOSTS.get(host)
    if not info:
        return f"ERROR: Unknown DMZ host {host}"

    sudo_pw = get_asa_password()
    SUDO_PREFIX = f"echo '{sudo_pw}' | sudo -S "
    cmd = SUDO_PREFIX + docker_cmd if "compose" in docker_cmd else docker_cmd
    key = os.path.expanduser("~/.ssh/one_key")

    # Try direct SSH first (works when VPN is up)
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5",
             "-i", key, f"operator@{host}", cmd],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass

    # GR DMZ: fall back to OOB two-hop when direct SSH fails
    # Path: nl-claude01 → 203.0.113.X:2222 → grclaude01 → gr-dmz01
    if info.get("site") == "GR":
        try:
            # Escape single quotes in cmd for nested SSH
            escaped_cmd = cmd.replace("'", "'\\''")
            inner = (f"ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "
                     f"-i ~/.ssh/one_key operator@{host} '{escaped_cmd}'")
            result = subprocess.run(
                ["ssh", "-p", GR_OOB_PORT,
                 "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
                 "-i", key, f"{GR_OOB_USER}@{GR_OOB_HOST}", inner],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout
        except Exception as e:
            return f"ERROR: OOB fallback failed: {e}"

    return f"ERROR: SSH to {host} failed (direct and OOB)"


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(state):
    # IFRNLLEI01PRD-709: atomic via tmpfile+os.replace so readers never see torn JSON.
    # Collision prevention for the FIRST write lives in _cmd_start_locked (below),
    # which calls check_no_cross_drill under marker_lock() (chaos_marker.py) before
    # this — the single shared cross-process lock, also used by chaos-port-shutdown.py
    # via install_marker(). Subsequent in-drill updates skip the check (they're
    # this drill's own state).
    atomic_write_marker(state, state_path=pathlib.Path(STATE_FILE))


def clear_state():
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass


def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(entry):
    history = load_history()
    history.append(entry)
    # Keep last 50 entries
    history = history[-50:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
    os.chmod(HISTORY_FILE, 0o600)


def check_rate_limit():
    """Check if enough time has passed since last chaos test."""
    history = load_history()
    if not history:
        return True, 0
    last = history[-1]
    last_time = datetime.datetime.fromisoformat(last["started_at"].replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    elapsed = (now - last_time).total_seconds()
    if elapsed < RATE_LIMIT_SECONDS:
        remaining = int(RATE_LIMIT_SECONDS - elapsed)
        return False, remaining
    return True, 0


def get_current_tunnel_status():
    """Quick check: get tunnel interface status from mesh-stats."""
    try:
        import urllib.request
        url = "https://n8n.example.net/webhook/mesh-stats"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read())
            return {(t["label"], t["wan"]): t["status"] for t in data.get("tunnels", [])}
    except Exception:
        return {}


PROM_DIR = "/var/lib/node_exporter/textfile_collector"
PROM_FILE = os.path.join(PROM_DIR, "chaos_test.prom")


def _write_prom_metrics():
    """Write chaos test metrics to Prometheus textfile collector (M5)."""
    if not os.path.isdir(PROM_DIR):
        return
    state = load_state()
    active = 1 if state else 0
    history = load_history()
    total = len(history)

    lines = [
        "# HELP chaos_test_active Whether a chaos test is currently active",
        "# TYPE chaos_test_active gauge",
        f"chaos_test_active {active}",
        "# HELP chaos_test_total Total chaos tests executed (from history)",
        "# TYPE chaos_test_total gauge",
        f"chaos_test_total {total}",
    ]
    if state:
        elapsed = int((datetime.datetime.now(datetime.timezone.utc) -
                       datetime.datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))).total_seconds())
        lines += [
            "# HELP chaos_test_elapsed_seconds Seconds since current test started",
            "# TYPE chaos_test_elapsed_seconds gauge",
            f"chaos_test_elapsed_seconds {elapsed}",
            "# HELP chaos_test_deadman_alive Whether the dead-man switch process is running",
            "# TYPE chaos_test_deadman_alive gauge",
            f"chaos_test_deadman_alive {1 if _deadman_alive() else 0}",
        ]
    try:
        tmp = PROM_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.rename(tmp, PROM_FILE)
    except OSError:
        pass


def schedule_deadman_recovery(target_type, target_id, delay_seconds, *, experiment_id=None):
    """Schedule a dead-man switch recovery via detached background process.

    The recover command handles both tunnel and DMZ restoration from state file,
    so we just need one scheduled recovery call regardless of chaos type.

    2026-04-22 fix: wrap the detached process with `systemd-run --user --scope
    --slice=app.slice` so the deadman is placed in a cgroup OUTSIDE the SSH
    session scope. Previously `setsid + nohup + start_new_session` looked
    detached but the child was still in the n8n SSH session's session-*.scope
    — when the SSH session closed, systemd-logind eventually killed the
    deadman along with the scope's other members, leaving chaos state stale
    and tunnels stuck shut until chaos-orphan-recovery.sh cron (up to 60s
    late) caught the orphan.

    2026-04-24 hygiene: propagate CHAOS_EXPECTED_EXPERIMENT_ID env var. The
    dead-man recovery uses it to verify the on-disk state still belongs to
    this drill — if another driver (chaos-port-shutdown.py) has overwritten
    the marker by the time the sleep fires, cmd_recover bails silently
    instead of running on the wrong state (root cause of the 2026-04-23 12:09
    "Experiment None completed" duplicates).

    Backup still in place: chaos-orphan-recovery.sh runs every minute.
    PID is stored in STATE_DIR/deadman.pid for observability and cancellation.
    """
    _kill_deadman()  # Cancel any previous dead-man

    import time as _t
    import shlex
    recover_script = os.path.abspath(__file__)
    unit = f"chaos-deadman-{os.getpid()}-{int(_t.time() * 1000)}"
    exp_env = (
        f"CHAOS_EXPECTED_EXPERIMENT_ID={shlex.quote(experiment_id)} "
        if experiment_id else ""
    )
    # systemd-run --user --scope places the child in
    #   /user.slice/user-UID.slice/user@UID.service/app.slice/<unit>.scope
    # which survives the SSH session scope closing.
    proc = subprocess.Popen(
        ["systemd-run", "--user", "--scope", "--quiet",
         "--slice=app.slice", f"--unit={unit}",
         "bash", "-c",
         f"trap '' HUP; sleep {delay_seconds} && {exp_env}CHAOS_INTERNAL_RECOVER=1 "
         f"python3 {recover_script} recover"],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    pid_file = os.path.join(STATE_DIR, "deadman.pid")
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))
    os.chmod(pid_file, 0o600)
    # Also stash the unit name so _kill_deadman can `systemctl --user stop` it
    # on cancel, belt-and-braces against the PID recycle risk.
    unit_file = os.path.join(STATE_DIR, "deadman.unit")
    with open(unit_file, "w") as f:
        f.write(unit)
    os.chmod(unit_file, 0o600)


def _kill_deadman():
    """Kill the dead-man switch process / scope if it exists."""
    pid_file = os.path.join(STATE_DIR, "deadman.pid")
    unit_file = os.path.join(STATE_DIR, "deadman.unit")
    # Prefer stopping the systemd scope (handles PID recycle + kills child)
    try:
        with open(unit_file) as f:
            unit = f.read().strip()
        if unit:
            subprocess.run(
                ["systemctl", "--user", "stop", f"{unit}.scope"],
                capture_output=True, timeout=5,
            )
    except (FileNotFoundError, ValueError, subprocess.SubprocessError):
        pass
    # Fall back to PID kill (handles pre-2026-04-22 deadmen still running)
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check alive
        os.kill(pid, 9)  # Kill process group leader (the bash sleep)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        pass
    for f in (pid_file, unit_file):
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


def _deadman_alive():
    """Check if the dead-man switch process is still running."""
    pid_file = os.path.join(STATE_DIR, "deadman.pid")
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # signal 0 = check existence
        return True
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return False


def _execute_tunnel_chaos(tunnel_keys, now):
    """Execute tunnel chaos — validate, safety-check, and shut down selected tunnels."""
    # Validate all tunnels
    tunnel_infos = []
    for tk in tunnel_keys:
        info = CHAOS_TUNNELS.get(tk)
        if not info:
            print(json.dumps({"error": f"Tunnel {tk[0]} ({tk[1]}) not available for chaos testing",
                              "available": [f"{k[0]} ({k[1]})" for k in CHAOS_TUNNELS]}))
            sys.exit(1)
        tunnel_infos.append((tk, info))

    # Check all tunnels are currently UP
    statuses = get_current_tunnel_status()
    for tk, _ in tunnel_infos:
        status = statuses.get(tk, "unknown")
        # Allow "up" and "standby" (standby = IKE up, ESP dormant — valid chaos target)
        # Only reject truly "down" tunnels
        if status == "down":
            print(json.dumps({"error": f"Tunnel {tk[0]} ({tk[1]}) is already down, cannot chaos test a dead tunnel"}))
            sys.exit(1)

    # Graph connectivity safety check (replaces legacy SAFETY_DEPS for multi-tunnel)
    safe, reason = validate_graph_connectivity(tunnel_keys)
    if not safe:
        print(json.dumps({"error": f"Safety check failed: {reason}"}))
        sys.exit(1)

    # Legacy per-tunnel backup check (single-tunnel backward compat)
    for tk in tunnel_keys:
        deps = SAFETY_DEPS.get(tk, [])
        for dep in deps:
            dep_status = statuses.get(dep, "unknown")
            if dep_status == "down":
                print(json.dumps({"error": f"Safety check failed: backup tunnel {dep[0]} ({dep[1]}) is down. "
                                  f"Killing {tk[0]} would risk site isolation."}))
                sys.exit(1)

    # Shut down all tunnels
    events = []
    killed = []
    for tk, info in tunnel_infos:
        if info["asa"].startswith("vps"):
            success = asa_config(info["asa"], [info["interface"], "shutdown"])
            device_label = "NO VPS swanctl"
        else:
            success = asa_config(info["asa"], [f"interface {info['interface']}", "shutdown"])
            device_label = f"{info['asa'].upper()} ASA"
        if success:
            events.append({
                "time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event": "tunnel_shutdown",
                "detail": f"{info['interface']} shut down on {device_label}",
            })
            killed.append({"tunnel": tk[0], "wan": tk[1], "asa": info["asa"],
                           "interface": info["interface"], "failover_via": info["failover_via"]})
        else:
            for prev in killed:
                if prev["asa"].startswith("vps"):
                    asa_config(prev["asa"], [prev["interface"], "no shutdown"])
                else:
                    asa_config(prev["asa"], [f"interface {prev['interface']}", "no shutdown"])
            print(json.dumps({"error": f"Failed to shut down {info['interface']} on {info['asa'].upper()} ASA. Rolled back."}))
            sys.exit(1)

    failover_desc = tunnel_infos[0][1]["failover_via"]

    return killed, events, failover_desc


def _execute_dmz_chaos(host, container, duration, now):
    """Execute DMZ container chaos. Returns (containers_killed, events)."""
    events = []
    containers_killed = []

    if container:
        # Single container kill
        if container not in DMZ_CONTAINERS:
            print(json.dumps({"error": f"Container '{container}' not available for chaos testing",
                              "available": list(DMZ_CONTAINERS.keys())}))
            sys.exit(1)
        # Verify container is running
        status_out = ssh_dmz_docker(host, 'docker ps --format "{{.Names}}"')
        if "ERROR" in status_out:
            print(json.dumps({"error": f"Cannot reach {host}: {status_out}"}))
            sys.exit(1)
        running = [line.strip() for line in status_out.strip().splitlines() if line.strip()]
        if container not in running:
            print(json.dumps({"error": f"Container '{container}' not running on {host}"}))
            sys.exit(1)

        cdir = DMZ_CONTAINERS[container]["compose_dir"]
        result = ssh_dmz_docker(host, f"cd /srv/{cdir} && docker compose stop {container}")
        if "ERROR" not in result:
            events.append({
                "time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event": "container_stop",
                "detail": f"Stopped {container} on {host}",
            })
            containers_killed.append({"host": host, "container": container,
                                      "domain": DMZ_CONTAINERS[container]["domain"]})
        else:
            print(json.dumps({"error": f"Failed to stop {container} on {host}: {result}"}))
            sys.exit(1)
    else:
        # Full node kill — disconnect VM NIC via Proxmox (real network failure)
        result = pve_nic_disconnect(host)
        if "ERROR" not in result:
            events.append({
                "time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event": "nic_disconnect",
                "detail": f"Disconnected NIC on {host} via Proxmox (VMID {DMZ_HOSTS[host]['vmid']})",
            })
            # Mark all containers as killed (they're unreachable)
            for cname in DMZ_CONTAINERS:
                containers_killed.append({"host": host, "container": cname,
                                          "domain": DMZ_CONTAINERS[cname]["domain"]})
        else:
            print(json.dumps({"error": f"Failed to disconnect NIC on {host}: {result}"}))
            sys.exit(1)

    return containers_killed, events


def cmd_start(args):
    # Concurrent-start protection lives inside _cmd_start_locked via marker_lock()
    # from chaos_marker.py (DEFAULT_LOCK_PATH = chaos-active.json.lock), which is
    # the single shared cross-process lock — also used by chaos-port-shutdown.py
    # via install_marker(). The previous outer flock here opened the SAME lock
    # file on a separate fd and then re-flocked it inside marker_lock(); Linux
    # treats different fds in the same process as independent flock holders, so
    # the second LOCK_EX | LOCK_NB returned EAGAIN and every start ABORTed with
    # "scenario=unknown, experiment_id=n/a" (lock-contention path in
    # chaos_marker.py:marker_lock with no marker file present).
    # Regression introduced 2026-04-24 (commit b9c0661, belt-and-braces inner
    # marker_lock added without removing this outer one). Six intensive sessions
    # / 18 baseline experiments lost between 2026-04-23 20:05 UTC and 2026-04-25
    # 12:25 UTC before detection.
    _cmd_start_locked(args)


def _cmd_start_locked(args):
    # If params passed as base64 JSON (shell-safe transport from n8n), decode them
    if getattr(args, "params_b64", None):
        import base64
        params = json.loads(base64.b64decode(args.params_b64))
        args.chaos_type = params.get("chaos_type", "tunnel")
        args.tunnel = params.get("tunnel", "")
        args.wan = params.get("wan", "")
        args.host = params.get("host", "")
        args.container = params.get("container", "")
        args.duration = int(params.get("duration", DEFAULT_DURATION))
        args.turnstile_token = params.get("cf-turnstile-response", "") or params.get("turnstile_token", "")
        args.tunnels = json.dumps(params["tunnels"]) if params.get("tunnels") else None
        if not getattr(args, "source_ip", ""):
            args.source_ip = params.get("source_ip", "")

    # Verify Cloudflare Turnstile token (bot protection)
    # TODO: Turnstile validation failing for website visitors — needs debugging
    # Token may be mangled in browser→CDN→HAProxy→n8n→SSH→base64 pipeline
    token = getattr(args, "turnstile_token", None) or ""
    if not os.environ.get("CHAOS_SKIP_TURNSTILE", "").lower() == "true":
        # C5: Turnstile verification MUST be blocking for public requests
        if not token:
            print(json.dumps({"error": "Turnstile token required"}))
            sys.exit(0)
        if not verify_turnstile(token):
            print(json.dumps({"error": "Turnstile verification failed. Try again."}))
            sys.exit(0)

    # Determine chaos type and resolve tunnel selections
    chaos_type = getattr(args, "chaos_type", "tunnel") or "tunnel"
    tunnel_keys = []
    if chaos_type in ("tunnel", "combined"):
        tunnels_json = getattr(args, "tunnels", None)
        if tunnels_json:
            try:
                tunnel_list = json.loads(tunnels_json)
                tunnel_keys = [(t["tunnel"], t["wan"]) for t in tunnel_list]
            except (json.JSONDecodeError, KeyError):
                print(json.dumps({"error": "Invalid --tunnels JSON"}))
                sys.exit(1)
        elif args.tunnel and args.wan:
            tunnel_keys = [(args.tunnel, args.wan)]
        elif chaos_type == "tunnel":
            print(json.dumps({"error": "Provide --tunnel+--wan or --tunnels JSON"}))
            sys.exit(1)

    # 2026-04-22: dedup tunnel_keys preserving order. Prevents double-click
    # from the UI from recording the same (tunnel, wan) pair twice in
    # tunnels_killed, which previously caused the recovery path to run
    # shutdown+no-shutdown on the same interface redundantly.
    tunnel_keys = list(dict.fromkeys(tunnel_keys))

    # DMZ parameters
    dmz_host = getattr(args, "host", None) or ""
    dmz_container = getattr(args, "container", None) or ""

    # Validate DMZ parameters for dmz/combined modes
    if chaos_type in ("dmz", "combined"):
        if not dmz_host:
            print(json.dumps({"error": "DMZ chaos requires --host parameter",
                              "available_hosts": list(DMZ_HOSTS.keys())}))
            sys.exit(1)
        if dmz_host not in DMZ_HOSTS:
            print(json.dumps({"error": f"Unknown DMZ host '{dmz_host}'",
                              "available_hosts": list(DMZ_HOSTS.keys())}))
            sys.exit(1)

    # Check if another test is running
    state = load_state()
    if state:
        expires = datetime.datetime.fromisoformat(state["expires_at"].replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        if now < expires:
            remaining = int((expires - now).total_seconds())
            print(json.dumps({"error": "Chaos test already active",
                              "tunnel": state.get("tunnel"),
                              "remaining_seconds": remaining}))
            sys.exit(1)
        else:
            clear_state()

    # Rate limit (shared across all chaos types)
    # Baseline tests use 10min rate limit instead of 1hr
    if os.environ.get("CHAOS_SKIP_TURNSTILE", "").lower() == "true":
        # Baseline mode: 10min rate limit (5min BGP convergence + 5min buffer)
        baseline_cooldown = 600  # 10 minutes
        history = load_history()
        if history:
            last = history[-1]
            last_time = datetime.datetime.fromisoformat(last["started_at"].replace("Z", "+00:00"))
            now_rl = datetime.datetime.now(datetime.timezone.utc)
            elapsed = (now_rl - last_time).total_seconds()
            if elapsed < baseline_cooldown:
                wait = int(baseline_cooldown - elapsed)
                print(json.dumps({"error": "Baseline rate limited (10min)", "retry_after_seconds": wait}))
                sys.exit(1)
    else:
        allowed, wait = check_rate_limit()
        if not allowed:
            print(json.dumps({"error": "Rate limited", "retry_after_seconds": wait}))
            sys.exit(1)

    # M6: Maintenance mode check — block chaos during planned maintenance
    maint_file = os.path.expanduser("~/gateway.maintenance")
    if os.path.isfile(maint_file):
        try:
            with open(maint_file) as f:
                maint = json.load(f)
            reason = maint.get("reason", "unknown")
        except (json.JSONDecodeError, IOError):
            reason = "unknown"
        print(json.dumps({"error": f"Maintenance mode active: {reason}. Chaos tests blocked during maintenance."}))
        sys.exit(1)

    # M1/M2: Pre-flight SSH connectivity check — verify recovery paths before killing anything
    preflight_failures = []
    targets_needed = set()
    for tk in tunnel_keys:
        info = CHAOS_TUNNELS.get(tk)
        if info:
            targets_needed.add(info["asa"])
    for asa in targets_needed:
        if asa == "nl":
            if not ssh_host_reachable(ASA_NL_HOST):
                preflight_failures.append(f"NL ASA ({ASA_NL_HOST}) SSH unreachable")
        elif asa == "gr":
            if not ssh_oob_reachable():
                preflight_failures.append(f"GR OOB path ({GR_OOB_HOST}:{GR_OOB_PORT}) unreachable "
                                          "— only recovery path (PiKVM bricked)")
        elif asa == "vps-no":
            if not ssh_host_reachable("198.51.100.X"):
                preflight_failures.append("NO VPS (198.51.100.X) SSH unreachable")
    if dmz_host and not ssh_host_reachable(dmz_host):
        preflight_failures.append(f"DMZ host {dmz_host} SSH unreachable")
    if preflight_failures:
        print(json.dumps({"error": "Pre-flight check failed - cannot guarantee recovery",
                           "failures": preflight_failures}))
        sys.exit(1)

    duration = min(args.duration, MAX_DURATION)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(seconds=duration)

    ensure_chaos_experiments_table()
    experiment_id = generate_experiment_id()
    is_baseline = os.environ.get("CHAOS_SKIP_TURNSTILE", "").lower() == "true"
    triggered_by = "baseline" if is_baseline else "visitor"
    source_ip = getattr(args, "source_ip", "") or ("cron" if is_baseline else "unknown")

    # Build target lists (for state + response, before actual kills)
    tunnel_infos = []
    for tk in tunnel_keys:
        info = CHAOS_TUNNELS.get(tk)
        if info:
            tunnel_infos.append({"tunnel": tk[0], "wan": tk[1], "asa": info["asa"],
                                 "interface": info["interface"], "failover_via": info["failover_via"]})

    container_targets = []
    if chaos_type in ("dmz", "combined"):
        if dmz_container:
            container_targets.append({"host": dmz_host, "container": dmz_container,
                                      "domain": DMZ_CONTAINERS.get(dmz_container, {}).get("domain", "")})
        else:
            for cname, cinfo in DMZ_CONTAINERS.items():
                container_targets.append({"host": dmz_host, "container": cname, "domain": cinfo["domain"]})

    failover_desc = tunnel_infos[0]["failover_via"] if tunnel_infos else "Cross-site failover via other DMZ host."

    # Generate recovery token with TTL (expires at test end + 5min buffer)
    recover_token = secrets.token_urlsafe(32)
    token_expires_at = expires_at + datetime.timedelta(minutes=5)
    tunnel_info_list = [{"tunnel": t["tunnel"], "wan": t["wan"], "asa": t["asa"]} for t in tunnel_infos]
    hypothesis, expected_convergence = generate_hypothesis(chaos_type, tunnel_info_list, container_targets)

    # Save state BEFORE kills — makes the test visible to status polling immediately
    state = {
        "chaos_type": chaos_type,
        "recover_token": recover_token,
        "token_expires_at": token_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tunnel": tunnel_infos[0]["tunnel"] if len(tunnel_infos) == 1 else None,
        "wan": tunnel_infos[0]["wan"] if len(tunnel_infos) == 1 else None,
        "tunnels_killed": [{"tunnel": t["tunnel"], "wan": t["wan"], "asa": t["asa"],
                            "interface": t["interface"]} for t in tunnel_infos],
        "containers_killed": container_targets,
        "failover_via": failover_desc,
        "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": duration,
        "events": [{"time": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": "starting", "detail": "Executing kills..."}],
        "experiment_id": experiment_id,
        "pre_state": {"skipped": True} if not is_baseline else {},
        "hypothesis": hypothesis,
        "expected_convergence": expected_convergence,
        "triggered_by": triggered_by,
        "source_ip": source_ip,
        "suppression": {},
    }
    # Clear live log BEFORE writing state — prevents race where status polling
    # sees the test as active but reads stale logs from a previous experiment
    try:
        open(LIVE_LOG_FILE, "w").close()
    except OSError:
        pass
    # IFRNLLEI01PRD-709 belt-and-braces: re-check for a cross-drill marker
    # under the shared fcntl lock right before the FIRST save. The earlier
    # load_state() probe at line ~819 is racy wrt other writers that might
    # have started in between; the flock makes this check atomic vs
    # chaos-port-shutdown.py (which uses the same lock via chaos_marker.py).
    try:
        with marker_lock():
            check_no_cross_drill(scenario_id=None, experiment_id=experiment_id)
            save_state(state)
    except ChaosCollisionError as e:
        # Matrix-clarity: name the other drill's scenario + expiry so the
        # operator sees who holds the marker, not just "collision detected".
        # Read from the exception's carried attributes, NOT by re-reading the
        # state file — the re-read is racy because the `with marker_lock()`
        # block has already released by the time this except runs, giving
        # the conflicting drill a window to clear the marker (observed live
        # 2026-04-24 20:05/20:15 UTC producing two "unknown/n/a/unknown"
        # ABORT posts). ChaosCollisionError now carries the marker dict it
        # saw at raise time.
        other_scenario = getattr(e, "other_scenario", "") or "unknown"
        other_exp_id = getattr(e, "other_experiment_id", "") or "n/a"
        other_expires = getattr(e, "other_expires_at", "") or "unknown"
        other_triggered_by = getattr(e, "other_triggered_by", "") or "unknown"
        _notify_matrix(
            f"[Chaos] ABORT — another drill owns the marker.\n"
            f"Other drill: scenario={other_scenario}, experiment_id={other_exp_id}, "
            f"triggered_by={other_triggered_by}, expires={other_expires}.\n"
            f"This request refused — retry after the other drill completes."
        )
        print(json.dumps({
            "error": "Chaos marker collision — another drill owns chaos-active.json",
            "other_scenario": other_scenario,
            "other_experiment_id": other_exp_id,
            "other_triggered_by": other_triggered_by,
            "other_expires_at": other_expires,
            "detail": str(e),
        }))
        sys.exit(1)
    schedule_deadman_recovery(chaos_type, "manual", duration + 60, experiment_id=experiment_id)

    # Save to history
    history_entry = {
        "chaos_type": chaos_type,
        "tunnels": [f"{t['tunnel']} ({t['wan']})" for t in tunnel_infos],
        "containers": [f"{c['container']}@{c['host']}" for c in container_targets],
        "started_at": state["started_at"],
        "duration_seconds": duration,
    }
    save_history(history_entry)

    # Print response IMMEDIATELY — frontend gets it in <1 second
    tunnel_labels = [f"{t['tunnel']} ({t['wan']})" for t in tunnel_infos]
    container_labels = [f"{c['container']} on {c['host']}" for c in container_targets]
    parts = []
    if tunnel_labels:
        parts.append(f"Killing {len(tunnel_labels)} tunnel(s): {', '.join(tunnel_labels)}")
    if container_labels:
        parts.append(f"Stopping {len(container_labels)} container(s): {', '.join(container_labels)}")
    msg = ". ".join(parts) + f". {failover_desc}. Auto-recovery in {duration}s."

    # R2: Notify Matrix at experiment start
    # Matrix-clarity: include expected restore + drill-complete ETAs so the
    # operator doesn't need to compute "when should I worry".
    target_desc = ", ".join(f"{t['tunnel']} ({t['wan']})" for t in tunnel_infos)
    if container_targets:
        container_desc = ", ".join(f"{c.get('container', 'all')}@{c.get('host', dmz_host)}" for c in container_targets)
        target_desc = f"{target_desc}, DMZ: {container_desc}" if target_desc else f"DMZ: {container_desc}"
    _restore_eta = (now + datetime.timedelta(seconds=duration)).strftime("%H:%M UTC")
    _drill_complete_eta = (now + datetime.timedelta(seconds=duration + 90)).strftime("%H:%M UTC")
    _notify_matrix(
        f"[Chaos] Experiment {experiment_id} started: {target_desc}\n"
        f"Duration: {duration}s | Failover: {failover_desc}\n"
        f"Restore at ~{_restore_eta}; full drill complete by ~{_drill_complete_eta}."
    )

    print(json.dumps({
        "status": "active",
        "chaos_type": chaos_type,
        "recover_token": recover_token,
        "tunnel": tunnel_infos[0]["tunnel"] if len(tunnel_infos) == 1 else None,
        "wan": tunnel_infos[0]["wan"] if len(tunnel_infos) == 1 else None,
        "tunnels_killed": [{"tunnel": t["tunnel"], "wan": t["wan"]} for t in tunnel_infos],
        "containers_killed": container_targets,
        "failover_via": failover_desc,
        "started_at": state["started_at"],
        "expires_at": state["expires_at"],
        "duration_seconds": duration,
        "message": msg,
    }))
    _write_prom_metrics()

    # === PHASE 2: Fork kills into background process ===
    # n8n SSH node buffers stdout until script exits. We must exit NOW
    # so the frontend gets the response. Kills run in a detached child.
    execute_script = os.path.abspath(__file__)
    kill_args = json.dumps({
        "chaos_type": chaos_type,
        "tunnel_keys": [[t[0], t[1]] for t in tunnel_keys],
        "dmz_host": dmz_host,
        "dmz_container": dmz_container or "",
        "is_baseline": is_baseline,
    })
    subprocess.Popen(
        ["python3", execute_script, "execute-kills", "--kill-args-b64",
         __import__("base64").b64encode(kill_args.encode()).decode()],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    # Main process exits immediately — n8n gets the response


def cmd_status(args):
    state = load_state()
    if not state:
        # Check rate limit for next available test
        _, wait = check_rate_limit()
        print(json.dumps({
            "status": "idle",
            "next_available_in": wait,
            "history": load_history()[-5:],
        }))
        _write_prom_metrics()
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    expires = datetime.datetime.fromisoformat(state["expires_at"].replace("Z", "+00:00"))
    remaining = max(0, int((expires - now).total_seconds()))
    elapsed = int((now - datetime.datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))).total_seconds())

    if remaining <= 0:
        # Test expired but wasn't cleaned up — recover now
        cmd_recover(args)
        return

    print(json.dumps({
        "status": "active",
        "chaos_type": state.get("chaos_type", "tunnel"),
        "tunnel": state.get("tunnel"),
        "wan": state.get("wan"),
        "tunnels_killed": state.get("tunnels_killed", []),
        "containers_killed": state.get("containers_killed", []),
        "failover_via": state.get("failover_via"),
        "started_at": state["started_at"],
        "expires_at": state["expires_at"],
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
        "deadman_alive": _deadman_alive(),
        "events": state.get("events", []),
        "live_logs": _read_live_logs(),
    }))
    _write_prom_metrics()


def _read_live_logs():
    """Read live log JSONL file, return list of {ts, src, line} entries."""
    try:
        with open(LIVE_LOG_FILE) as f:
            return [json.loads(line) for line in f if line.strip()]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def cmd_recover(args):
    # Cross-driver idempotency: exclusive flock so concurrent cmd_recover
    # invocations (dead-man firing + chaos-orphan-recovery.sh racing within
    # the same minute) can't both run the recovery workload + both post
    # Matrix completions. Lock is released on any exit path via the OS.
    recover_lock_path = STATE_FILE + ".recover-lock"
    try:
        os.makedirs(os.path.dirname(recover_lock_path), exist_ok=True)
        _recover_lock_fd = open(recover_lock_path, "w")
        os.chmod(recover_lock_path, 0o600)
    except OSError:
        _recover_lock_fd = None
    if _recover_lock_fd is not None:
        try:
            fcntl.flock(_recover_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            # Another cmd_recover holds the lock — bail silently. This is the
            # common-case idempotency guard for the dead-man + orphan-cron race.
            print(json.dumps({"status": "already_recovering",
                              "message": "another recovery already in progress"}))
            return

    # Identity guard: if the dead-man exported CHAOS_EXPECTED_EXPERIMENT_ID,
    # verify the on-disk state's experiment_id still matches. When another
    # driver (chaos-port-shutdown.py) has overwritten the shared state file
    # between cmd_start and dead-man fire, the IDs diverge and we bail
    # silently rather than running recovery on state we don't own — root
    # cause of the 2026-04-23 12:09 "Experiment None completed" duplicates.
    _expected_exp_id = os.environ.get("CHAOS_EXPECTED_EXPERIMENT_ID")
    if _expected_exp_id and os.environ.get("CHAOS_INTERNAL_RECOVER"):
        _probe_state = load_state()
        _actual_id = (_probe_state or {}).get("experiment_id")
        if _actual_id != _expected_exp_id:
            print(json.dumps({
                "status": "stale",
                "expected_experiment_id": _expected_exp_id,
                "actual_experiment_id": _actual_id,
                "message": "state no longer matches this dead-man's experiment — another drill owns the marker now",
            }))
            return

    # Cancel dead-man switch timer (avoid double-recovery race)
    _kill_deadman()

    # Verify recovery authorization
    # Dead-man switch sets CHAOS_INTERNAL_RECOVER — always allowed
    if not os.environ.get("CHAOS_INTERNAL_RECOVER"):
        # Web requests must provide the session recover_token (issued at chaos start)
        recover_token = ""
        if getattr(args, "params_b64", None):
            import base64
            params = json.loads(base64.b64decode(args.params_b64))
            recover_token = params.get("recover_token", "")
        else:
            recover_token = getattr(args, "turnstile_token", "") or ""

        state_check = load_state()
        if state_check and state_check.get("recover_token"):
            if recover_token != state_check["recover_token"]:
                print(json.dumps({"error": "Invalid or missing recovery token"}))
                sys.exit(1)
            # Check token TTL (expires at test end + 5min buffer)
            token_exp = state_check.get("token_expires_at", "")
            if token_exp:
                exp_dt = datetime.datetime.fromisoformat(token_exp.replace("Z", "+00:00"))
                if datetime.datetime.now(datetime.timezone.utc) > exp_dt:
                    print(json.dumps({"error": "Recovery token expired. Test has already ended."}))
                    sys.exit(1)

    state = load_state()
    if not state:
        print(json.dumps({"status": "idle", "message": "No active chaos test to recover"}))
        return

    # For web requests: respond immediately, fork recovery into background
    if not os.environ.get("CHAOS_INTERNAL_RECOVER"):
        print(json.dumps({
            "status": "recovered",
            "chaos_type": state.get("chaos_type", "tunnel"),
            "message": "Recovery initiated",
        }))
        # Fork actual recovery as background process
        recover_script = os.path.abspath(__file__)
        subprocess.Popen(
            ["bash", "-c", f"CHAOS_INTERNAL_RECOVER=1 python3 {recover_script} recover"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
        return

    # === Below runs in background (CHAOS_INTERNAL_RECOVER=1) ===

    # Clear shun on BOTH ASAs — threat detection may have shunned VTI/VPS IPs
    ssh_nl_asa_command(["clear shun"])
    try:
        ssh_gr_asa_command(["clear shun"])
    except Exception:
        pass  # GR ASA may be unreachable if tunnels are down

    # Restore all killed tunnels
    # Step 1: Terminate stale VPS swanctl SAs for affected peers
    #         (VPS may have stale SAs from before the tunnel was killed)
    tunnels_killed = state.get("tunnels_killed", [])
    vps_reload_needed = set()
    for tk in tunnels_killed:
        # Determine which VPS peers need SA reload based on tunnel
        tunnel_label = tk.get("tunnel", "")
        if "NO" in tunnel_label:
            vps_reload_needed.add("198.51.100.X")
        if "CH" in tunnel_label:
            vps_reload_needed.add("198.51.100.X")

    if vps_reload_needed:
        pw = get_asa_password()
        for vps_ip in vps_reload_needed:
            try:
                subprocess.run(
                    ["ssh"] + SSH_OPTS_BASE +
                    ["-i", os.path.expanduser("~/.ssh/one_key"),
                     f"operator@{vps_ip}",
                     f"echo '{pw}' | sudo -S swanctl --load-all 2>/dev/null"],
                    capture_output=True, text=True, timeout=15,
                )
            except Exception:
                pass

    # Step 2: Bounce ASA tunnels (shut + wait + no shut for clean IKE re-init)
    restored = []
    for tk in tunnels_killed:
        if tk["asa"].startswith("vps"):
            asa_config(tk["asa"], [tk["interface"], "no shutdown"])
            restored.append(f"{tk['interface']} on NO VPS swanctl")
        else:
            # Shut first to clear any stale crypto state
            asa_config(tk["asa"], [f"interface {tk['interface']}", "shut"])

    import time
    if tunnels_killed:
        time.sleep(5)

    for tk in tunnels_killed:
        if not tk["asa"].startswith("vps"):
            asa_config(tk["asa"], [f"interface {tk['interface']}", "no shut"])
            restored.append(f"{tk['interface']} on {tk['asa'].upper()} ASA")

    # Restore killed DMZ — check if NIC was disconnected or containers were stopped
    containers_killed = state.get("containers_killed", [])
    nic_disconnected = any(e.get("event") == "nic_disconnect" for e in state.get("events", []))
    containers_restored = []

    if nic_disconnected:
        # Reconnect NIC(s) via Proxmox
        import time
        hosts_reconnected = set()
        for ck in containers_killed:
            host = ck.get("host", "")
            if host and host not in hosts_reconnected:
                result = pve_nic_reconnect(host)
                if "ERROR" not in result:
                    containers_restored.append(f"NIC reconnected on {host}")
                else:
                    containers_restored.append(f"NIC reconnect FAILED on {host}: {result}")
                hosts_reconnected.add(host)
        # Wait for NIC + services to stabilize before post-state snapshot
        if hosts_reconnected:
            time.sleep(30)
    else:
        # Individual container recovery via docker compose start
        for ck in containers_killed:
            host = ck.get("host", "")
            container = ck.get("container", "")
            if host and container:
                cdir = DMZ_CONTAINERS.get(container, {}).get("compose_dir", container)
                result = ssh_dmz_docker(host, f"cd /srv/{cdir} && docker compose start {container}")
                if "ERROR" not in result:
                    containers_restored.append(f"{container} on {host}")
                else:
                    containers_restored.append(f"{container} on {host} (FAILED: {result})")

    now = datetime.datetime.now(datetime.timezone.utc)

    # Clear alert suppression layers
    suppression = state.get("suppression", {})
    if suppression:
        clear_alert_suppression(suppression)

    clear_state()

    # Post-recovery verification: confirm tunnels/containers actually came back
    verify_failures = []
    if tunnels_killed:
        time.sleep(30)  # 30s for IKE/BGP/BFD to re-establish
        for tk in tunnels_killed:
            if tk["asa"].startswith("vps"):
                continue  # VPS tunnels verified differently
            verified = False
            for attempt in range(3):  # 3 attempts
                if tk["asa"] == "nl":
                    out = ssh_nl_asa_command([f"show interface {tk['interface']} | include line protocol"])
                elif tk["asa"] == "gr":
                    out = ssh_gr_asa_command([f"show interface {tk['interface']} | include line protocol"])
                elif tk["asa"] == "rtr":
                    out = ssh_rtr01_command([f"show interface {tk['interface']} | include line protocol"])
                else:
                    break
                if "up" in out.lower() and "ERROR" not in out:
                    verified = True
                    break
                # Escalating recovery on each retry
                if attempt == 0:
                    # Retry: just no shut
                    if tk["asa"] == "nl":
                        ssh_nl_asa_config([f"interface {tk['interface']}", "no shut"])
                    elif tk["asa"] == "gr":
                        ssh_gr_asa_config([f"interface {tk['interface']}", "no shut"])
                    elif tk["asa"] == "rtr":
                        ssh_rtr01_config([f"interface {tk['interface']}", "no shutdown"])
                    time.sleep(10)
                elif attempt == 1:
                    # Retry: reload VPS swanctl + bounce tunnel
                    pw = get_asa_password()
                    for vps_ip in vps_reload_needed:
                        try:
                            subprocess.run(
                                ["ssh"] + SSH_OPTS_BASE +
                                ["-i", os.path.expanduser("~/.ssh/one_key"),
                                 f"operator@{vps_ip}",
                                 f"echo '{pw}' | sudo -S swanctl --load-all 2>/dev/null"],
                                capture_output=True, text=True, timeout=15)
                        except Exception:
                            pass
                    if tk["asa"] == "nl":
                        ssh_nl_asa_config([f"interface {tk['interface']}", "shut"])
                    elif tk["asa"] == "gr":
                        ssh_gr_asa_config([f"interface {tk['interface']}", "shut"])
                    elif tk["asa"] == "rtr":
                        ssh_rtr01_config([f"interface {tk['interface']}", "shutdown"])
                    time.sleep(5)
                    if tk["asa"] == "nl":
                        ssh_nl_asa_config([f"interface {tk['interface']}", "no shut"])
                    elif tk["asa"] == "gr":
                        ssh_gr_asa_config([f"interface {tk['interface']}", "no shut"])
                    elif tk["asa"] == "rtr":
                        ssh_rtr01_config([f"interface {tk['interface']}", "no shutdown"])
                    time.sleep(15)
            if not verified:
                verify_failures.append(f"{tk['interface']} on {tk['asa'].upper()} ASA still down")
    if containers_killed and not nic_disconnected:
        for ck in containers_killed:
            host, container = ck.get("host", ""), ck.get("container", "")
            if host and container:
                out = ssh_dmz_docker(host, f'docker ps --format "{{{{.Names}}}}" --filter name={container}')
                if container not in out:
                    verify_failures.append(f"{container} on {host} not running")

    # Baseline: snapshot post-state, compute verdict, write experiment journal
    experiment_id = state.get("experiment_id")
    pre_state = state.get("pre_state", {})
    started_at = state.get("started_at", "")
    recovered_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        post_state = snapshot_steady_state(timeout=30)
    except Exception as e:
        post_state = {"error": str(e), "timestamp": recovered_at}

    # Compute recovery duration
    recovery_seconds = None
    if started_at:
        try:
            started_dt = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            recovery_seconds = (now - started_dt).total_seconds()
        except Exception:
            pass

    # Compute verdict (per-metric pass/fail)
    verdict = "UNKNOWN"
    verdict_details = {}
    expected_convergence = state.get("expected_convergence", 90)
    if pre_state and not pre_state.get("error"):
        verdict, verdict_details = compute_verdict(
            pre_state, post_state, state.get("chaos_type", "tunnel"), expected_convergence)
        # Override to FAIL if verification failed
        if verify_failures and verdict == "PASS":
            verdict = "DEGRADED"

    # Write experiment journal to SQLite
    if experiment_id:
        targets = {
            "tunnels_killed": state.get("tunnels_killed", []),
            "containers_killed": state.get("containers_killed", []),
        }
        try:
            write_experiment(
                experiment_id=experiment_id,
                chaos_type=state.get("chaos_type", "tunnel"),
                targets=targets,
                hypothesis=state.get("hypothesis", ""),
                pre_state=pre_state,
                post_state=post_state,
                events=state.get("events", []),
                convergence_seconds=expected_convergence,
                recovery_seconds=recovery_seconds,
                verdict=verdict,
                verdict_details=verdict_details,
                triggered_by=state.get("triggered_by", "visitor"),
                started_at=started_at,
                recovered_at=recovered_at,
                source_ip=state.get("source_ip"),
            )
        except Exception as e:
            print(f"WARNING: Failed to write experiment journal: {e}", file=sys.stderr)

    parts = []
    if restored:
        parts.append(f"Restored {len(restored)} tunnel(s): {', '.join(restored)}")
    if containers_restored:
        parts.append(f"Started {len(containers_restored)} container(s): {', '.join(containers_restored)}")
    msg = ". ".join(parts) + "." if parts else "Nothing to recover."

    print(json.dumps({
        "status": "recovered",
        "chaos_type": state.get("chaos_type", "tunnel"),
        "tunnel": state.get("tunnel"),
        "wan": state.get("wan"),
        "tunnels_restored": restored,
        "containers_restored": containers_restored,
        "recovered_at": recovered_at,
        "verification": "passed" if not verify_failures else "FAILED",
        "verify_failures": verify_failures,
        "experiment_id": experiment_id,
        "verdict": verdict,
        "verdict_details": verdict_details,
        "message": msg,
    }))
    _write_prom_metrics()

    # R2: Notify Matrix at experiment end (3-line Matrix-clarity format)
    # Line 1: verdict header with experiment_id for journal lookup
    # Line 2: one-line mesh summary — convergence + recovery verification
    # Line 3: what to check next (verify_failures if any; else link hint)
    #
    # Guard: experiment_id may be None if state file was cleared before
    # cmd_recover ran (cross-driver state overwrite on a shared file).
    # Guard: convergence may be "N/A" string from verdict_details.get default,
    # which must NOT get the "s" unit suffix appended.
    exp_id = experiment_id or f"unknown-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
    raw_conv = verdict_details.get("convergence_seconds") if isinstance(verdict_details, dict) else None
    if not isinstance(raw_conv, (int, float)) and isinstance(recovery_seconds, (int, float)):
        raw_conv = recovery_seconds  # fall back to observed recovery time
    conv_str = f"{raw_conv:.0f}s" if isinstance(raw_conv, (int, float)) else "N/A"
    _recovery_label = "OK" if not verify_failures else "FAILED"
    _line3 = (
        f"verify_failures={len(verify_failures)}: {'; '.join(verify_failures)[:180]}"
        if verify_failures
        else f"Journal: chaos_exercises.experiment_id={exp_id}"
    )
    _notify_matrix(
        f"[Chaos] Experiment {exp_id} completed: {verdict}\n"
        f"Convergence: {conv_str} | Recovery: {_recovery_label}\n"
        f"{_line3}"
    )


def cmd_execute_kills(args):
    """Background process: execute the actual chaos kills after start returned."""
    import base64
    kill_args = json.loads(base64.b64decode(args.kill_args_b64))

    chaos_type = kill_args["chaos_type"]
    tunnel_keys = [tuple(t) for t in kill_args.get("tunnel_keys", [])]
    dmz_host = kill_args.get("dmz_host", "")
    dmz_container = kill_args.get("dmz_container", "")
    is_baseline = kill_args.get("is_baseline", False)
    now = datetime.datetime.now(datetime.timezone.utc)

    # Baseline: pre-state snapshot
    if is_baseline:
        try:
            pre_state = snapshot_steady_state(timeout=30)
            state_update = load_state()
            if state_update:
                state_update["pre_state"] = pre_state
                save_state(state_update)
        except Exception:
            pass

    # Execute kills — log to file since stdout/stderr are /dev/null
    log_file = os.path.expanduser("~/chaos-state/execute-kills.log")
    # Ensure log file has restricted permissions
    if not os.path.exists(log_file):
        open(log_file, "w").close()
    os.chmod(log_file, 0o600)
    events = []
    if chaos_type in ("dmz", "combined") and dmz_host:
        try:
            _, d_events = _execute_dmz_chaos(dmz_host, dmz_container or None, 0, now)
            events.extend(d_events)
            with open(log_file, "a") as f:
                f.write(f"{now.isoformat()} DMZ kill OK: {dmz_host}\n")
        except SystemExit as e:
            with open(log_file, "a") as f:
                f.write(f"{now.isoformat()} DMZ kill FAILED: {e}\n")
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"{now.isoformat()} DMZ kill ERROR: {e}\n")

    if chaos_type in ("tunnel", "combined") and tunnel_keys:
        try:
            _, t_events, _ = _execute_tunnel_chaos(tunnel_keys, now)
            events.extend(t_events)
            with open(log_file, "a") as f:
                f.write(f"{now.isoformat()} Tunnel kill OK: {tunnel_keys}\n")
        except SystemExit as e:
            with open(log_file, "a") as f:
                f.write(f"{now.isoformat()} Tunnel kill FAILED (SystemExit): {e}\n")
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"{now.isoformat()} Tunnel kill ERROR: {e}\n")

    # Update state with events
    try:
        tunnel_info_list = []
        for tk in tunnel_keys:
            info = CHAOS_TUNNELS.get(tk)
            if info:
                tunnel_info_list.append({"tunnel": tk[0], "wan": tk[1], "asa": info["asa"]})
        dmz_host_list = [dmz_host] if dmz_host else []
        suppression = suppress_alerts_for_chaos(chaos_type, tunnel_info_list, dmz_host_list,
                                                 load_state().get("duration_seconds", 120) if load_state() else 120)
        state_update = load_state()
        if state_update:
            state_update["events"] = events
            state_update["suppression"] = suppression
            save_state(state_update)
    except Exception:
        pass

    # Start live log collector -- polls all devices until test expires
    _run_live_log_collector()


# ── Live log collector ──────────────────────────────────────────────────────

LIVE_LOG_FILE = os.path.expanduser("~/chaos-state/chaos-live.jsonl")


def _live_log(source, line):
    """Append a log line to the live JSONL file."""
    import time as _t
    entry = json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S"),
                         "src": source, "line": line.rstrip()})
    with open(LIVE_LOG_FILE, "a") as f:
        f.write(entry + "\n")


def _ssh_quick(host, cmd, key=None, user="root", timeout=8):
    """Quick SSH command, returns stdout lines. Swallows errors."""
    ssh_args = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5"]
    if key:
        ssh_args += ["-i", key]
    ssh_args += [f"{user}@{host}", cmd]
    try:
        r = subprocess.run(ssh_args, capture_output=True, text=True, timeout=timeout)
        return [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
    except Exception:
        return []


def _run_live_log_collector():
    """Poll all infrastructure devices for chaos-relevant logs until test expires.

    Writes to chaos-live.jsonl, read by cmd_status for the frontend terminal panel.
    Sources: syslog-ng (ASA), HAProxy (VPS), charon (VPS), FRR (VPS), Proxmox (PVE).
    """
    import time

    state = load_state()
    if not state:
        return

    # Clear previous live log
    try:
        open(LIVE_LOG_FILE, "w").close()
        os.chmod(LIVE_LOG_FILE, 0o600)
    except OSError:
        pass

    pw = get_asa_password()
    key = os.path.expanduser("~/.ssh/one_key")
    start_dt = datetime.datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))
    since_str = start_dt.strftime("%Y-%m-%d %H:%M")
    date_str = start_dt.strftime("%Y-%m-%d")
    year = start_dt.strftime("%Y")
    month = start_dt.strftime("%m")

    # Log the commands that were executed (only for THIS test's events)
    for ev in state.get("events", []):
        _live_log("exec", f"$ {ev.get('detail', ev.get('event', ''))}")

    seen = set()
    poll_count = 0
    # Time filter: only show logs from AFTER this test started (prevents previous test bleed)
    since_hhmm = start_dt.strftime("%H:%M")
    since_utc = start_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    while True:
        # Check if test is still active
        s = load_state()
        if not s:
            break
        expires = datetime.datetime.fromisoformat(s["expires_at"].replace("Z", "+00:00"))
        if datetime.datetime.now(datetime.timezone.utc) > expires:
            break

        poll_count += 1
        new_lines = []

        # ── Syslog-ng: ASA logs (NL + GR) -- time-filtered to this test only ──
        syslog_since_time = since_hhmm + ":00"  # e.g. "17:59:00"
        for syslog_host, asa_host in [("nlsyslogng01", "nl-fw01"), ("grsyslogng01", "gr-fw01")]:
            log_path = f"/mnt/logs/syslog-ng/{asa_host}/{year}/{month}/{asa_host}-{date_str}.log"
            awk_cmd = f"awk -v t='{syslog_since_time}' '$3 >= t' {log_path} 2>/dev/null"
            grep_cmd = f"{awk_cmd} | grep -iE 'Tunnel|IKE|IPsec|BGP|vpn|nic|link|shut|interface' | tail -10"
            lines = _ssh_quick(syslog_host, grep_cmd, key=key)
            for l in lines:
                if l not in seen:
                    seen.add(l)
                    new_lines.append((asa_host, l))

        # ── HAProxy backend failover (both VPS) ──
        for vps_ip, vps_name in [("198.51.100.X", "no-haproxy"), ("198.51.100.X", "ch-haproxy")]:
            lines = _ssh_quick(vps_ip,
                f"echo '{pw}' | sudo -S journalctl -u haproxy --since '{since_utc}' --no-pager -q 2>/dev/null | "
                f"grep -iE 'DOWN|UP|backup|NOSRV|Layer[467]|check|portfolio|cubeos|meshsat|mulecube' | tail -10",
                key=key, user="operator")
            for l in lines:
                if l not in seen:
                    seen.add(l)
                    new_lines.append((vps_name, l))

        # ── charon / strongSwan IKE logs (both VPS) ──
        for vps_ip, vps_name in [("198.51.100.X", "no-ipsec"), ("198.51.100.X", "ch-ipsec")]:
            lines = _ssh_quick(vps_ip,
                f"echo '{pw}' | sudo -S journalctl _COMM=charon --since '{since_utc}' --no-pager -q 2>/dev/null | "
                f"grep -iE 'IKE_SA|CHILD_SA|establish|delete|rekey|peer' | tail -5",
                key=key, user="operator")
            for l in lines:
                if l not in seen:
                    seen.add(l)
                    new_lines.append((vps_name, l))

        # ── FRR BGP logs (both VPS) ──
        for vps_ip, vps_name in [("198.51.100.X", "no-bgp"), ("198.51.100.X", "ch-bgp")]:
            lines = _ssh_quick(vps_ip,
                f"grep -E 'BGP|peer|Established|Active|Idle|route' /var/log/frr/frr.log 2>/dev/null | tail -5",
                key=key, user="operator")
            for l in lines:
                if l not in seen:
                    seen.add(l)
                    new_lines.append((vps_name, l))

        # ── Proxmox NIC events (PVE hosts) ──
        for pve_host in ["nl-pve01", "gr-pve01"]:
            if pve_host.startswith("nllei"):
                lines = _ssh_quick(pve_host,
                    f"journalctl --since '{since_utc}' --no-pager -q 2>/dev/null | grep -iE 'qm set|net0|link_down|virtio' | tail -5")
            else:
                lines = _ssh_quick(pve_host,
                    f"journalctl --since '{since_utc}' --no-pager -q 2>/dev/null | grep -iE 'qm set|net0|link_down|virtio' | tail -5",
                    key=key)
            for l in lines:
                if l not in seen:
                    seen.add(l)
                    new_lines.append((pve_host, l))

        # Write new lines to live log
        for src, line in new_lines:
            _live_log(src, line)

        # Wait before next poll (5s between polls)
        time.sleep(5)

    _live_log("chaos-test", "--- log collection ended ---")


def main():
    parser = argparse.ArgumentParser(description="Chaos Engineering — VPN tunnel kill switch")
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start a chaos test")
    start_p.add_argument("--chaos-type", default="tunnel", choices=["tunnel", "dmz", "combined"],
                         help="Type of chaos test: tunnel (VPN), dmz (Docker containers), combined (both)")
    start_p.add_argument("--tunnel", default="", help='Tunnel label, e.g. "NL ↔ GR"')
    start_p.add_argument("--wan", default="", help='WAN label, e.g. "freedom"')
    start_p.add_argument("--host", default="", help='DMZ host, e.g. "nl-dmz01" (for dmz/combined)')
    start_p.add_argument("--container", default="", help='Container name, e.g. "portfolio" (for dmz; omit for all)')
    start_p.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="Duration in seconds (max 600)")
    start_p.add_argument("--turnstile-token", default="", help="Cloudflare Turnstile verification token")
    start_p.add_argument("--tunnels", default=None, help='Multi-tunnel JSON: [{"tunnel":"NL ↔ GR","wan":"freedom"},...]')
    start_p.add_argument("--source-ip", default="", help="IP address of the request origin (from n8n/Cloudflare headers)")
    start_p.add_argument("--params-b64", default=None,
                         help="Base64-encoded JSON with all parameters (shell-safe, used by n8n)")

    sub.add_parser("status", help="Get current chaos test status")
    recover_p = sub.add_parser("recover", help="Manually recover (restore tunnel)")
    recover_p.add_argument("--turnstile-token", default="", help="Cloudflare Turnstile verification token")
    recover_p.add_argument("--params-b64", default=None,
                           help="Base64-encoded JSON with turnstile token (shell-safe, used by n8n)")

    kill_p = sub.add_parser("execute-kills", help="(internal) Execute chaos kills in background")
    kill_p.add_argument("--kill-args-b64", required=True, help="Base64-encoded kill parameters")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "recover":
        cmd_recover(args)
    elif args.command == "execute-kills":
        cmd_execute_kills(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
