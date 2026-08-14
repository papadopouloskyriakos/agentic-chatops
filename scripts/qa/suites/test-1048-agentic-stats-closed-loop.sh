#!/usr/bin/env bash
# IFRNLLEI01PRD-1048 — agentic-stats closed-loop p95 must populate.
# Repeat-alert escalations dedup per incident; finalized durations resolve from
# sessions OR session_log; stale unfinalized escalations age out of n_open.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1048-agentic-stats-closed-loop"

FIXDB=$(mktemp --suffix=.db); sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
FIXLOG=$(mktemp)
python3 - "$FIXLOG" <<'PY'
import sys, datetime
now = datetime.datetime.now(datetime.timezone.utc)
def iso(days): return (now - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
rows = []
rows += [f"{iso(1)}|h|alert|nl|escalated|0|0|MESHSAT-9001"] * 5   # flap storm: 5 events, 1 incident
rows += [f"{iso(1)}|h|alert|nl|escalated|0|0|IFRNLLEI01PRD-9002"]  # recent, unfinalized -> open
rows += [f"{iso(5)}|h|alert|nl|escalated|0|0|IFRNLLEI01PRD-9003"]  # stale (>2d) -> abandoned, NOT open
rows += [f"{iso(2)}|h|alert|nl|resolved|0|0|IFRNLLEI01PRD-9004"]   # Tier-1 -> closed at 0
rows += [f"{iso(2)}|h|alert|nl|resolved|0|0|"]                     # no-id instant resolve -> 0
open(sys.argv[1], "w").write("\n".join(rows) + "\n")
PY
# MESHSAT-9001's session finalized in session_log (the archived path) — NOT in sessions
sqlite3 "$FIXDB" "INSERT INTO session_log(issue_id,duration_seconds,started_at,ended_at)
  VALUES('MESHSAT-9001',417,datetime('now','-1 day'),datetime('now','-1 day','+417 seconds'));"

CL=$(GATEWAY_DB="$FIXDB" TRIAGE_LOG="$FIXLOG" python3 "$REPO_ROOT/scripts/agentic-stats.py" 2>/dev/null \
     | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['outcomes']['closed_loop']))")
get() { printf '%s' "$CL" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$1'))"; }

start_test "p95_populates_from_finalized_escalation_in_session_log"
  # the core bug: a finalized escalated loop (in session_log, not sessions) must
  # produce a real p95 instead of 0/null.
  assert_eq "417" "$(get p95_seconds)" "p95 = the session_log duration"
  assert_ne "None" "$(get median_seconds)" "median is non-null when a loop is closed"
end_test

start_test "n_open_dedups_flap_storm_and_ages_out_stale"
  # 5 flap escalations -> 1 incident (closed via duration); recent unfinalized -> 1 open;
  # stale (>STALE_OPEN_DAYS) -> abandoned. So exactly 1 open, not 6+ phantoms.
  assert_eq "1" "$(get n_open)" "n_open = distinct recent unfinalized incidents only"
end_test

start_test "closed_pool_counts_incident_not_event"
  # closed = MESHSAT-9001 (417) + IFR-9004 resolved (0) + no-id instant (0) = 3,
  # NOT 5+ (the flap events collapsed to one).
  assert_eq "3" "$(get n_closed)"
end_test

start_test "db_and_log_paths_are_env_overridable"
  assert_contains "$(grep -E 'os.environ.get..GATEWAY_DB' "$REPO_ROOT/scripts/agentic-stats.py")" "GATEWAY_DB"
  assert_contains "$(grep -E 'os.environ.get..TRIAGE_LOG' "$REPO_ROOT/scripts/agentic-stats.py")" "TRIAGE_LOG"
end_test

rm -f "$FIXDB" "$FIXLOG"
