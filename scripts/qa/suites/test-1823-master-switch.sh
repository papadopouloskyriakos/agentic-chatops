#!/bin/bash
# test-1823-master-switch.sh — master power switch (IFRNLLEI01PRD-1823)
# Hermetic: isolated GATEWAY_HOME + isolated DB + all external planes skipped
# (MASTER_SWITCH_SKIP_CRONICLE/N8N/MATRIX=1). Never touches live sentinels,
# the live gateway.db, or the live prom dir.
# QA_SUITE_TIMEOUT: 120
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-1823-master-switch"

MSW="$REPO_ROOT/scripts/gateway-master-switch.py"
AUDIT="$REPO_ROOT/scripts/lib/master_switch_audit.py"

fresh_env() {
  # New isolated world per test: fake HOME with sentinels, isolated DB/log/prom/state.
  QA_HOME=$(mktemp -d)
  QA_DB=$(mktemp --suffix=.db)
  mkdir -p "$QA_HOME/gateway-state/master-switch" "$QA_HOME/logs/claude-gateway"
  # Arm a representative sentinel set (subset present, like live)
  touch "$QA_HOME/gateway.autonomy_forward" "$QA_HOME/gateway.platform_controller_armed" \
        "$QA_HOME/gateway.renovate_autonomy" "$QA_HOME/gateway.sched_reboot"
  # Guards present
  touch "$QA_HOME/gateway.plan_adherence_gate" "$QA_HOME/gateway.plan_adherence_enforce" \
        "$QA_HOME/gateway.territory_gate" "$QA_HOME/gateway.silent_cognition_guard"
  # Data files that must never be touched
  touch "$QA_HOME/gateway.mode" "$QA_HOME/gateway.db" "$QA_HOME/gateway.foldgate-verified"
  export GATEWAY_HOME="$QA_HOME" MASTER_SWITCH_DB="$QA_DB"
  export MASTER_SWITCH_STATE_DIR="$QA_HOME/gateway-state/master-switch"
  export MASTER_SWITCH_LOG="$QA_HOME/logs/claude-gateway/master-switch.log"
  export MASTER_SWITCH_PROM="$QA_HOME/master_switch.prom"
  export MASTER_SWITCH_SKIP_CRONICLE=1 MASTER_SWITCH_SKIP_N8N=1 MASTER_SWITCH_SKIP_MATRIX=1
  export MASTER_SWITCH_PID_GLOB="$QA_HOME/claude-pid-*"
}

cleanup_env() {
  rm -rf "$QA_HOME" "$QA_DB"
  unset GATEWAY_HOME MASTER_SWITCH_DB MASTER_SWITCH_STATE_DIR MASTER_SWITCH_LOG \
        MASTER_SWITCH_PROM MASTER_SWITCH_SKIP_CRONICLE MASTER_SWITCH_SKIP_N8N \
        MASTER_SWITCH_SKIP_MATRIX MASTER_SWITCH_PID_GLOB
}

# ── schema registry ─────────────────────────────────────────────────────────────
start_test "schema_version_registers_master_switch_log"
ver=$( (cd "$REPO_ROOT/scripts" && python3 -c "import lib.schema_version as s; print(s.current('master_switch_log'))") 2>&1 )
assert_eq "1" "$ver" "master_switch_log registered at v1"
end_test

# ── status on a virgin world ────────────────────────────────────────────────────
start_test "status_initial_state_is_on"
fresh_env
out=$(python3 "$MSW" status --json 2>&1)
assert_contains "$out" '"state": "on"' "virgin state is on"
assert_contains "$out" '"chain_intact": true' "empty ledger verifies"
cleanup_env
end_test

# ── off: sentinels removed, guards kept, data untouched ─────────────────────────
start_test "off_removes_arming_keeps_guards_and_data"
fresh_env
python3 "$MSW" off --reason "qa test" --operator qa >/dev/null 2>&1
rc=$?
assert_eq "0" "$rc" "off exits 0"
assert_eq "0" "$(ls "$QA_HOME"/gateway.autonomy_forward 2>/dev/null | wc -l)" "autonomy_forward removed"
assert_eq "0" "$(ls "$QA_HOME"/gateway.platform_controller_armed 2>/dev/null | wc -l)" "platform_controller_armed removed"
assert_file_exists "$QA_HOME/gateway.plan_adherence_gate" "guard plan_adherence_gate kept"
assert_file_exists "$QA_HOME/gateway.territory_gate" "guard territory_gate kept"
assert_file_exists "$QA_HOME/gateway.mode" "data gateway.mode untouched"
assert_file_exists "$QA_HOME/gateway.db" "data gateway.db untouched"
assert_file_exists "$QA_HOME/gateway.maintenance" "maintenance file created"
grep -q '"master_switch": true' "$QA_HOME/gateway.maintenance"
assert_eq "0" "$?" "maintenance file carries master_switch marker"
assert_eq "0" "$(ls "$QA_HOME"/gateway.tripwire_off 2>/dev/null | wc -l)" "tripwire_off NOT created"
cleanup_env
end_test

# ── off is stateful: second off refuses without --force ─────────────────────────
start_test "off_twice_refuses_without_force"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
python3 "$MSW" off --reason "qa again" --operator qa >/dev/null 2>&1
assert_eq "1" "$?" "second off exits 1"
cleanup_env
end_test

# ── on: exact restore ────────────────────────────────────────────────────────────
start_test "on_restores_exact_pre_off_state"
fresh_env
rm "$QA_HOME/gateway.sched_reboot"   # arm only 3 of the 4 -> restore must NOT resurrect it
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
python3 "$MSW" on --operator qa >/dev/null 2>&1
rc=$?
assert_eq "0" "$rc" "on exits 0"
assert_file_exists "$QA_HOME/gateway.autonomy_forward" "autonomy_forward restored"
assert_file_exists "$QA_HOME/gateway.renovate_autonomy" "renovate_autonomy restored"
assert_eq "0" "$(ls "$QA_HOME"/gateway.sched_reboot 2>/dev/null | wc -l)" "sched_reboot NOT resurrected (was absent at off)"
assert_eq "0" "$(ls "$QA_HOME"/gateway.maintenance 2>/dev/null | wc -l)" "maintenance file removed"
assert_file_exists "$QA_HOME/gateway.maintenance-ended" "cooldown marker written"
cleanup_env
end_test

# ── preexisting operator maintenance is preserved through off AND on ─────────────
start_test "preexisting_maintenance_preserved"
fresh_env
echo '{"reason":"operator window","operator":"human"}' > "$QA_HOME/gateway.maintenance"
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
grep -q "operator window" "$QA_HOME/gateway.maintenance"
assert_eq "0" "$?" "off left the operator's maintenance file untouched"
python3 "$MSW" on --operator qa >/dev/null 2>&1
assert_file_exists "$QA_HOME/gateway.maintenance" "on kept the foreign maintenance file"
grep -q "operator window" "$QA_HOME/gateway.maintenance"
assert_eq "0" "$?" "foreign content intact after on"
assert_eq "0" "$(ls "$QA_HOME"/gateway.maintenance-ended 2>/dev/null | wc -l)" "no cooldown marker when we did not own maintenance"
cleanup_env
end_test

# ── ledger: hash chain, 2 rows, verify, tamper detection ─────────────────────────
start_test "ledger_chain_appends_and_detects_tamper"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
python3 "$MSW" on --operator qa >/dev/null 2>&1
out=$(python3 "$AUDIT" verify --db "$QA_DB" 2>&1)
assert_contains "$out" "OK rows=2" "chain verifies with 2 rows"
sqlite3 "$QA_DB" "UPDATE master_switch_log SET reason='tampered' WHERE id=1;"
assert_exit_code 1 python3 "$AUDIT" verify --db "$QA_DB"
assert_contains "$_qa_last_stdout" "BROKEN:1" "tampered row 1 detected"
cleanup_env
end_test

# ── JSONL + prom side logs ───────────────────────────────────────────────────────
start_test "jsonl_and_prom_written"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
assert_eq "1" "$(grep -c '"action": "off"' "$MASTER_SWITCH_LOG")" "JSONL has the off entry"
assert_contains "$(cat "$MASTER_SWITCH_PROM")" "gateway_master_switch_state 0" "prom state=0 after off"
python3 "$MSW" on --operator qa >/dev/null 2>&1
assert_contains "$(cat "$MASTER_SWITCH_PROM")" "gateway_master_switch_state 1" "prom state=1 after on"
assert_contains "$(cat "$MASTER_SWITCH_PROM")" "gateway_master_switch_chain_intact 1" "chain gauge intact"
perms=$(stat -c %a "$MASTER_SWITCH_PROM")
assert_eq "644" "$perms" "prom file world-readable (node_exporter non-root)"
cleanup_env
end_test

# ── on without snapshot refuses ──────────────────────────────────────────────────
start_test "on_without_snapshot_refuses"
fresh_env
assert_exit_code 2 python3 "$MSW" on --operator qa
cleanup_env
end_test

# ── tampered snapshot cannot create inverted kill-switches ───────────────────────
start_test "on_refuses_never_create_from_tampered_snapshot"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
python3 - "$MASTER_SWITCH_STATE_DIR/snapshot-current.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
s = json.load(open(p))
s["sentinels_present"].append("gateway.tripwire_off")
json.dump(s, open(p, "w"))
PYEOF
python3 "$MSW" on --operator qa >/dev/null 2>&1
assert_eq "0" "$(ls "$QA_HOME"/gateway.tripwire_off 2>/dev/null | wc -l)" "tripwire_off refused even from snapshot"
cleanup_env
end_test

# ── status consistency detection ─────────────────────────────────────────────────
start_test "status_detects_inconsistency"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
touch "$QA_HOME/gateway.autonomy_forward"   # simulate drift while off
assert_exit_code 4 python3 "$MSW" status --json
assert_contains "$_qa_last_stdout" "arming sentinels present" "drift reported"
cleanup_env
end_test

# ── dry-run mutates nothing ──────────────────────────────────────────────────────
start_test "dry_run_is_side_effect_free"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa --dry-run >/dev/null 2>&1
assert_file_exists "$QA_HOME/gateway.autonomy_forward" "sentinel untouched by dry-run"
assert_eq "0" "$(ls "$QA_HOME"/gateway.maintenance 2>/dev/null | wc -l)" "no maintenance file from dry-run"
assert_eq "0" "$(sqlite3 "$QA_DB" 'SELECT COUNT(*) FROM master_switch_log' 2>/dev/null || echo 0)" "no ledger row from dry-run"
cleanup_env
end_test

# ── kill-sessions TERMs only listed pids ─────────────────────────────────────────
start_test "kill_sessions_terms_inflight"
fresh_env
sleep 300 &
FAKE_PID=$!
echo "$FAKE_PID" > "$QA_HOME/claude-pid-QA-1"
python3 "$MSW" off --reason "qa" --operator qa --kill-sessions >/dev/null 2>&1
sleep 1
alive=0
kill -0 "$FAKE_PID" 2>/dev/null && alive=1
assert_eq "0" "$alive" "in-flight session TERMed"
kill "$FAKE_PID" 2>/dev/null
cleanup_env
end_test

# ── REGRESSION (review CRITICAL): off --force preserves the restore baseline ─────
# After a first off, sentinels are gone; a --force re-off must NOT snapshot an empty
# baseline. 'on' must still restore the full original arming set.
start_test "force_reoff_preserves_full_restore_baseline"
fresh_env
python3 "$MSW" off --reason "first" --operator qa >/dev/null 2>&1
# sentinels now removed; re-off with --force (the documented recovery path)
python3 "$MSW" off --reason "reoff" --operator qa --force >/dev/null 2>&1
# snapshot must still carry all 4 arming sentinels
base=$(python3 -c "import json;print(len(json.load(open('$MASTER_SWITCH_STATE_DIR/snapshot-current.json'))['sentinels_present']))")
assert_eq "4" "$base" "re-off snapshot still holds all 4 arming sentinels"
python3 "$MSW" on --operator qa >/dev/null 2>&1
assert_file_exists "$QA_HOME/gateway.autonomy_forward" "autonomy_forward restored after force-reoff"
assert_file_exists "$QA_HOME/gateway.platform_controller_armed" "platform_controller_armed restored"
assert_file_exists "$QA_HOME/gateway.renovate_autonomy" "renovate_autonomy restored"
assert_file_exists "$QA_HOME/gateway.sched_reboot" "sched_reboot restored"
cleanup_env
end_test

# ── REGRESSION (review HIGH): partial ON keeps state OFF, retry restores ─────────
start_test "partial_on_keeps_state_off_and_retries"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
# Induce a REAL touch() failure: a dangling symlink into a nonexistent dir — touch follows
# it and gets ENOENT (a directory in its place would succeed via utime, so that won't work).
ln -s "$QA_HOME/nope/deep/target" "$QA_HOME/gateway.renovate_autonomy"
python3 "$MSW" on --operator qa >/dev/null 2>&1
rc=$?
assert_eq "3" "$rc" "partial on exits 3"
state=$(python3 "$MSW" status --json 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin)['state'])")
assert_eq "off" "$state" "state stays OFF after partial on"
# fix the obstruction and retry WITHOUT --force (allowed because state is still off)
rm -f "$QA_HOME/gateway.renovate_autonomy"
python3 "$MSW" on --operator qa >/dev/null 2>&1
assert_eq "0" "$?" "on retry (no --force) succeeds"
assert_file_exists "$QA_HOME/gateway.renovate_autonomy" "obstructed sentinel restored on retry"
cleanup_env
end_test

# ── REGRESSION (review CRITICAL): cronicle_set maps API code 0 = success ─────────
# Unit-test with a stubbed cronicle module so a code==0 return is recorded ok, not failed.
start_test "cronicle_set_treats_code_zero_as_success"
out=$( (cd "$REPO_ROOT/scripts" && python3 - <<'PYEOF'
import sys, types
sys.path.insert(0, "lib")
stub = types.ModuleType("cronicle")
stub.login = lambda: "sess-123"
stub.set_enabled = lambda eid, en, sid: 0          # 0 = Cronicle API success
stub.schedule = lambda: []
sys.modules["cronicle"] = stub
import importlib.util
spec = importlib.util.spec_from_file_location("gms", "gateway-master-switch.py")
gms = importlib.util.module_from_spec(spec); spec.loader.exec_module(gms)
gms.cronicle_lib = stub
res = gms.cronicle_set([{"id": "e1", "title": "job", "enabled": 1}], 0)
print("OK" if res and res[0]["ok"] else f"FAIL {res}")
# and a non-zero code must be recorded as failure
stub.set_enabled = lambda eid, en, sid: -1
res2 = gms.cronicle_set([{"id": "e1", "title": "job", "enabled": 1}], 0)
print("OK2" if res2 and not res2[0]["ok"] else f"FAIL2 {res2}")
# login failure must fail all
stub.login = lambda: ""
res3 = gms.cronicle_set([{"id": "e1", "title": "job", "enabled": 1}], 0)
print("OK3" if res3 and not res3[0]["ok"] else f"FAIL3 {res3}")
PYEOF
) 2>&1 )
assert_contains "$out" "OK" "code 0 recorded as success"
assert_contains "$out" "OK2" "code -1 recorded as failure"
assert_contains "$out" "OK3" "login failure fails all targets"
end_test

# ── REGRESSION (review MEDIUM): hash-chain truncation detected via anchor ─────────
start_test "ledger_truncation_detected_by_anchor"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
python3 "$MSW" on --operator qa >/dev/null 2>&1
# 2 rows + anchor. Delete the last row: plain chain replay would still pass, anchor catches it.
sqlite3 "$QA_DB" "DELETE FROM master_switch_log WHERE id=(SELECT MAX(id) FROM master_switch_log);"
assert_exit_code 1 python3 "$AUDIT" verify --db "$QA_DB"
cleanup_env
end_test

# ── REGRESSION (verify pass): --hard is sticky across a --force re-off ────────────
start_test "hard_is_sticky_across_force_reoff"
fresh_env
python3 "$MSW" off --reason "hard first" --operator qa --hard >/dev/null 2>&1
# re-off WITHOUT --hard must keep hard=true in the snapshot (dispatch stays targeted)
python3 "$MSW" off --reason "reoff soft-flag" --operator qa --force >/dev/null 2>&1
hard=$(python3 -c "import json;print(json.load(open('$MASTER_SWITCH_STATE_DIR/snapshot-current.json'))['hard'])")
assert_eq "True" "$hard" "hard flag sticky across --force re-off"
cleanup_env
end_test

# ── REGRESSION (verify pass): corrupt snapshot refuses without --force ────────────
start_test "corrupt_snapshot_refuses_off"
fresh_env
python3 "$MSW" off --reason "qa" --operator qa >/dev/null 2>&1
echo "{ this is not valid json" > "$MASTER_SWITCH_STATE_DIR/snapshot-current.json"
assert_exit_code 2 python3 "$MSW" off --reason "qa2" --operator qa
cleanup_env
end_test

# ── REGRESSION (verify pass): live cronicle import-failure ≠ silent skip ──────────
start_test "cronicle_import_failure_is_not_a_silent_skip"
out=$( (cd "$REPO_ROOT/scripts" && python3 - <<'PYEOF'
import os, sys, importlib.util
os.environ.pop("MASTER_SWITCH_SKIP_CRONICLE", None)   # NOT a skip
sys.path.insert(0, "lib")
spec = importlib.util.spec_from_file_location("gms", "gateway-master-switch.py")
gms = importlib.util.module_from_spec(spec); spec.loader.exec_module(gms)
gms.cronicle_lib = None                                # simulate import failure
tg = gms.cronicle_targets()
# must return the 9 titles as missing (attemptable → will fail → partial), NOT []
print("OK" if len(tg) == 9 and all(t.get("missing") for t in tg) else f"FAIL {tg}")
PYEOF
) 2>&1 )
assert_contains "$out" "OK" "live cronicle import failure yields 9 missing targets, not a silent []"
end_test

# ── REGRESSION (review MEDIUM): _canon type-stability (int/None/bool/empty) ───────
start_test "ledger_canon_type_stable"
fresh_env
out=$( (cd "$REPO_ROOT/scripts" && python3 - "$QA_DB" <<'PYEOF'
import sys
sys.path.insert(0, "lib")
import master_switch_audit as a
db = sys.argv[1]
# rows exercising None, empty string, int, and json — verify must stay OK across readback
for r in [
    {"action": "off", "operator": None, "reason": "", "partial": 0, "details_json": "{}"},
    {"action": "on", "operator": "x", "reason": "y", "partial": 1, "sentinels_json": "[]"},
]:
    a.append(db, r)
ok, brk, n = a.verify(db)
print("OK" if ok and n == 2 else f"FAIL ok={ok} brk={brk} n={n}")
PYEOF
) 2>&1 )
assert_contains "$out" "OK" "chain verifies across None/empty/int/json readback"
cleanup_env
end_test
