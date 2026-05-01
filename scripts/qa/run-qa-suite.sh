#!/usr/bin/env bash
# QA suite orchestrator for the 9-issue OpenAI SDK adoption batch.
#
# Runs:
#   * 9 per-issue test suites (sanity + QA + integration)
#   * 4 e2e cross-cutting scenarios
#   * 6 performance benchmarks (optional; skip with --no-bench)
#
# Emits a JSON scorecard to scripts/qa/reports/<date>.json plus a
# human-readable summary on stdout. Exit 0 iff all tests pass.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

QA_DIR="$REPO_ROOT/scripts/qa"
REPORT_DIR="$QA_DIR/reports"
mkdir -p "$REPORT_DIR"

STAMP=$(date +%Y-%m-%dT%H-%M-%SZ)
QA_RESULT_FILE="$REPORT_DIR/results-${STAMP}.jsonl"
QA_BENCH_FILE="$REPORT_DIR/bench-${STAMP}.jsonl"
SCORECARD="$REPORT_DIR/scorecard-${STAMP}.json"
SUMMARY_FILE="$REPORT_DIR/summary-${STAMP}.txt"
export QA_RESULT_FILE QA_BENCH_FILE
: > "$QA_RESULT_FILE"
: > "$QA_BENCH_FILE"

VERBOSE=0
RUN_BENCH=1
RUN_E2E=1
FILTER=""
for arg in "$@"; do
  case "$arg" in
    --verbose|-v)  VERBOSE=1 ;;
    --no-bench)    RUN_BENCH=0 ;;
    --no-e2e)      RUN_E2E=0 ;;
    --filter=*)    FILTER="${arg#--filter=}" ;;
    --help|-h)
      sed -n '3,12p' "${BASH_SOURCE[0]}" | sed 's/^# //'
      exit 0
      ;;
  esac
done
export QA_VERBOSE="$VERBOSE"

banner() { printf '\n\e[1m━━━ %s ━━━\e[0m\n' "$1"; }

run_one() {
  local path="$1"
  local name
  name="$(basename "$path" .sh)"
  if [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]]; then
    return 0
  fi
  banner "$name"
  # Per-suite timeout guard (IFRNLLEI01PRD-724): a single slow suite used
  # to wedge the whole orchestrator (test-642-edge-cases hang on 2026-04-23).
  # `timeout` + synthetic FAIL record ensures the scorecard surfaces the
  # wedge instead of silently truncating. Each suite also runs in a
  # subshell so a `set -e` or an exit 1 doesn't kill us.
  # Default 120s chosen empirically: test-639-deny-patterns needs ~74s solo
  # for its 53 pattern-level bash+python invocations, but scales to ~90-100s
  # under full-suite load (python startup + SQLite mutex contention with
  # other suites' fresh_db() calls). 120s absorbs that without masking real
  # hangs (a wedged suite would be minutes, not 120s). Override with
  # QA_PER_SUITE_TIMEOUT for stricter CI.
  local per_suite_timeout="${QA_PER_SUITE_TIMEOUT:-120}"
  local start_ts
  start_ts=$(date +%s)
  timeout --signal=TERM --kill-after=5 "$per_suite_timeout" bash "$path"
  local rc=$?
  if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
    local now
    now=$(date +%s)
    local dur_ms=$(( (now - start_ts) * 1000 ))
    python3 - "$name" "$per_suite_timeout" "$dur_ms" "$QA_RESULT_FILE" <<'PY' >/dev/null 2>&1 || true
import json, sys
suite, tmo, dur_ms, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
rec = {
    "suite": suite,
    "test": "per_suite_timeout_guard",
    "status": "FAIL",
    "detail": f"exceeded QA_PER_SUITE_TIMEOUT={tmo}s (wall {dur_ms}ms)",
    "duration_ms": dur_ms,
}
with open(out, "a") as f:
    f.write(json.dumps(rec) + "\n")
PY
    printf '  \e[31mTIMEOUT\e[0m %s exceeded %ss — synthetic FAIL recorded\n' \
           "$name" "$per_suite_timeout" >&2
  fi
  return 0
}

# ── Per-issue suites ──────────────────────────────────────────────────────────
banner "Per-issue suites"
for f in "$QA_DIR/suites"/*.sh; do run_one "$f"; done

# ── E2E scenarios ─────────────────────────────────────────────────────────────
if [ "$RUN_E2E" = "1" ]; then
  banner "E2E scenarios"
  for f in "$QA_DIR/e2e"/*.sh; do run_one "$f"; done
fi

# ── Benchmarks ────────────────────────────────────────────────────────────────
if [ "$RUN_BENCH" = "1" ]; then
  banner "Benchmarks"
  for f in "$QA_DIR/bench"/*.sh; do run_one "$f"; done
fi

# ── Scorecard ─────────────────────────────────────────────────────────────────
banner "Scorecard"
python3 - "$QA_RESULT_FILE" "$QA_BENCH_FILE" "$SCORECARD" "$SUMMARY_FILE" <<'PY'
import json, sys
from collections import defaultdict, Counter

result_file, bench_file, scorecard_path, summary_path = sys.argv[1:5]

# Load results.
per_suite = defaultdict(lambda: Counter())
all_tests = []
try:
    with open(result_file) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            rec = json.loads(line)
            per_suite[rec["suite"]][rec["status"]] += 1
            all_tests.append(rec)
except FileNotFoundError:
    pass

# Load benchmarks.
benchmarks = []
try:
    with open(bench_file) as f:
        for line in f:
            line = line.strip()
            if line: benchmarks.append(json.loads(line))
except FileNotFoundError:
    pass

total_pass = sum(c["PASS"] for c in per_suite.values())
total_fail = sum(c["FAIL"] for c in per_suite.values())
total_skip = sum(c["SKIP"] for c in per_suite.values())
total = total_pass + total_fail + total_skip
score = round(100.0 * total_pass / total, 2) if total else 0.0

suites_out = {
    s: {"pass": c["PASS"], "fail": c["FAIL"], "skip": c["SKIP"],
        "tests": [t for t in all_tests if t["suite"] == s]}
    for s, c in sorted(per_suite.items())
}

scorecard = {
    "total_pass": total_pass,
    "total_fail": total_fail,
    "total_skip": total_skip,
    "score_pct": score,
    "suites": suites_out,
    "benchmarks": benchmarks,
}
with open(scorecard_path, "w") as f:
    json.dump(scorecard, f, indent=2, sort_keys=True)

# Pretty summary
lines = []
lines.append(f"QA scorecard — pass={total_pass} fail={total_fail} skip={total_skip} score={score}%")
lines.append("")
w = max((len(s) for s in per_suite), default=0)
for s, c in sorted(per_suite.items()):
    bar = "PASS" if c["FAIL"] == 0 else f"FAIL ({c['FAIL']})"
    lines.append(f"  {s:<{w}}  pass={c['PASS']:>3} fail={c['FAIL']} skip={c['SKIP']}  [{bar}]")
if benchmarks:
    lines.append("")
    lines.append("Benchmarks:")
    for b in benchmarks:
        name = b.pop("benchmark", "?")
        keys = ", ".join(f"{k}={v}" for k, v in sorted(b.items()))
        lines.append(f"  {name}: {keys}")
summary = "\n".join(lines)
with open(summary_path, "w") as f:
    f.write(summary + "\n")
print(summary)

sys.exit(1 if total_fail > 0 else 0)
PY

rc=$?
echo
echo "Scorecard: $SCORECARD"
echo "Summary:   $SUMMARY_FILE"
exit "$rc"
