#!/usr/bin/env bash
# audit-skill-versions.sh — IFRNLLEI01PRD-712 governance followup.
#
# Advisory audit that surfaces "body-changed-without-version-bump" cases
# across all SKILL.md / agent .md files. Implements the stale-skill
# detection rule from docs/runbooks/skill-versioning.md.
#
# Usage:
#   scripts/audit-skill-versions.sh            # text report
#   scripts/audit-skill-versions.sh --json     # machine-readable
#   scripts/audit-skill-versions.sh --strict   # exit 1 on any stale finding
#                                               # (default: exit 0 — advisory)
#
# Algorithm:
#   For each .claude/{agents,skills}/**/*.md with frontmatter:
#     1. Read the current `version:` value.
#     2. Walk `git log --follow` to find the most recent commit where
#        `version:` was *added or modified* in this file's frontmatter.
#     3. Compare the file body at that "last-bump" commit vs the body at HEAD.
#     4. If body changed but version didn't → flag VERSION_STALE.

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="text"
STRICT=0
for arg in "$@"; do
  case "$arg" in
    --json)   MODE="json" ;;
    --strict) STRICT=1 ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# //'
      exit 0
      ;;
  esac
done

export REPO_ROOT
REPORT=$(python3 - "$MODE" <<'PY'
import hashlib, json, os, pathlib, re, subprocess, sys

mode = sys.argv[1] if len(sys.argv) > 1 else "text"
root = pathlib.Path(os.environ["REPO_ROOT"])
VERSION_RE = re.compile(r'^version:\s*([0-9A-Za-z.+\-]+)\s*$', re.MULTILINE)

def parse_frontmatter(text):
    """Return (frontmatter_str, body_str, version_str) or (None, None, None)."""
    if not text.startswith("---\n"):
        return (None, None, None)
    end = text.find("\n---\n", 4)
    if end < 0:
        return (None, None, None)
    fm = text[4:end]
    body = text[end + 5:]
    m = VERSION_RE.search(fm)
    version = m.group(1) if m else None
    return (fm, body, version)


def git_blob_at(path, commit):
    """Return the file content at the given commit, or None if git errors."""
    try:
        out = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout
    except subprocess.CalledProcessError:
        return None


def last_version_bump_commit(path):
    """Walk git log --follow; return the most recent commit where
    `version:` was added or changed in the frontmatter."""
    try:
        log = subprocess.run(
            ["git", "log", "--follow", "-L",
             r"/^version:/,+1:" + str(path),
             "--format=%H", "--pretty=format:"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Fallback: any commit that touched the file
        try:
            log = subprocess.run(
                ["git", "log", "--follow", "--format=%H", "-n", "50", "--", str(path)],
                capture_output=True, text=True, check=True, timeout=10,
            )
        except Exception:
            return None
    commits = [ln.strip() for ln in log.stdout.splitlines() if len(ln.strip()) == 40]
    # Most recent first (git log default order); pick the first commit where
    # current-version != parent-version, or fallback to the earliest commit
    # that added the file.
    for commit in commits:
        parent = commit + "^"
        here = git_blob_at(path, commit)
        there = git_blob_at(path, parent)
        if here is None:
            continue
        _, _, v_here = parse_frontmatter(here)
        _, _, v_there = parse_frontmatter(there or "")
        if v_here != v_there:
            return commit
    # If nothing found with a bump, return the oldest commit that touched the file
    return commits[-1] if commits else None


surfaces = (
    list((root / ".claude/agents").glob("*.md")) +
    list((root / ".claude/skills").glob("*/SKILL.md"))
)

rows = []
for p in sorted(surfaces):
    rel = str(p.relative_to(root))
    current = p.read_text()
    _, body_now, v_now = parse_frontmatter(current)
    if v_now is None:
        rows.append({"file": rel, "status": "SKIP", "reason": "no version frontmatter"})
        continue
    bump_commit = last_version_bump_commit(rel)
    if bump_commit is None:
        rows.append({"file": rel, "status": "INFO", "reason": "no git history (new file?)",
                     "version": v_now})
        continue
    at_bump = git_blob_at(rel, bump_commit) or ""
    _, body_bump, v_bump = parse_frontmatter(at_bump)
    body_hash_bump = hashlib.sha256((body_bump or "").encode()).hexdigest()[:12]
    body_hash_now = hashlib.sha256((body_now or "").encode()).hexdigest()[:12]
    if body_hash_bump == body_hash_now:
        rows.append({"file": rel, "status": "FRESH", "version": v_now,
                     "reason": f"body unchanged since bump ({bump_commit[:7]})"})
    else:
        rows.append({"file": rel, "status": "VERSION_STALE", "version": v_now,
                     "last_bump_commit": bump_commit[:7],
                     "reason": f"body changed since version {v_now} was set "
                               f"(bump blob {body_hash_bump} → now {body_hash_now})"})

stale = sum(1 for r in rows if r["status"] == "VERSION_STALE")

if mode == "json":
    print(json.dumps({"rows": rows, "stale_count": stale, "total": len(rows)}))
    sys.exit(0)

# text
w = 40
for r in rows:
    icon = {"FRESH": "[OK]  ", "VERSION_STALE": "[WARN]",
            "INFO": "[INFO]", "SKIP": "[SKIP]"}.get(r["status"], "[?]   ")
    print(f'  {icon} {r["file"]:<{w}}  {r.get("version","?"):<8}  {r["reason"]}')
print()
print(f'audit-skill-versions: total={len(rows)} fresh={sum(1 for r in rows if r["status"]=="FRESH")} stale={stale}')
sys.exit(0)
PY
)
rc=$?
echo "$REPORT"

if [ "$STRICT" = "1" ]; then
  # Check if there are any stale rows
  if echo "$REPORT" | grep -q '\[WARN\]' >/dev/null 2>&1; then
    echo "strict mode: stale findings present → exit 1" >&2
    exit 1
  fi
fi

exit $rc
