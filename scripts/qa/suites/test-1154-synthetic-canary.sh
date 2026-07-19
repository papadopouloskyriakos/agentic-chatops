#!/usr/bin/env bash
# IFRNLLEI01PRD-1154 — synthetic-incident end-to-end canary.
# Validates the classify->predict spine against an ISOLATED temp DB so it can
# never pollute the live tables, collide a real session's fail-closed gate, or
# trigger real remediation. CI-safe: static contract + (if the spine + sqlite3
# are present) a real isolated run asserting 3/3 stages and zero live leak.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1154-synthetic-canary"

C="$REPO_ROOT/scripts/synthetic-incident-canary.sh"

start_test "canary_syntax_ok"
  assert_eq "PASS" "$(bash -n "$C" 2>/dev/null && echo PASS || echo FAIL)"
end_test

start_test "isolated_db_design_present"
  # the safety contract: a throwaway mktemp DB, seeded from schema.sql, cleaned
  # via trap; the spine is pointed at it via GATEWAY_DB/--db, never the live DB.
  has_mktemp=$(grep -cE 'CANARY_DB="\$\(mktemp' "$C")
  has_seed=$(grep -cE 'sqlite3 "\$CANARY_DB" < "\$REPO/schema.sql"' "$C")
  has_trap=$(grep -cE 'trap cleanup EXIT' "$C")
  has_isolation=$(grep -cE 'GATEWAY_DB="\$CANARY_DB"' "$C")
  assert_eq "1 1 1" "$([ "$has_mktemp" -ge 1 ] && echo 1 || echo 0) $([ "$has_seed" -ge 1 ] && echo 1 || echo 0) $([ "$has_trap" -ge 1 ] && [ "$has_isolation" -ge 1 ] && echo 1 || echo 0)"
end_test

start_test "read_only_plan_no_remediation"
  # the synthetic PLAN JSON must carry no "awx_templates" key (the awx-runbooks
  # signal forces POLL and is a remediation marker). Quoted-key match so the
  # safety comment that says "no awx_templates" doesn't false-trip.
  assert_eq "OK" "$(grep -qE '"awx_templates"' "$C" && echo BAD || echo OK)"
end_test

start_test "emits_leak_guard_and_stage_metrics"
  for m in synthetic_incident_canary_stage_ok synthetic_incident_canary_stages_passed \
           synthetic_incident_canary_live_db_leak synthetic_incident_canary_last_run_timestamp; do
    grep -q "$m" "$C" || { echo "MISSING $m"; break; }
  done
  assert_eq "OK" "$(for m in synthetic_incident_canary_stage_ok synthetic_incident_canary_stages_passed synthetic_incident_canary_live_db_leak synthetic_incident_canary_last_run_timestamp; do grep -q "$m" "$C" || { echo MISSING; exit; }; done; echo OK)"
end_test

start_test "isolated_run_passes_3_stages_zero_leak_when_spine_present"
  # Only runs where the spine + sqlite3 exist (local host). In bare CI it SKIPs.
  if command -v sqlite3 >/dev/null 2>&1 && [ -f "$REPO_ROOT/scripts/classify-session-risk.py" ] && [ -f "$REPO_ROOT/schema.sql" ]; then
    out=$(SYNTHETIC_CANARY_OUT="$(mktemp)" bash "$C" --verbose 2>&1 | grep -oE 'stages_passed=[0-9]+/3 .* leak=[0-9]+' | tail -1)
    assert_eq "stages_passed=3/3" "$(echo "$out" | grep -oE 'stages_passed=3/3')"
    assert_eq "leak=0" "$(echo "$out" | grep -oE 'leak=[0-9]+')"
  else
    skip_test "spine/sqlite3 not present (bare CI)"
  fi
end_test
