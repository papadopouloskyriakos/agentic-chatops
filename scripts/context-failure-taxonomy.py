#!/usr/bin/env python3
"""context-failure-taxonomy.py — IFRNLLEI01PRD-1451 part (b): Context-Failure-Mode taxonomy.

Names + instruments the five context-failure classes from "AI Agents: The Definitive Guide"
(poisoning / distraction / confusion / clash / rot) as METERED, testable classes over the existing
RAG eval signals (ragas_evaluation dims + the bi-temporal incident_knowledge.valid_until). This gives
the eval flywheel a DIAGNOSTIC VOCABULARY — it can say *why* a retrieval failed, not just *that* it
scored low. Read-only; zero operator involvement. Pairs with the no-human eval anchors (part a).

Classes (priority cascade, per ragas_evaluation row; ONLY computed dims [>=0] are used — a -1 dim
means RAGAS did not score it and is ignored):
  poisoning   — ungrounded / unsupported answer (faithfulness < 0.5): bad/false data influenced the answer
  clash       — unfaithful DESPITE good retrieval (F<0.5 AND recall>=0.7 AND precision>=0.7): contradictory context
  distraction — irrelevant chunks dominate (context_precision < 0.5): the signal is crowded out by noise
  confusion   — off-target answer (answer_relevance < 0.5) despite acceptable retrieval
  none        — all computed dims healthy
  rot         — corpus-level: stale knowledge past valid_until still retrievable (separate gauge, the 5th class)

Usage:
  context-failure-taxonomy.py [--metrics]    # classify recent RAG evals + emit per-class metrics
  context-failure-taxonomy.py --list [N]      # show recent retrievals with their classified failure mode
"""
import os, sqlite3, time, argparse

DB = os.environ.get("GATEWAY_DB", "/app/cubeos/claude-context/gateway.db")
PROM_DIR = os.environ.get("TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector")
WINDOW_DAYS = 30
CLASSES = ("poisoning", "clash", "distraction", "confusion", "none")


def classify(F, R, AR, P):
    """Return the context-failure class for one RAG eval, or None if no dim was scored."""
    def c(x):
        return x if (x is not None and x >= 0) else None   # -1/None = not computed -> ignore
    F, R, AR, P = c(F), c(R), c(AR), c(P)
    if all(v is None for v in (F, R, AR, P)):
        return None                                         # unscored row -> skip
    if F is not None and F < 0.5:
        return "clash" if (R is not None and R >= 0.7 and P is not None and P >= 0.7) else "poisoning"
    if P is not None and P < 0.5:
        return "distraction"
    if AR is not None and AR < 0.5:
        return "confusion"
    return "none"


def _rows(db):
    return db.execute(
        "SELECT faithfulness, context_recall, answer_relevance, context_precision, query, issue_id "
        "FROM ragas_evaluation WHERE created_at > datetime('now', ?) ORDER BY created_at DESC",
        ("-%d day" % WINDOW_DAYS,)).fetchall()


def metrics():
    db = sqlite3.connect(DB, timeout=30)
    counts = {k: 0 for k in CLASSES}
    classified = 0
    for F, R, AR, P, q, iss in _rows(db):
        cl = classify(F, R, AR, P)
        if cl is None:
            continue
        counts[cl] += 1
        classified += 1
    rot = db.execute(
        "SELECT COUNT(*) FROM incident_knowledge WHERE valid_until IS NOT NULL "
        "AND valid_until < datetime('now') AND COALESCE(suppression_status,'') != 'analysis_only'").fetchone()[0]
    db.close()
    lines = [
        "# HELP context_failure_class_total RAG retrievals (30d) by context-failure class (IFRNLLEI01PRD-1451 taxonomy)",
        "# TYPE context_failure_class_total gauge",
    ]
    for k in CLASSES:
        lines.append('context_failure_class_total{class="%s"} %d' % (k, counts[k]))
    lines += [
        "# HELP context_failure_classified_total RAG evals with at least one computed RAGAS dim (the denominator)",
        "# TYPE context_failure_classified_total gauge",
        "context_failure_classified_total %d" % classified,
        "# HELP context_failure_rot_exposure stale knowledge past valid_until still retrievable (the 'rot' class)",
        "# TYPE context_failure_rot_exposure gauge",
        "context_failure_rot_exposure %d" % rot,
        "# HELP context_failure_last_run_timestamp_seconds unix time of last taxonomy classification",
        "# TYPE context_failure_last_run_timestamp_seconds gauge",
        "context_failure_last_run_timestamp_seconds %d" % int(time.time()),
    ]
    tmp = os.path.join(PROM_DIR, ".context_failure.prom.%d" % os.getpid())
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, os.path.join(PROM_DIR, "context_failure.prom"))
    print("taxonomy: " + " ".join("%s=%d" % (k, counts[k]) for k in CLASSES)
          + " | classified=%d rot_exposure=%d" % (classified, rot))


def show(n):
    db = sqlite3.connect(DB, timeout=30)
    print("recent RAG retrievals by context-failure class (last %dd):" % WINDOW_DAYS)
    shown = 0
    for F, R, AR, P, q, iss in _rows(db):
        cl = classify(F, R, AR, P)
        if cl is None:
            continue
        print("  %-11s F=%-5s P=%-5s AR=%-5s R=%-5s  %s" % (cl, F, P, AR, R, (q or "")[:50]))
        shown += 1
        if shown >= n:
            break
    db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", action="store_true", help="classify recent RAG evals + emit per-class metrics")
    ap.add_argument("--list", nargs="?", const=20, type=int, help="show recent retrievals with their failure mode")
    a = ap.parse_args()
    if a.list is not None:
        show(a.list)
    else:
        metrics()
