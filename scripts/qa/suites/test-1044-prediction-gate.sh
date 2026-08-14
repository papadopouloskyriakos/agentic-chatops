#!/usr/bin/env bash
# IFRNLLEI01PRD-1044 — mandatory-prediction gate test suite.
# The bypass-attempt tests run against the gate code EXTRACTED FROM THE
# WORKFLOW EXPORT (= the live Runner state), not a copy — if the deployed
# gate drifts, these tests drift with it and still test reality.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1044-prediction-gate"
PREDICT_PLAN="$REPO_ROOT/scripts/infragraph-predict-plan.py"
QUERY="$REPO_ROOT/scripts/infragraph-query.py"

# ── predictor + artifact ────────────────────────────────────────────────────
FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$FIXDB')
rel = ig.upsert_edge(conn, ('lxc', 'nl-n8n01'), ('pve_node', 'nl-pve01'), 'runs_on', source='pve', confidence=0.9)
ig.update_dynamics(conn, rel, observed_rules=['Service Down'], delay_s=30.0, recovery_s=240.0)
conn.commit()
")

start_test "predict_cli_refuses_missing_plan_hash"
  python3 "$QUERY" --db "$FIXDB" predict --action-kind reboot_host --target nl-pve01 --plan-hash "" >/dev/null 2>&1; rc=$?
  assert_eq 2 "$rc" "unkeyed action prediction cannot exist"
end_test

start_test "predict_plan_full_verdict_matrix"
  g1=$(echo '{"hostname": "nl-pve01", "steps": [{"command": "qm reboot 101"}]}' | python3 "$PREDICT_PLAN" --db "$FIXDB" | python3 -c "import json,sys; print(json.load(sys.stdin)['gate'])")
  assert_eq "eligible" "$g1"
  g2=$(echo '{"hostname": "nl-pve01", "steps": [{"command": "kubectl get pods"}]}' | python3 "$PREDICT_PLAN" --db "$FIXDB" | python3 -c "import json,sys; print(json.load(sys.stdin)['gate'])")
  assert_eq "not-applicable-readonly" "$g2"
  g3=$(echo '{"hostname": "nllei99nope01", "steps": [{"command": "systemctl restart foo"}]}' | python3 "$PREDICT_PLAN" --db "$FIXDB" | python3 -c "import json,sys; print(json.load(sys.stdin)['gate'].split(':')[0])")
  assert_eq "ineligible" "$g3"
  g4=$(echo '{"hostname": "nl-pve01", "steps": [{"command": "qm reboot 101"}]}' | INFRAGRAPH_DISABLED=1 python3 "$PREDICT_PLAN" --db "$FIXDB" | python3 -c "import json,sys; print(json.load(sys.stdin)['gate'])")
  assert_eq "ineligible:infragraph-disabled-analysis-only" "$g4" "fail-CLOSED on kill-switch"
end_test

start_test "plan_hash_parity_with_classifier"
  PLAN='{"hostname": "nl-pve01", "steps": [{"command": "kubectl get pods"}]}'
  H1=$(echo "$PLAN" | GATEWAY_DB="$FIXDB" python3 "$REPO_ROOT/scripts/classify-session-risk.py" --category availability --no-audit | python3 -c "import json,sys; print(json.load(sys.stdin)['plan_hash'])")
  H2=$(echo "$PLAN" | python3 "$PREDICT_PLAN" --db "$FIXDB" | python3 -c "import json,sys; print(json.load(sys.stdin)['plan_hash'])")
  assert_eq "$H1" "$H2" "gate key identical across both scripts"
end_test

start_test "committed_artifact_carries_plan_hash_key"
  row=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM infragraph_predictions WHERE kind='action' AND plan_hash != ''")
  assert_gt "$row" 0
  empty=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM infragraph_predictions WHERE kind='action' AND plan_hash = ''")
  assert_eq 0 "$empty" "no unkeyed action artifacts can exist"
end_test

# ── the deployed gate (extracted from the workflow export) ──────────────────
GATE_HARNESS=$(mktemp --suffix=.js)
python3 - "$REPO_ROOT/workflows/claude-gateway-runner.json" > "$GATE_HARNESS" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
code = next(n for n in d['nodes'] if n['name'] == 'Prepare Result')['parameters']['jsCode']
# rindex: the gate's own "To remove: delete up to ..." comment quotes the
# end marker, so the FIRST occurrence is inside a comment — take the LAST.
start = code.index('// <<< infragraph mandatory-prediction gate')
end = code.rindex('// >>> end prediction-gate')
gate = code[start:end]
print("""function runGate(result, pgStdout) {
  const $ = (name) => ({ first: () => ({ json: { stdout: pgStdout } }) });
""" + gate + """
  return { pollWithheld, eligible: predictionGate.eligible, id: predictionGate.id, result };
}
const POLL = "Done.\\n[POLL] Which approach?\\n- Plan A: reboot\\n- Plan B: restart";
const OK = JSON.stringify({gate: "eligible", plan_hash: "x", prediction: {eligible: true, prediction_id: 7, action_kind: "reboot_host", target: "h", predicted_total: 1, window_seconds: 900, blast_radius_count: 1, predicted: []}});
const cases = [
  ["missing-output", runGate(POLL, "").pollWithheld === true],
  ["disabled", runGate(POLL, '{"gate": "ineligible:infragraph-disabled-analysis-only"}').pollWithheld === true],
  ["forged-gate-string", runGate(POLL, '{"gate": "eligible"}').pollWithheld === true],
  ["forged-no-id", runGate(POLL, JSON.stringify({gate: "eligible", prediction: {eligible: true}})).pollWithheld === true],
  ["eligible-passes", runGate(POLL, OK).pollWithheld === false && runGate(POLL, OK).id === 7],
  ["readonly-untouched", runGate("ok [AUTO-RESOLVE]", "").pollWithheld === false],
  ["demoted-marker", /POLL-WITHHELD:NO-PREDICTION/.test(runGate(POLL, "").result)],
  ["demoted-poll-unparseable", !/^\\[POLL\\]/m.test(runGate(POLL, "").result)],
];
let fails = cases.filter(c => !c[1]);
console.log(fails.length === 0 ? "GATE-OK" : "GATE-FAIL: " + fails.map(c => c[0]).join(","));
process.exit(fails.length === 0 ? 0 : 1);""")
PYEOF

start_test "deployed_gate_default_denies_all_bypass_attempts"
  out=$(node "$GATE_HARNESS" 2>&1); rc=$?
  assert_eq 0 "$rc" "gate harness exit"
  assert_eq "GATE-OK" "$out"
end_test

start_test "runner_export_wiring_intact"
  W="$REPO_ROOT/workflows/claude-gateway-runner.json"
  py=$(python3 -c "
import json
d = json.load(open('$W'))
c = d['connections']
print(c['Classify Risk']['main'][0][0]['node'], c['Commit Prediction']['main'][0][0]['node'])")
  assert_eq "Commit Prediction Build Prompt" "$py" "Classify Risk -> Commit Prediction -> Build Prompt"
end_test

start_test "audit_script_carries_invariant_section"
  grep -q "Model-based invariant (IFRNLLEI01PRD-1044)" "$REPO_ROOT/scripts/audit-risk-decisions.sh"; assert_eq 0 $?
  bash -n "$REPO_ROOT/scripts/audit-risk-decisions.sh"; assert_eq 0 $?
end_test

rm -f "$FIXDB" "$GATE_HARNESS"
