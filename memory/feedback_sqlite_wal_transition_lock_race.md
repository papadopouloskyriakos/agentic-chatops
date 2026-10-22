---
name: feedback-sqlite-wal-transition-lock-race
description: "SQLite lost-update race — PRAGMA journal_mode=WAL on every connect races the fresh-DB DELETE->WAL transition under concurrency, throwing a transient 'database is locked' that (if it fires before the txn try-block) is unretryable -> silent lost write. Fix = busy_timeout-first + guard/tolerate the WAL switch + retry the whole transaction."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 446fe240-f009-4fd5-a87c-b8ecb446a101
---

**Diagnosed + fixed 2026-06-26 in `scripts/lib/handoff_depth.py` (gateway MR !74), the qa/643-concurrent flaky failure.** Parallel `bump()`s lost updates (final depth 6/7 instead of 8).

**The bug (non-obvious):** `_connect()` ran `conn.execute("PRAGMA journal_mode=WAL")` on EVERY connect. On a fresh DELETE-mode DB, N concurrent writers race the rollback->WAL transition; switching journal mode needs an exclusive lock, so the losers get a transient **`sqlite3.OperationalError: database is locked`**. Crucially this fires inside `_connect`, which is called BEFORE the transaction's `try/except` block — so the error propagated out of `bump()` un-retried, and the bump silently vanished. `busy_timeout` did NOT save it because the WAL pragma ran before busy_timeout was set AND the journal-mode switch isn't fully covered by the busy handler.

**The fix (mirror `session_events._emit_insert`, whose docstring already described this exact race):**
1. Set `PRAGMA busy_timeout` FIRST, before any other statement.
2. Only switch to WAL **if not already WAL** (`PRAGMA journal_mode` check) and wrap in `try/except OperationalError: pass`.
3. Wrap the WHOLE `BEGIN IMMEDIATE ... COMMIT` transaction in a bounded retry loop (`for attempt in range(8): ... except OperationalError: sleep(0.03*(attempt+1)); else: raise`).
Result: stress 12/12 correct (8 parallel bumps), was ~2/3.

**Diagnostic lessons:**
- **Capture per-subprocess stderr under parallel load — do NOT `2>/dev/null`.** The "database is locked" Exit 1 was invisible until each parallel worker's stderr went to its own file.
- **Reproduce with the REAL schema, not a minimal one.** A minimal-schema repro got depth=8 every time (masked the race); only `sqlite3 db < schema.sql` (what the test's `fresh_db` uses) reproduced the loss.

**Companion lesson (same MR):** a **static grep-count test assertion goes stale after a DRY refactor.** qa/1100 asserted `busy_timeout=30000` appears exactly 2x, but a consolidation routed both write paths through one `_emit_insert` (appears 1x) — code correct, test stale. Fix = assert the PROPERTY (pragma present AND both paths `return _emit_insert(`), not a literal occurrence count.
