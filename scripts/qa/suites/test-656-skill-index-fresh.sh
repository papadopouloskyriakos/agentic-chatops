#!/usr/bin/env bash
# IFRNLLEI01PRD-715 — drift guard for the auto-generated skill/agent/command
# index at docs/skills-index.md. Re-renders from .claude/**/*.md frontmatter
# and fails red on any divergence.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="656-skill-index-fresh"

# ─── T1 committed index exists ──────────────────────────────────────────
start_test "committed_skills_index_exists"
  if [ -f "$REPO_ROOT/docs/skills-index.md" ]; then
    :
  else
    fail_test "docs/skills-index.md is missing — run: python3 scripts/render-skill-index.py docs/skills-index.md"
  fi
end_test

# ─── T2 renderer executes cleanly ───────────────────────────────────────
start_test "renderer_runs_without_error"
  tmp_out=$(mktemp)
  if python3 "$REPO_ROOT/scripts/render-skill-index.py" "$tmp_out" >/dev/null 2>&1; then
    :
  else
    fail_test "scripts/render-skill-index.py errored"
  fi
  rm -f "$tmp_out"
end_test

# ─── T3 committed matches fresh render ──────────────────────────────────
start_test "committed_matches_fresh_render"
  tmp_out=$(mktemp)
  python3 "$REPO_ROOT/scripts/render-skill-index.py" "$tmp_out" >/dev/null 2>&1 || true
  if diff -q "$REPO_ROOT/docs/skills-index.md" "$tmp_out" >/dev/null 2>&1; then
    :
  else
    diff_head=$(diff -u "$REPO_ROOT/docs/skills-index.md" "$tmp_out" | head -20 | tr '\n' '|')
    fail_test "docs/skills-index.md is stale — re-render: python3 scripts/render-skill-index.py docs/skills-index.md ($diff_head)"
  fi
  rm -f "$tmp_out"
end_test

# ─── T4 frontmatter completeness: every SKILL.md/agent has version + requires ─
start_test "frontmatter_carries_version_and_requires"
  missing=$(cd "$REPO_ROOT" && python3 <<'PY'
import pathlib, yaml
root = pathlib.Path(".")
bad = []
for p in list((root / ".claude/agents").glob("*.md")) + list((root / ".claude/skills").glob("*/SKILL.md")):
    t = p.read_text()
    if not t.startswith("---\n"):
        continue
    end = t.find("\n---\n", 4)
    if end < 0:
        continue
    try:
        fm = yaml.safe_load(t[4:end])
    except yaml.YAMLError:
        bad.append(f"{p} (invalid YAML)")
        continue
    if not isinstance(fm, dict):
        continue
    if "version" not in fm:
        bad.append(f"{p} (missing: version)")
    if "requires" not in fm:
        bad.append(f"{p} (missing: requires)")
    else:
        req = fm.get("requires")
        if not isinstance(req, dict) or "bins" not in req or "env" not in req:
            bad.append(f"{p} (requires missing bins/env)")
print(";".join(bad))
PY
)
  if [ -z "$missing" ]; then
    :
  else
    fail_test "frontmatter gaps: $missing"
  fi
end_test

# ─── T5 deterministic render ────────────────────────────────────────────
start_test "render_is_deterministic"
  tmp1=$(mktemp)
  tmp2=$(mktemp)
  python3 "$REPO_ROOT/scripts/render-skill-index.py" "$tmp1" >/dev/null 2>&1 || true
  python3 "$REPO_ROOT/scripts/render-skill-index.py" "$tmp2" >/dev/null 2>&1 || true
  if diff -q "$tmp1" "$tmp2" >/dev/null 2>&1; then
    :
  else
    fail_test "renderer output is non-deterministic (sort order / timestamp / random?)"
  fi
  rm -f "$tmp1" "$tmp2"
end_test

# ─── T6 YAML is still parseable after every frontmatter edit ────────────
start_test "every_frontmatter_is_valid_yaml"
  bad=$(cd "$REPO_ROOT" && python3 <<'PY'
import pathlib, yaml
root = pathlib.Path(".")
bad = []
for p in (list((root / ".claude/agents").glob("*.md")) +
         list((root / ".claude/skills").glob("*/SKILL.md")) +
         list((root / ".claude/commands").glob("*.md"))):
    t = p.read_text()
    if not t.startswith("---\n"):
        continue
    end = t.find("\n---\n", 4)
    if end < 0:
        continue
    try:
        yaml.safe_load(t[4:end])
    except yaml.YAMLError as e:
        bad.append(f"{p}: {e}")
print(";".join(bad))
PY
)
  if [ -z "$bad" ]; then
    :
  else
    fail_test "invalid YAML frontmatter: $bad"
  fi
end_test
