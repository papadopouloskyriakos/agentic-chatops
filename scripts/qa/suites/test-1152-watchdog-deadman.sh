#!/usr/bin/env bash
# IFRNLLEI01PRD-1152 — control-plane dead-man's-switch.
# gateway-watchdog.sh emits a heartbeat + per-workflow/n8n-health gauges; a
# Prometheus absent()-or-stale alert routed to Twilio SMS pages the operator when
# the watchdog itself goes dark. CI-safe: static contract only, no live infra.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1152-watchdog-deadman"

WD="$REPO_ROOT/scripts/gateway-watchdog.sh"
YML="$REPO_ROOT/prometheus/alert-rules/agentic-health.yml"
HH="$REPO_ROOT/scripts/holistic-agentic-health.sh"

# Single source of truth for the YAML assertions (CI has python3+pyyaml).
rules_check() {
  python3 - "$YML" "$1" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
rules = {r['alert']: r for g in d['groups'] for r in g['rules']}
mode = sys.argv[2]
if mode == "sms_labels":
    ok = all(
        rules.get(n) and str(rules[n]['labels'].get('tier')) == '1'
        and rules[n]['labels'].get('severity') == 'critical'
        for n in ('GatewayWatchdogHeartbeatStale', 'GatewayWorkflowInactive'))
    print("OK" if ok else "BAD")
elif mode == "absent_clause":
    e = rules.get('GatewayWatchdogHeartbeatStale', {}).get('expr', '')
    print("OK" if 'absent(gateway_watchdog_heartbeat_timestamp_seconds)' in e else "MISSING")
elif mode == "no_watchdog_name":
    print(sum(1 for n in rules if n == 'Watchdog'))
PY
}

start_test "watchdog_script_syntax_ok"
  assert_eq "PASS" "$(bash -n "$WD" 2>/dev/null && echo PASS || echo FAIL)"
end_test

start_test "watchdog_emits_heartbeat_via_trap"
  has_trap=$(grep -cE "trap emit_metrics EXIT" "$WD")
  has_hb=$(grep -cE "gateway_watchdog_heartbeat_timestamp_seconds\{host=" "$WD")
  has_rec=$(grep -cE "^record_gauge\(\)" "$WD")
  assert_eq "1 1 1" "$has_trap $has_hb $has_rec"
end_test

start_test "watchdog_records_n8n_and_workflow_gauges"
  n8n=$(grep -cE "record_gauge \"gateway_n8n_healthy [01]\"" "$WD")
  wf=$(grep -cE "record_gauge \"gateway_workflow_active\{workflow=" "$WD")
  assert_eq "OK" "$([ "$n8n" -ge 2 ] && [ "$wf" -ge 3 ] && echo OK || echo "n8n=$n8n wf=$wf")"
end_test

start_test "alert_rules_present_with_sms_routing_labels"
  assert_eq "OK" "$(rules_check sms_labels)"
end_test

start_test "heartbeat_alert_has_absent_clause"
  assert_eq "OK" "$(rules_check absent_clause)"
end_test

start_test "alert_not_named_Watchdog_blackhole_guard"
  assert_eq "0" "$(rules_check no_watchdog_name)"
end_test

start_test "holistic_health_asserts_watchdog_deadman"
  assert_eq "OK" "$(grep -q 'watchdog-deadman' "$HH" && grep -q 'gateway_watchdog_heartbeat_timestamp_seconds' "$HH" && echo OK || echo MISSING)"
end_test
