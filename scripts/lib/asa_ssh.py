"""Shared ASA SSH and credential utilities.

Consolidates all ASA/VPS SSH access patterns used by chaos-test.py,
vpn-mesh-stats.py, and chaos-logs.py. Single source of truth for
credentials, SSH options, and connection logic.

Fixes: C1 (no hardcoded passwords), M3 (StrictHostKeyChecking=accept-new),
       M4 (eliminate 8x code duplication).
"""
import os
import socket
import subprocess
import sys

# ── Constants ────────────────────────────────────────────────────────────────

ASA_NL_HOST = "10.0.181.X"
ASA_USER = "operator"
GR_OOB_HOST = "203.0.113.X"
GR_OOB_PORT = "2222"
GR_OOB_USER = "app-user"
GR_ASA_HOST = "10.0.X.X"

# SSH options: accept-new trusts first connect, rejects key changes (MITM detection)
SSH_OPTS_BASE = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
SSH_OPTS_ASA = SSH_OPTS_BASE + [
    "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
    "-o", "HostKeyAlgorithms=+ssh-rsa",
    "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
]


# ── Credential management ───────────────────────────────────────────────────

def get_asa_password():
    """Get ASA/sudo password from env var or .env file. Never hardcoded."""
    pw = os.environ.get("CISCO_ASA_PASSWORD", "")
    if pw:
        return pw
    env_path = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("CISCO_ASA_PASSWORD="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    return ""


# ── NL ASA (pexpect, direct SSH) ────────────────────────────────────────────

def ssh_nl_asa_command(commands):
    """Execute show commands on NL ASA via pexpect. Returns output string."""
    import pexpect
    pw = get_asa_password()
    try:
        child = pexpect.spawn(
            "ssh " + " ".join(SSH_OPTS_ASA) + f" {ASA_USER}@{ASA_NL_HOST}",
            timeout=20, encoding="utf-8",
        )
        child.expect("[Pp]assword:")
        child.sendline(pw)
        child.expect(">")
        child.sendline("enable")
        child.expect("[Pp]assword:")
        child.sendline(pw)
        child.expect("#")
        child.sendline("terminal pager 0")
        child.expect("#")

        output = ""
        for cmd in commands:
            child.sendline(cmd)
            child.expect("#", timeout=15)
            output += child.before + "\n"

        child.sendline("exit")
        child.close()
        return output
    except Exception as e:
        return f"ERROR: {e}"


def ssh_nl_asa_config(config_commands):
    """Execute config-mode commands on NL ASA via pexpect. Returns True on success."""
    import pexpect
    pw = get_asa_password()
    try:
        child = pexpect.spawn(
            "ssh " + " ".join(SSH_OPTS_ASA) + f" {ASA_USER}@{ASA_NL_HOST}",
            timeout=20, encoding="utf-8",
        )
        child.expect("[Pp]assword:")
        child.sendline(pw)
        child.expect(">")
        child.sendline("enable")
        child.expect("[Pp]assword:")
        child.sendline(pw)
        child.expect("#")
        child.sendline("conf t")
        child.expect(r"\(config\)#")

        for cmd in config_commands:
            child.sendline(cmd)
            child.expect(["#"], timeout=15)

        child.sendline("end")
        child.expect("#")
        child.sendline("exit")
        child.close()
        return True
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return False


# ── GR ASA (netmiko via OOB stepstone) ──────────────────────────────────────
# Uses public internet path (203.0.113.X:2222 → grclaude01 → netmiko)
# so recovery commands reach the ASA even when VPN tunnels are killed.

def ssh_gr_asa_command(commands):
    """Execute show commands on GR ASA via OOB+netmiko. Returns output string."""
    pw = get_asa_password()
    py_script = f"""
from netmiko import ConnectHandler
import os
pw = os.environ.get('CISCO_ASA_PASSWORD', '')
device = {{
    'device_type': 'cisco_asa',
    'host': '{GR_ASA_HOST}',
    'username': '{ASA_USER}',
    'password': pw,
    'secret': pw,
}}
net = ConnectHandler(**device)
net.enable()
for cmd in {commands!r}:
    print(net.send_command(cmd, read_timeout=10))
net.disconnect()
"""
    try:
        result = subprocess.run(
            ["ssh", "-p", GR_OOB_PORT] + SSH_OPTS_BASE +
            ["-i", os.path.expanduser("~/.ssh/one_key"),
             f"{GR_OOB_USER}@{GR_OOB_HOST}",
             f"export CISCO_ASA_PASSWORD='{pw}'; "
             f"/tmp/netmiko-venv/bin/python3 -c \"{py_script}\""],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout
    except Exception as e:
        return f"ERROR: {e}"


def ssh_gr_asa_config(config_commands):
    """Execute config-mode commands on GR ASA via OOB+netmiko. Returns True on success."""
    pw = get_asa_password()
    py_script = f"""
from netmiko import ConnectHandler
import os
pw = os.environ.get('CISCO_ASA_PASSWORD', '')
device = {{
    'device_type': 'cisco_asa',
    'host': '{GR_ASA_HOST}',
    'username': '{ASA_USER}',
    'password': pw,
    'secret': pw,
}}
net = ConnectHandler(**device)
net.enable()
net.send_config_set({config_commands!r})
net.disconnect()
print('OK')
"""
    try:
        result = subprocess.run(
            ["ssh", "-p", GR_OOB_PORT] + SSH_OPTS_BASE +
            ["-i", os.path.expanduser("~/.ssh/one_key"),
             f"{GR_OOB_USER}@{GR_OOB_HOST}",
             f"export CISCO_ASA_PASSWORD='{pw}'; "
             f"/tmp/netmiko-venv/bin/python3 -c \"{py_script}\""],
            capture_output=True, text=True, timeout=30,
        )
        return "OK" in result.stdout
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return False


# ── VPS swanctl ─────────────────────────────────────────────────────────────

def ssh_vps_swanctl(host):
    """SSH to a VPS and get swanctl SA status. Returns dict {conn_name: 'up'|'down'}."""
    pw = get_asa_password()
    try:
        result = subprocess.run(
            ["ssh"] + SSH_OPTS_BASE +
            ["-i", os.path.expanduser("~/.ssh/one_key"),
             f"operator@{host}",
             f"echo '{pw}' | sudo -S swanctl --list-sas 2>/dev/null"],
            capture_output=True, text=True, timeout=20,
        )
        conns = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if ": #" in line and "ESTABLISHED" in line:
                name = line.split(":")[0].strip()
                conns[name] = "up"
            elif ": #" in line and "CONNECTING" in line:
                name = line.split(":")[0].strip()
                conns[name] = "down"
        return conns
    except Exception:
        return {}


# ── Connectivity checks ─────────────────────────────────────────────────────

def ssh_host_reachable(host, port=22, timeout=5):
    """Test TCP connectivity to an SSH host. Returns True if port is open."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, socket.error, OSError):
        return False


def ssh_oob_reachable(timeout=5):
    """Test GR OOB path (203.0.113.X:2222). Returns True if reachable."""
    return ssh_host_reachable(GR_OOB_HOST, int(GR_OOB_PORT), timeout)
