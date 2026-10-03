#!/usr/bin/env bash
# test-1451-no-human-anchors.sh — IFRNLLEI01PRD-1451 no-human eval ground-truth anchors.
# Validates the frontier cross-check end-to-end WITHOUT touching the live DB or the network:
# migration tables, schema_version registration, and the metric computation (especially the
# dead-judge local_unscored_rate signal). All on an isolated mktemp DB.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

start_test "migration_021_creates_anchor_tables"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" < "$REPO_ROOT/scripts/migrations/021_no_human_eval_anchors.sql"
  for t in judge_crosscheck autoresolve_outcome; do
    n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$t'")
    assert_eq 1 "$n" "table $t exists"
  done
  rm -f "$tmp"
end_test

start_test "schema_version_registers_anchors"
  v=$(cd "$REPO_ROOT/scripts" && python3 -c "import lib.schema_version as s; print(s.current('judge_crosscheck'), s.current('autoresolve_outcome'))" 2>/dev/null)
  assert_eq "1 1" "$v" "schema_version.current() returns 1 for both anchors"
end_test

start_test "frontier_metrics_compute_dead_judge_signal"
  tmp=$(mktemp --suffix=.db); td=$(mktemp -d)
  sqlite3 "$tmp" < "$REPO_ROOT/scripts/migrations/021_no_human_eval_anchors.sql"
  # A = dead-local (local -1, frontier scored real) ; B = agree ; C = disagree
  sqlite3 "$tmp" "INSERT INTO judge_crosscheck (issue_id,local_score,local_action,frontier_score,frontier_action,score_delta,action_agree) VALUES ('A',-1,'',4,'approve',-999,-1),('B',4,'approve',4,'approve',0,1),('C',4,'approve',2,'reject',2,0);"
  GATEWAY_DB="$tmp" TEXTFILE_DIR="$td" python3 "$REPO_ROOT/scripts/judge-frontier-crosscheck.py" --metrics >/dev/null 2>&1
  pairs=$(awk '/^judge_frontier_pairs /{print $2}' "$td/judge_frontier.prom")
  dead=$(awk '/^judge_frontier_local_unscored_rate /{print $2}' "$td/judge_frontier.prom")
  agree=$(awk '/^judge_frontier_action_agreement_rate /{print $2}' "$td/judge_frontier.prom")
  assert_eq "3" "$pairs" "3 crosscheck pairs"
  assert_eq "0.3333" "$dead" "dead-local rate = 1/3 (the dead-judge signal)"
  assert_eq "0.5000" "$agree" "action agreement = 1 of 2 actionable"
  rm -rf "$tmp" "$td"
end_test

start_test "outcome_metrics_compute"
  tmp=$(mktemp --suffix=.db); td=$(mktemp -d)
  sqlite3 "$tmp" < "$REPO_ROOT/scripts/migrations/021_no_human_eval_anchors.sql"
  # H=held ; F=false-resolve ; M=false-resolve the judge scored>=4 (judge-miss) ; P=pending
  sqlite3 "$tmp" "INSERT INTO autoresolve_outcome (issue_id,held,refire_within_hours,judge_score) VALUES ('H',1,-1,3),('F',0,2.0,2),('M',0,3.0,5),('P',-1,-1,-1);"
  GATEWAY_DB="$tmp" TEXTFILE_DIR="$td" python3 "$REPO_ROOT/scripts/session-outcome-truth.py" --metrics >/dev/null 2>&1
  assert_eq "3"      "$(awk '/^autoresolve_evaluated /{print $2}' "$td/autoresolve_outcome.prom")"                  "3 evaluated (held in 0,1)"
  assert_eq "0.3333" "$(awk '/^autoresolve_held_rate /{print $2}' "$td/autoresolve_outcome.prom")"                  "held_rate = 1/3"
  assert_eq "2"      "$(awk '/^autoresolve_false_resolve_total /{print $2}' "$td/autoresolve_outcome.prom")"        "2 false-resolves"
  assert_eq "1"      "$(awk '/^autoresolve_judge_missed_false_resolve /{print $2}' "$td/autoresolve_outcome.prom")" "1 judge-miss (held=0 + judge>=4)"
  assert_eq "1"      "$(awk '/^autoresolve_pending /{print $2}' "$td/autoresolve_outcome.prom")"                    "1 pending"
  rm -rf "$tmp" "$td"
end_test

start_test "outcome_excludes_dispositioned_patterns"
  tmp=$(mktemp --suffix=.db)
  sqlite3 "$tmp" "CREATE TABLE incident_knowledge (alert_rule TEXT, hostname TEXT, confidence REAL, suppression_status TEXT, tags TEXT, resolution TEXT);"
  sqlite3 "$tmp" "INSERT INTO incident_knowledge VALUES ('DemotedRule','h1',-1,'analysis_only','governance','x'),('TransientRule','*',0.9,'open','expected-noise','y'),('RealRule','h1',0.9,'open','infra','fixed');"
  r=$(GATEWAY_DB="$tmp" python3 -c "
import importlib.util, sqlite3, sys
sys.path.insert(0,'$REPO_ROOT/scripts')
spec=importlib.util.spec_from_file_location('sot','$REPO_ROOT/scripts/session-outcome-truth.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
db=sqlite3.connect('$tmp')
print(m.is_dispositioned(db,'h1','DemotedRule'), m.is_dispositioned(db,'h1','TransientRule'), m.is_dispositioned(db,'h1','RealRule'))
" 2>/dev/null)
  assert_eq "True True False" "$r" "is_dispositioned: demoted=True, transient(*-host)=True, real=False"
  rm -f "$tmp"
end_test

start_test "context_failure_taxonomy_classifies_all_classes"
  tmp=$(mktemp --suffix=.db); td=$(mktemp -d)
  sqlite3 "$tmp" "CREATE TABLE ragas_evaluation (faithfulness REAL, context_recall REAL, answer_relevance REAL, context_precision REAL, query TEXT, issue_id TEXT, created_at DATETIME);"
  sqlite3 "$tmp" "CREATE TABLE incident_knowledge (valid_until DATETIME, suppression_status TEXT);"
  # poisoning(F<.5,low R) ; distraction(P<.5) ; confusion(AR<.5) ; clash(F<.5 & R,P>=.7) ; none ; unscored(all -1 -> skip)
  sqlite3 "$tmp" "INSERT INTO ragas_evaluation VALUES (0.3,0.0,0.8,0.9,'q1','A',datetime('now')),(0.9,0.9,0.9,0.2,'q2','B',datetime('now')),(0.9,0.9,0.3,0.9,'q3','C',datetime('now')),(0.3,0.8,0.8,0.8,'q4','D',datetime('now')),(0.9,0.9,0.9,0.9,'q5','E',datetime('now')),(-1,-1,-1,-1,'q6','F',datetime('now'));"
  GATEWAY_DB="$tmp" TEXTFILE_DIR="$td" python3 "$REPO_ROOT/scripts/context-failure-taxonomy.py" --metrics >/dev/null 2>&1
  v() { grep "class=\"$1\"" "$td/context_failure.prom" | awk '{print $NF}'; }
  assert_eq "1" "$(v poisoning)"   "poisoning=1 (F<0.5, low R)"
  assert_eq "1" "$(v clash)"       "clash=1 (F<0.5 but R,P>=0.7)"
  assert_eq "1" "$(v distraction)" "distraction=1 (P<0.5)"
  assert_eq "1" "$(v confusion)"   "confusion=1 (AR<0.5)"
  assert_eq "1" "$(v none)"        "none=1 (all dims healthy)"
  assert_eq "5" "$(awk '/^context_failure_classified_total /{print $2}' "$td/context_failure.prom")" "classified=5 (unscored row skipped)"
  rm -rf "$tmp" "$td"
end_test
