#!/usr/bin/env bash
# audit-skill-requires.sh — verify that every SKILL.md / agent .md declares
# a `requires.bins` + `requires.env` block, and that every entry there is
# satisfied on the host (bin: `command -v`, env: non-empty).
#
# IFRNLLEI01PRD-716 (Phase D of the agents-cli authoring-discipline uplift).
#
# Usage:
#   scripts/audit-skill-requires.sh            # text report, exit 0 iff all OK
#   scripts/audit-skill-requires.sh --json     # machine-readable JSON to stdout
#   scripts/audit-skill-requires.sh --quiet    # suppress pass lines
#
# Exit codes:
#   0 — all pass
#   1 — one or more gaps (bin missing, env missing, frontmatter malformed)
#   2 — fatal (YAML library unavailable)

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Source the repo .env so requires.env checks see the same vars an actual
# agent invocation does (e.g. GITLAB_TOKEN / YOUTRACK_API_TOKEN). Without
# this, cron-driven metric writes report false-positive "env unset" gaps
# (IFRNLLEI01PRD-827).
if [ -f "$REPO_ROOT/.env" ]; then set -a; . "$REPO_ROOT/.env"; set +a; fi

MODE="text"
QUIET=0
for arg in "$@"; do
  case "$arg" in
    --json) MODE="json" ;;
    --quiet) QUIET=1 ;;
    -h|--help)
      sed -n '2,15p' "$0" | sed 's/^# //'
      exit 0
      ;;
  esac
done

export REPO_ROOT
REPORT=$(python3 - "$MODE" "$QUIET" <<'PY'
import json, os, pathlib, shutil, sys, yaml
mode = sys.argv[1] if len(sys.argv) > 1 else "text"
quiet = (sys.argv[2] == "1") if len(sys.argv) > 2 else False
root = pathlib.Path(os.environ["REPO_ROOT"])
surfaces = [
    ("agent", sorted((root / ".claude/agents").glob("*.md"))),
    ("skill", sorted(p for p in (root / ".claude/skills").glob("*/SKILL.md"))),
]
rows = []
for kind, paths in surfaces:
    for p in paths:
        text = p.read_text()
        if not text.startswith("---\n"):
            rows.append(dict(kind=kind, name=p.stem, file=str(p.relative_to(root)),
                             status="FAIL", reason="missing frontmatter"))
            continue
        end = text.find("\n---\n", 4)
        if end < 0:
            rows.append(dict(kind=kind, name=p.stem, file=str(p.relative_to(root)),
                             status="FAIL", reason="unterminated frontmatter"))
            continue
        try:
            fm = yaml.safe_load(text[4:end])
        except yaml.YAMLError as e:
            rows.append(dict(kind=kind, name=p.stem, file=str(p.relative_to(root)),
                             status="FAIL", reason="invalid YAML: {}".format(e)))
            continue
        if not isinstance(fm, dict):
            rows.append(dict(kind=kind, name=p.stem, file=str(p.relative_to(root)),
                             status="FAIL", reason="frontmatter is not a dict"))
            continue
        name = fm.get("name", p.stem)
        base = dict(kind=kind, name=name, file=str(p.relative_to(root)))
        req = fm.get("requires")
        if not isinstance(req, dict) or "bins" not in req or "env" not in req:
            rows.append({**base, "status": "FAIL", "reason": "requires{bins,env} missing"})
            continue
        bins = req.get("bins") or []
        env_vars = req.get("env") or []
        issues = []
        for b in bins:
            if not shutil.which(b):
                issues.append("bin:{} missing".format(b))
        for e in env_vars:
            if not os.environ.get(e):
                issues.append("env:{} unset".format(e))
        if issues:
            rows.append({**base, "status": "FAIL", "reason": "; ".join(issues)})
        else:
            rows.append({**base, "status": "PASS",
                         "reason": "bins={} env={}".format(len(bins), len(env_vars))})

if mode == "json":
    print(json.dumps({"rows": rows}))
    sys.exit(0)

# Text mode
passed = sum(1 for r in rows if r["status"] == "PASS")
failed = len(rows) - passed
for r in rows:
    name_label = "{}/{}".format(r["kind"], r["name"])
    if r["status"] == "PASS":
        if not quiet:
            print("  [PASS] {:<40}  {}".format(name_label, r["reason"]))
    else:
        print("  [FAIL] {:<40}  {}".format(name_label, r["reason"]))
print()
print("audit-skill-requires: total={} pass={} fail={}".format(len(rows), passed, failed))
sys.exit(0 if failed == 0 else 1)
PY
)
rc=$?
echo "$REPORT"
exit $rc
