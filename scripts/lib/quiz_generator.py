"""Quiz generator for the teacher agent (IFRNLLEI01PRD-652).

Calls a local LLM (gemma3:12b via Ollama by default) with `format=json` to
produce a single question targeting a specific Bloom level, grounded in
concrete source snippets drawn from the curriculum's sources.

**Hallucination gate** (the critical safety property): the generated JSON
MUST carry a non-empty `source_snippets` array AND every snippet's
`verbatim_text` MUST be a substring of the concatenated input sources. On
violation, retry up to 2× with a tightened prompt noting the previous
failure. After the 3rd failure, log + return None. The caller (teacher-
agent.py) translates None into a "no question this turn, retry later"
Matrix message — it never falls back to un-grounded content.

Breaker-aware via `rag_synth_ollama` (shared with RAG synth / knowledge
extraction / handoff compaction). When the breaker is OPEN, generate()
short-circuits to None without making a network call.

Testability: the Ollama call is injected as `_ollama_fn`. QA tests pass a
lambda returning canned JSON so no network or model dependency is needed
for offline CI.

Output schema:
    {
      question_text:          str
      question_type:          one of BLOOM_LEVELS
      bloom_level:            same as question_type (redundant for clarity)
      source_snippets:        [{source_path, section, verbatim_text}, ...]
      expected_answer_rubric: str — what a fully-correct answer covers
      distractor_hints:       [str] — only meaningful for 'recognition' (MCQ) type
    }
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
QUIZ_MODEL = os.environ.get("TEACHER_QUIZ_MODEL", "gemma3:12b")
MAX_RETRIES = 3
MIN_VERBATIM_LEN = 8  # any substring check shorter than this would trivially match


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class Snippet:
    """Input source provided to the generator (from curriculum)."""
    source_path: str
    section: str
    verbatim_text: str


@dataclass
class Question:
    """Output returned to the caller."""
    question_text: str
    question_type: str
    bloom_level: str
    source_snippets: list[dict] = field(default_factory=list)
    expected_answer_rubric: str = ""
    distractor_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "question_text": self.question_text,
            "question_type": self.question_type,
            "bloom_level": self.bloom_level,
            "source_snippets": list(self.source_snippets),
            "expected_answer_rubric": self.expected_answer_rubric,
            "distractor_hints": list(self.distractor_hints),
        }


class HallucinationRejection(ValueError):
    """Raised internally when the generated snippets don't match sources.

    Callers of `generate()` never see this — it's caught internally and
    triggers a retry. After MAX_RETRIES, `generate()` returns None.
    """


# ── Prompt ──────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """You generate Socratic quiz questions for an expert operator learning about agentic systems.

Target Bloom level: {bloom}
Topic: {topic}

Sources (the ONLY material you may draw from):
{sources_block}

Produce STRICT JSON (no prose, no markdown fences) with this schema:

{{
  "question_text": "<=500 chars — a single focused question at the target Bloom level",
  "question_type": "{bloom}",
  "bloom_level": "{bloom}",
  "source_snippets": [
    {{
      "source_path": "<path from the sources block>",
      "section": "<section label>",
      "verbatim_text": "<exact substring copied from the source — at least {min_len} chars, no paraphrasing, no ellipses>"
    }},
    ...
  ],
  "expected_answer_rubric": "<=300 chars — what a fully-correct answer must cover",
  "distractor_hints": ["<only if question_type is 'recognition'; else []>"]
}}

Rules — violating any one invalidates the output:
  * source_snippets MUST contain at least one entry.
  * Every source_snippets[i].verbatim_text MUST be a verbatim substring of the sources block — no paraphrasing, no rewording, no ellipses.
  * bloom_level MUST equal question_type MUST equal "{bloom}".
  * Never invent facts not present in the sources block.
  * If the target Bloom level is "teaching_back", ask the operator to write a mini-lesson of 200-500 words covering the topic; keep the rubric concrete (must cite X, must explain Y).
{retry_note}"""


def _sources_block(sources: list[Snippet]) -> str:
    """Format snippets as numbered blocks for the prompt."""
    out = []
    for i, s in enumerate(sources, 1):
        out.append(f"[{i}] source_path: {s.source_path}\n    section: {s.section}\n    text: {s.verbatim_text}")
    return "\n\n".join(out)


def _concatenated_text(sources: list[Snippet]) -> str:
    """Union of all snippet verbatim_text — substrate for the hallucination gate."""
    return "\n\n".join(s.verbatim_text for s in sources)


# ── Ollama call ─────────────────────────────────────────────────────────────

_USE_GRAMMAR = os.environ.get("OLLAMA_USE_GRAMMAR", "1") == "1"
_GRAMMAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "grammars", "quiz-generator.schema.json")


def _call_ollama(prompt: str, timeout: int = 180) -> Optional[dict]:
    """Call Ollama with format=json (or JSON-schema if OLLAMA_USE_GRAMMAR=1).
    Falls back to format=json on schema rejection. Returns parsed dict or None.
    """
    body: dict = {
        "model": QUIZ_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.3},
    }
    if _USE_GRAMMAR and os.path.isfile(_GRAMMAR_PATH):
        try:
            body["format"] = json.load(open(_GRAMMAR_PATH))
        except (OSError, json.JSONDecodeError):
            body["format"] = "json"
    else:
        body["format"] = "json"

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        raw = (result.get("response") or "").strip()
        # Gemma occasionally wraps in ```json fences even with format=json.
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        return json.loads(m.group(0))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[quiz-gen] Ollama error: {exc}", file=sys.stderr)
        return None


# ── Validation ──────────────────────────────────────────────────────────────

def _validate_hallucination_gate(parsed: dict, haystack: str, target_bloom: str) -> None:
    """Raise HallucinationRejection on any violation. Caller retries or gives up."""
    if not isinstance(parsed, dict):
        raise HallucinationRejection("response is not a JSON object")
    snippets = parsed.get("source_snippets")
    if not isinstance(snippets, list) or not snippets:
        raise HallucinationRejection("source_snippets is empty or not a list")
    for i, snip in enumerate(snippets):
        if not isinstance(snip, dict):
            raise HallucinationRejection(f"source_snippets[{i}] is not an object")
        vt = snip.get("verbatim_text", "")
        if not isinstance(vt, str) or len(vt) < MIN_VERBATIM_LEN:
            raise HallucinationRejection(
                f"source_snippets[{i}].verbatim_text missing or too short (<{MIN_VERBATIM_LEN} chars)"
            )
        if vt not in haystack:
            raise HallucinationRejection(
                f"source_snippets[{i}].verbatim_text is not a substring of the sources block"
            )
    qt = parsed.get("question_type", "")
    bl = parsed.get("bloom_level", "")
    if qt != target_bloom or bl != target_bloom:
        raise HallucinationRejection(
            f"bloom mismatch: question_type={qt!r} bloom_level={bl!r} target={target_bloom!r}"
        )
    # Shape checks
    if not isinstance(parsed.get("question_text"), str) or not parsed["question_text"].strip():
        raise HallucinationRejection("question_text missing or empty")
    if not isinstance(parsed.get("expected_answer_rubric"), str) or not parsed["expected_answer_rubric"].strip():
        raise HallucinationRejection("expected_answer_rubric missing or empty")


# ── Public API ──────────────────────────────────────────────────────────────

def generate(
    topic_id: str,
    target_bloom: str,
    sources: list[Snippet],
    *,
    _ollama_fn: Optional[Callable[[str], Optional[dict]]] = None,
) -> Optional[Question]:
    """Generate one quiz question for the given topic + Bloom level.

    Args:
        topic_id: curriculum topic id (used only in the prompt for clarity).
        target_bloom: one of BLOOM_LEVELS.
        sources: non-empty list of Snippet from the topic's curriculum entry.
        _ollama_fn: test injection; defaults to _call_ollama. Accepts the
            rendered prompt, returns parsed dict or None.

    Returns:
        A Question on success, or None if the breaker is OPEN / Ollama is
        unreachable / the hallucination gate fails MAX_RETRIES times.
    """
    if not is_valid_level(target_bloom):
        raise ValueError(f"invalid target_bloom {target_bloom!r}")
    if not sources:
        raise ValueError("sources must be non-empty")

    if _ollama_fn is None:
        if _SYNTH_CB is not None and not _SYNTH_CB.allow():
            print("[quiz-gen] rag_synth_ollama breaker OPEN — skipping", file=sys.stderr)
            return None
        _ollama_fn = _call_ollama

    haystack = _concatenated_text(sources)
    sources_block = _sources_block(sources)

    last_rejection = ""
    for attempt in range(1, MAX_RETRIES + 1):
        retry_note = ""
        if attempt > 1:
            retry_note = (
                f"\n*** This is retry {attempt}. Previous attempt failed the "
                f"hallucination gate with: {last_rejection}. Copy verbatim from "
                f"the sources block — no paraphrasing, no ellipses, no rewording. ***"
            )
        prompt = _PROMPT_TEMPLATE.format(
            bloom=target_bloom,
            topic=topic_id,
            sources_block=sources_block,
            min_len=MIN_VERBATIM_LEN,
            retry_note=retry_note,
        )
        parsed = _ollama_fn(prompt)
        if parsed is None:
            # Ollama error — retry through loop.
            last_rejection = "ollama returned None"
            continue
        try:
            _validate_hallucination_gate(parsed, haystack, target_bloom)
        except HallucinationRejection as exc:
            last_rejection = str(exc)
            print(f"[quiz-gen] attempt {attempt}/{MAX_RETRIES} rejected: {exc}", file=sys.stderr)
            continue
        # Success — record breaker + build Question.
        if _SYNTH_CB is not None and _ollama_fn is _call_ollama:
            _SYNTH_CB.record_success()
        return Question(
            question_text=parsed["question_text"],
            question_type=parsed["question_type"],
            bloom_level=parsed["bloom_level"],
            source_snippets=list(parsed.get("source_snippets", [])),
            expected_answer_rubric=parsed.get("expected_answer_rubric", ""),
            distractor_hints=list(parsed.get("distractor_hints", [])),
        )

    # All attempts failed
    if _SYNTH_CB is not None and _ollama_fn is _call_ollama:
        _SYNTH_CB.record_failure()
    print(
        f"[quiz-gen] gave up after {MAX_RETRIES} attempts for topic={topic_id} "
        f"bloom={target_bloom} — last_rejection={last_rejection}",
        file=sys.stderr,
    )
    return None
