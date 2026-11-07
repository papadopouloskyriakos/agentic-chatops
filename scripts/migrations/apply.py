#!/usr/bin/env python3
"""Migration runner for gateway.db.

Auto-discovers *.sql files in the same directory, applies them in order,
and tracks applied migrations in the schema_migrations table so re-runs
are no-ops.

Design:
- Each migration is a standalone .sql file named NNN_description.sql
  (three-digit zero-padded version prefix).
- Statements are separated by semicolon + newline. Empty statements are
  skipped. Comment-only lines (starting with --) are stripped.
- Idempotency is belt-and-suspenders: the schema_migrations table prevents
  re-apply, AND sqlite3.OperationalError for "duplicate column" /
  "already exists" is caught so legacy live-applied migrations converge.

Usage:
  python3 scripts/migrations/apply.py              # apply all pending
  python3 scripts/migrations/apply.py --dry-run    # show what would run
  python3 scripts/migrations/apply.py --status     # list applied/pending
"""
import argparse
import os
REDACTED_a7b84d63
import sqlite3
import sys

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))
MIGRATION_RE = re.compile(r"^(\d{3})_([a-z0-9_-]+)\.sql$")

IDEMPOTENT_ERRORS = ("duplicate column", "already exists")


def ensure_tracking_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now')),
            filename TEXT NOT NULL
        )"""
    )
    conn.commit()


def discover_migrations():
    """Return sorted list of (version, name, path) tuples."""
    files = []
    for fn in sorted(os.listdir(MIGRATIONS_DIR)):
        m = MIGRATION_RE.match(fn)
        if not m:
            continue
        files.append((m.group(1), m.group(2), os.path.join(MIGRATIONS_DIR, fn)))
    return files


def applied_versions(conn):
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def extract_statements(sql_text):
    """Split on `;` at line boundaries. Comment lines are stripped.

    Deliberately simple splitter — migrations here stick to DDL
    (ALTER, CREATE), so a full SQL parser is overkill.
    """
    stmts = []
    buf = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                stmts.append(stmt)
            buf = []
    if buf:
        tail = "\n".join(buf).strip()
        if tail:
            stmts.append(tail)
    return stmts


def apply_migration(conn, version, name, path, dry_run=False):
    with open(path) as f:
        text = f.read()
    stmts = extract_statements(text)
    skipped = 0
    for stmt in stmts:
        if dry_run:
            preview = stmt[:80] + ("..." if len(stmt) > 80 else "")
            print(f"  WOULD APPLY ({version}): {preview}")
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as e:
            if any(err in str(e).lower() for err in IDEMPOTENT_ERRORS):
                skipped += 1
                continue
            print(f"ERROR in {os.path.basename(path)}: {e}", file=sys.stderr)
            print(f"Statement: {stmt[:200]}", file=sys.stderr)
            raise
    if not dry_run:
        conn.execute(
            "INSERT INTO schema_migrations (version, name, filename) VALUES (?, ?, ?)",
            (version, name, os.path.basename(path)),
        )
    return skipped


def cmd_status():
    conn = sqlite3.connect(DB_PATH)
    ensure_tracking_table(conn)
    applied = applied_versions(conn)
    all_migs = discover_migrations()
    print(f"Gateway DB: {DB_PATH}")
    print(f"Discovered: {len(all_migs)} migrations")
    for version, name, _ in all_migs:
        mark = "[APPLIED]" if version in applied else "[PENDING]"
        print(f"  {mark} {version}_{name}")
    pending = [m for m in all_migs if m[0] not in applied]
    print(f"\nPending: {len(pending)}")
    conn.close()


def cmd_apply(dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    ensure_tracking_table(conn)
    applied = applied_versions(conn)
    all_migs = discover_migrations()
    pending = [(v, n, p) for v, n, p in all_migs if v not in applied]

    if not pending:
        print(f"No pending migrations ({len(all_migs)} already applied).")
        conn.close()
        return

    print(f"{'DRY RUN -- ' if dry_run else ''}Applying {len(pending)} migration(s):")
    total_skipped = 0
    for version, name, path in pending:
        print(f"  -> {version}_{name}")
        skipped = apply_migration(conn, version, name, path, dry_run=dry_run)
        total_skipped += skipped
    if not dry_run:
        conn.commit()
    conn.close()
    print(f"\nDone. idempotent_skipped_statements={total_skipped}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        cmd_status()
    else:
        cmd_apply(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
