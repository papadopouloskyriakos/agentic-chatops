"""Scheduled-reboot registry + Tier 1 suppression matcher (2026-06-29).

Self-learning suppression of INTENTIONAL scheduled reboots so the agentic
system stops treating every daily/weekly reboot as a novel incident. A
deterministic schedule (cron / systemd-timer / unattended-upgrade) is discovered
or root-caused, registered (status='observing'), promoted to 'live' after
>= 2 confirmed on-schedule reboots (scripts/promote-scheduled-reboots.py), and
then matched at triage time to suppress the NEXT on-schedule reboot BEFORE a
YouTrack issue is created or a Claude session launches.

This module is PURE DB + math (no SSH). The two-phase verify-and-reopen that
follows a suppression is triggered by the calling bash flow
(openclaw/skills/lib/tier1-suppression-flow.sh) using this module's returned
signals.fire_utc; see scripts/verify-scheduled-reboot-boot.sh.

SAFETY FLOOR — every guard that stops a wrong registration from darkening a
real/unexpected reboot. ALL of these must hold to suppress; any failure
direction fails toward ESCALATE (investigate), never silent suppress:

  1. TIER1_SCHED_REBOOT_ENABLED env (default OFF) — lands dark, operator flips.
  2. severity == 'critical' -> NEVER suppress (always investigate).
  3. reboot-class rule allowlist only (REBOOT_RULE_PATTERNS) — a CPU/disk alert
     on a registered host at the scheduled minute is NOT matched.
  4. only status='live' rows (observing never suppresses — observe-before-live).
  5. kill_switch=0 AND valid_until>now in the matcher SQL (instant deactivate).
  6. STRICT time-window: now must fall in [fire-pre_buffer, fire+window] for the
     cron's prev OR next fire (host-local tz, DST-correct via croniter+zoneinfo).
     An off-schedule reboot (e.g. a self-heal at 13:09 on a host whose cron is
     07:00) is OUTSIDE both windows -> escalate. This is the irreducible-residual
     guard; the two-phase verify-and-reopen backstops the coincident-in-window case.

croniter is vendored at scripts/lib/vendor/croniter (dateutil + zoneinfo are
system-present); no install dependency on the safety-critical path.
"""
from __future__ import annotations

import datetime
import fnmatch
import json
import os
import sqlite3
import sys
from typing import Any, Optional

# ── vendored croniter (pure-python; dateutil + zoneinfo are system-present) ────
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)
try:
    from croniter import croniter  # type: ignore
except Exception:  # pragma: no cover - vendor missing = fail-open everywhere
    croniter = None  # type: ignore
from zoneinfo import ZoneInfo  # stdlib (3.9+)

# ── schema-version stamp (robust to sibling- or package-style import) ─────────
try:
    from schema_version import current as _schema_current  # type: ignore
except Exception:  # pragma: no cover
    try:
        from lib.schema_version import current as _schema_current  # type: ignore
    except Exception:
        _schema_current = lambda _t: 1  # type: ignore


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCHEDULED_EVENTS_JSON = os.path.join(REPO_ROOT, "config", "scheduled-events.json")

# Only reboot-class rule names are eligible. fnmatch globs, case-insensitive.
# Operator-tunable: config/scheduled-events.json["reboot_rule_patterns"] is merged
# on top of these defaults (Increment C lands that key; defaults keep the matcher
# working before then).
DEFAULT_REBOOT_RULE_PATTERNS = (
    "*reboot*",
    "*reloaded*",
    "*sysuptime*",
    "*uptime*",
    "*scheduled reboot*",
    "*device rebooted*",
)

DEFAULT_WINDOW_MINUTES = 10
DEFAULT_PRE_BUFFER_MINUTES = 5
DEFAULT_VALID_UNTIL_DAYS = 90
PROMOTION_THRESHOLD = 2          # >=2 confirmed in-window boots -> live
OBSERVATIONS_CAP = 10           # in_window_observations JSON list cap
UNKNOWN_TZ = "UTC"

_TABLE = "discovered_scheduled_reboots"


def _enabled() -> bool:
    """Global enable. An explicit TIER1_SCHED_REBOOT_ENABLED env var always wins
    (tests/CI: =1 on, anything else off). Otherwise the sentinel file
    ~/gateway.sched_reboot decides — `touch` to enable, `rm` to disable, instant,
    no n8n edit (matches the gateway.autonomy_forward convention)."""
    env = os.environ.get("TIER1_SCHED_REBOOT_ENABLED", "")
    if env:
        return env == "1"
    return os.path.exists(os.path.expanduser("~/gateway.sched_reboot"))


def load_reboot_rule_patterns() -> tuple[str, ...]:
    """DEFAULT_REBOOT_RULE_PATTERNS overlaid with config/scheduled-events.json
    `reboot_rule_patterns` if present. Tolerant of missing/corrupt config."""
    patterns = list(DEFAULT_REBOOT_RULE_PATTERNS)
    try:
        with open(SCHEDULED_EVENTS_JSON) as fh:
            cfg = json.load(fh)
        extra = cfg.get("reboot_rule_patterns") or []
        if isinstance(extra, list) and extra:
            # config is authoritative when set
            REDACTED_4529f8c2str(p) for p in extra]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return tuple(patterns)


def is_reboot_rule(rule_name: str, patterns: Optional[tuple[str, ...]] = None) -> bool:
    pats = patterns if patterns is not None else load_reboot_rule_patterns()
    rn = (rule_name or "").lower()
    return any(fnmatch.fnmatchcase(rn, p.lower()) for p in pats)


def _tz(name: str):
    """Resolve a tz name to a tzinfo, or None if unresolvable (e.g. the tzdata
    package absent on a slim image). Callers MUST fail OPEN on None — never
    silently fall back to UTC, which would compute fire times in the wrong zone
    and could match/suppress at the wrong time. ZoneInfo('UTC') always resolves
    (built into the stdlib), so tz='' or 'UTC' rows are never affected."""
    try:
        return ZoneInfo(name or UNKNOWN_TZ)
    except Exception:
        return None


def _fire_windows_utc(cron_expr: str, tz_name: str, now_utc: datetime.datetime,
                      window_minutes: int, pre_buffer_minutes: int) -> list[tuple[datetime.datetime, datetime.datetime, datetime.datetime]]:
    """Return [(wstart_utc, wend_utc, fire_utc), ...] for the cron's prev and
    next fires around now. Empty list on any parse/tz error (fail-open)."""
    if croniter is None:
        return []
    tz = _tz(tz_name)
    if tz is None:
        return []  # unresolvable tz -> fail-open (never suppress on a guessed UTC zone)
    base_local = now_utc.astimezone(tz)
    out: list[tuple[datetime.datetime, datetime.datetime, datetime.datetime]] = []
    for getter in ("get_prev", "get_next"):
        try:
            it = croniter(cron_expr, base_local, ret_type=datetime.datetime)
            fire_local = getattr(it, getter)()
        except Exception:
            return []  # malformed cron / unsupported expr -> no window -> escalate
        fire_utc = fire_local.astimezone(datetime.timezone.utc)
        wstart = fire_utc - datetime.timedelta(minutes=pre_buffer_minutes)
        wend = fire_utc + datetime.timedelta(minutes=window_minutes)
        out.append((wstart, wend, fire_utc))
    return out


def boot_matches_schedule(cron_expr: str, tz_name: str, boot_utc: datetime.datetime,
                          window_minutes: int = DEFAULT_WINDOW_MINUTES,
                          pre_buffer_minutes: int = DEFAULT_PRE_BUFFER_MINUTES) -> bool:
    """True iff boot_utc falls within [fire-pre_buffer, fire+window] for the cron's
    prev or next fire (host-local tz, DST-correct). Used by the promoter to confirm
    an observed boot was the scheduled one. Fail-OPEN-to-false on any parse error
    (an unconfirmable boot does not count toward promotion)."""
    for wstart, wend, _fire in _fire_windows_utc(cron_expr, tz_name, boot_utc,
                                                 window_minutes, pre_buffer_minutes):
        if wstart <= boot_utc <= wend:
            return True
    return False


def match_scheduled_reboot(hostname: str, rule_name: str, severity: str,
                           now_utc: datetime.datetime,
                           db_conn: sqlite3.Connection) -> dict[str, Any]:
    """The matcher. Returns a dict always:

        {"matched": bool, "reason": str, "signals": {...}}

    On match, signals carries row_id, cron_expr, tz, fire_utc (ISO Z),
    window_minutes, pre_buffer_minutes, rationale, observed_count — enough for
    the calling flow to launch the two-phase verify with fire_utc.

    NEVER raises — every error path returns matched=False (escalate).
    """
    def _no(reason: str, **sig) -> dict[str, Any]:
        return {"matched": False, "reason": reason, "signals": dict(sig)}

    if not _enabled():
        return _no("phaseSR: TIER1_SCHED_REBOOT_ENABLED=0 (lands dark)")
    if (severity or "").lower() == "critical":
        return _no("phaseSR: severity=critical never auto-suppressed")
    patterns = load_reboot_rule_patterns()
    if not is_reboot_rule(rule_name, patterns):
        return _no("phaseSR: rule_name not reboot-class — skip")

    now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = db_conn.execute(
            f"SELECT id, cron_expr, tz, window_minutes, pre_buffer_minutes, "
            f"rationale, observed_count FROM {_TABLE} "
            f"WHERE hostname=? AND status='live' AND kill_switch=0 AND valid_until>?",
            (hostname, now_iso),
        ).fetchall()
    except sqlite3.Error as exc:
        # Pre-migration DB (no such table) or any SQL error -> fail-open.
        return _no(f"phaseSR: SQL error ({type(exc).__name__}) — failing open",
                   error=str(exc)[:200])

    for row in rows:
        row_id, cron_expr, tz_name, win, pre, rationale, obs_count = row
        windows = _fire_windows_utc(cron_expr or "", tz_name or UNKNOWN_TZ,
                                    now_utc, win or DEFAULT_WINDOW_MINUTES,
                                    pre or DEFAULT_PRE_BUFFER_MINUTES)
        for wstart, wend, fire_utc in windows:
            if wstart <= now_utc <= wend:
                return {
                    "matched": True,
                    "reason": (f"phaseSR: on-schedule reboot "
                               f"(fire={fire_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}, "
                               f"window=[{wstart.strftime('%H:%M')}..{wend.strftime('%H:%M')}Z], "
                               f"row_id={row_id})"),
                    "signals": {
                        "row_id": row_id,
                        "cron_expr": cron_expr,
                        "tz": tz_name,
                        "fire_utc": fire_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "window_minutes": win,
                        "pre_buffer_minutes": pre,
                        "rationale": rationale,
                        "observed_count": obs_count,
                    },
                }

    return _no(f"phaseSR: no live row matched the strict window "
               f"(scanned {len(rows)} live rows; all off-window or unparseable)",
               live_rows_scanned=len(rows))


# ─────────────────────────────────────────────────────────────────────────────
# Registry CRUD — used by discover-scheduled-reboots.py / classify-reboot-alert.py
# / promote-scheduled-reboots.py (Increments B + C). All take an open sqlite3 conn.
# ─────────────────────────────────────────────────────────────────────────────
def _site_from_hostname(hostname: str) -> str:
    h = hostname or ""
    if h.startswith("grskg"):
        return "gr"
    if h.startswith("nllei") or h.startswith("nl"):
        return "nl"
    return ""


def upsert_observing(conn: sqlite3.Connection, hostname: str, cron_expr: str,
                     reboot_kind: str, *, tz: str = UNKNOWN_TZ, source: str = "discovery",
                     window_minutes: int = DEFAULT_WINDOW_MINUTES,
                     pre_buffer_minutes: int = DEFAULT_PRE_BUFFER_MINUTES,
                     rationale: str = "") -> int:
    """Insert a new observing row, or no-op if an identical (host,expr,kind)
    row already exists (preserves status/observed_count of an existing live row)."""
    valid = (datetime.datetime.now(datetime.timezone.utc)
             + datetime.timedelta(days=DEFAULT_VALID_UNTIL_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sv = _schema_current(_TABLE)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        cur = conn.execute(
            f"INSERT INTO {_TABLE} (hostname, site, cron_expr, tz, reboot_kind, source, "
            f"window_minutes, pre_buffer_minutes, status, valid_until, rationale, "
            f"discovered_at, schema_version) "
            f"VALUES (?,?,?,?,?,?,?,?,'observing',?,?,?,?) "
            f"ON CONFLICT(hostname, cron_expr, reboot_kind) DO UPDATE SET "
            f"tz=excluded.tz, window_minutes=excluded.window_minutes, "
            f"pre_buffer_minutes=excluded.pre_buffer_minutes, rationale=excluded.rationale, "
            f"valid_until=excluded.valid_until, schema_version=excluded.schema_version "
            # NOTE: deliberately NOT touching status/observed_count/kill_switch —
            # a re-discovery must not silently (re)observe a host that promoted to
            # live, nor clear a kill_switch.
            f"WHERE {_TABLE}.kill_switch=0",
            (hostname, _site_from_hostname(hostname), cron_expr, tz, reboot_kind, source,
             window_minutes, pre_buffer_minutes, valid, rationale, now, sv),
        )
        conn.commit()
        return cur.rowcount or 0
    except sqlite3.Error:
        return 0


def record_observation(conn: sqlite3.Connection, row_id: int,
                       boot_utc: datetime.datetime) -> bool:
    """Append a confirmed in-window boot timestamp (capped) + bump observed_count.
    Called by the promoter after it confirms a boot landed in-window."""
    boot_iso = boot_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        row = conn.execute(f"SELECT in_window_observations, observed_count FROM {_TABLE} WHERE id=?",
                           (row_id,)).fetchone()
        if not row:
            return False
        try:
            obs = json.loads(row[0] or "[]")
        except (json.JSONDecodeError, TypeError):
            obs = []
        if boot_iso not in obs:
            obs.append(boot_iso)
        obs = obs[-OBSERVATIONS_CAP:]
        conn.execute(
            f"UPDATE {_TABLE} SET in_window_observations=?, observed_count=?, "
            f"last_reboot_at=? WHERE id=?",
            (json.dumps(obs), len(obs), boot_iso, row_id),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def promote_eligible(conn: sqlite3.Connection,
                     threshold: int = PROMOTION_THRESHOLD) -> int:
    """Flip every observing row with observed_count >= threshold to 'live'.
    Returns the number promoted. Safe-direction only."""
    try:
        cur = conn.execute(
            f"UPDATE {_TABLE} SET status='live' "
            f"WHERE status='observing' AND kill_switch=0 AND observed_count>=?",
            (threshold,),
        )
        conn.commit()
        return cur.rowcount or 0
    except sqlite3.Error:
        return 0


def disable(conn: sqlite3.Connection, row_id: int, reason: str = "") -> bool:
    try:
        conn.execute(f"UPDATE {_TABLE} SET status='disabled', rationale=? WHERE id=?",
                     (reason, row_id))
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def set_kill_switch(conn: sqlite3.Connection, row_id: int, on: bool) -> bool:
    try:
        conn.execute(f"UPDATE {_TABLE} SET kill_switch=? WHERE id=?", (1 if on else 0, row_id))
        conn.commit()
        return True
    except sqlite3.Error:
        return False


def renew_on_match(conn: sqlite3.Connection, row_id: int) -> None:
    """Renew valid_until when the matcher actually suppresses (keeps a live,
    actively-matching schedule from expiring). Best-effort."""
    try:
        valid = (datetime.datetime.now(datetime.timezone.utc)
                 + datetime.timedelta(days=DEFAULT_VALID_UNTIL_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(f"UPDATE {_TABLE} SET valid_until=?, last_match_at=? WHERE id=?",
                     (valid, now, row_id))
        conn.commit()
    except sqlite3.Error:
        pass


def list_rows(conn: sqlite3.Connection, hostname: Optional[str] = None) -> list[dict]:
    where = "WHERE hostname=?" if hostname else ""
    params: tuple = (hostname,) if hostname else ()
    try:
        rows = conn.execute(
            f"SELECT id, hostname, cron_expr, tz, reboot_kind, status, observed_count, "
            f"kill_switch, valid_until, rationale FROM {_TABLE} {where} "
            f"ORDER BY hostname, id",
            params,
        ).fetchall()
    except sqlite3.Error:
        return []
    cols = ["id", "hostname", "cron_expr", "tz", "reboot_kind", "status",
            "observed_count", "kill_switch", "valid_until", "rationale"]
    return [dict(zip(cols, r)) for r in rows]
