#!/usr/bin/env python3
"""Parse tool calls from Claude Code JSONL session files into tool_call_log.

Extracts tool_use / tool_result pairs from Claude Code stream-json JSONL,
calculates duration, detects errors, maps operations, and inserts into
the tool_call_log SQLite table.

Usage:
  parse-tool-calls.py <jsonl_file> [--issue ISSUE_ID] [--session SESSION_ID]
  parse-tool-calls.py --scan-dir ~/.claude/projects/   # all JSONL files
  parse-tool-calls.py --stats                           # tool usage stats
"""
import sys
import os
import json
import sqlite3
import glob
REDACTED_a7b84d63
from datetime import datetime
from pathlib import Path

# IFRNLLEI01PRD-635: schema version registry.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from schema_version import current as schema_current  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

# Directories to scan for JSONL files
SCAN_PATHS = [
    os.path.expanduser("~/.claude/projects/*/*.jsonl"),
    "/tmp/claude-run-*.jsonl",
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def extract_session_id(filepath):
    """Extract session_id from JSONL file by reading the first entry that has one."""
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                sid = entry.get("sessionId", "")
                if sid:
                    return sid
            except (json.JSONDecodeError, KeyError):
                continue
    # Fallback: use the filename stem (UUID portion)
    stem = Path(filepath).stem
    return stem


def extract_issue_id_from_path(filepath):
    """Extract issue_id from filename.

    - /tmp/claude-run-<ISSUE>.jsonl → <ISSUE>
    - ~/.claude/projects/**/<uuid>.jsonl → cli-<uuid>  (IFRNLLEI01PRD-648)
    """
    basename = os.path.basename(filepath)
    m = re.match(r"claude-run-(.+)\.jsonl$", basename)
    if m:
        return m.group(1)
    claude_projects = os.path.expanduser("~/.claude/projects")
    if filepath.startswith(claude_projects) and basename.endswith(".jsonl"):
        return f"cli-{basename[:-len('.jsonl')]}"
    return ""


def map_operation(tool_name, tool_input):
    """Map a tool_use name + input to a human-readable operation string."""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        # Truncate long commands but keep the meaningful prefix
        if len(cmd) > 200:
            cmd = cmd[:200] + "..."
        return cmd
    elif tool_name == "Read":
        return tool_input.get("file_path", "")
    elif tool_name == "Edit":
        return tool_input.get("file_path", "")
    elif tool_name == "Write":
        return tool_input.get("file_path", "")
    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"{pattern} in {path}" if path else pattern
    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"{pattern} in {path}" if path else pattern
    elif tool_name == "Agent":
        return tool_input.get("description", tool_input.get("prompt", ""))[:200]
    elif tool_name == "ToolSearch":
        return tool_input.get("query", "")
    elif tool_name.startswith("mcp__"):
        # MCP tools: return the most relevant input value
        parts = tool_name.split("__")
        label = parts[-1] if len(parts) >= 3 else tool_name
        # Pick the first string-valued input as the operation summary
        for key in ("query", "node", "name", "pattern", "object_types", "command"):
            if key in tool_input:
                val = tool_input[key]
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                return f"{label}: {str(val)[:150]}"
        return label
    else:
        # Generic: return first input key-value if available
        for key, val in tool_input.items():
            return f"{str(val)[:150]}"
        return ""


def detect_error(tool_result_content, is_error, tool_use_result_obj):
    """Detect error type from tool_result data. Returns (exit_code, error_type)."""
    exit_code = 0
    error_type = ""

    if is_error:
        exit_code = 1
        # Try to extract exit code from content
        if isinstance(tool_result_content, str):
            m = re.match(r"Exit code (\d+)", tool_result_content)
            if m:
                exit_code = int(m.group(1))
            # Classify the error
            content_lower = tool_result_content.lower()
            if "permission denied" in content_lower:
                error_type = "permission_denied"
            elif "no such file" in content_lower or "not found" in content_lower:
                error_type = "not_found"
            elif "timeout" in content_lower or "timed out" in content_lower:
                error_type = "timeout"
            elif "connection refused" in content_lower:
                error_type = "connection_refused"
            elif "syntax error" in content_lower:
                error_type = "syntax_error"
            elif "command not found" in content_lower:
                error_type = "command_not_found"
            elif exit_code != 0:
                error_type = f"exit_{exit_code}"
            else:
                error_type = "unknown"

    # Also check toolUseResult object if available
    if isinstance(tool_use_result_obj, dict):
        interrupted = tool_use_result_obj.get("interrupted", False)
        if interrupted:
            error_type = "interrupted"
            exit_code = exit_code or 130
    elif isinstance(tool_use_result_obj, str) and tool_use_result_obj.startswith("Error:"):
        if not exit_code:
            exit_code = 1
        if not error_type:
            m = re.match(r"Error: Exit code (\d+)", tool_use_result_obj)
            if m:
                exit_code = int(m.group(1))
                error_type = f"exit_{exit_code}"
            else:
                error_type = "unknown"

    return exit_code, error_type


def parse_timestamp(ts_str):
    """Parse ISO timestamp string to datetime, handling various formats."""
    if not ts_str:
        return None
    try:
        # Handle Z suffix and milliseconds
        ts_str = ts_str.replace("Z", "+00:00")
        if "." in ts_str:
            # Truncate nanosecond precision to microseconds
            base, frac_and_tz = ts_str.split(".", 1)
            # Separate fractional seconds from timezone
            m = re.match(r"(\d+)(.*)", frac_and_tz)
            if m:
                frac = m.group(1)[:6]  # max 6 digits for microseconds
                tz = m.group(2)
                ts_str = f"{base}.{frac}{tz}"
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def parse_jsonl_file(filepath):
    """Parse a JSONL file and extract tool call records.

    Returns list of dicts with keys:
      tool_name, operation, duration_ms, exit_code, error_type, created_at
    """
    # Phase 1: collect tool_use entries and tool_result entries
    tool_uses = {}   # id -> {name, input, timestamp, uuid}
    tool_results = []  # list of (tool_use_id, is_error, content, toolUseResult, timestamp)

    line_num = 0
    parse_errors = 0

    with open(filepath, "r") as f:
        for line in f:
            line_num += 1
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                if parse_errors <= 5:
                    print(f"  [warn] Malformed JSON at line {line_num}, skipping",
                          file=sys.stderr)
                continue

            entry_type = entry.get("type", "")
            timestamp = entry.get("timestamp", "")

            # Assistant message with tool_use blocks
            if entry_type == "assistant" and "message" in entry:
                msg = entry["message"]
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_id = block.get("id", "")
                            tool_name = block.get("name", "unknown")
                            tool_input = block.get("input", {})
                            if tool_id:
                                tool_uses[tool_id] = {
                                    "name": tool_name,
                                    "input": tool_input,
                                    "timestamp": timestamp,
                                    "uuid": entry.get("uuid", ""),
                                }

            # User message with tool_result blocks
            elif entry_type == "user":
                msg = entry.get("message", {})
                content = msg.get("content", [])
                tool_use_result_obj = entry.get("toolUseResult", {})
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tool_use_id = block.get("tool_use_id", "")
                            is_error = block.get("is_error", False)
                            result_content = block.get("content", "")
                            tool_results.append((
                                tool_use_id,
                                is_error,
                                result_content,
                                tool_use_result_obj,
                                timestamp,
                            ))

    if parse_errors > 5:
        print(f"  [warn] {parse_errors} total malformed JSON lines skipped",
              file=sys.stderr)

    # Phase 2: match tool_results back to tool_uses, compute duration
    records = []
    matched_ids = set()

    for (tool_use_id, is_error, result_content, tur_obj, result_ts) in tool_results:
        if tool_use_id not in tool_uses:
            continue

        tu = tool_uses[tool_use_id]
        matched_ids.add(tool_use_id)

        # Calculate duration
        duration_ms = 0
        use_dt = parse_timestamp(tu["timestamp"])
        result_dt = parse_timestamp(result_ts)
        if use_dt and result_dt:
            delta = (result_dt - use_dt).total_seconds()
            if delta >= 0:
                duration_ms = int(delta * 1000)

        # Map operation
        operation = map_operation(tu["name"], tu["input"])

        # Detect errors
        exit_code, error_type = detect_error(result_content, is_error, tur_obj)

        # Use the tool_use timestamp as created_at (when the call was initiated)
        created_at = tu["timestamp"] or result_ts

        records.append({
            "tool_name": tu["name"],
            "operation": operation,
            "duration_ms": duration_ms,
            "exit_code": exit_code,
            "error_type": error_type,
            "created_at": created_at,
        })

    # Phase 3: add unmatched tool_uses (no result received, e.g. session interrupted)
    for tool_id, tu in tool_uses.items():
        if tool_id in matched_ids:
            continue
        operation = map_operation(tu["name"], tu["input"])
        records.append({
            "tool_name": tu["name"],
            "operation": operation,
            "duration_ms": 0,
            "exit_code": -1,
            "error_type": "no_result",
            "created_at": tu["timestamp"],
        })

    return records, parse_errors


def is_already_processed(conn, session_id):
    """Check if a session_id already has entries in tool_call_log."""
    row = conn.execute(
        "SELECT COUNT(*) FROM tool_call_log WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    return row[0] > 0


def insert_records(conn, records, session_id, issue_id):
    """Insert tool call records into tool_call_log."""
    inserted = 0
    for rec in records:
        conn.execute(
            """INSERT INTO tool_call_log
               (session_id, issue_id, tool_name, operation, duration_ms,
                exit_code, error_type, created_at, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                issue_id,
                rec["tool_name"],
                rec["operation"][:1000],  # cap operation length
                rec["duration_ms"],
                rec["exit_code"],
                rec["error_type"],
                rec["created_at"] or datetime.utcnow().isoformat(),
                schema_current("tool_call_log"),
            )
        )
        inserted += 1
    conn.commit()
    return inserted


def process_file(filepath, issue_id="", session_id=""):
    """Process a single JSONL file: parse, insert, print summary."""
    if not os.path.exists(filepath):
        print(f"[error] File not found: {filepath}", file=sys.stderr)
        return 0

    # Derive session_id from file if not provided
    if not session_id:
        session_id = extract_session_id(filepath)

    # Derive issue_id from filename pattern if not provided
    if not issue_id:
        issue_id = extract_issue_id_from_path(filepath)

    conn = get_db()

    # Idempotent: skip if already processed
    if session_id and is_already_processed(conn, session_id):
        print(f"[skip] {os.path.basename(filepath)} — session {session_id[:12]}... already in DB")
        conn.close()
        return 0

    records, parse_errors = parse_jsonl_file(filepath)

    if not records:
        print(f"[skip] {os.path.basename(filepath)} — no tool calls found")
        conn.close()
        return 0

    inserted = insert_records(conn, records, session_id, issue_id)
    conn.close()

    # Summary
    tool_freq = {}
    error_count = 0
    total_duration = 0
    for rec in records:
        tool_freq[rec["tool_name"]] = tool_freq.get(rec["tool_name"], 0) + 1
        if rec["exit_code"] != 0 and rec["error_type"] != "no_result":
            error_count += 1
        total_duration += rec["duration_ms"]

    top_tools = ", ".join(
        f"{name}({count})"
        for name, count in sorted(tool_freq.items(), key=lambda x: -x[1])[:5]
    )
    print(
        f"[done] {os.path.basename(filepath)} — "
        f"{inserted} calls inserted, "
        f"{error_count} errors, "
        f"{total_duration / 1000:.1f}s total duration, "
        f"tools: {top_tools}"
    )
    return inserted


def scan_directory(scan_dir):
    """Scan a directory tree for JSONL files and process each."""
    if scan_dir:
        REDACTED_4529f8c2os.path.join(scan_dir, "**", "*.jsonl")]
    else:
        patterns = SCAN_PATHS

    files_found = set()
    for pattern in patterns:
        for f in glob.glob(pattern, recursive=True):
            files_found.add(f)

    if not files_found:
        print("[info] No JSONL files found.")
        return

    print(f"[scan] Found {len(files_found)} JSONL files")
    total_inserted = 0
    files_processed = 0
    files_skipped = 0

    for filepath in sorted(files_found):
        result = process_file(filepath)
        if result > 0:
            total_inserted += result
            files_processed += 1
        else:
            files_skipped += 1

    print(f"\n[summary] {files_processed} files processed, "
          f"{files_skipped} skipped, "
          f"{total_inserted} total tool calls inserted")


def show_stats():
    """Show tool usage statistics from the database."""
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) FROM tool_call_log").fetchone()[0]
    if total == 0:
        print("[stats] No tool call data in database yet.")
        conn.close()
        return

    print(f"=== Tool Call Statistics ({total} total calls) ===\n")

    # Tool frequency
    print("Tool usage by frequency:")
    rows = conn.execute("""
        SELECT tool_name, COUNT(*) as cnt,
               ROUND(AVG(duration_ms)) as avg_dur,
               SUM(CASE WHEN exit_code != 0 AND error_type != 'no_result' THEN 1 ELSE 0 END) as errors
        FROM tool_call_log
        GROUP BY tool_name
        ORDER BY cnt DESC
    """).fetchall()
    print(f"  {'Tool':<30} {'Count':>7} {'Avg ms':>8} {'Errors':>7} {'Err%':>6}")
    print(f"  {'-'*30} {'-'*7} {'-'*8} {'-'*7} {'-'*6}")
    for name, cnt, avg_dur, errors in rows:
        err_pct = (errors / cnt * 100) if cnt > 0 else 0
        avg_dur = avg_dur or 0
        print(f"  {name:<30} {cnt:>7} {avg_dur:>8.0f} {errors:>7} {err_pct:>5.1f}%")

    # Error types
    print(f"\nError types:")
    rows = conn.execute("""
        SELECT error_type, COUNT(*) as cnt
        FROM tool_call_log
        WHERE error_type != '' AND error_type != 'no_result'
        ORDER BY cnt DESC
    """).fetchall()
    if rows:
        for error_type, cnt in rows:
            print(f"  {error_type}: {cnt}")
    else:
        print("  (none)")

    # Sessions with most tool calls
    print(f"\nTop 10 sessions by tool calls:")
    rows = conn.execute("""
        SELECT session_id, issue_id, COUNT(*) as cnt,
               SUM(duration_ms) as total_dur,
               SUM(CASE WHEN exit_code != 0 AND error_type != 'no_result' THEN 1 ELSE 0 END) as errors
        FROM tool_call_log
        GROUP BY session_id
        ORDER BY cnt DESC
        LIMIT 10
    """).fetchall()
    print(f"  {'Session':<40} {'Issue':<20} {'Calls':>6} {'Dur(s)':>8} {'Errs':>5}")
    print(f"  {'-'*40} {'-'*20} {'-'*6} {'-'*8} {'-'*5}")
    for sid, iid, cnt, total_dur, errors in rows:
        sid_short = (sid[:37] + "...") if sid and len(sid) > 40 else (sid or "?")
        iid_short = (iid[:17] + "...") if iid and len(iid) > 20 else (iid or "-")
        total_dur = total_dur or 0
        print(f"  {sid_short:<40} {iid_short:<20} {cnt:>6} {total_dur / 1000:>8.1f} {errors:>5}")

    # Slowest tools (avg duration)
    print(f"\nSlowest tools (avg duration, min 5 calls):")
    rows = conn.execute("""
        SELECT tool_name, ROUND(AVG(duration_ms)) as avg_dur,
               MAX(duration_ms) as max_dur, COUNT(*) as cnt
        FROM tool_call_log
        WHERE duration_ms > 0
        GROUP BY tool_name
        HAVING cnt >= 5
        ORDER BY avg_dur DESC
        LIMIT 10
    """).fetchall()
    print(f"  {'Tool':<30} {'Avg ms':>8} {'Max ms':>8} {'Count':>6}")
    print(f"  {'-'*30} {'-'*8} {'-'*8} {'-'*6}")
    for name, avg_dur, max_dur, cnt in rows:
        print(f"  {name:<30} {avg_dur:>8.0f} {max_dur:>8} {cnt:>6}")

    # Daily trend (last 7 days)
    print(f"\nDaily tool calls (last 7 days):")
    rows = conn.execute("""
        SELECT DATE(created_at) as day, COUNT(*) as cnt,
               SUM(CASE WHEN exit_code != 0 AND error_type != 'no_result' THEN 1 ELSE 0 END) as errors
        FROM tool_call_log
        WHERE created_at >= DATE('now', '-7 days')
        GROUP BY day
        ORDER BY day DESC
    """).fetchall()
    if rows:
        for day, cnt, errors in rows:
            print(f"  {day}: {cnt} calls, {errors} errors")
    else:
        print("  (no data in last 7 days)")

    conn.close()


def print_usage():
    print("Usage:")
    print("  parse-tool-calls.py <jsonl_file> [--issue ISSUE_ID] [--session SESSION_ID]")
    print("  parse-tool-calls.py --scan-dir <dir>    Scan directory for all JSONL files")
    print("  parse-tool-calls.py --scan-dir           Scan default paths")
    print("  parse-tool-calls.py --stats              Show tool usage statistics")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    if sys.argv[1] == "--stats":
        show_stats()
    elif sys.argv[1] == "--scan-dir":
        scan_dir = sys.argv[2] if len(sys.argv) > 2 else ""
        scan_directory(scan_dir)
    elif sys.argv[1] == "--help" or sys.argv[1] == "-h":
        print_usage()
    else:
        filepath = sys.argv[1]
        issue_id = ""
        session_id = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--issue" and i + 1 < len(sys.argv):
                issue_id = sys.argv[i + 1]
            elif arg == "--session" and i + 1 < len(sys.argv):
                session_id = sys.argv[i + 1]
        process_file(filepath, issue_id, session_id)
