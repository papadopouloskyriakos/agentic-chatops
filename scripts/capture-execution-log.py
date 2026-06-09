#!/usr/bin/env python3
"""Capture infrastructure command executions from Claude Code JSONL session files.

Parses JSONL for Bash tool_use blocks that target remote infrastructure
(SSH, kubectl, curl to APIs) and records them in execution_log table.

Usage:
  capture-execution-log.py <jsonl_file> [--issue ISSUE_ID] [--session SESSION_ID]
  capture-execution-log.py --scan-dir               # scan default JSONL paths
  capture-execution-log.py --scan-dir <directory>    # scan specific directory
  capture-execution-log.py --stats                   # show execution statistics
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

SCAN_PATHS = [
    os.path.expanduser("~/.claude/projects/*/*.jsonl"),
    "/tmp/claude-run-*.jsonl",
]

# Patterns that identify infrastructure/remote commands (not local file ops)
INFRA_PATTERNS = [
    # SSH commands to remote hosts
    (r'^ssh\s+', "ssh"),
    (r'^ssh\s+-i\s+', "ssh"),
    # kubectl commands
    (r'^kubectl\s+', "kubectl"),
    (r'^KUBECONFIG=.*kubectl\s+', "kubectl"),
    # curl to APIs (not local)
    (r'^curl\s+.*https?://', "curl"),
    # Ansible / AWX
    (r'^ansible\b', "ansible"),
    (r'^ansible-playbook\b', "ansible"),
    # systemctl on remote (via ssh)
    (r'ssh.*systemctl\b', "systemctl"),
    # Docker/Podman on remote
    (r'ssh.*docker\b', "docker"),
    (r'ssh.*podman\b', "podman"),
    # pct/qm (Proxmox CLI)
    (r'^pct\s+', "proxmox"),
    (r'^qm\s+', "proxmox"),
    # swanctl (VPN)
    (r'swanctl\b', "swanctl"),
    # sqlite3 on gateway.db (infra state changes)
    (r'^sqlite3\s+.*gateway\.db', "sqlite"),
]

# Commands to skip (local file operations)
LOCAL_SKIP_PATTERNS = [
    r'^\s*$',
    r'^ls\b',
    r'^cat\b',
    r'^head\b',
    r'^tail\b',
    r'^grep\b',
    r'^rg\b',
    r'^find\b',
    r'^echo\b',
    r'^python3?\s+.*-c\s+',  # inline python
    r'^cd\b',
    r'^pwd\b',
    r'^wc\b',
    r'^sort\b',
    r'^uniq\b',
    r'^test\b',
    r'^\[',
    r'^true$',
    r'^false$',
    r'^which\b',
    r'^type\b',
    r'^stat\b',
    r'^file\b',
    r'^md5sum\b',
    r'^sha\d+sum\b',
    r'^diff\b',
    r'^mkdir\b',
    r'^touch\b',
    r'^date\b',
    r'^uname\b',
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def extract_session_id(filepath):
    """Extract session_id from JSONL file."""
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
    return Path(filepath).stem


def extract_issue_id_from_path(filepath):
    """Extract issue_id from /tmp/claude-run-<ISSUE>.jsonl filename."""
    basename = os.path.basename(filepath)
    m = re.match(r"claude-run-(.+)\.jsonl$", basename)
    if m:
        return m.group(1)
    return ""


def is_infra_command(command):
    """Check if a command targets remote infrastructure."""
    cmd = command.strip()
    if not cmd:
        return False

    # Skip local-only commands
    for pattern in LOCAL_SKIP_PATTERNS:
        if re.match(pattern, cmd):
            return False

    # Check for infrastructure patterns
    for pattern, _ in INFRA_PATTERNS:
        if re.search(pattern, cmd, re.MULTILINE):
            return True

    # Multi-line commands: check each line
    for line in cmd.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for pattern, _ in INFRA_PATTERNS:
            if re.search(pattern, line):
                return True

    return False


def extract_device(command):
    """Extract target device from command."""
    cmd = command.strip()

    # SSH target: ssh [-i key] [user@]host [command...]
    ssh_match = re.search(
        r'ssh\s+(?:-[^\s]+\s+)*(?:-i\s+\S+\s+)?(?:(\S+)@)?(\S+)',
        cmd
    )
    if ssh_match:
        host = ssh_match.group(2)
        # Clean up host (remove trailing commands)
        host = host.split("'")[0].split('"')[0].strip()
        # If it looks like an IP or hostname, use it
        if re.match(r'[\w\.\-]+$', host):
            return host

    # kubectl context
    kube_match = re.search(r'--context[=\s]+(\S+)', cmd)
    if kube_match:
        return kube_match.group(1)
    if cmd.strip().startswith("kubectl"):
        return "k8s-cluster"

    # curl target URL
    curl_match = re.search(r'curl\s+.*?(https?://[\w\.\-:]+)', cmd)
    if curl_match:
        url = curl_match.group(1)
        # Extract hostname from URL
        host_match = re.search(r'https?://([\w\.\-]+)', url)
        if host_match:
            return host_match.group(1)

    # pct/qm (Proxmox) - target is VMID
    pct_match = re.search(r'(?:pct|qm)\s+\w+\s+(\d+)', cmd)
    if pct_match:
        return f"vmid-{pct_match.group(1)}"

    # swanctl
    if "swanctl" in cmd:
        return "vpn-local"

    # sqlite3 gateway.db
    if "gateway.db" in cmd:
        return "gateway-db"

    return "unknown"


def extract_command_summary(command):
    """Extract a concise command summary (max 500 chars)."""
    cmd = command.strip()
    # For SSH, extract the remote command
    ssh_match = re.search(
        r"ssh\s+(?:-[^\s]+\s+)*(?:-i\s+\S+\s+)?(?:\S+@)?\S+\s+['\"](.+?)['\"]",
        cmd, re.DOTALL
    )
    if ssh_match:
        return ssh_match.group(1)[:500]

    # For multi-line, take the first meaningful line
    for line in cmd.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:500]

    return cmd[:500]


def parse_timestamp(ts_str):
    """Parse ISO timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        if "." in ts_str:
            base, frac_and_tz = ts_str.split(".", 1)
            m = re.match(r"(\d+)(.*)", frac_and_tz)
            if m:
                frac = m.group(1)[:6]
                tz = m.group(2)
                ts_str = f"{base}.{frac}{tz}"
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def extract_exit_code(result_content, is_error):
    """Extract exit code from tool_result."""
    if not is_error:
        return 0

    if isinstance(result_content, str):
        m = re.search(r"Exit code (\d+)", result_content)
        if m:
            return int(m.group(1))
        return 1

    if isinstance(result_content, list):
        for block in result_content:
            if isinstance(block, dict):
                text = block.get("text", "")
                m = re.search(r"Exit code (\d+)", text)
                if m:
                    return int(m.group(1))

    return 1 if is_error else 0


def parse_jsonl_file(filepath):
    """Parse JSONL and extract infrastructure execution records."""
    tool_uses = {}  # id -> {command, timestamp, input}
    tool_results = []  # (tool_use_id, is_error, content, timestamp)

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            timestamp = entry.get("timestamp", "")

            if entry_type == "assistant" and "message" in entry:
                content = entry["message"].get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if (isinstance(block, dict)
                                and block.get("type") == "tool_use"
                                and block.get("name") == "Bash"):
                            tool_id = block.get("id", "")
                            tool_input = block.get("input", {})
                            command = tool_input.get("command", "")
                            if tool_id and is_infra_command(command):
                                tool_uses[tool_id] = {
                                    "command": command,
                                    "timestamp": timestamp,
                                    "input": tool_input,
                                }

            elif entry_type == "user":
                content = entry.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if (isinstance(block, dict)
                                and block.get("type") == "tool_result"):
                            tool_use_id = block.get("tool_use_id", "")
                            if tool_use_id in tool_uses:
                                is_error = block.get("is_error", False)
                                result_content = block.get("content", "")
                                tool_results.append((
                                    tool_use_id, is_error,
                                    result_content, timestamp
                                ))

    # Match results to uses
    records = []
    step_index = 0
    matched_ids = set()

    for (tool_use_id, is_error, result_content, result_ts) in tool_results:
        if tool_use_id not in tool_uses:
            continue

        tu = tool_uses[tool_use_id]
        matched_ids.add(tool_use_id)
        step_index += 1

        # Duration
        duration_ms = 0
        use_dt = parse_timestamp(tu["timestamp"])
        result_dt = parse_timestamp(result_ts)
        if use_dt and result_dt:
            delta = (result_dt - use_dt).total_seconds()
            if delta >= 0:
                duration_ms = int(delta * 1000)

        exit_code = extract_exit_code(result_content, is_error)
        device = extract_device(tu["command"])
        command_summary = extract_command_summary(tu["command"])

        records.append({
            "step_index": step_index,
            "device": device,
            "command": command_summary,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "created_at": tu["timestamp"] or result_ts,
        })

    # Unmatched (no result)
    for tool_id, tu in tool_uses.items():
        if tool_id in matched_ids:
            continue
        step_index += 1
        records.append({
            "step_index": step_index,
            "device": extract_device(tu["command"]),
            "command": extract_command_summary(tu["command"]),
            "exit_code": -1,
            "duration_ms": 0,
            "created_at": tu["timestamp"],
        })

    return records


def is_already_processed(conn, session_id):
    """Check if session already has entries in execution_log."""
    row = conn.execute(
        "SELECT COUNT(*) FROM execution_log WHERE session_id = ?",
        (session_id,)
    ).fetchone()
    return row[0] > 0


def insert_records(conn, records, session_id, issue_id):
    """Insert execution records into execution_log."""
    inserted = 0
    for rec in records:
        conn.execute(
            """INSERT INTO execution_log
               (session_id, issue_id, step_index, device, command,
                exit_code, duration_ms, created_at, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                issue_id,
                rec["step_index"],
                rec["device"],
                rec["command"][:2000],
                rec["exit_code"],
                rec["duration_ms"],
                rec["created_at"] or datetime.utcnow().isoformat(),
                schema_current("execution_log"),
            )
        )
        inserted += 1
    conn.commit()
    return inserted


def process_file(filepath, issue_id="", session_id=""):
    """Process a single JSONL file."""
    if not os.path.exists(filepath):
        print(f"[error] File not found: {filepath}", file=sys.stderr)
        return 0

    if not session_id:
        session_id = extract_session_id(filepath)
    if not issue_id:
        issue_id = extract_issue_id_from_path(filepath)

    conn = get_db()

    if session_id and is_already_processed(conn, session_id):
        print(f"[skip] {os.path.basename(filepath)} -- session {session_id[:12]}... already in DB")
        conn.close()
        return 0

    records = parse_jsonl_file(filepath)

    if not records:
        conn.close()
        return 0

    inserted = insert_records(conn, records, session_id, issue_id)
    conn.close()

    devices = set(r["device"] for r in records)
    errors = sum(1 for r in records if r["exit_code"] != 0 and r["exit_code"] != -1)
    total_dur = sum(r["duration_ms"] for r in records)
    print(
        f"[done] {os.path.basename(filepath)} -- "
        f"{inserted} executions, {errors} errors, "
        f"{total_dur / 1000:.1f}s total, "
        f"devices: {', '.join(sorted(devices)[:5])}"
    )
    return inserted


def scan_directory(scan_dir):
    """Scan for JSONL files and process each."""
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

    for filepath in sorted(files_found):
        result = process_file(filepath)
        if result > 0:
            total_inserted += result
            files_processed += 1

    print(f"\n[summary] {files_processed} files with infra commands, "
          f"{total_inserted} total executions inserted")


def show_stats():
    """Show execution log statistics."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM execution_log").fetchone()[0]
    if total == 0:
        print("[stats] No execution data in database yet.")
        conn.close()
        return

    print(f"=== Execution Log Statistics ({total} total) ===\n")

    print("By device:")
    rows = conn.execute("""
        SELECT device, COUNT(*) as cnt,
               SUM(CASE WHEN exit_code != 0 AND exit_code != -1 THEN 1 ELSE 0 END) as errors,
               ROUND(AVG(duration_ms)) as avg_dur
        FROM execution_log
        GROUP BY device ORDER BY cnt DESC LIMIT 15
    """).fetchall()
    print(f"  {'Device':<35} {'Count':>6} {'Errors':>6} {'Avg ms':>8}")
    print(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*8}")
    for device, cnt, errors, avg_dur in rows:
        print(f"  {device:<35} {cnt:>6} {errors:>6} {(avg_dur or 0):>8.0f}")

    print(f"\nBy session:")
    rows = conn.execute("""
        SELECT session_id, issue_id, COUNT(*) as cnt,
               SUM(duration_ms) as total_dur
        FROM execution_log
        GROUP BY session_id ORDER BY cnt DESC LIMIT 10
    """).fetchall()
    for sid, iid, cnt, dur in rows:
        sid_short = (sid[:30] + "...") if sid and len(sid) > 33 else (sid or "?")
        print(f"  {sid_short:<33} {iid or '-':<20} {cnt:>4} cmds  {(dur or 0)/1000:>7.1f}s")

    conn.close()


def print_usage():
    print(__doc__)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    if sys.argv[1] == "--stats":
        show_stats()
    elif sys.argv[1] == "--scan-dir":
        scan_dir = sys.argv[2] if len(sys.argv) > 2 else ""
        scan_directory(scan_dir)
    elif sys.argv[1] in ("--help", "-h"):
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
