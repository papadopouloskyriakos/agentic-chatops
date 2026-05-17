"""SuperMemo-2 spaced-repetition scheduler (IFRNLLEI01PRD-651).

Pure functions, no side effects, no SQLite coupling. The teacher-agent
orchestrator (scripts/teacher-agent.py) calls `schedule()` after each
quiz grading to obtain the next (easiness_factor, interval_days,
repetition_count, next_due) and writes them back to learning_progress.

SM-2 algorithm (SuperMemo-2, 1987):
  - Quality is a 0-5 integer. 0-2 = incorrect/poor (reset repetition);
    3-5 = correct (advance repetition).
  - Interval progression on correct streak:
        n=1 → 1 day
        n=2 → 6 days
        n≥3 → round(prev_interval * easiness_factor)
  - Easiness-factor update every call:
        EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    Clamped to [1.3, 2.8]. The upper 2.8 bound is tightened from the
    original 2.5 (SuperMemo standard) because agentic-systems topics
    deserve repeated exposure even when recalled easily (design choice
    per docs/plans/teacher-agent-implementation-plan.md §9).

Grader score → quality mapping:
  score_0_to_1 → round(score * 5) → quality_0_to_5

Usage:

    from sm2 import Card, schedule, initial_card

    card = initial_card()   # easiness=2.5, interval=1, repetition=0
    card = schedule(card, quality=5, now=datetime.utcnow())
    # → interval=1, repetition=1, easiness=2.6, next_due=now+1d

    card = schedule(card, quality=5)
    # → interval=6, repetition=2, easiness=2.7, next_due=prev+6d
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Iterable


# Clamps match the SuperMemo-2 reference plus Anki's convention. An earlier
# design draft proposed EF_MAX=2.8 but empirical testing showed it grows the
# interval too fast (e.g. 5x quality-5 reaches 134-day interval, not the
# expected ~90). 2.5 keeps repeat-exposure cadence honest for high-cognitive-
# load agentic-systems material.
EF_MIN = 1.3
EF_MAX = 2.5


@dataclass(frozen=True)
class Card:
    """SM-2 state for one (operator, topic) row.

    Immutable so schedule() returns a new Card rather than mutating in place —
    matches the teacher-agent test expectations and makes the function trivially
    parallel-safe. The owning caller (teacher-agent.py) persists the new Card
    back to learning_progress via UPSERT.
    """
    easiness_factor: float = 2.5
    interval_days: int = 1
    repetition_count: int = 0
    next_due: datetime | None = None   # None = schedule immediately


def initial_card(now: datetime | None = None) -> Card:
    """Fresh card — scheduled for immediate first exposure."""
    return Card(
        easiness_factor=2.5,
        interval_days=1,
        repetition_count=0,
        next_due=now or datetime.utcnow(),
    )


def _update_easiness(ef: float, quality: int) -> float:
    """SM-2 easiness update with clamping."""
    # Classic SM-2 formula.
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    new_ef = ef + delta
    return max(EF_MIN, min(EF_MAX, new_ef))


def _next_interval(prev_interval: int, repetition: int, ef: float) -> int:
    """Given the NEW repetition count (post-increment), return the next interval."""
    if repetition == 1:
        return 1
    if repetition == 2:
        return 6
    return max(1, round(prev_interval * ef))


def schedule(card: Card, quality: int, now: datetime | None = None) -> Card:
    """Apply SM-2 update given a grader quality score.

    Args:
      card: current SM-2 state for this (operator, topic).
      quality: 0-5. 0-2 resets repetition_count; 3-5 advances.
      now: datetime to base next_due on. Defaults to UTC now.

    Returns:
      New Card with updated easiness/interval/repetition/next_due. The
      input Card is not mutated.
    """
    if quality < 0 or quality > 5:
        raise ValueError(f"quality must be 0..5, got {quality}")
    now = now or datetime.utcnow()

    new_ef = _update_easiness(card.easiness_factor, quality)

    if quality < 3:
        # Poor answer → reset learning, re-show tomorrow.
        new_repetition = 0
        new_interval = 1
    else:
        new_repetition = card.repetition_count + 1
        new_interval = _next_interval(card.interval_days, new_repetition, new_ef)

    new_due = now + timedelta(days=new_interval)
    return replace(
        card,
        easiness_factor=new_ef,
        interval_days=new_interval,
        repetition_count=new_repetition,
        next_due=new_due,
    )


def quality_from_score(score_0_to_1: float) -> int:
    """Map 0.0-1.0 grader score to 0-5 SM-2 quality via round(score * 5).

    Clamped to [0, 5] against grader misbehaviour.
    """
    q = round(float(score_0_to_1) * 5)
    return max(0, min(5, q))


def due_topics(rows: Iterable[dict], now: datetime | None = None) -> list[dict]:
    """Filter+sort rows to topics whose next_due has passed.

    Expected row shape (duck-typed): dict-like with keys `next_due` (datetime
    or ISO string) and `mastery_score` (float). Sorted ascending by next_due,
    tiebreak ascending by mastery_score so least-mastered-among-equally-due
    surfaces first.
    """
    now = now or datetime.utcnow()

    def _parse(v):
        if isinstance(v, datetime):
            return v
        if isinstance(v, str) and v:
            # Accept trailing 'Z' and the implicit UTC that SQLite returns.
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return datetime.max

    due = [r for r in rows if _parse(r.get("next_due")) <= now]
    due.sort(key=lambda r: (_parse(r.get("next_due")), float(r.get("mastery_score") or 0.0)))
    return due
