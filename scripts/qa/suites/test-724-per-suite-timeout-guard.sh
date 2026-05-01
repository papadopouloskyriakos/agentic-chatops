#!/usr/bin/env bash
# IFRNLLEI01PRD-724 — per-suite timeout guard in run-qa-suite.sh.
#
# The guard prevents a single slow/hung suite from wedging the full
# orchestrator. This test proves:
#   T1: the guard fires on a hanging suite
#   T2: the orchestrator continues past a timed-out suite
#   T3: a synthetic FAIL row lands in $QA_RESULT_FILE with the correct shape
#   T4: the orchestrator's own run (not the bench/e2e) stays green on clean suites
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="724-per-suite-timeout-guard"

# We isolate the test by making a sandboxed QA_DIR with only synthetic suites,
# so test-724 doesn't recursively invoke itself.
SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/scripts/qa/suites" "$SANDBOX/scripts/qa/e2e" "$SANDBOX/scripts/qa/bench" "$SANDBOX/scripts/qa/reports"
# Link assert.sh so sourcing works
mkdir -p "$SANDBOX/scripts/qa/lib"
cp "$REPO_ROOT/scripts/qa/lib/assert.sh" "$SANDBOX/scripts/qa/lib/"
cp "$REPO_ROOT/scripts/qa/lib/fixtures.sh" "$SANDBOX/scripts/qa/lib/" 2>/dev/null || true
cp "$REPO_ROOT/scripts/qa/lib/bench.sh" "$SANDBOX/scripts/qa/lib/" 2>/dev/null || true
# Copy the orchestrator too so our synthetic run uses the real logic
cp "$REPO_ROOT/scripts/qa/run-qa-suite.sh" "$SANDBOX/scripts/qa/"
# The orchestrator computes REPO_ROOT from its own path, so make a minimal
# project root by linking any files it might read
ln -s "$REPO_ROOT/scripts" "$SANDBOX/scripts_real" 2>/dev/null || true

# ─── Synthetic suite: hang (sleeps > QA_PER_SUITE_TIMEOUT) ───────────────
cat > "$SANDBOX/scripts/qa/suites/syn-hang.sh" <<'SH'
#!/usr/bin/env bash
sleep 20
SH
chmod +x "$SANDBOX/scripts/qa/suites/syn-hang.sh"

# ─── Synthetic suite: clean (fast PASS via framework) ──────────────────
cat > "$SANDBOX/scripts/qa/suites/syn-clean.sh" <<'SH'
#!/usr/bin/env bash
# Minimal test that uses the framework to emit a PASS record.
set -u
REPO_ROOT="${SANDBOX_REPO:-$REPO_ROOT}"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="syn-clean"
start_test "trivial_assertion"
  :
end_test
SH
chmod +x "$SANDBOX/scripts/qa/suites/syn-clean.sh"

# Run the orchestrator against the sandbox
export SANDBOX_REPO="$SANDBOX"
cd "$SANDBOX"
SANDBOX_OUTPUT=$(QA_PER_SUITE_TIMEOUT=2 timeout 30 \
  bash scripts/qa/run-qa-suite.sh --no-bench --no-e2e 2>&1 || true)

# Find the results file produced
RESULTS_FILE=$(ls -1t "$SANDBOX/scripts/qa/reports"/results-*.jsonl 2>/dev/null | head -1)

# ─── T1: the guard fired on syn-hang ────────────────────────────────────
start_test "guard_fires_on_hanging_suite"
  if echo "$SANDBOX_OUTPUT" | grep -qE 'TIMEOUT|exceeded [0-9]+s'; then
    :
  else
    fail_test "expected TIMEOUT banner on syn-hang, output was: $(echo "$SANDBOX_OUTPUT" | tail -3)"
  fi
end_test

# ─── T2: orchestrator continued past the timeout (reached syn-clean) ───
start_test "orchestrator_continues_past_timeout"
  if echo "$SANDBOX_OUTPUT" | grep -q 'syn-clean'; then
    :
  else
    fail_test "expected orchestrator to reach syn-clean banner after syn-hang; output: $(echo "$SANDBOX_OUTPUT" | tail -10)"
  fi
end_test

# ─── T3: synthetic FAIL row in results.jsonl for the timed-out suite ───
start_test "synthetic_fail_row_written"
  if [ -z "$RESULTS_FILE" ] || [ ! -s "$RESULTS_FILE" ]; then
    fail_test "no results file produced in sandbox; orchestrator output tail: $(echo "$SANDBOX_OUTPUT" | tail -5)"
  else
    found=$(grep 'per_suite_timeout_guard' "$RESULTS_FILE" | head -1)
    if [ -n "$found" ]; then
      # Validate JSON shape
      valid=$(echo "$found" | python3 -c "
import json, sys
try:
    r = json.loads(sys.stdin.read())
    ok = (r.get('suite') == 'syn-hang' and r.get('status') == 'FAIL'
          and r.get('test') == 'per_suite_timeout_guard')
    print('OK' if ok else 'BAD_SHAPE')
except Exception as e:
    print(f'PARSE_ERR:{e}')
" 2>&1)
      if [ "$valid" != "OK" ]; then
        fail_test "synthetic FAIL row malformed: $valid ($found)"
      fi
    else
      fail_test "no per_suite_timeout_guard row in results; tail: $(tail -5 "$RESULTS_FILE")"
    fi
  fi
end_test

# ─── T4: clean suite still emitted its own PASS row ────────────────────
start_test "clean_suite_still_runs_and_emits"
  if [ -z "$RESULTS_FILE" ] || [ ! -s "$RESULTS_FILE" ]; then
    fail_test "no results file in sandbox"
  else
    clean_pass=$(grep '"suite": "syn-clean"' "$RESULTS_FILE" | grep -c '"status": "PASS"')
    if [ "$clean_pass" -ge 1 ]; then
      :
    else
      fail_test "expected ≥1 PASS row for syn-clean, got $clean_pass (results tail: $(tail -5 "$RESULTS_FILE"))"
    fi
  fi
end_test

# ─── T5: configurable timeout via env var ──────────────────────────────
start_test "timeout_is_configurable_via_env"
  # Run again with a 5s timeout — syn-hang now sleeps 20s > 5s, so still fires
  SANDBOX_OUTPUT2=$(QA_PER_SUITE_TIMEOUT=5 timeout 30 \
    bash "$SANDBOX/scripts/qa/run-qa-suite.sh" --no-bench --no-e2e --filter=syn-hang 2>&1 || true)
  if echo "$SANDBOX_OUTPUT2" | grep -qE 'exceeded 5s'; then
    :
  else
    # Either the message format differs or the custom timeout didn't propagate
    fail_test "expected 'exceeded 5s' banner; got: $(echo "$SANDBOX_OUTPUT2" | tail -3)"
  fi
end_test
