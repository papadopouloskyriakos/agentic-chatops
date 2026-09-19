#!/usr/bin/env python3
"""Orchestrator -> Cronicle CONTROL path (IFRNLLEI01PRD-1421 extension, 2026-06-26).

The orchestrator's first *action* on the scheduler (beyond oversight): auto-quarantine a chronic-
failing job. A job that fails >= CRONICLE_FAIL_THRESHOLD times in the recent history window is broken
+ spamming + wasting runs every cycle; quarantining it = DISABLE it in Cronicle (reversible) + audit
+ alert a human to fix and re-enable.

Why this is a safe band=AUTO-class action: disabling a job EXECUTES NOTHING and is fully reversible
(re-enable). It only stops a job that is already failing. (Re-running a failed job is deliberately NOT
done — idempotency is unknown, so auto-replay could double-process.)

GATED, ships dark — matching the conservative-remediation pattern:
  - sentinel ~/gateway.cronicle_autoquarantine ABSENT (default) -> ANALYSIS-ONLY: flag candidates via
    cronicle_remediate_candidates metric + audit log, take NO action.
  - sentinel PRESENT -> ARMED: actually disable chronic-failers (+ audit + the CronicleJobsFailing
    alert already pages on the underlying failures).
Kill: rm ~/gateway.cronicle_autoquarantine. Reverse a quarantine: re-enable the event in Cronicle.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import cronicle as cron_api  # noqa: E402
import obs_log  # noqa: E402
try:
    import mutation_mode  # noqa: E402 - MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:  # noqa: BLE001 - absent lib must not crash the remediator
    mutation_mode = None

FAIL_THRESHOLD = int(os.environ.get("CRONICLE_FAIL_THRESHOLD", "3"))
SENTINEL = Path.home() / "gateway.cronicle_autoquarantine"
OUT = Path("/var/lib/node_exporter/textfile_collector/cronicle_remediate.prom")
AUDIT = Path.home() / "logs/claude-gateway/cronicle-remediate.log"


def _audit(msg):
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a") as f:
            f.write(f"{int(time.time())} {msg}\n")
    except Exception:
        pass


def _emit(candidates, quarantined, armed):
    lines = [
        "# HELP cronicle_remediate_candidates Chronic-failing jobs eligible for quarantine",
        "# TYPE cronicle_remediate_candidates gauge",
        f"cronicle_remediate_candidates {candidates}",
        "# HELP cronicle_remediate_quarantined_total Jobs auto-disabled this run",
        "# TYPE cronicle_remediate_quarantined_total gauge",
        f"cronicle_remediate_quarantined_total {quarantined}",
        "# HELP cronicle_remediate_armed Auto-quarantine sentinel present (1) or analysis-only (0)",
        "# TYPE cronicle_remediate_armed gauge",
        f"cronicle_remediate_armed {1 if armed else 0}",
        "# HELP cronicle_remediate_last_run_timestamp_seconds Last run",
        "# TYPE cronicle_remediate_last_run_timestamp_seconds gauge",
        f"cronicle_remediate_last_run_timestamp_seconds {int(time.time())}",
    ]
    try:
        tmp = str(OUT) + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, OUT)
    except Exception:
        pass


def main():
    armed = SENTINEL.exists()
    stats = cron_api.event_failure_stats(limit=1000)
    candidates = {eid: s for eid, s in stats.items()
                  if s["fails"] >= FAIL_THRESHOLD and s.get("enabled")}
    quarantined = 0
    sid = cron_api.login() if (armed and candidates) else ""
    for eid, s in candidates.items():
        desc = f"{s['title']} ({s['fails']}/{s['total']} recent fails)"
        if mutation_mode and mutation_mode.is_shadow():
            mutation_mode.log_wouldve("cronicle-quarantine", rationale="would disable chronic-failer",
                                      event_id=eid, job=s["title"])
            _audit(f"SHADOW (MUTATIONS=OFF) would quarantine {desc} -> logged, not disabled")
        elif armed and sid:
            code = cron_api.set_enabled(eid, False, sid)
            if code == 0:
                quarantined += 1
                _audit(f"QUARANTINED chronic-failer {desc} -> disabled (reversible; re-enable after fix)")
            else:
                _audit(f"quarantine FAILED for {desc} (api code={code})")
        else:
            _audit(f"CANDIDATE (analysis-only, sentinel off) chronic-failer {desc}")
        obs_log.event("orchestrator", source="cronicle-remediate",
                      action="quarantined" if (armed and sid) else "candidate",
                      job=s["title"], fails=s["fails"], total=s["total"], armed=armed, level="warn")
    _emit(len(candidates), quarantined, armed)
    print(f"  armed={armed} candidates={len(candidates)} quarantined={quarantined}")


if __name__ == "__main__":
    main()
