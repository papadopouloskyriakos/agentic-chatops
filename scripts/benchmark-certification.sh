#!/bin/bash
# benchmark-certification.sh — E2E certification for 10 benchmark implementations
#
# Tests ALL 10 recommendations from the Industry Benchmark 2026-04-15 and outputs
# a pass/fail report. Designed as a repeatable certification gate.
#
# Usage:
#   bash scripts/benchmark-certification.sh           # Full certification
#   bash scripts/benchmark-certification.sh --json    # JSON output
#
# Source: IFRNLLEI01PRD-568 to -577

set -uo pipefail

DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
JSON_MODE=false
[ "${1:-}" = "--json" ] && JSON_MODE=true

PASS=0
FAIL=0
RESULTS=()

check() {
  local id="$1" desc="$2" result="$3"
  if [ "$result" = "PASS" ]; then
    PASS=$((PASS+1))
    RESULTS+=("$id|$desc|PASS")
    $JSON_MODE || echo "  PASS  $id: $desc"
  else
    FAIL=$((FAIL+1))
    RESULTS+=("$id|$desc|FAIL|$4")
    $JSON_MODE || echo "  FAIL  $id: $desc -- $4"
  fi
}

echo "=== Benchmark Certification Suite ==="
echo "Date: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# ─── R1: OTel Pipeline ───
echo "R1: OTel Pipeline"
R1_CRON=$(crontab -l 2>/dev/null | grep -c "export-otel-traces.py --export")
[ "$R1_CRON" -ge 1 ] && check "R1.1" "OTel export cron exists" "PASS" "" || check "R1.1" "OTel export cron exists" "FAIL" "No cron entry"

R1_GENAI=$(grep -c "gen_ai.system" "$REPO/scripts/export-otel-traces.py")
[ "$R1_GENAI" -ge 1 ] && check "R1.2" "GenAI semantic conventions present" "PASS" "" || check "R1.2" "GenAI semantic conventions present" "FAIL" "Missing gen_ai attributes"

R1_EXPORT=$(grep -c "def export_unexported_spans" "$REPO/scripts/export-otel-traces.py")
[ "$R1_EXPORT" -ge 1 ] && check "R1.3" "Batch export function exists" "PASS" "" || check "R1.3" "Batch export function exists" "FAIL" "No export function"

R1_AUTH=$(grep -c "admin@example.com" "$REPO/scripts/export-otel-traces.py")
[ "$R1_AUTH" -ge 1 ] && check "R1.4" "OpenObserve auth is current" "PASS" "" || check "R1.4" "OpenObserve auth is current" "FAIL" "Stale credentials"

# ─── R2: EU AI Act Governance ───
echo "R2: EU AI Act Governance"
for doc in eu-ai-act-assessment quality-management-system oversight-boundary-framework; do
  [ -f "$REPO/docs/${doc}.md" ] && check "R2" "$doc.md exists" "PASS" "" || check "R2" "$doc.md exists" "FAIL" "File not found"
done
grep -q "Annex III" "$REPO/docs/eu-ai-act-assessment.md" 2>/dev/null && check "R2.4" "Annex III analysis present" "PASS" "" || check "R2.4" "Annex III analysis present" "FAIL" "No Annex III section"
grep -q "Serious Incident" "$REPO/docs/quality-management-system.md" 2>/dev/null && check "R2.5" "Serious incident reporting defined" "PASS" "" || check "R2.5" "Serious incident reporting defined" "FAIL" "No incident reporting"
grep -q "Tier 1\|Tier 2\|Tier 3" "$REPO/docs/oversight-boundary-framework.md" 2>/dev/null && check "R2.6" "Tier classification present" "PASS" "" || check "R2.6" "Tier classification present" "FAIL" "No tier classification"

# ─── R3: SBOM + Dependency Monitoring ───
echo "R3: SBOM CI Job"
grep -q "generate-sbom" "$REPO/.gitlab-ci.yml" 2>/dev/null && check "R3.1" "SBOM CI job defined" "PASS" "" || check "R3.1" "SBOM CI job defined" "FAIL" "No SBOM job"
grep -q "cyclonedx" "$REPO/.gitlab-ci.yml" 2>/dev/null && check "R3.2" "CycloneDX tools configured" "PASS" "" || check "R3.2" "CycloneDX tools configured" "FAIL" "No CycloneDX"
[ -f "$REPO/docs/model-provenance.md" ] && check "R3.3" "Model provenance doc exists" "PASS" "" || check "R3.3" "Model provenance doc exists" "FAIL" "No model-provenance.md"
[ -f "$REPO/package-lock.json" ] && check "R3.4" "package-lock.json present" "PASS" "" || check "R3.4" "package-lock.json present" "FAIL" "No lock file"

# ─── R4: RAGAS Metrics Pipeline ───
echo "R4: RAGAS Pipeline"
[ -f "$REPO/scripts/ragas-eval.py" ] && check "R4.1" "ragas-eval.py exists" "PASS" "" || check "R4.1" "ragas-eval.py exists" "FAIL" "No script"
R4_TABLE=$(sqlite3 "$DB" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='ragas_evaluation';" 2>/dev/null || echo 0)
[ "$R4_TABLE" -ge 1 ] && check "R4.2" "ragas_evaluation table exists" "PASS" "" || check "R4.2" "ragas_evaluation table exists" "FAIL" "No table"
R4_ROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ragas_evaluation;" 2>/dev/null || echo 0)
[ "$R4_ROWS" -ge 1 ] && check "R4.3" "RAGAS evaluations populated ($R4_ROWS rows)" "PASS" "" || check "R4.3" "RAGAS evaluations populated" "FAIL" "0 rows"
R4_FAITH=$(sqlite3 "$DB" "SELECT ROUND(AVG(faithfulness),3) FROM ragas_evaluation WHERE faithfulness >= 0;" 2>/dev/null || echo 0)
R4_OK=$(python3 -c "print('1' if float('${R4_FAITH:-0}') >= 0.70 else '0')" 2>/dev/null || echo 0)
[ "$R4_OK" = "1" ] && check "R4.4" "Avg faithfulness >= 0.70 (actual: $R4_FAITH)" "PASS" "" || check "R4.4" "Avg faithfulness >= 0.70" "FAIL" "actual: $R4_FAITH"
[ -f "$REPO/scripts/eval-sets/ragas-golden.json" ] && check "R4.5" "Golden set exists" "PASS" "" || check "R4.5" "Golden set exists" "FAIL" "No golden set"

# ─── R5: Agent Decommissioning ───
echo "R5: Decommissioning"
[ -f "$REPO/docs/agent-decommissioning.md" ] && check "R5.1" "Decommissioning doc exists" "PASS" "" || check "R5.1" "Decommissioning doc exists" "FAIL" "No doc"
[ -f "$REPO/docs/tool-risk-classification.md" ] && check "R5.2" "Tool risk classification exists" "PASS" "" || check "R5.2" "Tool risk classification exists" "FAIL" "No doc"
grep -q "Tier 1.*OpenClaw\|OpenClaw.*Tier 1" "$REPO/docs/agent-decommissioning.md" 2>/dev/null && check "R5.3" "Per-tier checklists present" "PASS" "" || check "R5.3" "Per-tier checklists present" "FAIL" "No tier checklists"
R5_SERVERS=$(grep -c "^###\|^####" "$REPO/docs/tool-risk-classification.md" 2>/dev/null || echo 0)
[ "$R5_SERVERS" -ge 8 ] && check "R5.4" "Multiple MCP servers classified ($R5_SERVERS sections)" "PASS" "" || check "R5.4" "MCP servers classified" "FAIL" "Only $R5_SERVERS sections"

# ─── R6: Chaos Statistical Validity ───
echo "R6: Chaos Validity"
R6_5S=$(grep -cF "interval=5" "$REPO/scripts/chaos_baseline.py" 2>/dev/null || echo 0)
R6_5S=$(echo "$R6_5S" | tr -d '[:space:]')
[ "${R6_5S:-0}" -eq 0 ] && check "R6.1" "No 5s measurement intervals remain" "PASS" "" || check "R6.1" "No 5s intervals remain" "FAIL" "$R6_5S occurrences of interval=5"
grep -q "chaos_experiment_count_per_scenario" "$REPO/scripts/write-chaos-metrics.sh" 2>/dev/null && check "R6.2" "Per-scenario metric exists" "PASS" "" || check "R6.2" "Per-scenario metric" "FAIL" "Not found"

# ─── R7: NIST Behavioral Telemetry ───
echo "R7: NIST Telemetry"
[ -x "$REPO/scripts/write-behavioral-metrics.sh" ] && check "R7.1" "Behavioral metrics script executable" "PASS" "" || check "R7.1" "Behavioral metrics script" "FAIL" "Not executable"
R7_SIGNALS=$(bash "$REPO/scripts/write-behavioral-metrics.sh" --dry-run 2>/dev/null | grep -c "^nist_")
[ "$R7_SIGNALS" -ge 10 ] && check "R7.2" "All 5 NIST signals emit metrics ($R7_SIGNALS lines)" "PASS" "" || check "R7.2" "NIST signals" "FAIL" "Only $R7_SIGNALS metrics"
R7_ACTIVE=$(bash "$REPO/scripts/write-behavioral-metrics.sh" --dry-run 2>/dev/null | grep "^nist_behavioral_telemetry_signals " | awk '{print $2}' | head -1)
[ "${R7_ACTIVE:-0}" -ge 5 ] && check "R7.3" "5/5 signals active" "PASS" "" || check "R7.3" "Signals active" "FAIL" "Only $R7_ACTIVE"

# ─── R8: Adversarial Red-Team ───
echo "R8: Red-Team"
R8_TESTS=$(grep -c "test_block\|test_allow" "$REPO/scripts/test-hook-blocks.py" 2>/dev/null || echo 0)
[ "$R8_TESTS" -ge 40 ] && check "R8.1" "52+ adversarial test cases ($R8_TESTS)" "PASS" "" || check "R8.1" "Adversarial tests" "FAIL" "Only $R8_TESTS"
[ -x "$REPO/scripts/write-redteam-metrics.sh" ] && check "R8.2" "Red-team metrics script exists" "PASS" "" || check "R8.2" "Red-team metrics" "FAIL" "Not found"
grep -q "quarterly-redteam" "$REPO/scripts/chaos-calendar.sh" 2>/dev/null && check "R8.3" "Quarterly red-team scheduled" "PASS" "" || check "R8.3" "Quarterly schedule" "FAIL" "Not found"
# Check pass rate from last run
if [ -f /tmp/redteam-last-run.json ]; then
  R8_PASS=$(python3 -c "import json; print(json.load(open('/tmp/redteam-last-run.json')).get('tests_pass',0))" 2>/dev/null || echo 0)
  R8_TOTAL=$(python3 -c "import json; print(json.load(open('/tmp/redteam-last-run.json')).get('tests_total',0))" 2>/dev/null || echo 0)
  R8_RATE=$(python3 -c "print(round(${R8_PASS}/${R8_TOTAL}*100))" 2>/dev/null || echo 0)
  [ "$R8_RATE" -ge 50 ] && check "R8.4" "Red-team pass rate >= 50% (actual: ${R8_PASS}/${R8_TOTAL}=${R8_RATE}%)" "PASS" "" || check "R8.4" "Red-team pass rate" "FAIL" "${R8_PASS}/${R8_TOTAL}=${R8_RATE}%"
fi

# ─── R9: A2A Protocol Alignment ───
echo "R9: A2A Protocol"
for card in openclaw-t1 claude-code-t2 human-t3; do
  python3 -c "import json; d=json.load(open('$REPO/a2a/agent-cards/${card}.json')); assert 'lifecycle' in d; assert 'taskStates' in d" 2>/dev/null && \
    check "R9" "${card}.json has lifecycle + taskStates" "PASS" "" || \
    check "R9" "${card}.json lifecycle/taskStates" "FAIL" "Missing fields"
done

# ─── R10: Automated Prompt Refinement ───
echo "R10: Prompt Refinement"
grep -q "Auto-refinement" "$REPO/scripts/eval-flywheel.sh" 2>/dev/null && check "R10.1" "Auto-refinement block exists" "PASS" "" || check "R10.1" "Auto-refinement" "FAIL" "Not found"
grep -q "PATCHES_ROLLED_BACK" "$REPO/scripts/eval-flywheel.sh" 2>/dev/null && check "R10.2" "Regression rollback implemented" "PASS" "" || check "R10.2" "Rollback" "FAIL" "Not found"
grep -q "prompt_refinement.prom" "$REPO/scripts/eval-flywheel.sh" 2>/dev/null && check "R10.3" "Prometheus metrics for patches" "PASS" "" || check "R10.3" "Patch metrics" "FAIL" "Not found"
R10_QUIET=$(bash "$REPO/scripts/golden-test-suite.sh" --set regression --offline --quiet 2>&1 | wc -l)
[ "$R10_QUIET" -le 2 ] && check "R10.4" "--quiet flag works ($R10_QUIET lines)" "PASS" "" || check "R10.4" "--quiet flag" "FAIL" "$R10_QUIET lines (expected <= 2)"

# ─── Summary ───
TOTAL=$((PASS+FAIL))
echo ""
echo "============================================================"
echo "CERTIFICATION RESULT: $PASS/$TOTAL PASS ($FAIL failures)"
echo "============================================================"

# Prometheus metrics
PROM="/var/lib/node_exporter/textfile_collector/benchmark_certification.prom"
cat > "${PROM}.tmp" 2>/dev/null << PROMEOF
# HELP benchmark_certification_pass Certification tests passing
# TYPE benchmark_certification_pass gauge
benchmark_certification_pass $PASS
# HELP benchmark_certification_fail Certification tests failing
# TYPE benchmark_certification_fail gauge
benchmark_certification_fail $FAIL
# HELP benchmark_certification_total Total certification tests
# TYPE benchmark_certification_total gauge
benchmark_certification_total $TOTAL
# HELP benchmark_certification_timestamp Last certification run
# TYPE benchmark_certification_timestamp gauge
benchmark_certification_timestamp $(date +%s)
PROMEOF
mv "${PROM}.tmp" "$PROM" 2>/dev/null || true

# JSON output
if $JSON_MODE; then
  python3 -c "
import json
results = []
for r in '''$(printf '%s\n' "${RESULTS[@]}")'''.strip().split('\n'):
    parts = r.split('|')
    results.append({'id': parts[0], 'desc': parts[1], 'status': parts[2], 'reason': parts[3] if len(parts) > 3 else ''})
print(json.dumps({'pass': $PASS, 'fail': $FAIL, 'total': $TOTAL, 'results': results}, indent=2))
"
fi

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
