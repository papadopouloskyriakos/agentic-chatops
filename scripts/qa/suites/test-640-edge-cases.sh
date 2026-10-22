#!/usr/bin/env bash
# IFRNLLEI01PRD-640 — HandoffInputData edge cases + column verification.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="640-edge-cases"

start_test "input_history_bytes_is_length_of_json"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
import json
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='a', to_agent='b',
    input_history=[{'role':'user','content':'hello'}])
print(env.input_history_bytes(), len(json.dumps(env.input_history)))
")
  a=$(echo "$out" | awk '{print $1}')
  b=$(echo "$out" | awk '{print $2}')
  assert_eq "$a" "$b"
end_test

start_test "handoff_log_captures_pre_and_new_counts"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  echo '{"input_history":[{"role":"u","content":"h"}],"pre_handoff_items":["a","b","c"],"new_items":["d","e"],"run_context":{}}' \
    | GATEWAY_DB="$tmp" python3 -m lib.handoff pack --issue Q --from P --to C --persist >/dev/null
  out=$(sqlite3 "$tmp" "SELECT pre_handoff_count, new_items_count FROM handoff_log WHERE issue_id='Q'")
  assert_eq "3|2" "$out"
end_test

start_test "handoff_log_compaction_flag_off_by_default"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  echo '{"input_history":[],"pre_handoff_items":[],"new_items":[],"run_context":{}}' \
    | GATEWAY_DB="$tmp" python3 -m lib.handoff pack --issue Q-C --from P --to C --persist >/dev/null
  out=$(sqlite3 "$tmp" "SELECT compaction_applied FROM handoff_log WHERE issue_id='Q-C'")
  assert_eq "0" "$out"
end_test

start_test "to_dict_includes_all_fields"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from handoff import HandoffInputData
d = HandoffInputData(issue_id='X', from_agent='a', to_agent='b').to_dict()
for k in ('issue_id','session_id','from_agent','to_agent','handoff_depth','handoff_chain','input_history','pre_handoff_items','new_items','run_context','compaction_applied','compaction_model','reason','envelope_version'):
    assert k in d, k
print('ok')
")
  assert_eq "ok" "$out"
end_test

start_test "from_b64_rejects_garbage"
  cd "$REPO_ROOT/scripts"
  rc=0
  err=$(PYTHONPATH=lib python3 -c "
from handoff import HandoffInputData
HandoffInputData.from_b64('this-is-not-valid-base64-or-anything-decompressable')
" 2>&1) || rc=$?
  assert_eq 1 "$rc"
end_test

start_test "section_includes_run_context_block"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='a', to_agent='b',
    run_context={'usage':{'tokens':1234},'tier':'T1'})
print(env.as_prompt_section())
")
  assert_contains "$out" "Inherited run_context"
  assert_contains "$out" '"tokens": 1234'
end_test

start_test "section_empty_history_omits_transcript_block"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='a', to_agent='b')
print(env.as_prompt_section())
")
  assert_not_contains "$out" "Prior transcript"
end_test

start_test "compaction_flag_flow_through"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='a', to_agent='b', compaction_applied=True, compaction_model='gemma3:12b')
b64 = env.to_b64()
restored = HandoffInputData.from_b64(b64)
print(restored.compaction_applied, restored.compaction_model)
")
  assert_contains "$out" "True gemma3:12b"
end_test
