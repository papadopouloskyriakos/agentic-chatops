#!/usr/bin/env bash
# test-1714-wave-c-actuators.sh — safety gates for the Wave-C actuators
# (operator directives #3 disk-grow, #9 judge-calibrate, 2026-07-08). Isolated mktemp DB.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
TMPDIR_T=$(mktemp -d); trap 'rm -rf "$TMPDIR_T"' EXIT
DB="$TMPDIR_T/gw.db"
sqlite3 "$DB" < "$REPO_ROOT/schema.sql" 2>/dev/null

start_test "disk_grow_log_and_registry"
  n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='disk_grow_log'")
  assert_eq 1 "$n" "disk_grow_log in schema.sql"
  reg=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION as C; print(C.get('disk_grow_log',0))")
  assert_eq 1 "$reg" "disk_grow_log in schema_version registry"
end_test

start_test "disk_actuator_disarmed_never_executes"
  # No sentinel in a fake HOME -> even --execute must run ANALYSIS(disarmed), never resize.
  out=$(HOME="$TMPDIR_T" GATEWAY_DB="$DB" python3 "$REPO_ROOT/scripts/remediate-disk-pressure.py" \
        --host nonexistent-host-xyz --execute 2>&1 | tail -1)
  assert_contains "$out" '"mode": "ANALYSIS(disarmed)"' "no sentinel => disarmed even with --execute"
  # and a bogus host resolves-fail without touching anything
  assert_contains "$out" "resolve-failed" "unresolvable host is a safe no-op"
end_test

start_test "judge_calibrate_classifies_scorer_fn_vs_softness"
  sqlite3 "$DB" "
    INSERT INTO session_trajectory (issue_id, graded_at, trajectory_score, steps_completed, steps_expected, tool_calls, turns, has_incident_kb_query, has_react_structure, has_confidence, has_evidence_commands, has_ssh_investigation, has_poll_or_approval, has_netbox_lookup, has_yt_comment) VALUES
      ('T-ACTIVE',  datetime('now'), 62, 5, 8, 25, 40, 0,0,1,1,1,1,1,1),   -- lots of work -> scorer-FN
      ('T-THIN',    datetime('now'), 37, 3, 8,  1,  2, 0,0,0,0,0,1,1,1);   -- barely worked -> genuine-softness
    INSERT INTO session_judgment (issue_id, judged_at, overall_score, safety_compliance, recommended_action, judge_model) VALUES
      ('T-ACTIVE', datetime('now'), 4.8, 5, 'approve', 'gemma3:12b'),
      ('T-THIN',   datetime('now'), 4.6, 5, 'approve', 'gemma3:12b');"
  out=$(GATEWAY_DB="$DB" HOME="$TMPDIR_T" python3 "$REPO_ROOT/scripts/judge-calibrate.py" --analyze 2>&1)
  js=$(echo "$out" | tail -1)
  assert_contains "$js" '"fooled_total": 2' "both synthetic sessions counted fooled"
  assert_contains "$js" '"scorer_false_negative": 1' "the 25-toolcall/40-turn session = scorer-FN"
  assert_contains "$js" '"genuine_softness": 1' "the 1-toolcall/2-turn session = genuine-softness"
  assert_contains "$out" "deliberately NOT performed" "never auto-mutates the rubric"
end_test

start_test "actuators_gated_by_their_own_sentinels"
  grep -q 'gateway.disk_autogrow_armed' "$REPO_ROOT/scripts/remediate-disk-pressure.py"
  assert_eq 0 "$?" "disk actuator reads ~/gateway.disk_autogrow_armed"
  grep -q 'gateway.judge_autocalibrate_armed' "$REPO_ROOT/scripts/judge-calibrate.py"
  assert_eq 0 "$?" "judge actuator reads ~/gateway.judge_autocalibrate_armed"
  # disk actuator must enforce the pool-free floor + rate cap + pmxcfs pre-flight in source
  for tok in "pool_free_pct" "rate-cap-days" "pmxcfs_ok" "rpool_healthy"; do
    grep -q "$tok" "$REPO_ROOT/scripts/remediate-disk-pressure.py"
    assert_eq 0 "$?" "disk actuator enforces $tok"
  done
end_test
