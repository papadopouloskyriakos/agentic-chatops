#!/usr/bin/env bash
# merge-coordinator.sh — assemble completed work_units into ONE MR per feature
# (IFRNLLEI01PRD-926 Phase 4 of parallel-dev architecture)
#
# Deterministic-only first pass (per plan AC). LLM-assist reconcile is
# scaffolded with TODO markers but not invoked; it can be added later when
# we measure non-zero conflict rates from real traffic.
#
# Flow:
#   1. Read all work_units for feature WHERE status='completed' in dep order
#   2. Create merge branch `merge/<feature_id>` from origin/main in repo's
#      main checkout (NOT a worktree — needs to push to origin from main)
#   3. Apply each task's diff_blob via `git apply` in dependency order
#   4. Run PROJECT.json's lint_command + test_command
#   5. On green: commit, push branch, open MR via GitLab API
#   6. On red/conflict: STOP, mark feature 'failed', emit reason
#
# Usage:
#   merge-coordinator.sh <feature_id> [--dry-run]
#     --dry-run: do everything except `git push` and `MR creation`

set -euo pipefail

DB=/home/app-user/gateway-state/gateway.db
SLOT_CONFIG=/home/app-user/gateway-state/slot-config.json

if [ $# -lt 1 ]; then
  echo "usage: $0 <feature_id> [--dry-run]" >&2
  exit 2
fi

FEATURE_ID="$1"
DRY_RUN=false
[ "${2:-}" = "--dry-run" ] && DRY_RUN=true

# Verify feature exists + all work_units in terminal states
STATE=$(sqlite3 "$DB" "SELECT status FROM features WHERE feature_id='$FEATURE_ID'")
[ -z "$STATE" ] && { echo "error: no feature $FEATURE_ID" >&2; exit 3; }

PENDING=$(sqlite3 "$DB" "SELECT count(*) FROM work_units WHERE feature_id='$FEATURE_ID' AND status NOT IN ('completed','failed','timeout','skipped')")
if [ "$PENDING" -gt 0 ]; then
  echo "error: $PENDING work_unit(s) still in non-terminal state — wait or abort first" >&2
  exit 4
fi

FAILED=$(sqlite3 "$DB" "SELECT count(*) FROM work_units WHERE feature_id='$FEATURE_ID' AND status IN ('failed','timeout')")
COMPLETED=$(sqlite3 "$DB" "SELECT count(*) FROM work_units WHERE feature_id='$FEATURE_ID' AND status='completed'")
TOTAL=$((FAILED + COMPLETED))
if [ "$FAILED" -gt 0 ]; then
  echo "warning: $FAILED/$TOTAL work_units failed/timeout — proceeding with completed-only, but flag this MR as needs-human"
fi
if [ "$COMPLETED" -eq 0 ]; then
  echo "error: no completed work_units — nothing to merge" >&2
  sqlite3 "$DB" "UPDATE features SET status='failed' WHERE feature_id='$FEATURE_ID'"
  exit 5
fi

# Resolve repo_cwd + PROJECT.json
REPO_SLUG=$(sqlite3 "$DB" "SELECT repo_slug FROM features WHERE feature_id='$FEATURE_ID'")
REPO_CWD=$(jq -r --arg slug "$REPO_SLUG" '(.[$slug] // .default).cwd' "$SLOT_CONFIG")
PROJECT_JSON="$REPO_CWD/PROJECT.json"
if [ ! -f "$PROJECT_JSON" ]; then
  echo "error: no PROJECT.json at $REPO_CWD; merge needs lint_command + test_command" >&2
  exit 6
fi
LINT_CMD=$(jq -r '.lint_command // "true"' "$PROJECT_JSON")
TEST_CMD=$(jq -r '.test_command // "true"' "$PROJECT_JSON")

# Update feature status
sqlite3 "$DB" "UPDATE features SET status='merging' WHERE feature_id='$FEATURE_ID'"

# Create merge branch from origin/main
BRANCH="merge/${FEATURE_ID}"
echo "==creating merge branch $BRANCH=="
cd "$REPO_CWD"
git fetch origin main 2>&1 | tail -1
git checkout -B "$BRANCH" origin/main 2>&1 | tail -1

# Apply patches in dependency-order
echo
echo "==applying patches in dep order=="
APPLY_ERRORS=0
ORDER_JSON=$(python3 <<PYEOF
import json, sqlite3
conn = sqlite3.connect("$DB")
rows = conn.execute(
    "SELECT task_id, dependencies FROM work_units WHERE feature_id=? AND status='completed'",
    ("$FEATURE_ID",),
).fetchall()
# Topological sort
deps = {t: set(json.loads(d or "[]")) for t, d in rows}
order, visited = [], set()
def visit(t):
    if t in visited: return
    for d in deps.get(t, set()):
        if d in deps:
            visit(d)
    visited.add(t)
    order.append(t)
for t in deps:
    visit(t)
print(json.dumps(order))
PYEOF
)

for tid in $(echo "$ORDER_JSON" | python3 -c "import json,sys; [print(t) for t in json.load(sys.stdin)]"); do
  echo "  applying $tid..."
  # Extract diff_blob to temp file
  TMP_PATCH="/tmp/merge-${FEATURE_ID}-${tid}.patch"
  python3 -c "
import sqlite3
c = sqlite3.connect('$DB')
b = c.execute(\"SELECT diff_blob FROM work_units WHERE feature_id='$FEATURE_ID' AND task_id='$tid'\").fetchone()[0]
if b is None: raise SystemExit('no diff_blob for $tid')
open('$TMP_PATCH', 'wb').write(b)
print(f'  patch size: {len(b)} bytes')
"
  if ! git apply --check "$TMP_PATCH" 2>/tmp/apply-err; then
    echo "  CONFLICT applying $tid:"
    head -10 /tmp/apply-err | sed 's/^/    /'
    APPLY_ERRORS=$((APPLY_ERRORS + 1))
    # TODO: invoke LLM-assist reconcile (Claude session with conflict context) — deferred per plan AC
    continue
  fi
  if ! git apply --index "$TMP_PATCH" 2>/tmp/apply-err; then
    echo "  APPLY FAILED for $tid (despite --check pass):"
    head -10 /tmp/apply-err | sed 's/^/    /'
    APPLY_ERRORS=$((APPLY_ERRORS + 1))
    continue
  fi
  git commit -m "feat($tid): parallel-dev worker output

work_unit task_id: $tid
feature: $FEATURE_ID
applied by merge-coordinator.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" 2>&1 | tail -1
  rm -f "$TMP_PATCH"
done

if [ "$APPLY_ERRORS" -gt 0 ]; then
  echo
  echo "==MERGE FAILED: $APPLY_ERRORS patches couldn't apply (no LLM-assist in this version) =="
  sqlite3 "$DB" "UPDATE features SET status='failed' WHERE feature_id='$FEATURE_ID'"
  exit 7
fi

# Run lint + test
echo
echo "==running lint: $LINT_CMD=="
LINT_OUT=$(bash -c "$LINT_CMD" 2>&1) || {
  echo "$LINT_OUT" | tail -20
  sqlite3 "$DB" "UPDATE features SET status='failed' WHERE feature_id='$FEATURE_ID'"
  echo "==MERGE FAILED: lint failed =="
  exit 8
}
echo "  lint OK"

echo "==running tests: $TEST_CMD=="
TEST_OUT=$(bash -c "$TEST_CMD" 2>&1) || {
  echo "$TEST_OUT" | tail -20
  sqlite3 "$DB" "UPDATE features SET status='failed' WHERE feature_id='$FEATURE_ID'"
  echo "==MERGE FAILED: tests failed =="
  exit 9
}
echo "  tests OK"

# Push + open MR
if $DRY_RUN; then
  echo
  echo "==DRY-RUN: would push + open MR =="
  echo "  branch: $BRANCH"
  echo "  base: main"
  echo "  commits on branch:"
  git log --oneline origin/main..HEAD | head -5
  sqlite3 "$DB" "UPDATE features SET status='done' WHERE feature_id='$FEATURE_ID'"
  exit 0
fi

echo
echo "==push $BRANCH=="
git push -u origin "$BRANCH" 2>&1 | tail -3

# Open MR via GitLab API
GITLAB_TOKEN=$(grep -E '^GITLAB_TOKEN=' /app/claude-gateway/.env | cut -d= -f2-)
# Find project_id from the repo's origin URL
ORIGIN_URL=$(git remote get-url origin)
# TODO: derive project_id from origin URL via API search (omitted for scaffold)
PROJECT_ID=27  # meshsat known id; PROJECT.json could store this in future

# Risk classification (Phase 6 wire-up via classify-feature-risk.py)
CLASS_JSON=$(/home/app-user/gateway-state/bin/classify-feature-risk.py "$FEATURE_ID" --json 2>/dev/null)
FEATURE_RISK=$(echo "$CLASS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('feature_risk_score',1.0))")
AUTO_MERGE=$(echo "$CLASS_JSON" | python3 -c "import sys,json; print('true' if json.load(sys.stdin).get('auto_merge',False) else 'false')")
RISK_REASONS=$(echo "$CLASS_JSON" | python3 -c "import sys,json; print(' | '.join(json.load(sys.stdin).get('reasons',[])))")

NEEDS_HUMAN=""
[ "$FAILED" -gt 0 ] && NEEDS_HUMAN="$NEEDS_HUMAN [PARTIAL: $FAILED tasks failed]"
[ "$AUTO_MERGE" = "false" ] && NEEDS_HUMAN="$NEEDS_HUMAN [NEEDS-HUMAN]"

MR_BODY=$(cat <<MRBODY
## Summary

Parallel-dev feature **$FEATURE_ID** — auto-assembled by \`merge-coordinator.sh\`.
$COMPLETED of $TOTAL work_units completed (risk_score=$FEATURE_RISK).

**Risk classification:** auto_merge=$AUTO_MERGE
**Reasons:** $RISK_REASONS

Co-Authored-By: parallel-dev workers (slots 1..4)$NEEDS_HUMAN
MRBODY
)

curl -fsS -X POST -H "PRIVATE-TOKEN: $GITLAB_TOKEN" -H "Content-Type: application/json" \
  "https://gitlab.example.net/api/v4/projects/$PROJECT_ID/merge_requests" \
  -d "$(jq -n --arg br "$BRANCH" --arg body "$MR_BODY" --arg title "feat($FEATURE_ID): parallel-dev assembly$NEEDS_HUMAN" '{
    source_branch: $br,
    target_branch: "main",
    title: $title,
    description: $body,
    remove_source_branch: false
  }')" | python3 -c "
import sys, json, sqlite3
r = json.load(sys.stdin)
print(f'MR opened: !{r[\"iid\"]} — {r[\"title\"]}')
print(f'  URL: {r[\"web_url\"]}')
c = sqlite3.connect('$DB')
c.execute(\"UPDATE features SET status='done', mr_iid=?, mr_url=?, completed_at=strftime('%s','now') WHERE feature_id='$FEATURE_ID'\", (r['iid'], r['web_url']))
c.commit()
"
echo "==merge-coordinator complete for $FEATURE_ID =="
