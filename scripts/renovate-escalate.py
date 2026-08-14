#!/usr/bin/env python3
"""
renovate-escalate.py — page the operator when the Renovate MR Autonomy lane POLLs (Dim-4).

A POLL is the fail-safe for every risky MR; if it notifies no one, the "human as circuit-breaker" is
fiction and the human is OUT of the loop. This makes the alarm real: multi-channel, best-effort, deduped.
  1. GitLab MR comment (reliable — uses GITLAB_TOKEN; deduped by head SHA via a hidden marker)
  2. SMS via the twilio bridge /alert-session (same path the incident lane uses)
  3. Matrix m.notice to #infra-nl-prod

--dry-run prints the channels it WOULD hit and sends nothing (used by shadow mode + tests).
Exit 0 if at least the MR comment succeeded (or dry-run); non-zero only on total failure.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _post(url, data, headers, method="POST", timeout=5):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return urllib.request.urlopen(req, context=CTX, timeout=timeout)


def mr_comment(gl_url, tok, project, iid, sha, body, dry):
    marker = f"<!-- renovate-autonomy-poll:{sha} -->"
    api = f"{gl_url}/api/v4/projects/{project}/merge_requests/{iid}"
    # dedup: skip if a POLL comment for this exact head SHA already exists
    try:
        existing = json.load(_post(f"{api}/notes?per_page=100", None,
                                   {"PRIVATE-TOKEN": tok}, method="GET"))
        if any(marker in (n.get("body") or "") for n in existing):
            return "deduped"
    except Exception:
        pass
    if dry:
        return "would-comment"
    payload = json.dumps({"body": f"{marker}\n{body}"}).encode()
    _post(f"{api}/notes", payload, {"PRIVATE-TOKEN": tok, "Content-Type": "application/json"})
    return "commented"


def sms(project, iid, tier, pkg, reason, dry):
    url = os.environ.get("AUTONOMY_SMS_URL", "http://127.0.0.1:9106/alert-session")
    if dry:
        return f"would-sms({url})"
    payload = json.dumps({
        "issue_id": f"renovate-{project}!{iid}",
        "summary": f"Renovate {tier} MR {pkg} needs a human decision ({reason})",
        "band": "POLL_PAUSE", "host": "", "risk_level": "high", "reason": "deviation",
    }).encode()
    try:
        _post(url, payload, {"Content-Type": "application/json"}, timeout=4).close()
        return "sms-sent"
    except Exception as e:
        return f"sms-failed:{e}"


def matrix(project, iid, sha, body, dry):
    hs = os.environ.get("MATRIX_HOMESERVER", "")
    tok = os.environ.get("MATRIX_CLAUDE_TOKEN", "")
    room = os.environ.get("MATRIX_ROOM_INFRA", "")
    if not (hs and tok and room):
        return "matrix-unconfigured"
    if not hs.startswith("http"):
        hs = "https://" + hs
    if dry:
        return f"would-matrix({room})"
    txn = f"renovate-{project}-{iid}-{sha[:8]}"
    url = f"{hs}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}"
    payload = json.dumps({"msgtype": "m.notice", "body": body}).encode()
    try:
        _post(url, payload, {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
              method="PUT").close()
        return "matrix-sent"
    except Exception as e:
        return f"matrix-failed:{e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--iid", required=True)
    ap.add_argument("--tier", default="")
    ap.add_argument("--package", default="")
    ap.add_argument("--sha", default="")
    ap.add_argument("--reason", default="poll")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    gl_url = os.environ.get("GITLAB_URL", "https://gitlab.example.net")
    tok = os.environ.get("GITLAB_TOKEN", "")
    web = f"{gl_url}/-/merge_requests/{a.iid}"
    body = (f"🤖 **Renovate MR Autonomy — POLL (human decision needed)**\n"
            f"Tier **{a.tier}**, `{a.package}`. The autonomy gate declined to auto-merge: **{a.reason}**.\n"
            f"Review the MR and merge/close manually, or fix the gate signal. ({web})")

    results = {}
    if tok:
        try:
            results["mr_comment"] = mr_comment(gl_url, tok, a.project, a.iid, a.sha, body, a.dry_run)
        except Exception as e:
            results["mr_comment"] = f"failed:{e}"
    results["sms"] = sms(a.project, a.iid, a.tier, a.package, a.reason, a.dry_run)
    results["matrix"] = matrix(a.project, a.iid, a.sha, body, a.dry_run)

    print("ESCALATED:" + json.dumps(results))
    ok = a.dry_run or results.get("mr_comment") in ("commented", "deduped")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
