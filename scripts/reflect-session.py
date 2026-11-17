#!/usr/bin/env python3
"""reflect-session.py — structured per-session reflection -> lessons_learned (R5).

Replaces the free-text ``LESSON:`` regex: the session's final response (+ a short
trajectory excerpt from its stream-json JSONL) goes to the local model with the
Harness2-style reflection mission (scripts/lib/reflection.py), the answer is parsed into
per-component edit rows + at most one {cue, lesson, evidence, confidence} entry, and ONE
row is stored per domain-keyed reflection. NO_ENTRY is a valid answer and is stored as
verdict='no_entry' so the flywheel can count that reflection ran.

  reflect-session.py --issue ID [--jsonl /tmp/claude-run-ID.jsonl] [--text-file F]
                     [--db PATH] [--domain D] [--harness-fp FP] [--dry-run]
                     [--offline-stub FILE]

Final text source, in order: --text-file > the JSONL's `result` event > the `sessions`
row's last_response_b64. --offline-stub FILE bypasses the model (tests). Always exits 0
on handled failures (fail-open: the reconciler must never be blocked by this).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
from typing import Any, Optional

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
from lib REDACTED_a7b84d63flection as R  # noqa: E402

DEFAULT_DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
EXCERPT_LINES = 40
RESULT_CHARS = 160
INPUT_CHARS = 100


def _entries(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(e, dict):
                    yield e
    except OSError:
        return


def final_text_from_jsonl(path: str) -> str:
    last = ""
    for e in _entries(path):
        if e.get("type") == "result" and isinstance(e.get("result"), str):
            last = e["result"]
    return last


def _compact_input(inp: Any) -> str:
    if isinstance(inp, dict):
        for key in ("command", "file_path", "pattern", "query", "url", "description"):
            v = inp.get(key)
            if isinstance(v, str) and v.strip():
                s = v
                break
        else:
            s = json.dumps(inp, ensure_ascii=False)
    else:
        s = str(inp)
    return " ".join(s.split())[:INPUT_CHARS]


def _result_text(content: Any) -> str:
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                parts.append(c["text"])
            elif isinstance(c, str):
                parts.append(c)
        content = " ".join(parts)
    return " ".join(str(content or "").split())[:RESULT_CHARS]


def trajectory_excerpt(path: str, limit: int = EXCERPT_LINES) -> str:
    """Last `limit` [ACTION]/[RESULT] lines rendered from the stream-json JSONL."""
    lines: list[str] = []
    for e in _entries(path):
        t = e.get("type")
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        content = msg.get("content", []) if msg else []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if t == "assistant" and block.get("type") == "tool_use":
                lines.append(f"[ACTION] {block.get('name', 'unknown')} "
                             f"{_compact_input(block.get('input', {}))}".rstrip())
            elif t == "user" and block.get("type") == "tool_result":
                tag = "[RESULT ERROR]" if block.get("is_error") else "[RESULT]"
                lines.append(f"{tag} {_result_text(block.get('content', ''))}".rstrip())
    return "\n".join(lines[-limit:])


def _conn(path: str, create: bool = False) -> Optional[sqlite3.Connection]:
    if not path or (not create and not os.path.exists(path)):
        return None
    c = sqlite3.connect(path, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def _session_row(conn: Optional[sqlite3.Connection], issue: str) -> dict[str, Any]:
    """Whatever the DB still knows about the issue (sessions, then session_log)."""
    if conn is None:
        return {}
    for table in ("sessions", "session_log"):
        try:
            r = conn.execute(f"SELECT * FROM {table} WHERE issue_id=? "  # noqa: S608
                             "ORDER BY rowid DESC LIMIT 1", (issue,)).fetchone()
        except sqlite3.OperationalError:
            continue
        if r:
            return dict(r)
    return {}


def _harness_fp(conn: Optional[sqlite3.Connection], issue: str, row: dict[str, Any]) -> str:
    fp = row.get("harness_fp")
    if isinstance(fp, str) and fp.strip():
        return fp.strip()
    if conn is None:
        return ""
    try:
        r = conn.execute("SELECT harness_fp FROM session_harness WHERE issue_id=? "
                         "ORDER BY stamped_at DESC LIMIT 1", (issue,)).fetchone()
        return (r[0] or "").strip() if r else ""
    except sqlite3.OperationalError:
        return ""


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--issue", required=True)
    ap.add_argument("--jsonl", default=None, help="default /tmp/claude-run-<ISSUE>.jsonl")
    ap.add_argument("--text-file", default=None, help="final assistant text (overrides JSONL/DB)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--domain", default=None)
    ap.add_argument("--harness-fp", default=None)
    ap.add_argument("--dry-run", action="store_true", help="parse + print, store nothing")
    ap.add_argument("--offline-stub", default=None, help="read the reflection text from FILE")
    args = ap.parse_args(argv)

    issue = args.issue.strip()
    jsonl = args.jsonl or f"/tmp/claude-run-{issue}.jsonl"
    summary: dict[str, Any] = {"script": "reflect-session", "issue": issue}
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = _conn(args.db, create=not args.dry_run)
        row = _session_row(conn, issue)

        text = ""
        if args.text_file:
            with open(args.text_file, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            summary["text_source"] = "text-file"
        if not text.strip() and os.path.exists(jsonl):
            text = final_text_from_jsonl(jsonl)
            summary["text_source"] = "jsonl"
        if not text.strip() and row.get("last_response_b64"):
            try:
                text = base64.b64decode(row["last_response_b64"]).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                text = ""
            summary["text_source"] = "db"
        if not text.strip():
            summary["skipped"] = "no-text"
            print(json.dumps(summary, ensure_ascii=False))
            return 0

        excerpt = trajectory_excerpt(jsonl) if os.path.exists(jsonl) else ""
        summary["excerpt_lines"] = len(excerpt.splitlines()) if excerpt else 0

        if args.offline_stub:
            with open(args.offline_stub, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
            summary["model"] = "offline-stub"
        else:
            raw = R.reflect(text, excerpt)
            summary["model"] = os.environ.get("REFLECTION_MODEL", R.DEFAULT_MODEL)

        parsed = R.parse_reflection(raw)
        domain = args.domain or R.domain_key(issue, row.get("alert_category") or "", issue)
        fp = (args.harness_fp or "").strip() or _harness_fp(conn, issue, row)
        summary.update(domain=domain, harness_fp=fp, no_entry=parsed["no_entry"],
                       dropped=parsed["dropped"], edits=len(parsed["edits"]),
                       verdict="entry" if parsed["experience"] else "no_entry")

        if args.dry_run:
            summary["dry_run"] = True
            summary["parsed"] = parsed
            print(json.dumps(summary, ensure_ascii=False))
            return 0

        if conn is None:
            summary["error"] = f"db not reachable: {args.db}"
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        rid = R.store_reflection(conn, issue, parsed, domain=domain, harness_fp=fp)
        summary["stored_id"] = rid
        summary["stored"] = rid is not None
    except Exception as e:  # noqa: BLE001 - fail-open, always exit 0
        summary["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
