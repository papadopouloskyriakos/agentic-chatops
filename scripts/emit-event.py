#!/usr/bin/env python3
"""Emit a typed session event to gateway.db event_log (IFRNLLEI01PRD-637).

Thin wrapper over `scripts/lib/session_events.py` so bash hooks /
Claude Code shell snippets can emit typed events without embedding Python.

See `scripts/lib/session_events.py` for the full taxonomy.

Example (PostToolUse hook emitting a tool_ended event):

    scripts/emit-event.py --type tool_ended \\
        --issue IFRNLLEI01PRD-123 --session $CLAUDE_SESSION \\
        --turn $TURN_ID --agent claude-code-t2 \\
        --duration-ms 1234 --exit-code 0 \\
        --payload-json '{"tool_name":"Bash","output_size":2048}'
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from session_events import _cli  # noqa: E402

if __name__ == "__main__":
    sys.exit(_cli())
