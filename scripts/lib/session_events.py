"""Typed session event taxonomy (IFRNLLEI01PRD-637).

Mirrors the OpenAI Agents SDK `stream_events.py` taxonomy
(`RunItemStreamEvent` subtypes) so our Matrix / DB / Grafana layers speak the
same structured vocabulary instead of ad-hoc progress strings.

Each event subclass knows its own event_type string and exposes a uniform
`.to_row()` mapping that lines up 1:1 with the columns of the `event_log`
table. All events are persisted by `emit(event)` which writes to SQLite.

Usage (Python):

    from session_events import (
        emit, ToolStartedEvent, ToolEndedEvent, HandoffRequestedEvent,
    )
    emit(ToolStartedEvent(
        issue_id="IFRNLLEI01PRD-123",
        session_id="abc",
        turn_id=5,
        tool_name="Bash",
        tool_use_id="toolu_01",
        arguments={"command": "kubectl get pods"},
    ))

Usage (CLI, for bash hooks):

    scripts/emit-event.py --type tool_started \\
        --issue IFRNLLEI01PRD-123 --session abc --turn 5 \\
        --payload-json '{"tool_name":"Bash","tool_use_id":"toolu_01"}'

Event types mirror OpenAI SDK's RunItemStreamEvent subtypes. Bump
schema_version in scripts/lib/schema_version.py -> CURRENT_SCHEMA_VERSION
if you add / remove / rename required payload fields.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

# IFRNLLEI01PRD-635: versioned event_log rows.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema_version import current as schema_current  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)


# ── Base event ──────────────────────────────────────────────────────────────────


@dataclass
class SessionEvent:
    """Base type. Concrete subclasses set event_type + payload fields."""

    # Correlation — None/'' means "not applicable at this emit site".
    issue_id: str = ""
    session_id: str = ""
    turn_id: int = -1
    agent_name: str = ""

    # Perf — populated by subclasses that wrap a completed action.
    duration_ms: int = -1
    exit_code: int = 0

    # Subclasses override these two.
    event_type: str = field(default="", init=False)

    def _payload(self) -> dict[str, Any]:
        """Return the event-specific payload dict (excl. correlation fields)."""
        raise NotImplementedError

    def to_row(self) -> dict[str, Any]:
        """Shape that lines up with event_log columns."""
        return {
            "issue_id": self.issue_id,
            "session_id": self.session_id,
            "turn_id": int(self.turn_id),
            "agent_name": self.agent_name,
            "event_type": self.event_type,
            "payload_json": json.dumps(self._payload(), sort_keys=True),
            "duration_ms": int(self.duration_ms),
            "exit_code": int(self.exit_code),
            "schema_version": schema_current("event_log")
            if "event_log" in _known_tables()
            else 1,
        }


def _known_tables() -> set[str]:
    # Lazy lookup — avoids importing schema_version at collect-time.
    try:
        from schema_version import CURRENT_SCHEMA_VERSION  # noqa: E402
        return set(CURRENT_SCHEMA_VERSION.keys())
    except Exception:
        return set()


# ── Concrete events ────────────────────────────────────────────────────────────


@dataclass
class ToolStartedEvent(SessionEvent):
    """A tool is about to execute. Mirrors OpenAI SDK `tool_called`."""

    tool_name: str = ""
    tool_use_id: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.event_type = "tool_started"

    def _payload(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "arguments": self.arguments,
        }


@dataclass
class ToolEndedEvent(SessionEvent):
    """A tool finished. Mirrors OpenAI SDK `tool_output`."""

    tool_name: str = ""
    tool_use_id: str = ""
    output_size: int = 0
    error_type: str = ""

    def __post_init__(self):
        self.event_type = "tool_ended"

    def _payload(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "output_size": self.output_size,
            "error_type": self.error_type,
        }


@dataclass
class HandoffRequestedEvent(SessionEvent):
    """Agent A requests handoff to Agent B. Mirrors `handoff_requested`.

    Carries the handoff_depth (IFRNLLEI01PRD-643) at request time so cycle
    detection can report what depth a potential cycle formed at.
    """

    from_agent: str = ""
    to_agent: str = ""
    handoff_depth: int = 0
    handoff_chain: list[str] = field(default_factory=list)
    reason: str = ""

    def __post_init__(self):
        self.event_type = "handoff_requested"

    def _payload(self) -> dict[str, Any]:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "handoff_depth": self.handoff_depth,
            "handoff_chain": self.handoff_chain,
            "reason": self.reason,
        }


@dataclass
class HandoffCompletedEvent(SessionEvent):
    """The target agent started running after a handoff."""

    from_agent: str = ""
    to_agent: str = ""
    handoff_depth: int = 0

    def __post_init__(self):
        self.event_type = "handoff_completed"

    def _payload(self) -> dict[str, Any]:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "handoff_depth": self.handoff_depth,
        }


@dataclass
class HandoffCycleDetectedEvent(SessionEvent):
    """IFRNLLEI01PRD-643: the same agent appeared twice in the handoff chain."""

    from_agent: str = ""
    to_agent: str = ""
    handoff_chain: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.event_type = "handoff_cycle_detected"

    def _payload(self) -> dict[str, Any]:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "handoff_chain": self.handoff_chain,
        }


@dataclass
class HandoffCompactionEvent(SessionEvent):
    """IFRNLLEI01PRD-641: transcript was compacted on a handoff."""

    pre_bytes: int = 0
    post_bytes: int = 0
    model: str = ""

    def __post_init__(self):
        self.event_type = "handoff_compaction"

    def _payload(self) -> dict[str, Any]:
        return {
            "pre_bytes": self.pre_bytes,
            "post_bytes": self.post_bytes,
            "model": self.model,
            "ratio": round(self.post_bytes / self.pre_bytes, 3)
            if self.pre_bytes
            else 0.0,
        }


@dataclass
class ReasoningItemCreatedEvent(SessionEvent):
    """Extended thinking block emitted by Claude. Mirrors `reasoning_item_created`."""

    thinking_chars: int = 0
    uncertainty_phrases: list[str] = field(default_factory=list)
    led_to_tool_call: bool = False

    def __post_init__(self):
        self.event_type = "reasoning_item_created"

    def _payload(self) -> dict[str, Any]:
        return {
            "thinking_chars": self.thinking_chars,
            "uncertainty_phrases": self.uncertainty_phrases,
            "led_to_tool_call": self.led_to_tool_call,
        }


@dataclass
class MCPApprovalRequestedEvent(SessionEvent):
    """An approval gate was emitted ([POLL] / [AUTO-RESOLVE] / m.poll.start).

    Mirrors OpenAI SDK `mcp_approval_requested`.
    """

    gate_type: str = "poll"  # poll | auto_resolve | human_review | confidence_threshold
    options: list[str] = field(default_factory=list)
    confidence: float = -1.0

    def __post_init__(self):
        self.event_type = "mcp_approval_requested"

    def _payload(self) -> dict[str, Any]:
        return {
            "gate_type": self.gate_type,
            "options": self.options,
            "confidence": self.confidence,
        }


@dataclass
class MCPApprovalResponseEvent(SessionEvent):
    """An approval gate was resolved. Mirrors `mcp_approval_response`."""

    gate_type: str = "poll"
    choice: str = ""
    responder: str = ""

    def __post_init__(self):
        self.event_type = "mcp_approval_response"

    def _payload(self) -> dict[str, Any]:
        return {
            "gate_type": self.gate_type,
            "choice": self.choice,
            "responder": self.responder,
        }


@dataclass
class AgentUpdatedEvent(SessionEvent):
    """Active agent changed (mode flip, bridge routing). Mirrors `agent_updated`."""

    previous_agent: str = ""

    def __post_init__(self):
        self.event_type = "agent_updated"

    def _payload(self) -> dict[str, Any]:
        return {"previous_agent": self.previous_agent}


@dataclass
class MessageOutputEvent(SessionEvent):
    """Assistant produced a visible message to the user. Mirrors `message_output_created`."""

    chars: int = 0
    has_confidence_tag: bool = False
    has_poll_tag: bool = False

    def __post_init__(self):
        self.event_type = "message_output_created"

    def _payload(self) -> dict[str, Any]:
        return {
            "chars": self.chars,
            "has_confidence_tag": self.has_confidence_tag,
            "has_poll_tag": self.has_poll_tag,
        }


@dataclass
class ToolGuardrailRejectionEvent(SessionEvent):
    """IFRNLLEI01PRD-639: a PreToolUse hook rejected or deny'd a tool call.

    `behavior` is one of `allow` / `reject_content` / `deny`, matching the
    OpenAI SDK `ToolGuardrailFunctionOutput` taxonomy.
    """

    tool_name: str = ""
    behavior: str = "deny"  # allow | reject_content | deny
    message: str = ""
    signals: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.event_type = "tool_guardrail_rejection"

    def _payload(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "behavior": self.behavior,
            "message": self.message,
            "signals": self.signals,
        }


@dataclass
class AgentAsToolCallEvent(SessionEvent):
    """IFRNLLEI01PRD-642: a sub-agent was invoked via the agent-as-tool surface."""

    sub_agent: str = ""
    input_bytes: int = 0
    output_bytes: int = 0
    confidence: float = -1.0

    def __post_init__(self):
        self.event_type = "agent_as_tool_call"

    def _payload(self) -> dict[str, Any]:
        return {
            "sub_agent": self.sub_agent,
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "confidence": self.confidence,
        }


# Keep this list authoritative — add new subclasses here so the emit-event CLI
# can validate --type against it, and Prometheus scrapers can enumerate.
EVENT_TYPES = (
    "tool_started",
    "tool_ended",
    "handoff_requested",
    "handoff_completed",
    "handoff_cycle_detected",
    "handoff_compaction",
    "reasoning_item_created",
    "mcp_approval_requested",
    "mcp_approval_response",
    "agent_updated",
    "message_output_created",
    "tool_guardrail_rejection",
    "agent_as_tool_call",
)


_EVENT_CLASSES = {
    "tool_started": ToolStartedEvent,
    "tool_ended": ToolEndedEvent,
    "handoff_requested": HandoffRequestedEvent,
    "handoff_completed": HandoffCompletedEvent,
    "handoff_cycle_detected": HandoffCycleDetectedEvent,
    "handoff_compaction": HandoffCompactionEvent,
    "reasoning_item_created": ReasoningItemCreatedEvent,
    "mcp_approval_requested": MCPApprovalRequestedEvent,
    "mcp_approval_response": MCPApprovalResponseEvent,
    "agent_updated": AgentUpdatedEvent,
    "message_output_created": MessageOutputEvent,
    "tool_guardrail_rejection": ToolGuardrailRejectionEvent,
    "agent_as_tool_call": AgentAsToolCallEvent,
}


# ── Emit (the single write path) ───────────────────────────────────────────────


def emit(event: SessionEvent, db_path: Optional[str] = None) -> int:
    """Write `event` to event_log. Returns the new row id, or -1 on soft error.

    Soft error = event_log table missing (fresh install before migration) or
    transient sqlite lock. We never raise — a telemetry emit should not kill
    the caller. Lookup lets the caller detect loss via a return value check
    if desired.
    """
    row = event.to_row()
    path = db_path or DB_PATH
    try:
        conn = sqlite3.connect(path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.execute(
            """INSERT INTO event_log
                (issue_id, session_id, turn_id, agent_name, event_type,
                 payload_json, duration_ms, exit_code, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["issue_id"],
                row["session_id"],
                row["turn_id"],
                row["agent_name"],
                row["event_type"],
                row["payload_json"],
                row["duration_ms"],
                row["exit_code"],
                row["schema_version"],
            ),
        )
        row_id = int(cur.lastrowid or -1)
        conn.commit()
        conn.close()
        return row_id
    except sqlite3.Error as e:
        # Don't kill the caller on telemetry failure — log to stderr and move on.
        print(f"[session_events] emit failed ({event.event_type}): {e}", file=sys.stderr)
        return -1


def emit_raw(event_type: str, payload: dict[str, Any], **correlation: Any) -> int:
    """Bypass the dataclass layer — used by the bash-facing CLI.

    `payload` is written verbatim into payload_json. Known correlation fields
    (`issue_id`, `session_id`, `turn_id`, `agent_name`, `duration_ms`, `exit_code`)
    are pulled from `correlation`. Validates event_type against EVENT_TYPES.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"Unknown event_type {event_type!r}. Known: {', '.join(EVENT_TYPES)}"
        )
    conn = sqlite3.connect(DB_PATH, timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.execute(
            """INSERT INTO event_log
                (issue_id, session_id, turn_id, agent_name, event_type,
                 payload_json, duration_ms, exit_code, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                correlation.get("issue_id", ""),
                correlation.get("session_id", ""),
                int(correlation.get("turn_id", -1)),
                correlation.get("agent_name", ""),
                event_type,
                json.dumps(payload, sort_keys=True),
                int(correlation.get("duration_ms", -1)),
                int(correlation.get("exit_code", 0)),
                schema_current("event_log"),
            ),
        )
        row_id = int(cur.lastrowid or -1)
        conn.commit()
        return row_id
    finally:
        conn.close()


# ── CLI (for bash hooks) ───────────────────────────────────────────────────────


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Emit a typed session event to event_log.")
    ap.add_argument("--type", required=True, choices=EVENT_TYPES, help="event_type")
    ap.add_argument("--issue", default="", help="issue_id")
    ap.add_argument("--session", default="", help="session_id")
    ap.add_argument("--turn", type=int, default=-1, help="turn_id")
    ap.add_argument("--agent", default="", help="agent_name")
    ap.add_argument("--duration-ms", type=int, default=-1)
    ap.add_argument("--exit-code", type=int, default=0)
    ap.add_argument("--payload-json", default="{}",
                    help="JSON dict of event-specific payload fields")
    args = ap.parse_args()
    try:
        payload = json.loads(args.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("--payload-json must decode to an object")
    except ValueError as e:
        print(f"[session_events] bad --payload-json: {e}", file=sys.stderr)
        return 2
    row_id = emit_raw(
        args.type,
        payload,
        issue_id=args.issue,
        session_id=args.session,
        turn_id=args.turn,
        agent_name=args.agent,
        duration_ms=args.duration_ms,
        exit_code=args.exit_code,
    )
    print(row_id)
    return 0 if row_id > 0 else 1


if __name__ == "__main__":
    sys.exit(_cli())
