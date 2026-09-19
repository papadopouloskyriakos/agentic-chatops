"""gepa_generator.py — IFRNLLEI01PRD-1159 (roadmap Stage-0 "I8").

GEPA-style reflective prompt evolution layered on the A/B patcher (IFRNLLEI01PRD-645)
as the variant GENERATOR only. It removes the "only 3 hand-shaped arms" ceiling by
asking the model to reflect on a seed instruction and propose diverse mutations.

CRITICAL INVARIANTS (why this is safe to land):
  * GENERATE-ONLY. The Welch t-test + control arm in finalize-prompt-trials.py stays
    the SOLE promotion gate — GEPA never promotes a prompt. A bad variant simply
    loses the A/B test like any hand-authored one.
  * DORMANT BY DEFAULT. PROMPT_GEPA_ENABLED!=1 => callers use the hand-authored pool;
    this module is never invoked => byte-identical legacy behavior.
  * NO NEW DEPS / NO API KEY. Reflection runs via `claude -p` (the Max-subscription
    CLI, $0), not the Anthropic SDK and not dspy (operator decision 2026-06-21).
  * FAIL-SAFE. Any failure (claude -p missing, timeout, bad JSON, too few variants)
    returns None => the caller falls back to the hand-authored CANDIDATE_POOL.

Reward-hacking guard (the audit's key ask for a self-improving loop): GEPA should
only be ENABLED once a contamination-free held-out eval set exists
(scripts/build-gepa-eval-set.py, sessions before 2026-05-01). Until then the live
Welch t-test on real sessions is the gate; see docs/runbooks/prompt-patch-trials.md.
"""
from __future__ import annotations

import json
import os
import subprocess

ENABLED = os.environ.get("PROMPT_GEPA_ENABLED", "0") == "1"
MODEL = os.environ.get("PROMPT_GEPA_MODEL", "sonnet")  # generate-only + Welch-t-test-gated promotion =>
# Sonnet is a safe downgrade from the host-default Opus (a weak variant just loses the A/B, no operational
# harm). Set PROMPT_GEPA_MODEL=haiku to A/B cheaper, or "" to fall back to the bare claude -p default.
TIMEOUT_S = int(os.environ.get("PROMPT_GEPA_TIMEOUT_S", "90"))

# Mutation lenses the reflection is asked to span — diversity by construction.
LENSES = ["concise", "detailed", "worked-examples", "formalize-checklist", "add-caveats"]


def _reflection_prompt(dim: str, seed: str, n: int) -> str:
    lenses = ", ".join(LENSES[:n])
    return (
        "You are improving ONE instruction line that is injected into an infrastructure "
        "incident-triage agent's system prompt. Reflect on the seed instruction for the "
        f"`{dim}` dimension, then propose {n} DIVERSE rewrites — each a different lens "
        f"({lenses}) — that could score higher WITHOUT changing the agent's task or "
        "weakening safety. Each rewrite must be a single self-contained instruction line "
        "(no preamble, <= 320 chars), materially different from the others.\n\n"
        f"SEED INSTRUCTION ({dim}):\n{seed}\n\n"
        'Return ONLY a JSON array of objects, no prose: '
        '[{"label": "<short kebab label>", "instruction": "<the rewritten line>"}, ...]'
    )


def _run_claude(prompt: str) -> str | None:
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if MODEL:
        cmd += ["--model", MODEL]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=TIMEOUT_S, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout


def _extract_array(raw: str) -> list[dict] | None:
    """claude -p --output-format json wraps the reply; the reply text itself should
    contain our JSON array. Be liberal: try the whole thing, then the 'result' field,
    then the first [...] slice."""
    candidates_text = []
    raw = raw.strip()
    candidates_text.append(raw)
    try:
        wrapper = json.loads(raw)
        if isinstance(wrapper, dict):
            for k in ("result", "text", "content", "response"):
                v = wrapper.get(k)
                if isinstance(v, str):
                    candidates_text.append(v)
        elif isinstance(wrapper, list):
            return wrapper
    except json.JSONDecodeError:
        pass
    for text in candidates_text:
        s, e = text.find("["), text.rfind("]")
        if s != -1 and e != -1 and e > s:
            try:
                arr = json.loads(text[s:e + 1])
                if isinstance(arr, list):
                    return arr
            except json.JSONDecodeError:
                continue
    return None


def _dedupe(items: list[dict]) -> list[dict]:
    """Drop near-identical instructions (normalized) so we don't waste an arm."""
    seen, out = set(), []
    for it in items:
        instr = (it.get("instruction") or "").strip()
        key = " ".join(instr.lower().split())[:200]
        if not instr or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def evolve_candidates(dim: str, seed_instruction: str, n_variants: int = 3):
    """Return a list of prompt_patch_trial.Candidate objects, or None to signal the
    caller to fall back to the hand-authored pool. GENERATE-ONLY; never promotes."""
    if not ENABLED:
        return None
    if not seed_instruction or not seed_instruction.strip():
        return None
    raw = _run_claude(_reflection_prompt(dim, seed_instruction.strip(), max(n_variants, 3)))
    if raw is None:
        return None
    arr = _extract_array(raw)
    if not arr:
        return None
    arr = _dedupe([a for a in arr if isinstance(a, dict)])
    if len(arr) < n_variants:
        return None  # not enough diversity => fall back rather than ship a thin trial
    # Import here so a missing module never breaks import-time of callers.
    from lib.prompt_patch_trial import Candidate
    out = []
    for i, a in enumerate(arr[:n_variants]):
        label = (a.get("label") or f"gepa-{i}").strip()[:40]
        instr = (a.get("instruction") or "").strip()[:320]
        if not instr:
            return None
        out.append(Candidate(idx=i, label=f"gepa:{label}", instruction=instr,
                             category="gepa"))
    return out
