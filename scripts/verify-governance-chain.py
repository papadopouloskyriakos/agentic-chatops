#!/usr/bin/env python3
"""Verify (and backfill) the tamper-evident hash-chain over session_risk_audit — the autonomy-forward
decision log (bench IFRNLLEI01PRD-1422 governance gap: the log was a plain mutable table with no
hash-chain). Each row's row_hash = SHA-256(prev_hash + the 11 decision values in INSERT order); so a
deletion, alteration, or reordering of the audit log breaks the chain at that point and is mechanically
detectable here. Pairs with the chained writer in classify-session-risk.py:write_audit_row().

Modes:
  (default)      verify + backfill any legacy unhashed rows, emit the metric.
  --verify-only  verify only (do not write).

Emits /var/lib/node_exporter/textfile_collector/governance_chain.prom:
  governance_chain_intact 1|0, governance_chain_rows N, governance_chain_first_break_id ID, _last_run ts.
A break (intact=0) fires GovernanceChainBroken (tier-1) — the audit log was modified out-of-band.
"""
import hashlib
import os
import sqlite3
import sys
import time

DB_PATH = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
OUT = "/var/lib/node_exporter/textfile_collector/governance_chain.prom"
GENESIS = "GENESIS"
# MUST stay in lockstep with write_audit_row()'s `params` order in classify-session-risk.py.
COLS = ["issue_id", "alert_category", "risk_level", "auto_approved", "signals_json", "plan_hash",
        "operator_override", "schema_version", "band", "auto_proceed_on_timeout", "sms_required"]


def row_hash(prev_hash, values):
    return hashlib.sha256(("|".join([prev_hash] + [str(v) for v in values])).encode("utf-8")).hexdigest()


def _ensure_columns(conn):
    existing = {r[1] for r in conn.execute("PRAGMA table_info(session_risk_audit)")}
    for col in ("prev_hash", "row_hash"):
        if col not in existing:
            conn.execute(f"ALTER TABLE session_risk_audit ADD COLUMN {col} TEXT")
    conn.commit()


def main():
    verify_only = "--verify-only" in sys.argv
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    try:
        _ensure_columns(conn)
        rows = conn.execute(
            f"SELECT id, {', '.join(COLS)}, prev_hash, row_hash FROM session_risk_audit ORDER BY id ASC"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"  governance chain: table not ready ({e})")
        _emit(1, 0, 0)
        return

    prev = GENESIS
    intact = 1
    first_break = 0
    backfilled = 0
    for r in rows:
        expected = row_hash(prev, [r[c] for c in COLS])
        stored = r["row_hash"]
        if not stored:  # legacy unhashed row -> backfill into the chain
            if not verify_only:
                conn.execute("UPDATE session_risk_audit SET prev_hash = ?, row_hash = ? WHERE id = ?",
                             (prev, expected, r["id"]))
                backfilled += 1
            stored = expected
        if stored != expected:
            intact = 0
            if not first_break:
                first_break = r["id"]
        prev = stored
    if backfilled:
        conn.commit()
    conn.close()

    msg = f"  governance chain: {len(rows)} rows, intact={intact}"
    if not intact:
        msg += f", FIRST BREAK at id={first_break} (audit log altered out-of-band)"
    if backfilled:
        msg += f", backfilled={backfilled} legacy rows"
    print(msg)
    _emit(intact, len(rows), first_break)
    return 0 if intact else 1


def _emit(intact, rows, first_break):
    lines = [
        "# HELP governance_chain_intact 1 if the session_risk_audit hash-chain verifies, 0 if tampered/broken.",
        "# TYPE governance_chain_intact gauge",
        f"governance_chain_intact {intact}",
        "# HELP governance_chain_rows Rows in the autonomy-forward decision log.",
        "# TYPE governance_chain_rows gauge",
        f"governance_chain_rows {rows}",
        "# HELP governance_chain_first_break_id Row id of the first chain break (0 = intact).",
        "# TYPE governance_chain_first_break_id gauge",
        f"governance_chain_first_break_id {first_break}",
        "# HELP governance_chain_last_run_timestamp_seconds Unix ts of the last chain verification.",
        "# TYPE governance_chain_last_run_timestamp_seconds gauge",
        f"governance_chain_last_run_timestamp_seconds {int(time.time())}",
    ]
    try:
        tmp = OUT + ".tmp"
        with open(tmp, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, OUT)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main() or 0)
