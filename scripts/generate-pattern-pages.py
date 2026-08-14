#!/usr/bin/env python3
"""Auto-generate wiki/patterns/gulli-NN-<slug>.md — one page per Gulli pattern.

Why: the audit doc keeps Gulli patterns inside tables, not under headings. The
teacher-agent's deep links were generating anchors like `#tool-use` that didn't
correspond to real headings, so clicking a link landed on the page top.

Each generated page has a clean `# Gulli pattern #N: <Name>` heading (so the
slug matches the teacher-agent's URL), plus the implementation excerpts from
both the "Well-Implemented" table (lines 13-29 of the audit doc) and the
"Summary Scorecard" table (lines 158-180). The teacher-agent then points
snippets at `wiki/patterns/gulli-NN-<slug>.md` and deep links land on a page
that's actually about that one pattern.

Rerun whenever:
  - docs/agentic-patterns-audit.md changes (new pattern, different wording)
  - config/curriculum.json regenerates (after canonical Gulli order changes)

Idempotent: diff-friendly output, safe to commit.
"""
from __future__ import annotations

REDACTED_a7b84d63
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "docs" / "agentic-patterns-audit.md"
OUT_DIR = REPO_ROOT / "wiki" / "patterns"

# Match the canonical Summary Scorecard table row:
#   | 1 | Prompt Chaining | **A+** | implementation description |
SCORECARD_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*\*\*([A-Z+\-]+)\*\*\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)

# Match the "Well-Implemented" table row (first table, bold-wrapped names):
#   | 1 | **Tool Use** | implementation | Grade |
FIRST_TABLE_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*\*\*([^*]+?)\*\*\s*\|\s*([^|]+?)\s*\|\s*([A-Z+\-]+)\s*\|",
    re.MULTILINE,
)


def _slug(name: str) -> str:
    """Match rebuild-curriculum's _slug (slash/colon/etc → space, then strip)."""
    s = re.sub(r"[/:,;()&]+", " ", name.lower())
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s


def _name_core(name: str) -> str:
    """Strip parenthetical chapter notes like 'Inter-Agent Communication (A2A)'."""
    return re.sub(r"\s*\([^)]+\)\s*$", "", name).strip() or name


def main() -> int:
    if not SRC.exists():
        print(f"source not found: {SRC}", file=sys.stderr)
        return 1
    text = SRC.read_text()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Parse the Summary Scorecard — this is the canonical 21-pattern list.
    scorecard = {}
    for m in SCORECARD_RE.finditer(text):
        n = int(m.group(1))
        scorecard[n] = {
            "name": m.group(2).strip(),
            "grade": m.group(3),
            "impl": m.group(4).strip(),
        }
    if len(scorecard) < 21:
        print(f"scorecard yielded {len(scorecard)} rows (need 21)", file=sys.stderr)
        return 2

    # Parse the first-table entries by name — they describe the SAME patterns
    # but use different numbering. Index by name (case-insensitive) to cross-ref.
    first_table_by_name = {}
    for m in FIRST_TABLE_RE.finditer(text):
        name = m.group(2).strip()
        first_table_by_name[name.lower()] = {
            "impl": m.group(3).strip(),
            "grade": m.group(4),
        }

    # Emit the index page
    index_lines = [
        "# Gulli Agentic Design Patterns (21)",
        "",
        "Catalogued from Antonio Gulli's *Agentic Design Patterns*.",
        "Each pattern is a chapter of the book + a dedicated page here with the",
        "system's current implementation note and grade.",
        "",
        "Source: [`docs/agentic-patterns-audit.md`](../../docs/agentic-patterns-audit.md)",
        "",
        "| # | Pattern | Grade | Page |",
        "|---|---|---|---|",
    ]

    topic_order = []
    for n in sorted(scorecard.keys()):
        entry = scorecard[n]
        name = entry["name"]
        core = _name_core(name)
        slug_name = _slug(core)
        page_id = f"gulli-{n:02d}-{slug_name}"
        topic_order.append((n, name, core, slug_name, page_id, entry))

        # Per-pattern page body
        body_lines = [
            f"# Gulli pattern #{n}: {name}",
            "",
            f"**Grade:** {entry['grade']}  ",
            f"**Book chapter:** {n}",
            "",
            "## Current implementation",
            "",
            entry["impl"],
            "",
        ]

        # If the first table has an entry for the same pattern (matched by core name)
        first = first_table_by_name.get(core.lower())
        if first and first["impl"] != entry["impl"]:
            body_lines.extend([
                "## Earlier implementation note (from the well-implemented-table)",
                "",
                f"**Grade at that time:** {first['grade']}",
                "",
                first["impl"],
                "",
            ])

        body_lines.extend([
            "## Related",
            "",
            "- Full audit (all 21 patterns in context): "
            "[`docs/agentic-patterns-audit.md`](../../docs/agentic-patterns-audit.md)",
            f"- Summary Scorecard row: see the table at "
            f"[`docs/agentic-patterns-audit.md#summary-scorecard-updated-2026-03-29`]"
            f"(../../docs/agentic-patterns-audit.md#summary-scorecard-updated-2026-03-29)",
            "",
            "_Auto-generated by `scripts/generate-pattern-pages.py` — re-run after "
            "editing the audit doc. Do not edit this file by hand._",
            "",
        ])

        out_path = OUT_DIR / f"{page_id}.md"
        out_path.write_text("\n".join(body_lines))

        index_lines.append(f"| {n} | {name} | **{entry['grade']}** | [{page_id}]({page_id}.md) |")

    # Index page
    (OUT_DIR / "index.md").write_text("\n".join(index_lines) + "\n")

    print(f"wrote {OUT_DIR / 'index.md'} + {len(topic_order)} per-pattern pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
