#!/usr/bin/env bash
# IFRNLLEI01PRD-1033 — infragraph-query.py CLI contract test suite.
# The JSON shapes asserted here are the FROZEN model_version-1 contract that
# infra-triage.sh Step 2-graph and classify-session-risk.py consume.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1033-infragraph-query"
CLI="$REPO_ROOT/scripts/infragraph-query.py"

# Shared fixture DB: pve03 <- gpu01 <- {ollama, rerank}; pve01 <- n8n01 (with dynamics)
FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$FIXDB')
ig.upsert_edge(conn, ('vm', 'nl-gpu01'), ('pve_node', 'nl-pve03'), 'runs_on', source='iac', confidence=0.95)
ig.upsert_edge(conn, ('service', 'ollama'), ('vm', 'nl-gpu01'), 'depends_on', source='declared', confidence=0.9)
ig.upsert_edge(conn, ('service', 'rerank'), ('vm', 'nl-gpu01'), 'depends_on', source='declared', confidence=0.9)
rel = ig.upsert_edge(conn, ('lxc', 'nl-n8n01'), ('pve_node', 'nl-pve01'), 'runs_on', source='netbox', confidence=0.8)
ig.update_dynamics(conn, rel, observed_rules=['Service Down'], delay_s=45.0, recovery_s=300.0)
conn.commit()
")

start_test "blast_radius_shape_and_counts"
  out=$(python3 "$CLI" --db "$FIXDB" blast-radius --host nl-pve03)
  assert_eq 0 $?
  assert_contains "$out" '"query": "blast_radius"'
  assert_contains "$out" '"host": "nl-pve03"'
  total=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['counts']['total'])")
  assert_eq 3 "$total" "gpu01 + 2 services"
  # node shape: every contract key present
  keys=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(sorted(d['nodes'][0].keys()))")
  assert_eq "['confidence', 'distance', 'entity_type', 'name', 'path', 'site', 'source', 'via']" "$keys"
  assert_contains "$out" '"elapsed_ms"'
end_test

start_test "deps_reverse_direction"
  out=$(python3 "$CLI" --db "$FIXDB" deps --host ollama)
  names=$(printf '%s' "$out" | python3 -c "import json,sys; print(','.join(n['name'] for n in json.load(sys.stdin)['nodes']))")
  assert_eq "nl-gpu01,nl-pve03" "$names"
end_test

start_test "depth_is_capped"
  out=$(python3 "$CLI" --db "$FIXDB" blast-radius --host nl-pve03 --depth 99)
  d=$(printf '%s' "$out" | python3 -c "import json,sys; print(json.load(sys.stdin)['depth'])")
  assert_eq 99 "$d" "requested depth echoed"  # echo only; traversal capped at 5 internally
  total=$(printf '%s' "$out" | python3 -c "import json,sys; print(json.load(sys.stdin)['counts']['total'])")
  assert_eq 3 "$total"
end_test

start_test "cascade_predictions_and_window"
  out=$(python3 "$CLI" --db "$FIXDB" cascade --host nl-pve01 --rule "Device Down")
  assert_contains "$out" '"query": "expected_cascade"'
  assert_contains "$out" '"window_seconds": 900'
  assert_contains "$out" '"model_version": 1'
  assert_contains "$out" '"prediction_id": null'
  rule=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['predictions'][0]['rule'], d['predictions'][0]['host'])")
  assert_eq "Service Down nl-n8n01" "$rule"
end_test

start_test "cascade_record_writes_prediction_with_control"
  out=$(python3 "$CLI" --db "$FIXDB" cascade --host nl-pve01 --rule "Device Down" --record --issue IFRNLLEI01PRD-QA)
  pid=$(printf '%s' "$out" | python3 -c "import json,sys; print(json.load(sys.stdin)['prediction_id'])")
  assert_gt "$pid" 0 "prediction_id returned"
  row=$(sqlite3 "$FIXDB" "SELECT parent_issue_id || '|' || parent_rule || '|' || schema_version || '|' || (control_predicted != '') FROM infragraph_predictions WHERE id=$pid")
  assert_eq "IFRNLLEI01PRD-QA|Device Down|1|1" "$row"
end_test

start_test "explain_paths"
  out=$(python3 "$CLI" --db "$FIXDB" explain --from ollama --to nl-pve03)
  assert_contains "$out" '"reachable": true'
  hops=$(printf '%s' "$out" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['paths'][0]['hops']))")
  assert_eq 2 "$hops"
  out2=$(python3 "$CLI" --db "$FIXDB" explain --from ollama --to nl-pve01)
  assert_contains "$out2" '"reachable": false'
end_test

start_test "health_counts"
  out=$(python3 "$CLI" --db "$FIXDB" health)
  assert_eq 0 $?
  nodes=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['nodes_total'], d['edges_total'], d['predictions']['total'])")
  assert_eq "6 4 1" "$nodes"
end_test

# ─── fail-open contract ─────────────────────────────────────────────────────
start_test "unknown_host_exits_1_with_json"
  out=$(python3 "$CLI" --db "$FIXDB" blast-radius --host bogus); rc=$?
  assert_eq 1 "$rc"
  assert_contains "$out" '"error": "host not in infragraph"'
end_test

start_test "disabled_killswitch_exits_1"
  out=$(INFRAGRAPH_DISABLED=1 python3 "$CLI" --db "$FIXDB" health); rc=$?
  assert_eq 1 "$rc"
  assert_contains "$out" "INFRAGRAPH_DISABLED"
end_test

start_test "broken_db_exits_2_with_json_error"
  out=$(python3 "$CLI" --db /nonexistent/nope.db health 2>/dev/null); rc=$?
  assert_eq 2 "$rc"
  assert_contains "$out" '"error"'
end_test

start_test "empty_graph_health_exits_1"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  python3 "$CLI" --db "$tmp" health >/dev/null; rc=$?
  assert_eq 1 "$rc"
  rm -f "$tmp"
end_test

# ─── latency budget ─────────────────────────────────────────────────────────
start_test "blast_radius_under_2s"
  out=$(python3 "$CLI" --db "$FIXDB" blast-radius --host nl-pve03)
  ms=$(printf '%s' "$out" | python3 -c "import json,sys; print(json.load(sys.stdin)['elapsed_ms'])")
  assert_lt "$ms" 2000
end_test

rm -f "$FIXDB"
