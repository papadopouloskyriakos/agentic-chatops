#!/usr/bin/env python3
"""infragraph-verify — mechanical post-execution verification of one prediction.

IFRNLLEI01PRD-1045 (model-based invariant #3). The orchestrator-callable
entry point for verifying a single committed prediction NOW:

    infragraph-verify.py --prediction-id N [--notify]

Exit codes:
    0  verdict written: match
    1  verdict written: partial
    2  verdict written: deviation (SURPRISE — never auto-resolve)
    3  window still open (Xs remaining) — call again later
    4  error / prediction not found

The hourly `infragraph-eval.py --pending` cron writes verdicts for everything
whose window closed; this script exists for the synchronous path (a Bridge or
operator wanting the verdict the moment the window closes). Both share the
same lib code — `infragraph.action_verdict()` is the ONLY verdict author.
The LLM session that proposed the action has no write path to these columns.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from lib import infragraph  # noqa: E402


def _load_eval():
    spec = importlib.util.spec_from_file_location(
        "infragraph_eval_mod", os.path.join(SCRIPT_DIR, "infragraph-eval.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(prog="infragraph-verify")
    ap.add_argument("--prediction-id", type=int, required=True)
    ap.add_argument("--db", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--notify", action="store_true",
                    help="post the verdict as a YT comment on the parent issue")
    args = ap.parse_args()

    ev = _load_eval()
    conn = infragraph.get_db(args.db)
    try:
        row = conn.execute(
            """SELECT id, created_at, kind, parent_issue_id, parent_host,
                      parent_rule, window_seconds, predicted, verdict
               FROM infragraph_predictions WHERE id=?""",
            (args.prediction_id,),
        ).fetchone()
        if row is None:
            json.dump({"error": f"prediction {args.prediction_id} not found"},
                      sys.stdout)
            print()
            return 4
        now = datetime.datetime.now(datetime.timezone.utc)
        start = datetime.datetime.strptime(
            row["created_at"].split(".")[0], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone.utc)
        remaining = row["window_seconds"] - (now - start).total_seconds()
        if remaining > 0:
            json.dump({"prediction_id": row["id"], "verdict": None,
                       "window_open": True,
                       "seconds_remaining": int(remaining)}, sys.stdout)
            print()
            return 3
        entries = infragraph.parse_triage_log(args.log)
        actual = ev._actual_set(entries, start, row["window_seconds"],
                                (row["parent_host"], row["parent_rule"]))
        predicted = json.loads(row["predicted"] or "[]")
        verdict, detail = infragraph.action_verdict(
            predicted, actual, target_host=row["parent_host"])
        infragraph.write_verdict(conn, row["id"], verdict, detail)
        # keep the eval bookkeeping consistent if the hourly cron hasn't run yet
        tp, fp, fn = ev._score(predicted, actual)
        conn.execute(
            """UPDATE infragraph_predictions
               SET evaluated_at=COALESCE(evaluated_at, ?), actual=?,
                   tp=?, fp=?, fn=?
               WHERE id=?""",
            (now.strftime("%Y-%m-%dT%H:%M:%SZ"),
             json.dumps(actual, ensure_ascii=False), tp, fp, fn, row["id"]),
        )
        conn.commit()
        if args.notify and row["parent_issue_id"]:
            ev._post_yt_comment(row["parent_issue_id"],
                                ev._verdict_comment(row, verdict, detail))
        json.dump({"prediction_id": row["id"], "verdict": verdict,
                   "detail": detail}, sys.stdout, ensure_ascii=False)
        print()
        return {"match": 0, "partial": 1, "deviation": 2}[verdict]
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
