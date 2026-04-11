#!/usr/bin/env python3
"""Predictive alerting script — queries LibreNMS API for NL and GR sites,
computes per-device risk scores, and produces a risk report.

Output modes:
  (default)   Human-readable report to stdout
  --json      Full JSON report to stdout
  --prom      Write Prometheus metrics to textfile collector
  --matrix    Post top-N digest to Matrix #alerts room
  --top N     Show top N devices (default 10)

Uses only stdlib (no pip dependencies). Handles self-signed certs.
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Timeouts (seconds)
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15

SITES = {
    "nl": {
        "base_url": "https://nl-nms01.example.net/api/v0",
        "api_key": "REDACTED_20ee4f7c",
        "timeout": READ_TIMEOUT,
    },
    "gr": {
        "base_url": "https://gr-nms01.example.net/api/v0",
        "api_key": "REDACTED_c7cb035f",
        "timeout": 30,  # cross-site VPN is slower
    },
}

PROM_OUTPUT = "/var/lib/node_exporter/textfile_collector/predictive_alerts.prom"

# Matrix config (loaded from .env)
ENV_FILE = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")
MATRIX_HOMESERVER = "https://matrix.example.net"
ALERTS_ROOM = "!xeNxtpScJWCmaFjeCL:matrix.example.net"

# SSL context that accepts self-signed certs
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg):
    """Log to stderr."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=sys.stderr)


def load_env():
    """Load .env file and return dict of key=value pairs."""
    env = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return env


def api_get(base_url, endpoint, api_key, timeout=None):
    """GET a LibreNMS API endpoint, return parsed JSON or None on error."""
    url = f"{base_url}{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("X-Auth-Token", api_key)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout or READ_TIMEOUT) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as e:
        log(f"API error {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def fetch_devices(site_cfg):
    """Fetch device list from LibreNMS. Returns dict keyed by device_id."""
    data = api_get(site_cfg["base_url"], "/devices", site_cfg["api_key"],
                   timeout=site_cfg.get("timeout", READ_TIMEOUT))
    if not data or "devices" not in data:
        return {}
    devices = {}
    for d in data["devices"]:
        did = d.get("device_id")
        if did is None:
            continue
        devices[did] = {
            "hostname": d.get("hostname", "unknown"),
            "status": d.get("status", 0),
            "uptime": d.get("uptime", 0),
            "hardware": d.get("hardware", ""),
            "os": d.get("os", ""),
            "sysName": d.get("sysName", ""),
        }
    return devices


def fetch_storage(site_cfg, devices):
    """Fetch storage data from LibreNMS.

    Tries the global /resources/storage endpoint first.  If that fails
    (404/500 on some LibreNMS versions), falls back to per-device
    /devices/{hostname}/storage for a single test device.  If the
    per-device endpoint also fails, logs a warning and returns empty.
    Returns list of dicts with hostname, storage_descr, storage_perc.
    """
    timeout = site_cfg.get("timeout", READ_TIMEOUT)

    # Try global endpoint first
    data = api_get(site_cfg["base_url"], "/resources/storage",
                   site_cfg["api_key"], timeout=timeout)
    if data:
        entries = data.get("storage", data.get("Storage", []))
        if entries:
            return entries

    # Probe a single device to see if per-device endpoint works
    test_host = None
    for did, dinfo in devices.items():
        if dinfo.get("os", "") not in ("ping", ""):
            test_host = dinfo["hostname"]
            break

    if test_host:
        probe = api_get(
            site_cfg["base_url"],
            f"/devices/{test_host}/storage",
            site_cfg["api_key"],
            timeout=CONNECT_TIMEOUT,
        )
        if not probe or "storage" not in probe:
            log("  Storage API not available on this LibreNMS version "
                "(disk risk scoring disabled)")
            return []

        # Per-device endpoint works -- fetch all devices
        log("  Using per-device storage fallback...")
        all_storage = []
        for s in probe["storage"]:
            s["hostname"] = test_host
            all_storage.append(s)
        for did, dinfo in devices.items():
            hostname = dinfo["hostname"]
            if hostname == test_host or dinfo.get("os", "") in ("ping", ""):
                continue
            per_dev = api_get(
                site_cfg["base_url"],
                f"/devices/{hostname}/storage",
                site_cfg["api_key"],
                timeout=CONNECT_TIMEOUT,
            )
            if per_dev and "storage" in per_dev:
                for s in per_dev["storage"]:
                    s["hostname"] = hostname
                    all_storage.append(s)
        return all_storage

    log("  No SNMP devices found to probe storage API")
    return []


def fetch_alerts(site_cfg, state):
    """Fetch alerts by state (1=active, 2=resolved). Returns list."""
    data = api_get(site_cfg["base_url"], f"/alerts?state={state}",
                   site_cfg["api_key"],
                   timeout=site_cfg.get("timeout", READ_TIMEOUT))
    if not data:
        return []
    return data.get("alerts", [])


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

def compute_disk_risk(storage_entries, hostname):
    """Compute disk risk for a device. Returns (score, worst_partition, worst_pct)."""
    partitions = [s for s in storage_entries if s.get("hostname") == hostname]
    if not partitions:
        return 0, None, 0

    worst_pct = 0
    worst_part = None
    for p in partitions:
        pct = p.get("storage_perc", 0)
        if pct is None:
            continue
        try:
            pct = float(pct)
        except (ValueError, TypeError):
            continue
        if pct > worst_pct:
            worst_pct = pct
            worst_part = p.get("storage_descr", "unknown")

    if worst_pct >= 95:
        score = 90
    elif worst_pct >= 90:
        score = 60
    elif worst_pct >= 80:
        score = 30
    else:
        score = 0

    return score, worst_part, worst_pct


def compute_alert_risk(active_alerts, resolved_alerts, hostname):
    """Compute alert frequency risk. Returns (score, count_7d)."""
    now = time.time()
    seven_days_ago = now - (7 * 86400)

    count_7d = 0
    # Count active alerts for this device
    for a in active_alerts:
        h = a.get("hostname", "")
        if h == hostname:
            count_7d += 1

    # Count resolved alerts in last 7 days
    for a in resolved_alerts:
        h = a.get("hostname", "")
        if h != hostname:
            continue
        # Use timestamp field if available
        ts_str = a.get("timestamp", "")
        if ts_str:
            try:
                # LibreNMS timestamps: "YYYY-MM-DD HH:MM:SS"
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                if ts.timestamp() >= seven_days_ago:
                    count_7d += 1
            except (ValueError, TypeError):
                # If we can't parse, count it conservatively
                count_7d += 1
        else:
            count_7d += 1

    if count_7d > 10:
        score = 60
    elif count_7d >= 4:
        score = 30
    elif count_7d >= 1:
        score = 10
    else:
        score = 0

    return score, count_7d


def compute_health_risk(device_info):
    """Compute health risk from status and uptime. Returns (score, reasons)."""
    score = 0
    reasons = []

    status = device_info.get("status", 1)
    uptime = device_info.get("uptime", 0)

    if status != 1:
        score += 100
        reasons.append("device DOWN")

    if uptime is not None and uptime > 0 and uptime < 86400:
        score += 20
        reasons.append("recent reboot")

    return score, reasons


def score_devices(site_name, site_cfg):
    """Score all devices for a site. Returns list of risk records."""
    log(f"Fetching data for site {site_name.upper()}...")

    devices = fetch_devices(site_cfg)
    if not devices:
        log(f"  No devices found for {site_name}")
        return []

    storage = fetch_storage(site_cfg, devices)
    active_alerts = fetch_alerts(site_cfg, 1)
    resolved_alerts = fetch_alerts(site_cfg, 2)

    log(f"  {len(devices)} devices, {len(storage)} storage entries, "
        f"{len(active_alerts)} active alerts, {len(resolved_alerts)} resolved alerts")

    results = []
    for did, dinfo in devices.items():
        hostname = dinfo["hostname"]

        disk_score, disk_part, disk_pct = compute_disk_risk(storage, hostname)
        alert_score, alert_count = compute_alert_risk(
            active_alerts, resolved_alerts, hostname
        )
        health_score, health_reasons = compute_health_risk(dinfo)

        composite = min(disk_score + alert_score + health_score, 100)

        risk_factors = []
        if disk_score > 0 and disk_part:
            risk_factors.append(f"disk {disk_part} at {disk_pct:.0f}%")
        if alert_count > 0:
            risk_factors.append(f"{alert_count} alerts this week")
        risk_factors.extend(health_reasons)

        results.append({
            "hostname": hostname,
            "site": site_name,
            "risk_score": composite,
            "disk_score": disk_score,
            "disk_max_pct": round(disk_pct, 1),
            "disk_partition": disk_part,
            "alert_score": alert_score,
            "alerts_7d": alert_count,
            "health_score": health_score,
            "health_reasons": health_reasons,
            "risk_factors": risk_factors,
            "status": dinfo["status"],
            "uptime": dinfo.get("uptime", 0),
            "hardware": dinfo.get("hardware", ""),
            "os": dinfo.get("os", ""),
        })

    return results


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------

def output_json(results, top_n):
    """Print full JSON report to stdout."""
    now = datetime.now(timezone.utc).isoformat()
    at_risk = [r for r in results if r["risk_score"] > 0]
    report = {
        "generated_at": now,
        "total_devices": len(results),
        "devices_at_risk": len(at_risk),
        "top_devices": sorted(results, key=lambda x: x["risk_score"], reverse=True)[:top_n],
        "all_devices": sorted(results, key=lambda x: x["risk_score"], reverse=True),
    }
    print(json.dumps(report, indent=2))


def output_human(results, top_n):
    """Print human-readable report to stdout."""
    today = datetime.now().strftime("%Y-%m-%d")
    ranked = sorted(results, key=lambda x: x["risk_score"], reverse=True)
    at_risk = [r for r in results if r["risk_score"] > 0]

    print(f"Predictive Alert Report ({today})")
    print(f"{'=' * 50}")
    print(f"Total devices scanned: {len(results)}")
    print(f"Devices at elevated risk: {len(at_risk)}")
    print()

    if not ranked or ranked[0]["risk_score"] == 0:
        print("All devices are within normal parameters.")
        return

    print(f"Top {min(top_n, len(ranked))} devices by risk score:")
    print(f"{'-' * 50}")
    for i, r in enumerate(ranked[:top_n], 1):
        if r["risk_score"] == 0:
            break
        factors = ", ".join(r["risk_factors"]) if r["risk_factors"] else "low-level risk"
        site_tag = f"[{r['site'].upper()}]"
        print(f"  {i:2d}. {r['hostname']} {site_tag} (risk: {r['risk_score']}) -- {factors}")

    print()
    # Breakdown by site
    for site in ["nl", "gr"]:
        site_devs = [r for r in ranked if r["site"] == site and r["risk_score"] > 0]
        if site_devs:
            print(f"{site.upper()} site: {len(site_devs)} device(s) at risk")


def output_prom(results):
    """Write Prometheus metrics to textfile collector."""
    lines = []
    lines.append("# HELP predictive_risk_score Composite risk score per device (0-100)")
    lines.append("# TYPE predictive_risk_score gauge")
    lines.append("# HELP predictive_disk_max_pct Highest disk usage percentage per device")
    lines.append("# TYPE predictive_disk_max_pct gauge")
    lines.append("# HELP predictive_alerts_7d Alert count in last 7 days per device")
    lines.append("# TYPE predictive_alerts_7d gauge")
    lines.append("# HELP predictive_devices_at_risk Total devices with risk score > 0")
    lines.append("# TYPE predictive_devices_at_risk gauge")
    lines.append("# HELP predictive_last_run_timestamp Unix timestamp of last run")
    lines.append("# TYPE predictive_last_run_timestamp gauge")

    at_risk_count = 0
    for r in results:
        h = r["hostname"]
        s = r["site"]
        lines.append(f'predictive_risk_score{{hostname="{h}",site="{s}"}} {r["risk_score"]}')
        lines.append(f'predictive_disk_max_pct{{hostname="{h}",site="{s}"}} {r["disk_max_pct"]}')
        lines.append(f'predictive_alerts_7d{{hostname="{h}",site="{s}"}} {r["alerts_7d"]}')
        if r["risk_score"] > 0:
            at_risk_count += 1

    lines.append(f"predictive_devices_at_risk {at_risk_count}")
    lines.append(f"predictive_last_run_timestamp {int(time.time())}")
    lines.append("")  # trailing newline

    content = "\n".join(lines)

    # Atomic write via temp file
    tmp_path = PROM_OUTPUT + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            f.write(content)
        os.rename(tmp_path, PROM_OUTPUT)
        log(f"Wrote {len(results)} device metrics to {PROM_OUTPUT}")
    except OSError as e:
        log(f"Failed to write Prometheus metrics: {e}")
        # Fall back to stdout
        print(content)


def output_matrix(results, top_n):
    """Post top-N risk digest to Matrix #alerts room."""
    env = load_env()
    bot_token = env.get("MATRIX_CLAUDE_TOKEN", "")
    homeserver = env.get("MATRIX_HOMESERVER", MATRIX_HOMESERVER)

    if not bot_token:
        log("No MATRIX_CLAUDE_TOKEN found in .env, skipping Matrix post")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    ranked = sorted(results, key=lambda x: x["risk_score"], reverse=True)
    at_risk = [r for r in results if r["risk_score"] > 0]

    lines = []
    lines.append(f"Daily Predictive Alert Report ({today})")
    lines.append(f"Top {min(top_n, len(ranked))} devices by risk score:")
    lines.append("")

    for i, r in enumerate(ranked[:top_n], 1):
        if r["risk_score"] == 0:
            break
        factors = ", ".join(r["risk_factors"]) if r["risk_factors"] else "nominal"
        lines.append(f"{i}. {r['hostname']} (risk: {r['risk_score']}) -- {factors}")

    lines.append("")
    lines.append(f"Full report: {len(results)} devices scanned, {len(at_risk)} at elevated risk.")

    body = "\n".join(lines)

    txn_id = f"predictive-{int(time.time())}-{os.getpid()}"
    url = (
        f"{homeserver}/_matrix/client/v3/rooms/"
        f"{urllib.parse.quote(ALERTS_ROOM, safe='')}/send/m.room.message/{txn_id}"
    )

    payload = json.dumps({"msgtype": "m.notice", "body": body}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="PUT")
    req.add_header("Authorization", f"Bearer {bot_token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, context=CTX, timeout=10) as resp:
            log(f"Matrix message sent (event: {json.loads(resp.read()).get('event_id', 'ok')})")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log(f"Failed to post to Matrix: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Predictive alerting via LibreNMS API")
    parser.add_argument("--json", action="store_true", help="Output full JSON report")
    parser.add_argument("--prom", action="store_true", help="Write Prometheus metrics")
    parser.add_argument("--matrix", action="store_true", help="Post digest to Matrix")
    parser.add_argument("--top", type=int, default=10, help="Number of top devices to show")
    args = parser.parse_args()

    # Collect data from both sites
    all_results = []
    for site_name, site_cfg in SITES.items():
        try:
            results = score_devices(site_name, site_cfg)
            all_results.extend(results)
        except Exception as e:
            log(f"Error processing site {site_name}: {e}")

    if not all_results:
        log("No device data collected from any site")
        sys.exit(1)

    log(f"Scored {len(all_results)} devices total")

    # Output
    if args.json:
        output_json(all_results, args.top)
    elif args.prom:
        output_prom(all_results)
    elif args.matrix:
        output_matrix(all_results, args.top)
    else:
        output_human(all_results, args.top)


if __name__ == "__main__":
    main()
