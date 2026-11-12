#!/usr/bin/env python3
"""ASA config-drift check — catches stripped access-group bindings, missing
NAT identity rules, broken SLA monitors, and an absent floating-conn timeout.

Root cause 2026-04-21 Matrix+portfolio outage: `access-group vti_access_in`
bindings were stripped from every VTI interface on both ASAs during unrelated
troubleshooting. ACL still existed; binding did not. Every VPS->NL and
site-to-site transit SYN was acl-dropped at ingress. BGP kept working because
control-plane traffic terminates on the ASA itself and bypasses the interface
ACL; that masked the outage signal.

2026-04-22 extension [IFRNLLEI01PRD-668]: add coverage for the 2 Section-1
NAT identity rules added during the budget migration (dmz_servers02 ↔
outside_budget), for SLA monitors 1+2 (Freedom + Budget failover tracking),
for track 1+2 (tied to the SLAs), and for `timeout floating-conn 0:00:30`
(required for TCP flow re-evaluation on route change). Any of these silently
going missing re-breaks BGP convergence or failover — this drift check is
the safety net.

This checker is run from cron. It queries ASA running-config for specific
fingerprints, emits Prometheus metrics, and exits non-zero on any drift.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/lib")

EXPECTED = {
    "nl-fw01": [
        "access-group vti_access_in in interface vti-gr-f",
        "access-group vti_access_in in interface vti-no-f",
        "access-group vti_access_in in interface vti-ch-f",
        "access-group outside_budget_access_in in interface outside_budget",
    ],
    "gr-fw01": [
        "access-group vti_access_in in interface vti-nl",
        "access-group vti_access_in in interface vti-nl-f",
        "access-group vti_access_in in interface vti-no",
        "access-group vti_access_in in interface vti-ch",
    ],
}

# NAT identity rules added 2026-04-21 (exempt transit traffic from the
# outside_budget failover PAT — without these, rtr01↔FRR + FRR02↔VPS BGP
# silently break). Strings match `show running-config nat | include ...`
# output verbatim.
EXPECTED_NAT = {
    "nl-fw01": [
        "nat (dmz_servers02,outside_budget) source static NET_k8s_rr NET_k8s_rr destination static NET_budget_transit NET_budget_transit no-proxy-arp route-lookup",
        "nat (dmz_servers02,outside_budget) source static NET_k8s_rr NET_k8s_rr destination static NET_vti_mesh NET_vti_mesh no-proxy-arp route-lookup",
    ],
    "gr-fw01": [],  # no equivalent rules on GR side (yet)
}

# SLA monitor IDs that must be present (and scheduled). Keyed by ASA →
# list of monitor ids. We validate the `sla monitor <id>` block header +
# `sla monitor schedule <id> life forever` presence.
EXPECTED_SLA = {
    "nl-fw01": [1, 2],  # 1=Freedom (BNG 198.51.100.X), 2=Budget (rtr01)
    "gr-fw01": [],
}

# Track objects — each bound to an SLA monitor.
EXPECTED_TRACK = {
    "nl-fw01": [
        "track 1 rtr 1 reachability",
        "track 2 rtr 2 reachability",
    ],
    "gr-fw01": [],
}

# floating-conn timeout required for TCP re-evaluation on route change.
# Absent timeout (default 0:00:00) = stale flows pinned to old interface
# during failover.
EXPECTED_TIMEOUT = {
    "nl-fw01": {"floating-conn": "0:00:30"},
    "gr-fw01": {},
}

PROM_DEFAULT = "/var/lib/node_exporter/textfile_collector/asa_binding_drift.prom"


def fetch_nl() -> dict:
    """Query nl-fw01 directly via netmiko. Returns dict of sections."""
    from netmiko import ConnectHandler
    from asa_ssh import get_asa_password, ASA_NL_HOST, ASA_USER

    pw = get_asa_password()
    if not pw:
        raise RuntimeError("CISCO_ASA_PASSWORD not in env or .env")
    dev = {
        "device_type": "cisco_asa", "host": ASA_NL_HOST,
        "username": ASA_USER, "password": pw, "secret": pw,
        "timeout": 20, "use_keys": False, "allow_agent": False,
    }
    n = ConnectHandler(**dev)
    try:
        n.enable()
        return {
            "access_group": n.send_command(
                "show run access-group | include vti|outside_budget", read_timeout=20),
            "nat": n.send_command(
                "show run nat | include dmz_servers02,outside_budget", read_timeout=20),
            "sla": n.send_command(
                "show run sla monitor", read_timeout=20),
            "track": n.send_command(
                "show run | include ^track ", read_timeout=20),
            "timeout": n.send_command(
                "show run timeout | include floating-conn", read_timeout=20),
        }
    finally:
        n.disconnect()


def fetch_gr() -> dict:
    """Query gr-fw01 via OOB stepping stone. Returns dict of sections."""
    from asa_ssh import ssh_gr_asa_command
    return {
        "access_group": ssh_gr_asa_command(["show run access-group | include vti"]),
        "nat": "",     # no NAT rules expected on GR side
        "sla": "",
        "track": "",
        "timeout": "",
    }


def check(asa: str, output: str, expected: list[str]) -> tuple[list[str], list[str]]:
    """Return (present, missing) fingerprints for the ASA from `expected`."""
    lines = {ln.strip() for ln in output.splitlines() if ln.strip()}
    present, missing = [], []
    for want in expected:
        (present if want in lines else missing).append(want)
    return present, missing


def check_sla(asa: str, sla_output: str) -> tuple[list[int], list[int]]:
    """Return (present, missing) SLA monitor ids (header + schedule both present)."""
    present, missing = [], []
    for sla_id in EXPECTED_SLA[asa]:
        has_header = f"sla monitor {sla_id}" in sla_output
        has_schedule = f"sla monitor schedule {sla_id} life forever" in sla_output
        if has_header and has_schedule:
            present.append(sla_id)
        else:
            missing.append(sla_id)
    return present, missing


def check_timeout(asa: str, timeout_output: str) -> tuple[dict, list[str]]:
    """Return (present_values {name: seconds}, missing [name])."""
    present: dict = {}
    missing: list = []
    for name, expected_val in EXPECTED_TIMEOUT[asa].items():
        needle = f"timeout {name} {expected_val}"
        if needle in timeout_output:
            # hh:mm:ss → seconds
            h, m, s = [int(x) for x in expected_val.split(":")]
            present[name] = h * 3600 + m * 60 + s
        else:
            missing.append(name)
    return present, missing


def emit_prom(results: dict, path: str) -> None:
    """Emit per-check gauges + aggregate drift counter to textfile collector."""
    tmp = pathlib.Path(path + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    lines: list = []

    # Access-group bindings (pre-existing)
    lines += [
        "# HELP asa_vti_access_group_present Whether vti_access_in / outside_budget_access_in is bound (1=present, 0=missing)",
        "# TYPE asa_vti_access_group_present gauge",
    ]
    for asa, result in results.items():
        for binding in result["ag"][0]:
            iface = binding.rsplit(" ", 1)[-1]
            lines.append(f'asa_vti_access_group_present{{asa="{asa}",interface="{iface}"}} 1')
        for binding in result["ag"][1]:
            iface = binding.rsplit(" ", 1)[-1]
            lines.append(f'asa_vti_access_group_present{{asa="{asa}",interface="{iface}"}} 0')

    # NAT identity rules (IFRNLLEI01PRD-668)
    lines += [
        "# HELP asa_nat_rule_present Whether a named NAT identity rule is present (1=present, 0=missing)",
        "# TYPE asa_nat_rule_present gauge",
    ]
    for asa, result in results.items():
        for rule in result["nat"][0]:
            label = _nat_label(rule)
            lines.append(f'asa_nat_rule_present{{asa="{asa}",rule="{label}"}} 1')
        for rule in result["nat"][1]:
            label = _nat_label(rule)
            lines.append(f'asa_nat_rule_present{{asa="{asa}",rule="{label}"}} 0')

    # SLA monitors
    lines += [
        "# HELP asa_sla_monitor_present Whether an SLA monitor (with schedule forever) is configured (1=present, 0=missing)",
        "# TYPE asa_sla_monitor_present gauge",
    ]
    for asa, result in results.items():
        for sla_id in result["sla"][0]:
            lines.append(f'asa_sla_monitor_present{{asa="{asa}",id="{sla_id}"}} 1')
        for sla_id in result["sla"][1]:
            lines.append(f'asa_sla_monitor_present{{asa="{asa}",id="{sla_id}"}} 0')

    # Track objects
    lines += [
        "# HELP asa_track_object_present Whether a track object tied to an SLA is configured (1=present, 0=missing)",
        "# TYPE asa_track_object_present gauge",
    ]
    for asa, result in results.items():
        for track in result["track"][0]:
            track_id = track.split()[1]
            lines.append(f'asa_track_object_present{{asa="{asa}",id="{track_id}"}} 1')
        for track in result["track"][1]:
            track_id = track.split()[1]
            lines.append(f'asa_track_object_present{{asa="{asa}",id="{track_id}"}} 0')

    # Timeouts (value gauge + presence gauge)
    lines += [
        "# HELP asa_floating_conn_seconds floating-conn timeout in seconds (0=disabled/missing)",
        "# TYPE asa_floating_conn_seconds gauge",
    ]
    for asa, result in results.items():
        value = result["timeout"][0].get("floating-conn", 0)
        lines.append(f'asa_floating_conn_seconds{{asa="{asa}"}} {value}')

    # Aggregate drift counter across ALL drift classes
    total_missing = 0
    for _, result in results.items():
        total_missing += len(result["ag"][1])
        total_missing += len(result["nat"][1])
        total_missing += len(result["sla"][1])
        total_missing += len(result["track"][1])
        total_missing += len(result["timeout"][1])

    lines += [
        "# HELP asa_binding_drift_total Total missing bindings/rules across ASA (access-group + NAT + SLA + track + timeout)",
        "# TYPE asa_binding_drift_total gauge",
        f"asa_binding_drift_total {total_missing}",
    ]

    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)


def _nat_label(rule: str) -> str:
    """Derive a short label from a NAT rule fingerprint."""
    # e.g. "...NET_k8s_rr NET_k8s_rr destination static NET_budget_transit..."
    # → "k8s_rr-to-budget_transit"
    try:
        tokens = rule.split()
        src = tokens[tokens.index("source") + 2]
        dst = tokens[tokens.index("destination") + 2]
        return f"{src}-to-{dst}".replace("NET_", "")
    except (ValueError, IndexError):
        return "unknown"


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prom", default=PROM_DEFAULT,
                   help="Prometheus textfile path (set '' to skip)")
    p.add_argument("--quiet", action="store_true",
                   help="Only print on drift")
    args = p.parse_args(list(argv))

    try:
        nl_sections = fetch_nl()
    except Exception as e:
        print(f"ERROR querying nl-fw01: {e}", file=sys.stderr)
        return 2
    try:
        gr_sections = fetch_gr()
    except Exception as e:
        print(f"ERROR querying gr-fw01: {e}", file=sys.stderr)
        return 2

    results = {
        "nl-fw01": {
            "ag":      check("nl-fw01", nl_sections["access_group"], EXPECTED["nl-fw01"]),
            "nat":     check("nl-fw01", nl_sections["nat"], EXPECTED_NAT["nl-fw01"]),
            "sla":     check_sla("nl-fw01", nl_sections["sla"]),
            "track":   check("nl-fw01", nl_sections["track"], EXPECTED_TRACK["nl-fw01"]),
            "timeout": check_timeout("nl-fw01", nl_sections["timeout"]),
        },
        "gr-fw01": {
            "ag":      check("gr-fw01", gr_sections["access_group"], EXPECTED["gr-fw01"]),
            "nat":     check("gr-fw01", gr_sections["nat"], EXPECTED_NAT["gr-fw01"]),
            "sla":     check_sla("gr-fw01", gr_sections["sla"]),
            "track":   check("gr-fw01", gr_sections["track"], EXPECTED_TRACK["gr-fw01"]),
            "timeout": check_timeout("gr-fw01", gr_sections["timeout"]),
        },
    }

    total_missing = 0
    for _, result in results.items():
        total_missing += len(result["ag"][1])
        total_missing += len(result["nat"][1])
        total_missing += len(result["sla"][1])
        total_missing += len(result["track"][1])
        total_missing += len(result["timeout"][1])

    if args.prom:
        try:
            emit_prom(results, args.prom)
        except Exception as e:
            print(f"WARN: could not write {args.prom}: {e}", file=sys.stderr)

    if total_missing == 0 and args.quiet:
        return 0

    for asa, result in results.items():
        ag_p, ag_m = result["ag"]
        nat_p, nat_m = result["nat"]
        sla_p, sla_m = result["sla"]
        tr_p, tr_m = result["track"]
        to_p, to_m = result["timeout"]
        total = (len(ag_p)+len(ag_m)+len(nat_p)+len(nat_m)+len(sla_p)+len(sla_m)
                 +len(tr_p)+len(tr_m)+len(to_p)+len(to_m))
        passed = len(ag_p)+len(nat_p)+len(sla_p)+len(tr_p)+len(to_p)
        print(f"{asa}: {passed}/{total} checks present")
        for b in ag_m:   print(f"  MISSING access-group: {b}")
        for b in nat_m:  print(f"  MISSING NAT rule    : {b}")
        for i in sla_m:  print(f"  MISSING SLA monitor : sla monitor {i}")
        for b in tr_m:   print(f"  MISSING track       : {b}")
        for n in to_m:   print(f"  MISSING timeout     : timeout {n}")

    if total_missing:
        print(f"\nDRIFT DETECTED: {total_missing} missing item(s) across access-group + NAT + SLA + track + timeout")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
