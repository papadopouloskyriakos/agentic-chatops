"""Map a repo-relative source path (+ optional heading section name) to a
public wiki URL served by the mkdocs-material build at
https://wiki.example.net/.

Contract:
  wiki_url("docs/agentic-patterns-audit.md", "Summary Scorecard (updated 2026-03-29)")
  → "https://wiki.example.net/docs/agentic-patterns-audit/#summary-scorecard-updated-2026-03-29"

  wiki_url("wiki/services/grafana.md", "")
  → "https://wiki.example.net/wiki/services/grafana/"

  wiki_url("README.extensive.md", "Compiled Knowledge Base")
  → "https://wiki.example.net/README/#compiled-knowledge-base"

  wiki_url("/var/outside/foo.md", "whatever")
  → None (not served by the wiki)

The slug algorithm MUST match the one mkdocs applies at build time
(pymdownx.slugs.slugify with case=lower). See mkdocs.yml for the exact
config. Verified against live HTML output: "Reasoning Techniques (B -> A)"
→ "reasoning-techniques-b---a" (three dashes from "b - a" where each
whitespace run becomes a separate "-").
"""
from __future__ import annotations

import os
REDACTED_a7b84d63
import unicodedata
from typing import Optional


DEFAULT_BASE = "https://wiki.example.net"


_INVALID_SLUG_CHAR = re.compile(r"[^\w\- ]", re.UNICODE)


def slugify(text: str) -> str:
    """Match mkdocs-material's `pymdownx.slugs.slugify(case=lower)` byte-for-byte.

    The pymdownx algorithm (verified against installed 10.21.2):
      1. Strip HTML tags (skipped — our input is never HTML)
      2. `unicodedata.normalize('NFC', text).strip()`  -- NFC, not NFKD
      3. lowercase
      4. remove any char not matching `[\\w\\- ]` (keep word chars, ASCII
         hyphen, and LITERAL SPACE only — not `\\s`)
      5. replace each literal " " with the separator (no collapse — two
         spaces become two dashes)
      6. no trailing strip of dashes
    """
    text = unicodedata.normalize("NFC", text).strip()
    text = text.lower()
    text = _INVALID_SLUG_CHAR.sub("", text)
    text = text.replace(" ", "-")
    return text


# Top-level directories below `wiki/` that mkdocs serves. The
# `wiki_articles` SQLite table stores these WITHOUT the `wiki/` prefix
# (e.g. `hosts/gr-fw01.md`), so the normalizer re-adds it when it
# recognises one of these as a leading segment.
_WIKI_SUBDIRS = {
    "decisions", "health", "hosts", "incidents", "lab",
    "operations", "patterns", "services", "topology",
}


def _normalize_path(source_path: str) -> Optional[str]:
    """Return the mkdocs page slug path (no .md, no leading/trailing slash)
    when the source is inside the wiki, or None.

    Strips any `#...` fragment upfront so callers that pass composite
    strings like `docs/foo.md#section-slug` (the wiki_articles table stores
    section-scoped rows this way) don't produce malformed URLs.

    Handles the various wiki_articles path conventions:
      - `docs/foo.md` → docs/foo
      - `wiki/foo.md` → wiki/foo
      - `memory/foo.md` → memory/foo
      - bare `hosts/…`, `services/…` (no wiki/ prefix) → wiki/hosts/…
      - `project-docs/CLAUDE.md` → project-docs/CLAUDE
      - `project-docs/.claude/rules/X.md` → project-docs/claude/rules/X
        (leading dot dropped; mkdocs hides dotfiles)
      - `openclaw/SOUL.md` → openclaw/SOUL
    """
    if not source_path:
        return None
    p = source_path.strip().lstrip("./")
    if "#" in p:
        p = p.split("#", 1)[0]
    if not p:
        return None
    # project-docs/.claude/... → project-docs/claude/... (mkdocs hides dotdirs)
    p = p.replace("/.claude/", "/claude/")
    # README.extensive.md lives at repo root but the build publishes it at
    # project-docs/README.extensive/ (keeping top-level README.md clear of
    # mkdocs's auto-generated index.html). Collapse every variant wiki-compile
    # might have indexed to that single canonical URL.
    if p in ("README.extensive.md", "README.md",
             "project-docs/README.extensive.md", "project-docs/README.md"):
        return "project-docs/README.extensive"
    if (p.startswith("docs/") or p.startswith("wiki/")
            or p.startswith("memory/") or p.startswith("project-docs/")
            or p.startswith("openclaw/")):
        return p[:-3] if p.endswith(".md") else p
    # Re-prefix `wiki/` when the path starts with a known wiki subdir.
    head = p.split("/", 1)[0]
    if head in _WIKI_SUBDIRS:
        p = "wiki/" + p
        return p[:-3] if p.endswith(".md") else p
    return None


def wiki_url(source_path: str, section: str = "",
             *, base: Optional[str] = None) -> Optional[str]:
    """Return the public wiki URL for this source + section, or None when
    the source isn't served by the wiki.

    The `base` arg overrides the default/env var; env `TEACHER_WIKI_BASE`
    wins over DEFAULT_BASE when `base` is None.
    """
    page = _normalize_path(source_path)
    if page is None:
        return None
    base_url = (base
                or os.environ.get("TEACHER_WIKI_BASE")
                or DEFAULT_BASE).rstrip("/")
    url = f"{base_url}/{page}/"
    if section:
        slug = slugify(section)
        if slug:
            url += "#" + slug
    return url


def linkify(source_path: str, section: str = "",
            *, label: Optional[str] = None,
            base: Optional[str] = None) -> str:
    """Return a markdown link `[label](url)` when the source is served by
    the wiki, else return just the plain `label` (or a back-tick-quoted
    source_path when no label is given).

    Used by the teacher-agent renderers so `[source path](wiki url)` shows
    up as a clickable link in Element DMs, but falls back cleanly when the
    source is outside the wiki corpus.
    """
    shown = label if label is not None else f"`{source_path}`"
    url = wiki_url(source_path, section, base=base)
    if not url:
        return shown
    return f"[{shown}]({url})"
