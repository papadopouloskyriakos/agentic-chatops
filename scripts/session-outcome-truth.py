#!/usr/bin/env python3
"""session-outcome-truth.py — IFRNLLEI01PRD-1451, no-human eval anchor #2 (outcome truth).

Did an auto-resolved session's fix actually HOLD? This is the strongest no-human anchor: it
measures the thing the whole autonomy-forward design rests on — *did autonomy actually work* —
with ZERO operator involvement (see memory/feedback_no_human_anchor_for_absent_operator).

It MIRRORS the -1153 repeat-incident governance (scripts/write-governance-metrics.py) so the two
agree on "the same incident": reuse parse_triage_log() for (host, rule, outcome, issue_id), and the
same rule — a RESOLVED event followed by ANY event for the same (host, rule) within 24h is a
false-resolve (the fix did NOT hold). It EXCLUDES chronic-by-design patterns the governance has
already dispositioned (analysis_only demotions + transient/expected-noise known-patterns) — auto-
acking those is the intended behaviour, not a false-resolve. The NEW value over governance is the
PER-SESSION outcome + the judge calibration: the killer signal is a GENUINE false-resolve the LLM
judge SCORED WELL (>=4) — a judge miss no purely-LLM metric can see.

Usage:
  session-outcome-truth.py [--run]    # evaluate auto-resolved sessions from triage.log + emit metrics
  session-outcome-truth.py --metrics   # recompute + emit metrics only (no re-evaluation)
"""
import os, sys, sqlite3, time, argparse
from collections import defaultdict
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lib.schema_version import current as schema_current     # noqa: E402
from lib.infragraph import parse_triage_log                   # noqa: E402
from lib.tier1_suppression import KNOWN_TRANSIENT_KEYWORDS    # noqa: E402

DB = os.environ.get("GATEWAY_DB", "/app/cubeos/claude-context/gateway.db")
PROM_DIR = os.environ.get("TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector")
# Mirror write-governance-metrics.py exactly:
RESOLVED = {"resolved", "resolved-knownpattern", "resolved-active-memory", "auto_resolved"}
WINDOW_H = 24        # RECURRENCE_THRESHOLD — a re-fire within 24h of a RESOLVED = false-resolve
LOOKBACK_DAYS = 30   # WINDOW_DAYS
JUDGE_PASS = 4       # judge overall_score >= 4 == "the judge endorsed it"
# Chronic-by-design patterns the -1153 governance has already dispositioned recur on purpose;
# broaden the governance's KNOWN_TRANSIENT_KEYWORDS with the markers seen on the agentic self-alerts.
DISPOSITION_KEYWORDS = tuple(KNOWN_TRANSIENT_KEYWORDS) + (
    "expected-noise", "expected noise", "known-con", "by design", "by-design",
    "chronic", "auto-demote", "self-inflicted", "not-actionable", "not actionable")


def parse_ts(s):
    try:
        d = datetime.fromisoformat((s or "").strip().replace("Z", "+00:00"))
        return d.replace(tzinfo=None) if d.tzinfo else d
    except Exception:
        return None


def is_dispositioned(db, host, rule):
    """A (host, rule) the governance already marked chronic/known recurs BY DESIGN — exclude it.
    analysis_only = a -1153 auto-demotion; a >=0.7-confidence known-pattern tagged transient/
    expected-noise/etc. is a deliberate disposition. Match host exactly OR the '*' wildcard."""
    rows = db.execute(
        "SELECT COALESCE(confidence,-1), COALESCE(suppression_status,''), "
        "lower(COALESCE(tags,'')||' '||COALESCE(resolution,'')) "
        "FROM incident_knowledge WHERE alert_rule=? AND (hostname=? OR hostname='*')",
        (rule, host)).fetchall()
    for conf, ss, blob in rows:
        if ss == "analysis_only":
            return True
        if conf >= 0.7 and any(k in blob for k in DISPOSITION_KEYWORDS):
            return True
    return False


def run():
    events = []
    for e in parse_triage_log():
        t = parse_ts(e.get("ts", ""))
        if t is not None:
            events.append((t, e.get("host", ""), e.get("rule", ""), e.get("outcome", ""), e.get("issue_id", "")))
    bykey = defaultdict(list)
    for t, host, rule, outcome, iss in events:
        bykey[(host, rule)].append((t, outcome, iss))
    for k in bykey:
        bykey[k].sort(key=lambda x: x[0])

    db = sqlite3.connect(DB, timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    auto_ids = set(r[0] for r in db.execute(
        "SELECT issue_id FROM session_log WHERE resolution_type='auto_resolved' AND ended_at > datetime('now', ?)",
        ("-%d day" % LOOKBACK_DAYS,)).fetchall())
    now = datetime.utcnow()
    n = skipped = 0
    seen = set()  # one row per issue_id (latest auto-resolved event wins via INSERT OR REPLACE)
    for (host, rule), evs in bykey.items():
        disp = None
        for i, (t, outcome, iss) in enumerate(evs):
            if not (iss and iss in auto_ids and outcome in RESOLVED):
                continue
            if disp is None:
                disp = is_dispositioned(db, host, rule)
            if disp:
                skipped += 1
                continue   # chronic-by-design: auto-acking it is intended, not a false-resolve
            age_h = (now - t).total_seconds() / 3600.0
            if age_h < WINDOW_H:
                held, refire_h = -1, -1.0   # pending: the 24h window has not elapsed yet
            else:
                refires = [(t2 - t).total_seconds() / 3600.0 for (t2, _o, _x) in evs[i + 1:]
                           if timedelta(0) < (t2 - t) <= timedelta(hours=WINDOW_H)]
                held, refire_h = (0, round(min(refires), 2)) if refires else (1, -1.0)
            jr = db.execute("SELECT overall_score, recommended_action FROM session_judgment "
                            "WHERE issue_id=? ORDER BY judged_at DESC LIMIT 1", (iss,)).fetchone()
            js = jr[0] if (jr and jr[0] is not None) else -1
            ja = (jr[1] if jr else "") or ""
            db.execute("""INSERT OR REPLACE INTO autoresolve_outcome
                (issue_id, resolution_type, resolved_at, evaluated_at, held, refire_within_hours,
                 judge_score, judge_action, schema_version)
                VALUES (?,?,?,datetime('now'),?,?,?,?,?)""",
                       (iss, "auto_resolved", t.isoformat(sep=" "), held, refire_h, js, ja,
                        schema_current("autoresolve_outcome")))
            seen.add(iss)
            n += 1
            if held == 0:
                tag = " <-- FALSE-RESOLVE" + ("  JUDGE-MISS(score=%s)" % js if js >= JUDGE_PASS else "")
                print("  %-22s %s / %s  re-fired in %sh%s" % (iss, host, rule, refire_h, tag))
    db.commit()
    print("evaluated %d genuine auto-resolved session(s) (%d skipped as chronic/dispositioned)" % (len(seen), skipped))
    db.close()


def metrics():
    db = sqlite3.connect(DB, timeout=30)
    r = db.execute("""SELECT
        SUM(CASE WHEN held IN (0,1) THEN 1 ELSE 0 END),
        SUM(CASE WHEN held=1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN held=0 THEN 1 ELSE 0 END),
        SUM(CASE WHEN held=0 AND judge_score>=? THEN 1 ELSE 0 END),
        SUM(CASE WHEN held=-1 THEN 1 ELSE 0 END)
        FROM autoresolve_outcome WHERE evaluated_at > datetime('now','-30 day')""", (JUDGE_PASS,)).fetchone()
    evaluated, held, false_r, judge_miss, pending = (r[0] or 0), (r[1] or 0), (r[2] or 0), (r[3] or 0), (r[4] or 0)
    held_rate = (held / evaluated) if evaluated else -1.0
    db.close()
    ts = int(time.time())
    lines = [
        "# HELP autoresolve_evaluated GENUINE auto-resolved sessions whose 24h window elapsed (chronic/dispositioned excluded, 30d)",
        "# TYPE autoresolve_evaluated gauge",
        "autoresolve_evaluated %d" % evaluated,
        "# HELP autoresolve_held_rate fraction of GENUINE evaluated auto-resolves whose fix HELD (no re-fire in 24h); -1=n/a",
        "# TYPE autoresolve_held_rate gauge",
        "autoresolve_held_rate %.4f" % held_rate,
        "# HELP autoresolve_false_resolve_total GENUINE auto-resolves whose incident re-fired within 24h (the fix did not hold)",
        "# TYPE autoresolve_false_resolve_total gauge",
        "autoresolve_false_resolve_total %d" % false_r,
        "# HELP autoresolve_judge_missed_false_resolve genuine false-resolves the LLM judge SCORED>=4 (endorsed a fix that did not hold)",
        "# TYPE autoresolve_judge_missed_false_resolve gauge",
        "autoresolve_judge_missed_false_resolve %d" % judge_miss,
        "# HELP autoresolve_pending genuine auto-resolves whose 24h window has not elapsed yet",
        "# TYPE autoresolve_pending gauge",
        "autoresolve_pending %d" % pending,
        "# HELP autoresolve_last_run_timestamp_seconds unix time of last outcome-truth metric emit",
        "# TYPE autoresolve_last_run_timestamp_seconds gauge",
        "autoresolve_last_run_timestamp_seconds %d" % ts,
    ]
    tmp = os.path.join(PROM_DIR, ".autoresolve_outcome.prom.%d" % os.getpid())
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, os.path.join(PROM_DIR, "autoresolve_outcome.prom"))
    print("metrics: evaluated=%d held_rate=%.2f false_resolves=%d judge_missed=%d pending=%d"
          % (evaluated, held_rate, false_r, judge_miss, pending))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="evaluate auto-resolved sessions from triage.log")
    ap.add_argument("--metrics", action="store_true", help="recompute + emit metrics only")
    a = ap.parse_args()
    if a.metrics and not a.run:
        metrics()
    else:
        run()
        metrics()
