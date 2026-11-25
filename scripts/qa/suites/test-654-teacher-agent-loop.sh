#!/usr/bin/env bash
# IFRNLLEI01PRD-654 — teacher-agent loop tier.
# Exercises: Prometheus exporter, alert rules YAML, Grafana dashboard JSON,
# touch-last-run plumbing in teacher-agent.py, and crontab entries.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="654-teacher-agent-loop"

# ── Exporter produces a valid Prometheus textfile ─────────────────────────

start_test "exporter_emits_all_required_metric_families"
  tmp=$(fresh_db)
  out_dir=$(mktemp -d)
  # Seed a learning_progress row so non-zero metrics appear.
  sqlite3 "$tmp" "
    INSERT INTO learning_progress
      (operator, topic, mastery_score, highest_bloom_reached, next_due, schema_version)
    VALUES
      ('@alice:m', 'gulli-01-tool-use', 0.92, 'application', datetime('now', '-1 day'), 1);
    INSERT INTO learning_progress
      (operator, topic, mastery_score, highest_bloom_reached, next_due, schema_version)
    VALUES
      ('@alice:m', 'gulli-02-multi-agent', 0.45, 'recognition', datetime('now', '+10 days'), 1);
    INSERT INTO learning_sessions
      (operator, topic, session_type, bloom_level, started_at, completed_at, quiz_score, schema_version)
    VALUES
      ('@alice:m', 'gulli-01-tool-use', 'quiz', 'application', datetime('now', '-2 days'), datetime('now', '-2 days'), 0.82, 1);
    INSERT INTO teacher_operator_dm
      (operator_mxid, dm_room_id, schema_version)
    VALUES
      ('@alice:m', '!alice', 1);"
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$out_dir" \
    bash "$REPO_ROOT/scripts/write-learning-metrics.sh"
  [ -f "$out_dir/learning_progress.prom" ] || fail_test "exporter did not write output file"
  content=$(cat "$out_dir/learning_progress.prom")
  for metric in \
    'learning_topics_total' \
    'learning_topics_mastered' \
    'learning_topics_due' \
    'learning_quiz_accuracy_7d' \
    'learning_weekly_sessions_total' \
    'learning_longest_streak_days' \
    'learning_bloom_distribution' \
    'learning_operators_total' \
    'learning_morning_nudge_last_run_timestamp' \
    'learning_class_digest_last_run_timestamp'; do
    echo "$content" | grep -q "^# TYPE $metric " || fail_test "missing TYPE line for $metric"
  done
  # Non-zero values for the seeded operator.
  echo "$content" | grep -q 'learning_topics_total{operator="@alice:m"} 2' || fail_test "alice topics_total != 2"
  echo "$content" | grep -q 'learning_topics_mastered{operator="@alice:m"} 1' || fail_test "alice mastered != 1"
  echo "$content" | grep -q 'learning_topics_due{operator="@alice:m"} 1' || fail_test "alice due != 1"
  echo "$content" | grep -q 'learning_quiz_accuracy_7d{operator="@alice:m"} 0.82' || fail_test "alice quiz_accuracy_7d != 0.82"
  echo "$content" | grep -q 'learning_bloom_distribution{operator="@alice:m",bloom_level="application"} 1' \
    || fail_test "bloom_distribution missing application band"
  cleanup_db "$tmp"
  rm -rf "$out_dir"
end_test

start_test "exporter_is_atomic_no_tmp_leftover"
  tmp=$(fresh_db)
  out_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$out_dir" \
    bash "$REPO_ROOT/scripts/write-learning-metrics.sh"
  # The .tmp file must have been renamed — it should not exist after successful write.
  [ ! -f "$out_dir/learning_progress.prom.tmp" ] || fail_test "tmp file left behind"
  cleanup_db "$tmp"
  rm -rf "$out_dir"
end_test

start_test "exporter_handles_pre_migration_db_gracefully"
  tmp=$(mktemp --suffix=.db)
  # Empty DB — no learning_progress table. Exporter must exit 0 and emit a sentinel.
  out_dir=$(mktemp -d)
  GATEWAY_DB="$tmp" PROMETHEUS_TEXTFILE_DIR="$out_dir" \
    bash "$REPO_ROOT/scripts/write-learning-metrics.sh"
  grep -q "not yet migrated" "$out_dir/learning_progress.prom" \
    || fail_test "expected 'not yet migrated' sentinel"
  rm -f "$tmp"
  rm -rf "$out_dir"
end_test

# ── Prometheus alert rules YAML is well-formed ────────────────────────────

start_test "alert_rules_parse_and_cover_expected_alerts"
  cd "$REPO_ROOT"
  out=$(python3 -c "
import yaml
y = yaml.safe_load(open('prometheus/alert-rules/teacher-agent.yml'))
assert 'groups' in y and len(y['groups']) == 1
rules = {r['alert'] for r in y['groups'][0]['rules']}
for needed in ('TeacherAgentMetricsAbsent', 'TeacherAgentMorningNudgeStale', 'TeacherAgentClassDigestStale'):
    assert needed in rules, f'missing alert: {needed}'
for r in y['groups'][0]['rules']:
    assert r.get('for'), f'alert {r[\"alert\"]} missing for: duration'
    assert r.get('labels', {}).get('severity'), f'alert {r[\"alert\"]} missing severity'
    a = r.get('annotations', {})
    assert a.get('summary'), f'alert {r[\"alert\"]} missing summary'
    assert a.get('description'), f'alert {r[\"alert\"]} missing description'
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Grafana dashboard JSON is well-formed ─────────────────────────────────

start_test "grafana_dashboard_is_valid_and_references_learning_metrics"
  cd "$REPO_ROOT"
  out=$(python3 -c "
import json
d = json.load(open('grafana/teacher-agent.json'))
assert d['uid'] == 'teacher-agent'
assert 'Teacher Agent' in d['title']
panels = d['panels']
assert len(panels) >= 10, f'expected >=10 panels, got {len(panels)}'
# Every panel must target a learning_* metric
REDACTED_a7b84d63
used = set()
for p in panels:
    for t in p.get('targets', []):
        expr = t.get('expr', '')
        for m in re.finditer(r'\blearning_[a-z0-9_]+', expr):
            used.add(m.group(0))
required = {
    'learning_operators_total',
    'learning_topics_mastered',
    'learning_topics_due',
    'learning_weekly_sessions_total',
    'learning_longest_streak_days',
    'learning_quiz_accuracy_7d',
    'learning_bloom_distribution',
    'learning_morning_nudge_last_run_timestamp',
    'learning_class_digest_last_run_timestamp',
}
missing = required - used
assert not missing, f'dashboard missing panels for: {missing}'
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── touch-last-run plumbing in teacher-agent.py ──────────────────────────

start_test "morning_nudge_touches_last_run_lockfile"
  tmp=$(fresh_db)
  last_dir=$(mktemp -d)
  out=$(GATEWAY_DB="$tmp" TEACHER_LAST_RUN_DIR="$last_dir" python3 -c "
import sys, json
sys.path.insert(0, '$REPO_ROOT/scripts/lib')
import matrix_teacher as mx
mx.is_authorised = lambda *a, **kw: True
mx.resolve_dm    = lambda op, **kw: '!dm'
mx.post_notice   = lambda *a, **kw: '\$evt'
import importlib.util
spec = importlib.util.spec_from_file_location('ta', '$REPO_ROOT/scripts/teacher-agent.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.cmd_morning_nudge()
print(json.dumps(r))
")
  assert_contains "$out" '"ok": true'
  [ -f "$last_dir/teacher-morning_nudge.last" ] || fail_test "morning-nudge did not touch lockfile"
  cleanup_db "$tmp"
  rm -rf "$last_dir"
end_test

start_test "class_digest_touches_last_run_lockfile"
  tmp=$(fresh_db)
  last_dir=$(mktemp -d)
  out=$(GATEWAY_DB="$tmp" TEACHER_LAST_RUN_DIR="$last_dir" python3 -c "
import sys, json
sys.path.insert(0, '$REPO_ROOT/scripts/lib')
import matrix_teacher as mx
mx.post_notice = lambda *a, **kw: '\$evt'
import importlib.util
spec = importlib.util.spec_from_file_location('ta', '$REPO_ROOT/scripts/teacher-agent.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.cmd_class_digest()
print(json.dumps(r))
")
  assert_contains "$out" '"ok": true'
  [ -f "$last_dir/teacher-class_digest.last" ] || fail_test "class-digest did not touch lockfile"
  cleanup_db "$tmp"
  rm -rf "$last_dir"
end_test

# ── Crontab entries are installed (live crontab inspection) ──────────────

start_test "crontab_has_three_teacher_entries"
  # Guard against running under a user with no crontab (e.g. CI).
  if ! crontab -l >/dev/null 2>&1; then
    return 0
  fi
  out=$(crontab -l 2>/dev/null)
  echo "$out" | grep -q "teacher-agent.py --morning-nudge" || fail_test "morning-nudge cron missing"
  echo "$out" | grep -q "teacher-agent.py --class-digest" || fail_test "class-digest cron missing"
  echo "$out" | grep -q "write-learning-metrics.sh" || fail_test "metrics exporter cron missing"
end_test

# ── crontab-reference.md mentions the new entries ─────────────────────────

start_test "crontab_reference_doc_catalogues_new_entries"
  cd "$REPO_ROOT"
  grep -q "teacher-agent.py" docs/crontab-reference.md \
    || fail_test "crontab-reference.md missing teacher-agent.py"
  grep -q "write-learning-metrics.sh" docs/crontab-reference.md \
    || fail_test "crontab-reference.md missing write-learning-metrics.sh"
  grep -q "IFRNLLEI01PRD-654" docs/crontab-reference.md \
    || fail_test "crontab-reference.md missing issue ID"
end_test
