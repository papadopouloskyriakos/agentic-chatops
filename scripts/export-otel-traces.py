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
  python3 scripts/export-otel-traces.py --export          # cron: export unexported spans to OpenObserve

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
    "Basic " + base64.b64encode(b"admin@example.com:kradGaPKMeR8xkeNXd2KWVGxerx5kfL4").decode()
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
    first_timestamp = ""  # First timestamp from ANY event (init events lack timestamps)

    for event in events:
        event_type = event.get("type", "")
        subtype = event.get("subtype", "")

        # Capture first available timestamp from any event
        if not first_timestamp and event.get("timestamp"):
            first_timestamp = event["timestamp"]

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
    # init events often lack timestamps; fall back to first available timestamp
    start_ts = init_event.get("timestamp", "") if init_event else ""
    if not start_ts:
        start_ts = first_timestamp
    end_ts = result_event.get("timestamp", "") if result_event else ""
    if not end_ts:
        end_ts = start_ts  # Worst case: zero-duration span at session start

    # OTel GenAI semantic conventions (2025) for root span
    root_attrs = {
        "session.id": init_event.get("session_id", "") if init_event else "",
        "session.tools_count": len(init_event.get("tools", [])) if init_event else 0,
        "session.result": result_event.get("subtype", "") if result_event else "",
        "session.cost_usd": result_event.get("cost_usd", 0) if result_event else 0,
        "session.num_turns": result_event.get("num_turns", 0) if result_event else 0,
        # OTel GenAI semantic conventions
        "gen_ai.system": "anthropic",
        "gen_ai.request.model": result_event.get("model", "claude-sonnet-4-6") if result_event else "claude-sonnet-4-6",
        "gen_ai.usage.input_tokens": result_event.get("input_tokens", 0) if result_event else 0,
        "gen_ai.usage.output_tokens": result_event.get("output_tokens", 0) if result_event else 0,
        "gen_ai.response.finish_reasons": result_event.get("subtype", "end_turn") if result_event else "",
    }

    spans.append({
        "traceId": trace_id,
        "spanId": root_span_id,
        "parentSpanId": "",
        "operationName": "session.lifecycle",
        "startTime": start_ts,
        "endTime": end_ts,
        "attributes": root_attrs,
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
        end_ns = iso_to_nanos(span.get("endTime", "")) or start_ns
        if start_ns == 0:
            start_ns = end_ns
        # Skip spans with no valid timestamp (OpenObserve rejects epoch-zero)
        if start_ns == 0 and end_ns == 0:
            continue

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
                    {"key": "service.version", "value": {"stringValue": "2026.04.15"}},
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


def export_unexported_spans(batch_size: int = 512) -> dict:
    """Export locally-stored spans that haven't been sent to OpenObserve yet.

    Designed for cron (*/5): reads otel_spans where exported_to_otlp=0,
    batches them into OTLP payloads, submits, and marks as exported.
    """
    import sqlite3
    stats = {"total": 0, "exported": 0, "failed": 0, "already_done": 0}

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # exported_to_otlp: 0=pending, 1=exported, 2=retention-expired (skip)
        rows = conn.execute(
            f"SELECT * FROM {TRACE_TABLE} WHERE exported_to_otlp = 0 ORDER BY created_at LIMIT ?",
            (batch_size,)
        ).fetchall()
    except Exception as e:
        print(f"DB read error: {e}", file=sys.stderr)
        return stats

    if not rows:
        stats["already_done"] = conn.execute(
            f"SELECT COUNT(*) FROM {TRACE_TABLE} WHERE exported_to_otlp = 1"
        ).fetchone()[0]
        conn.close()
        return stats

    stats["total"] = len(rows)

    # Group spans by trace_id for batch export
    traces = {}
    for row in rows:
        tid = row["trace_id"]
        if tid not in traces:
            traces[tid] = []
        attrs_raw = row["attributes"] or "{}"
        try:
            attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) else attrs_raw
        except json.JSONDecodeError:
            attrs = {}

        traces[tid].append({
            "traceId": tid,
            "spanId": row["span_id"],
            "parentSpanId": row["parent_span_id"] or "",
            "operationName": row["operation_name"],
            "startTime": row["start_time"] or "",
            "endTime": row["end_time"] or "",
            "attributes": attrs,
        })

    # Export each trace batch
    exported_ids = []
    for tid, spans in traces.items():
        otlp_data = convert_to_otlp(spans)
        if submit_otlp(otlp_data):
            stats["exported"] += len(spans)
            exported_ids.extend(
                (row["trace_id"], row["span_id"])
                for row in rows if row["trace_id"] == tid
            )
        else:
            stats["failed"] += len(spans)

    # Mark exported spans
    if exported_ids:
        for tid, sid in exported_ids:
            conn.execute(
                f"UPDATE {TRACE_TABLE} SET exported_to_otlp = 1 WHERE trace_id = ? AND span_id = ?",
                (tid, sid)
            )
        conn.commit()

    conn.close()
    return stats


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

    # Export mode: push unexported local spans to OpenObserve (for cron */5)
    if arg == "--export":
        stats = export_unexported_spans()
        if stats["total"] > 0:
            print(f"OTel export: {stats['exported']} spans exported, {stats['failed']} failed, {stats['total']} total")
        elif stats["already_done"] > 0:
            pass  # silent when nothing to do (cron-friendly)
        return

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
