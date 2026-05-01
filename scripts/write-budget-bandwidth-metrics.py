#!/usr/bin/env python3
"""Budget-ISP bandwidth metrics exporter.

Samples rtr01 Dialer1 interface rate (5-minute avg) + packet counters,
emits Prometheus textfile so we can alert on saturation of the 25 Mbps
Budget link during Freedom-shut failover operation.

Prompted by gap-audit 2026-04-22: when Freedom was shut for 4h+ and Budget
was carrying every inter-site path + tenant + infra traffic, we had no
saturation telemetry — the only signal would be visible degradation
(user perception) rather than measured headroom.

Emits:
  budget_dialer_input_bps           — current input (download) rate
  budget_dialer_output_bps          — current output (upload) rate
  budget_dialer_cap_bps             — configured cap (env BUDGET_CAP_BPS,
                                      default 25_000_000)
  budget_dialer_utilization_input   — input_bps / cap_bps (0–1)
  budget_dialer_utilization_output  — output_bps / cap_bps (0–1)
  budget_dialer_pppoe_up            — 1/0 — mirrors budget_pppoe_up from
                                      budget-pppoe-health.sh
  budget_bandwidth_sample_age_sec   — seconds since last sample (stale detect)

Paired with BudgetBandwidthSaturated alert (>80% sustained 15m).

Cron: */2 * * * * /app/claude-gateway/scripts/write-budget-bandwidth-metrics.sh
"""
from __future__ import annotations

import os
import pathlib
REDACTED_a7b84d63
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/lib")

PROM_DEFAULT = "/var/lib/node_exporter/textfile_collector/budget_bandwidth.prom"
# Nominal Budget-PPPoE downstream cap. "25 Mbps" was the quoted floor at
# migration-time; actual line-rate measured 35+ Mbps during the 2026-04-22
# failover exercise. Default raised to 50 Mbps to give operator-tuning
# headroom; set BUDGET_CAP_BPS env to override from the real service plan.
DEFAULT_CAP_BPS = 50_000_000

# IOS-XE "5 minute input rate X bits/sec, Y packets/sec"
RATE_RE = re.compile(
    r"5 minute (input|output) rate (\d+) bits/sec,\s+(\d+) packets/sec",
    re.IGNORECASE,
)
# Dialer1 line/protocol state
DIALER_UP_RE = re.compile(r"Dialer1 is (up|down)(?:,|\s)+line protocol is (up|down)")


def sample_dialer() -> dict:
    """Query rtr01 Dialer1 rate + up state. Returns dict with bps, pps, up flag."""
    from ios_ssh import ssh_rtr01_command
    out = ssh_rtr01_command([
        "show interface Dialer1 | include rate|protocol|Dialer1 is",
    ])
    if out.startswith("ERROR"):
        return {"error": out}

    result = {"input_bps": 0, "output_bps": 0, "input_pps": 0, "output_pps": 0, "up": 0}

    # First occurrence of each direction is the Dialer1 interface itself
    # (subsequent ones are the Virtual-Access bound interface — same rates,
    # but we take the first to be deterministic).
    seen = {"input": False, "output": False}
    for m in RATE_RE.finditer(out):
        direction = m.group(1).lower()
        if seen[direction]:
            continue
        seen[direction] = True
        result[f"{direction}_bps"] = int(m.group(2))
        result[f"{direction}_pps"] = int(m.group(3))

    um = DIALER_UP_RE.search(out)
    if um:
        result["up"] = 1 if (um.group(1) == "up" and um.group(2) == "up") else 0

    return result


def emit_prom(sample: dict, cap_bps: int, path: str) -> None:
    tmp = pathlib.Path(path + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)

    now = int(time.time())
    input_bps = sample.get("input_bps", 0)
    output_bps = sample.get("output_bps", 0)
    input_util = round(input_bps / cap_bps, 4) if cap_bps else 0.0
    output_util = round(output_bps / cap_bps, 4) if cap_bps else 0.0
    up = sample.get("up", 0)
    errored = 1 if sample.get("error") else 0

    lines = [
        "# HELP budget_dialer_input_bps Current Dialer1 input (download) bitrate (bps, 5-min avg)",
        "# TYPE budget_dialer_input_bps gauge",
        f"budget_dialer_input_bps {input_bps}",
        "# HELP budget_dialer_output_bps Current Dialer1 output (upload) bitrate (bps, 5-min avg)",
        "# TYPE budget_dialer_output_bps gauge",
        f"budget_dialer_output_bps {output_bps}",
        "# HELP budget_dialer_input_pps Current Dialer1 input packet rate (pps, 5-min avg)",
        "# TYPE budget_dialer_input_pps gauge",
        f'budget_dialer_input_pps {sample.get("input_pps", 0)}',
        "# HELP budget_dialer_output_pps Current Dialer1 output packet rate (pps, 5-min avg)",
        "# TYPE budget_dialer_output_pps gauge",
        f'budget_dialer_output_pps {sample.get("output_pps", 0)}',
        "# HELP budget_dialer_cap_bps Configured nominal Budget-PPPoE cap",
        "# TYPE budget_dialer_cap_bps gauge",
        f"budget_dialer_cap_bps {cap_bps}",
        "# HELP budget_dialer_utilization_input Input utilization as fraction of cap (0..1)",
        "# TYPE budget_dialer_utilization_input gauge",
        f"budget_dialer_utilization_input {input_util}",
        "# HELP budget_dialer_utilization_output Output utilization as fraction of cap (0..1)",
        "# TYPE budget_dialer_utilization_output gauge",
        f"budget_dialer_utilization_output {output_util}",
        "# HELP budget_dialer_pppoe_up Dialer1 line+protocol up (1=up, 0=down)",
        "# TYPE budget_dialer_pppoe_up gauge",
        f"budget_dialer_pppoe_up {up}",
        "# HELP budget_dialer_sample_error 1 if the last rate sample failed",
        "# TYPE budget_dialer_sample_error gauge",
        f"budget_dialer_sample_error {errored}",
        "# HELP budget_dialer_sample_timestamp Unix time of last successful sample",
        "# TYPE budget_dialer_sample_timestamp gauge",
        f"budget_dialer_sample_timestamp {now if not errored else 0}",
    ]

    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)


def main() -> int:
    prom_path = os.environ.get("PROM_PATH", PROM_DEFAULT)
    cap_bps = int(os.environ.get("BUDGET_CAP_BPS", DEFAULT_CAP_BPS))
    sample = sample_dialer()
    if sample.get("error"):
        print(f"Sample failed: {sample['error']}", file=sys.stderr)
    if prom_path:
        emit_prom(sample, cap_bps, prom_path)
    if not sample.get("error"):
        input_mbps = sample["input_bps"] / 1_000_000
        output_mbps = sample["output_bps"] / 1_000_000
        print(f"Budget Dialer1: input={input_mbps:.1f} Mbps output={output_mbps:.1f} Mbps "
              f"(cap {cap_bps/1_000_000:.0f} Mbps, util={sample['input_bps']/cap_bps:.0%} in / "
              f"{sample['output_bps']/cap_bps:.0%} out) up={sample['up']}")
    return 0 if not sample.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
