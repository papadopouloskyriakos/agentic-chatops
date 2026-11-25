#!/usr/bin/env bash
# IFRNLLEI01PRD-1034 (learners) + -1035 (replay eval) — synthetic-data suite.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1034-infragraph-learn"
SEED="$REPO_ROOT/scripts/infragraph-seed.py"
LEARN="$REPO_ROOT/scripts/infragraph-learn.py"
EVAL="$REPO_ROOT/scripts/infragraph-eval.py"

# Shared fixture: schema + openclaw_memory + chaos_experiments + declared edges
FIXDB=$(mktemp --suffix=.db)
sqlite3 "$FIXDB" < "$REPO_ROOT/schema.sql"
sqlite3 "$FIXDB" "
  CREATE TABLE IF NOT EXISTS openclaw_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT 'triage', key TEXT NOT NULL, value TEXT NOT NULL, issue_id TEXT DEFAULT '', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS chaos_experiments (id INTEGER PRIMARY KEY, experiment_id TEXT UNIQUE, chaos_type TEXT, targets TEXT, expected_alerts TEXT, unexpected_alerts TEXT, mttd_seconds REAL, mttr_seconds REAL, verdict TEXT);
"
python3 "$SEED" --db "$FIXDB" --tunnels --declared >/dev/null

FIXLOG=$(mktemp --suffix=.log)
cat > "$FIXLOG" << 'LOG'
2026-06-01T10:00:00Z|nl-pve01|-- ALERT -- nl-pve01 -  Device Down! Due to no ICMP response.  - Critical Alert|nl|escalated|0|0|IFR-1
2026-06-01T10:01:30Z|nl-n8n01|-- ALERT -- nl-n8n01 -  Service up/down  - Critical Alert|nl|escalated|0|0|IFR-2
2026-06-02T11:00:00Z|nl-pve01|-- ALERT -- nl-pve01 -  Device Down! Due to no ICMP response.  - Critical Alert|nl|escalated|0|0|IFR-3
2026-06-02T11:02:00Z|nl-n8n01|-- ALERT -- nl-n8n01 -  Service up/down  - Critical Alert|nl|escalated|0|0|IFR-4
2026-06-03T09:00:00Z|nl-pve01|-- ALERT -- nl-pve01 -  Device Down! Due to no ICMP response.  - Critical Alert|nl|escalated|0|0|IFR-5
2026-06-03T09:03:00Z|nl-n8n01|-- ALERT -- nl-n8n01 -  Service up/down  - Critical Alert|nl|escalated|0|0|IFR-6
2026-06-03T18:00:00Z|gr-sw01|-- ALERT -- gr-sw01 -  Device Down! Due to no ICMP response.  - Critical Alert|gr|escalated|0|0|IFR-7
LOG

start_test "rule_normalization_strips_alert_wrapper"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sys; sys.path.insert(0, '.')
from lib.infragraph import normalize_rule
print(normalize_rule('-- ALERT -- gr-pve02 -  Service up/down  - Critical Alert'))
print(normalize_rule('Plain Rule Name'))
")
  assert_eq "Service up/down
Plain Rule Name" "$out"
end_test

start_test "chaos_learner_updates_tunnel_dynamics_and_watermark"
  sqlite3 "$FIXDB" "INSERT INTO chaos_experiments (experiment_id, chaos_type, targets, expected_alerts, mttd_seconds, mttr_seconds, verdict) VALUES ('chaos-qa-001', 'tunnel', '{\"tunnels_killed\": [{\"tunnel\": \"NL ↔ GR\", \"wan\": \"budget\"}]}', '[\"Tunnel Down\"]', 42.0, 300.0, 'PASS')"
  out=$(python3 "$LEARN" --db "$FIXDB" --from-chaos)
  assert_contains "$out" '"edge_updates": 2'
  src=$(sqlite3 "$FIXDB" "SELECT DISTINCT d.source FROM infragraph_dynamics d JOIN graph_relationships r ON r.id=d.rel_id JOIN graph_entities t ON t.id=r.target_id WHERE t.name='tunnel:NL-GR:budget'")
  assert_eq "chaos" "$src" "provenance upgraded to chaos"
  # idempotency: watermark prevents re-processing
  out2=$(python3 "$LEARN" --db "$FIXDB" --from-chaos)
  assert_contains "$out2" '"experiments_processed": 0'
end_test

start_test "incident_miner_respects_lift_gate"
  out=$(python3 "$LEARN" --db "$FIXDB" --from-incidents --log "$FIXLOG")
  assert_contains "$out" '"edges_written": 0'  # lift 2.33 < default 3.0
  out2=$(INFRAGRAPH_LEARN_MIN_LIFT=2.0 python3 "$LEARN" --db "$FIXDB" --from-incidents --log "$FIXLOG")
  assert_contains "$out2" '"edges_written": 1'
end_test

start_test "incident_miner_resolves_existing_entity_types"
  # nl-n8n01 was seeded as lxc (declared doc) — the mined edge must attach
  # to that node, not create a physical_host twin.
  twins=$(sqlite3 "$FIXDB" "SELECT COUNT(*) FROM graph_entities WHERE name='nl-n8n01'")
  assert_eq 1 "$twins" "no duplicate entity for nl-n8n01"
  edge=$(sqlite3 "$FIXDB" "SELECT s.entity_type || '>' || t.entity_type FROM graph_relationships r JOIN graph_entities s ON s.id=r.source_id JOIN graph_entities t ON t.id=r.target_id JOIN infragraph_dynamics d ON d.rel_id=r.id WHERE d.source='incident'")
  assert_eq "lxc>pve_node" "$edge"
end_test

start_test "incident_mined_confidence_caps_below_suppression_eligibility"
  c=$(sqlite3 "$FIXDB" "SELECT MAX(confidence) FROM infragraph_dynamics WHERE source='incident'")
  ok=$(python3 -c "print(1 if float('$c') < 0.8 else 0)")
  assert_eq 1 "$ok" "incident-mined conf $c stays below the 0.8 Phase-C cutoff"
end_test

start_test "replay_retrodicts_symptom_not_root"
  out=$(python3 "$EVAL" --db "$FIXDB" --replay 2026-06-02 --log "$FIXLOG")
  # control_predicted is stochastic (degree-preserving shuffle) — assert only
  # the deterministic fields: 1 of 2 alerts predicted at rule level, and the
  # root miss is the pve01 parent itself.
  rule=$(printf '%s' "$out" | python3 -c "import json,sys; r=json.load(sys.stdin)['replay']; print(r['predicted_rule_level'], r['alerts_total'], r['sample_misses'][0]['host'])")
  assert_eq "1 2 nl-pve01" "$rule" "symptom rule-level predicted; root is the only miss"
end_test

start_test "eval_pending_scores_recorded_prediction"
  # record a prediction with created_at backdated beyond its window, then evaluate
  sqlite3 "$FIXDB" "INSERT INTO infragraph_predictions (created_at, kind, parent_host, parent_rule, window_seconds, predicted, control_predicted) VALUES ('2026-06-02 11:00:00', 'cascade', 'nl-pve01', 'Device Down! Due to no ICMP response.', 900, '[{\"host\": \"nl-n8n01\", \"rule\": \"Service up/down\"}]', '[{\"host\": \"gr-sw01\", \"rule\": \"Device Down! Due to no ICMP response.\"}]')"
  out=$(python3 "$EVAL" --db "$FIXDB" --pending --log "$FIXLOG")
  assert_contains "$out" '"evaluated": 1'
  row=$(sqlite3 "$FIXDB" "SELECT tp || '/' || fp || '/' || fn || '/' || control_tp FROM infragraph_predictions WHERE evaluated_at IS NOT NULL")
  assert_eq "1/0/0/0" "$row" "tp=1 (n8n01 followed), control miss"
end_test

rm -f "$FIXDB" "$FIXLOG"
