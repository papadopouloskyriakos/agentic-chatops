"""Circuit breaker for external API / service calls (IFRNLLEI01PRD-631).

Three-state pattern per Netflix Hystrix / Martin Fowler:

    CLOSED    (normal)      calls pass through; record_failure increments counter.
                            N consecutive failures -> OPEN.
    OPEN      (tripped)     calls short-circuit to `fallback` (or raise).
                            After `cooldown_seconds`, transitions to HALF_OPEN.
    HALF_OPEN (probe)       one call is allowed through as a canary.
                            Success -> CLOSED; failure -> OPEN again.

State is persisted to SQLite so sibling processes (Runner + Poller + cron
scripts invoking the same breaker name) share one view of upstream health.

Usage (decorator):

    from lib.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker("ollama", failure_threshold=3, cooldown_seconds=60)

    @cb.wrap(fallback=lambda *a, **kw: {"embedding": None})
    def get_embedding(text):
        ...

Usage (imperative — when you need finer control):

    if not cb.allow():
        return fallback_value
    try:
        result = call_api()
        cb.record_success()
        return result
    except Exception:
        cb.record_failure()
        raise

Prometheus textfile exporter:
    python3 -m lib.circuit_breaker --export /path/to/breaker_metrics.prom
"""
from __future__ import annotations

import argparse
import enum
import json
import os
import sqlite3
import sys
import threading
import time
from typing import Any, Callable, Optional

DEFAULT_DB = os.environ.get(
    "CIRCUIT_BREAKER_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)


class State(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised when a breaker is open and no fallback was supplied."""


class CircuitBreaker:
    """Per-named-endpoint circuit breaker with SQLite-backed state.

    Thread-safe within a process. Cross-process coordination via the shared
    SQLite row. Not race-free across processes in the millisecond window
    around state transitions, but the monotonic "failures accumulate then
    trip" pattern tolerates small races — worst case is one extra failure
    gets recorded before all workers see OPEN.
    """

    _registry: dict[str, "CircuitBreaker"] = {}
    _registry_lock = threading.Lock()

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: int = 60,
        half_open_successes_needed: int = 1,
        sqlite_path: Optional[str] = None,
    ) -> None:
        if not name or not name.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"invalid breaker name: {name!r}")
        self.name = name
        self.failure_threshold = int(failure_threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self.half_open_successes_needed = int(half_open_successes_needed)
        self.sqlite_path = sqlite_path if sqlite_path is not None else DEFAULT_DB

        self._lock = threading.Lock()
        self._state = State.CLOSED
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._half_open_successes = 0

        self._init_schema()
        existed = self._load_state()
        if not existed:
            # First time seen: write initial CLOSED row so exporter sees us even
            # before any failure accrues.
            self._persist()

        with CircuitBreaker._registry_lock:
            CircuitBreaker._registry[name] = self

    # ── SQLite persistence ──────────────────────────────────────────────

    def _init_schema(self) -> None:
        try:
            conn = sqlite3.connect(self.sqlite_path, timeout=5)
            conn.execute(
                """CREATE TABLE IF NOT EXISTS circuit_breakers (
                    name TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    opened_at REAL,
                    half_open_successes INTEGER NOT NULL DEFAULT 0,
                    last_transition_at REAL,
                    last_updated REAL NOT NULL
                )"""
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"[circuit_breaker:{self.name}] schema init failed: {e}", file=sys.stderr)

    def _load_state(self) -> bool:
        """Return True if an existing row was loaded, False if new breaker."""
        try:
            conn = sqlite3.connect(self.sqlite_path, timeout=5)
            row = conn.execute(
                "SELECT state, failure_count, opened_at, half_open_successes "
                "FROM circuit_breakers WHERE name = ?",
                (self.name,),
            ).fetchone()
            conn.close()
            if row:
                self._state = State(row[0])
                self._failure_count = int(row[1] or 0)
                self._opened_at = row[2]
                self._half_open_successes = int(row[3] or 0)
                return True
            return False
        except (sqlite3.Error, ValueError) as e:
            print(f"[circuit_breaker:{self.name}] load failed: {e}", file=sys.stderr)
            return False

    def _persist(self, transitioned: bool = False) -> None:
        try:
            now = time.time()
            conn = sqlite3.connect(self.sqlite_path, timeout=5)
            conn.execute(
                """INSERT INTO circuit_breakers
                    (name, state, failure_count, opened_at, half_open_successes,
                     last_transition_at, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                    state = excluded.state,
                    failure_count = excluded.failure_count,
                    opened_at = excluded.opened_at,
                    half_open_successes = excluded.half_open_successes,
                    last_transition_at = CASE WHEN ? THEN excluded.last_transition_at
                                              ELSE last_transition_at END,
                    last_updated = excluded.last_updated""",
                (
                    self.name,
                    self._state.value,
                    self._failure_count,
                    self._opened_at,
                    self._half_open_successes,
                    now,
                    now,
                    int(transitioned),
                ),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            print(f"[circuit_breaker:{self.name}] persist failed: {e}", file=sys.stderr)

    # ── State machine ───────────────────────────────────────────────────

    @property
    def state(self) -> State:
        return self._state

    def allow(self) -> bool:
        """True if caller should proceed; False if breaker is open."""
        with self._lock:
            if self._state == State.CLOSED:
                return True
            if self._state == State.OPEN:
                if self._opened_at is None or (
                    time.time() - self._opened_at > self.cooldown_seconds
                ):
                    self._transition(State.HALF_OPEN)
                    return True
                return False
            # HALF_OPEN: a probe is already allowed
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state == State.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_successes_needed:
                    self._transition(State.CLOSED)
                else:
                    self._persist()
            elif self._state == State.CLOSED and self._failure_count > 0:
                self._failure_count = 0
                self._persist()

    def record_failure(self, exc: Optional[BaseException] = None) -> None:
        with self._lock:
            if self._state == State.HALF_OPEN:
                self._transition(State.OPEN)
                return
            if self._state == State.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._transition(State.OPEN)
                else:
                    self._persist()

    def _transition(self, new_state: State) -> None:
        """Must be called under self._lock."""
        old = self._state
        self._state = new_state
        if new_state == State.CLOSED:
            self._failure_count = 0
            self._opened_at = None
            self._half_open_successes = 0
        elif new_state == State.OPEN:
            self._opened_at = time.time()
            self._half_open_successes = 0
        elif new_state == State.HALF_OPEN:
            self._half_open_successes = 0
        self._persist(transitioned=True)
        print(
            f"[circuit_breaker] {self.name}: {old.value} -> {new_state.value} "
            f"(failures={self._failure_count})",
            file=sys.stderr,
        )

    # ── Decorator API ───────────────────────────────────────────────────

    def wrap(self, fallback: Any = None) -> Callable:
        """Return a decorator that protects the wrapped function.

        `fallback` may be:
          - callable: invoked with same args as the wrapped fn when circuit is open
          - any other value: returned as-is when circuit is open
          - None: raise CircuitOpenError when circuit is open
        """

        def decorator(fn):
            def wrapped(*args, **kwargs):
                if not self.allow():
                    return _invoke_fallback(fallback, args, kwargs, self.name)
                try:
                    result = fn(*args, **kwargs)
                    self.record_success()
                    return result
                except Exception as e:
                    self.record_failure(e)
                    # If that failure tripped the breaker and there's a fallback,
                    # return it rather than raising.
                    if self._state == State.OPEN and fallback is not None:
                        return _invoke_fallback(fallback, args, kwargs, self.name)
                    raise

            wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
            wrapped.__name__ = getattr(fn, "__name__", "wrapped")
            return wrapped

        return decorator

    # ── Introspection ───────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "opened_at": self._opened_at,
                "cooldown_seconds": self.cooldown_seconds,
                "failure_threshold": self.failure_threshold,
            }


def _invoke_fallback(fallback, args, kwargs, name):
    if fallback is None:
        raise CircuitOpenError(f"{name} circuit is open")
    if callable(fallback):
        return fallback(*args, **kwargs)
    return fallback


# ── Prometheus exporter ─────────────────────────────────────────────────


def export_metrics(sqlite_path: str, output_path: str) -> None:
    """Read all breaker rows and emit Prometheus text format."""
    try:
        conn = sqlite3.connect(sqlite_path, timeout=5)
        rows = conn.execute(
            "SELECT name, state, failure_count, opened_at, last_transition_at "
            "FROM circuit_breakers"
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        print(f"[circuit_breaker] export failed: {e}", file=sys.stderr)
        return

    state_num = {"closed": 0, "half_open": 1, "open": 2}
    lines = [
        "# HELP circuit_breaker_state 0=closed (healthy), 1=half_open (probing), 2=open (tripped)",
        "# TYPE circuit_breaker_state gauge",
    ]
    for name, state, *_ in rows:
        lines.append(
            f'circuit_breaker_state{{name="{name}"}} {state_num.get(state, -1)}'
        )
    lines += [
        "# HELP circuit_breaker_failure_count Consecutive-failure counter",
        "# TYPE circuit_breaker_failure_count gauge",
    ]
    for name, _, failure_count, *_ in rows:
        lines.append(
            f'circuit_breaker_failure_count{{name="{name}"}} {int(failure_count or 0)}'
        )
    lines += [
        "# HELP circuit_breaker_opened_timestamp_seconds Unix time when circuit last opened (0 if closed)",
        "# TYPE circuit_breaker_opened_timestamp_seconds gauge",
    ]
    for name, _, _, opened_at, _ in rows:
        lines.append(
            f'circuit_breaker_opened_timestamp_seconds{{name="{name}"}} {opened_at or 0}'
        )

    tmp = output_path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, output_path)


# ── CLI ─────────────────────────────────────────────────────────────────


def _cli():
    p = argparse.ArgumentParser(description="Circuit breaker inspection + export")
    p.add_argument("--db", default=DEFAULT_DB, help="SQLite path")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all breakers and their state")
    reset = sub.add_parser("reset", help="force a breaker back to CLOSED")
    reset.add_argument("name")
    exp = sub.add_parser("export", help="write Prometheus metrics to file")
    exp.add_argument("output")
    args = p.parse_args()

    if args.cmd == "list":
        try:
            conn = sqlite3.connect(args.db, timeout=5)
            rows = conn.execute(
                "SELECT name, state, failure_count, opened_at, last_transition_at "
                "FROM circuit_breakers ORDER BY name"
            ).fetchall()
            conn.close()
        except sqlite3.Error as e:
            print(f"error: {e}", file=sys.stderr)
            sys.exit(1)
        if not rows:
            print("(no breakers registered)")
            return
        print(f"{'NAME':<28} {'STATE':<10} {'FAIL':<5} OPENED/SINCE")
        for name, state, fc, opened, lt in rows:
            since = ""
            if state == "open" and opened:
                since = f"{int(time.time() - opened)}s ago"
            elif lt:
                since = f"(last transition {int(time.time() - lt)}s ago)"
            print(f"{name:<28} {state:<10} {fc or 0:<5} {since}")
    elif args.cmd == "reset":
        cb = CircuitBreaker(args.name, sqlite_path=args.db)
        with cb._lock:
            cb._transition(State.CLOSED)
        print(f"{args.name}: reset to CLOSED")
    elif args.cmd == "export":
        export_metrics(args.db, args.output)
        print(f"wrote {args.output}")


if __name__ == "__main__":
    _cli()
