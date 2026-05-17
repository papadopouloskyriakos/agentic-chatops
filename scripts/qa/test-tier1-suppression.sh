#!/usr/bin/env bash
# Tier 1 suppression library — unit + integration tests.
# Builds a fixture SQLite DB + triage.log in a tempdir; never touches production state.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LIB="$REPO/scripts/lib/tier1_suppression.py"
PY=python3

# colours
GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
PASS=0; FAIL=0; FAILED_TESTS=()

# Build a tempdir with fixture DB + triage.log
TMP="$(mktemp -d -t tier1-suppr.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
DB="$TMP/test.db"
LOG="$TMP/triage.log"

# ── Schema fixture ──
$PY -c "
import sqlite3
db = sqlite3.connect('$DB')
db.executescript('''
  CREATE TABLE incident_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_rule TEXT, hostname TEXT, site TEXT,
    root_cause TEXT, resolution TEXT,
    confidence REAL, duration_seconds INTEGER, cost_usd REAL,
    created_at DATETIME, session_id TEXT, issue_id TEXT,
    tags TEXT, embedding TEXT, project TEXT
  );
  CREATE TABLE openclaw_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT, key TEXT, value TEXT,
    issue_id TEXT, updated_at DATETIME
  );
''')
db.commit()
db.close()
"

# helper: append a triage.log row (ISO ts is required)
log_event() { # ts host rule site outcome conf dur issue
  printf '%s|%s|%s|%s|%s|%s|%s|%s\n' "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" >> "$LOG"
}

ik_insert() {
  $PY -c "
import sqlite3
db = sqlite3.connect('$DB')
db.execute(
  'INSERT INTO incident_knowledge (alert_rule, hostname, root_cause, resolution, confidence, created_at, issue_id, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
  ($1)
)
db.commit(); db.close()
"
}

om_insert() {
  $PY -c "
import sqlite3
db = sqlite3.connect('$DB')
db.execute(
  'INSERT INTO openclaw_memory (category, key, value, updated_at) VALUES (?, ?, ?, ?)',
  ($1)
)
db.commit(); db.close()
"
}

# helper: invoke the CLI, parse JSON, assert a field
run_cli() {
  $PY "$LIB" "$@" 2>&1
}

assert_jq() { # description json_text python_expr expected
  local desc="$1" json="$2" expr="$3" expected="$4"
  local actual
  actual=$(printf '%s' "$json" | $PY -c "
import sys, json
d = json.loads(sys.stdin.read())
print($expr)
" 2>&1)
  if [ "$actual" = "$expected" ]; then
    PASS=$((PASS+1))
    printf '  %sPASS%s %s\n' "$GREEN" "$RESET" "$desc"
  else
    FAIL=$((FAIL+1))
    FAILED_TESTS+=("$desc")
    printf '  %sFAIL%s %s\n' "$RED" "$RESET" "$desc"
    printf '       expected: %s\n       actual:   %s\n       json:     %s\n' "$expected" "$actual" "$json"
  fi
}

***REMOVED***═════
echo "[1] Empty state → all three phases pass through → escalate"
***REMOVED***═════
NOW="2026-05-11T10:00:00Z"
OUT=$(run_cli --hostname host1 --rule-name 'Rule A' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "empty: outcome=escalate" "$OUT" "d['outcome']" "escalate"
assert_jq "empty: phase=none"       "$OUT" "d['phase']"   "none"

***REMOVED***═════
echo "[2] Phase 1 dedup — prior escalation within window, no YT check"
***REMOVED***═════
log_event "2026-05-11T08:30:00Z" "host2" "Rule B" "nl" "escalated" "0.8" "200" "IFRNLLEI01PRD-2001"
OUT=$(run_cli --hostname host2 --rule-name 'Rule B' --severity warning \
  --current-issue-id IFRNLLEI01PRD-2099 \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase1: outcome=dedup"   "$OUT" "d['outcome']" "dedup"
assert_jq "phase1: phase tag"       "$OUT" "d['phase']"   "phase1-dedup"
assert_jq "phase1: parent issue"    "$OUT" "d['existing_issue_id']" "IFRNLLEI01PRD-2001"

***REMOVED***═════
echo "[3] Phase 1 — parent outside window → escalate"
***REMOVED***═════
# 7h ago — outside 6h default window
log_event "2026-05-11T03:00:00Z" "host3" "Rule C" "nl" "escalated" "0.8" "200" "IFRNLLEI01PRD-3001"
OUT=$(run_cli --hostname host3 --rule-name 'Rule C' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase1-stale: outcome=escalate" "$OUT" "d['outcome']" "escalate"
assert_jq "phase1-stale: phase tag"        "$OUT" "d['phase']"   "none"

***REMOVED***═════
echo "[4] Phase 1 — different rule on same host → escalate"
***REMOVED***═════
log_event "2026-05-11T09:30:00Z" "host4" "Rule D" "nl" "escalated" "0.8" "200" "IFRNLLEI01PRD-4001"
OUT=$(run_cli --hostname host4 --rule-name 'Rule X' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase1-rule-mismatch: escalate" "$OUT" "d['outcome']" "escalate"

***REMOVED***═════
echo "[5] Phase 1 — prior was 'resolved' (not escalated) → escalate"
***REMOVED***═════
log_event "2026-05-11T09:30:00Z" "host5" "Rule E" "nl" "resolved" "0.8" "200" "IFRNLLEI01PRD-5001"
OUT=$(run_cli --hostname host5 --rule-name 'Rule E' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase1-resolved-prior: escalate" "$OUT" "d['outcome']" "escalate"

***REMOVED***═════
echo "[6] Phase 1 — critical severity dedup IS allowed"
***REMOVED***═════
log_event "2026-05-11T09:30:00Z" "host6" "Rule F" "nl" "escalated" "0.8" "200" "IFRNLLEI01PRD-6001"
OUT=$(run_cli --hostname host6 --rule-name 'Rule F' --severity critical \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase1-critical: dedup" "$OUT" "d['outcome']" "dedup"

***REMOVED***═════
echo "[7] Phase 2 — known-transient match in incident_knowledge"
***REMOVED***═════
ik_insert "'Rule G','host7','intermittent ICMP loss on edge AP','self-resolved after WAN re-association',0.85,'2026-05-09T14:00:00','IFRNLLEI01PRD-7001','flap,transient'"
OUT=$(run_cli --hostname host7 --rule-name 'Rule G' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase2: outcome=resolved-knownpattern" "$OUT" "d['outcome']" "resolved-knownpattern"
assert_jq "phase2: phase tag"                     "$OUT" "d['phase']"   "phase2-knownpattern"

***REMOVED***═════
echo "[8] Phase 2 — confidence below 0.7 → no match → escalate"
***REMOVED***═════
ik_insert "'Rule H','host8','transient','flap',0.5,'2026-05-09T14:00:00','IFRNLLEI01PRD-8001','transient'"
OUT=$(run_cli --hostname host8 --rule-name 'Rule H' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase2-lowconf: escalate" "$OUT" "d['outcome']" "escalate"

***REMOVED***═════
echo "[9] Phase 2 — critical severity disallows known-pattern auto-resolve"
***REMOVED***═════
ik_insert "'Rule I','host9','transient','self-resolved',0.9,'2026-05-09T14:00:00','IFRNLLEI01PRD-9001','transient'"
OUT=$(run_cli --hostname host9 --rule-name 'Rule I' --severity critical \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase2-critical: escalate" "$OUT" "d['outcome']" "escalate"

***REMOVED***═════
echo "[10] Phase 2 — no transient keyword in tags → escalate"
***REMOVED***═════
ik_insert "'Rule J','host10','config drift','applied fix manually',0.9,'2026-05-09T14:00:00','IFRNLLEI01PRD-10001','infra,drift'"
OUT=$(run_cli --hostname host10 --rule-name 'Rule J' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase2-no-keyword: escalate" "$OUT" "d['outcome']" "escalate"

***REMOVED***═════
echo "[11] Phase 3 — active-memory rule match"
***REMOVED***═════
om_insert "'triage-rule','host11:Sensor under *','suppress:HVAC sensor known-flaky','2026-05-08T10:00:00'"
OUT=$(run_cli --hostname host11 --rule-name 'Sensor under limit' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase3: outcome=resolved-active-memory" "$OUT" "d['outcome']" "resolved-active-memory"
assert_jq "phase3: phase tag"                       "$OUT" "d['phase']"   "phase3-active-memory"

***REMOVED***═════
echo "[12] Phase 3 — glob host match"
***REMOVED***═════
om_insert "'triage-rule','*ap0?:Device Down*','suppress:any-AP-icmp-flap','2026-05-08T10:00:00'"
OUT=$(run_cli --hostname "gr2ap01" --rule-name 'Device Down! Due to no ICMP' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase3-glob: outcome" "$OUT" "d['outcome']" "resolved-active-memory"

***REMOVED***═════
echo "[13] Phase 3 — critical severity disallows active-memory suppress"
***REMOVED***═════
om_insert "'triage-rule','host13:*','suppress:test','2026-05-08T10:00:00'"
OUT=$(run_cli --hostname host13 --rule-name 'AnyRule' --severity critical \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase3-critical: escalate" "$OUT" "d['outcome']" "escalate"

***REMOVED***═════
echo "[14] force_escalate short-circuits everything"
***REMOVED***═════
log_event "2026-05-11T09:30:00Z" "host14" "Rule N" "nl" "escalated" "0.8" "200" "IFRNLLEI01PRD-14001"
om_insert "'triage-rule','host14:*','suppress:would-have-fired','2026-05-08T10:00:00'"
OUT=$(run_cli --hostname host14 --rule-name 'Rule N' --severity warning \
  --force-escalate --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "force-escalate: outcome" "$OUT" "d['outcome']" "escalate"
assert_jq "force-escalate: phase"   "$OUT" "d['phase']"   "none"

***REMOVED***═════
echo "[15] TIER1_SUPPRESSION_DISABLED=1 env → escalate"
***REMOVED***═════
OUT=$(TIER1_SUPPRESSION_DISABLED=1 run_cli --hostname host7 --rule-name 'Rule G' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "disabled-env: outcome" "$OUT" "d['outcome']" "escalate"

***REMOVED***═════
echo "[16] YT-open checker returns False → phase1 backs off to escalate"
***REMOVED***═════
# Inject a stub checker via PYTHONPATH trick — use the library directly in a Python harness
OUT=$($PY <<EOF
import sys, json
sys.path.insert(0, "$REPO/scripts/lib")
from tier1_suppression import check_suppression
def closed(_): return False
d = check_suppression(
  hostname="host6", rule_name="Rule F", severity="warning",
  db_path="$DB", triage_log_path="$LOG",
  yt_issue_open_checker=closed,
)
print(d.to_json())
EOF
)
assert_jq "phase1-yt-closed: outcome" "$OUT" "d['outcome']" "escalate"
assert_jq "phase1-yt-closed: reason mentions closed" "$OUT" "'is closed' in d['reason']" "True"
assert_jq "phase1-yt-closed: parent in signals"      "$OUT" "'parent_state' in d['signals'].get('phase1', {})" "True"

***REMOVED***═════
echo "[17] YT-open checker raises → fails open (escalate, with error in signals)"
***REMOVED***═════
OUT=$($PY <<EOF
import sys, json
sys.path.insert(0, "$REPO/scripts/lib")
from tier1_suppression import check_suppression
def kaboom(_): raise RuntimeError("network down")
d = check_suppression(
  hostname="host6", rule_name="Rule F", severity="warning",
  db_path="$DB", triage_log_path="$LOG",
  yt_issue_open_checker=kaboom,
)
print(d.to_json())
EOF
)
assert_jq "yt-error: outcome=escalate"        "$OUT" "d['outcome']" "escalate"
assert_jq "yt-error: signals carry error msg" "$OUT" "'network down' in d['signals'].get('phase1',{}).get('error','')" "True"

***REMOVED***═════
echo "[18] Phase 1 precedence — also has a phase 2 match → returns phase1 first"
***REMOVED***═════
log_event "2026-05-11T09:30:00Z" "host18" "Rule P" "nl" "escalated" "0.8" "200" "IFRNLLEI01PRD-18001"
ik_insert "'Rule P','host18','transient','self-resolved',0.95,'2026-05-09T14:00:00','IFRNLLEI01PRD-18900','transient,flap'"
OUT=$(run_cli --hostname host18 --rule-name 'Rule P' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase1-wins: phase tag" "$OUT" "d['phase']" "phase1-dedup"

***REMOVED***═════
echo "[19] Phase 2 precedence over phase 3"
***REMOVED***═════
ik_insert "'Rule Q','host19','transient','recovered',0.9,'2026-05-09T14:00:00','IFRNLLEI01PRD-19001','transient'"
om_insert "'triage-rule','host19:Rule Q','suppress:active-mem-also-matches','2026-05-08T10:00:00'"
OUT=$(run_cli --hostname host19 --rule-name 'Rule Q' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
assert_jq "phase2-wins-vs-3: phase tag" "$OUT" "d['phase']" "phase2-knownpattern"

***REMOVED***═════
echo "[20] JSON shape is stable — required fields present"
***REMOVED***═════
log_event "2026-05-11T09:30:00Z" "host20" "Rule R" "nl" "escalated" "0.8" "200" "IFRNLLEI01PRD-20001"
OUT=$(run_cli --hostname host20 --rule-name 'Rule R' --severity warning \
  --db "$DB" --triage-log "$LOG" --no-yt-check --now-utc "$NOW")
for field in outcome phase reason existing_issue_id comment_text confidence signals; do
  assert_jq "shape: has '$field'" "$OUT" "'$field' in d" "True"
done

***REMOVED***═════
echo
echo "══════════════════════════════════════════════════════════════════"
echo "SUMMARY: ${GREEN}${PASS} pass${RESET}, ${RED}${FAIL} fail${RESET}"
if [ "$FAIL" -gt 0 ]; then
  printf 'Failed tests:\n'
  for t in "${FAILED_TESTS[@]}"; do printf '  - %s\n' "$t"; done
  exit 1
fi
exit 0
