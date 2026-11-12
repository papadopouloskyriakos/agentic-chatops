#!/usr/bin/env bash
# IFRNLLEI01PRD-1158 — bi-temporal edge invalidation on infragraph_dynamics.
# Columns + invalidate_edge() + decay (REPORTING-ONLY) + cycle-safe supersession
# chains + health/metrics. Shadow-safe: decay never alters prediction confidence;
# invalidate_edge is only called by an (unwired, flag-gated) trigger.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1158-bitemporal"

MIG="$REPO_ROOT/scripts/migrations/019_infragraph_temporal_supersession.sql"
LIB="$REPO_ROOT/scripts/lib/infragraph.py"
FIXDB=$(mktemp --suffix=.db); sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
sqlite3 "$FIXDB" < "$MIG" 2>/dev/null   # apply the temporal columns to the fixture
export GATEWAY_DB="$FIXDB"

start_test "migration_019_adds_temporal_columns"
  n=$(grep -cE "ADD COLUMN (invalid_at|superseded_by|last_confirmation)" "$MIG")
  assert_eq "3" "$n"
end_test

start_test "decay_is_reporting_only_not_in_prediction_path"
  # compute_confidence_with_decay must NOT be referenced inside expected_cascade /
  # predict_action / apply_cascade_gating — decay only flags re-ratification.
  bad=$(awk '/^def (expected_cascade|predict_action|apply_cascade_gating)\(/{f=1} /^def /&&!/expected_cascade|predict_action|apply_cascade_gating/{if(prev)f=0} {if(f&&/compute_confidence_with_decay/)print} {prev=1}' "$LIB" | wc -l)
  assert_eq "0" "$bad"
end_test

start_test "compute_confidence_with_decay_math"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
from lib import infragraph as ig
a=ig.compute_confidence_with_decay(0.9,'2026-03-13T00:00:00Z',now='2026-06-21T00:00:00Z')  # ~100d
b=ig.compute_confidence_with_decay(0.9,None)             # no last_confirmed -> base
c=ig.compute_confidence_with_decay(0.9,'2026-06-21T00:00:00Z',now='2026-06-21T00:00:00Z')  # 0d
print(f'{0.30 < a < 0.34} {b} {c}')")
  assert_eq "True 0.9 0.9" "$out"
end_test

start_test "invalidate_edge_flips_once_and_chain_is_cycle_safe"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
from lib import infragraph as ig
conn=ig.get_db()
conn.execute('PRAGMA foreign_keys=OFF')  # synthetic rel_ids have no parent rows; testing invalidate UPDATE only
# seed two edges directly into dynamics
conn.execute(\"INSERT INTO infragraph_dynamics(rel_id,source,confidence) VALUES(1001,'declared',0.9)\")
conn.execute(\"INSERT INTO infragraph_dynamics(rel_id,source,confidence) VALUES(1002,'declared',0.8)\")
conn.commit()
first=ig.invalidate_edge(conn,1001,'test-contradiction',superseded_by_rel_id=1002)
again=ig.invalidate_edge(conn,1001,'test-again')   # already invalid -> False
# make a self-cycle to prove chain traversal terminates
conn.execute(\"UPDATE infragraph_dynamics SET superseded_by=1002 WHERE rel_id=1002\")
conn.commit()
chain=ig.find_supersession_chain(conn,1001)
inv=conn.execute(\"SELECT COUNT(*) FROM infragraph_dynamics WHERE invalid_at IS NOT NULL\").fetchone()[0]
print(f'{first} {again} {chain} {inv}')")
  # first flip True, second False, chain [1001,1002] (stops at self-cycle), 1 invalid
  assert_eq "True False [1001, 1002] 1" "$out"
end_test

start_test "health_reports_invalid_and_decay_fields"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
from lib import infragraph as ig
h=ig.health(ig.get_db())
print('invalid_edges' in h and 'decay_at_risk' in h)")
  assert_eq "True" "$out"
end_test

start_test "metrics_writer_exposes_bitemporal_series"
  W="$REPO_ROOT/scripts/write-infragraph-metrics.py"
  assert_eq "OK" "$(grep -q infragraph_invalidated_edges "$W" && grep -q infragraph_decay_at_risk "$W" && echo OK || echo MISSING)"
end_test

rm -f "$FIXDB"
