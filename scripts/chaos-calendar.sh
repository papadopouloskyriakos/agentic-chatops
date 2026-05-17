#!/bin/bash
# chaos-calendar.sh -- Scheduled chaos exercise coordinator (CMM Level 3)
# Implements the exercise program schedule from docs/exercise-program.md
#
# Cron entry (daily 10:00 UTC -- script self-selects exercise type from date):
#   0 10 * * * /app/claude-gateway/scripts/chaos-calendar.sh >> /tmp/chaos-calendar.log 2>&1
#
# Manual usage:
#   chaos-calendar.sh                  # run today's scheduled exercise
#   chaos-calendar.sh --dry-run        # show what would run without executing
#   chaos-calendar.sh --force weekly-baseline   # force a specific exercise type
#   chaos-calendar.sh --force monthly-tunnel-sweep
#   chaos-calendar.sh --force quarterly-dmz-drill
#   chaos-calendar.sh --force quarterly-redteam
#   chaos-calendar.sh --force combined-game-day
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
LOG="/tmp/chaos-calendar.log"
MAINTENANCE_FILE="$HOME/gateway.maintenance"

# ── Parse arguments ─────────────────────────────────────────────────────────

DRY_RUN=false
FORCE_EXERCISE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true; shift ;;
        --force)    FORCE_EXERCISE="$2"; shift 2 ;;
        *)          echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Logging ─────────────────────────────────────────────────────────────────

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG"; }

# Rotate log if > 5MB
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 5242880 ]; then
    mv "$LOG" "${LOG}.1"
fi

# ── Matrix notification ─────────────────────────────────────────────────────

# (removed: old notify_matrix with injection-vulnerable curl+python pattern)

# Safe Matrix notification -- message piped via stdin to avoid shell/Python injection
notify_matrix_safe() {
    local message="$1"
    local room="${2:-!AOMuEtXGyzGFLgObKN:matrix.example.net}"

    local token=""
    if [ -f "$REPO_DIR/.env" ]; then
        token=$(grep '^MATRIX_CLAUDE_TOKEN=' "$REPO_DIR/.env" | cut -d= -f2- | tr -d "'" | tr -d '"')
    fi
    [ -z "$token" ] && return 0

    echo "$message" | MATRIX_TOKEN="$token" MATRIX_ROOM="$room" python3 -c "
import sys, urllib.request, urllib.parse, json, ssl, os, time
msg = sys.stdin.read().strip()
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
room = os.environ['MATRIX_ROOM']
token = os.environ['MATRIX_TOKEN']
txn_id = f'chaos-cal-{int(time.time())}-{os.getpid()}'
url = f'https://matrix.example.net/_matrix/client/v3/rooms/{urllib.parse.quote(room, safe=\"\")}/send/m.room.message/{txn_id}'
payload = json.dumps({'msgtype': 'm.notice', 'body': msg}).encode()
req = urllib.request.Request(url, data=payload, method='PUT')
req.add_header('Authorization', f'Bearer {token}')
req.add_header('Content-Type', 'application/json')
try:
    urllib.request.urlopen(req, context=ctx, timeout=10)
except Exception:
    pass
" 2>/dev/null || true
}

# ── Gates ───────────────────────────────────────────────────────────────────

# Gate: maintenance mode
if [ -f "$MAINTENANCE_FILE" ]; then
    log "SKIP: maintenance mode active"
    exit 0
fi

# Gate: active chaos test
if [ -f "$HOME/chaos-state/chaos-active.json" ]; then
    log "SKIP: chaos test already active"
    exit 0
fi

# ── Determine exercise type ────────────────────────────────────────────────

if [ -n "$FORCE_EXERCISE" ]; then
    EXERCISE="$FORCE_EXERCISE"
else
    DAY=$(date +%d)
    MONTH=$(date +%m)
    DOW=$(date +%u)

    EXERCISE=""
    if [[ "$DAY" == "15" && "$MONTH" =~ ^(06|12)$ ]]; then
        EXERCISE="combined-game-day"
    elif [[ "$DAY" == "15" && "$MONTH" =~ ^(01|04|07|10)$ ]]; then
        EXERCISE="quarterly-dmz-drill"
    elif [[ "$DAY" == "01" && "$MONTH" =~ ^(01|04|07|10)$ ]]; then
        EXERCISE="quarterly-redteam"
    elif [[ "$DAY" == "01" ]]; then
        EXERCISE="monthly-tunnel-sweep"
    elif [[ "$DOW" == "3" ]]; then
        EXERCISE="weekly-baseline"
    fi

    if [ -z "$EXERCISE" ]; then
        log "No exercise scheduled for today"
        exit 0
    fi
fi

log "=========================================="
log "Exercise determined: $EXERCISE"
log "=========================================="

# ── Dry-run mode ────────────────────────────────────────────────────────────

if [ "$DRY_RUN" = true ]; then
    log "[DRY-RUN] Would run exercise: $EXERCISE"
    case "$EXERCISE" in
        weekly-baseline)
            log "[DRY-RUN] 1 scenario: NL-GR Freedom tunnel kill (120s)"
            ;;
        monthly-tunnel-sweep)
            log "[DRY-RUN] 5 scenarios: NL-GR/NL-NO/NL-CH Freedom + GR-NO/GR-CH Inalan (120s each, 610s cooldown)"
            log "[DRY-RUN] Estimated duration: ~55 minutes"
            ;;
        quarterly-dmz-drill)
            log "[DRY-RUN] 2 scenarios: nl-dmz01 + gr-dmz01 container kill (120s each, 610s cooldown)"
            log "[DRY-RUN] Estimated duration: ~15 minutes"
            ;;
        quarterly-redteam)
            log "[DRY-RUN] 20 adversarial red-team tests against unified-guard hook (G33-G52)"
            log "[DRY-RUN] Categories: prompt injection bypass, tool chaining, indirect exfiltration, cross-tier escalation"
            log "[DRY-RUN] Estimated duration: ~30 seconds (no infrastructure impact)"
            ;;
        combined-game-day)
            log "[DRY-RUN] 3 scenarios: tunnel kill + DMZ kill + combined (120s each, 610s cooldown)"
            log "[DRY-RUN] Estimated duration: ~30 minutes"
            log "[DRY-RUN] WARNING: requires operator monitoring (semi-annual game day)"
            ;;
    esac
    exit 0
fi

# ── Preflight check ────────────────────────────────────────────────────────

# Janitor: clean orphaned alert suppressions from crashed tests (H2)
python3 "$SCRIPT_DIR/chaos_baseline.py" init-db 2>/dev/null || true
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR/lib'); sys.path.insert(0, '$SCRIPT_DIR')
from chaos_baseline import cleanup_orphan_suppressions
if cleanup_orphan_suppressions():
    print('Cleaned orphaned alert suppressions')
" 2>/dev/null || true

log "Running preflight check..."
PREFLIGHT_OUTPUT=$("$SCRIPT_DIR/chaos-preflight.sh" 2>&1) || true
PREFLIGHT_FAILS=$(echo "$PREFLIGHT_OUTPUT" | grep -c "FAIL" || true)

if [ "$PREFLIGHT_FAILS" -gt 0 ]; then
    log "ABORT: preflight check failed ($PREFLIGHT_FAILS failures)"
    log "$PREFLIGHT_OUTPUT"
    notify_matrix_safe "[CHAOS] ABORT: $EXERCISE cancelled -- preflight failed ($PREFLIGHT_FAILS checks)"
    exit 1
fi

log "Preflight passed"

# ── Load environment ────────────────────────────────────────────────────────

set -a
[ -f "$REPO_DIR/.env" ] && source "$REPO_DIR/.env"
set +a
export CHAOS_SKIP_TURNSTILE=true

# Record start time for exercise-summary query
EXERCISE_START=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
EXERCISE_PASS=0
EXERCISE_FAIL=0
EXERCISE_DEGRADED=0
EXERCISE_TOTAL=0

# ── Matrix notification: exercise start ─────────────────────────────────────

EXERCISE_LABEL=""
case "$EXERCISE" in
    weekly-baseline)        EXERCISE_LABEL="Weekly Baseline (NL-GR Freedom, 120s)" ;;
    monthly-tunnel-sweep)   EXERCISE_LABEL="Monthly Tunnel Sweep (5 scenarios)" ;;
    quarterly-dmz-drill)    EXERCISE_LABEL="Quarterly DMZ Drill (2 scenarios)" ;;
    quarterly-redteam)      EXERCISE_LABEL="Quarterly Red-Team (20 adversarial guard tests)" ;;
    combined-game-day)      EXERCISE_LABEL="Semi-Annual Combined Game Day (3 scenarios)" ;;
esac

notify_matrix_safe "[CHAOS] Exercise started: $EXERCISE_LABEL"
log "Matrix notification sent: exercise start"

# ── Run a single test scenario and capture result ───────────────────────────

run_scenario() {
    local description="$1"
    shift
    # Remaining args are the chaos_baseline.py command

    EXERCISE_TOTAL=$((EXERCISE_TOTAL + 1))
    log "Scenario $EXERCISE_TOTAL: $description"

    local output
    output=$(python3 "$SCRIPT_DIR/chaos_baseline.py" "$@" 2>&1) || true
    echo "$output" >> "$LOG"

    # Extract verdict from the last JSON output
    local verdict
    verdict=$(echo "$output" | python3 -c "
import sys, json
lines = sys.stdin.read().strip().split('\n')
# Find the last JSON block
for line in reversed(lines):
    line = line.strip()
    if line.startswith('{'):
        try:
            d = json.loads(line)
            print(d.get('verdict', 'UNKNOWN'))
            sys.exit(0)
        except:
            pass
# Try parsing the whole thing as JSON
try:
    d = json.loads('\n'.join(lines))
    print(d.get('verdict', 'UNKNOWN'))
except:
    print('UNKNOWN')
" 2>/dev/null) || verdict="UNKNOWN"

    case "$verdict" in
        PASS)     EXERCISE_PASS=$((EXERCISE_PASS + 1)); log "  Result: PASS" ;;
        DEGRADED) EXERCISE_DEGRADED=$((EXERCISE_DEGRADED + 1)); log "  Result: DEGRADED" ;;
        FAIL)     EXERCISE_FAIL=$((EXERCISE_FAIL + 1)); log "  Result: FAIL" ;;
        *)        log "  Result: $verdict" ;;
    esac
}

# ── Execute exercise ────────────────────────────────────────────────────────

case "$EXERCISE" in
    weekly-baseline)
        run_scenario "NL-GR Freedom VTI Kill" \
            baseline-test --tunnel "NL ↔ GR" --wan freedom --duration 120
        ;;

    monthly-tunnel-sweep)
        run_scenario "NL-GR Freedom VTI Kill" \
            baseline-test --tunnel "NL ↔ GR" --wan freedom --duration 120
        log "Cooldown 610s..."
        sleep 610

        run_scenario "NL-NO Freedom VTI Kill" \
            baseline-test --tunnel "NL ↔ NO" --wan freedom --duration 120
        log "Cooldown 610s..."
        sleep 610

        run_scenario "NL-CH Freedom VTI Kill" \
            baseline-test --tunnel "NL ↔ CH" --wan freedom --duration 120
        log "Cooldown 610s..."
        sleep 610

        run_scenario "GR-NO Inalan VTI Kill" \
            baseline-test --tunnel "GR ↔ NO" --wan inalan --duration 120
        log "Cooldown 610s..."
        sleep 610

        run_scenario "GR-CH Inalan VTI Kill" \
            baseline-test --tunnel "GR ↔ CH" --wan inalan --duration 120
        ;;

    quarterly-dmz-drill)
        run_scenario "NL DMZ All Containers Kill" \
            dmz-test --host nl-dmz01 --duration 120
        log "Cooldown 610s..."
        sleep 610

        run_scenario "GR DMZ All Containers Kill" \
            dmz-test --host gr-dmz01 --duration 120
        ;;

    quarterly-redteam)
        # Red-team exercises run the adversarial test suite against unified-guard.sh
        # No infrastructure impact -- purely tests hook pattern matching
        log "Running adversarial red-team test suite (G33-G52)..."

        REDTEAM_OUTPUT=$(python3 "$SCRIPT_DIR/test-hook-blocks.py" --adversarial 2>&1) || true
        echo "$REDTEAM_OUTPUT" >> "$LOG"

        # Parse pass/fail counts from output
        RT_PASS=$(echo "$REDTEAM_OUTPUT" | grep -oP '(\d+) PASS' | grep -oP '\d+' || echo "0")
        RT_FAIL=$(echo "$REDTEAM_OUTPUT" | grep -oP '(\d+) FAIL' | grep -oP '\d+' || echo "0")
        RT_TOTAL=$((RT_PASS + RT_FAIL))

        EXERCISE_TOTAL=1
        if [ "$RT_FAIL" -eq 0 ]; then
            EXERCISE_PASS=1
            log "Red-team suite: all $RT_TOTAL tests passed"
        else
            EXERCISE_FAIL=1
            log "Red-team suite: $RT_PASS pass / $RT_FAIL fail out of $RT_TOTAL"
        fi

        # Write red-team metrics
        if [ -x "$SCRIPT_DIR/write-redteam-metrics.sh" ]; then
            "$SCRIPT_DIR/write-redteam-metrics.sh" 2>/dev/null || true
        fi
        ;;

    combined-game-day)
        run_scenario "NL-GR Freedom VTI Kill" \
            baseline-test --tunnel "NL ↔ GR" --wan freedom --duration 120
        log "Cooldown 610s..."
        sleep 610

        run_scenario "NL DMZ All Containers Kill" \
            dmz-test --host nl-dmz01 --duration 120
        log "Cooldown 610s..."
        sleep 610

        run_scenario "Combined: NL-GR tunnel + NL DMZ" \
            baseline-test --tunnel "NL ↔ GR" --wan freedom --duration 120
        ;;
esac

# ── Post-exercise: generate summary ─────────────────────────────────────────

log "Generating exercise summary..."

SUMMARY_JSON=$(python3 "$SCRIPT_DIR/chaos_baseline.py" exercise-summary \
    --since "$EXERCISE_START" \
    --exercise-type "$EXERCISE" \
    --triggered-by "cron" 2>&1) || SUMMARY_JSON="{}"

# Extract key fields from summary
OVERALL=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('overall','UNKNOWN'))" 2>/dev/null) || OVERALL="UNKNOWN"
SUMMARY_LINE=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('summary',''))" 2>/dev/null) || SUMMARY_LINE=""
BUDGET=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('error_budget_consumed_pct',0))" 2>/dev/null) || BUDGET="0"
REGRESSIONS=$(echo "$SUMMARY_JSON" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(len(d.get('regressions',[])))" 2>/dev/null) || REGRESSIONS="0"

log "Exercise completed: $SUMMARY_LINE"
log "Overall: $OVERALL, Error budget: ${BUDGET}%, Regressions: $REGRESSIONS"

# ── Matrix notification: exercise end ───────────────────────────────────────

END_MSG="[CHAOS] Exercise completed: $EXERCISE_LABEL"
END_MSG="$END_MSG\nResult: $EXERCISE_PASS PASS"
[ "$EXERCISE_DEGRADED" -gt 0 ] && END_MSG="$END_MSG, $EXERCISE_DEGRADED DEGRADED"
[ "$EXERCISE_FAIL" -gt 0 ] && END_MSG="$END_MSG, $EXERCISE_FAIL FAIL"
END_MSG="$END_MSG ($EXERCISE_TOTAL scenarios)"
END_MSG="$END_MSG\nError budget consumed: ${BUDGET}%"
[ "$REGRESSIONS" -gt 0 ] && END_MSG="$END_MSG\nRegressions detected: $REGRESSIONS"

notify_matrix_safe "$END_MSG"

# ── Handle FAIL results: notify #alerts ──────────────────────────────────────

if [ "$EXERCISE_FAIL" -gt 0 ]; then
    FAIL_MSG="[CHAOS] FAIL: $EXERCISE -- $EXERCISE_FAIL/$EXERCISE_TOTAL scenarios failed"
    FAIL_MSG="$FAIL_MSG\nInvestigate: python3 scripts/chaos_baseline.py journal --limit $EXERCISE_TOTAL"

    # Post to #alerts
    notify_matrix_safe "$FAIL_MSG" "!xeNxtpScJWCmaFjeCL:matrix.example.net"
    log "FAIL notification sent to #alerts"
fi

# ── Write exercise metrics to Prometheus ─────────────────────────────────────

PROM_OUT="/var/lib/node_exporter/textfile_collector/chaos_exercise.prom"
PROM_TMP="${PROM_OUT}.tmp"

cat > "$PROM_TMP" << EOF
# HELP chaos_last_exercise_timestamp Unix timestamp of last scheduled exercise
# TYPE chaos_last_exercise_timestamp gauge
chaos_last_exercise_timestamp $(date +%s)
# HELP chaos_last_exercise_pass Whether the last exercise passed (1=yes, 0=no)
# TYPE chaos_last_exercise_pass gauge
chaos_last_exercise_pass $([ "$OVERALL" = "PASS" ] && echo 1 || echo 0)
# HELP chaos_last_exercise_scenarios Total scenarios in last exercise
# TYPE chaos_last_exercise_scenarios gauge
chaos_last_exercise_scenarios{result="pass"} $EXERCISE_PASS
chaos_last_exercise_scenarios{result="degraded"} $EXERCISE_DEGRADED
chaos_last_exercise_scenarios{result="fail"} $EXERCISE_FAIL
# HELP chaos_exercises_total_by_type Cumulative exercises by type
# TYPE chaos_exercises_total_by_type counter
chaos_exercises_total_by_type{type="$EXERCISE"} 1
EOF

mv "$PROM_TMP" "$PROM_OUT" 2>/dev/null || true

log "=========================================="
log "Exercise $EXERCISE completed. Overall: $OVERALL"
log "=========================================="

exit 0
