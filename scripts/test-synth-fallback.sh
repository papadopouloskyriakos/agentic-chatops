#!/bin/bash
# Test L02 Haiku synth + qwen fallback paths.
#
# Synthesis only fires when the max cross-encoder score is below
# SYNTH_THRESHOLD (0.4), so we use a deliberately vague query that won't
# strongly match any single chunk.
#
# Path 1 (happy): SYNTH_BACKEND=auto + valid ANTHROPIC_API_KEY → Haiku runs.
#   Expected stderr: no "[synth-haiku] failed" or "forced failure" line.
#   Expected stdout: a non-empty answer body.
#
# Path 2 (forced failure): SYNTH_HAIKU_FORCE_FAIL=1 → Haiku returns "" →
#   kb-semantic-search falls back to qwen automatically.
#   Expected stderr: exactly one "[synth-haiku] forced failure" line.
#   Expected stdout: still a non-empty answer body (from qwen).

set -u

cd "$(dirname "$0")/.."

QUERY="what are the subtle second-order effects of dual-WAN VTI migration on BGP convergence"
# Force synth by setting threshold above max observable rerank score (1.0 = always synth).
export SYNTH_THRESHOLD=1.0
PASS=0; FAIL=0

check() {
  local name="$1" result="$2"
  if [ "$result" = "PASS" ]; then
    echo "  [PASS] $name"
    PASS=$((PASS+1))
  else
    echo "  [FAIL] $name — $result"
    FAIL=$((FAIL+1))
  fi
}

echo "===== SYNTH FALLBACK TESTS ====="
echo "Query: $QUERY"
echo ""

# Path 1 — Haiku happy path
echo "Path 1: SYNTH_BACKEND=auto (Haiku)"
out1=$(python3 scripts/kb-semantic-search.py search "$QUERY" --limit 5 2>/tmp/synth-p1.err)
len1=${#out1}
[ "$len1" -gt 200 ] && check "Path 1 stdout non-empty (${len1}B)" "PASS" || check "Path 1 stdout" "too short: ${len1}B"
if grep -q "forced failure" /tmp/synth-p1.err; then
  check "Path 1 no forced-failure" "forced-failure leaked into happy path"
else
  check "Path 1 no forced-failure" "PASS"
fi

# Failure modes the injection point handles — each should fall back to qwen
# without a traceback and still produce a useful response.
declare -A MODES
MODES[empty]="1"                  # short-circuits before API call
MODES[rate_limit]="429"            # simulated HTTP 429 rate-limit
MODES[bad_auth]="auth"             # simulated HTTP 401 unauthorized
MODES[timeout]="timeout"           # simulated socket.timeout
MODES[network_error]="network"     # simulated URLError (DNS / connection refused)

# Each mode emits its own distinctive stderr marker — keep them in sync with
# kb-semantic-search.py's _call_haiku_synth() printouts.
declare -A MARKERS
MARKERS[empty]="forced failure via SYNTH_HAIKU_FORCE_FAIL=1"
MARKERS[rate_limit]="forced 429"
MARKERS[bad_auth]="forced auth failure"
MARKERS[timeout]="forced timeout"
MARKERS[network_error]="forced network error"

for mode_name in empty rate_limit bad_auth timeout network_error; do
  inj="${MODES[$mode_name]}"
  marker="${MARKERS[$mode_name]}"
  echo ""
  echo "Path [$mode_name]: SYNTH_HAIKU_FORCE_FAIL=$inj"
  err_log="/tmp/synth-p-${mode_name}.err"
  out=$(SYNTH_HAIKU_FORCE_FAIL="$inj" python3 scripts/kb-semantic-search.py search "$QUERY" --limit 5 2>"$err_log")
  len=${#out}
  [ "$len" -gt 200 ] && check "[$mode_name] fallback produced non-empty answer (${len}B)" "PASS" \
                    || check "[$mode_name] fallback produced answer" "too short: ${len}B"
  if grep -qF "$marker" "$err_log"; then
    check "[$mode_name] marker '$marker' present" "PASS"
  else
    check "[$mode_name] marker present" "missing — injection not exercised"
  fi
  if grep -q "Traceback" "$err_log"; then
    check "[$mode_name] no traceback" "traceback present"
  else
    check "[$mode_name] no traceback" "PASS"
  fi
done

echo ""
echo "Category Synth: $PASS PASS / $FAIL FAIL out of $((PASS + FAIL))"

# Helpful debug artifacts on failure.
if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "--- /tmp/synth-p1.err tail ---"
  tail -20 /tmp/synth-p1.err 2>/dev/null
  for m in empty rate_limit bad_auth timeout network_error; do
    echo "--- /tmp/synth-p-${m}.err tail ---"
    tail -15 "/tmp/synth-p-${m}.err" 2>/dev/null
  done
fi

[ "$FAIL" -eq 0 ]
