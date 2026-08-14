#!/usr/bin/env python3
"""infragraph-predict-plan — the Runner's mandatory pre-poll prediction step.

IFRNLLEI01PRD-1044 (model-based invariant #1+#2). Called by the n8n Runner's
"Commit Prediction" SSH node between Classify Risk and Build Prompt, with the
SAME plan JSON on stdin that Classify Risk received. It:

  1. recomputes plan_hash exactly as classify-session-risk.py does (the
     non-bypassable gate key — QA asserts hash parity),
  2. decides whether the plan is a REMEDIATION plan (same MUTATION_PATTERNS
     as the risk classifier, imported — not duplicated),
  3. derives (action_kind, target) and commits the prediction artifact via
     `infragraph-query.py predict` (an infragraph_predictions kind='action'
     row keyed by plan_hash),
  4. emits one JSON verdict for the Prepare Result gate.

Output JSON (stdout, single object):
  {plan_hash, remediation_plan: bool, action_kind, target,
   gate: "eligible" | "not-applicable-readonly" | "ineligible:<reason>",
   prediction: {<full predict artifact>} | null}

Exit code is 0 whenever a verdict was produced (including ineligible) — the
gate decision lives in the JSON. Non-zero only on internal crash, which the
Prepare Result gate treats as "no prediction" (default-DENY, fail closed).
Pure code end to end: no LLM is consulted at any point in this path.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
REDACTED_a7b84d63
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from lib import infragraph  # noqa: E402

# Hostname shape shared with populate-graph.py
HOSTNAME_RE = re.compile(r"\b([a-z]{2}[a-z0-9]{3,5}\d{2}[a-z][a-z0-9-]*\d{2})\b")

# Mutation-reason substring → action_kind (first match wins, order matters)
ACTION_KIND_MAP = [
    ("reboot", "reboot_host"),
    ("drain", "drain"),
    ("scale", "scale"),
    ("failover", "failover"),
    ("tunnel", "bounce_tunnel"),
    ("systemctl", "restart_service"),
    ("docker", "restart_service"),
    ("restart", "restart_service"),
    ("qm-", "restart_vm"),
    ("pct-", "restart_lxc"),
]


def _load_classifier():
    spec = importlib.util.spec_from_file_location(
        "classify_mod", os.path.join(SCRIPT_DIR, "classify-session-risk.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def plan_hash_of(plan: dict) -> str:
    """MUST stay byte-identical to classify-session-risk.py's computation."""
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def plan_blob(plan: dict) -> str:
    """Same text-concatenation surface the classifier regex-scans."""
    parts = []
    for key in ("hypothesis", "reason"):
        if isinstance(plan.get(key), str):
            parts.append(plan[key])
    for step in plan.get("steps", []) or []:
        if isinstance(step, str):
            parts.append(step)
        elif isinstance(step, dict):
            for k in ("description", "action", "command", "hint"):
                if isinstance(step.get(k), str):
                    parts.append(step[k])
    for t in plan.get("tools_needed", []) or []:
        if isinstance(t, str):
            parts.append(t)
    for tmpl in plan.get("awx_templates", []) or []:
        if isinstance(tmpl, dict):
            parts.append(tmpl.get("name", ""))
            parts.append(tmpl.get("description", ""))
        elif isinstance(tmpl, str):
            parts.append(tmpl)
    return " \n ".join(parts)


def derive_action(plan: dict, classifier) -> tuple[bool, str]:
    """(is_remediation, action_kind) from the classifier's own patterns."""
    blob = plan_blob(plan)
    reasons = []
    for pat, _level, reason in classifier.MUTATION_PATTERNS:
        if pat.search(blob):
            reasons.append(reason)
    if plan.get("awx_templates"):
        reasons.append("awx-templates-referenced")
    if not reasons:
        return False, ""
    joined = " ".join(reasons).lower() + " " + blob.lower()
    for needle, kind in ACTION_KIND_MAP:
        if needle in joined:
            return True, kind
    return True, "remediation"


def derive_target(conn, plan: dict) -> str:
    """plan.hostname if present, else first plan-mentioned host in the graph."""
    h = plan.get("hostname")
    if isinstance(h, str) and h:
        return h
    for cand in HOSTNAME_RE.findall(plan_blob(plan)):
        if infragraph.resolve_entity(conn, cand):
            return cand
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(prog="infragraph-predict-plan")
    ap.add_argument("--issue", default="")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    try:
        plan = json.load(sys.stdin)
        if not isinstance(plan, dict):
            plan = {}
    except Exception:
        plan = {}

    out = {
        "plan_hash": plan_hash_of(plan),
        "remediation_plan": False,
        "action_kind": "",
        "target": "",
        "gate": "not-applicable-readonly",
        "prediction": None,
    }

    classifier = _load_classifier()
    conn = infragraph.get_db(args.db)
    try:
        is_remediation, action_kind = derive_action(plan, classifier)
        if is_remediation:
            out["remediation_plan"] = True
            out["action_kind"] = action_kind
            target = derive_target(conn, plan)
            out["target"] = target
            if not target:
                out["gate"] = "ineligible:no-target-host-in-plan-or-graph"
            elif os.environ.get("INFRAGRAPH_DISABLED", "") not in ("", "0"):
                out["gate"] = "ineligible:infragraph-disabled-analysis-only"
            else:
                proc = subprocess.run(
                    [sys.executable,
                     os.path.join(SCRIPT_DIR, "infragraph-query.py")]
                    + (["--db", args.db] if args.db else [])
                    + ["predict", "--action-kind", action_kind,
                       "--target", target, "--plan-hash", out["plan_hash"],
                       "--issue", args.issue],
                    capture_output=True, timeout=10, check=False)
                try:
                    pred = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    pred = {"eligible": False, "reason": "predict-cli-bad-output"}
                out["prediction"] = pred
                out["gate"] = ("eligible" if pred.get("eligible")
                               else f"ineligible:{pred.get('reason') or pred.get('error') or 'unknown'}")
    finally:
        conn.close()

    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
