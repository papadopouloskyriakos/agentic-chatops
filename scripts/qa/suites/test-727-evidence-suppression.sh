#!/usr/bin/env bash
# IFRNLLEI01PRD-712 hardening J4 — evidence_missing suppresses [AUTO-RESOLVE]
# at Runner Prepare-Result time.
#
# Extracts the live Prepare Result jsCode from the committed workflow JSON,
# runs it via `new Function()` with mocked `$('NodeName')` inputs, and
# asserts behaviour for 4 cases.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="727-evidence-suppression"

WORKFLOW="$REPO_ROOT/workflows/claude-gateway-runner.json"

_run_case() {
  # Args: label reply_text em(true|false) reason_contains suppress(true|false)
  local label="$1" reply="$2" expect_em="$3" reason_sub="$4" expect_suppress="$5"

  python3 - "$WORKFLOW" "$reply" <<'PY' > /tmp/pr-extract-$$.js
import json, sys
workflow, reply = sys.argv[1], sys.argv[2]
wf = json.load(open(workflow))
pr = next(n for n in wf['nodes'] if n['name'] == 'Prepare Result')
print(pr['parameters']['jsCode'])
PY

  node -e "
    const fs = require('fs');
    const jsCode = fs.readFileSync('/tmp/pr-extract-$$.js', 'utf8');
    const reply = $(python3 -c "import json, sys; print(json.dumps(sys.argv[1]))" "$reply");
    const mockInputs = {
      'Parse Response': [{ json: {
        sessionId: 'qa-727',
        issueId: 'IFRNLLEI01PRD-727-test',
        summary: '$label',
        result: reply,
        hasValidSession: false,
        retriedWithWarnings: false, retryCount: 0,
        costEur: 0, numTurns: 1, durationMs: 1000,
        confidence: 0.9, model: 'claude-test',
        totalInputTokens: 0, totalOutputTokens: 0,
        totalCacheWrite: 0, totalCacheRead: 0, promptVariant: 'test',
      } }],
      'Format Pre Stats': [{ json: { preStartTime: Date.now() - 1000 } }],
      'Build Prompt': [{ json: { alertCategory: 'availability' } }],
    };
    global.\$input = { first: () => mockInputs['Parse Response'][0] };
    global.\$ = (n) => { const i = mockInputs[n] || [{ json: {} }]; return { first: () => i[0], all: () => i }; };
    try {
      const out = (new Function(jsCode))();
      const r = out[0].json;
      console.log(JSON.stringify({
        em: r.evidenceMissing, er: r.evidenceReason || '',
        suppress: (r.matrixBody||'').includes('AUTO-RESOLVE-SUPPRESSED'),
        banner: (r.matrixBody||'').includes('GUARDRAIL EVIDENCE-MISSING'),
      }));
    } catch (e) { console.error('RUNERR:', e.message); process.exit(1); }
  " 2>/tmp/pr-err-$$ | python3 -c "
import json, sys, os
line = sys.stdin.read().strip()
if not line:
    sys.stderr.write('empty output; stderr was: ' + open('/tmp/pr-err-$$').read() + '\n')
    sys.exit(1)
r = json.loads(line)
# Compare
expect_em = ('$expect_em' == 'true')
expect_suppress = ('$expect_suppress' == 'true')
reason_sub = '''$reason_sub'''
ok = r['em'] == expect_em and r['suppress'] == expect_suppress
if reason_sub and reason_sub not in r['er']:
    ok = False
sys.exit(0 if ok else 2)
"
  local rc=$?
  rm -f /tmp/pr-extract-$$.js /tmp/pr-err-$$
  return $rc
}

# ─── T1 workflow file exists + has Prepare Result node ──────────────────
start_test "workflow_has_prepare_result_node"
  if [ ! -f "$WORKFLOW" ]; then
    fail_test "missing $WORKFLOW"
  elif ! python3 -c "
import json
d = json.load(open('$WORKFLOW'))
pr = next((n for n in d['nodes'] if n['name'] == 'Prepare Result'), None)
assert pr, 'Prepare Result node not found'
js = pr['parameters']['jsCode']
assert '<<< evidence-missing check (IFRNLLEI01PRD-712 hardening J4) >>>' in js, 'injection markers absent'
assert '>>> end evidence-missing' in js, 'end marker absent'
" 2>/dev/null; then
    fail_test "Prepare Result missing or injection markers absent"
  fi
end_test

# ─── T2 high-confidence no-fence AUTO-RESOLVE is suppressed ─────────────
start_test "high_conf_no_fence_suppresses_auto_resolve"
  if _run_case "high_conf_no_fence" \
    "Root cause: DNS flap. CONFIDENCE: 0.9 — verified.
[AUTO-RESOLVE] Done." \
    "true" "high_confidence_no_code_fence:0.9" "true"; then
    :
  else
    fail_test "high-confidence no-fence reply should trigger suppression"
  fi
end_test

# ─── T3 high-confidence WITH fence passes through ───────────────────────
start_test "high_conf_with_fence_passes_through"
  if _run_case "high_conf_with_fence" \
    "Fix applied.
\`\`\`
systemctl status foo -> active
\`\`\`
CONFIDENCE: 0.9 — verified.
[AUTO-RESOLVE] Done." \
    "false" "" "false"; then
    :
  else
    fail_test "fenced reply with CONFIDENCE 0.9 should NOT trigger"
  fi
end_test

# ─── T4 low-confidence no-fence not flagged ─────────────────────────────
start_test "low_conf_no_fence_not_flagged"
  if _run_case "low_conf_no_fence" \
    "Need more investigation. CONFIDENCE: 0.5 — partial." \
    "false" "" "false"; then
    :
  else
    fail_test "CONFIDENCE 0.5 should NOT trigger"
  fi
end_test

# ─── T5 CONFIDENCE: 1.0 no-fence flagged ────────────────────────────────
start_test "confidence_one_no_fence_flagged"
  if _run_case "confidence_one" \
    "Fix complete. CONFIDENCE: 1.0. [AUTO-RESOLVE]" \
    "true" "high_confidence_no_code_fence:1.0" "true"; then
    :
  else
    fail_test "CONFIDENCE 1.0 no-fence should trigger"
  fi
end_test
