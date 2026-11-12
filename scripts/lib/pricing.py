#!/usr/bin/env python3
"""Single source of truth for LLM token pricing (USD).

Audit remediation IFRNLLEI01PRD-1080 (2026-06-16): token rates were duplicated
and INCONSISTENT across the codebase — Anthropic Haiku output was priced $4/M in
llm-judge.sh + build-investigation-plan.sh (stale Haiku-3.5 card) but $5/M in
ragas-eval.py + run-hard-eval.py (current Haiku-4.5). This module is the ONE rate
card; every cost calculation imports it so a price change is a one-line edit and
the ledger can never silently diverge again.

Rates are USD per 1,000,000 tokens (Anthropic published list pricing). Standard
prompt-cache multipliers: cache-write = 1.25x base input (5-min), cache-read =
0.10x base input. Local Ollama models are $0 marginal (self-hosted on gpu01).

Importable:
    from pricing import cost_usd
    c = cost_usd("claude-haiku-4-5-20251001", in_tok, out_tok, cache_write, cache_read)

CLI (for shell callers):
    python3 pricing.py <model> <in> <out> [cache_write] [cache_read]   # prints USD
"""
from __future__ import annotations

import sys

# USD per 1,000,000 tokens, by model family.
RATES = {
    "claude-opus":   {"in": 15.0, "out": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet": {"in": 3.0,  "out": 15.0, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-haiku":  {"in": 1.0,  "out": 5.0,  "cache_write": 1.25,  "cache_read": 0.10},
    # Local Ollama / self-hosted — $0 marginal.
    "local":         {"in": 0.0,  "out": 0.0,  "cache_write": 0.0,   "cache_read": 0.0},
}


def family(model: str) -> str:
    """Map a concrete model id (claude-haiku-4-5-20251001, gemma3:12b, ...) to a
    rate-card family. Unknown / local models fall back to the $0 local card so a
    local-model token count never fabricates a dollar cost."""
    m = (model or "").lower()
    if "opus" in m:
        return "claude-opus"
    if "sonnet" in m:
        return "claude-sonnet"
    if "haiku" in m:
        return "claude-haiku"
    return "local"


def rate(model: str) -> dict:
    return RATES[family(model)]


def cost_usd(model: str, in_tok: int = 0, out_tok: int = 0,
             cache_write_tok: int = 0, cache_read_tok: int = 0) -> float:
    """USD cost for a single API call. NEVER returns EUR — the ledger column is
    cost_usd and must hold USD (IFRNLLEI01PRD-1080)."""
    r = rate(model)
    return (
        in_tok * r["in"]
        + out_tok * r["out"]
        + cache_write_tok * r["cache_write"]
        + cache_read_tok * r["cache_read"]
    ) / 1_000_000.0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("usage: pricing.py <model> <in> <out> [cache_write] [cache_read]",
              file=sys.stderr)
        sys.exit(1)
    model = args[0]
    nums = [int(float(x)) for x in args[1:5]] + [0, 0, 0, 0]
    print(f"{cost_usd(model, nums[0], nums[1], nums[2], nums[3]):.6f}")
