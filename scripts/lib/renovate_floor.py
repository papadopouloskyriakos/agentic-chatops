#!/usr/bin/env python3
"""
Single source of truth for the Renovate MR Autonomy AUTO-merge FLOOR (policy, SEPARATED from mechanism).

renovate-mr-gate.sh calls this as an INDEPENDENT pre-merge re-check: after its own decision path says
AUTO, it re-derives the floor here from the raw gate outputs and merges ONLY if this ALSO returns ALLOW.
So a bug in the gate's decision line cannot merge out of policy — the policy lives here, not in the
decider. The audit/metrics floor SQL mirrors this same rule (detective layer), so decide-time and
audit-time cannot drift.

A merge is allowed ONLY if ALL hold:
  - not a never_auto engine (secret/config store)
  - CI pipeline == success
  - review verdict == APPROVE at/above the tier's confidence threshold
  - if a snapshot is required, it was verified
  - the reviewed head SHA has not changed (no Renovate push between review and merge — TOCTOU)

Usage: echo '<json inputs>' | renovate_floor.py   →  prints "ALLOW" or "DENY:<reasons>"; exit 0 / 1.
"""
import json
import sys


def floor_ok(d: dict) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if d.get("never_auto"):
        reasons.append("never_auto_engine")
    if d.get("ci_status") != "success":
        reasons.append(f"ci:{d.get('ci_status')}")
    if d.get("review_verdict") != "APPROVE":
        reasons.append(f"review:{d.get('review_verdict')}")
    try:
        if float(d.get("review_confidence", 0)) < float(d.get("confidence_threshold", 1)):
            reasons.append("confidence_below_threshold")
    except (TypeError, ValueError):
        reasons.append("confidence_unparseable")
    if d.get("snapshot_required") and not d.get("snapshot_verified"):
        reasons.append("snapshot_not_verified")
    if d.get("head_sha_changed"):
        reasons.append("head_sha_changed")
    return (len(reasons) == 0, reasons)


def main() -> None:
    try:
        d = json.load(sys.stdin)
    except Exception as e:  # fail closed: unparseable input → DENY
        print(f"DENY:bad-input:{e}")
        sys.exit(1)
    ok, reasons = floor_ok(d)
    print("ALLOW" if ok else "DENY:" + ",".join(reasons))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
