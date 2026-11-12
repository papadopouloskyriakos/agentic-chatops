"""Dependency-free BDD core for the gateway spec (IFRNLLEI01PRD-1260, Round 2).

Closes the "Gherkin is decorative" gap: scenarios are now EXECUTED, each step bound
to a real assertion. An unbound step is a hard failure, so no scenario step can be
cosmetic. No behave/pytest-bdd dependency — runs in CI's python:3.12-slim as-is.
"""
from __future__ import annotations

REDACTED_a7b84d63
from pathlib import Path

REGISTRY: list[tuple[re.Pattern, object]] = []  # (pattern, func)


def step(pattern: str):
    rx = re.compile(pattern)

    def deco(fn):
        REGISTRY.append((rx, fn))
        return fn

    return deco


_KEYWORD = re.compile(r"^\s*(Given|When|Then|And|But|\*)\s+(.*\S)\s*$")


def _strip_keyword(line: str):
    m = _KEYWORD.match(line)
    return m.group(2) if m else None


def parse_feature(text: str) -> list[tuple[str, list[str]]]:
    """Return [(scenario_name, [step_text, ...]), ...]."""
    scenarios: list[tuple[str, list[str]]] = []
    cur: tuple[str, list[str]] | None = None
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("@") or s.startswith("Feature:"):
            continue
        if re.match(r"^(Scenario|Scenario Outline):", s):
            cur = (s.split(":", 1)[1].strip(), [])
            scenarios.append(cur)
            continue
        st = _strip_keyword(s)
        if st is not None and cur is not None:
            cur[1].append(st)
    return scenarios


def match_step(step_text: str):
    for rx, fn in REGISTRY:
        m = rx.search(step_text)
        if m:
            return fn, m
    return None, None


def run_feature(path: Path) -> tuple[int, int, list[str]]:
    """Run every scenario in one .feature. Return (passed, total, failures)."""
    scenarios = parse_feature(Path(path).read_text())
    failures: list[str] = []
    passed = 0
    for name, steps in scenarios:
        ctx: dict = {}
        ok = True
        for st in steps:
            fn, m = match_step(st)
            if fn is None:
                failures.append(f"{Path(path).name} :: {name} :: UNBOUND step: '{st}'")
                ok = False
                break
            try:
                fn(ctx, *m.groups())
            except AssertionError as e:
                failures.append(f"{Path(path).name} :: {name} :: FAILED at '{st}': {e}")
                ok = False
                break
            except Exception as e:  # noqa: BLE001
                failures.append(f"{Path(path).name} :: {name} :: ERROR at '{st}': {type(e).__name__}: {e}")
                ok = False
                break
        if ok:
            passed += 1
    return passed, len(scenarios), failures
