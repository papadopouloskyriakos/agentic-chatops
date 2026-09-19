#!/usr/bin/env bash
# write-jailbreak-metrics.sh — Prometheus textfile metrics for the jailbreak
# corpus regression suite.
#
# IFRNLLEI01PRD-748 / G1.P0.2.
#
# Emits (one row per fixture category):
#   chatops_jailbreak_fixture_count{category}                       gauge
#   chatops_jailbreak_detector_match_total{category, status}        gauge (status=match|miss)
#   chatops_jailbreak_corpus_last_run_timestamp                     gauge (unix s)
#
# Cron: */30 * * * *
# Runs the detector against every fixture; counts category-level matches.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTDIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
mkdir -p "$OUTDIR"

TARGET="$OUTDIR/jailbreak-metrics.prom"
TMP=$(mktemp "${TARGET}.XXXXXX")
trap 'rm -f "$TMP"' EXIT

REPO_ROOT="$REPO_ROOT" python3 <<'PY' > "$TMP"
import importlib.util, json, os, time
root = os.environ["REPO_ROOT"]
fix_path = os.path.join(root, "scripts/qa/fixtures/jailbreak-corpus.json")
lib_path = os.path.join(root, "scripts/lib/jailbreak_detector.py")
lines = []
lines.append("# HELP chatops_jailbreak_fixture_count Number of fixtures per category in the corpus.")
lines.append("# TYPE chatops_jailbreak_fixture_count gauge")
lines.append("# HELP chatops_jailbreak_detector_match_total Detector outcome per category vs expected.")
lines.append("# TYPE chatops_jailbreak_detector_match_total gauge")
lines.append("# HELP chatops_jailbreak_corpus_last_run_timestamp Unix seconds of the latest detector run.")
lines.append("# TYPE chatops_jailbreak_corpus_last_run_timestamp gauge")

if os.path.exists(fix_path) and os.path.exists(lib_path):
    spec = importlib.util.spec_from_file_location("jbd", lib_path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    data = json.load(open(fix_path))
    fixtures = data.get("fixtures", [])
    by_cat: dict[str, dict[str, int]] = {}
    for f in fixtures:
        cat = f.get("category", "unknown")
        by_cat.setdefault(cat, {"total": 0, "match": 0, "miss": 0})
        by_cat[cat]["total"] += 1
        expected = set(f.get("expected_categories", []))
        actual = m.categories_hit(f.get("payload", "") or "")
        if expected == actual:
            by_cat[cat]["match"] += 1
        else:
            by_cat[cat]["miss"] += 1
    for cat, d in sorted(by_cat.items()):
        lines.append(f'chatops_jailbreak_fixture_count{{category="{cat}"}} {d["total"]}')
        lines.append(f'chatops_jailbreak_detector_match_total{{category="{cat}",status="match"}} {d["match"]}')
        lines.append(f'chatops_jailbreak_detector_match_total{{category="{cat}",status="miss"}} {d["miss"]}')

lines.append(f"chatops_jailbreak_corpus_last_run_timestamp {int(time.time())}")
print("\n".join(lines))
PY

chmod 0644 "$TMP"
mv "$TMP" "$TARGET"
trap - EXIT
