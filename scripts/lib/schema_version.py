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
    "session_risk_audit": 2,         # IFRNLLEI01PRD-1108 (autonomy-forward bands)
    "event_log": 4,                  # -637 → -750 → -749 → -751
    "handoff_log": 1,                # IFRNLLEI01PRD-640
    "session_state_snapshot": 1,     # IFRNLLEI01PRD-636
    "session_turns": 1,              # IFRNLLEI01PRD-638
    "prompt_patch_trial": 1,         # IFRNLLEI01PRD-645
    "session_trial_assignment": 1,   # IFRNLLEI01PRD-645
    "learning_progress": 1,          # IFRNLLEI01PRD-651
    "learning_sessions": 1,          # IFRNLLEI01PRD-651
    "teacher_operator_dm": 1,        # IFRNLLEI01PRD-653
    "long_horizon_replay_results": 1,  # IFRNLLEI01PRD-748
    "infragraph_dynamics": 1,        # IFRNLLEI01PRD-1031
    "infragraph_predictions": 1,     # IFRNLLEI01PRD-1031
    "infragraph_cascade_stats": 1,   # IFRNLLEI01PRD-1118 (cascade-probability gating)
    # JSON-payload / structured tables brought under governance (IFRNLLEI01PRD-1093, 2026-06-16)
    "llm_usage": 1,
    "ragas_evaluation": 1,
    "prompt_scorecard": 1,
    "graph_entities": 1,
    "graph_relationships": 1,
    "otel_spans": 1,
    # No-human eval ground-truth anchors (IFRNLLEI01PRD-1451, 2026-06-27)
    "judge_crosscheck": 1,           # frontier (Opus) vs local-judge cross-check
    "autoresolve_outcome": 1,        # did the auto-resolve's fix actually hold
    "discovered_scheduled_reboots": 1,  # self-learning scheduled-reboot registry (2026-06-29)
    "escalation_queue": 1,           # dropped-escalation requeue lane (2026-07-08)
    "disk_grow_log": 1,              # auto-disk-grow audit+rate-cap ledger (2026-07-08)
    "renovate_autonomy_audit": 1,    # Renovate MR Autonomy lane decisions (IFRNLLEI01PRD-1645, 2026-07-06)
    "master_switch_log": 1,          # master power-switch transition ledger (IFRNLLEI01PRD-1823, 2026-07-17)
}


# ── Per-version change notes ────────────────────────────────────────────────────
# Mirrors OpenAI SDK's SCHEMA_VERSION_SUMMARIES. Every version bump adds a line
# so operators reading an old row can tell what fields existed when it was written.

SCHEMA_VERSION_SUMMARIES: dict[str, dict[int, str]] = {
    "master_switch_log": {
        1: "Initial (IFRNLLEI01PRD-1823, 2026-07-17). One hash-chained row per master "
           "power-switch transition (off/on of the complete agentic system). Columns: ts, "
           "action, mode(soft|hard), operator, reason, hostname, sentinels_json, cronicle_json, "
           "n8n_json, sessions_json, maintenance_action, partial, details_json. Writer/verifier: "
           "scripts/lib/master_switch_audit.py (COLS lockstep).",
    },
    "disk_grow_log": {
        1: "Initial (2026-07-08 disk-autogrow actuator #3). One row per executed grow / refusal / escalation with before/after size, fs %, pool-free %, outcome.",
    },
    "escalation_queue": {
        1: "Initial schema (2026-07-08 escalation-drop defect trio). One row per "
           "dropped-then-queued escalation: kind is 'slot-locked' (Runner Is Locked? "
           "TRUE branch) or 'poll-recheck' (orphaned-poll delayed re-check); status "
           "pending|fired|dropped|recovered; producers queue-escalation.sh + "
           "reconcile-completed-sessions.py, consumer requeue-escalations.py.",
    },
    "renovate_autonomy_audit": {
        1: "Initial (IFRNLLEI01PRD-1645, 2026-07-06). One row per renovate-mr-gate.sh "
           "evaluation. Columns: ts, project_id, mr_iid, mr_title, package_update, tier, "
           "snapshot_required, ci_status, review_verdict, review_confidence, decision, "
           "reason, mode, gates_json, schema_version.",
    },
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
           "embedding is JSON TEXT — json.dumps() of a 768-float list "
           "(nomic-embed-text v1.5), NOT a packed BLOB (contract corrected "
           "IFRNLLEI01PRD-1093, 2026-06-16). source_file is a Claude Code JSONL "
           "path relative to ~/.claude/projects/.",
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
           "tags is a comma-separated list; embedding is JSON TEXT (json.dumps "
           "of a 768-float list), NOT a packed BLOB (IFRNLLEI01PRD-1093).",
    },
    # ── IFRNLLEI01PRD-1093 (2026-06-16): JSON-payload tables brought under governance ──
    "llm_usage": {
        1: "Per-call token/cost ledger. cost_usd holds USD (corrected from EUR, "
           "IFRNLLEI01PRD-1080). tier: 0=local, 1=triage, 2=agent. issue_id may "
           "be '' for legacy/poller rows.",
    },
    "ragas_evaluation": {
        1: "RAG eval rows. retrieved_docs is a JSON array; faithfulness / "
           "context_precision / context_recall / answer_relevance / "
           "semantic_quality are floats (-1 = unset).",
    },
    "prompt_scorecard": {
        1: "Per-dimension prompt grades. feedback is INTEGER (-1 = unset).",
    },
    "graph_entities": {
        1: "GraphRAG / infragraph nodes. attributes is a JSON blob; "
           "entity_type + source_table classify the node.",
    },
    "graph_relationships": {
        1: "GraphRAG / infragraph edges. metadata is a JSON blob; rel_type with "
           "source_id/target_id (convention: SOURCE depends on TARGET).",
    },
    "otel_spans": {
        1: "Local OTel span store (W3C trace context). exported_to_otlp drives "
           "the */5 OpenObserve export. Added to schema.sql in IFRNLLEI01PRD-1093 "
           "(previously defined inline only in export-otel-traces.py).",
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
        2: "Autonomy-forward gate (IFRNLLEI01PRD-1108, 2026-06-16). Added "
           "band (AUTO|AUTO_NOTICE|POLL_PROCEED|POLL_PAUSE), "
           "auto_proceed_on_timeout (int bool), and sms_required (int bool). "
           "All NULL on legacy / flag-off rows. signals_json may now include "
           "'irreversible:*' and 'critical:*' (blast-radius-p0, p0-reboot) "
           "entries when AUTONOMY_FORWARD is set.",
    },
    "event_log": {
        1: "Initial schema (IFRNLLEI01PRD-637, 2026-04-20). 13 event_type "
           "values enumerated in scripts/lib/session_events.py EVENT_TYPES. "
           "payload_json is a JSON object; shape per-event documented in each "
           "SessionEvent subclass.",
        2: "G3 NVIDIA-P1 bump (IFRNLLEI01PRD-750, 2026-04-29). Added "
           "team_charter (payload: category, risk_level, hostname, agents[], "
           "rationale) and its_budget_consumed (payload: budget_s, "
           "observed_turns, observed_thinking_chars, category). 13 → 15 "
           "event_types total. Existing 13 are unchanged.",
        3: "G2 NVIDIA-P0 bump (IFRNLLEI01PRD-749, 2026-04-29). Added "
           "intermediate_rail_check (payload: is_in_distribution, confidence, "
           "signals[], backend). 15 → 16 event_types total. DARK-FIRST "
           "deployment — emits but does not block.",
        4: "G4 NVIDIA-P1 bump (IFRNLLEI01PRD-751, 2026-04-29). Added "
           "session_replay_invoked (payload: outcome, prompt_chars, cost_usd, "
           "num_turns, model). 16 → 17 event_types total. Emitted by the "
           "server-side replay endpoint workflow lJEGboDYLmx25kBo.",
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
    "long_horizon_replay_results": {
        1: "Initial schema (IFRNLLEI01PRD-748, 2026-04-29). One row per "
           "session per replay run. Four scoring dimensions in [0,1]: "
           "trace_coherence (Jaccard of adjacent assistant turns), "
           "tool_efficiency (unique/total tool calls), poll_correctness "
           "(alignment with session_risk_audit), composite_score (mean of "
           "the four). cost_per_turn_z is the z-score against historical "
           "mean — negative is cheaper. run_id is the date-stamped tag "
           "from `scripts/long-horizon-replay.py` (e.g. replay-2026-04-29-0500).",
    },
    "infragraph_dynamics": {
        1: "Initial schema (IFRNLLEI01PRD-1031, 2026-06-09). One row per "
           "infragraph edge (rel_id UNIQUE FK to graph_relationships). "
           "expected_alerts is JSON [{rule, side}]; samples is JSON "
           "{delay_s: [...], recovery_s: [...]} capped at 64 entries each, "
           "from which delay_p50_s/delay_p95_s/recovery_p50_s are recomputed "
           "on every update. source is one of declared|chaos|incident|"
           "netbox|iac. valid_until NULL = open-ended.",
    },
    "infragraph_predictions": {
        1: "Initial schema (IFRNLLEI01PRD-1031, 2026-06-09; action/verdict "
           "columns added pre-merge for the operator-mandated model-based "
           "invariant, IFRNLLEI01PRD-1044/-1045). kind='cascade' rows are "
           "Phase B shadow predictions; kind='action' rows are mandatory "
           "pre-remediation artifacts (plan_hash joins "
           "session_risk_audit.plan_hash — the non-bypassable gate key). "
           "predicted/control_predicted are JSON [{host, rule, "
           "expected_delay_s: {p50, p95}, confidence}]; actual is JSON "
           "[{host, rule, ts}] filled at eval time with tp/fp/fn and "
           "control_tp/control_fp; verdict ('' until verified; "
           "match|partial|deviation) + verdict_detail are written "
           "mechanically by infragraph-verify.py, never by the LLM.",
    },
    "judge_crosscheck": {
        1: "Initial schema (IFRNLLEI01PRD-1451, 2026-06-27). One row per "
           "frontier-vs-local judge cross-check. local_* mirror the row under "
           "test in session_judgment (local_score -1 = the dead-judge signal); "
           "frontier_* are an Opus re-judgment of the same session+rubric. "
           "score_delta = frontier_score - local_score; action_agree = 1 if "
           "the approve/improve/reject recommendations match. No-human anchor.",
    },
    "autoresolve_outcome": {
        1: "Initial schema (IFRNLLEI01PRD-1451, 2026-06-27). One row per "
           "auto-resolved session, keyed UNIQUE on issue_id. held = 1 if the "
           "fix held (the incident's alert did not re-fire within the window), "
           "0 = re-fired (false-resolve; refire_issue_id/refire_within_hours "
           "name the recurrence), -1 = pending (window not elapsed). "
           "judge_score/judge_action copy session_judgment for calibration "
           "(did the judge's verdict predict the real outcome). No-human anchor.",
    },
    "discovered_scheduled_reboots": {
        1: "Self-learning scheduled-reboot registry (2026-06-29). One row per "
           "(hostname, deterministic schedule, reboot_kind). cron_expr is a "
           "5-field cron (cron) OR systemd OnCalendar (systemd-timer) OR the "
           "sentinel 'unattended'/'eem_watchdog'; tz is host-local (timedatectl), "
           "matched DST-correctly via croniter+zoneinfo. The Tier 1 matcher "
           "(scripts/lib/scheduled_reboots.py) reads ONLY status='live' AND "
           "kill_switch=0 AND valid_until>now rows; 'observing' rows never "
           "suppress (must confirm >=2 in-window boots via "
           "promote-scheduled-reboots.py). in_window_observations is a JSON "
           "list of UTC boot timestamps capped at 10. Severity=critical never "
           "suppresses; reboot-class rule allowlist only (config/scheduled-events.json "
           "reboot_rule_patterns).",
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
