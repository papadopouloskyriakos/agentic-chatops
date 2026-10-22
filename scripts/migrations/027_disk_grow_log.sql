-- 027: disk_grow_log — audit + rate-cap ledger for the auto-disk-grow actuator
-- (operator alert-automation directive #3, 2026-07-08). One row per executed grow.
-- The actuator refuses a second grow on the same guest within --rate-cap-days
-- (default 7) — repeated pressure on a just-grown guest means a real leak, escalate.
CREATE TABLE IF NOT EXISTS disk_grow_log (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  hostname           TEXT NOT NULL,
  vmid               INTEGER NOT NULL,
  node               TEXT NOT NULL,
  guest_type         TEXT NOT NULL DEFAULT '',       -- lxc | qemu
  disk_key           TEXT NOT NULL DEFAULT '',        -- rootfs | scsi0 | ...
  storage            TEXT NOT NULL DEFAULT '',
  before_size_g      REAL NOT NULL DEFAULT 0,
  grow_g             REAL NOT NULL DEFAULT 0,
  after_size_g       REAL NOT NULL DEFAULT 0,
  fs_pct_before      INTEGER NOT NULL DEFAULT -1,
  fs_pct_after       INTEGER NOT NULL DEFAULT -1,
  pool_free_pct_after REAL NOT NULL DEFAULT -1,
  cleanup_reclaimed_g REAL NOT NULL DEFAULT 0,
  outcome            TEXT NOT NULL DEFAULT '',         -- grown | cleanup-only | refused-* | escalated-*
  detail             TEXT NOT NULL DEFAULT '',
  grown_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
  schema_version     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_diskgrow_vmid ON disk_grow_log(vmid, grown_at);
CREATE INDEX IF NOT EXISTS idx_diskgrow_schema_v ON disk_grow_log(schema_version);
