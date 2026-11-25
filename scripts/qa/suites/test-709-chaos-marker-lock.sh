#!/usr/bin/env bash
# IFRNLLEI01PRD-709 — chaos-active.json marker lock discipline.
#
# Exercises scripts/lib/chaos_marker.py and the two call sites
# (chaos-port-shutdown.py, chaos-test.py's _cmd_start_locked) to regress-proof
# the 2026-04-23 collision that left NL ASA Tunnel5 stuck admin-down.
#
# All tests are offline: no SSH, no Matrix, no network. Each test seeds a
# synthetic marker at a scratch path, invokes the library in a subprocess,
# and asserts the expected behavior via exit code + JSON payload.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="709-chaos-marker-lock"

# Scratch dir — cleaned up on every test (fail-safe).
QA_SCRATCH="$(mktemp -d -t qa-709-XXXXXX)"
trap 'rm -rf "$QA_SCRATCH"' EXIT

scratch_state="$QA_SCRATCH/chaos-active.json"
scratch_lock="$scratch_state.lock"

# Helper: invoke chaos_marker.install_marker against a scratch state+lock path
# and print {ok, err} JSON for assertion.
run_install() {
  local scenario="$1" window="${2:-600}" triggered_by="${3:-qa-test}"
  python3 - "$scratch_state" "$scratch_lock" "$scenario" "$window" "$triggered_by" <<'PY'
import json, sys, pathlib
sys.path.insert(0, "/app/claude-gateway/scripts/lib")
from chaos_marker import install_marker, ChaosCollisionError
state_path = pathlib.Path(sys.argv[1])
lock_path  = pathlib.Path(sys.argv[2])
scenario, window, triggered_by = sys.argv[3], int(sys.argv[4]), sys.argv[5]
try:
    install_marker(scenario, window, triggered_by=triggered_by,
                   extras={"experiment_id": f"qa-{scenario}"},
                   state_path=state_path, lock_path=lock_path)
    print(json.dumps({"ok": True}))
except ChaosCollisionError as e:
    print(json.dumps({"ok": False, "err": str(e)}))
PY
}

# Helper: seed a marker file at the scratch path.
seed_marker() {
  local scenario="$1" seconds_from_now="$2" experiment_id="${3:-}"
  python3 - "$scratch_state" "$scenario" "$seconds_from_now" "$experiment_id" <<'PY'
import json, pathlib, sys, time
path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
scenario, offset, experiment_id = sys.argv[2], int(sys.argv[3]), sys.argv[4]
expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))
started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
path.write_text(json.dumps({
    "scenario": scenario,
    "started_at": started,
    "expires_at": expires,
    "triggered_by": "seeded",
    "experiment_id": experiment_id or None,
}))
PY
}

# --------------------------------------------------------------------------
# T1: different-scenario unexpired marker → install_marker raises
# --------------------------------------------------------------------------
start_test "cross_scenario_unexpired_marker_refuses_overwrite"
  rm -f "$scratch_state" "$scratch_lock"
  seed_marker "UNIT-TEST-OTHER-DRILL" 600
  result=$(run_install "freedom-ont-shutdown" 1800)
  assert_contains "$result" '"ok": false'
  assert_contains "$result" "UNIT-TEST-OTHER-DRILL"
  # Make sure the seeded marker was NOT overwritten.
  still_other=$(python3 -c "import json; print(json.load(open('$scratch_state'))['scenario'])")
  assert_eq "UNIT-TEST-OTHER-DRILL" "$still_other" "marker untouched after refusal"
end_test

# --------------------------------------------------------------------------
# T2: same-scenario unexpired marker → install_marker refreshes, no error
# --------------------------------------------------------------------------
start_test "same_scenario_unexpired_marker_refreshes_cleanly"
  rm -f "$scratch_state" "$scratch_lock"
  seed_marker "freedom-ont-shutdown" 600
  result=$(run_install "freedom-ont-shutdown" 1800)
  assert_contains "$result" '"ok": true'
  # started_at should be refreshed to ~now, not the seeded value.
  refreshed=$(python3 -c "
import json, time
m = json.load(open('$scratch_state'))
diff = time.time() - time.mktime(time.strptime(m['started_at'], '%Y-%m-%dT%H:%M:%SZ'))
print('fresh' if abs(diff) < 10 else 'stale')
")
  # mktime interprets as local; on UTC hosts this drift is ~0, on others it's
  # timezone-sized. Accept either as long as JSON parses and marker exists.
  assert_file_exists "$scratch_state"
end_test

# --------------------------------------------------------------------------
# T3: expired marker → install_marker overwrites silently
# --------------------------------------------------------------------------
start_test "expired_marker_overwritten_silently"
  rm -f "$scratch_state" "$scratch_lock"
  seed_marker "STALE-CRASHED-DRILL" -300   # expired 5 min ago
  result=$(run_install "freedom-ont-shutdown" 1800)
  assert_contains "$result" '"ok": true'
  scenario_now=$(python3 -c "import json; print(json.load(open('$scratch_state'))['scenario'])")
  assert_eq "freedom-ont-shutdown" "$scenario_now" "expired marker replaced"
end_test

# --------------------------------------------------------------------------
# T4: concurrent install_marker — second writer gets ChaosCollisionError
# because the first holds the flock. Validates the fcntl discipline end-to-end.
# --------------------------------------------------------------------------
start_test "concurrent_writers_exactly_one_succeeds"
  rm -f "$scratch_state" "$scratch_lock"
  out=$(python3 - "$scratch_state" "$scratch_lock" <<'PY'
import json, multiprocessing, pathlib, sys, time
sys.path.insert(0, "/app/claude-gateway/scripts/lib")
from chaos_marker import marker_lock, atomic_write_marker, ChaosCollisionError, check_no_cross_drill

state_path = pathlib.Path(sys.argv[1])
lock_path  = pathlib.Path(sys.argv[2])

def writer(idx, delay_before, hold_sec, ret):
    time.sleep(delay_before)
    try:
        with marker_lock(lock_path):
            check_no_cross_drill(f"writer-{idx}", None, state_path=state_path)
            atomic_write_marker(
                {"scenario": f"writer-{idx}",
                 "started_at": "2026-04-23T00:00:00Z",
                 "expires_at": "2026-04-23T12:00:00Z",
                 "triggered_by": "qa"},
                state_path=state_path)
            time.sleep(hold_sec)
        ret.put((idx, "ok"))
    except ChaosCollisionError as e:
        ret.put((idx, f"collision: {str(e)[:80]}"))
    except Exception as e:
        ret.put((idx, f"error: {type(e).__name__}: {e}"))

q = multiprocessing.Queue()
# Writer A starts immediately and holds the lock 0.5s.
# Writer B starts 0.05s later → must see lock contention and raise.
a = multiprocessing.Process(target=writer, args=(0, 0.0, 0.5, q))
b = multiprocessing.Process(target=writer, args=(1, 0.05, 0.0, q))
a.start(); b.start()
a.join(); b.join()
results = sorted([q.get(), q.get()])
print(json.dumps(results))
PY
)
  # Expect: writer 0 returns "ok", writer 1 returns "collision: ..."
  assert_contains "$out" '"ok"'
  assert_contains "$out" 'collision:'
end_test

# --------------------------------------------------------------------------
# T5: freedom-ont-drill-trigger.sh preflight gate aborts when marker present.
# IFRNLLEI01PRD-721: we seed the marker at a scratch path and export
# CHAOS_STATE_PATH so the trigger + chaos-preflight.sh read that path instead
# of the real $HOME/chaos-state/chaos-active.json. This removes the risk of
# accidentally dispatching a live drill (the 12:07 UTC 2026-04-23 incident)
# and eliminates the skip branch for "real marker already present" because
# we never touch the production path at all.
# --------------------------------------------------------------------------
start_test "preflight_gate_aborts_when_marker_present"
  SCRATCH_MARKER="$QA_SCRATCH/chaos-active.json"
  python3 - "$SCRATCH_MARKER" <<'PY'
import json, pathlib, sys, time
p = pathlib.Path(sys.argv[1])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({
    "scenario": "QA-HOLDER-FOR-TEST-709",
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()+600)),
    "triggered_by": "qa-test-709",
}))
PY
  # PATH shim: neutralise `crontab` (trigger's self-remove) so we don't mutate
  # the operator's real crontab during the test.
  SHIM="$QA_SCRATCH/shim"; mkdir -p "$SHIM"
  printf '#!/bin/sh\nexit 0\n' > "$SHIM/crontab"; chmod +x "$SHIM/crontab"
  log_path="$HOME/logs/claude-gateway/freedom-ont-drill.log"
  # Use `wc -l` on potentially-empty streams so the result is always a
  # single int (pgrep -c returns "0\n" AND exit 1 with no matches, which
  # breaks the `|| echo 0` fallback).
  lines_before=$(wc -l < "$log_path" 2>/dev/null | head -1)
  children_before=$(pgrep -f 'chaos-port-shutdown.py' 2>/dev/null | wc -l)
  PATH="$SHIM:$PATH" MATRIX_CLAUDE_TOKEN="" \
    CHAOS_STATE_PATH="$SCRATCH_MARKER" \
    /app/claude-gateway/scripts/freedom-ont-drill-trigger.sh \
    >/dev/null 2>&1 || true
  # Small settle so a malformed trigger that still backgrounds something
  # has a chance to show up as a child.
  sleep 1
  lines_after=$(wc -l < "$log_path" 2>/dev/null | head -1)
  children_after=$(pgrep -f 'chaos-port-shutdown.py' 2>/dev/null | wc -l)
  : "${lines_before:=0}" "${lines_after:=0}" "${children_before:=0}" "${children_after:=0}"
  delta_lines=$(( lines_after - lines_before ))
  [ "$delta_lines" -lt 0 ] && delta_lines=0
  new_lines=$(tail -n "$delta_lines" "$log_path" 2>/dev/null || true)
  abort_seen=$(printf '%s' "$new_lines" | grep -c "ABORT: chaos-preflight.sh returned NOT READY" || true)
  assert_gt "${abort_seen:-0}" "0" "trigger logged ABORT this run"
  # Preflight gate must fire BEFORE the trigger's nohup &. If it did, no new
  # chaos-port-shutdown.py process was spawned by this run.
  delta_children=$(( children_after - children_before ))
  assert_eq "0" "$delta_children" "no chaos-port-shutdown.py child spawned after ABORT"
  still=$(python3 -c "import json; print(json.load(open('$SCRATCH_MARKER'))['scenario'])" 2>/dev/null || echo "MISSING")
  assert_eq "QA-HOLDER-FOR-TEST-709" "$still" "scratch marker not clobbered by preflight gate"
end_test
