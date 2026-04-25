"""Schema version registry for gateway.db session tables (IFRNLLEI01PRD-635).

Adopts the discipline from OpenAI Agents SDK `src/agents/run_state.py:131`:
a central CURRENT_SCHEMA_VERSION dict + per-version summaries, so writer/reader
shape drift is caught instead of silently corrupting session replay.

Every INSERT into a versioned table must stamp schema_version=CURRENT. Readers
that decode structured columns (session_transcripts.content, execution_log.pre_state,
agent_diary.entry, session_judgment.scores_json, etc.) call check_row() to
fail-fast if they encounter a row written by a newer schema than they understand.

Usage (writer):

    from lib.schema_version import CURRENT_SCHEMA_VERSION as CSV
    conn.execute(
        "INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, schema_version) "
        "VALUES (?,?,?,?,?,?)",
        (issue_id, session_id, idx, role, content, CSV["session_transcripts"]),
    )

Usage (reader):

    from lib.schema_version import check_row
    for row in rows:
        check_row("session_transcripts", row["schema_version"])
        # ... decode row safely

Registry maintenance: whenever you change the JSON shape of a payload column,
bump the version for that table AND add an entry to SCHEMA_VERSION_SUMMARIES
describing what changed (mirror the OpenAI SDK's documentation discipline).
"""
from __future__ import annotations

import json
import sys
from typing import Any

# ── Current schema version per table ────────────────────────────────────────────
# Bump a value here when you change the shape of any versioned column in that
# table. Readers will refuse to decode rows with version > their compiled CURRENT.

CURRENT_SCHEMA_VERSION: dict[str, int] = {
    "sessions": 1,
    "session_log": 1,
    "session_transcripts": 1,
    "execution_log": 1,
    "tool_call_log": 1,
    "agent_diary": 1,
    "session_trajectory": 1,
    "session_judgment": 1,
    "session_risk_audit": 1,
    "event_log": 1,                  # IFRNLLEI01PRD-637
    "handoff_log": 1,                # IFRNLLEI01PRD-640
    "session_state_snapshot": 1,     # IFRNLLEI01PRD-636
    "session_turns": 1,              # IFRNLLEI01PRD-638
    "prompt_patch_trial": 1,         # IFRNLLEI01PRD-645
    "session_trial_assignment": 1,   # IFRNLLEI01PRD-645
    "learning_progress": 1,          # IFRNLLEI01PRD-651
    "learning_sessions": 1,          # IFRNLLEI01PRD-651
    "teacher_operator_dm": 1,        # IFRNLLEI01PRD-653
}


# ── Per-version change notes ────────────────────────────────────────────────────
# Mirrors OpenAI SDK's SCHEMA_VERSION_SUMMARIES. Every version bump adds a line
# so operators reading an old row can tell what fields existed when it was written.

SCHEMA_VERSION_SUMMARIES: dict[str, dict[int, str]] = {
    "sessions": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635, 2026-04-20). Columns: "
           "issue_id, issue_title, session_id, trace_id, started_at, last_active, "
           "message_count, paused, is_current, last_response_b64, cost_usd, "
           "num_turns, duration_seconds, confidence, prompt_variant, "
           "alert_category, retry_count, retry_improved, prompt_surface, "
           "subsystem, model, schema_version.",
    },
    "session_log": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635). Session-end snapshot "
           "of a sessions row with outcome + resolution_type.",
    },
    "session_transcripts": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635). content is free text; "
           "embedding is a BLOB (nomic-embed-text v1.5 768-dim, little-endian "
           "float32). source_file is a Claude Code JSONL path relative to "
           "~/.claude/projects/.",
    },
    "execution_log": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635). pre_state is free text "
           "(command output at capture time); rollback_command is a shell string.",
    },
    "tool_call_log": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635). tool_name matches "
           "Claude Code's tool identifier (e.g. Bash, Edit, Read, Grep).",
    },
    "agent_diary": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635). entry is free text; "
           "tags is a comma-separated list; embedding is a BLOB.",
    },
    "session_trajectory": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635). Score per step along "
           "an 8-infra-step (or 4-dev-step) trajectory rubric.",
    },
    "session_judgment": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635). scores_json is a dict "
           "of 5 LLM-as-judge dimensions -> {score: float, rationale: str}.",
    },
    "session_risk_audit": {
        1: "Initial versioned schema (IFRNLLEI01PRD-635, prior to this ticket "
           "the table existed unversioned). signals_json is a JSON array of "
           "named risk signals emitted by classify-session-risk.py.",
    },
    "event_log": {
        1: "Initial schema (IFRNLLEI01PRD-637, 2026-04-20). 13 event_type "
           "values enumerated in scripts/lib/session_events.py EVENT_TYPES. "
           "payload_json is a JSON object; shape per-event documented in each "
           "SessionEvent subclass.",
    },
    "handoff_log": {
        1: "Initial schema (IFRNLLEI01PRD-640, 2026-04-20). One row per "
           "T1->T2 escalation or sub-agent spawn. input_history_bytes and "
           "compaction_applied capture the handoff payload envelope size "
           "and whether IFRNLLEI01PRD-641 compaction ran.",
    },
    "session_state_snapshot": {
        1: "Initial schema (IFRNLLEI01PRD-636, 2026-04-20). snapshot_data "
           "is a JSON dict capturing (session_id, turn_id, pending_tool, "
           "context_usage, last_response_b64) taken BEFORE each tool call.",
    },
    "session_turns": {
        1: "Initial schema (IFRNLLEI01PRD-638, 2026-04-20). One row per turn. "
           "Tracks turn-level cost, tokens, and tool_count so dashboards can "
           "surface per-turn trending without reparsing JSONL.",
    },
    "prompt_patch_trial": {
        1: "Initial schema (IFRNLLEI01PRD-645, 2026-04-20). One row per trial. "
           "candidates_json is a list of {idx, label, instruction, category}. "
           "variant_idx=-1 in session_trial_assignment means the control arm "
           "(no patch). Unique active-per-(surface,dimension) enforced by "
           "partial index so arms stay comparable.",
    },
    "session_trial_assignment": {
        1: "Initial schema (IFRNLLEI01PRD-645, 2026-04-20). One row per "
           "(session, trial). variant_idx is deterministically hashed at "
           "Build Prompt time so re-runs of the same issue always pick the "
           "same arm. UNIQUE(issue_id, trial_id).",
    },
    "learning_progress": {
        1: "Initial schema (IFRNLLEI01PRD-651, 2026-04-20). One row per "
           "(operator, topic). SM-2 scheduler state (easiness_factor, "
           "interval_days, repetition_count) + mastery_score + "
           "highest_bloom_reached across the 7-level Bloom progression "
           "(recall → teaching_back). source_hash is BLAKE2b of the "
           "concatenated curriculum sources at mastery time — mismatch "
           "flags needs_review=1.",
    },
    "learning_sessions": {
        1: "Initial schema (IFRNLLEI01PRD-651, 2026-04-20). Append-only "
           "audit of every lesson/quiz/review/teaching_back interaction. "
           "question_payload is JSON {question_text, source_snippets[], "
           "rubric}; answer_payload is JSON {answer_text, submitted_at}; "
           "quiz_score is 0.0-1.0 as graded by the LLM-as-judge, mapped "
           "to SM-2 quality via round(score * 5).",
    },
    "teacher_operator_dm": {
        1: "Initial schema (IFRNLLEI01PRD-653, 2026-04-20). One row per "
           "multi-user classroom member. operator_mxid is the Matrix user "
           "identifier; dm_room_id is the Matrix room id of the lazy-created "
           "DM between the bot and that user. public_sharing=1 is opt-in: "
           "only then does the operator appear in !leaderboard / !class-digest "
           "per-user breakdowns. Default 0 = privacy-first.",
    },
}


# ── Exceptions ──────────────────────────────────────────────────────────────────


class SchemaVersionError(RuntimeError):
    """Raised when a row is written by a newer schema than the reader understands."""


class UnknownTableError(KeyError):
    """Raised when a caller asks about a table not in the registry."""


# ── Helpers ─────────────────────────────────────────────────────────────────────


def current(table: str) -> int:
    """Return the current schema version for `table`.

    Raises UnknownTableError if the table isn't in the registry — callers that
    INSERT into a table must either register it here or explicitly opt out.
    """
    try:
        return CURRENT_SCHEMA_VERSION[table]
    except KeyError as e:
        raise UnknownTableError(
            f"Table {table!r} is not in the schema_version registry. "
            f"Add it to scripts/lib/schema_version.py:CURRENT_SCHEMA_VERSION "
            f"before writing rows."
        ) from e


def stamp(row: dict[str, Any], table: str) -> dict[str, Any]:
    """Return `row` with schema_version set to the current version for `table`.

    Does not mutate the input. Use when building a dict before passing to an
    INSERT that takes a dict (e.g. sqlite3 named-parameter binding).
    """
    out = dict(row)
    out["schema_version"] = current(table)
    return out


def check_row(table: str, row_version: int | None) -> None:
    """Fail-fast if a row was written by a newer schema than this reader knows.

    Rows with row_version=None (legacy pre-IFRNLLEI01PRD-635 rows before the
    migration back-filled them) are treated as version 1 — the oldest version.
    Rows with row_version > current(table) raise SchemaVersionError so callers
    stop rather than silently mis-decoding a payload shape they haven't seen.
    """
    cur = current(table)
    eff = 1 if row_version is None else int(row_version)
    if eff > cur:
        raise SchemaVersionError(
            f"{table}: row written by schema_version={eff}, reader understands "
            f"up to {cur}. Upgrade scripts/lib/schema_version.py and the decode "
            f"path before reading rows from this database."
        )


def summarize(table: str, version: int) -> str:
    """Human-readable summary for a given (table, version) pair."""
    try:
        return SCHEMA_VERSION_SUMMARIES[table][version]
    except KeyError:
        return f"(no summary recorded for {table} v{version})"


# ── CLI (inspection) ────────────────────────────────────────────────────────────


def _cli() -> int:
    """`python3 -m lib.schema_version` prints the full registry as JSON."""
    out = {
        "current": CURRENT_SCHEMA_VERSION,
        "summaries": {
            t: {str(v): SCHEMA_VERSION_SUMMARIES.get(t, {}).get(v, "") for v in versions}
            for t, versions in {
                t: list(SCHEMA_VERSION_SUMMARIES.get(t, {}).keys())
                for t in CURRENT_SCHEMA_VERSION
            }.items()
        },
    }
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
