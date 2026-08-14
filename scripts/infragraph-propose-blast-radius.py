#!/usr/bin/env python3
"""infragraph-propose-blast-radius — Phase C proposal lane (IFRNLLEI01PRD-1041).

The system may ASK for suppression authority; only the operator GRANTS it.
A proposal is a control YouTrack issue + a pending row in openclaw_memory
(category='infragraph-proposal'). NOTHING is suppressed until the operator
approves — approval moves the row to category='blast-radius' keyed by the
control issue id, at which point the EXISTING tier1_suppression.py Phase 1b
machinery enforces it (active while the control issue is open; closing the
issue instantly deactivates — unchanged semantics, zero hot-path code).

Modes:
  --scan        propose from recorded predictions (last 24h) whose cascade
                has >= MIN_CHILDREN rule-level children at conf >= 0.8.
  --bootstrap   propose standing rules from the graph itself: the top-K
                widest parents whose downstream edges carry conf >= 0.8
                expected_alerts. This is what lets the operator activate
                meaningful suppression on day one.
  --list        show pending + active proposals.
  --approve ID  operator grant: move pending proposal -> active Phase 1b rule.
  --reject ID   discard a pending proposal (control issue should be closed).

Every generated rule carries "generated_by": "infragraph" so the weekly
audit-risk-decisions.sh and rollback runbooks can find them.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import ssl
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))

from lib import infragraph  # noqa: E402
try:
    import mutation_mode  # noqa: E402 - MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:  # noqa: BLE001
    mutation_mode = None

MIN_CHILDREN = int(os.environ.get("INFRAGRAPH_PROPOSE_MIN_CHILDREN", "3"))
MIN_CONF = float(os.environ.get("INFRAGRAPH_PROPOSE_MIN_CONF", "0.8"))
BOOTSTRAP_TOP_K = int(os.environ.get("INFRAGRAPH_PROPOSE_TOP_K", "3"))
YT_PROJECT = os.environ.get("INFRAGRAPH_PROPOSE_PROJECT", "IFRNLLEI01PRD")

# Autonomous fold (IFRNLLEI01PRD-1040, set live at precision 0.80 on 2026-06-24).
# A proposed blast-radius rule auto-approves ONLY while BOTH hold: the operator
# sentinel exists AND a FRESH scorecard reports the fold-gate met. Both fail-safe
# to manual --approve. rm the sentinel = instant kill. INFRAGRAPH_AUTOFOLD_DISABLED=1
# also forces manual. Folding = dedup only; never-auto-resolve floor is unchanged.
AUTOFOLD_SENTINEL = os.path.expanduser("~/gateway.infragraph_autofold")
SCORECARD_PATH = os.environ.get(
    "INFRAGRAPH_SCORECARD",
    os.path.join(SCRIPT_DIR, "..", "test-results", "infragraph-scorecard.json"))
AUTOFOLD_MAX_SCORECARD_AGE_S = 8 * 86400  # stale gate -> no auto-approve (fail-safe)


def _autofold_authorized() -> tuple[bool, str]:
    """True only if the operator sentinel exists AND a fresh scorecard reports the
    fold-gate met. Fail-CLOSED: any miss/staleness/error -> (False, reason)."""
    if os.environ.get("INFRAGRAPH_AUTOFOLD_DISABLED", "") == "1":
        return False, "INFRAGRAPH_AUTOFOLD_DISABLED=1"
    if not os.path.exists(AUTOFOLD_SENTINEL):
        return False, "sentinel ~/gateway.infragraph_autofold absent"
    try:
        age = time.time() - os.stat(SCORECARD_PATH).st_mtime
        if age > AUTOFOLD_MAX_SCORECARD_AGE_S:
            return False, f"scorecard stale ({age/86400:.1f}d) — fail-safe"
        with open(SCORECARD_PATH) as fh:
            sc = json.load(fh)
        gate = (sc.get("scorecard", sc) or {}).get("gate_b_to_c", {})
        fc = gate.get("fold_candidate", {})
        if fc.get("all_met_fold"):
            return True, f"fold-gate MET (precision {fc.get('precision_fold_family')})"
        return False, "fold-gate not met (NO-GO)"
    except Exception as exc:  # noqa: BLE001 — fail-safe to manual
        return False, f"scorecard read error ({type(exc).__name__}) — fail-safe"


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yt_creds() -> tuple[str, str]:
    url = os.environ.get("YOUTRACK_URL", "https://youtrack.example.net")
    token = os.environ.get("YOUTRACK_API_TOKEN", "")
    if not token:
        try:
            with open(os.path.expanduser("~/gitlab/n8n/claude-gateway/.env"),
                      encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("YOUTRACK_API_TOKEN="):
                        token = line.split("=", 1)[1].strip()
        except FileNotFoundError:
            pass
    return url, token


def _yt_create_issue(summary: str, description: str) -> str:
    if mutation_mode and mutation_mode.is_shadow():
        mutation_mode.log_wouldve("infragraph-yt-issue", rationale="would create a blast-radius proposal issue",
                                  summary=summary[:120])
        return "SHADOW-NOT-CREATED"  # MUTATIONS=OFF: log the proposal, do not create the YouTrack issue
    url, token = _yt_creds()
    if not token:
        raise RuntimeError("no YOUTRACK_API_TOKEN")
    req = urllib.request.Request(
        f"{url}/api/issues?fields=idReadable",
        data=json.dumps({
            "project": {"shortName": YT_PROJECT},
            "summary": summary,
            "description": description,
        }).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        return json.load(resp)["idReadable"]


def _candidate_rule(conn, parent: str) -> dict | None:
    """Build a Phase 1b rule candidate from the graph for `parent`."""
    preds, window = infragraph.expected_cascade(conn, parent, depth=2)
    strong = [p for p in preds if (p.get("confidence") or 0) >= MIN_CONF]
    if len(strong) < MIN_CHILDREN:
        return None
    hosts = sorted({p["host"] for p in strong})
    rules = sorted({p["rule"] for p in strong})
    return {
        "hosts": hosts,
        "host_patterns": [],
        "rules": [r + "*" if not r.endswith("*") else r for r in rules],
        "description": (f"Infragraph-generated blast radius for {parent}: "
                        f"{len(strong)} high-confidence downstream alert(s) "
                        f"within {window}s"),
        "started_at": _utcnow(),
        "generated_by": "infragraph",
        "parent_host": parent,
        "evidence": [
            {"host": p["host"], "rule": p["rule"], "confidence": p["confidence"],
             "source": p["source"], "observations": p.get("observations", 0)}
            for p in strong[:12]
        ],
    }


def _pending_exists(conn, parent: str) -> bool:
    for cat in ("infragraph-proposal", "blast-radius"):
        rows = conn.execute(
            "SELECT value FROM openclaw_memory WHERE category=?", (cat,)
        ).fetchall()
        for r in rows:
            try:
                if json.loads(r["value"]).get("parent_host") == parent:
                    return True
            except (json.JSONDecodeError, TypeError):
                continue
    return False


def _store_pending(conn, key: str, rule: dict) -> None:
    conn.execute(
        "INSERT INTO openclaw_memory (category, key, value, issue_id) "
        "VALUES ('infragraph-proposal', ?, ?, ?)",
        (key, json.dumps(rule, ensure_ascii=False), key))
    conn.commit()


def _proposal_description(rule: dict) -> str:
    ev = "\n".join(
        f"| {e['host']} | {e['rule']} | {e['confidence']} | {e['source']} | {e['observations']} |"
        for e in rule["evidence"])
    return f"""## Infragraph blast-radius rule PROPOSAL (operator approval required)

**THIS ISSUE IS THE CONTROL SWITCH.** While this issue is OPEN *and* the rule
is approved, matching alerts fold into it as dedup (tier1 Phase 1b, conf 0.90).
**Closing this issue instantly deactivates the rule.** Nothing is suppressed
until approval.

Parent: `{rule['parent_host']}` — machine-derived from the dependency graph
(IFRNLLEI01PRD-1041; per-rule operator approval per the 2026-06-09 decision).

### Rule (exact Phase 1b JSON)
```json
{json.dumps({k: rule[k] for k in ('hosts', 'host_patterns', 'rules', 'description', 'started_at', 'generated_by')}, indent=2, ensure_ascii=False)}
```

### Evidence (graph edges, conf >= {MIN_CONF})
| host | rule | confidence | source | observations |
|---|---|---|---|---|
{ev}

### To approve
```
python3 ~/gitlab/n8n/claude-gateway/scripts/infragraph-propose-blast-radius.py --approve <THIS-ISSUE-ID>
```
(or ask any gateway session to run it — your instruction IS the approval)

### To reject
Close this issue and run `--reject <THIS-ISSUE-ID>`.
"""


def propose(conn, parents: list[str], dry_run: bool, no_yt: bool) -> list[dict]:
    out = []
    for parent in parents:
        if _pending_exists(conn, parent):
            out.append({"parent": parent, "status": "already-proposed-or-active"})
            continue
        rule = _candidate_rule(conn, parent)
        if not rule:
            out.append({"parent": parent,
                        "status": f"below-threshold (<{MIN_CHILDREN} children at conf>={MIN_CONF})"})
            continue
        if dry_run:
            out.append({"parent": parent, "status": "dry-run", "rule": rule})
            continue
        if no_yt:
            key = f"pending-{parent}"
        else:
            key = _yt_create_issue(
                f"[INFRAGRAPH-PROPOSAL] blast-radius rule: {parent} "
                f"({len(rule['evidence'])} downstream alerts)",
                _proposal_description(rule))
        _store_pending(conn, key, rule)
        out.append({"parent": parent, "status": "proposed", "control_issue": key})
    return out


def scan_parents(conn) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT parent_host FROM infragraph_predictions
           WHERE created_at >= datetime('now', '-1 day')""").fetchall()
    return [r["parent_host"] for r in rows]


def bootstrap_parents(conn) -> list[str]:
    rows = conn.execute(
        """SELECT t.name AS parent, COUNT(*) AS n
           FROM infragraph_dynamics d
           JOIN graph_relationships r ON r.id = d.rel_id
           JOIN graph_entities s ON s.id = r.source_id
           JOIN graph_entities t ON t.id = r.target_id
           WHERE d.confidence >= ? AND d.expected_alerts != '[]'
             AND t.entity_type IN ('pve_node', 'network_device', 'vm')
           GROUP BY t.name ORDER BY n DESC LIMIT ?""",
        (MIN_CONF, BOOTSTRAP_TOP_K)).fetchall()
    return [r["parent"] for r in rows]


def cmd_approve(conn, key: str) -> dict:
    row = conn.execute(
        "SELECT id, value FROM openclaw_memory "
        "WHERE category='infragraph-proposal' AND key=? LIMIT 1", (key,)
    ).fetchone()
    if not row:
        return {"error": f"no pending proposal keyed {key!r}"}
    rule = json.loads(row["value"])
    phase1b = {k: rule[k] for k in ("hosts", "host_patterns", "rules",
                                    "description", "started_at")}
    phase1b["generated_by"] = "infragraph"
    # Preserve parent_host so _pending_exists() can see this now-active fold and
    # NOT re-propose the same parent on the next --scan (root cause of duplicate
    # proposals: pve02 re-proposed as -1731/-1733 while -1721 was already active,
    # because the active 'blast-radius' row had parent_host stripped). tier1's
    # _match_blast_radius ignores extra keys, so this is inert to suppression.
    if rule.get("parent_host"):
        phase1b["parent_host"] = rule["parent_host"]
    conn.execute(
        "INSERT INTO openclaw_memory (category, key, value, issue_id) "
        "VALUES ('blast-radius', ?, ?, ?)",
        (key, json.dumps(phase1b, ensure_ascii=False), key))
    conn.execute("DELETE FROM openclaw_memory WHERE id=?", (row["id"],))
    conn.commit()
    return {"approved": key, "rule_active_while_issue_open": True,
            "hosts": phase1b["hosts"], "rules": phase1b["rules"]}


def cmd_reject(conn, key: str) -> dict:
    n = conn.execute(
        "DELETE FROM openclaw_memory WHERE category='infragraph-proposal' AND key=?",
        (key,)).rowcount
    conn.commit()
    return {"rejected": key, "removed_rows": n}


def cmd_list(conn) -> dict:
    out = {"pending": [], "active_generated": []}
    for r in conn.execute(
            "SELECT key, value FROM openclaw_memory WHERE category='infragraph-proposal'"):
        v = json.loads(r["value"])
        out["pending"].append({"control_issue": r["key"],
                               "parent": v.get("parent_host"),
                               "hosts": len(v.get("hosts", []))})
    for r in conn.execute(
            "SELECT key, value FROM openclaw_memory WHERE category='blast-radius'"):
        try:
            v = json.loads(r["value"])
        except (json.JSONDecodeError, TypeError):
            continue
        if v.get("generated_by") == "infragraph":
            out["active_generated"].append({"control_issue": r["key"],
                                            "hosts": v.get("hosts", [])})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="infragraph-propose-blast-radius")
    ap.add_argument("--db", default=None)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--parent", default="", help="propose for one explicit parent host")
    ap.add_argument("--approve", default="")
    ap.add_argument("--reject", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-yt", action="store_true",
                    help="store pending row without creating a YT issue (QA)")
    args = ap.parse_args()

    conn = infragraph.get_db(args.db)
    try:
        if args.approve:
            report = cmd_approve(conn, args.approve)
        elif args.reject:
            report = cmd_reject(conn, args.reject)
        elif args.list:
            report = cmd_list(conn)
        else:
            parents: list[str] = []
            if args.parent:
                parents.append(args.parent)
            if args.scan:
                parents.extend(scan_parents(conn))
            if args.bootstrap:
                parents.extend(bootstrap_parents(conn))
            if not parents:
                ap.error("pick --scan / --bootstrap / --parent H / --approve / --reject / --list")
            seen: set[str] = set()
            parents = [p for p in parents if not (p in seen or seen.add(p))]
            report = {"proposals": propose(conn, parents, args.dry_run, args.no_yt)}
            # Autonomous fold (-1040, live 0.80): when the fold-gate is met AND the
            # operator sentinel is present, promote the just-proposed rules straight
            # to active. Fail-CLOSED: otherwise they stay pending for manual --approve.
            ok, why = (False, "dry-run") if args.dry_run else _autofold_authorized()
            report["autofold"] = {"authorized": ok, "reason": why}
            if ok:
                approved = []
                for p in report["proposals"]:
                    if p.get("status") == "proposed" and p.get("control_issue"):
                        res = cmd_approve(conn, p["control_issue"])
                        if "error" not in res:
                            approved.append(res["approved"])
                report["auto_approved"] = approved
    finally:
        conn.close()
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
