#!/usr/bin/env python3
"""
renovate-rollout.py — staged-rollout gate for the Renovate MR Autonomy lane (Dim-5).

Arming the lane (~/gateway.renovate_autonomy) makes it live, but this decides WHICH tiers may actually
auto-merge at the current stage and enforces a per-day rate cap — so arming starts a CANARY (routine
only, few/day), not all-tiers-at-once. renovate-mr-gate.sh calls this in the AUTO path:

  ALLOW                              → proceed to the floor re-check + merge
  POLL:tier-not-enabled(stage=…)     → demote to POLL and page (a human handles higher tiers pre-promotion)
  HOLD:rate-cap(<n>/<cap>)           → hold, do NOT page (throttle; re-evaluated on Renovate's next run)

Config (git-tracked = immutable POLICY): config/renovate-autonomy-rollout.json holds the ladder + criteria.
State (runtime = MUTABLE, NOT git-tracked): ~/gateway-state/renovate-rollout-state.json holds {stage,
stage_since}, written only by renovate-autonomy-promote.py — so a drift-sync of the tracked config cannot
reset the stage clock. The current stage's enabled_tiers/max are resolved from the ladder.

Usage: renovate-rollout.py --tier <routine|elevated|critical> [--db <gateway.db>]
Exit 0=ALLOW, 2=tier-not-enabled, 3=rate-cap.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

DEF_CFG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "renovate-autonomy-rollout.json")
DEF_STATE = os.path.expanduser("~/gateway-state/renovate-rollout-state.json")


def load_effective(cfg_path, state_path):
    """git-tracked policy (ladder + criteria) overlaid with the runtime stage from the state file."""
    cfg = json.load(open(cfg_path))
    stage = cfg.get("stage", cfg["promotion"]["ladder"][0]["stage"])
    if os.path.exists(state_path):
        try:
            st = json.load(open(state_path))
            stage = st.get("stage", stage)
        except Exception:
            pass
    rung = next((r for r in cfg["promotion"]["ladder"] if r["stage"] == stage),
                cfg["promotion"]["ladder"][0])
    return stage, rung.get("enabled_tiers", []), int(rung.get("max_auto_merges_per_day", 0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True)
    ap.add_argument("--db", default=os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db"))
    ap.add_argument("--config", default=os.environ.get("RENOVATE_ROLLOUT_CONFIG", DEF_CFG))
    ap.add_argument("--state", default=os.environ.get("RENOVATE_ROLLOUT_STATE", DEF_STATE))
    a = ap.parse_args()

    try:
        stage, enabled, cap = load_effective(a.config, a.state)
    except Exception:
        print("POLL:no-rollout-config")   # fail SAFE (nothing auto-merges) rather than open
        sys.exit(2)

    if a.tier not in enabled:
        print(f"POLL:tier-not-enabled(stage={stage},enabled={'+'.join(enabled) or 'none'})")
        sys.exit(2)

    start_of_day = int(time.time()) - (int(time.time()) % 86400)
    # Count today's live AUTO merges to enforce the daily cap. If the DB errors or the audit table is
    # missing we CANNOT verify the cap → fail CLOSED (POLL), never ALLOW. Previously this swallowed the
    # error and left n=0 → ALLOW, silently disabling the canary rate cap on a degraded/uninitialised DB.
    try:
        c = sqlite3.connect(a.db, timeout=30)
        c.execute("PRAGMA busy_timeout=30000")
        if not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='renovate_autonomy_audit'").fetchone():
            c.close()
            print("POLL:audit-table-missing")  # cannot verify daily cap → fail CLOSED
            sys.exit(2)
        # Exclude synthetic/test rows (convention: mr_iid >= 9000) from the daily cap. A test harness that
        # writes a mode='live' AUTO row into the live DB (e.g. RENOVATE_FORCE_LIVE / the 9998/9999 stubs run
        # against gateway.db) must NEVER consume real canary budget — otherwise a test steals a slot and a
        # genuine routine MR is wrongly HOLD:rate-cap'd. Real GitLab MR iids are small sequential integers
        # (project 7 is in the hundreds); 9000+ is reserved for synthetic fixtures. COALESCE(...,'0') makes a
        # NULL or non-numeric mr_iid count as REAL (cast→0 < 9000) so the exclusion can only ever DROP an
        # explicit 9000+ synthetic row — it can never fail-open by silently uncounting a real merge.
        n = c.execute("SELECT COUNT(*) FROM renovate_autonomy_audit "
                      "WHERE decision='AUTO' AND mode='live' AND ts >= ? "
                      "AND CAST(COALESCE(mr_iid,'0') AS INTEGER) < 9000", (start_of_day,)).fetchone()[0]
        c.close()
    except SystemExit:
        raise
    except Exception:
        print("POLL:cap-count-failed")  # DB locked/corrupt → cannot verify daily cap → fail CLOSED
        sys.exit(2)

    if n >= cap:
        print(f"HOLD:rate-cap({n}/{cap})")
        sys.exit(3)
    print("ALLOW")
    sys.exit(0)


if __name__ == "__main__":
    main()
