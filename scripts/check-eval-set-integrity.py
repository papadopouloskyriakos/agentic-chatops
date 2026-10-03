#!/usr/bin/env python3
"""Offline eval-set integrity / sealed-holdout gate (IFRNLLEI01PRD-1085).

Runs in CI (no DB/Ollama needed). Fails if the eval-sets are malformed OR if the
SEALED holdout set overlaps the tuned sets (discovery/regression) by id or by
payload content. This enforces the decontamination + sealed-holdout discipline
the LLM Engineer's Handbook (Ch 7) requires, and is what makes the eval-flywheel's
overfit detector meaningful — it must compare tuned-vs-sealed, never a set vs
itself (the bug fixed alongside this in eval-flywheel.sh).

Exit 0 = clean. Exit 1 = malformed or holdout leakage.
"""
import hashlib
import json
import os
import sys

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval-sets")


def load(name):
    return json.load(open(os.path.join(D, name)))


def sig(item):
    payload = item.get("payload", item)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def main():
    errs = []
    sets = {}
    for n in ("regression", "discovery", "holdout"):
        try:
            items = load(f"{n}.json")
        except Exception as e:
            errs.append(f"{n}.json: load failed: {e}")
            continue
        if not isinstance(items, list) or not items:
            errs.append(f"{n}.json: not a non-empty list")
            continue
        for it in items:
            if not all(k in it for k in ("id", "payload", "expected")):
                errs.append(f"{n}.json: item {it.get('id', '?')} missing id/payload/expected")
        sets[n] = items

    try:
        rg = load("ragas-golden.json")
        for it in rg:
            if not all(k in it for k in ("query", "ground_truth")):
                errs.append(f"ragas-golden: item {it.get('id', '?')} missing query/ground_truth")
    except Exception as e:
        errs.append(f"ragas-golden.json: {e}")

    # Sealed holdout: must NOT overlap the tuned sets (by id or payload signature).
    if "holdout" in sets:
        hold_ids = {i["id"] for i in sets["holdout"]}
        hold_sigs = {sig(i) for i in sets["holdout"]}
        for tuned in ("discovery", "regression"):
            if tuned not in sets:
                continue
            dup_ids = {i["id"] for i in sets[tuned]} & hold_ids
            dup_sigs = {sig(i) for i in sets[tuned]} & hold_sigs
            if dup_ids:
                errs.append(f"holdout LEAKED into {tuned} by id: {sorted(dup_ids)}")
            if dup_sigs:
                errs.append(f"holdout LEAKED into {tuned} by payload: {len(dup_sigs)} duplicate payload(s)")

    if errs:
        print("EVAL-SET INTEGRITY FAILED:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("eval-set integrity OK: "
          f"regression={len(sets.get('regression', []))} "
          f"discovery={len(sets.get('discovery', []))} "
          f"holdout={len(sets.get('holdout', []))} (sealed, no overlap); "
          "ragas-golden well-formed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
