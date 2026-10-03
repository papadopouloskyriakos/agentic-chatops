#!/usr/bin/env python3
"""Auto-derive teacher-agent curriculum from wiki + docs + memory sources.

IFRNLLEI01PRD-651 — teacher-agent foundation.

Reads a fixed set of source directories / files, extracts a topic candidate
per logical unit (Gulli pattern, invariant, wiki service article, runbook,
etc.), and writes config/curriculum.json. Existing operator edits (marked
by a `source: operator-edited` field in the JSON) are preserved on rewrite.

Usage:
    scripts/rebuild-curriculum.py                   # rewrite config/curriculum.json
    scripts/rebuild-curriculum.py --dry-run         # print diff summary, no write
    scripts/rebuild-curriculum.py --print-topics    # emit topic list to stdout

The output schema:

    {
      "topics": [
        {
          "id": "invariant-1-hitl",
          "title": "Invariant 1: HITL gate on mutating actions",
          "sources": [{"path": "docs/system-as-abstract-agent.md", "anchor": "#invariants"}],
          "bloom_progression": ["recall", "recognition", "explanation",
                                "application", "analysis", "evaluation",
                                "teaching_back"],
          "prerequisites": [],
          "difficulty": "foundational",
          "estimated_minutes": 10,
          "origin": "auto"           # or "operator-edited" for hand-tuned entries
        },
        ...
      ],
      "curricula": [
        {"id": "foundations", "name": "Agentic System Foundations",
         "topics": ["invariant-1-hitl", "invariant-2-memory", ...]}
      ],
      "meta": {
        "generated_at": "2026-04-20T17:45:00Z",
        "source_count": 47,
        "topic_count": 47
      }
    }
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
REDACTED_a7b84d63
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "curriculum.json"
DEFAULT_BLOOM = [
    "recall", "recognition", "explanation",
    "application", "analysis", "evaluation", "teaching_back",
]


def _slug(s: str, prefix: str = "") -> str:
    """Reduce a string to a stable topic id."""
    # Collapse separator-like punctuation (slash, colon, comma, semicolon,
    # parentheses, ampersand as word-joiner) to spaces BEFORE the strip step,
    # so "Guardrails/Safety" → "guardrails-safety" rather than
    # "guardrailssafety".
    s = re.sub(r"[/:,;()&]+", " ", s.lower())
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (prefix + s) if prefix else s


def _first_h1(path: Path) -> str | None:
    """First `# heading` in a markdown file, or None."""
    try:
        for line in path.open():
            line = line.strip()
            if line.startswith("# ") and not line.startswith("## "):
                return line[2:].strip()
    except OSError:
        pass
    return None


def derive_invariants_and_lenses() -> list[dict]:
    """6 invariants + 4 lenses + 1 pure-signature = 11 topics from
    docs/system-as-abstract-agent.md."""
    src = "docs/system-as-abstract-agent.md"
    topics = []
    invariants = [
        ("1", "HITL gate on mutating actions"),
        ("2", "Memory never shrinks"),
        ("3", "Policy change is externally judged"),
        ("4", "Confidence is a first-class scalar"),
        ("5", "Every decision cascades through three tiers"),
        ("6", "Failure preserves Memory and permits re-entry"),
    ]
    for n, title in invariants:
        topics.append({
            "id": f"invariant-{n}-{_slug(title)}",
            "title": f"Invariant {n}: {title}",
            "sources": [{"path": src, "anchor": "#invariants"}],
            "bloom_progression": DEFAULT_BLOOM,
            "prerequisites": [],
            "difficulty": "foundational",
            "estimated_minutes": 10,
            "origin": "auto",
        })
    lenses = [
        ("control-theory", "Control theory lens", "plant + sensors + actuators + reference signal + error"),
        ("rl", "Reinforcement learning lens", "POMDP / state-action-reward / A-B trials"),
        ("three-stage-filter", "Three-stage filter lens", "deterministic → LLM reasoning → human"),
        ("classical-agent", "Classical agent lens", "Perceive → Reason → Act → Observe → Update at three timescales"),
    ]
    for slug, title, summary in lenses:
        topics.append({
            "id": f"lens-{slug}",
            "title": f"Lens: {title}",
            "sources": [{"path": src, "anchor": "#four-lenses"}],
            "bloom_progression": DEFAULT_BLOOM,
            "prerequisites": [],
            "difficulty": "intermediate",
            "estimated_minutes": 15,
            "origin": "auto",
            "summary_hint": summary,
        })
    topics.append({
        "id": "pure-signature",
        "title": "The pure signature: (Signal, Context, Memory, Policy) → (Action, Memory', Policy', Communication)",
        "sources": [{"path": src, "anchor": "#pure-signature"}],
        "bloom_progression": DEFAULT_BLOOM,
        "prerequisites": [],
        "difficulty": "foundational",
        "estimated_minutes": 12,
        "origin": "auto",
    })
    return topics


def derive_gulli_patterns() -> list[dict]:
    """21 Gulli patterns in canonical chapter order.

    Prefer the Summary Scorecard table (`| N | Name | **Grade** | ...`), which
    lists all 21 in book order. Fall back to the first table (`| N | **Name** |
    Implementation | Grade |`) when the scorecard is missing — that only has 15
    patterns but at least lets the curriculum bootstrap.
    """
    src_rel = "docs/agentic-patterns-audit.md"
    path = REPO_ROOT / src_rel
    if not path.exists():
        return []
    text = path.read_text()

    # Summary Scorecard: `| 1 | Prompt Chaining | **A+** | ...`
    # Name is column 2 (unbolded), grade is column 3 (bolded).
    scorecard_re = re.compile(
        r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*\*\*[A-Z+\-]+\*\*\s*\|",
        re.MULTILINE,
    )
    matches = list(scorecard_re.finditer(text))
    if len(matches) < 21:
        # Fall back to the first, shorter table with bolded names.
        first_table_re = re.compile(r"^\|\s*(\d+)\s*\|\s*\*\*([^*]+?)\*\*\s*\|", re.MULTILINE)
        matches = list(first_table_re.finditer(text))

    topics = []
    for m in matches:
        n, name = m.group(1), m.group(2).strip()
        # Strip trailing "(Chapter)" annotation like "Inter-Agent Communication (A2A)"
        name_clean = re.sub(r"\s*\([^)]+\)\s*$", "", name).strip() or name
        slug = _slug(name_clean)
        topic_id = f"gulli-{int(n):02d}-{slug}"
        # Prefer the per-pattern wiki page (generated by
        # scripts/generate-pattern-pages.py) when present — it has a clean
        # heading whose slug matches, so deep-links land on the right spot
        # rather than the top of the 21-pattern table.
        per_page = REPO_ROOT / "wiki" / "patterns" / f"{topic_id}.md"
        if per_page.exists():
            sources = [{"path": f"wiki/patterns/{topic_id}.md", "anchor": ""}]
        else:
            sources = [{"path": src_rel, "anchor": f"#pattern-{n}"}]
        topics.append({
            "id": topic_id,
            "title": f"Gulli pattern #{n}: {name}",
            "sources": sources,
            "bloom_progression": DEFAULT_BLOOM,
            "prerequisites": [],
            "difficulty": "intermediate",
            "estimated_minutes": 12,
            "origin": "auto",
        })
    return topics


def derive_wiki_services() -> list[dict]:
    """One topic per article in wiki/services/."""
    topics = []
    root = REPO_ROOT / "wiki" / "services"
    if not root.exists():
        return []
    for md in sorted(root.glob("*.md")):
        title = _first_h1(md) or md.stem.replace("-", " ").title()
        rel = md.relative_to(REPO_ROOT).as_posix()
        topics.append({
            "id": f"wiki-service-{_slug(md.stem)}",
            "title": f"Service: {title}",
            "sources": [{"path": rel}],
            "bloom_progression": DEFAULT_BLOOM,
            "prerequisites": [],
            "difficulty": "intermediate",
            "estimated_minutes": 12,
            "origin": "auto",
        })
    return topics


def derive_runbooks() -> list[dict]:
    """One topic per docs/runbooks/*.md."""
    topics = []
    root = REPO_ROOT / "docs" / "runbooks"
    if not root.exists():
        return []
    for md in sorted(root.glob("*.md")):
        title = _first_h1(md) or md.stem.replace("-", " ").title()
        rel = md.relative_to(REPO_ROOT).as_posix()
        topics.append({
            "id": f"runbook-{_slug(md.stem)}",
            "title": f"Runbook: {title}",
            "sources": [{"path": rel}],
            "bloom_progression": DEFAULT_BLOOM,
            "prerequisites": [],
            "difficulty": "intermediate",
            "estimated_minutes": 15,
            "origin": "auto",
        })
    return topics


def derive_readme_sections() -> list[dict]:
    """Top-level README.extensive.md adoption-batch sections (§22-25)."""
    src_rel = "README.extensive.md"
    path = REPO_ROOT / src_rel
    if not path.exists():
        return []
    topics = []
    # Each section looks like "## 22. OpenAI Agents SDK Adoption Batch"
    pat = re.compile(r"^##\s+(\d{2})\.\s+(.+)$", re.MULTILINE)
    for m in pat.finditer(path.read_text()):
        n, name = m.group(1), m.group(2).strip()
        if int(n) < 22 or int(n) > 25:
            continue
        topics.append({
            "id": f"readme-sec-{n}-{_slug(name)}",
            "title": f"Platform §{n}: {name}",
            "sources": [{"path": src_rel, "anchor": f"#{n}-{_slug(name)}"}],
            "bloom_progression": DEFAULT_BLOOM,
            "prerequisites": [],
            "difficulty": "advanced",
            "estimated_minutes": 20,
            "origin": "auto",
        })
    return topics


def derive_memory_picks() -> list[dict]:
    """Curated high-value project memories (not every memory — just the
    ones that document major system decisions)."""
    picks = [
        ("openai_sdk_adoption_batch", "SDK adoption batch — what landed 2026-04-20"),
        ("preference_iterating_prompt_patcher", "Preference-iterating prompt patcher (IFRNLLEI01PRD-645)"),
        ("cli_session_rag_capture", "CLI-session RAG capture pipeline (-646/-647/-648)"),
        ("rag_circuit_breakers", "RAG circuit breakers (rerank / embed / synth)"),
        ("risk_based_auto_approval", "Risk-based auto-approval (IFRNLLEI01PRD-632)"),
        ("wiki_knowledge_base", "Karpathy-style compiled wiki"),
        ("mempalace_integration", "MemPalace integration — 8 patterns"),
    ]
    memory_dir = Path(
        "/home/app-user/.claude/projects/"
        "-home-app-user-gitlab-n8n-claude-gateway/memory"
    )
    topics = []
    for stem, title in picks:
        fpath = memory_dir / f"{stem}.md"
        if not fpath.exists():
            continue
        topics.append({
            "id": f"memory-{_slug(stem)}",
            "title": f"Project memory: {title}",
            "sources": [{"path": str(fpath), "role": "project-memory"}],
            "bloom_progression": DEFAULT_BLOOM,
            "prerequisites": [],
            "difficulty": "intermediate",
            "estimated_minutes": 10,
            "origin": "auto",
        })
    return topics


def build() -> dict:
    """Compose the full curriculum JSON dict."""
    all_topics: list[dict] = []
    all_topics.extend(derive_invariants_and_lenses())
    all_topics.extend(derive_gulli_patterns())
    all_topics.extend(derive_wiki_services())
    all_topics.extend(derive_runbooks())
    all_topics.extend(derive_readme_sections())
    all_topics.extend(derive_memory_picks())

    # Merge with any existing operator-edited topics (preserve origin='operator-edited').
    existing_operator = []
    if CONFIG_PATH.exists():
        try:
            prior = json.loads(CONFIG_PATH.read_text())
            for t in prior.get("topics", []):
                if t.get("origin") == "operator-edited":
                    existing_operator.append(t)
        except (json.JSONDecodeError, OSError):
            pass

    # Dedupe by id: auto loses to operator-edited
    ids_operator = {t["id"] for t in existing_operator}
    keep_auto = [t for t in all_topics if t["id"] not in ids_operator]
    topics = keep_auto + existing_operator
    # Stable sort by id for diff-friendliness
    topics.sort(key=lambda t: t["id"])

    curricula = [
        {
            "id": "foundations",
            "name": "Agentic System Foundations",
            "topics": [t["id"] for t in topics if (
                t["id"].startswith(("invariant-", "lens-"))
                or t["id"] == "pure-signature"
            )],
        },
        {
            "id": "patterns",
            "name": "Gulli's 21 Agentic Design Patterns",
            "topics": [t["id"] for t in topics if t["id"].startswith("gulli-")],
        },
        {
            "id": "platform",
            "name": "Platform & Runtime",
            "topics": [t["id"] for t in topics if t["id"].startswith(("wiki-service-", "readme-sec-", "runbook-"))],
        },
        {
            "id": "memory",
            "name": "Project memories (major decisions)",
            "topics": [t["id"] for t in topics if t["id"].startswith("memory-")],
        },
    ]

    return {
        "topics": topics,
        "curricula": curricula,
        "meta": {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "source_count": len({s["path"] for t in topics for s in t.get("sources", [])}),
            "topic_count": len(topics),
            "curricula_count": len(curricula),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print diff summary, do not write")
    ap.add_argument("--print-topics", action="store_true",
                    help="print the topic id list to stdout and exit")
    args = ap.parse_args()

    data = build()

    if args.print_topics:
        for t in data["topics"]:
            print(f"{t['id']:50s}  {t['title']}")
        return 0

    before_count = 0
    before_ids: set[str] = set()
    if CONFIG_PATH.exists():
        try:
            prior = json.loads(CONFIG_PATH.read_text())
            before_count = len(prior.get("topics", []))
            before_ids = {t["id"] for t in prior.get("topics", [])}
        except (json.JSONDecodeError, OSError):
            pass

    new_ids = {t["id"] for t in data["topics"]}
    added = sorted(new_ids - before_ids)
    removed = sorted(before_ids - new_ids)

    print(f"topics: before={before_count} → after={len(data['topics'])}")
    print(f"curricula: {len(data['curricula'])}")
    print(f"sources:   {data['meta']['source_count']}")
    print(f"added:     {len(added)}")
    print(f"removed:   {len(removed)}")
    if added:
        print("  + " + "\n  + ".join(added[:10]))
        if len(added) > 10:
            print(f"  + ... and {len(added) - 10} more")
    if removed:
        print("  - " + "\n  - ".join(removed[:10]))

    if args.dry_run:
        print("(dry-run — no write)")
        return 0

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
