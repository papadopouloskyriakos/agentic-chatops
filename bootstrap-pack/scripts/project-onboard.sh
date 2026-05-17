#!/usr/bin/env bash
# project-onboard.sh — register a validated project with the gateway
# (IFRNLLEI01PRD-934 Phase 5 of project-spec-schema epic)
#
# Runs the Phase F validator first; if PASS, appends to gateway-state/slot-config.json,
# emits Matrix-room-creation + YouTrack-project-creation reminders. Idempotent (re-run safe).
#
# Usage:
#   project-onboard.sh <project-dir>
#   project-onboard.sh <project-dir> --dry-run

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <project-dir> [--dry-run]" >&2
  exit 2
fi

PROJECT_DIR=$(realpath "$1")
DRY_RUN=false
[ "${2:-}" = "--dry-run" ] && DRY_RUN=true
SLOT_CONFIG=/home/app-user/gateway-state/slot-config.json
BOOTSTRAP_PACK=$(dirname $(realpath $(dirname "$0")))
VALIDATOR=$BOOTSTRAP_PACK/scripts/validate-project-spec.py

[ ! -d "$PROJECT_DIR" ] && { echo "error: $PROJECT_DIR is not a directory" >&2; exit 3; }
[ ! -f "$PROJECT_DIR/PROJECT.json" ] && { echo "error: no PROJECT.json at $PROJECT_DIR" >&2; exit 4; }

# Step 1: Run Phase F validator
echo "==Phase F gate: running validate-project-spec.py=="
if ! "$VALIDATOR" "$PROJECT_DIR" --json > /tmp/onboard-report.json; then
  echo "BLOCKED: validator failed. Report:"
  cat /tmp/onboard-report.json | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(f'  {r[\"passed\"]}/{r[\"total_checks\"]} checks passed')
for chk in r['results']:
    if not chk['passed']:
        print(f'  [FAIL] {chk[\"name\"]}: {chk[\"details\"]}')
        for e in chk.get('errors', [])[:3]:
            print(f'         - {e}')"
  exit 5
fi
echo "  PASS — all 17 checks green"

# Step 2: Parse PROJECT.json
SLUG=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/PROJECT.json'))['slug'])")
TITLE=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/PROJECT.json'))['title'])")
PREFIX=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/PROJECT.json'))['youtrack_prefix'])")
ROOM=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/PROJECT.json'))['matrix_room'])")
TEST_CMD=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/PROJECT.json'))['test_command'])")
LINT_CMD=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/PROJECT.json'))['lint_command'])")

echo
echo "==project metadata=="
echo "  slug: $SLUG"
echo "  prefix: $PREFIX"
echo "  room: $ROOM"
echo "  cwd: $PROJECT_DIR"

# Step 3: Check for duplicate slot
if jq -e ".[\"$SLUG\"]" "$SLOT_CONFIG" >/dev/null 2>&1; then
  EXISTING_CWD=$(jq -r ".[\"$SLUG\"].cwd" "$SLOT_CONFIG")
  if [ "$EXISTING_CWD" = "$PROJECT_DIR" ]; then
    echo "  slot '$SLUG' already in slot-config.json pointing to same cwd → idempotent no-op"
  else
    echo "ERROR: slot '$SLUG' exists in slot-config.json pointing to DIFFERENT cwd ($EXISTING_CWD vs $PROJECT_DIR)" >&2
    echo "  Resolve manually or pick a different slug." >&2
    exit 6
  fi
else
  echo
  echo "==Step 4: append to slot-config.json=="
  ENTRY=$(jq -n --arg cwd "$PROJECT_DIR" --arg room "$ROOM" \
    --arg test "$TEST_CMD" --arg lint "$LINT_CMD" \
    '{cwd: $cwd, room: $room, test_command: $test, lint_command: $lint}')
  if $DRY_RUN; then
    echo "[DRY-RUN] would add slot '$SLUG': $ENTRY"
  else
    # Atomic write: read → modify → write
    BACKUP="$SLOT_CONFIG.before-onboard-$(date +%s)"
    cp "$SLOT_CONFIG" "$BACKUP"
    jq --arg slug "$SLUG" --argjson entry "$ENTRY" \
      '. + {($slug): $entry}' "$SLOT_CONFIG" > "$SLOT_CONFIG.tmp" \
      && mv "$SLOT_CONFIG.tmp" "$SLOT_CONFIG"
    echo "  slot '$SLUG' added (backup: $BACKUP)"
  fi
fi

# Step 5: Operator-facing instructions
echo
echo "==NEXT STEPS — operator actions=="
echo
echo "1. Edit n8n Derive Slot in BOTH workflows (Runner qadF2WcaBsIR7SWG + Matrix Bridge QGKnHGkw4casiWIU):"
echo "   Add to the slot if/else: : (prefix === '$PREFIX') ? '$SLUG'"
echo "   Add to slotConfig dict: '$SLUG': {cwd: '$PROJECT_DIR', room: '$ROOM'}"
echo "   Follow docs/runbooks/n8n-code-node-safety.md per node edit."
echo
echo "2. Create the YouTrack project (or confirm it exists):"
echo "   POST https://youtrack.example.net/api/admin/projects"
echo "   shortName='$PREFIX' name='$TITLE'"
echo
echo "3. Invite @claude:matrix.example.net to room $ROOM"
echo
echo "4. Smoke-test with a trivial $PREFIX-9999 issue + confirm session lands in cwd, lock at gateway-state/gateway.lock.$SLUG, Matrix message in $ROOM"
echo
echo "5. If parallel-dev wave dispatched, expect MR titled 'feat($PREFIX-NNNN): parallel-dev assembly' under the project repo."
echo
echo "==project-onboard COMPLETE — READY FOR DISPATCH=="
