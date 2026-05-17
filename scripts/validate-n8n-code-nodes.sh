#!/bin/bash
# validate-n8n-code-nodes.sh — pre-push validator for n8n Code node jsCode.
#
# Purpose: catch the class of bug that caused the 2026-04-10 14-hour outage
# (Runner Build Prompt SyntaxError on parse — try/catch can't catch it).
#
# Usage:
#   validate-n8n-code-nodes.sh <workflow-id>         # fetch live from n8n API
#   validate-n8n-code-nodes.sh --file <path.json>    # check exported workflow JSON
#
# Checks every Code node in the workflow for:
#   1. Node.js --check parse (the authoritative smoking-gun check — this is
#      exactly what was broken during the 14h outage)
#   2. `new Function(...)` constructor parse (matches n8n runtime semantics —
#      catches issues --check can miss like strict-mode redeclaration)
#   3. Exactly one top-level `return` (>1 = unreachable code, the exact shape
#      the Build Prompt had before IFRNLLEI01PRD-622 cleanup — invites
#      accidental edits of dead code that look live)
#   4. No duplicate top-level `var foo` declarations for the same name
#      (catches "3 copy-pasted variant blocks share scope" pattern)
#
# Raw quote-balance was removed — escaped quotes in string literals produce
# odd raw counts even for fully-valid code (false positive on "Prepare Result"
# in the Runner workflow). --check + new Function() already detect truncated
# string literals authoritatively.
#
# Exit non-zero on any failure. Meant to run before `curl -X PUT` to
# /api/v1/workflows/<id>.

set -uo pipefail
MODE="fetch"
TARGET=""
N8N_URL="${N8N_URL:-https://n8n.example.net}"
N8N_API_KEY="${N8N_API_KEY:-$(grep -E '^N8N_API_KEY|^N8N_JWT_TOKEN' ~/.claude.json 2>/dev/null | head -1 | cut -d'"' -f4)}"

case "${1:-}" in
  --file)
    MODE="file"
    TARGET="${2:?missing file path}"
    ;;
  -h|--help|"")
    sed -n '3,30p' "$0"
    exit 0
    ;;
  *)
    TARGET="$1"
    ;;
esac

TMP=$(mktemp -d)
trap "rm -rf $TMP" EXIT

if [ "$MODE" = "file" ]; then
    [ -f "$TARGET" ] || { echo "file not found: $TARGET" >&2; exit 1; }
    cp "$TARGET" "$TMP/workflow.json"
else
    # Fetch from n8n API
    [ -n "$N8N_API_KEY" ] || { echo "no N8N_API_KEY in env or ~/.claude.json" >&2; exit 1; }
    curl -sS -H "X-N8N-API-KEY: $N8N_API_KEY" "$N8N_URL/api/v1/workflows/$TARGET" > "$TMP/workflow.json"
    if ! python3 -c "import json; json.load(open('$TMP/workflow.json'))" 2>/dev/null; then
        echo "failed to fetch workflow $TARGET" >&2
        head -c 500 "$TMP/workflow.json" >&2
        exit 1
    fi
fi

# Extract each Code node into its own file
python3 <<PYEOF
import json, os
data = json.load(open('$TMP/workflow.json'))
count = 0
for n in data.get('nodes', []):
    if n.get('type') == 'n8n-nodes-base.code':
        name = n.get('name', 'unnamed').replace('/', '_').replace(' ', '_')
        code = n.get('parameters', {}).get('jsCode', '')
        if code.strip():
            path = f'$TMP/{name}.js'
            open(path, 'w').write(code if code.endswith('\n') else code + '\n')
            count += 1
print(f'extracted {count} Code node(s)')
PYEOF

FAIL=0
for js in "$TMP"/*.js; do
    [ -f "$js" ] || continue
    name=$(basename "$js" .js)
    echo
    echo "=== $name ==="

    # Check 1: Node.js --check
    if ! node --check "$js" 2>&1 | sed 's/^/  /'; then
        FAIL=1
        echo "  [FAIL] node --check failed"
        continue
    fi

    # Structural checks in one Node pass
    node_output=$(node - "$js" <<'NODEEOF' 2>&1
const fs = require('fs');
const path = process.argv[2];
const code = fs.readFileSync(path, 'utf-8');
let fail = 0;

// new Function() parse matches n8n runtime
try {
    new Function('$', '$input', 'Buffer', 'require', code);
    console.log('[ok]   new Function() parse');
} catch (e) {
    console.log('[FAIL] new Function() parse:', e.message);
    fail = 1;
}

// Top-level return count — >1 means unreachable dead code
const topReturns = (code.match(/^return /gm) || []).length;
if (topReturns > 1) {
    console.log('[FAIL] ' + topReturns + ' top-level returns — code after the first is unreachable. Delete dead code.');
    fail = 1;
} else if (topReturns === 1) {
    console.log('[ok]   top-level returns: 1');
} else {
    console.log('[ok]   top-level returns: 0 (transform node)');
}

// Duplicate top-level var declarations signal the "3 variant blocks share scope" pattern
const varDecls = {};
for (const line of code.split('\n')) {
    const m = line.match(/^var ([A-Za-z_$][\w$]*)\s*=/);
    if (m) varDecls[m[1]] = (varDecls[m[1]] || 0) + 1;
}
const dups = Object.entries(varDecls).filter(([, n]) => n > 1);
if (dups.length > 0) {
    console.log('[WARN] duplicate top-level var declarations (accepted by JS but often a dead-code signal):');
    for (const [name, n] of dups) console.log('         ' + name + ': ' + n + ' declarations');
}

process.exit(fail);
NODEEOF
)
    rc=$?
    echo "$node_output" | sed 's/^/  /'
    [ $rc -ne 0 ] && FAIL=1

done

echo
if [ $FAIL -ne 0 ]; then
    echo "VALIDATION FAILED — do NOT push this workflow"
    exit 1
fi
echo "VALIDATION PASSED — safe to push"
