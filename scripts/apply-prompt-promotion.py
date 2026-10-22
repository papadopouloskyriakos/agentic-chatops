#!/usr/bin/env python3
"""apply-prompt-promotion.py — operator circuit-breaker for held prompt-patch promotions.

When the self-modifying prompt loop runs with PROMPT_PROMOTION_REVIEW=1 (or the holdout
gate holds a winner), finalize-prompt-trials records the winning promotion to
config/prompt-promotions-pending.json instead of applying it live. This CLI lets the
human review and APPLY or REJECT each one — the human-as-circuit-breaker on the one fully
self-modifying loop (IFRNLLEI01PRD-1267, D16 self-improvement).

Usage:
  apply-prompt-promotion.py --list
  apply-prompt-promotion.py --apply  <trial_id>
  apply-prompt-promotion.py --reject <trial_id> [--note "why"]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PENDING_FILE = Path(os.environ.get("PROMPT_PROMOTIONS_PENDING_FILE",
                                   str(HERE.parent / "config" / "prompt-promotions-pending.json")))
PATCH_FILE = Path(os.environ.get("PROMPT_PATCHES_FILE",
                                 str(HERE.parent / "config" / "prompt-patches.json")))


def _load(p: Path):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2) + "\n")


def _pending_only(records):
    return [r for r in records if r.get("status") == "pending"]


def cmd_list() -> int:
    pend = _pending_only(_load(PENDING_FILE))
    if not pend:
        print("No pending prompt-patch promotions.")
        return 0
    print(f"{len(pend)} pending promotion(s) awaiting review:\n")
    for r in pend:
        print(f"  trial {r['trial_id']}  [{r['dimension']}/{r['category']}]  "
              f"label={r.get('label')}  recorded={r.get('recorded_at')}")
        print(f"    reason: {r.get('reason')}")
        print(f"    instruction: {r['instruction'][:120]}")
    return 0


def cmd_apply(trial_id: int) -> int:
    records = _load(PENDING_FILE)
    rec = next((r for r in records if r.get("trial_id") == trial_id and r.get("status") == "pending"), None)
    if not rec:
        print(f"No pending promotion for trial {trial_id}", file=sys.stderr)
        return 1
    patches = _load(PATCH_FILE)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Deactivate any active patch for the same (dimension, category) — mirror finalize.
    for p in patches:
        if (p.get("dimension") == rec["dimension"] and p.get("category") == rec["category"]
                and p.get("active", False)):
            p["active"] = False
            p["deactivated_at"] = now
            p["deactivated_reason"] = f"superseded by reviewed promotion trial {trial_id}"
    patches.append({
        "dimension": rec["dimension"], "category": rec["category"],
        "instruction": rec["instruction"], "applied_at": now,
        "score_before": rec.get("score_before"), "score_after": None,
        "active": True, "expires_at": expires,
        "source": rec.get("source", f"reviewed-promotion:trial:{trial_id}"),
        "human_reviewed": True,
    })
    _save(PATCH_FILE, patches)
    rec["status"] = "applied"
    rec["applied_at"] = now
    _save(PENDING_FILE, records)
    print(f"Applied promotion for trial {trial_id} ({rec['dimension']}/{rec['category']}) to {PATCH_FILE.name}")
    return 0


def cmd_reject(trial_id: int, note: str) -> int:
    records = _load(PENDING_FILE)
    rec = next((r for r in records if r.get("trial_id") == trial_id and r.get("status") == "pending"), None)
    if not rec:
        print(f"No pending promotion for trial {trial_id}", file=sys.stderr)
        return 1
    rec["status"] = "rejected"
    rec["rejected_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["reject_note"] = note
    _save(PENDING_FILE, records)
    print(f"Rejected promotion for trial {trial_id}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--apply", type=int, metavar="TRIAL_ID")
    g.add_argument("--reject", type=int, metavar="TRIAL_ID")
    ap.add_argument("--note", default="", help="reason (with --reject)")
    args = ap.parse_args()
    if args.list:
        return cmd_list()
    if args.apply is not None:
        return cmd_apply(args.apply)
    return cmd_reject(args.reject, args.note)


if __name__ == "__main__":
    sys.exit(main())
