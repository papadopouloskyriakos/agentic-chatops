#!/usr/bin/env bash
# pipeline-resume.sh — handle a GitLab pipeline_events webhook by resuming the right Claude worker
# (IFRNLLEI01PRD-927 Phase 5 of parallel-dev architecture)
#
# Called by the n8n "NL - ChatDevOps CI Resume" workflow via SSH after parsing
# the GitLab webhook payload. Maps pipeline → work_unit → session_id and SSHes
# `claude -r <session_id>` with the pipeline result as the new turn.
#
# This eliminates the FM-1.5 "unaware of termination conditions" failure mode:
# workers never poll pipelines; they're resumed via this webhook→event flow.
#
# Usage:
#   pipeline-resume.sh <pipeline_id> <branch_name> <status> [pipeline_url]
#     pipeline_id    GitLab pipeline ID
#     branch_name    The branch the pipeline ran on (must be parallel-dev/<feature>/<task>)
#     status         success | failed | canceled
#     pipeline_url   (optional) for the resume prompt context

set -euo pipefail

DB=/home/app-user/gateway-state/gateway.db

if [ $# -lt 3 ]; then
  echo "usage: $0 <pipeline_id> <branch_name> <status> [pipeline_url]" >&2
  exit 2
fi

PIPELINE_ID="$1"
BRANCH="$2"
STATUS="$3"
PIPELINE_URL="${4:-}"

# Branch must match parallel-dev/<feature_id>/<task_id>
if ! [[ "$BRANCH" =~ ^parallel-dev/([A-Z][A-Z0-9_]+-[0-9]+)/(T-[0-9]+)$ ]]; then
  echo "skip: branch $BRANCH doesn't match parallel-dev/<feature>/<task> — not a parallel-dev pipeline"
  exit 0
fi
FEATURE_ID="${BASH_REMATCH[1]}"
TASK_ID="${BASH_REMATCH[2]}"

# Look up session_id for this work_unit
SID=$(sqlite3 "$DB" "SELECT session_id FROM work_units WHERE feature_id='$FEATURE_ID' AND task_id='$TASK_ID'")
if [ -z "$SID" ]; then
  echo "warn: no session_id for $FEATURE_ID/$TASK_ID (worker may have completed already)"
  # Still record pipeline_id for audit
  sqlite3 "$DB" "UPDATE work_units SET pipeline_id=$PIPELINE_ID WHERE feature_id='$FEATURE_ID' AND task_id='$TASK_ID'"
  exit 0
fi

# Record pipeline_id
sqlite3 "$DB" "UPDATE work_units SET pipeline_id=$PIPELINE_ID WHERE feature_id='$FEATURE_ID' AND task_id='$TASK_ID'"

# Compose resume prompt
case "$STATUS" in
  success)  RESUME_MSG="CI pipeline $PIPELINE_ID for branch $BRANCH succeeded${PIPELINE_URL:+ ($PIPELINE_URL)}. You can proceed." ;;
  failed)   RESUME_MSG="CI pipeline $PIPELINE_ID for branch $BRANCH FAILED${PIPELINE_URL:+ ($PIPELINE_URL)}. Investigate logs and decide: fix in-place, or report blocker and exit." ;;
  canceled) RESUME_MSG="CI pipeline $PIPELINE_ID for branch $BRANCH was canceled${PIPELINE_URL:+ ($PIPELINE_URL)}. Decide whether to retry or abort." ;;
  *)        RESUME_MSG="CI pipeline $PIPELINE_ID for branch $BRANCH ended in unexpected status: $STATUS." ;;
esac

# Look up the worktree path so we can cd into it
REPO_SLUG=$(sqlite3 "$DB" "SELECT repo_slug FROM features WHERE feature_id='$FEATURE_ID'")
REPO_CWD=$(jq -r --arg slug "$REPO_SLUG" '(.[$slug] // .default).cwd' /home/app-user/gateway-state/slot-config.json)
SLOT=$(sqlite3 "$DB" "SELECT worker_slot FROM work_units WHERE feature_id='$FEATURE_ID' AND task_id='$TASK_ID'")
[ -n "$SLOT" ] && WORKTREE="$REPO_CWD/.parallel-dev/slot-$SLOT" || WORKTREE="$REPO_CWD"

echo "resume: feature=$FEATURE_ID task=$TASK_ID slot=$SLOT session=$SID pipeline=$PIPELINE_ID status=$STATUS"
echo "  worktree: $WORKTREE"
echo "  resume_msg: $RESUME_MSG"

# Real launch (uncommented 2026-05-17 during operator-activation per IFRNLLEI01PRD-929 close).
# First fire is the verification — watch /tmp/claude-work-*.jsonl for the resume session output.
LOG="/tmp/claude-work-${FEATURE_ID}-${TASK_ID}.jsonl"
cd "$WORKTREE"
unset CLAUDECODE
nohup systemd-run --user --scope --quiet --slice=app.slice \
  --unit="claude-resume-${FEATURE_ID}-${TASK_ID}-$$" \
  timeout 600 \
  /home/app-user/.local/bin/claude -r "$SID" \
    --output-format stream-json --verbose \
    --dangerously-skip-permissions "$RESUME_MSG" >> "$LOG" 2>&1 &
echo "  launched resume PID=$!"
