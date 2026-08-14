#!/usr/bin/env python3
"""write-governance-metrics.py — IFRNLLEI01PRD-1153 (roadmap Stage-0 "I2").

Governance KPIs for the autonomy-forward gate, now that it auto-resolves real
Tier-2 incidents. The cleanest root-cause-discipline signal is RECURRENCE: an
incident the gate auto-resolved that fires again within 24h means the auto-resolve
didn't fix the cause.

DATA SOURCE NOTE (the non-obvious bit): session_log carries no host/rule and only
~1/33 auto-resolves link to incident_knowledge by issue_id — so recurrence is NOT
computable from those tables. triage.log (ts|host|rule|site|outcome|conf|dur|issue)
is the alert-event source-of-truth that has host+rule+outcome, parsed via the
shared lib.infragraph.parse_triage_log(). incident_knowledge is used only for the
demotion-state rows.

Emits (node_exporter textfile collector):
  chatops_false_auto_resolve_total{window="30d"}      auto-resolved (host,rule) that recurred <=24h
  chatops_repeat_incident_classes{window="30d"}        distinct (host,rule) with >=2 events
  chatops_governance_demote_candidates                 (host,rule) with >=3 events not yet demoted
  chatops_governance_demoted_patterns_total            incident_knowledge rows suppression_status='analysis_only'
  chatops_governance_metrics_last_run_timestamp        freshness (for a staleness alert)

Demotion hook (GOVERNANCE_AUTODEMOTE=1, default OFF = shadow): for each >=3x/30d
(host,rule) not already demoted, INSERT an incident_knowledge row with
suppression_status='analysis_only', demotion_reason='pattern_repeat_3plus',
valid_until=now+30d. Default-off because it writes to the live RAG base; the
candidates metric + log show what WOULD be demoted so the operator can review
before flipping the flag (shadow-first, like the autonomy-forward gate).

Cron: */15 on nl-claude01.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.infragraph import parse_triage_log  # noqa: E402  (shared parser)
from lib.tier1_suppression import (  # noqa: E402  (keep the transient definition in lockstep)
    KNOWN_TRANSIENT_KEYWORDS, KNOWN_TRANSIENT_MIN_CONFIDENCE,
)

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OUT = os.environ.get(
    "GOVERNANCE_METRICS_OUT",
    "/var/lib/node_exporter/textfile_collector/governance_metrics.prom",
)
# Default ON (autonomy-forward: human-as-circuit-breaker, not gatekeeper). A
# demotion is reversible (30-day valid_until expiry), safe-direction-only (a
# demoted (host,rule) is ESCALATED by tier1_suppression, never auto-resolved or
# suppressed), confidence=-1 (invisible to the transient-suppression matcher), and
# project='chatops-governance' (excluded from RAG embedding/retrieval). The
# circuit-breaker is the metric + weekly audit + auto-expiry, NOT manual review.
# Set GOVERNANCE_AUTODEMOTE=0 to fall back to shadow (candidates logged, not acted).
AUTODEMOTE = os.environ.get("GOVERNANCE_AUTODEMOTE", "1").lower() in ("1", "true", "yes")
PIPELINE_LOG = os.path.expanduser("~/logs/claude-gateway/pipeline-debug.log")

# Rank-3 "the gate considered this handled" outcomes (NOT dedup=suppressed-dup,
# NOT escalated). An auto-resolve here that recurs is the false-positive signal.
RESOLVED = {"resolved", "resolved-knownpattern", "resolved-active-memory", "auto_resolved"}
REPEAT_DEMOTE_THRESHOLD = int(os.environ.get("GOVERNANCE_DEMOTE_REPEATS", "3"))
WINDOW_DAYS = 30


def _dt(s: str):
    s = (s or "").replace("Z", "").replace("T", " ")[:19]
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def compute(rows):
    """Returns (false_auto_resolves, repeat_classes, demote_candidates list)."""
    cutoff = (_now() - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    bykey: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r["host"] and r["rule"] and r["ts"] >= cutoff:
            d = _dt(r["ts"])
            if d:
                bykey[(r["host"], r["rule"])].append((d, r["outcome"]))

    false_resolves = 0
    repeat_classes = 0
    candidates = []
    for (host, rule), evs in bykey.items():
        evs.sort(key=lambda e: e[0])
        if len(evs) >= 2:
            repeat_classes += 1
        if len(evs) >= REPEAT_DEMOTE_THRESHOLD:
            candidates.append((host, rule, len(evs)))
        for i, (t, outcome) in enumerate(evs):
            if outcome in RESOLVED:
                # recurred (any event) within 24h after the resolve?
                if any((t2 - t) <= dt.timedelta(hours=24) for t2, _ in evs[i + 1:]):
                    false_resolves += 1
                    break
    return false_resolves, repeat_classes, candidates


def is_intentionally_suppressed(conn, host, rule) -> bool:
    """True if (host,rule) is a KNOWN-TRANSIENT pattern the operator deliberately
    auto-resolves (incident_knowledge row, confidence>=0.7, transient keyword).
    Such patterns recur BY DESIGN — their recurrence is not a false-auto-resolve,
    so they must NOT be demoted (demoting them re-introduces suppressed noise)."""
    try:
        rows = conn.execute(
            "SELECT root_cause, resolution, tags FROM incident_knowledge "
            "WHERE (hostname = ? OR hostname = '*') AND alert_rule = ? "
            "AND confidence >= ? AND COALESCE(suppression_status,'open') != 'analysis_only'",
            (host, rule, KNOWN_TRANSIENT_MIN_CONFIDENCE),
        ).fetchall()
    except sqlite3.OperationalError:
        return False
    for rc, res, tags in rows:
        blob = " ".join(x or "" for x in (rc, res, tags)).lower()
        if any(kw in blob for kw in KNOWN_TRANSIENT_KEYWORDS):
            return True
    return False


def already_demoted(conn, host, rule) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM incident_knowledge WHERE hostname=? AND alert_rule=? "
            "AND suppression_status='analysis_only' "
            "AND (valid_until IS NULL OR valid_until > datetime('now')) LIMIT 1",
            (host, rule),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False  # pre-migration


def demote(conn, host, rule, count):
    conn.execute(
        "INSERT INTO incident_knowledge "
        "(alert_rule, hostname, site, root_cause, resolution, confidence, "
        " created_at, issue_id, tags, project, valid_until, "
        " suppression_status, demotion_reason, demotion_at) "
        "VALUES (?, ?, '', ?, 'analysis-only pending root-cause', -1, "
        " datetime('now'), '', 'governance,auto-demote', 'chatops-governance', "
        " datetime('now','+30 days'), 'analysis_only', ?, datetime('now'))",
        (rule, host, f"recurred {count}x in {WINDOW_DAYS}d without durable fix",
         f"pattern_repeat_{REPEAT_DEMOTE_THRESHOLD}plus"),
    )


def log_event(msg):
    try:
        os.makedirs(os.path.dirname(PIPELINE_LOG), exist_ok=True)
        with open(PIPELINE_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{_now().isoformat()}Z event=governance_metrics {msg}\n")
    except OSError:
        pass


def judge_scored_fraction(conn):
    """Semantic liveness of the LOCAL LLM judge, computed from tables the judge
    does NOT write (2026-07-03 follow-up: the judge died twice — 06-07..06-27 and
    06-27..07-03 — with every process-liveness signal green; its own metrics tail
    kept running and the frontier cross-check starved because it sampled from
    session_judgment). Eligible = session_log sessions that ENDED 26h..2h ago
    (2h lag = the judge's */2h cron cadence), excluding synthetics. Scored =
    eligible with a real (overall_score >= 0) session_judgment row."""
    try:
        eligible, scored = conn.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN EXISTS (SELECT 1 FROM session_judgment j
                                          WHERE j.issue_id = s.issue_id
                                            AND j.overall_score >= 0)
                       THEN 1 ELSE 0 END)
            FROM session_log s
            WHERE s.ended_at BETWEEN datetime('now', '-26 hours')
                                 AND datetime('now', '-2 hours')
              AND COALESCE(s.model, '') != '<synthetic>'
        """).fetchone()
    except sqlite3.OperationalError:
        return -1.0, 0
    eligible, scored = eligible or 0, scored or 0
    return ((scored / eligible) if eligible else -1.0), eligible


def main():
    rows = parse_triage_log()
    false_resolves, repeat_classes, candidates = compute(rows)

    demoted_now = 0
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        # Exclude KNOWN-TRANSIENT patterns the operator deliberately auto-resolves —
        # their recurrence is by-design, not a false-auto-resolve. Demoting them
        # would re-introduce suppressed noise.
        genuine = [c for c in candidates if not is_intentionally_suppressed(conn, c[0], c[1])]
        skipped_transient = len(candidates) - len(genuine)
        fresh = [c for c in genuine if not already_demoted(conn, c[0], c[1])]
        if AUTODEMOTE and fresh:
            for host, rule, count in fresh:
                demote(conn, host, rule, count)
                demoted_now += 1
            conn.commit()
            log_event(f"autodemote=on demoted={demoted_now} skipped_transient={skipped_transient} "
                      f"{[ (h,r) for h,r,_ in fresh]}")
        elif fresh:
            log_event(f"autodemote=off demote_candidates={len(fresh)} "
                      f"skipped_transient={skipped_transient} {[(h, r, n) for h, r, n in fresh]}")
        try:
            demoted_total = conn.execute(
                "SELECT COUNT(*) FROM incident_knowledge "
                "WHERE suppression_status='analysis_only'"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            demoted_total = 0
        scored_fraction, eligible_sessions = judge_scored_fraction(conn)
    finally:
        conn.close()

    ts = int(_now().replace(tzinfo=dt.timezone.utc).timestamp())
    lines = [
        "# HELP chatops_false_auto_resolve_total Auto-resolved (host,rule) that recurred within 24h (IFRNLLEI01PRD-1153).",
        "# TYPE chatops_false_auto_resolve_total gauge",
        f'chatops_false_auto_resolve_total{{window="30d"}} {false_resolves}',
        "# HELP chatops_repeat_incident_classes Distinct (host,rule) with >=2 events in the window.",
        "# TYPE chatops_repeat_incident_classes gauge",
        f'chatops_repeat_incident_classes{{window="30d"}} {repeat_classes}',
        "# HELP chatops_governance_demote_candidates Genuine repeat-offender (host,rule) candidates (excludes known-transient patterns).",
        "# TYPE chatops_governance_demote_candidates gauge",
        f"chatops_governance_demote_candidates {len(genuine)}",
        "# HELP chatops_governance_demoted_patterns_total incident_knowledge rows in analysis_only state.",
        "# TYPE chatops_governance_demoted_patterns_total gauge",
        f"chatops_governance_demoted_patterns_total {demoted_total}",
        "# HELP chatops_governance_autodemote_enabled 1 if the demote hook writes to incident_knowledge.",
        "# TYPE chatops_governance_autodemote_enabled gauge",
        f"chatops_governance_autodemote_enabled {1 if AUTODEMOTE else 0}",
        "# HELP judge_scored_fraction Fraction of sessions ended 26h..2h ago with a real local judgment (semantic judge liveness, independent of the judge pipeline; -1 = no eligible sessions).",
        "# TYPE judge_scored_fraction gauge",
        f"judge_scored_fraction {scored_fraction:.4f}",
        "# HELP judge_eligible_sessions Sessions in the 26h..2h evaluation window (denominator; gates the alert on real volume).",
        "# TYPE judge_eligible_sessions gauge",
        f"judge_eligible_sessions {eligible_sessions}",
        "# HELP chatops_governance_metrics_last_run_timestamp Unix time of last run (freshness).",
        "# TYPE chatops_governance_metrics_last_run_timestamp gauge",
        f"chatops_governance_metrics_last_run_timestamp {ts}",
    ]
    tmp = OUT + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, OUT)
    except OSError as e:
        print(f"write failed: {e}", file=sys.stderr)
        return 1
    print(f"false_auto_resolve={false_resolves} repeat_classes={repeat_classes} "
          f"demote_candidates={len(genuine)} (raw={len(candidates)} skipped_transient={skipped_transient}) "
          f"demoted_now={demoted_now} "
          f"autodemote={'on' if AUTODEMOTE else 'off'}")
    # IFRNLLEI01PRD-1663: piggyback the workspace-guardrail health writer on this */15 cycle so
    # prom:workspace_guardrail stays fresh without a new scheduler job. Isolated subprocess — a
    # failure here NEVER affects the governance metrics already written above.
    try:
        import subprocess
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "write-workspace-guardrail-metrics.py")],
            timeout=30, check=False)
    except Exception as _e:
        print(f"workspace-guardrail writer skipped: {_e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
