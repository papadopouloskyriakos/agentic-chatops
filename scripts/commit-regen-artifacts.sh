#!/usr/bin/env bash
# commit-regen-artifacts.sh — commit cron-regenerated tracked artifacts so the live working tree
# doesn't perpetually carry uncommitted regen churn (the "71 dirty files" fragility class: a naive
# `git stash` / `git reset` on the shared live checkout could sweep or lose regenerated state).
#
# WHY THIS EXISTS: wiki-compile.py, registry-seed/curate, interaction-graph.py, rebuild-curriculum.py,
# mine-failures-to-evals.py and the auto-refreshed docs rewrite tracked files in place on every cron
# cycle, but none of them commit — so the changes pile up between episodic doc commits. This script
# sweeps them into a reviewable MR on a fixed cadence.
#
# SAFETY PROPERTIES (do not weaken):
#   * Stages ONLY the explicit REGEN_PATHS below — NEVER scripts/*.py, memory/, .env, docs/plans/,
#     or anything a Claude session might be editing. Regeneration output only.
#   * Authors the commit in an ISOLATED git worktree off origin/main — the live checkout is never
#     switched, stashed, or reset (lesson: feedback_dont_disturb_foreign_repo_working_tree).
#   * main is protected (Maintainers-only); opens an MR by default. --auto-merge (root token) merges
#     then fast-forwards the live checkout so tree == origin/main.
#
# The path list is kept in sync with check-repo-deploy-drift.py's REGEN tuple + the auto-refreshed docs.
# Usage: commit-regen-artifacts.sh [--auto-merge] [--dry-run]
# Cronicle: weekly.
set -euo pipefail

REPO="${GATEWAY_REPO:-/app/claude-gateway}"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.net}"
PROJECT="${GITLAB_PROJECT:-30}"

DRY_RUN=0; AUTO_MERGE=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    --auto-merge) AUTO_MERGE=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

# MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824): committing a branch + opening/merging an MR to
# main is external actuation. In shadow, log the intent and skip the whole regen-commit-MR-merge.
# shellcheck source=scripts/lib/suppression-gates.sh
source "$(dirname "$0")/lib/suppression-gates.sh"
mutation_shadow && { mutation_shadow_log "regen-artifacts-commit" "would regenerate + commit + open/merge MR to main"; echo "MUTATIONS=OFF shadow: logged, not run"; exit 0; }

# Regenerated tracked artifacts. wiki/ is a directory (whole compiled knowledge base).
REGEN_PATHS=(
  "wiki"
  "config/interaction-graph.json"
  "config/component-registry.json"
  "config/orchestration-scorecard.json"
  "config/curriculum.json"
  "docs/crontab-reference.md"
  "docs/host-blast-radius.md"
  "docs/network-addresses.md"
  "docs/rag-architecture-current.md"
  "docs/rag-metrics-reference.md"
  "scripts/eval-sets/discovery.json"
)

STAMP="$(date -u +%Y%m%d)"                                   # for commit message / MR title
BR="chore/regen-artifacts-$(date -u +%Y%m%d-%H%M%S)"        # unique per run; remove_source_branch cleans on merge

cd "$REPO"
git fetch origin main -q

# Isolated worktree off origin/main — live checkout stays on main, untouched.
WT="$(mktemp -d -t regen-commit.XXXXXX)"
trap 'git worktree remove --force "$WT" 2>/dev/null || true; git branch -D "$BR" 2>/dev/null || true; rm -rf "$WT"' EXIT
git worktree add -b "$BR" "$WT" origin/main -q

# Copy current regen content from the live tree into the worktree, then stage ONLY those paths.
for p in "${REGEN_PATHS[@]}"; do
  if [ -e "$REPO/$p" ]; then
    mkdir -p "$WT/$(dirname "$p")"
    if [ -d "$REPO/$p" ]; then
      rm -rf "$WT/$p"; cp -a "$REPO/$p" "$WT/$p"   # rm-first so removed wiki files propagate (rsync absent on host)
    else
      cp -a "$REPO/$p" "$WT/$p"
    fi
  fi
done
git -C "$WT" add -- "${REGEN_PATHS[@]}"

if git -C "$WT" diff --cached --quiet; then
  echo "commit-regen-artifacts: no regen changes vs origin/main; nothing to commit."
  exit 0
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "commit-regen-artifacts [dry-run]: would commit on $BR:"
  git -C "$WT" diff --cached --stat
  exit 0
fi

git -C "$WT" commit -q -m "chore(regen): refresh cron-regenerated artifacts ($STAMP)

Auto-committed by scripts/commit-regen-artifacts.sh.
Scoped to wiki/ + auto-refreshed docs + regen config + eval-sets only.
Authored in an isolated worktree off origin/main (live checkout untouched).

Co-Authored-By: Claude <noreply@anthropic.com>"
git -C "$WT" push -u origin "$BR" -q

# Open MR to protected main. Token from .env (gitignored, host-local).
TOK="$(grep -hiE '^GITLAB_TOKEN=' "$REPO/.env" 2>/dev/null | head -1 | cut -d= -f2- || true)"
if [ -z "$TOK" ]; then
  echo "commit-regen-artifacts: pushed $BR but GITLAB_TOKEN absent — open MR manually." >&2
  exit 0
fi
MR_JSON="$(curl -sk --fail --max-time 20 -H "PRIVATE-TOKEN: $TOK" \
  --data-urlencode "source_branch=$BR" \
  --data-urlencode "target_branch=main" \
  --data-urlencode "title=chore(regen): refresh cron-regenerated artifacts ($STAMP)" \
  --data-urlencode "description=Auto-generated weekly sweep of cron-regenerated artifacts (wiki/docs/config/eval-sets). No code changes. Authored in an isolated worktree." \
  --data-urlencode "remove_source_branch=true" \
  "$GITLAB_URL/api/v4/projects/$PROJECT/merge_requests")" || { echo "MR open failed" >&2; exit 1; }
MR_IID="$(printf '%s' "$MR_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin).get('iid',''))")"
MR_URL="$(printf '%s' "$MR_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin).get('web_url',''))")"
echo "commit-regen-artifacts: MR !$MR_IID opened: $MR_URL"

if [ "$AUTO_MERGE" = 1 ] && [ -n "$MR_IID" ]; then
  curl -sk --fail --max-time 20 -X PUT -H "PRIVATE-TOKEN: $TOK" \
    "$GITLAB_URL/api/v4/projects/$PROJECT/merge_requests/$MR_IID/merge" >/dev/null \
    && git -C "$REPO" fetch origin main -q \
    && git -C "$REPO" merge --ff-only origin/main -q \
    && echo "commit-regen-artifacts: auto-merged; live checkout advanced to origin/main (clean tree)." \
    || echo "commit-regen-artifacts: auto-merge/pull non-fatal — live checkout will catch up on next ff-only." >&2
fi
