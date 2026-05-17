#!/bin/bash
# validate-crowdsec-suppression.sh — Weekly CrowdSec suppression validation
#
# Checks if auto-suppressed scenarios have reappeared, computes false positive rate.
# Designed to run weekly via cron.
#
# Usage:
#   validate-crowdsec-suppression.sh           # Run validation
#   validate-crowdsec-suppression.sh --verbose  # Show details

set -uo pipefail

DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1

if [ ! -f "$DB" ]; then
  echo "ERROR: Database not found at $DB" >&2
  exit 1
fi

# Check suppressed scenarios that reappeared
REAPPEARED=$(sqlite3 "$DB" "
  SELECT scenario, host, total_count, suppressed_count
  FROM crowdsec_scenario_stats
  WHERE auto_suppressed = 1
  AND last_seen > datetime('now', '-7 days')
" 2>/dev/null)

TOTAL_SUPPRESSED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM crowdsec_scenario_stats WHERE auto_suppressed=1" 2>/dev/null)
REAPPEARED_COUNT=0
if [ -n "$REAPPEARED" ]; then
  REAPPEARED_COUNT=$(echo "$REAPPEARED" | grep -c '|' 2>/dev/null || echo 0)
fi

echo "=== CrowdSec Suppression Validation ==="
echo "Suppressed scenarios: $TOTAL_SUPPRESSED"
echo "Reappeared (last 7d): $REAPPEARED_COUNT"

if [ "$TOTAL_SUPPRESSED" -gt 0 ]; then
  FP_RATE=$(echo "scale=1; $REAPPEARED_COUNT * 100 / $TOTAL_SUPPRESSED" | bc 2>/dev/null || echo 0)
  echo "False positive rate: ${FP_RATE}%"
fi

if [ "$VERBOSE" -eq 1 ] && [ -n "$REAPPEARED" ]; then
  echo ""
  echo "Reappeared details:"
  echo "$REAPPEARED" | while IFS='|' read -r scenario host total suppressed; do
    echo "  $scenario on $host (total: $total, suppressed: $suppressed)"
  done
fi

# Show all suppressed scenarios
if [ "$VERBOSE" -eq 1 ]; then
  echo ""
  echo "All auto-suppressed scenarios:"
  sqlite3 -column -header "$DB" "
    SELECT scenario, host, total_count, suppressed_count, last_seen
    FROM crowdsec_scenario_stats
    WHERE auto_suppressed = 1
    ORDER BY last_seen DESC
  " 2>/dev/null
fi

echo ""
echo "Validation complete."
