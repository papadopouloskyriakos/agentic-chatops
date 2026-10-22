#!/usr/bin/env bash
# IFRNLLEI01PRD-640 — HandoffInputData envelope.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="640-handoff-envelope"

start_test "handoff_log_table_exists"
  tmp=$(fresh_db)
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='handoff_log'")
  assert_eq 1 "$n"
  cleanup_db "$tmp"
end_test

start_test "pack_unpack_round_trip"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  B64=$(echo '{"input_history":[{"role":"user","content":"hi"}],"pre_handoff_items":["x"],"new_items":[],"run_context":{"u":1}}' \
    | GATEWAY_DB="$tmp" python3 -m lib.handoff pack --issue Q --from P --to C --session s --depth 1 --chain '["P","C"]')
  assert_gt "${#B64}" 50
  OUT=$(echo "$B64" | GATEWAY_DB="$tmp" python3 -m lib.handoff unpack)
  assert_contains "$OUT" '"from_agent":"P"'
  assert_contains "$OUT" '"to_agent":"C"'
  assert_contains "$OUT" '"input_history":[{"content":"hi","role":"user"}]'
  cleanup_db "$tmp"
end_test

start_test "persist_flag_writes_handoff_log"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  echo '{"input_history":[],"pre_handoff_items":[],"new_items":[]}' \
    | GATEWAY_DB="$tmp" python3 -m lib.handoff pack --issue Q-L --from P --to C --persist >/dev/null
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM handoff_log WHERE issue_id='Q-L'")
  assert_eq "1" "$n"
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM handoff_log WHERE issue_id='Q-L'")
  assert_eq "1" "$sv"
  cleanup_db "$tmp"
end_test

start_test "compression_ratio_below_10pct_on_large_payload"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='a', to_agent='b',
    input_history=[{'role':'user','content':'repeat '*500} for _ in range(50)])
raw = env.to_json()
b64 = env.to_b64()
print(len(raw), len(b64))
")
  raw=$(echo "$out" | awk '{print $1}')
  b64=$(echo "$out" | awk '{print $2}')
  ratio=$(python3 -c "print($b64/$raw)")
  assert_lt "$ratio" "0.10"
end_test

start_test "section_render_truncates_history"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='P', to_agent='C',
    input_history=[{'role':'assistant','content':'m'+str(i)} for i in range(100)])
print(env.as_prompt_section(max_history_items=5))
")
  # Exactly 5 numbered history lines expected. Backticks don't need escaping
  # inside the regex — single quotes in bash already pass them through literally.
  n=$(printf '%s\n' "$out" | grep -cE '^- `\[[0-9]+\]`' || true)
  assert_eq "5" "$n"
end_test

start_test "from_env_returns_none_when_unset"
  cd "$REPO_ROOT/scripts"
  out=$(env -u HANDOFF_INPUT_DATA_B64 PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "from handoff import from_env; print(from_env())")
  assert_eq "None" "$out"
end_test

start_test "from_b64_fails_fast_on_future_envelope_version"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 env PYTHONPATH="$REPO_ROOT/scripts/lib" python3 -c "
import json, zlib, base64
from handoff import HandoffInputData
data = {'issue_id':'X','from_agent':'a','to_agent':'b','envelope_version':99}
b64 = base64.urlsafe_b64encode(zlib.compress(json.dumps(data).encode())).decode()
HandoffInputData.from_b64(b64)
"
  assert_contains "$_qa_last_stderr" "envelope_version"
end_test
