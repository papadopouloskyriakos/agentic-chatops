#!/usr/bin/env python3
"""Agent-as-tool wrapper (IFRNLLEI01PRD-642).

Wraps `.claude/agents/*.md` sub-agent definitions so a parent Claude (or
the Build Prompt risk-classifier branch) can invoke them as structured
tool calls — mirroring the OpenAI Agents SDK `@function_tool` pattern but
on top of the Claude Code CLI.

Three layers:
  1. **Registry** — discovers .claude/agents/*.md files, parses the YAML
     frontmatter, exposes a `list()` / `describe(name)` API.
  2. **Invoker** — spawns `claude -p` with the sub-agent's system-prompt
     and the caller's tool-input; streams JSONL output back; returns
     a structured result {summary, confidence, findings, raw_output}.
  3. **Envelope** — optionally passes a HandoffInputData via env var so
     the sub-agent sees the parent's context (IFRNLLEI01PRD-640).
     Also enforces the handoff depth ceiling (IFRNLLEI01PRD-643).

Does NOT replace the deterministic `Task(subagent_type=...)` path used by
Build Prompt. It's an ADDITIONAL surface for the ambiguous-risk band
(0.4 <= risk <= 0.6) where the LLM should decide whether to escalate.

Usage (JSON on stdin):

    echo '{"agent":"triage-researcher","prompt":"Investigate nl-pve01 down","parent_agent":"claude-code-t2","issue_id":"IFRNLLEI01PRD-400"}' \\
      | scripts/agent_as_tool.py

Returns JSON on stdout:

    {
      "agent": "triage-researcher",
      "summary": "...",
      "confidence": 0.72,
      "findings": ["..."],
      "new_items": [...],
      "duration_ms": 48000,
      "exit_code": 0
    }
"""
from __future__ import annotations

import argparse
import json
import os
REDACTED_a7b84d63
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from handoff import HandoffInputData  # noqa: E402
from handoff_depth import bump as bump_depth  # noqa: E402
from handoff_depth import HandoffCycleDetected, HandoffDepthExceeded  # noqa: E402
from session_events import AgentAsToolCallEvent, emit  # noqa: E402

AGENTS_DIR = Path(
    os.environ.get(
        "CLAUDE_AGENTS_DIR",
        "/app/claude-gateway/.claude/agents",
    )
)
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/home/app-user/.local/bin/claude")
DEFAULT_TIMEOUT = int(os.environ.get("AGENT_AS_TOOL_TIMEOUT", "300"))


# ── Registry ───────────────────────────────────────────────────────────────────


@dataclass
class AgentSpec:
    name: str
    description: str
    model: str = "haiku"
    tools: list[str] = field(default_factory=list)
    max_turns: int = 15
    effort: str = "medium"
    body: str = ""  # the markdown body after the frontmatter

    @classmethod
    def from_path(cls, p: Path) -> Optional["AgentSpec"]:
        text = p.read_text()
        if not text.startswith("---"):
            return None
        parts = text.split("---", 2)
        if len(parts) < 3:
            return None
        front = parts[1]
        body = parts[2].lstrip()
        meta: dict[str, Any] = {}
        for line in front.splitlines():
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip()
            meta[key] = val
        # Multi-line `description: >` folded style — strip the leading `>` and
        # collapse runs of whitespace. The simple parser above already pulled
        # the first line; append continuation lines that start with whitespace.
        # Good enough for our formats; switch to pyyaml if we add more shapes.
        raw_tools = meta.get("tools", "").strip()
        # Accept either CSV (`Read, Grep, ...`) or YAML-list (`[Read, Grep, ...]`)
        # frontmatter shapes; strip outer brackets before splitting.
        if raw_tools.startswith("[") and raw_tools.endswith("]"):
            raw_tools = raw_tools[1:-1]
        tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
        return cls(
            name=meta.get("name", p.stem),
            description=meta.get("description", "").strip(">").strip() or meta.get("name", ""),
            model=meta.get("model", "haiku"),
            tools=tools,
            max_turns=int(meta.get("maxTurns", 15) or 15),
            effort=meta.get("effort", "medium"),
            body=body,
        )


def registry() -> dict[str, AgentSpec]:
    out: dict[str, AgentSpec] = {}
    if not AGENTS_DIR.is_dir():
        return out
    for p in sorted(AGENTS_DIR.glob("*.md")):
        spec = AgentSpec.from_path(p)
        if spec is not None:
            out[spec.name] = spec
    return out


# ── Result parsing ─────────────────────────────────────────────────────────────


CONFIDENCE_RE = re.compile(
    r"CONFIDENCE[\s:\-\u2013\u2014]+(\d+(?:\.\d+)?)", re.IGNORECASE
)


def _parse_result(raw_stdout: str) -> dict[str, Any]:
    """Pull confidence, findings list, summary from the sub-agent's JSONL output.

    We look for the terminal `{"type":"result",...}` JSONL record (Claude
    Code's stream-json format) and extract its `result` text. Soft parse:
    if Claude returns plain text, we still pull `CONFIDENCE: 0.X` and split
    bullet lines into findings.
    """
    summary = ""
    # Scan JSONL lines from the end for the result record.
    for line in reversed(raw_stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("type") == "result":
                summary = obj.get("result") or ""
                break
        except (ValueError, TypeError):
            continue
    if not summary:
        # Fallback: treat whole stdout as the summary.
        summary = raw_stdout.strip()

    confidence = -1.0
    m = CONFIDENCE_RE.search(summary or "")
    if m:
        try:
            confidence = float(m.group(1))
        except ValueError:
            confidence = -1.0

    findings: list[str] = []
    for line in (summary or "").splitlines():
        line = line.strip()
        if line.startswith(("-", "*", "•")):
            findings.append(line.lstrip("-*• ").strip())
    findings = [f for f in findings if f][:20]

    return {
        "summary": summary,
        "confidence": confidence,
        "findings": findings,
    }


# ── Invoker ────────────────────────────────────────────────────────────────────


def invoke(
    agent: str,
    prompt: str,
    *,
    issue_id: str = "",
    parent_agent: str = "claude-code-t2",
    handoff_data: Optional[HandoffInputData] = None,
    timeout: int = DEFAULT_TIMEOUT,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Spawn the sub-agent and return a structured result.

    Enforces handoff depth + cycle detection via scripts/lib/handoff_depth.py.
    On HandoffCycleDetected or HandoffDepthExceeded we return an error result
    rather than spawning (so the parent can fall back gracefully).
    """
    reg = registry()
    if agent not in reg:
        return {
            "agent": agent,
            "error": f"agent not found; known: {sorted(reg)}",
            "exit_code": 2,
        }
    spec = reg[agent]

    # Depth gate — attempt the bump first; if it raises, abort without spawning.
    depth_info: dict[str, Any] = {"handoff_depth": 0, "handoff_chain": [parent_agent, agent]}
    if issue_id:
        if dry_run:
            # Compute what the bump would do, but don't persist.
            from handoff_depth REDACTED_a7b84d63ad as read_depth, next_state as next_depth
            cur = read_depth(issue_id)
            nxt = next_depth(cur, agent)
            depth_info = {
                "handoff_depth": nxt.depth,
                "handoff_chain": nxt.chain,
                "would_poll": nxt.should_poll,
                "would_halt": nxt.should_halt,
                "cycle_agent": nxt.cycle_agent,
            }
            if nxt.cycle_agent is not None:
                return {"agent": agent, "error": f"would cycle on {nxt.cycle_agent!r}",
                        "exit_code": 3, "depth_info": depth_info}
            if nxt.depth >= 10:
                return {"agent": agent, "error": f"would halt at depth {nxt.depth}",
                        "exit_code": 4, "depth_info": depth_info}
        else:
            try:
                state = bump_depth(
                    issue_id=issue_id,
                    from_agent=parent_agent,
                    to_agent=agent,
                    reason=f"agent_as_tool invocation of {agent}",
                )
                depth_info = {
                    "handoff_depth": state.depth,
                    "handoff_chain": state.chain,
                }
            except HandoffCycleDetected as e:
                return {"agent": agent, "error": f"cycle: {e}", "exit_code": 3}
            except HandoffDepthExceeded as e:
                return {"agent": agent, "error": f"depth: {e}", "exit_code": 4}

    # Build the sub-agent prompt: [system body] + [parent context, if any] + [caller prompt].
    prompt_parts = [spec.body.strip()]
    if handoff_data is not None:
        prompt_parts.append(handoff_data.as_prompt_section(max_history_items=20))
    prompt_parts.append(f"## TASK FROM PARENT ({parent_agent})\n\n{prompt.strip()}")
    full_prompt = "\n\n".join(prompt_parts)

    cmd = [
        CLAUDE_BIN, "-p", full_prompt,
        "--output-format", "stream-json", "--verbose",
        # max turns from spec; Claude Code flag is --max-turns on recent versions.
        "--max-turns", str(spec.max_turns),
    ]

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # nested Claude calls must unset this
    if handoff_data is not None:
        env["HANDOFF_INPUT_DATA_B64"] = handoff_data.to_b64()

    if dry_run:
        return {
            "agent": agent,
            "cmd": cmd,
            "env_keys": [k for k in env if k.startswith(("HANDOFF_", "AGENT_", "CLAUDE_"))],
            "prompt_bytes": len(full_prompt.encode()),
            "handoff_depth": depth_info["handoff_depth"],
        }

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, input="", capture_output=True, text=True, env=env,
            timeout=timeout,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        stderr = (e.stderr or "") + "\n[agent_as_tool] timeout after {}s".format(timeout)
        exit_code = 124
    duration_ms = int((time.time() - t0) * 1000)

    parsed = _parse_result(stdout)
    parsed.update({
        "agent": agent,
        "model": spec.model,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "handoff_depth": depth_info["handoff_depth"],
        "handoff_chain": depth_info["handoff_chain"],
        "stderr_tail": stderr[-500:] if stderr else "",
    })

    # Emit telemetry (fire-and-forget).
    try:
        emit(AgentAsToolCallEvent(
            issue_id=issue_id,
            session_id="",
            turn_id=-1,
            agent_name=parent_agent,
            duration_ms=duration_ms,
            exit_code=exit_code,
            sub_agent=agent,
            input_bytes=len(full_prompt.encode()),
            output_bytes=len(stdout.encode()),
            confidence=parsed.get("confidence", -1.0),
        ))
    except Exception:
        pass

    return parsed


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list available agents (JSON)")

    p_call = sub.add_parser("call",
                            help="read {agent, prompt, issue_id?, parent_agent?} JSON on stdin")
    p_call.add_argument("--dry-run", action="store_true",
                        help="don't spawn; just print what would run")
    p_call.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)

    p_describe = sub.add_parser("describe")
    p_describe.add_argument("agent")

    args = ap.parse_args()

    if args.cmd == "list":
        reg = registry()
        out = {
            name: {
                "description": s.description[:200],
                "model": s.model,
                "tools": s.tools,
                "max_turns": s.max_turns,
                "effort": s.effort,
            }
            for name, s in sorted(reg.items())
        }
        json.dump(out, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if args.cmd == "describe":
        reg = registry()
        if args.agent not in reg:
            print(f"agent not found: {args.agent}", file=sys.stderr)
            return 1
        s = reg[args.agent]
        json.dump({
            "name": s.name, "description": s.description, "model": s.model,
            "tools": s.tools, "max_turns": s.max_turns, "effort": s.effort,
            "body_bytes": len(s.body),
        }, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if args.cmd == "call":
        req = json.loads(sys.stdin.read() or "{}")
        agent = req.get("agent", "")
        prompt = req.get("prompt", "")
        if not agent or not prompt:
            print('"agent" and "prompt" are required in stdin JSON', file=sys.stderr)
            return 2
        handoff = None
        hd = req.get("handoff_data")
        if hd and isinstance(hd, dict):
            try:
                handoff = HandoffInputData(**{
                    k: v for k, v in hd.items()
                    if k in HandoffInputData.__dataclass_fields__  # type: ignore[attr-defined]
                })
            except Exception:
                handoff = None
        result = invoke(
            agent=agent,
            prompt=prompt,
            issue_id=req.get("issue_id", ""),
            parent_agent=req.get("parent_agent", "claude-code-t2"),
            handoff_data=handoff,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
        json.dump(result, sys.stdout, indent=2, sort_keys=True, default=str)
        sys.stdout.write("\n")
        return 0 if result.get("exit_code", 0) == 0 else 1

    return 2


if __name__ == "__main__":
    sys.exit(_cli())
