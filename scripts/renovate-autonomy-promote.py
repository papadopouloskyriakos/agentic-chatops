#!/usr/bin/env python3
"""
renovate-autonomy-promote.py — data-driven stage promotion/demotion for the Renovate MR Autonomy
staged rollout (Dim-5). Weekly cron. Reads the append-only audit record + the ladder/criteria from the
git-tracked config, and reads/writes the MUTABLE stage state ({stage, stage_since}) in a RUNTIME state
file under ~/gateway-state — NOT the git-tracked config — so a drift-sync of the config can't reset the
stage clock.

  PROMOTE (canary → expand → full) when, since the current stage began:
    live auto-merges >= min_auto_merges_at_stage AND rollbacks <= max_rollbacks_at_stage AND days >= min_days.
  DEMOTE (drop one rung) immediately if rollbacks_at_stage > max_rollbacks_at_stage.
  SEED stage_since on the first run (so days/rollback windows measure from a real epoch, not "now" each run).

--check (default) reports only; --apply writes the state file. Never merges anything — only widens/narrows scope.
"""
import argparse
import json
import os
import sqlite3
import time

DEF_CFG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "renovate-autonomy-rollout.json")
DEF_STATE = os.path.expanduser("~/gateway-state/renovate-rollout-state.json")


def counts(db, since):
    a = r = 0
    try:
        c = sqlite3.connect(db, timeout=30)
        if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='renovate_autonomy_audit'").fetchone():
            a = c.execute("SELECT COUNT(*) FROM renovate_autonomy_audit "
                          "WHERE decision='AUTO' AND mode='live' AND ts>=?", (since,)).fetchone()[0]
            r = c.execute("SELECT COUNT(*) FROM renovate_autonomy_audit "
                          "WHERE decision='POSTMERGE_ROLLBACK' AND ts>=?", (since,)).fetchone()[0]
        c.close()
    except Exception:
        pass
    return a, r


def write_state(path, stage, stage_since):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    json.dump({"stage": stage, "stage_since": stage_since}, open(tmp, "w"), indent=2)
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.environ.get("RENOVATE_ROLLOUT_CONFIG", DEF_CFG))
    ap.add_argument("--state", default=os.environ.get("RENOVATE_ROLLOUT_STATE", DEF_STATE))
    ap.add_argument("--db", default=os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--now", type=int, default=None)
    a = ap.parse_args()

    cfg = json.load(open(a.config))
    now = a.now if a.now is not None else int(time.time())
    ladder = cfg["promotion"]["ladder"]
    stages = [s["stage"] for s in ladder]
    p = cfg["promotion"]

    state = {}
    if os.path.exists(a.state):
        try:
            state = json.load(open(a.state))
        except Exception:
            state = {}
    cur = state.get("stage", cfg.get("stage", stages[0]))
    idx = stages.index(cur) if cur in stages else 0

    # SEED the clock on first run (no state yet) — seed-then-measure avoids the "since=now every run" deadlock.
    if "stage_since" not in state:
        if a.apply:
            write_state(a.state, cur, now)
        print(json.dumps({"stage": cur, "decision": "seeded-stage-since", "stage_since": now}))
        return
    since = int(state["stage_since"])

    am, rb = counts(a.db, since)
    days = (now - since) / 86400.0
    decision, target_idx = "hold", idx
    if rb > p["max_rollbacks_at_stage"] and idx > 0:
        decision, target_idx = "demote", idx - 1
    elif (am >= p["min_auto_merges_at_stage"] and rb <= p["max_rollbacks_at_stage"]
          and days >= p["min_days_at_stage"] and idx < len(ladder) - 1):
        decision, target_idx = "promote", idx + 1

    report = {"stage": cur, "auto_merges": am, "rollbacks": rb, "days_at_stage": round(days, 2),
              "decision": decision, "target_stage": stages[target_idx]}
    if a.apply and target_idx != idx:
        write_state(a.state, stages[target_idx], now)
        report["applied"] = True
    print(json.dumps(report))


if __name__ == "__main__":
    main()
