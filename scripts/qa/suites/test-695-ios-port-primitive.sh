#!/usr/bin/env bash
# IFRNLLEI01PRD-695 follow-up — ios-port-shutdown / ios-port-noshut primitives
# landed in scripts/chaos_parallel.py. Catalog scenario freedom-ont-shutdown
# can now run unattended via chaos-test.py's catalog runner instead of
# manual_execute dispatch through freedom-ont-drill-trigger.sh.
#
# Regression target: if someone ever drops the ios_ssh import or deletes
# the elif branch, the catalog freedom-ont-shutdown drill silently returns
# "unknown action type" instead of shutting the port. This suite catches that.
#
# All tests are offline — sw01_port_shutdown / sw01_port_noshut are mocked.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="695-ios-port-primitive"

# --- T1: dispatcher recognises ios-port-shutdown ------------------------------
start_test "dispatcher handles ios-port-shutdown"
out=$(python3 <<'PY'
import sys, json, unittest.mock as mock
sys.path.insert(0, "/app/claude-gateway/scripts")
sys.path.insert(0, "/app/claude-gateway/scripts/lib")
import chaos_parallel as cp
with mock.patch.object(cp, "sw01_port_shutdown", return_value=(True, "mock-shut-ok")):
    action = {"type":"ios-port-shutdown","target":"nl-sw01","interface":"GigabitEthernet1/0/36"}
    ok, ev = cp._execute_action(action)
print(json.dumps({"ok": ok, "type": ev.get("action"), "success": ev.get("success"), "detail": ev.get("detail")}))
PY
)
ok=$(jq -r '.ok' <<<"$out")
detail=$(jq -r '.detail' <<<"$out")
assert_eq "true" "$ok" "action must succeed when primitive returns (True, msg)"
assert_contains "$detail" "GigabitEthernet1/0/36" "event detail names the interface"
end_test

# --- T2: dispatcher refuses unsupported target (fail-closed) ------------------
start_test "dispatcher refuses non-sw01 target"
out=$(python3 <<'PY'
import sys, json
sys.path.insert(0, "/app/claude-gateway/scripts")
sys.path.insert(0, "/app/claude-gateway/scripts/lib")
import chaos_parallel as cp
action = {"type":"ios-port-shutdown","target":"nlsw99","interface":"Gi1/0/1"}
ok, ev = cp._execute_action(action)
print(json.dumps({"ok": ok, "detail": ev.get("detail")}))
PY
)
ok=$(jq -r '.ok' <<<"$out")
detail=$(jq -r '.detail' <<<"$out")
assert_eq "false" "$ok" "unsupported switch target must fail closed"
assert_contains "$detail" "sw01 only" "detail names the sw01-only restriction"
end_test

# --- T3: rollback dispatcher wires ios-port-noshut with force_poe_cycle -------
start_test "rollback handler forwards force_poe_cycle"
out=$(python3 <<'PY'
import sys, json, unittest.mock as mock
sys.path.insert(0, "/app/claude-gateway/scripts")
sys.path.insert(0, "/app/claude-gateway/scripts/lib")
import chaos_parallel as cp
calls = []
def fake_noshut(iface, force_poe_cycle=False):
    calls.append({"iface": iface, "force_poe_cycle": force_poe_cycle})
    return (True, "ok")
with mock.patch.object(cp, "sw01_port_noshut", side_effect=fake_noshut):
    cp._execute_rollback_action({
        "type":"ios-port-noshut",
        "target":"nl-sw01",
        "interface":"GigabitEthernet1/0/36",
        "force_poe_cycle": True,
    })
print(json.dumps({"calls": calls}))
PY
)
iface=$(jq -r '.calls[0].iface' <<<"$out")
poe=$(jq -r '.calls[0].force_poe_cycle' <<<"$out")
assert_eq "GigabitEthernet1/0/36" "$iface" "rollback passes interface through"
assert_eq "true" "$poe" "force_poe_cycle flag propagates from rollback spec"
end_test

# --- T4: rollback skips silently when target is non-sw01 ----------------------
start_test "rollback handler skips non-sw01 target without raising"
out=$(python3 <<'PY'
import sys, json, unittest.mock as mock
sys.path.insert(0, "/app/claude-gateway/scripts")
sys.path.insert(0, "/app/claude-gateway/scripts/lib")
import chaos_parallel as cp
with mock.patch.object(cp, "sw01_port_noshut") as m:
    try:
        cp._execute_rollback_action({
            "type":"ios-port-noshut",
            "target":"nlsw99",
            "interface":"Gi1/0/1",
            "force_poe_cycle": False,
        })
        raised = False
    except Exception as e:
        raised = True
print(json.dumps({"raised": raised, "called": m.called}))
PY
)
raised=$(jq -r '.raised' <<<"$out")
called=$(jq -r '.called' <<<"$out")
assert_eq "false" "$raised" "non-sw01 rollback must not raise"
assert_eq "false" "$called" "non-sw01 rollback must NOT call the primitive"
end_test

# --- T5: catalog freedom-ont-shutdown scenario references the new primitives -
start_test "catalog references ios-port-shutdown + ios-port-noshut types"
catalog="$REPO_ROOT/experiments/catalog.yaml"
assert_file_exists "$catalog" "catalog.yaml exists"
grep -q "id: freedom-ont-shutdown" "$catalog" || fail_test "catalog missing freedom-ont-shutdown id"
grep -q "type: ios-port-shutdown" "$catalog" || fail_test "catalog missing ios-port-shutdown method type"
grep -q "type: ios-port-noshut" "$catalog" || fail_test "catalog missing ios-port-noshut rollback type"
end_test