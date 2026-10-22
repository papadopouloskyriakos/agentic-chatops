# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Vendored from google-research/harness2 @ 1cfe254 (Apache-2.0), adapted for the Claude Code
# surface by claude-gateway.

"""The c1..c8 component tree: read, validate, write, diff — parametrised by SurfaceSpec.

Everything that differs between agent frameworks is data on `SurfaceSpec` (paths, caps,
frontmatter rules, README seeds) plus a per-surface hooks-schema validator; the shared logic
exists once. The edit contract is omitted-is-inherited: a proposal emits only what it changes.

claude-gateway adaptation (upstream file: harness2/core/tree.py). The upstream surfaces are
Codex (`AGENTS.md`, `.agents/skills`, `sub_agents/<n>/AGENT.md`, `.codex/hooks.json`) and
Gemini CLI. This copy adds the Claude Code surface this repo actually runs on:

  always-on   CLAUDE.md + every `.claude/rules/*.md` (all loaded into EVERY session)
  skills      .claude/skills/<name>/SKILL.md   (frontmatter name/description/version)
  sub-agents  .claude/agents/<name>.md         (FLAT files; frontmatter name/description/version)
  scripts     scripts/<name>.py|.sh            (kebab/snake case; .py must compile)
  hooks       .claude/settings.json            ({"hooks": {...}} plus other settings keys)

The extra `SurfaceSpec` fields all default to the upstream behaviour, so `CODEX_SURFACE`-style
specs still validate byte-for-byte as before; `CLAUDE_CODE_SURFACE` / `claude_code_surface()`
turn the adaptations on. Use `scripts/validate-harness-tree.py` for the CLI.
"""

from __future__ import annotations

import dataclasses
import json
import os
REDACTED_a7b84d63
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

Tree = dict[str, str]


RESERVED_SCRIPTS = frozenset({"read_doc.py", "pack.py", "unpack.py"})


_NAME = r"[a-z0-9][a-z0-9_\-]*"

# Upstream defaults (Codex / Gemini layout), kept as the SurfaceSpec field defaults.
_UPSTREAM_SUBAGENT_PATTERN = rf"sub_agents/({_NAME})/AGENT\.md"
_UPSTREAM_SUBAGENT_PATH = "sub_agents/{name}/AGENT.md"
_UPSTREAM_SCRIPT_PATTERN = r"scripts/[a-z0-9_][a-z0-9_]*\.py"

# Claude Code layout. `{sd}` in a ref pattern is replaced by the escaped skill_dir at compile.
_CC_SUBAGENT_PATTERN = rf"\.claude/agents/({_NAME})\.md"
_CC_SUBAGENT_PATH = ".claude/agents/{name}.md"
_CC_SCRIPT_PATTERN = r"scripts/[A-Za-z0-9_.\-]+\.(?:py|sh)"
# A relative `scripts/<file>.py|.sh` token (optionally `./`-prefixed, optionally a skill-local
# `.claude/skills/<n>/scripts/...`), NOT preceded by a path character (so absolute paths and
# `other-repo/scripts/x.py` are out of scope) and NOT continued by one (so `scripts/x.py.bak`
# and `scripts/qa/...` nested paths are skipped). One capture group = the path.
_CC_SCRIPT_REF_PATTERN = (
    r"(?<![A-Za-z0-9_/.\-~])(?:\./)?"
    rf"((?:{{sd}}/{_NAME}/)?scripts/[A-Za-z0-9_.\-]+\.(?:py|sh))"
    r"(?![A-Za-z0-9_/\-])(?!\.\w)"
)

_SEMVER = re.compile(r"""^version:\s*["']?\d+\.\d+\.\d+(?:[\-+][A-Za-z0-9.\-]+)?["']?\s*$""", re.M)

CLAUDE_CODE_HOOK_EVENTS = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "PermissionRequest",
        "PreCompact",
        "PostCompact",
        "SessionStart",
        "SessionEnd",
        "SubagentStart",
        "SubagentStop",
        "UserPromptSubmit",
        "Stop",
        "Notification",
    }
)

DEFAULT_ALWAYS_ON_MAX = 48_000


def _env_always_on_max(default: int = DEFAULT_ALWAYS_ON_MAX) -> int:
    """`ALWAYS_ON_MAX` from the environment, else the 48 KB plan default."""
    raw = os.environ.get("ALWAYS_ON_MAX", "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class SurfaceSpec:
    """The editable surface of one agent framework: paths, caps and per-surface rules."""

    name: str
    always_on: tuple[str, ...]
    always_on_max: int
    always_on_cap_reason: str
    skill_dir: str
    skill_name_rule: str
    trigger_hint: str
    autotrigger_file: str
    trigger_line: str
    subagent_requires_mode: bool
    plugin_dir: str | None
    hooks_file: str | None
    hook_events: frozenset[str] = frozenset()
    compile_skill_scripts: bool = False
    reject_empty_always_on: bool = False

    stubs: tuple[tuple[str, str], ...] = ()

    # --- claude-gateway additions; every default reproduces the upstream behaviour ---------
    # Regex with ONE capture group (the sub-agent name) and the path template it came from.
    subagent_pattern: str = _UPSTREAM_SUBAGENT_PATTERN
    subagent_path: str = _UPSTREAM_SUBAGENT_PATH
    # "ignore" (upstream) or "must_match": frontmatter `name:` must equal the file stem.
    subagent_name_rule: str = "ignore"
    # Regex (fullmatch) for a helper script path; .py matches are compiled.
    script_pattern: str = _UPSTREAM_SCRIPT_PATTERN
    # Regex (findall, one capture group) for a script invocation in a SKILL.md / always-on
    # file; `{sd}` is replaced with the escaped skill_dir. None = upstream `python3 scripts/x.py`.
    script_ref_pattern: str | None = None
    # Skills and sub-agents must carry a semver `version:` in their frontmatter.
    require_version: bool = False
    # Hook `type` values the framework dispatches.
    hook_types: frozenset[str] = frozenset({"command"})
    # The hooks file is a general settings file: a missing/empty `hooks` block is fine.
    hooks_optional: bool = False
    # "substring" (upstream `name in body`) or "slash_or_backtick" (`/name` or `` `name` ``).
    trigger_match: str = "substring"


@lru_cache(maxsize=8)
def _res(
    surface_name: str,
    skill_dir: str,
    plugin_dir: str | None,
    subagent_pattern: str,
    script_pattern: str,
    script_ref_pattern: str | None,
) -> dict[str, re.Pattern]:
    sd = re.escape(skill_dir)
    if script_ref_pattern is None:
        script_ref_pattern = rf"(?:python3?\s+)((?:{sd}/[\w\-]+/)?scripts/[\w.\-]+\.py)"
    else:
        script_ref_pattern = script_ref_pattern.replace("{sd}", sd)
    out = {
        "skill": re.compile(rf"{sd}/({_NAME})/SKILL\.md"),
        "skill_script": re.compile(rf"{sd}/{_NAME}/scripts/[A-Za-z0-9_.\-]+"),
        "subagent": re.compile(subagent_pattern),
        "script": re.compile(script_pattern),
        "script_ref": re.compile(script_ref_pattern),
    }
    if plugin_dir is not None:
        out["plugin"] = re.compile(rf"{re.escape(plugin_dir)}/({_NAME})\.ts")
    return out


def _rx(surface: SurfaceSpec) -> dict[str, re.Pattern]:
    return _res(
        surface.name,
        surface.skill_dir,
        surface.plugin_dir,
        surface.subagent_pattern,
        surface.script_pattern,
        surface.script_ref_pattern,
    )


def normalize_rel(rel: str) -> str:
    """Normalise a relative path, rejecting escapes before it is joined to a directory."""
    r = str(rel).strip().replace("\\", "/")
    if r.startswith("/") or ".." in r.split("/"):
        raise ValueError(f"path escapes the harness: {rel!r}")
    while r.startswith("./"):
        r = r[2:]
    return r.strip("/")


def is_allowed(surface: SurfaceSpec, rel: str) -> bool:
    """Whether this path is on the editable surface. A predicate: it never raises."""
    try:
        rel = normalize_rel(rel)
    except ValueError:
        return False
    if rel in surface.always_on:
        return True
    if surface.hooks_file is not None and rel == surface.hooks_file:
        return True
    r = _rx(surface)
    if (
        r["skill"].fullmatch(rel)
        or r["skill_script"].fullmatch(rel)
        or r["subagent"].fullmatch(rel)
        or r["script"].fullmatch(rel)
    ):
        return True
    return "plugin" in r and bool(r["plugin"].fullmatch(rel))


def skill_names(surface: SurfaceSpec, tree: Tree) -> list[str]:
    rx = _rx(surface)["skill"]
    return sorted({m.group(1) for rel in tree if (m := rx.fullmatch(rel))})


def subagent_names(surface: SurfaceSpec, tree: Tree) -> list[str]:
    rx = _rx(surface)["subagent"]
    return sorted({m.group(1) for rel in tree if (m := rx.fullmatch(rel))})


def _stub_paths(surface: SurfaceSpec) -> frozenset[str]:
    return frozenset(rel for rel, _ in surface.stubs)


def read_tree(surface: SurfaceSpec, d: Path | str, *, rejected: list[str] | None = None) -> Tree:
    """rel -> content for every file on the editable surface, README stubs excluded.

    Pass `rejected` to collect paths that exist on disk but are off the surface.
    """
    d = Path(d)
    out: Tree = {}
    if not d.is_dir():
        return out
    stubs = _stub_paths(surface)
    for p in sorted(d.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = str(p.relative_to(d))
        if rel in stubs:
            continue
        if not is_allowed(surface, rel):
            if rejected is not None:
                rejected.append(rel)
            continue
        out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def is_tree(surface: SurfaceSpec, d: Path | str) -> bool:
    d = Path(d)
    return d.is_dir() and any((d / a).is_file() for a in surface.always_on)


def write_tree(surface: SurfaceSpec, tree: Tree, dest: Path | str, *, stubs: bool = True) -> Path:
    """Materialise an exact editable tree, with always-on files and optional stubs present.

    Files outside the editable surface are preserved; editable files already there are not.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stub_set = _stub_paths(surface)
    for p in sorted(dest.rglob("*"), reverse=True):
        if not p.is_file():
            continue
        rel = str(p.relative_to(dest))
        if is_allowed(surface, rel) or rel in stub_set:
            p.unlink()
    for a in surface.always_on:
        p = dest / a
        p.parent.mkdir(parents=True, exist_ok=True)
        if a not in tree and not p.exists():
            p.write_text("", encoding="utf-8")
    for rel, content in tree.items():
        p = dest / normalize_rel(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if stubs:
        for rel, body in surface.stubs:
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text(body, encoding="utf-8")
    return dest


def always_on_text(surface: SurfaceSpec, tree: Tree) -> str:
    return "\n\n".join(tree.get(a, "") for a in surface.always_on)


def _frontmatter(src: str) -> str:
    """The YAML block between the opening and closing `---` fences, else the first 600 chars.

    Upstream slices `[:600]`; a long single-line `description:` (this repo's agents) pushes
    `version:` past that, so the fence-delimited block is used when one exists.
    """
    if src.startswith("---"):
        end = src.find("\n---", 3)
        if end != -1:
            return src[: end + 1]
    return src[:600]


def is_triggered(surface: SurfaceSpec, name: str, body: str) -> bool:
    """Whether `body` names the skill in a form the agent recognises as a trigger."""
    if surface.trigger_match == "slash_or_backtick":
        n = re.escape(name)
        # `/name` not continued by a name char and not `/name.ext` (a script path); or `name`.
        return re.search(rf"`{n}`|/{n}(?![A-Za-z0-9_\-])(?!\.\w)", body) is not None
    return name in body


def autotrigger(surface: SurfaceSpec, tree: Tree, *, always_on_max: int | None = None) -> list[str]:
    """Give every skill a trigger line in always-on text; return the names repaired.

    A line that would push the body over the always-on cap is skipped instead.
    """
    cap = surface.always_on_max if always_on_max is None else always_on_max
    body = always_on_text(surface, tree)
    fixed: list[str] = []
    for name in skill_names(surface, tree):
        if is_triggered(surface, name, body):
            continue
        fm = _frontmatter(tree.get(f"{surface.skill_dir}/{name}/SKILL.md", ""))
        m = re.search(r"^description:\s*(.+)$", fm, re.M)
        desc = m.group(1).strip().rstrip(".") if m else f"the {name} workflow applies"
        line = surface.trigger_line.format(name=name, desc=desc)
        cur = tree.get(surface.autotrigger_file, "")
        if len(always_on_text(surface, tree)) + len(line) + 2 > cap:
            continue
        tree[surface.autotrigger_file] = (cur.rstrip() + "\n" + line) if cur.strip() else line
        body = always_on_text(surface, tree)
        fixed.append(name)
    return fixed


def check_hooks(
    surface: SurfaceSpec, src: str, errs: list[str], *, hooks_file: str | None = None
) -> None:
    """Validate the hooks file against the schema the framework dispatches; a malformed one
    never fires rather than erroring, so the shape is enforced where the proposer sees it.

    `hooks_file` overrides the name used in messages (e.g. a second settings file that carries
    the same `{"hooks": ...}` shape). Top-level keys other than `hooks` are ignored.
    """
    hf = surface.hooks_file if hooks_file is None else hooks_file
    try:
        doc = json.loads(src)
    except json.JSONDecodeError as exc:
        errs.append(f"{hf} is not valid JSON: {exc}")
        return
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    if isinstance(doc, dict) and surface.hooks_optional and (hooks is None or hooks == {}):
        return  # a settings file without a hooks block is a settings file, not a broken hook
    if not isinstance(hooks, dict) or not hooks:
        errs.append(f'{hf} needs a top-level {{"hooks": {{"<Event>": [...]}}}} object')
        return
    for event, entries in hooks.items():
        if event not in surface.hook_events:
            errs.append(
                f"{hf}: unknown event {event!r}; the framework dispatches "
                f"{', '.join(sorted(surface.hook_events))} (PascalCase)"
            )
            continue
        if not isinstance(entries, list):
            errs.append(f"{hf}: {event} must map to a LIST of matcher entries")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                errs.append(f"{hf}: {event}[{i}] needs a `hooks` list")
                continue
            for h in entry["hooks"]:
                htype = h.get("type") if isinstance(h, dict) else None
                if htype not in surface.hook_types:
                    if surface.hook_types == frozenset({"command"}):
                        errs.append(
                            f'{hf}: {event}[{i}] hook type must be "command" — '
                            f"async/prompt/agent hooks are skipped as 'not supported yet'"
                        )
                    else:
                        errs.append(
                            f"{hf}: {event}[{i}] hook type must be one of "
                            f"{', '.join(sorted(surface.hook_types))} (got {htype!r})"
                        )
                elif htype == "command" and not str(h.get("command", "")).strip():
                    errs.append(f"{hf}: {event}[{i}] has an empty `command`")
                elif htype in ("prompt", "agent") and not str(h.get("prompt", "")).strip():
                    errs.append(f"{hf}: {event}[{i}] {htype} hook has an empty `prompt`")


def _py_compiles(rel: str, src: str, errs: list[str]) -> None:

    try:
        compile(src, rel, "exec")
    except (SyntaxError, ValueError) as exc:
        detail = (
            f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
            if isinstance(exc, SyntaxError)
            else f"{type(exc).__name__}: {exc}"
        )
        errs.append(f"{rel} does not compile: {detail[:160]}")


def _check_skills(surface: SurfaceSpec, tree: Tree, body: str, errs: list[str]) -> list[str]:
    """Append every skill-frontmatter and untriggered-skill problem; return the skill names."""
    skills = skill_names(surface, tree)
    for name in skills:
        path = f"{surface.skill_dir}/{name}/SKILL.md"
        fm = _frontmatter(tree[path])
        if not re.search(r"^description:\s*\S", fm, re.M):
            errs.append(
                f"{path} needs a `description:` in its "
                f"frontmatter, or the skill is dropped SILENTLY at load"
            )
        m_name = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
        if surface.skill_name_rule == "must_match":
            if not (m_name and m_name.group(1) == name):
                errs.append(
                    f"{path} needs frontmatter "
                    f"`name: {name}` matching its directory (a mismatch is dropped "
                    f"SILENTLY at load)"
                )
        elif m_name and m_name.group(1) != name:
            errs.append(
                f"{path} frontmatter `name: "
                f"{m_name.group(1)}` OVERRIDES the directory name at load, so every "
                f"trigger line naming `{name}` stops matching; drop the `name:` line "
                f"or make it `name: {name}`"
            )
        if surface.require_version and not _SEMVER.search(fm):
            errs.append(
                f"{path} needs a semver `version:` in its frontmatter "
                f"(e.g. `version: 1.0.0`; see docs/runbooks/skill-versioning.md)"
            )
        if not is_triggered(surface, name, body):
            errs.append(
                f"skill '{name}' is never named in the always-on text, so the agent "
                f"will not know to invoke it — an untriggered skill is dead weight. "
                + surface.trigger_hint.format(name=name)
            )
    return skills


def _check_subagents(
    surface: SurfaceSpec, tree: Tree, allow_subagents: bool, errs: list[str]
) -> list[str]:
    """Append every sub-agent problem; return the sub-agent names."""
    subs = subagent_names(surface, tree)
    if subs and not allow_subagents:
        errs.append(f"sub_agents are not available on this deployment: {subs}")
    for name in subs:
        path = surface.subagent_path.format(name=name)
        fm = _frontmatter(tree[path])
        if surface.subagent_requires_mode and not re.search(r"^mode:\s*subagent\s*$", fm, re.M):
            errs.append(f"{path} needs frontmatter `mode: subagent`")
        if not re.search(r"^description:\s*\S", fm, re.M):
            errs.append(f"{path} needs a `description:`")
        if surface.subagent_name_rule == "must_match":
            m_name = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
            if not (m_name and m_name.group(1) == name):
                errs.append(
                    f"{path} needs frontmatter `name: {name}` matching its file name "
                    f"(the Agent tool addresses it by that name)"
                )
        if surface.require_version and not _SEMVER.search(fm):
            errs.append(
                f"{path} needs a semver `version:` in its frontmatter (e.g. `version: 1.0.0`)"
            )
    return subs


def _check_script_refs(
    surface: SurfaceSpec,
    tree: Tree,
    r: dict[str, re.Pattern],
    reserved_scripts: frozenset[str] | set[str],
    errs: list[str],
) -> None:
    """Append a problem for every script a skill or always-on file invokes but does not ship."""
    have = {rel for rel in tree if r["script"].fullmatch(rel) or r["skill_script"].fullmatch(rel)}
    for rel, src in tree.items():
        if not (r["skill"].fullmatch(rel) or rel in surface.always_on):
            continue
        seen: set[str] = set()
        for ref in r["script_ref"].findall(src):
            if ref in seen or ref.rsplit("/", 1)[-1] in reserved_scripts:
                continue
            seen.add(ref)
            if ref not in have:
                errs.append(f"{rel} invokes `{ref}` but that file is not in the harness")


def census(surface: SurfaceSpec, tree: Tree) -> dict:
    """Counts of what the tree holds (what `validate` returns when the tree is clean)."""
    r = _rx(surface)
    body = always_on_text(surface, tree)
    out = {
        "always_on_chars": len(body),
        "always_on_bytes": len(body.encode("utf-8")),
        "n_files": len(tree),
        "skills": len(skill_names(surface, tree)),
        "sub_agents": len(subagent_names(surface, tree)),
        "scripts": sum(1 for rel in tree if r["script"].fullmatch(rel)),
    }
    if surface.plugin_dir is not None:
        out["plugins"] = sum(1 for rel in tree if r["plugin"].fullmatch(rel))
    if surface.hooks_file is not None:
        out["hooks"] = 1 if surface.hooks_file in tree else 0
    return out


def validate(
    surface: SurfaceSpec,
    tree: Tree,
    *,
    allow_subagents: bool = True,
    always_on_max: int | None = None,
    reserved_scripts: frozenset[str] | set[str] = RESERVED_SCRIPTS,
    extra_trigger_text: str = "",
) -> dict:
    """Raise ValueError listing every problem; return a census of the validated tree.

    `extra_trigger_text` is text that also counts for skill triggers but NOT for the
    always-on cap — e.g. the Runner's Build Prompt code, which is injected into every
    dispatched session's prompt and names skills the always-on files do not.
    """
    errs: list[str] = []
    r = _rx(surface)
    cap = surface.always_on_max if always_on_max is None else always_on_max
    body = always_on_text(surface, tree)
    trigger_body = body + ("\n\n" + extra_trigger_text if extra_trigger_text else "")

    if len(body) > cap:
        errs.append(
            f"always-on content is {len(body)} chars, over the {cap} cap; "
            f"{surface.always_on_cap_reason}"
        )
    if surface.reject_empty_always_on and not body.strip():
        errs.append(
            f"{surface.always_on[0]} is empty — it is the only always-on file on "
            f"this framework, so an empty one is a harness that does not exist"
        )

    _check_skills(surface, tree, trigger_body, errs)
    _check_subagents(surface, tree, allow_subagents, errs)

    for rel, src in tree.items():
        if (r["script"].fullmatch(rel) and rel.endswith(".py")) or (
            surface.compile_skill_scripts
            and r["skill_script"].fullmatch(rel)
            and rel.endswith(".py")
        ):
            _py_compiles(rel, src, errs)

    if surface.hooks_file is not None and surface.hooks_file in tree:
        check_hooks(surface, tree[surface.hooks_file], errs)

    _check_script_refs(surface, tree, r, reserved_scripts, errs)

    if errs:
        raise ValueError(" | ".join(errs))
    return census(surface, tree)


def diff_summary(surface: SurfaceSpec, before: Tree, after: Tree) -> dict:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(rel for rel in set(before) & set(after) if before[rel] != after[rel])
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "always_on_char_delta": (
            len(always_on_text(surface, after)) - len(always_on_text(surface, before))
        ),
    }


def diversity(trees: dict[str, Tree]) -> dict:
    """Pairwise line-Jaccard over candidate trees, so collapse to one body is visible."""
    names = sorted(trees)
    if len(names) < 2:
        return {"n": len(names), "n_distinct": len(names), "mean_line_jaccard": 1.0}

    def lines(t: Tree) -> set[str]:
        return {f"{rel}:{ln}" for rel, c in t.items() for ln in c.splitlines() if ln.strip()}

    sets = {n: lines(trees[n]) for n in names}
    sims = []
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            u = sets[a] | sets[b]
            sims.append(len(sets[a] & sets[b]) / len(u) if u else 1.0)
    distinct = len({tuple(sorted(t.items())) for t in trees.values()})
    return {
        "n": len(names),
        "n_distinct": distinct,
        "mean_line_jaccard": round(sum(sims) / len(sims), 4),
    }


# ---------------------------------------------------------------------------------------------
# Claude Code surface (claude-gateway)
# ---------------------------------------------------------------------------------------------

CLAUDE_CODE_SURFACE = SurfaceSpec(
    name="claude_code",
    always_on=(
        "CLAUDE.md",
        ".claude/rules/ci-cd.md",
        ".claude/rules/infrastructure.md",
        ".claude/rules/openclaw.md",
        ".claude/rules/platform-features.md",
        ".claude/rules/references.md",
        ".claude/rules/workflows.md",
    ),
    always_on_max=_env_always_on_max(),
    always_on_cap_reason=(
        "every byte of CLAUDE.md and .claude/rules/*.md is loaded into every session in "
        "this repo; prefer a skill, script, subagent or hook"
    ),
    skill_dir=".claude/skills",
    skill_name_rule="must_match",
    trigger_hint=(
        "Fix it by naming `/{name}` (or `{name}`) once in CLAUDE.md, a rules file, or the "
        "Runner Build Prompt text."
    ),
    autotrigger_file="CLAUDE.md",
    trigger_line="- When {desc}, load the `/{name}` skill.\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=".claude/settings.json",
    hook_events=CLAUDE_CODE_HOOK_EVENTS,
    compile_skill_scripts=True,
    reject_empty_always_on=True,
    stubs=(),
    subagent_pattern=_CC_SUBAGENT_PATTERN,
    subagent_path=_CC_SUBAGENT_PATH,
    subagent_name_rule="must_match",
    script_pattern=_CC_SCRIPT_PATTERN,
    script_ref_pattern=_CC_SCRIPT_REF_PATTERN,
    require_version=True,
    hook_types=frozenset({"command", "prompt", "agent"}),
    hooks_optional=True,
    trigger_match="slash_or_backtick",
)


def claude_code_surface(
    repo_root: Path | str | None = None, *, always_on_max: int | None = None
) -> SurfaceSpec:
    """`CLAUDE_CODE_SURFACE` with `always_on` = CLAUDE.md + the `.claude/rules/*.md` files that
    exist in `repo_root` (the infra repos carry a different rules set), and the cap from
    `always_on_max` / `$ALWAYS_ON_MAX` / 48 KB.
    """
    rules: tuple[str, ...] = ()
    if repo_root is not None:
        rd = Path(repo_root) / ".claude" / "rules"
        if rd.is_dir():
            rules = tuple(f".claude/rules/{p.name}" for p in sorted(rd.glob("*.md")) if p.is_file())
    cap = _env_always_on_max() if always_on_max is None else always_on_max
    return dataclasses.replace(
        CLAUDE_CODE_SURFACE, always_on=("CLAUDE.md", *rules), always_on_max=cap
    )
