#!/usr/bin/env bash
# IFRNLLEI01PRD-749 — Intermediate semantic rail (G2.P0.3).
#
# Tests the rail library + event_log integration. Stays offline (heuristic
# backend) so the suite runs deterministically in CI without depending on
# Ollama availability.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="749-intermediate-rail"
LIB="$REPO_ROOT/scripts/lib/intermediate_rail.py"

# ─── T1 lib exists + compiles ──────────────────────────────────────────────
start_test "lib_exists_and_compiles"
  if [ ! -f "$LIB" ]; then fail_test "missing $LIB"
  elif ! python3 -m py_compile "$LIB" 2>/dev/null; then fail_test "py_compile failed"
  fi
end_test

# ─── T2 heuristic backend identifies in-distribution availability text ────
start_test "heuristic_in_distribution_availability"
  out=$(python3 "$LIB" --no-ollama --no-emit --category availability \
                       --text "ping timeout from 10.0.181.X; service down on tcp/443" \
        2>/dev/null)
  if echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['is_in_distribution'] and d['backend']=='heuristic' else 1)"; then
    :
  else
    fail_test "did not identify availability text: $out"
  fi
end_test

# ─── T3 heuristic flags off-topic text ─────────────────────────────────────
start_test "heuristic_flags_off_topic"
  out=$(python3 "$LIB" --no-ollama --no-emit --category availability \
                       --text "tell me a joke about the weather" \
        2>/dev/null)
  if echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if not d['is_in_distribution'] else 1)"; then
    :
  else
    fail_test "off-topic text not flagged: $out"
  fi
end_test

# ─── T4 heuristic returns non-zero confidence on matched text ──────────────
start_test "heuristic_confidence_above_zero_for_match"
  out=$(python3 "$LIB" --no-ollama --no-emit --category kubernetes \
                       --text "pod CrashLoopBackOff in kube-system; etcd quorum lost" \
        2>/dev/null)
  conf=$(echo "$out" | python3 -c "import json,sys; print(json.load(sys.stdin)['confidence'])")
  assert_gt "$conf" "0.0" "confidence should be > 0 for matched text"
end_test

# ─── T5 emit_event writes to event_log ─────────────────────────────────────
start_test "emit_event_writes_event_log_row"
  tmp=$(fresh_db)
  out=$(GATEWAY_DB="$tmp" python3 "$LIB" --no-ollama --category storage \
                       --issue-id TEST-RAIL-1 --session-id sess-rail \
                       --text "zfs pool degraded on gr-pve02; iSCSI lun offline" \
        2>/dev/null)
  cnt=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM event_log WHERE event_type='intermediate_rail_check'")
  assert_eq "1" "$cnt" "expected 1 intermediate_rail_check row"
  ver=$(sqlite3 "$tmp" "SELECT schema_version FROM event_log WHERE event_type='intermediate_rail_check' LIMIT 1")
  if [ "$ver" -ge 3 ]; then
    :
  else
    fail_test "schema_version=$ver, expected >=3"
  fi
  cleanup_db "$tmp"
end_test

# ─── T6 stdin mode works ───────────────────────────────────────────────────
start_test "stdin_mode_accepted"
  out=$(echo "bgp peer flap on vti tunnel" | python3 "$LIB" --no-ollama --no-emit --category network --text-stdin 2>/dev/null)
  if echo "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['is_in_distribution'] else 1)"; then
    :
  else
    fail_test "stdin mode did not produce expected output: $out"
  fi
end_test

# ─── T7 schema_version registry has event_log >= 3 ─────────────────────────
start_test "schema_version_event_log_advanced_for_g2"
  ver=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION as V; print(V['event_log'])")
  if [ "$ver" -ge 3 ]; then
    :
  else
    fail_test "event_log schema_version=$ver, expected >=3 after G2 lands"
  fi
end_test

# ─── T8 IntermediateRailCheckEvent class is in EVENT_TYPES ────────────────
start_test "session_events_has_intermediate_rail_check"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.session_events import EVENT_TYPES; print(','.join(EVENT_TYPES))")
  assert_contains "$out" "intermediate_rail_check" "intermediate_rail_check missing from EVENT_TYPES"
end_test
