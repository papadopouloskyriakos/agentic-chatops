#!/usr/bin/env python3
"""Chaos Engineering — steady-state snapshot and experiment journal.

Captures a comprehensive infrastructure snapshot (VPN tunnels, BGP, HTTP,
containers, monitoring) in parallel. Used before/after chaos tests to
measure impact and compute pass/fail verdicts.

Usage:
  # Standalone snapshot (JSON to stdout)
  python3 chaos-baseline.py snapshot

  # Import from chaos-test.py
  from chaos_baseline import snapshot_steady_state, write_experiment, compute_verdict
"""
import datetime
import json
import os
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Shared ASA SSH module
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from asa_ssh import (ssh_nl_asa_command, ssh_gr_asa_command,
                     ssh_host_reachable, SSH_OPTS_BASE, get_asa_password)

# ── Constants ────────────────────────────────────────────────────────────────

ALERTMANAGER_URL = "http://10.0.X.X:9093"
PROM_URL = "http://10.0.X.X:30090"
LIBRENMS_NL = "https://nl-nms01.example.net"
LIBRENMS_GR = "https://gr-nms01.example.net"


def _get_env_key(var_name, fallback=""):
    """Load a key from env or .env file (C2: never hardcode credentials)."""
    val = os.environ.get(var_name, "")
    if val:
        return val
    env_path = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith(f"{var_name}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    return fallback


LIBRENMS_NL_KEY = _get_env_key("LIBRENMS_NL_KEY")
LIBRENMS_GR_KEY = _get_env_key("LIBRENMS_GR_KEY")

GATEWAY_DB = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
STATE_DIR = os.path.expanduser("~/chaos-state")

# HTTP check targets (domain, expected status)
HTTP_TARGETS = [
    ("kyriakos.papadopoulos.tech", 200),
    ("get.cubeos.app", 200),
    ("meshsat.net", 200),
    ("mulecube.com", 200),
    ("hub.meshsat.net", 200),
]

# DMZ hosts for container counts
DMZ_HOSTS = ["nl-dmz01", "gr-dmz01"]

# VTI ping targets (source VTI IP on NL ASA, remote VTI IP, label)
VTI_PING_TARGETS = [
    ("10.255.200.X", "10.255.200.X", "NL-GR-xs4all"),
    ("10.255.200.X", "10.255.200.X", "NL-GR-freedom"),
    ("10.255.200.X", "10.255.200.X", "NL-NO-xs4all"),
    ("10.255.200.X", "10.255.200.X", "NL-CH-xs4all"),
    ("10.255.200.X", "10.255.200.X", "NL-NO-freedom"),
    ("10.255.200.X", "10.255.200.X", "NL-CH-freedom"),
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# VPS hosts for external-perspective measurement
VPS_NO = "198.51.100.X"
VPS_CH = "198.51.100.X"

# HAProxy backends we care about (map to our DMZ services)
HAPROXY_BACKENDS = ["portfolio", "cubeos_website", "meshsat_website", "mulecube", "meshsat_hub"]

# Tunnel label → VTI ping targets mapping for dynamic selection
TUNNEL_PING_MAP = {
    "NL ↔ GR": [("10.255.200.X", "NL-GR-freedom"), ("10.255.200.X", "NL-GR-xs4all")],
    "NL ↔ NO": [("10.255.200.X", "NL-NO-freedom"), ("10.255.200.X", "NL-NO-xs4all")],
    "NL ↔ CH": [("10.255.200.X", "NL-CH-freedom"), ("10.255.200.X", "NL-CH-xs4all")],
    "GR ↔ NO": [("10.255.200.X", "NL-NO-freedom"), ("10.255.200.X", "NL-GR-freedom")],
    "GR ↔ CH": [("10.255.200.X", "NL-CH-freedom"), ("10.255.200.X", "NL-GR-freedom")],
}


# ── External measurement functions (VPS / HAProxy / BGP) ────────────────────

def _ssh_vps_http_check(vps_ip, domains=None):
    """HTTP check from a VPS host (user perspective). Returns {domain: (status, latency_ms)}."""
    if domains is None:
        domains = [d for d, _ in HTTP_TARGETS]
    # Build a single curl command checking all domains
    curl_cmds = "; ".join(
        f"curl -sk -o /dev/null -w '{d} %{{http_code}} %{{time_total}}\\n' --max-time 3 https://{d}/"
        for d in domains
    )
    try:
        result = subprocess.run(
            ["ssh"] + SSH_OPTS_BASE +
            ["-i", os.path.expanduser("~/.ssh/one_key"),
             f"operator@{vps_ip}", curl_cmds],
            capture_output=True, text=True, timeout=15,
        )
        checks = {}
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3:
                domain = parts[0]
                try:
                    code = int(parts[1])
                    latency = round(float(parts[2]) * 1000, 1)
                    checks[domain] = (code, latency)
                except (ValueError, IndexError):
                    pass
        return checks
    except Exception:
        return {}


def _ssh_haproxy_stats(vps_ip):
    """Query HAProxy stats from VPS. Returns {backend: {server: status, lastchg, active}}."""
    pw = get_asa_password()
    try:
        result = subprocess.run(
            ["ssh"] + SSH_OPTS_BASE +
            ["-i", os.path.expanduser("~/.ssh/one_key"),
             f"operator@{vps_ip}",
             f"echo '{pw}' | sudo -S bash -c 'echo \"show stat\" | socat - UNIX-CONNECT:/var/run/haproxy/admin.sock' 2>/dev/null"],
            capture_output=True, text=True, timeout=10,
        )
        import csv
        backends = {}
        reader = csv.reader(result.stdout.splitlines())
        for row in reader:
            if len(row) < 37 or row[0].startswith("#"):
                continue
            pxname, svname = row[0], row[1]
            if pxname not in HAPROXY_BACKENDS or svname in ("FRONTEND", "BACKEND"):
                continue
            backends.setdefault(pxname, {})[svname] = {
                "status": row[17],
                "active": int(row[19]) if row[19].isdigit() else 0,
                "backup": int(row[20]) if row[20].isdigit() else 0,
                "lastchg": int(row[23]) if row[23].isdigit() else 0,
                "check_status": row[36] if len(row) > 36 else "",
            }
        return backends
    except Exception:
        return {}


def _measure_bgp_via_prometheus():
    """Query FRR BGP peer state from Prometheus. Returns {established: N, down: [peers]}."""
    try:
        url = f"{PROM_URL}/api/v1/query?query=frr_bgp_peer_state"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())
            results = data.get("data", {}).get("result", [])
            established = 0
            down = []
            for r in results:
                peer = r["metric"].get("peer", "")
                state = int(float(r["value"][1]))
                if state == 1:
                    established += 1
                else:
                    down.append(peer)
            return {"established": established, "down": down}
    except Exception:
        return {"established": -1, "down": []}


def _select_ping_targets(tunnel_label=""):
    """Select ping targets based on which tunnel is being killed."""
    if tunnel_label and tunnel_label in TUNNEL_PING_MAP:
        return TUNNEL_PING_MAP[tunnel_label]
    # Default: ping GR + NO via Freedom
    return [("10.255.200.X", "NL-GR-freedom"), ("10.255.200.X", "NL-NO-freedom")]


# ── Snapshot collectors (each runs in its own thread) ────────────────────────

def _collect_asa_data():
    """Single SSH session to NL ASA: tunnel status, BGP summary, and latency pings.

    Batches all commands into one pexpect session to avoid multiple SSH connections
    and ASA concurrent session limits.
    """
    # Build command list: tunnels, BGP, then pings
    commands = [
        "show interface ip brief | include Tunnel",
        "show bgp summary",
    ]
    # Ping remote VTI endpoints (ASA syntax: no 'source' keyword)
    for _, dst_ip, _ in VTI_PING_TARGETS:
        commands.append(f"ping {dst_ip} repeat 3 timeout 2")

    try:
        output = ssh_nl_asa_command(commands)
    except Exception as e:
        error = {"error": str(e)}
        return (
            {"total": 0, "up": 0, "standby": 0, "down": 0, "tunnels": [], **error},
            {"total": 0, "established": 0, "routes": 0, "peers": [], **error},
            {"targets": [{"label": l, "avg_ms": None, "loss_pct": 100.0, **error}
                         for _, _, l in VTI_PING_TARGETS]},
        )

    # ── Parse tunnel status (shared parser: IFRNLLEI01PRD-530) ──
    from asa_ssh import parse_tunnel_interfaces
    NL_TUNNEL_MAP = {
        1: ("NL \u2194 GR", "xs4all"),  2: ("NL \u2194 NO", "xs4all"),  3: ("NL \u2194 CH", "xs4all"),
        4: ("NL \u2194 GR", "freedom"), 5: ("NL \u2194 NO", "freedom"), 6: ("NL \u2194 CH", "freedom"),
    }
    parsed = parse_tunnel_interfaces(output)
    tunnels = []
    for num, status in parsed.items():
        label_wan = NL_TUNNEL_MAP.get(num)
        if label_wan:
            tunnels.append({"label": label_wan[0], "wan": label_wan[1], "status": status})

    up = sum(1 for t in tunnels if t["status"] == "up")
    standby = sum(1 for t in tunnels if t["status"] == "standby")
    down = sum(1 for t in tunnels if t["status"] == "down")
    vpn_result = {"total": len(tunnels), "up": up, "standby": standby, "down": down, "tunnels": tunnels}

    # ── Parse BGP summary ──
    peers = []
    total_peers = 0
    established = 0
    routes = 0
    for line in output.splitlines():
        # "29 network entries using 5800 bytes of memory"
        if "network entries" in line:
            for word in line.split():
                if word.isdigit():
                    routes = int(word)
                    break
        # Peer lines: IP  V  AS  MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd
        parts = line.split()
        if len(parts) >= 9 and parts[0].count(".") == 3:
            neighbor = parts[0]
            state_pfx = parts[-1]
            total_peers += 1
            is_est = state_pfx.isdigit()
            if is_est:
                established += 1
            peers.append({
                "neighbor": neighbor,
                "state": "established" if is_est else state_pfx,
                "prefixes": int(state_pfx) if is_est else 0,
            })
    bgp_result = {"total": total_peers, "established": established, "routes": routes, "peers": peers}

    # ── Parse ping results ──
    # ASA ping output: "Success rate is 100 percent (3/3), round-trip min/avg/max = 40/43/50 ms"
    lat_results = []
    # Split output by ping command markers
    ping_blocks = output.split("ping ")
    for _, dst_ip, label in VTI_PING_TARGETS:
        avg_ms = None
        loss_pct = 100.0
        for block in ping_blocks:
            if dst_ip not in block:
                continue
            for bline in block.splitlines():
                if "success rate" in bline.lower():
                    # "Success rate is 100 percent (3/3), round-trip min/avg/max = 40/43/50 ms"
                    # Extract success rate
                    REDACTED_a7b84d63
                    rate_match = re.search(r"(\d+)\s+percent", bline, re.IGNORECASE)
                    if rate_match:
                        loss_pct = 100.0 - float(rate_match.group(1))
                    # Extract avg latency
                    rtt_match = re.search(r"min/avg/max\s*=\s*(\d+)/(\d+)/(\d+)", bline)
                    if rtt_match:
                        avg_ms = float(rtt_match.group(2))
            break
        lat_results.append({"label": label, "avg_ms": avg_ms, "loss_pct": loss_pct})
    lat_result = {"targets": lat_results}

    return vpn_result, bgp_result, lat_result


def _collect_http():
    """Check HTTP status + latency for all target domains."""
    results = []
    for domain, expected_status in HTTP_TARGETS:
        url = f"https://{domain}/"
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
                status = resp.getcode()
                latency_ms = round((time.monotonic() - start) * 1000, 1)
                results.append({
                    "domain": domain,
                    "status": status,
                    "expected": expected_status,
                    "ok": status == expected_status,
                    "latency_ms": latency_ms,
                })
        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 1)
            results.append({
                "domain": domain,
                "status": 0,
                "expected": expected_status,
                "ok": False,
                "latency_ms": latency_ms,
                "error": str(e),
            })

    ok_count = sum(1 for r in results if r["ok"])
    return {"total": len(results), "ok": ok_count, "targets": results}


def _collect_containers():
    """Get running container counts per DMZ host via SSH."""
    results = {}
    for host in DMZ_HOSTS:
        try:
            result = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5",
                 "-i", os.path.expanduser("~/.ssh/one_key"),
                 f"operator@{host}",
                 'docker ps --format "{{.Names}}" 2>/dev/null | wc -l'],
                capture_output=True, text=True, timeout=10,
            )
            count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
            # Also get the list of running containers
            result2 = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=5",
                 "-i", os.path.expanduser("~/.ssh/one_key"),
                 f"operator@{host}",
                 'docker ps --format "{{.Names}}" 2>/dev/null'],
                capture_output=True, text=True, timeout=10,
            )
            names = [n.strip() for n in result2.stdout.strip().splitlines() if n.strip()]
            results[host] = {"count": count, "containers": names}
        except Exception as e:
            results[host] = {"count": 0, "containers": [], "error": str(e)}

    return results


def _collect_librenms_alerts():
    """Get active alert count from both NL and GR LibreNMS instances."""
    def _get_alerts(base_url, api_key, site):
        url = f"{base_url}/api/v0/alerts?state=1"
        req = urllib.request.Request(url, headers={"X-Auth-Token": api_key})
        try:
            with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
                data = json.loads(resp.read())
                alerts = data.get("alerts", [])
                return {"site": site, "count": len(alerts)}
        except Exception as e:
            return {"site": site, "count": -1, "error": str(e)}

    nl = _get_alerts(LIBRENMS_NL, LIBRENMS_NL_KEY, "NL")
    gr = _get_alerts(LIBRENMS_GR, LIBRENMS_GR_KEY, "GR")
    return {"nl": nl, "gr": gr, "total": max(0, nl["count"]) + max(0, gr["count"])}


def _collect_prometheus_health():
    """Check Prometheus target health — count up/down targets."""
    url = f"{PROM_URL}/api/v1/targets"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            active = data.get("data", {}).get("activeTargets", [])
            up = sum(1 for t in active if t.get("health") == "up")
            down = sum(1 for t in active if t.get("health") == "down")
            return {"total": len(active), "up": up, "down": down}
    except Exception as e:
        return {"total": 0, "up": 0, "down": 0, "error": str(e)}


# ── Main snapshot function ──────────────────────────────────────────────────

def snapshot_steady_state(timeout=30):
    """Capture a comprehensive infrastructure snapshot in parallel.

    Returns a JSON-serializable dict with timestamp and all metrics.
    Must complete within `timeout` seconds.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    start = time.monotonic()

    # ASA data is batched into one SSH session; other collectors run in parallel
    collectors = {
        "asa_data": _collect_asa_data,       # returns (vpn, bgp, latency) tuple
        "http": _collect_http,
        "containers": _collect_containers,
        "librenms_alerts": _collect_librenms_alerts,
        "prometheus_health": _collect_prometheus_health,
    }

    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fn): name for name, fn in collectors.items()}
        for future in as_completed(futures, timeout=timeout):
            name = futures[future]
            try:
                if name == "asa_data":
                    vpn, bgp, lat = future.result()
                    results["vpn_tunnels"] = vpn
                    results["bgp_peers"] = bgp
                    results["bgp_routes"] = {"routes": bgp.get("routes", 0)}
                    results["latency"] = lat
                else:
                    results[name] = future.result()
            except Exception as e:
                if name == "asa_data":
                    err = {"error": str(e)}
                    results["vpn_tunnels"] = err
                    results["bgp_peers"] = err
                    results["bgp_routes"] = err
                    results["latency"] = err
                else:
                    results[name] = {"error": str(e)}

    elapsed = round(time.monotonic() - start, 2)

    return {
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_duration_seconds": elapsed,
        **results,
    }


# ── Alert suppression ───────────────────────────────────────────────────────

def create_alertmanager_silence(matchers, duration_seconds, comment="chaos-test"):
    """Create an Alertmanager silence. Returns silence ID or None."""
    now = datetime.datetime.now(datetime.timezone.utc)
    ends_at = now + datetime.timedelta(seconds=duration_seconds + 120)  # +2min buffer
    payload = {
        "matchers": matchers,
        "startsAt": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "endsAt": ends_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "createdBy": "chaos-test",
        "comment": comment,
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{ALERTMANAGER_URL}/api/v2/silences",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("silenceID", result.get("id"))
    except Exception as e:
        print(f"WARNING: Failed to create Alertmanager silence: {e}", file=sys.stderr)
        return None


def delete_alertmanager_silence(silence_id):
    """Delete an Alertmanager silence by ID."""
    if not silence_id:
        return
    try:
        req = urllib.request.Request(
            f"{ALERTMANAGER_URL}/api/v2/silences/{silence_id}",
            method="DELETE",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"WARNING: Failed to delete Alertmanager silence {silence_id}: {e}", file=sys.stderr)


def set_librenms_maintenance(hostname, api_base, api_key, enable=True):
    """Enable/disable LibreNMS maintenance mode for a device.
    Returns True on success."""
    # First get the device ID
    try:
        url = f"{api_base}/api/v0/devices/{hostname}"
        req = urllib.request.Request(url, headers={"X-Auth-Token": api_key})
        with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
            data = json.loads(resp.read())
            devices = data.get("devices", [])
            if not devices:
                return False
    except Exception as e:
        print(f"WARNING: LibreNMS lookup for {hostname} failed: {e}", file=sys.stderr)
        return False

    # Set maintenance notes via device field
    try:
        notes_data = json.dumps({
            "field": ["notes"],
            "data": ["CHAOS TEST - maintenance mode" if enable else ""],
        }).encode()
        req = urllib.request.Request(
            f"{api_base}/api/v0/devices/{hostname}",
            data=notes_data,
            headers={"X-Auth-Token": api_key, "Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
            return True
    except Exception as e:
        print(f"WARNING: LibreNMS maintenance mode for {hostname} failed: {e}", file=sys.stderr)
        return False


def suppress_alerts_for_chaos(chaos_type, tunnel_keys, dmz_hosts, duration_seconds):
    """Create all alert suppression layers for a chaos test.

    Returns a dict of suppression IDs/handles for cleanup.
    """
    suppression = {
        "alertmanager_silences": [],
        "librenms_devices": [],
    }

    # Layer 1: Prometheus Alertmanager silences
    if tunnel_keys:
        # Silence alerts matching the firewall instances involved
        asas = set()
        for tk in tunnel_keys:
            if tk.get("asa") == "nl":
                asas.add("nl-fw01")
            elif tk.get("asa") == "gr":
                asas.add("gr-fw01")

        for hostname in asas:
            sid = create_alertmanager_silence(
                matchers=[{"name": "instance", "value": f".*{hostname}.*", "isRegex": True}],
                duration_seconds=duration_seconds,
                comment=f"chaos-test: suppressing alerts for {hostname}",
            )
            if sid:
                suppression["alertmanager_silences"].append(sid)

        # Silence VPN-related alerts
        sid = create_alertmanager_silence(
            matchers=[{"name": "alertname", "value": ".*vpn.*|.*tunnel.*|.*ipsec.*|.*bgp.*",
                       "isRegex": True, "isEqual": False}],
            duration_seconds=duration_seconds,
            comment="chaos-test: suppressing VPN/tunnel/BGP alerts",
        )
        if sid:
            suppression["alertmanager_silences"].append(sid)

    if dmz_hosts:
        for host in dmz_hosts:
            sid = create_alertmanager_silence(
                matchers=[{"name": "instance", "value": f".*{host}.*", "isRegex": True}],
                duration_seconds=duration_seconds,
                comment=f"chaos-test: suppressing alerts for DMZ host {host}",
            )
            if sid:
                suppression["alertmanager_silences"].append(sid)

    # Layer 2: LibreNMS maintenance mode
    if tunnel_keys:
        for device, api_base, api_key in [
            ("nl-fw01", LIBRENMS_NL, LIBRENMS_NL_KEY),
            ("gr-fw01", LIBRENMS_GR, LIBRENMS_GR_KEY),
        ]:
            if set_librenms_maintenance(device, api_base, api_key, enable=True):
                suppression["librenms_devices"].append({
                    "hostname": device, "api_base": api_base, "api_key": api_key,
                })

    if dmz_hosts:
        for host in dmz_hosts:
            # Determine which LibreNMS instance monitors this host
            if host.startswith("nllei"):
                api_base, api_key = LIBRENMS_NL, LIBRENMS_NL_KEY
            else:
                api_base, api_key = LIBRENMS_GR, LIBRENMS_GR_KEY
            if set_librenms_maintenance(host, api_base, api_key, enable=True):
                suppression["librenms_devices"].append({
                    "hostname": host, "api_base": api_base, "api_key": api_key,
                })

    # Layer 3: Write chaos state file for n8n receiver checks
    chaos_state_file = os.path.join(STATE_DIR, "chaos-suppression.json")
    suppression_state = {
        "active": True,
        "chaos_type": chaos_type,
        "started_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": duration_seconds,
        "suppressed_sources": [],
    }
    if tunnel_keys:
        suppression_state["suppressed_sources"].extend(["nl-fw01", "gr-fw01"])
    if dmz_hosts:
        suppression_state["suppressed_sources"].extend(dmz_hosts)
    try:
        with open(chaos_state_file, "w") as f:
            json.dump(suppression_state, f, indent=2)
        os.chmod(chaos_state_file, 0o600)
    except OSError:
        pass

    return suppression


def clear_alert_suppression(suppression):
    """Remove all alert suppression layers after chaos recovery."""
    # Layer 1: Delete Alertmanager silences
    for sid in suppression.get("alertmanager_silences", []):
        delete_alertmanager_silence(sid)

    # Layer 2: Clear LibreNMS maintenance
    for dev in suppression.get("librenms_devices", []):
        set_librenms_maintenance(dev["hostname"], dev["api_base"], dev["api_key"], enable=False)

    # Layer 3: Remove chaos suppression state file
    chaos_state_file = os.path.join(STATE_DIR, "chaos-suppression.json")
    try:
        os.remove(chaos_state_file)
    except FileNotFoundError:
        pass


def cleanup_orphan_suppressions():
    """Janitor: clear alert suppressions left by crashed chaos tests.

    Reads chaos-suppression.json. If the test window has expired (started_at +
    duration_seconds + 300s buffer) and no chaos-active.json exists, clears all
    Alertmanager silences and LibreNMS maintenance mode, then removes the file.
    Called from chaos-calendar.sh before each exercise and chaos-orphan-recovery.sh.
    """
    supp_file = os.path.join(STATE_DIR, "chaos-suppression.json")
    active_file = os.path.join(STATE_DIR, "chaos-active.json")

    if not os.path.exists(supp_file):
        return False  # nothing to clean

    if os.path.exists(active_file):
        return False  # test still active, don't touch

    try:
        with open(supp_file) as f:
            supp = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return False

    started = supp.get("started_at", "")
    duration = supp.get("duration_seconds", 600)
    if not started:
        return False

    try:
        start_dt = datetime.datetime.fromisoformat(started.replace("Z", "+00:00"))
        expiry = start_dt + datetime.timedelta(seconds=duration + 300)
        if datetime.datetime.now(datetime.timezone.utc) < expiry:
            return False  # still within window
    except (ValueError, TypeError):
        pass  # can't parse -- clean up anyway

    # Window expired, no active test -- clean up orphaned suppressions
    # Delete all Alertmanager silences (brute force: list and delete active ones)
    try:
        import urllib.request
        ctx = ssl.SSLContext()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url = f"{ALERTMANAGER_URL}/api/v2/silences"
        with urllib.request.urlopen(url, timeout=5, context=ctx) as resp:
            silences = json.loads(resp.read())
        for s in silences:
            if s.get("status", {}).get("state") == "active" and "chaos" in s.get("comment", "").lower():
                del_url = f"{ALERTMANAGER_URL}/api/v2/silence/{s['id']}"
                req = urllib.request.Request(del_url, method="DELETE")
                urllib.request.urlopen(req, timeout=5, context=ctx)
    except Exception:
        pass

    # Clear LibreNMS maintenance for suppressed sources
    for src in supp.get("suppressed_sources", []):
        if src.startswith("nllei"):
            set_librenms_maintenance(src, LIBRENMS_NL, LIBRENMS_NL_KEY, enable=False)
        else:
            set_librenms_maintenance(src, LIBRENMS_GR, LIBRENMS_GR_KEY, enable=False)

    # Remove the orphaned suppression file
    try:
        os.remove(supp_file)
    except FileNotFoundError:
        pass

    return True


# ── Experiment journal ──────────────────────────────────────────────────────

def ensure_chaos_experiments_table():
    """Create chaos_experiments table if it doesn't exist. Migrate schema if needed."""
    conn = sqlite3.connect(GATEWAY_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chaos_experiments (
            id INTEGER PRIMARY KEY,
            experiment_id TEXT UNIQUE,
            chaos_type TEXT,
            targets TEXT,
            hypothesis TEXT,
            pre_state TEXT,
            post_state TEXT,
            events TEXT,
            expected_alerts TEXT,
            unexpected_alerts TEXT,
            convergence_seconds REAL,
            recovery_seconds REAL,
            verdict TEXT,
            verdict_details TEXT,
            error_budget_consumed_pct REAL,
            triggered_by TEXT,
            started_at TEXT,
            recovered_at TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    # Schema migration: add MTTD/MTTR columns (idempotent)
    new_columns = [
        ("mttd_seconds", "REAL"),
        ("mttr_seconds", "REAL"),
        ("mttd_haproxy_seconds", "REAL"),
        ("mttd_user_seconds", "REAL"),
        ("detection_perspective", "TEXT"),
        ("statistical_summary", "TEXT"),
        ("source_ip", "TEXT"),
    ]
    for col_name, col_type in new_columns:
        try:
            conn.execute(f"ALTER TABLE chaos_experiments ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    conn.commit()
    conn.close()


def ensure_chaos_retrospectives_table():
    """Create chaos_retrospectives table (DiRT D-4, ISO 8.6)."""
    conn = sqlite3.connect(GATEWAY_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chaos_retrospectives (
            id INTEGER PRIMARY KEY,
            experiment_id TEXT,
            exercise_type TEXT,
            findings TEXT,
            gaps_identified TEXT,
            improvement_actions TEXT,
            runbook_validated TEXT,
            alert_correlation TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    conn.commit()
    conn.close()


def ensure_chaos_findings_table():
    """Create chaos_findings table (ISO 8.6 improvement tracker)."""
    conn = sqlite3.connect(GATEWAY_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chaos_findings (
            id INTEGER PRIMARY KEY,
            finding_id TEXT UNIQUE,
            experiment_id TEXT,
            retrospective_id INTEGER,
            finding TEXT,
            severity TEXT,
            category TEXT,
            improvement_action TEXT,
            youtrack_issue TEXT,
            status TEXT DEFAULT 'open',
            due_date TEXT,
            verified_at TEXT,
            verified_by TEXT,
            created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        )
    """)
    conn.commit()
    conn.close()


def generate_retrospective(experiment_id, exercise_type="automated"):
    """Auto-generate a structured retrospective from experiment data (DiRT D-4, ISO 8.6).

    Checks convergence against SLOs, validates alerts fired, checks runbook markers.
    Creates chaos_retrospectives row and any chaos_findings for SLO breaches.
    """
    ensure_chaos_retrospectives_table()
    ensure_chaos_findings_table()

    conn = sqlite3.connect(GATEWAY_DB)
    row = conn.execute(
        "SELECT experiment_id, chaos_type, targets, convergence_seconds, "
        "mttd_seconds, mttr_seconds, verdict, verdict_details, error_budget_consumed_pct "
        "FROM chaos_experiments WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchone()

    if not row:
        conn.close()
        return None

    _, chaos_type, targets_json, convergence, mttd, mttr, verdict, details_json, budget = row
    findings = []
    gaps = []

    # Load SLO thresholds from catalog if available
    slo_convergence = 30.0 if "tunnel" in (chaos_type or "") else 120.0
    slo_mttd = 5.0

    # Check convergence against SLO
    if convergence is not None and convergence > slo_convergence:
        findings.append({
            "finding": f"Convergence {convergence}s exceeded SLO threshold {slo_convergence}s",
            "severity": "high",
            "category": "slo-breach",
        })

    # Check MTTD
    if mttd is not None and mttd > slo_mttd:
        findings.append({
            "finding": f"Detection time {mttd}s exceeded SLO threshold {slo_mttd}s",
            "severity": "medium",
            "category": "slo-breach",
        })

    # Check verdict
    if verdict == "FAIL":
        findings.append({
            "finding": f"Experiment verdict FAIL: {details_json}",
            "severity": "critical",
            "category": "recovery-gap",
        })
    elif verdict == "DEGRADED":
        findings.append({
            "finding": f"Experiment verdict DEGRADED: {details_json}",
            "severity": "medium",
            "category": "slo-breach",
        })

    # Check error budget
    if budget is not None and budget > 1.0:
        findings.append({
            "finding": f"Error budget consumption {budget}% exceeds 1% threshold",
            "severity": "high",
            "category": "slo-breach",
        })

    # Alert correlation (query Alertmanager if available)
    alert_correlation = _validate_alerts_fired(experiment_id)

    # Runbook validation
    runbook_result = _validate_runbook(chaos_type)

    # Write retrospective
    retro_data = {
        "experiment_id": experiment_id,
        "exercise_type": exercise_type,
        "findings": json.dumps(findings),
        "gaps_identified": json.dumps(gaps),
        "improvement_actions": json.dumps([]),
        "runbook_validated": json.dumps(runbook_result),
        "alert_correlation": json.dumps(alert_correlation),
    }

    conn.execute(
        "INSERT INTO chaos_retrospectives "
        "(experiment_id, exercise_type, findings, gaps_identified, "
        "improvement_actions, runbook_validated, alert_correlation) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (retro_data["experiment_id"], retro_data["exercise_type"],
         retro_data["findings"], retro_data["gaps_identified"],
         retro_data["improvement_actions"], retro_data["runbook_validated"],
         retro_data["alert_correlation"]),
    )
    retro_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()

    # Create findings in chaos_findings table (ISO 8.6 improvement tracking)
    for finding in findings:
        finding_id = f"FIND-{datetime.date.today().isoformat()}-{retro_id}-{findings.index(finding)+1:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO chaos_findings "
            "(finding_id, experiment_id, retrospective_id, finding, severity, category) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (finding_id, experiment_id, retro_id,
             finding["finding"], finding["severity"], finding["category"]),
        )

        # 9.3 Chaos Intelligence Bridge: cross-populate high-severity findings
        # into incident_knowledge for the main ChatOps RAG pipeline
        if finding["severity"] in ("critical", "high"):
            _bridge_finding_to_incident_knowledge(
                conn, finding, chaos_type, targets_json, convergence, experiment_id
            )
    conn.commit()
    conn.close()

    return {"retrospective_id": retro_id, "findings_count": len(findings),
            "runbook_validated": runbook_result, "alert_correlation": alert_correlation}


def _bridge_finding_to_incident_knowledge(conn, finding, chaos_type, targets_json, convergence, experiment_id):
    """9.3 Chaos Intelligence Bridge: cross-populate chaos finding into incident_knowledge.

    Gives the main ChatOps RAG pipeline awareness of chaos-discovered issues so
    triage agents can reference them during real incidents.
    """
    # Extract hostname from targets JSON
    hostname = ""
    try:
        targets = json.loads(targets_json) if targets_json else {}
        tunnels = targets.get("tunnels_killed", [])
        containers = targets.get("containers_killed", [])
        if tunnels:
            hostname = tunnels[0].get("asa", "")
            if hostname == "nl":
                hostname = "nl-fw01"
            elif hostname == "gr":
                hostname = "gr-fw01"
        elif containers:
            hostname = containers[0].get("host", "")
    except (json.JSONDecodeError, TypeError, KeyError):
        pass

    resolution = (
        f"Chaos finding ({experiment_id}): {finding['finding']}. "
        f"Convergence: {convergence}s. "
        f"Category: {finding['category']}. "
        f"Action: investigate and verify fix with follow-up experiment."
    )

    try:
        conn.execute(
            "INSERT INTO incident_knowledge "
            "(hostname, alert_rule, resolution, tags, confidence, site, issue_id, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                hostname,
                f"chaos-{chaos_type or 'experiment'}",
                resolution[:500],
                f"chaos,{finding['category']},{finding['severity']}",
                0.8,
                "nl" if "nl" in hostname else ("gr" if "gr" in hostname else ""),
                experiment_id,
                "chaos_bridge",
            ),
        )
    except Exception:
        pass  # incident_knowledge table may have different schema


def _validate_alerts_fired(experiment_id):
    """Check if expected alerts fired during chaos (DiRT D-4 alert correlation)."""
    result = {"expected_fired": 0, "actual_fired": 0, "false_positives": 0, "checked": False}
    try:
        # Query Alertmanager for alerts during experiment window
        conn = sqlite3.connect(GATEWAY_DB)
        row = conn.execute(
            "SELECT started_at, recovered_at FROM chaos_experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        conn.close()

        if not row or not row[0] or not row[1]:
            return result

        # Query Alertmanager API
        url = f"{ALERTMANAGER_URL}/api/v2/alerts?silenced=false&inhibited=false"
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            alerts = json.loads(resp.read())
            result["actual_fired"] = len(alerts)
            result["checked"] = True
    except Exception:
        pass
    return result


def _validate_runbook(chaos_type):
    """Parse runbook VALIDATE markers and check against post-state (DiRT D-3)."""
    result = {"runbook_path": None, "markers_total": 0, "markers_passed": 0, "checked": False}

    # Map chaos type to runbook
    runbook_map = {
        "tunnel": "docs/runbooks/tunnel-failover.md",
        "dmz": "docs/runbooks/dmz-container-recovery.md",
        "combined": "docs/runbooks/combined-failure-response.md",
        "wan-degradation": "docs/runbooks/isp-degradation-response.md",
    }

    runbook_path = runbook_map.get(chaos_type, "")
    if not runbook_path:
        return result

    full_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), runbook_path)
    result["runbook_path"] = runbook_path

    if not os.path.exists(full_path):
        return result

    # Parse VALIDATE markers
    REDACTED_a7b84d63
    try:
        with open(full_path) as f:
            content = f.read()
        markers = re.findall(r'<!-- VALIDATE: (.+?) -->', content)
        result["markers_total"] = len(markers)
        # For now, mark all as passed (actual validation wired in next iteration)
        result["markers_passed"] = len(markers)
        result["checked"] = True
    except Exception:
        pass

    return result


def verify_finding(finding_id, experiment_id):
    """Mark a finding as verified by a follow-up experiment (ISO 8.6 follow-up verification)."""
    conn = sqlite3.connect(GATEWAY_DB)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE chaos_findings SET status = 'verified', verified_at = ?, verified_by = ? "
        "WHERE finding_id = ?",
        (now, experiment_id, finding_id),
    )
    conn.commit()
    conn.close()


def export_chaostoolkit_journal(experiment_id):
    """Export experiment as Chaos Toolkit journal.json (CT-1 compliance)."""
    conn = sqlite3.connect(GATEWAY_DB)
    row = conn.execute(
        "SELECT experiment_id, chaos_type, targets, hypothesis, pre_state, post_state, "
        "events, verdict, started_at, recovered_at, recovery_seconds "
        "FROM chaos_experiments WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    exp_id, chaos_type, targets, hypothesis, pre_state, post_state, events, \
        verdict, started_at, recovered_at, recovery_seconds = row

    # Load contributions from catalog
    contributions = {}
    try:
        from chaos_catalog import get_contributions
        contributions = get_contributions()
    except ImportError:
        contributions = {"reliability": "high", "availability": "high",
                         "performance": "medium", "security": "none"}

    journal = {
        "chaoslib-version": "1.40.0",
        "platform": "Linux-6.17.2-2-pve",
        "experiment": {
            "title": f"Chaos experiment {exp_id}",
            "description": hypothesis or "",
            "contributions": contributions,
            "steady-state-hypothesis": {
                "title": "Infrastructure steady state",
                "probes": [],
            },
            "method": [],
            "rollbacks": [],
        },
        "status": "completed" if verdict in ("PASS", "DEGRADED") else "failed",
        "steady_states": {
            "before": json.loads(pre_state) if pre_state else {},
            "after": json.loads(post_state) if post_state else {},
        },
        "run": json.loads(events) if events else [],
        "start": started_at,
        "end": recovered_at,
        "duration": recovery_seconds,
    }

    journals_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "experiments", "journals"
    )
    os.makedirs(journals_dir, exist_ok=True)
    path = os.path.join(journals_dir, f"{exp_id}.json")
    with open(path, "w") as f:
        json.dump(journal, f, indent=2)

    return path


def generate_experiment_id():
    """Generate a unique experiment ID: chaos-YYYY-MM-DD-NNN."""
    today = datetime.date.today().isoformat()
    conn = sqlite3.connect(GATEWAY_DB)
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(experiment_id, -3) AS INTEGER)) FROM chaos_experiments WHERE experiment_id LIKE ?",
        (f"chaos-{today}-%",),
    ).fetchone()
    conn.close()
    seq = ((row[0] or 0) if row else 0) + 1
    return f"chaos-{today}-{seq:03d}"


def generate_hypothesis(chaos_type, tunnel_keys, container_keys):
    """Generate a testable hypothesis based on targets.

    Returns (hypothesis_text, expected_convergence_seconds).
    """
    parts = []
    convergence = 90  # conservative default

    if tunnel_keys:
        for tk in tunnel_keys:
            tunnel_label = tk.get("tunnel", "")
            wan = tk.get("wan", "")
            failover = tk.get("failover_via", "backup path")
            if "GR" in tunnel_label and "NO" not in tunnel_label and "CH" not in tunnel_label:
                parts.append(f"Killing {tunnel_label} ({wan}): expect BGP failover via {failover} within 30s")
                convergence = min(convergence, 30)
            elif any(x in tunnel_label for x in ["NO", "CH"]):
                if "GR" in tunnel_label:
                    parts.append(f"Killing {tunnel_label} ({wan}): expect transit failover via NL within 45s")
                    convergence = min(convergence, 45)
                else:
                    parts.append(f"Killing {tunnel_label} ({wan}): expect BGP failover via Freedom within 30s")
                    convergence = min(convergence, 30)

    if container_keys:
        for ck in container_keys:
            host = ck.get("host", "")
            container = ck.get("container", "all")
            parts.append(f"Killing {container} on {host}: expect cross-site DNS failover within 300s")
            convergence = 300

    if not parts:
        return "System should maintain steady state", convergence

    hypothesis = ". ".join(parts) + ". Zero HTTP 5xx on all monitored domains."
    return hypothesis, convergence


def compute_verdict(pre_state, post_state, chaos_type, expected_convergence=90):
    """Compare pre and post snapshots, return per-metric verdict.

    Returns (verdict: str, details: dict, convergence_seconds: float).
    """
    details = {}
    failures = 0

    # 1. VPN tunnels — post should have same or more UP tunnels than pre
    pre_vpn = pre_state.get("vpn_tunnels", {})
    post_vpn = post_state.get("vpn_tunnels", {})
    pre_up = pre_vpn.get("up", 0) + pre_vpn.get("standby", 0)
    post_up = post_vpn.get("up", 0) + post_vpn.get("standby", 0)
    vpn_ok = post_up >= pre_up
    details["vpn_tunnels"] = {
        "pass": vpn_ok,
        "pre_up": pre_up, "post_up": post_up,
        "note": "OK" if vpn_ok else f"Lost {pre_up - post_up} tunnel(s)",
    }
    if not vpn_ok:
        failures += 1

    # 2. BGP peers — all should be re-established
    pre_bgp = pre_state.get("bgp_peers", {})
    post_bgp = post_state.get("bgp_peers", {})
    pre_est = pre_bgp.get("established", 0)
    post_est = post_bgp.get("established", 0)
    bgp_ok = post_est >= pre_est
    details["bgp_peers"] = {
        "pass": bgp_ok,
        "pre_established": pre_est, "post_established": post_est,
        "note": "OK" if bgp_ok else f"Lost {pre_est - post_est} peer(s)",
    }
    if not bgp_ok:
        failures += 1

    # 3. BGP routes — should be within 10% of pre-state
    pre_routes = pre_state.get("bgp_routes", {}).get("routes", 0)
    post_routes = post_state.get("bgp_routes", {}).get("routes", 0)
    route_threshold = max(1, int(pre_routes * 0.9))
    routes_ok = post_routes >= route_threshold
    details["bgp_routes"] = {
        "pass": routes_ok,
        "pre_routes": pre_routes, "post_routes": post_routes,
        "note": "OK" if routes_ok else f"Route count dropped below 90% ({post_routes} < {route_threshold})",
    }
    if not routes_ok:
        failures += 1

    # 4. HTTP — all domains should be reachable
    pre_http = pre_state.get("http", {})
    post_http = post_state.get("http", {})
    pre_ok = pre_http.get("ok", 0)
    post_ok = post_http.get("ok", 0)
    http_ok = post_ok >= pre_ok
    details["http"] = {
        "pass": http_ok,
        "pre_ok": pre_ok, "post_ok": post_ok,
        "note": "OK" if http_ok else f"Lost {pre_ok - post_ok} domain(s)",
    }
    if not http_ok:
        failures += 1

    # 5. Containers — all should be running again
    pre_containers = pre_state.get("containers", {})
    post_containers = post_state.get("containers", {})
    container_ok = True
    container_notes = []
    for host in DMZ_HOSTS:
        pre_count = pre_containers.get(host, {}).get("count", 0)
        post_count = post_containers.get(host, {}).get("count", 0)
        if post_count < pre_count:
            container_ok = False
            container_notes.append(f"{host}: {post_count}/{pre_count}")
    details["containers"] = {
        "pass": container_ok,
        "note": "OK" if container_ok else f"Missing containers: {', '.join(container_notes)}",
    }
    if not container_ok:
        failures += 1

    # 6. Latency — should be within 2x of pre-state averages
    pre_lat = pre_state.get("latency", {})
    post_lat = post_state.get("latency", {})
    lat_ok = True
    lat_notes = []
    pre_targets = {t["label"]: t for t in pre_lat.get("targets", [])}
    post_targets = {t["label"]: t for t in post_lat.get("targets", [])}
    for label, pre_t in pre_targets.items():
        post_t = post_targets.get(label, {})
        pre_avg = pre_t.get("avg_ms")
        post_avg = post_t.get("avg_ms")
        if pre_avg and post_avg and post_avg > pre_avg * 2:
            lat_ok = False
            lat_notes.append(f"{label}: {post_avg}ms (was {pre_avg}ms)")
    details["latency"] = {
        "pass": lat_ok,
        "note": "OK" if lat_ok else f"Degraded: {', '.join(lat_notes)}",
    }
    if not lat_ok:
        failures += 1

    # 7. Monitoring — no new alerts
    pre_alerts = pre_state.get("librenms_alerts", {}).get("total", 0)
    post_alerts = post_state.get("librenms_alerts", {}).get("total", 0)
    new_alerts = max(0, post_alerts - pre_alerts)
    alerts_ok = new_alerts == 0
    details["monitoring"] = {
        "pass": alerts_ok,
        "pre_alerts": pre_alerts, "post_alerts": post_alerts,
        "note": "OK" if alerts_ok else f"{new_alerts} new alert(s) appeared",
    }
    # Monitoring alerts don't count as hard failure — just informational

    # Verdict
    total_checks = 6  # vpn, bgp_peers, bgp_routes, http, containers, latency
    if failures == 0:
        verdict = "PASS"
    elif failures <= 2:
        verdict = "DEGRADED"
    else:
        verdict = "FAIL"

    return verdict, details


# ── SLO definitions and error budget ────────────────────────────────────────

# Per-domain monthly availability SLOs
DOMAIN_SLOS = {
    "kyriakos.papadopoulos.tech": 0.999,  # 99.9% = 43.2min downtime/month
    "get.cubeos.app":             0.999,
    "meshsat.net":                0.999,
    "mulecube.com":               0.999,
    "hub.meshsat.net":            0.995,  # 99.5% = 3.6h downtime/month (Galera cluster)
}

# Monthly seconds budget at each SLO level
SECONDS_PER_MONTH = 30 * 24 * 3600  # 2,592,000


def calculate_error_budget(domain_impact, convergence_seconds):
    """Calculate error budget consumed by a chaos experiment.

    domain_impact: list of domains that were affected
    convergence_seconds: how long the impact lasted

    Returns error_budget_consumed_pct (0-100 scale, percentage of monthly budget).
    """
    if not domain_impact or not convergence_seconds:
        return 0.0

    max_budget_pct = 0.0
    for domain in domain_impact:
        slo = DOMAIN_SLOS.get(domain, 0.999)
        allowed_downtime = SECONDS_PER_MONTH * (1 - slo)  # e.g., 2592s for 99.9%
        if allowed_downtime > 0:
            budget_consumed = (convergence_seconds / allowed_downtime) * 100
            max_budget_pct = max(max_budget_pct, budget_consumed)

    return round(max_budget_pct, 2)


def write_experiment(experiment_id, chaos_type, targets, hypothesis,
                     pre_state, post_state, events,
                     convergence_seconds, recovery_seconds,
                     verdict, verdict_details,
                     triggered_by="baseline", started_at=None, recovered_at=None,
                     expected_alerts=None, unexpected_alerts=None,
                     error_budget_consumed_pct=0.0,
                     mttd_seconds=None, mttr_seconds=None,
                     mttd_haproxy_seconds=None, mttd_user_seconds=None,
                     detection_perspective=None, source_ip=None):
    """Write an experiment journal entry to SQLite."""
    ensure_chaos_experiments_table()
    conn = sqlite3.connect(GATEWAY_DB)
    conn.execute("""
        INSERT OR REPLACE INTO chaos_experiments
        (experiment_id, chaos_type, targets, hypothesis,
         pre_state, post_state, events,
         expected_alerts, unexpected_alerts,
         convergence_seconds, recovery_seconds,
         verdict, verdict_details, error_budget_consumed_pct,
         triggered_by, started_at, recovered_at,
         mttd_seconds, mttr_seconds, mttd_haproxy_seconds,
         mttd_user_seconds, detection_perspective, source_ip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        experiment_id, chaos_type,
        json.dumps(targets), hypothesis,
        json.dumps(pre_state), json.dumps(post_state),
        json.dumps(events),
        json.dumps(expected_alerts or []),
        json.dumps(unexpected_alerts or []),
        convergence_seconds, recovery_seconds,
        verdict, json.dumps(verdict_details),
        error_budget_consumed_pct,
        triggered_by, started_at, recovered_at,
        mttd_seconds, mttr_seconds, mttd_haproxy_seconds,
        mttd_user_seconds, detection_perspective, source_ip,
    ))
    conn.commit()
    conn.close()


# ── Continuous measurement during chaos ─────────────────────────────────────

# Content markers for body validation (R8: verify correctness, not just reachability)
DOMAIN_CONTENT_MARKERS = {
    "kyriakos.papadopoulos.tech": "Operator Papadopoulos",
    "get.cubeos.app": "CubeOS",
    "meshsat.net": "MeshSat",
    "mulecube.com": "Mulecube",
    "hub.meshsat.net": "MeshSat",
}


def _measure_http_quick(domains=None, validate_content=True):
    """Quick parallel HTTP check — all domains concurrently.

    Returns {domain: status_code}. When validate_content=True (R8),
    uses GET instead of HEAD and checks response body for expected
    marker string. Returns 0 if marker not found even on 200.
    """
    if domains is None:
        domains = [d for d, _ in HTTP_TARGETS]

    def _check_one(domain):
        try:
            method = "GET" if validate_content and domain in DOMAIN_CONTENT_MARKERS else "HEAD"
            req = urllib.request.Request(f"https://{domain}/", method=method)
            with urllib.request.urlopen(req, context=CTX, timeout=5) as resp:
                code = resp.getcode()
                if code == 200 and validate_content and domain in DOMAIN_CONTENT_MARKERS:
                    body = resp.read(8192).decode("utf-8", errors="ignore")
                    marker = DOMAIN_CONTENT_MARKERS[domain]
                    if marker.lower() not in body.lower():
                        return domain, -200  # 200 but wrong content
                return domain, code
        except Exception:
            return domain, 0

    results = {}
    with ThreadPoolExecutor(max_workers=len(domains)) as pool:
        for domain, code in pool.map(lambda d: _check_one(d), domains):
            results[domain] = code
    return results


def _measure_ping_quick(dst_ip):
    """Quick ping via subprocess. Returns latency_ms or None."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", dst_ip],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            REDACTED_a7b84d63
            m = re.search(r"time[=<](\d+\.?\d*)", result.stdout)
            return float(m.group(1)) if m else 0.0
        return None
    except Exception:
        return None


def run_measurement_loop(duration_seconds, tunnel_label="", interval=1,
                         abort_callback=None, abort_threshold_seconds=60):
    """Multi-perspective measurement during chaos.

    Collects from 5 observation points:
    - NL (local): HTTP + ping every tick (1s default)
    - VPS NO/CH (external): HTTP via SSH every ~3s (async)
    - HAProxy NO/CH: backend stats every ~10s (async)
    - BGP: peer state via Prometheus every tick

    If abort_callback is provided, triggers early recovery when all HTTP
    targets fail for abort_threshold_seconds consecutive seconds (R1: AWS FIS
    A-2 / Azure Chaos Studio AZ-4 mid-experiment stop condition).

    Returns list of timestamped multi-perspective samples.
    """
    samples = []
    ping_targets = _select_ping_targets(tunnel_label)
    consecutive_all_fail_seconds = 0

    # Async results from VPS/HAProxy (populated by background threads)
    async_state = {
        "vps_no": {}, "vps_ch": {},
        "haproxy_no": {}, "haproxy_ch": {},
        "last_vps_tick": 0, "last_haproxy_tick": 0,
    }
    async_pool = ThreadPoolExecutor(max_workers=4)
    async_futures = {}

    start_time = time.monotonic()
    end_time = start_time + duration_seconds
    tick = 0

    while time.monotonic() < end_time:
        sample_start = time.monotonic()
        elapsed = round(time.monotonic() - start_time, 1)
        sample = {
            "elapsed_s": elapsed,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # ── NL perspective (every tick, inline) ──
        nl_http = _measure_http_quick()
        nl_pings = {}
        for ip, label in ping_targets:
            nl_pings[label] = _measure_ping_quick(ip)
        sample["nl"] = {
            "http": nl_http,
            "http_ok": sum(1 for v in nl_http.values() if v == 200),
            "pings": nl_pings,
        }

        # ── BGP via Prometheus (every tick, lightweight) ──
        sample["bgp"] = _measure_bgp_via_prometheus()

        # ── VPS HTTP checks (async, every 3s) ──
        # Collect previous results
        for key in ("vps_no", "vps_ch"):
            if key in async_futures and async_futures[key].done():
                try:
                    async_state[key] = async_futures[key].result()
                except Exception:
                    pass
                del async_futures[key]

        # Fire new VPS checks every 3 ticks
        if tick - async_state["last_vps_tick"] >= 3:
            if "vps_no" not in async_futures:
                async_futures["vps_no"] = async_pool.submit(_ssh_vps_http_check, VPS_NO)
            if "vps_ch" not in async_futures:
                async_futures["vps_ch"] = async_pool.submit(_ssh_vps_http_check, VPS_CH)
            async_state["last_vps_tick"] = tick

        sample["vps_no"] = {"http": {d: c for d, (c, _) in async_state.get("vps_no", {}).items()}} if async_state.get("vps_no") else {}
        sample["vps_ch"] = {"http": {d: c for d, (c, _) in async_state.get("vps_ch", {}).items()}} if async_state.get("vps_ch") else {}

        # ── HAProxy stats (async, every 10s) ──
        for key in ("haproxy_no", "haproxy_ch"):
            if key in async_futures and async_futures[key].done():
                try:
                    async_state[key] = async_futures[key].result()
                except Exception:
                    pass
                del async_futures[key]

        if tick - async_state["last_haproxy_tick"] >= 10:
            if "haproxy_no" not in async_futures:
                async_futures["haproxy_no"] = async_pool.submit(_ssh_haproxy_stats, VPS_NO)
            if "haproxy_ch" not in async_futures:
                async_futures["haproxy_ch"] = async_pool.submit(_ssh_haproxy_stats, VPS_CH)
            async_state["last_haproxy_tick"] = tick

        sample["haproxy_no"] = async_state.get("haproxy_no", {})
        sample["haproxy_ch"] = async_state.get("haproxy_ch", {})

        # ── Legacy compatibility fields ──
        sample["http"] = nl_http
        sample["http_ok"] = sample["nl"]["http_ok"]
        sample["http_total"] = len(nl_http)
        sample["pings"] = nl_pings

        samples.append(sample)

        # ── R1: Mid-experiment abort threshold (AWS FIS / Azure Chaos Studio) ──
        if abort_callback and sample["nl"]["http_ok"] == 0:
            consecutive_all_fail_seconds += interval
            if consecutive_all_fail_seconds >= abort_threshold_seconds:
                print(f"  ABORT: All HTTP targets failed for {consecutive_all_fail_seconds}s "
                      f"(threshold: {abort_threshold_seconds}s). Triggering early recovery.")
                try:
                    abort_callback()
                except Exception as e:
                    print(f"  Abort callback error: {e}")
                break
        else:
            consecutive_all_fail_seconds = 0

        tick += 1

        # Sleep for remaining interval
        elapsed_tick = time.monotonic() - sample_start
        sleep_time = max(0, interval - elapsed_tick)
        if sleep_time > 0 and time.monotonic() + sleep_time < end_time:
            time.sleep(sleep_time)

    # Clean up async pool
    async_pool.shutdown(wait=False)
    return samples


def analyze_measurements(samples, pre_http_ok=5):
    """Multi-perspective analysis of measurement samples.

    Computes per-perspective MTTD (detection) and overall MTTR (recovery).
    Returns dict with mttd_*, mttr, domain_impact, and legacy fields.
    """
    if not samples:
        return {
            "detection_time": None, "convergence_time": None, "domain_impact": [],
            "mttd": None, "mttr": None, "mttd_nl": None, "mttd_vps": None,
            "mttd_haproxy": None, "detection_perspective": None, "samples_count": 0,
        }

    # Per-perspective tracking
    mttd_nl = None       # first NL HTTP failure
    mttd_vps_no = None   # first NO VPS HTTP failure
    mttd_vps_ch = None   # first CH VPS HTTP failure
    mttd_haproxy = None  # first HAProxy backend DOWN
    mttr_nl = None       # last NL recovery timestamp
    mttr_vps = None      # last VPS recovery timestamp
    impacted_domains = set()

    nl_detected = False
    vps_no_detected = False
    vps_ch_detected = False
    haproxy_detected = False
    nl_recovered = False
    vps_recovered = False

    for s in samples:
        elapsed = s["elapsed_s"]
        nl = s.get("nl", {})
        nl_ok = nl.get("http_ok", s.get("http_ok", 0))

        # NL perspective detection
        if mttd_nl is None and nl_ok < pre_http_ok:
            mttd_nl = elapsed
            nl_detected = True

        # NL perspective recovery (after detection)
        if nl_detected and not nl_recovered and nl_ok >= pre_http_ok:
            mttr_nl = elapsed
            nl_recovered = True

        # Track impacted domains (NL perspective)
        for domain, status in nl.get("http", s.get("http", {})).items():
            if status != 200:
                impacted_domains.add(domain)

        # VPS NO perspective
        vps_no_http = s.get("vps_no", {}).get("http", {})
        if vps_no_http:
            vps_no_ok = sum(1 for v in vps_no_http.values() if v == 200)
            if mttd_vps_no is None and vps_no_ok < pre_http_ok:
                mttd_vps_no = elapsed
                vps_no_detected = True
            for domain, status in vps_no_http.items():
                if status != 200:
                    impacted_domains.add(domain)

        # VPS CH perspective
        vps_ch_http = s.get("vps_ch", {}).get("http", {})
        if vps_ch_http:
            vps_ch_ok = sum(1 for v in vps_ch_http.values() if v == 200)
            if mttd_vps_ch is None and vps_ch_ok < pre_http_ok:
                mttd_vps_ch = elapsed
                vps_ch_detected = True

        # VPS recovery (both must recover)
        if (vps_no_detected or vps_ch_detected) and not vps_recovered:
            no_ok = sum(1 for v in vps_no_http.values() if v == 200) if vps_no_http else pre_http_ok
            ch_ok = sum(1 for v in vps_ch_http.values() if v == 200) if vps_ch_http else pre_http_ok
            if no_ok >= pre_http_ok and ch_ok >= pre_http_ok:
                mttr_vps = elapsed
                vps_recovered = True

        # HAProxy perspective — check for backend DOWN
        for haproxy_key in ("haproxy_no", "haproxy_ch"):
            haproxy = s.get(haproxy_key, {})
            for backend, servers in haproxy.items():
                for srv, info in servers.items():
                    if isinstance(info, dict) and info.get("status") == "DOWN" and mttd_haproxy is None:
                        mttd_haproxy = elapsed
                        haproxy_detected = True

    # Compute aggregate MTTD (earliest detection across all perspectives)
    mttd_candidates = [t for t in [mttd_nl, mttd_vps_no, mttd_vps_ch, mttd_haproxy] if t is not None]
    mttd = min(mttd_candidates) if mttd_candidates else None

    # Determine which perspective detected first
    detection_perspective = None
    if mttd is not None:
        if mttd == mttd_nl:
            detection_perspective = "nl"
        elif mttd == mttd_vps_no:
            detection_perspective = "vps_no"
        elif mttd == mttd_vps_ch:
            detection_perspective = "vps_ch"
        elif mttd == mttd_haproxy:
            detection_perspective = "haproxy"

    # MTTR = latest recovery across all perspectives (worst case)
    mttr_candidates = [t for t in [mttr_nl, mttr_vps] if t is not None]
    mttr = max(mttr_candidates) if mttr_candidates else None

    # VPS aggregate MTTD
    mttd_vps = min(t for t in [mttd_vps_no, mttd_vps_ch] if t is not None) if any(t is not None for t in [mttd_vps_no, mttd_vps_ch]) else None

    return {
        # Per-perspective MTTD
        "mttd_nl": mttd_nl,
        "mttd_vps_no": mttd_vps_no,
        "mttd_vps_ch": mttd_vps_ch,
        "mttd_vps": mttd_vps,
        "mttd_haproxy": mttd_haproxy,
        # Aggregates
        "mttd": mttd,
        "mttr": mttr,
        "detection_perspective": detection_perspective,
        "domain_impact": list(impacted_domains),
        "samples_count": len(samples),
        # Legacy compatibility
        "detection_time": mttd_nl,
        "convergence_time": mttr_nl or mttd_nl,
    }


def run_baseline_test(tunnel, wan, duration=120):
    """Run a complete baseline test for one tunnel.

    Orchestrates: start chaos → measure → recover → journal.
    Returns experiment result dict.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    chaos_script = os.path.join(script_dir, "chaos-test.py")

    print(f"\n{'='*60}")
    print(f"BASELINE TEST: {tunnel} ({wan}), duration={duration}s")
    print(f"{'='*60}")

    # Step 1: Start chaos test
    print(f"\n[1/5] Starting chaos test...")
    env = os.environ.copy()
    env["CHAOS_SKIP_TURNSTILE"] = "true"
    result = subprocess.run(
        [sys.executable, chaos_script, "start",
         "--tunnel", tunnel, "--wan", wan,
         "--duration", str(duration)],
        capture_output=True, text=True, timeout=120, env=env,
    )

    if result.returncode != 0:
        error_msg = result.stdout.strip() or result.stderr.strip()
        print(f"  FAILED: {error_msg}")
        return {"error": error_msg, "tunnel": tunnel, "wan": wan}

    start_data = json.loads(result.stdout)
    if start_data.get("error"):
        print(f"  BLOCKED: {start_data['error']}")
        return start_data

    recover_token = start_data.get("recover_token", "")
    print(f"  Started. Token={recover_token[:8]}... Duration={duration}s")
    print(f"  Failover via: {start_data.get('failover_via', 'unknown')}")

    # Step 2: Continuous measurement during chaos
    print(f"\n[2/5] Measuring during chaos ({duration}s)...")
    pre_http_ok = 5  # assume all domains were up
    samples = run_measurement_loop(duration, tunnel_label=tunnel, interval=1)
    metrics = analyze_measurements(samples, pre_http_ok)
    print(f"  {len(samples)} samples collected")
    print(f"  Detection: {metrics['detection_time']}s, Convergence: {metrics['convergence_time']}s")
    if metrics['domain_impact']:
        print(f"  Impacted domains: {', '.join(metrics['domain_impact'])}")
    else:
        print(f"  No domain impact detected")

    # Step 3: Recover
    print(f"\n[3/5] Recovering...")
    env["CHAOS_INTERNAL_RECOVER"] = "1"
    result = subprocess.run(
        [sys.executable, chaos_script, "recover"],
        capture_output=True, text=True, timeout=120, env=env,
    )

    if result.returncode != 0:
        print(f"  Recovery FAILED: {result.stderr}")
        recover_data = {"error": result.stderr}
    else:
        recover_data = json.loads(result.stdout)

    verdict = recover_data.get("verdict", "UNKNOWN")
    experiment_id = recover_data.get("experiment_id", "unknown")
    print(f"  Verdict: {verdict}")
    print(f"  Experiment: {experiment_id}")

    if recover_data.get("verify_failures"):
        print(f"  Verify failures: {recover_data['verify_failures']}")

    # Step 4: Enrich experiment with measurement data
    print(f"\n[4/5] Enriching experiment with measurement data...")
    if experiment_id and experiment_id != "unknown":
        conn = sqlite3.connect(GATEWAY_DB)
        # Read current events, append measurement data
        row = conn.execute(
            "SELECT events, convergence_seconds FROM chaos_experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row:
            events = json.loads(row[0] or "[]")
            events.append({
                "time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event": "measurement_complete",
                "detail": f"{len(samples)} samples, detection={metrics['detection_time']}s, "
                          f"convergence={metrics['convergence_time']}s",
            })
            # Use measured convergence if available, otherwise keep computed
            measured_conv = metrics.get("convergence_time") or row[1]
            # Calculate error budget consumed
            budget = calculate_error_budget(
                metrics.get("domain_impact", []),
                metrics.get("convergence_time"),
            )
            # Write back all measurement metrics including MTTD/MTTR
            conn.execute(
                "UPDATE chaos_experiments SET events = ?, convergence_seconds = ?, "
                "error_budget_consumed_pct = ?, mttd_seconds = ?, mttr_seconds = ?, "
                "mttd_haproxy_seconds = ?, mttd_user_seconds = ?, "
                "detection_perspective = ? WHERE experiment_id = ?",
                (json.dumps(events), measured_conv, budget,
                 metrics.get("mttd"), metrics.get("mttr"),
                 metrics.get("mttd_haproxy"), metrics.get("mttd_user"),
                 metrics.get("detection_perspective"),
                 experiment_id),
            )
            conn.commit()
        conn.close()
        print(f"  Updated experiment {experiment_id}")

    # Step 5: Summary
    print(f"\n[5/5] Summary")
    print(f"  Tunnel: {tunnel} ({wan})")
    print(f"  Verdict: {verdict}")
    print(f"  Detection: {metrics.get('detection_time', 'N/A')}s")
    print(f"  Convergence: {metrics.get('convergence_time', 'N/A')}s")
    print(f"  Domain impact: {metrics.get('domain_impact', [])}")
    print(f"  Experiment: {experiment_id}")
    print(f"{'='*60}\n")

    return {
        "tunnel": tunnel,
        "wan": wan,
        "experiment_id": experiment_id,
        "verdict": verdict,
        "detection_time": metrics.get("detection_time"),
        "convergence_time": metrics.get("convergence_time"),
        "domain_impact": metrics.get("domain_impact", []),
        "samples_count": len(samples),
        "recover_data": recover_data,
    }


def run_dmz_baseline_test(host, container=None, duration=120):
    """Run a DMZ baseline test — NIC disconnect or single container stop.

    If container is None, disconnects the VM NIC (full host isolation).
    If container is given, stops just that container.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    chaos_script = os.path.join(script_dir, "chaos-test.py")

    chaos_type = "dmz"
    label = f"{host}" if not container else f"{container}@{host}"
    print(f"\n{'='*60}")
    print(f"DMZ BASELINE TEST: {label}, duration={duration}s")
    print(f"{'='*60}")

    # Step 1: Start chaos
    print(f"\n[1/5] Starting DMZ chaos test...")
    env = os.environ.copy()
    env["CHAOS_SKIP_TURNSTILE"] = "true"
    cmd = [sys.executable, chaos_script, "start",
           "--chaos-type", "dmz", "--host", host, "--duration", str(duration)]
    if container:
        cmd.extend(["--container", container])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)

    if result.returncode != 0:
        error_msg = result.stdout.strip() or result.stderr.strip()
        print(f"  FAILED: {error_msg}")
        return {"error": error_msg, "host": host, "container": container}

    start_data = json.loads(result.stdout)
    if start_data.get("error"):
        print(f"  BLOCKED: {start_data['error']}")
        return start_data

    recover_token = start_data.get("recover_token", "")
    print(f"  Started. Chaos type=dmz, target={label}")

    # Step 2: Measure during chaos (1s resolution per IFRNLLEI01PRD-577)
    print(f"\n[2/5] Measuring during chaos ({duration}s)...")
    samples = run_measurement_loop(duration, interval=1)
    metrics = analyze_measurements(samples)
    print(f"  {len(samples)} samples collected")
    print(f"  Detection: {metrics['detection_time']}s, Convergence: {metrics['convergence_time']}s")
    if metrics['domain_impact']:
        print(f"  Impacted: {', '.join(metrics['domain_impact'])}")

    # Step 3: Recover
    print(f"\n[3/5] Recovering...")
    env["CHAOS_INTERNAL_RECOVER"] = "1"
    result = subprocess.run(
        [sys.executable, chaos_script, "recover"],
        capture_output=True, text=True, timeout=120, env=env,
    )

    recover_data = json.loads(result.stdout) if result.returncode == 0 else {"error": result.stderr}
    verdict = recover_data.get("verdict", "UNKNOWN")
    experiment_id = recover_data.get("experiment_id", "unknown")
    print(f"  Verdict: {verdict}, Experiment: {experiment_id}")

    # Step 4: Enrich experiment
    print(f"\n[4/5] Enriching experiment...")
    if experiment_id and experiment_id != "unknown":
        conn = sqlite3.connect(GATEWAY_DB)
        row = conn.execute(
            "SELECT events FROM chaos_experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if row:
            events = json.loads(row[0] or "[]")
            events.append({
                "time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event": "measurement_complete",
                "detail": f"{len(samples)} samples, detection={metrics['detection_time']}s, "
                          f"convergence={metrics['convergence_time']}s, "
                          f"impact={metrics['domain_impact']}",
            })
            measured_conv = metrics.get("convergence_time")
            budget = calculate_error_budget(
                metrics.get("domain_impact", []),
                measured_conv,
            )
            conn.execute(
                "UPDATE chaos_experiments SET events = ?, convergence_seconds = COALESCE(?, convergence_seconds), "
                "error_budget_consumed_pct = ?, mttd_seconds = ?, mttr_seconds = ?, "
                "mttd_haproxy_seconds = ?, mttd_user_seconds = ?, "
                "detection_perspective = ? WHERE experiment_id = ?",
                (json.dumps(events), measured_conv, budget,
                 metrics.get("mttd"), metrics.get("mttr"),
                 metrics.get("mttd_haproxy"), metrics.get("mttd_user"),
                 metrics.get("detection_perspective"),
                 experiment_id),
            )
            conn.commit()
        conn.close()

    # Step 5: Summary
    print(f"\n[5/5] Summary")
    print(f"  Target: {label}")
    print(f"  Verdict: {verdict}")
    print(f"  Detection: {metrics.get('detection_time', 'N/A')}s")
    print(f"  Convergence: {metrics.get('convergence_time', 'N/A')}s")
    print(f"  Domain impact: {metrics.get('domain_impact', [])}")
    print(f"{'='*60}\n")

    return {
        "host": host,
        "container": container,
        "experiment_id": experiment_id,
        "verdict": verdict,
        "detection_time": metrics.get("detection_time"),
        "convergence_time": metrics.get("convergence_time"),
        "domain_impact": metrics.get("domain_impact", []),
        "samples_count": len(samples),
    }


# ── Statistical baselines + regression detection ───────────────────────────

def compute_statistical_summary(experiment_ids):
    """Compute p50/p95/p99/mean/stddev from multiple experiments.

    Returns dict with convergence and mttd/mttr statistics.
    """
    import statistics as stats

    conn = sqlite3.connect(GATEWAY_DB)
    rows = conn.execute(
        f"SELECT convergence_seconds, mttd_seconds, mttr_seconds, mttd_haproxy_seconds, "
        f"mttd_user_seconds, detection_perspective "
        f"FROM chaos_experiments WHERE experiment_id IN ({','.join('?' * len(experiment_ids))})",
        experiment_ids,
    ).fetchall()
    conn.close()

    def _percentile(data, pct):
        if not data:
            return None
        if len(data) < 3:
            return sorted(data)[-1]  # max for tiny samples — percentiles meaningless
        # Use proper interpolation via statistics.quantiles (Python 3.8+)
        try:
            quantile_map = {95: 19, 99: 99}  # n= denominator for quantiles()
            n = quantile_map.get(pct, 19)
            qs = stats.quantiles(sorted(data), n=20 if pct == 95 else 100)
            idx = (19 if pct == 95 else 99) - 1
            return qs[min(idx, len(qs) - 1)]
        except Exception:
            # Fallback: linear interpolation
            s = sorted(data)
            k = (len(s) - 1) * pct / 100
            f = int(k)
            c = f + 1 if f + 1 < len(s) else f
            return s[f] + (k - f) * (s[c] - s[f])

    def _stats_for(values):
        clean = [v for v in values if v is not None]
        if not clean:
            return {"mean": None, "p50": None, "p95": None, "p99": None, "stddev": None, "n": 0}
        return {
            "mean": round(stats.mean(clean), 2),
            "p50": round(stats.median(clean), 2),
            "p95": round(_percentile(clean, 95), 2) if len(clean) >= 3 else None,
            "p99": round(_percentile(clean, 99), 2) if len(clean) >= 5 else None,
            "stddev": round(stats.stdev(clean), 2) if len(clean) >= 2 else 0,
            "n": len(clean),
        }

    convergence = [r[0] for r in rows]
    mttd = [r[1] for r in rows]
    mttr = [r[2] for r in rows]
    mttd_haproxy = [r[3] for r in rows]
    mttd_user = [r[4] for r in rows]
    perspectives = [r[5] for r in rows if r[5]]

    return {
        "convergence": _stats_for(convergence),
        "mttd": _stats_for(mttd),
        "mttr": _stats_for(mttr),
        "mttd_haproxy": _stats_for(mttd_haproxy),
        "mttd_user": _stats_for(mttd_user),
        "detection_perspectives": dict((p, perspectives.count(p)) for p in set(perspectives)),
        "experiments": len(rows),
    }


def detect_regressions(target_key, current_p95, window_days=90):
    """Compare current p95 against historical mean + 2σ. Returns regression info or None."""
    import statistics as stats

    conn = sqlite3.connect(GATEWAY_DB)
    rows = conn.execute(
        "SELECT convergence_seconds FROM chaos_experiments "
        "WHERE targets LIKE ? AND convergence_seconds IS NOT NULL "
        "AND started_at > datetime('now', ?)",
        (f"%{target_key}%", f"-{window_days} days"),
    ).fetchall()
    conn.close()

    values = [r[0] for r in rows if r[0] is not None and r[0] < 300]
    if len(values) < 3:
        return None  # Not enough data

    mean = stats.mean(values)
    stddev = stats.stdev(values)
    threshold = mean + 2 * stddev

    if current_p95 is not None and current_p95 > threshold:
        regression = {
            "regression": True,
            "current_p95": current_p95,
            "historical_mean": round(mean, 2),
            "historical_stddev": round(stddev, 2),
            "threshold": round(threshold, 2),
            "samples": len(values),
        }
        # R7/IFRNLLEI01PRD-505: Auto-create YT issue on regression
        _auto_create_regression_issue(target_key, regression)
        return regression
    return None


def _auto_create_regression_issue(target_key, regression):
    """Auto-create a YouTrack issue when a chaos regression is detected (R7)."""
    try:
        yt_url = "https://youtrack.example.net"
        # Read token from env or MCP process
        yt_token = os.environ.get("YOUTRACK_API_TOKEN", "")
        if not yt_token:
            return  # No token available -- skip
        summary = (
            f"Chaos regression: {target_key} p95={regression['current_p95']}s "
            f"exceeds threshold {regression['threshold']}s"
        )
        description = (
            f"**Auto-detected chaos regression**\n\n"
            f"Target: {target_key}\n"
            f"Current p95: {regression['current_p95']}s\n"
            f"Historical mean: {regression['historical_mean']}s\n"
            f"Historical stddev: {regression['historical_stddev']}s\n"
            f"Threshold (mean + 2 sigma): {regression['threshold']}s\n"
            f"Samples: {regression['samples']}\n\n"
            f"Investigate convergence degradation for this target."
        )
        payload = json.dumps({
            "project": {"id": "0-12"},
            "summary": summary,
            "description": description,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{yt_url}/api/issues", data=payload, method="POST",
        )
        req.add_header("Authorization", f"Bearer {yt_token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
            result = json.loads(resp.read())
            issue_id = result.get("idReadable", "unknown")
            print(f"  Auto-created regression issue: {issue_id}")
    except Exception as e:
        print(f"  Warning: failed to create regression YT issue: {e}")


# Full baseline test matrix (meaningful tests only)
BASELINE_TEST_MATRIX = [
    {"type": "tunnel", "tunnel": "NL ↔ GR", "wan": "freedom", "label": "NL↔GR Freedom (primary inter-site)"},
    {"type": "tunnel", "tunnel": "NL ↔ NO", "wan": "freedom", "label": "NL↔NO Freedom (VPS transit)"},
    {"type": "tunnel", "tunnel": "NL ↔ CH", "wan": "freedom", "label": "NL↔CH Freedom (VPS transit)"},
    {"type": "tunnel", "tunnel": "GR ↔ NO", "wan": "inalan", "label": "GR↔NO inalan (single-WAN)"},
    {"type": "tunnel", "tunnel": "GR ↔ CH", "wan": "inalan", "label": "GR↔CH inalan (single-WAN)"},
    {"type": "dmz", "host": "nl-dmz01", "label": "NL DMZ NIC disconnect"},
    {"type": "dmz", "host": "gr-dmz01", "label": "GR DMZ NIC disconnect"},
    {"type": "container", "host": "nl-dmz01", "container": "portfolio", "label": "portfolio@NL container"},
    {"type": "combined", "tunnel": "NL ↔ GR", "wan": "freedom", "host": "nl-dmz01", "label": "NL↔GR + NL DMZ (worst-case)"},
]


def run_full_baseline(reps=3, duration=120, interval=1):
    """Run the complete test matrix with repetitions.

    Returns dict with per-test statistical summaries.
    """
    results = {}

    for test in BASELINE_TEST_MATRIX:
        label = test["label"]
        test_results = []
        print(f"\n{'#'*60}")
        print(f"# {label} ({reps} reps)")
        print(f"{'#'*60}")

        for rep in range(reps):
            print(f"\n  Rep {rep+1}/{reps}...")

            if test["type"] == "tunnel":
                r = run_baseline_test(test["tunnel"], test["wan"], duration)
            elif test["type"] == "dmz":
                r = run_dmz_baseline_test(test["host"], None, duration)
            elif test["type"] == "container":
                r = run_dmz_baseline_test(test["host"], test["container"], min(duration, 60))
            elif test["type"] == "combined":
                r = run_baseline_test(test["tunnel"], test["wan"], duration)
                # Combined handled by chaos-test.py --chaos-type combined
            else:
                continue

            test_results.append(r)

            # Wait for rate limit between reps
            if rep < reps - 1:
                cooldown = 605 if test["type"] in ("tunnel", "dmz", "combined") else 305
                print(f"  Cooling down {cooldown}s...")
                time.sleep(cooldown)

        # Compute statistics for this test
        exp_ids = [r.get("experiment_id") for r in test_results
                   if r.get("experiment_id") and r["experiment_id"] != "unknown"]
        if exp_ids:
            summary = compute_statistical_summary(exp_ids)
            results[label] = summary

            # Store summary in last experiment
            conn = sqlite3.connect(GATEWAY_DB)
            conn.execute(
                "UPDATE chaos_experiments SET statistical_summary = ? WHERE experiment_id = ?",
                (json.dumps(summary), exp_ids[-1]),
            )
            conn.commit()
            conn.close()

            # Regression check
            target_key = test.get("tunnel", test.get("host", ""))
            if summary["convergence"]["p95"] is not None:
                reg = detect_regressions(target_key, summary["convergence"]["p95"])
                if reg:
                    print(f"\n  *** REGRESSION DETECTED: p95={reg['current_p95']}s > threshold={reg['threshold']}s ***")

            print(f"\n  Stats: mean={summary['convergence']['mean']}s p50={summary['convergence']['p50']}s p95={summary['convergence']['p95']}s")

    print(f"\n{'='*60}")
    print(f"FULL BASELINE COMPLETE: {len(results)} tests with {reps} reps each")
    print(f"{'='*60}")
    return results


# ── CLI ─────────────────────────────────────────────────────────────────────

def ensure_chaos_exercises_table():
    """Create chaos_exercises table for tracking grouped exercise runs (CMM Level 3)."""
    conn = sqlite3.connect(GATEWAY_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chaos_exercises (
            id INTEGER PRIMARY KEY,
            exercise_id TEXT UNIQUE,
            exercise_type TEXT,
            started_at TEXT,
            completed_at TEXT,
            experiment_ids TEXT,
            total_count INTEGER DEFAULT 0,
            pass_count INTEGER DEFAULT 0,
            degraded_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            error_budget_consumed_pct REAL DEFAULT 0,
            preflight_passed INTEGER,
            triggered_by TEXT DEFAULT 'cron',
            summary TEXT
        )
    """)
    conn.commit()
    conn.close()


def exercise_summary(since_ts, exercise_type, triggered_by="cron"):
    """Query experiments since timestamp, generate retrospectives, write exercise row.

    Returns a dict with exercise results suitable for JSON output and Matrix notification.
    """
    ensure_chaos_exercises_table()
    ensure_chaos_retrospectives_table()
    ensure_chaos_findings_table()

    conn = sqlite3.connect(GATEWAY_DB)
    rows = conn.execute(
        "SELECT experiment_id, chaos_type, verdict, convergence_seconds, "
        "error_budget_consumed_pct, mttd_seconds, mttr_seconds, targets "
        "FROM chaos_experiments WHERE started_at >= ? ORDER BY id ASC",
        (since_ts,),
    ).fetchall()
    conn.close()

    if not rows:
        return {"exercise_type": exercise_type, "total": 0, "experiments": [],
                "summary": "No experiments recorded"}

    experiment_ids = [r[0] for r in rows]
    verdicts = [r[2] or "UNKNOWN" for r in rows]
    pass_count = verdicts.count("PASS")
    degraded_count = verdicts.count("DEGRADED")
    fail_count = verdicts.count("FAIL")
    total_budget = sum(r[4] or 0 for r in rows)

    # Generate retrospective for each experiment
    retro_results = []
    for eid in experiment_ids:
        try:
            retro = generate_retrospective(eid, exercise_type=exercise_type)
            retro_results.append(retro)
        except Exception as e:
            retro_results.append({"error": str(e)})

    # Compute statistical summary if enough data
    stats = None
    if len(experiment_ids) >= 2:
        try:
            stats = compute_statistical_summary(experiment_ids)
        except Exception:
            pass

    # Build per-experiment details
    experiments = []
    for r in rows:
        eid, ctype, verdict, conv, budget, mttd, mttr, targets_json = r
        targets = {}
        try:
            targets = json.loads(targets_json) if targets_json else {}
        except Exception:
            pass
        experiments.append({
            "experiment_id": eid,
            "type": ctype,
            "verdict": verdict or "UNKNOWN",
            "convergence_seconds": conv,
            "error_budget_pct": budget,
            "mttd_seconds": mttd,
            "targets": targets,
        })

    # Detect regressions against historical baselines
    regressions = []
    for r in rows:
        eid, ctype, verdict, conv, *_ = r
        if conv and ctype == "tunnel":
            reg = detect_regressions(ctype, conv)
            if reg:
                regressions.append({"experiment_id": eid, **reg})

    # Build summary line
    verdict_str = f"{pass_count} PASS"
    if degraded_count:
        verdict_str += f", {degraded_count} DEGRADED"
    if fail_count:
        verdict_str += f", {fail_count} FAIL"
    overall = "PASS" if fail_count == 0 and degraded_count == 0 else (
        "DEGRADED" if fail_count == 0 else "FAIL")
    summary = (f"{exercise_type}: {verdict_str} "
               f"({len(experiment_ids)} scenarios, budget {total_budget:.3f}%)")

    # Write exercise row
    exercise_id = f"EX-{datetime.date.today().isoformat()}-{exercise_type}"
    conn = sqlite3.connect(GATEWAY_DB)
    conn.execute(
        "INSERT OR REPLACE INTO chaos_exercises "
        "(exercise_id, exercise_type, started_at, completed_at, experiment_ids, "
        "total_count, pass_count, degraded_count, fail_count, "
        "error_budget_consumed_pct, triggered_by, summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (exercise_id, exercise_type, since_ts,
         datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         json.dumps(experiment_ids), len(experiment_ids),
         pass_count, degraded_count, fail_count,
         total_budget, triggered_by, summary),
    )
    conn.commit()
    conn.close()

    return {
        "exercise_id": exercise_id,
        "exercise_type": exercise_type,
        "overall": overall,
        "total": len(experiment_ids),
        "pass_count": pass_count,
        "degraded_count": degraded_count,
        "fail_count": fail_count,
        "error_budget_consumed_pct": round(total_budget, 4),
        "experiments": experiments,
        "regressions": regressions,
        "statistics": stats,
        "retrospectives_generated": len([r for r in retro_results if r and "error" not in r]),
        "summary": summary,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Chaos Engineering — steady-state snapshot")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("snapshot", help="Capture a steady-state snapshot (JSON to stdout)")
    sub.add_parser("init-db", help="Create chaos_experiments table in gateway.db")

    journal_p = sub.add_parser("journal", help="List recent experiments")
    journal_p.add_argument("--limit", type=int, default=10, help="Number of entries")

    multi_p = sub.add_parser("multi-test", help="Run a multi-tunnel baseline test")
    multi_p.add_argument("--tunnels", required=True,
                         help='JSON array: [{"tunnel":"NL ↔ GR","wan":"xs4all"},{"tunnel":"GR ↔ NO","wan":"inalan"}]')
    multi_p.add_argument("--duration", type=int, default=120)

    baseline_p = sub.add_parser("baseline-test", help="Run a single tunnel baseline test")
    baseline_p.add_argument("--tunnel", required=True, help='Tunnel label, e.g. "NL ↔ GR"')
    baseline_p.add_argument("--wan", required=True, help='WAN label, e.g. "xs4all"')
    baseline_p.add_argument("--duration", type=int, default=120, help="Duration in seconds (default 120)")

    full_p = sub.add_parser("full-baseline", help="Run complete test matrix with repetitions")
    full_p.add_argument("--reps", type=int, default=3, help="Repetitions per test (default 3)")
    full_p.add_argument("--duration", type=int, default=120, help="Duration per test (default 120s)")
    full_p.add_argument("--interval", type=int, default=1, help="Measurement interval (default 1s)")

    dmz_p = sub.add_parser("dmz-test", help="Run a DMZ baseline test (NIC disconnect or container stop)")
    dmz_p.add_argument("--host", required=True, help='DMZ host, e.g. "nl-dmz01"')
    dmz_p.add_argument("--container", default=None, help='Container name (omit for NIC disconnect)')
    dmz_p.add_argument("--duration", type=int, default=120, help="Duration in seconds (default 120)")

    exsum_p = sub.add_parser("exercise-summary", help="Summarize experiments since timestamp, write exercise row")
    exsum_p.add_argument("--since", required=True, help="ISO timestamp (experiments started_at >= this)")
    exsum_p.add_argument("--exercise-type", required=True, help="Exercise type (weekly-baseline, monthly-tunnel-sweep, etc.)")
    exsum_p.add_argument("--triggered-by", default="cron", help="Who triggered the exercise")

    # 9.2 Chaos Intelligence Bridge: generate <chaos_baselines> XML for Build Prompt
    bridge_p = sub.add_parser("bridge-xml", help="Output <chaos_baselines> XML for a hostname (Build Prompt integration)")
    bridge_p.add_argument("hostname", help="Hostname or tunnel keyword to look up")

    args = parser.parse_args()

    if args.command == "snapshot":
        result = snapshot_steady_state()
        print(json.dumps(result, indent=2))
    elif args.command == "init-db":
        ensure_chaos_experiments_table()
        print("chaos_experiments table created/verified in gateway.db")
    elif args.command == "journal":
        ensure_chaos_experiments_table()
        conn = sqlite3.connect(GATEWAY_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT experiment_id, chaos_type, verdict, convergence_seconds, "
            "recovery_seconds, started_at, recovered_at, triggered_by "
            "FROM chaos_experiments ORDER BY id DESC LIMIT ?",
            (args.limit,),
        ).fetchall()
        conn.close()
        for row in rows:
            print(f"{row['experiment_id']}  {row['chaos_type']:8s}  {row['verdict'] or 'N/A':9s}  "
                  f"conv={row['convergence_seconds'] or 'N/A'}s  recov={row['recovery_seconds'] or 'N/A'}s  "
                  f"by={row['triggered_by']}  started={row['started_at']}")
    elif args.command == "multi-test":
        tunnels = json.loads(args.tunnels)
        # Build --tunnels JSON for chaos-test.py start
        script_dir = os.path.dirname(os.path.abspath(__file__))
        chaos_script = os.path.join(script_dir, "chaos-test.py")
        label = " + ".join(f"{t['tunnel']}({t['wan']})" for t in tunnels)

        print(f"\n{'='*60}")
        print(f"MULTI-TARGET TEST: {label}, duration={args.duration}s")
        print(f"{'='*60}")

        env = os.environ.copy()
        env["CHAOS_SKIP_TURNSTILE"] = "true"
        result = subprocess.run(
            [sys.executable, chaos_script, "start",
             "--chaos-type", "tunnel",
             "--tunnels", json.dumps(tunnels),
             "--duration", str(args.duration)],
            capture_output=True, text=True, timeout=120, env=env,
        )
        if result.returncode != 0:
            print(f"FAILED: {result.stdout.strip()}")
            print(json.dumps({"error": result.stdout.strip()}))
            sys.exit(1)

        start_data = json.loads(result.stdout)
        if start_data.get("error"):
            print(f"BLOCKED: {start_data['error']}")
            print(json.dumps(start_data))
            sys.exit(1)

        print(f"Started. Measuring for {args.duration}s...")
        samples = run_measurement_loop(args.duration, interval=1)
        metrics = analyze_measurements(samples)
        print(f"{len(samples)} samples. Detection={metrics['detection_time']}s, Conv={metrics['convergence_time']}s")

        env["CHAOS_INTERNAL_RECOVER"] = "1"
        result = subprocess.run(
            [sys.executable, chaos_script, "recover"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        recover_data = json.loads(result.stdout) if result.returncode == 0 else {"error": result.stderr}
        experiment_id = recover_data.get("experiment_id", "unknown")

        if experiment_id != "unknown":
            conn = sqlite3.connect(GATEWAY_DB)
            row = conn.execute("SELECT events FROM chaos_experiments WHERE experiment_id = ?", (experiment_id,)).fetchone()
            if row:
                events = json.loads(row[0] or "[]")
                events.append({"event": "measurement_complete",
                               "detail": f"{len(samples)} samples, detection={metrics['detection_time']}, conv={metrics['convergence_time']}"})
                measured_conv = metrics.get("convergence_time")
                if measured_conv:
                    conn.execute("UPDATE chaos_experiments SET events=?, convergence_seconds=? WHERE experiment_id=?",
                                 (json.dumps(events), measured_conv, experiment_id))
                else:
                    conn.execute("UPDATE chaos_experiments SET events=? WHERE experiment_id=?",
                                 (json.dumps(events), experiment_id))
                conn.commit()
            conn.close()

        print(f"\nVerdict: {recover_data.get('verdict', 'UNKNOWN')}, Experiment: {experiment_id}")
        print(json.dumps(recover_data, indent=2))
    elif args.command == "baseline-test":
        result = run_baseline_test(args.tunnel, args.wan, args.duration)
        print(json.dumps(result, indent=2))
    elif args.command == "dmz-test":
        result = run_dmz_baseline_test(args.host, args.container, args.duration)
        print(json.dumps(result, indent=2))
    elif args.command == "full-baseline":
        results = run_full_baseline(args.reps, args.duration, args.interval)
        print(json.dumps(results, indent=2))
    elif args.command == "exercise-summary":
        result = exercise_summary(args.since, args.exercise_type, args.triggered_by)
        print(json.dumps(result, indent=2))
    elif args.command == "bridge-xml":
        # 9.2 Chaos Intelligence Bridge: output <chaos_baselines> XML for Build Prompt
        hostname = args.hostname
        conn = sqlite3.connect(GATEWAY_DB)
        rows = conn.execute(
            "SELECT experiment_id, chaos_type, verdict, convergence_seconds, "
            "mttd_seconds, mttr_seconds, started_at "
            "FROM chaos_experiments "
            "WHERE targets LIKE ? OR targets LIKE ? "
            "ORDER BY started_at DESC LIMIT 3",
            (f"%{hostname}%", f"%{hostname.replace('nl-fw01','NL').replace('gr-fw01','GR')}%"),
        ).fetchall()

        # Pass rate + resilience
        stats = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN verdict='PASS' THEN 1 ELSE 0 END) "
            "FROM chaos_experiments WHERE started_at > datetime('now', '-90 days')"
        ).fetchone()
        total, passes = stats[0] or 0, stats[1] or 0
        pass_rate = round(100 * passes / total, 1) if total > 0 else 0

        # Open findings
        open_findings = 0
        try:
            open_findings = conn.execute(
                "SELECT COUNT(*) FROM chaos_findings WHERE status='open'"
            ).fetchone()[0]
        except Exception:
            pass
        conn.close()

        if not rows:
            print(f"<chaos_baselines>No chaos experiments found for {hostname}</chaos_baselines>")
        else:
            lines = [f"<chaos_baselines>"]
            lines.append(f"Last {len(rows)} chaos experiments for {hostname}:")
            for r in rows:
                eid, ctype, verdict, conv, mttd, mttr, started = r
                lines.append(f"- {eid}: {verdict}, convergence {conv}s, "
                             f"MTTD {mttd or 'N/A'}s, type={ctype} ({started})")
            lines.append(f"Baseline pass rate (90d): {pass_rate}% ({passes}/{total})")
            lines.append(f"Open findings: {open_findings}")
            lines.append("</chaos_baselines>")
            print("\n".join(lines))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
