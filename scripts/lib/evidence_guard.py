#!/usr/bin/env python3
"""Evidence guard (R2) — keep the judge's own verdicts out of any model context.

Mirror of harness2/core/context.py::assert_no_grader_verdicts: a tripwire, not the
defence. The session judge (scripts/llm-judge.sh) writes rationale/scores into
session_judgment; prompt patches are shaped by those scores; CLI-session transcripts
that discuss judge output are embedded into session_transcripts, which is a RAG
signal. If judge text ever reaches a Build Prompt or an embedded chunk, the next
session (or the next improver) optimises for the grader instead of the work.

Rule from upstream, kept verbatim in spirit: if the tripwire fires, find the read
path that produced the match. Do NOT widen the marker list to make it pass.

API
  scan(text) -> list[str]            markers found (empty = clean)
  is_clean(text) -> bool
  assert_no_grader_verdicts(text, where="") -> None  (raises EvidenceLeak)
  guard_lines(lines, where="", log=None) -> list[str]
                                     drop offending lines, log one JSON record per drop
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Iterable

# Strings that only ever occur in grader output (ours or the benchmarks'). Each one
# is specific enough that ordinary incident text does not contain it.
GRADER_VERDICT_MARKERS: tuple[str, ...] = (
    '"overall_score"',
    '"recommended_action"',
    '"investigation_quality"',
    '"safety_compliance"',
    '"judge_model"',
    "judge_effort",
    "JUDGE VERDICT",
    "judge-fooled",
    "overall_score=",
    "session_judgment",
    # upstream benchmark graders (kept so vendored evidence trees stay clean too)
    "deterministic_eval_summary",
    "deterministic_eval_result",
    '"pass_rate"',
    '"test_pass_rate"',
)

LOG_PATH = os.environ.get(
    "EVIDENCE_GUARD_LOG",
    os.path.expanduser("~/logs/claude-gateway/evidence-guard.jsonl"),
)


class EvidenceLeak(ValueError):
    """Grader output would enter a model context."""


def scan(text: str, markers: Iterable[str] = GRADER_VERDICT_MARKERS) -> list[str]:
    body = text or ""
    return [m for m in markers if m in body]


def is_clean(text: str) -> bool:
    return not scan(text)


def assert_no_grader_verdicts(text: str, where: str = "") -> None:
    hits = scan(text)
    if hits:
        m = hits[0]
        at = (text or "").index(m)
        snippet = (text or "")[max(0, at - 60): at + 100].replace("\n", " ")
        raise EvidenceLeak(
            f"grader verdict would enter model context{(' via ' + where) if where else ''}: "
            f"marker {m!r} at offset {at} ({snippet!r}). The tripwire fired — find the "
            f"read path that produced it, do not widen the marker list."
        )


def _log(record: dict, log: str | None) -> None:
    path = log or LOG_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


def guard_lines(lines: Iterable[str], where: str = "", log: str | None = None) -> list[str]:
    """Return the lines that are clean; every dropped line is logged (never silently)."""
    kept: list[str] = []
    for line in lines:
        hits = scan(line)
        if hits:
            _log({"ts": int(time.time()), "where": where, "markers": hits,
                  "preview": (line or "")[:160]}, log)
            continue
        kept.append(line)
    return kept


def guard_text(text: str, where: str = "", log: str | None = None) -> str | None:
    """Return the text when clean, else None (and log). For whole-chunk writers."""
    hits = scan(text)
    if hits:
        _log({"ts": int(time.time()), "where": where, "markers": hits,
              "preview": (text or "")[:160]}, log)
        return None
    return text


def main(argv: list[str] | None = None) -> int:
    """CLI: evidence_guard.py [FILE ...]  (stdin when no file). Exit 1 on a hit."""
    args = sys.argv[1:] if argv is None else argv
    rc = 0
    sources = [(p, open(p, encoding="utf-8", errors="replace").read()) for p in args] \
        if args else [("<stdin>", sys.stdin.read())]
    for name, body in sources:
        hits = scan(body)
        if hits:
            print(f"{name}: LEAK markers={hits}")
            rc = 1
        else:
            print(f"{name}: clean")
    return rc


if __name__ == "__main__":
    sys.exit(main())
