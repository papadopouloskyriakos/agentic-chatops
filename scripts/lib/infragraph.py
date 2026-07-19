"""Infragraph — causal infra dependency graph with learned dynamics.

Epic IFRNLLEI01PRD-1029; this module is IFRNLLEI01PRD-1031.
Plan of record: docs/plans/infragraph-implementation-plan.md.

Topology lives on the existing G10 GraphRAG tables (graph_entities /
graph_relationships) with source_table='infragraph'; per-edge dynamics live in
the G15 sidecar table infragraph_dynamics; shadow predictions in
infragraph_predictions.

Edge direction convention: SOURCE depends on TARGET.
    vm  -runs_on->     pve_node
    svc -depends_on->  vm
    site-routes_via->  tunnel
blast_radius(H) therefore traverses edges *into* H transitively (who would be
affected if H fails); deps(H) traverses *out of* H (what H needs).

Everything here is read-mostly and must stay cheap: callers in the triage hot
path budget <2s wall for a full blast-radius + cascade query.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import random
import sqlite3
from typing import Any

from lib.schema_version import CURRENT_SCHEMA_VERSION as CSV

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

SOURCE_TABLE = "infragraph"
DEPTH_CAP = 5
MODEL_VERSION = 2  # v2 = cascade-probability gating (IFRNLLEI01PRD-1118); v1 = ungated structural
SAMPLE_CAP = 64  # per-metric reservoir size in infragraph_dynamics.samples
DEFAULT_WINDOW_S = 900

# ── Cascade-probability gating (IFRNLLEI01PRD-1118) ────────────────────────────
# Laplace(alpha,beta) smoothing: an unobserved (parent-family -> child) pair
# defaults to prior mean alpha/(alpha+beta) = 0.20, so cold-start edges are
# emitted (gather observations) but never reach the high-confidence subset until
# they demonstrably cascade. beta>alpha keeps the prior conservative.
CASCADE_PRIOR_ALPHA = 1.0
CASCADE_PRIOR_BETA = 4.0

ENTITY_TYPES = frozenset({
    "physical_host", "pve_node", "vm", "lxc", "service",
    "network_device", "tunnel", "bgp_session", "site",
})
REL_TYPES = frozenset({
    "runs_on", "depends_on", "routes_via", "member_of",
    "backs_up_to", "peers_with",
})
EDGE_SOURCES = frozenset({"declared", "chaos", "incident", "netbox", "iac",
                          "pve", "librenms"})


def get_db(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── triage.log helpers (shared by learners + eval) ──────────────────────────────

TRIAGE_LOG = os.environ.get(
    "TRIAGE_LOG",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/triage.log"),
)

# Live triage.log rule fields embed full alert text, e.g.
#   "-- ALERT -- gr-pve02 -  Service up/down  - Critical Alert"
_RULE_WRAP_RE = None  # compiled lazily


def normalize_rule(raw: str, hostname: str = "") -> str:
    """Strip the LibreNMS alert-text wrapper down to the bare rule name."""
    REDACTED_a7b84d63
    global _RULE_WRAP_RE
    if _RULE_WRAP_RE is None:
        _RULE_WRAP_RE = re.compile(
            r"^--\s*ALERT\s*--\s*(?P<host>\S+)\s*-\s*(?P<rule>.*?)\s*-\s*"
            r"(?:Critical|Warning|Ok)\s*Alert\s*$"
        )
    s = (raw or "").strip()
    m = _RULE_WRAP_RE.match(s)
    if m:
        return m.group("rule").strip()
    return s


def parse_triage_log(path: str | None = None,
                     since: str = "", until: str = "") -> list[dict[str, str]]:
    """Parse triage.log lines (ts|host|rule|site|outcome|conf|dur|issue).

    Rules are normalized. Malformed lines are skipped. since/until are
    inclusive ISO-prefix filters on the timestamp column.
    """
    out = []
    try:
        with open(path or TRIAGE_LOG, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("|")
                if len(parts) < 8 or not parts[0]:
                    continue
                ts = parts[0].strip()
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue
                out.append({
                    "ts": ts,
                    "host": parts[1].strip(),
                    "rule": normalize_rule(parts[2], parts[1].strip()),
                    "site": parts[3].strip(),
                    "outcome": parts[4].strip(),
                    "issue_id": parts[7].strip(),
                })
    except FileNotFoundError:
        pass
    return out


def stamp_seed(conn, source: str) -> None:
    """Record last_seed.<source> in openclaw_memory (read back by health()).

    openclaw_memory has no UNIQUE(category, key) constraint, so this is a
    manual select-then-write upsert to avoid one duplicate row per seed run.
    """
    row = conn.execute(
        "SELECT id FROM openclaw_memory WHERE category='infragraph-seed' AND key=? LIMIT 1",
        (source,),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE openclaw_memory SET value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (_utcnow(), row["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO openclaw_memory (category, key, value) VALUES ('infragraph-seed', ?, ?)",
            (source, _utcnow()),
        )


# ── Upserts (provenance-stamped) ────────────────────────────────────────────────


def upsert_entity(conn, entity_type: str, name: str,
                  attributes: dict | None = None, source_id: str = "") -> int:
    """Insert-or-fetch an infragraph entity; returns graph_entities.id.

    Attributes are merged (new keys win) so repeated seeds enrich rather than
    clobber.
    """
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown infragraph entity_type {entity_type!r}")
    conn.execute(
        """INSERT OR IGNORE INTO graph_entities
           (entity_type, name, source_table, source_id, attributes)
           VALUES (?, ?, ?, ?, ?)""",
        (entity_type, name, SOURCE_TABLE, source_id,
         json.dumps(attributes or {}, ensure_ascii=False)),
    )
    row = conn.execute(
        "SELECT id, attributes FROM graph_entities WHERE entity_type=? AND name=?",
        (entity_type, name),
    ).fetchone()
    if attributes:
        merged = {}
        try:
            merged = json.loads(row["attributes"] or "{}")
        except (json.JSONDecodeError, TypeError):
            pass
        merged.update(attributes)
        conn.execute(
            "UPDATE graph_entities SET attributes=? WHERE id=?",
            (json.dumps(merged, ensure_ascii=False), row["id"]),
        )
    return row["id"]


def upsert_edge(conn, src: tuple[str, str], tgt: tuple[str, str], rel_type: str,
                *, source: str, confidence: float = 0.5,
                valid_until: str | None = None,
                metadata: dict | None = None) -> int:
    """Insert-or-fetch an edge (src depends on tgt) and ensure its dynamics row.

    src/tgt are (entity_type, name) pairs. Returns graph_relationships.id.
    A re-seed refreshes valid_until and bumps confidence only upward for the
    same source; it never downgrades a better-evidenced edge.
    """
    if rel_type not in REL_TYPES:
        raise ValueError(f"unknown infragraph rel_type {rel_type!r}")
    if source not in EDGE_SOURCES:
        raise ValueError(f"unknown infragraph edge source {source!r}")
    src_id = upsert_entity(conn, src[0], src[1])
    tgt_id = upsert_entity(conn, tgt[0], tgt[1])
    row = conn.execute(
        """SELECT id FROM graph_relationships
           WHERE source_id=? AND target_id=? AND rel_type=?""",
        (src_id, tgt_id, rel_type),
    ).fetchone()
    if row:
        rel_id = row["id"]
    else:
        rel_id = conn.execute(
            """INSERT INTO graph_relationships
               (source_id, target_id, rel_type, confidence, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (src_id, tgt_id, rel_type, confidence,
             json.dumps(metadata or {}, ensure_ascii=False)),
        ).lastrowid
    dyn = conn.execute(
        "SELECT id, confidence FROM infragraph_dynamics WHERE rel_id=?",
        (rel_id,),
    ).fetchone()
    if dyn is None:
        conn.execute(
            """INSERT INTO infragraph_dynamics
               (rel_id, source, confidence, valid_until, schema_version)
               VALUES (?, ?, ?, ?, ?)""",
            (rel_id, source, confidence, valid_until, CSV["infragraph_dynamics"]),
        )
    else:
        conn.execute(
            """UPDATE infragraph_dynamics
               SET valid_until=?, confidence=MAX(confidence, ?), updated_at=?
               WHERE rel_id=?""",
            (valid_until, confidence, _utcnow(), rel_id),
        )
    return rel_id


# ── Dynamics ────────────────────────────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round(pct * (len(s) - 1))))
    return float(s[idx])


def update_dynamics(conn, rel_id: int, *,
                    observed_rules: list[str] | None = None,
                    delay_s: float | None = None,
                    recovery_s: float | None = None,
                    confidence: float | None = None) -> None:
    """Fold one observation (chaos run or incident) into an edge's dynamics.

    Keeps the most recent SAMPLE_CAP raw samples per metric and recomputes the
    stored percentiles, so a config change shows up within ~SAMPLE_CAP
    observations rather than being diluted by all history.
    """
    row = conn.execute(
        "SELECT expected_alerts, samples, observation_count FROM infragraph_dynamics WHERE rel_id=?",
        (rel_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no infragraph_dynamics row for rel_id={rel_id}")

    try:
        expected = json.loads(row["expected_alerts"] or "[]")
    except json.JSONDecodeError:
        expected = []
    known = {e.get("rule") for e in expected if isinstance(e, dict)}
    for rule in observed_rules or []:
        if rule not in known:
            expected.append({"rule": rule, "side": "source"})
            known.add(rule)

    try:
        samples = json.loads(row["samples"] or "{}")
    except json.JSONDecodeError:
        samples = {}
    if delay_s is not None:
        samples.setdefault("delay_s", []).append(float(delay_s))
        samples["delay_s"] = samples["delay_s"][-SAMPLE_CAP:]
    if recovery_s is not None:
        samples.setdefault("recovery_s", []).append(float(recovery_s))
        samples["recovery_s"] = samples["recovery_s"][-SAMPLE_CAP:]

    conn.execute(
        """UPDATE infragraph_dynamics SET
             expected_alerts=?, samples=?,
             delay_p50_s=?, delay_p95_s=?, recovery_p50_s=?,
             observation_count=observation_count+1,
             last_validated=?, updated_at=?,
             confidence=COALESCE(?, confidence),
             schema_version=?
           WHERE rel_id=?""",
        (json.dumps(expected, ensure_ascii=False),
         json.dumps(samples, ensure_ascii=False),
         _percentile(samples.get("delay_s", []), 0.50),
         _percentile(samples.get("delay_s", []), 0.95),
         _percentile(samples.get("recovery_s", []), 0.50),
         _utcnow(), _utcnow(), confidence,
         CSV["infragraph_dynamics"], rel_id),
    )


# ── Traversal ───────────────────────────────────────────────────────────────────

_TRAVERSE_SQL = """
WITH RECURSIVE walk(node_id, distance, via, path, conf, provenance) AS (
    SELECT e.id, 0, '', '/' || e.name || '/', 1.0, ''
    FROM graph_entities e
    WHERE e.name = :host AND e.source_table = :st
    UNION ALL
    SELECT next_id, walk.distance + 1, r.rel_type,
           walk.path || ge.name || '/',
           walk.conf * MIN(COALESCE(d.confidence, r.confidence), 1.0),
           d.source
    FROM walk
    JOIN graph_relationships r
         ON {join_cond}
    JOIN infragraph_dynamics d ON d.rel_id = r.id
    JOIN graph_entities ge ON ge.id = next_id
    WHERE walk.distance < :depth
      AND (d.valid_until IS NULL OR d.valid_until > :now)
      AND instr(walk.path, '/' || ge.name || '/') = 0
)
SELECT w.node_id, ge.name, ge.entity_type, ge.attributes,
       w.distance, w.via, w.path, w.conf, w.provenance
FROM walk w
JOIN graph_entities ge ON ge.id = w.node_id
WHERE w.distance > 0
"""


def traverse(conn, host: str, direction: str = "blast_radius",
             depth: int = 3, reduce: bool = True) -> list[dict[str, Any]]:
    """Walk the dependency graph from `host`.

    direction='blast_radius' walks dependency edges in reverse (who depends on
    host, transitively); direction='deps' walks forward (what host needs).
    Returns one dict per reached node with distance, last-hop rel type, full
    path, path-product confidence, and edge provenance — reduced per node to
    the shortest path (ties broken by highest confidence) unless reduce=False,
    in which case every distinct simple path is returned (used by explain to
    surface alternative routes). Cycle-safe via the path string check; depth
    capped at DEPTH_CAP.
    """
    depth = max(1, min(int(depth), DEPTH_CAP))
    if direction == "blast_radius":
        join_cond = "r.target_id = walk.node_id"
        next_expr = "r.source_id"
    elif direction == "deps":
        join_cond = "r.source_id = walk.node_id"
        next_expr = "r.target_id"
    else:
        raise ValueError(f"unknown direction {direction!r}")
    sql = _TRAVERSE_SQL.format(join_cond=join_cond).replace("next_id", next_expr)
    rows = conn.execute(sql, {
        "host": host, "st": SOURCE_TABLE, "depth": depth, "now": _utcnow(),
    }).fetchall()
    # Per-node reduction in Python: SQLite's bare-column-with-MIN() guarantee
    # doesn't hold once a second aggregate is involved, so don't GROUP BY.
    if reduce:
        best: dict[int, sqlite3.Row] = {}
        for r in rows:
            cur = best.get(r["node_id"])
            if cur is None or (r["distance"], -r["conf"]) < (cur["distance"], -cur["conf"]):
                best[r["node_id"]] = r
        selected = list(best.values())
    else:
        selected = list(rows)
    out = []
    for r in sorted(selected, key=lambda x: (x["distance"], x["name"])):
        attrs = {}
        try:
            attrs = json.loads(r["attributes"] or "{}")
        except json.JSONDecodeError:
            pass
        path = [p for p in (r["path"] or "").split("/") if p]
        out.append({
            "name": r["name"],
            "entity_type": r["entity_type"],
            "site": attrs.get("site", ""),
            "distance": r["distance"],
            "via": r["via"],
            "path": path,
            "confidence": round(float(r["conf"]), 4),
            "source": r["provenance"] or "declared",
        })
    return out


def node_exists(conn, host: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM graph_entities WHERE name=? AND source_table=? LIMIT 1",
        (host, SOURCE_TABLE),
    ).fetchone() is not None


def resolve_entity(conn, name: str) -> tuple[str, str] | None:
    """Find the existing infragraph (entity_type, name) for a bare hostname.

    graph_entities is UNIQUE(entity_type, name) — writing an edge against the
    wrong type creates a disconnected twin node, so writers that only know a
    hostname MUST resolve through this first.
    """
    row = conn.execute(
        "SELECT entity_type, name FROM graph_entities "
        "WHERE name=? AND source_table=? LIMIT 1",
        (name, SOURCE_TABLE),
    ).fetchone()
    return (row["entity_type"], row["name"]) if row else None


# ── Cascade prediction ──────────────────────────────────────────────────────────

SIBLING_CONF_PENALTY = 0.6


def siblings(conn, host: str) -> list[dict[str, Any]]:
    """Common-cause siblings: hosts sharing a direct dependency target with
    `host`, where that target is infrastructure (pve_node / network_device /
    tunnel). When `host` alerts, its siblings are at risk through the shared
    parent even if the parent itself never alerts (e.g. 4 VMs on one PVE node
    flapping within seconds while the node's own alert never fires —
    2026-05-08 15:16 pattern).
    """
    rows = conn.execute(
        """SELECT DISTINCT s.name AS sib, t.name AS shared,
                  MIN(COALESCE(d1.confidence, 0.5), COALESCE(d2.confidence, 0.5))
                    AS conf
           FROM graph_relationships r1
           JOIN graph_entities h  ON h.id = r1.source_id
           JOIN graph_entities t  ON t.id = r1.target_id
           JOIN graph_relationships r2 ON r2.target_id = r1.target_id
           JOIN graph_entities s  ON s.id = r2.source_id
           LEFT JOIN infragraph_dynamics d1 ON d1.rel_id = r1.id
           LEFT JOIN infragraph_dynamics d2 ON d2.rel_id = r2.id
           WHERE h.name = :host AND h.source_table = :st
             AND s.name != :host
             AND t.entity_type IN ('pve_node', 'network_device', 'tunnel')
             AND (d1.valid_until IS NULL OR d1.valid_until > :now)
             AND (d2.valid_until IS NULL OR d2.valid_until > :now)
           GROUP BY s.name, t.name""",
        {"host": host, "st": SOURCE_TABLE, "now": _utcnow()},
    ).fetchall()
    return [{"name": r["sib"], "shared_parent": r["shared"],
             "confidence": round(float(r["conf"]) * SIBLING_CONF_PENALTY, 4)}
            for r in rows]


def rule_family(rule: str) -> str:
    """Coarse equivalence class for an alert rule. Used by cascade-probability
    gating (IFRNLLEI01PRD-1118) and -1119 family-granular scoring. Stable map —
    changing it invalidates learned cascade stats (re-run learn --from-cascades).
    """
    r = (rule or "").lower()
    if any(k in r for k in ("up/down", "device down", "icmp", "port status",
                            "targetdown", "unreachable")):
        return "host-down"
    # etcd-internal degradation (fsync / commit / grpc / leader-changes) is ONE
    # subsystem with one causal progression; consolidating the per-rule singletons
    # into a single family lets the cascade learn a coherent probability for the
    # etcd chain (IFRNLLEI01PRD-1065 precision). Apiserver/pod tiers are left in
    # k8s-pod on purpose — merging them too would coarsen the family only to clear
    # the bar (gaming), not because they are the same subsystem.
    if "etcd" in r:
        return "etcd"
    if any(k in r for k in ("kube", "pod", "oomkill", "crashloop", "container",
                            "cilium", "pdb", "replica", "statefulset", "deployment")):
        return "k8s-pod"
    if "rag" in r or "rerank" in r:
        return "rag"
    if any(k in r for k in ("memory", "saturation", "space on", "disk", "cpu",
                            "load", "fstrim", "swap")):
        return "resource"
    if "backup" in r or "dsm" in r:
        return "backup"
    return (r[:24] or "other")


def score_prediction(predicted: list[dict], actual: list[dict],
                     family: bool = False) -> tuple[int, int, int]:
    """(tp, fp, fn) of a cascade prediction vs observed alerts. Exact (host,rule)
    by default; at (host, rule-FAMILY) when family=True (IFRNLLEI01PRD-1119 —
    the operationally-meaningful unit: a cascade is 'right' if the predicted host
    has the predicted KIND of alert, even if the exact rule name differs)."""
    def key(x):
        r = x.get("rule")
        return (x.get("host"), rule_family(r) if family else r)
    pred = {key(p) for p in predicted}
    act = {key(a) for a in actual}
    return len(pred & act), len(pred - act), len(act - pred)


def _cascade_stats(conn) -> dict:
    """Load + cache the cascade-stats table on the connection (one query per
    process). Missing table (pre-migration) -> empty -> pure prior everywhere."""
    cache = getattr(conn, "_igcs_cache", None)
    if cache is not None:
        return cache
    cache = {}
    try:
        for r in conn.execute(
            "SELECT scope, parent_family, child_host, child_key, seen, fired "
            "FROM infragraph_cascade_stats"
        ):
            cache[(r["scope"], r["parent_family"], r["child_host"],
                   r["child_key"])] = (r["seen"], r["fired"])
    except sqlite3.OperationalError:
        pass
    try:
        conn._igcs_cache = cache
    except (AttributeError, TypeError):
        pass
    return cache


def cascade_prob(conn, parent_family: str, child_host: str,
                 child_key: str, scope: str) -> float:
    """Laplace-smoothed P(child fires | parent-family alerted), from learned
    history. scope='family' (child_key=rule-family) gates emission;
    scope='exact' (child_key=rule) sets the per-item confidence."""
    seen, fired = _cascade_stats(conn).get(
        (scope, parent_family, child_host, child_key), (0, 0))
    return (fired + CASCADE_PRIOR_ALPHA) / (seen + CASCADE_PRIOR_ALPHA + CASCADE_PRIOR_BETA)


def apply_cascade_gating(conn, predictions: list[dict[str, Any]],
                         parent_rule: str, *, drop: bool = True,
                         parent_family: str | None = None) -> list[dict[str, Any]]:
    """IFRNLLEI01PRD-1118 — calibrate cascade predictions against learned
    probability. Applied SYMMETRICALLY to real predictions and the shuffled
    control, so the falsifiability ratio stays fair. Env
    INFRAGRAPH_CASCADE_GATING=0 -> legacy (no gate). Shadow-only: no change to
    what is auto-suppressed.

    drop=True (default, the cascade/shadow lane): drop downstream whose
      (host, rule-family) demonstrably does not cascade (the over-prediction that
      tanked precision) AND replace the structural per-item confidence with the
      learned exact-rule probability (the signal precision_conf08 / the -1040
      gate consumes).
    drop=False (the fail-CLOSED action lane, IFRNLLEI01PRD-1145 Gap 2): keep
      EVERY prediction and the caller's confidence untouched — action_verdict must
      see the FULL structural blast-radius or a real cascade to a dropped host
      flips match->deviation — and only ATTACH cascade_prob_family so the family
      conf08 subset (the gate signal) is honest for action rows too. No emission
      change, no confidence change => the verdict + the Runner-reported confidence
      are byte-identical.
    parent_family overrides rule_family(parent_rule); the action lane passes the
      mapped family (reboot_host -> host-down) so its annotations look up the same
      learned stat a real host-down alert would (shared corpus with Gap 1)."""
    if os.environ.get("INFRAGRAPH_CASCADE_GATING", "1").lower() in ("0", "false", "no"):
        return predictions
    # Only the family-keyed path is gated. Ruleless advisory callers — the triage
    # cascade-context in classify-session-risk and infragraph-propose-blast-radius
    # — pass neither parent_rule nor parent_family, so leave them byte-identical
    # legacy (they would key the family stat on "other" = always cold-start).
    if not parent_rule and not parent_family:
        return predictions
    # Inert until there is learned history (fresh fixtures / pre-first-learn ->
    # byte-identical legacy: no gate, structural confidence untouched).
    if not _cascade_stats(conn):
        return predictions
    try:
        tau = float(os.environ.get("INFRAGRAPH_CASCADE_MIN_PROB", "0.10"))
    except ValueError:
        tau = 0.10
    pf = parent_family or rule_family(parent_rule)
    out: list[dict[str, Any]] = []
    for p in predictions:
        host, rule = p.get("host"), p.get("rule")
        fam_p = cascade_prob(conn, pf, host, rule_family(rule), "family")
        if drop and fam_p < tau:
            continue
        q = dict(p)
        q["cascade_prob_family"] = round(fam_p, 4)
        if drop:
            q["structural_confidence"] = p.get("confidence")
            q["confidence"] = round(cascade_prob(conn, pf, host, rule, "exact"), 4)
        out.append(q)
    return out


# Action kinds whose cascade signature matches an alert family: a reboot/restart/
# drain/failover takes the target offline, so its observed consequence teaches the
# same (parent-family -> child) statistic a real host-down alert on that parent
# would (IFRNLLEI01PRD-1119). Without this, action-lane negatives — the bulk of
# the remediation evidence — are discarded (the learner historically filtered
# kind='cascade' only), leaving the gate starved outside the few hosts that
# happened to cascade in the recorded shadow set. Unmapped kinds (bounce_tunnel,
# restart_service, config_change, scale, remediation) key on their own bucket.
ACTION_PARENT_FAMILY = {
    "reboot_host": "host-down",
    "restart_vm": "host-down",
    "restart_lxc": "host-down",
    "drain": "host-down",
    "failover": "host-down",
}


def _learn_parent_family(kind: str, parent_rule: str, action_kind: str) -> str:
    """Parent-family key for cascade learning. Cascade rows key on the parent
    alert rule; action rows pool with the alert family their consequence matches
    so the two evidence streams reinforce one stat (IFRNLLEI01PRD-1119)."""
    if kind == "action":
        ak = action_kind or parent_rule
        return ACTION_PARENT_FAMILY.get(ak, rule_family(ak))
    return rule_family(parent_rule)


def learn_cascade_stats(conn) -> dict:
    """IFRNLLEI01PRD-1118 — recompute per-(parent-family -> child) cascade
    hit-rates from EVALUATED shadow predictions. Full recompute => idempotent.
    Family scope dedupes per prediction: P(host-family cascades | predicted).
    Exact scope counts per predicted item: P(exact rule fires | predicted).
    Model-agnostic (learns from whatever the predictor recorded + what fired).
    Includes kind='action' rows (IFRNLLEI01PRD-1119): a remediation's observed
    consequence is cascade evidence too, pooled under the equivalent alert family
    via _learn_parent_family — else those negatives are discarded and the gate
    cold-starts every non-recorded host over tau."""
    rows = conn.execute(
        "SELECT kind, parent_rule, action_kind, predicted, actual "
        "FROM infragraph_predictions "
        "WHERE kind IN ('cascade','action') "
        "AND evaluated_at IS NOT NULL AND actual IS NOT NULL"
    ).fetchall()
    stats: dict[tuple, list] = {}

    def bump(key, hit):
        s = stats.setdefault(key, [0, 0])
        s[0] += 1
        s[1] += int(hit)

    for r in rows:
        try:
            pred = json.loads(r["predicted"] or "[]")
            act = json.loads(r["actual"] or "[]")
        except json.JSONDecodeError:
            continue
        pf = _learn_parent_family(r["kind"], r["parent_rule"], r["action_kind"])
        act_exact = {(a.get("host"), a.get("rule")) for a in act}
        act_fam = {(a.get("host"), rule_family(a.get("rule"))) for a in act}
        for p in pred:
            h, rule = p.get("host"), p.get("rule")
            bump(("exact", pf, h, rule), (h, rule) in act_exact)
        for (h, fam) in {(p.get("host"), rule_family(p.get("rule"))) for p in pred}:
            bump(("family", pf, h, fam), (h, fam) in act_fam)

    now = _utcnow()
    conn.execute("DELETE FROM infragraph_cascade_stats")
    conn.executemany(
        "INSERT INTO infragraph_cascade_stats "
        "(scope, parent_family, child_host, child_key, seen, fired, updated_at, schema_version) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [(s, pf, h, ck, v[0], v[1], now, CSV["infragraph_cascade_stats"])
         for (s, pf, h, ck), v in stats.items()],
    )
    try:
        delattr(conn, "_igcs_cache")
    except AttributeError:
        pass
    return {"pass": "cascade_stats", "predictions_used": len(rows),
            "stat_rows": len(stats)}


def expected_cascade(conn, host: str, rule: str = "",
                     depth: int = 2, *, gate_drop: bool = True,
                     gate_parent_family: str | None = None
                     ) -> tuple[list[dict[str, Any]], int]:
    """Predict the downstream alert set if `host` fails.

    Two mechanisms, same provenance trail:
      1. blast-radius: nodes that transitively depend on `host`, with the
         expected_alerts declared/learned on their dependency edges.
      2. common-cause siblings: hosts sharing an infrastructure parent with
         `host`, at SIBLING_CONF_PENALTY x edge confidence (sibling co-failure
         where the shared parent never alerts itself).
    Returns (predictions, window_seconds), window = max(900, 2 x max p95).

    gate_drop / gate_parent_family thread to apply_cascade_gating: the
    fail-CLOSED action lane (predict_action) passes gate_drop=False +
    gate_parent_family so it annotates without dropping (IFRNLLEI01PRD-1145).
    """
    affected = traverse(conn, host, "blast_radius", depth)
    affected = affected + [
        {"name": s["name"], "confidence": s["confidence"], "sibling": True}
        for s in siblings(conn, host)
        if s["name"] not in {a["name"] for a in affected}
    ]
    # NOTE: for sibling nodes the loop below naturally picks up the rules on
    # the sibling's own edge to the shared parent (S -> T expected_alerts) —
    # exactly the common-cause rule set.
    predictions: list[dict[str, Any]] = []
    max_p95 = 0.0
    for node in affected:
        rows = conn.execute(
            """SELECT d.expected_alerts, d.delay_p50_s, d.delay_p95_s,
                      d.confidence, d.observation_count, d.source, d.last_validated
               FROM infragraph_dynamics d
               JOIN graph_relationships r ON r.id = d.rel_id
               JOIN graph_entities s ON s.id = r.source_id
               WHERE s.name = ? AND (d.valid_until IS NULL OR d.valid_until > ?)""",
            (node["name"], _utcnow()),
        ).fetchall()
        seen: set[tuple[str, str]] = set()
        for d in rows:
            try:
                alerts = json.loads(d["expected_alerts"] or "[]")
            except json.JSONDecodeError:
                continue
            for a in alerts:
                arule = a.get("rule") if isinstance(a, dict) else None
                if not arule or (node["name"], arule) in seen:
                    continue
                seen.add((node["name"], arule))
                edge_conf = float(d["confidence"] or 0.5)
                p95 = d["delay_p95_s"]
                if p95:
                    max_p95 = max(max_p95, float(p95))
                predictions.append({
                    "host": node["name"],
                    "rule": arule,
                    "rule_family": rule_family(arule),  # IFRNLLEI01PRD-1119
                    "expected_delay_s": {
                        "p50": d["delay_p50_s"], "p95": d["delay_p95_s"],
                    },
                    "confidence": round(min(node["confidence"], edge_conf), 4),
                    "observations": d["observation_count"],
                    "source": d["source"],
                    "last_validated": d["last_validated"],
                })
    window = max(DEFAULT_WINDOW_S, int(2 * max_p95))
    predictions = apply_cascade_gating(conn, predictions, rule,
                                       drop=gate_drop,
                                       parent_family=gate_parent_family)
    return predictions, window


def shuffled_control(conn, host: str, depth: int = 2,
                     seed: str | None = None) -> list[dict[str, Any]]:
    """Degree-preserving shuffled-graph prediction — the negative control.

    Loads all infragraph edges, permutes targets within each rel_type bucket
    with a per-day deterministic seed, then computes the same cascade on the
    shuffled structure in Python. If real predictions don't beat this, the
    graph encodes nothing beyond degree distribution.
    """
    seed = seed or _utcnow()[:10]
    rng = random.Random(seed)
    edges = conn.execute(
        """SELECT r.id, r.rel_type, s.name AS src, t.name AS tgt,
                  d.expected_alerts, d.confidence
           FROM graph_relationships r
           JOIN graph_entities s ON s.id = r.source_id
           JOIN graph_entities t ON t.id = r.target_id
           JOIN infragraph_dynamics d ON d.rel_id = r.id
           WHERE (d.valid_until IS NULL OR d.valid_until > ?)""",
        (_utcnow(),),
    ).fetchall()
    by_rel: dict[str, list[sqlite3.Row]] = {}
    for e in edges:
        by_rel.setdefault(e["rel_type"], []).append(e)
    shuffled: list[dict[str, Any]] = []
    for rel_type, bucket in sorted(by_rel.items()):
        tgts = [e["tgt"] for e in bucket]
        rng.shuffle(tgts)
        for e, new_tgt in zip(bucket, tgts):
            shuffled.append({"src": e["src"], "tgt": new_tgt,
                             "expected_alerts": e["expected_alerts"],
                             "confidence": e["confidence"]})
    # BFS on the shuffled reverse-dependency structure
    rev: dict[str, list[dict[str, Any]]] = {}
    for e in shuffled:
        rev.setdefault(e["tgt"], []).append(e)
    frontier, visited = [host], {host}
    predictions, seen = [], set()
    for _ in range(max(1, min(depth, DEPTH_CAP))):
        nxt = []
        for node in frontier:
            for e in rev.get(node, []):
                src = e["src"]
                if src in visited:
                    continue
                visited.add(src)
                nxt.append(src)
                try:
                    alerts = json.loads(e["expected_alerts"] or "[]")
                except json.JSONDecodeError:
                    alerts = []
                for a in alerts:
                    arule = a.get("rule") if isinstance(a, dict) else None
                    if arule and (src, arule) not in seen:
                        seen.add((src, arule))
                        predictions.append({
                            "host": src, "rule": arule,
                            "confidence": round(float(e["confidence"] or 0.5), 4),
                        })
        frontier = nxt
    return predictions


ACTION_KINDS = frozenset({
    "restart_vm", "restart_lxc", "restart_service", "reboot_host",
    "bounce_tunnel", "config_change", "scale", "drain", "failover",
    "remediation",  # generic fallback when the plan's verb isn't classifiable
})


def predict_action(conn, action_kind: str, target: str,
                   depth: int = 2) -> dict[str, Any]:
    """Deterministic action-consequence prediction (model-based invariant #1).

    Given a remediation action against `target`, predict the observable
    consequences from graph traversal: the expected alert set (cascade +
    siblings), the alerting window, blast-radius size, and a recovery
    estimate from learned edge dynamics. Pure code — no LLM anywhere in
    this path. The caller (n8n Runner via the CLI) commits the result as
    an infragraph_predictions kind='action' row BEFORE any approval poll.

    Raises ValueError for unknown action kinds; returns eligible=False
    (never raises) when the target isn't in the graph — the gate treats
    that as "no prediction available" and the remediation lane fails CLOSED.
    """
    if action_kind not in ACTION_KINDS:
        raise ValueError(f"unknown action_kind {action_kind!r}")
    if not node_exists(conn, target):
        return {"eligible": False,
                "reason": f"target {target!r} not in infragraph"}
    # Fail-CLOSED lane (IFRNLLEI01PRD-1145 Gap 2): annotate cascade_prob_family
    # for the conf08 gate signal but NEVER drop — action_verdict needs the full
    # blast-radius, and the Runner-reported confidence must stay structural.
    predictions, window = expected_cascade(
        conn, target, depth=depth, gate_drop=False,
        gate_parent_family=_learn_parent_family("action", "", action_kind))
    blast = traverse(conn, target, "blast_radius", depth)
    recoveries = [r[0] for r in conn.execute(
        """SELECT d.recovery_p50_s FROM infragraph_dynamics d
           JOIN graph_relationships r ON r.id = d.rel_id
           JOIN graph_entities t ON t.id = r.target_id
           WHERE t.name = ? AND d.recovery_p50_s IS NOT NULL""",
        (target,),
    ).fetchall()]
    confs = sorted(p["confidence"] for p in predictions)
    return {
        "eligible": True,
        "action_kind": action_kind,
        "target": target,
        "predicted": predictions,
        "window_seconds": window,
        "blast_radius_count": len(blast),
        "recovery_p50_s": max(recoveries) if recoveries else None,
        "confidence": confs[len(confs) // 2] if confs else None,  # median
        "model_version": MODEL_VERSION,
    }


def record_prediction(conn, *, parent_host: str, parent_rule: str,
                      parent_issue_id: str, window_seconds: int,
                      predicted: list[dict], control: list[dict],
                      kind: str = "cascade", action_kind: str = "",
                      action_target: str = "", plan_hash: str = "") -> int:
    """Commit a prediction artifact.

    kind='cascade' = Phase B shadow row. kind='action' = the mandatory
    pre-remediation artifact of the model-based invariant — the n8n Runner
    commits it BEFORE the approval poll; plan_hash is the non-bypassable gate
    key joining session_risk_audit.plan_hash.
    """
    if kind not in ("cascade", "action"):
        raise ValueError(f"unknown prediction kind {kind!r}")
    if kind == "action" and not plan_hash:
        raise ValueError("kind='action' predictions require plan_hash "
                         "(the non-bypassable gate key)")
    cur = conn.execute(
        """INSERT INTO infragraph_predictions
           (kind, parent_issue_id, parent_host, parent_rule,
            action_kind, action_target, plan_hash, window_seconds,
            predicted, control_predicted, model_version, schema_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (kind, parent_issue_id, parent_host, parent_rule,
         action_kind, action_target, plan_hash, window_seconds,
         json.dumps(predicted, ensure_ascii=False),
         json.dumps(control, ensure_ascii=False),
         MODEL_VERSION, CSV["infragraph_predictions"]),
    )
    return cur.lastrowid


# ── Mechanical verification (IFRNLLEI01PRD-1045) ───────────────────────────────
# The ONLY writer of infragraph_predictions.verdict / verdict_detail. The LLM
# never adjudicates its own outcome — these functions diff observed reality
# against the committed prediction in pure code.


def _host_site(host: str | None) -> str | None:
    """Coarse site of a host for the verdict's cross-site coincidence filter. NL/GR only;
    VPS and unknown hosts return None (never excluded — conservative)."""
    if not host:
        return None
    if host.startswith("nl"):
        return "nl"
    if host.startswith("gr") or host.startswith("gr2"):
        return "gr"
    return None


def action_verdict(predicted: list[dict],
                   actual: list[dict],
                   target_host: str | None = None) -> tuple[str, dict[str, Any]]:
    """Mechanical verdict for an executed action's prediction.

    match     — every observed alert was predicted (rule-level); includes the
                quiet case (nothing observed: a healthy remediation does not
                have to fire its possible cascade).
    partial   — observed alerts only on predicted HOSTS but with unpredicted
                rules (the graph knew the blast area, not the exact symptom).
    deviation — at least one alert on a host the prediction never named.
                SURPRISE: the world diverged from the model — escalate, and
                never auto-resolve.

    `target_host` is the host the action runs ON / directly affects (the
    rebooted/restarted host). Its OWN alerts are the EXPECTED direct effect of
    the action — NOT a cascade surprise — so they are excluded from the verdict
    (IFRNLLEI01PRD-1408 #1: a reboot causing the rebooted host to alert is not a
    divergence). They are surfaced separately as `target_host_self`. Default
    None preserves legacy behaviour.
    """
    pred_pairs = {(p.get("host"), p.get("rule")) for p in predicted}
    pred_hosts = {p.get("host") for p in predicted}
    obs_all = [(a["host"], a["rule"]) for a in actual]
    self_alerts = [list(o) for o in obs_all if target_host and o[0] == target_host]
    # #2 Layer-1 (IFRNLLEI01PRD-1408): a surprise on a DIFFERENT SITE than the action target
    # is coincidental — NL and GR are independent except over the VPN, so an NL alert during a
    # GR action (or vice-versa) is background noise, not a cascade. Excluded from the verdict
    # and surfaced as `coincidental_cross_site`. VPS/unknown hosts have no site -> never
    # excluded (conservative). A genuine cross-site cascade only comes from VPN/BGP actions,
    # which are POLL_PAUSE (never auto) anyway.
    _ts = _host_site(target_host)

    def _excluded(h):
        return (target_host and h == target_host) or (
            _ts and _host_site(h) and _host_site(h) != _ts)
    coincidental = [list(o) for o in obs_all
                    if _ts and _host_site(o[0]) and _host_site(o[0]) != _ts
                    and not (target_host and o[0] == target_host)]
    observed = [o for o in obs_all if not _excluded(o[0])]
    surprises = [list(o) for o in observed if o[0] not in pred_hosts]
    host_level = [list(o) for o in observed
                  if o[0] in pred_hosts and o not in pred_pairs]
    matched = [list(o) for o in observed if o in pred_pairs]
    not_observed = [list(p) for p in pred_pairs
                    if p not in {tuple(o) for o in observed}]
    if surprises:
        verdict = "deviation"
    elif host_level:
        verdict = "partial"
    else:
        verdict = "match"
    return verdict, {
        "observed": [list(o) for o in obs_all],
        "matched": matched,
        "host_level_only": host_level,
        "surprises": surprises,
        "predicted_not_observed": not_observed,
        "target_host_self": self_alerts,
        "coincidental_cross_site": coincidental,
    }


def write_verdict(conn, prediction_id: int, verdict: str,
                  detail: dict[str, Any]) -> None:
    if verdict not in ("match", "partial", "deviation"):
        raise ValueError(f"invalid verdict {verdict!r}")
    conn.execute(
        """UPDATE infragraph_predictions
           SET verdict=?, verdict_detail=?, schema_version=?
           WHERE id=?""",
        (verdict, json.dumps(detail, ensure_ascii=False),
         CSV["infragraph_predictions"], prediction_id),
    )


# ── Health ──────────────────────────────────────────────────────────────────────


def health(conn) -> dict[str, Any]:
    now = _utcnow()
    nodes_by_type = dict(conn.execute(
        "SELECT entity_type, COUNT(*) FROM graph_entities WHERE source_table=? GROUP BY entity_type",
        (SOURCE_TABLE,),
    ).fetchall())
    edges_by_rel = dict(conn.execute(
        """SELECT r.rel_type, COUNT(*) FROM graph_relationships r
           JOIN infragraph_dynamics d ON d.rel_id = r.id GROUP BY r.rel_type""",
    ).fetchall())
    edges_by_source = dict(conn.execute(
        "SELECT source, COUNT(*) FROM infragraph_dynamics GROUP BY source",
    ).fetchall())
    edges_total = sum(edges_by_rel.values())
    stale = conn.execute(
        "SELECT COUNT(*) FROM infragraph_dynamics WHERE valid_until IS NOT NULL AND valid_until <= ?",
        (now,),
    ).fetchone()[0]
    with_dyn = conn.execute(
        "SELECT COUNT(*) FROM infragraph_dynamics WHERE observation_count > 0 OR expected_alerts != '[]'",
    ).fetchone()[0]
    last_seed = {}
    try:
        for row in conn.execute(
            "SELECT key, value FROM openclaw_memory WHERE category='infragraph-seed'",
        ).fetchall():
            last_seed[row["key"]] = row["value"]
    except sqlite3.OperationalError:
        pass  # fixture DBs without openclaw_memory
    pred = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN evaluated_at IS NOT NULL THEN 1 ELSE 0 END) AS evaluated,
                  SUM(CASE WHEN evaluated_at >= datetime('now', '-30 days') THEN tp ELSE 0 END) AS tp30,
                  SUM(CASE WHEN evaluated_at >= datetime('now', '-30 days') THEN fp ELSE 0 END) AS fp30,
                  SUM(CASE WHEN evaluated_at >= datetime('now', '-30 days') THEN fn ELSE 0 END) AS fn30
           FROM infragraph_predictions""",
    ).fetchone()
    tp30, fp30, fn30 = (pred["tp30"] or 0), (pred["fp30"] or 0), (pred["fn30"] or 0)
    # Family-granular precision/recall (IFRNLLEI01PRD-1119) — recomputed from
    # the 30d JSON since family tp/fp aren't stored per row.
    #
    # ALSO compute fold-band precision (IFRNLLEI01PRD-1040): family precision on
    # the cascade_prob_family >= 0.60 subset. This is the OPERATIVE precision for
    # the fold/suppression use-case — the 0.80 bar the operator set live applies
    # HERE, not to the raw exact-match precision_30d. precision_30d scores the
    # FULL enumerated blast radius (dozens of intentionally-low-probability
    # candidate rows, cascade_prob_family ~0.02-0.10), so it is structurally
    # ~0.05-0.15 by design and has been since the predictions table started
    # (2026-06-09) — it is NOT a fold/suppression gate. The InfragraphPrecisionDrop
    # alert reads this fold-band series so it measures the precision the 0.80
    # threshold was actually designed for. Mirrors infragraph-eval.py's
    # precision_fold_family in scorecard() (FOLD_GATE.fold_min_prob).
    FOLD_MIN_PROB = 0.60
    ftp = ffp = ffn = 0
    fold_tp = fold_fp = 0
    for r in conn.execute(
        """SELECT predicted, actual FROM infragraph_predictions
           WHERE evaluated_at >= datetime('now', '-30 days') AND actual IS NOT NULL""",
    ).fetchall():
        try:
            pred_list = json.loads(r["predicted"] or "[]")
            act = json.loads(r["actual"] or "[]")
            t, f, n = score_prediction(pred_list, act, family=True)
        except json.JSONDecodeError:
            continue
        ftp += t; ffp += f; ffn += n
        actual_fams = {(a["host"], rule_family(a["rule"])) for a in act}
        for p in pred_list:
            fc = p.get("cascade_prob_family")
            if fc is None:
                fc = p.get("confidence") or 0
            if fc >= FOLD_MIN_PROB:
                if (p.get("host"), rule_family(p.get("rule"))) in actual_fams:
                    fold_tp += 1
                else:
                    fold_fp += 1
    return {
        "nodes_total": sum(nodes_by_type.values()),
        "nodes_by_type": nodes_by_type,
        "edges_total": edges_total,
        "edges_by_rel": edges_by_rel,
        "edges_by_source": edges_by_source,
        "stale_edges": stale,
        "dynamics_coverage": round(with_dyn / edges_total, 4) if edges_total else 0.0,
        "last_seed": last_seed,
        "predictions": {
            "total": pred["total"] or 0,
            "evaluated": pred["evaluated"] or 0,
            "precision_30d": round(tp30 / (tp30 + fp30), 4) if (tp30 + fp30) else None,
            "recall_30d": round(tp30 / (tp30 + fn30), 4) if (tp30 + fn30) else None,
            "precision_family_30d": round(ftp / (ftp + ffp), 4) if (ftp + ffp) else None,
            "recall_family_30d": round(ftp / (ftp + ffn), 4) if (ftp + ffn) else None,
            # OPERATIVE fold-band precision (cascade_prob_family >= 0.60) — the
            # series the InfragraphPrecisionDrop 0.80 bar is meaningful against
            # (IFRNLLEI01PRD-1040). None when the band is empty.
            "precision_fold_family_30d": round(fold_tp / (fold_tp + fold_fp), 4)
            if (fold_tp + fold_fp) else None,
            "fold_band_n_30d": fold_tp + fold_fp,
        },
        **_temporal_health(conn, now),
    }


# ── Bi-temporal edge invalidation (IFRNLLEI01PRD-1158) ─────────────────────────
# valid_until = TTL expiry of seeded edges (existing). invalid_at = a NEWER
# observation/contradiction superseded this edge (Zep/Graphiti pattern). Decay is
# REPORTING-ONLY: it flags edges that have gone too long without re-confirmation so
# they get RE-RATIFIED — it never alters the confidence predictions/suppression use.
# invalidate_edge() is only invoked by the flag-gated wiki contradiction path
# (INFRAGRAPH_BITEMPORAL_INVALIDATE), default shadow/off. Operator-approved
# constants (2026-06-21): 0.01/day decay, 0.30 at-risk threshold, single invalid_at.
DECAY_PER_DAY = float(os.environ.get("INFRAGRAPH_DECAY_PER_DAY", "0.01"))
DECAY_AT_RISK = float(os.environ.get("INFRAGRAPH_DECAY_AT_RISK", "0.30"))
SUPERSEDE_MAX_DEPTH = 5


def _parse_ts(s: str | None):
    """Parse either _utcnow() ('...T..Z') or SQLite CURRENT_TIMESTAMP ('.. ..')."""
    if not s:
        return None
    t = str(s).strip().replace("Z", "").replace("T", " ")[:19]
    try:
        return _dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def compute_confidence_with_decay(base_confidence, last_confirmed,
                                  decay_per_day: float = DECAY_PER_DAY,
                                  now: str | None = None) -> float:
    """REPORTING-ONLY effective confidence = base * (1 - decay_per_day)^days_since.
    Never persisted, never fed to predictions. Used to flag re-ratification need."""
    try:
        base = max(0.0, min(1.0, float(base_confidence)))
    except (TypeError, ValueError):
        return 0.0
    lc = _parse_ts(last_confirmed)
    if lc is None:
        return round(base, 4)
    nowdt = _parse_ts(now) or _dt.datetime.utcnow()
    days = max(0.0, (nowdt - lc).total_seconds() / 86400.0)
    factor = (1.0 - max(0.0, min(1.0, decay_per_day))) ** days
    return round(max(0.0, min(1.0, base * factor)), 4)


def invalidate_edge(conn, rel_id: int, reason: str,
                    superseded_by_rel_id: int | None = None) -> bool:
    """Mark a dynamics edge invalid (contradiction/supersession). Single invalid_at
    (first-writer-wins, per operator decision). Records the reason in openclaw_memory.
    Returns True if it flipped an open edge to invalid, False if already invalid /
    missing. Shadow-safe: callers gate this behind INFRAGRAPH_BITEMPORAL_INVALIDATE."""
    try:
        cur = conn.execute(
            "UPDATE infragraph_dynamics SET invalid_at=?, superseded_by=? "
            "WHERE rel_id=? AND invalid_at IS NULL",
            (_utcnow(), superseded_by_rel_id, rel_id),
        )
    except sqlite3.OperationalError:
        return False  # pre-migration DB
    if cur.rowcount:
        try:
            conn.execute(
                "INSERT INTO openclaw_memory (category, key, value) VALUES "
                "('infragraph-invalidation', ?, ?)",
                (f"rel:{rel_id}", json.dumps({"reason": reason, "at": _utcnow(),
                                              "superseded_by": superseded_by_rel_id})),
            )
        except sqlite3.OperationalError:
            pass
        return True
    return False


def find_supersession_chain(conn, rel_id: int) -> list[int]:
    """Follow superseded_by pointers from rel_id, cycle-safe + depth-capped at
    SUPERSEDE_MAX_DEPTH. Returns [rel_id, next, ...]."""
    chain: list[int] = []
    seen: set[int] = set()
    cur_id = rel_id
    for _ in range(SUPERSEDE_MAX_DEPTH + 1):
        if cur_id is None or cur_id in seen:
            break
        seen.add(cur_id)
        chain.append(cur_id)
        try:
            row = conn.execute(
                "SELECT superseded_by FROM infragraph_dynamics WHERE rel_id=?",
                (cur_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            break
        cur_id = row[0] if row and row[0] is not None else None
    return chain


def _temporal_health(conn, now: str) -> dict[str, Any]:
    """invalid_edges + decay_at_risk for health(). Pre-migration DBs -> zeros."""
    try:
        invalid = conn.execute(
            "SELECT COUNT(*) FROM infragraph_dynamics WHERE invalid_at IS NOT NULL"
        ).fetchone()[0]
        at_risk = 0
        for r in conn.execute(
            "SELECT confidence, COALESCE(last_confirmation, last_validated, updated_at) lc "
            "FROM infragraph_dynamics WHERE invalid_at IS NULL "
            "AND (valid_until IS NULL OR valid_until > ?)", (now,),
        ).fetchall():
            if compute_confidence_with_decay(r["confidence"], r["lc"], now=now) < DECAY_AT_RISK:
                at_risk += 1
    except (sqlite3.OperationalError, IndexError):
        return {"invalid_edges": 0, "decay_at_risk": 0}
    return {"invalid_edges": invalid, "decay_at_risk": at_risk}
