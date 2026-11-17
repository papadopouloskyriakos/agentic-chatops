#!/bin/bash
# write-redteam-metrics.sh -- Prometheus textfile exporter for adversarial red-team results
#
# Reads /tmp/redteam-last-run.json (written by test-hook-blocks.py --adversarial)
# and exports metrics to node_exporter textfile collector.
#
# Output: /var/lib/node_exporter/textfile_collector/redteam_metrics.prom
#
# Usage:
#   Called automatically by chaos-calendar.sh after quarterly-redteam exercise.
#   Can also be run manually after: python3 scripts/test-hook-blocks.py --adversarial
#   write-redteam-metrics.sh --dry-run   # print to stdout instead of file
#
# Cron (optional, for dashboards between quarterly runs):
#   */5 * * * * /app/claude-gateway/scripts/write-redteam-metrics.sh

set -euo pipefail

RESULTS_FILE="/tmp/redteam-last-run.json"
PROM_OUT="/var/lib/node_exporter/textfile_collector/redteam_metrics.prom"

[ "${1:-}" = "--dry-run" ] && PROM_OUT="/dev/stdout"

PROM_TMP="${PROM_OUT}.tmp"
[ "$PROM_OUT" = "/dev/stdout" ] && PROM_TMP="/dev/stdout"

# Parse fields from JSON results (keys match test-hook-blocks.py output)
if [ -f "$RESULTS_FILE" ]; then
    TESTS_TOTAL=$(jq -r '.tests_total // 0' "$RESULTS_FILE" 2>/dev/null || echo 0)
    TESTS_PASS=$(jq -r '.tests_pass // 0' "$RESULTS_FILE" 2>/dev/null || echo 0)
    TESTS_FAIL=$(jq -r '.tests_fail // 0' "$RESULTS_FILE" 2>/dev/null || echo 0)
    LAST_RUN_TS=$(jq -r '.timestamp // 0' "$RESULTS_FILE" 2>/dev/null || echo 0)
else
    TESTS_TOTAL=0
    TESTS_PASS=0
    TESTS_FAIL=0
    LAST_RUN_TS=0
fi

# Validate parsed values are numeric (defense against malformed JSON)
for val in "$TESTS_TOTAL" "$TESTS_PASS" "$TESTS_FAIL" "$LAST_RUN_TS"; do
    if ! [[ "$val" =~ ^[0-9]+$ ]]; then
        echo "Error: non-numeric value parsed from $RESULTS_FILE" >&2
        exit 1
    fi
done

# Write metrics atomically (tmp + mv)
cat > "$PROM_TMP" << EOF
# HELP redteam_tests_total Total number of adversarial red-team test cases
# TYPE redteam_tests_total gauge
redteam_tests_total $TESTS_TOTAL
# HELP redteam_tests_pass Number of adversarial tests that passed (attack was blocked) in last run
# TYPE redteam_tests_pass gauge
redteam_tests_pass $TESTS_PASS
# HELP redteam_tests_fail Number of adversarial tests that failed (attack was NOT blocked) in last run
# TYPE redteam_tests_fail gauge
redteam_tests_fail $TESTS_FAIL
# HELP redteam_last_run_timestamp Unix epoch seconds of last adversarial test run
# TYPE redteam_last_run_timestamp gauge
redteam_last_run_timestamp $LAST_RUN_TS
EOF

[ "$PROM_OUT" != "/dev/stdout" ] && mv "$PROM_TMP" "$PROM_OUT" 2>/dev/null || true
