# Implementation plan — Teacher agent

**Tracking YT issues:** [IFRNLLEI01PRD-651](https://youtrack.example.net/issue/IFRNLLEI01PRD-651) (foundation), [-652](https://youtrack.example.net/issue/IFRNLLEI01PRD-652) (intelligence), [-653](https://youtrack.example.net/issue/IFRNLLEI01PRD-653) (interface), [-654](https://youtrack.example.net/issue/IFRNLLEI01PRD-654) (loop), [-655](https://youtrack.example.net/issue/IFRNLLEI01PRD-655) (gate).
**Author:** 2026-04-20, app-user session.
**Status:** Proposed. Not yet started.

This document is the design spec. The linked YT issues hold the per-tier work breakdown and acceptance criteria. Read the plan first; the issues assume you've read it.

---

## 1. Goal

Add a sub-agent that teaches the operator about agentic systems theory and this system's practice, tracks progress via spaced repetition, and verifies mastery through Bloom's-taxonomy-progressive questioning. Grounded in the system's own documentation — no hallucinated content, ever.

**Non-goals (explicit):**

- Not a general-purpose tutor. Curriculum is bounded by this system's docs and memory.
- Not a performance-review tool. The operator grades the system; the system only reflects back.
- Not a replacement for operator judgement. If the operator says a source is wrong, the teacher flags the source for review — it does not argue.
- No new LLM provider. Local gemma3:12b via Ollama, matching the 2026-04-19 local-first flip.

## 2. Key design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Reflexive grounding** — the system teaches using its own memory | Avoids hallucination by construction; every question cites a verbatim source snippet. The system's self-documentation is now live training data. |
| D2 | **Bloom's-taxonomy progression gates mastery** — not quiz-score | Mastery means the operator can *apply* and *teach back*, not just recall. Mitigates Goodhart drift where operators memorise quiz format. |
| D3 | **SuperMemo-2 scheduling** — not FSRS or custom | Battle-tested (Anki), small surface area, deterministic. Teacher agent's pedagogy is not the research contribution — soundness is. |
| D4 | **Local LLMs only** | Zero marginal cost. Matches the 2026-04-19 judge/synth flip. Breaker-aware via `rag_synth_ollama`. |
| D5 | **Matrix UX — no new chat surface** | Reuses existing HITL pattern. One new set of commands (`!learn`, `!quiz`, …); zero new rooms. |
| D6 | **Read-only against operational world** | Teacher is `.claude/agents/teacher-agent.md` with Edit / Write / mutating-Bash explicitly disallowed. All writes go through `teacher-agent.py` against `learning_*` tables only. Invariant 1 is hardened, not just honoured. |
| D7 | **Curriculum auto-derived from wiki + docs + memory** | Hand-authoring 30+ topics is tedious and drifts. `rebuild-curriculum.py` walks the sources; operator edits only to override difficulty or prerequisites. |
| D8 | **Idempotent everywhere** | Grading the same answer twice updates the row; does not double-advance. Re-running `rebuild-curriculum.py` on unchanged sources produces identical output. |

## 3. Architecture

```
                 ┌───────────────────────────────────┐
                 │  Operator (Matrix)                 │
                 └───────────────┬───────────────────┘
                                 │ !learn / !quiz / !progress / !grade
                                 ▼
                 ┌───────────────────────────────────┐
                 │  matrix-bridge (existing n8n)      │
                 │  + new command parser              │
                 └───────────────┬───────────────────┘
                                 │ webhook /teacher-command
                                 ▼
                 ┌───────────────────────────────────┐
                 │  teacher-runner (new n8n workflow) │
                 │  - SSH dispatch to claude01        │
                 │  - format response for Matrix      │
                 └───────────────┬───────────────────┘
                                 │
                                 ▼
                 ┌───────────────────────────────────┐
                 │  scripts/teacher-agent.py          │
                 │  subcommand dispatcher             │
                 └──┬─────────────────┬──────────────┘
                    │                 │
            ┌───────▼──────┐   ┌──────▼──────────┐   ┌─────────────────┐
            │ lib/sm2.py   │   │ lib/quiz_gen    │   │ lib/quiz_grader │
            │ pure sched   │   │ gemma3:12b      │   │ gemma3:12b      │
            └───────┬──────┘   └──────┬──────────┘   └────────┬────────┘
                    │                 │                       │
                    └─────────────────┼───────────────────────┘
                                      ▼
                 ┌─────────────────────────────────────────┐
                 │  SQLite gateway.db                      │
                 │  - learning_progress (writes)           │
                 │  - learning_sessions (appends)          │
                 │  - wiki_articles, incident_knowledge,   │
                 │    docs/*  (reads — curriculum + sources)│
                 └─────────────────────────────────────────┘
                                      │
                                      ▼
                 ┌─────────────────────────────────────────┐
                 │  write-learning-metrics.sh (*/5)         │
                 │  → Prometheus textfile collector         │
                 │  → Grafana "Learning Progress" dashboard │
                 └─────────────────────────────────────────┘

         Crons (nl-claude01):
         - 08:30 UTC daily     morning nudge
         - 18:00 UTC Sunday    weekly digest → #chatops
         - */5 * * * *         metrics exporter
```

## 4. Data model

### Migration 013 — `scripts/migrations/013_teacher_agent.sql`

```sql
CREATE TABLE IF NOT EXISTS learning_progress (
  id                        INTEGER PRIMARY KEY AUTOINCREMENT,
  operator                  TEXT NOT NULL,
  topic                     TEXT NOT NULL,
  mastery_score             REAL DEFAULT 0.0,       -- 0.0 - 1.0
  easiness_factor           REAL DEFAULT 2.5,       -- SM-2, clamped [1.3, 2.8]
  interval_days             INTEGER DEFAULT 1,      -- SM-2
  repetition_count          INTEGER DEFAULT 0,      -- SM-2
  highest_bloom_reached     TEXT DEFAULT 'recall',  -- recall|recognition|explanation|application|analysis|evaluation|teaching_back
  last_reviewed             DATETIME,
  next_due                  DATETIME DEFAULT CURRENT_TIMESTAMP,
  quiz_history              TEXT DEFAULT '[]',      -- JSON [{session_id, score, ts}]
  paused                    INTEGER DEFAULT 0,      -- !learn pause toggle
  needs_review              INTEGER DEFAULT 0,      -- source content changed since mastery
  source_hash               TEXT DEFAULT '',        -- BLAKE2b of concatenated sources at mastery time
  created_at                DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at                DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version            INTEGER DEFAULT 1,
  UNIQUE(operator, topic)
);

CREATE INDEX IF NOT EXISTS idx_lp_next_due ON learning_progress(operator, next_due);
CREATE INDEX IF NOT EXISTS idx_lp_mastery ON learning_progress(operator, mastery_score);

CREATE TABLE IF NOT EXISTS learning_sessions (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  operator          TEXT NOT NULL,
  topic             TEXT NOT NULL,
  session_type      TEXT NOT NULL,              -- lesson|quiz|review|teaching_back
  bloom_level       TEXT,                       -- set for quiz/review/teaching_back
  started_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at      DATETIME,
  quiz_score        REAL,                       -- 0.0 - 1.0, null until graded
  question_payload  TEXT,                       -- JSON {question_text, source_snippets[], rubric}
  answer_payload    TEXT,                       -- JSON {answer_text, submitted_at}
  judge_feedback    TEXT,                       -- grader prose feedback
  citation_flag     INTEGER DEFAULT 0,          -- answer references content not in sources
  schema_version    INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_ls_operator ON learning_sessions(operator, topic);
CREATE INDEX IF NOT EXISTS idx_ls_started ON learning_sessions(started_at);
```

### Schema version registry update

`scripts/lib/schema_version.py` gains two entries:

```python
CURRENT_SCHEMA_VERSION["learning_progress"] = 1
CURRENT_SCHEMA_VERSION["learning_sessions"] = 1
SCHEMA_VERSION_SUMMARIES["learning_progress"] = {
    1: "initial shape for IFRNLLEI01PRD-651 teacher-agent foundation"
}
SCHEMA_VERSION_SUMMARIES["learning_sessions"] = {
    1: "initial shape for IFRNLLEI01PRD-651 teacher-agent foundation"
}
```

## 5. Module contracts

### `scripts/lib/sm2.py` (pure, no side-effects)

```python
@dataclass
class Card:
    easiness_factor: float    # [1.3, 2.8]
    interval_days: int
    repetition_count: int
    next_due: datetime

def initial_card() -> Card: ...

def schedule(card: Card, quality_0_to_5: int) -> Card:
    """Apply SM-2 update. Quality 0-2 resets repetition_count to 0."""

def due_topics(rows: list[dict], now: datetime) -> list[dict]:
    """Return rows where next_due <= now, ordered by (next_due asc, mastery_score asc)."""
```

### `scripts/lib/quiz_generator.py`

```python
@dataclass
class Snippet:
    source_path: str
    section: str
    verbatim_text: str

@dataclass
class Question:
    question_text: str
    question_type: str          # recall|recognition|explanation|application|analysis|evaluation|teaching_back
    bloom_level: str
    source_snippets: list[Snippet]
    expected_answer_rubric: str
    distractor_hints: list[str]  # only for recognition type

def generate(topic_id: str, target_bloom: str, sources: list[Snippet]) -> Question | None:
    """Ollama gemma3:12b format=json. Hallucination gate:
       - source_snippets MUST be non-empty
       - every snippet.verbatim_text MUST be substring of concatenated sources
       - 3 retries with tighter prompt on violation; None after 3rd fail.
       Breaker-aware: returns None immediately if rag_synth_ollama is OPEN."""
```

### `scripts/lib/quiz_grader.py`

```python
@dataclass
class Grade:
    score_0_to_1: float
    feedback: str
    bloom_demonstrated: str
    citation_check: dict       # {in_sources: bool, extra_claims: list[str]}
    clarifying_question: str | None  # populated iff grader confidence < 0.6

def grade(question: Question, operator_answer: str, sources: list[Snippet]) -> Grade | None:
    """Same Ollama backend. Grader rubric enforces referencing source snippets
       in feedback. Returns None on breaker-open or 3-retry failure."""

def quality_from_score(score: float) -> int:
    """Map 0-1 grader score to SM-2 quality 0-5 via round(score * 5)."""
```

### `scripts/teacher-agent.py` (orchestrator)

Subcommands — exit code 0 on success, 1 on error, 2 on user-visible refusal (e.g., invalid topic):

| Subcommand | Input | Output (stdout JSON) |
|---|---|---|
| `--next` | `--operator X` | `{topic, next_due, reason}` or `{message: "no topics due"}` |
| `--lesson <topic>` | | markdown lesson string |
| `--quiz <topic>` | | `{session_id, question_payload, bloom_level}` |
| `--grade <session_id> --answer <text>` | | `{score, feedback, next_due_days, bloom_demonstrated, clarifying_question?}` |
| `--progress` | `--operator X` | `{mastery_map, due_queue, weak_areas, streak_days}` |
| `--digest [--weekly]` | `--post-to-matrix?` | markdown digest string |
| `--pause` / `--resume` | `--operator X` | `{paused: true/false}` |
| `--morning-nudge` | | side-effect (Matrix post); stdout summary |
| `--rebuild-curriculum` | | `{topics_before, topics_after, added, removed}` |

## 6. Bloom progression policy

The mastery gate — NOT quiz-score-driven alone.

| Current band | Mastery range | Questions sampled | Advance if... |
|---|---|---|---|
| **Foundation** | 0.0 – 0.4 | recall, recognition | 2 consecutive score ≥ 0.8, interval ≥ 3 days |
| **Conceptual** | 0.4 – 0.7 | explanation, application | 2 consecutive score ≥ 0.8, interval ≥ 7 days |
| **Analytical** | 0.7 – 0.9 | analysis, evaluation | 2 consecutive score ≥ 0.8, interval ≥ 7 days |
| **Mastery** | 0.9 – 1.0 | teaching-back | 2 passes, score ≥ 0.9, interval ≥ 14 days — only now is `mastery_score = 1.0` set |

Teaching-back is the hard gate. Operator writes a mini-lesson (200-500 words); grader evaluates:

1. **Clarity** — would a new operator understand this?
2. **Accuracy** — every factual claim cites or aligns with source snippets.
3. **Completeness** — covers the full scope defined in the topic's `sources[]`.
4. **No hallucination** — extra claims surface in `citation_check.extra_claims`.

## 7. Anti-hallucination strategy (detailed)

The teacher agent has three layers of defence against hallucinated teaching:

1. **Source-bounded generation** (`lib/quiz_generator.py`). The generator prompt includes only the topic's declared sources. The output JSON *must* include a `source_snippets` array with verbatim substrings of those inputs. Post-generation validation rejects responses where:
   - `source_snippets` is empty
   - any `snippet.verbatim_text` is not `in` the concatenated source string
   Three retries with tightened prompt; third failure emits a `quiz_generation_failed` typed event and aborts. Never degrades to free-form.

2. **Grounded grading** (`lib/quiz_grader.py`). The grader rubric requires citing source snippets in feedback. An answer that references material outside the sources is **not penalised** — it might be correct operator synthesis — but it's flagged via `citation_check.extra_claims` for later operator review. Operator can dismiss or mark "actually this source is wrong."

3. **Source-change auditing**. Each `learning_progress` row stores a `source_hash` at mastery time (BLAKE2b over concatenated sources). The nightly `rebuild-curriculum.py` recomputes hashes; mismatches set `needs_review=1` and schedule a refresh session. Mastery is NOT automatically revoked — the operator decides.

## 8. Invariant compliance

| # | Invariant | How teacher-agent satisfies it |
|---|---|---|
| 1 | HITL gate on mutating actions | Teacher is read-only against the operational world. `.claude/agents/teacher-agent.md` tools allowlist excludes Edit / Write / any mutating Bash. Writes only via `teacher-agent.py` on `learning_*` tables. Enforced by `agent_as_tool.py` validator + QA test `invariant_1_teacher_is_read_only`. |
| 2 | Memory never shrinks | `learning_progress` updates in place (UPSERT); `learning_sessions` is append-only. No DELETE paths. `quiz_history` field accumulates. |
| 3 | Policy change externally judged | Grader is the external judge; operator cannot self-certify mastery. Mastery only advances when `grader.score ≥ 0.8` (or ≥ 0.9 for teaching-back). No operator override. |
| 4 | Confidence first-class | Grader returns `score` + `bloom_demonstrated`. When grader's own confidence < 0.6, it populates `clarifying_question` instead of a final score — topic remains in progress, not advanced. |
| 5 | Every decision three-tier | T1 deterministic lesson-structure renderer → T2 LLM quiz generation + grading → T3 operator-typed answer. Each tier can refuse: renderer refuses unknown topics; generator refuses un-grounded; operator can `!learn pause`. |
| 6 | Failure preserves state + re-entry | `learning_sessions` row created on lesson/quiz start with `completed_at = NULL`. Mid-flow crash leaves the row in "started" state. Next `!progress` call lists it as `in_flight`; operator can resume or cancel. |

## 9. SM-2 parameter choices

Starting values chosen conservatively for technical content with high cognitive load:

| Parameter | Value | Rationale |
|---|---|---|
| Initial `easiness_factor` | 2.5 | SM-2 default. Self-calibrates over ~5 reviews. |
| Easiness clamp | `[1.3, 2.8]` | Upper-bound below SM-2's 3.0 because agentic systems topics deserve repeated exposure even when "easy." |
| Initial `interval_days` | 1 | First review next day. |
| Second interval | 6 | After first pass. |
| Third+ interval | `round(prev_interval * easiness_factor)` | Standard SM-2. |
| Quality threshold for count reset | `quality ≤ 2` | Poor answer = re-learn. |

## 10. Curriculum source mapping

Initial foundations curriculum (≥ 30 topics), auto-generated by `rebuild-curriculum.py` from:

| Source | Topics extracted |
|---|---|
| `docs/system-as-abstract-agent.md` | 1 topic per invariant (6) + 1 per lens (4) + 1 for the pure signature itself = 11 topics |
| `docs/agentic-patterns-audit.md` | 1 topic per Gulli pattern (21) |
| `wiki/services/*.md` | 1 topic per service wiki article (~10) |
| `README.extensive.md` §22–25 | 1 topic per adoption batch section (4) |
| `docs/runbooks/*.md` | 1 topic per runbook (~8) |
| `memory/*.md` | 1 topic per major project memory entry (optional, curated) |

Each topic declares:
- `sources[]` — paths + optional section anchors
- `prerequisites[]` — topic IDs that must be at Conceptual band first
- `difficulty` — `foundational|intermediate|advanced`
- `estimated_minutes` — for time-spent dashboards
- `bloom_progression` — ordered list of Bloom levels to advance through

Operator edits `config/curriculum.json` overrides; `rebuild-curriculum.py` preserves operator-edited entries.

## 11. Matrix UX flows

### Flow A — Morning nudge (cron)

```
[cron 08:30 UTC]
  → teacher-agent.py --morning-nudge
  → reads learning_progress where next_due <= now and not paused
  → top 5 topics → Matrix post to operator DM:
      "Good morning. 3 topics due:
       1. Invariant 1: HITL gate  (analytical band, quiz)
       2. Preference-iterating prompt patcher  (conceptual band, lesson)
       3. RAG Fusion  (foundation band, quiz)
       Type !learn to start with #1."
```

### Flow B — `!learn` interactive

```
Operator: !learn
Bot:      [lesson/quiz content]
Operator: [answer text]
Bot:      "Score 0.87 (good). Next review in 6 days.
           Bloom: explanation → now eligible for application.
           Tomorrow: 2 other topics due."
```

### Flow C — `!progress`

```
Operator: !progress
Bot:      "Mastery map:
           ✓✓✓ 7 topics mastered
           ✓✓  9 topics analytical band
           ✓   12 topics conceptual band
           ◯   5 topics foundation band
           ?   3 topics not yet started
           Streak: 11 days. Weak area: 'chaos engineering'."
```

## 12. Observability contract

Metrics in `/var/lib/prometheus/node-exporter/learning_progress.prom`:

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `learning_topics_total` | gauge | `operator` | Total topics in the operator's active curriculum. |
| `learning_topics_mastered` | gauge | `operator` | `mastery_score ≥ 0.8` count. |
| `learning_topics_due` | gauge | `operator` | `next_due ≤ now` count. |
| `learning_quiz_accuracy_7d` | gauge | `operator` | Rolling 7-day avg score. |
| `learning_weekly_sessions_total` | counter | `operator` | Sessions completed per week. |
| `learning_longest_streak_days` | gauge | `operator` | Consecutive-day session streak. |
| `learning_bloom_distribution` | gauge | `operator, bloom_level` | Topics at each Bloom band. |

Alerts (in `prometheus/alert-rules/learning.yml`):

- **`TeacherAgentStaleDigest`** — `absent_over_time(learning_weekly_sessions_total[14d])` → weekly digest cron didn't fire.
- **`TeacherAgentMetricsAbsent`** — `absent(learning_topics_total)` → exporter broken.

## 13. Rollback plan

If the teacher agent proves problematic:

```bash
# 1. Pause the operator (immediate, reversible):
scripts/teacher-agent.py --pause

# 2. Disable crons (in crontab -e, comment the 3 teacher lines).

# 3. Stop the n8n workflow (deactivate claude-gateway-teacher-runner).

# 4. (Optional) Suppress Matrix commands (remove !learn branch from
#    matrix-bridge). Keeps the underlying state.

# 5. Nuclear — drop tables (loses progress history, keeps QA green):
sqlite3 gateway.db "DROP TABLE learning_sessions; DROP TABLE learning_progress;"
# AND revert migration 013 + schema_version registry entries.
```

The curriculum JSON is kept under version control; tables can always be rebuilt.

## 14. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Grader hallucinates (judges wrong answer correct) | med | high | 85% calibration baseline vs hand-grading; `citation_check` flags extra claims; operator can mark "regrade"; periodic judge-vs-Haiku sanity check. |
| Operator game-s quiz format | low-med | med | Bloom progression requires application + teaching-back; cannot advance on recall alone. |
| Source drift invalidates mastery | med | low | `source_hash` + `needs_review=1` flow; operator notified of drift, not auto-revoked. |
| Operator ignores the teacher | med | low | SM-2 naturally stretches intervals; weekly digest is passive; `!learn pause` is first-class. No punitive escalation. |
| LLM latency (Ollama cold-start) | low | low | Async Matrix posts already tolerate it; pre-warm via a daily dummy query if needed. |
| Curriculum generator produces too many topics | low | med | `rebuild-curriculum.py` has caps per source; operator reviews diff before accepting. |
| `agent_as_tool.py` tool-allowlist bypass | low | high | QA test `invariant_1_teacher_is_read_only` runs in every CI build; regressions fail the suite. |

## 15. Open questions

1. **Single-operator vs multi-operator.** Current memory states solo-operator setup. We model `operator TEXT` but default to one row per topic. Do we want per-operator isolation now, or defer? **Proposed:** defer; use `operator='default'` until a second operator appears.
2. **Should the teacher agent emit typed events** (`lesson_delivered`, `quiz_graded`, `topic_mastered`) into `event_log` alongside its own `learning_sessions`? **Proposed:** yes, low-cost and consistent with the adoption batch. Land in issue -653.
3. **Morning nudge time.** 08:30 UTC = 10:30 / 11:30 local time depending on DST. Good for a morning coffee routine; adjustable via env. **Proposed:** keep 08:30 UTC as default.
4. **Should teaching-back lessons be posted back to the wiki as operator-authored notes?** An interesting reflexive loop — operator's teaching-back becomes training material for the next learner. **Proposed:** defer to a follow-up issue if the feature works.

## 16. Issue sequence + dependencies

```
651 foundation        ──┐
   schema+SM-2          │
   curriculum           │
                        ├──▶  652 intelligence ──┐
                        │        quiz gen/grade  │
                        │                        │
                        └────────────────────────┴──▶  653 interface  ──┐
                                                         CLI+agent+n8n │
                                                         +matrix        │
                                                                        │
                                                                        ├──▶  654 loop
                                                                        │   crons+metrics
                                                                        │   +Grafana
                                                                        │
                                                                        └──▶  655 gate
                                                                           QA+docs
                                                                           +invariants
```

651 and 652 can **partially parallelise** — the quiz lib can be scaffolded against fixture sources while migration 013 is still being reviewed.

654 and 655 can **fully parallelise** once 653 is done — observability and QA are independent.

## 17. Effort estimate

| Issue | Solo-developer days | Parallelisable with |
|---|---|---|
| [-651](https://youtrack.example.net/issue/IFRNLLEI01PRD-651) foundation | 1.0 | 652 (partial) |
| [-652](https://youtrack.example.net/issue/IFRNLLEI01PRD-652) intelligence | 1.5 | 651 (partial) |
| [-653](https://youtrack.example.net/issue/IFRNLLEI01PRD-653) interface | 1.0 | — |
| [-654](https://youtrack.example.net/issue/IFRNLLEI01PRD-654) loop | 0.5 | 655 |
| [-655](https://youtrack.example.net/issue/IFRNLLEI01PRD-655) gate | 1.0 | 654 |
| **Total serial** | **5.0** | |
| **Total parallel** | **~3.5** | |

## 18. References

- [`docs/system-as-abstract-agent.md`](../system-as-abstract-agent.md) — the six invariants the teacher-agent must preserve.
- [`docs/agentic-patterns-audit.md`](../agentic-patterns-audit.md) — source material for the "Gulli's 21 patterns" curriculum slice.
- [`docs/runbooks/prompt-patch-trials.md`](../runbooks/prompt-patch-trials.md) — example of a similarly-structured runbook for an active feature.
- [`scripts/lib/circuit_breaker.py`](../../scripts/lib/circuit_breaker.py) — breaker-awareness pattern used by quiz gen/grade.
- [`scripts/lib/schema_version.py`](../../scripts/lib/schema_version.py) — canonical registry; update before shipping migration 013.
- [`docs/runbooks/n8n-code-node-safety.md`](../runbooks/n8n-code-node-safety.md) — mandatory validator gate for matrix-bridge command-parser edit (issue 653).
- OpenAI Agents SDK adoption memory — how the five invariants were derived and what patterns we chose not to adopt.

---

*This plan is a design spec, not a living document. Once the issues close, the truth moves to `docs/runbooks/teacher-agent.md`. This file then remains a historical record of intent.*
