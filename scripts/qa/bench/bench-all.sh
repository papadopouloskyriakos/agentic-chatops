#!/usr/bin/env bash
# Performance benchmarks for the 9-issue adoption batch.
#
# Each bench runs N iterations and reports p50/p95/max via bench_time_ms.
# Targets come from the issue descriptions; failures here are SOFT (warn-only)
# to keep CI green on slower hardware, but the numbers get stamped into the
# scorecard for trending.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"
source "$REPO_ROOT/scripts/qa/lib/bench.sh"

export QA_SUITE_NAME="bench"

# Prepare shared DB (benchmarks all read/write same DB; they're independent calls).
tmp=$(fresh_db)
seed_session "$tmp" "BENCH-1" "sb"

# ── event_log insert throughput ───────────────────────────────────────────────
start_test "event_emit_latency"
  # 30 iterations of single emit.
  data=$(bench_time_ms 30 event_emit_ms -- env GATEWAY_DB="$tmp" \
    "$REPO_ROOT/scripts/emit-event.py" --type tool_started --issue BENCH-1 \
    --session sb --turn 0 --payload-json '{"tool_name":"Bash"}')
  p95=$(printf '%s' "$data" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["p95"])')
  # Target: <200ms per invocation (most latency is python startup, not the emit itself).
  [ "${QA_VERBOSE:-0}" = "1" ] && echo "    event_emit p95=${p95}ms" >&2
  assert_lt "$p95" "500" "event_emit p95 < 500ms"
end_test

# ── handoff_depth bump latency ────────────────────────────────────────────────
start_test "handoff_bump_latency"
  data=$(bench_time_ms 20 handoff_bump_ms -- env GATEWAY_DB="$tmp" \
    python3 -c "
import sys; sys.path.insert(0,'$REPO_ROOT/scripts/lib')
from handoff_depth import bump
try: bump('BENCH-HB','p','a')
except Exception: pass
")
  p95=$(printf '%s' "$data" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["p95"])')
  [ "${QA_VERBOSE:-0}" = "1" ] && echo "    handoff_bump p95=${p95}ms" >&2
  assert_lt "$p95" "500" "handoff_bump p95 < 500ms"
end_test

# ── HandoffInputData encode throughput ────────────────────────────────────────
start_test "handoff_envelope_encode_latency"
  data=$(bench_time_ms 20 handoff_envelope_encode_ms -- python3 -c "
import sys; sys.path.insert(0,'$REPO_ROOT/scripts/lib')
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='a', to_agent='b',
    input_history=[{'role':'user','content':'x'*500} for _ in range(30)])
env.to_b64()
")
  p95=$(printf '%s' "$data" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["p95"])')
  [ "${QA_VERBOSE:-0}" = "1" ] && echo "    envelope_encode p95=${p95}ms" >&2
  assert_lt "$p95" "500" "envelope encode p95 < 500ms"
end_test

# ── compression ratio at a known payload size ─────────────────────────────────
start_test "handoff_envelope_compression_ratio"
  out=$(python3 -c "
import sys; sys.path.insert(0,'$REPO_ROOT/scripts/lib')
from handoff import HandoffInputData
env = HandoffInputData(issue_id='X', from_agent='a', to_agent='b',
    input_history=[{'role':'user','content':'repeat '*500} for _ in range(50)])
raw = env.to_json(); b64 = env.to_b64()
print(len(raw), len(b64))
")
  raw=$(echo "$out" | awk '{print $1}')
  b64=$(echo "$out" | awk '{print $2}')
  ratio=$(python3 -c "print(round($b64/$raw, 4))")
  bench_record handoff_compression raw_bytes "$raw"
  bench_record handoff_compression b64_bytes "$b64"
  bench_record handoff_compression ratio "$ratio"
  [ "${QA_VERBOSE:-0}" = "1" ] && echo "    compression ratio=$ratio (raw=$raw b64=$b64)" >&2
  assert_lt "$ratio" "0.10" "compression ratio < 10%"
end_test

# ── snapshot capture latency ──────────────────────────────────────────────────
start_test "snapshot_capture_latency"
  data=$(bench_time_ms 15 snapshot_capture_ms -- env GATEWAY_DB="$tmp" \
    python3 -c "
import sys; sys.path.insert(0,'$REPO_ROOT/scripts/lib')
from snapshot import capture
capture('BENCH-1','sb',0,'Bash',{'command':'ls'})
")
  p95=$(printf '%s' "$data" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["p95"])')
  [ "${QA_VERBOSE:-0}" = "1" ] && echo "    snapshot_capture p95=${p95}ms" >&2
  assert_lt "$p95" "500" "snapshot capture p95 < 500ms"
end_test

# ── unified-guard hook latency ────────────────────────────────────────────────
start_test "unified_guard_hook_latency"
  data=$(bench_time_ms 25 unified_guard_ms -- bash -c "
echo '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo hello\"}}' | \
  GATEWAY_DB='$tmp' ISSUE_ID=BENCH bash '$REPO_ROOT/scripts/hooks/unified-guard.sh'
")
  p95=$(printf '%s' "$data" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["p95"])')
  [ "${QA_VERBOSE:-0}" = "1" ] && echo "    unified_guard_hook p95=${p95}ms" >&2
  assert_lt "$p95" "500" "unified-guard hook p95 < 500ms"
end_test

cleanup_db "$tmp"
