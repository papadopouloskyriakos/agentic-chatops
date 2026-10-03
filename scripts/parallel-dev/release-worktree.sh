#!/usr/bin/env bash
# release-worktree.sh — release a worker slot after task completion or failure
# (IFRNLLEI01PRD-925, parallel-dev architecture Phase 3)
#
# Marks the work_units row as completed (or failed), captures diff if requested,
# and cleans up the worktree so the slot can be reused.
#
# Usage:
#   release-worktree.sh <feature_id> <task_id> <status> [diff_file]
#     status ∈ {completed, failed, timeout, skipped}
#     If diff_file is provided, its contents are written to work_units.diff_blob.

set -euo pipefail

DB=/home/app-user/gateway-state/gateway.db

if [ $# -lt 3 ]; then
  echo "usage: $0 <feature_id> <task_id> <status> [diff_file]" >&2
  exit 2
fi

FEATURE_ID="$1"
TASK_ID="$2"
STATUS="$3"
DIFF_FILE="${4:-}"

case "$STATUS" in
  completed|failed|timeout|skipped) ;;
  *) echo "error: status must be one of: completed, failed, timeout, skipped" >&2; exit 3 ;;
esac

# Look up the worker slot before releasing
SLOT=$(sqlite3 "$DB" "SELECT worker_slot FROM work_units WHERE feature_id='$FEATURE_ID' AND task_id='$TASK_ID'")
if [ -z "$SLOT" ] || [ "$SLOT" = "" ]; then
  echo "error: no work_units row for $FEATURE_ID/$TASK_ID, or worker_slot is NULL" >&2
  exit 4
fi

# Status + diff capture via Python for SQLite BLOB binding (avoids xxd dependency + injection risk)
if [ -n "$DIFF_FILE" ] && [ -f "$DIFF_FILE" ]; then
  python3 - "$DB" "$FEATURE_ID" "$TASK_ID" "$STATUS" "$DIFF_FILE" <<'PYEOF'
import sqlite3, sys
db, fid, tid, status, diff_path = sys.argv[1:]
blob = open(diff_path, "rb").read()
conn = sqlite3.connect(db, timeout=30)
conn.execute("PRAGMA busy_timeout=30000")
conn.execute(
    "UPDATE work_units SET status=?, completed_at=strftime('%s','now'), diff_blob=? "
    "WHERE feature_id=? AND task_id=?",
    (status, blob, fid, tid),
)
conn.commit()
conn.close()
PYEOF
else
  sqlite3 "$DB" "UPDATE work_units SET status='$STATUS', completed_at=strftime('%s','now') WHERE feature_id='$FEATURE_ID' AND task_id='$TASK_ID'"
fi

# Look up the worktree path from the slot config + the repo from features
REPO_SLUG=$(sqlite3 "$DB" "SELECT repo_slug FROM features WHERE feature_id='$FEATURE_ID'")
REPO_CWD=$(jq -r --arg slug "$REPO_SLUG" '(.[$slug] // .default).cwd' /home/app-user/gateway-state/slot-config.json)
WORKTREE="$REPO_CWD/.parallel-dev/slot-$SLOT"

# Don't actually remove the worktree directory — it gets reused for the next task
# Just reset its branch state to placeholder so it's clean
if [ -d "$WORKTREE/.git" ]; then
  cd "$WORKTREE"
  # Detach so the parallel-dev branch can be deleted by merge-coordinator later
  git checkout --detach 2>/dev/null || true
fi

echo "released: feature=$FEATURE_ID task=$TASK_ID slot=$SLOT status=$STATUS"
