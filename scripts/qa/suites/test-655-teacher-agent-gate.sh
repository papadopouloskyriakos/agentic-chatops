#!/usr/bin/env bash
# IFRNLLEI01PRD-655 — teacher-agent gate tier.
# Exercises: invariant audit, calibration harness (offline), runbook + plan
# doc presence, five-tier auto-discovery by run-qa-suite.sh.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="655-teacher-agent-gate"

# ── Invariant audit runs green on the live repo ─────────────────────────────

start_test "invariant_audit_passes_on_live_repo"
  cd "$REPO_ROOT"
  if ! bash scripts/audit-teacher-invariants.sh >/tmp/inv.log 2>&1; then
    echo "--- invariant audit output ---" >&2
    cat /tmp/inv.log >&2
    fail_test "audit-teacher-invariants.sh exited non-zero"
  fi
  grep -q "RESULT: all invariants PASS" /tmp/inv.log \
    || fail_test "invariant audit did not report all-pass"
  rm -f /tmp/inv.log
end_test

# ── Invariant audit detects a seeded Edit violation in the agent definition ─

start_test "invariant_audit_detects_mutating_tool_in_allowlist"
  cd "$REPO_ROOT"
  # Copy the agent def to a tempdir so we can mutate it without touching the repo.
  sandbox=$(mktemp -d)
  cp -r .claude "$sandbox/.claude"
  cp -r scripts "$sandbox/scripts"
  cp -r docs "$sandbox/docs"
  cp -r config "$sandbox/config" 2>/dev/null || true
  # Seed a failure: add Edit to the tools line.
  sed -i 's/^tools: .*/& Edit/' "$sandbox/.claude/agents/teacher-agent.md"
  # Re-point the audit at the sandbox via its REPO_ROOT computation.
  out=$(cd "$sandbox" && bash scripts/audit-teacher-invariants.sh 2>&1 || true)
  echo "$out" | grep -q "FAIL — mutating tool present in allowlist: Edit" \
    || fail_test "audit did not detect seeded Edit violation — output: $(echo "$out" | tail -5)"
  rm -rf "$sandbox"
end_test

# ── Calibration harness runs offline with 100% agreement on synthetic stub ──

start_test "calibration_offline_hits_85pct_agreement"
  cd "$REPO_ROOT"
  report_dir=$(mktemp -d)
  stamp=$(date +%Y%m%d-%H%M%S)
  report="$report_dir/calibration-$stamp.json"
  python3 scripts/teacher-calibration-baseline.py --offline --report "$report" >/dev/null 2>&1
  rc=$?
  [ "$rc" = "0" ] || fail_test "calibration harness exit=$rc (expected 0)"
  agreement=$(python3 -c "import json; print(json.load(open('$report'))['agreement'])")
  python3 -c "
import json, sys
r = json.load(open('$report'))
assert r['mode'] == 'offline', r
assert r['n_fixtures'] >= 12, r
assert r['agreement'] >= 0.85, r
for row in r['results']:
    assert 'score' in row and 'band' in row, row
print('ok')
" | grep -q ok || fail_test "calibration report JSON shape invalid (agreement=$agreement)"
  rm -rf "$report_dir"
end_test

# ── Real-data calibration: export mode handles empty DB ────────────────────

start_test "calibration_export_handles_no_graded_sessions"
  cd "$REPO_ROOT"
  tmp_db=$(mktemp --suffix=.db)
  sqlite3 "$tmp_db" < schema.sql
  GATEWAY_DB="$tmp_db" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1 || true
  out_json=$(mktemp --suffix=.json)
  rc=0
  python3 scripts/teacher-calibration-baseline.py --db "$tmp_db" \
    --export-for-review "$out_json" >/dev/null 2>&1 || rc=$?
  # Expect exit 1 + empty file when no graded sessions exist
  [ "$rc" = "1" ] || fail_test "expected exit 1 on empty DB, got $rc"
  rm -f "$tmp_db" "$out_json"
end_test

# ── Real-data calibration: export mode dumps real quiz rows ────────────────

start_test "calibration_export_writes_recent_quiz_rows"
  cd "$REPO_ROOT"
  tmp_db=$(mktemp --suffix=.db)
  sqlite3 "$tmp_db" < schema.sql
  GATEWAY_DB="$tmp_db" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1 || true
  # Seed 2 completed quizzes
  sqlite3 "$tmp_db" "
    INSERT INTO learning_sessions (operator, topic, session_type, bloom_level,
      started_at, completed_at, quiz_score, question_payload, answer_payload, schema_version)
    VALUES ('@a:m', 'gulli-05-tool-use', 'quiz', 'explanation',
      datetime('now','-2 hours'), datetime('now','-1 hour'), 0.92,
      '{\"question_text\":\"Name the MCPs\"}', '{\"answer_text\":\"netbox n8n-mcp\"}', 1);
    INSERT INTO learning_sessions (operator, topic, session_type, bloom_level,
      started_at, completed_at, quiz_score, question_payload, answer_payload, schema_version)
    VALUES ('@a:m', 'gulli-07-multi-agent', 'quiz', 'analysis',
      datetime('now','-3 hours'), datetime('now','-2 hours'), 0.45,
      '{\"question_text\":\"Explain the tiers\"}', '{\"answer_text\":\"three tiers\"}', 1);
  "
  out_json=$(mktemp --suffix=.json)
  python3 scripts/teacher-calibration-baseline.py --db "$tmp_db" \
    --export-for-review "$out_json" >/dev/null 2>&1
  out=$(python3 -c "
import json
d = json.load(open('$out_json'))
assert d['n_records'] == 2, d
for r in d['records']:
    for k in ('session_id', 'topic', 'grader_score', 'grader_band',
              'question_text', 'answer_text', 'operator_band'):
        assert k in r, (k, r)
    assert r['operator_band'] is None, r
bands = {r['grader_band'] for r in d['records']}
assert 'excellent' in bands and 'partial' in bands, bands
print('ok')
")
  assert_contains "$out" "ok"
  rm -f "$tmp_db" "$out_json"
end_test

# ── Real-data calibration: from-reviewed mode ─────────────────────────────

start_test "calibration_from_reviewed_computes_agreement"
  cd "$REPO_ROOT"
  tmp=$(mktemp --suffix=.json)
  python3 -c "
import json
json.dump({
    'records': [
        {'session_id': 1, 'topic': 't1', 'bloom_level': 'recall',
         'grader_score': 0.9, 'grader_band': 'excellent',
         'operator_band': 'excellent'},
        {'session_id': 2, 'topic': 't2', 'bloom_level': 'recall',
         'grader_score': 0.7, 'grader_band': 'good',
         'operator_band': 'good'},
        {'session_id': 3, 'topic': 't3', 'bloom_level': 'recall',
         'grader_score': 0.9, 'grader_band': 'excellent',
         'operator_band': 'good'},
    ]
}, open('$tmp','w'))
"
  rc=0
  out=$(python3 scripts/teacher-calibration-baseline.py --from-reviewed "$tmp" 2>&1) || rc=$?
  # 2/3 PASS → 66.67% → below 0.85 threshold → exit 1
  [ "$rc" = "1" ] || fail_test "expected exit 1 (below threshold), got $rc"
  echo "$out" | grep -q "agreement=66.67%" || fail_test "expected 66.67% agreement in output"
  # And above-threshold case
  python3 -c "
import json
json.dump({
    'records': [
        {'session_id': n, 'topic': 't','bloom_level':'r','grader_score':0.9,
         'grader_band':'excellent','operator_band':'excellent'}
        for n in range(10)
    ]
}, open('$tmp','w'))
"
  rc=0
  out=$(python3 scripts/teacher-calibration-baseline.py --from-reviewed "$tmp" 2>&1) || rc=$?
  [ "$rc" = "0" ] || fail_test "expected exit 0 (at/above threshold), got $rc"
  echo "$out" | grep -q "agreement=100.00%" || fail_test "expected 100% agreement in output"
  rm -f "$tmp"
end_test

# ── Fixture file exists and has >=12 entries across all 5 bands ─────────────

start_test "calibration_fixtures_cover_all_five_bands"
  cd "$REPO_ROOT"
  out=$(python3 -c "
import json
f = json.load(open('scripts/qa/fixtures/teacher-calibration-fixtures.json'))
assert len(f) >= 12, f'expected >=12 fixtures, got {len(f)}'
bands = {x['expected_band'] for x in f}
for b in ('excellent', 'good', 'partial', 'wrong', 'irrelevant'):
    assert b in bands, f'band {b!r} missing'
# Each fixture must have the fields the harness needs
for x in f:
    for k in ('id', 'question', 'answer', 'source_snippets', 'bloom_level', 'expected_band', 'stub_score'):
        assert k in x, f'fixture {x.get(\"id\")} missing field {k!r}'
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Runbook exists and links the invariant audit + calibration scripts ─────

start_test "runbook_exists_and_references_audit_and_calibration"
  cd "$REPO_ROOT"
  [ -f docs/runbooks/teacher-agent.md ] || fail_test "docs/runbooks/teacher-agent.md missing"
  grep -q "audit-teacher-invariants.sh" docs/runbooks/teacher-agent.md \
    || fail_test "runbook does not reference audit-teacher-invariants.sh"
  grep -q "teacher-calibration-baseline.py" docs/runbooks/teacher-agent.md \
    || fail_test "runbook does not reference teacher-calibration-baseline.py"
  grep -q "Rollback ladder" docs/runbooks/teacher-agent.md \
    || fail_test "runbook missing Rollback ladder section"
  grep -q "Alert response" docs/runbooks/teacher-agent.md \
    || fail_test "runbook missing Alert response section"
end_test

# ── All five tier suites are auto-discoverable by run-qa-suite.sh ───────────

start_test "all_five_tier_suites_discoverable"
  cd "$REPO_ROOT"
  for t in 651-teacher-agent-foundation 652-teacher-agent-intelligence \
           653-teacher-agent-interface 654-teacher-agent-loop 655-teacher-agent-gate; do
    [ -f "scripts/qa/suites/test-${t}.sh" ] \
      || fail_test "test-${t}.sh missing (run-qa-suite globs scripts/qa/suites/*.sh)"
  done
  # The master harness globs *.sh; assert the glob picks them up.
  out=$(bash -c "ls $REPO_ROOT/scripts/qa/suites/test-65*-teacher-agent-*.sh | wc -l")
  [ "$out" = "5" ] || fail_test "glob returned $out suites, expected 5"
end_test

# ── CLAUDE.md references all five tier YT issues ────────────────────────────

start_test "claude_md_references_all_five_tier_issue_ids"
  cd "$REPO_ROOT"
  for id in IFRNLLEI01PRD-651 IFRNLLEI01PRD-652 IFRNLLEI01PRD-653 \
            IFRNLLEI01PRD-654 IFRNLLEI01PRD-655; do
    grep -q "$id" CLAUDE.md || fail_test "CLAUDE.md does not reference $id"
  done
end_test

# ── Plan doc has a status block reflecting completion ──────────────────────

start_test "plan_doc_exists"
  cd "$REPO_ROOT"
  [ -f docs/plans/teacher-agent-implementation-plan.md ] \
    || fail_test "plan doc missing"
  grep -q "IFRNLLEI01PRD-655" docs/plans/teacher-agent-implementation-plan.md \
    || fail_test "plan doc does not reference IFRNLLEI01PRD-655"
end_test

# ── Free-chat mode (teacher_chat.py + cmd_chat) ──────────────────────────

start_test "chat_grounded_answer_cites_sources"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys, json
sys.path.insert(0, 'lib')
import matrix_teacher as mx
mx.is_authorised = lambda *a, **kw: True
mx.resolve_dm    = lambda op, **kw: '!dm'
mx.post_message  = lambda room, body, **kw: 'EVT'
mx.post_notice   = lambda room, body, **kw: 'EVT'
import teacher_chat
teacher_chat.chat = lambda q, snippets, **kw: teacher_chat.ChatAnswer(
    answer='Tool Use uses 9 MCP servers.',
    cited_snippets=[{'source_path': snippets[0].source_path, 'section': 'x'}],
    refused=False,
)
import importlib.util
spec = importlib.util.spec_from_file_location('teacher_agent', 'teacher-agent.py')
m = importlib.util.module_from_spec(spec); sys.modules['teacher_agent'] = m; spec.loader.exec_module(m)
r = m.cmd_chat('@alice:m', 'How many MCP servers?')
print(json.dumps(r))
" 2>&1)
  assert_contains "$out" '"ok": true'
  assert_contains "$out" '"cited_count": 1'
  cleanup_db "$tmp"
end_test

start_test "chat_refuses_off_curriculum_without_sources"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys, json
sys.path.insert(0, 'lib')
import matrix_teacher as mx
mx.is_authorised = lambda *a, **kw: True
mx.resolve_dm    = lambda op, **kw: '!dm'
mx.post_message  = lambda room, body, **kw: 'EVT'
mx.post_notice   = lambda room, body, **kw: 'EVT'
import teacher_chat
teacher_chat.chat = lambda q, snippets, **kw: teacher_chat.ChatAnswer(
    answer='', cited_snippets=[], refused=True,
    refusal_reason='Off-curriculum: question is about kubernetes internals.',
)
import importlib.util
spec = importlib.util.spec_from_file_location('teacher_agent', 'teacher-agent.py')
m = importlib.util.module_from_spec(spec); sys.modules['teacher_agent'] = m; spec.loader.exec_module(m)
r = m.cmd_chat('@alice:m', 'Why does etcd raft leader election...')
print(json.dumps(r))
" 2>&1)
  assert_contains "$out" '"ok": true'
  assert_contains "$out" '"refused": true'
  cleanup_db "$tmp"
end_test

start_test "chat_rate_limit_blocks_runaway"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # Verify schema then seed 31 chat sessions in the last hour —
  # one over TEACHER_CHAT_RATE_LIMIT default (30).
  sqlite3 "$tmp" "SELECT 1 FROM learning_sessions LIMIT 1" >/dev/null 2>&1 \
    || fail_test "learning_sessions not in fresh_db ($tmp)"
  for i in $(seq 1 31); do
    sqlite3 "$tmp" "INSERT INTO learning_sessions (operator, topic, session_type, started_at, schema_version) \
      VALUES ('@alice:m', 'gulli-01-prompt-chaining', 'chat', datetime('now','-10 minutes'), 1);"
  done
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys, json
sys.path.insert(0, 'lib')
import matrix_teacher as mx
mx.is_authorised = lambda *a, **kw: True
mx.resolve_dm    = lambda op, **kw: '!dm'
mx.post_message  = lambda *a, **kw: 'EVT'
mx.post_notice   = lambda *a, **kw: 'EVT'
import importlib.util
spec = importlib.util.spec_from_file_location('teacher_agent', 'teacher-agent.py')
m = importlib.util.module_from_spec(spec); sys.modules['teacher_agent'] = m; spec.loader.exec_module(m)
r = m.cmd_chat('@alice:m', 'a follow-up question')
print(json.dumps(r))
" 2>&1)
  assert_contains "$out" 'rate limited'
  cleanup_db "$tmp"
end_test

start_test "chat_semantic_falls_through_on_embed_failure"
  tmp=$(fresh_db)
  cd "$REPO_ROOT/scripts"
  # With the fresh DB's wiki_articles empty, _semantic_snippets has nothing
  # to score and returns []. _chat_snippets should then fall through to the
  # keyword/recent path and still return a non-empty list.
  out=$(GATEWAY_DB="$tmp" python3 -c "
import sys, importlib.util
sys.path.insert(0, 'lib')
spec = importlib.util.spec_from_file_location('ta', 'teacher-agent.py')
m = importlib.util.module_from_spec(spec); sys.modules['ta'] = m; spec.loader.exec_module(m)
snips = m._chat_snippets('@alice:m', 'how does prompt chaining decompose tasks?', limit=3)
assert snips, 'fallback should have returned snippets'
# The keyword branch should pick the gulli-01 pattern page
paths = [s.source_path for s in snips]
assert any('gulli-01-prompt-chaining' in p for p in paths), paths
print('ok')
")
  assert_contains "$out" "ok"
  cleanup_db "$tmp"
end_test

start_test "chat_snippet_selection_prefers_keyword_matches"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys, importlib.util
sys.path.insert(0, 'lib')
spec = importlib.util.spec_from_file_location('teacher_agent', 'teacher-agent.py')
m = importlib.util.module_from_spec(spec); sys.modules['teacher_agent'] = m; spec.loader.exec_module(m)
# 'prompt chaining' in the question should rank gulli-01 first even with
# no operator history (empty learning_sessions).
snips = m._chat_snippets('@alice:m', 'how does prompt chaining decompose tasks?', limit=3)
assert snips, 'no snippets returned'
paths = [s.source_path for s in snips]
# gulli-01-prompt-chaining should surface (directly in wiki/patterns/)
assert any('gulli-01-prompt-chaining' in p for p in paths), paths
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── CrontabReference doc includes teacher + write-learning-metrics entries ──

start_test "crontab_reference_includes_teacher_entries"
  cd "$REPO_ROOT"
  grep -q "teacher-agent.py" docs/crontab-reference.md \
    || fail_test "crontab-reference.md missing teacher-agent.py"
  grep -q "write-learning-metrics.sh" docs/crontab-reference.md \
    || fail_test "crontab-reference.md missing write-learning-metrics.sh"
end_test
