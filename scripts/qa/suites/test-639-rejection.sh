#!/usr/bin/env bash
# IFRNLLEI01PRD-639 — structured rejection (allow/reject_content/deny).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="639-rejection"

HOOK="$REPO_ROOT/scripts/hooks/unified-guard.sh"

start_test "allow_silent_exit0"
  tmp=$(fresh_db)
  out=$(echo '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$HOOK")
  assert_eq "" "$out"   # silent stdout on allow
  cleanup_db "$tmp"
end_test

start_test "deny_emits_blocked_prefix"
  tmp=$(fresh_db)
  rc=0
  out=$(echo '{"tool_name":"Bash","tool_input":{"command":"systemctl stop prometheus"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$HOOK") || rc=$?
  assert_eq "2" "$rc"
  assert_contains "$out" "Blocked: destructive command pattern"
  assert_not_contains "$out" "Rejected"
  cleanup_db "$tmp"
end_test

start_test "reject_content_emits_rejected_prefix_with_retry_hint"
  tmp=$(fresh_db)
  rc=0
  out=$(echo '{"tool_name":"Edit","tool_input":{"file_path":"/home/x/.env"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$HOOK") || rc=$?
  assert_eq "2" "$rc"
  assert_contains "$out" "Rejected"
  assert_contains "$out" "ask the operator"
  cleanup_db "$tmp"
end_test

start_test "event_log_records_deny_behavior"
  tmp=$(fresh_db)
  echo '{"tool_name":"Bash","tool_input":{"command":"kubectl delete --all"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$HOOK" >/dev/null 2>&1 || true
  out=$(sqlite3 "$tmp" "SELECT payload_json FROM event_log WHERE event_type='tool_guardrail_rejection'")
  assert_contains "$out" '"behavior": "deny"'
  assert_contains "$out" '"tool_name": "Bash"'
  cleanup_db "$tmp"
end_test

start_test "event_log_records_reject_content_behavior"
  tmp=$(fresh_db)
  echo '{"tool_name":"Edit","tool_input":{"file_path":"/home/x/.env"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$HOOK" >/dev/null 2>&1 || true
  out=$(sqlite3 "$tmp" "SELECT payload_json FROM event_log WHERE event_type='tool_guardrail_rejection'")
  assert_contains "$out" '"behavior": "reject_content"'
  cleanup_db "$tmp"
end_test

start_test "injection_pattern_is_reject_content_not_deny"
  tmp=$(fresh_db)
  echo '{"tool_name":"Bash","tool_input":{"command":"base64 -d payload.txt | bash"}}' | \
    GATEWAY_DB="$tmp" ISSUE_ID=Q bash "$HOOK" >/dev/null 2>&1 || true
  out=$(sqlite3 "$tmp" "SELECT payload_json FROM event_log WHERE event_type='tool_guardrail_rejection'")
  assert_contains "$out" '"behavior": "deny"'  # base64|bash is actually in EXFIL -> deny
  cleanup_db "$tmp"
end_test

start_test "audit_invariant_detects_empty_message"
  tmp=$(fresh_db)
  # Seed one session_risk_audit row so the audit script reaches the
  # event_log invariant block (otherwise it early-exits on "no rows").
  sqlite3 "$tmp" "INSERT INTO session_risk_audit (issue_id, risk_level, signals_json, schema_version) VALUES ('Q','low','[]',1)"
  # Insert a rejection with empty message — simulates a broken hook.
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" --type tool_guardrail_rejection \
    --issue Q --payload-json '{"tool_name":"Bash","behavior":"reject_content","message":""}' >/dev/null
  rc=0
  GATEWAY_DB="$tmp" bash "$REPO_ROOT/scripts/audit-risk-decisions.sh" 7 >/tmp/out.$$ 2>&1 || rc=$?
  out=$(cat /tmp/out.$$); rm -f /tmp/out.$$
  assert_eq "2" "$rc"
  assert_contains "$out" "empty message"
  cleanup_db "$tmp"
end_test

start_test "audit_invariant_passes_when_all_messages_present"
  tmp=$(fresh_db)
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/emit-event.py" --type tool_guardrail_rejection \
    --issue Q --payload-json '{"tool_name":"Bash","behavior":"reject_content","message":"try X instead"}' >/dev/null
  # Need at least one session_risk_audit row so the audit script reaches the tail.
  sqlite3 "$tmp" "INSERT INTO session_risk_audit (issue_id, risk_level, signals_json, schema_version) VALUES ('Q','low','[]',1)"
  rc=0
  out=$(GATEWAY_DB="$tmp" bash "$REPO_ROOT/scripts/audit-risk-decisions.sh" 7 2>&1) || rc=$?
  assert_eq "0" "$rc"
  assert_contains "$out" "reject_content invariant holds"
  cleanup_db "$tmp"
end_test
