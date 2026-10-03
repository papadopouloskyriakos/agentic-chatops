#!/usr/bin/env bash
# IFRNLLEI01PRD-651 — teacher-agent foundation QA (schema + SM-2 + curriculum).
# Full suite lands in IFRNLLEI01PRD-655 gate; this is the foundation-tier stub.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
# shellcheck source=../lib/fixtures.sh
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="651-teacher-agent-foundation"

# ── SM-2 math ──────────────────────────────────────────────────────────────

start_test "sm2_interval_progression_shape"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from datetime import datetime
from sm2 import initial_card, schedule
card = initial_card(now=datetime(2026, 1, 1))
intervals = []
for _ in range(5):
    card = schedule(card, quality=5, now=datetime(2026, 1, 1))
    intervals.append(card.interval_days)
# Expected shape: [1, 6, 15, ~38, ~95] with EF_MAX=2.5 clamp
assert intervals[0] == 1, intervals
assert intervals[1] == 6, intervals
assert intervals[2] == 15, intervals
assert 35 <= intervals[3] <= 40, intervals
assert 85 <= intervals[4] <= 100, intervals
assert intervals == sorted(intervals), intervals  # monotonic increasing
print('ok', intervals)
")
  assert_contains "$out" "ok"
end_test

start_test "sm2_quality_zero_resets_repetition"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from sm2 import initial_card, schedule
card = initial_card()
for _ in range(3):
    card = schedule(card, quality=5)
assert card.repetition_count == 3, card
card = schedule(card, quality=0)
assert card.repetition_count == 0, card
assert card.interval_days == 1, card
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "sm2_easiness_clamped_1_3_to_2_5"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from sm2 import _update_easiness, EF_MIN, EF_MAX
assert EF_MIN == 1.3, EF_MIN
assert EF_MAX == 2.5, EF_MAX
ef = 2.5
for _ in range(30): ef = _update_easiness(ef, 5)
assert ef <= 2.5 + 1e-9
ef = 2.5
for _ in range(30): ef = _update_easiness(ef, 0)
assert ef >= 1.3 - 1e-9
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "sm2_quality_from_score_roundtrip"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from sm2 import quality_from_score
assert quality_from_score(0.0) == 0
assert quality_from_score(1.0) == 5
assert quality_from_score(0.9) == 4
# Out-of-range clamp
assert quality_from_score(-1.0) == 0
assert quality_from_score(2.0) == 5
print('ok')
")
  assert_contains "$out" "ok"
end_test

start_test "sm2_due_topics_sort_and_filter"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from datetime import datetime, timedelta
from sm2 import due_topics
now = datetime(2026, 4, 20, 12, 0, 0)
rows = [
    {'topic': 'A', 'next_due': now - timedelta(days=2), 'mastery_score': 0.9},
    {'topic': 'B', 'next_due': now - timedelta(days=1), 'mastery_score': 0.3},
    {'topic': 'C', 'next_due': now + timedelta(days=1), 'mastery_score': 0.5},
    {'topic': 'D', 'next_due': now - timedelta(days=2), 'mastery_score': 0.5},
]
due = due_topics(rows, now)
ids = [r['topic'] for r in due]
assert ids == ['D', 'A', 'B'], ids
assert 'C' not in ids
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Schema registry ────────────────────────────────────────────────────────

start_test "schema_registry_learning_tables_registered"
  cd "$REPO_ROOT/scripts"
  out=$(python3 -c "
import sys; sys.path.insert(0, 'lib')
from schema_version import CURRENT_SCHEMA_VERSION, SCHEMA_VERSION_SUMMARIES
assert 'learning_progress' in CURRENT_SCHEMA_VERSION
assert 'learning_sessions' in CURRENT_SCHEMA_VERSION
assert CURRENT_SCHEMA_VERSION['learning_progress'] == 1
assert CURRENT_SCHEMA_VERSION['learning_sessions'] == 1
# Summaries must exist
assert 1 in SCHEMA_VERSION_SUMMARIES['learning_progress']
assert 1 in SCHEMA_VERSION_SUMMARIES['learning_sessions']
print('ok')
")
  assert_contains "$out" "ok"
end_test

# ── Migration 013 ──────────────────────────────────────────────────────────

start_test "migration_013_creates_both_tables_from_schema_sql"
  tmp=$(fresh_db)
  # fresh_db applies schema.sql + all migrations including 013.
  for t in learning_progress learning_sessions; do
    n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$t'")
    [ "$n" = "1" ] || fail_test "table $t missing"
  done
  # All columns of learning_progress present
  for col in operator topic mastery_score easiness_factor interval_days repetition_count highest_bloom_reached next_due schema_version; do
    n=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM pragma_table_info('learning_progress') WHERE name='$col'")
    [ "$n" = "1" ] || fail_test "column learning_progress.$col missing"
  done
  cleanup_db "$tmp"
end_test

start_test "migration_013_idempotent"
  tmp=$(fresh_db)
  before=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'learning_%'")
  GATEWAY_DB="$tmp" python3 "$REPO_ROOT/scripts/migrations/apply.py" >/dev/null 2>&1
  after=$(sqlite3 "$tmp" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'learning_%'")
  assert_eq "$before" "$after"
  cleanup_db "$tmp"
end_test

start_test "learning_progress_unique_operator_topic"
  tmp=$(fresh_db)
  sqlite3 "$tmp" "INSERT INTO learning_progress (operator, topic) VALUES ('default', 'invariant-1-hitl-gate-on-mutating-actions')"
  # Duplicate should fail
  out=$(sqlite3 "$tmp" "INSERT INTO learning_progress (operator, topic) VALUES ('default', 'invariant-1-hitl-gate-on-mutating-actions')" 2>&1 || true)
  assert_contains "$out" "UNIQUE"
  cleanup_db "$tmp"
end_test

# ── Curriculum builder ─────────────────────────────────────────────────────

start_test "curriculum_rebuild_produces_at_least_30_topics"
  cd "$REPO_ROOT"
  python3 scripts/rebuild-curriculum.py --dry-run > /tmp/curr-dry.log 2>&1
  topic_count=$(grep -oP 'after=\K\d+' /tmp/curr-dry.log | head -1 || echo 0)
  [ "$topic_count" -ge 30 ] || fail_test "expected >=30 topics; got $topic_count"
end_test

start_test "curriculum_has_four_curricula"
  cd "$REPO_ROOT"
  python3 -c "
import json
d = json.load(open('config/curriculum.json'))
assert len(d['curricula']) == 4, len(d['curricula'])
ids = {c['id'] for c in d['curricula']}
assert ids == {'foundations', 'patterns', 'platform', 'memory'}, ids
print('ok')
" | grep -q ok || fail_test "curricula set mismatch"
end_test

start_test "curriculum_foundations_has_six_invariants"
  cd "$REPO_ROOT"
  python3 -c "
import json
d = json.load(open('config/curriculum.json'))
found = next(c for c in d['curricula'] if c['id'] == 'foundations')
inv_count = sum(1 for t in found['topics'] if t.startswith('invariant-'))
assert inv_count == 6, f'expected 6 invariants, got {inv_count}'
print('ok')
" | grep -q ok || fail_test "invariant count mismatch"
end_test

start_test "curriculum_rebuild_is_stable_on_unchanged_sources"
  cd "$REPO_ROOT"
  python3 scripts/rebuild-curriculum.py --dry-run > /tmp/curr-r1.log 2>&1
  python3 scripts/rebuild-curriculum.py --dry-run > /tmp/curr-r2.log 2>&1
  c1=$(grep -oP 'after=\K\d+' /tmp/curr-r1.log | head -1)
  c2=$(grep -oP 'after=\K\d+' /tmp/curr-r2.log | head -1)
  assert_eq "$c1" "$c2"
end_test

end_test
