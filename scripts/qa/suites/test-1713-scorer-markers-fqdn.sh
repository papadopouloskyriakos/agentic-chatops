#!/usr/bin/env bash
# test-1713-scorer-markers-fqdn.sh — trajectory-scorer marker widening (kill judge-fooled
# false-negatives) + autocloser LibreNMS FQDN fallback (IFRNLLEI01PRD-1713 + -1472, 2026-07-08).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
TMPDIR_T=$(mktemp -d); trap 'rm -rf "$TMPDIR_T"' EXIT
DB="$TMPDIR_T/gw.db"
sqlite3 "$DB" < "$REPO_ROOT/schema.sql" 2>/dev/null

start_test "backfill_raises_mcp_investigation_session_over_75"
  # A session that investigated via MCP tools but the old grep scored 5/8=62 (fooled).
  sqlite3 "$DB" "
    INSERT INTO session_trajectory (issue_id, graded_at, trajectory_score, steps_completed, steps_expected, tool_calls, turns,
      has_netbox_lookup, has_incident_kb_query, has_react_structure, has_poll_or_approval, has_confidence,
      has_evidence_commands, has_ssh_investigation, has_yt_comment) VALUES
      ('T-MCP', datetime('now'), 62, 5, 8, 20, 30, 1,0,0,1,1,0,0,1);
    INSERT INTO tool_call_log (issue_id, tool_name) VALUES
      ('T-MCP','mcp__kubernetes__kubectl_get'),('T-MCP','mcp__kubernetes__kubectl_describe'),
      ('T-MCP','Bash'),('T-MCP','mcp__youtrack__add_comment');"
  GATEWAY_DB="$DB" python3 "$REPO_ROOT/scripts/backfill-trajectory-markers.py" >/dev/null 2>&1
  sc=$(sqlite3 "$DB" "SELECT trajectory_score FROM session_trajectory WHERE issue_id='T-MCP'")
  assert_ge "$sc" 75 "MCP-investigation session raised to >=75 (no longer judge-fooled)"
  kb=$(sqlite3 "$DB" "SELECT has_incident_kb_query FROM session_trajectory WHERE issue_id='T-MCP'")
  assert_eq 1 "$kb" "auto-injected KB credited for an infra session that investigated"
end_test

start_test "backfill_never_raises_a_genuinely_thin_session"
  sqlite3 "$DB" "INSERT INTO session_trajectory (issue_id, graded_at, trajectory_score, steps_completed, steps_expected, tool_calls, turns,
      has_netbox_lookup, has_incident_kb_query, has_react_structure, has_poll_or_approval, has_confidence,
      has_evidence_commands, has_ssh_investigation, has_yt_comment) VALUES
      ('T-THIN', datetime('now'), 25, 2, 8, 1, 2, 0,0,1,0,1,0,0,0);"
  GATEWAY_DB="$DB" python3 "$REPO_ROOT/scripts/backfill-trajectory-markers.py" >/dev/null 2>&1
  sc=$(sqlite3 "$DB" "SELECT trajectory_score FROM session_trajectory WHERE issue_id='T-THIN'")
  assert_lt "$sc" 75 "thin session (1 tool call, no investigation tools) stays < 75"
  assert_eq 25 "$sc" "thin session score unchanged (raise-only, no false credit)"
end_test

start_test "scorer_source_is_mcp_aware_and_toollog_based"
  grep -q "tool_call_log" "$REPO_ROOT/scripts/score-trajectory.sh"
  assert_eq 0 "$?" "score-trajectory.sh reads tool_call_log (persistent evidence)"
  grep -qE "kubernetes\|proxmox\|kubectl\|exec_in_pod" "$REPO_ROOT/scripts/score-trajectory.sh"
  assert_eq 0 "$?" "score-trajectory.sh matches MCP investigation tools"
end_test

start_test "autocloser_fqdn_fallback_forms"
  out=$(python3 - "$REPO_ROOT" <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("ac", __import__('sys').argv[1] + "/scripts/alert-yt-autoclose.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# _ln_device tries short, then FQDN forms; assert domains configured + helper exists
ok = hasattr(m, "_ln_device") and "example.net" in ",".join(m._LN_DOMAINS)
print("OK" if ok else "FAIL")
PY
)
  assert_contains "$out" "OK" "autocloser has _ln_device with example.net FQDN fallback"
end_test
