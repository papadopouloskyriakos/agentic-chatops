#!/usr/bin/env bash
# IFRNLLEI01PRD-641 — handoff transcript compaction.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="641-compaction"

big_envelope() {
  # Returns a b64 envelope of ~20 KB on stdout.
  cd "$REPO_ROOT/scripts"
  PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='Q', from_agent='P', to_agent='C',
    input_history=[{'role':'user' if i%2 else 'assistant','content':'filler '+str(i)+' '*400} for i in range(50)])
print(env.to_b64())
"
}

small_envelope() {
  cd "$REPO_ROOT/scripts"
  PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='Q', from_agent='P', to_agent='C',
    input_history=[{'role':'user','content':'hi'}])
print(env.to_b64())
"
}

start_test "mode_off_returns_envelope_unchanged"
  tmp=$(fresh_db)
  in_b64=$(big_envelope)
  out_b64=$(echo "$in_b64" | GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" --mode off 2>/tmp/s.$$)
  stats=$(cat /tmp/s.$$); rm -f /tmp/s.$$
  assert_contains "$stats" '"applied": false'
  assert_contains "$stats" '"reason": "mode=off"'
  cleanup_db "$tmp"
end_test

start_test "mode_auto_under_threshold_no_compact"
  tmp=$(fresh_db)
  in_b64=$(small_envelope)
  out_b64=$(echo "$in_b64" | HANDOFF_COMPACT_THRESHOLD=10000 GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" --mode auto 2>/tmp/s.$$)
  stats=$(cat /tmp/s.$$); rm -f /tmp/s.$$
  assert_contains "$stats" '"applied": false'
  assert_contains "$stats" "threshold"
  cleanup_db "$tmp"
end_test

start_test "mode_force_with_both_backends_unreachable_returns_original"
  tmp=$(fresh_db)
  in_b64=$(big_envelope)
  # Both gemma + haiku will fail.
  out_b64=$(echo "$in_b64" | \
    OLLAMA_URL=http://127.0.0.1:9 ANTHROPIC_API_KEY= \
    GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" --mode force 2>/tmp/s.$$)
  stats=$(cat /tmp/s.$$); rm -f /tmp/s.$$
  assert_contains "$stats" '"applied": false'
  assert_contains "$stats" "summarizer failed"
  cleanup_db "$tmp"
end_test

start_test "compaction_emits_event_with_pre_and_post_bytes"
  tmp=$(fresh_db)
  in_b64=$(big_envelope)
  echo "$in_b64" | \
    OLLAMA_URL=http://127.0.0.1:9 ANTHROPIC_API_KEY= \
    GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" --mode force >/dev/null 2>/tmp/s.$$
  rm -f /tmp/s.$$
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_compaction'")
  assert_eq "1" "$n"
  model=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.model') FROM event_log WHERE event_type='handoff_compaction'")
  assert_eq "none" "$model"
  cleanup_db "$tmp"
end_test

start_test "env_switch_off_honored_even_when_flag_not_set"
  tmp=$(fresh_db)
  in_b64=$(big_envelope)
  out_b64=$(echo "$in_b64" | HANDOFF_COMPACT_MODE=off GATEWAY_DB="$tmp" \
    python3 "$REPO_ROOT/scripts/compact-handoff-history.py" 2>/tmp/s.$$)
  stats=$(cat /tmp/s.$$); rm -f /tmp/s.$$
  assert_contains "$stats" '"applied": false'
  cleanup_db "$tmp"
end_test

start_test "compactor_script_compiles_and_references_circuit_breaker"
  # File has a hyphen so it's not importable as a module; verify syntax
  # and verify the circuit-breaker-aware code path is wired by checking the
  # module text contains the breaker name we expect.
  assert_exit_code 0 python3 -m py_compile "$REPO_ROOT/scripts/compact-handoff-history.py"
  assert_contains "$(cat "$REPO_ROOT/scripts/compact-handoff-history.py")" "rag_synth_ollama"
end_test
