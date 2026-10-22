#!/usr/bin/env python3
"""validate-harness-tree.py — Harness² harness-tree validation for this repo's Claude Code surface.

Vendored validator: scripts/lib/harness_tree.py (google-research/harness2 @ 1cfe254, Apache-2.0).

Usage:
  validate-harness-tree.py [--repo PATH] [--extra-always-on FILE ...]
                           [--runner-build-prompt WORKFLOW.json] [--json]
                           [--warn-bytes 32000] [--max-bytes 48000]

What it checks (see harness_tree.CLAUDE_CODE_SURFACE):
  * always-on text (CLAUDE.md + .claude/rules/*.md): WARN above --warn-bytes, FAIL above
    --max-bytes ($ALWAYS_ON_MAX, default 48000) — every byte is loaded into every session
  * .claude/skills/<n>/SKILL.md: frontmatter name (== dir) / description / semver version,
    and every skill is TRIGGERED — named as `/<n>` or `<n>` in the always-on text or in the
    extra trigger text (--extra-always-on files, --runner-build-prompt Build Prompt jsCode)
  * .claude/agents/<n>.md: frontmatter name (== stem) / description / semver version
  * scripts/<n>.py compile; scripts/<n>.py|.sh invoked by a SKILL.md or always-on file exist
  * .claude/settings.json and config/dispatched-session-settings.json `hooks` shape

Exit codes: 0 = OK (a WARN alone is still 0), 1 = problems, 2 = usage / read error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))

import harness_tree as ht  # noqa: E402

DISPATCHED_SETTINGS = "config/dispatched-session-settings.json"
BUILD_PROMPT_NODE = "Build Prompt"


def _resolve(path_arg: str, repo: Path) -> Path:
    """A path argument as given (cwd-relative), else relative to the repo."""
    p = Path(path_arg).expanduser()
    if p.is_file():
        return p.resolve()
    alt = repo / path_arg
    if alt.is_file():
        return alt.resolve()
    raise FileNotFoundError(path_arg)


def _build_prompt_code(workflow_json: Path) -> str:
    """The `jsCode` of the Runner's Build Prompt Code node."""
    data = json.loads(workflow_json.read_text(encoding="utf-8"))
    nodes = data.get("nodes") or []
    node = next((n for n in nodes if n.get("name") == BUILD_PROMPT_NODE), None)
    if node is None:
        node = next((n for n in nodes if BUILD_PROMPT_NODE in str(n.get("name", ""))), None)
    if node is None:
        raise KeyError(f"no node named {BUILD_PROMPT_NODE!r} in {workflow_json}")
    code = (node.get("parameters") or {}).get("jsCode") or ""
    if not str(code).strip():
        raise KeyError(f"{BUILD_PROMPT_NODE!r} node in {workflow_json} has no jsCode")
    return str(code)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="validate-harness-tree.py",
        description="Validate the Claude Code harness tree (CLAUDE.md, rules, skills, agents, "
        "scripts, hooks) with the vendored Harness² tree validator.",
    )
    ap.add_argument("--repo", default=str(HERE.parent), help="repo root (default: this repo)")
    ap.add_argument(
        "--extra-always-on",
        nargs="+",
        action="extend",
        default=[],
        metavar="FILE",
        help="file(s) whose text counts for skill triggers (not for the always-on cap)",
    )
    ap.add_argument(
        "--runner-build-prompt",
        metavar="WORKFLOW_JSON",
        help="n8n workflow export; its 'Build Prompt' node jsCode counts as trigger text",
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--warn-bytes", type=int, default=32_000, help="WARN above this (default 32000)")
    ap.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        help="FAIL above this (default: $ALWAYS_ON_MAX or 48000)",
    )
    args = ap.parse_args(argv)

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / "CLAUDE.md").is_file():
        print(f"error: no CLAUDE.md under {repo} — not a Claude Code harness root", file=sys.stderr)
        return 2

    surface = ht.claude_code_surface(repo, always_on_max=args.max_bytes)
    tree = ht.read_tree(surface, repo)

    extra_parts: list[str] = []
    extra_sources: list[str] = []
    try:
        for f in args.extra_always_on:
            p = _resolve(f, repo)
            extra_parts.append(p.read_text(encoding="utf-8", errors="replace"))
            extra_sources.append(str(p))
        if args.runner_build_prompt:
            p = _resolve(args.runner_build_prompt, repo)
            extra_parts.append(_build_prompt_code(p))
            extra_sources.append(f"{p}#{BUILD_PROMPT_NODE}")
    except (FileNotFoundError, KeyError, json.JSONDecodeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    extra = "\n\n".join(extra_parts)

    problems: list[str] = []
    try:
        ht.validate(surface, tree, extra_trigger_text=extra)
    except ValueError as exc:
        problems.extend(str(exc).split(" | "))
    cen = ht.census(surface, tree)

    hooks_checked = [surface.hooks_file] if surface.hooks_file in tree else []
    ds = repo / DISPATCHED_SETTINGS
    if ds.is_file():
        errs: list[str] = []
        ht.check_hooks(
            surface, ds.read_text(encoding="utf-8", errors="replace"), errs, hooks_file=DISPATCHED_SETTINGS
        )
        problems.extend(errs)
        hooks_checked.append(DISPATCHED_SETTINGS)

    body = ht.always_on_text(surface, tree)
    nbytes = len(body.encode("utf-8"))
    warn = nbytes > args.warn_bytes
    ok = not problems

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "repo": str(repo),
                    "surface": surface.name,
                    "always_on_files": list(surface.always_on),
                    "always_on_bytes": nbytes,
                    "always_on_chars": len(body),
                    "warn_bytes": args.warn_bytes,
                    "max_bytes": surface.always_on_max,
                    "warn": warn,
                    "problems": problems,
                    "census": cen,
                    "extra_trigger_sources": extra_sources,
                    "hooks_files_checked": hooks_checked,
                },
                indent=2,
            )
        )
    else:
        if ok:
            print("HARNESS TREE: OK")
        else:
            print(f"HARNESS TREE: PROBLEMS ({len(problems)})")
            for p in problems:
                print(f"  - {p}")
        print(
            f"always-on text: {nbytes} bytes ({len(body)} chars) across "
            f"{len(surface.always_on)} files; warn {args.warn_bytes}, cap {surface.always_on_max}"
        )
        if warn:
            print(f"WARN: always-on text {nbytes} bytes exceeds warn threshold ({args.warn_bytes})")
        print(
            "census: "
            + " ".join(f"{k}={v}" for k, v in cen.items() if k not in ("always_on_chars", "always_on_bytes"))
        )
        if extra_sources:
            print("extra trigger text from: " + ", ".join(extra_sources))
        if hooks_checked:
            print("hooks files checked: " + ", ".join(hooks_checked))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)
