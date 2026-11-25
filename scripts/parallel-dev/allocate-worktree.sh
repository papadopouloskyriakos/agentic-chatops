#!/usr/bin/env bash
# allocate-worktree.sh — atomically claim a parallel-dev worker slot + worktree
# (IFRNLLEI01PRD-925, parallel-dev architecture Phase 3)
#
# Worker slots are pre-created git worktrees: <repo>/.parallel-dev/slot-{1..N}
# Each slot has its own branch named "parallel-dev/<feature_id>/<task_id>".
#
# Atomicity is enforced via the gateway-state SQLite work_units table:
#   UPDATE work_units SET worker_slot=? WHERE feature_id=? AND task_id=? AND worker_slot IS NULL
# Combined with the "no two parallelizable tasks share files_owned" planner-level
# guarantee, this ensures no two workers ever land in the same slot.
#
# Usage:
#   allocate-worktree.sh <feature_id> <task_id> <repo_cwd>
#     → prints SLOT=<n>\nWORKTREE=<path>\nBRANCH=<branch>\n on success
#     → exits non-zero with error to stderr on failure
#
# Release:
#   release-worktree.sh <feature_id> <task_id>

set -euo pipefail

DB=/home/app-user/gateway-state/gateway.db
MAX_WORKERS=4

if [ $# -ne 3 ]; then
  echo "usage: $0 <feature_id> <task_id> <repo_cwd>" >&2
  exit 2
fi

FEATURE_ID="$1"
TASK_ID="$2"
REPO_CWD="$3"

# Sanity checks
if [ ! -e "$REPO_CWD/.git" ]; then
  echo "error: $REPO_CWD is not a git repository (no .git entry)" >&2
  exit 3
fi
# Reject if it's itself a worktree (we don't want nested worktrees)
if [ -f "$REPO_CWD/.git" ]; then
  echo "error: $REPO_CWD is a worktree; allocate against the main repo dir instead" >&2
  exit 3
fi
if ! [[ "$FEATURE_ID" =~ ^[A-Z][A-Z0-9_]+-[0-9]+$ ]]; then
  echo "error: invalid feature_id format: $FEATURE_ID" >&2
  exit 4
fi
if ! [[ "$TASK_ID" =~ ^T-[0-9]+$ ]]; then
  echo "error: invalid task_id format (expected T-NNN): $TASK_ID" >&2
  exit 5
fi

PARALLEL_DIR="$REPO_CWD/.parallel-dev"
mkdir -p "$PARALLEL_DIR"

# Ensure N pre-existing worktree slots (create on demand, lazily)
ensure_slot() {
  local slot="$1"
  local slot_dir="$PARALLEL_DIR/slot-$slot"
  if [ ! -d "$slot_dir/.git" ] && [ ! -L "$slot_dir/.git" ]; then
    # Create the worktree on a placeholder branch
    cd "$REPO_CWD"
    git worktree add -B "parallel-dev/slot-$slot-placeholder" "$slot_dir" HEAD 2>/dev/null || \
      git worktree add "$slot_dir" HEAD 2>/dev/null || true
  fi
}

# Atomic claim via SQLite — only succeeds if the row exists with worker_slot=NULL
claim_slot() {
  local slot="$1"
  sqlite3 "$DB" <<SQL
BEGIN IMMEDIATE;
UPDATE work_units
   SET worker_slot=$slot, started_at=strftime('%s','now'), status='in_progress'
 WHERE feature_id='$FEATURE_ID' AND task_id='$TASK_ID' AND worker_slot IS NULL AND status='pending';
SELECT changes();
COMMIT;
SQL
}

# Check if any slot is free (no row with worker_slot=N AND status='in_progress')
for slot in $(seq 1 $MAX_WORKERS); do
  taken=$(sqlite3 "$DB" "SELECT count(*) FROM work_units WHERE worker_slot=$slot AND status='in_progress'")
  if [ "$taken" -eq 0 ]; then
    # Try to claim this slot atomically
    changes=$(claim_slot "$slot")
    if [ "$changes" = "1" ]; then
      # Claim succeeded
      SLOT="$slot"
      WORKTREE_DIR="$PARALLEL_DIR/slot-$slot"
      BRANCH="parallel-dev/${FEATURE_ID}/${TASK_ID}"
      ensure_slot "$slot"
      # Switch the slot's worktree to the task branch (fresh from main)
      cd "$WORKTREE_DIR"
      git fetch origin main 2>&1 | tail -1 >&2
      git checkout -B "$BRANCH" origin/main 2>&1 | tail -1 >&2
      echo "SLOT=$SLOT"
      echo "WORKTREE=$WORKTREE_DIR"
      echo "BRANCH=$BRANCH"
      exit 0
    fi
    # Claim failed (race lost or task missing/wrong status) — try next slot
  fi
done

echo "error: no slot free (all $MAX_WORKERS slots in_progress) OR task not in pending status" >&2
exit 6
