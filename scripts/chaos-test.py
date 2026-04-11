#!/usr/bin/env python3
"""Chaos Engineering — safely kill a VPN tunnel and let visitors watch failover.

Called by n8n webhook. Validates Cloudflare Turnstile token, checks safety,
shuts down tunnel, schedules auto-recovery.
State tracked in ~/chaos-state/chaos-active.json. Dead-man switch via detached background process.

Usage:
  chaos-test.py start --tunnel "NL ↔ GR" --wan xs4all [--duration 600] --turnstile-token TOKEN
  chaos-test.py status
  chaos-test.py recover
"""
import argparse
import datetime
import fcntl
import json
import os
import secrets
import subprocess
import sys
import urllib.request
import urllib.parse

# Shared ASA SSH module (eliminates duplicated SSH patterns and hardcoded passwords)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from asa_ssh import (get_asa_password, ssh_nl_asa_command, ssh_nl_asa_config,
                     ssh_gr_asa_command, ssh_gr_asa_config, ssh_vps_swanctl,
                     ssh_host_reachable, ssh_oob_reachable,
                     SSH_OPTS_BASE, ASA_NL_HOST, ASA_USER,
                     GR_OOB_HOST, GR_OOB_PORT, GR_OOB_USER, GR_ASA_HOST)

STATE_DIR = os.path.expanduser("~/chaos-state")
STATE_FILE = os.path.join(STATE_DIR, "chaos-active.json")
HISTORY_FILE = os.path.join(STATE_DIR, "chaos-history.json")
os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
RATE_LIMIT_SECONDS = 3600  # 1 test per hour
DEFAULT_DURATION = 600  # 10 minutes
MAX_DURATION = 600


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
    secret = _get_turnstile_secret()
    if not secret:
        # Only skip verification if explicitly opted in via env var
        if os.environ.get("CHAOS_SKIP_TURNSTILE", "").lower() == "true":
            return True
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

# Tunnel → ASA mapping (only tunnels safe for public chaos testing)
CHAOS_TUNNELS = {
    ("NL ↔ GR", "xs4all"):   {"asa": "nl", "interface": "Tunnel1", "failover_via": "NO transit (NL→NO→GR)"},
    ("NL ↔ NO", "xs4all"):   {"asa": "nl", "interface": "Tunnel2", "failover_via": "GR transit (NL→GR→NO)"},
    ("NL ↔ CH", "xs4all"):   {"asa": "nl", "interface": "Tunnel3", "failover_via": "NO transit (NL→NO→CH)"},
    ("GR ↔ NO", "inalan"):   {"asa": "gr", "interface": "Tunnel2", "failover_via": "NL transit (GR→NL→NO)"},
    ("GR ↔ CH", "inalan"):   {"asa": "gr", "interface": "Tunnel3", "failover_via": "NL transit (GR→NL→CH)"},
    # NO ↔ CH temporarily excluded — VPS swanctl recovery has XFRM reqid/policy
    # binding issues that prevent clean auto-heal. Needs dedicated investigation.
    # ("NO ↔ CH", "vps"):    {"asa": "vps-no", "interface": "ch", "failover_via": "NL/GR transit (NO→NL→GR→CH)"},
}

# Tunnels that must stay UP to prevent site isolation
# For each tunnel, list what other tunnel must be up
SAFETY_DEPS = {
    ("NL ↔ GR", "xs4all"): [("NL ↔ GR", "freedom")],  # freedom backup must be up
    ("NL ↔ NO", "xs4all"): [("NL ↔ NO", "freedom")],
    ("NL ↔ CH", "xs4all"): [("NL ↔ CH", "freedom")],
    ("GR ↔ NO", "inalan"): [],  # GR→NO can route via NL
    ("GR ↔ CH", "inalan"): [],  # GR→CH can route via NL
    ("NO ↔ CH", "vps"):   [],   # NO→CH can route via NL/GR
}

# DMZ host → SSH access + Proxmox NIC config for link-level chaos
DMZ_HOSTS = {
    "nldmz01": {
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
    """Execute config commands on ASA. Dispatches to shared module or VPS-specific logic."""
    if asa == "nl":
        return ssh_nl_asa_config(config_commands)
    elif asa == "gr":
        return ssh_gr_asa_config(config_commands)
    elif asa == "vps-no":
        # NO VPS: swanctl terminate/initiate — chaos-specific, not in shared module
        conn_name = config_commands[0] if config_commands else ""
        pw = get_asa_password()
        if "shutdown" in (config_commands[1] if len(config_commands) > 1 else ""):
            cmd = f"echo '{pw}' | sudo -S swanctl --terminate --ike {conn_name} 2>/dev/null; echo OK"
        else:
            cmd = (f"echo '{pw}' | sudo -S swanctl --initiate --ike {conn_name} 2>/dev/null; "
                   f"sleep 2; "
                   f"echo '{pw}' | sudo -S swanctl --initiate --child {conn_name} 2>/dev/null; "
                   f"echo OK")
        try:
            result = subprocess.run(
                ["ssh"] + SSH_OPTS_BASE +
                ["-i", os.path.expanduser("~/.ssh/one_key"),
                 "operator@185.125.171.172", cmd],
                capture_output=True, text=True, timeout=20,
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
    """SSH to a DMZ host and execute a Docker command. Returns stdout."""
    info = DMZ_HOSTS.get(host)
    if not info:
        return f"ERROR: Unknown DMZ host {host}"

    # Direct SSH over VPN for both NL and GR DMZ hosts
    # Some /srv/ directories are root-owned — need sudo for compose commands
    sudo_pw = _get_asa_password()
    SUDO_PREFIX = f"echo '{sudo_pw}' | sudo -S "
    cmd = SUDO_PREFIX + docker_cmd if "compose" in docker_cmd else docker_cmd
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
             "-i", os.path.expanduser("~/.ssh/one_key"),
             f"operator@{host}", cmd],
            capture_output=True, text=True, timeout=20,
        )
        return result.stdout
    except Exception as e:
        return f"ERROR: {e}"


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    os.chmod(STATE_FILE, 0o600)


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


def schedule_deadman_recovery(target_type, target_id, delay_seconds):
    """Schedule a dead-man switch recovery via detached background process.

    The recover command handles both tunnel and DMZ restoration from state file,
    so we just need one scheduled recovery call regardless of chaos type.
    Uses a detached process (start_new_session) so recovery survives parent exit.
    PID is stored in STATE_DIR/deadman.pid for observability and cancellation.
    """
    _kill_deadman()  # Cancel any previous dead-man

    recover_script = os.path.abspath(__file__)
    proc = subprocess.Popen(
        ["bash", "-c", f"sleep {delay_seconds} && CHAOS_INTERNAL_RECOVER=1 python3 {recover_script} recover"],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    pid_file = os.path.join(STATE_DIR, "deadman.pid")
    with open(pid_file, "w") as f:
        f.write(str(proc.pid))
    os.chmod(pid_file, 0o600)


def _kill_deadman():
    """Kill the dead-man switch process if it exists."""
    pid_file = os.path.join(STATE_DIR, "deadman.pid")
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # Check alive
        os.kill(pid, 9)  # Kill process group leader (the bash sleep)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        pass
    try:
        os.remove(pid_file)
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

    # Safety: check backup dependency for each tunnel
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

    return containers_killed, events


def cmd_start(args):
    # Acquire exclusive lock to prevent concurrent start requests
    lock_fd = open(STATE_FILE + ".lock", "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print(json.dumps({"error": "Another chaos test operation is in progress"}))
        sys.exit(1)

    try:
        _cmd_start_locked(args)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


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

    # Verify Cloudflare Turnstile token (bot protection)
    token = getattr(args, "turnstile_token", None) or ""
    if not verify_turnstile(token):
        print(json.dumps({"error": "Turnstile verification failed. Please complete the challenge and try again."}))
        sys.exit(1)

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
            if not ssh_host_reachable("185.125.171.172"):
                preflight_failures.append("NO VPS (185.125.171.172) SSH unreachable")
    if dmz_host and not ssh_host_reachable(dmz_host):
        preflight_failures.append(f"DMZ host {dmz_host} SSH unreachable")
    if preflight_failures:
        print(json.dumps({"error": "Pre-flight check failed - cannot guarantee recovery",
                           "failures": preflight_failures}))
        sys.exit(1)

    duration = min(args.duration, MAX_DURATION)
    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(seconds=duration)

    # Execute based on chaos type
    killed_tunnels = []
    killed_containers = []
    events = []
    failover_desc = ""

    if chaos_type == "tunnel":
        killed_tunnels, events, failover_desc = _execute_tunnel_chaos(tunnel_keys, now)
    elif chaos_type == "dmz":
        killed_containers, events = _execute_dmz_chaos(
            dmz_host, dmz_container or None, duration, now)
        failover_desc = "Cross-site failover via other DMZ host."
    elif chaos_type == "combined":
        # Execute tunnel kill first, then DMZ
        killed_tunnels, t_events, failover_desc = _execute_tunnel_chaos(tunnel_keys, now)
        events.extend(t_events)
        killed_containers, d_events = _execute_dmz_chaos(
            dmz_host, dmz_container or None, duration, now)
        events.extend(d_events)

    # Generate a session recovery token (required to recover via API)
    recover_token = secrets.token_urlsafe(32)

    # Save state
    state = {
        "chaos_type": chaos_type,
        "recover_token": recover_token,
        "tunnel": killed_tunnels[0]["tunnel"] if len(killed_tunnels) == 1 else None,
        "wan": killed_tunnels[0]["wan"] if len(killed_tunnels) == 1 else None,
        "tunnels_killed": [{"tunnel": k["tunnel"], "wan": k["wan"], "asa": k["asa"],
                            "interface": k["interface"]} for k in killed_tunnels],
        "containers_killed": killed_containers,
        "failover_via": failover_desc,
        "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": duration,
        "events": events,
    }
    save_state(state)

    # Single dead-man switch — recover reads full state file, so one process handles all
    schedule_deadman_recovery(chaos_type, "manual", duration + 60)

    # Save to history
    history_entry = {
        "chaos_type": chaos_type,
        "tunnels": [f"{k['tunnel']} ({k['wan']})" for k in killed_tunnels],
        "containers": [f"{k['container']}@{k['host']}" for k in killed_containers],
        "started_at": state["started_at"],
        "duration_seconds": duration,
    }
    save_history(history_entry)

    # Build response
    tunnel_labels = [f"{k['tunnel']} ({k['wan']})" for k in killed_tunnels]
    container_labels = [f"{k['container']} on {k['host']}" for k in killed_containers]
    parts = []
    if tunnel_labels:
        parts.append(f"Killed {len(tunnel_labels)} tunnel(s): {', '.join(tunnel_labels)}")
    if container_labels:
        parts.append(f"Stopped {len(container_labels)} container(s): {', '.join(container_labels)}")
    msg = ". ".join(parts) + f". {failover_desc}. Auto-recovery in {duration}s."

    print(json.dumps({
        "status": "active",
        "chaos_type": chaos_type,
        "recover_token": recover_token,
        "tunnel": killed_tunnels[0]["tunnel"] if len(killed_tunnels) == 1 else None,
        "wan": killed_tunnels[0]["wan"] if len(killed_tunnels) == 1 else None,
        "tunnels_killed": [{"tunnel": k["tunnel"], "wan": k["wan"]} for k in killed_tunnels],
        "containers_killed": killed_containers,
        "failover_via": failover_desc,
        "started_at": state["started_at"],
        "expires_at": state["expires_at"],
        "duration_seconds": duration,
        "message": msg,
    }))
    _write_prom_metrics()


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
    }))
    _write_prom_metrics()


def cmd_recover(args):
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

    state = load_state()
    if not state:
        print(json.dumps({"status": "idle", "message": "No active chaos test to recover"}))
        return

    # Restore all killed tunnels first (for combined, tunnel before containers)
    tunnels_killed = state.get("tunnels_killed", [])

    restored = []
    for tk in tunnels_killed:
        if tk["asa"].startswith("vps"):
            asa_config(tk["asa"], [tk["interface"], "no shutdown"])
            restored.append(f"{tk['interface']} on NO VPS swanctl")
        else:
            asa_config(tk["asa"], [f"interface {tk['interface']}", "no shutdown"])
            restored.append(f"{tk['interface']} on {tk['asa'].upper()} ASA")

    # Restore killed DMZ — check if NIC was disconnected or containers were stopped
    containers_killed = state.get("containers_killed", [])
    nic_disconnected = any(e.get("event") == "nic_disconnect" for e in state.get("events", []))
    containers_restored = []

    if nic_disconnected:
        # Reconnect NIC(s) via Proxmox
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
    clear_state()

    # Post-recovery verification: confirm tunnels/containers actually came back
    import time
    verify_failures = []
    if tunnels_killed:
        time.sleep(10)  # Wait for IKE/BGP to re-establish
        for tk in tunnels_killed:
            if tk["asa"] == "nl":
                out = ssh_nl_asa_command([f"show interface {tk['interface']} | include line protocol"])
                if "up" not in out.lower() or "ERROR" in out:
                    verify_failures.append(f"{tk['interface']} on NL ASA still down")
            elif tk["asa"] == "gr":
                out = ssh_gr_asa_command([f"show interface {tk['interface']} | include line protocol"])
                if "up" not in out.lower() or "ERROR" in out:
                    verify_failures.append(f"{tk['interface']} on GR ASA still down")
    if containers_killed and not nic_disconnected:
        for ck in containers_killed:
            host, container = ck.get("host", ""), ck.get("container", "")
            if host and container:
                out = ssh_dmz_docker(host, f'docker ps --format "{{{{.Names}}}}" --filter name={container}')
                if container not in out:
                    verify_failures.append(f"{container} on {host} not running")

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
        "recovered_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verification": "passed" if not verify_failures else "FAILED",
        "verify_failures": verify_failures,
        "message": msg,
    }))
    _write_prom_metrics()


def main():
    parser = argparse.ArgumentParser(description="Chaos Engineering — VPN tunnel kill switch")
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start a chaos test")
    start_p.add_argument("--chaos-type", default="tunnel", choices=["tunnel", "dmz", "combined"],
                         help="Type of chaos test: tunnel (VPN), dmz (Docker containers), combined (both)")
    start_p.add_argument("--tunnel", default="", help='Tunnel label, e.g. "NL ↔ GR"')
    start_p.add_argument("--wan", default="", help='WAN label, e.g. "xs4all"')
    start_p.add_argument("--host", default="", help='DMZ host, e.g. "nldmz01" (for dmz/combined)')
    start_p.add_argument("--container", default="", help='Container name, e.g. "portfolio" (for dmz; omit for all)')
    start_p.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="Duration in seconds (max 600)")
    start_p.add_argument("--turnstile-token", default="", help="Cloudflare Turnstile verification token")
    start_p.add_argument("--tunnels", default=None, help='Multi-tunnel JSON: [{"tunnel":"NL ↔ GR","wan":"xs4all"},...]')
    start_p.add_argument("--params-b64", default=None,
                         help="Base64-encoded JSON with all parameters (shell-safe, used by n8n)")

    sub.add_parser("status", help="Get current chaos test status")
    recover_p = sub.add_parser("recover", help="Manually recover (restore tunnel)")
    recover_p.add_argument("--turnstile-token", default="", help="Cloudflare Turnstile verification token")
    recover_p.add_argument("--params-b64", default=None,
                           help="Base64-encoded JSON with turnstile token (shell-safe, used by n8n)")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "recover":
        cmd_recover(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
