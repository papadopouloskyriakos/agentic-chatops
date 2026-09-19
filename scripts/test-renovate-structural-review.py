#!/usr/bin/env python3
"""Regression guard for renovate-structural-review.py — the deterministic routine-tier review.
APPROVE ⟺ every changed hunk is a pure version/tag/digest edit in a dependency-manifest file.
Run: python3 scripts/test-renovate-structural-review.py  (exit 0 = pass)."""
import importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sr = importlib.import_module("renovate-structural-review")


def ch(path, diff):
    return {"new_path": path, "diff": diff}


CASES = [
    # (changes, expected_verdict, note)
    ([ch("docker/h/svc/docker-compose.yml", "@@ -3 +3 @@\n-    image: alpine:3.21\n+    image: alpine:3.24\n")],
     "APPROVE", "pure docker tag bump"),
    ([ch("docker/h/immich/docker-compose.yml",
         "@@ -5 +5 @@\n-    image: docker.io/redis:8.4-alpine@sha256:" + "4" * 64 + "\n+    image: docker.io/redis:8.8-alpine@sha256:" + "9" * 64 + "\n")],
     "APPROVE", "digest bump"),
    ([ch("k8s/_core/cilium/main.tf", '@@ -24 +24 @@\n-  version          = "1.18.4"\n+  version          = "1.19.5"\n')],
     "APPROVE", "helm version bump (structural only — atlantis gating is separate)"),
    ([ch("k8s/main.tf", '@@ -19 +19 @@\n-      version = "~> 3.1.0"\n+      version = "~> 3.2.0"\n')],
     "APPROVE", "terraform constraint bump"),
    # ── REQUEST_CHANGES: a non-version line changed alongside the version ──
    ([ch("docker/h/svc/docker-compose.yml",
         "@@ -3,2 +3,2 @@\n-    image: alpine:3.21\n-    restart: no\n+    image: alpine:3.24\n+    restart: always\n")],
     "REQUEST_CHANGES", "config line changed too — not a pure bump"),
    # ── REQUEST_CHANGES: a code/non-manifest file changed ──
    ([ch("scripts/deploy.sh", "@@ -1 +1 @@\n-echo old\n+echo new\n")],
     "REQUEST_CHANGES", "non-manifest file"),
    # ── REQUEST_CHANGES: pure insertion (added a whole new line, not an in-place bump) ──
    ([ch("docker/h/svc/docker-compose.yml", "@@ -3 +3,2 @@\n     image: alpine:3.21\n+    newkey: value\n")],
     "REQUEST_CHANGES", "added a non-version line"),
    ([], "REQUEST_CHANGES", "no changes"),
    # ── REGRESSION 2026-07-07: numeric NON-version manifest edits must NOT read as a version bump ──
    ([ch("k8s/svc/values.yaml", "@@ -1 +1 @@\n-  replicas: 2\n+  replicas: 5\n")],
     "REQUEST_CHANGES", "replica count is not a version"),
    ([ch("docker/h/svc/docker-compose.yml", "@@ -1 +1 @@\n-      - 8080:8080\n+      - 9090:9090\n")],
     "REQUEST_CHANGES", "port mapping is not a version"),
    ([ch("docker/h/svc/docker-compose.yml", "@@ -1 +1 @@\n-      MAX_CONNECTIONS: 100\n+      MAX_CONNECTIONS: 999\n")],
     "REQUEST_CHANGES", "numeric env value is not a version"),
    # ── and single-integer docker TAGS (postgres:17→18) must STILL auto-approve (no false-reject) ──
    ([ch("docker/h/svc/docker-compose.yml", "@@ -1 +1 @@\n-    image: postgres:17\n+    image: postgres:18\n")],
     "APPROVE", "single-int docker tag still a version"),
    ([ch("docker/h/svc/Dockerfile", "@@ -1 +1 @@\n-ARG UV_VERSION=0.11.26\n+ARG UV_VERSION=0.11.27\n")],
     "APPROVE", "dockerfile ARG *_VERSION bump"),
]


def main() -> int:
    fails = 0
    for changes, exp, note in CASES:
        r = sr.review_changes(changes)
        ok = r["verdict"] == exp
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {note:<52} got {r['verdict']}"
              + ("" if ok else f"  EXPECTED {exp}  ({r['reason'][:60]})"))
    # invariant: APPROVE ⇒ confidence high; REQUEST_CHANGES ⇒ 0
    allr = [sr.review_changes(c) for c, *_ in CASES]
    inv = all((r["confidence"] >= 0.9) == (r["verdict"] == "APPROVE") for r in allr)
    print(f"{'PASS' if inv else 'FAIL'}  INVARIANT: APPROVE ⟺ confidence≥0.9")
    fails += not inv
    print(f"\n{len(CASES)} cases, {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
