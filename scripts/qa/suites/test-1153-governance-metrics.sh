#!/usr/bin/env bash
# IFRNLLEI01PRD-1153 — false-auto-resolve + repeat-incident governance metrics.
# Recurrence is computed from triage.log (session_log/incident_knowledge lack the
# host+rule linkage). Auto-demote is shadow-OFF by default. CI-safe.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1153-governance-metrics"

WR="$REPO_ROOT/scripts/write-governance-metrics.py"
MIG="$REPO_ROOT/scripts/migrations/018_incident_knowledge_suppression_status.sql"

start_test "migration_018_adds_suppression_columns"
  n=$(grep -cE "ADD COLUMN (suppression_status|demotion_reason|demotion_at)" "$MIG")
  assert_eq "3" "$n"
end_test

start_test "writer_py_syntax_ok"
  assert_eq "OK" "$(python3 -c "import ast;ast.parse(open('$WR').read());print('OK')" 2>/dev/null || echo FAIL)"
end_test

start_test "recurrence_logic_flags_resolve_then_recur_within_24h"
  # deterministic fixture: hostA/ruleX resolved then recurs in 2h => 1 false-resolve;
  # hostB/ruleY fires 3x => repeat class + demote candidate; hostC resolved, recurs
  # 30h later => NOT a false-resolve (outside 24h).
  out=$(cd "$REPO_ROOT/scripts" && python3 - <<'PY'
import importlib.util, datetime as dt, os
spec = importlib.util.spec_from_file_location("wg", "write-governance-metrics.py")
wg = importlib.util.module_from_spec(spec); spec.loader.exec_module(wg)
def row(ts, h, r, o): return {"ts": ts, "host": h, "rule": r, "site": "nl", "outcome": o, "issue_id": ""}
now = dt.datetime.utcnow()
def t(hrs): return (now - dt.timedelta(hours=hrs)).strftime("%Y-%m-%d %H:%M:%S")
rows = [
    row(t(50), "hostA", "ruleX", "resolved"),     # resolve...
    row(t(48), "hostA", "ruleX", "escalated"),    # ...recurs 2h later => false-resolve
    row(t(40), "hostB", "ruleY", "escalated"),
    row(t(39), "hostB", "ruleY", "escalated"),
    row(t(38), "hostB", "ruleY", "escalated"),    # 3x => repeat + candidate
    row(t(60), "hostC", "ruleZ", "resolved"),     # resolve...
    row(t(29), "hostC", "ruleZ", "escalated"),    # ...recurs 31h later => NOT false-resolve
]
fr, rc, cand = wg.compute(rows)
print(f"{fr} {rc} {[c[0] for c in cand]}")
PY
)
  # 1 false-resolve (hostA only; hostC recurs at 31h > 24h => excluded).
  # repeat classes = hostA(2) + hostB(3) + hostC(2) = 3 (all have >=2 events).
  # demote candidate = hostB only (>=3 events).
  assert_eq "1 3 ['hostB']" "$out"
end_test

start_test "autodemote_default_on_autonomy_forward"
  # human-as-circuit-breaker, not gatekeeper: demotion auto-executes (reversible).
  assert_eq "1" "$(grep -cE 'GOVERNANCE_AUTODEMOTE.*\"1\"' "$WR")"
end_test

start_test "known_transient_patterns_excluded_from_demotion"
  # a deliberately-suppressed flappy pattern recurs BY DESIGN; demoting it would
  # re-introduce suppressed noise. is_intentionally_suppressed must exclude it.
  FIX=$(mktemp --suffix=.db); sqlite3 "$FIX" < "$REPO_ROOT/schema.sql"
  sqlite3 "$FIX" < "$REPO_ROOT/scripts/migrations/018_incident_knowledge_suppression_status.sql" 2>/dev/null
  sqlite3 "$FIX" "INSERT INTO incident_knowledge(alert_rule,hostname,confidence,resolution,tags) VALUES('FlapAlert','hostX',0.9,'Self-resolved; transient flap','transient,flap');"
  sqlite3 "$FIX" "INSERT INTO incident_knowledge(alert_rule,hostname,confidence,resolution,tags) VALUES('RealBug','hostY',0.5,'fixed disk','');"
  out=$(cd "$REPO_ROOT/scripts" && GATEWAY_DB="$FIX" python3 -c "
import sqlite3, importlib.util as u
s=u.spec_from_file_location('wg','write-governance-metrics.py'); wg=u.module_from_spec(s); s.loader.exec_module(wg)
c=sqlite3.connect('$FIX')
print(wg.is_intentionally_suppressed(c,'hostX','FlapAlert'), wg.is_intentionally_suppressed(c,'hostY','RealBug'))")
  rm -f "$FIX"
  assert_eq "True False" "$out"
end_test

start_test "tier1_escalates_a_governance_demoted_pattern_safe_direction"
  # the demotion CONSUMER: a demoted (host,rule) must ESCALATE (never suppress).
  FIX=$(mktemp --suffix=.db); sqlite3 "$FIX" < "$REPO_ROOT/schema.sql"
  sqlite3 "$FIX" < "$REPO_ROOT/scripts/migrations/018_incident_knowledge_suppression_status.sql" 2>/dev/null
  # incident_knowledge.valid_until is live-schema drift (present in prod, absent
  # from schema.sql + migrations); add it to the fixture to mirror production.
  sqlite3 "$FIX" "ALTER TABLE incident_knowledge ADD COLUMN valid_until DATETIME;" 2>/dev/null
  sqlite3 "$FIX" "INSERT INTO incident_knowledge(alert_rule,hostname,confidence,suppression_status,valid_until) VALUES('Service up/down','hostZ',-1,'analysis_only',datetime('now','+30 days'));"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "
import sqlite3, datetime
from lib import tier1_suppression as t
c=sqlite3.connect('$FIX'); c.row_factory=sqlite3.Row
d=t.check_phase2_knownpattern('hostZ','Service up/down','warning',c,datetime.datetime.utcnow(),30)
print(d.outcome, d.signals.get('governance_demoted'))")
  rm -f "$FIX"
  assert_eq "escalate True" "$out"
end_test

start_test "governance_rows_excluded_from_rag"
  # demotion markers must never pollute RAG embedding/retrieval.
  K="$REPO_ROOT/scripts/kb-semantic-search.py"
  assert_eq "3" "$(grep -cE "COALESCE\(project,''\) != 'chatops-governance'" "$K")"
end_test

start_test "emits_required_metric_series"
  for m in chatops_false_auto_resolve_total chatops_repeat_incident_classes \
           chatops_governance_demote_candidates chatops_governance_demoted_patterns_total \
           chatops_governance_metrics_last_run_timestamp; do
    grep -q "$m" "$WR" || { echo "MISSING $m"; break; }
  done
  assert_eq "OK" "$(for m in chatops_false_auto_resolve_total chatops_repeat_incident_classes chatops_governance_demote_candidates chatops_governance_demoted_patterns_total chatops_governance_metrics_last_run_timestamp; do grep -q "$m" "$WR" || { echo "MISSING $m"; exit; }; done; echo OK)"
end_test
