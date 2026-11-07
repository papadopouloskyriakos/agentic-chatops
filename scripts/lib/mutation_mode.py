#!/usr/bin/env python3
"""
mutation_mode.py — global MUTATIONS=OFF (shadow) mode helper (IFRNLLEI01PRD-1824).

Shadow mode = the agentic system runs at 100% (triage, reasoning, session dispatch) but NEVER
actuates: every mutating action is intercepted and LOGGED (action + rationale) instead of executed.
Enforced two ways: the PreToolUse hook `mutation-shadow-gate.py` hard-blocks dispatched-session
mutations, and the cron actuators call is_shadow()/log_wouldve() at their actuation points.

is_shadow():   True when env GATEWAY_MUTATIONS_OFF is truthy, else when ~/gateway.mutations_off
               exists. Env wins so QA/CI can force either state. Mirrors classify-session-risk.py::
               _envflag semantics exactly.
log_wouldve(): append one JSONL line to the dedicated shadow-log folder AND (best-effort) emit an
               obs_log notice so shadow decisions surface in OpenObserve/Langfuse. Never raises.

Import-safe: pure stdlib, no DB, no network. Safe to import at module top of any actuator.
"""
import json
import os
import socket
import sys
import time
from pathlib import Path

SENTINEL = Path(os.environ.get("GATEWAY_HOME", str(Path.home()))) / "gateway.mutations_off"
_LOG_DIR = Path(os.environ.get(
    "MUTATION_SHADOW_LOG_DIR",
    str(Path(os.environ.get("GATEWAY_HOME", str(Path.home()))) / "logs" / "claude-gateway" / "mutation-shadow")))


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def is_shadow() -> bool:
    """True if MUTATIONS=OFF (shadow) is active. Env override wins, else the sentinel file.

    Env var name is MUTATIONS_OFF to match the house _envflag convention in classify-session-risk.py
    (env name == sentinel suffix uppercased), so a single `MUTATIONS_OFF=1` forces shadow across the
    hook, the lib, the actuators, AND the classifier consistently. The sentinel ~/gateway.mutations_off
    is the production source of truth."""
    env = os.environ.get("MUTATIONS_OFF")
    if env is not None:
        return _truthy(env)
    return SENTINEL.exists()


def _log_path() -> Path:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    # one file per UTC day so the dedicated folder stays navigable
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return _LOG_DIR / f"shadow-{day}.jsonl"


def log_wouldve(action: str, rationale: str = "", **kv) -> None:
    """Record a would-have-actuated decision. action=short verb (e.g. 'yt-close', 'pct-resize');
    rationale=why (the caller's stated intent); kv=structured context (host, issue, cmd, ...).
    Writes JSONL to the dedicated shadow folder + a best-effort obs_log notice. Never raises."""
    entry = {
        "ts": int(time.time()),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": socket.gethostname(),
        "source": os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else "?",
        "action": action,
        "rationale": rationale,
        "blocked": True,
        "mode": "shadow",
        **kv,
    }
    try:
        with open(_log_path(), "a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass  # logging must never break the caller
    # Best-effort observability so shadow decisions are visible in OpenObserve/Langfuse.
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        import obs_log  # noqa: E402
        obs_log.event("orchestrator", source=entry["source"], action="would_" + action,
                      level="notice", rationale=rationale[:500], **{k: str(v)[:200] for k, v in kv.items()})
    except Exception:  # noqa: BLE001 - obs_log absent/misconfigured must not break shadow logging
        pass


def status() -> dict:
    return {"shadow": is_shadow(), "sentinel": str(SENTINEL), "present": SENTINEL.exists(),
            "env": os.environ.get("GATEWAY_MUTATIONS_OFF"), "log_dir": str(_LOG_DIR)}


if __name__ == "__main__":
    print(json.dumps(status(), indent=2))
