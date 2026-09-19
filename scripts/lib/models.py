"""Central Anthropic model registry — single source of truth for model-id selection.

Bench IFRNLLEI01PRD-1422 dim-10 (future-readiness): the gateway pins the dated model id
`claude-haiku-4-5-20251001` in ~8 scripts, so adopting a newer model means hunting every
pin. This registry is the ONE place to bump a tier, and `check-model-provenance-drift.py`
reads from it so a straggler pin is flagged. Adopting a newer model stays a deliberate,
one-line change here — the system does NOT silently auto-adopt an unverified model.

REPRODUCIBILITY_PINS are intentionally frozen (calibration baselines / eval golden runs)
and MUST NOT be bumped — doing so invalidates the baseline they anchor.
"""

# Canonical current Anthropic model ids per tier (keep in lockstep with CLAUDE.md's
# model-id table). Bump a value here to adopt a newer model fleet-wide.
ANTHROPIC_MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
}

# Scripts whose model pin is FROZEN for reproducibility — excluded from "newer-model
# available" drift. Bumping these is a deliberate re-baselining, never automatic.
REPRODUCIBILITY_PINS = {
    "scripts/judge-calibration.py": "claude-haiku-4-5-20251001",
    "scripts/ragas-eval.py:EVAL_MODEL": "claude-haiku-4-5-20251001",
}

# Live model-SELECTION callers that SHOULD track the current registry id (the drift guard
# flags any of these pinning a value not in ANTHROPIC_MODELS.values()).
LIVE_SELECTION_CALLERS = [
    "scripts/screen-response.sh",
    "scripts/build-investigation-plan.sh",
    "scripts/llm-judge.sh",
]


def tier_for(model_id: str) -> str:
    """Map a concrete model id to its tier alias (haiku/sonnet/opus), or '' if unknown."""
    for tier, mid in ANTHROPIC_MODELS.items():
        if model_id == mid or model_id.startswith("claude-" + tier):
            return tier
    return ""


def current(tier: str) -> str:
    """Current canonical model id for a tier alias."""
    return ANTHROPIC_MODELS.get(tier, "")
