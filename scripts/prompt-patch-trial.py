#!/usr/bin/env python3
"""Wrapper around scripts/prompt-improver.py that creates an N-candidate trial
instead of writing a single patch directly to config/prompt-patches.json
(IFRNLLEI01PRD-645).

Usage:
    scripts/prompt-patch-trial.py --analyze
    scripts/prompt-patch-trial.py --start            # create trials for low-scoring dims
    scripts/prompt-patch-trial.py --start --dry-run  # show what would be created

When PROMPT_TRIAL_ENABLED is falsy, this script no-ops and falls through to
the legacy single-patch flow (run prompt-improver.py --apply instead).

Design: the legacy prompt-improver has ONE hardcoded instruction per
dimension. Here we bracket it with two variations: a shorter imperative
and a longer, example-heavy version. The baseline (-1 = control in
session_trial_assignment) is "no patch" — that's what the judges score
against.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from prompt_patch_trial import (  # noqa: E402
    Candidate, start_trial, active_trial_for, list_active,
    MIN_SAMPLES_PER_ARM, MIN_LIFT, TIMEOUT_DAYS,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

ENABLED = os.environ.get("PROMPT_TRIAL_ENABLED", "0") == "1"
DEFAULT_SURFACE = os.environ.get("PROMPT_TRIAL_SURFACE", "build-prompt")

# Hand-authored variations per dimension. Three stylistic axes: (0) concise
# imperative — current baseline wording shortened; (1) detailed — the
# current prompt-improver.py instruction verbatim; (2) examples — same
# content plus a concrete example the model can pattern-match on.
#
# These replace a single prompt-improver.py rule and get A/B tested against
# a "no patch" control. The finalizer promotes the winner to the same
# prompt-patches.json that Build Prompt already reads.
CANDIDATE_POOL: dict[str, dict[str, Candidate]] = {
    "investigation_quality": {
        "concise": Candidate(
            idx=0, label="concise", category="investigation",
            instruction=(
                "Before drawing conclusions: SSH to the affected host and run "
                "at least 2 diagnostic commands. Verify with evidence, don't infer."
            ),
        ),
        "detailed": Candidate(
            idx=1, label="detailed", category="investigation",
            instruction=(
                "INVESTIGATION REQUIREMENT: You MUST SSH to the affected device "
                "and run at least 2 diagnostic commands (e.g., systemctl status, "
                "free -h, df -h, docker ps, pct list) before drawing any "
                "conclusion. Do NOT guess or infer — verify with evidence."
            ),
        ),
        "examples": Candidate(
            idx=2, label="examples", category="investigation",
            instruction=(
                "INVESTIGATION REQUIREMENT: Before a conclusion, SSH to the "
                "affected device and run >=2 diagnostic commands. Example "
                "(good): `ssh nl-pve01 'systemctl status corosync && "
                "journalctl -u corosync --since -1h | tail -20'`. Example "
                "(bad): \"I suspect corosync is unhealthy\" with no command. "
                "Cite the command output in your root-cause claim."
            ),
        ),
    },
    "evidence_based": {
        "concise": Candidate(
            idx=0, label="concise", category="evidence",
            instruction=(
                "Every factual claim must cite a specific command output, "
                "metric value, or API response. No unsourced claims."
            ),
        ),
        "detailed": Candidate(
            idx=1, label="detailed", category="evidence",
            instruction=(
                "EVIDENCE REQUIREMENT: Every factual claim in your response MUST "
                "cite a specific command output, metric value, or API response. "
                "Format: \"Based on [command output showing X], the root cause is Y.\""
            ),
        ),
        "examples": Candidate(
            idx=2, label="examples", category="evidence",
            instruction=(
                "EVIDENCE REQUIREMENT: Tag every claim with its source. "
                "Good: \"kubelet memory at 92% per `kubectl top node nl-w01` "
                "-> OOM-kill imminent\". Bad: \"node looks stressed\". If you "
                "can't cite a source, run the command first or mark the claim "
                "\"unverified\"."
            ),
        ),
    },
    "actionability": {
        "concise": Candidate(
            idx=0, label="concise", category="actionability",
            instruction=(
                "Remediation steps must be exact commands or config changes, "
                "with expected outcomes. No vague suggestions."
            ),
        ),
        "detailed": Candidate(
            idx=1, label="detailed", category="actionability",
            instruction=(
                "ACTIONABILITY REQUIREMENT: Remediation plans must include exact "
                "commands to run, specific config changes, and expected outcomes. "
                "Avoid vague suggestions like \"check the logs\" — instead specify "
                "which log file and what pattern to grep for."
            ),
        ),
        "examples": Candidate(
            idx=2, label="examples", category="actionability",
            instruction=(
                "ACTIONABILITY: Each step = (command, expected output, rollback). "
                "Good: \"1. `systemctl restart nginx` -> expect `active (running)` "
                "within 5s. Rollback: `journalctl -u nginx -n 50` then revert "
                "the config change.\" Bad: \"restart nginx and see.\" If you "
                "can't express a step this way, mark it investigation-only."
            ),
        ),
    },
    "safety_compliance": {
        "concise": Candidate(
            idx=0, label="concise", category="safety",
            instruction=(
                "Never execute infrastructure changes without a [POLL] first "
                "and human approval."
            ),
        ),
        "detailed": Candidate(
            idx=1, label="detailed", category="safety",
            instruction=(
                "SAFETY ENFORCEMENT: NEVER execute infrastructure changes without "
                "presenting a [POLL] first. Always present 2-3 options with risk "
                "levels. Wait for human approval before any modification."
            ),
        ),
        "examples": Candidate(
            idx=2, label="examples", category="safety",
            instruction=(
                "SAFETY: Mutating commands (`kubectl apply`, `systemctl restart`, "
                "`git push`, `iptables`, etc.) require a [POLL] block and a human "
                "reaction BEFORE execution. Example [POLL]: \"Plan A: restart nginx "
                "(low risk, 5s). Plan B: drain the node and migrate pods (med risk, "
                "3min).\" Read-only commands don't need a [POLL]."
            ),
        ),
    },
    "completeness": {
        "concise": Candidate(
            idx=0, label="concise", category="completeness",
            instruction=(
                "Every response: CONFIDENCE: X.XX, root cause, evidence citations, "
                "remediation plan, risk assessment."
            ),
        ),
        "detailed": Candidate(
            idx=1, label="detailed", category="completeness",
            instruction=(
                "COMPLETENESS CHECKLIST: Your response MUST include: "
                "(1) CONFIDENCE: X.XX score, (2) Root cause identification, "
                "(3) Evidence citations, (4) Remediation plan with [POLL] options, "
                "(5) Risk assessment."
            ),
        ),
        "examples": Candidate(
            idx=2, label="examples", category="completeness",
            instruction=(
                "COMPLETENESS: End every response with 5 sections: "
                "(1) `CONFIDENCE: 0.XX`, (2) Root cause = 1-line claim + 1 citation, "
                "(3) Evidence bullets with commands/values, (4) [POLL] with 2-3 plans, "
                "(5) Risk assessment (blast radius + rollback). Skip any section and "
                "the response will be marked incomplete."
            ),
        ),
    },
}


# ── Dimension thresholds copied from prompt-improver.py so the two agree ──
PATCH_THRESHOLDS = {
    "investigation_quality": 3.5,
    "evidence_based": 3.5,
    "actionability": 3.5,
    "safety_compliance": 3.0,
    "completeness": 3.5,
}

MIN_SAMPLES_TO_EVAL = int(os.environ.get("PROMPT_TRIAL_ANALYSIS_MIN_SAMPLES", "3"))


def compute_dim_avg(conn: sqlite3.Connection, dim: str) -> tuple[float, int]:
    """30-day avg + count for `dim` from session_judgment."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    row = conn.execute(
        f"SELECT AVG({dim}), COUNT(*) FROM session_judgment "
        f"WHERE {dim} > 0 AND judged_at >= ?",
        (cutoff,),
    ).fetchone()
    return round(row[0] or 0.0, 2), int(row[1] or 0)


def low_scoring_dims(conn: sqlite3.Connection) -> list[tuple[str, float, int]]:
    out = []
    for dim, thr in PATCH_THRESHOLDS.items():
        avg, cnt = compute_dim_avg(conn, dim)
        if cnt < MIN_SAMPLES_TO_EVAL:
            continue
        if avg < thr:
            out.append((dim, avg, cnt))
    return out


def candidates_for(dim: str) -> list[Candidate]:
    pool = CANDIDATE_POOL.get(dim)
    if not pool:
        raise ValueError(f"no candidate pool for dimension {dim!r}")
    ordered = [pool["concise"], pool["detailed"], pool["examples"]]
    # Re-index to 0..N-1 (the pool has original idx values).
    return [Candidate(idx=i, label=c.label, instruction=c.instruction, category=c.category)
            for i, c in enumerate(ordered)]


def cmd_analyze() -> int:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        low = low_scoring_dims(conn)
        actives = {(t.surface, t.dimension) for t in list_active()}
        if not low:
            print("All dimensions above threshold; nothing to start.")
            return 0
        print(f"{'dim':<24}  {'avg':>6}  {'cnt':>5}  active-trial?")
        for dim, avg, cnt in low:
            has = (DEFAULT_SURFACE, dim) in actives
            print(f"{dim:<24}  {avg:>6.2f}  {cnt:>5}  {'yes' if has else 'no'}")
        return 0
    finally:
        conn.close()


def cmd_start(dry_run: bool) -> int:
    if not ENABLED and not dry_run:
        print("PROMPT_TRIAL_ENABLED is not set to '1'; refusing to start trials.",
              file=sys.stderr)
        print("(Set PROMPT_TRIAL_ENABLED=1 or pass --dry-run to preview.)",
              file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        low = low_scoring_dims(conn)
    finally:
        conn.close()

    started, skipped, planned = [], [], []
    for dim, avg, cnt in low:
        existing = active_trial_for(DEFAULT_SURFACE, dim)
        if existing is not None:
            skipped.append((dim, f"active trial {existing.id} already exists"))
            continue
        cands = candidates_for(dim)
        if dry_run:
            planned.append({
                "surface": DEFAULT_SURFACE, "dimension": dim,
                "baseline_mean": avg, "baseline_samples": cnt,
                "candidates": [c.to_dict() for c in cands],
            })
            continue
        try:
            tid = start_trial(DEFAULT_SURFACE, dim, cands,
                              baseline_mean=avg, baseline_samples=cnt,
                              note=f"auto-started from dim avg {avg} below threshold")
            started.append((dim, tid))
        except RuntimeError as e:
            skipped.append((dim, str(e)))

    if dry_run:
        json.dump(
            {"would_start": planned, "would_skip": [{"dim": d, "reason": r} for d, r in skipped]},
            sys.stdout, indent=2,
        )
        sys.stdout.write("\n")
        return 0

    if started:
        for d, tid in started:
            print(f"started trial {tid} for dimension={d}")
    else:
        print("no trials started")
    for d, r in skipped:
        print(f"skipped {d}: {r}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyze", action="store_true", help="show low-scoring dims + trial state")
    ap.add_argument("--start", action="store_true", help="start trials for low-scoring dims")
    ap.add_argument("--dry-run", action="store_true", help="with --start: show what would happen")
    args = ap.parse_args()

    if args.analyze:
        return cmd_analyze()
    if args.start:
        return cmd_start(args.dry_run)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
