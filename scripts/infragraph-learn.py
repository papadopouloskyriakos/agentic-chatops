#!/usr/bin/env python3
"""infragraph-learn — fold empirical observations into edge dynamics.

Epic IFRNLLEI01PRD-1029; this learner is IFRNLLEI01PRD-1034.

  --from-chaos      chaos_experiments rows → tunnel-edge dynamics
                    (expected_alerts ∪ observed, delay←mttd, recovery←mttr,
                    observation_count++, confidence from verdict). Idempotent
                    via experiment_id watermark in openclaw_memory.
  --from-incidents  triage.log co-occurrence mining → depends_on edges +
                    expected_alerts. A candidate (parent_host → child_host,
                    child_rule) is written ONLY when:
                      * observed ≥ MIN_OBS times (default 3), AND
                      * lift ≥ MIN_LIFT (default 3.0) over the child pair's
                        base rate, AND
                      * the hosts are ≤ MAX_HOPS apart in the existing
                        topology graph (default 2) OR same site-prefix.
                    Guards against coincidental simultaneity.

Run hourly by cron; both passes are incremental and cheap.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import infragraph  # noqa: E402

MIN_OBS = int(os.environ.get("INFRAGRAPH_LEARN_MIN_OBS", "3"))
MIN_LIFT = float(os.environ.get("INFRAGRAPH_LEARN_MIN_LIFT", "3.0"))
MAX_HOPS = int(os.environ.get("INFRAGRAPH_LEARN_MAX_HOPS", "2"))
WINDOW_S = int(os.environ.get("INFRAGRAPH_LEARN_WINDOW_S", "900"))
WATERMARK_KEY = "learn-chaos-watermark"


# ── chaos pass ──────────────────────────────────────────────────────────────────


def _tunnel_entity_name(label: str, wan: str) -> str:
    return f"tunnel:{label.replace(' ', '').replace('↔', '-')}:{wan}"


def _get_watermark(conn) -> str:
    row = conn.execute(
        "SELECT value FROM openclaw_memory WHERE category='infragraph-seed' AND key=? LIMIT 1",
        (WATERMARK_KEY,),
    ).fetchone()
    return row["value"] if row else ""


def _set_watermark(conn, experiment_id: str) -> None:
    row = conn.execute(
        "SELECT id FROM openclaw_memory WHERE category='infragraph-seed' AND key=? LIMIT 1",
        (WATERMARK_KEY,),
    ).fetchone()
    if row:
        conn.execute("UPDATE openclaw_memory SET value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (experiment_id, row["id"]))
    else:
        conn.execute(
            "INSERT INTO openclaw_memory (category, key, value) VALUES ('infragraph-seed', ?, ?)",
            (WATERMARK_KEY, experiment_id))


def learn_from_chaos(conn) -> dict:
    watermark = _get_watermark(conn)
    rows = conn.execute(
        """SELECT id, experiment_id, targets, expected_alerts, unexpected_alerts,
                  mttd_seconds, mttr_seconds, verdict
           FROM chaos_experiments
           WHERE experiment_id > ? ORDER BY experiment_id""",
        (watermark,),
    ).fetchall()
    n_edges = n_rows = 0
    last_id = watermark
    for r in rows:
        last_id = r["experiment_id"]
        try:
            targets = json.loads(r["targets"] or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(targets, dict):
            # 3 legacy game-day rows store a bare list of "device:interface"
            # strings — no tunnel mapping to learn from; skip, don't crash.
            continue
        observed_rules: list[str] = []
        for col in ("expected_alerts", "unexpected_alerts"):
            try:
                vals = json.loads(r[col] or "[]")
            except json.JSONDecodeError:
                vals = []
            for v in vals:
                rule = v.get("rule") if isinstance(v, dict) else str(v)
                if rule:
                    observed_rules.append(infragraph.normalize_rule(rule))
        verdict_conf = {"PASS": 0.9, "DEGRADED": 0.7, "FAIL": 0.5}.get(
            (r["verdict"] or "").upper(), None)
        for t in targets.get("tunnels_killed", []) or []:
            tname = _tunnel_entity_name(t.get("tunnel", ""), t.get("wan", ""))
            edge_rows = conn.execute(
                """SELECT gr.id FROM graph_relationships gr
                   JOIN graph_entities tgt ON tgt.id = gr.target_id
                   WHERE tgt.entity_type='tunnel' AND tgt.name=?""",
                (tname,),
            ).fetchall()
            for er in edge_rows:
                infragraph.update_dynamics(
                    conn, er["id"],
                    observed_rules=observed_rules or None,
                    delay_s=r["mttd_seconds"],
                    recovery_s=r["mttr_seconds"],
                    confidence=verdict_conf,
                )
                # provenance: chaos-grade evidence outranks the seed bucket
                conn.execute(
                    "UPDATE infragraph_dynamics SET source='chaos' WHERE rel_id=?",
                    (er["id"],))
                n_edges += 1
        n_rows += 1
    if last_id != watermark:
        _set_watermark(conn, last_id)
    return {"experiments_processed": n_rows, "edge_updates": n_edges,
            "watermark": last_id}


# ── incident co-occurrence pass ─────────────────────────────────────────────────


def _ts(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def _site_prefix(host: str) -> str:
    return host[:7] if len(host) >= 7 else host


def _hops_ok(conn, a: str, b: str) -> bool:
    """≤ MAX_HOPS apart in topology, either direction — or same site prefix
    (the topology is still sparse; same-site is a weaker but useful prior)."""
    if _site_prefix(a) == _site_prefix(b):
        return True
    for direction in ("deps", "blast_radius"):
        for n in infragraph.traverse(conn, a, direction, MAX_HOPS):
            if n["name"] == b:
                return True
    return False


def learn_from_incidents(conn, log_path: str | None = None,
                         since: str = "", until: str = "") -> dict:
    entries = infragraph.parse_triage_log(log_path, since=since, until=until)
    if not entries:
        return {"entries": 0, "candidates": 0, "edges_written": 0}

    # Pair counting: parent (host,rule) at t → child (host,rule) within WINDOW_S.
    # Same-host pairs are excluded (that's flapping, not propagation).
    pair_count: dict[tuple, int] = defaultdict(int)
    child_count: dict[tuple, int] = defaultdict(int)
    parent_count: dict[tuple, int] = defaultdict(int)
    parsed = [(e, _ts(e["ts"])) for e in entries]
    for i, (e, t) in enumerate(parsed):
        parent_count[(e["host"], e["rule"])] += 1
        child_count[(e["host"], e["rule"])] += 1
        for j in range(i + 1, len(parsed)):
            e2, t2 = parsed[j]
            if (t2 - t).total_seconds() > WINDOW_S:
                break
            if e2["host"] == e["host"]:
                continue
            pair_count[(e["host"], e["rule"], e2["host"], e2["rule"])] += 1

    total = len(parsed)
    written = candidates = 0
    for (ph, pr, ch, cr), cnt in sorted(pair_count.items()):
        if cnt < MIN_OBS:
            continue
        # lift = P(child | parent) / P(child)
        p_child_given_parent = cnt / max(parent_count[(ph, pr)], 1)
        p_child = child_count[(ch, cr)] / max(total, 1)
        lift = p_child_given_parent / p_child if p_child > 0 else 0.0
        if lift < MIN_LIFT:
            continue
        candidates += 1
        if not _hops_ok(conn, ph, ch):
            continue
        # child depends on parent (child's alert is a consequence of parent
        # failing). Resolve to the seeded entity type — a wrong-typed twin
        # node would be invisible to traversal.
        src = infragraph.resolve_entity(conn, ch) or ("physical_host", ch)
        tgt = infragraph.resolve_entity(conn, ph) or ("physical_host", ph)
        conf = min(0.75, 0.4 + 0.05 * cnt)  # incident-mined edges cap below 0.8
        rel_id = infragraph.upsert_edge(
            conn, src, tgt, "depends_on",
            source="incident", confidence=conf,
            metadata={"mined": True, "observations": cnt, "lift": round(lift, 2)})
        infragraph.update_dynamics(conn, rel_id, observed_rules=[cr])
        written += 1
    return {"entries": total, "candidates": candidates, "edges_written": written}


def main() -> int:
    ap = argparse.ArgumentParser(prog="infragraph-learn")
    ap.add_argument("--db", default=None)
    ap.add_argument("--log", default=None, help="triage.log override")
    ap.add_argument("--from-chaos", action="store_true")
    ap.add_argument("--from-incidents", action="store_true")
    ap.add_argument("--since", default="", help="ISO prefix filter for incidents pass")
    ap.add_argument("--until", default="")
    args = ap.parse_args()
    if not (args.from_chaos or args.from_incidents):
        ap.error("pick --from-chaos and/or --from-incidents")

    conn = infragraph.get_db(args.db)
    report = {}
    try:
        if args.from_chaos:
            report["chaos"] = learn_from_chaos(conn)
            conn.commit()
        if args.from_incidents:
            report["incidents"] = learn_from_incidents(
                conn, args.log, since=args.since, until=args.until)
            conn.commit()
    finally:
        conn.close()
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
