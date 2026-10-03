"""Bloom's-taxonomy progression for the teacher agent (IFRNLLEI01PRD-652).

Determines which question type to sample next given the operator's current
mastery_score and repetition_count on a topic. Implements the 4-band model
from docs/plans/teacher-agent-implementation-plan.md §6:

    Foundation   mastery  0.0-0.4  →  recall, recognition
    Conceptual   mastery  0.4-0.7  →  explanation, application
    Analytical   mastery  0.7-0.9  →  analysis, evaluation
    Mastery      mastery  0.9-1.0  →  teaching_back

Within a band, rotate through candidates by repetition_count so the operator
sees variety instead of always getting the first candidate.

Separately exposes the 7-element BLOOM_LEVELS ordered list so callers can
iterate / validate. `is_advance_target()` answers: given current
highest_bloom_reached and proposed target, is this advancement allowed, or
only a revisit within the current band?
"""
from __future__ import annotations

# Ordered from foundational to mastery. Used for advancement comparisons.
BLOOM_LEVELS = [
    "recall",
    "recognition",
    "explanation",
    "application",
    "analysis",
    "evaluation",
    "teaching_back",
]

# Candidate question types per mastery band. Plan §6.
_BAND_CANDIDATES: list[tuple[float, float, list[str]]] = [
    (0.0, 0.4, ["recall", "recognition"]),
    (0.4, 0.7, ["explanation", "application"]),
    (0.7, 0.9, ["analysis", "evaluation"]),
    (0.9, 1.01, ["teaching_back"]),
]


def band_for(mastery_score: float) -> str:
    """Return band name for the given mastery score."""
    if mastery_score < 0.4:
        return "foundation"
    if mastery_score < 0.7:
        return "conceptual"
    if mastery_score < 0.9:
        return "analytical"
    return "mastery"


def candidates_for(mastery_score: float) -> list[str]:
    """Return the list of candidate question types for this mastery level."""
    for lo, hi, cands in _BAND_CANDIDATES:
        if lo <= mastery_score < hi:
            return list(cands)
    # mastery 1.0+ → mastery band
    return list(_BAND_CANDIDATES[-1][2])


def select_target_bloom(mastery_score: float, repetition_count: int = 0) -> str:
    """Pick the next Bloom level for a quiz.

    Deterministic given (mastery, repetition) so the same operator gets the
    same sequence on replay. Rotates within band by repetition_count mod
    len(candidates).
    """
    cands = candidates_for(mastery_score)
    idx = max(0, repetition_count) % len(cands)
    return cands[idx]


def is_valid_level(level: str) -> bool:
    return level in BLOOM_LEVELS


def level_index(level: str) -> int:
    """Return the 0-6 rank of a Bloom level. Raises if invalid."""
    return BLOOM_LEVELS.index(level)


def is_advance(current: str, proposed: str) -> bool:
    """True iff `proposed` sits higher in the progression than `current`."""
    if not is_valid_level(current) or not is_valid_level(proposed):
        return False
    return level_index(proposed) > level_index(current)
