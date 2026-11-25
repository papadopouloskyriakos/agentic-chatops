#!/bin/bash
# test-readonly-monitors.sh — READ-ONLY monitor classification in scripts/lib/suppression-gates.sh
# (IFRNLLEI01PRD-2992, NL power-loss postmortem item I).
#
# The master switch (~/gateway.maintenance, 2026-08-26) made every check_suppression_gates caller
# exit early, so pure monitors wrote nothing for 10 weeks. readonly_monitor_gate lets a monitor keep
# observing + writing metrics while gated; only its notification edge stays suppressed. This suite
# proves, structurally, that (a) the registered list is exactly the callers, (b) none of them carries
# an actuation verb, (c) every notification call sits behind the NOTIFY_SUPPRESSED exit, (d) the
# watchdog hands its consumer --observe-only while gated, and (e) actuators still exit early.
# Never touches live sentinels, never runs a monitor against a device.
# QA_SUITE_TIMEOUT: 60
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-readonly-monitors"
GATES="$REPO_ROOT/scripts/lib/suppression-gates.sh"
TMP="$(mktemp -d)"

listed=$(bash -c "source '$GATES'; echo \$READONLY_MONITORS" | tr ' ' '\n' | sort)

# ── T1 the registered list == the scripts that call readonly_monitor_gate ────
start_test "registry_matches_callers"
callers=$(grep -l '^readonly_monitor_gate; NOTIFY_SUPPRESSED=\$?' "$REPO_ROOT"/scripts/*.sh | xargs -n1 basename | sort)
assert_eq "$listed" "$callers" "READONLY_MONITORS lists exactly the callers"
assert_contains "$listed" "budget-pppoe-health.sh" "budget-pppoe-health registered"
assert_contains "$listed" "vps-route-health.sh" "vps-route-health registered"
assert_contains "$listed" "bgp-mesh-watchdog.sh" "bgp-mesh-watchdog registered"
end_test

# ── T2 no listed monitor exits early on the gate any more ────────────────────
start_test "monitors_do_not_exit_on_gate"
for f in $listed; do
  assert_eq "0" "$(grep -c 'check_suppression_gates || exit' "$REPO_ROOT/scripts/$f")" "$f has no early gate exit"
  bash -n "$REPO_ROOT/scripts/$f" || fail_test "bash -n failed: $f"
done
end_test

# ── T3 no actuation verb anywhere in a listed monitor (comments stripped) ────
start_test "monitors_carry_no_actuation_verb"
ACT='send_config_set|_config\(|_exec\(|conf t|configure terminal|clear crypto|vpn-sessiondb|power inline|no shutdown|systemctl (restart|stop|start|reload)|pct (stop|start|reboot|set|resize)|qm (stop|start|reboot|set)|kubectl (apply|delete|patch|scale|rollout)|ip route (add|del|replace|flush)|sudo |crontab -'
for f in $listed; do
  hits=$(grep -vE '^\s*#' "$REPO_ROOT/scripts/$f" | grep -cE "$ACT")
  assert_eq "0" "$hits" "$f: no actuation verb"
done
end_test

# ── T4 every notification call sits AFTER the NOTIFY_SUPPRESSED exit ─────────
start_test "notifications_behind_the_gate"
for f in $listed; do
  path="$REPO_ROOT/scripts/$f"
  gate_line=$(grep -n 'if \[ "\$NOTIFY_SUPPRESSED" -ne 0 \]; then' "$path" | head -1 | cut -d: -f1)
  calls=$(grep -nE '^\s*(send_sms|ntfy_publish|post_matrix|notify_matrix) ' "$path" | cut -d: -f1)
  if [ -z "$calls" ]; then
    continue   # no notification edge (the watchdog): T5 covers its gated behaviour
  fi
  [ -n "$gate_line" ] || { fail_test "$f notifies but has no NOTIFY_SUPPRESSED exit"; continue; }
  for c in $calls; do
    [ "$c" -gt "$gate_line" ] || fail_test "$f: notification at line $c precedes the gate exit at $gate_line"
  done
  # the metrics write must come BEFORE the gate exit (that is the whole point)
  w=$(grep -nE '^write_prom ' "$path" | head -1 | cut -d: -f1)
  [ -n "$w" ] && [ "$w" -lt "$gate_line" ] || fail_test "$f: write_prom must run before the gate exit"
done
end_test

# ── T5 the watchdog hands its consumer --observe-only while gated ────────────
start_test "watchdog_consumer_observe_only_when_gated"
wd="$REPO_ROOT/scripts/bgp-mesh-watchdog.sh"
assert_contains "$(cat "$wd")" '[ "$NOTIFY_SUPPRESSED" -ne 0 ] && consumer_args+=(--observe-only)' "observe-only wiring"
assert_contains "$(cat "$REPO_ROOT/scripts/intersite-tunnel-heal.py")" '"--observe-only"' "consumer accepts --observe-only"
end_test

# ── T6 readonly_monitor_gate semantics: same verdict as the gate, never exits ─
start_test "gate_function_semantics"
mkdir -p "$TMP/home"
rc_gate=$(HOME="$TMP/home" bash -c "source '$GATES'; check_suppression_gates; echo \$?")
out=$(HOME="$TMP/home" bash -c "source '$GATES'; readonly_monitor_gate; echo rc=\$?; echo still-running")
assert_contains "$out" "rc=$rc_gate" "same verdict as check_suppression_gates"
assert_contains "$out" "still-running" "never exits the caller"
mkdir -p "$TMP/home/chaos-state"; echo '{}' > "$TMP/home/chaos-state/chaos-active.json"
out=$(HOME="$TMP/home" bash -c "source '$GATES'; readonly_monitor_gate; echo rc=\$?")
assert_contains "$out" "rc=1" "chaos marker -> notifications suppressed"
rc_shadow=$(HOME="$TMP/home" MUTATIONS_OFF=1 bash -c "source '$GATES'; readonly_monitor_gate; echo \$?")
assert_eq "1" "$rc_shadow" "shadow mode does not change the verdict (chaos still wins)"
end_test

# ── T7 actuators keep exiting early and are NOT classified read-only ─────────
start_test "actuators_still_gated"
for f in vti-freedom-recovery.sh vti-budget-recovery.sh freedom-qos-toggle.sh; do
  assert_ge "$(grep -c 'check_suppression_gates || exit 0' "$REPO_ROOT/scripts/$f")" "1" "$f still exits on the gate"
  assert_not_contains "$listed" "$f" "$f not in READONLY_MONITORS"
done
end_test

# ── T8 the revived Cisco reads are netmiko (2026-08-14 directive) ────────────
start_test "revived_monitors_use_netmiko_for_cisco"
for f in budget-pppoe-health.sh bgp-mesh-watchdog.sh; do
  assert_eq "0" "$(grep -cE 'ssh_nl_asa_command\(' "$REPO_ROOT/scripts/$f")" "$f: no pexpect NL ASA helper"
  assert_ge "$(grep -c 'ssh_nl_asa_netmiko_command' "$REPO_ROOT/scripts/$f")" "1" "$f: netmiko NL ASA helper"
done
end_test

rm -rf "$TMP"
