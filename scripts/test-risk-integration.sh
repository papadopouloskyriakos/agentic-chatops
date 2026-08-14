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
    # IFRNLLEI01PRD-1153: the harness now runs against an ISOLATED temp DB (below), so it
    # never writes INTEGRATION-TEST rows to the live governance log — nothing to clean in
    # production. Deleting live audit rows is what broke the tamper-evident hash-chain
    # (GovernanceChainBroken, 2026-06-27), so --cleanup no longer touches the live DB.
    echo "test-risk-integration.sh is isolated (temp DB) — no production INTEGRATION-TEST rows to clean."
    exit 0
fi

# IFRNLLEI01PRD-1153/-632: run against an ISOLATED temp DB, NEVER the live gateway.db.
# Writing INTEGRATION-TEST audit rows into the live session_risk_audit (and later deleting
# them) broke the tamper-evident governance hash-chain on 2026-06-27. classify-session-risk.py
# honours GATEWAY_DB, so an isolated copy of the table's schema keeps the harness fully
# self-contained — the live governance log is never written.
_LIVE_DB="/app/cubeos/claude-context/gateway.db"
GATEWAY_DB="$(mktemp -t risk-integ.XXXXXX.db)"
export GATEWAY_DB
trap 'rm -f "$GATEWAY_DB"' EXIT
sqlite3 "$_LIVE_DB" ".schema session_risk_audit" | sqlite3 "$GATEWAY_DB"

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

    # Carve-dependent cases (IFRNLLEI01PRD-1102): the conservative-remediation carve — active only under
    # BOTH the autonomy_forward and conservative_remediation sentinels (autonomy also honours an env flag)
    # — downgrades reversible restarts (M1 DMZ container restart, H2 systemctl restart). Both bands are
    # legitimate depending on that gate, so accept EITHER valid outcome instead of re-implementing the
    # Python gate in bash. A regression to an INVALID band (e.g. M1 -> high) is still caught.
    accept="$expected"
    [ "$id" = "M1" ] && accept="mixed low"
    # H2 (systemctl restart n8n) is deterministically HIGH: the self-protected veto keeps the carve off the
    # gateway's own control plane, so restarting n8n POLLs in BOTH carve states. Strict = it tests the veto.

    result=$(echo "$plan" | python3 scripts/classify-session-risk.py \
        --category "$category" --issue-id "$ISSUE_ID" $AUDIT_FLAG 2>/dev/null)
    got=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('risk_level','?'))")

    if echo " $accept " | grep -qw "$got"; then
        echo "  [ok]   $id  cat=$category  risk=$got"
        PASS=$((PASS + 1))
    else
        signals=$(echo "$result" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('signals', [])))" 2>/dev/null)
        echo "  [FAIL] $id  cat=$category  got=$got  expected=$accept"
        echo "         signals: $signals"
        FAIL=$((FAIL + 1))
    fi
done

echo
echo "=== result: $PASS / ${#CASES[@]} pass ==="

# ── IFRNLLEI01PRD-1448: OOD / novel-incident gate ───────────────────────────────
# A genuinely NOVEL incident class (explicit prior_incidents==0) must NOT auto-resolve:
# under AUTONOMY_FORWARD the band is forced to POLL_PAUSE with an `ood:novel-incident`
# signal. A KNOWN class (prior_incidents>0) is unaffected. With the flag OFF the output
# stays byte-identical legacy (no band, no ood signal). These run --no-audit (band/ood
# logic is independent of the audit write) so they never pollute the audit table.
echo
echo "--- OOD novel-incident gate (IFRNLLEI01PRD-1448) ---"
_RO_PLAN='{"hypothesis":"flap","steps":[{"description":"kubectl get pods -A"}],"tools_needed":["kubectl get"]}'

# Novel + flag ON -> POLL_PAUSE + ood signal
out=$(echo "$_RO_PLAN" | sed 's/{"hypothesis"/{"prior_incidents":0,"hypothesis"/' \
    | AUTONOMY_FORWARD=1 ALERT_HOSTNAME=oodnovel01 INFRAGRAPH_DISABLED=1 \
      python3 scripts/classify-session-risk.py --category availability --no-audit 2>/dev/null)
band=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin).get('band','-'))")
hasood=$(echo "$out" | python3 -c "import sys,json;print(any(s.startswith('ood:novel-incident') for s in json.load(sys.stdin).get('signals',[])))")
if [ "$band" = "POLL_PAUSE" ] && [ "$hasood" = "True" ]; then
    echo "  [ok]   OOD-NOVEL  prior_incidents=0  band=POLL_PAUSE + ood signal"; PASS=$((PASS + 1))
else
    echo "  [FAIL] OOD-NOVEL  got band=$band ood=$hasood (expected POLL_PAUSE + ood signal)"; FAIL=$((FAIL + 1))
fi

# Known + flag ON -> AUTO, NO ood signal (gate must not over-fire)
out=$(echo "$_RO_PLAN" | sed 's/{"hypothesis"/{"prior_incidents":7,"hypothesis"/' \
    | AUTONOMY_FORWARD=1 ALERT_HOSTNAME=oodknown01 INFRAGRAPH_DISABLED=1 \
      python3 scripts/classify-session-risk.py --category availability --no-audit 2>/dev/null)
band=$(echo "$out" | python3 -c "import sys,json;print(json.load(sys.stdin).get('band','-'))")
hasood=$(echo "$out" | python3 -c "import sys,json;print(any(s.startswith('ood:') for s in json.load(sys.stdin).get('signals',[])))")
if [ "$band" = "AUTO" ] && [ "$hasood" = "False" ]; then
    echo "  [ok]   OOD-KNOWN  prior_incidents=7  band=AUTO, no ood signal"; PASS=$((PASS + 1))
else
    echo "  [FAIL] OOD-KNOWN  got band=$band ood=$hasood (expected AUTO, no ood)"; FAIL=$((FAIL + 1))
fi

# Novel + flag OFF -> byte-identical legacy (no band key, no ood signal)
out=$(echo "$_RO_PLAN" | sed 's/{"hypothesis"/{"prior_incidents":0,"hypothesis"/' \
    | AUTONOMY_FORWARD=0 ALERT_HOSTNAME=oodnovel01 INFRAGRAPH_DISABLED=1 \
      python3 scripts/classify-session-risk.py --category availability --no-audit 2>/dev/null)
legacy=$(echo "$out" | python3 -c "import sys,json;d=json.load(sys.stdin);print('band' not in d and not any(s.startswith('ood:') for s in d.get('signals',[])))")
if [ "$legacy" = "True" ]; then
    echo "  [ok]   OOD-OFF    flag-off legacy: no band, no ood signal"; PASS=$((PASS + 1))
else
    echo "  [FAIL] OOD-OFF    flag-off emitted band/ood (not byte-identical legacy)"; FAIL=$((FAIL + 1))
fi

# Invariant check (band-aware, IFRNLLEI01PRD-1102): an auto_approved row is unsafe only if it is a
# LEGACY row (band NULL, autonomy-forward off) with risk != low, OR an AUTONOMY row whose band is not an
# auto band (AUTO/AUTO_NOTICE). Mirrors the authoritative scripts/audit-risk-decisions.sh — the
# conservative-remediation carve legitimately auto-approves reversible MIXED actions under band=AUTO.
if [ -z "$AUDIT_FLAG" ]; then
    v=$(sqlite3 "$GATEWAY_DB" \
        "SELECT COUNT(*) FROM session_risk_audit WHERE issue_id LIKE 'INTEGRATION-TEST-%' AND auto_approved = 1 AND ((band IS NULL AND risk_level != 'low') OR (band IS NOT NULL AND band NOT IN ('AUTO','AUTO_NOTICE')))" 2>/dev/null)
    if [ "$v" -gt 0 ]; then
        echo "  [FAIL] audit invariant violated: $v auto_approved row(s) outside AUTO/AUTO_NOTICE band (or legacy non-low)"
        FAIL=$((FAIL + 1))
    else
        echo "  [ok]   audit invariant holds across integration rows"
    fi
fi

exit $([ $FAIL -eq 0 ] && echo 0 || echo 1)
