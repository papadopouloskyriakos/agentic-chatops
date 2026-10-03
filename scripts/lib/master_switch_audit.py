#!/usr/bin/env python3
"""
master_switch_audit.py — tamper-evident append + verify for master_switch_log (IFRNLLEI01PRD-1823).

SHA-256 hash chain: row_hash = sha256(prev_row_hash + canonical(row)). Any UPDATE, DELETE, or reorder
of a committed row breaks the chain from that point on — the same construction as the platform's
governance ledger (session_risk_audit) and the renovate autonomy ledger (renovate_audit.py).
gateway-master-switch.py appends THROUGH here on every power-off/power-on transition, and verifies
the chain on every `status` run (→ gateway_master_switch_chain_intact gauge).

CLI:
  master_switch_audit.py append  --db X  (row as --json '<obj>' or JSON on stdin)  → chained insert
  master_switch_audit.py verify  --db X  → prints OK / BROKEN:<id>; exit 0 / 1
  master_switch_audit.py tail    --db X  [--n 10] → last N rows as JSON lines
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time

# LOCKSTEP: this COLS order is the hash canonicalization order AND the INSERT column order.
# verify() replays rows with the same list. Never reorder or insert in the middle — append only,
# and bump schema_version in scripts/lib/schema_version.py when the shape changes.
COLS = ["ts", "action", "mode", "operator", "reason", "hostname", "sentinels_json",
        "cronicle_json", "n8n_json", "sessions_json", "maintenance_action", "partial",
        "details_json", "schema_version"]

DDL = """CREATE TABLE IF NOT EXISTS master_switch_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, action TEXT, mode TEXT, operator TEXT,
  reason TEXT, hostname TEXT, sentinels_json TEXT, cronicle_json TEXT, n8n_json TEXT,
  sessions_json TEXT, maintenance_action TEXT, partial INTEGER, details_json TEXT,
  schema_version INTEGER NOT NULL DEFAULT 1, prev_hash TEXT, row_hash TEXT)"""


def _conn(db):
    c = sqlite3.connect(db, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute(DDL)
    c.execute("CREATE INDEX IF NOT EXISTS idx_master_switch_log_schema_v ON master_switch_log(schema_version)")
    return c


def _norm(v):
    """Type-stable canonicalization so append-time (in-memory Python) and verify-time (SQLite
    readback) hash IDENTICALLY. bool→'1'/'0' (SQLite stores bools as ints), int/float via str,
    None→a NUL sentinel that no real string collides with, everything else via str."""
    if v is None:
        return "\x00NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(v)


def _canon(row):
    return "|".join(_norm(row.get(k)) for k in COLS)


def _anchor_path(db):
    return os.environ.get("MASTER_SWITCH_ANCHOR", db + ".msw-anchor.json")


def _write_anchor(db, rows, last_hash):
    try:
        with open(_anchor_path(db), "w") as f:
            json.dump({"rows": rows, "last_hash": last_hash}, f)
    except OSError:
        pass


def _read_anchor(db):
    try:
        with open(_anchor_path(db)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def append(db, row):
    """Chained insert. row: dict with COLS keys (missing → None). Returns (id, row_hash).

    SQLite-visible values only: callers must pass str/int/float/None (JSON-encode structures)
    so append-time and verify-time canonicalization agree."""
    row = dict(row)
    row.setdefault("ts", int(time.time()))
    row.setdefault("schema_version", 1)  # registry: scripts/lib/schema_version.py master_switch_log
    c = _conn(db)
    try:
        c.isolation_level = None
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute(
            "SELECT row_hash FROM master_switch_log WHERE row_hash IS NOT NULL AND row_hash != '' "
            "ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = cur[0] if cur else "GENESIS"
        row_hash = hashlib.sha256((prev_hash + "|" + _canon(row)).encode("utf-8")).hexdigest()
        placeholders = ",".join(["?"] * (len(COLS) + 2))
        c.execute(
            f"INSERT INTO master_switch_log ({','.join(COLS)},prev_hash,row_hash) VALUES ({placeholders})",
            [row.get(k) for k in COLS] + [prev_hash, row_hash])
        rowid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        rows = c.execute("SELECT COUNT(*) FROM master_switch_log").fetchone()[0]
        c.execute("COMMIT")
        # Truncation anchor: a hash chain alone cannot detect deletion of the TAIL (or a full
        # wipe re-linking from GENESIS). The side-car anchor records (rows, last_hash) on every
        # append; verify() cross-checks it.
        _write_anchor(db, rows, row_hash)
        return rowid, row_hash
    finally:
        c.close()


def verify(db):
    """Replay the chain + cross-check the truncation anchor.

    Returns (ok: bool, first_break_id: int, rows: int). first_break_id -1 = anchor mismatch
    (tail truncation / wipe), -2 = anchor row-count regression."""
    c = _conn(db)
    try:
        prev = "GENESIS"
        n = 0
        last_hash = None
        for r in c.execute(
                f"SELECT id,{','.join(COLS)},prev_hash,row_hash FROM master_switch_log ORDER BY id ASC"):
            n += 1
            rid = r[0]
            row = {k: r[i + 1] for i, k in enumerate(COLS)}
            stored_prev, stored_hash = r[-2], r[-1]
            expect = hashlib.sha256((prev + "|" + _canon(row)).encode("utf-8")).hexdigest()
            if stored_prev != prev or stored_hash != expect:
                return False, rid, n
            prev = stored_hash
            last_hash = stored_hash
        anchor = _read_anchor(db)
        if anchor is not None:
            if n < int(anchor.get("rows", 0)):
                return False, -2, n
            if n == int(anchor.get("rows", 0)) and last_hash != anchor.get("last_hash"):
                return False, -1, n
        return True, 0, n
    finally:
        c.close()


def tail(db, n=10):
    c = _conn(db)
    try:
        rows = c.execute(
            f"SELECT id,{','.join(COLS)},row_hash FROM master_switch_log ORDER BY id DESC LIMIT ?",
            (n,)).fetchall()
        out = []
        for r in reversed(rows):
            d = {"id": r[0]}
            d.update({k: r[i + 1] for i, k in enumerate(COLS)})
            d["row_hash"] = r[-1]
            out.append(d)
        return out
    finally:
        c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["append", "verify", "tail"])
    ap.add_argument("--db", default=os.environ.get(
        "MASTER_SWITCH_DB", os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")))
    ap.add_argument("--json", help="row JSON for append (default: stdin)")
    ap.add_argument("--n", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "append":
        row = json.loads(a.json) if a.json else json.load(sys.stdin)
        rowid, h = append(a.db, row)
        print(json.dumps({"id": rowid, "row_hash": h}))
    elif a.cmd == "verify":
        ok, first_break, n = verify(a.db)
        print(f"OK rows={n}" if ok else f"BROKEN:{first_break} rows={n}")
        sys.exit(0 if ok else 1)
    else:
        for d in tail(a.db, a.n):
            print(json.dumps(d))


if __name__ == "__main__":
    main()
