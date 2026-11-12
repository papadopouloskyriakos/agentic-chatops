#!/usr/bin/env bash
# IFRNLLEI01PRD-1032 — infragraph seeder test suite (offline sources only;
# --pve/--netbox need live endpoints and are covered by the deploy validation).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1032-infragraph-seed"
SEED="$REPO_ROOT/scripts/infragraph-seed.py"

_mkdb() {
  local tmp; tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/schema.sql"
  sqlite3 "$tmp" "CREATE TABLE IF NOT EXISTS openclaw_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT 'triage', key TEXT NOT NULL, value TEXT NOT NULL, issue_id TEXT DEFAULT '', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
  echo "$tmp"
}

start_test "tunnels_seed_matches_chaos_test_dict"
  tmp=$(_mkdb)
  out=$(python3 "$SEED" --db "$tmp" --tunnels)
  assert_eq 0 $?
  n_dict=$(python3 -c "
import ast
src = open('$REPO_ROOT/scripts/chaos-test.py').read()
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'TUNNEL_GRAPH_EDGE':
        print(len(ast.literal_eval(node.value))); break
")
  n_graph=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM graph_entities WHERE entity_type='tunnel'")
  assert_eq "$n_dict" "$n_graph" "graph-parity: tunnel count == TUNNEL_GRAPH_EDGE size"
  # every tunnel has exactly 2 routes_via edges (both endpoint sites)
  bad=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM (SELECT t.id, COUNT(r.id) c FROM graph_entities t LEFT JOIN graph_relationships r ON r.target_id=t.id AND r.rel_type='routes_via' WHERE t.entity_type='tunnel' GROUP BY t.id HAVING c != 2)")
  assert_eq 0 "$bad" "every tunnel has exactly 2 site edges"
  # IFRNLLEI01PRD-1042: FULL edge-by-edge parity with the chaos safety BFS —
  # every dict entry maps to its tunnel node + routes_via edges from EXACTLY
  # the dict's two endpoint sites. This is the lockstep guard that must hold
  # >=30d before chaos-test.py may ever read the graph instead of the dict.
  parity=$(python3 - "$tmp" << 'PARITYEOF'
import ast, json, sqlite3, sys, os
src = open(os.environ["REPO_ROOT"] + '/scripts/chaos-test.py').read()
edges = None
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'TUNNEL_GRAPH_EDGE':
        edges = ast.literal_eval(node.value)
conn = sqlite3.connect(sys.argv[1]); conn.row_factory = sqlite3.Row
bad = []
for (label, wan), (a, b) in edges.items():
    tname = f"tunnel:{label.replace(' ', '').replace(chr(0x2194), '-')}:{wan}"
    rows = conn.execute(
        "SELECT s.name FROM graph_relationships r "
        "JOIN graph_entities s ON s.id=r.source_id "
        "JOIN graph_entities t ON t.id=r.target_id "
        "WHERE t.name=? AND r.rel_type='routes_via'", (tname,)).fetchall()
    got = sorted(r['name'] for r in rows)
    if got != sorted([a, b]):
        bad.append(f"{tname}: expected {sorted([a,b])} got {got}")
print("PARITY-OK" if not bad else "PARITY-FAIL: " + "; ".join(bad[:3]))
PARITYEOF
)
  assert_eq "PARITY-OK" "$parity"
  rm -f "$tmp"
end_test

start_test "declared_seed_parses_doc_and_records_dynamics"
  tmp=$(_mkdb)
  python3 "$SEED" --db "$tmp" --declared >/dev/null; rc=$?
  assert_eq 0 "$rc"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM infragraph_dynamics WHERE source='declared' AND expected_alerts != '[]'")
  assert_gt "$n" 0 "at least one declared edge carries expected_alerts"
  stamp=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM openclaw_memory WHERE category='infragraph-seed' AND key='declared'")
  assert_eq 1 "$stamp" "last_seed.declared stamped exactly once"
  # idempotency: second run, no growth, still one stamp row
  python3 "$SEED" --db "$tmp" --declared >/dev/null
  stamp2=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM openclaw_memory WHERE category='infragraph-seed' AND key='declared'")
  assert_eq 1 "$stamp2" "re-seed does not duplicate the stamp row"
  rm -f "$tmp"
end_test

start_test "malformed_declared_row_fails_loud"
  tmp=$(_mkdb)
  doc=$(mktemp --suffix=.md)
  cat > "$doc" << 'DOC'
| source | rel_type | target | expected_alerts | notes |
|---|---|---|---|---|
| lxc:nl-n8n01 | runs_on | pve_node:nl-pve01 | | ok row |
| bogus-no-colon | runs_on | pve_node:nl-pve01 | | broken row |
DOC
  # point the seeder at the broken doc by patching DECLARED_DOC via env-free trick:
  # run from a temp module call
  python3 - "$tmp" "$doc" << 'PY'
import sys, importlib.util, os
sys.path.insert(0, os.path.join(os.environ.get("REPO_ROOT", "."), "scripts"))
spec = importlib.util.spec_from_file_location("seedmod", os.path.join(os.environ["REPO_ROOT"], "scripts", "infragraph-seed.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.DECLARED_DOC = sys.argv[2]
from lib import infragraph
conn = infragraph.get_db(sys.argv[1])
try:
    m.seed_declared(conn)
    sys.exit(0)
except RuntimeError:
    sys.exit(7)
PY
  rc=$?
  assert_eq 7 "$rc" "malformed entity token raises RuntimeError"
  rm -f "$tmp" "$doc"
end_test

start_test "seed_cli_requires_a_source"
  tmp=$(_mkdb)
  python3 "$SEED" --db "$tmp" >/dev/null 2>&1; rc=$?
  assert_eq 2 "$rc" "argparse error when no source picked"
  rm -f "$tmp"
end_test
