"""Quiz grader for the teacher agent (IFRNLLEI01PRD-652).

Given a Question (produced by quiz_generator) + the operator's free-text
answer + the original source snippets, call a local LLM (gemma3:12b via
Ollama by default) to evaluate the answer against the rubric.

Output contract:
    {
      score_0_to_1:        float — 0.0 fully wrong, 1.0 fully correct
      feedback:            str — prose; MUST reference source snippets
      bloom_demonstrated:  one of BLOOM_LEVELS (may be lower than the
                           question's target if the answer was shallow)
      citation_check: {
        in_sources:        bool — True iff every factual claim in the
                           answer traces back to the sources
        extra_claims:      [str] — factual claims NOT in sources (may
                           still be correct — operator synthesis — just
                           flagged for later review)
      }
      clarifying_question: str | null — populated only when the grader's
                           own confidence < 0.6 on the final score
      grader_confidence:   float — 0.0 to 1.0, grader's self-reported
                           certainty about the score
    }

Mapping to SM-2 scheduler: score_0_to_1 → quality 0-5 via sm2.quality_from_score.
The grader does NOT apply the SM-2 update — that's the caller's job
(teacher-agent.py at -653).

Testability: same _ollama_fn injection pattern as quiz_generator. Tests
pass canned-response lambdas; production uses the real Ollama call.
"""
from __future__ import annotations

import json
import os
REDACTED_a7b84d63
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bloom import BLOOM_LEVELS, is_valid_level  # noqa: E402

try:
    from circuit_breaker import CircuitBreaker  # type: ignore
    _SYNTH_CB: Optional[CircuitBreaker] = CircuitBreaker(
        "rag_synth_ollama", failure_threshold=4, cooldown_seconds=120,
    )
except ImportError:  # pragma: no cover
    _SYNTH_CB = None


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
GRADER_MODEL = os.environ.get("TEACHER_GRADER_MODEL", "gemma3:12b")
CONFIDENCE_THRESHOLD = 0.6  # grader_confidence below this → clarifying_question required
MAX_RETRIES = 2

# IFRNLLEI01PRD-749 (G2.P1.1): JSON-Schema-constrained decoding.
# When OLLAMA_USE_GRAMMAR=1 (default since 2026-04-29), pass the schema dict
# to Ollama's `format` field (Ollama 0.5+ supports this). Falls back to
# `format=json` automatically on schema rejection or any HTTP error.
_USE_GRAMMAR = os.environ.get("OLLAMA_USE_GRAMMAR", "1") == "1"
_GRAMMAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "grammars", "quiz-grader.schema.json")


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class Grade:
    score_0_to_1: float
    feedback: str
    bloom_demonstrated: str
    citation_check: dict  # {in_sources: bool, extra_claims: list[str]}
    clarifying_question: Optional[str] = None
    grader_confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "score_0_to_1": self.score_0_to_1,
            "feedback": self.feedback,
            "bloom_demonstrated": self.bloom_demonstrated,
            "citation_check": dict(self.citation_check),
            "clarifying_question": self.clarifying_question,
            "grader_confidence": self.grader_confidence,
        }


class GraderRejection(ValueError):
    """Raised internally when grader output has a malformed shape."""


# ── Prompt ──────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """You grade an operator's answer to a Socratic quiz on agentic systems.

Question:
    {question_text}

Target Bloom level: {target_bloom}

Expected-answer rubric (what a fully-correct answer covers):
    {rubric}

Sources the question was grounded in (the ONLY authoritative material):
{sources_block}

Operator's answer:
    {answer}

Produce STRICT JSON (no prose, no markdown fences) with this schema:

{{
  "score_0_to_1":       <float 0.0-1.0 — how well the answer meets the rubric>,
  "feedback":           "<=500 chars prose — MUST quote or reference a source snippet to justify the score>",
  "bloom_demonstrated": "<one of {bloom_levels_csv} — may be below the target if the answer was shallow>",
  "citation_check": {{
    "in_sources":  <boolean — true iff every factual claim in the answer maps to a source>,
    "extra_claims": ["<factual claims in the answer that are NOT in sources — may still be correct synthesis, just flagged>"]
  }},
  "clarifying_question": <string or null — populated only when your own confidence about the score is below {conf_threshold}>,
  "grader_confidence":   <float 0.0-1.0 — how sure you are about this score>
}}

Rules:
  * feedback MUST reference at least one source snippet explicitly (by section or verbatim).
  * extra_claims lists items that sound correct but aren't in the sources — don't penalise the score for them, just surface.
  * Never invent facts not in the sources when writing feedback.
  * If the operator's answer is empty or purely a restatement of the question, score ≤ 0.2 and set bloom_demonstrated="recall".
"""


def _sources_block(snippets: list[dict]) -> str:
    out = []
    for i, s in enumerate(snippets, 1):
        path = s.get("source_path", "?")
        section = s.get("section", "?")
        text = s.get("verbatim_text", "")
        out.append(f"[{i}] source_path: {path}\n    section: {section}\n    text: {text}")
    return "\n\n".join(out) if out else "(no source snippets)"


# ── Ollama call ─────────────────────────────────────────────────────────────

def _call_ollama(prompt: str, timeout: int = 180) -> Optional[dict]:
    # G2.P1.1: try schema-constrained format first; fall back to format=json.
    body: dict = {
        "model": GRADER_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.1},
    }
    if _USE_GRAMMAR and os.path.isfile(_GRAMMAR_PATH):
        try:
            body["format"] = json.load(open(_GRAMMAR_PATH))
        except (OSError, json.JSONDecodeError):
            body["format"] = "json"
    else:
        body["format"] = "json"

    def _post(payload: dict) -> Optional[dict]:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            raw = (result.get("response") or "").strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return None
            return json.loads(m.group(0))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"[quiz-grade] Ollama error: {exc}", file=sys.stderr)
            return None

    parsed = _post(body)
    if parsed is None and isinstance(body.get("format"), dict):
        # Schema-constrained call rejected by server — fall back to format=json.
        body["format"] = "json"
        parsed = _post(body)
    return parsed


# ── Validation ──────────────────────────────────────────────────────────────

def _coerce_and_validate(parsed: dict) -> dict:
    """Coerce grader output into the expected shape or raise.

    Accepts numeric strings for score fields (some models return them as
    strings); clamps to [0, 1]; ensures bloom_demonstrated is a valid level;
    ensures citation_check has the two required keys.
    """
    if not isinstance(parsed, dict):
        raise GraderRejection("response is not a JSON object")

    # Score
    try:
        score = float(parsed.get("score_0_to_1"))
    except (TypeError, ValueError):
        raise GraderRejection("score_0_to_1 missing or not a number")
    score = max(0.0, min(1.0, score))

    # Feedback
    feedback = parsed.get("feedback", "")
    if not isinstance(feedback, str) or not feedback.strip():
        raise GraderRejection("feedback missing or empty")

    # Bloom
    bloom = parsed.get("bloom_demonstrated", "")
    if not is_valid_level(bloom):
        raise GraderRejection(f"bloom_demonstrated {bloom!r} not in BLOOM_LEVELS")

    # Citation check
    cc = parsed.get("citation_check", {})
    if not isinstance(cc, dict):
        cc = {}
    in_sources = bool(cc.get("in_sources", True))
    extras = cc.get("extra_claims", [])
    if not isinstance(extras, list):
        extras = []
    extras = [str(x) for x in extras if x]

    # Grader confidence
    try:
        grader_conf = float(parsed.get("grader_confidence", 1.0))
    except (TypeError, ValueError):
        grader_conf = 1.0
    grader_conf = max(0.0, min(1.0, grader_conf))

    # Clarifying question
    cq = parsed.get("clarifying_question")
    if cq == "null" or cq == "":
        cq = None
    if cq is not None and not isinstance(cq, str):
        cq = None

    # Invariant #4 — low grader confidence requires a clarifying question.
    # If the grader reported low confidence but produced no clarifier, synthesise
    # one rather than silently advancing the progression on a dubious score.
    if grader_conf < CONFIDENCE_THRESHOLD and not cq:
        cq = (
            "The grader's confidence on this answer was below threshold. Please "
            "elaborate on the specific aspect of the question you found most "
            "challenging, so a follow-up quiz can target it precisely."
        )

    return {
        "score_0_to_1": score,
        "feedback": feedback.strip(),
        "bloom_demonstrated": bloom,
        "citation_check": {"in_sources": in_sources, "extra_claims": extras},
        "clarifying_question": cq,
        "grader_confidence": grader_conf,
    }


# ── Public API ──────────────────────────────────────────────────────────────

def grade(
    question: dict,
    operator_answer: str,
    *,
    _ollama_fn: Optional[Callable[[str], Optional[dict]]] = None,
) -> Optional[Grade]:
    """Grade one answer against the question's rubric + sources.

    Args:
        question: dict matching Question.to_dict() — has question_text,
            source_snippets, expected_answer_rubric, bloom_level.
        operator_answer: free-text string.
        _ollama_fn: test injection; defaults to _call_ollama.

    Returns:
        Grade on success; None if the breaker is OPEN or all retries fail.
    """
    if not isinstance(question, dict):
        raise ValueError("question must be a dict")
    if not isinstance(operator_answer, str):
        raise ValueError("operator_answer must be a string")

    if _ollama_fn is None:
        if _SYNTH_CB is not None and not _SYNTH_CB.allow():
            print("[quiz-grade] rag_synth_ollama breaker OPEN — skipping", file=sys.stderr)
            return None
        _ollama_fn = _call_ollama

    prompt = _PROMPT_TEMPLATE.format(
        question_text=question.get("question_text", ""),
        target_bloom=question.get("bloom_level", ""),
        rubric=question.get("expected_answer_rubric", ""),
        sources_block=_sources_block(question.get("source_snippets", [])),
        answer=operator_answer.strip() or "(empty answer)",
        bloom_levels_csv=", ".join(BLOOM_LEVELS),
        conf_threshold=CONFIDENCE_THRESHOLD,
    )

    last_rejection = ""
    for attempt in range(1, MAX_RETRIES + 1):
        parsed = _ollama_fn(prompt)
        if parsed is None:
            last_rejection = "ollama returned None"
            continue
        try:
            coerced = _coerce_and_validate(parsed)
        except GraderRejection as exc:
            last_rejection = str(exc)
            print(f"[quiz-grade] attempt {attempt}/{MAX_RETRIES} rejected: {exc}", file=sys.stderr)
            continue
        if _SYNTH_CB is not None and _ollama_fn is _call_ollama:
            _SYNTH_CB.record_success()
        return Grade(**coerced)

    if _SYNTH_CB is not None and _ollama_fn is _call_ollama:
        _SYNTH_CB.record_failure()
    print(
        f"[quiz-grade] gave up after {MAX_RETRIES} attempts — last_rejection={last_rejection}",
        file=sys.stderr,
    )
    return None
