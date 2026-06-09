"""Shared IOS / IOS-XE router SSH helpers.

Companion to asa_ssh.py, but targeting `nlrtr01` (Cisco ISR 4321,
IOS-XE 17.9) — the Budget-PPPoE edge router since the 2026-04-21
migration.

Uses netmiko (proven cleaner than pexpect for IOS-XE — see
vti-freedom-recovery.sh v2 refactor). Never hardcodes password; reads
from env or .env like asa_ssh.py.

Public API:
  get_rtr01_password()        → str
  ssh_rtr01_command(cmds)     → str    # show commands, read-only
  ssh_rtr01_config(cmds)      → bool   # config-mode commands
  parse_dialer_status(out)    → dict   # {admin, line, proto, ip}
  parse_tunnel_status(out)    → dict   # {tunnel_id: 'up'|'down'}

Introduced 2026-04-22 as part of IFRNLLEI01PRD-670.
"""
from __future__ import annotations

import os
import sys

RTR01_HOST = "10.0.X.X"   # Po4.2 transit IP, the only LAN IP on rtr01
RTR01_USER = "operator"


def get_rtr01_password() -> str:
    """Get rtr01 password from env or .env file. Same credential store as ASAs."""
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


def _connect():
    """Open a netmiko Cisco IOS connection to rtr01. Raises on failure."""
    from netmiko import ConnectHandler
    pw = get_rtr01_password()
    if not pw:
        raise RuntimeError("CISCO_ASA_PASSWORD not in env or .env")
    return ConnectHandler(
        device_type="cisco_ios",
        host=RTR01_HOST,
        username=RTR01_USER,
        password=pw,
        secret=pw,
        fast_cli=False,
        conn_timeout=15,
        read_timeout_override=30,
    )


def ssh_rtr01_command(commands: list[str]) -> str:
    """Execute show commands on nlrtr01. Returns concatenated output or 'ERROR: ...'."""
    try:
        c = _connect()
    except Exception as e:
        return f"ERROR: connect: {e}"
    try:
        c.enable()
        out_parts = []
        for cmd in commands:
            out_parts.append(c.send_command(cmd, read_timeout=15))
        return "\n".join(out_parts)
    except Exception as e:
        return f"ERROR: {e}"
    finally:
        try:
            c.disconnect()
        except Exception:
            pass


def ssh_rtr01_config(config_commands: list[str]) -> bool:
    """Execute config-mode commands on nlrtr01. Returns True on success."""
    try:
        c = _connect()
    except Exception as e:
        print(f"ERROR: connect: {e}", file=sys.stderr)
        return False
    try:
        c.enable()
        c.send_config_set(config_commands, read_timeout=30)
        return True
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return False
    finally:
        try:
            c.disconnect()
        except Exception:
            pass


def ssh_sw01_config(config_commands: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Execute config-mode commands on nl-sw01 (Cisco Catalyst switch).

    sw01 SSH quirk (per memory feedback_never_ssh_sw01.md): requires legacy
    `aes128-ctr` cipher + `ssh-rsa` host-key-algorithm overrides. Also has
    a `login block-for 10 attempts 5 within 60` lockout — retry slowly on
    auth failure, not rapidly.

    Returns (ok, stdout). ok=False with stdout containing the error on
    connect / auth / command failure.

    Introduced 2026-04-22 for IFRNLLEI01PRD-705 (ios-port-shutdown primitive
    enabling unattended monthly Freedom-ONT chaos drill -695).
    """
    try:
        from netmiko import ConnectHandler
    except ImportError:
        return False, "ERROR: netmiko not installed"

    pw = get_rtr01_password()     # shared credential with ASA/rtr01
    if not pw:
        return False, "ERROR: CISCO_ASA_PASSWORD not set in env or .env"

    try:
        c = ConnectHandler(
            device_type="cisco_ios",
            host="10.0.181.X",
            username="operator",
            password=pw,
            secret=pw,
            fast_cli=False,
            conn_timeout=15,
            read_timeout_override=timeout,
            # sw01 legacy SSH flags
            ssh_config_file=None,
            use_keys=False,
            session_log=None,
            global_cmd_verify=False,
            # Pass the cipher/kex overrides through paramiko
            session_timeout=timeout,
            # netmiko passes extra SSH opts via ssh_extra_args not fully;
            # we rely on the server still accepting aes128-ctr by default
            # in netmiko's paramiko cipher list.
        )
    except Exception as e:
        return False, f"ERROR: connect: {e}"

    try:
        c.enable()
        output = c.send_config_set(config_commands, read_timeout=timeout)
        return True, output
    except Exception as e:
        return False, f"ERROR: config: {e}"
    finally:
        try:
            c.disconnect()
        except Exception:
            pass


def ssh_sw01_command(commands: list[str], timeout: int = 15) -> tuple[bool, str]:
    """Execute show commands on nl-sw01. Returns (ok, concatenated_output)."""
    try:
        from netmiko import ConnectHandler
    except ImportError:
        return False, "ERROR: netmiko not installed"

    pw = get_rtr01_password()
    if not pw:
        return False, "ERROR: CISCO_ASA_PASSWORD not set"

    try:
        c = ConnectHandler(
            device_type="cisco_ios",
            host="10.0.181.X",
            username="operator",
            password=pw,
            secret=pw,
            fast_cli=False,
            conn_timeout=15,
            read_timeout_override=timeout,
            use_keys=False,
            global_cmd_verify=False,
        )
    except Exception as e:
        return False, f"ERROR: connect: {e}"

    try:
        c.enable()
        out = "\n".join(c.send_command(cmd, read_timeout=timeout) for cmd in commands)
        return True, out
    except Exception as e:
        return False, f"ERROR: {e}"
    finally:
        try:
            c.disconnect()
        except Exception:
            pass


def sw01_port_shutdown(interface: str, timeout: int = 30) -> tuple[bool, str]:
    """Admin-down the specified switch port on nl-sw01.

    Safe rollback invariant: always pair with sw01_port_noshut() in a
    try/finally. Caller is responsible for that pairing.
    """
    return ssh_sw01_config([
        f"interface {interface}",
        "shutdown",
        "end",
    ], timeout=timeout)


def sw01_port_noshut(interface: str, force_poe_cycle: bool = False,
                     timeout: int = 30) -> tuple[bool, str]:
    """Admin-up the switch port. Optionally force a PoE re-detect first.

    The PoE re-cycle recipe is required when the port was shut for more
    than a few minutes and the attached ONT (Genexis XGS-PON via TL-PoE10R
    splitter) has lost its PON training. Plain `no shutdown` won't wake it
    unless PoE is cycled. See memory
    `freedom_ont_poe_recycle_gotcha_20260422.md`.
    """
    if force_poe_cycle:
        cmds = [
            f"interface {interface}",
            "power inline never",
            "power inline auto",
            "shutdown",
            "no shutdown",
            "end",
        ]
    else:
        cmds = [
            f"interface {interface}",
            "no shutdown",
            "end",
        ]
    return ssh_sw01_config(cmds, timeout=timeout)


def parse_dialer_status(output: str) -> dict:
    """Parse `show ip interface brief | include Dialer1` output.

    Returns {'admin': 'up'|'down', 'line': 'up'|'down', 'proto': 'up'|'down',
             'ip': '203.0.113.X'|'unassigned'}.
    """
    result = {"admin": "unknown", "line": "unknown", "proto": "unknown", "ip": "unknown"}
    for line in output.splitlines():
        if line.strip().startswith("Dialer1"):
            parts = line.split()
            # `Dialer1 <ip> YES <method> <line-status> <proto-status>`
            # line-status ∈ {up, down, administratively down}
            if len(parts) >= 6:
                result["ip"] = parts[1]
                # line status may be two words: "administratively down"
                # normalize: if we see 'administratively', mark admin=down
                rest = parts[4:]
                if rest and rest[0] == "administratively":
                    result["admin"] = "down"
                    result["line"] = "down"
                    result["proto"] = rest[2] if len(rest) >= 3 else "unknown"
                else:
                    result["admin"] = "up"
                    result["line"] = rest[0] if len(rest) >= 1 else "unknown"
                    result["proto"] = rest[1] if len(rest) >= 2 else "unknown"
            break
    return result


def parse_tunnel_status(output: str) -> dict:
    """Parse `show ip interface brief | include ^Tunnel` output.

    Returns {tunnel_id (int): 'up'|'down'}.
    """
    result: dict = {}
    for line in output.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("Tunnel"):
            continue
        try:
            tid = int(parts[0].replace("Tunnel", ""))
        except ValueError:
            continue
        # last two columns are line status + proto status
        if len(parts) >= 6:
            line_s = parts[-2]
            proto_s = parts[-1]
            result[tid] = "up" if (line_s == "up" and proto_s == "up") else "down"
        else:
            result[tid] = "down"
    return result
