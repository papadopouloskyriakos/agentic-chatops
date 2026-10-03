#!/usr/bin/env python3
"""check-a2a-card-drift.py — make the A2A agent cards the authoritative single source of truth.

D14 (open-protocol interop, IFRNLLEI01PRD-1305). The agent cards (a2a/agent-cards/*.json) used
to be DECORATIVE — referenced only by health scripts, with their routing/policy/model duplicated
and drifting against the live system. The literal course fix ("routing reads the cards at runtime")
is infeasible here: n8n Code nodes run in a sandbox that cannot read files, and the live Derive
Slot routes issue->slot (rooms/cwd), which the cards do not describe. So instead of a runtime read,
this gate makes the cards AUTHORITATIVE by failing whenever the live system drifts from them:

  1. escalation-graph consistency — each card's escalateTo/delegatesTo target actually accepts/
     reviews from it (the A2A tier graph is internally coherent).
  2. approval policy is card-driven — the human-tier card's timeoutReminder/timeoutPause +
     authorizedSenders match what the live Matrix Bridge enforces.
  3. model provenance is current — every card's model is in the current-model set (no stale strings).

Exit 0 if the cards and the live system agree; 1 on drift. --json for machine output.
Override the repo root with GATEWAY_A2A_REPO (used by the QA negative test).
"""
from __future__ import annotations

import argparse
import json
import os
REDACTED_a7b84d63
import sys
from pathlib import Path

REPO = Path(os.environ.get("GATEWAY_A2A_REPO", str(Path(__file__).resolve().parents[1])))
CARDS_DIR = REPO / "a2a" / "agent-cards"
BRIDGE = REPO / "workflows" / "claude-gateway-matrix-bridge.json"

# Current production models (keep in lockstep with docs/model-provenance.md). A card model
# outside this set is stale drift (the exact class fixed in IFRNLLEI01PRD-1305 part d).
CURRENT_MODELS = {
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-cli/claude-sonnet-4-6",
}

# Map a card filename -> the short agent name used inside routing blocks.
_FILE_TO_AGENT = {
    "claude-code-t2": "claude-code",
    "openclaw-t1": "openclaw",
    "human-t3": "human",
}
# routing references that are external (not cards) — allowed targets that need no card.
_EXTERNAL = {"alert-pipeline"}


def _load_cards() -> dict[str, dict]:
    cards: dict[str, dict] = {}
    for f in sorted(CARDS_DIR.glob("*.json")):
        agent = _FILE_TO_AGENT.get(f.stem, f.stem)
        try:
            cards[agent] = json.loads(f.read_text()).get("_nla2a", {})
        except json.JSONDecodeError as e:
            cards[agent] = {"__parse_error__": str(e)}
    return cards


def check_escalation_graph(cards: dict[str, dict]) -> list[str]:
    errs: list[str] = []
    known = set(cards) | _EXTERNAL
    for agent, nla in cards.items():
        if "__parse_error__" in nla:
            errs.append(f"{agent}: card parse error: {nla['__parse_error__']}")
            continue
        routing = nla.get("routing", {})
        # every referenced agent must exist (card or external)
        refs = []
        for k in ("escalateTo", "acceptsFrom", "delegatesTo", "reviewsFor"):
            v = routing.get(k)
            refs += ([v] if isinstance(v, str) else (v or []))
        for r in refs:
            if r and r not in known:
                errs.append(f"{agent}.routing references unknown agent '{r}'")
        # escalateTo target must accept from this agent
        esc = routing.get("escalateTo")
        if esc and esc in cards:
            tgt = cards[esc].get("routing", {}).get("acceptsFrom", []) or []
            if agent not in tgt:
                errs.append(f"{agent} escalateTo '{esc}', but {esc}.acceptsFrom does not include '{agent}'")
        # delegatesTo target must accept OR review from this agent
        for d in (routing.get("delegatesTo") or []):
            if d in cards:
                tr = cards[d].get("routing", {})
                if agent not in (tr.get("acceptsFrom") or []) and agent not in (tr.get("reviewsFor") or []):
                    errs.append(f"{agent} delegatesTo '{d}', but {d} neither acceptsFrom nor reviewsFor '{agent}'")
    return errs


def check_approval_policy(cards: dict[str, dict]) -> list[str]:
    errs: list[str] = []
    human = cards.get("human", {})
    pol = human.get("approvalPolicy")
    if not pol:
        return ["human card has no approvalPolicy block"]
    if not BRIDGE.is_file():
        return [f"matrix bridge not found at {BRIDGE.name} — cannot verify approval policy is card-driven"]
    bridge_txt = BRIDGE.read_text()
    for field, val in (("timeoutReminder", pol.get("timeoutReminder")),
                       ("timeoutPause", pol.get("timeoutPause"))):
        if val is not None and str(val) not in bridge_txt:
            errs.append(f"approval drift: human card {field}={val} not found in the live Matrix Bridge")
    for sender in (pol.get("authorizedSenders") or []):
        if sender not in bridge_txt:
            errs.append(f"approval drift: human card authorizedSender '{sender}' not enforced by the live Bridge")
    return errs


def check_model_provenance(cards: dict[str, dict]) -> list[str]:
    errs: list[str] = []
    for agent, nla in cards.items():
        model = nla.get("model")
        if model is None:
            continue  # e.g. human tier has no model
        if model not in CURRENT_MODELS:
            errs.append(f"stale model on {agent} card: '{model}' not in current set {sorted(CURRENT_MODELS)}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not CARDS_DIR.is_dir():
        print(f"FAIL: no agent cards at {CARDS_DIR}")
        return 1
    cards = _load_cards()
    results = {
        "escalation_graph": check_escalation_graph(cards),
        "approval_policy": check_approval_policy(cards),
        "model_provenance": check_model_provenance(cards),
    }
    all_errs = [e for v in results.values() for e in v]

    if args.json:
        print(json.dumps({"cards": list(cards), "drift": all_errs,
                          "by_check": results, "ok": not all_errs}, indent=2))
    elif all_errs:
        print(f"FAIL: {len(all_errs)} A2A card<->live drift issue(s):")
        for e in all_errs:
            print(f"  - {e}")
    else:
        print(f"PASS: {len(cards)} agent cards are the authoritative source — escalation graph "
              f"coherent, approval policy card-driven, models current; no drift")
    return 0 if not all_errs else 1


if __name__ == "__main__":
    sys.exit(main())
