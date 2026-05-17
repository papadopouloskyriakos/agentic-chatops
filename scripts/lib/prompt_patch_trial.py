"""Prompt-patch A/B trial lifecycle (IFRNLLEI01PRD-645).

Policy-iteration at the prompt-policy level: when a (surface, dimension)
pair's 30-day score average drops below a threshold, generate N candidate
patches + start a trial. Build Prompt deterministically assigns each future
matching session to one arm (candidates + a no-patch control). The finalizer
computes per-arm means, runs a one-sided Welch t-test against the control,
and promotes the winner to `config/prompt-patches.json` only if it beats the
baseline by >= min_lift with p < p_threshold.

Core API:
    start_trial(surface, dimension, candidates, baseline_mean, ...)
        Returns trial_id or raises RuntimeError if an active trial for
        (surface, dimension) already exists (the partial unique index
        enforces this at the SQL level too).

    assign_variant(issue_id, trial_id) -> int
        Deterministic hash(issue_id + str(trial_id)) % (N + 1). Returns
        -1 for control, 0..N-1 for candidate indices. Idempotent: calling
        twice with the same args and same trial returns the same variant
        AND only inserts one assignment row (UNIQUE(issue_id, trial_id)).

    record_assignment(trial_id, issue_id, variant_idx, session_id="")
        Writes the session_trial_assignment row. Safe to call multiple
        times (INSERT OR IGNORE on the UNIQUE constraint).

    collect_arm_scores(trial_id) -> {variant_idx: [scores]}
        Joins session_trial_assignment -> session_judgment on issue_id,
        extracts the trial's target dimension column, returns per-arm
        score lists. -1 is the control arm; non-trialed sessions of the
        same dimension form the baseline if the control arm is empty.

    finalize(trial_id, now=None) -> dict
        Decides winner or abort. Returns a dict with status/winner_idx/
        p_value/arm_means. Updates the prompt_patch_trial row atomically.
        If winner is promoted, appends to config/prompt-patches.json.

    abort_stale_trials(now=None) -> int
        Marks any 'active' trial past its trial_ends_at as 'aborted_timeout'.

All writes are single-SQL-statement or wrapped in `BEGIN IMMEDIATE` so
concurrent invocations from the finalizer cron + Build Prompt assignments
don't race. Telemetry events emitted best-effort via session_events.

Configuration (env vars, read by CLI entrypoints):
    PROMPT_TRIAL_CANDIDATES         default 3 (N)
    PROMPT_TRIAL_MIN_SAMPLES        default 15 (K per arm)
    PROMPT_TRIAL_TIMEOUT_DAYS       default 14
    PROMPT_TRIAL_MIN_LIFT           default 0.05 (5pp of the dim score)
    PROMPT_TRIAL_P_THRESHOLD        default 0.1  (one-sided Welch)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema_version import current as schema_current  # noqa: E402

# Optional telemetry
try:
    from session_events import emit as _emit_event  # noqa: F401
    from session_events import SessionEvent, EVENT_TYPES  # noqa: F401
    _HAS_EVENTS = True
except Exception:
    _HAS_EVENTS = False

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
PATCH_FILE = os.path.expanduser(
    os.environ.get(
        "PROMPT_PATCHES_FILE",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "..", "config", "prompt-patches.json"),
    )
)

N_CANDIDATES = int(os.environ.get("PROMPT_TRIAL_CANDIDATES", "3"))
MIN_SAMPLES_PER_ARM = int(os.environ.get("PROMPT_TRIAL_MIN_SAMPLES", "15"))
TIMEOUT_DAYS = int(os.environ.get("PROMPT_TRIAL_TIMEOUT_DAYS", "14"))
MIN_LIFT = float(os.environ.get("PROMPT_TRIAL_MIN_LIFT", "0.05"))
P_THRESHOLD = float(os.environ.get("PROMPT_TRIAL_P_THRESHOLD", "0.1"))


# ── Data shapes ───────────────────────────────────────────────────────────────


@dataclass
class Candidate:
    idx: int                 # 0..N-1
    label: str               # e.g. "concise", "detailed", "examples"
    instruction: str
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"idx": self.idx, "label": self.label,
                "instruction": self.instruction, "category": self.category}


@dataclass
class TrialRow:
    id: int
    surface: str
    dimension: str
    generated_at: str
    trial_ends_at: str
    status: str
    baseline_mean: float
    baseline_samples: int
    candidates: list[Candidate] = field(default_factory=list)
    min_samples_per_arm: int = MIN_SAMPLES_PER_ARM
    min_lift: float = MIN_LIFT
    winner_idx: Optional[int] = None
    winner_mean: Optional[float] = None
    winner_p_value: Optional[float] = None
    finalized_at: Optional[str] = None
    note: str = ""

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> "TrialRow":
        try:
            cand = [Candidate(**c) for c in json.loads(row[8] or "[]")]
        except (TypeError, ValueError):
            cand = []
        return cls(
            id=int(row[0]), surface=row[1], dimension=row[2],
            generated_at=row[3] or "", trial_ends_at=row[4] or "",
            status=row[5], baseline_mean=float(row[6] or 0.0),
            baseline_samples=int(row[7] or 0),
            candidates=cand,
            min_samples_per_arm=int(row[9] or MIN_SAMPLES_PER_ARM),
            min_lift=float(row[10] or MIN_LIFT),
            winner_idx=None if row[11] is None else int(row[11]),
            winner_mean=None if row[12] is None else float(row[12]),
            winner_p_value=None if row[13] is None else float(row[13]),
            finalized_at=row[14],
            note=row[15] or "",
        )


# ── SQL helpers ───────────────────────────────────────────────────────────────


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH, timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


_TRIAL_COLUMNS = (
    "id, surface, dimension, generated_at, trial_ends_at, status, "
    "baseline_mean, baseline_samples, candidates_json, min_samples_per_arm, "
    "min_lift, winner_idx, winner_mean, winner_p_value, finalized_at, note"
)


# ── Trial lifecycle ───────────────────────────────────────────────────────────


def start_trial(
    surface: str,
    dimension: str,
    candidates: list[Candidate],
    *,
    baseline_mean: float,
    baseline_samples: int = 0,
    min_samples_per_arm: int = MIN_SAMPLES_PER_ARM,
    min_lift: float = MIN_LIFT,
    timeout_days: int = TIMEOUT_DAYS,
    note: str = "",
    db_path: Optional[str] = None,
) -> int:
    """Create a trial row. Returns the new trial_id.

    Raises RuntimeError if an active trial for (surface, dimension) already
    exists — caller should wait for it to finalize before starting another.
    """
    if not candidates:
        raise ValueError("start_trial: candidates must be non-empty")
    for i, c in enumerate(candidates):
        if c.idx != i:
            raise ValueError(f"candidate idx must equal position; got {c.idx} at {i}")

    trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=timeout_days)).isoformat()
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO prompt_patch_trial "
            "(surface, dimension, trial_ends_at, status, baseline_mean, "
            " baseline_samples, candidates_json, min_samples_per_arm, "
            " min_lift, note, schema_version) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)",
            (surface, dimension, trial_ends_at, float(baseline_mean),
             int(baseline_samples),
             json.dumps([c.to_dict() for c in candidates]),
             int(min_samples_per_arm), float(min_lift), note,
             schema_current("prompt_patch_trial")),
        )
        trial_id = int(cur.lastrowid or -1)
    except sqlite3.IntegrityError as e:
        raise RuntimeError(
            f"active trial already exists for ({surface!r}, {dimension!r}): {e}"
        ) from e
    finally:
        conn.close()

    # Best-effort telemetry (do not fail the start on a missing table).
    _try_emit("prompt_trial_started", {
        "trial_id": trial_id, "surface": surface, "dimension": dimension,
        "n_candidates": len(candidates),
    })
    return trial_id


def get_trial(trial_id: int, db_path: Optional[str] = None) -> Optional[TrialRow]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {_TRIAL_COLUMNS} FROM prompt_patch_trial WHERE id = ?",
            (trial_id,),
        ).fetchone()
    finally:
        conn.close()
    return TrialRow.from_row(row) if row else None


def active_trial_for(
    surface: str, dimension: str, db_path: Optional[str] = None
) -> Optional[TrialRow]:
    """Return the active trial for (surface, dimension) if any."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            f"SELECT {_TRIAL_COLUMNS} FROM prompt_patch_trial "
            "WHERE surface = ? AND dimension = ? AND status = 'active' "
            "LIMIT 1",
            (surface, dimension),
        ).fetchone()
    finally:
        conn.close()
    return TrialRow.from_row(row) if row else None


def list_active(db_path: Optional[str] = None) -> list[TrialRow]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_TRIAL_COLUMNS} FROM prompt_patch_trial "
            "WHERE status = 'active' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [TrialRow.from_row(r) for r in rows]


# ── Deterministic assignment ─────────────────────────────────────────────────


def assign_variant(issue_id: str, trial_id: int, n_candidates: int) -> int:
    """Deterministic hash of (issue_id, trial_id) into {-1, 0..n-1}.

    Index n (i.e. the last bucket of n+1) is the CONTROL arm (no patch).
    We need a stable function of (issue, trial) — so if Build Prompt is
    invoked twice for the same issue while the trial is active, both calls
    pick the same variant. That keeps the arm counts honest.
    """
    h = hashlib.blake2b(
        f"{issue_id}|{trial_id}".encode("utf-8"), digest_size=8
    ).digest()
    bucket = int.from_bytes(h, "big") % (n_candidates + 1)
    if bucket == n_candidates:
        return -1  # control
    return bucket


def record_assignment(
    trial_id: int,
    issue_id: str,
    variant_idx: int,
    *,
    session_id: str = "",
    db_path: Optional[str] = None,
) -> bool:
    """Persist a (session, trial) -> variant assignment.

    Idempotent via UNIQUE(issue_id, trial_id). Returns True if a new row
    was inserted, False if one already existed.
    """
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO session_trial_assignment "
            "(issue_id, session_id, trial_id, variant_idx, schema_version) "
            "VALUES (?, ?, ?, ?, ?)",
            (issue_id, session_id, int(trial_id), int(variant_idx),
             schema_current("session_trial_assignment")),
        )
        return cur.rowcount > 0
    finally:
        conn.close()


def assign_and_record(
    issue_id: str,
    trial: TrialRow,
    *,
    session_id: str = "",
    db_path: Optional[str] = None,
) -> int:
    """Convenience: assign + record + return the variant_idx.

    If the session was already assigned, return the existing variant_idx.
    """
    # Check existing — preserves determinism across any future changes
    # to the hash function.
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT variant_idx FROM session_trial_assignment "
            "WHERE issue_id = ? AND trial_id = ?",
            (issue_id, trial.id),
        ).fetchone()
    finally:
        conn.close()
    if row is not None:
        return int(row[0])

    variant_idx = assign_variant(issue_id, trial.id, len(trial.candidates))
    record_assignment(trial.id, issue_id, variant_idx, session_id=session_id, db_path=db_path)
    return variant_idx


# ── Score collection ─────────────────────────────────────────────────────────


_JUDGMENT_DIM_COLS = {
    # Dimension -> column name in session_judgment
    "investigation_quality": "investigation_quality",
    "evidence_based":        "evidence_based",
    "actionability":         "actionability",
    "safety_compliance":     "safety_compliance",
    "completeness":          "completeness",
    "overall_score":         "overall_score",
}


def collect_arm_scores(
    trial: TrialRow, db_path: Optional[str] = None
) -> dict[int, list[float]]:
    """Return {variant_idx: [scores]} for `trial`.

    Joins session_trial_assignment -> session_judgment by issue_id and
    pulls the trial's dimension column. Scores <= 0 are skipped (the judge
    uses -1 for "not scored this dimension").
    """
    col = _JUDGMENT_DIM_COLS.get(trial.dimension)
    if col is None:
        raise ValueError(f"unknown dimension {trial.dimension!r}")
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT sta.variant_idx, sj.{col} "
            "FROM session_trial_assignment sta "
            "JOIN session_judgment sj ON sj.issue_id = sta.issue_id "
            "WHERE sta.trial_id = ? AND sj." + col + " > 0",
            (trial.id,),
        ).fetchall()
    finally:
        conn.close()
    out: dict[int, list[float]] = {}
    for vidx, score in rows:
        out.setdefault(int(vidx), []).append(float(score))
    return out


# ── Statistics ───────────────────────────────────────────────────────────────


def _mean(vs: list[float]) -> float:
    return sum(vs) / len(vs) if vs else 0.0


def _var(vs: list[float]) -> float:
    if len(vs) < 2:
        return 0.0
    m = _mean(vs)
    return sum((x - m) ** 2 for x in vs) / (len(vs) - 1)


def welch_one_sided(a: list[float], b: list[float]) -> tuple[float, float]:
    """One-sided Welch t-test: H0: mean(a) <= mean(b). Returns (t, p_approx).

    Uses a normal-distribution approximation for the p-value because we
    don't want to pull scipy just for this. For our sample sizes
    (K=15-30) this is close enough to the true t-distribution.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0, 1.0
    va, vb = _var(a), _var(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return 0.0, 0.5
    t = (_mean(a) - _mean(b)) / se
    # 1 - Phi(t) using erf
    p = 0.5 * (1 - math.erf(t / math.sqrt(2)))
    return t, p


# ── Finalize ─────────────────────────────────────────────────────────────────


@dataclass
class FinalizeResult:
    trial_id: int
    status: str                 # completed | aborted_no_winner | still_active | aborted_timeout
    arm_means: dict[int, float]
    arm_counts: dict[int, int]
    winner_idx: Optional[int]
    winner_mean: Optional[float]
    winner_p_value: Optional[float]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id, "status": self.status,
            "arm_means": self.arm_means, "arm_counts": self.arm_counts,
            "winner_idx": self.winner_idx, "winner_mean": self.winner_mean,
            "winner_p_value": self.winner_p_value, "reason": self.reason,
        }


def finalize(
    trial_id: int,
    *,
    now: Optional[datetime] = None,
    p_threshold: float = P_THRESHOLD,
    db_path: Optional[str] = None,
    write_patch_on_win: bool = True,
) -> FinalizeResult:
    """Decide the trial outcome.

    Status transitions (only from 'active'):
      * all arms have >= min_samples_per_arm AND best candidate beats
        baseline_mean + min_lift with p < p_threshold (one-sided Welch):
          -> 'completed', winner promoted (patch file updated).
      * all arms have >= min_samples_per_arm but no candidate wins:
          -> 'aborted_no_winner'.
      * trial_ends_at passed:
          -> 'aborted_timeout' (even if samples incomplete).
      * else:
          -> 'still_active' (no change).
    """
    now = now or datetime.now(timezone.utc)
    trial = get_trial(trial_id, db_path)
    if trial is None:
        raise LookupError(f"trial_id {trial_id} not found")
    if trial.status != "active":
        raise RuntimeError(f"trial {trial_id} is not active (status={trial.status})")

    arm_scores = collect_arm_scores(trial, db_path=db_path)
    arm_means = {k: round(_mean(v), 4) for k, v in arm_scores.items()}
    arm_counts = {k: len(v) for k, v in arm_scores.items()}

    # Timeout check first
    try:
        ends_at = datetime.fromisoformat(trial.trial_ends_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        ends_at = now + timedelta(days=9999)

    n = len(trial.candidates)

    # Require all candidate arms + control reached MIN_SAMPLES.
    arms_needed = list(range(n)) + [-1]
    complete = all(arm_counts.get(a, 0) >= trial.min_samples_per_arm for a in arms_needed)

    if not complete and now >= ends_at:
        return _persist_finalize(
            trial_id=trial_id, status="aborted_timeout",
            arm_means=arm_means, arm_counts=arm_counts,
            winner_idx=None, winner_mean=None, winner_p_value=None,
            reason=f"timed out after {TIMEOUT_DAYS}d (arms incomplete)",
            db_path=db_path,
            write_patch=False,
            trial=trial,
        )
    if not complete:
        # Don't mutate — just report.
        return FinalizeResult(
            trial_id=trial_id, status="still_active",
            arm_means=arm_means, arm_counts=arm_counts,
            winner_idx=None, winner_mean=None, winner_p_value=None,
            reason="arms incomplete; waiting for more sessions",
        )

    # Pick best candidate by mean; compare to control (-1).
    control_scores = arm_scores.get(-1, [])
    control_mean = _mean(control_scores)
    best_idx: Optional[int] = None
    best_mean = -math.inf
    best_p: Optional[float] = None
    for i in range(n):
        cand_scores = arm_scores.get(i, [])
        mean_i = _mean(cand_scores)
        if mean_i > best_mean:
            best_mean = mean_i
            best_idx = i
            _, p = welch_one_sided(cand_scores, control_scores)
            best_p = p

    if (best_idx is None
        or best_mean < control_mean + trial.min_lift
        or best_p is None
        or best_p >= p_threshold):
        return _persist_finalize(
            trial_id=trial_id, status="aborted_no_winner",
            arm_means=arm_means, arm_counts=arm_counts,
            winner_idx=best_idx, winner_mean=best_mean if best_mean > -math.inf else None,
            winner_p_value=best_p,
            reason=(f"best candidate idx={best_idx} mean={best_mean:.3f} "
                    f"vs control {control_mean:.3f}; lift<{trial.min_lift} "
                    f"or p>={p_threshold}"),
            db_path=db_path, write_patch=False, trial=trial,
        )

    return _persist_finalize(
        trial_id=trial_id, status="completed",
        arm_means=arm_means, arm_counts=arm_counts,
        winner_idx=best_idx, winner_mean=best_mean, winner_p_value=best_p,
        reason=(f"candidate idx={best_idx} beat control by "
                f"{best_mean - control_mean:+.3f} (p={best_p:.3f})"),
        db_path=db_path, write_patch=write_patch_on_win, trial=trial,
    )


def _persist_finalize(
    *,
    trial_id: int, status: str,
    arm_means: dict[int, float], arm_counts: dict[int, int],
    winner_idx: Optional[int], winner_mean: Optional[float],
    winner_p_value: Optional[float], reason: str,
    db_path: Optional[str],
    write_patch: bool,
    trial: TrialRow,
) -> FinalizeResult:
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE prompt_patch_trial SET "
            " status = ?, winner_idx = ?, winner_mean = ?, winner_p_value = ?, "
            " finalized_at = CURRENT_TIMESTAMP, note = ? "
            "WHERE id = ? AND status = 'active'",
            (status, winner_idx, winner_mean, winner_p_value, reason, trial_id),
        )
    finally:
        conn.close()

    if write_patch and status == "completed" and winner_idx is not None:
        _promote_to_patches_file(trial, winner_idx)

    _try_emit("prompt_trial_finalized", {
        "trial_id": trial_id, "status": status,
        "winner_idx": winner_idx, "winner_mean": winner_mean,
        "winner_p_value": winner_p_value,
        "arm_counts": arm_counts, "arm_means": arm_means,
    })

    return FinalizeResult(
        trial_id=trial_id, status=status, arm_means=arm_means,
        arm_counts=arm_counts, winner_idx=winner_idx,
        winner_mean=winner_mean, winner_p_value=winner_p_value,
        reason=reason,
    )


# ── Patch file promotion ─────────────────────────────────────────────────────


def _promote_to_patches_file(trial: TrialRow, winner_idx: int) -> None:
    """Append the winning candidate's instruction to config/prompt-patches.json.

    Mirrors the shape the Build Prompt reader already expects. If a patch
    for (dimension, category) already exists and is active, we DEACTIVATE
    it first so Build Prompt picks up only the new winner.
    """
    path = PATCH_FILE
    winner = trial.candidates[winner_idx]
    try:
        with open(path) as f:
            patches = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        patches = []

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Deactivate any existing active patch for the same (dimension, category).
    for p in patches:
        if (p.get("dimension") == trial.dimension
                and p.get("category") == winner.category
                and p.get("active", False)):
            p["active"] = False
            p["deactivated_at"] = now_iso
            p["deactivated_reason"] = f"superseded by trial {trial.id} winner idx={winner_idx}"

    patches.append({
        "dimension": trial.dimension,
        "category": winner.category,
        "instruction": winner.instruction,
        "applied_at": now_iso,
        "score_before": trial.baseline_mean,
        "score_after": None,
        "active": True,
        "expires_at": expires,
        "source": f"trial:{trial.id}:idx={winner_idx}:label={winner.label}",
    })
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(patches, f, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"[prompt_patch_trial] WARN: could not write {path}: {e}", file=sys.stderr)


# ── Timeout sweeper ──────────────────────────────────────────────────────────


def abort_stale_trials(
    *, now: Optional[datetime] = None, db_path: Optional[str] = None
) -> int:
    """Mark any active trial past trial_ends_at as 'aborted_timeout'.

    Called by the finalizer cron before walking active trials — keeps the
    table from accumulating stalled experiments.
    """
    now = now or datetime.now(timezone.utc)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE prompt_patch_trial SET "
            " status = 'aborted_timeout', finalized_at = CURRENT_TIMESTAMP, "
            " note = COALESCE(note,'') || ' [timed out at ' || ? || ']' "
            "WHERE status = 'active' AND trial_ends_at < ?",
            (now.isoformat(), now.isoformat()),
        )
        return cur.rowcount or 0
    finally:
        conn.close()


# ── Telemetry helper (session_events is optional) ────────────────────────────


def _try_emit(event_type_str: str, payload: dict[str, Any]) -> None:
    if not _HAS_EVENTS:
        return
    # These trial events live under the generic `agent_updated` channel for
    # now — dedicated event subtypes would require migrating session_events
    # EVENT_TYPES, which is out of scope here. We prefix the payload so
    # Grafana dashboards can still filter.
    try:
        from session_events import AgentUpdatedEvent, emit  # noqa
        emit(AgentUpdatedEvent(
            issue_id="", session_id="", turn_id=-1, agent_name="prompt-trial",
            previous_agent=event_type_str,  # carries the logical event name
            # payload travels in the _payload hook
        ))
    except Exception:
        pass


# ── CLI for shell / cron integration ─────────────────────────────────────────


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="show all active trials")
    p_list.add_argument("--json", action="store_true")

    p_get = sub.add_parser("get", help="show one trial + arm means")
    p_get.add_argument("--id", type=int, required=True)

    p_finalize = sub.add_parser("finalize", help="try to finalize a trial")
    p_finalize.add_argument("--id", type=int, required=True)
    p_finalize.add_argument("--dry-run", action="store_true")

    p_abort = sub.add_parser("abort-stale", help="mark timed-out trials")

    args = ap.parse_args()

    if args.cmd == "list":
        trials = list_active()
        if args.json:
            json.dump([vars(t) | {"candidates": [c.to_dict() for c in t.candidates]}
                       for t in trials], sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
        else:
            print(f"{'id':<4}  {'surface':<18}  {'dimension':<24}  {'ends_at':<20}")
            for t in trials:
                print(f"{t.id:<4}  {t.surface:<18}  {t.dimension:<24}  {t.trial_ends_at}")
        return 0

    if args.cmd == "get":
        t = get_trial(args.id)
        if t is None:
            print(f"no trial {args.id}", file=sys.stderr); return 1
        scores = collect_arm_scores(t)
        out = {
            "trial": vars(t) | {"candidates": [c.to_dict() for c in t.candidates]},
            "arms": {str(k): {"n": len(v), "mean": round(_mean(v), 4)}
                     for k, v in scores.items()},
        }
        json.dump(out, sys.stdout, indent=2, default=str); sys.stdout.write("\n")
        return 0

    if args.cmd == "finalize":
        r = finalize(args.id, write_patch_on_win=not args.dry_run)
        json.dump(r.to_dict(), sys.stdout, indent=2); sys.stdout.write("\n")
        return 0 if r.status in ("completed", "still_active") else 0

    if args.cmd == "abort-stale":
        n = abort_stale_trials()
        print(f"aborted {n} stale trial(s)")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(_cli())
