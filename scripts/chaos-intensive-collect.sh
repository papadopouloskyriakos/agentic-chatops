#!/bin/bash
# chaos-intensive-collect.sh -- Intensive data collection for statistical baselines
#
# Runs 3 experiments per session, 3 sessions/day at varied times for temporal diversity.
# 610s cooldown between experiments (rate limit minimum).
#
# Schedule (2 weeks):
#   Week 1+2: 06:00, 14:00, 22:00 UTC daily
#   Week 3: SKIP (rest)
#   Week 4+: Switch to regular chaos-calendar.sh
#
# Cron:
#   0 6,14,22 * * * /app/claude-gateway/scripts/chaos-intensive-collect.sh >> /tmp/chaos-intensive.log 2>&1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG="/tmp/chaos-intensive.log"
DB="$HOME/gitlab/products/cubeos/claude-context/gateway.db"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }

# Gates
[ -f "$HOME/gateway.maintenance" ] && { log "SKIP: maintenance mode"; exit 0; }
[ -f "$HOME/chaos-state/chaos-active.json" ] && { log "SKIP: chaos already active"; exit 0; }

# Check if we're still in the 2-week collection window
START_DATE="2026-04-14"
DAYS_SINCE=$(( ( $(date +%s) - $(date -d "$START_DATE" +%s) ) / 86400 ))
if [ "$DAYS_SINCE" -ge 14 ]; then
    log "Collection window closed (day $DAYS_SINCE). Remove this cron and activate chaos-calendar.sh"
    exit 0
fi

WEEK=$(( DAYS_SINCE / 7 + 1 ))
log "Intensive collection: week $WEEK, day $DAYS_SINCE"

export CHAOS_SKIP_TURNSTILE=true
cd "$REPO_DIR"

# Determine which 3 experiments to run this session.
# Rotate through all 13 scenarios using hour + day as index.
HOUR=$(date +%H)
DAY_OF_PERIOD=$DAYS_SINCE

# Build the full scenario list. Expanded 2026-04-22 [IFRNLLEI01PRD-674]
# to include Budget tunnel kills (3 new rows) since Budget is now
# active-active with Freedom on rtr01.
SCENARIOS=(
    "tunnel:NL ↔ GR:freedom"
    "tunnel:NL ↔ NO:freedom"
    "tunnel:NL ↔ CH:freedom"
    "tunnel:NL ↔ GR:budget"
    "tunnel:NL ↔ NO:budget"
    "tunnel:NL ↔ CH:budget"
    "tunnel:GR ↔ NO:inalan"
    "tunnel:GR ↔ CH:inalan"
    "dmz:nl-dmz01:"
    "dmz:gr-dmz01:"
    "container:nl-dmz01:portfolio"
    "tunnel:NL ↔ GR:freedom"
    "tunnel:NL ↔ NO:freedom"
    "tunnel:GR ↔ NO:inalan"
    "dmz:nl-dmz01:"
    "tunnel:NL ↔ CH:freedom"
)

# Calculate offset: 3 experiments per session, rotating through scenarios
# session_index = (day * 3 + hour_slot) where hour_slot = 0(06h), 1(14h), 2(22h)
case "$HOUR" in
    06) SLOT=0 ;;
    14) SLOT=1 ;;
    22) SLOT=2 ;;
    *)  SLOT=0 ;;
esac
OFFSET=$(( (DAY_OF_PERIOD * 3 + SLOT) * 3 ))

for i in 0 1 2; do
    IDX=$(( (OFFSET + i) % ${#SCENARIOS[@]} ))
    SCENARIO="${SCENARIOS[$IDX]}"
    IFS=: read -r TYPE ARG1 ARG2 <<< "$SCENARIO"

    log "Experiment $((i+1))/3: $TYPE $ARG1 $ARG2"

    case "$TYPE" in
        tunnel)
            python3 "$SCRIPT_DIR/chaos_baseline.py" baseline-test \
                --tunnel "$ARG1" --wan "$ARG2" --duration 120 2>&1 | tail -5
            ;;
        dmz)
            python3 "$SCRIPT_DIR/chaos_baseline.py" dmz-test \
                --host "$ARG1" --duration 120 2>&1 | tail -5
            ;;
        container)
            python3 "$SCRIPT_DIR/chaos_baseline.py" dmz-test \
                --host "$ARG1" --container "$ARG2" --duration 60 2>&1 | tail -5
            ;;
    esac

    RESULT=$?
    if [ $RESULT -ne 0 ]; then
        log "WARN: experiment failed (exit $RESULT), continuing"
    fi

    # Cooldown (skip after last experiment)
    if [ $i -lt 2 ]; then
        log "Cooldown 620s..."
        sleep 620
    fi
done

# Log session summary
TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_experiments;" 2>/dev/null || echo "?")
PASS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM chaos_experiments WHERE verdict='PASS';" 2>/dev/null || echo "?")
log "Session complete. Total experiments: $TOTAL, PASS: $PASS"
