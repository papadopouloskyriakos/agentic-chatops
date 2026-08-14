#!/usr/bin/env python3
"""planner-decompose.py — decompose a feature into work_units for parallel-dev (IFRNLLEI01PRD-924).

The thin Python layer that the n8n "NL - ChatDevOps Planner" workflow calls via SSH.

Flow:
  1. Read feature description (from YT issue id, or from STDIN)
  2. Run Claude in plan mode with a decomposition prompt
  3. Parse Claude's JSON output (looking for a fenced ```json block with `tasks` array)
  4. Validate the work_units (DAG, file-overlap, required fields, count limits)
  5. Insert into /home/app-user/gateway-state/gateway.db work_units table
  6. Emit summary JSON to stdout

Usage:
  planner-decompose.py --feature-id CUBEOS-9999 --repo-slug cubeos
  planner-decompose.py --feature-id CUBEOS-9999 --dry-run    # synthetic tasks, no Claude
  planner-decompose.py --validate-only /tmp/tasks.json       # just run validators
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

DB = "/home/app-user/gateway-state/gateway.db"
SLOT_CONFIG = "/home/app-user/gateway-state/slot-config.json"
MAX_WORKERS = 4
MAX_LOC_PER_WORKER = 500
MAX_WALL_MIN = 30
REQUIRED_TASK_FIELDS = {
    "task_id", "title", "files_owned", "prompt",
    "acceptance_test", "dependencies", "parallelizable", "bounded_context",
}


def validate_work_units(feature_id: str, tasks: list[dict]) -> list[str]:
    """Return list of validation errors (empty = OK)."""
    errors: list[str] = []

    if not tasks:
        errors.append("no tasks in decomposition output")
        return errors
    if len(tasks) > MAX_WORKERS:
        errors.append(f"too many tasks: {len(tasks)} > MAX_WORKERS={MAX_WORKERS}")

    # Required field check
    seen_ids: set[str] = set()
    for i, t in enumerate(tasks):
        missing = REQUIRED_TASK_FIELDS - set(t.keys())
        if missing:
            errors.append(f"task[{i}] ({t.get('task_id', '?')}): missing required fields: {sorted(missing)}")
        tid = t.get("task_id", f"_anon_{i}")
        if tid in seen_ids:
            errors.append(f"task_id '{tid}' duplicated")
        seen_ids.add(tid)
        # files_owned must be non-empty list
        fo = t.get("files_owned")
        if not isinstance(fo, list) or not fo:
            errors.append(f"task {tid}: files_owned must be non-empty array")
        # parallelizable must be bool/0/1
        if "parallelizable" in t and not isinstance(t["parallelizable"], (bool, int)):
            errors.append(f"task {tid}: parallelizable must be bool")

    if errors:
        return errors

    # DAG check (Kahn's algorithm)
    deps = {t["task_id"]: set(t.get("dependencies") or []) for t in tasks}
    for tid, ds in deps.items():
        unknown = ds - seen_ids
        if unknown:
            errors.append(f"task {tid}: depends on unknown task_ids: {sorted(unknown)}")
    if errors:
        return errors

    indeg = {tid: len(ds) for tid, ds in deps.items()}
    queue = [tid for tid, n in indeg.items() if n == 0]
    visited: list[str] = []
    while queue:
        tid = queue.pop(0)
        visited.append(tid)
        # Find tasks that depend on tid
        for other_tid, other_ds in deps.items():
            if tid in other_ds:
                indeg[other_tid] -= 1
                if indeg[other_tid] == 0:
                    queue.append(other_tid)
    if len(visited) != len(tasks):
        errors.append(f"DAG cycle detected: only {len(visited)}/{len(tasks)} tasks reachable from roots")
        return errors

    # File-overlap check among parallelizable tasks within same dependency wave
    waves: dict[int, list[dict]] = {}
    depth = {tid: 0 for tid in deps}
    for tid in visited:  # topological order
        for d in deps[tid]:
            depth[tid] = max(depth[tid], depth[d] + 1)
    for t in tasks:
        d = depth[t["task_id"]]
        waves.setdefault(d, []).append(t)

    for wave_depth, wave_tasks in waves.items():
        parallel = [t for t in wave_tasks if t.get("parallelizable", True)]
        for i, t1 in enumerate(parallel):
            for t2 in parallel[i + 1:]:
                overlap = set(t1["files_owned"]) & set(t2["files_owned"])
                if overlap:
                    errors.append(
                        f"wave {wave_depth}: parallelizable tasks {t1['task_id']} + {t2['task_id']} "
                        f"share files_owned: {sorted(overlap)}"
                    )

    return errors


def synthetic_tasks(feature_id: str) -> list[dict]:
    """Synthetic 2-task decomposition for dry-run testing."""
    return [
        {
            "task_id": "T-001",
            "title": "Add Module A skeleton + tests",
            "files_owned": ["src/module_a.go", "src/module_a_test.go"],
            "prompt": "Implement module A per spec; write unit tests; verify go test passes.",
            "acceptance_test": "go test ./src/... -run TestModuleA",
            "dependencies": [],
            "parallelizable": True,
            "bounded_context": "transports",
            "risk_score": 0.3,
            "complexity": 4,
        },
        {
            "task_id": "T-002",
            "title": "Add Module B skeleton + tests",
            "files_owned": ["src/module_b.go", "src/module_b_test.go"],
            "prompt": "Implement module B per spec; write unit tests; verify go test passes.",
            "acceptance_test": "go test ./src/... -run TestModuleB",
            "dependencies": [],
            "parallelizable": True,
            "bounded_context": "drivers",
            "risk_score": 0.3,
            "complexity": 4,
        },
    ]


def insert_work_units(feature_id: str, repo_slug: str, tasks: list[dict], planner_session_id: str = "") -> int:
    """Insert into work_units + features tables. Returns number of rows inserted."""
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")

    # Feature-level row (upsert)
    feature_risk = max([float(t.get("risk_score", 0.5)) for t in tasks] + [0.0])
    conn.execute(
        """INSERT INTO features (feature_id, repo_slug, source_issue_id, planner_session_id,
                                 total_work_units, feature_risk_score, status)
           VALUES (?, ?, ?, ?, ?, ?, 'dispatching')
           ON CONFLICT(feature_id) DO UPDATE SET
             total_work_units=excluded.total_work_units,
             feature_risk_score=excluded.feature_risk_score,
             status='dispatching',
             planner_session_id=excluded.planner_session_id""",
        (feature_id, repo_slug, feature_id, planner_session_id, len(tasks), feature_risk),
    )

    n = 0
    for t in tasks:
        conn.execute(
            """INSERT OR REPLACE INTO work_units
               (feature_id, task_id, title, files_owned, prompt, acceptance_test,
                dependencies, parallelizable, bounded_context, risk_score, complexity,
                max_wall_clock_minutes, max_loc_delta, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                feature_id,
                t["task_id"],
                t.get("title", ""),
                json.dumps(t["files_owned"]),
                t["prompt"],
                t.get("acceptance_test", ""),
                json.dumps(t.get("dependencies", [])),
                int(bool(t.get("parallelizable", True))),
                t.get("bounded_context", ""),
                float(t.get("risk_score", 0.5)),
                int(t.get("complexity", 5)),
                int(t.get("max_wall_clock_minutes", MAX_WALL_MIN)),
                int(t.get("max_loc_delta", MAX_LOC_PER_WORKER)),
            ),
        )
        n += 1

    conn.commit()
    conn.close()
    return n


DECOMPOSE_TIMEOUT_S = int(os.environ.get("PLANNER_DECOMPOSE_TIMEOUT_S", "300"))


def _decomposition_prompt(feature_id: str, feature_text: str) -> str:
    """Build the architect prompt: a feature -> a parallel-safe work-unit DAG."""
    return (
        f"You are the ARCHITECT in an architecture-execution-separated agent system. "
        f"Decompose feature {feature_id} into at most {MAX_WORKERS} work units that "
        f"sandboxed coder agents will implement in parallel git worktrees.\n\n"
        f"FEATURE:\n{feature_text}\n\n"
        f"Output ONLY a fenced ```json block containing an object with a 'tasks' array. "
        f"Each task object MUST have: task_id (e.g. T-001), title, files_owned "
        f"(non-empty array; tasks that run in parallel — same dependency wave — MUST NOT "
        f"share any file), prompt (the instruction for the coder agent), acceptance_test "
        f"(a command that proves the task done), dependencies (array of task_ids; the set "
        f"must form a DAG with no cycles), parallelizable (boolean), bounded_context, "
        f"risk_score (0.0-1.0), complexity (1-10). Keep each unit under "
        f"{MAX_LOC_PER_WORKER} LOC and {MAX_WALL_MIN} wall-minutes. Architect only — do "
        f"NOT write the implementation, only the decomposition."
    )


def _run_claude(prompt: str, repo_cwd: str) -> tuple[str | None, str]:
    """Run `claude -p --output-format json` (Max-subscription OAuth, no API key — mirrors
    lib/gepa_generator). Returns (reply_text|None, session_id). Fail-safe: any error -> None."""
    model = os.environ.get("PLANNER_DECOMPOSE_MODEL", "")
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_cwd,
                              timeout=DECOMPOSE_TIMEOUT_S, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, ""
    if proc.returncode != 0:
        return None, ""
    try:
        wrapper = json.loads(proc.stdout)
        return wrapper.get("result", ""), wrapper.get("session_id", "")
    except (json.JSONDecodeError, AttributeError):
        return proc.stdout or None, ""


def _extract_tasks(reply: str) -> list[dict]:
    """Pull the tasks array from a fenced ```json block (or a bare JSON object)."""
    REDACTED_a7b84d63 as _re
    block = None
    m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", reply, _re.DOTALL)
    if m:
        block = m.group(1)
    else:
        s, e = reply.find("{"), reply.rfind("}")
        if s != -1 and e > s:
            block = reply[s:e + 1]
    if not block:
        return []
    try:
        data = json.loads(block)
    except json.JSONDecodeError:
        return []
    tasks = data.get("tasks", []) if isinstance(data, dict) else data
    return tasks if isinstance(tasks, list) else []


def run_decomposition(feature_id: str, repo_cwd: str, feature_text: str) -> tuple[list[dict], str]:
    """Architect step: invoke Claude to decompose a feature into a validated work-unit DAG.

    Returns (tasks, session_id). Raises RuntimeError (never silently degrades) if Claude is
    unavailable / times out / returns unparseable or invalid output — the caller then aborts
    rather than dispatching a half-built decomposition. `--dry-run` bypasses this entirely.
    """
    reply, session_id = _run_claude(_decomposition_prompt(feature_id, feature_text), repo_cwd)
    if reply is None:
        raise RuntimeError(
            "decomposition failed: `claude -p` unavailable, errored, or timed out "
            f"(>{DECOMPOSE_TIMEOUT_S}s). Use --dry-run for synthetic tasks, or retry.")
    tasks = _extract_tasks(reply)
    if not tasks:
        raise RuntimeError("decomposition failed: no parseable `tasks` array in Claude output")
    errs = validate_work_units(feature_id, tasks)
    if errs:
        raise RuntimeError("decomposition failed validation: " + "; ".join(errs[:8]))
    return tasks, session_id or "claude-decompose"


def main() -> int:
    parser = argparse.ArgumentParser(description="Decompose a feature into work_units (Planner step).")
    parser.add_argument("--feature-id", required=True, help="YouTrack issue id (e.g. CUBEOS-1234)")
    parser.add_argument("--repo-slug", help="Repo slug (cubeos, meshsat); defaults to slot derived from feature-id")
    parser.add_argument("--dry-run", action="store_true", help="Use synthetic tasks, no Claude call")
    parser.add_argument("--validate-only", type=Path, help="Just validate a tasks.json file, don't insert")
    parser.add_argument("--json", action="store_true", help="JSON output to stdout")
    args = parser.parse_args()

    # Validate-only mode
    if args.validate_only:
        tasks = json.loads(args.validate_only.read_text())
        if isinstance(tasks, dict):
            tasks = tasks.get("tasks", [])
        errs = validate_work_units(args.feature_id, tasks)
        report = {"feature_id": args.feature_id, "task_count": len(tasks), "errors": errs, "pass": not errs}
        print(json.dumps(report, indent=2) if args.json else report)
        return 0 if not errs else 1

    # Derive slot/cwd from feature_id if repo-slug not given
    if not args.repo_slug:
        cfg = json.loads(Path(SLOT_CONFIG).read_text())
        prefix = args.feature_id.split("-")[0]
        slot = {"CUBEOS": "cubeos", "MESHSAT": "meshsat"}.get(prefix, "cubeos")
        args.repo_slug = slot

    cfg = json.loads(Path(SLOT_CONFIG).read_text())
    repo_cwd = cfg.get(args.repo_slug, cfg["default"])["cwd"]

    # Get tasks
    if args.dry_run:
        tasks = synthetic_tasks(args.feature_id)
        session_id = "dry-run"
    else:
        tasks, session_id = run_decomposition(args.feature_id, repo_cwd, "<feature text from YT>")

    # Validate
    errs = validate_work_units(args.feature_id, tasks)
    if errs:
        print(json.dumps({"error": "validation failed", "errors": errs}, indent=2), file=sys.stderr)
        return 1

    # Insert
    n = insert_work_units(args.feature_id, args.repo_slug, tasks, session_id)

    report = {
        "feature_id": args.feature_id,
        "repo_slug": args.repo_slug,
        "repo_cwd": repo_cwd,
        "tasks_inserted": n,
        "planner_session_id": session_id,
        "dry_run": args.dry_run,
    }
    print(json.dumps(report, indent=2) if args.json else report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
