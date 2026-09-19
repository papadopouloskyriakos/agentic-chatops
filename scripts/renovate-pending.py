#!/usr/bin/env python3
"""renovate-pending.py — the PULL review surface for the Renovate autonomy lane.

The operator is not reachable via Matrix/SMS, so instead of pushing pages nobody reads, this prints the
current state on demand (surfaced in-session by the agent, or run by the operator). Two buckets:

  SCHEDULED (timeout-auto)  — reversible bumps holding in the grace window; they auto-merge at the deadline
                              unless vetoed (add the veto_label / close the MR). No action needed.
  PARKED (needs YOU)        — open Renovate MRs that are NOT timeout-eligible: never_auto secret stores
                              (openbao/vault) and MAJOR data-migrating bumps. These never auto-merge; they
                              wait for an explicit decision (merge / close / hold).

Usage: renovate-pending.py [--project 7] [--json]
"""
from __future__ import annotations

import importlib.util
import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))
REDACTED_a7b84d63novate_deferred as rd  # noqa: E402

_spec = importlib.util.spec_from_file_location("classify_renovate_mr", REPO / "scripts" / "classify-renovate-mr.py")
_clf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_clf)

DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
GITLAB_URL = os.environ.get("GITLAB_URL", "https://gitlab.example.net")


def _gl(path):
    tok = os.environ.get("GITLAB_TOKEN", "")
    if not tok:
        ef = REPO / ".env"
        if ef.exists():
            for line in ef.read_text().splitlines():
                if line.startswith("GITLAB_TOKEN="):
                    tok = line.split("=", 1)[1].strip(); break
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(f"{GITLAB_URL}/api/v4{path}", headers={"PRIVATE-TOKEN": tok})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.load(r)


def _rel(ts):
    d = int(ts) - int(time.time())
    if d <= 0:
        return "now/overdue"
    h = d // 3600
    return f"~{h}h" if h < 48 else f"~{h // 24}d"


def main() -> int:
    project = "7"
    as_json = "--json" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--project" and i + 1 < len(sys.argv):
            project = sys.argv[i + 1]

    pend = {(str(r["project_id"]), str(r["mr_iid"]), r["head_sha"]): r for r in rd.list_pending(DB)}
    mrs = _gl(f"/projects/{project}/merge_requests?author_username=renovate-bot&state=opened&per_page=50")

    scheduled, parked = [], []
    for mr in sorted(mrs, key=lambda m: m["iid"]):
        iid, sha = str(mr["iid"]), mr.get("sha", "")
        try:
            full = _gl(f"/projects/{project}/merge_requests/{iid}/changes")
        except Exception:
            full = mr
        c = _clf.classify(full)
        row = {"iid": iid, "package": c["package"], "tier": c["tier"], "update_type": c["update_type"],
               "never_auto": c["never_auto"]}
        key = (project, iid, sha)
        if key in pend:
            row["deadline"] = pend[key]["deadline_ts"]
            row["merges_in"] = _rel(pend[key]["deadline_ts"])
            scheduled.append(row)
        elif rd.eligible(c["tier"], c["update_type"], c["never_auto"]):
            row["note"] = "eligible; will schedule once CI-green + review-APPROVE"
            scheduled.append(row)
        else:
            sig = " ".join(c.get("signals", []))
            if c["never_auto"]:
                why = ("secret-store engine" if "never-auto-engine:" in sig
                       else "Dockerfile — needs rebuild+redeploy" if "never-auto:dockerfile-needs-rebuild" in sig
                       else "atlantis-managed (plan review)" if "never-auto:atlantis-review-required" in sig
                       else "never-auto tier")
                row["reason"] = f"never_auto ({why})"
            else:
                row["reason"] = ("MAJOR data-migrating bump" if c["update_type"] == "major"
                                 else f"{c['tier']} — no timeout-auto (explicit decision)")
            parked.append(row)

    if as_json:
        print(json.dumps({"scheduled": scheduled, "parked": parked}, indent=2)); return 0

    print(f"=== Renovate autonomy — pending review (project {project}, {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z) ===")
    print(f"\nSCHEDULED (timeout-auto — no action needed, veto to stop):  {len(scheduled)}")
    for r in scheduled:
        when = f"merges {r['merges_in']}" if "merges_in" in r else r.get("note", "")
        print(f"  !{r['iid']:<5} {r['package']:<26} {r['tier']:<9} {r['update_type']:<11} {when}")
    print(f"\nPARKED (needs YOUR explicit call — merge / close / hold):    {len(parked)}")
    for r in parked:
        print(f"  !{r['iid']:<5} {r['package']:<26} {r['tier']:<9} {r['update_type']:<11} {r['reason']}")
    if not scheduled and not parked:
        print("  (nothing pending)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
