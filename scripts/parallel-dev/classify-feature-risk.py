#!/usr/bin/env python3
"""classify-feature-risk.py — aggregate per-task risk into a feature-level risk decision
(IFRNLLEI01PRD-928 Phase 6 of parallel-dev architecture)

Sibling of `scripts/classify-session-risk.py` used by the cc-cc infra side. Same
output shape so the merge-coordinator + downstream audit scripts can treat
infra-session-risk and feature-risk uniformly.

Decision rules (deliberately simple — first pass; refine with real data):
  - feature_risk_score = max(task.risk_score for all completed tasks)
  - count_high = number of tasks with risk_score > 0.7
  - auto_merge = (feature_risk_score <= 0.7) AND (count_high == 0) AND (failed_tasks == 0)
  - needs_human = NOT auto_merge

Usage:
  classify-feature-risk.py <feature_id>
  classify-feature-risk.py <feature_id> --json
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

DB = "/home/app-user/gateway-state/gateway.db"
HIGH_RISK_THRESHOLD = 0.7
CLASSIFIER_VERSION = "feature-risk-v1-2026-05-17"


def classify(feature_id: str) -> dict:
    conn = sqlite3.connect(DB)
    feat = conn.execute(
        "SELECT repo_slug, feature_risk_score, status, total_work_units FROM features WHERE feature_id=?",
        (feature_id,),
    ).fetchone()
    if not feat:
        return {"error": f"no feature {feature_id}", "auto_merge": False, "needs_human": True}
    repo_slug, prior_risk, status, total = feat

    tasks = conn.execute(
        "SELECT task_id, risk_score, status FROM work_units WHERE feature_id=?",
        (feature_id,),
    ).fetchall()

    completed = [t for t in tasks if t[2] == "completed"]
    failed = [t for t in tasks if t[2] in ("failed", "timeout")]
    high_risk = [t for t in completed if (t[1] or 0) > HIGH_RISK_THRESHOLD]

    if completed:
        feature_risk_score = max(t[1] or 0 for t in completed)
    else:
        feature_risk_score = 1.0  # all failed = max risk

    reasons: list[str] = []
    if feature_risk_score > HIGH_RISK_THRESHOLD:
        reasons.append(f"feature_risk_score={feature_risk_score} > {HIGH_RISK_THRESHOLD}")
    if high_risk:
        reasons.append(f"{len(high_risk)} high-risk task(s): {[t[0] for t in high_risk]}")
    if failed:
        reasons.append(f"{len(failed)} task(s) failed/timed out: {[t[0] for t in failed]}")

    auto_merge = not reasons
    return {
        "feature_id": feature_id,
        "repo_slug": repo_slug,
        "classifier_version": CLASSIFIER_VERSION,
        "feature_risk_score": feature_risk_score,
        "total_work_units": total,
        "completed_count": len(completed),
        "failed_count": len(failed),
        "high_risk_count": len(high_risk),
        "auto_merge": auto_merge,
        "needs_human": not auto_merge,
        "reasons": reasons or ["all checks pass: low-risk, no failures, no high-risk tasks"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify feature-level risk for parallel-dev auto-merge gating.")
    parser.add_argument("feature_id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = classify(args.feature_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for k, v in result.items():
            print(f"  {k}: {v}")
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    sys.exit(main())
