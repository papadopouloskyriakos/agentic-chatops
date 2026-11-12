#!/usr/bin/env python3
"""Domain-first lessons block for the Runner Build Prompt (Harness² reuse R5).

Harness² retrieves earlier harnesses by CONSTRUCTION (one library directory per
domain) before any similarity search. This prints the last N structured
reflection entries (verdict='entry') for the session's domain as a markdown block,
so Build Prompt can show them ahead of the similarity-ranked RAG hits.

Usage:
  domain-lessons.py --issue IFRNLLEI01PRD-1234 [--category kubernetes | --summary S --description D] [--limit 5] [--db PATH] [--b64]

Prints nothing when the domain has no entries (the block is optional). --b64 emits
a single base64 line so an n8n SSH node can carry it without newline mangling.
Fail-open: any error prints nothing and exits 0.
"""
from __future__ import annotations

import argparse
import base64
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DEFAULT_DB = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)


def build_block(issue: str, category: str, limit: int, db_path: str) -> str:
    from lib.reflection import domain_key, recent_domain_entries, render_domain_block
    domain = domain_key(issue, category or "", issue)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lessons_learned'"
        ).fetchone():
            return ""
        cols = {r[1] for r in conn.execute("PRAGMA table_info(lessons_learned)")}
        if "domain" not in cols:
            return ""  # pre-029 schema: no domain key
        entries = recent_domain_entries(conn, domain, limit=limit)
    finally:
        conn.close()
    if not entries:
        return ""
    return render_domain_block(entries, domain=domain)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--issue", required=True)
    ap.add_argument("--category", default="", help="alert category; derived from --summary/--description when empty")
    ap.add_argument("--summary", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--b64", action="store_true")
    a = ap.parse_args(argv)
    try:
        category = a.category
        if not category and (a.summary or a.description):
            from lib.reflection import classify_alert_category
            category = classify_alert_category(a.summary, a.description[:2000])
        block = build_block(a.issue, category, a.limit, a.db)
    except Exception as exc:  # noqa: BLE001 — fail-open by contract
        print(f"domain-lessons: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    if not block:
        return 0
    if a.b64:
        print(base64.b64encode(block.encode("utf-8")).decode("ascii"))
    else:
        print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
