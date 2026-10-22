#!/usr/bin/env bash
# IFRNLLEI01PRD-1408 — territory-gate WIRING watchdog (scripts/check-territory-gate-wiring.sh).
#
# Asserts the invariant: while ~/gateway.territory_gate is ON, the PreToolUse hook must be wired
# in BOTH session-settings surfaces (interactive + dispatched) AND parse — else VIOLATION (exit
# 1 + metric=1). Gate OFF => allowed (enforcement intentionally disabled). Hermetic: all inputs
# (sentinel, settings files, hook path, metric dir) are temp + env-overridden.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1408-territory-wiring"
CHK="$REPO_ROOT/scripts/check-territory-gate-wiring.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

SENT="$T/sentinel"
WIRED="$T/wired.json";   printf '{"hooks":{"PreToolUse":[{"hooks":[{"command":"x/scripts/hooks/territory-gate.py"}]}]}}' > "$WIRED"
UNWIRED="$T/unwired.json"; printf '{"hooks":{}}' > "$UNWIRED"
GOODHOOK="$REPO_ROOT/scripts/hooks/territory-gate.py"
BADHOOK="$T/bad.py"; printf 'def (:\n' > "$BADHOOK"   # syntax error -> hook_parses=0

# rc <sentinel> <interactive> <dispatched> <hook> -> exit code (also writes metric to $T)
rc() {
  TERRITORY_GATE_SENTINEL="$1" INTERACTIVE_SETTINGS="$2" DISPATCHED_SETTINGS="$3" \
    TERRITORY_HOOK="$4" PROM_TEXTFILE_DIR="$T" bash "$CHK" >/dev/null 2>&1; echo $?
}
metric() { grep -E "^$1 " "$T/gateway_territory_gate_wiring.prom" 2>/dev/null | awk '{print $2}'; }

touch "$SENT"
start_test "wiring_ok_both_surfaces_wired"
  assert_eq 0 "$(rc "$SENT" "$WIRED" "$WIRED" "$GOODHOOK")" "gate ON + both wired + parses -> OK"
  assert_eq 0 "$(metric gateway_territory_gate_wiring_violation)" "violation metric 0"
end_test

start_test "wiring_violation_dispatched_unwired"
  assert_eq 1 "$(rc "$SENT" "$WIRED" "$UNWIRED" "$GOODHOOK")" "dispatched surface missing the hook -> VIOLATION"
  assert_eq 1 "$(metric gateway_territory_gate_wiring_violation)" "violation metric 1"
  assert_eq 0 "$(metric 'gateway_territory_gate_wired{surface="dispatched"}')" "dispatched wired metric 0"
end_test

start_test "wiring_violation_interactive_unwired"
  assert_eq 1 "$(rc "$SENT" "$UNWIRED" "$WIRED" "$GOODHOOK")" "interactive surface missing the hook -> VIOLATION"
end_test

start_test "wiring_violation_hook_unparseable"
  assert_eq 1 "$(rc "$SENT" "$WIRED" "$WIRED" "$BADHOOK")" "hook does not parse -> VIOLATION"
  assert_eq 0 "$(metric gateway_territory_gate_hook_parses)" "hook_parses metric 0"
end_test

start_test "wiring_gate_off_is_allowed_even_if_unwired"
  assert_eq 0 "$(rc "$T/nope" "$UNWIRED" "$UNWIRED" "$BADHOOK")" "sentinel OFF -> OK regardless of wiring"
  assert_eq 0 "$(metric gateway_territory_gate_sentinel_on)" "sentinel_on metric 0"
end_test

start_test "wiring_emits_freshness_timestamp"
  rc "$SENT" "$WIRED" "$WIRED" "$GOODHOOK" >/dev/null
  ts="$(metric gateway_territory_gate_wiring_last_run_timestamp)"
  [ -n "$ts" ] && [ "$ts" -gt 0 ] && pass "$QA_SUITE_NAME" "freshness timestamp emitted ($ts)" \
    || fail "$QA_SUITE_NAME" "no freshness timestamp metric"
end_test
