#!/usr/bin/env python3
"""check-spec-code-lockstep.py — enforce spec<->code traceability (constitution Article VII).

The D2 (spec-driven development) lockstep gate for claude-gateway (IFRNLLEI01PRD-1260).
Companion to bootstrap-pack/scripts/validate-project-spec.py: that proves the spec is
internally well-formed; this proves the spec and the code it governs have not drifted.

Checks:
  1. No dangling spec   — every spec/<ctx>/tasks.json#files_owned path exists.
  2. No unspec'd safety — every safety-critical file is owned by some spec task.
  3. No double-owned    — each files_owned path belongs to exactly one task.
  4. CONTENT-AWARE drift (Round 2) — every governed file's content hash is recorded in
     spec/.lockstep.lock; if a governed CODE file changes but its owning context's
     specification (requirements.md + features) does NOT, that is spec drift and FAILS.
     `--update-manifest` re-stamps the hashes — the deliberate "I reviewed the spec for
     this change" action. So you cannot change safety code without touching its spec.

Exit 0 if in lockstep, 1 otherwise. Runs in CI, the QA suite, and holistic-health.

Env overrides (used by the BDD drift fixture): GATEWAY_SPEC_REPO (repo root),
GATEWAY_SAFETY_FILES (colon-separated safety-critical file list).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
REDACTED_a7b84d63
import sys
from pathlib import Path

# Semantic-content matchers (REQ-704): the spec hash covers only the requirement
# statements and Gherkin structure — NOT prose/comments — so a cosmetic spec edit
# cannot clear genuine code drift.
_REQ_LINE = re.compile(r"^REQ-\d{3,}:")
_GHERKIN_LINE = re.compile(r"^(Feature:|Scenario|Scenario Outline:|Background:|Given |When |Then |And |But )")

REPO = Path(os.environ.get("GATEWAY_SPEC_REPO", str(Path(__file__).resolve().parents[1])))
MANIFEST = REPO / "spec" / ".lockstep.lock"

_DEFAULT_SAFETY: list[str] = [
    "scripts/classify-session-risk.py",
    "scripts/infragraph-predict-plan.py",
    "scripts/infragraph-verify.py",
    "scripts/reconcile-completed-sessions.py",
    "scripts/write-governance-metrics.py",
    "scripts/lib/tier1_suppression.py",
    "schema.sql",
    "scripts/agentic-stats.py",
]


def safety_files() -> list[str]:
    env = os.environ.get("GATEWAY_SAFETY_FILES")
    return [x for x in env.split(":") if x] if env else _DEFAULT_SAFETY


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _collect() -> tuple[dict, dict, list[str]]:
    """Return (owned{file:task_id}, owned_ctx{file:ctx_dir}, structural_errors)."""
    spec = REPO / "spec"
    owned: dict[str, str] = {}
    owned_ctx: dict[str, str] = {}
    errors: list[str] = []
    if not spec.is_dir():
        return owned, owned_ctx, [f"no spec/ tree at {spec}"]
    for tj in sorted(spec.rglob("tasks.json")):
        ctx_dir = tj.parent.name
        try:
            data = json.loads(tj.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{tj.relative_to(REPO)}: parse error: {e}")
            continue
        for task in data.get("tasks", []):
            tid = task.get("task_id", "?")
            for f in task.get("files_owned", []):
                if f in owned:
                    errors.append(f"file double-owned: {f} by {owned[f]} and {tid}")
                owned[f] = tid
                owned_ctx[f] = ctx_dir
                if not (REPO / f).exists():
                    errors.append(f"dangling spec: task {tid} owns missing file {f}")
    return owned, owned_ctx, errors


def _spec_hash(ctx_dir: str) -> str:
    """Hash only the SEMANTIC content of a context's spec (REQ-704): requirement
    statements + Gherkin structure. Cosmetic prose/comment edits do not change it,
    so they cannot suppress a real code-drift signal."""
    d = REPO / "spec" / ctx_dir
    h = hashlib.sha256()
    rq = d / "requirements.md"
    if rq.exists():
        for line in rq.read_text().splitlines():
            s = line.strip()
            if _REQ_LINE.match(s):
                h.update(s.encode())
    acc = d / "acceptance"
    if acc.is_dir():
        for feat in sorted(acc.glob("*.feature")):
            for line in feat.read_text().splitlines():
                s = line.strip()
                if _GHERKIN_LINE.match(s):
                    h.update(s.encode())
    return h.hexdigest()


def _current_hashes(owned: dict, owned_ctx: dict) -> dict:
    governed_files = set(owned) | set(safety_files())
    governed = {f: _sha(REPO / f) for f in sorted(governed_files)}
    specs = {c: _spec_hash(c) for c in sorted(set(owned_ctx.values()))}
    return {"governed": governed, "specs": specs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update-manifest", action="store_true",
                    help="re-stamp spec/.lockstep.lock with current content hashes")
    args = ap.parse_args()

    owned, owned_ctx, errors = _collect()
    for sc in safety_files():
        if sc not in owned:
            errors.append(f"unspec'd safety-critical file: {sc} (add a spec task that owns it)")

    cur = _current_hashes(owned, owned_ctx)

    if args.update_manifest:
        if errors:
            print(f"FAIL: refusing to stamp manifest over {len(errors)} structural issue(s):")
            for e in errors:
                print(f"  - {e}")
            return 1
        MANIFEST.write_text(json.dumps(cur, indent=2, sort_keys=True) + "\n")
        print(f"manifest updated: {len(cur['governed'])} governed files, "
              f"{len(cur['specs'])} contexts -> {MANIFEST.relative_to(REPO)}")
        return 0

    # content-aware drift detection
    if MANIFEST.is_file():
        try:
            man = json.loads(MANIFEST.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"unreadable manifest {MANIFEST.name}: {e}")
            man = None
        if man:
            for f, h in cur["governed"].items():
                mh = man.get("governed", {}).get(f)
                if mh is None or mh == h:
                    continue  # new file or unchanged
                ctx = owned_ctx.get(f)
                if ctx and man.get("specs", {}).get(ctx) == cur["specs"].get(ctx):
                    errors.append(
                        f"spec drift: governed file {f} changed but its specification "
                        f"(context {ctx}) was not updated — review its REQ/feature, then "
                        f"run check-spec-code-lockstep.py --update-manifest")
    else:
        print(f"note: no manifest at {MANIFEST.name}; drift detection skipped "
              f"(run --update-manifest to enable)")

    if errors:
        print(f"FAIL: {len(errors)} spec<->code lockstep issue(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"PASS: {len(owned)} spec-owned file(s) exist; {len(safety_files())} safety-critical "
          f"files spec-owned; {len(cur['governed'])} content hashes match manifest; no drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
