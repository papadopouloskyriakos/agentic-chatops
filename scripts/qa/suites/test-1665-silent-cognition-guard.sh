#!/usr/bin/env bash
# IFRNLLEI01PRD-1665 — silent-cognition guard (repositioned to Phase 5 / Prepare Result).
# The guard fires in the Runner's Prepare Result node: it suppresses an [AUTO-RESOLVE]
# whose FINAL reply ships no fenced post-state evidence block, at ANY confidence
# (extending the CONFIDENCE>=0.8 J4 evidence-missing check). n8n Code nodes cannot read
# ~/gateway.* sentinels, so classify-session-risk.py emits a `silent_cognition_guard`
# flag that threads the sentinel state Phase 4 -> Phase 5. This suite guards that
# flag-emission plumbing + the byte-identical-when-off invariant (REQ-005/REQ-008). The
# Prepare Result JS itself is guarded by scripts/validate-n8n-code-nodes.sh + a live
# test-fire (docs/runbooks/n8n-code-node-safety.md).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
source "$REPO_ROOT/scripts/qa/lib/fixtures.sh"

export QA_SUITE_NAME="1665-silent-cognition-guard"

# flag_for <guard 0|1> — prints "yes" iff classify() emits silent_cognition_guard=true
flag_for() {
  cd "$REPO_ROOT/scripts"
  GUARD="$1" python3 - <<'PY'
import importlib.util, os
spec = importlib.util.spec_from_file_location("csr", "classify-session-risk.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
os.environ["INFRAGRAPH_DISABLED"] = "1"
if os.environ.get("GUARD") == "1":
    os.environ["SILENT_COGNITION_GUARD"] = "1"
else:
    # Force "0" (an explicit env value wins over the sentinel in _envflag) so the
    # test is HERMETIC — it must pass whether or not the live host has the
    # ~/gateway.silent_cognition_guard sentinel active (it does, post go-live).
    os.environ["SILENT_COGNITION_GUARD"] = "0"
r = m.classify({"hostname": "h1", "summary": "x", "steps": ["kubectl get pods"], "tools_needed": ["Bash"]}, "availability")
print("yes" if r.get("silent_cognition_guard") is True else "no")
PY
}

# fence_detect <text> — prints "1" iff the Prepare-Result-mirroring fence regex matches
fence_detect() {
  cd "$REPO_ROOT/scripts"
  TXT="$1" python3 - <<'PY'
import importlib.util, os
spec = importlib.util.spec_from_file_location("csr", "classify-session-risk.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("1" if m.CODE_FENCE_RE.search(os.environ["TXT"]) else "0")
PY
}

start_test "guard_off_emits_no_flag_byte_identical"
  assert_eq "no" "$(flag_for 0)"
end_test

start_test "guard_on_emits_flag_for_prepare_result"
  assert_eq "yes" "$(flag_for 1)"
end_test

start_test "fence_regex_detects_fenced_evidence"
  assert_eq "1" "$(fence_detect $'ok\n```\ndf -h\n```')"
end_test

start_test "fence_regex_absent_for_narrated_only"
  assert_eq "0" "$(fence_detect 'All healthy, no action taken.')"
end_test
