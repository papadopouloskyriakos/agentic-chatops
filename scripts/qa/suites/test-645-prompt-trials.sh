#!/usr/bin/env bash
# IFRNLLEI01PRD-645 — preference-iterating prompt patcher.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="645-prompt-trials"

# ─── library primitives ────────────────────────────────────────────────────
start_test "schema_tables_exist"
  tmp=$(fresh_db)
  a=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE name='prompt_patch_trial'")
  b=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE name='session_trial_assignment'")
  assert_eq 1 "$a"
  assert_eq 1 "$b"
  cleanup_db "$tmp"
end_test

start_test "start_trial_writes_row_with_schema_version"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  tid=$(GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate
tid = start_trial('s','d',[Candidate(0,'a','x','c'),Candidate(1,'b','y','c'),Candidate(2,'c','z','c')],baseline_mean=2.5)
print(tid)
")
  assert_gt "$tid" 0
  sv=$(sqlite3 "$tmp" "SELECT schema_version FROM prompt_patch_trial WHERE id=$tid")
  assert_eq "1" "$sv"
  cleanup_db "$tmp"
end_test

start_test "cannot_start_two_active_trials_for_same_surface_dimension"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  rc=0
  out=$(GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate
c=[Candidate(i,'a'+str(i),'x','c') for i in range(3)]
start_trial('s','d',c,baseline_mean=2.5)
start_trial('s','d',c,baseline_mean=2.5)  # should fail
" 2>&1) || rc=$?
  assert_ne 0 "$rc"
  assert_contains "$out" "active trial already exists"
  cleanup_db "$tmp"
end_test

# ─── deterministic assignment ──────────────────────────────────────────────
start_test "assign_variant_is_deterministic"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from prompt_patch_trial import assign_variant
a = assign_variant('ISSUE-1', 7, 3)
b = assign_variant('ISSUE-1', 7, 3)
c = assign_variant('ISSUE-2', 7, 3)
print(a, b, c)
print('SAME' if a==b else 'DIFF')
")
  # First two must be equal (same input), third may differ.
  assert_contains "$out" "SAME"
end_test

start_test "assign_variant_roughly_uniform_over_n_plus_control"
  cd "$REPO_ROOT/scripts"
  out=$(PYTHONPATH=lib python3 -c "
from prompt_patch_trial import assign_variant
from collections import Counter
c = Counter(assign_variant(f'ISS-{i:04d}', 42, 3) for i in range(400))
# 4 arms (3 candidates + control = -1); expected 100 each.
print(dict(c))
# Fail if any arm is <60 or >140 (wide binomial CI for N=400).
bad = [v for v in c.values() if v < 60 or v > 140]
print('BAD' if bad else 'OK')
")
  assert_contains "$out" "OK"
end_test

start_test "record_assignment_is_idempotent"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate, assign_and_record, get_trial
c=[Candidate(i,'a'+str(i),'x','c') for i in range(3)]
tid = start_trial('s','d',c,baseline_mean=2.5)
t = get_trial(tid)
v1 = assign_and_record('ISS-1', t)
v2 = assign_and_record('ISS-1', t)  # should return same variant, no new row
print(v1, v2)
"
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM session_trial_assignment WHERE issue_id='ISS-1'")
  assert_eq 1 "$n"
  cleanup_db "$tmp"
end_test

# ─── score collection ──────────────────────────────────────────────────────
start_test "collect_arm_scores_groups_by_variant"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
import sqlite3, random
from prompt_patch_trial import start_trial, Candidate, assign_and_record, collect_arm_scores, get_trial
c=[Candidate(i,'x','i','actionability') for i in range(3)]
tid = start_trial('infra-triage','actionability',c,baseline_mean=2.5)
t = get_trial(tid)
for i in range(40):
    assign_and_record(f'I-{i:02d}', t)
# seed session_judgment for each assigned issue
conn = sqlite3.connect('$tmp')
for row in conn.execute('SELECT issue_id, variant_idx FROM session_trial_assignment'):
    conn.execute('INSERT INTO session_judgment (issue_id, judge_model, actionability, schema_version) VALUES (?, ?, ?, 1)',
                 (row[0], 'test', 3.0 + 0.01 * row[1]))
conn.commit()
arms = collect_arm_scores(t)
print('arms:', sorted(arms.keys()))
print('total:', sum(len(v) for v in arms.values()))
"
  cleanup_db "$tmp"
end_test

# ─── finalize paths ────────────────────────────────────────────────────────
start_test "finalize_still_active_when_arms_incomplete"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" PROMPT_TRIAL_MIN_SAMPLES=10 PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate, finalize
c=[Candidate(i,'x','i','c') for i in range(3)]
tid = start_trial('s','actionability',c,baseline_mean=2.5)
r = finalize(tid)
print(r.status)
")
  assert_eq "still_active" "$out"
  cleanup_db "$tmp"
end_test

start_test "finalize_completed_when_winner_beats_control"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  patches=$(mktemp)
  out=$(GATEWAY_DB="$tmp" PROMPT_TRIAL_MIN_SAMPLES=5 PROMPT_PATCHES_FILE="$patches" PYTHONPATH=lib python3 -c "
import sqlite3, random
from prompt_patch_trial import start_trial, Candidate, assign_and_record, finalize, get_trial
c=[Candidate(i,'v'+str(i),'inst','actionability') for i in range(3)]
tid = start_trial('build-prompt','actionability',c,baseline_mean=2.5,min_samples_per_arm=5,min_lift=0.3)
t = get_trial(tid)
for i in range(40):
    assign_and_record(f'W-{i:03d}', t)
conn = sqlite3.connect('$tmp')
WIN = 1
for row in conn.execute('SELECT issue_id, variant_idx FROM session_trial_assignment'):
    random.seed(row[0])
    s = 4.0 + random.random()*0.4 if row[1]==WIN else 2.8 + random.random()*0.4
    conn.execute('INSERT INTO session_judgment (issue_id, judge_model, actionability, schema_version) VALUES (?, ?, ?, 1)',
                 (row[0], 'test', s))
conn.commit()
r = finalize(tid)
print(r.status, r.winner_idx)
")
  assert_contains "$out" "completed"
  assert_contains "$out" "1"   # winner_idx
  # Patch file must exist and contain the winner's instruction.
  assert_file_exists "$patches"
  assert_contains "$(cat $patches)" '"active": true'
  assert_contains "$(cat $patches)" '"source":'
  rm -f "$patches"
  cleanup_db "$tmp"
end_test

start_test "finalize_aborted_no_winner_when_no_candidate_beats_control"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  patches=$(mktemp)
  out=$(GATEWAY_DB="$tmp" PROMPT_TRIAL_MIN_SAMPLES=5 PROMPT_PATCHES_FILE="$patches" PYTHONPATH=lib python3 -c "
import sqlite3, random
from prompt_patch_trial import start_trial, Candidate, assign_and_record, finalize, get_trial
c=[Candidate(i,'v'+str(i),'inst','actionability') for i in range(3)]
tid = start_trial('build-prompt','actionability',c,baseline_mean=2.5,min_samples_per_arm=5,min_lift=0.3)
t = get_trial(tid)
for i in range(40):
    assign_and_record(f'N-{i:03d}', t)
conn = sqlite3.connect('$tmp')
# All arms similar — no winner.
for row in conn.execute('SELECT issue_id, variant_idx FROM session_trial_assignment'):
    random.seed(row[0])
    s = 3.0 + random.random()*0.2
    conn.execute('INSERT INTO session_judgment (issue_id, judge_model, actionability, schema_version) VALUES (?, ?, ?, 1)',
                 (row[0], 'test', s))
conn.commit()
r = finalize(tid)
print(r.status)
")
  assert_contains "$out" "aborted_no_winner"
  # Patch file must NOT contain a winner.
  if [ -f "$patches" ]; then
    if grep -q '"active": true' "$patches" 2>/dev/null; then
      fail_test "patch file was written despite aborted_no_winner"
    fi
  fi
  rm -f "$patches"
  cleanup_db "$tmp"
end_test

start_test "abort_stale_trials_marks_overdue_as_timeout"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate
c=[Candidate(i,'x','i','c') for i in range(3)]
tid = start_trial('s','d',c,baseline_mean=2.5)
print(tid)
" >/dev/null
  # Force trial_ends_at to the past.
  sqlite3 "$tmp" "UPDATE prompt_patch_trial SET trial_ends_at = datetime('now','-1 day') WHERE id=1"
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import abort_stale_trials
print('aborted:', abort_stale_trials())
"
  st=$(sqlite3 "$tmp" "SELECT status FROM prompt_patch_trial WHERE id=1")
  assert_eq "aborted_timeout" "$st"
  cleanup_db "$tmp"
end_test

# ─── generator + analyze ───────────────────────────────────────────────────
start_test "analyze_detects_low_scoring_dimension"
  tmp=$(fresh_db)
  for i in 1 2 3 4 5 6; do
    sqlite3 "$tmp" "INSERT INTO session_judgment (issue_id, judge_model, actionability, schema_version) VALUES ('A-$i','haiku',2.0,1)"
  done
  out=$(GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/prompt-patch-trial.py" --analyze)
  assert_contains "$out" "actionability"
  cleanup_db "$tmp"
end_test

start_test "start_refuses_without_enable_flag"
  tmp=$(fresh_db)
  rc=0
  out=$(GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/prompt-patch-trial.py" --start 2>&1) || rc=$?
  assert_eq 2 "$rc"
  assert_contains "$out" "PROMPT_TRIAL_ENABLED"
  cleanup_db "$tmp"
end_test

start_test "start_creates_trial_when_enabled_and_dim_low"
  tmp=$(fresh_db)
  for i in 1 2 3 4 5; do
    sqlite3 "$tmp" "INSERT INTO session_judgment (issue_id, judge_model, actionability, schema_version) VALUES ('Z-$i','haiku',2.0,1)"
  done
  GATEWAY_DB="$tmp" PROMPT_TRIAL_ENABLED=1 "$REPO_ROOT/scripts/prompt-patch-trial.py" --start >/dev/null
  n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM prompt_patch_trial WHERE dimension='actionability' AND status='active'")
  assert_eq 1 "$n"
  # Candidates JSON must have 3 items.
  cjson=$(sqlite3 "$tmp" "SELECT candidates_json FROM prompt_patch_trial LIMIT 1")
  cn=$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1])))" "$cjson")
  assert_eq 3 "$cn"
  cleanup_db "$tmp"
end_test

# ─── finalizer cron script ─────────────────────────────────────────────────
start_test "finalizer_cron_dry_run_does_not_mutate"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate
c=[Candidate(i,'x','i','c') for i in range(3)]
start_trial('s','d',c,baseline_mean=2.5)
" >/dev/null
  GATEWAY_DB="$tmp" "$REPO_ROOT/scripts/finalize-prompt-trials.py" --dry-run --json >/tmp/out.$$ 2>&1
  rm -f /tmp/out.$$
  # Trial must still be active.
  st=$(sqlite3 "$tmp" "SELECT status FROM prompt_patch_trial WHERE id=1")
  assert_eq "active" "$st"
  cleanup_db "$tmp"
end_test

# ─── prometheus exporter ───────────────────────────────────────────────────
start_test "prom_exporter_emits_expected_metrics"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  GATEWAY_DB="$tmp" PYTHONPATH=lib python3 -c "
from prompt_patch_trial import start_trial, Candidate
c=[Candidate(i,'x','i','c') for i in range(3)]
start_trial('s','d',c,baseline_mean=2.5)
" >/dev/null
  prom_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$prom_dir" "$REPO_ROOT/scripts/write-trial-metrics.sh"
  out=$(cat "$prom_dir/prompt_trials.prom")
  assert_contains "$out" "prompt_trials_active 1"
  assert_contains "$out" "prompt_trials_completed_total 0"
  rm -rf "$prom_dir"
  cleanup_db "$tmp"
end_test
