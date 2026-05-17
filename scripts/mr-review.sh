#!/bin/bash
# Claude Code MR Review — automated code review for GitLab merge requests
# Usage: mr-review.sh <project-id> <mr-iid>
# Fetches MR diff, runs Claude Code review, posts feedback as MR comment.
#
# Environment: GITLAB_TOKEN, GITLAB_URL (from .env or env vars)

set -euo pipefail

PROJECT_ID="${1:?Usage: mr-review.sh <project-id> <mr-iid>}"
MR_IID="${2:?Usage: mr-review.sh <project-id> <mr-iid>}"

# Load credentials
if [ -f "$HOME/gitlab/n8n/claude-gateway/.env" ]; then
  source "$HOME/gitlab/n8n/claude-gateway/.env"
fi
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.net}"
GITLAB_TOKEN="${GITLAB_TOKEN:?GITLAB_TOKEN required}"

echo "=== MR REVIEW: Project $PROJECT_ID, MR !$MR_IID ==="

# ─── Step 1: Fetch MR metadata ───
echo "--- Fetching MR metadata ---"
MR_JSON=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID" 2>&1)

if [ -z "$MR_JSON" ]; then
  echo "ERROR: Failed to fetch MR !$MR_IID from project $PROJECT_ID"
  exit 1
fi

MR_TITLE=$(echo "$MR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('title',''))")
MR_DESC=$(echo "$MR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('description','')[:500])")
MR_AUTHOR=$(echo "$MR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('author',{}).get('username',''))")
MR_SOURCE=$(echo "$MR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('source_branch',''))")
MR_TARGET=$(echo "$MR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('target_branch',''))")
MR_WEB_URL=$(echo "$MR_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('web_url',''))")

echo "Title: $MR_TITLE"
echo "Author: $MR_AUTHOR"
echo "Branch: $MR_SOURCE → $MR_TARGET"

# ─── Step 2: Fetch MR diff ───
echo "--- Fetching MR diff ---"
MR_DIFF=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/changes" 2>&1)

DIFF_SUMMARY=$(echo "$MR_DIFF" | python3 -c "
import json, sys
data = json.load(sys.stdin)
changes = data.get('changes', [])
files = []
total_add = 0
total_del = 0
for c in changes:
    path = c.get('new_path', c.get('old_path', ''))
    diff = c.get('diff', '')
    adds = diff.count('\n+') - diff.count('\n+++')
    dels = diff.count('\n-') - diff.count('\n---')
    total_add += adds
    total_del += dels
    files.append(path)
print(f'Files changed: {len(files)}')
print(f'Lines: +{total_add} -{total_del}')
for f in files[:20]:
    print(f'  {f}')
if len(files) > 20:
    print(f'  ... and {len(files) - 20} more')
")
echo "$DIFF_SUMMARY"

# Extract actual diffs (truncated to avoid context overflow)
DIFF_CONTENT=$(echo "$MR_DIFF" | python3 -c "
import json, sys
data = json.load(sys.stdin)
changes = data.get('changes', [])
output = []
total_chars = 0
MAX_CHARS = 30000  # Keep under context limits
for c in changes:
    path = c.get('new_path', c.get('old_path', ''))
    diff = c.get('diff', '')
    header = f'--- {path} ---\n'
    if total_chars + len(header) + len(diff) > MAX_CHARS:
        remaining = MAX_CHARS - total_chars - len(header) - 50
        if remaining > 100:
            output.append(header + diff[:remaining] + '\n[...truncated]')
        break
    output.append(header + diff)
    total_chars += len(header) + len(diff)
print('\n'.join(output))
" 2>/dev/null)

if [ -z "$DIFF_CONTENT" ]; then
  echo "No diff content found"
  exit 0
fi

# ─── Step 3: Determine project directory ───
PROJECT_DIR="$HOME/gitlab/n8n/claude-gateway"
# Map known project IDs to directories
case "$PROJECT_ID" in
  7)  PROJECT_DIR="$HOME/gitlab/infrastructure/nl/production" ;;
  30) PROJECT_DIR="$HOME/gitlab/n8n/claude-gateway" ;;
  *)  PROJECT_DIR="$HOME/gitlab/products/cubeos" ;;
esac

# ─── Step 4: Build review prompt ───
REVIEW_PROMPT="You are reviewing MR !${MR_IID}: ${MR_TITLE}
Author: ${MR_AUTHOR}
Branch: ${MR_SOURCE} → ${MR_TARGET}

Description:
${MR_DESC}

Diff:
${DIFF_CONTENT}

Review this merge request. Focus on:
1. **Correctness** — Will this change work as intended? Any bugs or logic errors?
2. **Safety** — Any security issues, credential exposure, destructive operations without guards?
3. **Conventions** — Does it follow the project's conventions (check CLAUDE.md)?
4. **Impact** — What could break? Any missing error handling or edge cases?

Format your review as:

## MR Review: !${MR_IID}

### Summary
One-sentence assessment.

### Issues Found
- [CRITICAL/WARNING/INFO] Description of issue (file:line if applicable)

### Suggestions
- Specific improvement suggestions

### Verdict
One of: APPROVE, REQUEST_CHANGES, or NEEDS_DISCUSSION

CONFIDENCE: 0.X — reason

If the diff is trivial (docs, formatting, comments only), say so briefly and APPROVE."

# ─── Step 5: Run Claude Code review ───
echo "--- Running Claude Code review ---"
REVIEW_B64=$(echo "$REVIEW_PROMPT" | base64 -w0)

cd "$PROJECT_DIR"
unset CLAUDECODE

REVIEW_OUTPUT=$(timeout 300 "$HOME/.local/bin/claude" -p "$(echo "$REVIEW_B64" | base64 -d)" \
  --output-format json --dangerously-skip-permissions --no-session-persistence 2>&1)

REVIEW_RESULT=$(echo "$REVIEW_OUTPUT" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data.get('result', ''))
except:
    print(sys.stdin.read() if hasattr(sys.stdin, 'read') else '')
" 2>/dev/null)

if [ -z "$REVIEW_RESULT" ]; then
  echo "ERROR: Claude returned empty review"
  exit 1
fi

echo "--- Review result ---"
echo "$REVIEW_RESULT" | head -30
echo "..."

# ─── Step 6: Post review as MR comment ───
echo "--- Posting review to MR ---"
COMMENT_BODY="### Automated Code Review (Claude Code)

${REVIEW_RESULT}

---
*Automated review by Claude Code. Not a substitute for human review.*"

python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'body': '''$( echo "$COMMENT_BODY" | sed "s/'/\\\\'/g" )'''}).encode()
req = urllib.request.Request(
    '${GITLAB_URL}/api/v4/projects/${PROJECT_ID}/merge_requests/${MR_IID}/notes',
    data=data,
    headers={'PRIVATE-TOKEN': '${GITLAB_TOKEN}', 'Content-Type': 'application/json'},
    method='POST'
)
try:
    resp = urllib.request.urlopen(req, context=ctx)
    result = json.loads(resp.read())
    print('Posted review as comment ID:', result.get('id', ''))
except Exception as e:
    print('WARN: Failed to post comment:', e)
" 2>/dev/null

# ─── Step 7: Extract verdict ───
VERDICT=$(echo "$REVIEW_RESULT" | grep -oP '(?:Verdict|verdict).*?(APPROVE|REQUEST_CHANGES|NEEDS_DISCUSSION)' | grep -oP 'APPROVE|REQUEST_CHANGES|NEEDS_DISCUSSION' | head -1 || echo "UNKNOWN")
CONFIDENCE=$(echo "$REVIEW_RESULT" | grep -oP 'CONFIDENCE:\s*\K[0-9.]+' | head -1 || echo "0.0")

echo ""
echo "REVIEW_JSON:{\"project\":$PROJECT_ID,\"mr\":$MR_IID,\"verdict\":\"$VERDICT\",\"confidence\":$CONFIDENCE}"
echo "=== MR REVIEW COMPLETE ==="
