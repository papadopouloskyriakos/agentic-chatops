-- 024_renovate_autonomy_audit_hashchain.sql
-- Make renovate_autonomy_audit tamper-evident (IFRNLLEI01PRD-1645 benchmark hardening, Dim-6):
-- a SHA-256 hash chain (row_hash = sha256(prev_hash + canonical(row))). Written by
-- scripts/lib/renovate_audit.py; verified by write-renovate-autonomy-metrics.py → renovate_autonomy_chain_ok.
-- Idempotent-ish: renovate_audit.py also ADD COLUMNs on demand, so this is belt-and-suspenders.
-- (SQLite ADD COLUMN errors if the column exists; apply.py tolerates that, or run once on a fresh table.)
ALTER TABLE renovate_autonomy_audit ADD COLUMN prev_hash TEXT;
ALTER TABLE renovate_autonomy_audit ADD COLUMN row_hash TEXT;
