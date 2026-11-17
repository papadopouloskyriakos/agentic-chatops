#!/usr/bin/env python3
"""
classify-renovate-mr.py — dependency-aware reversibility classifier for the
Renovate MR Autonomy lane (IFRNLLEI01PRD epic, 2026-07-06).

WHY THIS EXISTS (the trap): the incident-lane classifier scripts/classify-session-risk.py
decides reversibility by matching destructive SHELL VERBS in a proposed plan
(dropdb / mkfs / terraform destroy / ...). A Renovate MR diff contains NO such verb —
a `postgres:15 -> postgres:18` bump is a one-line change whose destruction happens
*inside the container's own migration on first boot*, which that classifier never sees.
Fed through it, a stateful major scores LOW -> AUTO. That is exactly backwards.

So this classifier derives reversibility from the DEPENDENCY ITSELF — package name,
semver delta (updateType), and statefulness — not from scanning the diff for verbs.

It does NOT decide merge. It emits the REQUIRED GATES + risk tier for an MR. The n8n
lane then merges only if every required gate passes (CI green, review APPROVE at the
tier's confidence threshold, and — for stateful — a verified snapshot). Operator posture
(2026-07-06): "everything that passes review" auto-merges, but the gates scale with
blast radius and stateful bumps are hard-blocked on a verified restore point.

Output is a JSON object (see classify()). Usage:
  # one MR from a JSON blob (GitLab MR object or the minimal {title,source_branch,labels,changes}):
  cat mr.json | python3 classify-renovate-mr.py --mr-json -
  # replay a whole corpus (one GitLab MR object per line) and print a table + JSONL:
  python3 classify-renovate-mr.py --replay renovate_mrs.jsonl
  # live fetch by project id + iid (needs GITLAB_TOKEN in env):
  python3 classify-renovate-mr.py --project 12 --iid 251

Ships DARK: this is analysis only; nothing here merges anything. The n8n lane that
consumes it is gated behind ~/gateway.renovate_autonomy.
"""
from __future__ import annotations

import json
import os
REDACTED_a7b84d63
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_CFG_PATH = Path(__file__).resolve().parent.parent / "config" / "renovate-stateful-services.json"

# Non-dependency Renovate branches (config/onboarding changes, not version bumps).
_CONFIG_BRANCHES = {"configure", "migrate-config"}

# Trailing version token on a renovate branch slug: "-8.x", "-2.6.19", "-8.4-alpine",
# "-2025.x", "-v3", "-8". Stripped only to derive a cosmetic package name; statefulness
# matching does NOT rely on this (it tokens-matches the whole slug + title).
_VER_TAIL = re.compile(r"-v?\d[\w.]*(?:\.x)?(?:-[a-z0-9]+)?$", re.IGNORECASE)
_DELIM = re.compile(r"[^a-z0-9]+")  # slug/title tokeniser


def _load_cfg() -> dict:
    with open(_CFG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _stateful_tokens(cfg: dict) -> set[str]:
    out: set[str] = set()
    for group in cfg.get("stateful_tokens", {}).values():
        out.update(t.lower() for t in group)
    return out


def _tokens(text: str) -> set[str]:
    return {t for t in _DELIM.split((text or "").lower()) if t}


def _ngram_hay(text: str) -> set[str]:
    """Single tokens PLUS every contiguous hyphen-joined n-gram, so a MULTI-WORD allowlist / stateful
    entry like 'cert-manager', 'external-secrets', 'kube-prometheus-stack' or 'victoria-metrics' matches
    a slug the tokeniser split into ['cert','manager', ...]. Delimiter-bounded (only *contiguous* slug
    tokens are joined) → it reconstructs real hyphenated names WITHOUT the substring false-positives a
    naive `token in text` would create (e.g. 'go' inside 'mongo')."""
    toks = [t for t in _DELIM.split((text or "").lower()) if t]
    out: set[str] = set(toks)
    for i in range(len(toks)):
        for j in range(i + 2, len(toks) + 1):
            out.add("-".join(toks[i:j]))
    return out


def _detect_update_type(title: str, branch: str, labels: list[str]) -> str:
    labs = {l.lower() for l in labels}
    slug = branch[len("renovate/"):] if branch.startswith("renovate/") else branch
    if slug in _CONFIG_BRANCHES or "renovate/configure" in branch or "migrate-config" in branch:
        return "config"
    t = f"{title} {branch}".lower()
    # Major: the most reliable signal in this Renovate config is the `major-update`
    # label; `[MAJOR]` / ⚠️ in the title is the backup.
    if "major-update" in labs or "[major]" in t or "⚠" in (title or ""):
        return "major"
    if "digest" in t:
        return "digest"
    if "pin" in labs or re.search(r"\bpin\b", t):
        return "pin"
    if "lock file" in t or "lockfile" in t or "lock-file" in t:
        return "lockfile"
    return "minor_patch"


def _package_name(title: str, branch: str) -> str:
    slug = branch[len("renovate/"):] if branch.startswith("renovate/") else branch
    if slug in _CONFIG_BRANCHES:
        return slug
    name = _VER_TAIL.sub("", slug)
    return name or slug


def _managers_from_changes(changes: list[dict]) -> list[str]:
    """Best-effort manager + host inference from diff file paths (may be empty in
    metadata-only replay). Host convention: docker/<hostname>/<service>/...."""
    mgrs: set[str] = set()
    for ch in changes or []:
        p = (ch.get("new_path") or ch.get("old_path") or "").lower()
        if not p:
            continue
        base = os.path.basename(p)
        if base.startswith("docker-compose") or base == "compose.yml":
            mgrs.add("docker-compose")
        elif base == "dockerfile" or base.startswith("dockerfile."):
            mgrs.add("dockerfile")
        elif p.endswith(".tf") or p.endswith(".tf.json"):
            mgrs.add("terraform")
        elif base in ("chart.yaml", "values.yaml") or "helm" in p:
            mgrs.add("helm")
        elif p.endswith((".yaml", ".yml")) and ("k8s" in p or "kubernetes" in p or "namespaces" in p):
            mgrs.add("kubernetes")
        elif base in ("requirements.txt", "pyproject.toml", "poetry.lock"):
            mgrs.add("pip")
    return sorted(mgrs)


def _affected_host(changes: list[dict]) -> str | None:
    # Docker-plane host conventions: `docker/<host>/<svc>/…` (main) and `edge/dmz/<host>/<svc>/…`
    # (DMZ services deploy to the named host). `images/<x>` is a CI-built base image → NO running host
    # to health-check, so it deliberately returns None (postmerge is skipped/inconclusive, never reverted).
    for ch in changes or []:
        p = ch.get("new_path") or ch.get("old_path") or ""
        m = (re.search(r"(?:^|/)docker/([a-z0-9][a-z0-9-]*)/", p)
             or re.search(r"(?:^|/)edge/dmz/([a-z0-9][a-z0-9-]*)/", p))
        if m:
            return m.group(1)
    return None


def _affected_service(changes: list[dict]) -> str | None:
    """The SERVICE directory that names the running container — `.../<host>/<SVC>/…`. postmerge-verify
    health-checks THIS, not the bumped package: a Dockerfile build-tool bump (e.g. `uv`) has package=uv
    but the running service is <SVC> (librechat). Returns the first non-empty service segment."""
    for ch in changes or []:
        p = ch.get("new_path") or ch.get("old_path") or ""
        m = (re.search(r"(?:^|/)docker/[a-z0-9][a-z0-9-]*/([a-z0-9][a-z0-9._-]*)/", p)
             or re.search(r"(?:^|/)edge/dmz/[a-z0-9][a-z0-9-]*/([a-z0-9][a-z0-9._-]*)/", p))
        if m:
            return m.group(1)
    return None


def _major_from_diff(changes: list[dict]) -> bool:
    """True if any changed hunk bumps a semver-shaped token whose LEADING component strictly increases
    (7.x→8.x, 1.x→2.x). Renovate docker-tag majors carry no `major-update` label, so the version DELTA
    is the reliable signal. Erring toward detecting major is fail-SAFE here: a false-major only parks the
    MR for the operator (POLL), never auto-merges something it shouldn't."""
    sem = re.compile(r"v?([0-9]+)\.([0-9]+)(?:\.[0-9]+)*")
    for ch in changes or []:
        diff = ch.get("diff") or ""
        rem = [l[1:] for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
        add = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
        for r, a in zip(rem, add):
            rv = sem.findall(r)
            av = sem.findall(a)
            for (r_maj, _), (a_maj, _) in zip(rv, av):
                if int(a_maj) > int(r_maj):
                    return True
    return False


def classify(mr: dict, cfg: dict | None = None) -> dict:
    """Classify one MR. `mr` accepts a full GitLab MR object OR a minimal
    {title, source_branch, labels, changes}. Returns the routing decision."""
    cfg = cfg or _load_cfg()
    stateful_tokens = _stateful_tokens(cfg)

    # Accept a raw GitLab merge_request WEBHOOK event too (title/branch nested under object_attributes),
    # not just a REST MR object — so never_auto/statefulness detection can't be silently defeated by being
    # handed the webhook shape (defense in depth). Top-level non-empty fields win; object_attributes fills gaps.
    oa = mr.get("object_attributes")
    if isinstance(oa, dict):
        mr = {**oa, **{k: v for k, v in mr.items() if k != "object_attributes" and v not in (None, "", [])}}

    title = mr.get("title", "") or ""
    branch = mr.get("source_branch", "") or ""
    labels = mr.get("labels", []) or []
    changes = mr.get("changes", []) or []
    # A webhook event's `changes` is a field-diff dict, not the file-diff list the manager/host helpers
    # expect — only treat it as a diff when it is actually a list.
    if not isinstance(changes, list):
        changes = []

    update_type = _detect_update_type(title, branch, labels)
    package = _package_name(title, branch)
    managers = _managers_from_changes(changes)
    host = _affected_host(changes)
    service = _affected_service(changes)
    # Docker-tag MAJORs (v7→v8) carry no `major-update` label → _detect_update_type sees "minor_patch"
    # → they become timeout-auto eligible. Re-detect major from the version delta in the diff so a MAJOR
    # is parked for the operator, not silently timeout-auto-merged. (Data stays snapshot-protected either way.)
    if update_type == "minor_patch" and _major_from_diff(changes):
        update_type = "major"

    # ── Statefulness — FAIL CLOSED on unknown (Dim-1 fix) ──────────────────────
    hay = _ngram_hay(branch) | _ngram_hay(title)
    matched_stateful = sorted(hay & stateful_tokens)
    # Veto: package names that CONTAIN a stateful token but are themselves stateless
    # (gitlab-runner/-agent, DB metrics exporters, ...). Exact-or-prefix on the package.
    pkg_l = package.lower()
    overrides = [o.lower() for o in cfg.get("stateless_overrides", [])]
    vetoed_by = next((o for o in overrides if pkg_l == o or pkg_l.startswith(o)), None)
    if vetoed_by:
        matched_stateful = []
    stateful = bool(matched_stateful)

    # CONFIDENTLY-stateless allowlist. A bump is treated as reversible-without-snapshot ONLY if the
    # engine is provably stateless (here) OR an override; anything else UNKNOWN is snapshot-gated.
    known_stateless_tokens: set[str] = set()
    for grp in cfg.get("known_stateless_tokens", {}).values():
        if isinstance(grp, list):
            known_stateless_tokens |= {t.lower() for t in grp}
    known_stateless = bool(hay & known_stateless_tokens) or bool(vetoed_by)

    # never-auto engines (secret/config stores) — POLL regardless of snapshot success (defense in depth).
    never_auto_engines = {e.lower() for e in cfg.get("never_auto_engines", [])}
    never_auto_engine = sorted(hay & never_auto_engines)

    is_major = update_type == "major"
    is_config = update_type == "config"

    # ── Atlantis-managed (k8s / Terraform IaC) — the discipline gap (2026-07-07) ──────────────
    # A helm-release / Terraform / kubernetes-manifest bump is applied by ATLANTIS (apply-before-
    # merge), NOT by the docker deploy_docker path — and it needs discipline the lane cannot do:
    #   1. rebase onto main FIRST (else the whole-project plan reverts a just-merged sibling MR),
    #   2. plan review (reject any reversion / destroy / forces-replacement),
    #   3. canary for high-blast-radius controllers (CNI/cilium, ingress).
    # This is ORTHOGONAL to statefulness: cilium & ingress-nginx are "stateless" (revert by tag) yet
    # are the CNI and the ingress controller — a blind apply can take the cluster down. So an Atlantis
    # MR is emitted as never_auto (→ POLL) regardless of tier, with the required Atlantis gates, so it
    # is never auto-applied blind and never silently sits. Signal: file-path managers (ground truth
    # when the diff is present) OR the Renovate infra-MR title conventions (metadata-only webhook).
    title_l = title.lower()
    atlantis_managers = {"terraform", "helm", "kubernetes"}
    atlantis_managed = bool(set(managers) & atlantis_managers) or ("[infra]" in title_l) \
        or ("helm release" in title_l) or bool(re.search(r"\bterraform\b", title_l))
    atlantis_canary_tokens = {t.lower() for t in cfg.get("atlantis_canary_tokens", [])}
    atlantis_canary_required = atlantis_managed and bool(hay & atlantis_canary_tokens)

    signals: list[str] = [f"update:{update_type}", f"stateful:{str(stateful).lower()}"]
    if matched_stateful:
        signals.append("stateful-match:" + ",".join(matched_stateful))
    if managers:
        signals.append("manager:" + ",".join(managers))
    if host:
        signals.append(f"host:{host}")
    if atlantis_managed:
        signals.append("atlantis-managed")
    if atlantis_canary_required:
        signals.append("atlantis-canary:" + ",".join(sorted(hay & atlantis_canary_tokens)))

    # ── Tier (fail closed) ─────────────────────────────────────────────────────
    if is_config:
        tier, reversibility = "elevated", "config-change"
        signals.append("renovate-config-change")
    elif stateful:
        # ANY bump of a KNOWN stateful service — even a patch/digest — can migrate on-disk data.
        tier, reversibility = "critical", "recoverable-with-snapshot"
    elif known_stateless:
        # Provably stateless → reverts cleanly by tag/version; no data snapshot required.
        tier, reversibility = ("elevated", "reversible-breaking") if is_major else ("routine", "reversible")
    else:
        # UNKNOWN statefulness → FAIL CLOSED → snapshot-gate it. An unlisted DB/store must never
        # slip through as routine; the generic snapshot recipe keeps it auto-mergeable safely.
        tier, reversibility = "critical", "assumed-stateful-unverified"
        signals.append("stateful:assumed-unknown")

    snapshot_required = tier == "critical"
    required_gates = ["ci_green", "review_approve"]
    if snapshot_required:
        required_gates.append("snapshot_verified")
    # Atlantis MRs carry gates the lane cannot auto-satisfy → they force POLL (below) and the
    # operator/heartbeat runs scripts/renovate-atlantis-review.sh to satisfy them mechanically.
    if atlantis_managed:
        required_gates += ["atlantis_rebase", "atlantis_plan_review"]
        if atlantis_canary_required:
            required_gates.append("atlantis_canary")

    review_profile = "hardened" if tier in ("critical", "elevated") or atlantis_managed else "standard"
    confidence_threshold = 0.90 if tier in ("critical", "elevated") or atlantis_managed else 0.80

    # never_auto: a secret/config-store engine, a tier in policy.never_auto_tiers, OR any Atlantis MR
    # (needs rebase+plan-review+canary the lane can't do) → always POLL, never auto-applied blind.
    never_auto_tiers = set(cfg.get("policy", {}).get("never_auto_tiers", []))
    # A Dockerfile bump (e.g. a build-tool like uv/node in a FROM / COPY --from) must NOT auto-merge:
    # deploy_docker does `compose pull`, NOT `build`, so the change never takes effect on the running image
    # AND the post-merge health check sees the OLD-image container as healthy → a false PASS (this is exactly
    # what let the reverted uv bump !376 through). Worse, when the image IS later rebuilt the bumped build-tool
    # can break the build, decoupled from the merge. So Dockerfile-manager MRs POLL for human review (rebuild +
    # verify). docker-compose IMAGE-TAG bumps are unaffected (pull DOES apply them). Tunable: dockerfile_needs_review.
    dockerfile_needs_review = cfg.get("dockerfile_needs_review", True)
    dockerfile_build = ("dockerfile" in set(managers)) and dockerfile_needs_review
    never_auto = bool(never_auto_engine) or (tier in never_auto_tiers) or atlantis_managed or dockerfile_build
    if never_auto_engine:
        signals.append("never-auto-engine:" + ",".join(never_auto_engine))
    if atlantis_managed:
        signals.append("never-auto:atlantis-review-required")
    if dockerfile_build:
        signals.append("never-auto:dockerfile-needs-rebuild")
    auto_merge_allowed = not never_auto

    return {
        "schema_version": SCHEMA_VERSION,
        "mr": {
            "project_id": mr.get("project_id"),
            "iid": mr.get("iid"),
            "title": title,
            "source_branch": branch,
            "state": mr.get("state"),
            "web_url": mr.get("web_url"),
        },
        "package": package,
        "update_type": update_type,
        "managers": managers,
        "affected_host": host,
        "affected_service": service,
        "stateful": stateful,
        "stateful_match": matched_stateful,
        "tier": tier,
        "reversibility": reversibility,
        "snapshot_required": snapshot_required,
        "atlantis_managed": atlantis_managed,
        "atlantis_canary_required": atlantis_canary_required,
        "required_gates": required_gates,
        "review_profile": review_profile,
        "confidence_threshold": confidence_threshold,
        "never_auto": never_auto,
        "never_auto_engine": never_auto_engine,
        "dockerfile_build": dockerfile_build,
        "auto_merge_allowed_if_gates_pass": auto_merge_allowed,
        "signals": signals,
    }


# ── I/O helpers ─────────────────────────────────────────────────────────────
def _fetch_mr(project_id: str, iid: str) -> dict:
    import urllib.request

    base = os.environ.get("GITLAB_ENDPOINT", "https://gitlab.example.net/api/v4")
    tok = os.environ.get("GITLAB_TOKEN", "")
    if not tok:
        sys.exit("GITLAB_TOKEN not set (source .env)")
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    url = f"{base}/projects/{project_id}/merge_requests/{iid}/changes"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": tok})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.load(r)


def _replay(path: str, cfg: dict) -> None:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(classify(json.loads(line), cfg))
    # table
    w = sys.stderr
    print(f"{'iid':>5}  {'state':<7} {'tier':<9} {'update':<11} {'snap':<4} {'pkg'}", file=w)
    print("-" * 78, file=w)
    for r in sorted(rows, key=lambda x: (x["tier"], str(x["mr"]["iid"]))):
        print(
            f"{str(r['mr']['iid']):>5}  {str(r['mr']['state'] or ''):<7} "
            f"{r['tier']:<9} {r['update_type']:<11} "
            f"{'YES' if r['snapshot_required'] else '-':<4} {r['package']}",
            file=w,
        )
    # counts
    from collections import Counter

    tc = Counter(r["tier"] for r in rows)
    print("\ntiers: " + ", ".join(f"{k}={v}" for k, v in sorted(tc.items())) +
          f"  (snapshot_required={sum(r['snapshot_required'] for r in rows)}/{len(rows)})", file=w)
    # machine-readable to stdout
    for r in rows:
        print(json.dumps(r))


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mr-json", help="path to a JSON MR object, or - for stdin")
    ap.add_argument("--replay", help="path to a JSONL corpus (one GitLab MR object per line)")
    ap.add_argument("--project", help="GitLab project id (with --iid)")
    ap.add_argument("--iid", help="MR iid (with --project)")
    args = ap.parse_args()
    cfg = _load_cfg()

    if args.replay:
        _replay(args.replay, cfg)
    elif args.mr_json:
        raw = sys.stdin.read() if args.mr_json == "-" else Path(args.mr_json).read_text()
        print(json.dumps(classify(json.loads(raw), cfg), indent=2))
    elif args.project and args.iid:
        print(json.dumps(classify(_fetch_mr(args.project, args.iid), cfg), indent=2))
    else:
        ap.error("need --mr-json, --replay, or --project+--iid")


if __name__ == "__main__":
    main()
