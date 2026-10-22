-- 022_discovered_scheduled_reboots.sql — self-learning scheduled-reboot suppression
--
-- One row per (host, deterministic reboot schedule, reboot kind). The Tier 1
-- matcher (scripts/lib/scheduled_reboots.py::match_scheduled_reboot, wired into
-- tier1_suppression.py as phase SR) reads ONLY status='live' rows; 'observing'
-- rows never suppress (observe-before-live: a schedule must confirm >=2 real
-- in-window reboots before it can suppress — see scripts/promote-scheduled-reboots.py).
--
-- Safety floor lives in the matcher SQL + code, not here:
--   * status='live' AND kill_switch=0 AND valid_until>now  (the matcher WHERE)
--   * strict time-window match (cron prev/next fire in host-local tz, DST-correct)
--   * severity=critical NEVER suppresses; reboot-class rule allowlist only.
--
-- reboot_kind values: cron | systemd-timer | unattended-upgrade | eem_watchdog.
--   cron_expr is a 5-field cron expression (cron) OR a systemd OnCalendar value
--   (systemd-timer) OR the literal 'unattended' / 'eem_watchdog' sentinel.
-- source: discovery (weekly sweep) | classifier (RCA at triage) | operator.

CREATE TABLE IF NOT EXISTS discovered_scheduled_reboots (
  id                     INTEGER PRIMARY KEY AUTOINCREMENT,
  hostname               TEXT    NOT NULL,
  site                   TEXT    NOT NULL DEFAULT '',           -- nl|gr (hostname prefix / netbox)
  cron_expr              TEXT    NOT NULL,                      -- 5-field cron OR systemd calendar OR sentinel
  tz                     TEXT    NOT NULL DEFAULT 'Europe/Amsterdam',  -- host-local tz (from timedatectl); DST-correct via zoneinfo
  reboot_kind            TEXT    NOT NULL CHECK (reboot_kind IN
                           ('cron','systemd-timer','unattended-upgrade','eem_watchdog')),
  source                 TEXT    NOT NULL DEFAULT 'discovery', -- discovery|classifier|operator
  window_minutes         INTEGER NOT NULL DEFAULT 10,          -- +side: host expected down/rebooting past the fire
  pre_buffer_minutes     INTEGER NOT NULL DEFAULT 5,           -- -side: allow an early alert before the fire
  status                 TEXT    NOT NULL DEFAULT 'observing'
                           CHECK (status IN ('observing','live','disabled')),
  observed_count         INTEGER NOT NULL DEFAULT 0,           -- in-window boots confirmed (promoter increments)
  in_window_observations TEXT    NOT NULL DEFAULT '[]',        -- JSON list of UTC boot timestamps (capped 10) — promotion evidence
  last_reboot_at         DATETIME,                             -- last in-window boot observed (UTC)
  last_match_at          DATETIME,                             -- last time the matcher actually suppressed (UTC)
  valid_until            DATETIME NOT NULL,                    -- row TTL; renewed on each match; default now+90d
  kill_switch            INTEGER NOT NULL DEFAULT 0,           -- 1 = force-deactivate instantly (checked in matcher SQL)
  rationale              TEXT    NOT NULL DEFAULT '',          -- audit reason / trigger command line
  discovered_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  schema_version         INTEGER NOT NULL DEFAULT 1            -- scripts/lib/schema_version.py registry
);

-- Matcher hot path: live, un-killed, un-expired rows for a host.
CREATE INDEX IF NOT EXISTS idx_dsr_match ON discovered_scheduled_reboots(hostname, cron_expr)
  WHERE status = 'live' AND kill_switch = 0;

-- Promoter / drift / expiry sweeps.
CREATE INDEX IF NOT EXISTS idx_dsr_status     ON discovered_scheduled_reboots(status);
CREATE INDEX IF NOT EXISTS idx_dsr_valid_until ON discovered_scheduled_reboots(valid_until);
CREATE INDEX IF NOT EXISTS idx_dsr_host       ON discovered_scheduled_reboots(hostname);

-- One row per (host, schedule, kind) — clean upsert target for discovery/classifier.
CREATE UNIQUE INDEX IF NOT EXISTS uq_dsr_host_expr_kind
  ON discovered_scheduled_reboots(hostname, cron_expr, reboot_kind);
