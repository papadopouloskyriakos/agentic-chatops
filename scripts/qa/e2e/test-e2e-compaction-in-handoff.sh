#!/usr/bin/env bash
# E2E — compaction is part of the happy T1→T2 handoff flow.
#
# Scenario: T1 OpenClaw finishes a 50-turn triage → Build Prompt detects the
# envelope is >8KB → compact-handoff-history.py runs via mocked gemma →
# resulting envelope is passed to the T2 Claude (mocked) as HANDOFF_INPUT_DATA_B64.
# Verifies: (a) the compaction event is logged, (b) the envelope marker appears
# in the sub-agent's prompt, (c) handoff_log records compaction_applied=1.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="e2e-compaction-in-handoff"

start_test "t1_to_t2_handoff_with_compaction_end_to_end"
  tmp=$(fresh_db)
  ollama_port=$(python3 "$REPO_ROOT/scripts/qa/lib/mock_http.py" start --behavior=ollama-ok)
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"

  # ── Step 1: T1 produced a 50-turn triage.
  cd "$REPO_ROOT/scripts"
  BIG_B64=$(PYTHONPATH=lib python3 -c "
from handoff import HandoffInputData
env = HandoffInputData(issue_id='E2E-CMP', from_agent='openclaw-t1', to_agent='claude-code-t2',
    input_history=[{'role':'user' if i%2 else 'assistant','content':'turn '+str(i)+' '*500} for i in range(50)])
print(env.to_b64())
")

  # ── Step 2: Compact via mocked gemma.
  SMALL_B64=$(echo "$BIG_B64" | \
    OLLAMA_URL="http://127.0.0.1:$ollama_port" HANDOFF_COMPACT_THRESHOLD=1000 \
    GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/compact-handoff-history.py" \
    --mode auto 2>/tmp/s.$$)
  stats=$(cat /tmp/s.$$); rm -f /tmp/s.$$
  assert_contains "$stats" '"applied": true'

  # ── Step 3: Persist the (compacted) handoff log row.
  echo "$SMALL_B64" | GATEWAY_DB="$tmp" python3 -c "
import sys; sys.path.insert(0,'lib')
from handoff import HandoffInputData
env = HandoffInputData.from_b64(sys.stdin.read().strip())
env.persist_log()
print(env.compaction_applied, env.compaction_model)
" >/tmp/p.$$ 2>&1
  persist_out=$(cat /tmp/p.$$); rm -f /tmp/p.$$
  assert_contains "$persist_out" "True gemma3:12b"

  # ── Step 4: Build the sub-agent call's JSON entirely in Python — avoids
  # shell double-quote + embedded-JSON interactions. The Python helper
  # decodes the compacted envelope dict and wraps it as the `handoff_data`
  # field of the agent_as_tool input.
  call_json=$(mktemp)
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
import json, sys
sys.path.insert(0,'$REPO_ROOT/scripts/lib')
from handoff import HandoffInputData
env = HandoffInputData.from_b64(open('/dev/stdin').read().strip() if False else '''$SMALL_B64''')
req = {
  'agent': 'triage-researcher',
  'prompt': 'proceed',
  'issue_id': 'E2E-CMP',
  'parent_agent': 'openclaw-t1',
  'handoff_data': env.to_dict(),
}
json.dump(req, open('$call_json','w'))
"
  # Invoke agent_as_tool. Use the JSON file as stdin.
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10 \
    < "$call_json" > /tmp/at.$$ 2>&1
  rm -f "$call_json"
  at_out=$(cat /tmp/at.$$); rm -f /tmp/at.$$

  # ── Step 5: Assertions.
  # (a) handoff_compaction event
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_compaction'")
  assert_eq 1 "$n"
  # (b) handoff_log row reflects compaction_applied=1
  ca=$(sqlite3 "$tmp" "SELECT compaction_applied FROM handoff_log WHERE issue_id='E2E-CMP'")
  assert_eq 1 "$ca"
  # (c) agent_as_tool_call event logged
  atc=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='agent_as_tool_call'")
  assert_eq 1 "$atc"
  # (d) The mocked Claude was invoked and captured env+prompt.
  assert_file_exists "$MOCK_CLAUDE_LAST"
  inv=$(cat "$MOCK_CLAUDE_LAST")
  assert_contains "$inv" "HANDOFF_INPUT_DATA_B64="
  # (e) The prompt contains the compaction marker.
  assert_contains "$inv" "COMPACTED by gemma3:12b"

  python3 "$REPO_ROOT/scripts/qa/lib/mock_http.py" stop "$ollama_port"
  unset_mock_claude
  cleanup_db "$tmp"
end_test
