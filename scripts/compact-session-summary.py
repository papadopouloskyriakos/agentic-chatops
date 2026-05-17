#!/usr/bin/env python3
"""G3: Recall-optimized context compaction for long-running sessions.

Reads the current session's JSONL transcript and generates a structured summary
preserving key decisions, unresolved issues, state snapshots, and tool outputs.

Source: Anthropic 'Effective Context Engineering for AI Agents' (2025)
"Start by maximizing recall...then iterate to improve precision."

Usage:
  compact-session-summary.py <session_id>              # Generate summary
  compact-session-summary.py <session_id> --inject     # Generate + write to memory
  compact-session-summary.py --recent                  # Summarize most recent session
"""

import json
import os
import sys
import glob
import sqlite3

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
SUMMARY_DIR = os.path.expanduser(
    "~/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory"
)


def find_jsonl(session_id):
    """Find JSONL file for a session."""
    # Try /tmp first (active sessions)
    REDACTED_4529f8c2
        f"/tmp/claude-run-*{session_id}*.jsonl",
        f"/tmp/claude-run-*.jsonl",
    ]
    for pattern in patterns:
        for f in sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True):
            return f
    return None


def extract_turns(jsonl_path, max_chars=15000):
    """Extract key turns from JSONL, prioritizing decisions and tool outputs."""
    turns = []
    total_chars = 0

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type", "")
            if etype == "assistant":
                msg = event.get("message", {})
                content_blocks = msg.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        # Prioritize: decisions, findings, errors, CONFIDENCE
                        if any(
                            kw in text.lower()
                            for kw in [
                                "confidence:",
                                "decision:",
                                "finding:",
                                "error",
                                "root cause",
                                "resolved",
                                "plan",
                                "[poll]",
                                "thought",
                                "observation",
                            ]
                        ):
                            turns.append(("assistant_key", text[:500]))
                            total_chars += min(len(text), 500)
                        elif total_chars < max_chars:
                            turns.append(("assistant", text[:200]))
                            total_chars += min(len(text), 200)
                    elif block.get("type") == "tool_use":
                        tool = block.get("name", "unknown")
                        turns.append(("tool_call", f"Called: {tool}"))
                        total_chars += 30

            if total_chars >= max_chars:
                break

    return turns


def generate_summary(turns, session_id):
    """Generate structured summary from extracted turns."""
    # Build summary from turns without LLM call (fast, deterministic)
    decisions = []
    findings = []
    tools_used = set()
    confidence_lines = []

    for turn_type, text in turns:
        text_lower = text.lower()
        if "confidence:" in text_lower:
            confidence_lines.append(text[:200])
        elif any(kw in text_lower for kw in ["decision:", "plan", "[poll]"]):
            decisions.append(text[:200])
        elif any(
            kw in text_lower for kw in ["finding:", "root cause", "resolved", "error"]
        ):
            findings.append(text[:200])
        elif turn_type == "tool_call":
            tools_used.add(text.replace("Called: ", ""))

    summary_parts = [f"# Session Summary: {session_id}\n"]

    if decisions:
        summary_parts.append("## Key Decisions")
        for d in decisions[:5]:
            summary_parts.append(f"- {d}")

    if findings:
        summary_parts.append("\n## Findings")
        for f in findings[:5]:
            summary_parts.append(f"- {f}")

    if confidence_lines:
        summary_parts.append("\n## Confidence Assessments")
        for c in confidence_lines[:3]:
            summary_parts.append(f"- {c}")

    if tools_used:
        summary_parts.append(f"\n## Tools Used: {', '.join(sorted(tools_used))}")

    summary_parts.append(
        f"\n## Stats: {len(turns)} turns extracted, "
        f"{len(decisions)} decisions, {len(findings)} findings"
    )

    return "\n".join(summary_parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: compact-session-summary.py <session_id> [--inject]")
        sys.exit(1)

    session_id = sys.argv[1]
    inject = "--inject" in sys.argv

    if session_id == "--recent":
        # Find most recent JSONL
        jsonl_files = sorted(
            glob.glob("/tmp/claude-run-*.jsonl"), key=os.path.getmtime, reverse=True
        )
        if not jsonl_files:
            print("No active session JSONL files found")
            sys.exit(0)
        jsonl_path = jsonl_files[0]
        session_id = (
            os.path.basename(jsonl_path).replace("claude-run-", "").replace(".jsonl", "")
        )
    else:
        jsonl_path = find_jsonl(session_id)

    if not jsonl_path or not os.path.exists(jsonl_path):
        print(f"No JSONL found for session {session_id}")
        sys.exit(0)

    turns = extract_turns(jsonl_path)
    if not turns:
        print("No turns extracted")
        sys.exit(0)

    summary = generate_summary(turns, session_id)
    print(summary)

    if inject and os.path.isdir(SUMMARY_DIR):
        summary_file = os.path.join(
            SUMMARY_DIR, f"session_summary_{session_id[:20]}.md"
        )
        with open(summary_file, "w") as f:
            f.write(f"---\n")
            f.write(f"name: Session summary {session_id}\n")
            f.write(
                f"description: Compacted session context for {session_id}\n"
            )
            f.write(f"type: project\n")
            f.write(f"---\n\n")
            f.write(summary)
        print(f"\nInjected to: {summary_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
