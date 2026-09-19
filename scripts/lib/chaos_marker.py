"""Shared chaos-active.json marker discipline — IFRNLLEI01PRD-709.

Every writer of `~/chaos-state/chaos-active.json` MUST go through this module
so that the single cross-process lock file `chaos-active.json.lock` is honored
and cross-scenario overwrites are refused atomically.

Public surface:
  - ChaosCollisionError
  - DEFAULT_STATE_PATH, DEFAULT_LOCK_PATH
  - marker_lock()              — context manager acquiring fcntl.LOCK_EX
  - read_existing_marker()     — parse current marker or return None
  - check_no_cross_drill()     — raise if an unexpired marker identifies a different drill
  - atomic_write_marker()      — os.replace-backed atomic write
  - install_marker()           — acquire lock + check + atomic write in one call

The lock file path matches `STATE_FILE + ".lock"`. This is the single shared
cross-process lock for chaos-test.py and chaos-port-shutdown.py (via
install_marker). Taking it serialises every writer.

Historical note: chaos-test.py::cmd_start used to acquire a redundant outer
flock on the same file path, which produced an EAGAIN self-conflict when the
inner marker_lock here re-flocked the same path on a different fd in the same
process. Removed 2026-04-25 (commit 8075721); see
`memory/chaos_cron_collision_20260423.md` § Re-observation for the timeline.
"""
from __future__ import annotations

import calendar
import contextlib
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Iterator, Optional

# Honour CHAOS_STATE_PATH at import time (IFRNLLEI01PRD-721). QA fixtures
# export the env var to a scratch tempdir so they never touch the real
# `~/chaos-state/` and can't accidentally leave the production marker in
# a stale state that the next cron fire would misread as "no drill active".
DEFAULT_STATE_PATH = Path(
    os.environ.get("CHAOS_STATE_PATH")
    or Path.home() / "chaos-state" / "chaos-active.json"
)
DEFAULT_LOCK_PATH = Path(str(DEFAULT_STATE_PATH) + ".lock")


class ChaosCollisionError(RuntimeError):
    """Raised when chaos-active.json belongs to a different, unexpired drill.

    Carries the existing marker's identity as attributes so callers can build
    a Matrix-clarity ABORT message without re-reading the state file. The
    re-read path is racy: between the `with marker_lock()` context exiting
    and the caller's except block running, another writer (or the conflicting
    drill's own completion) can clear the file, leaving the caller with
    only the default "unknown" fallback. Attributes avoid that hazard.
    """

    def __init__(self, msg, existing_marker=None):
        super().__init__(msg)
        self.existing_marker = existing_marker or {}
        self.other_scenario = self.existing_marker.get("scenario") \
            or self.existing_marker.get("chaos_type") or ""
        self.other_experiment_id = self.existing_marker.get("experiment_id") or ""
        self.other_triggered_by = self.existing_marker.get("triggered_by") or ""
        self.other_expires_at = self.existing_marker.get("expires_at") or ""


@contextlib.contextmanager
def marker_lock(lock_path: Path = DEFAULT_LOCK_PATH, *,
                blocking: bool = False) -> Iterator[None]:
    """Acquire the chaos-active lock via fcntl.flock. Non-blocking by default.

    Raises ChaosCollisionError on contention when blocking=False.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "w")
    try:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
        flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(fd, flags)
        except (IOError, OSError) as e:
            # Best-effort: read the current marker so the ABORT message can
            # name the drill that holds the lock. Under contention the file
            # is normally present; if read fails (race with rename etc) the
            # exception attributes fall back to empty strings.
            existing = None
            try:
                existing = read_existing_marker(
                    Path(str(lock_path).removesuffix(".lock"))
                )
            except Exception:
                pass
            raise ChaosCollisionError(
                f"cannot acquire chaos-active lock at {lock_path}: {e} "
                f"(another chaos writer is running)",
                existing_marker=existing,
            )
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except (IOError, OSError):
                pass
    finally:
        fd.close()


def _parse_iso_z(ts: str) -> float:
    """Parse 'YYYY-MM-DDTHH:MM:SSZ' as a UTC epoch. Returns 0 on junk."""
    try:
        return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return 0.0


def read_existing_marker(state_path: Path = DEFAULT_STATE_PATH) -> Optional[dict]:
    """Return the parsed marker dict, or None if absent/unreadable."""
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _drill_identity(marker: dict) -> tuple:
    """Derive a comparable identity tuple from a marker dict.

    chaos-port-shutdown.py uses `scenario`; chaos-test.py uses `experiment_id`.
    Both are accepted — two markers with matching (scenario, experiment_id)
    are considered the same drill; any mismatch is treated as cross-drill.
    """
    return (marker.get("scenario"), marker.get("experiment_id"))


def check_no_cross_drill(scenario_id: Optional[str],
                         experiment_id: Optional[str] = None,
                         *,
                         now_ts: Optional[float] = None,
                         state_path: Path = DEFAULT_STATE_PATH) -> None:
    """Raise ChaosCollisionError if an UNEXPIRED marker identifies a different drill.

    Expired markers are ignored (treated as stale; caller is free to overwrite).
    Missing markers are accepted silently.

    Pass whichever identity your writer uses — scenario_id (chaos-port-shutdown)
    OR experiment_id (chaos-test). If either matches the on-disk marker, no
    collision is reported.
    """
    existing = read_existing_marker(state_path)
    if not existing:
        return
    expires_ts = _parse_iso_z(existing.get("expires_at", ""))
    t_now = time.time() if now_ts is None else now_ts
    if expires_ts <= t_now:
        return  # stale, caller may overwrite
    existing_scenario, existing_exp = _drill_identity(existing)
    if scenario_id and existing_scenario == scenario_id:
        return
    if experiment_id and existing_exp == experiment_id:
        return
    raise ChaosCollisionError(
        f"chaos-active.json already owned by "
        f"scenario='{existing_scenario}' "
        f"experiment_id='{existing_exp}' "
        f"triggered_by='{existing.get('triggered_by')}' "
        f"expires {existing.get('expires_at')}",
        existing_marker=existing,
    )


def atomic_write_marker(payload: dict,
                        state_path: Path = DEFAULT_STATE_PATH,
                        *,
                        mode: int = 0o600) -> None:
    """Write the marker via tmpfile + os.replace so readers never see torn JSON."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile on same filesystem → rename is atomic.
    fd, tmp_path = tempfile.mkstemp(prefix=".chaos-marker-",
                                    dir=str(state_path.parent),
                                    text=True)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, state_path)
    except Exception:
        # Best-effort cleanup on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def install_marker(scenario_id: str,
                   window_sec: int,
                   *,
                   triggered_by: str,
                   extras: Optional[dict] = None,
                   state_path: Path = DEFAULT_STATE_PATH,
                   lock_path: Path = DEFAULT_LOCK_PATH) -> None:
    """Acquire lock → refuse cross-drill overwrite → atomic write.

    `extras` is merged into the marker payload and can carry driver-specific
    fields (suppressions list, experiment_id, recover_token, etc).
    """
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                               time.gmtime(time.time() + window_sec))
    payload = {
        "scenario": scenario_id,
        "started_at": started_at,
        "expires_at": expires_at,
        "triggered_by": triggered_by,
    }
    if extras:
        payload.update(extras)
    with marker_lock(lock_path):
        check_no_cross_drill(scenario_id, payload.get("experiment_id"),
                             state_path=state_path)
        atomic_write_marker(payload, state_path=state_path)
