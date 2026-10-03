"""Structured HandoffInputData envelope (IFRNLLEI01PRD-640).

Mirrors OpenAI Agents SDK `src/agents/handoffs/__init__.py:142`
(`HandoffInputData`) so T1 -> T2 escalations and sub-agent spawns pass a
serialisable, versioned payload rather than re-deriving context via RAG.

Usage (parent, when escalating):

    from handoff import HandoffInputData, marshal
    env = HandoffInputData(
        issue_id="IFRNLLEI01PRD-123",
        session_id="s-abc",
        from_agent="openclaw-t1",
        to_agent="claude-code-t2",
        handoff_depth=1,
        handoff_chain=["openclaw-t1", "claude-code-t2"],
        input_history=[...],     # prior transcript messages
        pre_handoff_items=[...], # tools already invoked
        new_items=[...],         # items produced in the final turn
        run_context={...},       # approvals, usage counters, etc.
    )
    b64 = env.to_b64()          # opaque, url-safe, ~KB for typical session
    # parent spawns child: os.execv("claude", ..., env={"HANDOFF_INPUT_DATA_B64": b64, ...})
    env.persist_log()            # writes one row to handoff_log

Usage (child, on startup):

    import os
    from handoff import from_env
    env = from_env()             # reads $HANDOFF_INPUT_DATA_B64, returns None if absent
    if env is not None:
        prior_context = env.as_prompt_section()  # formatted markdown
        # inject into agent's initial prompt

The envelope is opt-in: the parent decides when to include it. Sub-agents
that weren't launched with one just get None from `from_env()` and fall back
to re-deriving context from RAG.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import time
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema_version import current as schema_current  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

ENV_VAR = "HANDOFF_INPUT_DATA_B64"


@dataclass
class HandoffInputData:
    """Serialisable envelope carried across a handoff boundary."""

    issue_id: str
    from_agent: str
    to_agent: str
    session_id: str = ""
    handoff_depth: int = 0
    handoff_chain: list[str] = field(default_factory=list)

    # The actual payload. Shape of each item is agent-specific — we don't
    # enforce a schema here (Haiku/gemma sub-agents hallucinate, so we do
    # soft parsing downstream). Consumer responsibility.
    input_history: list[Any] = field(default_factory=list)
    pre_handoff_items: list[Any] = field(default_factory=list)
    new_items: list[Any] = field(default_factory=list)
    run_context: dict[str, Any] = field(default_factory=dict)

    # Flagged by IFRNLLEI01PRD-641 when the compactor ran.
    compaction_applied: bool = False
    compaction_model: str = ""

    reason: str = ""
    envelope_version: int = 1  # bump when the *shape* of this dataclass changes

    # ── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    def to_b64(self) -> str:
        """Compressed, URL-safe base64 encoding for env var transport.

        zlib + urlsafe_b64 keeps typical envelopes under env-var size limits
        (4-8 KiB). For truly large histories (>64 KiB), pair with the
        IFRNLLEI01PRD-641 compactor.
        """
        raw = self.to_json().encode("utf-8")
        compressed = zlib.compress(raw, level=9)
        return base64.urlsafe_b64encode(compressed).decode("ascii")

    @classmethod
    def from_b64(cls, b64: str) -> "HandoffInputData":
        compressed = base64.urlsafe_b64decode(b64.encode("ascii"))
        raw = zlib.decompress(compressed).decode("utf-8")
        data = json.loads(raw)
        # Strict: if envelope_version is newer than this reader knows about,
        # fail fast rather than silently dropping fields.
        if int(data.get("envelope_version", 1)) > 1:
            raise ValueError(
                f"HandoffInputData envelope_version={data.get('envelope_version')} "
                f"unknown; upgrade scripts/lib/handoff.py"
            )
        # Keep only keys that map to dataclass fields.
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def input_history_bytes(self) -> int:
        """Approximate wire size of input_history for handoff_log audit."""
        return len(json.dumps(self.input_history).encode("utf-8"))

    def as_prompt_section(self, max_history_items: int = 50) -> str:
        """Render the envelope as a markdown section for the child agent's prompt.

        Truncates `input_history` to `max_history_items` so a huge parent
        session doesn't drown the child prompt. Pair with gap #9 compaction
        to summarise the older portion.
        """
        parts = [
            "## PRIOR CONTEXT (from " + self.from_agent + ")",
            f"- issue_id: `{self.issue_id}`",
            f"- session_id: `{self.session_id}`",
            f"- handoff_depth: `{self.handoff_depth}` chain: `{self.handoff_chain}`",
        ]
        if self.reason:
            parts.append(f"- reason: {self.reason}")
        if self.compaction_applied:
            parts.append(f"- compaction: applied via `{self.compaction_model}`")
        if self.run_context:
            parts.append("### Inherited run_context")
            parts.append("```json")
            parts.append(json.dumps(self.run_context, indent=2))
            parts.append("```")
        if self.input_history:
            parts.append("### Prior transcript (most recent first)")
            history = self.input_history[-max_history_items:]
            for i, item in enumerate(reversed(history)):
                parts.append(f"- `[{i}]` {json.dumps(item)[:400]}")
        return "\n".join(parts)

    # ── Persistence (handoff_log row) ─────────────────────────────────────────

    def persist_log(self, db_path: Optional[str] = None) -> int:
        """Write one row to handoff_log. Returns the new row id, or -1."""
        conn = sqlite3.connect(db_path or DB_PATH, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.execute(
                """INSERT INTO handoff_log
                    (issue_id, session_id, from_agent, to_agent, handoff_depth,
                     input_history_bytes, compaction_applied, compaction_model,
                     pre_handoff_count, new_items_count, reason, schema_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.issue_id, self.session_id, self.from_agent, self.to_agent,
                    self.handoff_depth, self.input_history_bytes(),
                    1 if self.compaction_applied else 0, self.compaction_model,
                    len(self.pre_handoff_items), len(self.new_items), self.reason,
                    schema_current("handoff_log"),
                ),
            )
            row_id = int(cur.lastrowid or -1)
            conn.commit()
            return row_id
        except sqlite3.Error as e:
            print(f"[handoff] persist_log failed: {e}", file=sys.stderr)
            return -1
        finally:
            conn.close()


# ── Env-var helpers (for the CLI boundary) ───────────────────────────────────


def to_env(env: HandoffInputData, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build a dict suitable for `os.execve`-style env injection."""
    out = dict(os.environ)
    if extra:
        out.update(extra)
    out[ENV_VAR] = env.to_b64()
    return out


def from_env(env: Optional[dict[str, str]] = None) -> Optional[HandoffInputData]:
    """Read the envelope from the process env. Returns None if absent."""
    src = env or os.environ
    b64 = src.get(ENV_VAR)
    if not b64:
        return None
    try:
        return HandoffInputData.from_b64(b64)
    except Exception as e:
        print(f"[handoff] from_env decode failed: {e}", file=sys.stderr)
        return None


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli() -> int:
    """`python3 -m lib.handoff {pack|unpack|log}` for shell integration."""
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pack = sub.add_parser("pack", help="read JSON on stdin, write b64 envelope to stdout")
    p_pack.add_argument("--issue", required=True)
    p_pack.add_argument("--from", dest="from_agent", required=True)
    p_pack.add_argument("--to", dest="to_agent", required=True)
    p_pack.add_argument("--session", default="")
    p_pack.add_argument("--depth", type=int, default=0)
    p_pack.add_argument("--chain", default="[]", help="JSON array of agent names")
    p_pack.add_argument("--reason", default="")
    p_pack.add_argument("--persist", action="store_true", help="also write handoff_log row")

    p_unpack = sub.add_parser("unpack",
                              help="read b64 on stdin or $HANDOFF_INPUT_DATA_B64, write JSON to stdout")
    p_unpack.add_argument("--pretty", action="store_true")

    p_section = sub.add_parser("section",
                               help="render envelope as markdown prompt section")
    p_section.add_argument("--max-history", type=int, default=50)

    args = ap.parse_args()

    if args.cmd == "pack":
        stdin_payload = json.loads(sys.stdin.read() or "{}")
        env = HandoffInputData(
            issue_id=args.issue,
            session_id=args.session,
            from_agent=args.from_agent,
            to_agent=args.to_agent,
            handoff_depth=args.depth,
            handoff_chain=json.loads(args.chain),
            input_history=stdin_payload.get("input_history", []),
            pre_handoff_items=stdin_payload.get("pre_handoff_items", []),
            new_items=stdin_payload.get("new_items", []),
            run_context=stdin_payload.get("run_context", {}),
            reason=args.reason,
        )
        if args.persist:
            env.persist_log()
        sys.stdout.write(env.to_b64())
        return 0

    if args.cmd == "unpack":
        b64 = sys.stdin.read().strip() or os.environ.get(ENV_VAR, "")
        if not b64:
            print("no envelope on stdin or $HANDOFF_INPUT_DATA_B64", file=sys.stderr)
            return 2
        env = HandoffInputData.from_b64(b64)
        if args.pretty:
            json.dump(env.to_dict(), sys.stdout, indent=2, sort_keys=True)
        else:
            json.dump(env.to_dict(), sys.stdout, separators=(",", ":"), sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if args.cmd == "section":
        env = from_env()
        if env is None:
            print("# (no HANDOFF_INPUT_DATA_B64 in env; nothing to render)")
            return 0
        print(env.as_prompt_section(max_history_items=args.max_history))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(_cli())
