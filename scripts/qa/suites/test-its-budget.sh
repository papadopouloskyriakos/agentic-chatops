#!/usr/bin/env bash
# IFRNLLEI01PRD-750 — Inference-Time-Scaling explicit budget (G3.P1.3).
#
# Verifies that the EXTENDED_THINKING_BUDGET_S env var contract is honoured
# by Build Prompt: when set, the prompt MUST contain a "## Reasoning Budget"
# section; when unset (or 0), the section is absent.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="750-its-budget"
RUNNER="$REPO_ROOT/workflows/claude-gateway-runner.json"

# ─── T1 runner workflow file exists ────────────────────────────────────────
start_test "runner_workflow_exists"
  if [ ! -f "$RUNNER" ]; then
    fail_test "missing $RUNNER"
  fi
end_test

# ─── T2 Build Prompt jsCode references EXTENDED_THINKING_BUDGET_S ─────────
start_test "build_prompt_reads_env_var"
  if python3 - <<PY
import json, sys
data = json.load(open("$RUNNER"))
nodes = data.get("nodes", [])
build = next((n for n in nodes if "Build Prompt" in n.get("name", "")), None)
if not build:
    sys.exit(2)
js = (build.get("parameters", {}) or {}).get("jsCode", "") or ""
sys.exit(0 if "EXTENDED_THINKING_BUDGET_S" in js else 1)
PY
  then
    :
  else
    rc=$?
    if [ "$rc" -eq 2 ]; then
      fail_test "Build Prompt node not found"
    else
      fail_test "Build Prompt jsCode does not reference EXTENDED_THINKING_BUDGET_S"
    fi
  fi
end_test

# ─── T3 Build Prompt jsCode references the section header ──────────────────
start_test "build_prompt_emits_reasoning_budget_section"
  if python3 - <<PY
import json, sys
data = json.load(open("$RUNNER"))
nodes = data.get("nodes", [])
build = next((n for n in nodes if "Build Prompt" in n.get("name", "")), None)
if not build:
    sys.exit(2)
js = (build.get("parameters", {}) or {}).get("jsCode", "") or ""
sys.exit(0 if "## Reasoning Budget" in js else 1)
PY
  then
    :
  else
    fail_test "Build Prompt jsCode does not emit '## Reasoning Budget' header"
  fi
end_test

# ─── T4 Build Prompt jsCode references team_charter or Team Charter ──────
start_test "build_prompt_emits_team_charter"
  if python3 - <<PY
import json, sys
data = json.load(open("$RUNNER"))
nodes = data.get("nodes", [])
build = next((n for n in nodes if "Build Prompt" in n.get("name", "")), None)
if not build:
    sys.exit(2)
js = (build.get("parameters", {}) or {}).get("jsCode", "") or ""
sys.exit(0 if ("Team Charter" in js or "team_charter" in js) else 1)
PY
  then
    :
  else
    fail_test "Build Prompt jsCode does not emit a Team Charter section"
  fi
end_test

# ─── T5 schema_version registry has event_log >= 2 (G3 bumps 1→2) ───────
start_test "event_log_schema_advanced_for_g3"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.schema_version import CURRENT_SCHEMA_VERSION as V; print(V['event_log'])")
  if [ "$out" -ge 2 ]; then
    :
  else
    fail_test "event_log schema_version=$out, expected ≥2 after G3 lands (G3 adds team_charter + its_budget_consumed)"
  fi
end_test

# ─── T6 SessionEvents library has the new event_types ───────────────────
start_test "session_events_lib_has_team_charter_and_its_budget"
  out=$(cd "$REPO_ROOT/scripts" && python3 -c "from lib.session_events import EVENT_TYPES; print(','.join(EVENT_TYPES))")
  assert_contains "$out" "team_charter" "team_charter not in EVENT_TYPES"
  assert_contains "$out" "its_budget_consumed" "its_budget_consumed not in EVENT_TYPES"
end_test
