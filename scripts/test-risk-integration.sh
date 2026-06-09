#!/bin/bash
# test-risk-integration.sh — IFRNLLEI01PRD-632 integration replay harness.
#
# Feeds 10 pre-constructed plans through classify-session-risk.py and asserts
# the risk_level matches the expected tier. Deterministic — plans are static
# rather than Haiku-generated, which eliminates non-repeatable test failures
# from the planner's stochastic output.
#
# Exits 0 if all 10 assertions pass, non-zero on any failure.
# Writes audit rows to session_risk_audit with issue_id prefix
# INTEGRATION-TEST-* so they can be filtered out of production reports.
#
# Usage:
#   scripts/test-risk-integration.sh             # run all 10 (writes audit rows)
#   scripts/test-risk-integration.sh --dry-run   # skip audit rows
#   scripts/test-risk-integration.sh --cleanup   # delete INTEGRATION-TEST-* rows

set -u
cd "$(dirname "$0")/.."
MODE="${1:-}"

if [ "$MODE" = "--cleanup" ]; then
    sqlite3 /app/cubeos/claude-context/gateway.db \
        "DELETE FROM session_risk_audit WHERE issue_id LIKE 'INTEGRATION-TEST-%'"
    echo "cleaned up INTEGRATION-TEST-* rows"
    exit 0
fi

AUDIT_FLAG=""
[ "$MODE" = "--dry-run" ] && AUDIT_FLAG="--no-audit"

# Case format: TEST_ID|category|expected|plan_json
# Plans are deliberately minimal — each exercises one classifier signal path
# so we can tell which rule fired if anything regresses.
CASES=(
    # Pure read-only plans across LOW-lean categories — no AWX, no mutation verbs
    'L1|availability|low|{"hypothesis":"Device flapping","steps":[{"description":"kubectl get pods -A and find NotReady"},{"description":"kubectl logs on the failing pod"}],"tools_needed":["kubectl get","kubectl logs"]}'
    'L2|resource|low|{"hypothesis":"CPU spike","steps":[{"description":"Run ps aux and top to find heavy process"},{"description":"journalctl --since 1h on the host"}],"tools_needed":["ps","journalctl"]}'
    'L3|certificate|low|{"hypothesis":"Cert expiring","steps":[{"description":"openssl s_client -connect host:443 </dev/null | openssl x509 -noout -dates"}],"tools_needed":["openssl"]}'
    'L4|generic|low|{"hypothesis":"General triage","steps":[{"description":"Read CLAUDE.md for runbook"},{"description":"grep /var/log for errors"}],"tools_needed":["grep"]}'

    # AWX-referenced plans → MIXED (plan gestures at mutation path even if dry_run)
    'M1|availability|mixed|{"hypothesis":"DMZ container unhealthy","steps":[{"description":"Check status"}],"tools_needed":["kubectl get"],"awx_templates":[{"id":64,"name":"DMZ container restart"}]}'
    'M2|kubernetes|mixed|{"hypothesis":"Pod issue","steps":[{"description":"Investigate"}],"awx_templates":[{"id":71,"name":"K8s node drain"}]}'

    # Explicit mutation verbs → HIGH
    'H1|availability|high|{"hypothesis":"Stale config","steps":[{"description":"Run kubectl apply -f k8s/config.yaml to reconcile"}],"tools_needed":["kubectl apply"]}'
    'H2|resource|high|{"hypothesis":"Service hung","steps":[{"description":"systemctl restart n8n to clear the hang"}],"tools_needed":["systemctl"]}'

    # Category-driven HIGH → regardless of plan content
    'H3|maintenance|high|{"hypothesis":"Scheduled reboot","steps":[{"description":"Check preflight"}],"tools_needed":["uptime"]}'
    'H4|security-incident|high|{"hypothesis":"Intrusion attempt","steps":[{"description":"Check CrowdSec decisions"}],"tools_needed":["cscli"]}'
)

PASS=0
FAIL=0

echo "=== IFRNLLEI01PRD-632 integration replay harness (classifier path) ==="
echo "Running ${#CASES[@]} deterministic cases"
echo

for case in "${CASES[@]}"; do
    IFS='|' read -r id category expected plan <<< "$case"
    ISSUE_ID="INTEGRATION-TEST-${id}"

    result=$(echo "$plan" | python3 scripts/classify-session-risk.py \
        --category "$category" --issue-id "$ISSUE_ID" $AUDIT_FLAG 2>/dev/null)
    got=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('risk_level','?'))")

    if [ "$got" = "$expected" ]; then
        echo "  [ok]   $id  cat=$category  risk=$got"
        PASS=$((PASS + 1))
    else
        signals=$(echo "$result" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('signals', [])))" 2>/dev/null)
        echo "  [FAIL] $id  cat=$category  got=$got  expected=$expected"
        echo "         signals: $signals"
        FAIL=$((FAIL + 1))
    fi
done

echo
echo "=== result: $PASS / ${#CASES[@]} pass ==="

# Invariant check: no INTEGRATION-TEST-* row should have auto_approved=1 with risk_level != low
if [ -z "$AUDIT_FLAG" ]; then
    v=$(sqlite3 /app/cubeos/claude-context/gateway.db \
        "SELECT COUNT(*) FROM session_risk_audit WHERE issue_id LIKE 'INTEGRATION-TEST-%' AND auto_approved = 1 AND risk_level != 'low'" 2>/dev/null)
    if [ "$v" -gt 0 ]; then
        echo "  [FAIL] audit invariant violated: $v row(s) auto_approved with risk != low"
        FAIL=$((FAIL + 1))
    else
        echo "  [ok]   audit invariant holds across integration rows"
    fi
fi

exit $([ $FAIL -eq 0 ] && echo 0 || echo 1)
