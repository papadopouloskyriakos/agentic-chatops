#!/usr/bin/env python3
"""Fail if docs/model-provenance.md drifts from the live active local models.

IFRNLLEI01PRD-1097: the provenance doc had silently gone stale (listed
qwen3:4b/qwen3:30b/devstral as the active local set while the live env defaults
were gemma3:12b + qwen2.5:7b + nomic-embed-text + bge-reranker-v2-m3). This check
extracts the ACTIVE local-model env defaults from the live code and asserts each
is documented in model-provenance.md's "Local Models" section.

Exit 0 = in sync. Exit 1 = drift (a code default not in the doc). Advisory: run
in holistic-agentic-health.sh / QA.
"""
from __future__ import annotations

import os
REDACTED_a7b84d63
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO, "docs", "model-provenance.md")

# (env var, source file, regex capturing the DEFAULT model id). Patterns match
# the bash ${VAR:-default} form and the python os.environ.get("VAR", "default") form.
ACTIVE_DEFAULTS = [
    ("JUDGE_LOCAL_MODEL", "scripts/llm-judge.sh", r'JUDGE_LOCAL_MODEL:-([\w.:\-]+)'),
    ("JUDGE_LOCAL_FALLBACK", "scripts/llm-judge.sh", r'JUDGE_LOCAL_FALLBACK:-([\w.:\-]+)'),
    ("REWRITE_MODEL", "scripts/kb-semantic-search.py", r'"REWRITE_MODEL",\s*"([\w.:\-]+)"'),
    ("SYNTH_MODEL", "scripts/kb-semantic-search.py", r'"SYNTH_MODEL",\s*"([\w.:\-]+)"'),
    ("EMBED_MODEL", "scripts/kb-semantic-search.py", r'"EMBED_MODEL",\s*"([\w.:\-]+)"'),
]


def doc_local_section() -> str:
    text = open(DOC).read()
    m = re.search(r"### Local Models.*?(?:\n## |\Z)", text, re.S)
    return (m.group(0) if m else text).lower()


def grep_default(src: str, pattern: str) -> str | None:
    path = os.path.join(REPO, src)
    try:
        body = open(path).read()
    except FileNotFoundError:
        return None
    m = re.search(pattern, body)
    return m.group(1) if m else None


def main() -> int:
    section = doc_local_section()
    drift = []
    checked = []
    for env, src, pat in ACTIVE_DEFAULTS:
        model = grep_default(src, pat)
        if not model:
            continue
        checked.append((env, model))
        # the doc must mention the model id (allow ":latest"/version suffix tolerance)
        base = model.split(":")[0].lower()
        if model.lower() not in section and base not in section:
            drift.append(f"{env}={model} (from {src}) is NOT documented in model-provenance.md Local Models")
    for env, model in checked:
        print(f"  active default {env}={model}")
    if drift:
        print("\nMODEL PROVENANCE DRIFT:", file=sys.stderr)
        for d in drift:
            print(f"  - {d}", file=sys.stderr)
        print("Fix: update docs/model-provenance.md Local Models table.", file=sys.stderr)
        return 1
    print("model-provenance.md in sync with live active local-model defaults ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
