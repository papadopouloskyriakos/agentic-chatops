#!/bin/bash
# CrowdSec Scenario Learning Loop
# Analyzes crowdsec_scenario_stats to auto-suppress consistently noisy scenarios
# and un-suppress scenarios that start getting escalated.
# Cron: 0 */6 * * * (every 6 hours, same cadence as regression-detector)

set -euo pipefail

DB="/app/cubeos/claude-context/gateway.db"
PROM_FILE="/var/lib/node_exporter/textfile_collector/crowdsec-learn.prom"
MATRIX_URL="https://matrix.example.net"
ALERTS_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
TOKEN_FILE="$HOME/.matrix-claude-token"

# Thresholds
MIN_ALERTS_FOR_LEARNING=20        # Minimum total alerts before learning kicks in
LEARNING_WINDOW_DAYS=7            # Look-back window
NOISE_SCORE_THRESHOLD=0           # escalated_count must be 0 to suppress

log() { echo "[$(date -u +%FT%TZ)] $*"; }

post_alert() {
  local msg="$1"
  if [ -f "$TOKEN_FILE" ]; then
    local token
    token=$(cat "$TOKEN_FILE")
    local txn="cs-learn-$(date +%s)-$RANDOM"
    curl -sf --max-time 10 -X PUT \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -d "{\"msgtype\":\"m.notice\",\"body\":\"$(echo "$msg" | sed 's/"/\\"/g')\"}" \
      "${MATRIX_URL}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/${txn}" >/dev/null 2>&1 || true
  fi
}

if [ ! -f "$DB" ]; then
  log "ERROR: Database not found at $DB"
  exit 1
fi

# --- Phase 1: Auto-suppress noisy scenarios ---
# Find scenarios with high count but zero escalations/YT issues in the learning window
NEWLY_SUPPRESSED=$(sqlite3 "$DB" "
  SELECT scenario, host, total_count
  FROM crowdsec_scenario_stats
  WHERE total_count >= $MIN_ALERTS_FOR_LEARNING
    AND escalated_count = $NOISE_SCORE_THRESHOLD
    AND yt_issues_created = 0
    AND auto_suppressed = 0
    AND last_seen >= datetime('now', '-${LEARNING_WINDOW_DAYS} days');
")

SUPPRESS_COUNT=0
if [ -n "$NEWLY_SUPPRESSED" ]; then
  while IFS='|' read -r scenario host count; do
    sqlite3 "$DB" "UPDATE crowdsec_scenario_stats SET auto_suppressed = 1 WHERE scenario = '$scenario' AND host = '$host';"
    log "AUTO-SUPPRESS: $scenario on $host ($count alerts, 0 escalations in ${LEARNING_WINDOW_DAYS}d)"
    SUPPRESS_COUNT=$((SUPPRESS_COUNT + 1))
  done <<< "$NEWLY_SUPPRESSED"

  if [ "$SUPPRESS_COUNT" -gt 0 ]; then
    post_alert "[CrowdSec Learning] Auto-suppressed $SUPPRESS_COUNT scenario(s):
$(echo "$NEWLY_SUPPRESSED" | while IFS='|' read -r s h c; do echo "  - $s on $h ($c alerts, 0 escalations)"; done)"
  fi
fi

# --- Phase 2: Un-suppress scenarios that got escalated ---
# If a suppressed scenario gets an escalation or YT issue, it's no longer noise
NEWLY_UNSUPPRESSED=$(sqlite3 "$DB" "
  SELECT scenario, host, escalated_count, yt_issues_created
  FROM crowdsec_scenario_stats
  WHERE auto_suppressed = 1
    AND (escalated_count > 0 OR yt_issues_created > 0);
")

UNSUPPRESS_COUNT=0
if [ -n "$NEWLY_UNSUPPRESSED" ]; then
  while IFS='|' read -r scenario host esc yt; do
    sqlite3 "$DB" "UPDATE crowdsec_scenario_stats SET auto_suppressed = 0 WHERE scenario = '$scenario' AND host = '$host';"
    log "UN-SUPPRESS: $scenario on $host (escalated=$esc, yt_issues=$yt)"
    UNSUPPRESS_COUNT=$((UNSUPPRESS_COUNT + 1))
  done <<< "$NEWLY_UNSUPPRESSED"

  if [ "$UNSUPPRESS_COUNT" -gt 0 ]; then
    post_alert "[CrowdSec Learning] Un-suppressed $UNSUPPRESS_COUNT scenario(s) (now generating escalations/issues):
$(echo "$NEWLY_UNSUPPRESSED" | while IFS='|' read -r s h e y; do echo "  - $s on $h (escalated=$e, yt=$y)"; done)"
  fi
fi

# --- Phase 3: Export Prometheus metrics ---
TOTAL_SUPPRESSED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM crowdsec_scenario_stats WHERE auto_suppressed = 1;" 2>/dev/null || echo 0)
TOTAL_SCENARIOS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM crowdsec_scenario_stats;" 2>/dev/null || echo 0)
TOTAL_ALERTS_7D=$(sqlite3 "$DB" "SELECT COALESCE(SUM(total_count), 0) FROM crowdsec_scenario_stats WHERE last_seen >= datetime('now', '-7 days');" 2>/dev/null || echo 0)

# Per-scenario suppression gauge
SUPPRESSED_DETAIL=$(sqlite3 "$DB" "SELECT scenario, host FROM crowdsec_scenario_stats WHERE auto_suppressed = 1;" 2>/dev/null || echo "")

TMPOUT="${PROM_FILE}.tmp"
cat > "$TMPOUT" <<EOF
# HELP crowdsec_learn_suppressed_total Total auto-suppressed scenario-host pairs
# TYPE crowdsec_learn_suppressed_total gauge
crowdsec_learn_suppressed_total $TOTAL_SUPPRESSED
# HELP crowdsec_learn_scenarios_total Total unique scenario-host pairs tracked
# TYPE crowdsec_learn_scenarios_total gauge
crowdsec_learn_scenarios_total $TOTAL_SCENARIOS
# HELP crowdsec_learn_alerts_7d Total CrowdSec alerts in last 7 days
# TYPE crowdsec_learn_alerts_7d gauge
crowdsec_learn_alerts_7d $TOTAL_ALERTS_7D
# HELP crowdsec_learn_last_run Timestamp of last learning loop run
# TYPE crowdsec_learn_last_run gauge
crowdsec_learn_last_run $(date +%s)
EOF

# Individual suppression entries
if [ -n "$SUPPRESSED_DETAIL" ]; then
  echo "# HELP crowdsec_learn_auto_suppressed Per-scenario auto-suppression flag" >> "$TMPOUT"
  echo "# TYPE crowdsec_learn_auto_suppressed gauge" >> "$TMPOUT"
  echo "$SUPPRESSED_DETAIL" | while IFS='|' read -r scenario host; do
    echo "crowdsec_learn_auto_suppressed{scenario=\"$scenario\",host=\"$host\"} 1" >> "$TMPOUT"
  done
fi

mv "$TMPOUT" "$PROM_FILE"

log "Learning complete: suppressed=$SUPPRESS_COUNT un-suppressed=$UNSUPPRESS_COUNT total_tracked=$TOTAL_SCENARIOS total_suppressed=$TOTAL_SUPPRESSED"
