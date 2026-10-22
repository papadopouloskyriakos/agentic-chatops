#!/usr/bin/env python3
"""Assign + record trial variants for an incoming session (IFRNLLEI01PRD-645).

Runs from the n8n Runner's Query Knowledge SSH node. For each active trial
matching the given surface, deterministically assigns the session to one arm
(candidates + control), persists the assignment to `session_trial_assignment`,
and prints a compact JSON of the selected candidate *instructions* (control
arms are elided — they contribute no prompt text).

Shell contract:
    scripts/prompt-trial-assign.py --issue ISSUE-ID --surface build-prompt [--session SESSION_ID]

    stdout: a single compact JSON array:
        [{"trial_id": N, "dimension": "...", "category": "...",
          "instruction": "...", "label": "...", "variant_idx": I}, ...]

    Empty array ("[]") when there are no active trials for the surface or
    when every match landed on the control arm.

Exit 0 on success, even when the array is empty. Exit 1 on unrecoverable
error (DB missing, etc.) — Build Prompt fallback handles this by treating
the line as empty and continuing with existing PROMPT_PATCHES only.

The Query Knowledge SSH node wraps this as:

    echo "PROMPT_TRIAL_INSTRUCTIONS:$(scripts/prompt-trial-assign.py --issue "$ISSUE_ID" --surface build-prompt 2>/dev/null || echo '[]')"

and Build Prompt pairs the `PROMPT_TRIAL_INSTRUCTIONS:` line with its
existing `PROMPT_PATCHES:` handler.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from prompt_patch_trial import (  # noqa: E402
    active_trial_for, assign_and_record,
)

# Dimensions we run trials on. MUST stay a superset-consistent mirror of the
# finalizer's _JUDGMENT_DIM_COLS whitelist in lib/prompt_patch_trial.py: a trial
# registered on a dimension absent HERE is never assigned (dead on arrival, 0
# samples) even though the finalizer would happily score it. That drift silently
# killed trial 9 (overall_score) — added below; guarded by
# test-1666-trial-dimension-sync.sh so the two lists can't diverge again.
DIMENSIONS = (
    "investigation_quality",
    "evidence_based",
    "actionability",
    "safety_compliance",
    "completeness",
    "overall_score",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", required=True)
    ap.add_argument("--surface", default=os.environ.get("PROMPT_TRIAL_SURFACE", "build-prompt"))
    ap.add_argument("--session", default="", help="session_id (optional; improves audit trail)")
    args = ap.parse_args()

    # Defensive normalization (IFRNLLEI01PRD-1664/1666 trial-data integrity): the n8n
    # Runner's SSH expression can wrap the value in literal quotes ("IFR-123" instead of
    # IFR-123), and an absent issueId renders as the two-char string `""`. Strip a
    # surrounding quote-pair + whitespace so the stored issue_id matches
    # session_judgment.issue_id (unquoted) on the finalizer join; bail on empty so a junk
    # assignment row that can never join is NEVER persisted (root cause of the ~2.5-month
    # dark trial pipeline).
    args.issue = args.issue.strip().strip('"').strip("'").strip()
    if not args.issue:
        print("[]")
        return 0

    out: list[dict[str, Any]] = []

    for dim in DIMENSIONS:
        try:
            trial = active_trial_for(args.surface, dim)
        except Exception as e:
            # DB missing / schema error — return empty array; caller keeps going.
            print("[]")
            print(f"[prompt-trial-assign] active_trial_for({args.surface},{dim}) failed: {e}",
                  file=sys.stderr)
            return 1
        if trial is None:
            continue

        try:
            variant_idx = assign_and_record(
                issue_id=args.issue,
                trial=trial,
                session_id=args.session,
            )
        except Exception as e:
            # Don't break Build Prompt on a single-trial error.
            print(f"[prompt-trial-assign] assign_and_record failed for trial {trial.id}: {e}",
                  file=sys.stderr)
            continue

        # Control arm contributes nothing to the prompt.
        if variant_idx < 0:
            continue

        if variant_idx >= len(trial.candidates):
            print(f"[prompt-trial-assign] BUG: variant_idx={variant_idx} >= n={len(trial.candidates)}",
                  file=sys.stderr)
            continue

        cand = trial.candidates[variant_idx]
        out.append({
            "trial_id": trial.id,
            "dimension": trial.dimension,
            "category": cand.category,
            "instruction": cand.instruction,
            "label": cand.label,
            "variant_idx": variant_idx,
        })

    # Compact JSON (no pretty-print) — this goes on a single shell echo line
    # that Build Prompt parses with a regex. Any newline would break the
    # `.match(/PROMPT_TRIAL_INSTRUCTIONS:(.*)/)` capture.
    sys.stdout.write(json.dumps(out, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
