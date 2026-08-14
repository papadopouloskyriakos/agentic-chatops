#!/usr/bin/env python3
"""
Regression guard for scripts/classify-renovate-mr.py + config/renovate-stateful-services.json.

Codifies the labeled-corpus oracle discovered on 2026-07-06 during shadow validation:
- the DB majors the operator hand-DECLINED (mariadb v12 !91, postgres v18 !93) MUST land
  in tier=critical with a mandatory snapshot gate (they can never auto-merge without a
  verified restore point);
- stateless CI infra whose NAME merely contains a stateful token (gitlab-runner,
  gitlab-agent) must NOT be snapshot-gated;
- stateless majors (Terraform providers, base images) => elevated, no snapshot;
- any bump of a stateful service (even a minor/digest) => critical + snapshot;
- every critical carries 'snapshot_verified'; nothing else does.

Fixtures are the real GitLab MR metadata shapes (title/source_branch/labels) so the test
runs with no external corpus. Run: python3 scripts/test-renovate-classifier.py
Exit 0 = all pass; non-zero = a change broke the safety oracle.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib

clf = importlib.import_module("classify-renovate-mr")


def mr(iid, title, branch, labels, state="opened"):
    return {"iid": iid, "title": title, "source_branch": branch, "labels": labels, "state": state}


# (mr, expected_tier, expected_snapshot_required, note)
CASES = [
    # ── ORACLE: hand-declined DB majors — must be critical + snapshot ──────────
    (mr(91, "⚠️ [MAJOR] Update mariadb Docker tag to v12", "renovate/mariadb-12.x",
        ["major-update", "renovate"], "closed"), "critical", True, "declined DB major"),
    (mr(93, "⚠️ [MAJOR] Update postgres Docker tag to v18", "renovate/postgres-18.x",
        ["major-update", "renovate"], "closed"), "critical", True, "declined DB major"),
    # ── stateful non-major still snapshot-gated ───────────────────────────────
    (mr(130, "chore(deps): update milvusdb/milvus docker tag to v2.6.19",
        "renovate/milvusdb-milvus-2.x", ["renovate"]), "critical", True, "vector store minor"),
    (mr(251, "chore(deps): update docker.io/redis:8.4-alpine docker digest",
        "renovate/docker.io-redis-8.4-alpine", ["renovate"]), "critical", True, "redis digest"),
    (mr(129, "chore(deps): update jetbrains/youtrack docker tag to v2025.3",
        "renovate/jetbrains-youtrack-2025.x", ["renovate"]), "critical", True, "app-with-db"),
    # ── stateless CI infra containing a stateful token — NOT snapshot ──────────
    (mr(42, "🏗️ [INFRA] Update Helm release gitlab-runner to v0.83.1",
        "renovate/gitlab-runner-0.x", ["renovate"], "closed"), "routine", False, "runner != gitlab"),
    (mr(39, "🏗️ [INFRA] Update Helm release gitlab-agent to v2.28.0",
        "renovate/gitlab-agent-2.x", ["renovate"]), "routine", False, "agent != gitlab"),
    # ── stateless majors => elevated, no snapshot ─────────────────────────────
    (mr(131, "⚠️ [MAJOR] Update Terraform kubernetes to v3", "renovate/kubernetes-3.x",
        ["major-update", "renovate"]), "elevated", False, "tf provider major"),
    (mr(90, "⚠️ [MAJOR] Update ubuntu Docker tag to v24", "renovate/ubuntu-24.x",
        ["major-update", "renovate"]), "elevated", False, "base image major"),
    # ── stateless minor/patch => routine ──────────────────────────────────────
    (mr(2, "chore(deps): update nginx docker tag to v1.29", "renovate/nginx-1.x",
        ["renovate"]), "routine", False, "reverse proxy minor"),
    (mr(84, "chore(deps): update python docker tag", "renovate/python-3.x",
        ["renovate"]), "routine", False, "base image minor"),
    (mr(45, "🏗️ [INFRA] Update velero/velero to v1.18", "renovate/velero-velero-1.x",
        ["renovate"]), "routine", False, "backup binary"),
    # ── renovate config/onboarding MR => elevated (changes automation itself) ──
    (mr(1, "Configure Renovate", "renovate/configure", ["renovate"]), "elevated", False, "onboarding"),
    # ── FAIL CLOSED: an UNKNOWN engine (not in stateful NOR known-stateless) => critical+snapshot ──
    (mr(200, "chore(deps): update surrealdb docker tag to v2", "renovate/surrealdb-2.x",
        ["renovate"]), "critical", True, "unknown→fail-closed"),
    (mr(201, "chore(deps): update ferretdb docker tag", "renovate/ferretdb-1.x",
        ["renovate"]), "critical", True, "unknown→fail-closed"),
    # ── never-auto engine (secret store) => critical + never_auto ─────────────
    (mr(202, "chore(deps): update openbao/openbao docker tag", "renovate/openbao-openbao-2.x",
        ["renovate"]), "critical", True, "never-auto engine"),
    # ── REGRESSION 2026-07-07: a Helm RELEASE of a STATEFUL chart must be critical, not routine.
    # 'helm' used to be a known_stateless token, so the word "Helm" in an MR title flipped the whole
    # MR to routine → auto-mergeable (live exposure: !126 kube-prometheus-stack, the monitoring stack).
    (mr(126, "🏗️ [INFRA] Update Helm release kube-prometheus-stack to v79.12.0",
        "renovate/kube-prometheus-stack-79.x", ["renovate"]), "critical", True, "helm monitoring stack"),
    (mr(300, "🏗️ [INFRA] Update Helm release loki to v6", "renovate/loki-6.x",
        ["renovate"]), "critical", True, "helm log store"),
    (mr(301, "chore(deps): update prometheus docker tag to v3", "renovate/prometheus-3.x",
        ["renovate"]), "critical", True, "prometheus TSDB"),
    (mr(302, "chore(deps): update thanos docker tag", "renovate/thanos-0.x",
        ["renovate"]), "critical", True, "thanos store"),
    # ── genuinely stateless Helm charts still route routine (by CHART name, not the helm token) ──
    (mr(303, "🏗️ [INFRA] Update Helm release ingress-nginx to v4.12", "renovate/ingress-nginx-4.x",
        ["renovate"]), "routine", False, "helm stateless proxy chart"),
    (mr(304, "🏗️ [INFRA] Update Helm release cert-manager to v1.16", "renovate/cert-manager-1.x",
        ["renovate"]), "routine", False, "helm stateless controller chart"),
    # ── an UNRECOGNISED Helm chart now fails CLOSED to critical (no longer routine via 'helm') ──
    (mr(305, "🏗️ [INFRA] Update Helm release frobnicator to v2", "renovate/frobnicator-2.x",
        ["renovate"]), "critical", True, "helm unknown chart → fail-closed"),
    # ── unchanged: a Terraform PROVIDER bump (kubernetes/helm providers) stays elevated (stateless major) ──
    (mr(131, "⚠️ [MAJOR] Update Terraform helm to v3", "renovate/helm-3.x",
        ["major-update", "renovate"]), "elevated", False, "tf helm-provider major (not a release)"),
    # ── multi-word matcher (_ngram_hay): HYPHENATED allowlist/stateful entries now match (they never did
    # before — they only "worked" for helm MRs via the blanket 'helm' token). argo-cd → routine (stateless
    # controller), victoria-metrics → critical (stateful TSDB) ──
    (mr(306, "🏗️ [INFRA] Update Helm release argo-cd to v7", "renovate/argo-cd-7.x",
        ["renovate"]), "routine", False, "hyphenated stateless (argo-cd)"),
    (mr(307, "chore(deps): update victoria-metrics docker tag", "renovate/victoria-metrics-1.x",
        ["renovate"]), "critical", True, "hyphenated stateful (victoria-metrics)"),
]


def main() -> int:
    fails = 0
    for m, exp_tier, exp_snap, note in CASES:
        r = clf.classify(m)
        ok_tier = r["tier"] == exp_tier
        ok_snap = r["snapshot_required"] == exp_snap
        ok_inv = ("snapshot_verified" in r["required_gates"]) == (r["tier"] == "critical")
        ok = ok_tier and ok_snap and ok_inv
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  !{m['iid']:<4} {note:<20} "
              f"got tier={r['tier']} snap={r['snapshot_required']}"
              + ("" if ok else f"  EXPECTED tier={exp_tier} snap={exp_snap} inv_ok={ok_inv}"))
    # global invariant across all cases
    allr = [clf.classify(m) for m, *_ in CASES]
    inv = all(("snapshot_verified" in r["required_gates"]) == (r["tier"] == "critical") for r in allr)
    print(f"{'PASS' if inv else 'FAIL'}  INVARIANT: snapshot_verified gate <=> critical tier")
    fails += not inv

    # fail-closed + never_auto assertions
    def one(iid, title, branch, labels):
        return clf.classify(mr(iid, title, branch, labels))
    checks = [
        ("openbao is never_auto", one(202, "x", "renovate/openbao-openbao-2.x", ["renovate"])["never_auto"] is True),
        ("postgres is NOT never_auto", one(93, "x", "renovate/postgres-18.x", ["major-update", "renovate"])["never_auto"] is False),
        ("unknown flagged assumed-stateful", "stateful:assumed-unknown" in one(200, "x", "renovate/surrealdb-2.x", ["renovate"])["signals"]),
        ("known-stateless (nginx) NOT assumed-unknown", "stateful:assumed-unknown" not in one(2, "x", "renovate/nginx-1.x", ["renovate"])["signals"]),
        # ── REGRESSION 2026-07-06: never_auto must survive the raw WEBHOOK shape (title/branch nested
        # under object_attributes) — the live !359 gate fed a shape that defeated the top-level reads,
        # yielding never_auto=false (fail-closed still POLL'd, but the explicit engine tag was lost). ──
        ("webhook-shape openbao still never_auto", clf.classify({
            "object_attributes": {"iid": 359, "title": "chore(deps): update openbao/openbao docker tag to v2.5.5",
            "source_branch": "renovate/openbao-openbao-2.x", "target_branch": "main", "action": "open"},
            "user": {"username": "renovate-bot"}})["never_auto"] is True),
        ("webhook-shape routine (traefik) stays routine", clf.classify({
            "object_attributes": {"iid": 900, "title": "chore(deps): update traefik docker tag to v3.1.2",
            "source_branch": "renovate/traefik-3.x", "target_branch": "main"}})["tier"] == "routine"),
        # ── REGRESSION 2026-07-07: Atlantis/k8s MRs must NOT auto-merge blind — they need
        # rebase-onto-main + plan-review + (canary for CNI/ingress) that the lane cannot do. The
        # classifier emits atlantis_managed + never_auto regardless of tier; CNI/ingress add a canary gate.
        # cilium & ingress-nginx are "stateless" (revert-by-tag) yet are the CNI + ingress controller. ──
        ("cilium is atlantis_managed", one(400, "🏗️ [INFRA] Update Helm release cilium to v1.19.5", "renovate/cilium-1.x", ["renovate"])["atlantis_managed"] is True),
        ("cilium is never_auto (was auto-mergeable!)", one(400, "🏗️ [INFRA] Update Helm release cilium to v1.19.5", "renovate/cilium-1.x", ["renovate"])["never_auto"] is True),
        ("cilium requires canary", one(400, "🏗️ [INFRA] Update Helm release cilium to v1.19.5", "renovate/cilium-1.x", ["renovate"])["atlantis_canary_required"] is True),
        ("cilium has atlantis_rebase+plan gates", set(["atlantis_rebase", "atlantis_plan_review", "atlantis_canary"]).issubset(set(one(400, "🏗️ [INFRA] Update Helm release cilium to v1.19.5", "renovate/cilium-1.x", ["renovate"])["required_gates"]))),
        ("ingress-nginx never_auto + canary", (lambda r: r["never_auto"] and r["atlantis_canary_required"])(one(303, "🏗️ [INFRA] Update Helm release ingress-nginx to v4.15", "renovate/ingress-nginx-4.x", ["renovate"]))),
        ("goldpinger-in-tf ([INFRA] docker) is atlantis_managed never_auto, NO canary", (lambda r: r["atlantis_managed"] and r["never_auto"] and not r["atlantis_canary_required"])(one(363, "🏗️ [INFRA] Update docker.io/bloomberg/goldpinger Docker tag to v3.11.2", "renovate/docker.io-bloomberg-goldpinger-3.x", ["renovate"]))),
        ("terraform provider is atlantis_managed never_auto", (lambda r: r["atlantis_managed"] and r["never_auto"])(one(370, "🏗️ [INFRA] Update Terraform helm to ~> 3.2.0", "renovate/helm-3.x", ["renovate"]))),
        ("kps helm stays critical AND atlantis never_auto", (lambda r: r["tier"] == "critical" and r["atlantis_managed"] and r["never_auto"])(one(126, "🏗️ [INFRA] Update Helm release kube-prometheus-stack to v79.12.0", "renovate/kube-prometheus-stack-79.x", ["renovate"]))),
        # docker-plane MRs must NOT become atlantis_managed (they use deploy_docker, not Atlantis).
        ("docker redis is NOT atlantis_managed", one(251, "chore(deps): update docker.io/redis:8.4-alpine docker digest", "renovate/docker.io-redis-8.4-alpine", ["renovate"])["atlantis_managed"] is False),
        ("docker alpine is NOT atlantis_managed", one(372, "chore(deps): update alpine docker tag to v3.24", "renovate/alpine-3.x", ["renovate"])["atlantis_managed"] is False),
        # atlantis MRs must NOT introduce a spurious snapshot_verified gate (invariant preserved).
        ("cilium (routine) has NO snapshot_verified gate", "snapshot_verified" not in one(400, "🏗️ [INFRA] Update Helm release cilium to v1.19.5", "renovate/cilium-1.x", ["renovate"])["required_gates"]),
        # ── REGRESSION 2026-07-07 (postmerge host/service + docker-MAJOR): a merged bad image must be
        # health-checkable in ALL docker layouts, and a docker-tag MAJOR must be parked, not timeout-auto'd. ──
        ("edge/dmz/<host>/ host detected (was null → postmerge skipped)",
         clf.classify({"iid": 375, "title": "x", "source_branch": "renovate/x",
                       "changes": [{"new_path": "edge/dmz/notrf01dmz01/reactive-resume/cookie-patch/Dockerfile"}]})["affected_host"] == "notrf01dmz01"),
        ("edge/dmz service = dir (reactive-resume), not package",
         clf.classify({"iid": 375, "title": "x", "source_branch": "renovate/x",
                       "changes": [{"new_path": "edge/dmz/notrf01dmz01/reactive-resume/cookie-patch/Dockerfile"}]})["affected_service"] == "reactive-resume"),
        ("Dockerfile build-tool bump: service = svc dir (librechat), not the tool (uv)",
         clf.classify({"iid": 376, "title": "update uv", "source_branch": "renovate/uv",
                       "changes": [{"new_path": "docker/nllibrechat01/librechat/Dockerfile"}]})["affected_service"] == "librechat"),
        ("images/<x> CI base image → NO host (postmerge skipped, never reverted)",
         clf.classify({"iid": 1, "title": "x", "source_branch": "renovate/x",
                       "changes": [{"new_path": "images/rust-runner/Dockerfile"}]})["affected_host"] is None),
        ("docker-tag MAJOR (redis 7.4→8.8, no label) re-detected as major",
         clf.classify({"iid": 373, "title": "update redis docker tag", "source_branch": "renovate/redis-8.x", "labels": ["renovate"],
                       "changes": [{"new_path": "docker/h/redis/docker-compose.yml", "diff": "@@ -1 +1 @@\n-    image: redis:7.4-alpine\n+    image: redis:8.8-alpine\n"}]})["update_type"] == "major"),
        ("docker-tag MINOR (redis 8.4→8.8) stays non-major",
         clf.classify({"iid": 373, "title": "update redis docker tag", "source_branch": "renovate/redis-8.x", "labels": ["renovate"],
                       "changes": [{"new_path": "docker/h/redis/docker-compose.yml", "diff": "@@ -1 +1 @@\n-    image: redis:8.4-alpine\n+    image: redis:8.8-alpine\n"}]})["update_type"] != "major"),
        # ── REGRESSION 2026-07-07: a Dockerfile build-tool bump must NOT auto-merge — deploy_docker does
        # `pull` not `build`, so it never deploys AND postmerge sees the old-image container as healthy
        # (the false PASS that let the reverted uv !376 through). docker-compose IMAGE bumps are unaffected. ──
        ("Dockerfile build-tool bump (uv) → never_auto (needs rebuild+review)",
         clf.classify({"iid": 376, "title": "update uv", "source_branch": "renovate/uv", "labels": ["renovate"],
                       "changes": [{"new_path": "docker/nllibrechat01/librechat/Dockerfile", "diff": "@@ -1 +1 @@\n-COPY --from=ghcr.io/astral-sh/uv:0.9.15 /uv /bin/\n+COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /bin/\n"}]})["never_auto"] is True),
        ("Dockerfile MR carries dockerfile-needs-rebuild signal",
         "never-auto:dockerfile-needs-rebuild" in clf.classify({"iid": 375, "title": "x", "source_branch": "renovate/x",
                       "changes": [{"new_path": "edge/dmz/notrf01dmz01/reactive-resume/cookie-patch/Dockerfile"}]})["signals"]),
        ("docker-compose IMAGE-tag bump is NOT flagged dockerfile (still auto-mergeable)",
         clf.classify({"iid": 372, "title": "update alpine", "source_branch": "renovate/alpine", "labels": ["renovate"],
                       "changes": [{"new_path": "docker/h/svc/docker-compose.yml", "diff": "@@ -1 +1 @@\n-    image: alpine:3.21\n+    image: alpine:3.24\n"}]})["never_auto"] is False),
    ]
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
        fails += not ok
    print(f"\n{len(CASES)} cases, {fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
