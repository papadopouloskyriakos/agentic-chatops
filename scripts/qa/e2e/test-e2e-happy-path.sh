#!/usr/bin/env bash
# E2E — complete happy-path session: SessionStart -> HandoffInputData carry
# from T1 to T2 -> 3 tool calls (snapshots + event_log + turn_counter) ->
# 1 guarded reject_content -> agent-as-tool sub-agent (with mocked spawn) ->
# end turn.
#
# Verifies all 9 improvements interact correctly in a single flow.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="e2e-happy-path"
tmp=$(fresh_db)

start_test "session_lifecycle_produces_expected_audit_trail"
  ISSUE="QA-E2E-HP"
  SESSION="sess-e2e-happy"
  export GATEWAY_DB="$tmp"
  export ISSUE_ID="$ISSUE"
  export CLAUDE_SESSION_ID="$SESSION"

  # ── Phase 1: T1 -> T2 handoff with HandoffInputData envelope ────────────
  cd "$REPO_ROOT/scripts"
  B64=$(echo '{"input_history":[{"role":"user","content":"pve01 is down"},{"role":"assistant","content":"checked netbox; 192.168.181.x"}],"pre_handoff_items":["netbox lookup"],"new_items":[],"run_context":{"tier":"T1"}}' \
    | python3 -m lib.handoff pack --issue "$ISSUE" --from openclaw-t1 --to claude-code-t2 --session "$SESSION" --depth 1 --chain '["openclaw-t1","claude-code-t2"]' --persist)
  assert_gt "${#B64}" 100

  # Depth bump (T2 joined):
  python3 -c "
import sys; sys.path.insert(0,'lib')
from handoff_depth import bump
bump('$ISSUE','openclaw-t1','claude-code-t2', session_id='$SESSION')
" >/dev/null 2>&1

  # ── Phase 2: session-start hook seeds turn 0 + emits agent_updated ──────
  echo "{\"session_id\":\"$SESSION\",\"source\":\"resume\"}" | \
    bash "$REPO_ROOT/scripts/hooks/session-start.sh"

  # ── Phase 3: 3 tool calls (pre-snapshot + post-event + turn_counter) ────
  for i in 1 2 3; do
    export TURN_ID=$i
    python3 -m lib.turn_counter begin --issue "$ISSUE" --session "$SESSION" --turn "$i" >/dev/null

    # Snapshot pre-tool
    echo '{"tool_name":"Bash","tool_input":{"command":"kubectl get pods -n kube-system"}}' | \
      bash "$REPO_ROOT/scripts/hooks/snapshot-pre-tool.sh"

    # Emit tool_started, tool_ended
    "$REPO_ROOT/scripts/emit-event.py" --type tool_started \
      --issue "$ISSUE" --session "$SESSION" --turn "$i" \
      --payload-json '{"tool_name":"Bash","tool_use_id":"t'$i'"}' >/dev/null

    echo '{"tool_name":"Bash","tool_use_id":"t'$i'","is_error":false,"output_size":500}' | \
      bash "$REPO_ROOT/scripts/hooks/post-tool-use.sh"

    # End the turn
    python3 -m lib.turn_counter end --session "$SESSION" --turn "$i" \
      --cost 0.05 --input-tokens 500 --output-tokens 100 --duration-ms 1200 >/dev/null
  done

  # ── Phase 4: one reject_content (edit .env) ──────────────────────────────
  TURN_ID=4
  export TURN_ID
  echo '{"tool_name":"Edit","tool_input":{"file_path":"/home/x/.env"}}' | \
    bash "$REPO_ROOT/scripts/hooks/unified-guard.sh" >/dev/null 2>&1 || true

  # ── Phase 5: agent-as-tool sub-agent via mocked Claude CLI ───────────────
  make_mock_claude
  export CLAUDE_BIN="$MOCK_CLAUDE_BIN"
  SUB_B64=$(echo '{"input_history":[{"role":"assistant","content":"k8s issue"}],"pre_handoff_items":[],"new_items":[],"run_context":{}}' \
    | python3 -m lib.handoff pack --issue "$ISSUE" --from claude-code-t2 --to k8s-diagnostician --depth 2 --chain '["openclaw-t1","claude-code-t2","k8s-diagnostician"]')
  echo '{"agent":"k8s-diagnostician","prompt":"investigate the k8s pods","issue_id":"'$ISSUE'","parent_agent":"claude-code-t2"}' | \
    "$REPO_ROOT/scripts/agent_as_tool.py" call --timeout 10 >/tmp/at.$$ 2>&1 || true
  at_out=$(cat /tmp/at.$$); rm -f /tmp/at.$$
  unset_mock_claude

  # ── Assertions: audit trail completeness ────────────────────────────────
  # event_log should have: agent_updated (1) + tool_started (3) + tool_ended (3) + tool_guardrail_rejection (1) + handoff_requested (>=2) + agent_as_tool_call (1)
  agent_upd=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='agent_updated'")
  tool_start=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='tool_started'")
  tool_end=$(sqlite3 "$tmp"   "SELECT COUNT(*) FROM event_log WHERE event_type='tool_ended'")
  rej=$(sqlite3 "$tmp"         "SELECT COUNT(*) FROM event_log WHERE event_type='tool_guardrail_rejection'")
  handoffs=$(sqlite3 "$tmp"    "SELECT COUNT(*) FROM event_log WHERE event_type='handoff_requested'")
  at_call=$(sqlite3 "$tmp"     "SELECT COUNT(*) FROM event_log WHERE event_type='agent_as_tool_call'")

  assert_ge "$agent_upd" 1 "agent_updated count"
  assert_eq "3" "$tool_start" "tool_started count"
  assert_eq "3" "$tool_end" "tool_ended count"
  assert_eq "1" "$rej" "rejection count"
  assert_ge "$handoffs" 2 "handoff_requested count (expected >=2)"
  assert_eq "1" "$at_call" "agent_as_tool_call count"

  # session_turns: should have 4 rows (turn 0 seeded by session-start + turns 1-3)
  turns=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_turns WHERE session_id='$SESSION'")
  assert_ge "$turns" 3 "session_turns count"

  # session_state_snapshot: 3 rows (one per mutating Bash tool call)
  snaps=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_state_snapshot WHERE issue_id='$ISSUE'")
  assert_eq "3" "$snaps" "snapshots for 3 Bash tool calls"

  # handoff_log: 1 row from pack --persist
  hl=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM handoff_log WHERE issue_id='$ISSUE'")
  assert_ge "$hl" 1 "handoff_log rows"

  # sessions.handoff_depth should reflect 2 bumps (openclaw-t1->t2 from bump, plus t2->k8s from agent_as_tool)
  depth=$(sqlite3 "$tmp" "SELECT handoff_depth FROM sessions WHERE issue_id='$ISSUE'")
  assert_ge "$depth" 2 "final handoff_depth"

  # Every row carries the table's CURRENT_SCHEMA_VERSION (registry-driven, so a
  # bump on any table — e.g. event_log v=4 after the NVIDIA P0+P1 batch — does
  # not silently regress this assertion).
  for t in sessions event_log session_turns session_state_snapshot handoff_log; do
    expected=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION as V; print(V['$t'])")
    nulls=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM $t WHERE schema_version IS NULL OR schema_version != $expected")
    assert_eq "0" "$nulls" "$t rows have schema_version=$expected"
  done
end_test

cleanup_db "$tmp"
