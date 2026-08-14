#!/usr/bin/env python3
"""
renovate_audit.py — tamper-evident append + verify for renovate_autonomy_audit (Dim-6).

SHA-256 hash chain: row_hash = sha256(prev_row_hash + canonical(row)). Any UPDATE, DELETE, or reorder of
a committed row breaks the chain from that point on — the same construction as the platform's governance
ledger. renovate-mr-gate.sh and renovate-postmerge-verify.sh append THROUGH here so the ledger is chained,
and write-renovate-autonomy-metrics.py verifies it every run (→ renovate_autonomy_chain_ok / an alert).

CLI:
  renovate_audit.py append  --db X  (row as --json '<obj>' or JSON on stdin)  → chained insert
  renovate_audit.py verify  --db X  → prints OK / BROKEN:<id>; exit 0 / 1
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time

COLS = ["ts", "project_id", "mr_iid", "mr_title", "package_update", "tier", "snapshot_required",
        "ci_status", "review_verdict", "review_confidence", "decision", "reason", "mode",
        "gates_json", "schema_version"]

DDL = """CREATE TABLE IF NOT EXISTS renovate_autonomy_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, project_id TEXT, mr_iid TEXT, mr_title TEXT,
  package_update TEXT, tier TEXT, snapshot_required TEXT, ci_status TEXT, review_verdict TEXT,
  review_confidence REAL, decision TEXT, reason TEXT, mode TEXT, gates_json TEXT, schema_version INTEGER,
  prev_hash TEXT, row_hash TEXT)"""


def _conn(db):
    c = sqlite3.connect(db, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute(DDL)
    have = {r[1] for r in c.execute("PRAGMA table_info(renovate_autonomy_audit)")}
    for col in ("prev_hash", "row_hash"):
        if col not in have:
            c.execute(f"ALTER TABLE renovate_autonomy_audit ADD COLUMN {col} TEXT")
    return c


# Columns SQLite stores as REAL — must be coerced to a deterministic float form so append-time (python
# int/float, e.g. confidence 0) and verify-time (REAL readback 0.0) canonicalise IDENTICALLY. Without this
# str(0)=='0' != str(0.0)=='0.0' would false-report the chain BROKEN on any integer-confidence row.
_FLOAT_FIELDS = {"review_confidence"}


def _norm(k: str, v):
    if v is None:
        return None
    if k in _FLOAT_FIELDS:
        try:
            return repr(float(v))   # 0 → '0.0', 0.0 → '0.0', 0.95 → '0.95' (REAL round-trips exactly)
        except (TypeError, ValueError):
            return str(v)
    return str(v)


def _canon(row: dict) -> str:
    # normalise every field so append-time (python) and verify-time (sqlite readback) agree.
    return json.dumps({k: _norm(k, row.get(k)) for k in COLS}, sort_keys=True, separators=(",", ":"))


def append(db: str, row: dict) -> str:
    c = _conn(db)
    last = c.execute("SELECT row_hash FROM renovate_autonomy_audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = last[0] if last and last[0] else "GENESIS"
    row.setdefault("ts", int(time.time()))
    row.setdefault("schema_version", 1)
    rh = hashlib.sha256((prev + _canon(row)).encode()).hexdigest()
    c.execute(f"INSERT INTO renovate_autonomy_audit({','.join(COLS)},prev_hash,row_hash) "
              f"VALUES({','.join(['?'] * len(COLS))},?,?)",
              [row.get(k) for k in COLS] + [prev, rh])
    c.commit()
    c.close()
    return rh


def verify(db: str):
    """Return None if the chain is intact, else the id of the first broken row."""
    c = _conn(db)
    prev = "GENESIS"
    broken = None
    for r in c.execute(f"SELECT id,{','.join(COLS)},prev_hash,row_hash FROM renovate_autonomy_audit ORDER BY id"):
        rid = r[0]
        row = {k: r[i + 1] for i, k in enumerate(COLS)}
        ph, rh = r[-2], r[-1]
        exp = hashlib.sha256((prev + _canon(row)).encode()).hexdigest()
        if ph != prev or rh != exp:
            broken = rid
            break
        prev = rh
    c.close()
    return broken


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["append", "verify"])
    ap.add_argument("--db", default=os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db"))
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.cmd == "append":
        row = json.loads(a.json) if a.json else json.load(sys.stdin)
        append(a.db, row)
        print("APPENDED")
    else:
        b = verify(a.db)
        print("OK" if b is None else f"BROKEN:{b}")
        sys.exit(0 if b is None else 1)


if __name__ == "__main__":
    main()
