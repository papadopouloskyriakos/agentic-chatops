#!/usr/bin/env bash
# IFRNLLEI01PRD-751 — Server-side session-replay endpoint (G4.P1.4).
#
# Offline tests. Asserts library + workflow file invariants. Live webhook
# round-trip is exercised in the certification phase (Phase 3 — live e2e).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="751-session-replay"
WF="$REPO_ROOT/workflows/claude-gateway-session-replay.json"

# ─── T1 workflow file exists in repo ───────────────────────────────────────
start_test "workflow_file_in_repo"
  if [ ! -f "$WF" ]; then
    fail_test "missing $WF — export with `n8n_get_workflow lJEGboDYLmx25kBo` and commit"
  fi
end_test

# ─── T2 workflow JSON parses ───────────────────────────────────────────────
start_test "workflow_json_parses"
  if [ -f "$WF" ] && python3 -c "import json; json.load(open('$WF'))" 2>/dev/null; then
    :
  else
    fail_test "JSON parse failed"
  fi
end_test

# ─── T3 workflow has webhook node with path 'session-replay' ──────────────
start_test "workflow_has_session_replay_path"
  if [ ! -f "$WF" ]; then skip_test "no workflow file"
  else
    out=$(python3 - <<PY 2>/dev/null
import json
d = json.load(open("$WF"))
nodes = d.get("nodes", [])
hooks = [n for n in nodes if n.get("type") == "n8n-nodes-base.webhook"]
paths = [n.get("parameters",{}).get("path","") for n in hooks]
print(",".join(paths))
PY
)
    assert_contains "$out" "session-replay" "webhook path missing"
  fi
end_test

# ─── T4 SessionReplayInvokedEvent registered in EVENT_TYPES ───────────────
start_test "event_type_registered"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.session_events import EVENT_TYPES; print(','.join(EVENT_TYPES))")
  assert_contains "$out" "session_replay_invoked" "session_replay_invoked not in EVENT_TYPES"
end_test

# ─── T5 schema_version event_log >= 4 ──────────────────────────────────────
start_test "event_log_schema_v4"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION as V; print(V['event_log'])")
  if [ "$out" -ge 4 ]; then
    :
  else
    fail_test "event_log schema_version=$out, expected >= 4 after G4"
  fi
end_test

# ─── T6 Validate Input node rejects empty session_id ──────────────────────
start_test "validate_input_rejects_empty_session_id"
  if [ ! -f "$WF" ]; then skip_test "no workflow file"
  else
    out=$(python3 - <<PY 2>/dev/null
import json
d = json.load(open("$WF"))
n = next((x for x in d.get("nodes", []) if x.get("name") == "Validate Input"), None)
if not n: print("MISSING"); raise SystemExit
js = (n.get("parameters") or {}).get("jsCode") or ""
print("OK" if "session_id and prompt are required" in js else "MISSING_GUARD")
PY
)
    assert_eq "OK" "$out" "validator does not reject empty session_id"
  fi
end_test

# ─── T7 SSH Claude Resume does an existence check via sqlite3 ─────────────
# (Moved out of Validate Input because n8n sandbox disallows child_process —
# see workflow update on 2026-04-29 after first activation smoke test.)
start_test "ssh_replay_checks_session_exists"
  if [ ! -f "$WF" ]; then skip_test "no workflow file"
  else
    out=$(python3 - <<PY 2>/dev/null
import json
d = json.load(open("$WF"))
n = next((x for x in d.get("nodes", []) if x.get("name") == "SSH Claude Resume"), None)
cmd = ((n or {}).get("parameters") or {}).get("command") or ""
print("OK" if ("sqlite3" in cmd and "FROM sessions" in cmd and "unknown_session" in cmd) else "MISSING")
PY
)
    assert_eq "OK" "$out" "no sqlite3 existence check / unknown_session guard in SSH Claude Resume"
  fi
end_test

# ─── T8 SessionReplayInvokedEvent serialises correctly ────────────────────
start_test "event_serialises_correctly"
  out=$(cd "$REPO_ROOT/scripts" && python3 - <<PY 2>/dev/null
from lib.session_events import SessionReplayInvokedEvent
ev = SessionReplayInvokedEvent(session_id="x", outcome="success", prompt_chars=42, cost_usd=0.01, num_turns=2, model="claude-sonnet-4-6")
import json
row = ev.to_row()
p = json.loads(row["payload_json"])
print(p["outcome"], p["prompt_chars"], p["model"])
PY
)
  assert_eq "success 42 claude-sonnet-4-6" "$out" "payload_json shape wrong"
end_test
