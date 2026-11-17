"""Shared FRR (vtysh) SSH helpers.

Targets 4 FRR instances across both sites via direct SSH over the
inter-site VTI mesh:
  - nlk8s-frr01 (10.0.X.X, direct SSH as root)
  - nlk8s-frr02 (10.0.X.X, direct SSH as root)
  - grk8s-frr01 (10.0.X.X, direct SSH as root via VPN)
  - grk8s-frr02 (10.0.X.X, direct SSH as root via VPN)

Plus the VPS FRRs (notrf01vps01, chzrh01vps01) which run FRR alongside
strongSwan and need password+sudo. Exposed separately via
`ssh_vps_frr_command()` since the auth path differs.

Rationale for *not* using the OOB bastion path for GR FRRs: the watchdog
that uses this lib is itself measuring whether the inter-site mesh is
healthy. If the VPN is down, the GR FRR BGP sessions would correctly
report Idle/Active/unreachable — which is the truth we want surfaced.
Going over OOB would mask that signal and add latency + a bastion
dependency for no real resilience gain.

Public API:
  ssh_nl_frr_command(frr_id, cmds)   → str   # frr_id: 1 or 2
  ssh_gr_frr_command(frr_id, cmds)   → str   # frr_id: 1 or 2
  ssh_vps_frr_command(host, cmds)    → str   # host: 198.51.100.X / 198.51.100.X
  parse_bgp_summary(output)          → dict  # {neighbor: {state, prefix_rcd}}

Introduced 2026-04-22 as part of IFRNLLEI01PRD-671.
"""
from __future__ import annotations

import os
import subprocess

# NL FRRs — direct SSH, root, key auth
NL_FRR_HOSTS = {
    1: "10.0.X.X",
    2: "10.0.X.X",
}
# GR FRRs — direct SSH via inter-site VPN, root, key auth
GR_FRR_HOSTS = {
    1: "10.0.X.X",
    2: "10.0.X.X",
}

KEY_PATH = os.path.expanduser("~/.ssh/one_key")
SSH_OPTS = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]


def _get_pw() -> str:
    """VPS sudo password — same credential store as ASA/rtr01."""
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


def ssh_nl_frr_command(frr_id: int, commands: list) -> str:
    """Run vtysh -c '<cmd>' on an NL FRR. Joins multiple commands with `-c`."""
    if frr_id not in NL_FRR_HOSTS:
        return f"ERROR: unknown NL FRR id {frr_id}"
    host = NL_FRR_HOSTS[frr_id]
    # ssh concatenates remote args with spaces; we must shell-quote for vtysh.
    vtysh_cmd_str = "vtysh " + " ".join(f"-c '{c}'" for c in commands)
    try:
        r = subprocess.run(
            ["ssh"] + SSH_OPTS + ["-i", KEY_PATH, f"root@{host}", vtysh_cmd_str],
            capture_output=True, text=True, timeout=25,
        )
        return r.stdout if r.returncode == 0 else f"ERROR: {r.stderr or 'rc=' + str(r.returncode)}"
    except Exception as e:
        return f"ERROR: {e}"


def ssh_gr_frr_command(frr_id: int, commands: list) -> str:
    """Run vtysh on a GR FRR via direct SSH over the inter-site VPN."""
    if frr_id not in GR_FRR_HOSTS:
        return f"ERROR: unknown GR FRR id {frr_id}"
    host = GR_FRR_HOSTS[frr_id]
    vtysh_cmd_str = "vtysh " + " ".join(f"-c '{c}'" for c in commands)
    try:
        r = subprocess.run(
            ["ssh"] + SSH_OPTS + ["-i", KEY_PATH, f"root@{host}", vtysh_cmd_str],
            capture_output=True, text=True, timeout=25,
        )
        return r.stdout if r.returncode == 0 else f"ERROR: {r.stderr or 'rc=' + str(r.returncode)}"
    except Exception as e:
        return f"ERROR: {e}"


def ssh_vps_frr_command(host: str, commands: list) -> str:
    """Run vtysh on a VPS (notrf01vps01 or chzrh01vps01). Needs operator + sudo."""
    pw = _get_pw()
    if not pw:
        return "ERROR: no password"
    vtysh_cmd_str = " ".join(f"-c '{c}'" for c in commands)
    remote = f"echo '{pw}' | sudo -S vtysh {vtysh_cmd_str} 2>/dev/null"
    try:
        r = subprocess.run(
            ["ssh"] + SSH_OPTS + ["-i", KEY_PATH, f"operator@{host}", remote],
            capture_output=True, text=True, timeout=25,
        )
        return r.stdout if r.returncode == 0 else f"ERROR: {r.stderr or 'rc=' + str(r.returncode)}"
    except Exception as e:
        return f"ERROR: {e}"


def parse_bgp_summary(output: str) -> dict:
    """Parse `show bgp summary` output → {neighbor_ip: {state, prefix_rcd}}.

    Works for FRR vtysh and Cisco `show ip bgp summary`. Peer-line format:
      Neighbor  V  AS  MsgRcvd  MsgSent  TblVer  InQ  OutQ  Up/Down  State/PfxRcd ...
    Last column is an int (established, prefix count) or a state word
    (Active, Idle, Connect, OpenSent, OpenConfirm, etc.).
    """
    result = {}
    for line in output.splitlines():
        parts = line.split()
        if not parts:
            continue
        neighbor = parts[0]
        if not _looks_like_ipv4(neighbor):
            continue
        if len(parts) < 10:
            continue
        last = parts[9]
        if last.isdigit():
            result[neighbor] = {"state": "established", "prefix_rcd": int(last)}
        else:
            result[neighbor] = {"state": last.lower(), "prefix_rcd": 0}
    return result


def _looks_like_ipv4(s: str) -> bool:
    octets = s.split(".")
    if len(octets) != 4:
        return False
    try:
        return all(0 <= int(o) <= 255 for o in octets)
    except ValueError:
        return False
