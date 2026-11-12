#!/bin/bash
# Weekly hard-eval cron.
# Runs the 50-query hard retrieval + 10-query KG eval, writes JSON results,
# emits kb_hard_eval_hit_rate / kb_hard_eval_kg_coverage metrics to the node-exporter
# textfile collector so Grafana can trend quality over time.
#
# Schedule: 0 5 * * 1 (Monday 05:00 UTC)
# Log: /tmp/weekly-eval.log

set -u
LOG=/tmp/weekly-eval.log
METRICS=/var/lib/node_exporter/textfile_collector/kb_rag_eval.prom
REPO=/app/claude-gateway

echo "=== $(date -Iseconds) weekly-eval start ===" >> "$LOG"
cd "$REPO" || { echo "cd failed" >> "$LOG"; exit 1; }

OUT=$(python3 scripts/run-hard-eval.py 2>>"$LOG")
# Extract the path printed by run-hard-eval.py as "Results written to <path>".
# The original -F': ' regex never matched (no colon on the line) — silently
# aborted every run with "no results file" before the first real Monday fire.
# Fixed 2026-04-18 (IFRNLLEI01PRD-614): use $NF (last whitespace-separated field).
RESULTS_PATH=$(echo "$OUT" | awk '/Results written to/ {print $NF}' | tail -1)
if [ -z "$RESULTS_PATH" ] || [ ! -f "$RESULTS_PATH" ]; then
  echo "no results file — aborting metric emit (OUT tail: $(echo "$OUT" | tail -3))" >> "$LOG"
  exit 1
fi

HIT=$(python3 -c "import json; d=json.load(open('$RESULTS_PATH')); print(d['retrieval']['judge_hit_at_5'])")
COV=$(python3 -c "import json; d=json.load(open('$RESULTS_PATH')); print(d['retrieval']['judge_coverage_at_5_mean'])")
KG=$(python3 -c "import json; d=json.load(open('$RESULTS_PATH')); print(d['kg']['judge_coverage_at_5'])")
P50=$(python3 -c "import json; d=json.load(open('$RESULTS_PATH')); print(d['retrieval']['latency_p50'])")
P95=$(python3 -c "import json; d=json.load(open('$RESULTS_PATH')); print(d['retrieval']['latency_p95'])")

TMP=$(mktemp)
{
  echo "# HELP kb_hard_eval_hit_rate Judge-graded hit@5 on 50-query hard retrieval eval"
  echo "# TYPE kb_hard_eval_hit_rate gauge"
  echo "kb_hard_eval_hit_rate $HIT"
  echo "# HELP kb_hard_eval_coverage_rate Judge-graded coverage@5 mean on hard retrieval eval"
  echo "# TYPE kb_hard_eval_coverage_rate gauge"
  echo "kb_hard_eval_coverage_rate $COV"
  echo "# HELP kb_hard_eval_kg_coverage KG traversal judge coverage@5 on 10-query hard KG eval"
  echo "# TYPE kb_hard_eval_kg_coverage gauge"
  echo "kb_hard_eval_kg_coverage $KG"
  echo "# HELP kb_hard_eval_latency_p50_seconds p50 retrieval latency during eval"
  echo "# TYPE kb_hard_eval_latency_p50_seconds gauge"
  echo "kb_hard_eval_latency_p50_seconds $P50"
  echo "# HELP kb_hard_eval_latency_p95_seconds p95 retrieval latency during eval"
  echo "# TYPE kb_hard_eval_latency_p95_seconds gauge"
  echo "kb_hard_eval_latency_p95_seconds $P95"
  echo "# HELP kb_hard_eval_last_run_timestamp_seconds Unix timestamp of last eval"
  echo "# TYPE kb_hard_eval_last_run_timestamp_seconds gauge"
  echo "kb_hard_eval_last_run_timestamp_seconds $(date +%s)"
} > "$TMP"

# Atomic rename into textfile collector dir (falls back to /tmp if not writable).
# Fixed 2026-04-18 (IFRNLLEI01PRD-614): chmod 644 so node-exporter (running
# as 'nobody') can read the file. mktemp creates mode 0600 by default.
if [ -w "$(dirname "$METRICS")" ]; then
  mv "$TMP" "$METRICS"
  chmod 644 "$METRICS"
  echo "metrics -> $METRICS" >> "$LOG"
else
  mv "$TMP" /tmp/kb_rag_eval.prom
  chmod 644 /tmp/kb_rag_eval.prom
  echo "metrics -> /tmp/kb_rag_eval.prom (fallback)" >> "$LOG"
fi

echo "hit=$HIT coverage=$COV kg=$KG p50=$P50 p95=$P95" >> "$LOG"
echo "=== $(date -Iseconds) weekly-eval done ===" >> "$LOG"
