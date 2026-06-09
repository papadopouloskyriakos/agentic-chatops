#!/usr/bin/env python3
"""Compact a HandoffInputData envelope's input_history via local LLM (IFRNLLEI01PRD-641).

When a T1->T2 (or deeper) handoff carries more than HANDOFF_COMPACT_THRESHOLD
bytes of prior conversation, collapse it into a single summary turn via
local gemma3:12b on Ollama. Haiku fallback when gemma is unhealthy.

Mirrors OpenAI Agents SDK `src/agents/handoffs/history.py::nest_handoff_history`
but with two divergences:

  1. Opt-in by default (HANDOFF_COMPACT_MODE=auto unless set to `off`/`force`)
     — humans running T1 triage want visibility into incremental discoveries
       and can override by passing --mode=force.
  2. Uses local gemma/qwen (not Haiku) by default to match the 2026-04-19
     judge/synth flip (see judge_local_first_20260419.md).

Usage (invoked by Build Prompt or parent SSH node):

    cat envelope.b64 | scripts/compact-handoff-history.py --mode auto > compacted.b64

Env vars:
    HANDOFF_COMPACT_MODE    off | auto (default) | force
    HANDOFF_COMPACT_THRESHOLD  bytes (default 8192)
    HANDOFF_COMPACT_MODEL   ollama model name (default gemma3:12b)
    OLLAMA_URL              default http://nl-gpu01:11434
    ANTHROPIC_API_KEY       used if gemma breaker is OPEN

Reads `rag_synth_ollama` circuit breaker (IFRNLLEI01PRD-631) — short-circuits
to Haiku if the breaker is OPEN.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from handoff import HandoffInputData  # noqa: E402
from session_events import HandoffCompactionEvent, emit  # noqa: E402

# Optional circuit breaker integration (graceful if lib missing)
try:
    from circuit_breaker import CircuitBreaker  # type: ignore
except ImportError:
    CircuitBreaker = None  # type: ignore

THRESHOLD = int(os.environ.get("HANDOFF_COMPACT_THRESHOLD", "8192"))
MODE = os.environ.get("HANDOFF_COMPACT_MODE", "auto")  # off | auto | force
MODEL = os.environ.get("HANDOFF_COMPACT_MODEL", "gemma3:12b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
HAIKU_FALLBACK_MODEL = "claude-haiku-4-5-20251001"


SUMMARY_PROMPT = """You are compressing a multi-turn agent conversation into a single briefing paragraph for a successor agent that will continue the work.

Produce a terse, information-dense summary of the conversation below. Include:
  * the user's original goal
  * what the prior agent already tried, and whether it worked
  * any entities discovered (hostnames, issue IDs, file paths, error messages)
  * any open questions or next-steps the prior agent flagged
  * any approvals or decisions already logged (do not repeat them if unresolved)

Omit filler, greetings, prose reasoning that didn't lead to a decision, and
anything already visible in the issue title. Aim for under 300 words. Write
in third person ("the prior agent did X") so the successor reads it as
briefing material, not its own history.

--- conversation below ---
"""


def _ollama_summarize(body_text: str, model: str = MODEL) -> Optional[str]:
    data = json.dumps({
        "model": model,
        "prompt": SUMMARY_PROMPT + body_text,
        "stream": False,
        "options": {"num_ctx": 16384, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read())
            return (result.get("response") or "").strip() or None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
        print(f"[compact] ollama {model} error: {e}", file=sys.stderr)
        return None


def _haiku_summarize(body_text: str) -> Optional[str]:
    if not ANTHROPIC_KEY:
        return None
    data = json.dumps({
        "model": HAIKU_FALLBACK_MODEL,
        "max_tokens": 500,
        "messages": [{"role": "user", "content": SUMMARY_PROMPT + body_text}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            blocks = result.get("content", [])
            texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            return ("".join(texts)).strip() or None
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as e:
        print(f"[compact] haiku error: {e}", file=sys.stderr)
        return None


def summarize(body_text: str) -> tuple[Optional[str], str]:
    """Try local gemma first (per judge_local_first_20260419). Haiku fallback.

    Returns (summary_text, model_used) — (None, "") if both fail.
    """
    # Consult the rag_synth_ollama circuit breaker if available.
    breaker_allows = True
    if CircuitBreaker is not None:
        try:
            cb = CircuitBreaker(
                "rag_synth_ollama", failure_threshold=3, cooldown_seconds=60,
            )
            breaker_allows = cb.allow()
        except Exception:
            breaker_allows = True  # don't block on breaker-lib failure

    if breaker_allows:
        s = _ollama_summarize(body_text)
        if s:
            if CircuitBreaker is not None:
                try: cb.record_success()  # type: ignore
                except Exception: pass
            return s, MODEL
        if CircuitBreaker is not None:
            try: cb.record_failure()  # type: ignore
            except Exception: pass

    s = _haiku_summarize(body_text)
    if s:
        return s, HAIKU_FALLBACK_MODEL
    return None, ""


def _history_to_text(history: list[Any]) -> str:
    """Flatten input_history into a plain text blob for the summarizer."""
    lines = []
    for item in history:
        if isinstance(item, dict):
            role = item.get("role", "?")
            content = item.get("content", "")
            if isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict):
                        parts.append(c.get("text", "") or json.dumps(c))
                    else:
                        parts.append(str(c))
                content = " ".join(p for p in parts if p)
            lines.append(f"[{role}] {content}")
        else:
            lines.append(str(item))
    return "\n".join(lines)


def compact(env: HandoffInputData, mode: str, threshold: int = THRESHOLD) -> tuple[HandoffInputData, dict[str, Any]]:
    """Apply compaction policy. Returns (new_env, stats_dict)."""
    pre_bytes = env.input_history_bytes()
    stats = {
        "pre_bytes": pre_bytes,
        "post_bytes": pre_bytes,
        "applied": False,
        "model": "",
        "mode": mode,
        "reason": "",
        "duration_ms": 0,
    }

    if mode == "off":
        stats["reason"] = "mode=off"
        return env, stats
    if mode == "auto" and pre_bytes <= threshold:
        stats["reason"] = f"{pre_bytes}B <= {threshold}B threshold"
        return env, stats
    if not env.input_history:
        stats["reason"] = "empty history"
        return env, stats

    body = _history_to_text(env.input_history)
    t0 = time.time()
    summary, model_used = summarize(body)
    stats["duration_ms"] = int((time.time() - t0) * 1000)

    if not summary:
        stats["reason"] = "summarizer failed; keeping original history"
        return env, stats

    # Build the new envelope: replace input_history with one synthetic turn
    # whose content is the summary, prefixed with a discoverable marker.
    new_item = {
        "role": "assistant",
        "content": f"[COMPACTED by {model_used}] " + summary,
    }
    new_env = HandoffInputData(
        issue_id=env.issue_id,
        session_id=env.session_id,
        from_agent=env.from_agent,
        to_agent=env.to_agent,
        handoff_depth=env.handoff_depth,
        handoff_chain=list(env.handoff_chain),
        input_history=[new_item],
        pre_handoff_items=list(env.pre_handoff_items),
        new_items=list(env.new_items),
        run_context=dict(env.run_context),
        compaction_applied=True,
        compaction_model=model_used,
        reason=env.reason,
    )
    stats["applied"] = True
    stats["model"] = model_used
    stats["post_bytes"] = new_env.input_history_bytes()
    stats["reason"] = f"compacted via {model_used}"
    return new_env, stats


def _cli() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("off", "auto", "force"), default=MODE)
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--in-b64", help="read envelope from this file instead of stdin")
    ap.add_argument("--out-b64", help="write output envelope here (default: stdout)")
    ap.add_argument("--stats-json", help="write stats JSON here (default: stderr)")
    args = ap.parse_args()

    if args.in_b64:
        b64 = open(args.in_b64).read().strip()
    else:
        b64 = sys.stdin.read().strip()
    if not b64:
        print("no envelope on stdin", file=sys.stderr)
        return 2
    env = HandoffInputData.from_b64(b64)

    new_env, stats = compact(env, args.mode, threshold=args.threshold)

    # Emit telemetry (best-effort; swallow failures).
    try:
        emit(HandoffCompactionEvent(
            issue_id=env.issue_id,
            session_id=env.session_id,
            turn_id=-1,
            agent_name=env.from_agent,
            duration_ms=stats["duration_ms"],
            pre_bytes=stats["pre_bytes"],
            post_bytes=stats["post_bytes"],
            model=stats["model"] or "none",
        ))
    except Exception:
        pass

    out_b64 = new_env.to_b64()
    if args.out_b64:
        with open(args.out_b64, "w") as f:
            f.write(out_b64)
    else:
        sys.stdout.write(out_b64)

    stats_line = json.dumps(stats, sort_keys=True)
    if args.stats_json:
        with open(args.stats_json, "w") as f:
            f.write(stats_line + "\n")
    else:
        sys.stderr.write(stats_line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
