#!/usr/bin/env bash
# IFRNLLEI01PRD-1118 — cascade-probability gating on the infragraph predictor.
# Shadow-only calibration: emit-gate by (host, rule-family) probability, per-item
# confidence by (host, exact-rule) probability. Inert until learn has run.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1118-infragraph-cascade-gating"

FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
export GATEWAY_DB="$FIXDB"

ig() {  # run a python snippet with `infragraph` + `conn` bound to the fixture
  ( cd "$REPO_ROOT/scripts" && python3 -c "
import os, json
from lib import infragraph
conn = infragraph.get_db()
$1
" )
}

start_test "rule_family_maps_alert_classes"
  out=$(ig "print(infragraph.rule_family('Service up/down'), infragraph.rule_family('KubePodCrashLooping'), infragraph.rule_family('RAGLatencyP95High'), infragraph.rule_family('Linux High Memory Usage'), infragraph.rule_family('DSM: Data backup task'))")
  assert_eq "host-down k8s-pod rag resource backup" "$out"
end_test

start_test "cascade_prob_laplace_smoothing"
  sqlite3 "$FIXDB" "INSERT INTO infragraph_cascade_stats(scope,parent_family,child_host,child_key,seen,fired) VALUES
    ('family','host-down','nl-claude01','resource',14,0),
    ('exact','host-down','nl-claude01','TargetDown',14,5);"
  # never-firer (0+1)/(14+5)=0.053 ; cascader (5+1)/(14+5)=0.316 ; cold-start (0+1)/(0+5)=0.2
  out=$(ig "print(round(infragraph.cascade_prob(conn,'host-down','nl-claude01','resource','family'),3), round(infragraph.cascade_prob(conn,'host-down','nl-claude01','TargetDown','exact'),3), round(infragraph.cascade_prob(conn,'host-down','zz','yy','family'),3))")
  assert_eq "0.053 0.316 0.2" "$out"
end_test

start_test "gating_drops_never_firers_and_recalibrates_confidence"
  # NodeSystemSaturation = 'resource' family (fam_p 0.053 < 0.10 -> GATED);
  # TargetDown = 'host-down' family (cold-start 0.2 -> kept), confidence = exact 0.316
  out=$(ig "
preds=[{'host':'nl-claude01','rule':'NodeSystemSaturation','confidence':0.9},
       {'host':'nl-claude01','rule':'TargetDown','confidence':0.9}]
g=infragraph.apply_cascade_gating(conn,preds,'Service up/down')
print(len(g), [p['rule'] for p in g], round(g[0]['confidence'],3), g[0]['structural_confidence'])")
  assert_eq "1 ['TargetDown'] 0.316 0.9" "$out"
end_test

start_test "empty_stats_is_byte_identical_legacy"
  EMPTY=$(mktemp --suffix=.db); sqlite3 "$EMPTY" < "$REPO_ROOT/schema.sql"
  out=$(cd "$REPO_ROOT/scripts" && GATEWAY_DB="$EMPTY" python3 -c "
from lib import infragraph
conn=infragraph.get_db()
g=infragraph.apply_cascade_gating(conn,[{'host':'h','rule':'r','confidence':0.9}],'Service up/down')
print(len(g), g[0]['confidence'], 'structural_confidence' in g[0])")
  assert_eq "1 0.9 False" "$out"
  rm -f "$EMPTY"
end_test

start_test "gating_flag_off_is_legacy"
  out=$(ig "
import os; os.environ['INFRAGRAPH_CASCADE_GATING']='0'
g=infragraph.apply_cascade_gating(conn,[{'host':'nl-claude01','rule':'NodeSystemSaturation','confidence':0.9}],'Service up/down')
print(len(g), g[0]['confidence'], 'structural_confidence' in g[0])")
  assert_eq "1 0.9 False" "$out"
end_test

start_test "learn_cascade_stats_correct_and_idempotent"
  sqlite3 "$FIXDB" "DELETE FROM infragraph_cascade_stats;"
  sqlite3 "$FIXDB" <<'SQL'
INSERT INTO infragraph_predictions(kind,parent_host,parent_rule,window_seconds,predicted,control_predicted,evaluated_at,actual)
VALUES('cascade','nl-pve03','Service up/down',900,
  '[{"host":"nl-claude01","rule":"TargetDown"},{"host":"nl-claude01","rule":"RAGLatencyP95High"}]',
  '[]','2026-06-15 00:00:00',
  '[{"host":"nl-claude01","rule":"TargetDown"}]');
SQL
  r1=$(ig "print(json.dumps(infragraph.learn_cascade_stats(conn),sort_keys=True)); conn.commit()")
  r2=$(ig "print(json.dumps(infragraph.learn_cascade_stats(conn),sort_keys=True)); conn.commit()")
  assert_eq "$r1" "$r2"
  # exact: TargetDown fired (1/1), RAGLatency did not (1/0)
  assert_eq "1/1" "$(sqlite3 "$FIXDB" "SELECT seen||'/'||fired FROM infragraph_cascade_stats WHERE scope='exact' AND child_key='TargetDown';")"
  assert_eq "1/0" "$(sqlite3 "$FIXDB" "SELECT seen||'/'||fired FROM infragraph_cascade_stats WHERE scope='exact' AND child_key='RAGLatencyP95High';")"
  # family (deduped per prediction): host-down family fired (TargetDown), rag did not
  assert_eq "1/1" "$(sqlite3 "$FIXDB" "SELECT seen||'/'||fired FROM infragraph_cascade_stats WHERE scope='family' AND child_key='host-down';")"
  assert_eq "1/0" "$(sqlite3 "$FIXDB" "SELECT seen||'/'||fired FROM infragraph_cascade_stats WHERE scope='family' AND child_key='rag';")"
end_test

start_test "learn_parent_family_action_mapping"
  # IFRNLLEI01PRD-1119: host-offline actions pool under 'host-down'; unmapped
  # kinds fall back to their own rule_family bucket; cascade rows unchanged.
  out=$(ig "print(infragraph._learn_parent_family('action','reboot_host','reboot_host'), infragraph._learn_parent_family('cascade','Service up/down',''), infragraph._learn_parent_family('action','','bounce_tunnel')==infragraph.rule_family('bounce_tunnel'))")
  assert_eq "host-down host-down True" "$out"
end_test

start_test "learn_pools_action_lane_misses_under_host_down"
  # The id=42 scenario: a reboot_host action predicted host-down cascades that
  # never fired. Pre-1119 these kind='action' negatives were dropped entirely.
  sqlite3 "$FIXDB" "DELETE FROM infragraph_predictions; DELETE FROM infragraph_cascade_stats;"
  sqlite3 "$FIXDB" <<'SQL'
INSERT INTO infragraph_predictions(kind,parent_host,parent_rule,action_kind,action_target,plan_hash,window_seconds,predicted,control_predicted,evaluated_at,actual,model_version)
VALUES('action','grk8s-ctrl03','reboot_host','reboot_host','grk8s-ctrl03','deadbeef',900,
  '[{"host":"grimmich01","rule":"Port status up/down"},{"host":"grnpm01","rule":"Device Down! Due to no ICMP response."}]',
  '[]','2026-06-18 12:40:01','[]',2);
SQL
  ig "infragraph.learn_cascade_stats(conn); conn.commit()" >/dev/null
  # the action MISS is now learned, keyed under the mapped 'host-down' family
  assert_eq "1/0" "$(sqlite3 "$FIXDB" "SELECT seen||'/'||fired FROM infragraph_cascade_stats WHERE scope='family' AND parent_family='host-down' AND child_host='grimmich01' AND child_key='host-down';")"
  assert_eq "1/0" "$(sqlite3 "$FIXDB" "SELECT seen||'/'||fired FROM infragraph_cascade_stats WHERE scope='exact' AND parent_family='host-down' AND child_host='grnpm01';")"
  # nothing leaked into a phantom 'reboot_host' parent bucket
  assert_eq "0" "$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM infragraph_cascade_stats WHERE parent_family='reboot_host';")"
end_test

start_test "gating_drop_false_annotates_without_dropping_or_recalibrating"
  # IFRNLLEI01PRD-1145 Gap 2: the fail-CLOSED action lane keeps EVERY prediction
  # and the caller's confidence; only cascade_prob_family is attached.
  # stats: host-down -> claude01/resource never fires (14/0 -> fam_p 0.053 < tau).
  sqlite3 "$FIXDB" "DELETE FROM infragraph_cascade_stats;"
  sqlite3 "$FIXDB" "INSERT INTO infragraph_cascade_stats(scope,parent_family,child_host,child_key,seen,fired) VALUES
    ('family','host-down','nl-claude01','resource',14,0);"
  out=$(ig "
preds=[{'host':'nl-claude01','rule':'NodeSystemSaturation','confidence':0.9},
       {'host':'nl-claude01','rule':'TargetDown','confidence':0.9}]
g=infragraph.apply_cascade_gating(conn,preds,'',drop=False,parent_family='host-down')
print(len(g), [round(p['cascade_prob_family'],3) for p in g], [p['confidence'] for p in g], ['structural_confidence' in p for p in g])")
  # nothing dropped (2 kept), family probs attached, confidence UNCHANGED (0.9/0.9), no structural_confidence key
  assert_eq "2 [0.053, 0.2] [0.9, 0.9] [False, False]" "$out"
end_test

start_test "predict_action_annotates_cascade_prob_family_but_does_not_drop"
  # Build a tiny graph: claude01 runs_on pve03; pve03 host-down -> claude01 fires
  # 'resource' (the 14/0 never-firer family). A reboot_host action must still emit
  # claude01 (deviation-safety) with cascade_prob_family attached, NOT drop it.
  sqlite3 "$FIXDB" "DELETE FROM infragraph_cascade_stats;"
  sqlite3 "$FIXDB" "INSERT INTO infragraph_cascade_stats(scope,parent_family,child_host,child_key,seen,fired) VALUES
    ('family','host-down','nl-claude01','resource',14,0);"
  out=$(ig "
import json
# minimal graph
conn.execute(\"INSERT INTO graph_entities(name,entity_type,source_table) VALUES('nl-pve03','pve_node','infragraph')\")
conn.execute(\"INSERT INTO graph_entities(name,entity_type,source_table) VALUES('nl-claude01','lxc','infragraph')\")
sid=conn.execute(\"SELECT id FROM graph_entities WHERE name='nl-claude01'\").fetchone()[0]
tid=conn.execute(\"SELECT id FROM graph_entities WHERE name='nl-pve03'\").fetchone()[0]
conn.execute(\"INSERT INTO graph_relationships(source_id,target_id,rel_type) VALUES(?,?,'runs_on')\",(sid,tid))
rid=conn.execute(\"SELECT id FROM graph_relationships WHERE rel_type='runs_on'\").fetchone()[0]
conn.execute(\"INSERT INTO infragraph_dynamics(rel_id,expected_alerts,confidence,observation_count,source) VALUES(?,?,?,?,?)\",
  (rid, json.dumps([{'rule':'NodeSystemSaturation'}]), 0.9, 5, 'declared'))
conn.commit()
r=infragraph.predict_action(conn,'reboot_host','nl-pve03')
ps=[p for p in r['predicted'] if p['host']=='nl-claude01']
print(r['eligible'], len(ps)==1, 'cascade_prob_family' in ps[0], round(ps[0]['cascade_prob_family'],3), ps[0]['confidence']==0.9)")
  # eligible, claude01 STILL predicted (not dropped despite fam_p 0.053 < tau),
  # cascade_prob_family attached (0.053), structural confidence preserved (0.9)
  assert_eq "True True True 0.053 True" "$out"
end_test

start_test "model_version_is_2"
  assert_eq "2" "$(ig "print(infragraph.MODEL_VERSION)")"
end_test

rm -f "$FIXDB"
