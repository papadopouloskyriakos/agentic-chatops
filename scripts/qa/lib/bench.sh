#!/usr/bin/env bash
# Benchmark helpers: timing, percentile, scorecard emission.
# shellcheck shell=bash
set -u

QA_BENCH_FILE="${QA_BENCH_FILE:-/tmp/qa-bench.jsonl}"

bench_time_ms() {
  # Usage: bench_time_ms <iters> <name> -- <cmd...>
  # Runs <cmd> <iters> times, prints mean/p50/p95/max/min to stdout as JSON,
  # and appends one JSONL line to $QA_BENCH_FILE.
  local iters="$1" name="$2"; shift 2
  [ "$1" = "--" ] && shift
  local t0 t1 dur
  local -a durations
  local i=0
  while [ $i -lt "$iters" ]; do
    t0=$(python3 -c 'import time; print(time.time_ns())')
    "$@" >/dev/null 2>&1 || true
    t1=$(python3 -c 'import time; print(time.time_ns())')
    dur=$(( (t1 - t0) / 1000000 ))
    durations+=("$dur")
    i=$(( i + 1 ))
  done
  local data
  data=$(printf '%s\n' "${durations[@]}" | python3 -c '
import json,sys,statistics
vals = sorted(int(x) for x in sys.stdin.read().split())
n = len(vals) or 1
def q(p):
    idx = min(n-1, int(p*(n-1)+0.5))
    return vals[idx]
out = {"n": n, "min": vals[0], "p50": q(0.50), "p95": q(0.95),
       "max": vals[-1], "mean": round(statistics.mean(vals), 2)}
print(json.dumps(out))
')
  printf '%s\n' "$data"
  python3 -c '
import json,sys
d = json.loads(sys.argv[1])
d["benchmark"] = sys.argv[2]
print(json.dumps(d))
' "$data" "$name" >> "$QA_BENCH_FILE"
}

bench_record() {
  # Usage: bench_record <name> <key> <value>  — emit a single-value metric
  python3 -c '
import json,sys
print(json.dumps({"benchmark": sys.argv[1], sys.argv[2]: float(sys.argv[3])}))
' "$1" "$2" "$3" >> "$QA_BENCH_FILE"
}
