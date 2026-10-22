#!/usr/bin/env bash
# IFRNLLEI01PRD-1100 — approval-poll vote ledger test suite.
#
# Background: the original "how many times did the human vote on approval polls?"
# question had NO clean answer because vote outcomes were never persisted. This
# wires the matrix-bridge to emit a typed `mcp_approval_response` event to
# event_log at the two resolution points: the vote path (Release Lock SSH) and
# the timeout-pause path (Pause Timed Out Session SSH).
#
# Covers: the event type is registered + emits round-trip, the timed_out variant,
# emit-event.py rejects bogus types, the lock-robust connect hardening, and a
# doc-drift lock on the live-exported bridge JSON so a future edit that drops the
# emission wiring FAILS QA. Hermetic: temp GATEWAY_DB, no network.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="1100-approval-vote-ledger"
EMIT="$REPO_ROOT/scripts/emit-event.py"
SE="$REPO_ROOT/scripts/lib/session_events.py"
BRIDGE="$REPO_ROOT/workflows/claude-gateway-matrix-bridge.json"
TESTDB="$(mktemp --suffix=.db)"
trap 'rm -f "$TESTDB"' EXIT

# Hermetic event_log table (matches the live schema; emit needs only this table —
# schema_version.current() is a constant, no DB read).
sqlite3 "$TESTDB" "CREATE TABLE event_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  emitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  issue_id TEXT DEFAULT '',
  session_id TEXT DEFAULT '',
  turn_id INTEGER DEFAULT -1,
  agent_name TEXT DEFAULT '',
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  duration_ms INTEGER DEFAULT -1,
  exit_code INTEGER DEFAULT 0,
  schema_version INTEGER DEFAULT 1
);"

emit() { env GATEWAY_DB="$TESTDB" python3 "$EMIT" "$@"; }
q() { sqlite3 "$TESTDB" "$1"; }

# ─── the event type backing the ledger is registered ─────────────────────────
start_test "event_type_registered_in_session_events"
  src="$(cat "$SE")"
  assert_contains "$src" "class MCPApprovalResponseEvent" "dataclass must exist"
  assert_contains "$src" '"mcp_approval_response"' "must be in EVENT_TYPES"
end_test

# ─── vote emit round-trips with correct payload ──────────────────────────────
start_test "approval_vote_round_trip"
  rid=$(emit --type mcp_approval_response --issue IFRNLLEI01PRD-1046 \
        --session s-vote \
        --payload-json '{"gate_type":"approval_poll","choice":"approved","responder":"@dominicus:matrix.example.net"}')
  assert_gt "$rid" 0 "emit returns a row id"
  assert_eq 1 "$(q "SELECT count(*) FROM event_log WHERE event_type='mcp_approval_response';")"
  assert_eq approved          "$(q "SELECT json_extract(payload_json,'\$.choice') FROM event_log WHERE id=$rid;")"
  assert_eq approval_poll     "$(q "SELECT json_extract(payload_json,'\$.gate_type') FROM event_log WHERE id=$rid;")"
  assert_eq IFRNLLEI01PRD-1046 "$(q "SELECT issue_id FROM event_log WHERE id=$rid;")"
  assert_eq "@dominicus:matrix.example.net" \
            "$(q "SELECT json_extract(payload_json,'\$.responder') FROM event_log WHERE id=$rid;")"
end_test

# ─── timed_out variant (operator never voted → POLL_PAUSE timed out) ──────────
start_test "timed_out_variant"
  rid=$(emit --type mcp_approval_response --issue IFRNLLEI01PRD-900 \
        --payload-json '{"gate_type":"poll","choice":"timed_out","responder":"timeout"}')
  assert_eq timed_out "$(q "SELECT json_extract(payload_json,'\$.choice') FROM event_log WHERE id=$rid;")"
  assert_eq timeout   "$(q "SELECT json_extract(payload_json,'\$.responder') FROM event_log WHERE id=$rid;")"
end_test

# ─── emit-event.py rejects an unknown event type (guards EVENT_TYPES) ─────────
start_test "unknown_event_type_rejected"
  if env GATEWAY_DB="$TESTDB" python3 "$EMIT" --type not_a_real_event \
       --payload-json '{}' >/dev/null 2>&1; then
    fail_test "unknown event_type should exit non-zero"
  fi
end_test

# ─── lock-robust connect (rare votes must not drop on the busy 455MB DB) ──────
start_test "emit_connect_is_lock_robust"
  src="$(cat "$SE")"
  # Lock-robustness lives in the shared _emit_insert (busy_timeout=30000 + WAL-tolerant + retry);
  # emit() + emit_raw() BOTH delegate to it, so the pragma is set once (DRY) and neither opens an
  # un-protected connection. Verify the pragma exists AND both write paths route through it.
  assert_contains "$src" "busy_timeout=30000" "the shared write path needs PRAGMA busy_timeout=30000"
  assert_eq 2 "$(printf '%s' "$src" | grep -c 'return _emit_insert(')" \
    "emit() + emit_raw() must both delegate to the lock-robust _emit_insert"
  assert_not_contains "$src" "sqlite3.connect(DB_PATH, timeout=5)" "legacy 5s timeout must be gone"
end_test

# ─── DOC-DRIFT LOCK: the live-exported bridge must carry the emission wiring ──
# If a future bridge edit drops these, this suite fails — the ledger silently
# stops filling otherwise (the exact failure mode -1100 was created to prevent).
start_test "bridge_release_lock_emits_votes"
  rl=$(python3 -c "import json;d=json.load(open('$BRIDGE'));print(next(n for n in d['nodes'] if n['name']=='Release Lock')['parameters']['command'])")
  assert_contains "$rl" "mcp_approval_response"           "Release Lock must emit the event"
  assert_contains "$rl" "emit-event.py"                   "Release Lock must call the emitter"
  assert_contains "$rl" "voteCmd"                         "Release Lock vote loop"
  assert_contains "$rl" "^POLL RESPONSE:"                 "plan-poll selections must be skipped"
  assert_contains "$rl" "|| true"                         "emit must be non-fatal to lock release"
  assert_contains "$rl" "session_feedback"                "must not clobber the existing feedback write"
end_test

start_test "bridge_pause_emits_timed_out"
  pz=$(python3 -c "import json;d=json.load(open('$BRIDGE'));print(next(n for n in d['nodes'] if n['name']=='Pause Timed Out Session')['parameters']['command'])")
  assert_contains "$pz" "mcp_approval_response"           "Pause must emit the event"
  assert_contains "$pz" '"choice":"timed_out"'            "Pause emits the timed_out outcome"
  assert_contains "$pz" "UPDATE sessions SET paused=1"    "must not clobber the existing pause write"
end_test
