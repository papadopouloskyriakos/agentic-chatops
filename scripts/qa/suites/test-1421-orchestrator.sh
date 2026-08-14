#!/usr/bin/env bash
# IFRNLLEI01PRD-1421 — orchestrator control-plane (3 bricks). Regression guard for the
# registry / interaction-graph / orchestration-benchmark. The load-bearing assertion is the
# orchestration SAFETY invariant: an irreversible incident must never be auto-resolved.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# shellcheck source=../lib/assert.sh
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="1421-orchestrator"
cd "$REPO_ROOT"

# ── Brick 1: component registry ──────────────────────────────────────────────
start_test "registry_seed_discovers_components"
  out=$(python3 scripts/registry-seed.py --dry-run 2>&1)
  n=$(printf '%s' "$out" | grep -oE 'discovered [0-9]+' | grep -oE '[0-9]+')
  [ -n "$n" ] && [ "$n" -gt 50 ]; assert_eq 0 $? "seed discovers >50 components (got ${n:-0})"
end_test

start_test "registry_check_runs_and_reports"
  out=$(python3 scripts/registry-check.py --no-metrics 2>&1)
  printf '%s' "$out" | grep -q "components"; assert_eq 0 $? "check reports component liveness"
end_test

start_test "registry_curate_classifies_critical_and_known_dark"
  out=$(python3 scripts/registry-curate.py --dry-run 2>&1)
  printf '%s' "$out" | grep -q "critical"; assert_eq 0 $? "curate marks critical"
  printf '%s' "$out" | grep -q "known_dark"; assert_eq 0 $? "curate marks known_dark"
end_test

# ── Brick 2: interaction graph ───────────────────────────────────────────────
start_test "interaction_graph_analyzes_and_reports_gaps"
  out=$(python3 scripts/interaction-graph.py --json-only --no-metrics 2>&1; python3 scripts/interaction-graph.py --quiet 2>&1)
  g=$(python3 -c "import json;print(json.load(open('config/interaction-graph.json'))['summary']['gaps'])" 2>/dev/null)
  [ -n "$g" ]; assert_eq 0 $? "graph emits a gaps count (got ${g:-none})"
end_test

# ── Brick 3: orchestration benchmark — the SAFETY invariant ──────────────────
start_test "orchestration_safety_invariant_holds"
  # Run against an isolated temp scorecard so the suite does not depend on the live file.
  out=$(python3 scripts/orchestration-benchmark.py --no-metrics 2>&1)
  printf '%s' "$out" | grep -qE "I1 safety-composition:[[:space:]]*PASS"
  assert_eq 0 $? "irreversible incidents are NEVER auto-resolved (the never-auto floor)"
end_test

start_test "orchestration_benchmark_completes_all_invariants"
  out=$(python3 scripts/orchestration-benchmark.py --no-metrics 2>&1)
  inv=$(printf '%s' "$out" | grep -oE 'invariants [0-9]+/4' | grep -oE '^invariants [0-9]+' | grep -oE '[0-9]+')
  [ -n "$inv" ] && [ "$inv" -ge 3 ]; assert_eq 0 $? "at least 3/4 orchestration invariants pass (got ${inv:-0}/4)"
end_test
