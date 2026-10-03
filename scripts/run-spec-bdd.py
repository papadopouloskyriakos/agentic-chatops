#!/usr/bin/env python3
"""run-spec-bdd.py — execute the gateway's Gherkin acceptance specs (IFRNLLEI01PRD-1260, Round 2).

Closes the "Gherkin is decorative" gap: every scenario step is bound to a real assertion
and actually run. Dependency-free (no behave/pytest-bdd) so it runs in CI as-is.

Exit 0 if every scenario in every spec/*/acceptance/*.feature passes; 1 otherwise.
Override repo root with env GATEWAY_SPEC_REPO.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("GATEWAY_SPEC_REPO", str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(REPO / "spec" / "steps"))

import _core  # noqa: E402
import steps  # noqa: E402,F401  (importing registers the step definitions)


def main() -> int:
    features = sorted((REPO / "spec").rglob("acceptance/*.feature"))
    if not features:
        print("no .feature files found")
        return 1
    total_pass = total = 0
    all_failures: list[str] = []
    for f in features:
        p, t, fails = _core.run_feature(f)
        total_pass += p
        total += t
        all_failures += fails
        print(f"  [{p}/{t}] {f.relative_to(REPO)}")
    for x in all_failures:
        print(f"  FAIL: {x}")
    print(f"\n{total_pass}/{total} scenarios passed across {len(features)} feature file(s)")
    return 0 if (total_pass == total and not all_failures) else 1


if __name__ == "__main__":
    sys.exit(main())
