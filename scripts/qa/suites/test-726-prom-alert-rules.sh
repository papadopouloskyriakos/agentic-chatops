#!/usr/bin/env bash
# IFRNLLEI01PRD-712 hardening — exercise Prometheus alert rules under
# synthetic time-series via promtool test rules. Runs against the live
# Prom pod (prometheus-monitoring-kube-prometheus-prometheus-0) since
# promtool isn't installed on app-user host.
#
# Skips if the Prom pod isn't reachable — this is a best-effort hardening
# test, not a hard gate.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="726-prom-alert-rules"

POD=prometheus-monitoring-kube-prometheus-prometheus-0
NS=monitoring

_pod_exists() {
  kubectl -n "$NS" get pod "$POD" --no-headers 2>/dev/null | grep -q Running
}

# ─── T1 Prom pod reachable + promtool installed ─────────────────────────
start_test "prom_pod_reachable_and_promtool_present"
  if ! _pod_exists; then
    skip_test "prometheus-monitoring pod not running on this cluster"
  else
    if ! kubectl -n "$NS" exec "$POD" -c prometheus -- /bin/promtool --version >/dev/null 2>&1; then
      fail_test "promtool not runnable in pod $POD"
    fi
  fi
end_test

# ─── T2 agentic-health.yml passes syntax check ──────────────────────────
start_test "agentic_health_rules_syntax"
  if ! _pod_exists; then
    skip_test "pod unavailable"
  else
    out=$(cat "$REPO_ROOT/prometheus/alert-rules/agentic-health.yml" | \
      kubectl -n "$NS" exec -i "$POD" -c prometheus -- /bin/promtool check rules /dev/stdin 2>&1)
    if echo "$out" | grep -q 'SUCCESS'; then
      :
    else
      fail_test "promtool check rules failed: $out"
    fi
  fi
end_test

# ─── T3 alert rules fire under synthetic time-series (the core test) ───
start_test "alert_rules_fire_under_synthetic_conditions"
  if ! _pod_exists; then
    skip_test "pod unavailable"
  else
    # Stage rule + test file together, run promtool test rules, cleanup
    TEST_OUTPUT=$(tar -C "$REPO_ROOT/prometheus/alert-rules" -cf - agentic-health.yml agentic-health.test.yml 2>/dev/null | \
      kubectl -n "$NS" exec -i "$POD" -c prometheus -- sh -c '
        cd /prometheus &&
        tar -xf - &&
        TMPDIR=/prometheus /bin/promtool test rules agentic-health.test.yml 2>&1
        RC=$?
        rm -f agentic-health.yml agentic-health.test.yml
        exit $RC
      ' 2>&1)
    if echo "$TEST_OUTPUT" | grep -q 'SUCCESS'; then
      :
    else
      # Truncate output — promtool on FAIL emits large diffs
      snippet=$(echo "$TEST_OUTPUT" | head -c 400 | tr '\n' ' ')
      fail_test "promtool test rules failed: $snippet"
    fi
  fi
end_test

# ─── T4 test file exists + is loadable YAML ─────────────────────────────
start_test "test_file_exists_and_parses"
  if [ ! -f "$REPO_ROOT/prometheus/alert-rules/agentic-health.test.yml" ]; then
    fail_test "agentic-health.test.yml missing"
  elif ! python3 -c "import yaml; yaml.safe_load(open('$REPO_ROOT/prometheus/alert-rules/agentic-health.test.yml'))" >/dev/null 2>&1; then
    fail_test "agentic-health.test.yml is not valid YAML"
  fi
end_test
