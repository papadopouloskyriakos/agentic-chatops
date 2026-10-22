#!/bin/bash
# test-intersite-autoheal.sh — Layer-2 intersite tunnel auto-heal consumer + the
# intersite mutation-exemption lane (IFRNLLEI01PRD-1833, 2026-08-14).
#
# Hermetic: GATEWAY_HOME + all state/log/prom paths in mktemp dirs; MUTATIONS
# forced via env (never touches live sentinels); INTERSITE_FORBID_DEVICE=1 makes
# ANY live device call raise — a gate-ordering regression fails loudly here
# instead of touching an ASA. Real 2026-08-14 counter samples as fixtures.
# QA_SUITE_TIMEOUT: 120
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-intersite-autoheal"

HEAL="$REPO_ROOT/scripts/intersite-tunnel-heal.py"
GATES="$REPO_ROOT/scripts/lib/suppression-gates.sh"

TMP="$(mktemp -d)"
export GATEWAY_HOME="$TMP"
export MUTATION_SHADOW_LOG_DIR="$TMP/shadow"
export INTERSITE_STATE_FILE="$TMP/intersite-heal.json"
export INTERSITE_AUDIT_LOG="$TMP/intersite-heal.log"
export PROMETHEUS_TEXTFILE_DIR="$TMP/prom"
export INTERSITE_FORBID_DEVICE=1
export INTERSITE_NO_MATRIX=1
export INTERSITE_MIN_DOWN_RUNS=1

# module loader for the dashed filename
_py() { python3 - "$@" <<PYEOF
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("ith", "$HEAL")
ith = importlib.util.module_from_spec(spec); spec.loader.exec_module(ith)
$(cat)
PYEOF
}

FIX_FREEDOM_DOWN='{"devices":{"nl-fw01":{"unreachable":false,"sessions":{"10.255.200.X":{"state":"idle","established":0}}},"nlrtr01":{"unreachable":false,"sessions":{"10.255.200.X":{"state":"established","established":1}}}}}'
FIX_HEALTHY='{"devices":{"nl-fw01":{"unreachable":false,"sessions":{"10.255.200.X":{"state":"established","established":1}}},"nlrtr01":{"unreachable":false,"sessions":{"10.255.200.X":{"state":"established","established":1}}}}}'
FIX_UNREACHABLE='{"devices":{"nl-fw01":{"unreachable":true,"sessions":{}},"nlrtr01":{"unreachable":false,"sessions":{"10.255.200.X":{"state":"established","established":1}}}}}'

# ── T1 wedge signature evaluator (real 2026-08-14 fixtures) ──────────────────
start_test "wedge_from_samples_signatures"
out=$(echo '
s_frozen1 = "      #pkts decaps: 23123211, #pkts decrypt: 23123211, #pkts verify: 23123211"
s_frozen2 = "      #pkts decaps: 23123211, #pkts decrypt: 23123211, #pkts verify: 23123211"
s_move2   = "      #pkts decaps: 23123999, #pkts decrypt: 23123999, #pkts verify: 23123999"
s_reset2  = "      #pkts decaps: 104, #pkts decrypt: 104, #pkts verify: 104"
print(ith.wedge_from_samples(s_frozen1, s_frozen2))
print(ith.wedge_from_samples(s_frozen1, s_move2))
print(ith.wedge_from_samples("", ""))
print(ith.wedge_from_samples(s_frozen1, s_reset2))
' | _py)
assert_contains "$out" "(True, 'decaps_frozen_at_23123211')" "frozen decaps = wedge"
assert_contains "$out" "(False, 'decaps_moving')" "rising decaps = healthy"
assert_contains "$out" "(True, 'no_sa_data')" "no SA data = 08-08 variant wedge"
assert_contains "$out" "(False, 'counters_reset')" "reset counters = already re-keyed"
end_test

# ── T2 watchdog JSON -> leg states ───────────────────────────────────────────
start_test "legs_down_from_watchdog_mapping"
out=$(echo "
print(ith.legs_down_from_watchdog(json.loads('$FIX_FREEDOM_DOWN')))
print(ith.legs_down_from_watchdog(json.loads('$FIX_HEALTHY')))
print(ith.legs_down_from_watchdog(json.loads('$FIX_UNREACHABLE')))
" | _py)
assert_contains "$out" "{'freedom': True, 'budget': False}" "freedom down parsed"
assert_contains "$out" "{'freedom': False, 'budget': False}" "healthy parsed"
assert_contains "$out" "{'freedom': None, 'budget': False}" "unreachable = unknown, never down"
end_test

# ── T3 backoff / escalate decisioning ────────────────────────────────────────
start_test "heal_decision_backoff_and_escalate"
out=$(echo '
now = time.time()
print(ith.heal_decision({}, "freedom", now))                                   # no history
print(ith.heal_decision({"legs":{"freedom":{"heals":[now-30]}}}, "freedom", now))    # 30s ago
print(ith.heal_decision({"legs":{"freedom":{"heals":[now-3000]}}}, "freedom", now))  # cooled
print(ith.heal_decision({"legs":{"freedom":{"heals":[now-100, now-200, now-300]}}}, "freedom", now))
' | _py)
assert_eq "heal backoff heal escalate" "$(echo "$out" | tr '\n' ' ' | sed 's/ $//')" \
  "0-history heal / recent backoff / cooled heal / 3-strike escalate"
end_test

# ── T4 shadow without exemption sentinel -> logged not run ──────────────────
start_test "shadow_no_exemption_suppresses"
out=$(echo "$FIX_FREEDOM_DOWN" | MUTATIONS_OFF=1 python3 "$HEAL" --from-watchdog 2>&1); rc=$?
assert_eq "0" "$rc" "exit 0"
assert_contains "$out" "shadow (no intersite exemption sentinel)" "suppression decision"
assert_file_exists "$PROMETHEUS_TEXTFILE_DIR/intersite_autoheal.prom" "prom still written under shadow"
assert_contains "$(cat "$PROMETHEUS_TEXTFILE_DIR/intersite_autoheal.prom")" "intersite_autoheal_armed 0" "armed=0"
rm -f "$INTERSITE_STATE_FILE"
end_test

# ── T5 not-shadow but disarmed -> analysis-only ──────────────────────────────
start_test "disarmed_is_analysis_only"
out=$(echo "$FIX_FREEDOM_DOWN" | MUTATIONS_OFF=0 python3 "$HEAL" --from-watchdog 2>&1); rc=$?
assert_eq "0" "$rc" "exit 0"
assert_contains "$out" "analysis-only (arming sentinel absent)" "disarmed decision"
rm -f "$INTERSITE_STATE_FILE"
end_test

# ── T6 gates pass (shadow+exempt+armed) -> next step is a DEVICE call ────────
start_test "gates_pass_reaches_device_stage_only_then"
touch "$GATEWAY_HOME/gateway.mutations_intersite_allow" "$GATEWAY_HOME/gateway.intersite_autoheal_armed"
out=$(echo "$FIX_FREEDOM_DOWN" | MUTATIONS_OFF=1 python3 "$HEAL" --from-watchdog 2>&1); rc=$?
assert_ne "0" "$rc" "device guard tripped AFTER gates (ordering proof)"
assert_contains "$out" "INTERSITE_FORBID_DEVICE" "the forbidden call is the signature probe"
# --check stops before the device stage by design
out=$(echo "$FIX_FREEDOM_DOWN" | MUTATIONS_OFF=1 python3 "$HEAL" --check 2>&1); rc=$?
assert_eq "0" "$rc" "--check exit 0"
assert_contains "$out" "WOULD HEAL" "--check reports would-heal without device calls"
rm -f "$INTERSITE_STATE_FILE"
end_test

# ── T7 maintenance suppresses even when armed+exempt ─────────────────────────
start_test "maintenance_suppresses_armed_lane"
touch "$GATEWAY_HOME/gateway.maintenance"
out=$(echo "$FIX_FREEDOM_DOWN" | MUTATIONS_OFF=1 python3 "$HEAL" --from-watchdog 2>&1); rc=$?
assert_eq "0" "$rc" "exit 0"
assert_contains "$out" "suppressed (maintenance/chaos)" "maintenance gate"
rm -f "$GATEWAY_HOME/gateway.maintenance" "$INTERSITE_STATE_FILE"
end_test

# ── T8 healthy mesh -> all idle, streaks reset ───────────────────────────────
start_test "healthy_mesh_is_idle"
out=$(echo "$FIX_HEALTHY" | MUTATIONS_OFF=1 python3 "$HEAL" --from-watchdog 2>&1); rc=$?
assert_eq "0" "$rc" "exit 0"
assert_contains "$out" '"freedom": "healthy"' "freedom healthy"
assert_contains "$out" '"budget": "healthy"' "budget healthy"
end_test

# ── T9 unreachable local host -> unknown, never treated as down ──────────────
start_test "unreachable_device_never_down"
out=$(echo "$FIX_UNREACHABLE" | MUTATIONS_OFF=1 python3 "$HEAL" --from-watchdog 2>&1)
assert_contains "$out" "unknown (device unreachable" "unknown not down"
rm -f "$GATEWAY_HOME/gateway.mutations_intersite_allow" "$GATEWAY_HOME/gateway.intersite_autoheal_armed" "$INTERSITE_STATE_FILE"
end_test

# ── T10 bash lane helper: mutation_shadow_exempt ─────────────────────────────
start_test "bash_mutation_shadow_exempt_lane"
rc_noexempt=$(bash -c "source '$GATES'; MUTATIONS_OFF=1 GATEWAY_HOME='$TMP' mutation_shadow_exempt intersite; echo \$?" | tail -1)
touch "$TMP/gateway.mutations_intersite_allow"
rc_exempt=$(bash -c "source '$GATES'; MUTATIONS_OFF=1 GATEWAY_HOME='$TMP' mutation_shadow_exempt intersite; echo \$?" | tail -1)
rc_noshadow=$(bash -c "source '$GATES'; MUTATIONS_OFF=0 GATEWAY_HOME='$TMP' mutation_shadow_exempt intersite; echo \$?" | tail -1)
assert_eq "1" "$rc_noexempt" "shadow + no sentinel = suppressed"
assert_eq "0" "$rc_exempt" "shadow + sentinel = allowed"
assert_eq "0" "$rc_noshadow" "no shadow = allowed"
MUTATION_SHADOW_LOG_DIR="$TMP/shadow2" bash -c "source '$GATES'; mutation_exempt_audit intersite 'action=test'"
assert_contains "$(cat "$TMP/shadow2/intersite-exempt-allows.log")" "lane=intersite" "audit line written"
rm -f "$TMP/gateway.mutations_intersite_allow"
end_test

# ── T11 wiring: vti scripts use the lane, watchdog invokes the consumer ──────
start_test "wiring_and_syntax"
for f in vti-freedom-recovery.sh vti-budget-recovery.sh bgp-mesh-watchdog.sh; do
  bash -n "$REPO_ROOT/scripts/$f" || fail_test "bash -n failed: $f"
done
python3 -m py_compile "$HEAL" || fail_test "py_compile failed on healer"
for f in vti-freedom-recovery.sh vti-budget-recovery.sh; do
  assert_eq "1" "$(grep -c 'mutation_shadow_exempt intersite' "$REPO_ROOT/scripts/$f")" "$f gates on the lane"
done
assert_contains "$(tail -15 "$REPO_ROOT/scripts/bgp-mesh-watchdog.sh")" 'intersite-tunnel-heal.py" --from-watchdog' "watchdog hook present"
assert_contains "$(grep 'gateway.intersite_autoheal_armed' "$REPO_ROOT/scripts/gateway-master-switch.py")" "intersite_autoheal_armed" "sentinel registered in ARMING_SENTINELS"
end_test

rm -rf "$TMP"
