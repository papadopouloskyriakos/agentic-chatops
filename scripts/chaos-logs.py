#!/usr/bin/env python3
"""Fetch raw syslog entries related to an active or recent chaos test.

SSHes to syslog-ng servers, greps for tunnel/IKE/BGP events around the
chaos test window. Returns sanitized raw log lines as proof of real hardware.

Called by n8n webhook. Output: JSON with timestamped log entries per device.
"""
import json
import datetime
import os
import subprocess
import sys

# Shared ASA SSH module
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from asa_ssh import get_asa_password

STATE_DIR = os.path.expanduser("~/chaos-state")
STATE_FILE = os.path.join(STATE_DIR, "chaos-active.json")
HISTORY_FILE = os.path.join(STATE_DIR, "chaos-history.json")

# Syslog servers (both reachable via VPN from nl-claude01)
NL_SYSLOG = "nlsyslogng01"
GR_SYSLOG = "grsyslogng01"


# get_asa_password imported from lib.asa_ssh (replaces local _get_sudo_password)

# Map tunnel kills to relevant log sources and grep patterns
TUNNEL_LOG_MAP = {
    ("NL ↔ GR", "xs4all"): {
        "nl_hosts": ["nl-fw01"],
        "gr_hosts": ["gr-fw01"],
        "patterns": ["Tunnel1|vti-gr|203.0.113.X|shutdown|no shutdown|line protocol|IKE_SA|CHILD_SA|DPD"],
    },
    ("NL ↔ NO", "xs4all"): {
        "nl_hosts": ["nl-fw01", "nlstrongswan01"],
        "gr_hosts": [],
        "patterns": ["Tunnel2|vti-no|185.125.171.172|shutdown|no shutdown|line protocol|IKE_SA|CHILD_SA|DPD"],
    },
    ("NL ↔ CH", "xs4all"): {
        "nl_hosts": ["nl-fw01", "nlstrongswan01"],
        "gr_hosts": [],
        "patterns": ["Tunnel3|vti-ch|185.44.82.32|shutdown|no shutdown|line protocol|IKE_SA|CHILD_SA|DPD"],
    },
    ("GR ↔ NO", "inalan"): {
        "nl_hosts": [],
        "gr_hosts": ["gr-fw01"],
        "patterns": ["Tunnel2|vti-no|185.125.171.172|shutdown|no shutdown|line protocol|IKE_SA|CHILD_SA|DPD"],
    },
    ("GR ↔ CH", "inalan"): {
        "nl_hosts": [],
        "gr_hosts": ["gr-fw01"],
        "patterns": ["Tunnel3|vti-ch|185.44.82.32|shutdown|no shutdown|line protocol|IKE_SA|CHILD_SA|DPD"],
    },
}

# IPs to sanitize (replace with labels)
SANITIZE = {
    "192.168.181.": "10.NL.mgmt.",
    "192.168.85.": "10.NL.k8s.",
    "192.168.192.": "10.NL.dmz.",
    "192.168.2.": "10.GR.mgmt.",
    "192.168.58.": "10.GR.k8s.",
    "192.168.15.": "10.GR.dmz.",
    "192.168.87.": "10.NL.coro.",
    "192.168.187.": "10.GR.coro.",
}

def sanitize_line(line):
    """Replace internal IPs with labels.

    SANITIZE prefixes (192.168.x.) are disjoint from public/VTI IPs,
    so replacing them never affects public addresses.
    """
    for ip_prefix, label in SANITIZE.items():
        line = line.replace(ip_prefix, label)
    return line


def ssh_grep_logs(syslog_host, hostname, date_str, pattern, time_window=None):
    """SSH to syslog server and grep for pattern in host's log file.

    Both NL and GR syslog servers are reachable via VPN from nl-claude01.
    """
    # date_str format: "YYYY-MM-DD" — extract year/month for directory path
    year = date_str[:4]
    month = date_str[5:7]
    log_path = f"/mnt/logs/syslog-ng/{hostname}/{year}/{month}/{hostname}-{date_str}.log"

    grep_cmd = f"grep -E '{pattern}' {log_path} 2>/dev/null"
    if time_window:
        grep_cmd += f" | grep -E '{time_window}'"
    grep_cmd += " | tail -30"

    cmd = [
        "ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
        "-i", os.path.expanduser("~/.ssh/one_key"),
        f"root@{syslog_host}", grep_cmd
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        return lines
    except Exception:
        return []


def get_chaos_window():
    """Get the time window of the current or most recent chaos test."""
    # Check active test
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
            start = state["started_at"]
            return start, None, state
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # Check history (includes tunnel details since scenarios update)
    try:
        with open(HISTORY_FILE) as f:
            history = json.load(f)
            if history:
                last = history[-1]
                # Build a pseudo-state with tunnel info
                pseudo_state = {
                    "started_at": last["started_at"],
                    "tunnels_killed": [],
                    "tunnel": None, "wan": None,
                }
                # Parse tunnels from history
                for t_str in last.get("tunnels", []):
                    # Format: "GR ↔ NO (inalan)"
                    if "(" in t_str:
                        tunnel = t_str.split(" (")[0]
                        wan = t_str.split("(")[1].rstrip(")")
                        pseudo_state["tunnels_killed"].append({"tunnel": tunnel, "wan": wan})
                        if not pseudo_state["tunnel"]:
                            pseudo_state["tunnel"] = tunnel
                            pseudo_state["wan"] = wan
                return last["started_at"], last.get("duration_seconds", 600), pseudo_state
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    return None, None, None


def build_time_window(start_str, duration=None):
    """Build a grep pattern for the time window (HH:MM range, minute-level)."""
    start = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    if duration:
        end = start + datetime.timedelta(seconds=duration + 120)  # +2min buffer
    else:
        end = start + datetime.timedelta(minutes=15)  # default window

    # Generate minute-level HH:MM patterns for precise log filtering
    patterns = set()
    t = start
    while t <= end:
        patterns.add(t.strftime("%H:%M"))
        t += datetime.timedelta(minutes=1)

    return "|".join(sorted(patterns))


def main():
    # Validate session token (prevents unauthenticated log access)
    # Token arrives base64-encoded from n8n (shell-safe transport)
    import argparse
    import base64
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default="", help="Base64-encoded session recover_token")
    args = parser.parse_args()
    try:
        args.token = base64.b64decode(args.token).decode() if args.token else ""
    except Exception:
        args.token = ""

    # Check token against active chaos state
    try:
        with open(STATE_FILE) as f:
            state_data = json.load(f)
            expected_token = state_data.get("recover_token", "")
            if expected_token and args.token != expected_token:
                print(json.dumps({"status": "unauthorized", "message": "Invalid session token", "logs": []}))
                return
    except (FileNotFoundError, json.JSONDecodeError):
        # No active test — allow historical log access without token
        pass

    start_str, duration, active_state = get_chaos_window()

    if not start_str:
        print(json.dumps({
            "status": "no_data",
            "message": "No active or recent chaos test found.",
            "logs": [],
        }))
        return

    # Determine which tunnels were killed
    tunnels_killed = []
    if active_state:
        for tk in active_state.get("tunnels_killed", []):
            tunnels_killed.append((tk["tunnel"], tk["wan"]))
        if not tunnels_killed and active_state.get("tunnel"):
            tunnels_killed.append((active_state["tunnel"], active_state["wan"]))
    else:
        # From history — we don't store tunnel details, so grep broadly
        tunnels_killed = []

    # Build date string
    start_dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
    date_str = start_dt.strftime("%Y-%m-%d")
    time_window = build_time_window(start_str, duration)

    # Collect logs from all relevant sources
    all_logs = []

    if tunnels_killed:
        # Targeted grep per killed tunnel
        for tk in tunnels_killed:
            log_map = TUNNEL_LOG_MAP.get(tk, {})
            pattern = "|".join(log_map.get("patterns", ["shutdown|Tunnel|vti"]))

            for host in log_map.get("nl_hosts", []):
                lines = ssh_grep_logs(NL_SYSLOG, host, date_str, pattern, time_window)
                for line in lines:
                    all_logs.append({"source": host, "raw": sanitize_line(line)})

            for host in log_map.get("gr_hosts", []):
                lines = ssh_grep_logs(GR_SYSLOG, host, date_str, pattern, time_window)
                for line in lines:
                    all_logs.append({"source": host, "raw": sanitize_line(line)})
    else:
        # Broad grep on ASA logs
        pattern = "shutdown|Tunnel|vti|DPD|IKE_SA|line protocol"
        lines = ssh_grep_logs(NL_SYSLOG, "nl-fw01", date_str, pattern, time_window)
        for line in lines:
            all_logs.append({"source": "nl-fw01", "raw": sanitize_line(line)})

    # Fetch DMZ Docker logs for container chaos tests
    containers_killed = []
    if active_state:
        containers_killed = active_state.get("containers_killed", [])
    if containers_killed:
        dmz_hosts_to_check = set()
        for ck in containers_killed:
            dmz_hosts_to_check.add(ck.get("host", ""))

        for dmz_host in dmz_hosts_to_check:
            if not dmz_host:
                continue
            # Build docker events command for the chaos window
            # Filter for lifecycle actions only (not healthcheck/exec noise)
            since_str = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
            docker_cmd = (
                f"docker events --since '{since_str}' --until '$(date -u +%Y-%m-%dT%H:%M:%S)' "
                f"--filter type=container "
                f"--filter event=stop --filter event=start --filter event=die "
                f"--filter event=kill --filter event=create --filter event=destroy "
                f"--format '{{{{.Time}}}} {{{{.Action}}}} {{{{.Actor.Attributes.name}}}}' "
                f"2>/dev/null | tail -30"
            )

            try:
                if dmz_host not in ("nldmz01", "gr-dmz01"):
                    continue
                # Both DMZ hosts reachable via direct SSH over VPN
                result = subprocess.run(
                    ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
                     "-i", os.path.expanduser("~/.ssh/one_key"),
                     f"operator@{dmz_host}", f"bash -c \"{docker_cmd}\""],
                    capture_output=True, text=True, timeout=15,
                )

                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line:
                        all_logs.append({"source": dmz_host, "raw": line})
            except Exception:
                pass

    # Fetch VPS logs directly via SSH (journal + FRR)
    vps_hosts = {
        "185.125.171.172": "notrf01vps01",
        "185.44.82.32": "chzrh01vps01",
    }
    for vps_ip, vps_name in vps_hosts.items():
        try:
            # Get charon/IKE and FRR/BGP logs from journal + FRR log file
            result = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5",
                 "-i", os.path.expanduser("~/.ssh/one_key"),
                 f"operator@{vps_ip}",
                 f"echo '{get_asa_password()}' | sudo -S bash -c '"
                 f"journalctl _COMM=charon --since \"{start_dt.strftime('%Y-%m-%d %H:%M')}\" "
                 f"--until \"{(start_dt + datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M')}\" "
                 f"--no-pager -q 2>/dev/null | grep -iE \"IKE_SA|CHILD_SA|peer|establish|delete|rekey\" | tail -15; "
                 f"grep -E \"BGP|peer|Established|Active|route\" /var/log/frr/frr.log 2>/dev/null | "
                 f"grep \"{start_dt.strftime('%Y/%m/%d %H:')}\" | tail -10'"],
                capture_output=True, text=True, timeout=15,
            )
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line:
                    all_logs.append({"source": vps_name, "raw": sanitize_line(line)})
        except Exception:
            pass

    # Sort by timestamp (syslog format: "Apr  9 HH:MM:SS")
    all_logs.sort(key=lambda x: x["raw"])

    # Deduplicate
    seen = set()
    deduped = []
    for log in all_logs:
        key = log["raw"]
        if key not in seen:
            seen.add(key)
            deduped.append(log)

    output = {
        "status": "active" if active_state else "historical",
        "chaos_start": start_str,
        "tunnels_killed": [f"{t[0]} ({t[1]})" for t in tunnels_killed] if tunnels_killed else [],
        "containers_killed": [f"{c['container']}@{c['host']}" for c in containers_killed],
        "log_sources": list(set(l["source"] for l in deduped)),
        "log_count": len(deduped),
        "logs": deduped[-50:],  # Last 50 entries max
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
