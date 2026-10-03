#!/usr/bin/env bash
# IFRNLLEI01PRD-1031 — infragraph schema + library test suite.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1031-infragraph-schema"

# ─── registry ───────────────────────────────────────────────────────────────
start_test "registry_exports_infragraph_tables"
  out=$(cd "$REPO_ROOT/scripts" && python3 -m lib.schema_version 2>&1)
  assert_contains "$out" '"infragraph_dynamics"'
  assert_contains "$out" '"infragraph_predictions"'
end_test

start_test "current_version_is_1"
  v=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import current; print(current('infragraph_dynamics'), current('infragraph_predictions'))")
  assert_eq "1 1" "$v"
end_test

# ─── DDL via schema.sql ─────────────────────────────────────────────────────
start_test "schema_sql_creates_g15_tables_and_indexes"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  for t in infragraph_dynamics infragraph_predictions; do
    n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$t'")
    assert_eq 1 "$n" "table $t exists"
  done
  for ix in idx_gr_source_type idx_gr_target_type idx_igd_rel idx_igd_valid idx_igp_eval idx_igp_parent; do
    n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='$ix'")
    assert_eq 1 "$n" "index $ix exists"
  done
  rm -f "$tmp"
end_test

# ─── DDL via migration 016 (existing installs) ──────────────────────────────
start_test "migration_016_applies_and_is_idempotent"
  tmp=$(mktemp --suffix=.db)
  # Minimal pre-existing G10 layer the migration's FK references need, plus
  # schema_migrations pre-seeded with 004..015 so ONLY 016 is pending (the
  # earlier migrations need unrelated tables this fixture doesn't carry —
  # same isolation trick as test-635-schema-versioning.sh).
  sqlite3 "$tmp" "
    CREATE TABLE graph_entities (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, name TEXT NOT NULL, source_table TEXT DEFAULT '', source_id TEXT DEFAULT '', attributes TEXT DEFAULT '{}', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(entity_type, name));
    CREATE TABLE graph_relationships (id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, rel_type TEXT NOT NULL, confidence REAL DEFAULT 1.0, metadata TEXT DEFAULT '{}', created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, name TEXT, applied_at TEXT, filename TEXT);
  "
  for v in 004 005 006 007 008 009 010 011 012 013 014 015; do
    sqlite3 "$tmp" "INSERT INTO schema_migrations VALUES ('$v','x','2026','x')"
  done
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  # Count 016's tables by name so later infragraph migrations (017+) don't skew it.
  q016="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('infragraph_dynamics','infragraph_predictions')"
  n=$(sqlite3 "$tmp" "$q016")
  assert_eq 2 "$n" "both infragraph tables created by migration"
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  n2=$(sqlite3 "$tmp" "$q016")
  assert_eq 2 "$n2" "re-apply is a no-op"
  rm -f "$tmp"
end_test

# ─── library: upserts stamp schema_version + provenance ─────────────────────
start_test "lib_upsert_edge_creates_stamped_dynamics_row"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$tmp')
rel = ig.upsert_edge(conn, ('vm', 'nl-gpu01'), ('pve_node', 'nl-pve03'), 'runs_on', source='iac', confidence=0.95)
conn.commit()
row = conn.execute('SELECT source, confidence, schema_version FROM infragraph_dynamics WHERE rel_id=?', (rel,)).fetchone()
print(row['source'], row['confidence'], row['schema_version'])
ent = conn.execute(\"SELECT source_table FROM graph_entities WHERE name='nl-gpu01'\").fetchone()
print(ent['source_table'])
")
  assert_contains "$out" "iac 0.95 1"
  assert_contains "$out" "infragraph"
  rm -f "$tmp"
end_test

start_test "lib_upsert_edge_is_idempotent_and_never_downgrades_confidence"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$tmp')
a = ig.upsert_edge(conn, ('vm', 'x'), ('pve_node', 'y'), 'runs_on', source='netbox', confidence=0.9)
b = ig.upsert_edge(conn, ('vm', 'x'), ('pve_node', 'y'), 'runs_on', source='netbox', confidence=0.5)
n = conn.execute('SELECT COUNT(*) FROM graph_relationships').fetchone()[0]
c = conn.execute('SELECT confidence FROM infragraph_dynamics WHERE rel_id=?', (a,)).fetchone()[0]
print(a == b, n, c)
")
  assert_contains "$out" "True 1 0.9"
  rm -f "$tmp"
end_test

start_test "lib_rejects_unknown_vocabulary"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  cd "$REPO_ROOT/scripts"
  assert_exit_code 1 python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$tmp')
try:
    ig.upsert_edge(conn, ('vm', 'x'), ('pve_node', 'y'), 'bogus_rel', source='netbox')
except ValueError:
    raise SystemExit(1)
"
  rm -f "$tmp"
end_test

start_test "lib_update_dynamics_recomputes_percentiles_and_caps_samples"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sys, json; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$tmp')
rel = ig.upsert_edge(conn, ('lxc', 'nl-n8n01'), ('pve_node', 'nl-pve01'), 'runs_on', source='netbox', confidence=0.8)
for i in range(100):
    ig.update_dynamics(conn, rel, observed_rules=['Service Down'], delay_s=float(i))
conn.commit()
row = conn.execute('SELECT samples, delay_p50_s, observation_count, expected_alerts FROM infragraph_dynamics WHERE rel_id=?', (rel,)).fetchone()
samples = json.loads(row['samples'])
alerts = json.loads(row['expected_alerts'])
print(len(samples['delay_s']), row['observation_count'], len(alerts), row['delay_p50_s'] is not None)
")
  assert_contains "$out" "64 100 1 True"
  rm -f "$tmp"
end_test

start_test "lib_valid_until_expiry_excludes_edge_from_traversal"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$tmp')
ig.upsert_edge(conn, ('vm', 'a'), ('pve_node', 'h'), 'runs_on', source='netbox',
               confidence=0.9, valid_until='2020-01-01T00:00:00Z')
ig.upsert_edge(conn, ('vm', 'b'), ('pve_node', 'h'), 'runs_on', source='netbox',
               confidence=0.9, valid_until='2099-01-01T00:00:00Z')
conn.commit()
names = [n['name'] for n in ig.traverse(conn, 'h', 'blast_radius', 3)]
print(','.join(names))
")
  assert_eq "b" "$out" "expired edge excluded, fresh edge included"
  rm -f "$tmp"
end_test

# ─── model-based invariant plumbing (IFRNLLEI01PRD-1044/-1045) ──────────────
start_test "action_prediction_requires_plan_hash"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$tmp')
try:
    ig.record_prediction(conn, parent_host='nl-gpu01', parent_rule='Device Down',
                         parent_issue_id='X', window_seconds=900, predicted=[], control=[],
                         kind='action', action_kind='reboot_host', action_target='nl-gpu01')
    print('NO-ERROR')
except ValueError as e:
    print('REFUSED:', 'plan_hash' in str(e))
")
  assert_eq "REFUSED: True" "$out" "action prediction without plan_hash must be refused"
  rm -f "$tmp"
end_test

start_test "action_prediction_with_plan_hash_commits_artifact"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$tmp')
pid = ig.record_prediction(conn, parent_host='nl-gpu01', parent_rule='Device Down',
                           parent_issue_id='IFRNLLEI01PRD-QA', window_seconds=900,
                           predicted=[{'host':'ollama','rule':'Service Down','confidence':0.9}],
                           control=[], kind='action', action_kind='reboot_host',
                           action_target='nl-gpu01', plan_hash='abc123')
conn.commit()
r = conn.execute('SELECT kind, action_kind, action_target, plan_hash, verdict FROM infragraph_predictions WHERE id=?', (pid,)).fetchone()
print(r['kind'], r['action_kind'], r['action_target'], r['plan_hash'], repr(r['verdict']))
")
  assert_eq "action reboot_host nl-gpu01 abc123 ''" "$out"
  rm -f "$tmp"
end_test

start_test "invariant_columns_present_via_migration_016"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" "
    CREATE TABLE graph_entities (id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, name TEXT NOT NULL, source_table TEXT DEFAULT '', source_id TEXT DEFAULT '', attributes TEXT DEFAULT '{}', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(entity_type, name));
    CREATE TABLE graph_relationships (id INTEGER PRIMARY KEY AUTOINCREMENT, source_id INTEGER NOT NULL, target_id INTEGER NOT NULL, rel_type TEXT NOT NULL, confidence REAL DEFAULT 1.0, metadata TEXT DEFAULT '{}', created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, name TEXT, applied_at TEXT, filename TEXT);
  "
  for v in 004 005 006 007 008 009 010 011 012 013 014 015; do
    sqlite3 "$tmp" "INSERT INTO schema_migrations VALUES ('$v','x','2026','x')"
  done
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('infragraph_predictions') WHERE name IN ('kind','action_kind','action_target','plan_hash','verdict','verdict_detail')")
  assert_eq 6 "$n" "all 6 invariant columns present"
  rm -f "$tmp"
end_test
