#!/usr/bin/env python3
"""build-gepa-eval-set.py — IFRNLLEI01PRD-1159.

Builds the contamination-free held-out eval set GEPA needs as its reward-hacking
guard. ONLY sessions created before the GEPA-launch cutoff (2026-05-01) are
eligible, so a GEPA-evolved prompt cannot be validated against sessions it could
have influenced. Writes scripts/eval-sets/gepa-task-eval.jsonl.

Enforces the contract: GEPA must not be ENABLED until this set has >= MIN_EVAL
entries. Exit 0 + the set on success; exit 3 (non-fatal advisory) if too few
eligible sessions — in which case PROMPT_GEPA_ENABLED should stay 0 and the live
Welch t-test remains the only gate.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "eval-sets", "gepa-task-eval.jsonl")
CUTOFF = os.environ.get("GEPA_EVAL_CUTOFF", "2026-05-01")  # pre-GEPA launch
MIN_EVAL = int(os.environ.get("GEPA_EVAL_MIN", "20"))


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT issue_id, alert_category, confidence, resolution_type, started_at "
            "FROM session_log WHERE started_at < ? AND confidence >= 0 "
            "AND issue_id != '' ORDER BY started_at DESC",
            (CUTOFF,),
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"query failed: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    seen = set()
    n = 0
    with open(OUT, "w", encoding="utf-8") as fh:
        for issue_id, cat, conf, res, started in rows:
            if issue_id in seen:
                continue
            seen.add(issue_id)
            fh.write(json.dumps({
                "issue_id": issue_id, "alert_category": cat or "",
                "confidence": conf, "resolution_type": res or "",
                "started_at": started,
            }) + "\n")
            n += 1

    print(f"wrote {n} held-out eval entries (< {CUTOFF}) to {OUT}")
    if n < MIN_EVAL:
        print(f"ADVISORY: only {n} < {MIN_EVAL} contamination-free sessions — keep "
              f"PROMPT_GEPA_ENABLED=0; live Welch t-test remains the gate.",
              file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
