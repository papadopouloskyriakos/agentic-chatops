#!/usr/bin/env bash
# write-learning-metrics.sh — Prometheus exporter for teacher-agent state
# (IFRNLLEI01PRD-654). Cron: */5 * * * *.
#
# Metrics (per docs/plans/teacher-agent-implementation-plan.md §12):
#   learning_topics_total{operator}                    gauge
#   learning_topics_mastered{operator}                 gauge    (mastery_score >= 0.9)
#   learning_topics_due{operator}                      gauge    (next_due <= now AND paused=0)
#   learning_quiz_accuracy_7d{operator}                gauge    (avg quiz_score over last 7d)
#   learning_weekly_sessions_total{operator}           gauge    (count of sessions in last 7d)
#   learning_longest_streak_days{operator}             gauge    (max consecutive-day session streak)
#   learning_bloom_distribution{operator,bloom_level}  gauge    (topics currently at each band)
#
# Operator aggregate (label operator="__all__") for dashboard sums.
set -uo pipefail
DB="${GATEWAY_DB:-$HOME/gitlab/products/cubeos/claude-context/gateway.db}"
OUT_DIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
OUT_FILE="${OUT_DIR}/learning_progress.prom"
TMP_FILE="${OUT_FILE}.tmp"

[ -f "$DB" ] || exit 1
mkdir -p "$OUT_DIR" 2>/dev/null || true

# Table gate — silently emit the "not migrated yet" sentinel so absent() alerts
# don't fire before migration 013 is applied.
if ! sqlite3 "$DB" "SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_progress'" | grep -q 1; then
  { echo "# learning_progress table not yet migrated"; } > "$TMP_FILE"
  mv "$TMP_FILE" "$OUT_FILE"
  exit 0
fi

# Escape an mxid for Prometheus label syntax. We only need to quote `"` and `\`.
_esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

{
  echo "# HELP learning_topics_total Total rows in learning_progress for the operator."
  echo "# TYPE learning_topics_total gauge"
  sqlite3 "$DB" "SELECT operator, COUNT(*) FROM learning_progress GROUP BY operator" |
    while IFS='|' read -r op n; do
      [ -n "$op" ] && echo "learning_topics_total{operator=\"$(_esc "$op")\"} ${n}"
    done

  echo "# HELP learning_topics_mastered Topics with mastery_score >= 0.9."
  echo "# TYPE learning_topics_mastered gauge"
  sqlite3 "$DB" "SELECT operator, COUNT(*) FROM learning_progress WHERE mastery_score >= 0.9 GROUP BY operator" |
    while IFS='|' read -r op n; do
      [ -n "$op" ] && echo "learning_topics_mastered{operator=\"$(_esc "$op")\"} ${n}"
    done

  echo "# HELP learning_topics_due Topics with next_due <= now and not paused."
  echo "# TYPE learning_topics_due gauge"
  sqlite3 "$DB" "SELECT operator, COUNT(*) FROM learning_progress WHERE paused=0 AND next_due <= datetime('now') GROUP BY operator" |
    while IFS='|' read -r op n; do
      [ -n "$op" ] && echo "learning_topics_due{operator=\"$(_esc "$op")\"} ${n}"
    done

  echo "# HELP learning_quiz_accuracy_7d Avg quiz_score over completed quizzes in last 7d (NaN-safe: emits 0 when no quizzes)."
  echo "# TYPE learning_quiz_accuracy_7d gauge"
  sqlite3 "$DB" "
    SELECT operator,
           ROUND(COALESCE(AVG(quiz_score), 0.0), 4)
      FROM learning_sessions
     WHERE session_type='quiz'
       AND quiz_score IS NOT NULL
       AND completed_at >= datetime('now', '-7 days')
     GROUP BY operator" |
    while IFS='|' read -r op v; do
      [ -n "$op" ] && echo "learning_quiz_accuracy_7d{operator=\"$(_esc "$op")\"} ${v}"
    done

  echo "# HELP learning_weekly_sessions_total Completed sessions in last 7 days (gauge: resets naturally as the window rolls)."
  echo "# TYPE learning_weekly_sessions_total gauge"
  sqlite3 "$DB" "
    SELECT operator, COUNT(*)
      FROM learning_sessions
     WHERE completed_at >= datetime('now', '-7 days')
     GROUP BY operator" |
    while IFS='|' read -r op n; do
      [ -n "$op" ] && echo "learning_weekly_sessions_total{operator=\"$(_esc "$op")\"} ${n}"
    done

  echo "# HELP learning_longest_streak_days Current consecutive-day streak of having completed >=1 session."
  echo "# TYPE learning_longest_streak_days gauge"
  # Per-operator streak: walk distinct session dates backwards from today.
  # SQLite lacks window LAG with interval comparison ergonomics, so pull
  # distinct dates and compute the streak in Python (small N).
  python3 - <<PY
import os, sqlite3, datetime
db = os.environ.get('GATEWAY_DB', os.path.expanduser('~/gitlab/products/cubeos/claude-context/gateway.db'))
conn = sqlite3.connect(db)
rows = conn.execute(
    "SELECT operator, date(completed_at) FROM learning_sessions "
    "WHERE completed_at IS NOT NULL"
).fetchall()
conn.close()
from collections import defaultdict
days = defaultdict(set)
for op, d in rows:
    if not d:
        continue
    days[op].add(datetime.date.fromisoformat(d))
today = datetime.date.today()
for op, ds in days.items():
    streak = 0
    cur = today
    # Allow today OR yesterday as "still alive" anchor — otherwise missing today drops streak to 0.
    if cur not in ds and (cur - datetime.timedelta(days=1)) in ds:
        cur = cur - datetime.timedelta(days=1)
    while cur in ds:
        streak += 1
        cur = cur - datetime.timedelta(days=1)
    op_esc = op.replace('\\\\', '\\\\\\\\').replace('"', '\\\\"')
    print(f'learning_longest_streak_days{{operator="{op_esc}"}} {streak}')
PY

  echo "# HELP learning_bloom_distribution Topics currently at each Bloom band (highest_bloom_reached)."
  echo "# TYPE learning_bloom_distribution gauge"
  sqlite3 "$DB" "
    SELECT operator, highest_bloom_reached, COUNT(*)
      FROM learning_progress
     GROUP BY operator, highest_bloom_reached" |
    while IFS='|' read -r op bl n; do
      [ -n "$op" ] && [ -n "$bl" ] && \
        echo "learning_bloom_distribution{operator=\"$(_esc "$op")\",bloom_level=\"$(_esc "$bl")\"} ${n}"
    done

  echo "# HELP learning_chat_sessions_total Chat sessions (cmd_chat) completed in last 7 days."
  echo "# TYPE learning_chat_sessions_total gauge"
  sqlite3 "$DB" "
    SELECT operator, COUNT(*)
      FROM learning_sessions
     WHERE session_type='chat'
       AND started_at >= datetime('now', '-7 days')
     GROUP BY operator" |
    while IFS='|' read -r op n; do
      [ -n "$op" ] && echo "learning_chat_sessions_total{operator=\"$(_esc "$op")\"} ${n}"
    done

  echo "# HELP learning_chat_refused_total Chat sessions that refused (off-curriculum) in last 7 days."
  echo "# TYPE learning_chat_refused_total gauge"
  sqlite3 "$DB" "
    SELECT operator, COUNT(*)
      FROM learning_sessions
     WHERE session_type='chat'
       AND started_at >= datetime('now', '-7 days')
       AND answer_payload LIKE '%\"refused\": true%'
     GROUP BY operator" |
    while IFS='|' read -r op n; do
      [ -n "$op" ] && echo "learning_chat_refused_total{operator=\"$(_esc "$op")\"} ${n}"
    done

  # Fleet aggregate — sum across operators so dashboard Stat panels can render
  # a single value without needing PromQL sum() at query time.
  TOTAL_OPS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM teacher_operator_dm")
  echo "# HELP learning_operators_total Total registered operators (teacher_operator_dm row count)."
  echo "# TYPE learning_operators_total gauge"
  echo "learning_operators_total ${TOTAL_OPS}"

  # Last morning-nudge / class-digest / DM-fetch timestamps, read from lockfiles
  # that the crons and bridge touch. absent()/stale alerts key off these.
  for kind in morning_nudge class_digest dm_fetch; do
    f="/var/lib/claude-gateway/teacher-${kind}.last"
    ts=0
    [ -f "$f" ] && ts=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    echo "# HELP learning_${kind}_last_run_timestamp Unix timestamp of the most recent successful ${kind} run."
    echo "# TYPE learning_${kind}_last_run_timestamp gauge"
    echo "learning_${kind}_last_run_timestamp ${ts}"
  done
} > "$TMP_FILE" 2>/dev/null

mv "$TMP_FILE" "$OUT_FILE"
