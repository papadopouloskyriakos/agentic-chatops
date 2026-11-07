#!/usr/bin/env python3
"""
renovate-structural-review.py — deterministic review gate for ROUTINE Renovate version bumps.

WHY (2026-07-07): the lane's review gate calls mr-review.sh (a full Claude Code review). For a
routine, provably-stateless dependency BUMP there is no code to review — the only question is
"does this diff change ONLY a version/tag/digest, and nothing else?". The Claude review is slow +
flaky in the n8n SSH context (the audit showed review_verdict EMPTY on every MR → REVIEW_OK=0 →
nothing ever auto-merged). This gives the routine tier a FAST, DETERMINISTIC verdict so the safe
stuff can actually auto-merge; elevated/critical/atlantis still go to the Claude review + POLL.

It emits the SAME REVIEW_JSON contract as mr-review.sh so it is a drop-in for the routine path:
  REVIEW_JSON:{"project":P,"mr":I,"verdict":"APPROVE|REQUEST_CHANGES","confidence":0.0-1.0,"reason":"..."}

APPROVE (confidence 0.96) ONLY IF every changed hunk is a pure version/tag/digest edit AND the files
are expected dependency-manifest shapes. ANY non-version change / unexpected file / added-or-removed
non-version line → REQUEST_CHANGES (→ falls back to human/Claude review). Fail CLOSED.

Usage:
  cat mr_changes.json | python3 renovate-structural-review.py --changes-json - --project 7 --iid 372
  python3 renovate-structural-review.py --project 7 --iid 372   # live fetch (needs GITLAB_TOKEN)
"""
from __future__ import annotations
import json, os, re, sys

# A "version-ish" token: semver (1.2.3, v1.2, 2025.3.148033), docker tag suffixes (-alpine, -gpu),
# sha256 digests, terraform constraints (~> 3.2.0, >= 1.0), chart versions. Broad on purpose — the
# safety comes from requiring the WHOLE line to be identical once versions are blanked.
_VER = re.compile(
    r"(@sha256:[0-9a-f]{64})"                     # docker digest
    r"|(~>\s*[0-9][\w.\-]*)"                       # terraform ~> constraint
    r"|([><=]=?\s*[0-9][\w.\-]*)"                  # >= / == constraints
    r"|(\bv[0-9]+(?:\.[0-9]+)*)"                   # v-prefixed: v8, v8.8, v1.2.3
    r"|([0-9]+\.[0-9]+(?:\.[0-9]+)*(?:[.\-][0-9A-Za-z][\w.\-]*)*)"  # dotted semver + suffixes (1.2.3-alpine, 2025.3.148033)
    r"|((?<=:)[0-9]+(?:-[a-z][\w.\-]*)?)",         # bare-int docker TAG only (immediately after ':', e.g. redis:8)
    re.IGNORECASE,
)
# NB (2026-07-07): the old final alternative `\bv?[0-9]+(?:\.[0-9]+)*…` matched a BARE integer anywhere → a
# numeric CONFIG edit (`replicas: 2→5`, `port: 8080→9090`) blanked identically both sides and was APPROVED as
# a "version bump". Now a lone integer only counts as a version when it is a docker TAG (immediately after `:`
# with no space — image refs are `redis:8`, config is `key: 8` WITH a space). So config-value edits differ
# after blanking → REQUEST_CHANGES, while single-int image tags (postgres:17→18) still auto-approve.
# Files that are legitimate dependency manifests (a version bump lives here). Anything else = suspicious.
_OK_FILE = re.compile(
    r"(^|/)(docker-compose\.ya?ml|compose\.ya?ml|Dockerfile[^/]*|Chart\.ya?ml|values\.ya?ml"
    r"|\.terraform\.lock\.hcl|[^/]+\.tf|requirements\.txt|package\.json|go\.mod|Cargo\.toml)$",
    re.IGNORECASE,
)


def _blank_versions(line: str) -> str:
    return _VER.sub("§V§", line).rstrip()


def review_changes(changes: list[dict]) -> dict:
    if not changes:
        return {"verdict": "REQUEST_CHANGES", "confidence": 0.0, "reason": "no changes/diff available"}
    bad_files, nonversion = [], []
    total_hunks = 0
    for ch in changes:
        path = ch.get("new_path") or ch.get("old_path") or ""
        if not _OK_FILE.search(path):
            bad_files.append(path)
            continue
        diff = ch.get("diff") or ""
        removed = [l[1:] for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
        added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        # Pure version bump ⇒ removed and added lines are identical once version tokens are blanked,
        # AND the same count (a line changed in place, none purely inserted/deleted).
        if len(removed) != len(added):
            nonversion.append(f"{path}: {len(removed)}-/{len(added)}+ (added/removed non-version line)")
            continue
        rblank = sorted(_blank_versions(l) for l in removed)
        ablank = sorted(_blank_versions(l) for l in added)
        if rblank != ablank:
            # find a representative offending pair for the reason
            diffset = set(rblank) ^ set(ablank)
            nonversion.append(f"{path}: non-version change {sorted(diffset)[:2]}")
            continue
        # and the version token actually changed (otherwise it's a no-op / weird diff)
        if removed and _blank_versions("".join(removed)) == "".join(removed):
            nonversion.append(f"{path}: no version token in the changed lines")
            continue
        total_hunks += len(removed)
    if bad_files:
        return {"verdict": "REQUEST_CHANGES", "confidence": 0.0,
                "reason": "non-manifest file(s) changed: " + ", ".join(bad_files[:5])}
    if nonversion:
        return {"verdict": "REQUEST_CHANGES", "confidence": 0.0,
                "reason": "not a pure version bump: " + " | ".join(nonversion[:5])}
    if total_hunks == 0:
        return {"verdict": "REQUEST_CHANGES", "confidence": 0.0, "reason": "no version-change hunks found"}
    return {"verdict": "APPROVE", "confidence": 0.96,
            "reason": f"pure version/tag/digest bump across {total_hunks} line(s) in manifest files only"}


def _fetch_changes(pid: str, iid: str) -> list[dict]:
    import ssl, urllib.request
    base = os.environ.get("GITLAB_ENDPOINT", "https://gitlab.example.net/api/v4")
    tok = os.environ.get("GITLAB_TOKEN", "")
    if not tok:
        sys.exit("GITLAB_TOKEN not set")
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(f"{base}/projects/{pid}/merge_requests/{iid}/changes",
                                 headers={"PRIVATE-TOKEN": tok})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.load(r).get("changes", [])


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--changes-json", help="path to a JSON {changes:[...]} or [...], or - for stdin")
    ap.add_argument("--project"); ap.add_argument("--iid")
    a = ap.parse_args()
    if a.changes_json:
        raw = sys.stdin.read() if a.changes_json == "-" else open(a.changes_json).read()
        obj = json.loads(raw)
        changes = obj.get("changes", obj) if isinstance(obj, dict) else obj
    elif a.project and a.iid:
        changes = _fetch_changes(a.project, a.iid)
    else:
        ap.error("need --changes-json or --project+--iid")
    res = review_changes(changes)
    res.update({"project": a.project, "mr": a.iid})
    print("REVIEW_JSON:" + json.dumps(res))
    return 0 if res["verdict"] == "APPROVE" else 0  # exit 0 always; the verdict is in the JSON


if __name__ == "__main__":
    sys.exit(main())
