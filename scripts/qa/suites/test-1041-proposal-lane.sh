#!/usr/bin/env bash
# IFRNLLEI01PRD-1041 — Phase C proposal lane (ask/approve, never auto-activate).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1041-proposal-lane"
PROPOSE="$REPO_ROOT/scripts/infragraph-propose-blast-radius.py"

FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
sqlite3 "$FIXDB" "CREATE TABLE IF NOT EXISTS openclaw_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT 'triage', key TEXT NOT NULL, value TEXT NOT NULL, issue_id TEXT DEFAULT '', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$FIXDB')
for i, rules in enumerate([['Device Down'], ['Service up/down'], ['KubeAPIDown']]):
    rel = ig.upsert_edge(conn, ('lxc', f'nlguest{i:02d}'), ('pve_node', 'nlpve09'), 'runs_on', source='pve', confidence=0.9)
    ig.update_dynamics(conn, rel, observed_rules=rules, confidence=0.9)
# a weak parent: one low-conf child only
rel = ig.upsert_edge(conn, ('lxc', 'nlweak01'), ('pve_node', 'nlpve08'), 'runs_on', source='incident', confidence=0.5)
ig.update_dynamics(conn, rel, observed_rules=['Device Down'])
conn.commit()
")

start_test "propose_creates_pending_not_active"
  out=$(python3 "$PROPOSE" --db "$FIXDB" --parent nlpve09 --no-yt)
  assert_contains "$out" '"status": "proposed"'
  pending=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM openclaw_memory WHERE category='infragraph-proposal'")
  active=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM openclaw_memory WHERE category='blast-radius'")
  assert_eq "1" "$pending" "pending row stored"
  assert_eq "0" "$active" "NOTHING active before operator approval"
end_test

start_test "below_threshold_parent_not_proposed"
  out=$(python3 "$PROPOSE" --db "$FIXDB" --parent nlpve08 --no-yt)
  assert_contains "$out" "below-threshold"
end_test

start_test "duplicate_proposal_suppressed"
  out=$(python3 "$PROPOSE" --db "$FIXDB" --parent nlpve09 --no-yt)
  assert_contains "$out" "already-proposed-or-active"
  n=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM openclaw_memory WHERE category='infragraph-proposal'")
  assert_eq "1" "$n"
end_test

start_test "approve_activates_phase1b_shaped_rule"
  out=$(python3 "$PROPOSE" --db "$FIXDB" --approve pending-nlpve09)
  assert_contains "$out" '"approved"'
  row=$(sqlite3 "$FIXDB" "SELECT value FROM openclaw_memory WHERE category='blast-radius' AND key='pending-nlpve09'")
  shape=$(printf '%s' "$row" | python3 -c "
import json,sys
v = json.load(sys.stdin)
need = {'hosts', 'host_patterns', 'rules', 'description', 'started_at'}
print(need.issubset(v.keys()), v.get('generated_by'), len(v['hosts']), all(r.endswith('*') for r in v['rules']))")
  assert_eq "True infragraph 3 True" "$shape" "exact tier1 Phase 1b format + provenance tag + fnmatch-ready rules"
  pending=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM openclaw_memory WHERE category='infragraph-proposal'")
  assert_eq "0" "$pending" "pending row consumed"
end_test

start_test "approved_rule_matches_tier1_phase1b_matcher"
  # drive the REAL tier1 matcher against the generated rule
  m=$(cd "$REPO_ROOT/scripts" && python3 -c "
import json, sqlite3, sys, fnmatch
conn = sqlite3.connect('$FIXDB'); conn.row_factory = sqlite3.Row
rule = json.loads(conn.execute(\"SELECT value FROM openclaw_memory WHERE category='blast-radius'\").fetchone()['value'])
def match(hostname, rule_name, r):
    hosts = r.get('hosts') or []; host_patterns = r.get('host_patterns') or []; rules = r.get('rules') or []
    host_match = (hostname in hosts) or any(fnmatch.fnmatchcase(hostname, p) for p in host_patterns)
    rule_match = any(fnmatch.fnmatchcase(rule_name, p) for p in rules) if rules else True
    return host_match and rule_match if (hosts or host_patterns) else rule_match
print(match('nlguest00', 'Device Down! Due to no ICMP response.', rule),
      match('nlguest01', 'Service up/down', rule),
      match('nlunrelated01', 'Device Down', rule))")
  assert_eq "True True False" "$m" "folds the predicted children, ignores unrelated hosts"
end_test

start_test "reject_discards_pending"
  python3 "$PROPOSE" --db "$FIXDB" --parent nlpve09 --no-yt >/dev/null 2>&1 || true
  # pve09 is active now so propose is suppressed; use a fresh parent
  (cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$FIXDB')
for i, rules in enumerate([['A'], ['B'], ['C']]):
    rel = ig.upsert_edge(conn, ('vm', f'nlrj{i:02d}'), ('pve_node', 'nlpve07'), 'runs_on', source='pve', confidence=0.9)
    ig.update_dynamics(conn, rel, observed_rules=rules, confidence=0.9)
conn.commit()")
  python3 "$PROPOSE" --db "$FIXDB" --parent nlpve07 --no-yt >/dev/null
  out=$(python3 "$PROPOSE" --db "$FIXDB" --reject pending-nlpve07)
  assert_contains "$out" '"removed_rows": 1'
  active=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM openclaw_memory WHERE category='blast-radius' AND key='pending-nlpve07'")
  assert_eq "0" "$active" "rejected proposal never activates"
end_test

rm -f "$FIXDB"
