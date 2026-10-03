#!/usr/bin/env bash
# IFRNLLEI01PRD-1119 — host/rule-family granularity scoring for cascade predictions.
# A cascade is "right" if the predicted host has the predicted KIND of alert,
# even when the exact rule name differs (the operationally-meaningful unit).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1119-infragraph-family-scoring"

FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
export GATEWAY_DB="$FIXDB"

ig() { ( cd "$REPO_ROOT/scripts" && python3 -c "
import json, os
from lib import infragraph
conn = infragraph.get_db()
$1
" ); }

start_test "score_prediction_exact_vs_family_right_host_wrong_rule"
  # predicted k8s-pod rule, actual a DIFFERENT k8s-pod rule on the same host:
  # exact = miss (0 tp,1 fp,1 fn); family = hit (1 tp,0 fp,0 fn)
  out=$(ig "
pred=[{'host':'nl-claude01','rule':'HighPodRestartRate'}]
act=[{'host':'nl-claude01','rule':'KubePodNotReady'}]
print(infragraph.score_prediction(pred,act,False), infragraph.score_prediction(pred,act,True))")
  assert_eq "(0, 1, 1) (1, 0, 0)" "$out"
end_test

start_test "family_scoring_recovers_both_families"
  # two right-host-wrong-rule predictions across two families -> exact 0 tp, family 2 tp
  out=$(ig "
pred=[{'host':'h','rule':'KubePodCrashLooping'},{'host':'h','rule':'RAGLatencyP95High'}]
act=[{'host':'h','rule':'ContainerOOMKilled'},{'host':'h','rule':'RAGRerankServiceDown'}]
print(infragraph.score_prediction(pred,act,False), infragraph.score_prediction(pred,act,True))")
  assert_eq "(0, 2, 2) (2, 0, 0)" "$out"
end_test

start_test "wrong_host_is_a_miss_even_at_family_granularity"
  out=$(ig "
pred=[{'host':'hostA','rule':'KubePodCrashLooping'}]
act=[{'host':'hostB','rule':'KubePodNotReady'}]
print(infragraph.score_prediction(pred,act,True))")
  assert_eq "(0, 1, 1)" "$out"
end_test

start_test "health_reports_family_metrics_with_lift"
  sqlite3 "$FIXDB" <<'SQL'
INSERT INTO infragraph_predictions(kind,parent_host,parent_rule,window_seconds,predicted,control_predicted,evaluated_at,actual,tp,fp,fn)
VALUES('cascade','nl-pve03','Service up/down',900,
 '[{"host":"nl-claude01","rule":"HighPodRestartRate"},{"host":"nl-claude01","rule":"RAGLatencyP95High"}]',
 '[]', datetime('now','-1 day'),
 '[{"host":"nl-claude01","rule":"KubePodNotReady"}]', 0, 2, 1);
SQL
  # exact P=0/(0+2)=0.0 R=0/(0+1)=0.0 ; family: k8s-pod hit (tp1), rag fp1 -> P 0.5 R 1.0
  out=$(ig "h=infragraph.health(conn)['predictions']; print(h['precision_30d'],h['precision_family_30d'],h['recall_30d'],h['recall_family_30d'])")
  assert_eq "0.0 0.5 0.0 1.0" "$out"
end_test

start_test "scorecard_reports_family_block_without_changing_exact_all_met"
  python3 -c "import sys,os; sys.path.insert(0,'$REPO_ROOT/scripts')" 2>/dev/null
  ( cd "$REPO_ROOT/scripts" && GATEWAY_DB="$FIXDB" python3 infragraph-eval.py --scorecard --out /tmp/sc-1119.json >/dev/null 2>&1 )
  out=$(python3 -c "
import json; d=json.load(open('/tmp/sc-1119.json')); w=d['window_30d']; g=d['gate_b_to_c']
print('precision_family' in w, 'precision_conf08_family' in w, 'family' in g, 'all_met_family' in g['family'], 'precision_conf08_family_ok' not in g)")
  assert_eq "True True True True True" "$out"
  rm -f /tmp/sc-1119.json
end_test

start_test "expected_cascade_items_carry_rule_family"
  # rule_family is added unconditionally on each emitted item
  out=$(ig "print(infragraph.rule_family('KubePodNotReady'), infragraph.rule_family('Service up/down'))")
  assert_eq "k8s-pod host-down" "$out"
end_test

rm -f "$FIXDB"
