#!/usr/bin/env python3
"""infragraph-eval — evaluate predictions against observed reality.

Epic IFRNLLEI01PRD-1029; this evaluator is IFRNLLEI01PRD-1035 (+ the hourly
Phase B pass of -1039).

  --pending           evaluate recorded infragraph_predictions whose window
                      has closed: actual = triage.log (host, rule) pairs in
                      (created_at, created_at + window]; writes tp/fp/fn +
                      control_tp/control_fp + actual JSON back to the row.
  --replay YYYY-MM-DD backtest: walk that day's triage.log chronologically;
                      for each alert, use the CURRENT graph to predict the
                      cascade and score it against what actually followed.
                      Also scores the shuffled-graph control on the same
                      walk. Pure read-only — nothing is written. This is the
                      concept's go/no-go evidence (designed to be able to
                      FAIL: if control ≈ real, the graph adds nothing).

Replay honesty notes (also encoded in the output):
  * Retrodiction with today's graph — including edges learned FROM the replay
    period. Fine for "does graph structure capture cascades", documented.
  * recall counts every later same-window alert as in-scope, so it is a
    LOWER BOUND (independent co-incident alerts count against it).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import infragraph  # noqa: E402

from lib.schema_version import CURRENT_SCHEMA_VERSION as CSV  # noqa: E402

REPLAY_WINDOW_S = int(os.environ.get("INFRAGRAPH_REPLAY_WINDOW_S", "900"))
REPLAY_DEPTH = int(os.environ.get("INFRAGRAPH_REPLAY_DEPTH", "2"))


def _ts(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


# ── pending-prediction evaluation (Phase B hourly pass) ─────────────────────────


def _actual_set(entries: list[dict], start: datetime.datetime,
                window_s: int, exclude: tuple[str, str]) -> list[dict]:
    out, seen = [], set()
    for e in entries:
        t = _ts(e["ts"])
        if t <= start or (t - start).total_seconds() > window_s:
            continue
        key = (e["host"], e["rule"])
        if key == exclude or key in seen:
            continue
        seen.add(key)
        out.append({"host": e["host"], "rule": e["rule"], "ts": e["ts"]})
    return out


def _score(predicted: list[dict], actual: list[dict]) -> tuple[int, int, int]:
    # Exact (host, rule). Single source of truth in lib (IFRNLLEI01PRD-1119).
    return infragraph.score_prediction(predicted, actual, family=False)


def _post_yt_comment(issue_id: str, text: str) -> bool:
    """Best-effort YT comment (verdict evidence trail). Never raises."""
    import ssl
    import urllib.request
    url = os.environ.get("YOUTRACK_URL", "https://youtrack.example.net")
    token = os.environ.get("YOUTRACK_API_TOKEN", "")
    if not token:
        env_path = os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")
        try:
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("YOUTRACK_API_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    if not token or not issue_id:
        return False
    try:
        req = urllib.request.Request(
            f"{url}/api/issues/{issue_id}/comments?fields=id",
            data=json.dumps({"text": text}).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            method="POST")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx):
            return True
    except Exception:  # noqa: BLE001 — evidence trail is best-effort
        return False


def _verdict_comment(row, verdict: str, detail: dict) -> str:
    head = {"match": "✅ MATCH", "partial": "🟡 PARTIAL",
            "deviation": "🔴 DEVIATION — SURPRISE, do not auto-resolve"}[verdict]
    lines = [
        f"## Infragraph mechanical verification — {head}",
        "",
        f"Prediction #{row['id']} ({row['parent_rule']} on {row['parent_host']}, "
        f"window {row['window_seconds']}s) scored by `infragraph-eval.py` — "
        "machine-computed diff, not LLM judgment (IFRNLLEI01PRD-1045).",
        "",
        f"- observed alerts in window: {len(detail['observed'])}",
        f"- matched predictions: {len(detail['matched'])}",
        f"- host-level only (predicted host, unpredicted rule): {len(detail['host_level_only'])}",
        f"- surprises (unpredicted hosts): {len(detail['surprises'])}",
    ]
    for s in detail["surprises"][:5]:
        lines.append(f"  - 🔴 {s[0]}: \"{s[1]}\"")
    if verdict == "deviation":
        lines.append("")
        lines.append("**The world diverged from the model — human review required. "
                     "This outcome is NOT eligible for auto-resolution.**")
    return "\n".join(lines)


def eval_pending(conn, log_path: str | None = None,
                 notify: bool = True) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = conn.execute(
        """SELECT id, created_at, kind, parent_issue_id, parent_host,
                  parent_rule, window_seconds, predicted, control_predicted
           FROM infragraph_predictions WHERE evaluated_at IS NULL""",
    ).fetchall()
    entries = infragraph.parse_triage_log(log_path)
    n_eval = n_verdict = 0
    verdicts: dict[str, int] = {}
    for r in rows:
        created = r["created_at"]
        # created_at is SQLite CURRENT_TIMESTAMP ("YYYY-MM-DD HH:MM:SS", UTC)
        start = datetime.datetime.strptime(
            created.split(".")[0], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone.utc)
        if (now - start).total_seconds() <= r["window_seconds"]:
            continue  # window still open
        actual = _actual_set(entries, start, r["window_seconds"],
                             (r["parent_host"], r["parent_rule"]))
        predicted = json.loads(r["predicted"] or "[]")
        tp, fp, fn = _score(predicted, actual)
        ctp, cfp, _ = _score(json.loads(r["control_predicted"] or "[]"), actual)
        conn.execute(
            """UPDATE infragraph_predictions
               SET evaluated_at=?, actual=?, tp=?, fp=?, fn=?,
                   control_tp=?, control_fp=?, schema_version=?
               WHERE id=?""",
            (now.strftime("%Y-%m-%dT%H:%M:%SZ"),
             json.dumps(actual, ensure_ascii=False),
             tp, fp, fn, ctp, cfp, CSV["infragraph_predictions"], r["id"]),
        )
        n_eval += 1
        if r["kind"] == "action":
            # IFRNLLEI01PRD-1045: mechanical verdict — code adjudicates,
            # never the session that proposed the action.
            verdict, detail = infragraph.action_verdict(
                predicted, actual, target_host=r["parent_host"])
            infragraph.write_verdict(conn, r["id"], verdict, detail)
            n_verdict += 1
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
            if notify and r["parent_issue_id"]:
                _post_yt_comment(r["parent_issue_id"],
                                 _verdict_comment(r, verdict, detail))
    conn.commit()
    return {"pending": len(rows), "evaluated": n_eval,
            "action_verdicts": n_verdict, "verdict_breakdown": verdicts}


# ── weekly scorecard (Phase B evidence for the -1040 gate review) ───────────────

GATE_B2C = {
    "min_evaluated": 30, "min_days": 14, "min_parent_rules": 3,
    "min_precision_conf08": 0.95, "min_recall": 0.40,
    "max_control_ratio": 0.5,
}

# Honest current-model gate: the exact precision_conf08 above is computed over a
# 0.8 confidence floor, but calibrated cascade probabilities top out at ~0.70
# (no real infra cascade is 95% deterministic), so under honest gating (v2) the
# >=0.8 band is empty and the exact gate is unsatisfiable. The legacy v1 rows
# (structural confidence) are the only thing that ever populated it, all misses.
# GATE_MIN_MODEL_VERSION restricts the gate to the live gating model so the
# scorecard reflects the CURRENT predictor, not a retired one.
GATE_MIN_MODEL_VERSION = 2

# OPERATIVE recalibrated gate for the FOLD use-case (blast-radius dedup, NOT
# auto-resolution). Operator set this LIVE at precision 0.80 on 2026-06-24
# (IFRNLLEI01PRD-1040). Folding is reversible + guarded by the never-auto-resolve
# floor, so it tolerates the stochastic ~0.70 ceiling that auto-resolution can't.
# Eligible band = cascade_prob_family >= fold_min_prob; scored at rule-family
# granularity; bar = fold_min_precision. RECALL IS NOT A BLOCKER: for folding,
# low recall = under-folding = SAFE (missed folds just escalate normally); only
# precision (wrong folds), evidence (days/n), and falsifiability (control) gate.
FOLD_GATE = {
    "fold_min_prob": 0.60, "fold_min_precision": 0.80,
    "min_recall": 0.40, "max_control_ratio": 0.5,
}


def scorecard(conn, log_path: str | None = None) -> dict:
    def window_stats(days: int, min_mv: int | None = None) -> dict:
        rows = conn.execute(
            """SELECT kind, parent_host, parent_rule, predicted, actual,
                      tp, fp, fn, control_tp, control_fp, created_at,
                      COALESCE(model_version, 1) AS model_version
               FROM infragraph_predictions
               WHERE evaluated_at IS NOT NULL
                 AND created_at >= datetime('now', ?)
                 AND (? IS NULL OR COALESCE(model_version, 1) >= ?)""",
            (f"-{days} days", min_mv, min_mv),
        ).fetchall()
        tp = sum(r["tp"] or 0 for r in rows)
        fp = sum(r["fp"] or 0 for r in rows)
        fn = sum(r["fn"] or 0 for r in rows)
        ctp = sum(r["control_tp"] or 0 for r in rows)
        cfp = sum(r["control_fp"] or 0 for r in rows)
        # conf>=0.8 subset (the only subset eligible for Phase C suppression),
        # scored both exact and at rule-family granularity (IFRNLLEI01PRD-1119).
        h_tp = h_fp = hf_tp = hf_fp = 0          # conf08 exact / conf08 family
        fold_tp = fold_fp = 0                      # CANDIDATE fold-gate band (family)
        ftp = ffp = ffn = 0                       # overall family
        for r in rows:
            act = json.loads(r["actual"] or "[]")
            pred = json.loads(r["predicted"] or "[]")
            t, f, n = infragraph.score_prediction(pred, act, family=True)
            ftp += t; ffp += f; ffn += n
            actual_pairs = {(a["host"], a["rule"]) for a in act}
            actual_fams = {(a["host"], infragraph.rule_family(a["rule"])) for a in act}
            for p in pred:
                if (p.get("confidence") or 0) >= 0.8:
                    if (p.get("host"), p.get("rule")) in actual_pairs:
                        h_tp += 1
                    else:
                        h_fp += 1
                # family conf08 gates on the FAMILY confidence (cascade_prob_family,
                # set by -1118 gating); falls back to exact confidence for legacy
                # v1 rows that predate gating.
                fam_conf = p.get("cascade_prob_family")
                if fam_conf is None:
                    fam_conf = p.get("confidence") or 0
                fam_hit = (p.get("host"), infragraph.rule_family(p.get("rule"))) in actual_fams
                if fam_conf >= 0.8:
                    if fam_hit:
                        hf_tp += 1
                    else:
                        hf_fp += 1
                # CANDIDATE fold-gate band (advisory, -1040): family precision on
                # the realistic cascade_prob_family >= FOLD_MIN_PROB subset.
                if fam_conf >= FOLD_GATE["fold_min_prob"]:
                    if fam_hit:
                        fold_tp += 1
                    else:
                        fold_fp += 1
        prec = tp / (tp + fp) if (tp + fp) else None
        cprec = ctp / (ctp + cfp) if (ctp + cfp) else None
        return {
            "evaluated": len(rows),
            "distinct_parent_rules": len({r["parent_rule"] for r in rows}),
            "sites": sorted({r["parent_host"][:7] for r in rows}),
            "precision": round(prec, 4) if prec is not None else None,
            "recall_lower_bound": round(tp / (tp + fn), 4) if (tp + fn) else None,
            "precision_conf08": round(h_tp / (h_tp + h_fp), 4) if (h_tp + h_fp) else None,
            # rule-family granularity (IFRNLLEI01PRD-1119) — the operationally
            # meaningful unit; reported next to exact for the -1040 gate review.
            "precision_family": round(ftp / (ftp + ffp), 4) if (ftp + ffp) else None,
            "recall_lower_bound_family": round(ftp / (ftp + ffn), 4) if (ftp + ffn) else None,
            "precision_conf08_family": round(hf_tp / (hf_tp + hf_fp), 4) if (hf_tp + hf_fp) else None,
            # CANDIDATE fold-gate (advisory): family precision on the realistic
            # cascade_prob_family >= FOLD_MIN_PROB band (IFRNLLEI01PRD-1040 proposal).
            "precision_fold_family": round(fold_tp / (fold_tp + fold_fp), 4) if (fold_tp + fold_fp) else None,
            "fold_band_n": fold_tp + fold_fp,
            "control_precision": round(cprec, 4) if cprec is not None else None,
            "control_ratio": round(cprec / prec, 4) if (prec and cprec is not None) else None,
            "first_created": min((r["created_at"] for r in rows), default=None),
        }

    s7, s30 = window_stats(7), window_stats(30)
    # Honest current-model gate view: exclude retired v1 (structural-confidence)
    # predictions so the gate measures the LIVE gating model, not a superseded one
    # (the v1 rows are the only thing that ever populated the >=0.8 band — all
    # misses — so including them reports a dead model's precision).
    s30_gate = window_stats(30, min_mv=GATE_MIN_MODEL_VERSION)
    # frozen per-incident auto-resolve baseline (best outcome per issue, 30d)
    entries = infragraph.parse_triage_log(log_path)
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    best: dict[str, str] = {}
    rank = {"resolved": 3, "resolved-knownpattern": 3,
            "resolved-active-memory": 3, "dedup": 2, "escalated": 1}
    for e in entries:
        if e["ts"] < cutoff or not e["issue_id"]:
            continue
        if rank.get(e["outcome"], 0) > rank.get(best.get(e["issue_id"], ""), 0):
            best[e["issue_id"]] = e["outcome"]
    res = sum(1 for v in best.values() if rank.get(v) == 3)
    esc = sum(1 for v in best.values() if rank.get(v) == 1)
    days_observed = 0.0
    if s30_gate["first_created"]:
        first = datetime.datetime.strptime(
            s30_gate["first_created"].split(".")[0], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=datetime.timezone.utc)
        days_observed = (datetime.datetime.now(datetime.timezone.utc)
                         - first).total_seconds() / 86400
    gate = {
        "criteria": GATE_B2C,
        "model_version_floor": GATE_MIN_MODEL_VERSION,
        "evaluated_ok": s30_gate["evaluated"] >= GATE_B2C["min_evaluated"],
        "days_ok": days_observed >= GATE_B2C["min_days"],
        "rules_ok": s30_gate["distinct_parent_rules"] >= GATE_B2C["min_parent_rules"],
        "sites_ok": len(s30_gate["sites"]) >= 2,
        "precision_conf08_ok": (s30_gate["precision_conf08"] or 0) >= GATE_B2C["min_precision_conf08"],
        "recall_ok": (s30_gate["recall_lower_bound"] or 0) >= GATE_B2C["min_recall"],
        "control_ok": s30_gate["control_ratio"] is not None
                      and s30_gate["control_ratio"] <= GATE_B2C["max_control_ratio"],
    }
    gate["all_met"] = all(v for k, v in gate.items() if k.endswith("_ok"))
    # Family-granularity verdict (IFRNLLEI01PRD-1119), REPORTED alongside the
    # exact gate — the -1040 human review decides whether to promote on the
    # rule-family unit. Nested so its *_ok keys stay out of the exact all_met above.
    pcf = s30_gate["precision_conf08_family"]
    gate["family"] = {
        "precision_conf08_family": pcf,
        "precision_family": s30_gate["precision_family"],
        "recall_family": s30_gate["recall_lower_bound_family"],
        "precision_conf08_family_ok": (pcf or 0) >= GATE_B2C["min_precision_conf08"],
        "all_met_family": all([
            gate["evaluated_ok"], gate["days_ok"], gate["rules_ok"],
            gate["sites_ok"], gate["recall_ok"], gate["control_ok"],
            (pcf or 0) >= GATE_B2C["min_precision_conf08"],
        ]),
    }
    # OPERATIVE fold-gate verdict (IFRNLLEI01PRD-1040, set LIVE at 0.80 by the
    # operator 2026-06-24). When all_met_fold is True AND the operator sentinel
    # ~/gateway.infragraph_autofold exists, infragraph-propose-blast-radius
    # auto-approves proposed fold rules (autonomous Phase C). Folding = dedup only
    # (conf 0.90); the never-auto-resolve floor (critical/irreversible/deviation)
    # is unchanged. RECALL is reported but does NOT gate (low recall = under-fold
    # = safe). precision + evidence(days/n/rules/sites) + control(falsifiability) gate.
    pff = s30_gate["precision_fold_family"]
    gate["fold_candidate"] = {
        "criteria": FOLD_GATE,
        "precision_fold_family": pff,
        "fold_band_n": s30_gate["fold_band_n"],
        "precision_ok": (pff or 0) >= FOLD_GATE["fold_min_precision"],
        "recall_family": s30_gate["recall_lower_bound_family"],  # reported, not gating
        "control_ok": gate["control_ok"],
        "all_met_fold": all([
            gate["evaluated_ok"], gate["days_ok"], gate["rules_ok"], gate["sites_ok"],
            (pff or 0) >= FOLD_GATE["fold_min_precision"],
            gate["control_ok"],
        ]),
        "note": "OPERATIVE — fold use-case gate, set live at precision 0.80 by the "
                "operator (-1040). Autonomous fold activates only while the "
                "~/gateway.infragraph_autofold sentinel exists (rm = instant kill). "
                "Safety floor (critical/irreversible/deviation never auto-resolve) unchanged.",
    }
    return {
        "window_7d": s7,
        "window_30d": s30,
        "window_30d_gated": s30_gate,   # current-model (v2+) honest view
        "days_observed": round(days_observed, 1),
        "auto_resolve_baseline_30d": {
            "counting_unit": "incident",
            "resolved": res, "escalated": esc,
            "rate": round(res / (res + esc), 4) if (res + esc) else None,
        },
        "gate_b_to_c": gate,
    }


# ── backtest replay (read-only) ─────────────────────────────────────────────────


def replay(conn, day: str, log_path: str | None = None) -> dict:
    entries = infragraph.parse_triage_log(
        log_path, since=day, until=day + "T23:59:59Z")
    parsed = [(e, _ts(e["ts"])) for e in entries]
    total = len(parsed)

    # Per-alert: was it RETRODICTED by any earlier alert's predicted cascade?
    # An alert E is "predicted" if some earlier alert P (within WINDOW before E)
    # has E.host in blast_radius(P.host) AND (edge expected_alerts contain
    # E.rule OR no expected_alerts are recorded for that host yet — host-level
    # match at half confidence, reported separately).
    cascade_cache: dict[str, dict[str, set]] = {}

    def predicted_map(host: str) -> dict[str, set]:
        if host not in cascade_cache:
            preds, _w = infragraph.expected_cascade(conn, host, depth=REPLAY_DEPTH) \
                if infragraph.node_exists(conn, host) else ([], 0)
            by_host: dict[str, set] = {}
            for p in preds:
                by_host.setdefault(p["host"], set()).add(p["rule"])
            # blast-radius + sibling hosts without recorded rules: host-level reach
            if infragraph.node_exists(conn, host):
                for n in infragraph.traverse(conn, host, "blast_radius", REPLAY_DEPTH):
                    by_host.setdefault(n["name"], set())
                for s in infragraph.siblings(conn, host):
                    by_host.setdefault(s["name"], set())
            cascade_cache[host] = by_host
        return cascade_cache[host]

    # Control: same walk on the shuffled graph (host-level only).
    control_cache: dict[str, set] = {}

    def control_hosts(host: str) -> set:
        if host not in control_cache:
            ctrl = infragraph.shuffled_control(conn, host, REPLAY_DEPTH, seed=day) \
                if infragraph.node_exists(conn, host) else []
            hosts = {c["host"] for c in ctrl}
            # shuffled_control only emits hosts with rules; widen with a
            # degree-matched BFS is overkill — host set is the control surface
            control_cache[host] = hosts
        return control_cache[host]

    rule_hits = host_hits = control_hits = 0
    escalated_total = escalated_hits = 0
    misses: list[dict] = []
    for i, (e, t) in enumerate(parsed):
        is_esc = e["outcome"] == "escalated"
        predicted_by_rule = predicted_by_host = predicted_by_control = False
        for j in range(i - 1, -1, -1):
            p, tp_ = parsed[j]
            if (t - tp_).total_seconds() > REPLAY_WINDOW_S:
                break
            if p["host"] == e["host"]:
                continue
            pm = predicted_map(p["host"])
            if e["host"] in pm:
                if e["rule"] in pm[e["host"]]:
                    predicted_by_rule = True
                else:
                    predicted_by_host = True
            if e["host"] in control_hosts(p["host"]):
                predicted_by_control = True
            if predicted_by_rule:
                break
        if predicted_by_rule:
            rule_hits += 1
        elif predicted_by_host:
            host_hits += 1
        elif len(misses) < 15:
            misses.append({"ts": e["ts"], "host": e["host"], "rule": e["rule"]})
        if predicted_by_control:
            control_hits += 1
        if is_esc:
            escalated_total += 1
            if predicted_by_rule or predicted_by_host:
                escalated_hits += 1

    covered = rule_hits + host_hits
    return {
        "replay_day": day,
        "window_seconds": REPLAY_WINDOW_S,
        "depth": REPLAY_DEPTH,
        "alerts_total": total,
        "predicted_rule_level": rule_hits,
        "predicted_host_level": host_hits,
        "predicted_any": covered,
        "coverage": round(covered / total, 4) if total else None,
        "escalated_total": escalated_total,
        "escalated_predicted": escalated_hits,
        "escalated_coverage": round(escalated_hits / escalated_total, 4)
        if escalated_total else None,
        "control_predicted": control_hits,
        "control_coverage": round(control_hits / total, 4) if total else None,
        "control_ratio": round(control_hits / covered, 4) if covered else None,
        "sample_misses": misses,
        "notes": [
            "retrodiction with the CURRENT graph (incl. edges learned from this period)",
            "first-alert roots can never be 'predicted' — coverage ceiling < 1.0 by design",
            "control = degree-preserving shuffled graph, host-level, same walk",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="infragraph-eval")
    ap.add_argument("--db", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--replay", metavar="YYYY-MM-DD", default="")
    ap.add_argument("--scorecard", action="store_true",
                    help="emit the weekly Phase B scorecard (-1040 gate evidence)")
    ap.add_argument("--out", default="", help="also write scorecard JSON here")
    ap.add_argument("--no-notify", action="store_true",
                    help="suppress YT verdict comments (QA)")
    args = ap.parse_args()
    if not (args.pending or args.replay or args.scorecard):
        ap.error("pick --pending, --replay DATE, and/or --scorecard")

    conn = infragraph.get_db(args.db)
    report = {}
    try:
        if args.pending:
            report["pending"] = eval_pending(conn, args.log,
                                             notify=not args.no_notify)
        if args.replay:
            report["replay"] = replay(conn, args.replay, args.log)
        if args.scorecard:
            report["scorecard"] = scorecard(conn, args.log)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    json.dump(report["scorecard"], fh, ensure_ascii=False,
                              indent=2)
    finally:
        conn.close()
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
