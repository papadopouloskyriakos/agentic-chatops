"""Curriculum-grounded free-chat for the teacher agent.

Reuses the `quiz_generator` / `quiz_grader` pattern: every answer cites
verbatim from the operator's currently-active curriculum sources (or
nearby curriculum topics). Off-curriculum questions are refused rather
than hallucinated — same hallucination gate philosophy as quiz generation.

The design goal is operator trust: if the teacher agent answers a
question, the operator can be confident the claim is actually in the
indexed corpus. That's a harder bar than generic chat but critical for a
learning context.
"""
from __future__ import annotations

import json
import os
REDACTED_a7b84d63
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from quiz_generator import Snippet  # noqa: E402 — reuse snippet dataclass

try:
    from circuit_breaker import CircuitBreaker  # type: ignore
    _SYNTH_CB: Optional["CircuitBreaker"] = CircuitBreaker(
        "rag_synth_ollama", failure_threshold=4, cooldown_seconds=120,
    )
except ImportError:  # pragma: no cover
    _SYNTH_CB = None

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
CHAT_MODEL = os.environ.get("TEACHER_CHAT_MODEL", "gemma3:12b")
CHAT_NUM_CTX = int(os.environ.get("TEACHER_CHAT_NUM_CTX", "8192"))
# ~2500 answer chars + cited_snippets + refused + clarifying_question
# fits comfortably under 2048 output tokens. Without an explicit cap,
# gemma3:12b occasionally stopped mid-word and let Ollama auto-close
# the JSON shell — the operator saw a truncated sentence.
CHAT_NUM_PREDICT = int(os.environ.get("TEACHER_CHAT_NUM_PREDICT", "2048"))
CHAT_MAX_RETRIES = 2


@dataclass
class ChatAnswer:
    answer: str
    cited_snippets: list[dict]   # subset of source_snippets the LLM actually cited
    refused: bool = False
    refusal_reason: str = ""
    clarifying_question: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "cited_snippets": list(self.cited_snippets),
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "clarifying_question": self.clarifying_question,
        }


class ChatRejection(ValueError):
    """Raised internally when the chat response shape is malformed."""


_PROMPT_TEMPLATE = """You are the teacher agent for the Example Corp ChatOps platform. An
operator who is studying agentic-systems theory has asked you the question
below. Your job is to answer it GROUNDED STRICTLY in the source snippets
listed below — these are passages from the operator's own curriculum.

OPERATOR QUESTION:
    {question}

AVAILABLE SOURCES:
{sources_block}

Produce STRICT JSON (no prose, no markdown fences) with this schema:

{{
  "answer":              "<your answer — aim for 3-8 short paragraphs, up to ~2500 chars — MUST reference at least one source by quoting its section or a short verbatim substring>",
  "cited_snippets":      [{{ "source_path": "<path>", "section": "<heading>" }}, ...],
  "refused":             <boolean — true when the question is off-curriculum (answer would require material NOT in the sources above)>,
  "refusal_reason":      "<non-empty iff refused=true — briefly tell the operator WHY you can't answer and which topic might be closer>",
  "clarifying_question": <string or null — populated when the question is too vague to ground>
}}

Rules:
  * If the answer cannot be supported by the sources above, set refused=true
    and refusal_reason. Do NOT invent facts.
  * cited_snippets MUST include every source you reference. Empty array is
    allowed only when refused=true.
  * Teach — don't summarise. Walk the operator through WHAT the concept is,
    HOW it works mechanically, and WHY the system is designed that way,
    grounded in the source text. Concrete names (files, metrics, thresholds,
    signal weights) beat abstract descriptions. A few short paragraphs is
    better than one dense one; bulleted lists are fine where they help.
  * If the operator's question is ambiguous (multiple curriculum topics
    could plausibly be asked about), set clarifying_question and leave
    answer short and generic.
"""


def _sources_block(snippets: list[Snippet]) -> str:
    out = []
    for i, s in enumerate(snippets, 1):
        out.append(f"[{i}] source_path: {s.source_path}\n"
                   f"    section: {s.section}\n"
                   f"    text: {s.verbatim_text}")
    return "\n\n".join(out) if out else "(no source snippets available)"


def _call_ollama(prompt: str, timeout: int = 120) -> Optional[dict]:
    data = json.dumps({
        "model": CHAT_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": CHAT_NUM_CTX,
            "num_predict": CHAT_NUM_PREDICT,
            "temperature": 0.1,
        },
    }).encode()
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        raw = (result.get("response") or "").strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        return json.loads(m.group(0))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[teacher-chat] Ollama error: {exc}", file=sys.stderr)
        return None


def _validate(parsed: dict, snippets: list[Snippet]) -> dict:
    if not isinstance(parsed, dict):
        raise ChatRejection("response is not a JSON object")

    answer = parsed.get("answer", "")
    if not isinstance(answer, str):
        raise ChatRejection("answer is not a string")
    answer = answer.strip()

    refused = bool(parsed.get("refused", False))
    refusal_reason = (parsed.get("refusal_reason") or "").strip() if isinstance(parsed.get("refusal_reason"), str) else ""
    if refused and not refusal_reason:
        raise ChatRejection("refused=true requires a non-empty refusal_reason")

    cites = parsed.get("cited_snippets", [])
    if not isinstance(cites, list):
        cites = []
    cited_snippets: list[dict] = []
    snippet_keys = {(s.source_path, s.section) for s in snippets}
    for c in cites:
        if not isinstance(c, dict):
            continue
        sp, sec = c.get("source_path", ""), c.get("section", "")
        # Accept matches against the provided snippets (loose: source_path alone suffices).
        paths = {s.source_path for s in snippets}
        if sp and sp in paths:
            cited_snippets.append({"source_path": sp, "section": sec or ""})

    cq = parsed.get("clarifying_question")
    if cq == "null" or cq == "":
        cq = None
    if cq is not None and not isinstance(cq, str):
        cq = None

    # If the LLM answered (not refused, not clarifying) without ANY cited
    # snippet, treat it as a grounding failure — refuse.
    if answer and not refused and not cq and not cited_snippets:
        raise ChatRejection("answer provided without any cited source — grounding gate")

    return {
        "answer": answer,
        "cited_snippets": cited_snippets,
        "refused": refused,
        "refusal_reason": refusal_reason,
        "clarifying_question": cq,
    }


def chat(question: str, snippets: list[Snippet],
         *, _ollama_fn: Optional[Callable[[str], Optional[dict]]] = None,
         ) -> Optional[ChatAnswer]:
    """Main entry. Returns ChatAnswer or None on retry exhaustion."""
    if not question.strip():
        return ChatAnswer(
            answer="",
            cited_snippets=[],
            refused=True,
            refusal_reason="empty question",
        )

    prompt = _PROMPT_TEMPLATE.format(
        question=question.strip(),
        sources_block=_sources_block(snippets),
    )

    # Share the rag_synth_ollama circuit breaker with quiz_generator +
    # quiz_grader. When OPEN, fast-fail instead of burning 60-120s on retries.
    # The breaker is bypassed when an explicit _ollama_fn is injected (QA path).
    call_fn = _ollama_fn
    if call_fn is None:
        if _SYNTH_CB is not None and not _SYNTH_CB.allow():
            print("[teacher-chat] rag_synth_ollama breaker OPEN — skipping", file=sys.stderr)
            return None
        call_fn = _call_ollama

    last_err = "unknown"
    ok = False
    for attempt in range(1, CHAT_MAX_RETRIES + 1):
        parsed = call_fn(prompt)
        if parsed is None:
            last_err = "ollama returned None"
            continue
        try:
            validated = _validate(parsed, snippets)
        except ChatRejection as e:
            last_err = str(e)
            print(f"[teacher-chat] attempt {attempt}/{CHAT_MAX_RETRIES} rejected: {e}", file=sys.stderr)
            continue
        ok = True
        if _SYNTH_CB is not None and _ollama_fn is None:
            _SYNTH_CB.record_success()
        return ChatAnswer(**validated)

    if not ok and _SYNTH_CB is not None and _ollama_fn is None:
        _SYNTH_CB.record_failure()
    print(f"[teacher-chat] gave up after {CHAT_MAX_RETRIES} attempts — last: {last_err}", file=sys.stderr)
    return None
