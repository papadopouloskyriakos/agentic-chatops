#!/usr/bin/env bash
# Harness² harness-tree validator (scripts/lib/harness_tree.py, vendored from
# google-research/harness2 core/tree.py @ 1cfe254 and adapted for the Claude Code
# surface) + its CLI scripts/validate-harness-tree.py.
#
# Negative cases run against a throw-away fixture tree built in $TMP, never the
# real repo. T10/T11 run the CLI on the real repo and PASS on exit 0 OR 1 (the
# live harness may legitimately carry problems — they are printed to stderr as
# a finding, not a test failure).
# QA_SUITE_TIMEOUT: 120
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="harness-tree-validator"

LIB="$REPO_ROOT/scripts/lib"
CLI="$REPO_ROOT/scripts/validate-harness-tree.py"
export HT_LIB="$LIB"

TMP="$(mktemp -d "${TMPDIR:-/tmp}/qa-harness-tree.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

# ─── fixture + helpers ──────────────────────────────────────────────────────

# make_fixture <dir> — a minimal VALID Claude Code harness tree.
make_fixture() {
  local d="$1"
  mkdir -p "$d/.claude/rules" "$d/.claude/skills/demo-skill" "$d/.claude/agents" "$d/scripts"
  cat > "$d/CLAUDE.md" <<'EOF'
# Fixture harness

When an alert fires, load the `/demo-skill` skill. Helpers: `python3 scripts/hello.py`.
EOF
  printf '# rule one\n\nAlways use full hostnames.\n' > "$d/.claude/rules/r1.md"
  cat > "$d/.claude/skills/demo-skill/SKILL.md" <<'EOF'
---
name: demo-skill
description: Demo skill for the validator fixture.
version: 1.0.0
requires:
  bins: []
  env: []
---

## Demo

Run `bash scripts/hello.sh` then `python3 scripts/hello.py`.
EOF
  cat > "$d/.claude/agents/demo-agent.md" <<'EOF'
---
name: demo-agent
description: >
  Demo sub-agent for the validator fixture. It returns a structured summary.
tools: Read, Grep
version: 1.0.0
---

You are a demo agent.
EOF
  printf 'print("hello")\n' > "$d/scripts/hello.py"
  printf '#!/usr/bin/env bash\necho hello\n' > "$d/scripts/hello.sh"
  cat > "$d/.claude/settings.json" <<'EOF'
{
  "permissions": { "allow": ["Bash(ls:*)"] },
  "hooks": {
    "Stop": [
      { "matcher": "", "hooks": [ { "type": "command", "command": "echo stop" } ] }
    ]
  }
}
EOF
}

# add_skill <dir> <name> [with_description=1] — a well-formed extra skill.
add_skill() {
  local d="$1" name="$2" with_desc="${3:-1}"
  mkdir -p "$d/.claude/skills/$name"
  {
    echo '---'
    echo "name: $name"
    [ "$with_desc" = "1" ] && echo "description: Extra skill $name."
    echo 'version: 1.0.0'
    echo '---'
    echo
    echo "## $name"
  } > "$d/.claude/skills/$name/SKILL.md"
}

# ht_validate <dir> — prints "OK <census-json>" (rc 0) or "PROBLEMS <joined>" (rc 1).
ht_validate() {
  python3 - "$1" <<'PY'
import json, os, sys
sys.path.insert(0, os.environ["HT_LIB"])
import harness_tree as ht
root = sys.argv[1]
surface = ht.claude_code_surface(root)
tree = ht.read_tree(surface, root)
try:
    c = ht.validate(surface, tree)
    print("OK " + json.dumps(c))
    sys.exit(0)
except ValueError as e:
    print("PROBLEMS " + str(e))
    sys.exit(1)
PY
}

# ─── T1 module imports ──────────────────────────────────────────────────────
start_test "import_ok"
  out=$(python3 -c "import sys; sys.path.insert(0, '$LIB'); import harness_tree as ht; print(ht.CLAUDE_CODE_SURFACE.name, ht.CLAUDE_CODE_SURFACE.skill_dir, ht.CLAUDE_CODE_SURFACE.hooks_file)" 2>&1)
  assert_eq "claude_code .claude/skills .claude/settings.json" "$out" "import / surface constants"
end_test

# ─── T2 valid minimal tree passes with a census ────────────────────────────
start_test "valid_minimal_tree_passes"
  F="$TMP/t2"; make_fixture "$F"
  out=$(ht_validate "$F" 2>&1); rc=$?
  assert_eq 0 "$rc" "validate rc (out=${out:0:300})"
  assert_contains "$out" "OK " "census line"
  assert_contains "$out" '"skills": 1' "skills count"
  assert_contains "$out" '"sub_agents": 1' "sub_agents count"
  assert_contains "$out" '"scripts": 2' "scripts count (hello.py + hello.sh)"
  assert_contains "$out" '"hooks": 1' "hooks count"
end_test

# ─── T3 untriggered skill is reported by name ──────────────────────────────
start_test "untriggered_skill_reported"
  F="$TMP/t3"; make_fixture "$F"; add_skill "$F" "orphan-skill"
  out=$(ht_validate "$F" 2>&1); rc=$?
  assert_eq 1 "$rc" "validate rc"
  assert_contains "$out" "skill 'orphan-skill' is never named in the always-on text" "untriggered wording"
  assert_contains "$out" '/orphan-skill' "trigger hint names the skill"
  assert_not_contains "$out" "skill 'demo-skill' is never named" "triggered skill not reported"
end_test

# ─── T4 skill without description is reported ──────────────────────────────
start_test "skill_missing_description_reported"
  F="$TMP/t4"; make_fixture "$F"; add_skill "$F" "nodesc-skill" 0
  printf '\nAlso load `/nodesc-skill` when asked.\n' >> "$F/CLAUDE.md"
  out=$(ht_validate "$F" 2>&1); rc=$?
  assert_eq 1 "$rc" "validate rc"
  assert_contains "$out" ".claude/skills/nodesc-skill/SKILL.md needs a \`description:\`" "description wording"
  assert_not_contains "$out" "skill 'nodesc-skill' is never named" "it IS triggered, so only the description problem"
end_test

# ─── T5 referenced-but-missing script is reported ──────────────────────────
start_test "missing_referenced_script_reported"
  F="$TMP/t5"; make_fixture "$F"
  printf '\nMaintenance: run `bash scripts/ghost.sh` first.\n' >> "$F/CLAUDE.md"
  out=$(ht_validate "$F" 2>&1); rc=$?
  assert_eq 1 "$rc" "validate rc"
  assert_contains "$out" "CLAUDE.md invokes \`scripts/ghost.sh\` but that file is not in the harness" "missing script wording"
  assert_not_contains "$out" "scripts/hello.sh\` but that file" "shipped script not reported"
end_test

# ─── T6 script that does not compile is reported ───────────────────────────
start_test "non_compiling_script_reported"
  F="$TMP/t6"; make_fixture "$F"
  printf 'def broken(:\n    pass\n' > "$F/scripts/broken.py"
  out=$(ht_validate "$F" 2>&1); rc=$?
  assert_eq 1 "$rc" "validate rc"
  assert_contains "$out" "scripts/broken.py does not compile: SyntaxError" "compile wording"
end_test

# ─── T7 hooks json with an unknown event is reported ───────────────────────
start_test "hooks_unknown_event_reported"
  F="$TMP/t7"; make_fixture "$F"
  cat > "$F/.claude/settings.json" <<'EOF'
{ "hooks": { "BogusEvent": [ { "hooks": [ { "type": "command", "command": "echo x" } ] } ] } }
EOF
  out=$(ht_validate "$F" 2>&1); rc=$?
  assert_eq 1 "$rc" "validate rc"
  assert_contains "$out" ".claude/settings.json: unknown event 'BogusEvent'" "unknown event wording"
  assert_contains "$out" "PreToolUse" "lists the dispatched events"
end_test

# ─── T8 always-on text over the cap is reported ────────────────────────────
start_test "always_on_over_cap_reported"
  F="$TMP/t8"; make_fixture "$F"
  out=$(ALWAYS_ON_MAX=60 ht_validate "$F" 2>&1); rc=$?
  assert_eq 1 "$rc" "validate rc"
  assert_contains "$out" "always-on content is" "cap wording"
  assert_contains "$out" "over the 60 cap" "cap value from ALWAYS_ON_MAX"
  assert_contains "$out" "loaded into every session" "cap reason"
end_test

# ─── T9 path escape rejected by normalize_rel ──────────────────────────────
start_test "normalize_rel_rejects_escape"
  out=$(python3 - <<PY
import sys
sys.path.insert(0, "$LIB")
import harness_tree as ht
for bad in ("../x", "/etc/passwd", "a/../../x"):
    try:
        ht.normalize_rel(bad); print("ACCEPTED", bad)
    except ValueError as e:
        print("REJECTED", bad)
print("NORM", ht.normalize_rel("./scripts/x.py"))
print("ALLOWED", ht.is_allowed(ht.CLAUDE_CODE_SURFACE, "../CLAUDE.md"))
PY
)
  assert_contains "$out" "REJECTED ../x" "../x rejected"
  assert_contains "$out" "REJECTED /etc/passwd" "absolute rejected"
  assert_contains "$out" "REJECTED a/../../x" "nested .. rejected"
  assert_not_contains "$out" "ACCEPTED" "nothing escaped"
  assert_contains "$out" "NORM scripts/x.py" "./ prefix stripped"
  assert_contains "$out" "ALLOWED False" "is_allowed never raises on an escape"
end_test

# ─── T10 the REAL repo tree validates via the CLI (0 or 1 both PASS) ───────
start_test "real_repo_cli_verdict"
  out=$(cd "$REPO_ROOT" && python3 "$CLI" --repo "$REPO_ROOT" --runner-build-prompt workflows/claude-gateway-runner.json 2>&1); rc=$?
  if [ "$rc" = "0" ]; then
    assert_contains "$out" "HARNESS TREE: OK" "verdict line"
    printf '  [harness-tree] real repo: OK (rc=0)\n' >&2
  elif [ "$rc" = "1" ]; then
    assert_contains "$out" "HARNESS TREE: PROBLEMS" "verdict line"
    printf '  [harness-tree] real repo: PROBLEMS (rc=1) — finding, not a test failure:\n%s\n' "$out" >&2
  else
    fail_test "CLI rc=$rc (expected 0 or 1): ${out:0:300}"
  fi
  assert_contains "$out" "always-on text:" "byte total line"
  assert_contains "$out" "census:" "census line"
  assert_contains "$out" "Build Prompt" "Build Prompt counted as trigger text"
end_test

# ─── T11 --json output parses ──────────────────────────────────────────────
start_test "json_output_parses"
  out=$(cd "$REPO_ROOT" && python3 "$CLI" --repo "$REPO_ROOT" --runner-build-prompt workflows/claude-gateway-runner.json --json 2>/dev/null); rc=$?
  parsed=$(printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
keys = ["ok", "problems", "census", "always_on_bytes", "warn", "max_bytes", "always_on_files"]
missing = [k for k in keys if k not in d]
print("MISSING", missing) if missing else print("KEYS ok", "ok=%s problems=%d bytes=%d" % (d["ok"], len(d["problems"]), d["always_on_bytes"]))
print("CONSISTENT" if d["ok"] == (len(d["problems"]) == 0) else "INCONSISTENT")
' 2>&1)
  assert_contains "$parsed" "KEYS ok" "json keys present (rc=$rc; ${parsed:0:200})"
  assert_contains "$parsed" "CONSISTENT" "ok flag matches problems list"
  if [ "$rc" != "0" ] && [ "$rc" != "1" ]; then fail_test "CLI --json rc=$rc"; fi
end_test

# ─── T12 CLI validates config/dispatched-session-settings.json too ─────────
start_test "cli_checks_dispatched_session_settings"
  F="$TMP/t12"; make_fixture "$F"; mkdir -p "$F/config"
  cat > "$F/config/dispatched-session-settings.json" <<'EOF'
{ "_comment": "fixture", "hooks": { "PreToolUse": [ { "matcher": "Bash", "hooks": [ { "type": "command", "command": "" } ] } ] } }
EOF
  assert_exit_code 1 python3 "$CLI" --repo "$F"
  assert_contains "$_qa_last_stdout" "HARNESS TREE: PROBLEMS" "verdict"
  assert_contains "$_qa_last_stdout" "config/dispatched-session-settings.json: PreToolUse[0] has an empty \`command\`" "problem names the dispatched file"
  # and a clean one passes through the CLI with exit 0
  cat > "$F/config/dispatched-session-settings.json" <<'EOF'
{ "_comment": "fixture", "hooks": { "PreToolUse": [ { "matcher": "Bash", "hooks": [ { "type": "command", "command": "echo ok" } ] } ] } }
EOF
  assert_exit_code 0 python3 "$CLI" --repo "$F"
  assert_contains "$_qa_last_stdout" "HARNESS TREE: OK" "clean verdict"
  assert_contains "$_qa_last_stdout" "config/dispatched-session-settings.json" "reports the file was checked"
end_test

# ─── T13 Build Prompt jsCode counts as trigger text ────────────────────────
start_test "runner_build_prompt_counts_as_trigger"
  F="$TMP/t13"; make_fixture "$F"; add_skill "$F" "prompt-only-skill"
  cat > "$F/runner.json" <<'EOF'
{ "nodes": [ { "name": "Other", "parameters": {} },
             { "name": "Build Prompt", "type": "n8n-nodes-base.code",
               "parameters": { "jsCode": "prompt += 'consult the `/prompt-only-skill` skill';" } } ] }
EOF
  assert_exit_code 1 python3 "$CLI" --repo "$F"
  assert_contains "$_qa_last_stdout" "skill 'prompt-only-skill' is never named" "untriggered without the Build Prompt"
  assert_exit_code 0 python3 "$CLI" --repo "$F" --runner-build-prompt "$F/runner.json"
  assert_contains "$_qa_last_stdout" "HARNESS TREE: OK" "triggered via Build Prompt jsCode"
  # --extra-always-on works the same way
  printf 'see `prompt-only-skill`\n' > "$F/extra.txt"
  assert_exit_code 0 python3 "$CLI" --repo "$F" --extra-always-on "$F/extra.txt"
  # a workflow without the node is a usage error
  printf '{"nodes": []}\n' > "$F/empty.json"
  assert_exit_code 2 python3 "$CLI" --repo "$F" --runner-build-prompt "$F/empty.json"
end_test

# ─── T14 sub-agent frontmatter rules (flat .claude/agents/<n>.md) ──────────
start_test "subagent_frontmatter_rules"
  F="$TMP/t14"; make_fixture "$F"
  printf -- '---\nname: wrong-name\ndescription: x\n---\nbody\n' > "$F/.claude/agents/other-agent.md"
  out=$(ht_validate "$F" 2>&1); rc=$?
  assert_eq 1 "$rc" "validate rc"
  assert_contains "$out" ".claude/agents/other-agent.md needs frontmatter \`name: other-agent\`" "name must match stem"
  assert_contains "$out" ".claude/agents/other-agent.md needs a semver \`version:\`" "version required"
  assert_not_contains "$out" "demo-agent.md needs" "well-formed agent passes"
end_test
