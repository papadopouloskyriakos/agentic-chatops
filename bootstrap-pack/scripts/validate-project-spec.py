#!/usr/bin/env python3
"""
validate-project-spec.py — Phase F Definition-of-Done gate for the project-bootstrap-pack.

Runs 17 checks against a project's spec/ tree. Exits 0 if ready for parallel agents, 1 otherwise.
Outputs human-readable report or JSON.

Spiritual sibling of scripts/validate-n8n-code-nodes.sh — gates spec-correctness the same way
the n8n validator gates workflow-correctness.

References:
- docs/plans/project-spec-schema-and-bootstrap.md
- EARS notation: https://alistairmavin.com/ears/
- GitHub Spec Kit: https://github.com/github/spec-kit
- claude-task-master schema: https://github.com/eyaltoledano/claude-task-master

Usage:
  ./validate-project-spec.py <project_root>
  ./validate-project-spec.py <project_root> --json
  ./validate-project-spec.py <project_root> --check ears_compliance
"""

import argparse
import json
import os
REDACTED_a7b84d63
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ============================================================================
# Constants
# ============================================================================

# EARS pattern regexes (Mavin et al., IEEE RE'09)
# Each line in requirements.md must match exactly one of these.
EARS_PATTERNS: dict[str, re.Pattern] = {
    "ubiquitous":   re.compile(r"^REQ-\d{3,}:\s+[Tt]he\s+\S.+?\sshall\s+.+\.$"),
    "event_driven": re.compile(r"^REQ-\d{3,}:\s+When\s+.+?,\s+the\s+\S.+?\sshall\s+.+\.$"),
    "state_driven": re.compile(r"^REQ-\d{3,}:\s+While\s+.+?,\s+the\s+\S.+?\sshall\s+.+\.$"),
    "optional":     re.compile(r"^REQ-\d{3,}:\s+Where\s+.+?,\s+the\s+\S.+?\sshall\s+.+\.$"),
    "unwanted":     re.compile(r"^REQ-\d{3,}:\s+If\s+.+?,\s+then\s+the\s+\S.+?\sshall\s+.+\.$"),
}

REQ_ID_RE = re.compile(r"^(REQ-\d{3,}):")

# Forbidden weasel-words in spec files
WEASEL_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bTODO\b"),
    re.compile(r"\bTBD\b"),
    re.compile(r"\bFIXME\b"),
    re.compile(r"\bshould be\b", re.IGNORECASE),
    re.compile(r"\bvarious\b", re.IGNORECASE),
    re.compile(r"\betc\.\b", re.IGNORECASE),
    re.compile(r"\bmight\b", re.IGNORECASE),
    re.compile(r"\bmaybe\b", re.IGNORECASE),
]

# PROJECT.json required top-level fields
PROJECT_JSON_REQUIRED: list[str] = [
    "slug", "title", "youtrack_prefix", "matrix_room",
    "primary_language", "test_command", "lint_command",
    "bounded_contexts", "max_parallel_workers", "owners", "risk_profile",
    "surfaces",  # NEW: declares which contracts the project exposes (see SURFACES_DEFAULT)
]

# PROJECT.json#surfaces — declares which contract artifacts the project produces.
# Default to strict (all true) so a forgotten declaration FAILS loudly instead of
# silently passing via "absent = OK" loophole.
SURFACES_KEYS: set[str] = {"http_api", "events", "persistent_data"}
SURFACES_DEFAULT: dict[str, bool] = {"http_api": True, "events": True, "persistent_data": True}


def load_surfaces(root: Path) -> dict[str, bool]:
    """Read PROJECT.json#surfaces, falling back to SURFACES_DEFAULT (all true)."""
    pj_path = root / "PROJECT.json"
    if not pj_path.is_file():
        return SURFACES_DEFAULT.copy()
    try:
        data = json.loads(pj_path.read_text())
    except json.JSONDecodeError:
        return SURFACES_DEFAULT.copy()
    declared = data.get("surfaces", {})
    out = SURFACES_DEFAULT.copy()
    if isinstance(declared, dict):
        for k in SURFACES_KEYS:
            if k in declared:
                out[k] = bool(declared[k])
    return out

# tasks.json — required fields per task
TASK_REQUIRED_FIELDS: list[str] = [
    "task_id", "title", "dependencies", "parallelizable",
    "files_owned", "requirement_ids", "bounded_context",
    "acceptance_test", "risk_score",
]
# Optional but recommended: complexity, max_wall_clock_minutes, max_loc_delta, details
# status is auto-defaulted to 'pending' by the planner.


# ============================================================================
# Result model
# ============================================================================

@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": self.details,
            "errors": self.errors,
        }


# ============================================================================
# 17 Checks (skeletons — TODO mark real implementation work)
# ============================================================================

def check_project_json_schema(root: Path) -> CheckResult:
    """C01: PROJECT.json parses and has all required fields."""
    path = root / "PROJECT.json"
    if not path.is_file():
        return CheckResult("project_json_schema", False, f"missing: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return CheckResult("project_json_schema", False, f"parse error: {e}")
    missing = [f for f in PROJECT_JSON_REQUIRED if f not in data]
    if missing:
        return CheckResult("project_json_schema", False,
                           f"missing fields: {missing}")
    return CheckResult("project_json_schema", True,
                       f"all {len(PROJECT_JSON_REQUIRED)} required fields present")


def check_constitution_article_count(root: Path) -> CheckResult:
    """C02: constitution.md has 5-15 articles (Article I, II, ...)."""
    path = root / "constitution.md"
    if not path.is_file():
        return CheckResult("constitution_article_count", False, f"missing: {path}")
    # Accept any markdown heading level (# / ## / ###) for Article headers — templates use ##,
    # but operators sometimes promote to # if their constitution.md is a flat list without a title.
    articles = re.findall(r"^#+\s*Article\s+[IVXLC]+\b", path.read_text(), re.MULTILINE)
    n = len(articles)
    if 5 <= n <= 15:
        return CheckResult("constitution_article_count", True, f"{n} articles")
    return CheckResult("constitution_article_count", False,
                       f"expected 5-15 articles, got {n}")


def check_ears_compliance(root: Path) -> CheckResult:
    """C03: Every REQ-NNN line in every requirements.md matches one of 5 EARS patterns."""
    spec_dir = root / "spec"
    if not spec_dir.is_dir():
        return CheckResult("ears_compliance", False, "missing spec/ directory")
    errors: list[str] = []
    total = 0
    for req_file in spec_dir.rglob("requirements.md"):
        for lineno, line in enumerate(req_file.read_text().splitlines(), 1):
            stripped = line.strip()
            if not stripped or not stripped.startswith("REQ-"):
                continue
            total += 1
            if not any(p.match(stripped) for p in EARS_PATTERNS.values()):
                errors.append(f"{req_file.relative_to(root)}:{lineno}: not EARS-shape: {stripped[:80]}")
    if errors:
        return CheckResult("ears_compliance", False,
                           f"{len(errors)}/{total} non-EARS lines", errors[:20])
    return CheckResult("ears_compliance", True, f"all {total} requirement lines EARS-compliant")


def check_requirement_unique_ids(root: Path) -> CheckResult:
    """C04: Every REQ-NNN ID is unique across all requirements.md files."""
    spec_dir = root / "spec"
    if not spec_dir.is_dir():
        return CheckResult("requirement_unique_ids", False, "missing spec/ directory")
    seen: dict[str, str] = {}
    errors: list[str] = []
    for req_file in spec_dir.rglob("requirements.md"):
        for lineno, line in enumerate(req_file.read_text().splitlines(), 1):
            m = REQ_ID_RE.match(line.strip())
            if not m:
                continue
            req_id = m.group(1)
            if req_id in seen:
                errors.append(f"{req_id} duplicated: first at {seen[req_id]}, again at {req_file.relative_to(root)}:{lineno}")
            else:
                seen[req_id] = f"{req_file.relative_to(root)}:{lineno}"
    if errors:
        return CheckResult("requirement_unique_ids", False, f"{len(errors)} duplicates", errors)
    return CheckResult("requirement_unique_ids", True, f"{len(seen)} unique REQ ids")


def check_no_weasel_words(root: Path) -> CheckResult:
    """C05: No TODO / TBD / FIXME / 'should be' / 'various' / 'etc.' in any spec file."""
    errors: list[str] = []
    for path in (root / "spec").rglob("*.md") if (root / "spec").is_dir() else []:
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for pat in WEASEL_PATTERNS:
                if pat.search(line):
                    errors.append(f"{path.relative_to(root)}:{lineno}: {pat.pattern}: {line.strip()[:80]}")
    if errors:
        return CheckResult("no_weasel_words", False, f"{len(errors)} weasel-words", errors[:20])
    return CheckResult("no_weasel_words", True, "no weasel-words found")


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _load_yaml(path: Path):
    """Load YAML via PyYAML if present, else a minimal top-level-key parser (offline-safe)."""
    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text()), None
    except ImportError:
        top: dict = {}
        for line in path.read_text().splitlines():
            m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
            if m:
                top[m.group(1)] = m.group(2)
        return top, "pyyaml-absent"
    except Exception as e:  # noqa: BLE001
        return None, f"yaml parse error: {e}"


def _validate_contract(f: Path, kind: str) -> tuple[bool, str]:
    """Prefer the canonical npx CLI; fall back to offline structural validation in CI.

    Closes the npx-fragility debt: a Node-less runner (CI python:3.12-slim) still
    validates contract shape instead of silently erroring.
    """
    cli = {"openapi": ("@apidevtools/swagger-cli", "validate"),
           "asyncapi": ("@asyncapi/cli", "validate")}[kind]
    if _have("npx"):
        result = subprocess.run(["npx", "--yes", cli[0], cli[1], str(f)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return True, "npx-validated"
        return False, (result.stderr.strip()[:200] or result.stdout.strip()[:200])
    data, note = _load_yaml(f)
    if data is None:
        return False, note or "could not parse"
    need = "openapi" if kind == "openapi" else "asyncapi"
    anchor = "paths" if kind == "openapi" else "channels"
    if note == "pyyaml-absent":
        if need not in data:
            return False, f"missing top-level '{need}:'"
        if anchor not in data:
            return False, f"missing top-level '{anchor}:'"
        return True, "structural (pyyaml absent)"
    if not isinstance(data, dict):
        return False, "not a mapping"
    errs: list[str] = []
    if not str(data.get(need, "")):
        errs.append(f"missing '{need}' version")
    if "info" not in data:
        errs.append("missing 'info'")
    block = data.get(anchor)
    if not isinstance(block, dict) or not block:
        errs.append(f"missing or empty '{anchor}'")
    return (not errs), ("; ".join(errs) if errs else "structural-validated")


def check_openapi_valid(root: Path) -> CheckResult:
    """C06: All contracts/openapi.yaml validate via swagger-cli (npx) or an offline fallback.

    Strict per PROJECT.json#surfaces.http_api: if http_api=true, openapi.yaml MUST exist.
    If http_api=false, absence is a substantive pass (no surface to validate).
    """
    surfaces = load_surfaces(root)
    files = list((root / "spec").rglob("openapi.yaml")) if (root / "spec").is_dir() else []
    if not files:
        if surfaces["http_api"]:
            return CheckResult("openapi_valid", False,
                               "no openapi.yaml found but PROJECT.json#surfaces.http_api=true; "
                               "either author openapi.yaml or set http_api=false")
        return CheckResult("openapi_valid", True, "PROJECT.json#surfaces.http_api=false; no openapi.yaml expected")
    errors: list[str] = []
    for f in files:
        ok, msg = _validate_contract(f, "openapi")
        if not ok:
            errors.append(f"{f.relative_to(root)}: {msg}")
    if errors:
        return CheckResult("openapi_valid", False, f"{len(errors)}/{len(files)} invalid", errors)
    return CheckResult("openapi_valid", True, f"{len(files)} openapi.yaml file(s) valid")


def check_asyncapi_valid(root: Path) -> CheckResult:
    """C07: All contracts/asyncapi.yaml validate via @asyncapi/cli.

    Strict per PROJECT.json#surfaces.events: if events=true, asyncapi.yaml MUST exist.
    If events=false, absence is a substantive pass (no surface to validate).
    """
    surfaces = load_surfaces(root)
    files = list((root / "spec").rglob("asyncapi.yaml")) if (root / "spec").is_dir() else []
    if not files:
        if surfaces["events"]:
            return CheckResult("asyncapi_valid", False,
                               "no asyncapi.yaml found but PROJECT.json#surfaces.events=true; "
                               "either author asyncapi.yaml or set events=false")
        return CheckResult("asyncapi_valid", True, "PROJECT.json#surfaces.events=false; no asyncapi.yaml expected")
    errors: list[str] = []
    for f in files:
        ok, msg = _validate_contract(f, "asyncapi")
        if not ok:
            errors.append(f"{f.relative_to(root)}: {msg}")
    if errors:
        return CheckResult("asyncapi_valid", False, f"{len(errors)}/{len(files)} invalid", errors)
    return CheckResult("asyncapi_valid", True, f"{len(files)} asyncapi.yaml file(s) valid")


def check_json_schemas_valid(root: Path) -> CheckResult:
    """C08: All contracts/schemas/*.json are valid JSON Schema.

    Strict per PROJECT.json#surfaces.persistent_data: if persistent_data=true,
    at least one schemas/*.json MUST exist (data shapes must have schemas).
    """
    surfaces = load_surfaces(root)
    schemas_dirs = list((root / "spec").rglob("schemas")) if (root / "spec").is_dir() else []
    files: list[Path] = []
    for d in schemas_dirs:
        files.extend(d.glob("*.json"))
    if not files:
        if surfaces["persistent_data"]:
            return CheckResult("json_schemas_valid", False,
                               "no schemas/*.json found but PROJECT.json#surfaces.persistent_data=true; "
                               "either author at least one JSON Schema for your data shapes or set persistent_data=false")
        return CheckResult("json_schemas_valid", True, "PROJECT.json#surfaces.persistent_data=false; no schemas expected")
    errors: list[str] = []
    # Use Python jsonschema directly — avoids ajv-cli's Node-module-resolution + format-vocab issues.
    try:
        import jsonschema
    except ImportError:
        return CheckResult("json_schemas_valid", False,
                           "python3 'jsonschema' package not installed; "
                           "install via: pip3 install jsonschema")
    for f in files:
        try:
            schema = json.loads(f.read_text())
            # Validate the schema is itself a valid JSON Schema (meta-validation)
            jsonschema.Draft7Validator.check_schema(schema)
        except json.JSONDecodeError as e:
            errors.append(f"{f.relative_to(root)}: JSON parse error: {e}")
        except jsonschema.exceptions.SchemaError as e:
            errors.append(f"{f.relative_to(root)}: invalid schema: {e.message[:200]}")
        except Exception as e:
            errors.append(f"{f.relative_to(root)}: {type(e).__name__}: {str(e)[:200]}")
    if errors:
        return CheckResult("json_schemas_valid", False, f"{len(errors)}/{len(files)} invalid", errors)
    return CheckResult("json_schemas_valid", True, f"{len(files)} JSON Schema(s) valid")


def check_tasks_required_fields(root: Path) -> CheckResult:
    """C09: Every task in every tasks.json has all required fields."""
    files = list((root / "spec").rglob("tasks.json")) if (root / "spec").is_dir() else []
    if not files:
        return CheckResult("tasks_required_fields", False, "no tasks.json found")
    errors: list[str] = []
    total = 0
    for f in files:
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{f.relative_to(root)}: JSON parse error: {e}")
            continue
        for task in data.get("tasks", []):
            total += 1
            missing = [k for k in TASK_REQUIRED_FIELDS if k not in task]
            if missing:
                errors.append(f"{f.relative_to(root)}: task {task.get('task_id', '?')} missing fields: {missing}")
    if errors:
        return CheckResult("tasks_required_fields", False,
                           f"{len(errors)} field issue(s) across {total} task(s)", errors[:20])
    return CheckResult("tasks_required_fields", True, f"all {total} tasks have required fields")


def check_tasks_dag_no_cycles(root: Path) -> CheckResult:
    """C10: tasks.json forms a DAG (no dependency cycles). Kahn's algorithm."""
    files = list((root / "spec").rglob("tasks.json")) if (root / "spec").is_dir() else []
    if not files:
        return CheckResult("tasks_dag_no_cycles", False, "no tasks.json found")
    errors: list[str] = []
    total_tasks = 0
    for f in files:
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        ids = {t["task_id"] for t in tasks if "task_id" in t}
        deps: dict[str, set] = {}
        for t in tasks:
            tid = t.get("task_id")
            if not tid:
                continue
            ds = set(t.get("dependencies") or [])
            unknown = ds - ids
            if unknown:
                errors.append(f"{f.relative_to(root)}: task {tid} depends on unknown ids: {sorted(unknown)}")
            deps[tid] = ds & ids
            total_tasks += 1
        indeg = {tid: len(d) for tid, d in deps.items()}
        queue = [tid for tid, n in indeg.items() if n == 0]
        visited: list[str] = []
        while queue:
            tid = queue.pop(0)
            visited.append(tid)
            for other, other_d in deps.items():
                if tid in other_d:
                    indeg[other] -= 1
                    if indeg[other] == 0:
                        queue.append(other)
        if len(visited) != len(deps):
            cyclic = sorted(set(deps) - set(visited))
            errors.append(f"{f.relative_to(root)}: dependency cycle involves: {cyclic}")
    if errors:
        return CheckResult("tasks_dag_no_cycles", False, f"{len(errors)} issue(s)", errors[:10])
    return CheckResult("tasks_dag_no_cycles", True, f"all {total_tasks} tasks form a DAG")


def check_parallelizable_no_file_collision(root: Path) -> CheckResult:
    """C11: No two parallelizable:true tasks in the same wave share files_owned. Wave = topological depth."""
    files = list((root / "spec").rglob("tasks.json")) if (root / "spec").is_dir() else []
    if not files:
        return CheckResult("parallelizable_no_file_collision", False, "no tasks.json found")
    errors: list[str] = []
    waves_checked = 0
    for f in files:
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        deps_by_id = {t["task_id"]: set(t.get("dependencies") or []) for t in tasks if "task_id" in t}
        depth: dict[str, int] = {}
        def compute_depth(tid: str, stack: set[str]) -> int:
            if tid in depth:
                return depth[tid]
            if tid in stack:
                return 0  # Cycle — handled elsewhere
            stack.add(tid)
            ds = deps_by_id.get(tid, set())
            d = 0 if not ds else (1 + max((compute_depth(x, stack) for x in ds if x in deps_by_id), default=0))
            depth[tid] = d
            stack.discard(tid)
            return d
        for tid in deps_by_id:
            compute_depth(tid, set())
        waves: dict[int, list[dict]] = {}
        for t in tasks:
            if "task_id" not in t:
                continue
            waves.setdefault(depth.get(t["task_id"], 0), []).append(t)
        for d, wave_tasks in waves.items():
            parallel = [t for t in wave_tasks if t.get("parallelizable", True)]
            for i, t1 in enumerate(parallel):
                for t2 in parallel[i + 1:]:
                    overlap = set(t1.get("files_owned", [])) & set(t2.get("files_owned", []))
                    if overlap:
                        errors.append(
                            f"{f.relative_to(root)}: wave {d}: {t1['task_id']} + {t2['task_id']} share: {sorted(overlap)}"
                        )
            waves_checked += 1
    if errors:
        return CheckResult("parallelizable_no_file_collision", False, f"{len(errors)} collision(s)", errors[:10])
    return CheckResult("parallelizable_no_file_collision", True, f"{waves_checked} wave(s) checked, no collisions")


def check_req_cross_references(root: Path) -> CheckResult:
    """C12: Every task's requirement_ids references real REQ-NNN; every task has at least one ref."""
    spec_dir = root / "spec"
    if not spec_dir.is_dir():
        return CheckResult("req_cross_references", False, "no spec/ dir")
    real_reqs: set[str] = set()
    for req_file in spec_dir.rglob("requirements.md"):
        for line in req_file.read_text().splitlines():
            m = REQ_ID_RE.match(line.strip())
            if m:
                real_reqs.add(m.group(1))
    errors: list[str] = []
    total = 0
    for f in spec_dir.rglob("tasks.json"):
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        tasks = data.get("tasks", []) if isinstance(data, dict) else data
        for t in tasks:
            total += 1
            req_ids = t.get("requirement_ids") or []
            if not req_ids:
                errors.append(f"{f.relative_to(root)}: task {t.get('task_id', '?')} has empty requirement_ids")
                continue
            unknown = [r for r in req_ids if r not in real_reqs]
            if unknown:
                errors.append(f"{f.relative_to(root)}: task {t.get('task_id', '?')} references unknown REQs: {unknown}")
    if errors:
        return CheckResult("req_cross_references", False, f"{len(errors)} issue(s)", errors[:10])
    return CheckResult("req_cross_references", True, f"all {total} tasks reference real REQs (of {len(real_reqs)} defined)")


def check_bounded_context_membership(root: Path) -> CheckResult:
    """C13: Every task[].bounded_context is in PROJECT.json#bounded_contexts."""
    project = root / "PROJECT.json"
    if not project.is_file():
        return CheckResult("bounded_context_membership", False, "missing PROJECT.json")
    try:
        contexts = set(json.loads(project.read_text()).get("bounded_contexts", []))
    except json.JSONDecodeError as e:
        return CheckResult("bounded_context_membership", False, f"PROJECT.json parse: {e}")
    if not contexts:
        return CheckResult("bounded_context_membership", False, "PROJECT.json has empty bounded_contexts")
    errors: list[str] = []
    total = 0
    for f in (root / "spec").rglob("tasks.json") if (root / "spec").is_dir() else []:
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        for task in data.get("tasks", []):
            total += 1
            bc = task.get("bounded_context")
            if bc not in contexts:
                errors.append(f"{f.relative_to(root)}: task {task.get('task_id')} bounded_context={bc!r} not in {sorted(contexts)}")
    if errors:
        return CheckResult("bounded_context_membership", False, f"{len(errors)}/{total} tasks invalid", errors[:20])
    if total == 0:
        # Strict: no tasks = no validation evidence. Fail rather than vacuous-pass.
        return CheckResult("bounded_context_membership", False,
                           "no tasks found in any tasks.json to validate against bounded_contexts")
    return CheckResult("bounded_context_membership", True, f"all {total} tasks in valid contexts")


_GHERKIN_STEP_RE = re.compile(r"^(Given|When|Then|And|But|\*)\s+\S")


def _validate_gherkin(text: str) -> list[str]:
    """Structural Gherkin validation (no Node/cucumber dependency).

    Enforces: exactly one Feature; Scenario after Feature; every scenario has >=1 step;
    steps use Given/When/Then/And/But; a scenario's first step is not And/But; >=1 REQ ref.
    Catches malformed-but-keyword-present files the old substring check passed.
    """
    errors: list[str] = []
    lines = text.splitlines()
    feature_count = sum(1 for ln in lines if ln.strip().startswith("Feature:"))
    if feature_count == 0:
        errors.append("no 'Feature:' declaration")
    elif feature_count > 1:
        errors.append(f"{feature_count} 'Feature:' declarations (expected 1)")
    seen_feature = False
    in_block = False          # inside a Scenario/Background that may hold steps
    steps_in_current = 0
    scenario_count = 0
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("@"):
            continue
        if s.startswith("Feature:"):
            seen_feature = True
            in_block = False
            continue
        if re.match(r"^(Scenario|Scenario Outline):", s):
            if not seen_feature:
                errors.append(f"line {i}: Scenario before Feature")
            if in_block and steps_in_current == 0:
                errors.append(f"line {i}: previous scenario has no steps")
            in_block = True
            steps_in_current = 0
            scenario_count += 1
            continue
        if re.match(r"^(Background|Rule|Examples):", s):
            in_block = True
            steps_in_current = 0
            continue
        m = _GHERKIN_STEP_RE.match(s)
        if m:
            if not in_block:
                errors.append(f"line {i}: step '{m.group(1)}' outside any scenario")
                continue
            if steps_in_current == 0 and m.group(1) in ("And", "But"):
                errors.append(f"line {i}: scenario's first step uses '{m.group(1)}' (need Given/When/Then)")
            steps_in_current += 1
            continue
        if s.startswith("|") or s.startswith('"""'):
            continue  # data table / doc string
        if in_block:
            errors.append(f"line {i}: not a valid Gherkin step: {s[:60]}")
        # lines before the first scenario are Feature description — allowed
    if in_block and steps_in_current == 0:
        errors.append("final scenario has no steps")
    if scenario_count == 0:
        errors.append("no Scenario found")
    if "REQ-" not in text:
        errors.append("no REQ-NNN reference")
    return errors


def check_gherkin_parseable(root: Path) -> CheckResult:
    """C14: Every .feature file in acceptance/ parses (real structural check) and references a REQ-NNN."""
    files = list((root / "spec").rglob("acceptance/*.feature")) if (root / "spec").is_dir() else []
    # Strict: if requirements.md exists with REQ-NNN entries, at least one .feature file
    # must exist that references a REQ. Otherwise absence is substantive pass.
    req_files = list((root / "spec").rglob("requirements.md")) if (root / "spec").is_dir() else []
    has_reqs = any(REQ_ID_RE.search(rf.read_text()) for rf in req_files)
    if not files:
        if has_reqs:
            return CheckResult("gherkin_parseable", False,
                               "no acceptance/*.feature files found but spec/*/requirements.md "
                               "contains REQ-NNN entries — every REQ needs at least one Gherkin scenario")
        return CheckResult("gherkin_parseable", True, "no requirements declared yet; no .feature files expected")
    errors: list[str] = []
    for f in files:
        for err in _validate_gherkin(f.read_text()):
            errors.append(f"{f.relative_to(root)}: {err}")
    if errors:
        return CheckResult("gherkin_parseable", False, f"{len(errors)} issue(s) across {len(files)} file(s)", errors[:20])
    return CheckResult("gherkin_parseable", True, f"{len(files)} .feature files structurally valid")


def check_adr_exists(root: Path) -> CheckResult:
    """C15: At least one ADR (Architecture Decision Record) exists in adr/."""
    adr_dir = root / "adr"
    if not adr_dir.is_dir():
        return CheckResult("adr_exists", False, "missing adr/ directory")
    adrs = list(adr_dir.glob("[0-9]*-*.md"))
    if not adrs:
        return CheckResult("adr_exists", False, "no ADRs found (expected NNNN-<title>.md)")
    return CheckResult("adr_exists", True, f"{len(adrs)} ADR(s) found")


def check_slot_config_entry_valid(root: Path) -> CheckResult:
    """C16: .agentic/slot-config.entry.json parses + non-duplicate against existing slot-config.json.

    Caller must provide path to live slot-config.json via env GATEWAY_SLOT_CONFIG
    (default /home/app-user/gateway-state/slot-config.json after (b) refactor lands).
    """
    entry_path = root / ".agentic" / "slot-config.entry.json"
    if not entry_path.is_file():
        return CheckResult("slot_config_entry_valid", False, f"missing: {entry_path}")
    try:
        entry = json.loads(entry_path.read_text())
    except json.JSONDecodeError as e:
        return CheckResult("slot_config_entry_valid", False, f"parse error: {e}")
    if not isinstance(entry, dict) or not entry:
        return CheckResult("slot_config_entry_valid", False, "expected non-empty object")

    # Deep validation: each slot needs absolute cwd + Matrix-shaped room; no key may
    # collide with a slot already present in the live dispatch slot-config.json.
    room_re = re.compile(r"^![^:\s]+:[^:\s]+$")
    errors: list[str] = []
    for slot, cfg in entry.items():
        if not isinstance(cfg, dict):
            errors.append(f"slot {slot!r}: value is not an object")
            continue
        cwd = cfg.get("cwd")
        if not cwd or not os.path.isabs(str(cwd)):
            errors.append(f"slot {slot!r}: 'cwd' missing or not an absolute path")
        room = cfg.get("room")
        if not room or not room_re.match(str(room)):
            errors.append(f"slot {slot!r}: 'room' missing or not a Matrix room id (!id:server)")

    live_path = Path(os.environ.get(
        "GATEWAY_SLOT_CONFIG", "/home/app-user/gateway-state/slot-config.json"))
    if live_path.is_file():
        try:
            live = json.loads(live_path.read_text())
            live_keys = set(live.keys()) if isinstance(live, dict) else set()
            dup = sorted(set(entry.keys()) & live_keys)
            if dup:
                errors.append(f"slot key(s) already in live slot-config: {dup}")
        except (json.JSONDecodeError, OSError):
            pass  # unreadable live config is not this check's failure

    if errors:
        return CheckResult("slot_config_entry_valid", False, f"{len(errors)} issue(s)", errors)
    return CheckResult("slot_config_entry_valid", True,
                       f"{len(entry)} slot(s) declared, cwd+room valid, no collision")


def check_risk_score_per_task(root: Path) -> CheckResult:
    """C17: Every task has a risk_score in [0, 1]; high-risk tasks (score > 0.7) flagged for human review."""
    files = list((root / "spec").rglob("tasks.json")) if (root / "spec").is_dir() else []
    if not files:
        return CheckResult("risk_score_per_task", False, "no tasks.json found")
    errors: list[str] = []
    high_risk: list[str] = []
    total = 0
    for f in files:
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        for task in data.get("tasks", []):
            total += 1
            score = task.get("risk_score")
            if not isinstance(score, (int, float)) or not 0.0 <= score <= 1.0:
                errors.append(f"{f.relative_to(root)}: task {task.get('task_id')} risk_score={score!r} not in [0,1]")
            elif score > 0.7:
                high_risk.append(f"{task.get('task_id')} (risk_score={score})")
    if errors:
        return CheckResult("risk_score_per_task", False, f"{len(errors)}/{total} invalid", errors)
    details = f"all {total} tasks have valid risk_score"
    if high_risk:
        details += f"; {len(high_risk)} HIGH-RISK requiring human review: {high_risk[:5]}"
    return CheckResult("risk_score_per_task", True, details)


# ============================================================================
# Main
# ============================================================================

ALL_CHECKS: list[Callable[[Path], CheckResult]] = [
    check_project_json_schema,
    check_constitution_article_count,
    check_ears_compliance,
    check_requirement_unique_ids,
    check_no_weasel_words,
    check_openapi_valid,
    check_asyncapi_valid,
    check_json_schemas_valid,
    check_tasks_required_fields,
    check_tasks_dag_no_cycles,
    check_parallelizable_no_file_collision,
    check_req_cross_references,
    check_bounded_context_membership,
    check_gherkin_parseable,
    check_adr_exists,
    check_slot_config_entry_valid,
    check_risk_score_per_task,
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a project spec for parallel-agent readiness (Phase F DoD gate).",
    )
    parser.add_argument("project_root", type=Path,
                        help="Path to project root containing PROJECT.json + spec/ etc.")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON report to stdout (machine-readable)")
    parser.add_argument("--check", type=str, default=None,
                        help="Run only one named check (e.g. ears_compliance)")
    parser.add_argument("--report", action="store_true",
                        help="Punch-list progress view: shows what's done / what's TODO without "
                             "claiming pass/fail. Useful for intermediate states during /bootstrap. "
                             "Does NOT replace the strict gate (exit 0 still requires all checks pass).")
    args = parser.parse_args()

    if not args.project_root.is_dir():
        print(f"error: not a directory: {args.project_root}", file=sys.stderr)
        return 2

    results: list[CheckResult] = []
    for fn in ALL_CHECKS:
        if args.check and fn.__name__ != f"check_{args.check}" and fn.__name__ != args.check:
            continue
        results.append(fn(args.project_root))

    if args.json:
        print(json.dumps({
            "project_root": str(args.project_root),
            "total_checks": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "results": [r.to_dict() for r in results],
        }, indent=2))
    elif args.report:
        # Honest punch-list — no PASS/FAIL claim, just done/todo per check
        passed = sum(1 for r in results if r.passed)
        if passed == len(results):
            print(f"Spec readiness: READY FOR DISPATCH — {passed}/{len(results)} checks complete\n")
        else:
            print(f"Spec readiness: NOT READY — {passed}/{len(results)} complete, "
                  f"{len(results) - passed} pending\n")
        for r in results:
            marker = "done" if r.passed else "TODO"
            print(f"  [{marker}] {r.name}: {r.details}")
        if passed < len(results):
            print(f"\nNext step: see docs/runbooks/new-project-bootstrap.md for the "
                  f"/specify → /constitute → /plan → /tasks flow")
    else:
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"  [{status}] {r.name}: {r.details}")
            for err in r.errors[:5]:
                print(f"          - {err}")
            if len(r.errors) > 5:
                print(f"          ... and {len(r.errors) - 5} more")
        passed = sum(1 for r in results if r.passed)
        print(f"\n{passed}/{len(results)} checks passed")

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
