#!/usr/bin/env python3
"""Export session JSONL as OpenTelemetry-compatible trace spans.

G8: Lightweight OTel tracing — generates W3C Trace Context compatible spans
from Claude Code JSONL session files. Can output to:
  1. JSON (for manual inspection or future OTLP export)
  2. stdout (human-readable span summary)

Usage:
  python3 scripts/export-otel-traces.py <session-jsonl-path>
  python3 scripts/export-otel-traces.py --issue IFRNLLEI01PRD-281
  python3 scripts/export-otel-traces.py --recent

Span hierarchy:
  session.lifecycle (root)
  ├── session.init          (first system event → first assistant)
  ├── tool.build_prompt     (Build Prompt execution, if detectable)
  ├── tool.launch_claude    (claude CLI invocation)
  ├── tool.call.*           (each tool_use event)
  ├── tool.eval             (score-trajectory + llm-judge)
  └── session.end           (final result event)
"""

import json
import os
import sys
import uuid
import hashlib
import urllib.request
import base64
from datetime import datetime, timezone
from pathlib import Path
import glob as glob_mod

DB_PATH = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")

# OpenObserve OTLP endpoint (nlopenobserve01 at 10.0.181.X, LXC on pve03)
OTLP_ENDPOINT = os.environ.get(
    "OTLP_ENDPOINT",
    "http://10.0.181.X:5080/api/default/v1/traces"
)
OTLP_AUTH = os.environ.get(
    "OTLP_AUTH",
    "Basic " + base64.b64encode(b"chatops@mail.example.net:D8WY74ulgxGRTVJU").decode()
)
# Local trace storage table (fallback when OpenObserve is unreachable)
TRACE_TABLE = "otel_spans"


def generate_trace_id(issue_id: str) -> str:
    """Generate a deterministic 32-hex-char trace ID from issue ID."""
    return hashlib.md5(issue_id.encode()).hexdigest()


def generate_span_id() -> str:
    """Generate a random 16-hex-char span ID."""
    return uuid.uuid4().hex[:16]


def parse_jsonl(path: str) -> list:
    """Parse a JSONL file into a list of events."""
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def events_to_spans(events: list, trace_id: str) -> list:
    """Convert JSONL events into OTel-style spans."""
    spans = []
    root_span_id = generate_span_id()

    # Find session boundaries
    init_event = None
    result_event = None
    tool_calls = []

    for event in events:
        event_type = event.get("type", "")
        subtype = event.get("subtype", "")

        if event_type == "system" and subtype == "init":
            init_event = event
        elif event_type == "result":
            result_event = event
        elif event_type == "assistant":
            message = event.get("message", {})
            for content in message.get("content", []):
                if content.get("type") == "tool_use":
                    tool_calls.append({
                        "name": content.get("name", "unknown"),
                        "input_keys": list(content.get("input", {}).keys()),
                        "timestamp": event.get("timestamp", ""),
                    })

    # Root span: session.lifecycle
    start_ts = init_event.get("timestamp", "") if init_event else ""
    end_ts = result_event.get("timestamp", "") if result_event else ""

    spans.append({
        "traceId": trace_id,
        "spanId": root_span_id,
        "parentSpanId": "",
        "operationName": "session.lifecycle",
        "startTime": start_ts,
        "endTime": end_ts,
        "attributes": {
            "session.id": init_event.get("session_id", "") if init_event else "",
            "session.tools_count": len(init_event.get("tools", [])) if init_event else 0,
            "session.result": result_event.get("subtype", "") if result_event else "",
            "session.cost_usd": result_event.get("cost_usd", 0) if result_event else 0,
            "session.num_turns": result_event.get("num_turns", 0) if result_event else 0,
        },
    })

    # session.init span
    if init_event:
        spans.append({
            "traceId": trace_id,
            "spanId": generate_span_id(),
            "parentSpanId": root_span_id,
            "operationName": "session.init",
            "startTime": start_ts,
            "endTime": start_ts,
            "attributes": {
                "tools": len(init_event.get("tools", [])),
                "session_id": init_event.get("session_id", ""),
            },
        })

    # Tool call spans
    for tc in tool_calls:
        spans.append({
            "traceId": trace_id,
            "spanId": generate_span_id(),
            "parentSpanId": root_span_id,
            "operationName": f"tool.call.{tc['name']}",
            "startTime": tc.get("timestamp", ""),
            "endTime": "",  # Duration not available from JSONL
            "attributes": {
                "tool.name": tc["name"],
                "tool.input_keys": tc["input_keys"],
            },
        })

    # session.end span
    if result_event:
        spans.append({
            "traceId": trace_id,
            "spanId": generate_span_id(),
            "parentSpanId": root_span_id,
            "operationName": "session.end",
            "startTime": end_ts,
            "endTime": end_ts,
            "attributes": {
                "result": result_event.get("subtype", ""),
                "cost_usd": result_event.get("cost_usd", 0),
                "num_turns": result_event.get("num_turns", 0),
                "is_error": result_event.get("is_error", False),
            },
        })

    return spans


def store_trace_id(issue_id: str, trace_id: str):
    """Store trace_id in the sessions table."""
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE sessions SET trace_id = ? WHERE issue_id = ?",
            (trace_id, issue_id),
        )
        conn.execute(
            "UPDATE session_log SET trace_id = ? WHERE issue_id = ? AND trace_id = ''",
            (trace_id, issue_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Warning: could not store trace_id: {e}", file=sys.stderr)


def find_jsonl_for_issue(issue_id: str) -> str:
    """Find the JSONL file for a given issue ID."""
    path = f"/tmp/claude-run-{issue_id}.jsonl"
    if os.path.exists(path):
        return path
    # Search in claude projects
    for p in Path.home().glob(".claude/projects/**/*.jsonl"):
        if issue_id in str(p):
            return str(p)
    return ""


def iso_to_nanos(ts: str) -> int:
    """Convert ISO timestamp to nanoseconds since epoch."""
    if not ts:
        return 0
    try:
        # Handle various timestamp formats
        ts = ts.replace("Z", "+00:00")
        if "." in ts:
            dt = datetime.fromisoformat(ts)
        else:
            dt = datetime.fromisoformat(ts)
        return int(dt.timestamp() * 1_000_000_000)
    except (ValueError, TypeError):
        return 0


def convert_to_otlp(spans: list, service_name: str = "claude-gateway") -> dict:
    """Convert internal spans to OTLP JSON format for OpenObserve."""
    otlp_spans = []
    for span in spans:
        start_ns = iso_to_nanos(span.get("startTime", ""))
        end_ns = iso_to_nanos(span.get("endTime", "")) or start_ns or int(datetime.now(timezone.utc).timestamp() * 1e9)
        if start_ns == 0:
            start_ns = end_ns

        attrs = []
        for k, v in span.get("attributes", {}).items():
            if isinstance(v, bool):
                attrs.append({"key": str(k), "value": {"boolValue": v}})
            elif isinstance(v, int):
                attrs.append({"key": str(k), "value": {"intValue": str(v)}})
            elif isinstance(v, float):
                attrs.append({"key": str(k), "value": {"doubleValue": v}})
            elif isinstance(v, list):
                attrs.append({"key": str(k), "value": {"stringValue": json.dumps(v)}})
            else:
                attrs.append({"key": str(k), "value": {"stringValue": str(v)}})

        is_error = span.get("attributes", {}).get("is_error", False)
        otlp_spans.append({
            "traceId": span["traceId"],
            "spanId": span["spanId"],
            "parentSpanId": span.get("parentSpanId", ""),
            "name": span["operationName"],
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": str(start_ns),
            "endTimeUnixNano": str(end_ns),
            "attributes": attrs,
            "status": {"code": 2 if is_error else 1},  # ERROR=2, OK=1
        })

    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                    {"key": "service.version", "value": {"stringValue": "2026.04.11"}},
                    {"key": "deployment.environment", "value": {"stringValue": "production"}},
                ]
            },
            "scopeSpans": [{
                "scope": {"name": "claude-gateway-tracer", "version": "1.0.0"},
                "spans": otlp_spans,
            }]
        }]
    }


def submit_otlp(otlp_data: dict, endpoint: str = OTLP_ENDPOINT, auth: str = OTLP_AUTH) -> bool:
    """Submit OTLP JSON to OpenObserve via HTTP POST."""
    data = json.dumps(otlp_data).encode("utf-8")
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", auth)

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"OTLP submit HTTP error {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"OTLP submit failed: {e}", file=sys.stderr)
        return False


def store_spans_locally(spans: list, issue_id: str):
    """Store spans in local SQLite as fallback when OpenObserve is unreachable."""
    import sqlite3
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"""CREATE TABLE IF NOT EXISTS {TRACE_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            span_id TEXT NOT NULL,
            parent_span_id TEXT DEFAULT '',
            operation_name TEXT NOT NULL,
            issue_id TEXT DEFAULT '',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            attributes TEXT DEFAULT '{{}}',
            exported_to_otlp BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(trace_id, span_id)
        )""")
        for span in spans:
            conn.execute(f"""INSERT OR IGNORE INTO {TRACE_TABLE}
                (trace_id, span_id, parent_span_id, operation_name, issue_id,
                 start_time, end_time, attributes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (span["traceId"], span["spanId"], span.get("parentSpanId", ""),
                 span["operationName"], issue_id,
                 span.get("startTime", ""), span.get("endTime", ""),
                 json.dumps(span.get("attributes", {}))))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Local span storage failed: {e}", file=sys.stderr)
        return False


def process_and_export(path: str, issue_id: str, do_otlp: bool = False) -> dict:
    """Process a single JSONL file: generate spans, optionally submit OTLP. Returns stats."""
    trace_id = generate_trace_id(issue_id)
    events = parse_jsonl(path)
    if not events:
        return {"issue_id": issue_id, "spans": 0, "exported": False, "reason": "no_events"}

    spans = events_to_spans(events, trace_id)
    store_trace_id(issue_id, trace_id)

    exported = False
    stored_locally = False
    if do_otlp and spans:
        otlp_data = convert_to_otlp(spans)
        exported = submit_otlp(otlp_data)
        if not exported:
            # Fallback: store in local SQLite for later export
            stored_locally = store_spans_locally(spans, issue_id)
    elif spans:
        # Always store locally even without --otlp
        stored_locally = store_spans_locally(spans, issue_id)

    return {
        "issue_id": issue_id,
        "trace_id": trace_id,
        "spans": len(spans),
        "events": len(events),
        "exported": exported,
        "stored_locally": stored_locally,
    }


def scan_and_export(scan_dir: str, do_otlp: bool = False, limit: int = 50):
    """Scan directory for JSONL files and export traces."""
    import sqlite3

    # Find all JSONL files
    REDACTED_4529f8c2
        os.path.join(scan_dir, "**", "*.jsonl"),
        "/tmp/claude-run-*.jsonl",
    ]
    files = []
    for pattern in patterns:
        files.extend(glob_mod.glob(pattern, recursive=True))

    # Filter out subagent files and tiny files
    files = [f for f in files if "/subagents/" not in f and os.path.getsize(f) > 5000]
    files = sorted(files, key=os.path.getmtime, reverse=True)[:limit]

    # Track already-exported (check trace_id in session_log)
    already_exported = set()
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT issue_id FROM session_log WHERE trace_id != ''").fetchall()
        already_exported = {r[0] for r in rows}
        conn.close()
    except Exception:
        pass

    total = 0
    exported = 0
    skipped = 0
    for f in files:
        issue_id = Path(f).stem.replace("claude-run-", "")
        if issue_id in already_exported:
            skipped += 1
            continue

        result = process_and_export(f, issue_id, do_otlp=do_otlp)
        total += 1
        if result.get("exported"):
            exported += 1
            print(f"  EXPORTED {issue_id}: {result['spans']} spans -> OpenObserve")
        elif result.get("spans", 0) > 0:
            print(f"  PARSED   {issue_id}: {result['spans']} spans (OTLP={'sent' if do_otlp else 'off'})")
        else:
            print(f"  SKIP     {issue_id}: {result.get('reason', 'no spans')}")

    print(f"\nScan complete: {total} processed, {exported} exported, {skipped} already traced")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAdditional flags:")
        print("  --otlp              Submit spans to OpenObserve via OTLP HTTP")
        print("  --scan-dir [PATH]   Scan directory for JSONL files (default: ~/.claude/projects/)")
        print("  --json              Output spans as JSON")
        sys.exit(1)

    do_otlp = "--otlp" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--otlp", "--json")]
    arg = args[0] if args else "--recent"

    # Scan mode: process many files
    if arg == "--scan-dir":
        scan_path = args[1] if len(args) > 1 else os.path.expanduser("~/.claude/projects/")
        scan_and_export(scan_path, do_otlp=do_otlp)
        return

    # Single-file modes
    if arg == "--recent":
        jsonls = sorted(Path("/tmp").glob("claude-run-*.jsonl"), key=os.path.getmtime, reverse=True)
        if not jsonls:
            # Fall back to CLI sessions
            jsonls = sorted(
                [p for p in Path.home().glob(".claude/projects/**/*.jsonl")
                 if "/subagents/" not in str(p) and p.stat().st_size > 5000],
                key=os.path.getmtime, reverse=True
            )[:5]
        if not jsonls:
            print("No JSONL files found")
            sys.exit(1)
        for jf in jsonls:
            path = str(jf)
            issue_id = jf.stem.replace("claude-run-", "")
            result = process_and_export(path, issue_id, do_otlp=do_otlp)
            status = "EXPORTED" if result.get("exported") else "PARSED"
            print(f"  {status} {issue_id}: {result['spans']} spans")
        return
    elif arg == "--issue":
        issue_id = args[1] if len(args) > 1 else ""
        if not issue_id:
            print("Usage: --issue <ISSUE-ID>")
            sys.exit(1)
        path = find_jsonl_for_issue(issue_id)
        if not path:
            print(f"No JSONL found for {issue_id}")
            sys.exit(1)
    else:
        path = arg
        issue_id = Path(path).stem.replace("claude-run-", "")

    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    result = process_and_export(path, issue_id, do_otlp=do_otlp)

    # Output
    if "--json" in sys.argv:
        trace_id = result["trace_id"]
        events = parse_jsonl(path)
        spans = events_to_spans(events, trace_id)
        print(json.dumps({"traceId": trace_id, "spans": spans}, indent=2))
    else:
        print(f"Trace ID: {result.get('trace_id', '?')}")
        print(f"Issue:    {issue_id}")
        print(f"JSONL:    {path}")
        print(f"Events:   {result.get('events', 0)}")
        print(f"Spans:    {result.get('spans', 0)}")
        print(f"Exported: {result.get('exported', False)}")
        if not do_otlp:
            # Show span details
            events = parse_jsonl(path)
            spans = events_to_spans(events, result.get("trace_id", ""))
            print()
            for span in spans:
                parent = f" (parent: {span['parentSpanId'][:8]})" if span["parentSpanId"] else " (root)"
                print(f"  [{span['spanId'][:8]}] {span['operationName']}{parent}")
                for k, v in span.get("attributes", {}).items():
                    if v:
                        print(f"           {k}: {v}")


if __name__ == "__main__":
    main()
