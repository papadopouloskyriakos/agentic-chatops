#!/usr/bin/env bash
# distribute-workers.sh — fan out pending work_units to N parallel Claude workers
# (IFRNLLEI01PRD-925 Phase 3 of parallel-dev architecture)
#
# Reads all pending+parallelizable work_units for a given feature_id whose
# dependencies are satisfied (all dep tasks completed), allocates a worktree
# per task, and SSH-launches `claude -p` in each worktree in parallel.
#
# Each worker writes its JSONL log to /tmp/claude-work-<feature_id>-<task_id>.jsonl
# and its PID file to /tmp/claude-work-<feature_id>-<task_id>.pid.
#
# This script is intended to be called from the n8n "NL - ChatDevOps Distribute"
# workflow via SSH, or manually for testing.
#
# Usage:
#   distribute-workers.sh <feature_id> [--dry-run]
#     --dry-run: allocate worktrees but don't actually launch Claude

set -euo pipefail

DB=/home/app-user/gateway-state/gateway.db
SLOT_CONFIG=/home/app-user/gateway-state/slot-config.json
ALLOCATOR=/home/app-user/gateway-state/bin/allocate-worktree.sh
MAX_WORKERS=4

if [ $# -lt 1 ]; then
  echo "usage: $0 <feature_id> [--dry-run]" >&2
  exit 2
fi

FEATURE_ID="$1"
DRY_RUN=false
[ "${2:-}" = "--dry-run" ] && DRY_RUN=true

# Resolve repo_cwd from features table
REPO_SLUG=$(sqlite3 "$DB" "SELECT repo_slug FROM features WHERE feature_id='$FEATURE_ID'")
if [ -z "$REPO_SLUG" ]; then
  echo "error: no features row for $FEATURE_ID" >&2
  exit 3
fi
REPO_CWD=$(jq -r --arg slug "$REPO_SLUG" '(.[$slug] // .default).cwd' "$SLOT_CONFIG")

# Find the next wave: pending tasks whose dependencies are all completed
# (Tasks with empty dependencies are always wave-0 candidates)
WAVE_TASKS=$(python3 <<PYEOF
import json, sqlite3
conn = sqlite3.connect("$DB")
rows = conn.execute(
    "SELECT task_id, dependencies, parallelizable, max_wall_clock_minutes, max_loc_delta, prompt, files_owned, acceptance_test FROM work_units WHERE feature_id=? AND status='pending'",
    ("$FEATURE_ID",),
).fetchall()
if not rows:
    print("NO_PENDING")
else:
    # Build set of completed task_ids
    completed = {r[0] for r in conn.execute(
        "SELECT task_id FROM work_units WHERE feature_id=? AND status='completed'",
        ("$FEATURE_ID",),
    ).fetchall()}
    wave = []
    for task_id, deps_json, parallelizable, wall_min, loc_delta, prompt, files_owned, acceptance_test in rows:
        deps = set(json.loads(deps_json or "[]"))
        if deps <= completed:
            wave.append({
                "task_id": task_id, "parallelizable": bool(parallelizable),
                "wall_min": wall_min, "loc_delta": loc_delta,
                "prompt": prompt, "files_owned": files_owned, "acceptance_test": acceptance_test,
            })
    # Cap to MAX_WORKERS parallelizable; sequential tasks run in order
    parallel = [t for t in wave if t["parallelizable"]][:$MAX_WORKERS]
    seq      = [t for t in wave if not t["parallelizable"]]
    final = parallel + seq[:max(0, $MAX_WORKERS - len(parallel))]
    print(json.dumps(final))
PYEOF
)

if [ "$WAVE_TASKS" = "NO_PENDING" ]; then
  echo "no pending tasks for $FEATURE_ID — distribute is a no-op"
  exit 0
fi

# Allocate + launch each task in the wave
N_LAUNCHED=0
echo "$WAVE_TASKS" | python3 -c "
import json, sys
tasks = json.load(sys.stdin)
print(f'wave size: {len(tasks)} tasks')
for t in tasks:
    print(f'  {t[\"task_id\"]} (parallelizable={t[\"parallelizable\"]}, max_wall={t[\"wall_min\"]}min)')
"

# For each task, allocate worktree + (optionally) launch claude
for tid in $(echo "$WAVE_TASKS" | python3 -c "import json,sys; [print(t['task_id']) for t in json.load(sys.stdin)]"); do
  echo
  echo "--- $tid ---"
  ALLOC_OUTPUT=$("$ALLOCATOR" "$FEATURE_ID" "$tid" "$REPO_CWD" 2>&1) || { echo "  ALLOC FAILED: $ALLOC_OUTPUT"; continue; }
  echo "$ALLOC_OUTPUT" | head -3 | tail -3
  WORKTREE=$(echo "$ALLOC_OUTPUT" | grep ^WORKTREE= | cut -d= -f2)

  if $DRY_RUN; then
    echo "  [DRY-RUN] would launch claude -p in $WORKTREE"
  else
    # Real launch — extract prompt + per-task limits from work_units
    LOG="/tmp/claude-work-${FEATURE_ID}-${tid}.jsonl"
    PID_FILE="/tmp/claude-work-${FEATURE_ID}-${tid}.pid"
    PROMPT=$(sqlite3 "$DB" "SELECT prompt FROM work_units WHERE feature_id='$FEATURE_ID' AND task_id='$tid'")
    WALL_SEC=$(sqlite3 "$DB" "SELECT max_wall_clock_minutes*60 FROM work_units WHERE feature_id='$FEATURE_ID' AND task_id='$tid'")
    rm -f "$LOG" "${LOG}.offset"
    cd "$WORKTREE"
    unset CLAUDECODE
    nohup systemd-run --user --scope --quiet --slice=app.slice \
      --unit="claude-work-${FEATURE_ID}-${tid}-$$" \
      timeout "$WALL_SEC" \
      /home/app-user/.local/bin/claude -p "$PROMPT" \
        --output-format stream-json --verbose \
        --dangerously-skip-permissions > "$LOG" 2>&1 &
    echo $! > "$PID_FILE"
    echo "  launched PID=$(cat $PID_FILE), LOG=$LOG, TIMEOUT=${WALL_SEC}s"
  fi
  N_LAUNCHED=$((N_LAUNCHED + 1))
done

echo
echo "distribute complete: $N_LAUNCHED task(s) launched for $FEATURE_ID"
sqlite3 "$DB" "UPDATE features SET status='in_progress' WHERE feature_id='$FEATURE_ID' AND status='dispatching'"
