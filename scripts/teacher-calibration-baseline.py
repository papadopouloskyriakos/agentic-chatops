#!/usr/bin/env python3
"""Teacher grader calibration baseline (IFRNLLEI01PRD-655).

Runs the grader against a fixture set of question+answer pairs with known
expected score bands and computes the agreement rate:

    agreement = (# fixtures whose grader.score_0_to_1 fell in expected_band) / N

The plan targets >=85% agreement across >=20 examples. This harness ships 12
synthetic fixtures spanning five quality bands (excellent / good / partial /
wrong / irrelevant). A live calibration run calls the real Ollama grader;
an offline run injects a deterministic `_ollama_fn` stub so QA can verify
the harness itself without network dependency.

Usage:

    # Live (calls real Ollama via quiz_grader.grade):
    python3 scripts/teacher-calibration-baseline.py

    # Offline (deterministic stub, used by QA):
    python3 scripts/teacher-calibration-baseline.py --offline

    # Custom fixtures:
    python3 scripts/teacher-calibration-baseline.py --fixtures path.json

Writes a JSON report to scripts/qa/reports/calibration-<ISO>.json containing
every fixture's expected band, produced score, pass/fail flag, and the
overall agreement rate. Exit 0 iff agreement >= --threshold (default 0.85).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import quiz_grader  # noqa: E402


FIXTURES_DEFAULT = REPO_ROOT / "scripts" / "qa" / "fixtures" / "teacher-calibration-fixtures.json"
REPORT_DIR = REPO_ROOT / "scripts" / "qa" / "reports"


def _band_for(score: float) -> str:
    if score >= 0.85: return "excellent"
    if score >= 0.65: return "good"
    if score >= 0.40: return "partial"
    if score >= 0.20: return "wrong"
    return "irrelevant"


def _deterministic_stub(prompt: str) -> dict:
    """Offline grader stub. Reads a `# FIXTURE-ID: <id>` marker we inject into
    the prompt and returns the expected score from the fixture's `expected_score`.

    Lets QA exercise the full calibration pipeline without Ollama.
    """
    marker = "# FIXTURE-ID: "
    fid = None
    for line in prompt.splitlines():
        if line.startswith(marker):
            fid = line[len(marker):].strip()
            break
    fixtures = _load_fixtures(FIXTURES_DEFAULT)
    fixture = next((f for f in fixtures if f["id"] == fid), None) if fid else None
    if not fixture:
        # Unexpected — surface as a grader rejection so the test fails loudly.
        return {
            "score_0_to_1": 0.0,
            "feedback": "stub: missing fixture id",
            "bloom_demonstrated": "recall",
            "citation_check": {"in_sources": True, "extra_claims": []},
            "clarifying_question": None,
            "grader_confidence": 0.5,
        }
    return {
        "score_0_to_1": fixture["stub_score"],
        "feedback": f"stub feedback for {fid}: referring to source [1]",
        "bloom_demonstrated": fixture["stub_bloom"],
        "citation_check": {"in_sources": True, "extra_claims": []},
        "clarifying_question": None,
        "grader_confidence": fixture.get("stub_confidence", 0.9),
    }


def _load_fixtures(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _tag_prompt_with_id(fid: str, orig_prompt: str) -> str:
    # The stub reads this marker; the real Ollama grader ignores comment lines.
    return f"# FIXTURE-ID: {fid}\n{orig_prompt}"


def run(fixtures: list[dict], *, offline: bool) -> dict:
    results = []
    for f in fixtures:
        question = {
            "question_text": f["question"],
            "rubric": f.get("rubric", ""),
            "source_snippets": f["source_snippets"],
            "bloom_level": f["bloom_level"],
            "question_type": f.get("question_type", "explanation"),
        }
        if offline:
            # Stub gets the fixture id via a marker we sneak into the prompt.
            fid = f["id"]
            def wrapped_stub(prompt, fid=fid):
                return _deterministic_stub(_tag_prompt_with_id(fid, prompt))
            g = quiz_grader.grade(question, f["answer"], _ollama_fn=wrapped_stub)
        else:
            g = quiz_grader.grade(question, f["answer"])
        if g is None:
            results.append({
                "id": f["id"],
                "expected_band": f["expected_band"],
                "score": None,
                "band": None,
                "passed": False,
                "reason": "grader returned None",
            })
            continue
        band = _band_for(g.score_0_to_1)
        passed = band == f["expected_band"]
        results.append({
            "id": f["id"],
            "expected_band": f["expected_band"],
            "score": round(g.score_0_to_1, 3),
            "band": band,
            "passed": passed,
            "grader_confidence": round(g.grader_confidence, 3),
            "clarifying_question": bool(g.clarifying_question),
        })
    n = len(results)
    passed = sum(1 for r in results if r["passed"])
    agreement = (passed / n) if n else 0.0
    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "mode": "offline" if offline else "live",
        "n_fixtures": n,
        "n_passed": passed,
        "agreement": round(agreement, 4),
        "results": results,
    }


def export_for_review(db_path: Path, out_path: Path, *, limit: int = 50) -> int:
    """Dump completed quiz sessions from learning_sessions into a reviewable
    JSON template. Operator hand-grades each row by setting `operator_band`
    to one of {excellent, good, partial, wrong, irrelevant}, then re-feeds
    the file via --from-reviewed to compute grader-vs-operator agreement.
    """
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, operator, topic, bloom_level, started_at, completed_at,
               quiz_score, question_payload, answer_payload, judge_feedback
          FROM learning_sessions
         WHERE session_type = 'quiz'
           AND quiz_score IS NOT NULL
           AND completed_at IS NOT NULL
         ORDER BY completed_at DESC
         LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    if not rows:
        print("no graded quiz sessions yet — operator needs to !learn + !grade real content first",
              file=sys.stderr)
        return 1

    records = []
    for r in rows:
        try:
            q = json.loads(r["question_payload"] or "{}")
        except json.JSONDecodeError:
            q = {}
        try:
            a = json.loads(r["answer_payload"] or "{}")
        except json.JSONDecodeError:
            a = {"answer_text": r["answer_payload"]}
        grader_score = float(r["quiz_score"] or 0.0)
        records.append({
            "session_id": r["id"],
            "operator": r["operator"],
            "topic": r["topic"],
            "bloom_level": r["bloom_level"],
            "completed_at": r["completed_at"],
            "question_text": q.get("question_text", ""),
            "answer_text": a.get("answer_text", ""),
            "grader_score": round(grader_score, 3),
            "grader_band": _band_for(grader_score),
            "judge_feedback": r["judge_feedback"] or "",
            "operator_band": None,   # OPERATOR FILLS THIS IN
            "operator_notes": "",
        })

    with open(out_path, "w") as f:
        json.dump({
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "n_records": len(records),
            "note": ("Operator: set `operator_band` on each record to one of "
                     "[excellent|good|partial|wrong|irrelevant] matching your "
                     "own judgment of the answer quality (independent of the "
                     "grader's score). Then run "
                     "`teacher-calibration-baseline.py --from-reviewed <this-file>` "
                     "to compute agreement."),
            "records": records,
        }, f, indent=2)
    print(f"wrote {len(records)} records to {out_path}")
    return 0


def from_reviewed(path: Path) -> dict:
    """Ingest an operator-filled review JSON and compute grader-vs-operator
    band agreement."""
    with open(path) as f:
        doc = json.load(f)
    records = doc.get("records", [])
    ungraded = [r for r in records if not r.get("operator_band")]
    graded = [r for r in records if r.get("operator_band")]
    if not graded:
        raise SystemExit(
            f"no records have operator_band set in {path} "
            f"(found {len(records)} records, 0 graded)"
        )

    results = []
    for r in graded:
        ob = str(r["operator_band"]).lower().strip()
        gb = r["grader_band"]
        passed = (ob == gb)
        results.append({
            "session_id": r["session_id"],
            "topic": r["topic"],
            "bloom_level": r["bloom_level"],
            "grader_score": r.get("grader_score"),
            "grader_band": gb,
            "operator_band": ob,
            "passed": passed,
        })
    n = len(results)
    passed = sum(1 for r in results if r["passed"])
    agreement = passed / n if n else 0.0
    return {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "mode": "reviewed",
        "source": str(path),
        "n_records": len(records),
        "n_reviewed": n,
        "n_ungraded": len(ungraded),
        "n_passed": passed,
        "agreement": round(agreement, 4),
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path, default=FIXTURES_DEFAULT)
    ap.add_argument("--offline", action="store_true",
                    help="Use deterministic grader stub (for QA; no Ollama call)")
    ap.add_argument("--threshold", type=float, default=0.85,
                    help="Minimum agreement rate to treat as PASS (default 0.85)")
    ap.add_argument("--report", type=Path, default=None,
                    help="Override report output path (default scripts/qa/reports/calibration-<stamp>.json)")
    ap.add_argument("--export-for-review", type=Path, default=None,
                    metavar="OUT",
                    help="Dump recent completed quiz sessions to OUT as a reviewable "
                         "JSON template. Operator hand-grades operator_band; then "
                         "run --from-reviewed OUT.")
    ap.add_argument("--limit", type=int, default=50,
                    help="Row limit for --export-for-review (default 50, max 200)")
    ap.add_argument("--db", type=Path,
                    default=Path(os.environ.get(
                        "GATEWAY_DB",
                        Path.home() / "gitlab/products/cubeos/claude-context/gateway.db",
                    )),
                    help="SQLite DB path (default $GATEWAY_DB or canonical path)")
    ap.add_argument("--from-reviewed", type=Path, default=None,
                    metavar="IN",
                    help="Load an operator-filled review JSON and compute grader-vs-"
                         "operator band agreement.")
    args = ap.parse_args()

    if args.export_for_review:
        return export_for_review(args.db, args.export_for_review,
                                 limit=max(1, min(args.limit, 200)))

    if args.from_reviewed:
        if not args.from_reviewed.exists():
            print(f"review file not found: {args.from_reviewed}", file=sys.stderr)
            return 2
        report = from_reviewed(args.from_reviewed)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = args.report
        if out is None:
            stamp = report["generated_at"].replace(":", "-").replace(".", "-")
            out = REPORT_DIR / f"calibration-reviewed-{stamp}.json"
        with open(out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"mode={report['mode']} reviewed={report['n_reviewed']} "
              f"ungraded={report['n_ungraded']} passed={report['n_passed']} "
              f"agreement={report['agreement']:.2%}")
        for r in report["results"]:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"  {mark}  #{r['session_id']:<6d}  {r['topic']:40s}  "
                  f"grader={r['grader_band']:<10s}  operator={r['operator_band']}")
        print(f"report={out}")
        return 0 if report["agreement"] >= args.threshold else 1

    if not args.fixtures.exists():
        print(f"fixtures not found: {args.fixtures}", file=sys.stderr)
        return 2

    fixtures = _load_fixtures(args.fixtures)
    if not fixtures:
        print("no fixtures loaded", file=sys.stderr)
        return 2

    report = run(fixtures, offline=args.offline)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.report
    if out is None:
        stamp = report["generated_at"].replace(":", "-").replace(".", "-")
        out = REPORT_DIR / f"calibration-{stamp}.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)

    print(f"mode={report['mode']} n={report['n_fixtures']} passed={report['n_passed']} agreement={report['agreement']:.2%}")
    for r in report["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  {mark}  {r['id']:40s}  expected={r['expected_band']:<10s}  score={r['score']}  band={r['band']}")
    print(f"report={out}")

    return 0 if report["agreement"] >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
