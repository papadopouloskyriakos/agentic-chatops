#!/bin/bash
# test-freedom-ont-heal.sh — capped Freedom ONT auto-heal (scripts/freedom-ont-heal.py,
# IFRNLLEI01PRD-2992, NL power-loss postmortem).
#
# Hermetic: GATEWAY_HOME + state/log/prom in a mktemp dir, MUTATIONS forced via env,
# FREEDOM_ONT_FORBID_DEVICE=1 makes ANY live switch/ASA call raise, Matrix suppressed.
# Device outputs are the real nl-sw01 / nl-fw01 text captured 2026-11-07; the
# actuation + verify functions are replaced in-process, so no PoE cycle can ever happen here.
# QA_SUITE_TIMEOUT: 120
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-freedom-ont-heal"

HEAL="$REPO_ROOT/scripts/freedom-ont-heal.py"
TMP="$(mktemp -d)"
export GATEWAY_HOME="$TMP"
export MUTATION_SHADOW_LOG_DIR="$TMP/shadow"
export FREEDOM_ONT_STATE_FILE="$TMP/state.json"
export FREEDOM_ONT_AUDIT_LOG="$TMP/heal.log"
export PROMETHEUS_TEXTFILE_DIR="$TMP/prom"
export FREEDOM_ONT_FORBID_DEVICE=1
export FREEDOM_ONT_NO_MATRIX=1
PROM="$TMP/prom/freedom_ont_autoheal.prom"

# In-process harness: load the module, stub the device layer, run cycles with a synthetic clock.
_py() { python3 - "$@" <<PYEOF
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("foh", "$HEAL")
foh = importlib.util.module_from_spec(spec); spec.loader.exec_module(foh)
def _audit_only(msg):                      # keep stdout for the test's own prints
    with open(foh.AUDIT_LOG, "a") as f: f.write(msg + "\n")
foh.log = _audit_only
SW_OK = {"ok": True, "status": "connected", "poe_admin": "auto", "poe_oper": "on",
         "poe_watts": 15.4, "description": "*** Connection to Freedom Internet | Genexis XGS-PON ONT | 1 Gbps | PoE ***"}
SW_WEDGED = dict(SW_OK, status="notconnect")
ASA_UP = {"ok": True, "track_up": True, "ip": "203.0.113.X"}
ASA_DOWN = {"ok": True, "track_up": False, "ip": None}
HEALTHY = {"switch": SW_OK, "asa": ASA_UP}
WEDGED = {"switch": SW_WEDGED, "asa": ASA_DOWN}
calls = []
def stub(cycle=(True, "poe off applied; 15s; poe auto + shut/no shut applied"),
         res={"link": True, "track": True, "poe_admin": "auto"}):
    foh.poe_cycle = lambda: (calls.append("cycle"), cycle)[1]
    foh.verify = lambda: res
$(cat)
PYEOF
}

reset_world() { rm -f "$FREEDOM_ONT_STATE_FILE" "$PROM" "$GATEWAY_HOME"/gateway.* ; rm -rf "$GATEWAY_HOME/chaos-state" "$MUTATION_SHADOW_LOG_DIR"; }

# ── T1 parsers on the real 2026-11-07 device output ─────────────────────────
start_test "parsers_real_device_output"
out=$(echo '
sw_conn = """
Port         Name               Status       Vlan       Duplex  Speed Type
Gi1/0/36     *** Connection to  connected    trunk      a-full a-1000 10/100/1000BaseTX
Interface Admin  Oper       Power   Device              Class Max
                            (Watts)
--------- ------ ---------- ------- ------------------- ----- ----
Gi1/0/36  auto   on         15.4    Ieee PD             3     60.0
Interface                      Status         Protocol Description
Gi1/0/36                       up             up       *** Connection to Freedom Internet | Genexis XGS-PON ONT | 1 Gbps | PoE ***
"""
sw_wedged = sw_conn.replace("connected    trunk      a-full a-1000", "notconnect   trunk      auto   auto  ").replace("up             up ", "down           down")
sw_shut = sw_conn.replace("connected    trunk", "disabled     trunk").replace("up             up ", "admin down     down")
sw_poe_off = sw_wedged.replace("auto   on         15.4    Ieee PD", "auto   off        0.0     n/a    ")
print(foh.parse_switch(sw_conn))
print(foh.parse_switch(sw_wedged)["status"], foh.parse_switch(sw_wedged)["poe_oper"], "Freedom" in foh.parse_switch(sw_wedged)["description"])
print(foh.parse_switch(sw_shut)["status"], "Freedom" in foh.parse_switch(sw_shut)["description"])
print(foh.parse_switch(sw_poe_off)["poe_oper"], foh.parse_switch(sw_poe_off)["poe_watts"])
print(foh.parse_track("Track 1\n  Response Time Reporter 1 reachability\n  Reachability is Up\n  4 changes"))
print(foh.parse_track("Track 1\n  Response Time Reporter 1 reachability\n  Reachability is Down\n"))
print(foh.parse_track("garbage"))
ip = """Current IP Address:
Interface                Name                   IP address      Subnet mask     Method
Port-channel1.6          outside_freedom        203.0.113.X    255.255.255.255 CONFIG"""
print(foh.parse_asa_ip(ip), foh.parse_asa_ip(ip.replace("203.0.113.X   ", "unassigned     ")))
' | _py)
assert_contains "$out" "'status': 'connected', 'poe_admin': 'auto', 'poe_oper': 'on', 'poe_watts': 15.4" "connected + PoE on parsed"
assert_contains "$out" "notconnect on True" "notconnect + PoE on + Freedom description"
assert_contains "$out" "disabled True" "admin-shut port parsed as disabled"
assert_contains "$out" "off 0.0" "PoE off parsed"
assert_eq "True False None" "$(echo "$out" | sed -n 5,7p | tr '\n' ' ' | sed 's/ $//')" "track Up/Down/absent"
assert_contains "$out" "203.0.113.X None" "current IP vs unassigned"
end_test

# ── T2 classification matrix ─────────────────────────────────────────────────
start_test "classify_matrix"
out=$(echo '
for name, snap in [
  ("healthy", HEALTHY),
  ("wedged_asa_down", WEDGED),
  ("wedged_asa_unknown", {"switch": SW_WEDGED, "asa": {"ok": False}}),
  ("asa_contradiction", {"switch": SW_WEDGED, "asa": ASA_UP}),
  ("admin_down", {"switch": dict(SW_WEDGED, status="disabled"), "asa": ASA_DOWN}),
  ("poe_off", {"switch": dict(SW_WEDGED, poe_oper="off"), "asa": ASA_DOWN}),
  ("err_disabled", {"switch": dict(SW_WEDGED, status="err-disabled"), "asa": ASA_DOWN}),
  ("wrong_port", {"switch": dict(SW_WEDGED, description="uplink to something else"), "asa": ASA_DOWN}),
  ("switch_unreachable", {"switch": {"ok": False}, "asa": ASA_DOWN}),
]:
    print(name, foh.classify(snap)[0])
' | _py)
for pair in "healthy healthy" "wedged_asa_down wedged" "wedged_asa_unknown unconfirmed" \
            "asa_contradiction contradiction" "admin_down admin-down" "poe_off poe-not-on" \
            "err_disabled other" "wrong_port identity-mismatch" "switch_unreachable unknown"; do
  assert_contains "$out" "$pair" "classify: $pair"
done
end_test

# ── T3 cap + exponential backoff decisioning ─────────────────────────────────
start_test "heal_decision_cap_and_backoff"
out=$(echo '
now = 1_000_000.0
for hist in ([], [now-30], [now-700], [now-1500, now-900], [now-2000, now-1300],
             [now-3000, now-2000, now-100], [now-90000, now-89000, now-88000]):
    print(foh.heal_decision({"attempts": list(hist)}, now), end=" ")
' | _py)
assert_eq "heal backoff heal backoff heal escalate heal" "$(echo "$out" | sed 's/ $//')" \
  "0 / 30s(<10m) / 700s(>=10m) / 2nd-at-900s(<20m) / 2nd-at-1300s / 3-in-24h / old-attempts-pruned"
end_test

# ── T4 healthy -> no action, truthful metrics, no last_result ────────────────
start_test "healthy_no_action"
reset_world
echo '{"switch":{"ok":true,"status":"connected","poe_admin":"auto","poe_oper":"on","poe_watts":15.4,"description":"*** Connection to Freedom Internet"},"asa":{"ok":true,"track_up":true}}' > "$TMP/healthy.json"
out=$(MUTATIONS_OFF=1 python3 "$HEAL" --snapshot-file "$TMP/healthy.json" 2>&1); rc=$?
assert_eq "0" "$rc" "exit 0"
assert_contains "$out" '"decision": "no action (healthy)"' "healthy = no action"
assert_file_exists "$PROM" "prom written"
p=$(cat "$PROM")
assert_contains "$p" "freedom_ont_autoheal_wedged 0" "wedged 0"
assert_contains "$p" "freedom_ont_autoheal_link_down 0" "link_down 0"
assert_contains "$p" "freedom_ont_autoheal_armed 0" "armed 0 (sentinel absent)"
assert_contains "$p" 'freedom_ont_autoheal_gate_active{gate="mutation_shadow"} 1' "shadow gate reported"
assert_contains "$p" "freedom_ont_autoheal_failure_open 0" "no open failure"
assert_not_contains "$p" "freedom_ont_autoheal_last_result" "no last_result without a real attempt"
end_test

# ── T5 down-streak: 2 runs AND >=240 s before any gate is even evaluated ─────
start_test "streak_needs_two_runs_and_four_minutes"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
stub()
print(foh.run_cycle(WEDGED, now=1000)["decision"])
print(foh.run_cycle(WEDGED, now=1120)["decision"])
print(foh.run_cycle(WEDGED, now=1240)["decision"])
print(len(calls))
' | MUTATIONS_OFF=0 _py)
assert_contains "$(echo "$out" | sed -n 1p)" "wait (streak 1/2" "run 1 waits"
assert_contains "$(echo "$out" | sed -n 2p)" "wait (streak 2/2, held 120s/240s)" "run 2 (2 min) still waits"
assert_contains "$(echo "$out" | sed -n 3p)" "healed: success" "run 3 (4 min) heals"
assert_eq "1" "$(echo "$out" | sed -n 4p)" "exactly one PoE cycle"
end_test

# ── T6 gate ordering via the real CLI (device guard proves where it stops) ───
start_test "gates_block_before_any_device_call"
reset_world
echo '{"switch":{"ok":true,"status":"notconnect","poe_admin":"auto","poe_oper":"on","poe_watts":15.4,"description":"*** Connection to Freedom Internet"},"asa":{"ok":true,"track_up":false}}' > "$TMP/wedged.json"
run() { FREEDOM_ONT_MIN_DOWN_RUNS=1 FREEDOM_ONT_MIN_DOWN_SECONDS=0 python3 "$HEAL" --snapshot-file "$TMP/wedged.json" 2>&1; }
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed" "$GATEWAY_HOME/gateway.mutations_freedom_ont_allow" "$GATEWAY_HOME/gateway.maintenance"
out=$(MUTATIONS_OFF=1 run); rc=$?
assert_eq "0" "$rc" "maintenance: exit 0"; assert_contains "$out" "suppressed (maintenance window/chaos)" "a real maintenance window blocks even armed+exempt"
rm -f "$GATEWAY_HOME/gateway.maintenance"; mkdir -p "$GATEWAY_HOME/chaos-state"; echo '{}' > "$GATEWAY_HOME/chaos-state/chaos-active.json"
out=$(MUTATIONS_OFF=1 run); assert_contains "$out" "suppressed (maintenance window/chaos)" "chaos marker blocks (ONT drill)"
rm -rf "$GATEWAY_HOME/chaos-state"; rm -f "$GATEWAY_HOME/gateway.mutations_freedom_ont_allow"
out=$(MUTATIONS_OFF=1 run); assert_contains "$out" "shadow (no ~/gateway.mutations_freedom_ont_allow)" "shadow without lane sentinel blocks"
rm -f "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(MUTATIONS_OFF=0 run); assert_contains "$out" "analysis-only (arming sentinel absent)" "disarmed = analysis-only"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_wedged 1" "detection metric still live while disarmed"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_suppressed 1" "suppressed reported"
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed" "$GATEWAY_HOME/gateway.mutations_freedom_ont_allow"
out=$(MUTATIONS_OFF=1 run); rc=$?
assert_ne "0" "$rc" "all gates open -> the NEXT step is the device (guard trips)"
assert_contains "$out" "FREEDOM_ONT_FORBID_DEVICE" "the forbidden call is the PoE cycle itself"
assert_contains "$(cat "$FREEDOM_ONT_STATE_FILE")" '"attempts": [' "the attempt was persisted before the (forbidden) device call"
rm -f "$FREEDOM_ONT_STATE_FILE"
out=$(MUTATIONS_OFF=1 FREEDOM_ONT_MIN_DOWN_RUNS=1 FREEDOM_ONT_MIN_DOWN_SECONDS=0 python3 "$HEAL" --dry-run --snapshot-file "$TMP/wedged.json" 2>&1); rc=$?
assert_eq "0" "$rc" "--dry-run exit 0"; assert_contains "$out" "WOULD HEAL (dry-run: no actuation)" "--dry-run stops before the device"
end_test

# ── T6b the master-switch marker does not block; a real window and junk do ──
start_test "master_switch_marker_exempt_real_window_blocks"
reset_world
run() { FREEDOM_ONT_MIN_DOWN_RUNS=1 FREEDOM_ONT_MIN_DOWN_SECONDS=0 python3 "$HEAL" --snapshot-file "$TMP/wedged.json" 2>&1; }
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed" "$GATEWAY_HOME/gateway.mutations_freedom_ont_allow"
echo '{"started":"2026-08-26T18:58:53Z","reason":"master-switch: TG primary","eta_minutes":0,"operator":"tg-graduation","master_switch":true}' > "$GATEWAY_HOME/gateway.maintenance"
out=$(MUTATIONS_OFF=1 run); rc=$?
assert_ne "0" "$rc" "master-switch marker: gates open -> reaches the device (guard trips)"
assert_contains "$out" "FREEDOM_ONT_FORBID_DEVICE" "master-switch marker does not block the PoE cycle"
rm -f "$FREEDOM_ONT_STATE_FILE"
out=$(MUTATIONS_OFF=1 python3 "$HEAL" --snapshot-file "$TMP/healthy.json" 2>&1)
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_master_switch_exempt 1" "exemption is visible in the metrics"
assert_contains "$(cat "$PROM")" 'freedom_ont_autoheal_gate_active{gate="maintenance"} 0' "master switch is not reported as the maintenance gate"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_suppressed 0" "armed + lane + master switch = not suppressed"
rm -f "$FREEDOM_ONT_STATE_FILE"
echo '{"started":"2026-11-07T15:00:00Z","reason":"planned work","eta_minutes":30,"operator":"operator"}' > "$GATEWAY_HOME/gateway.maintenance"
out=$(MUTATIONS_OFF=1 run); rc=$?
assert_eq "0" "$rc" "real window: exit 0"; assert_contains "$out" "suppressed (maintenance window/chaos)" "a real maintenance window (no marker) blocks"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_master_switch_exempt 0" "no exemption for a real window"
assert_contains "$(cat "$PROM")" 'freedom_ont_autoheal_gate_active{gate="maintenance"} 1' "a real window is reported as the maintenance gate"
echo '{"master_switch": "true"}' > "$GATEWAY_HOME/gateway.maintenance"
out=$(MUTATIONS_OFF=1 run); assert_contains "$out" "suppressed (maintenance window/chaos)" "a non-boolean marker fails closed"
echo 'not json' > "$GATEWAY_HOME/gateway.maintenance"
out=$(MUTATIONS_OFF=1 run); assert_contains "$out" "suppressed (maintenance window/chaos)" "an unreadable maintenance file fails closed"
end_test

# ── T7 three failed attempts, backoff between them, then ONE escalation ──────
start_test "cap_three_per_24h_then_escalate_once"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
stub(res={"link": False, "track": False, "poe_admin": "auto"})
t = 10_000
for dt in (0, 120, 240, 360, 900, 1000, 2500, 2700, 2900, 3100):
    r = foh.run_cycle(WEDGED, now=t + dt)
    print(dt, r["decision"], r["attempts_24h"])
print("cycles", len(calls))
s = foh.load_state()
print("escalations", s["counters"]["escalations"], "attempts", s["counters"]["attempts"])
' | MUTATIONS_OFF=0 _py)
assert_contains "$out" "240 healed: failed 1" "attempt 1 at 4 min"
assert_contains "$out" "360 backoff (recent attempt, cooling down) 1" "2 min later: backoff"
assert_contains "$out" "900 healed: failed 2" "attempt 2 after >=10 min"
assert_contains "$out" "1000 backoff" "backoff after attempt 2"
assert_contains "$out" "2500 healed: failed 3" "attempt 3 after >=20 min"
assert_contains "$out" "2700 escalate (3 attempts in 24 h, still wedged) 3" "cap reached -> escalate"
assert_contains "$out" "2900 escalated (already notified this episode) 3" "no repeat escalation"
assert_contains "$out" "cycles 3" "never more than 3 PoE cycles"
assert_contains "$out" "escalations 1 attempts 3" "one escalation counted"
p=$(cat "$PROM")
assert_contains "$p" "freedom_ont_autoheal_last_result 0" "last_result 0 after failed real attempts"
assert_contains "$p" "freedom_ont_autoheal_failure_open 1" "failure open while still wedged"
assert_contains "$p" "freedom_ont_autoheal_escalations_total 1" "escalation exported"
assert_contains "$(cat "$FREEDOM_ONT_AUDIT_LOG")" "ESCALATE:" "escalation audited"
end_test

# ── T8 recovery closes the failure; a new 24 h window allows healing again ───
start_test "recovery_closes_failure"
out=$(echo '
r = foh.run_cycle(HEALTHY, now=10_000 + 3300)
print(r["decision"], foh.failure_open(foh.load_state()))
' | MUTATIONS_OFF=0 _py)
assert_contains "$out" "no action (healthy) False" "healthy + Track 1 Up closes the open failure"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_failure_open 0" "metric closed"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_last_result 0" "last_result kept as history"
end_test

# ── T9 PoE restore failure -> immediate escalation (ONT may be unpowered) ────
start_test "poe_left_off_escalates_immediately"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
stub(cycle=(False, "POE-LEFT-OFF on GigabitEthernet1/0/36: restore retry 3 failed"))
foh.run_cycle(WEDGED, now=5000); foh.run_cycle(WEDGED, now=5300)
s = foh.load_state(); print(s["last_result"], s["counters"]["escalations"], len(calls))
' | MUTATIONS_OFF=0 _py)
assert_eq "failed 1 1" "$out" "failed + escalated once + one cycle"
assert_contains "$(cat "$FREEDOM_ONT_AUDIT_LOG")" "power inline auto" "escalation tells the human the restore command"
end_test

# ── T10 link back but PPPoE/Track not Up -> link_only, failure stays open ────
start_test "link_only_is_not_success"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
stub(res={"link": True, "track": False, "poe_admin": "auto"})
foh.run_cycle(WEDGED, now=5000); r = foh.run_cycle(WEDGED, now=5300)
print(r["decision"], foh.failure_open(foh.load_state()))
r = foh.run_cycle({"switch": SW_OK, "asa": ASA_DOWN}, now=5420)
print(r["state"], foh.failure_open(foh.load_state()))
' | MUTATIONS_OFF=0 _py)
assert_contains "$out" "healed: link_only True" "link_only keeps the failure open"
assert_contains "$out" "healthy True" "link up but Track 1 Down does not close it"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_last_link_restored 1" "link restoration exported"
end_test

# ── T11 shadow logs the would-have-acted once per episode ────────────────────
start_test "shadow_logs_once_per_episode"
reset_world
out=$(echo '
stub()
for t in (5000, 5300, 5420, 5540): foh.run_cycle(WEDGED, now=t)
print(len(calls))
' | MUTATIONS_OFF=1 _py)
assert_eq "0" "$out" "shadow never cycles"
assert_eq "1" "$(cat "$TMP"/shadow/shadow-*.jsonl 2>/dev/null | grep -c freedom-ont-poe-cycle)" "one would-have-acted line per episode"
end_test

# ── T11b --drill-force is human-only: refused without a TTY, before any probe ─
start_test "drill_force_refused_without_tty"
out=$(python3 "$HEAL" --drill-force < /dev/null 2>&1); rc=$?
assert_eq "2" "$rc" "no TTY -> refused (rc 2)"
assert_contains "$out" "DRILL refused" "refusal logged"
assert_not_contains "$out" "FREEDOM_ONT_FORBID_DEVICE" "refused before any device call"
out=$(python3 "$HEAL" --drill-force --dry-run < /dev/null 2>&1); rc=$?
assert_ne "0" "$rc" "--drill-force combined with another flag is rejected"
end_test

# ── T11c fail closed: unreadable state never resets the cap; attempt persisted pre-actuation ─
start_test "fail_closed_state_and_attempt_persisted_first"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
echo '{not json' > "$FREEDOM_ONT_STATE_FILE"
out=$(echo '
stub()
r = foh.run_cycle(WEDGED, now=7000); r = foh.run_cycle(WEDGED, now=7300)
print(r["decision"], len(calls))
print(open(foh.STATE_FILE).read().strip())
' | MUTATIONS_OFF=0 FREEDOM_ONT_MIN_DOWN_RUNS=1 FREEDOM_ONT_MIN_DOWN_SECONDS=0 _py)
assert_contains "$out" "refused (state file unreadable" "unreadable state -> no actuation"
assert_contains "$out" " 0" "zero PoE cycles"
assert_contains "$out" "{not json" "the unreadable file is left untouched"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
def boom(): raise RuntimeError("verify blew up")
stub(); foh.verify = boom
foh.run_cycle(WEDGED, now=8000); r = foh.run_cycle(WEDGED, now=8300)
print("survived", r["decision"])
s = foh.load_state(); print("persisted", len(s["attempts"]), s["counters"]["attempts"], "esc", s["counters"]["escalations"])
print(foh.run_cycle(WEDGED, now=8420)["decision"], len(calls))
' | MUTATIONS_OFF=0 _py)
assert_contains "$out" "survived healed: failed" "a crashing verify cannot abort the bookkeeping"
assert_contains "$out" "persisted 1 1 esc 1" "attempt on disk + escalated (PoE state unknown after the cycle)"
assert_contains "$out" "backoff (recent attempt, cooling down) 1" "next run backs off; still one cycle"
end_test

# ── T11d review fixes: unconfirmed ASA never acts; a gate lifting needs fresh runs; PoE-admin check ─
start_test "unconfirmed_asa_and_fresh_runs_after_gate_and_poe_admin_check"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
stub()
UNCONF = {"switch": SW_WEDGED, "asa": {"ok": False}}
for t in (9000, 9300, 9600): r = foh.run_cycle(UNCONF, now=t)
print("unconf", r["state"], r["decision"], len(calls))
' | MUTATIONS_OFF=0 _py)
assert_contains "$out" "unconf unconfirmed no action (unconfirmed: probe failed" "Track 1 unreadable -> no action"
assert_contains "$out" " 0" "zero PoE cycles while unconfirmed"
assert_contains "$(cat "$PROM")" "freedom_ont_autoheal_wedged 1" "but the signature is still reported (FreedomOntWedged can fire)"
reset_world
out=$(echo '
stub()
for t in (10000, 10300, 10600): foh.run_cycle(WEDGED, now=t)      # disarmed for 10 min
open(os.path.join(os.environ["GATEWAY_HOME"], "gateway.freedom_ont_autoheal_armed"), "w").close()
print(foh.run_cycle(WEDGED, now=10720)["decision"], len(calls))
print(foh.run_cycle(WEDGED, now=10840)["decision"], len(calls))
' | MUTATIONS_OFF=0 _py)
assert_contains "$out" "wait (gates just opened: 1/2 un-gated runs) 0" "arming mid-episode: first open run waits"
assert_contains "$out" "healed: success 1" "second open run heals"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
stub(res={"link": False, "track": False, "poe_admin": "off"})
foh.run_cycle(WEDGED, now=12000); r = foh.run_cycle(WEDGED, now=12300)
s = foh.load_state(); print(r["decision"], s["counters"]["escalations"])
' | MUTATIONS_OFF=0 _py)
assert_contains "$out" "healed: failed 1" "still dark + PoE admin not auto -> escalated at once"
assert_contains "$(cat "$FREEDOM_ONT_AUDIT_LOG")" "may be unpowered" "escalation says why"
reset_world
touch "$GATEWAY_HOME/gateway.freedom_ont_autoheal_armed"
out=$(echo '
foh.mutation_mode = None
print(foh.is_shadow())
' | MUTATIONS_OFF=1 _py)
assert_eq "True" "$out" "mutation_mode import failure falls back to the env/sentinel (fail closed)"
end_test

# ── T12 wiring ───────────────────────────────────────────────────────────────
start_test "wiring_and_syntax"
python3 -m py_compile "$HEAL" || fail_test "py_compile failed"
python3 -m py_compile "$REPO_ROOT/scripts/lib/ios_ssh.py" || fail_test "ios_ssh py_compile failed"
ms=$(cd "$REPO_ROOT/scripts" && python3 -c "
import importlib.util as u
s=u.spec_from_file_location('msw','gateway-master-switch.py'); m=u.module_from_spec(s); s.loader.exec_module(m)
w=['gateway.freedom_ont_autoheal_armed','gateway.mutations_freedom_ont_allow']
print(sum(x in m.ARMING_SENTINELS for x in w), sum(x in m.OFF_EXEMPT_SENTINELS for x in w))")
assert_eq "2 2" "$ms" "both sentinels in ARMING_SENTINELS (master-off removes them) and OFF_EXEMPT_SENTINELS (not drift while off)"
for h in "from ios_ssh import ssh_sw01_command" "from ios_ssh import sw01_poe_cycle" "from asa_ssh import ssh_nl_asa_netmiko_command"; do
  assert_contains "$(cat "$HEAL")" "$h" "netmiko device helper: $h"
done
assert_eq "0" "$(grep -cE 'pexpect|ssh_nl_asa_command\(' "$HEAL")" "no pexpect / pexpect-based ASA helper (netmiko only)"
assert_file_exists "$REPO_ROOT/docs/runbooks/freedom-ont-autoheal.md" "runbook present"
assert_file_exists "$REPO_ROOT/prometheus/alert-rules/freedom-ont-autoheal.yml" "alert rules present"
end_test

# ── T13 sw01_poe_cycle restores PoE even when the in-session restore fails ───
start_test "poe_cycle_primitive_restore_retry"
out=$(python3 - <<PYEOF
import sys
sys.path.insert(0, "$REPO_ROOT/scripts/lib")
import ios_ssh
sent = []
class Conn:
    def __init__(self, fail_on_restore): self.fail = fail_on_restore
    def enable(self): pass
    def send_config_set(self, cmds, read_timeout=30):
        if "power inline auto" in cmds and self.fail: raise OSError("socket closed")
        sent.append(tuple(cmds)); return ""
    def disconnect(self): pass
conns = [Conn(True), Conn(False)]
ios_ssh._sw01_connect = lambda timeout=30: conns.pop(0)
ok, detail = ios_ssh.sw01_poe_cycle("GigabitEthernet1/0/36", _sleep=lambda s: None)
print(ok, "retry 1" in detail, sent[0][1], sent[-1][1:4])
conns[:] = [Conn(True)] + [type("X", (), {"__init__": lambda s: None})() for _ in range(3)]
ios_ssh._sw01_connect = lambda timeout=30: (_ for _ in ()).throw(OSError("auth")) if not conns or not isinstance(conns[0], Conn) else conns.pop(0)
ok, detail = ios_ssh.sw01_poe_cycle("GigabitEthernet1/0/36", _sleep=lambda s: None)
print(ok, detail.startswith("POE-LEFT-OFF"))
# IOS rejects the off step in-band -> nothing changed, no restore/bounce
class Rej(Conn):
    def send_config_set(self, cmds, read_timeout=30):
        sent.append(tuple(cmds)); return "% Invalid input detected at '^' marker."
sent.clear(); conns[:] = [Rej(False)]
ios_ssh._sw01_connect = lambda timeout=30: conns.pop(0)
ok, detail = ios_ssh.sw01_poe_cycle("GigabitEthernet1/0/36", _sleep=lambda s: None)
print("offrej", ok, "nothing changed" in detail, len(sent))
# IOS rejects the in-session restore -> retried on a fresh session
class RejOn(Conn):
    def send_config_set(self, cmds, read_timeout=30):
        sent.append(tuple(cmds)); return "% Invalid input" if "power inline auto" in cmds else ""
sent.clear(); conns[:] = [RejOn(False), Conn(False)]
ok, detail = ios_ssh.sw01_poe_cycle("GigabitEthernet1/0/36", _sleep=lambda s: None)
print("onrej", ok, "retry 1" in detail)
PYEOF
)
assert_contains "$out" "True True power inline never ('power inline auto', 'shutdown', 'no shutdown')" "restore re-applied on a fresh session"
assert_contains "$out" "False True" "restore never applied -> POE-LEFT-OFF (escalation trigger)"
assert_contains "$out" "offrej False True 1" "IOS-rejected off step: nothing changed, no bounce"
assert_contains "$out" "onrej True True" "IOS-rejected restore: retried until accepted"
end_test

rm -rf "$TMP"
