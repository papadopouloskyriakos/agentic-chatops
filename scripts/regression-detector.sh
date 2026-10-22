#!/bin/bash
# regression-detector.sh — Detect regressions in ChatOps platform metrics
# Compares rolling 7-day windows. Posts to Matrix #alerts on significant changes.
# Cron: every 6 hours — 0 */6 * * *

set -uo pipefail

DB="/app/cubeos/claude-context/gateway.db"
MATRIX_URL="https://matrix.example.net"
ALERTS_ROOM="!xeNxtpScJWCmaFjeCL:matrix.example.net"
MATRIX_TOKEN=$(grep -oP 'MATRIX_BOT_TOKEN=\K.*' /home/app-user/.env 2>/dev/null || echo "")

[ -f "$DB" ] || exit 0

# ─── Helper: post to Matrix #alerts ───
post_alert() {
  local msg="$1"
  [ -z "$MATRIX_TOKEN" ] && { echo "$msg"; return; }
  curl -sf --max-time 10 \
    -X PUT \
    -H "Authorization: Bearer $MATRIX_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"msgtype\":\"m.notice\",\"body\":\"$msg\"}" \
    "${MATRIX_URL}/_matrix/client/v3/rooms/${ALERTS_ROOM}/send/m.room.message/$(date +%s%N)" \
    >/dev/null 2>&1 || true
}

# ─── Minimum session count check ───
CURRENT_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE started_at > datetime('now','-7 days');" 2>/dev/null || echo 0)
PRIOR_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log WHERE started_at BETWEEN datetime('now','-14 days') AND datetime('now','-7 days');" 2>/dev/null || echo 0)

if [ "$CURRENT_COUNT" -lt 3 ] || [ "$PRIOR_COUNT" -lt 3 ]; then
  echo "Not enough sessions for comparison (current: $CURRENT_COUNT, prior: $PRIOR_COUNT). Need 3+ each."
  exit 0
fi

ALERTS=""

# ─── 1. Confidence regression ───
CURRENT_CONF=$(sqlite3 "$DB" "SELECT COALESCE(AVG(confidence),-1) FROM session_log WHERE confidence >= 0 AND started_at > datetime('now','-7 days');" 2>/dev/null)
PRIOR_CONF=$(sqlite3 "$DB" "SELECT COALESCE(AVG(confidence),-1) FROM session_log WHERE confidence >= 0 AND started_at BETWEEN datetime('now','-14 days') AND datetime('now','-7 days');" 2>/dev/null)

if [ "$(echo "$CURRENT_CONF >= 0 && $PRIOR_CONF >= 0" | bc -l 2>/dev/null)" = "1" ]; then
  CONF_DROP=$(echo "$PRIOR_CONF - $CURRENT_CONF" | bc -l 2>/dev/null || echo 0)
  if [ "$(echo "$CONF_DROP > 0.1" | bc -l 2>/dev/null)" = "1" ]; then
    ALERTS="${ALERTS}Confidence dropped: $(printf '%.2f' "$PRIOR_CONF") -> $(printf '%.2f' "$CURRENT_CONF") (delta: -$(printf '%.2f' "$CONF_DROP"))\n"
  fi
fi

# ─── 2. Cost increase ───
CURRENT_COST=$(sqlite3 "$DB" "SELECT COALESCE(AVG(cost_usd),0) FROM session_log WHERE cost_usd > 0 AND started_at > datetime('now','-7 days');" 2>/dev/null)
PRIOR_COST=$(sqlite3 "$DB" "SELECT COALESCE(AVG(cost_usd),0) FROM session_log WHERE cost_usd > 0 AND started_at BETWEEN datetime('now','-14 days') AND datetime('now','-7 days');" 2>/dev/null)

if [ "$(echo "$PRIOR_COST > 0" | bc -l 2>/dev/null)" = "1" ]; then
  COST_RATIO=$(echo "$CURRENT_COST / $PRIOR_COST" | bc -l 2>/dev/null || echo 1)
  if [ "$(echo "$COST_RATIO > 1.5" | bc -l 2>/dev/null)" = "1" ]; then
    ALERTS="${ALERTS}Avg session cost increased: \$$(printf '%.2f' "$PRIOR_COST") -> \$$(printf '%.2f' "$CURRENT_COST") ($(printf '%.0f' "$(echo "($COST_RATIO - 1) * 100" | bc -l)")% increase)\n"
  fi
fi

# ─── 3. Thumbs down rate increase ───
CURRENT_DOWNS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_feedback WHERE feedback_type='thumbs_down' AND created_at > datetime('now','-7 days');" 2>/dev/null || echo 0)
PRIOR_DOWNS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_feedback WHERE feedback_type='thumbs_down' AND created_at BETWEEN datetime('now','-14 days') AND datetime('now','-7 days');" 2>/dev/null || echo 0)

if [ "$PRIOR_DOWNS" -gt 0 ] && [ "$CURRENT_DOWNS" -gt "$((PRIOR_DOWNS * 2))" ]; then
  ALERTS="${ALERTS}Thumbs-down rate doubled: $PRIOR_DOWNS -> $CURRENT_DOWNS (last 7d vs prior 7d)\n"
fi

# ─── 4. Prompt variant comparison (if A/B testing is active) ───
VARIANT_DATA=$(sqlite3 "$DB" "
  SELECT prompt_variant, COUNT(*), COALESCE(AVG(confidence),-1), COALESCE(AVG(cost_usd),0)
  FROM session_log
  WHERE prompt_variant != '' AND prompt_variant IS NOT NULL
    AND started_at > datetime('now','-14 days')
  GROUP BY prompt_variant
  HAVING COUNT(*) >= 3;" 2>/dev/null)

if [ -n "$VARIANT_DATA" ]; then
  VARIANT_REPORT=""
  while IFS='|' read -r variant count avg_conf avg_cost; do
    VARIANT_REPORT="${VARIANT_REPORT}  ${variant}: n=${count}, conf=$(printf '%.2f' "$avg_conf"), cost=\$$(printf '%.2f' "$avg_cost")\n"
  done <<< "$VARIANT_DATA"
  if [ -n "$VARIANT_REPORT" ]; then
    echo -e "A/B variant comparison (14d):\n$VARIANT_REPORT"
  fi
fi

# ─── 5. Duration increase ───
CURRENT_DUR=$(sqlite3 "$DB" "SELECT COALESCE(AVG(duration_seconds),0) FROM session_log WHERE duration_seconds > 0 AND started_at > datetime('now','-7 days');" 2>/dev/null)
PRIOR_DUR=$(sqlite3 "$DB" "SELECT COALESCE(AVG(duration_seconds),0) FROM session_log WHERE duration_seconds > 0 AND started_at BETWEEN datetime('now','-14 days') AND datetime('now','-7 days');" 2>/dev/null)

if [ "$(echo "$PRIOR_DUR > 0" | bc -l 2>/dev/null)" = "1" ]; then
  DUR_RATIO=$(echo "$CURRENT_DUR / $PRIOR_DUR" | bc -l 2>/dev/null || echo 1)
  if [ "$(echo "$DUR_RATIO > 2.0" | bc -l 2>/dev/null)" = "1" ]; then
    ALERTS="${ALERTS}Avg session duration doubled: $(printf '%.0f' "$PRIOR_DUR")s -> $(printf '%.0f' "$CURRENT_DUR")s\n"
  fi
fi

# ─── 6. Confidence calibration gap ───
CAL_DATA=$(sqlite3 "$DB" "
SELECT COUNT(*), COALESCE(SUM(CASE WHEN sf.feedback_type='thumbs_up' THEN 1 ELSE 0 END), 0)
FROM session_log sl JOIN session_feedback sf ON sl.issue_id = sf.issue_id
WHERE sl.confidence >= 0.8 AND sl.started_at > datetime('now', '-30 days');" 2>/dev/null || echo "0|0")
CAL_N=$(echo "$CAL_DATA" | cut -d'|' -f1)
CAL_UP=$(echo "$CAL_DATA" | cut -d'|' -f2)
if [ "$CAL_N" -ge 5 ]; then
  CAL_RATE=$(echo "$CAL_UP $CAL_N" | awk '{printf "%.2f", $1/$2}')
  if [ "$(echo "$CAL_RATE < 0.70" | bc -l 2>/dev/null)" = "1" ]; then
    ALERTS="${ALERTS}Confidence calibration gap: high-confidence band (>=0.8) has only ${CAL_RATE} thumbs-up rate (n=$CAL_N, expected >=0.70)\n"
  fi
fi

# ─── 7. Quality score drop ───
CURRENT_Q=$(sqlite3 "$DB" "SELECT COALESCE(AVG(quality_score),0) FROM session_quality WHERE quality_score >= 0 AND created_at > datetime('now','-7 days');" 2>/dev/null || echo 0)
PRIOR_Q=$(sqlite3 "$DB" "SELECT COALESCE(AVG(quality_score),0) FROM session_quality WHERE quality_score >= 0 AND created_at BETWEEN datetime('now','-14 days') AND datetime('now','-7 days');" 2>/dev/null || echo 0)
if [ "$(echo "$CURRENT_Q > 0 && $PRIOR_Q > 0" | bc -l 2>/dev/null)" = "1" ]; then
  Q_DROP=$(echo "$PRIOR_Q - $CURRENT_Q" | bc -l 2>/dev/null || echo 0)
  if [ "$(echo "$Q_DROP > 10" | bc -l 2>/dev/null)" = "1" ]; then
    ALERTS="${ALERTS}Quality score dropped: $(printf '%.0f' "$PRIOR_Q") -> $(printf '%.0f' "$CURRENT_Q") (delta: -$(printf '%.0f' "$Q_DROP"))\n"
  fi
fi

# ─── CrowdSec-specific regression checks ───

# Check 1: Learning instability — too many suppression changes in one cycle
CS_SUPP_CURRENT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM crowdsec_scenario_stats WHERE auto_suppressed = 1;" 2>/dev/null || echo 0)
CS_SUPP_PREV=$(sqlite3 "$DB" "SELECT COUNT(*) FROM crowdsec_scenario_stats WHERE auto_suppressed = 1 AND last_seen < datetime('now', '-6 hours');" 2>/dev/null || echo 0)
CS_SUPP_DELTA=$(( ${CS_SUPP_CURRENT:-0} - ${CS_SUPP_PREV:-0} ))
if [ "${CS_SUPP_DELTA#-}" -gt 3 ] 2>/dev/null; then
  ALERTS="${ALERTS}- CrowdSec learning instability: suppression count changed by $CS_SUPP_DELTA in 6h (was $CS_SUPP_PREV, now $CS_SUPP_CURRENT)\n"
fi

# Check 2: CrowdSec alert drought — 0 alerts for 24h may indicate agent failure
CS_LAST_ALERT=$(sqlite3 "$DB" "SELECT MAX(last_seen) FROM crowdsec_scenario_stats;" 2>/dev/null || echo "")
if [ -n "$CS_LAST_ALERT" ] && [ "$CS_LAST_ALERT" != "" ]; then
  CS_HOURS_AGO=$(python3 -c "
from datetime import datetime
try:
    last = datetime.fromisoformat('$CS_LAST_ALERT')
    delta = (datetime.utcnow() - last).total_seconds() / 3600
    print(int(delta))
except: print(0)
" 2>/dev/null || echo 0)
  if [ "${CS_HOURS_AGO:-0}" -gt 24 ] 2>/dev/null; then
    ALERTS="${ALERTS}- CrowdSec alert drought: no alerts for ${CS_HOURS_AGO}h — possible agent failure on one or more hosts\n"
  fi
fi

# Check 3: Sustained high flap rate — persistent attacker evading detection
CS_FLAP_24H=$(sqlite3 "$DB" "SELECT COALESCE(SUM(total_count), 0) FROM crowdsec_scenario_stats WHERE last_seen >= datetime('now', '-1 day');" 2>/dev/null || echo 0)
# Note: we check flap from the active alerts file, not the stats table
CS_FLAP_FILE="/app/cubeos/claude-context/active-crowdsec-alerts.json"
if [ -f "$CS_FLAP_FILE" ]; then
  CS_FLAP_TOTAL=$(python3 -c "
import json
try:
    d = json.load(open('$CS_FLAP_FILE'))
    alerts = d.get('activeAlerts', {})
    print(sum(a.get('flapCount', 0) for a in alerts.values()))
except: print(0)
" 2>/dev/null || echo 0)
  if [ "${CS_FLAP_TOTAL:-0}" -gt 5 ] 2>/dev/null; then
    ALERTS="${ALERTS}- CrowdSec sustained flapping: $CS_FLAP_TOTAL flap events active — persistent attacker or misconfigured bouncer\n"
  fi
fi

# ─── Post alerts if any ───
if [ -n "$ALERTS" ]; then
  MSG="REGRESSION DETECTED (7d vs prior 7d, n=$CURRENT_COUNT vs n=$PRIOR_COUNT):\n${ALERTS}Review prompt changes, model updates, or infrastructure issues."
  echo -e "$MSG"
  post_alert "$(echo -e "$MSG")"
else
  echo "No regressions detected (current: n=$CURRENT_COUNT, prior: n=$PRIOR_COUNT)"
fi
