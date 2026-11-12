# Runbook — Scheduled-reboot suppression (self-learning, 2026-06-29)

## What it is
Stop treating **intentional scheduled reboots** (e.g. `nl-gpu01` daily 07:00
GPU/VRAM-mitigation cron) as novel incidents. A new Tier-1 phase (**phase SR**, in
`scripts/lib/tier1_suppression.py`, runs *between* blast-radius fold and the
knowledge-pattern match) suppresses an on-schedule reboot on a host that has a
**live / un-killed / un-expired** registered deterministic schedule — **before**
YouTrack-issue creation and before a Claude session launches. A **two-phase verify**
then re-checks the actual boot reason and **re-opens + pages** if it wasn't a clean
`systemd-reboot`.

Self-learning loop (the host gets added to the registry automatically):
- `scripts/discover-scheduled-reboots.py` (weekly Cronicle) — proactive sweep of all
  PVE guests+nodes for reboot `cron` / systemd-timer / `unattended-upgrades` schedules.
- `scripts/classify-reboot-alert.py` (RCA at triage, infra-triage Step 2) — when a
  reboot alert reaches investigation, RCAs it; if the root cause is a deterministic
  trigger **and** the boot was clean, registers the host `observing`.
- `scripts/promote-scheduled-reboots.py` (daily Cronicle) — `observing`→`live` after
  **≥2 confirmed in-window boots** (behavioral confirmation of the declared cron),
  + drift (cron removed → disable) + `valid_until` expiry.

Registry table: `discovered_scheduled_reboots` (migration `022_*`). Matcher core:
`scripts/lib/scheduled_reboots.py` (`match_scheduled_reboot`). Reboot-rule allowlist:
`config/scheduled-events.json` `reboot_rule_patterns`. Full build:
[`memory/scheduled_reboot_suppression_build_20260629.md`](../../memory/scheduled_reboot_suppression_build_20260629.md).

## Safety floor (every guard must hold to suppress; all failures fail OPEN = escalate)
- **Env/sentinel gate** — off unless `TIER1_SCHED_REBOOT_ENABLED=1` **or** sentinel
  `~/gateway.sched_reboot` exists (env wins for tests/CI; sentinel is the prod toggle,
  matches `gateway.autonomy_forward`). Ships dark.
- **severity=critical** → never suppressed (always investigated).
- **Reboot-class rule allowlist only** — a CPU/disk alert on a registered host at the
  scheduled minute is NOT matched.
- **observe-before-live** — `status='observing'` rows never suppress; only `live`.
- **`kill_switch=0` AND `valid_until>now`** — in the matcher's SQL `WHERE` (instant
  deactivate; no cache).
- **Strict time-window** — `now ∈ [fire−pre_buffer, fire+window]` for the cron's prev
  OR next fire, computed in the host's local tz (DST-correct via vendored
  `croniter` + stdlib `zoneinfo`). An off-schedule reboot (e.g. a 13:09 self-heal on a
  host whose cron is 07:00) is outside both windows → investigated.
- **Fail-open** — per-row `try/except` + outer wrapper + the flow's `timeout 10 …`.
  Any error (malformed cron, unresolvable tz, DB error) → escalate, never silent suppress.
- **Two-phase verify-and-reopen** — the irreducible residual (a reactive reboot that
  coincidentally lands in-window) is caught within ~60s by `verify-scheduled-reboot-boot.sh`,
  which SSHes the host, reads the boot reason, and if NOT a clean `systemd-reboot`
  (OOM/panic/watchdog/self-heal/unknown) → force-escalates + pages `#alerts`.

## Activate / deactivate
- **Activate:** `touch ~/gateway.sched_reboot` (enables matcher + classifier hook).
  One host can be seeded manually: `python3 scripts/discover-scheduled-reboots.py --host <h>`
  then `python3 scripts/promote-scheduled-reboots.py` (promotes once ≥2 boots confirmed).
- **Deactivate (instant, global):** `rm ~/gateway.sched_reboot`.
- **Deactivate one host:** `sqlite3 <db> "UPDATE discovered_scheduled_reboots SET kill_switch=1 WHERE hostname='<h>';"`.
- **Disable a Cronicle job:** `cronicle.set_enabled(<event_id>, False, session_id)` or the UI.

## Cronicle jobs (`scripts/register-scheduled-reboot-cronicle.py`, idempotent)
| job | event id | schedule |
|---|---|---|
| discover | `emqzcrk789p` | Sun 05:17 UTC |
| promote | `emqzcrk7l9q` | daily 06:30 UTC |
| metrics | `emqzcrk7x9r` | every 5 min |
| digest | `emqzcrk8g9s` | Mon 05:00 UTC |
| audit | `emqzcrk8q9t` | Mon 05:30 UTC |

> The matcher itself runs **inline at triage** (no cron needed) — suppression works as
> soon as the sentinel is on + a host is `live`, independent of these jobs. The jobs are
> for proactive discovery, promotion, observability, and the weekly reconcile.

## Metrics (node_exporter textfile `scheduled_reboot_metrics.prom`) + alerts
| metric | meaning |
|---|---|
| `scheduled_reboot_registry_entries{status}` | rows by observing/live/disabled |
| `scheduled_reboot_verified_total` | two-phase verifies that confirmed a clean reboot |
| `scheduled_reboot_misclassified_total` | verifies that REOPENED (boot not clean) |
| `scheduled_reboot_verify_unreachable_total` | host couldn't be SSH-checked |
| `scheduled_reboot_metrics_last_run_timestamp_seconds` | exporter freshness |

Alerts (`prometheus/alert-rules/agentic-health.yml`, group `scheduled-reboot`):
`ScheduledRebootMisclassified` (critical/tier1 — note: the **two-phase verify already
pages in real time**; this is the aggregate), `ScheduledRebootMetricsStale`,
`ScheduledRebootPromotionStuck`. **The alert tf-twin (`agentic-health-alerts.tf`) is
deferred** — the YAML is the doc/test copy; deploy via IaC when ready.

Holistic health: `scripts/holistic-agentic-health.sh` §43 (matcher-wired, croniter
vendored, metrics fresh, registry hygiene). Weekly reconcile: `scripts/audit-scheduled-reboot-suppressions.sh`.
Spec: EARS REQ-404..407 + REQ-506; BDD `spec/005-tier1-suppression/acceptance/*.feature`;
QA `scripts/qa/suites/test-1160-scheduled-reboot-matcher.sh`.

## Debug ladder
- **A reboot that should suppress didn't:** is `~/gateway.sched_reboot` present? Is the
  host `status='live' AND kill_switch=0 AND valid_until>now`? Is the rule reboot-class
  (`config/scheduled-events.json reboot_rule_patterns`)? Is severity != critical? Is the
  alert time in-window? — `python3 -c "import sys;sys.path.insert(0,'scripts/lib');import scheduled_reboots as sr,sqlite3,datetime;print(sr.match_scheduled_reboot('<host>','<rule>','warning',datetime.datetime.fromisoformat('<utc+00:00>'),sqlite3.connect('<db>')))"`.
- **A reboot that was suppressed shouldn't have been:** check `event_log`
  (`event_type='tier1_suppression'`, `payload_json LIKE '%phaseSR%'`) + the two-phase
  verify counters (`~/gateway-state/scheduled-reboot-verify-counters.json`); the verify
  should have reopened it. If it didn't reopen, the boot reason read as clean — review
  `~/logs/claude-gateway/scheduled-reboot-verify.log`.
- **Host stuck `observing`:** the promoter can't confirm ≥2 in-window boots (wrong cron
  expr? host not SSH-able from nl-claude01?). Re-run `promote-scheduled-reboot --lookback-days 30`.
- **`journalctl --list-boots --utc` is NOT honored** (prints local tz) — the
  promoter/verify use `-o json` + `first_entry` epoch-µs instead.

## Operator-locked design decisions (2026-06-29)
Two-phase suppress+verify-and-reopen (not weekly-audit-only) · ≥2-boot promotion ·
digest-only (no per-host YouTrack control issues) · always-investigate-critical.
