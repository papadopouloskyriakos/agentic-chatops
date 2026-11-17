#!/usr/bin/env python3
"""Harness fingerprint — which editable harness did this session run under? (R3)

Mirror of google-research/harness2 `core/runmark.py::fingerprint` (a sha1 over the
sorted relative paths + bytes of the harness tree), extended to the surface a
dispatched claude-gateway session actually loads:

  workspace repo (cwd)   CLAUDE.md, .claude/rules/*.md, .claude/skills/**, .claude/agents/**
  gateway repo           config/prompt-patches.json (ACTIVE entries only, normalised),
                         config/dispatched-session-settings.json,
                         workflows/claude-gateway-runner.json  -> Build Prompt jsCode only
  user scope (~/.claude) CLAUDE.md, agents/*.md, skills/*/SKILL.md (symlinks resolved)

Each component contributes one sha1; the fingerprint is the sha1 over the sorted
(component, digest) pairs, cut to 16 hex chars — so two sessions share a fingerprint
iff every byte of harness they could have loaded was identical.

Usage:
  harness_fingerprint.py                      # print the fp for the cwd repo
  harness_fingerprint.py --repo PATH --json   # fp + per-component digests
  harness_fingerprint.py --stamp --session SID --issue ID [--repo PATH]
                                              # record into harness_fingerprints +
                                              # session_harness (idempotent, fail-open)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

GATEWAY_REPO = Path(os.environ.get("GATEWAY_REPO", "/app/claude-gateway"))
DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
HOME = Path(os.environ.get("HOME", "/home/app-user"))
SCHEMA_VERSION = 1  # harness_fingerprints / session_harness — registry: scripts/lib/schema_version.py

_IGNORE_PARTS = {"__pycache__", ".trash"}


def _sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sha1_tree(root: Path) -> str | None:
    """sha1 over sorted rel paths + bytes under `root`; None when root is absent."""
    root = Path(root)
    if not root.exists():
        return None
    if root.is_file():
        try:
            return _sha1_bytes(root.read_bytes())
        except OSError:
            return "unreadable"
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        if any(part in _IGNORE_PARTS for part in p.parts) or p.suffix == ".pyc":
            continue
        if not p.is_file():
            continue
        h.update(str(p.relative_to(root)).encode())
        h.update(b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"<unreadable>")
        h.update(b"\0")
    return h.hexdigest()


def _active_patches_digest(path: Path) -> str | None:
    """Only ACTIVE prompt patches reach a session; ignore inactive/expired entries."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unparseable"
    entries = data if isinstance(data, list) else (data.get("patches") if isinstance(data, dict) else [])
    active = [e for e in (entries or []) if isinstance(e, dict) and e.get("active")]
    canon = json.dumps(
        sorted(
            ({"dimension": e.get("dimension"), "category": e.get("category"),
              "instruction": e.get("instruction")} for e in active),
            key=lambda d: json.dumps(d, sort_keys=True),
        ),
        sort_keys=True,
    )
    return _sha1_bytes(canon.encode())


def _build_prompt_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        wf = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unparseable"
    node = next((n for n in wf.get("nodes", []) if n.get("name") == "Build Prompt"), None)
    if not node:
        return "no-build-prompt-node"
    code = (node.get("parameters") or {}).get("jsCode") or ""
    return _sha1_bytes(code.encode())


def collect_components(repo: Path, gateway: Path = GATEWAY_REPO, home: Path = HOME) -> dict[str, str]:
    """component name -> sha1 (absent components are omitted, so the fp still changes
    when a component appears or disappears)."""
    repo = Path(repo)
    comps: dict[str, str | None] = {
        "repo:CLAUDE.md": _sha1_tree(repo / "CLAUDE.md"),
        "repo:.claude/rules": _sha1_tree(repo / ".claude" / "rules"),
        "repo:.claude/skills": _sha1_tree(repo / ".claude" / "skills"),
        "repo:.claude/agents": _sha1_tree(repo / ".claude" / "agents"),
        "gateway:prompt-patches(active)": _active_patches_digest(gateway / "config" / "prompt-patches.json"),
        "gateway:dispatched-session-settings": _sha1_tree(gateway / "config" / "dispatched-session-settings.json"),
        "gateway:build-prompt-jscode": _build_prompt_digest(gateway / "workflows" / "claude-gateway-runner.json"),
        "user:CLAUDE.md": _sha1_tree(home / ".claude" / "CLAUDE.md"),
        "user:agents": _sha1_tree(home / ".claude" / "agents"),
        "user:skills": _sha1_tree(home / ".claude" / "skills"),
    }
    return {k: v for k, v in comps.items() if v is not None}


def fingerprint(components: dict[str, str]) -> str:
    h = hashlib.sha1()
    for name, digest in sorted(components.items()):
        h.update(name.encode())
        h.update(b"\0")
        h.update(digest.encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def _git_rev(repo: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def compute(repo: Path | str | None = None) -> dict:
    repo = Path(repo) if repo else Path.cwd()
    comps = collect_components(repo)
    return {
        "fp": fingerprint(comps),
        "repo": str(repo),
        "gateway_rev": _git_rev(GATEWAY_REPO),
        "components": comps,
    }


def record(conn: sqlite3.Connection, info: dict) -> None:
    """Idempotent dictionary write: a fingerprint is immutable once recorded."""
    conn.execute(
        "INSERT OR IGNORE INTO harness_fingerprints (fp, repo, git_rev, components_json, schema_version) "
        "VALUES (?,?,?,?,?)",
        (info["fp"], info["repo"], info.get("gateway_rev", ""),
         json.dumps(info["components"], sort_keys=True), SCHEMA_VERSION),
    )


def stamp_session(conn: sqlite3.Connection, session_id: str, issue_id: str, info: dict) -> None:
    """One row per session_id; a re-stamp (e.g. the SessionEnd hook after
    UserPromptSubmit) keeps the FIRST fingerprint — the harness the session started under."""
    conn.execute(
        "INSERT OR IGNORE INTO session_harness (session_id, issue_id, harness_fp, repo, schema_version) "
        "VALUES (?,?,?,?,?)",
        (session_id, issue_id or "", info["fp"], info["repo"], SCHEMA_VERSION),
    )


def stamp(session_id: str, issue_id: str, repo: Path | str | None, db_path: str = DB_PATH) -> dict:
    info = compute(repo)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        record(conn, info)
        stamp_session(conn, session_id, issue_id, info)
        conn.commit()
    finally:
        conn.close()
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=None, help="workspace repo (default: cwd)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--stamp", action="store_true", help="record into the gateway DB")
    ap.add_argument("--session", default="")
    ap.add_argument("--issue", default="")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args(argv)

    if args.stamp:
        if not args.session:
            print("--stamp needs --session", file=sys.stderr)
            return 2
        try:
            info = stamp(args.session, args.issue, args.repo, args.db)
        except sqlite3.Error as exc:  # fail-open: a hook must never block a session
            print(f"harness_fingerprint: db error ignored: {exc}", file=sys.stderr)
            return 0
    else:
        info = compute(args.repo)

    if args.json:
        print(json.dumps(info, indent=2, sort_keys=True))
    else:
        print(info["fp"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
