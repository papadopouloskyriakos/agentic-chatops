#!/usr/bin/env python3
"""Cron-driven finalizer for prompt_patch_trial (IFRNLLEI01PRD-645).

Runs daily at ~03:17 UTC. Walks every 'active' row, tries to finalize it.
Sweeps timed-out rows first so the following finalize pass only touches
still-in-scope trials.

Exits 0 regardless of outcome — the state lives in the DB, not the exit
code. A logs-only failure is captured in the trial's `note` column.

Usage:
    finalize-prompt-trials.py              # real run
    finalize-prompt-trials.py --dry-run    # no DB writes, print would-do JSON
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from prompt_patch_trial import (  # noqa: E402
    abort_stale_trials, finalize, list_active, get_trial, collect_arm_scores,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print decisions without mutating the DB or patches file")
    ap.add_argument("--json", action="store_true",
                    help="emit a single JSON summary to stdout")
    args = ap.parse_args()

    # 1. Sweep timed-out trials.
    aborted = 0
    if not args.dry_run:
        aborted = abort_stale_trials()

    # 2. Walk active trials.
    trials = list_active()
    results = []
    for t in trials:
        scores = collect_arm_scores(t)
        summary = {
            "trial_id": t.id,
            "surface": t.surface,
            "dimension": t.dimension,
            "arm_counts": {str(k): len(v) for k, v in scores.items()},
            "baseline_mean": t.baseline_mean,
        }
        if args.dry_run:
            summary["would_finalize"] = True
            results.append(summary)
            continue

        try:
            r = finalize(t.id)
        except Exception as e:
            summary["error"] = str(e)
            results.append(summary)
            continue

        summary.update({
            "status": r.status, "winner_idx": r.winner_idx,
            "winner_mean": r.winner_mean, "winner_p_value": r.winner_p_value,
            "reason": r.reason,
        })
        results.append(summary)

    out = {"aborted_stale": aborted, "active_processed": len(results), "trials": results}
    if args.json:
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"swept {aborted} stale, processed {len(results)} active trial(s)")
        for r in results:
            line = (
                f"  id={r['trial_id']:<4}  "
                f"dim={r['dimension']:<22}  "
                f"status={r.get('status') or '(dry-run)':<18}  "
                f"arms={r['arm_counts']}"
            )
            if r.get("winner_idx") is not None:
                line += f"  winner=idx{r['winner_idx']} ({r.get('winner_mean')})"
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
