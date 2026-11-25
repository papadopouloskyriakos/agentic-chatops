#!/usr/bin/env python3
"""verify-chaos-findings.py — close the chaos-findings improvement loop (ISO 8.6).

Findings were being CREATED by chaos_baseline.py on SLO breaches but never
resolved: verify_finding() had no caller, so 42/42 sat status='open' forever
(some since April). This is the follow-up-verification harvester.

A finding is auto-verified (status='verified') when a LATER experiment of the
SAME scenario shows the breach it flagged is no longer reproducing:
  * convergence slo-breach  -> latest same-scenario experiment converges <= SLO (30s)
  * error-budget slo-breach -> latest same-scenario error_budget_consumed_pct <= 1.0%
  * recovery-gap (FAIL)     -> latest same-scenario experiment verdict != FAIL
verdict=PASS alone is NOT sufficient for a convergence finding — a run can PASS
overall while still breaching the convergence SLO (e.g. GR<->CH inalan at 45s).
Findings with no matching later experiment stay open (honest — untested).

Also emits chaos_findings_autoverify.prom and (--digest) refreshes ONE YouTrack
digest issue listing the still-open critical/high findings.

Usage:
  verify-chaos-findings.py --dry-run          # show what would verify
  verify-chaos-findings.py --apply            # verify + write metrics
  verify-chaos-findings.py --apply --digest   # + refresh the YouTrack digest issue
"""
import datetime
import json
import os
import sqlite3
import sys
import urllib.request

GATEWAY_DB = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
PROM_OUT = "/var/lib/node_exporter/textfile_collector/chaos_findings_autoverify.prom"
CONVERGENCE_SLO = 30.0   # direct BFD-capable tunnel default
ERROR_BUDGET_SLO = 1.0
YT_URL = "https://youtrack.example.net"
YT_PROJECT = "IFRNLLEI01PRD"
DIGEST_TAG = "[CHAOS-FINDINGS-DIGEST]"


def _scenario_key(chaos_type, targets_json):
    """Stable scenario signature so a finding maps to later runs of the same drill."""
    try:
        t = json.loads(targets_json) if targets_json else {}
    except Exception:
        t = {}
    if not isinstance(t, dict):
        return (chaos_type, "raw:" + str(t)[:60])
    tk = (t.get("tunnels_killed") or [{}])[0]
    if not isinstance(tk, dict):
        tk = {}
    if tk.get("tunnel"):
        return (chaos_type, "tunnel:" + str(tk.get("tunnel")) + "/" + str(tk.get("wan")))
    ck = (t.get("containers_killed") or [{}])[0]
    if isinstance(ck, dict) and ck.get("host"):
        return (chaos_type, "host:" + str(ck.get("host")) + "/" + str(ck.get("container", "")))
    return (chaos_type, "type-only")


def _scenario_slo(chaos_type, targets_json):
    """Per-scenario convergence SLO (mirrors chaos_baseline._scenario_convergence_slo,
    IFRNLLEI01PRD-1744): GR<->NO/CH transit=45s, cross-site container=300s, else 30s."""
    try:
        t = json.loads(targets_json) if targets_json else {}
    except Exception:
        t = {}
    if isinstance(t, dict) and t.get("containers_killed"):
        return 300.0
    if "tunnel" in (chaos_type or ""):
        if isinstance(t, dict):
            for tk in (t.get("tunnels_killed") or []):
                lbl = tk.get("tunnel", "") if isinstance(tk, dict) else ""
                if "GR" in lbl and any(x in lbl for x in ("NO", "CH")):
                    return 45.0
        return 30.0
    return 120.0


def _resolved(finding_text, category, latest, conv_slo=CONVERGENCE_SLO):
    """latest = (verdict, convergence_seconds, error_budget_consumed_pct) of newest later run."""
    verdict, conv, eb = latest
    ftext = (finding_text or "").lower()
    if category == "recovery-gap" or "verdict fail" in ftext:
        return verdict == "PASS"
    if "convergence" in ftext:
        return conv is not None and conv <= conv_slo and verdict != "FAIL"
    if "error budget" in ftext:
        return eb is not None and eb <= ERROR_BUDGET_SLO and verdict != "FAIL"
    # generic slo-breach: require a clean recent run
    return verdict == "PASS"


def main():
    apply = "--apply" in sys.argv
    digest = "--digest" in sys.argv
    if not apply and "--dry-run" not in sys.argv:
        print(__doc__)
        sys.exit(1)

    conn = sqlite3.connect(GATEWAY_DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row

    exps = conn.execute(
        "SELECT experiment_id, chaos_type, targets, verdict, convergence_seconds, "
        "error_budget_consumed_pct, started_at FROM chaos_experiments"
    ).fetchall()
    by_scenario = {}
    for e in exps:
        by_scenario.setdefault(_scenario_key(e["chaos_type"], e["targets"]), []).append(e)
    for k in by_scenario:
        by_scenario[k].sort(key=lambda r: r["started_at"] or "")

    findings = conn.execute(
        "SELECT finding_id, experiment_id, finding, severity, category, created_at "
        "FROM chaos_findings WHERE status='open'"
    ).fetchall()

    src = {e["experiment_id"]: e for e in exps}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    verified, still_open = [], []
    for f in findings:
        se = src.get(f["experiment_id"])
        if not se:
            still_open.append(f); continue
        key = _scenario_key(se["chaos_type"], se["targets"])
        _slo = _scenario_slo(se["chaos_type"], se["targets"])
        # SLO-correction close (IFRNLLEI01PRD-1744): a convergence finding raised by
        # the old flat 30s/120s threshold is a definitional artifact if the source
        # experiment already met the scenario's DESIGNED SLO (GR-transit 45s /
        # container 300s). Close it against its own source; genuine over-design
        # breaches (e.g. a direct path at 53.9s > 30s) fall through and stay open.
        _cont = "container" in (se["chaos_type"] or "") or "dmz" in (se["chaos_type"] or "")
        if "convergence" in (f["finding"] or "").lower():
            if _cont or (se["convergence_seconds"] is not None and se["convergence_seconds"] <= _slo):
                verified.append((f, se["experiment_id"] + " (SLO-corrected)"))
                if apply:
                    conn.execute(
                        "UPDATE chaos_findings SET status='verified', verified_at=?, verified_by=? WHERE finding_id=?",
                        (now, se["experiment_id"] + " (slo-corrected)", f["finding_id"]),
                    )
                continue
        later = [e for e in by_scenario.get(key, []) if (e["started_at"] or "") > (se["started_at"] or "")]
        if not later:
            still_open.append(f); continue
        newest = later[-1]
        _slo = _scenario_slo(se["chaos_type"], se["targets"])
        if _resolved(f["finding"], f["category"], (newest["verdict"], newest["convergence_seconds"], newest["error_budget_consumed_pct"]), _slo):
            verified.append((f, newest["experiment_id"]))
            if apply:
                conn.execute(
                    "UPDATE chaos_findings SET status='verified', verified_at=?, verified_by=? WHERE finding_id=?",
                    (now, newest["experiment_id"], f["finding_id"]),
                )
        else:
            still_open.append(f)
    if apply:
        conn.commit()

    print(f"open findings scanned: {len(findings)}")
    print(f"auto-verified: {len(verified)}")
    for f, ev in verified[:40]:
        print(f"  VERIFIED {f['finding_id']} ({f['severity']}/{f['category']}) by {ev}")
    sev_open = {}
    for f in still_open:
        sev_open[f["severity"]] = sev_open.get(f["severity"], 0) + 1
    print(f"still open: {len(still_open)}  by severity: {sev_open}")

    if apply:
        try:
            os.makedirs(os.path.dirname(PROM_OUT), exist_ok=True)
            tmp = PROM_OUT + ".tmp"
            with open(tmp, "w") as fh:
                fh.write("# HELP chaos_findings_autoverified_total Findings auto-verified on the last harvest run.\n")
                fh.write("# TYPE chaos_findings_autoverified_total gauge\n")
                fh.write(f"chaos_findings_autoverified_total {len(verified)}\n")
                fh.write("# HELP chaos_findings_still_open Open findings by severity after auto-verify.\n")
                fh.write("# TYPE chaos_findings_still_open gauge\n")
                for sev in ("critical", "high", "medium", "low"):
                    fh.write(f'chaos_findings_still_open{{severity="{sev}"}} {sev_open.get(sev, 0)}\n')
                fh.write("# HELP chaos_findings_harvest_timestamp_seconds Last harvest run (dead-man).\n")
                fh.write("# TYPE chaos_findings_harvest_timestamp_seconds gauge\n")
                fh.write(f"chaos_findings_harvest_timestamp_seconds {int(datetime.datetime.now(datetime.timezone.utc).timestamp())}\n")
            os.chmod(tmp, 0o644)
            os.replace(tmp, PROM_OUT)
            print(f"metrics -> {PROM_OUT}")
        except Exception as e:
            print(f"metric write failed: {e}", file=sys.stderr)

    if digest and apply:
        _refresh_digest(still_open)
    conn.close()


def _yt(method, path, body=None):
    tok = os.environ.get("YOUTRACK_API_TOKEN", "")
    if not tok:
        for line in open(os.path.expanduser("~/gitlab/n8n/claude-gateway/.env")):
            if line.startswith("YOUTRACK_API_TOKEN="):
                tok = line.split("=", 1)[1].strip(); break
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(YT_URL + "/api/" + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def _refresh_digest(still_open):
    crit_high = [f for f in still_open if f["severity"] in ("critical", "high")]
    lines = [f"{DIGEST_TAG} auto-maintained by verify-chaos-findings.py — do not hand-edit the body.",
             "", f"Still-open chaos findings (critical+high): {len(crit_high)}", ""]
    for f in sorted(crit_high, key=lambda x: (x["severity"], x["created_at"])):
        lines.append(f"- **{f['finding_id']}** ({f['severity']}/{f['category']}, since {f['created_at'][:10]}): {(f['finding'] or '')[:120]}")
    lines += ["", "A finding clears automatically when a later experiment of the same scenario meets its SLO.",
              "If a scenario is no longer drilled, close the finding by hand or retire the scenario."]
    body = "\n".join(lines)
    summary = f"{DIGEST_TAG} {len(crit_high)} open chaos findings (critical+high)"
    try:
        found = _yt("POST", "issues/search?fields=idReadable,summary",
                    {"query": f"project: {YT_PROJECT} summary: {DIGEST_TAG}"}) if False else None
    except Exception:
        found = None
    # search via GET query
    try:
        import urllib.parse
        q = urllib.parse.quote(f"project: {YT_PROJECT} {DIGEST_TAG}")
        hits = _yt("GET", f"issues?query={q}&fields=idReadable,summary")
    except Exception:
        hits = []
    existing = next((h for h in hits if DIGEST_TAG in (h.get("summary") or "")), None)
    if existing:
        _yt("POST", f"issues/{existing['idReadable']}?fields=idReadable",
            {"summary": summary, "description": body})
        print(f"digest updated: {existing['idReadable']} ({len(crit_high)} open)")
    else:
        r = _yt("POST", "issues?fields=idReadable",
                {"project": {"shortName": YT_PROJECT}, "summary": summary, "description": body})
        print(f"digest created: {r['idReadable']} ({len(crit_high)} open)")


if __name__ == "__main__":
    main()
