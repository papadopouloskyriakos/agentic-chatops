#!/usr/bin/env bash
# build-wiki-site.sh — assemble docs/wiki/README into a unified mkdocs source
# tree, then run `mkdocs build`. Idempotent; nukes wiki-site/ between runs.
#
# Output: wiki-site/site/ (static HTML + search index) — served by caddy on :8080.
#
# Usage:
#   scripts/build-wiki-site.sh           # full build
#   scripts/build-wiki-site.sh --serve   # dev mode (mkdocs serve, live-reload)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WIKI_VENV="${WIKI_VENV:-/home/app-user/.wiki-venv}"
SITE_SRC="$REPO_ROOT/wiki-site/site-src"
SITE_OUT="$REPO_ROOT/wiki-site/site"

cd "$REPO_ROOT"

# Prevent overlapping builds — systemd.path + operator-typed rebuild can
# race, leaving the tree half-populated. flock serialises runs; a second
# invocation waits up to 60s for the first to finish.
LOCK="/tmp/claude-gateway-wiki-build.lock"
exec 9>"$LOCK"
if ! flock -w 60 9; then
  echo "[build-wiki-site] another build still holding the lock after 60s — aborting" >&2
  exit 1
fi

# ── Drift monitor — regenerate derived content before assembling ──────────
# Every build re-emits the per-pattern pages + curriculum so a docs change
# flows into the published wiki + teacher curriculum without manual steps.
# Both scripts are idempotent on unchanged sources.
if [ -x scripts/generate-pattern-pages.py ]; then
  python3 scripts/generate-pattern-pages.py >/dev/null || {
    echo "[build-wiki-site] generate-pattern-pages.py failed; continuing with stale pages" >&2
  }
fi
if [ -x scripts/rebuild-curriculum.py ]; then
  python3 scripts/rebuild-curriculum.py >/dev/null || {
    echo "[build-wiki-site] rebuild-curriculum.py failed; continuing with stale curriculum" >&2
  }
fi

# Fresh source tree on every build — avoids stale files when sources disappear.
rm -rf "$SITE_SRC" "$SITE_OUT"
mkdir -p "$SITE_SRC"

# 1. Homepage — a curated landing page listing the major sections.
cat > "$SITE_SRC/index.md" <<'HOMEPAGE'
# Example Corp Wiki

Compiled knowledge base for the ChatOps / teacher-agent platform.
**Internal-only** — not public-facing.

## Sections

- **[docs/](docs/)** — runbooks, plans, audits, architecture references
- **[wiki/](wiki/)** — auto-compiled Karpathy-style articles (services, hosts, incidents, operations)
- **[memory/](memory/)** — operator memory (decisions, incidents, tuning notes)
- **[project-docs/](project-docs/)** — top-level specs + `.claude/` rules + agent definitions
- **[openclaw/](openclaw/)** — OpenClaw Tier-1 agent: SOUL.md + skill definitions
- **[Teacher curriculum](docs/plans/teacher-agent-implementation-plan/)** — the 21 Gulli patterns + foundation invariants

Use the search box (top right) to find any topic. Every heading has a
permalink anchor you can share.
HOMEPAGE

# 2. Copy `docs/` in (excluding binaries + large non-markdown assets)
if [ -d "$REPO_ROOT/docs" ]; then
  mkdir -p "$SITE_SRC/docs"
  # Only markdown + code/text — skip PDFs, images, drawio sources
  find "$REPO_ROOT/docs" -type f \
    \( -name '*.md' -o -name '*.yml' -o -name '*.yaml' -o -name '*.txt' \) \
    -not -path '*/node_modules/*' \
    | while read -r f; do
      rel="${f#$REPO_ROOT/docs/}"
      dest="$SITE_SRC/docs/$rel"
      mkdir -p "$(dirname "$dest")"
      cp "$f" "$dest"
    done
fi

# 3. Copy `wiki/` in
if [ -d "$REPO_ROOT/wiki" ]; then
  mkdir -p "$SITE_SRC/wiki"
  cp -r "$REPO_ROOT/wiki/." "$SITE_SRC/wiki/"
fi

# 4. README.extensive.md → site-src/project-docs/README.extensive.md.
#    (Top-level `README.md` conflicts with mkdocs's auto-generated
#    index.html; keeping it under project-docs also matches the path
#    wiki_articles indexes it under.)
if [ -f "$REPO_ROOT/README.extensive.md" ]; then
  mkdir -p "$SITE_SRC/project-docs"
  cp "$REPO_ROOT/README.extensive.md" "$SITE_SRC/project-docs/README.extensive.md"
fi

# 5. Operator memory — lives outside the repo at
#    ~/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory/.
#    wiki-compile.py indexes these rows into wiki_articles as `memory/*.md`,
#    so teacher-chat citations need to resolve to real URLs. Copy them into
#    the site under wiki-site/site-src/memory/.
MEMORY_SRC="$HOME/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory"
if [ -d "$MEMORY_SRC" ]; then
  mkdir -p "$SITE_SRC/memory"
  find "$MEMORY_SRC" -maxdepth 1 -type f -name '*.md' -print0 \
    | xargs -0 -I{} cp {} "$SITE_SRC/memory/"
fi

# 6. Project-level specs + .claude/ rules + agent definitions. The wiki is
#    internal-only so everything the operator might want to reference
#    should be browsable.
PROJECT_DOCS="$SITE_SRC/project-docs"
mkdir -p "$PROJECT_DOCS"
for f in CLAUDE.md KNOWN-ISSUES.md GR-INFRA-CHATOPS-SPEC.md \
         MAINTENANCE-COMPANION-SPEC.md QA_REPORT.md; do
  [ -f "$REPO_ROOT/$f" ] && cp "$REPO_ROOT/$f" "$PROJECT_DOCS/$f"
done
# .claude/ rules, agents, commands — stripped of the leading dot so mkdocs
# doesn't filter them out via its hidden-file rule.
if [ -d "$REPO_ROOT/.claude" ]; then
  mkdir -p "$PROJECT_DOCS/claude"
  find "$REPO_ROOT/.claude" -type f -name '*.md' -print0 \
    | while IFS= read -r -d '' f; do
        rel="${f#$REPO_ROOT/.claude/}"
        dest="$PROJECT_DOCS/claude/$rel"
        mkdir -p "$(dirname "$dest")"
        cp "$f" "$dest"
      done
fi

# 7. OpenClaw — SOUL.md + skill docs
if [ -d "$REPO_ROOT/openclaw" ]; then
  mkdir -p "$SITE_SRC/openclaw"
  find "$REPO_ROOT/openclaw" -type f -name '*.md' -print0 \
    | while IFS= read -r -d '' f; do
        rel="${f#$REPO_ROOT/openclaw/}"
        dest="$SITE_SRC/openclaw/$rel"
        mkdir -p "$(dirname "$dest")"
        cp "$f" "$dest"
      done
fi

# 5. Build
MKDOCS="$WIKI_VENV/bin/mkdocs"
[ -x "$MKDOCS" ] || { echo "mkdocs not found at $MKDOCS — run: python3 -m venv $WIKI_VENV && $WIKI_VENV/bin/pip install mkdocs-material" >&2; exit 1; }

if [ "${1:-}" = "--serve" ]; then
  exec "$MKDOCS" serve --dev-addr 127.0.0.1:8000
fi

"$MKDOCS" build --strict 2>&1 | tail -20 || {
  echo "build failed (strict mode); retrying without --strict so we at least ship something" >&2
  "$MKDOCS" build
}

ARTICLE_COUNT=$(find "$SITE_OUT" -name "index.html" | wc -l)
echo "built $ARTICLE_COUNT pages → $SITE_OUT"
