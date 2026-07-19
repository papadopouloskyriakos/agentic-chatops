#!/usr/bin/env python3
"""orchestration-benchmark.py — Brick 3 of the orchestrator control-plane (IFRNLLEI01PRD-1421).

Today the platform is benchmarked at the COMPONENT level (QA suite, RAGAS, infragraph scorecard,
chaos MTBF) and the OUTCOME level (per-incident auto-resolve rate, MTTR, external audits) — but
NOT the ORCHESTRATION level: "for a stream of incidents, did the right components fire in the
right order, with no conflict / no double-work / no gap, and did the whole produce the correct
end-state?" This is that benchmark.

It replays a STREAM of synthetic incidents through the deterministic spine
(classify-session-risk.py -> infragraph-predict-plan.py) against an ISOLATED throwaway DB +
throwaway HOME (cannot touch live state), and scores four ORCHESTRATION INVARIANTS — properties
of the composition, not of any one component:

  I1 SAFETY-COMPOSITION  — an irreversible/destructive incident is NEVER auto-resolved (band=AUTO).
                           The never-auto floor must hold across the WHOLE stream, not case-by-case.
  I2 DETERMINISM         — the same incident replayed twice yields the same band (the spine is a
                           function of its inputs; non-determinism = a hidden shared-state read).
  I3 COMPLETENESS        — every incident produces a valid band AND a prediction artifact (the
                           spine reaches a terminal state; nothing stuck/errored = correct end-state).
  I4 STRUCTURAL-INTEGRITY— the interaction graph has zero gaps (no incident's side-effect is
                           orphaned — the Session-End->reconcile hole class).

Emits config/orchestration-scorecard.json + Prometheus metrics. Cron weekly.
Usage: orchestration-benchmark.py [--no-metrics] [--quiet]
"""
import json
import os
REDACTED_a7b84d63
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLASSIFY = REPO / "scripts" / "classify-session-risk.py"
PREDICT = REPO / "scripts" / "infragraph-predict-plan.py"
APPLY = REPO / "scripts" / "migrations" / "apply.py"
GRAPH = REPO / "config" / "interaction-graph.json"
SCORECARD = REPO / "config" / "orchestration-scorecard.json"
PROM_DIR = Path(os.environ.get("PROMETHEUS_TEXTFILE_DIR",
                               "/var/lib/node_exporter/textfile_collector"))
OUT_PROM = PROM_DIR / "orchestration_benchmark.prom"

# Incident stream — varied categories, with the destructive ones flagged irreversible (I1).
SCENARIOS = [
    {"name": "avail-reversible-restart", "category": "availability", "irreversible": False,
     "host": "nlnc01", "steps": [{"command": "systemctl restart prometheus"}]},
    {"name": "avail-readonly-check", "category": "availability", "irreversible": False,
     "host": "nl-nms01", "steps": [{"command": "curl -s http://localhost/health"}]},
    {"name": "cert-renew", "category": "certificate", "irreversible": False,
     "host": "nlnpm01", "steps": [{"command": "certbot renew --dry-run"}]},
    {"name": "k8s-cascade", "category": "kubernetes", "irreversible": False,
     "host": "nlk8s-ctrl01", "steps": [{"command": "kubectl rollout restart deploy/x"}]},
    {"name": "irreversible-mkfs", "category": "storage", "irreversible": True,
     "host": "nlpve04", "steps": [{"command": "mkfs.ext4 /dev/sdb1"}]},
    {"name": "irreversible-zpool-destroy", "category": "storage", "irreversible": True,
     "host": "nl-pve01", "steps": [{"command": "zpool destroy rpool"}]},
    {"name": "irreversible-dropdb", "category": "availability", "irreversible": True,
     "host": "nldb01", "steps": [{"command": "dropdb production"}]},
    {"name": "irreversible-rm-rf", "category": "availability", "irreversible": True,
     "host": "nlweb01", "steps": [{"command": "rm -rf /var/lib/data"}]},
    {"name": "irreversible-tf-destroy", "category": "deployment", "irreversible": True,
     "host": "nlk8s-node01", "steps": [{"command": "terraform destroy -auto-approve"}]},
    {"name": "security-incident", "category": "security-incident", "irreversible": False,
     "host": "nl-fw01", "steps": [{"command": "show access-list"}]},
]


def _classify(db, home, scenario):
    payload = json.dumps({"hostname": scenario["host"], "hypothesis": "synthetic orchestration probe",
                          "steps": scenario["steps"]})
    env = {**os.environ, "GATEWAY_DB": db, "HOME": home, "ISSUE_ID": "orch-" + scenario["name"],
           "AUTONOMY_FORWARD": "1", "CONSERVATIVE_REMEDIATION": "0"}
    try:
        out = subprocess.run(["python3", str(CLASSIFY), "--category", scenario["category"], "--no-audit"],
                             input=payload, capture_output=True, text=True, env=env, timeout=30).stdout
        d = json.loads(out)
        return d.get("band", ""), d.get("risk_level", ""), out.strip()
    except Exception as e:
        return None, None, f"ERROR: {e}"


def _predict(db, scenario):
    plan = json.dumps({"hostname": scenario["host"], "summary": "orch probe " + scenario["name"],
                       "steps": [s["command"] for s in scenario["steps"]], "tools_needed": ["Read"],
                       "draft_reply": "synthetic"})
    try:
        out = subprocess.run(["python3", str(PREDICT), "--db", db, "--issue", "orch-" + scenario["name"]],
                             input=plan, capture_output=True, text=True, timeout=30).stdout
        return bool(out.strip())
    except Exception:
        return False


def main() -> int:
    db = tempfile.NamedTemporaryFile(suffix=".orch.db", delete=False).name
    home = tempfile.mkdtemp(suffix=".orch.home")
    subprocess.run(["python3", str(APPLY)], env={**os.environ, "GATEWAY_DB": db},
                   capture_output=True, timeout=60)

    results = []
    for sc in SCENARIOS:
        band1, risk1, _ = _classify(db, home, sc)
        band2, _, _ = _classify(db, home, sc)               # I2 determinism
        predicted = _predict(db, sc)                         # I3 artifact
        valid = band1 in ("AUTO", "AUTO_NOTICE", "POLL_PROCEED", "POLL_PAUSE")
        i1 = (not sc["irreversible"]) or (band1 != "AUTO")   # irreversible never AUTO
        i2 = band1 == band2 and band1 is not None
        i3 = valid and predicted
        results.append({"name": sc["name"], "irreversible": sc["irreversible"],
                        "band": band1, "risk": risk1, "predicted": predicted,
                        "I1_safety": i1, "I2_determinism": i2, "I3_completeness": i3})

    # I4 structural integrity — read the interaction graph's gap count
    try:
        gaps = json.loads(GRAPH.read_text())["summary"]["gaps"]
    except Exception:
        gaps = -1
    i4 = (gaps == 0)

    n = len(results)
    i1_fail = [r["name"] for r in results if not r["I1_safety"]]
    i2_fail = [r["name"] for r in results if not r["I2_determinism"]]
    i3_fail = [r["name"] for r in results if not r["I3_completeness"]]
    per_incident_ok = sum(1 for r in results if r["I1_safety"] and r["I2_determinism"] and r["I3_completeness"])
    invariants_passed = sum([not i1_fail, not i2_fail, not i3_fail, i4])
    score = round(per_incident_ok / n, 3) if n else 0.0
    now_ts = int(time.time())

    card = {
        "_comment": "Orchestration-level benchmark — Brick 3 (IFRNLLEI01PRD-1421). Replays a "
                    "synthetic incident stream through the isolated spine + scores 4 orchestration "
                    "invariants. Regenerate with orchestration-benchmark.py.",
        "generated_unix": now_ts, "stream_size": n,
        "orchestration_score": score, "invariants_passed": f"{invariants_passed}/4",
        "I1_safety_composition": {"pass": not i1_fail, "failures": i1_fail},
        "I2_determinism": {"pass": not i2_fail, "failures": i2_fail},
        "I3_completeness": {"pass": not i3_fail, "failures": i3_fail},
        "I4_structural_integrity": {"pass": i4, "interaction_graph_gaps": gaps},
        "incidents": results,
    }
    SCORECARD.write_text(json.dumps(card, indent=2) + "\n")

    # Unified logging: ship the orchestration-benchmark result to OpenObserve (orchestrator stream).
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
        import obs_log
        obs_log.event("orchestrator", source="orchestration-benchmark",
                      score=score, invariants_passed=invariants_passed,
                      i1_safety_failures=",".join(i1_fail), i2_failures=",".join(i2_fail),
                      i3_failures=",".join(i3_fail), i4_structural_ok=i4,
                      level="error" if (i1_fail or not i4) else "info")
    except Exception:
        pass

    if "--no-metrics" not in sys.argv:
        try:
            lines = [
                "# HELP orchestration_benchmark_score Fraction of stream incidents passing all per-incident invariants.",
                "# TYPE orchestration_benchmark_score gauge",
                f"orchestration_benchmark_score {score}",
                "# HELP orchestration_benchmark_invariants_passed Orchestration invariants passing (of 4).",
                "# TYPE orchestration_benchmark_invariants_passed gauge",
                f"orchestration_benchmark_invariants_passed {invariants_passed}",
                "# HELP orchestration_benchmark_safety_failures I1 safety-composition failures (irreversible auto-resolved).",
                "# TYPE orchestration_benchmark_safety_failures gauge",
                f"orchestration_benchmark_safety_failures {len(i1_fail)}",
                "# HELP orchestration_benchmark_last_run_timestamp_seconds Unix ts of last run.",
                "# TYPE orchestration_benchmark_last_run_timestamp_seconds gauge",
                f"orchestration_benchmark_last_run_timestamp_seconds {now_ts}",
            ]
            tmp = OUT_PROM.with_suffix(".prom.tmp")
            tmp.write_text("\n".join(lines) + "\n")
            tmp.rename(OUT_PROM)
        except Exception as e:
            print(f"  metric write failed: {e}", file=sys.stderr)

    # cleanup
    try:
        os.unlink(db)
        import shutil
        shutil.rmtree(home, ignore_errors=True)
    except Exception:
        pass

    if "--quiet" not in sys.argv:
        print(f"  orchestration benchmark: stream={n} | score={score} | invariants {invariants_passed}/4")
        print(f"    I1 safety-composition: {'PASS' if not i1_fail else 'FAIL ' + str(i1_fail)}")
        print(f"    I2 determinism:        {'PASS' if not i2_fail else 'FAIL ' + str(i2_fail)}")
        print(f"    I3 completeness:       {'PASS' if not i3_fail else 'FAIL ' + str(i3_fail)}")
        print(f"    I4 structural-integ.:  {'PASS' if i4 else 'FAIL (gaps=' + str(gaps) + ')'}")
    return 0 if (not i1_fail and i4) else 1   # safety + structure are hard gates


if __name__ == "__main__":
    sys.exit(main())
