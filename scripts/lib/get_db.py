#!/usr/bin/env python3
"""Single canonical gateway.db connection factory (IFRNLLEI01PRD-1090).

The split-brain — gateway-state/gateway.db (live sessions/locks) vs
claude-context/gateway.db (knowledge + cost ledger) — was consolidated
2026-06-16: the live `sessions`/`queue` + the 1,130 unique `llm_usage` rows were
merged into the claude-context file (the fresh superset for everything else), and
`~/gateway-state/gateway.db` is now a SYMLINK to it (same inode). This factory is
the ONE place that resolves the path so new code never reintroduces the split —
import `get_db()` instead of hardcoding either path. Honors a GATEWAY_DB override.
"""
import os
import sqlite3

CANONICAL_DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)


def db_path() -> str:
    return CANONICAL_DB_PATH


def get_db(timeout: int = 30, row_factory=None) -> sqlite3.Connection:
    """Open the one canonical gateway.db with WAL-friendly pragmas."""
    conn = sqlite3.connect(CANONICAL_DB_PATH, timeout=timeout)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


if __name__ == "__main__":
    import sys
    print(CANONICAL_DB_PATH)
    try:
        c = get_db()
        print(f"ok: sessions={c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]}, "
              f"incident_knowledge={c.execute('SELECT COUNT(*) FROM incident_knowledge').fetchone()[0]}")
    except Exception as e:
        print("ERR:", e)
        sys.exit(1)
