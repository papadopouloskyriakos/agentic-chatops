#!/bin/bash
# Cron wrapper for write-budget-bandwidth-metrics.py.
# Runs every 2 minutes, samples rtr01 Dialer1 interface rate, emits Prometheus textfile.
# Paired with BudgetBandwidthSaturated alert in prometheus/alert-rules/infrastructure-integrity.yml.

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
LOG_FILE="/home/app-user/logs/claude-gateway/budget-bandwidth-metrics.log"

mkdir -p "$(dirname "$LOG_FILE")"

# Load .env for CISCO_ASA_PASSWORD (shared with rtr01 credential)
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
fi

# Suppression: skip during maintenance window or active chaos test
# shellcheck source=scripts/lib/suppression-gates.sh
source "$REPO_DIR/scripts/lib/suppression-gates.sh"
check_suppression_gates || exit 0

exec python3 "$REPO_DIR/scripts/write-budget-bandwidth-metrics.py" >> "$LOG_FILE" 2>&1
