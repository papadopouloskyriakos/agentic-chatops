#!/usr/bin/env python3
"""renovate-deferred-merge-processor.py — drive the Renovate timeout-to-auto queue.

Runs on a cron (hourly). For each PENDING deferred entry whose grace window has elapsed, it re-invokes
renovate-mr-gate.sh with RENOVATE_DEFERRED_ELAPSED=1 (which overrides the rollout-stage POLL for an
eligible, non-vetoed, reversible bump and merges through the SAME safety path: fresh tested snapshot +
independent floor + sha-pin + post-merge auto-rollback). Before invoking the gate it resolves obvious
terminal states cheaply (MR closed/merged/rebased/vetoed) and enforces a daily cap. Fail-safe: if EITHER
sentinel (~/gateway.renovate_autonomy, ~/gateway.renovate_timeout_auto) is absent it is a NO-OP.

The human is a break-glass here: veto by adding the veto_label to an MR or closing it. Nothing merges that
isn't eligible (secrets/majors are never queued) and every merge still passes every gate at merge time.
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))
REDACTED_a7b84d63novate_deferred as rd  # noqa: E402

DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
GATE = str(REPO / "scripts" / "renovate-mr-gate.sh")
CFG = REPO / "config" / "renovate-autonomy-rollout.json"
GITLAB_URL = os.environ.get("GITLAB_URL", "https://gitlab.example.net")
AUTONOMY_SENTINEL = Path(os.environ.get("RENOVATE_AUTONOMY_SENTINEL") or (Path.home() / "gateway.renovate_autonomy"))
TIMEOUT_SENTINEL = Path(os.environ.get("RENOVATE_TIMEOUT_SENTINEL") or (Path.home() / "gateway.renovate_timeout_auto"))


def _cfg():
    try:
        t = json.loads(CFG.read_text()).get("timeout_auto", {})
    except Exception:
        t = {}
    return (str(t.get("veto_label", "renovate-hold")),
            int(t.get("daily_cap", 5)),
            int(t.get("max_age_days", 7)),
            int(t.get("max_merges_per_run", 1)))


def _gl(path):
    tok = os.environ.get("GITLAB_TOKEN", "")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(f"{GITLAB_URL}/api/v4{path}", headers={"PRIVATE-TOKEN": tok})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.load(r)


def _labels(mr):
    return {(l["name"] if isinstance(l, dict) else l) for l in (mr.get("labels") or [])}


def main() -> int:
    force = "--force" in sys.argv  # test hook: bypass the sentinel guard (never set in cron)
    if not force and not (AUTONOMY_SENTINEL.exists() and TIMEOUT_SENTINEL.exists()):
        print("timeout-auto disarmed (a sentinel is absent) — no-op")
        return 0
    if "GITLAB_TOKEN" not in os.environ:
        # match the gate's env model — .env is not exported to a bare cron shell
        envfile = REPO / ".env"
        if envfile.exists():
            for line in envfile.read_text().splitlines():
                if line.startswith("GITLAB_TOKEN=") and "GITLAB_TOKEN" not in os.environ:
                    os.environ["GITLAB_TOKEN"] = line.split("=", 1)[1].strip()

    veto_label, daily_cap, max_age_days, per_run = _cfg()
    now = int(time.time())
    budget = max(0, daily_cap - rd.count_merged_today(DB, now))
    due = rd.list_due(DB, now)
    merged = superseded = vetoed = expired = retried = 0
    merged_this_run = 0   # pace merges: at most `per_run` per tick so N due entries drip out, not batch
    print(f"deferred-processor: {len(due)} due, daily_cap={daily_cap}, budget={budget}, per_run={per_run}")

    for e in due:
        pid, iid, sha = str(e["project_id"]), str(e["mr_iid"]), e["head_sha"]
        # expire stale entries (never surfaced/merged for too long) so they don't retry forever
        if now - int(e["created_ts"]) > max_age_days * 86400:
            rd.mark(DB, pid, iid, sha, "expired", "max-age", now)
            expired += 1
            continue
        try:
            mr = _gl(f"/projects/{pid}/merge_requests/{iid}")
        except Exception as ex:
            print(f"  !{iid}: fetch failed ({ex}) — leave pending"); continue
        state = mr.get("state")
        if state == "merged":
            rd.mark(DB, pid, iid, sha, "merged", "already-merged", now); merged += 1; continue
        if state in ("closed", "locked"):
            rd.mark(DB, pid, iid, sha, "vetoed", f"mr-{state}", now); vetoed += 1; continue
        if (mr.get("sha") or "") != sha:
            rd.mark(DB, pid, iid, sha, "superseded", "head-moved", now); superseded += 1; continue
        if veto_label in _labels(mr):
            rd.mark(DB, pid, iid, sha, "vetoed", f"label:{veto_label}", now); vetoed += 1; continue
        if budget <= 0 or merged_this_run >= per_run:
            print(f"  !{iid}: cap reached (run={merged_this_run}/{per_run}, day-budget={budget}) — hold for next run"); continue

        # elapsed → re-invoke the gate; it re-does CI/review/snapshot/floor and merges if all still hold.
        env = dict(os.environ, RENOVATE_DEFERRED_ELAPSED="1", RENOVATE_DEDUP_OFF="1", GATEWAY_DB=DB)
        try:
            out = subprocess.run(["bash", GATE, "--project", pid, "--iid", iid],
                                 env=env, capture_output=True, text=True, timeout=420).stdout
        except Exception as ex:
            print(f"  !{iid}: gate invocation failed ({ex}) — retry next run"); rd.bump_attempt(DB, pid, iid, sha); continue
        res = ""
        for ln in out.splitlines():
            if ln.startswith("RENOVATE_GATE_RESULT:"):
                res = ln[len("RENOVATE_GATE_RESULT:"):]
        try:
            j = json.loads(res)
        except Exception:
            j = {}
        if j.get("acted") == "merged" or j.get("decision") == "AUTO":
            merged += 1; budget -= 1; merged_this_run += 1
            print(f"  !{iid}: TIMEOUT-AUTO MERGED ({e.get('package')} {e.get('update_type')})")
        else:
            rd.bump_attempt(DB, pid, iid, sha)
            print(f"  !{iid}: not merged this cycle (decision={j.get('decision')} reason={j.get('acted')}) — retry")
            retried += 1

    print(f"deferred-processor done: merged={merged} vetoed={vetoed} superseded={superseded} "
          f"expired={expired} retried={retried}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
