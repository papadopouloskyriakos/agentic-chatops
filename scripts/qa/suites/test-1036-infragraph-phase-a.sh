#!/usr/bin/env bash
# IFRNLLEI01PRD-1036 (Phase A advisory wiring) + -1037 (observability).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1036-infragraph-phase-a"
CLASSIFY="$REPO_ROOT/scripts/classify-session-risk.py"

# Fixture graph with a wide-blast host (10 guests on one pve node)
FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$FIXDB')
for i in range(10):
    ig.upsert_edge(conn, ('vm', f'nlguest{i:02d}'), ('pve_node', 'nlpve09'), 'runs_on', source='pve', confidence=0.95)
ig.upsert_edge(conn, ('vm', 'nllonely01'), ('pve_node', 'nlpve08'), 'runs_on', source='pve', confidence=0.95)
conn.commit()
")
PLAN='{"hostname": "nlpve09", "hypothesis": "check status", "steps": [{"command": "kubectl get pods"}]}'

start_test "classifier_bumps_low_to_mixed_on_wide_blast_radius"
  out=$(echo "$PLAN" | GATEWAY_DB="$FIXDB" python3 "$CLASSIFY" --category availability --no-audit)
  risk=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['risk_level'], [s for s in d['signals'] if s.startswith('infragraph:')][0])")
  assert_eq "mixed infragraph:blast-radius-high(10)" "$risk"
end_test

start_test "classifier_signal_never_lowers_and_small_blast_stays_low"
  out=$(echo '{"hostname": "nlpve08", "hypothesis": "check", "steps": [{"command": "kubectl get pods"}]}' | GATEWAY_DB="$FIXDB" python3 "$CLASSIFY" --category availability --no-audit)
  risk=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['risk_level'], [s for s in d['signals'] if s.startswith('infragraph:')][0])")
  assert_eq "low infragraph:blast-radius(1)" "$risk"
end_test

start_test "classifier_disabled_killswitch_leaves_classification_unchanged"
  out=$(echo "$PLAN" | GATEWAY_DB="$FIXDB" INFRAGRAPH_DISABLED=1 python3 "$CLASSIFY" --category availability --no-audit)
  risk=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['risk_level'], len([s for s in d['signals'] if s.startswith('infragraph:')]))")
  assert_eq "low 0" "$risk"
end_test

start_test "classifier_unavailable_graph_fails_open"
  out=$(echo "$PLAN" | GATEWAY_DB="/nonexistent/nope.db" python3 "$CLASSIFY" --category availability --no-audit 2>/dev/null)
  risk=$(printf '%s' "$out" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['risk_level'], [s for s in d['signals'] if s.startswith('infragraph:')][0])")
  assert_eq "low infragraph:unavailable" "$risk"
end_test

start_test "classifier_high_risk_unaffected_by_infragraph"
  # Pin the conservative-remediation carve OFF (CONSERVATIVE_REMEDIATION=0) so this baseline
  # assertion is deterministic regardless of the live ~/gateway.conservative_remediation sentinel —
  # the carve would otherwise reclassify `qm reboot` (a reversible guest-restart) high->mixed, a
  # FALSE failure of the "stays high regardless of graph" intent. Tests must not read live control
  # sentinels (same class as the test-1103 pinning fix).
  out=$(echo '{"hostname": "nlpve09", "hypothesis": "fix", "steps": [{"command": "qm reboot 101"}]}' | GATEWAY_DB="$FIXDB" CONSERVATIVE_REMEDIATION=0 python3 "$CLASSIFY" --category availability --no-audit)
  risk=$(printf '%s' "$out" | python3 -c "import json,sys; print(json.load(sys.stdin)['risk_level'])")
  assert_eq "high" "$risk" "mutation plans stay high regardless of graph"
end_test

# ─── triage wiring (structural) ─────────────────────────────────────────────
start_test "triage_step_2graph_present_and_guarded"
  T="$REPO_ROOT/openclaw/skills/infra-triage/infra-triage.sh"
  grep -q 'Step 2-graph: Infragraph' "$T"; assert_eq 0 $? "step present"
  grep -q 'INFRAGRAPH_DISABLED' "$T"; assert_eq 0 $? "kill-switch guard present"
  grep -q 'timeout 5 python3 "$IG_QUERY"' "$T"; assert_eq 0 $? "hard timeout on CLI calls"
end_test

# ─── observability (-1037) ──────────────────────────────────────────────────
start_test "exporter_writes_valid_prom_file"
  tmpdir=$(mktemp -d)
  tmpdb=$(mktemp --suffix=.db)
  sqlite3 "$tmpdb" < "$REPO_ROOT/schema.sql"
  GATEWAY_DB="$tmpdb" TEXTFILE_DIR="$tmpdir" python3 "$REPO_ROOT/scripts/write-infragraph-metrics.py"
  assert_eq 0 $?
  f="$tmpdir/infragraph.prom"
  [ -f "$f" ]; assert_eq 0 $? "prom file written"
  grep -q "infragraph_exporter_last_run_timestamp" "$f"; assert_eq 0 $?
  grep -q "infragraph_stale_edges 0" "$f"; assert_eq 0 $?
  rm -rf "$tmpdir" "$tmpdb"
end_test

start_test "alert_rules_contain_infragraph_family"
  Y="$REPO_ROOT/prometheus/alert-rules/agentic-health.yml"
  for a in InfragraphMetricsExporterStale InfragraphSeedStale InfragraphPrecisionDrop; do
    grep -q "alert: $a" "$Y"; assert_eq 0 $? "$a present"
  done
  python3 -c "import yaml; yaml.safe_load(open('$Y'))"; assert_eq 0 $? "YAML parses"
end_test

start_test "holistic_health_has_section_39"
  H="$REPO_ROOT/scripts/holistic-agentic-health.sh"
  grep -q 'section "39. Infragraph' "$H"; assert_eq 0 $?
  grep -q 'infragraph-triage-wiring' "$H"; assert_eq 0 $?
end_test

rm -f "$FIXDB"

# ─── -1038: classifier emits compact context for Build Prompt ───────────────
start_test "classifier_emits_infragraph_context_object"
  FIXDB2=$(mktemp --suffix=.db)
  sqlite3 "$FIXDB2" < "$REPO_ROOT/schema.sql"
  (cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib import infragraph as ig
conn = ig.get_db('$FIXDB2')
rel = ig.upsert_edge(conn, ('lxc', 'nl-n8n01'), ('pve_node', 'nl-pve01'), 'runs_on', source='pve', confidence=0.9)
ig.update_dynamics(conn, rel, observed_rules=['Service Down'], delay_s=30.0)
conn.commit()
")
  out=$(echo '{"hostname": "nl-pve01", "hypothesis": "check", "steps": [{"command": "kubectl get pods"}]}' | GATEWAY_DB="$FIXDB2" python3 "$CLASSIFY" --category availability --no-audit)
  ctx=$(printf '%s' "$out" | python3 -c "
import json,sys
d = json.load(sys.stdin)
ig = d.get('infragraph') or {}
print(ig.get('blast_radius_total'), ig.get('top_affected'), ig.get('cascade')[0]['rule'] if ig.get('cascade') else None, ig.get('window_seconds'))")
  assert_eq "1 ['nl-n8n01'] Service Down 900" "$ctx"
  # disabled => no context key at all
  out2=$(echo '{"hostname": "nl-pve01", "hypothesis": "check", "steps": [{"command": "kubectl get pods"}]}' | GATEWAY_DB="$FIXDB2" INFRAGRAPH_DISABLED=1 python3 "$CLASSIFY" --category availability --no-audit)
  haskey=$(printf '%s' "$out2" | python3 -c "import json,sys; print('infragraph' in json.load(sys.stdin))")
  assert_eq "False" "$haskey" "no context object when disabled"
  rm -f "$FIXDB2"
end_test
