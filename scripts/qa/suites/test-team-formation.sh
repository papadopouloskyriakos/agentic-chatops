#!/usr/bin/env bash
# IFRNLLEI01PRD-750 — Team-formation library + skill (G3.P1.2).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="750-team-formation"
LIB="$REPO_ROOT/scripts/lib/team_formation.py"
SKILL="$REPO_ROOT/.claude/skills/team-formation/SKILL.md"

# ─── T1 lib + skill files exist and parse ──────────────────────────────────
start_test "lib_and_skill_exist"
  if [ ! -f "$LIB" ]; then fail_test "missing $LIB"
  elif [ ! -f "$SKILL" ]; then fail_test "missing $SKILL"
  fi
end_test

start_test "lib_compiles"
  rc=0
  python3 -m py_compile "$LIB" >/dev/null 2>&1 || rc=$?
  assert_eq 0 "$rc" "py_compile failed"
end_test

# ─── T2 every agent in KNOWN_AGENTS has a real .claude/agents/<name>.md ────
start_test "known_agents_all_have_files"
  out=$(python3 - <<PY
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("tf", "$LIB")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = pathlib.Path("$REPO_ROOT/.claude/agents")
missing = [a for a in m.KNOWN_AGENTS if not (root / f"{a}.md").exists()]
print(",".join(missing))
PY
)
  assert_eq "" "$out" "missing agent files: $out"
end_test

# ─── T3 propose_team: low-risk availability returns triage-researcher ──────
start_test "low_risk_availability"
  out=$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/scripts/lib'); from team_formation import propose_team; t=propose_team('availability','low'); print([a['agent'] for a in t['agents']])")
  assert_contains "$out" "triage-researcher" "no triage in low-risk avail"
end_test

# ─── T4 high-risk session adds workflow-validator and code-reviewer ────────
start_test "high_risk_adds_validators"
  out=$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/scripts/lib'); from team_formation import propose_team; t=propose_team('maintenance','high'); print(','.join(a['agent'] for a in t['agents']))")
  assert_contains "$out" "workflow-validator" "no workflow-validator in high"
  assert_contains "$out" "code-reviewer" "no code-reviewer in high"
end_test

# ─── T5 hostname maps to specialist (k8s-diagnostician for ctrl01) ────────
start_test "hostname_maps_to_specialist"
  out=$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/scripts/lib'); from team_formation import propose_team; t=propose_team('availability','low','nlk8s-ctrl01'); print(','.join(a['agent'] for a in t['agents']))")
  assert_contains "$out" "k8s-diagnostician" "no k8s-diagnostician for k8s ctrl01"
end_test

# ─── T6 hostname maps to cisco-asa-specialist for fw01 ─────────────────────
start_test "hostname_maps_to_asa"
  out=$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/scripts/lib'); from team_formation import propose_team; t=propose_team('availability','low','gr-fw01'); print(','.join(a['agent'] for a in t['agents']))")
  assert_contains "$out" "cisco-asa-specialist" "no asa specialist for fw01"
end_test

# ─── T7 dev category gets code-explorer not triage-researcher ──────────────
start_test "dev_category_gets_code_explorer"
  out=$(python3 -c "import sys; sys.path.insert(0, '$REPO_ROOT/scripts/lib'); from team_formation import propose_team; t=propose_team('dev','low'); print(','.join(a['agent'] for a in t['agents']))")
  assert_contains "$out" "code-explorer" "no code-explorer in dev"
  assert_not_contains "$out" "triage-researcher" "triage in dev session"
end_test

# ─── T8 result is JSON-serializable (no NamedTuple leaks) ──────────────────
start_test "result_is_json_serializable"
  out=$(python3 -c "import sys, json; sys.path.insert(0, '$REPO_ROOT/scripts/lib'); from team_formation import propose_team; print(json.dumps(propose_team('storage','mixed','gr-pve02')))")
  if [ -z "$out" ] || [ "${out:0:1}" != "{" ]; then
    fail_test "expected JSON object, got: ${out:0:80}"
  fi
end_test

# ─── T9 CLI runs without arguments error ───────────────────────────────────
start_test "cli_runs"
  rc=0
  out=$(python3 -m lib.team_formation --category availability --json 2>&1) || rc=$?
  cd "$REPO_ROOT/scripts" && rc2=0 && out2=$(python3 -m lib.team_formation --category availability --json 2>&1) || rc2=$?
  assert_eq 0 "$rc2" "CLI errored: $out2"
  assert_contains "$out2" '"agents"' "CLI did not emit agents"
end_test

# ─── T10 skill frontmatter is well-formed ─────────────────────────────────
start_test "skill_frontmatter_well_formed"
  if grep -q "^name: team-formation$" "$SKILL" && \
     grep -q "^version: 1\.0\.0$" "$SKILL" && \
     grep -q "^requires:$" "$SKILL"; then
    :
  else
    fail_test "skill missing required frontmatter fields"
  fi
end_test
