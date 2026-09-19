#!/bin/bash
# write-qa-metrics.sh — export the latest QA-suite scorecard to Prometheus.
#
# Wires the 51-suite QA harness (scripts/qa/run-qa-suite.sh) into observability
# so it stops being a manual-only asset (IFRNLLEI01PRD-1089, 2026-06-16). Cron
# */5 reads the newest scorecard; the nightly run-qa-suite.sh regenerates it.
# Boot sentinels per feedback_prom_describe_needs_boot_sentinel so a stopped
# series never silently vanishes; PromQL filters {label!="boot"}.
set -uo pipefail
REPO="/app/claude-gateway"
OUT_DIR="${NODE_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
OUT="$OUT_DIR/qa_suite.prom"
TMP="$OUT.$$"
SCORECARD=$(ls -t "$REPO"/scripts/qa/reports/scorecard-*.json 2>/dev/null | head -1)

{
  echo "# HELP chatops_qa_total_pass QA-suite tests passing in the latest run."
  echo "# TYPE chatops_qa_total_pass gauge"
  echo "# HELP chatops_qa_total_fail QA-suite tests failing in the latest run."
  echo "# TYPE chatops_qa_total_fail gauge"
  echo "# HELP chatops_qa_score_pct QA-suite pass percentage in the latest run."
  echo "# TYPE chatops_qa_score_pct gauge"
  echo "# HELP chatops_qa_last_run_timestamp Unix mtime of the newest QA scorecard."
  echo "# TYPE chatops_qa_last_run_timestamp gauge"
  echo 'chatops_qa_total_pass{label="boot"} 0'
  echo 'chatops_qa_total_fail{label="boot"} 0'
  if [ -n "$SCORECARD" ] && [ -f "$SCORECARD" ]; then
    python3 - "$SCORECARD" <<'PY'
import json, sys, os
d = json.load(open(sys.argv[1]))
print(f'chatops_qa_total_pass{{label="latest"}} {d.get("total_pass", 0)}')
print(f'chatops_qa_total_fail{{label="latest"}} {d.get("total_fail", 0)}')
print(f'chatops_qa_score_pct {d.get("score_pct", 0)}')
print(f'chatops_qa_last_run_timestamp {int(os.path.getmtime(sys.argv[1]))}')
PY
  else
    echo 'chatops_qa_score_pct 0'
    echo 'chatops_qa_last_run_timestamp 0'
  fi
} > "$TMP" && mv "$TMP" "$OUT"
