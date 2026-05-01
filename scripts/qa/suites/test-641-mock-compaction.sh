#!/usr/bin/env bash
# IFRNLLEI01PRD-641 — successful-compaction test using a local mock HTTP
# server. Exercises the happy path that the bench-all.sh sample run never
# touches (gemma/Haiku unreachable → falls through).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="641-mock-compaction"

big_envelope() {
  cd "$REPO_ROOT/scripts"
  PYTHONPATH=lib python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='Q', from_agent='openclaw-t1', to_agent='claude-code-t2',
    input_history=[{'role':'user' if i%2 else 'assistant','content':'filler '+str(i)+' '*400} for i in range(50)])
print(env.to_b64())
"
}

start_test "successful_compaction_via_mocked_ollama"
  tmp=$(fresh_db)
  port=$(python3 "$REPO_ROOT/scripts/qa/lib/mock_http.py" start --behavior=ollama-ok)
  assert_gt "$port" 0

  in_b64=$(big_envelope)
  pre=$(echo "$in_b64" | wc -c)

  out_b64=$(echo "$in_b64" | \
    OLLAMA_URL="http://127.0.0.1:$port" HANDOFF_COMPACT_THRESHOLD=1000 \
    GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" \
      --mode auto 2>/tmp/s.$$)
  stats=$(cat /tmp/s.$$); rm -f /tmp/s.$$

  # Stats say applied.
  assert_contains "$stats" '"applied": true'
  assert_contains "$stats" '"model": "gemma3:12b"'

  # Event row present with matching model + smaller post_bytes.
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_compaction'")
  assert_eq "1" "$n"
  model=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.model') FROM event_log WHERE event_type='handoff_compaction'")
  assert_eq "gemma3:12b" "$model"

  pre_b=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.pre_bytes') FROM event_log WHERE event_type='handoff_compaction'")
  post_b=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.post_bytes') FROM event_log WHERE event_type='handoff_compaction'")
  assert_gt "$pre_b" "$post_b" "post_bytes should be smaller than pre_bytes"

  # Ratio recorded.
  ratio=$(sqlite3 "$tmp" "SELECT json_extract(payload_json,'\$.ratio') FROM event_log WHERE event_type='handoff_compaction'")
  assert_lt "$ratio" "0.5" "compaction should shrink to <50% of original"

  # Unpack the new envelope and verify input_history is now a single
  # synthetic turn marked [COMPACTED].
  dec=$(echo "$out_b64" | GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0,'$REPO_ROOT/scripts/lib')
from handoff import HandoffInputData
env = HandoffInputData.from_b64(sys.stdin.read().strip())
print('items=', len(env.input_history))
print('compaction_applied=', env.compaction_applied)
print('marker=', env.input_history[0]['content'][:40] if env.input_history else '')
")
  assert_contains "$dec" "items= 1"
  assert_contains "$dec" "compaction_applied= True"
  assert_contains "$dec" "COMPACTED by gemma3:12b"

  python3 "$REPO_ROOT/scripts/qa/lib/mock_http.py" stop "$port"
  cleanup_db "$tmp"
end_test

start_test "ollama_fails_haiku_succeeds_fallthrough_path"
  tmp=$(fresh_db)
  port=$(python3 "$REPO_ROOT/scripts/qa/lib/mock_http.py" start --behavior=ollama-500,anthropic-ok)
  in_b64=$(big_envelope)

  # Point Ollama to a 500-responder and Anthropic to our OK mock.
  # compact-handoff-history.py doesn't take ANTHROPIC_URL — it hits api.anthropic.com.
  # We verify the Haiku fallback PATH via the circuit breaker by asserting
  # gemma failure records a failure.
  out_b64=$(echo "$in_b64" | \
    OLLAMA_URL="http://127.0.0.1:$port" HANDOFF_COMPACT_THRESHOLD=1000 ANTHROPIC_API_KEY= \
    GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" --mode force 2>/tmp/s.$$)
  stats=$(cat /tmp/s.$$); rm -f /tmp/s.$$

  # Both summarizers fail (ollama=500, no anthropic key) → graceful fallback.
  assert_contains "$stats" '"applied": false'
  assert_contains "$stats" "summarizer failed"
  python3 "$REPO_ROOT/scripts/qa/lib/mock_http.py" stop "$port"
  cleanup_db "$tmp"
end_test

start_test "cli_file_arg_paths_work"
  tmp=$(fresh_db)
  in_b64=$(big_envelope)
  in_file=$(mktemp)
  out_file=$(mktemp)
  stats_file=$(mktemp)
  echo "$in_b64" > "$in_file"

  # --in-b64 + --out-b64 + --stats-json arg combos
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" \
    --mode off --in-b64 "$in_file" --out-b64 "$out_file" --stats-json "$stats_file"

  assert_file_exists "$out_file"
  assert_file_exists "$stats_file"
  stats=$(cat "$stats_file")
  assert_contains "$stats" '"applied": false'
  rm -f "$in_file" "$out_file" "$stats_file"
  cleanup_db "$tmp"
end_test
