#!/usr/bin/env bash
# IFRNLLEI01PRD-1665 — regression guard for the LIVE silent-cognition guard, which fires
# in the Runner's "Prepare Result" Code node (Phase 5), not in any Python module. It reads
# the silent_cognition_guard flag from $('Classify Risk') and suppresses an [AUTO-RESOLVE]
# whose reply ships no fenced evidence, at ANY confidence (extending the >=0.8 J4 check).
# This suite extracts that exact JS block from workflows/claude-gateway-runner.json and
# exercises it in a node harness with a mocked Classify Risk input, so a future node rewire
# cannot silently break the guard with CI green (the months-dark failure mode).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1665-prepare-result-suppression"

# pr_suppressed <reply-text> <flag true|false> -> prints "yes" iff [AUTO-RESOLVE] gets suppressed
pr_suppressed() {
  RESULT="$1" FLAG="$2" REPO="$REPO_ROOT" python3 <<'PY'
import json, os, re, subprocess, tempfile
repo = os.environ["REPO"]
w = json.load(open(f"{repo}/workflows/claude-gateway-runner.json"))
code = [n for n in w["nodes"] if n["name"] == "Prepare Result"][0]["parameters"]["jsCode"]
i = code.find("const EVIDENCE_HIGH_CONF_RE")
ends = [m.end() for m in re.finditer(r"// >>> end evidence-missing", code)]
assert i >= 0 and ends, "evidence block not found in Prepare Result — guard may have been removed"
block = code[i:ends[-1]]
harness = (
    "let result = " + json.dumps(os.environ["RESULT"]) + ";\n"
    "const $ = (n) => ({ first: () => ({ json: { stdout: JSON.stringify({ silent_cognition_guard: "
    + os.environ["FLAG"] + " }) } }) });\n"
    + block + "\n"
    'console.log(/AUTO-RESOLVE-SUPPRESSED/.test(result) ? "yes" : "no");\n'
)
h = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
h.write(harness); h.close()
print(subprocess.run(["node", h.name], capture_output=True, text=True).stdout.strip())
os.unlink(h.name)
PY
}

AR='Incident resolved, host healthy. [AUTO-RESOLVE]'
ARF=$'Resolved.\n```\nsystemctl is-active svc -> active\n```\n[AUTO-RESOLVE]'
HC='Root cause found. CONFIDENCE: 0.9 [AUTO-RESOLVE]'

start_test "guard_on_unfenced_autoresolve_is_suppressed"
  assert_eq "yes" "$(pr_suppressed "$AR" true)"
end_test

start_test "guard_off_unfenced_autoresolve_byte_identical"
  assert_eq "no" "$(pr_suppressed "$AR" false)"
end_test

start_test "guard_on_fenced_evidence_passes_through"
  assert_eq "no" "$(pr_suppressed "$ARF" true)"
end_test

start_test "j4_high_confidence_no_fence_suppressed_even_guard_off"
  assert_eq "yes" "$(pr_suppressed "$HC" false)"
end_test
