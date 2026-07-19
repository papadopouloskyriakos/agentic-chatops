#!/usr/bin/env python3
"""infragraph-query — the frozen query contract for the infragraph.

Epic IFRNLLEI01PRD-1029; this CLI is IFRNLLEI01PRD-1033.
Contract (model_version 1) documented in docs/plans/infragraph-implementation-plan.md.

Subcommands:
  blast-radius --host H [--depth 3]      who is affected if H fails
  deps         --host H [--depth 3]      what H depends on
  cascade      --host H [--rule R] [--depth 2] [--record --issue YT-ID]
                                          predicted downstream alert set
  explain      --from A --to B            top-3 dependency paths A -> B
  health                                  graph + prediction statistics

Output: one JSON object on stdout. Exit codes: 0 = ok, 1 = host unknown /
graph empty (callers treat as "no graph data" and fail open), 2 = error or
the 2-second self-timeout. Callers in the triage hot path MUST treat any
non-zero exit as advisory-absent, never as a triage failure.

Set INFRAGRAPH_DISABLED=1 to make every invocation exit 1 immediately
(the kill-switch the rollback runbook references).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import infragraph  # noqa: E402

TIMEOUT_S = 2


class _Timeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise _Timeout()


def _emit(obj: dict, started: float, code: int = 0) -> int:
    obj["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_traverse(conn, args, started: float, direction: str) -> int:
    query_name = "blast_radius" if direction == "blast_radius" else "deps"
    if not infragraph.node_exists(conn, args.host):
        return _emit({"query": query_name, "host": args.host,
                      "error": "host not in infragraph"}, started, 1)
    nodes = infragraph.traverse(conn, args.host, direction, args.depth)
    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n["entity_type"]] = by_type.get(n["entity_type"], 0) + 1
    return _emit({
        "query": query_name,
        "host": args.host,
        "depth": args.depth,
        "generated_at": _now_iso(),
        "nodes": nodes,
        "counts": {"total": len(nodes), "by_type": by_type},
    }, started)


def cmd_cascade(conn, args, started: float) -> int:
    if not infragraph.node_exists(conn, args.host):
        return _emit({"query": "expected_cascade", "host": args.host,
                      "rule": args.rule, "error": "host not in infragraph"},
                     started, 1)
    predictions, window = infragraph.expected_cascade(conn, args.host,
                                                      args.rule, args.depth)
    prediction_id = None
    if args.record:
        # Gate the negative control through the SAME cascade-probability pipeline
        # (IFRNLLEI01PRD-1118) so the falsifiability ratio compares like with
        # like. The action lane (cmd_predict) is deliberately NOT gated.
        control = infragraph.shuffled_control(conn, args.host, args.depth)
        control = infragraph.apply_cascade_gating(conn, control, args.rule)
        prediction_id = infragraph.record_prediction(
            conn,
            parent_host=args.host, parent_rule=args.rule,
            parent_issue_id=args.issue, window_seconds=window,
            predicted=predictions, control=control,
        )
        conn.commit()
    return _emit({
        "query": "expected_cascade",
        "host": args.host,
        "rule": args.rule,
        "window_seconds": window,
        "predictions": predictions,
        "model_version": infragraph.MODEL_VERSION,
        "prediction_id": prediction_id,
    }, started)


def cmd_predict(conn, args, started: float) -> int:
    """Action-conditioned prediction + MANDATORY artifact commit (-1044).

    Unlike the advisory subcommands this one is part of the fail-CLOSED
    remediation lane: the Runner calls it before any approval poll, and the
    Prepare Result gate refuses remediation polls without the prediction_id
    this emits. Exit 1 = not eligible (gate demotes session to analysis-only).
    """
    if not args.plan_hash:
        return _emit({"query": "predict", "eligible": False,
                      "error": "plan-hash is required (non-bypassable gate key)"},
                     started, 2)
    result = infragraph.predict_action(conn, args.action_kind, args.target,
                                       args.depth)
    result["query"] = "predict"
    result["plan_hash"] = args.plan_hash
    if not result.get("eligible"):
        return _emit(result, started, 1)
    control = infragraph.shuffled_control(conn, args.target, args.depth)
    prediction_id = infragraph.record_prediction(
        conn,
        parent_host=args.target, parent_rule=args.rule or args.action_kind,
        parent_issue_id=args.issue, window_seconds=result["window_seconds"],
        predicted=result["predicted"], control=control,
        kind="action", action_kind=args.action_kind,
        action_target=args.target, plan_hash=args.plan_hash,
    )
    conn.commit()
    result["prediction_id"] = prediction_id
    # compact for prompt/poll rendering: cap the inline list, keep the count
    result["predicted_total"] = len(result["predicted"])
    result["predicted"] = result["predicted"][:10]
    return _emit(result, started)


def cmd_explain(conn, args, started: float) -> int:
    if not infragraph.node_exists(conn, args.frm):
        return _emit({"query": "explain", "from": args.frm, "to": args.to,
                      "error": "from-host not in infragraph"}, started, 1)
    # Forward walk from A keeping ALL simple paths, then filter ones ending at B.
    rows = infragraph.traverse(conn, args.frm, "deps", infragraph.DEPTH_CAP,
                               reduce=False)
    paths = []
    for node in rows:
        if node["name"] != args.to:
            continue
        hops = []
        chain = node["path"]
        for i in range(len(chain) - 1):
            hops.append({"from": chain[i], "to": chain[i + 1]})
        paths.append({
            "hops": hops,
            "length": node["distance"],
            "min_confidence": node["confidence"],
            "via": node["via"],
        })
    paths.sort(key=lambda p: (-p["min_confidence"], p["length"]))
    return _emit({
        "query": "explain",
        "from": args.frm,
        "to": args.to,
        "reachable": bool(paths),
        "paths": paths[:3],
    }, started)


def cmd_health(conn, _args, started: float) -> int:
    h = infragraph.health(conn)
    h["query"] = "health"
    code = 1 if h["nodes_total"] == 0 else 0
    return _emit(h, started, code)


def main() -> int:
    started = time.monotonic()
    if os.environ.get("INFRAGRAPH_DISABLED", "") not in ("", "0"):
        return _emit({"error": "INFRAGRAPH_DISABLED is set"}, started, 1)

    ap = argparse.ArgumentParser(prog="infragraph-query")
    ap.add_argument("--db", default=None, help="override gateway.db path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("blast-radius")
    p.add_argument("--host", required=True)
    p.add_argument("--depth", type=int, default=3)

    p = sub.add_parser("deps")
    p.add_argument("--host", required=True)
    p.add_argument("--depth", type=int, default=3)

    p = sub.add_parser("cascade")
    p.add_argument("--host", required=True)
    p.add_argument("--rule", default="")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--record", action="store_true",
                   help="write a shadow prediction row (Phase B)")
    p.add_argument("--issue", default="", help="parent YouTrack issue id")

    p = sub.add_parser("predict")
    p.add_argument("--action-kind", required=True,
                   choices=sorted(infragraph.ACTION_KINDS))
    p.add_argument("--target", required=True)
    p.add_argument("--plan-hash", required=True)
    p.add_argument("--issue", default="")
    p.add_argument("--rule", default="")
    p.add_argument("--depth", type=int, default=2)

    p = sub.add_parser("explain")
    p.add_argument("--from", dest="frm", required=True)
    p.add_argument("--to", required=True)

    sub.add_parser("health")

    args = ap.parse_args()

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT_S)
    try:
        conn = infragraph.get_db(args.db)
        try:
            if args.cmd == "blast-radius":
                return cmd_traverse(conn, args, started, "blast_radius")
            if args.cmd == "deps":
                return cmd_traverse(conn, args, started, "deps")
            if args.cmd == "cascade":
                return cmd_cascade(conn, args, started)
            if args.cmd == "predict":
                return cmd_predict(conn, args, started)
            if args.cmd == "explain":
                return cmd_explain(conn, args, started)
            if args.cmd == "health":
                return cmd_health(conn, args, started)
            return _emit({"error": f"unknown subcommand {args.cmd}"}, started, 2)
        finally:
            conn.close()
    except _Timeout:
        return _emit({"error": f"self-timeout after {TIMEOUT_S}s"}, started, 2)
    except Exception as e:  # noqa: BLE001 — contract: errors become JSON + exit 2
        return _emit({"error": f"{type(e).__name__}: {e}"}, started, 2)
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    sys.exit(main())
