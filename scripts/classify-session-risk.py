#!/usr/bin/env python3
"""Risk-based session classifier for IFRNLLEI01PRD-632.

Given an investigation plan (from build-investigation-plan.sh) and the
alert category, emit one of:

    low     — read-only investigation; safe to auto-resolve with no human poll
    mixed   — may modify infra but unclear; keep human-in-the-loop path
    high    — definitely modifies infra; always HITL

Writes an audit row to `session_risk_audit` so we can prove, after the fact,
that no high-risk session was auto-approved.

Usage (stdin JSON, env for context):

    echo "$PLAN_JSON" | ALERT_CATEGORY=availability ISSUE_ID=IFRNLLEI01PRD-123 \\
        python3 scripts/classify-session-risk.py

Usage (file):

    python3 scripts/classify-session-risk.py --plan /tmp/plan.json --category availability

Output (stdout):

    {
      "risk_level": "low",
      "auto_approve_recommended": true,
      "signals": ["category:availability", "read_only_tools_only", ...],
      "plan_hash": "abc123..."
    }

Exit 0 = classification produced (even if risk=high).
Exit 1 = bad input (plan missing / unparseable).
Exit 2 = fail-closed override: env `RISK_FAIL_CLOSED=1` forces risk=high on
         any error. Use in production so a broken classifier never auto-approves.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
REDACTED_a7b84d63
import sqlite3
import subprocess
import sys
import time
from typing import Any

# IFRNLLEI01PRD-635: central schema version registry for audit table rows.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from schema_version import current as schema_current  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

# ── Debug instrumentation (IFRNLLEI01PRD pipeline observability) ────────────────
#
# The auto-resolve pipeline failed SILENTLY for weeks: the n8n "Classify Risk"
# SSH node passed a broken/empty plan, the classifier fail-closed to high, and the
# fail-closed branch exited BEFORE writing session_risk_audit — so the audit table
# was empty and nobody could see why nothing auto-resolved. This always-on,
# low-volume (one classification per alert) structured log leaves a trail so this
# class of break is visible immediately, now and in future.
#   Follow one issue's full pipeline flow (this script + the bash skills):
#     grep <ISSUE-ID> /home/app-user/logs/claude-gateway/pipeline-debug.log
#   GATEWAY_DEBUG=1 logs the FULL stdin (default truncates to 160 chars).
#   GATEWAY_DEBUG_LOG redirects the file (absolute default so it survives an
#   unset/odd HOME in the n8n SSH context — the very bug that hid the autonomy flag).
_DBG_LOG = os.environ.get(
    "GATEWAY_DEBUG_LOG",
    "/home/app-user/logs/claude-gateway/pipeline-debug.log",
)


def _dbg(event: str, **fields: Any) -> None:
    """Append one JSON debug record. Never raises — logging must not break triage."""
    try:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "script": "classify-session-risk",
            "pid": os.getpid(),
            "event": event,
            **fields,
        }
        os.makedirs(os.path.dirname(_DBG_LOG), exist_ok=True)
        with open(_DBG_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:  # noqa: BLE001 — telemetry must never break classification
        pass


# ── Risk signals ──────────────────────────────────────────────────────────────
#
# Each signal is (pattern, risk_contribution). Evaluating a plan yields a list
# of matched signals; the highest risk_contribution wins. This gives a clear
# audit trail ("why was this low?") rather than an opaque score.

# Categories that default to HIGH regardless of plan content — these alerts
# almost always end with an infra change.
HIGH_RISK_CATEGORIES = {
    "maintenance",          # planned reboots, drains, kernel updates
    "security-incident",    # containment usually = infra change (ban, shun, isolate)
    "deployment",           # releases / rollouts by definition modify
}

# Categories that lean LOW — diagnosis-first with rare need to modify.
LOW_LEAN_CATEGORIES = {
    "availability",
    "resource",             # CPU/mem/disk/gpu monitoring
    "certificate",          # cert-expiry warnings — usually just early-warning
    "generic",
}

# Tool / step keywords that force MIXED or HIGH.
# Order matters: first match wins (check HIGH before MIXED).
MUTATION_PATTERNS = [
    # Shell / MCP write operations
    (re.compile(r"\b(kubectl|k)\s+(apply|create|delete|replace|patch|rollout|scale|drain|cordon|uncordon|edit|taint|annotate|label)\b"), "high", "kubectl-write"),
    (re.compile(r"\bhelm\s+(install|upgrade|uninstall|rollback)\b"), "high", "helm-write"),
    (re.compile(r"\bpct\s+(set|start|stop|reboot|shutdown|destroy|create|restore|clone)\b"), "high", "pct-write"),
    (re.compile(r"\bqm\s+(set|start|stop|reboot|shutdown|destroy|create|clone|reset|migrate|rollback)\b"), "high", "qm-write"),
    (re.compile(r"\bsystemctl\s+(start|stop|restart|reload|enable|disable|mask|unmask|daemon-reload)\b"), "high", "systemctl-write"),
    (re.compile(r"\b(git\s+(commit|push|merge|rebase|reset|tag|branch)\b|git\s+checkout\s+-b)"), "high", "git-write"),
    (re.compile(r"\b(rm|mv|cp|chmod|chown|mkdir|rmdir|truncate)\s+-?"), "high", "fs-write"),
    (re.compile(r"\b(iptables|nft|ufw)\s+"), "high", "firewall-write"),
    (re.compile(r"\bcrypto\s+map\b|\bclear\s+(crypto|conn|shun|arp|xlate)\b"), "high", "asa-write"),
    (re.compile(r"\bswanctl\s+(--(load|terminate|initiate|install|flush))\b"), "high", "swanctl-write"),
    (re.compile(r"\bvtysh.*-c\s+['\"](conf|write|clear)"), "high", "frr-write"),
    (re.compile(r"\bawx.*(launch|post)|curl.*awx.*-X\s+POST|ansible-tower-cli.*(launch|job)|\btower-cli\s+job"), "high", "awx-launch"),
    # HOST reboot only — a `qm reboot`/`pct reboot` is a GUEST power-cycle (reversible,
    # carved conservative below), so exclude it here via negative lookbehind. A bare
    # `reboot`/`shutdown` (host) still matches and stays HIGH.
    (re.compile(r"(?<!qm )(?<!pct )\b(reboot|shutdown|halt|poweroff|kexec|init\s+[06])\b"), "high", "system-reboot"),
    # Softer mutations — MIXED (usually wrapped in dry_run or preview)
    (re.compile(r"\b(atlantis\s+(plan|apply)|terraform\s+(plan|apply|destroy)|tofu\s+(plan|apply|destroy))\b"), "mixed", "iac-plan-or-apply"),
    (re.compile(r"\bdocker\s+(run|exec|stop|restart|rm|kill|build|pull|push|tag)\b"), "mixed", "docker-write"),
    (re.compile(r"\bcscli\s+decisions\s+(add|delete)\b"), "mixed", "crowdsec-write"),
    # Ban / unban / shun mentions as bare words — strong HITL signal
    (re.compile(r"\b(ban|unban|shun|block|isolate|quarantine|drain|evict|kill)\b", re.IGNORECASE), "mixed", "containment-verb"),
]

# ── Autonomy-forward band engine (IFRNLLEI01PRD-1102 / -1103) ───────────────────
#
# When AUTONOMY_FORWARD is enabled the classifier emits a *band* alongside the
# legacy risk_level, mapping each session to one of four operating modes (the
# human is a circuit-breaker, not a gatekeeper):
#
#   AUTO         — auto-resolve, no poll, no SMS (low, or reversible+mixed)
#   AUTO_NOTICE  — auto-resolve + parallel SMS (reversible action touching a P0 host)
#   POLL_PROCEED — courtesy poll; no-vote => PROCEED (reversible, prediction-backed)
#   POLL_PAUSE   — hard HITL floor; no-vote => PAUSE; SMS at poll-post
#                  (high / irreversible / deviation / partial / no-prediction /
#                   jailbreak / P0-reboot)
#
# Default OFF: with AUTONOMY_FORWARD unset/0 the stdout JSON is byte-identical to
# the legacy classifier — band keys are NOT emitted and the irreversible
# re-tagging is NOT applied. This lets the code deploy dark, then flip on per
# docs/runbooks/risk-based-auto-approval.md. The Infragraph prediction/verdict
# gate in the Runner (IFRNLLEI01PRD-1044 / -1106) is the real safety floor: an
# AUTO/AUTO_NOTICE/POLL_PROCEED band is necessary-not-sufficient — the Runner
# demotes it to POLL_PAUSE unless a committed plan_hash prediction returns
# verdict=match. The verdict column is written ONLY by infragraph-verify.py.


def _envflag(name: str) -> bool:
    """Truthy if the env var is set truthy, OR (when the env var is UNSET) a
    sentinel file ~/gateway.<name lowercased> exists. The sentinel is the
    operator kill-switch — `touch ~/gateway.autonomy_forward` to enable,
    `rm` to disable, instant, no n8n edit (matches gateway.mode /
    gateway.maintenance). An explicitly-set env var always wins (so tests/CI
    can force on or off regardless of the sentinel)."""
    v = os.environ.get(name)
    if v is not None:
        return v not in ("", "0", "false", "False", "no", "NO")
    return os.path.exists(os.path.expanduser(f"~/gateway.{name.lower()}"))


def _fire_session_sms(issue_id: str, plan: dict, result: dict) -> None:
    """Best-effort page to the Twilio bridge /alert-session (IFRNLLEI01PRD-1105).
    Fired at classify time for sms_required bands — earlier than the poll, which
    only gives the operator MORE reaction time. Dedup is the endpoint's job
    (issue_id key). Fire-and-forget: a short timeout + swallowed errors so a
    paging hiccup NEVER blocks or fails classification."""
    try:
        import urllib.request
        host = plan.get("hostname") or os.environ.get("ALERT_HOSTNAME", "")
        summary = ""
        for k in ("hypothesis", "reason", "summary"):
            if isinstance(plan.get(k), str) and plan[k].strip():
                summary = plan[k].strip()[:120]
                break
        reason = next((s for s in result.get("signals", [])
                       if s.startswith(("critical:", "high:", "irreversible:"))
                       or "jailbreak" in s or "deviation" in s), result.get("risk_level", ""))
        payload = json.dumps({
            "issue_id": issue_id or "unknown",
            "summary": summary,
            "band": result.get("band", ""),
            "host": host if isinstance(host, str) else "",
            "risk_level": result.get("risk_level", ""),
            "reason": reason,
        }).encode()
        url = os.environ.get("AUTONOMY_SMS_URL", "http://127.0.0.1:9106/alert-session")
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=4) as resp:
            print(f"[classify] session-sms -> {resp.status}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 — paging must never block classification
        print(f"[classify] session-sms skipped: {e}", file=sys.stderr)


# P0 = site-wide / cross-site blast radius. Source of truth: docs/host-blast-radius.md
# (machine-readable YAML block, kept in sync by test-1103's drift check). Extend at
# runtime with AUTONOMY_P0_HOSTS_EXTRA (csv) — no code push needed.
_P0_HOSTS_BASE = {
    "nl-pve01",   # NL gateway + DNS — total NL outage
    "nl-pve03",   # monitoring + claude01 + gpu01
    "nlpve04",   # compute
    "gr-pve01",   # most GR VMs
    "gr-pve02",   # GR K8s iSCSI storage
    "nl-fw01",    # NL total outage + VPN
    "gr-fw01",    # GR VPN — cross-site pipeline offline if down
}


def _p0_hosts() -> set[str]:
    extra = os.environ.get("AUTONOMY_P0_HOSTS_EXTRA", "")
    return _P0_HOSTS_BASE | {h.strip() for h in extra.split(",") if h.strip()}


# Mixed-level mutation reasons considered REVERSIBLE — eligible to widen into the
# AUTO band (operator Q3). Anything matching IRREVERSIBLE_PATTERNS is re-tagged
# high and can never be here. Extend with AUTONOMY_SOFT_REVERSIBLE_EXTRA (csv).
_SOFT_REVERSIBLE_BASE = {
    "iac-plan-or-apply",   # destroy is caught by IRREVERSIBLE_PATTERNS -> high
    "docker-write",        # rm/stop/restart — recreatable from image
    "crowdsec-write",      # decisions add/delete — undoable
    "containment-verb",    # ban/shun/block/isolate/drain/evict — reversible containment
}


def _soft_reversible() -> set[str]:
    extra = os.environ.get("AUTONOMY_SOFT_REVERSIBLE_EXTRA", "")
    # CONSERVATIVE_REMEDIATION_PATTERNS (defined below) reasons are reversible by
    # construction — resolved at call time, so the forward reference is fine.
    base = _SOFT_REVERSIBLE_BASE | {r for _p, r in CONSERVATIVE_REMEDIATION_PATTERNS}
    return base | {r.strip() for r in extra.split(",") if r.strip()}


# Irreversible / destructive operations. Under AUTONOMY_FORWARD these ADD a
# ('high', 'irreversible:*') signal, forcing risk=high so they can never reach
# AUTO/AUTO_NOTICE/POLL_PROCEED. They also close real gaps in MUTATION_PATTERNS:
# `terraform destroy` was only MIXED; mkfs/dd-to-dev/zpool destroy/dropdb were
# entirely unmatched (and could land in LOW -> auto-resolve a disk wipe).
IRREVERSIBLE_PATTERNS = [
    (re.compile(r"\b(terraform|tofu|atlantis)\b[^\n]*\bdestroy\b"), "irreversible:iac-destroy"),
    (re.compile(r"\b(mkfs(\.\w+)?|wipefs|shred|blkdiscard)\b|\bdd\b[^\n|]*\bof=/dev/"), "irreversible:disk-destroy"),
    (re.compile(r"\b(vgremove|lvremove|pvremove|zpool\s+destroy|zfs\s+destroy)\b"), "irreversible:storage-destroy"),
    (re.compile(r"\b(dropdb|drop\s+database|drop\s+table|truncate\s+table)\b", re.IGNORECASE), "irreversible:db-destroy"),
    (re.compile(r"\b(certbot\s+revoke|vault\s+(token|lease)\s+revoke|openssl\s+ca\b[^\n]*-revoke)\b"), "irreversible:credential-revoke"),
    # IFRNLLEI01PRD-1408: docker volume/system/network prune can delete stateful data
    # (named volumes, networks) — was UNMATCHED (=> LOW => silently AUTO-eligible). Only
    # `docker image|builder prune` is reversible (re-pull) and carved conservative below.
    (re.compile(r"\bdocker\s+(?:volume|system|network)\s+prune\b"), "irreversible:docker-prune-stateful"),
    # kubectl delete of a stateful/structural object = data loss. A SEPARATE high reason
    # (not the coarse kubectl-write) so a co-occurring conservative carve can't un-protect
    # it (the carve only supersedes kubectl-write).
    (re.compile(r"\bkubectl\s+delete\s+(?:pvc|persistentvolumeclaim|pv|persistentvolume\w*|namespace|ns|secret)\b"), "irreversible:k8s-delete-stateful"),
    # IFRNLLEI01PRD-1408 blind-spot closures (operator risk-appetite 2026-06-25). zfs
    # rollback / zpool offline = data/redundancy loss. Catastrophic Cisco verbs (wipe
    # config / kill routing / reset an interface) are remotely-unrecoverable lockouts — the
    # network CLAUDE.md never-do list — so they stay on the floor even when the network tier
    # is gate-governed. (`reload` is intentionally NOT matched here: it collides with the
    # conservative `systemctl reload`; a device reload via netmiko is caught as a gate-
    # governed network-config-write and the loaded manual forbids it.)
    (re.compile(r"\b(?:zfs\s+rollback|zpool\s+offline)\b"), "irreversible:zfs-rollback-or-offline"),
    (re.compile(r"\b(?:write\s+erase|erase\s+(?:startup-config|nvram|flash)|no\s+ip\s+routing|default\s+interface|clear\s+configure\s+all)\b"), "irreversible:network-catastrophic"),
]

# Host / guest reboot or power-cycle — transient outage. On a P0 host this stays
# on the POLL_PAUSE floor unless the operator opts in via AUTONOMY_P0_REBOOT_AUTO.
REBOOT_RE = re.compile(
    r"\b(reboot|shutdown|halt|poweroff|kexec|init\s+[06])\b"
    r"|\b(pct|qm)\s+(stop|reboot|shutdown)\b"
)

# ── Blind-spot closures (IFRNLLEI01PRD-1408, risk-appetite 2026-06-25 — docs/risk-
# appetite.md) ───────────────────────────────────────────────────────────────────────
# "An action that matches no pattern must not silently AUTO by omission." Folded high
# ONLY under AUTONOMY_FORWARD (like IRREVERSIBLE_PATTERNS) so flag-off legacy stays
# byte-identical. Gate-governable reasons (below) relax to AUTO_NOTICE when the territory
# gate is live; the rest are HELD.
_AUTONOMY_BLINDSPOT_PATTERNS = [
    # Cisco/network device config write (conf t / save / netmiko send_config_set). A
    # generic ACL/route/interface change isn't crypto-map, so it bypassed asa-write -> was
    # silently AUTO. Now classified -> gate-governed (network/edge CLAUDE.md + verdict).
    (re.compile(r"\bconf(?:ig(?:ure)?)?\s+t(?:erm(?:inal)?)?\b|\bcopy\s+run(?:ning-config)?\s+start(?:up-config)?\b|\bsend_config_set\b|\bwrite\s+mem(?:ory)?\b"), "high", "network-config-write"),
    # service x stop + alternative container engines stop|rm|kill -> gate-governed (their
    # docker/systemctl equivalents already are).
    (re.compile(r"\bservice\s+[\w.@-]+\s+stop\b"), "high", "service-stop"),
    (re.compile(r"\b(?:podman|nerdctl|ctr|crictl)\s+(?:rm|kill|stop)\b"), "high", "container-stop"),
    (re.compile(r"\b(?:lxc|incus)\s+(?:stop|restart|delete|rm)\b"), "high", "lxc-write"),
    # Code deploy / repo destruction via the GitHub/GitLab API. `gh pr merge` triggers
    # CI/CD -> deploys UNREVIEWED code; `api -X DELETE` destroys refs. Bypasses git-write
    # (which only sees `git ...`). HELD (a human owns the merge-and-deploy).
    (re.compile(r"\b(?:gh|glab)\s+(?:[\w.-]+\s+)*(?:pr|mr)\s+merge\b|\b(?:gh|glab)\s+release\s+create\b|\b(?:gh|glab)\s+api\b[^\n]*(?:-X|--method)\s+(?:DELETE|PUT|POST)\b"), "high", "code-deploy-or-repo-write"),
    # Overwriting system config files (sed -i / tee / > / dd into /etc) -> HELD. `dd of=/dev/`
    # is caught by IRREVERSIBLE disk-destroy; `dd of=/etc/` is a config overwrite that fell
    # through both (adversarial review f4d494e) — closed here.
    (re.compile(r"\bsed\s+-i\b[^\n]*/etc/|\btee\b[^\n]*/etc/|>\s*/etc/\w|\bdd\b[^\n]*\bof=/etc/"), "high", "config-file-overwrite"),
]

# High reasons that RELAX from POLL_PAUSE to AUTO_NOTICE when the territory gate is live
# (the relevant CLAUDE.md must be loaded + the prediction verdict must match). Operator
# decision 2026-06-25: gate-govern the network/firewall/BGP/AWX tier + service/container
# stop. NOT code-deploy or config-overwrite (HELD), NOT irreversible:* (floor).
_GATE_GOVERNABLE_HIGH = {
    "firewall-write", "asa-write", "swanctl-write", "frr-write", "awx-launch",
    "network-config-write", "service-stop", "container-stop", "lxc-write",
}
# SAFETY BOUNDARY — do NOT add a reason here without understanding it relaxes to AUTO_NOTICE
# when the territory gate is live. Deliberately EXCLUDED (must stay POLL_PAUSE regardless of
# the gate): code-deploy-or-repo-write (unreviewed deploy / ref destruction = human),
# config-file-overwrite (/etc corruption), and every irreversible:* (destruction is never
# gate-governable). In _assign_bands the relaxation requires ALL high reasons to be in this
# set, so any one of the excluded reasons co-occurring forces POLL_PAUSE.

# ── Conservative-remediation carve-out (IFRNLLEI01PRD-1408) ──────────────────────
# Precise REVERSIBLE remediation verbs, carved out of the coarse high MUTATION_PATTERNS
# into a 'mixed' soft-reversible class so they reach AUTO/AUTO_NOTICE. Each regex is the
# conservative form; the destructive sibling is excluded by negative-lookahead and stays
# HIGH. Active ONLY under BOTH AUTONOMY_FORWARD and CONSERVATIVE_REMEDIATION sentinels
# (two gates in series); IRREVERSIBLE_PATTERNS still wins (folded high after the carve).
# Patterns match the conservative VERB only; the destructive sibling is excluded by a
# blob-wide _CONS_BLOCKERS check below (robust across newlines/flags — adversarial review).
CONSERVATIVE_REMEDIATION_PATTERNS = [
    (re.compile(r"\bsystemctl\s+(?:restart|reload|reload-or-restart|try-restart)\b"), "conservative:systemctl-restart"),
    (re.compile(r"\bdocker(?:\s+compose)?\s+restart\b"), "conservative:docker-restart"),
    (re.compile(r"\bkubectl\s+rollout\s+restart\b"), "conservative:kubectl-rollout-restart"),
    (re.compile(r"\bkubectl\s+scale\b[^\n]*--replicas=[1-9]\d*\b"), "conservative:kubectl-scale-up"),
    # A graceful guest reboot (`pct|qm reboot <id>`) is a reversible power-cycle of ONE
    # VM/CT — the classic fix for a wedged guest — distinct from a HOST reboot. Now that
    # system-reboot excludes qm/pct reboot, this only supersedes the qm/pct-write coarse
    # high. NOT qm reset/stop/destroy (those stay HIGH, and block this carve if co-present).
    (re.compile(r"\b(?:pct|qm)\s+reboot\s+\d+\b"), "conservative:guest-restart"),
    (re.compile(r"\bdocker\s+image\s+prune\b"), "conservative:docker-image-prune"),
    (re.compile(r"\bdocker\s+builder\s+prune\b"), "conservative:docker-builder-prune"),
    (re.compile(r"\bfstrim\b"), "conservative:fstrim"),
    (re.compile(r"\bjournalctl\b[^\n]*--vacuum-(?:size|time|files)\b"), "conservative:journal-vacuum"),
    (re.compile(r"\becho\s+[123]\s*>\s*/proc/sys/vm/drop_caches\b"), "conservative:drop-caches"),
    (re.compile(r"\bcertbot\s+renew\b"), "conservative:certbot-renew"),
    (re.compile(r"\brm\b[^\n]*\.(?:lock|pid)\b"), "conservative:stale-lock-rm"),
    (re.compile(r"\bkubectl\s+delete\s+pod\b"), "conservative:pod-delete-reschedule"),
]

# The coarse high MUTATION reason each conservative verb supersedes (removed so it no
# longer forces risk=high). Verbs not listed match no high pattern (already low) — the
# carve just makes the reason explicit so the action is predicted+verified, not skipped.
_CONS_SUPERSEDES = {
    "conservative:systemctl-restart": "systemctl-write",
    "conservative:docker-restart": "docker-write",
    "conservative:kubectl-rollout-restart": "kubectl-write",
    "conservative:kubectl-scale-up": "kubectl-write",
    "conservative:pod-delete-reschedule": "kubectl-write",
    "conservative:stale-lock-rm": "fs-write",
    "conservative:guest-restart": frozenset({"pct-write", "qm-write"}),
}

# Stateful workloads a rollout-restart / scale must NOT auto-touch (restart-during-sync
# / quorum-loss / data-loss risk; e.g. SeaweedFS replication-000). Extend via env csv.
# Broad by design (safety): a statefulset OR any DB/queue/store name -> POLL_PAUSE.
_STATEFUL_DENY_RE = re.compile(
    r"\b(?:etcd|postgres\w*|mysql\w*|mariadb\w*|seaweedfs|thanos|redis\w*|prometheus|"
    r"mongo\w*|cassandra|elasticsearch|opensearch|vault|consul|clickhouse|kafka|"
    r"zookeeper|rabbitmq|nats|minio|influxdb\w*|victoria\w*|loki|cockroach\w*|"
    r"mssql|sqlserver|oracle\w*|couch\w*|neo4j|qdrant|weaviate|valkey|"
    r"percona\w*|proxysql|graylog|"
    r"statefulset|[\w-]+-db|[\w-]+-database)\b|\bsts/", re.IGNORECASE)

# A NON-reboot pct/qm verb co-occurring with a guest reboot is a destructive/disruptive
# guest op (stop/destroy/reset/...) whose coarse pct/qm-write the guest-restart carve
# would otherwise un-protect. If present anywhere, block the carve -> POLL_PAUSE.
_GUEST_DESTRUCTIVE_RE = re.compile(
    r"\b(?:pct|qm)\s+(?:set|start|stop|shutdown|destroy|create|restore|clone|reset|"
    r"rollback|migrate|template|resize|unlink|move[-_]disk)\b")

# Command-scoped reboot detection. A system-reboot reason on the full blob may come from
# prose ("reboot the frozen VM"); the guest-restart carve supersedes it ONLY when the
# executable COMMANDS contain a guest reboot and NO host reboot. Host regex reuses the
# qm/pct lookbehind so `qm reboot` is not mistaken for a host reboot.
_GUEST_REBOOT_CMD_RE = re.compile(r"\b(?:pct|qm)\s+reboot\s+\d+\b")
_HOST_REBOOT_CMD_RE = re.compile(
    r"(?<!qm )(?<!pct )\b(?:reboot|shutdown|halt|poweroff|kexec|init\s+[06])\b")
# A guest reboot inside a loop / fan-out, or 2+ guest reboots in one plan, can take down a
# whole quorum (e.g. all etcd members) — NOT a single-guest power-cycle. Block the carve.
_GUEST_LOOP_RE = re.compile(r"\b(?:for|while|xargs|parallel|seq|ansible|pvesh\s+\w+\s+/cluster)\b")

# The gateway's OWN control-plane services (IFRNLLEI01PRD-1408 follow-up). The conservative carve must
# NOT auto-restart them: the platform-controller owns those restarts externally (Plane-A), and the carve
# runs INSIDE an n8n-orchestrated session, so auto-restarting n8n mid-session can orphan the reconcile. A
# restart TARGETING one of these stays HIGH -> POLL_PAUSE -> human (a deterministic, non-bypassable veto;
# the platform may still restart itself, but the platform-controller does it, not the mission lane).
# Command-scoped (verb + target) so a plan that merely MENTIONS n8n in prose is not over-vetoed; scoped to
# the restart reasons so unrelated carves (fstrim/prune/...) still auto-resolve.
_SELF_PROTECTED_RESTART_RE = re.compile(
    r"\b(?:systemctl\s+(?:restart|reload|reload-or-restart|try-restart)"
    r"|docker(?:\s+compose)?\s+restart"
    r"|kubectl\s+rollout\s+restart(?:\s+\S+)?)\s+[\w./@:-]*\b(?:n8n|cronicle)\b", re.IGNORECASE)
_SELF_PROTECTED_REASONS = frozenset({
    "conservative:systemctl-restart", "conservative:docker-restart",
    "conservative:kubectl-rollout-restart"})


def _stateful_deny_re():
    extra = os.environ.get("AUTONOMY_STATEFUL_DENY", "")
    alts = [re.escape(t.strip()) for t in extra.split(",") if t.strip()]
    if not alts:
        return _STATEFUL_DENY_RE
    return re.compile(_STATEFUL_DENY_RE.pattern[:-2] + "|" + "|".join(alts) + r")\b", re.IGNORECASE)


def _conservative_remediation_patterns():
    pats = list(CONSERVATIVE_REMEDIATION_PATTERNS)
    extra = os.environ.get("AUTONOMY_CONSERVATIVE_EXTRA", "")  # "regex===reason||regex===reason"
    for spec in extra.split("||"):
        spec = spec.strip()
        if "===" in spec:
            rx, reason = spec.split("===", 1)
            try:
                pats.append((re.compile(rx.strip()), "conservative:" + reason.strip()))
            except re.error:
                pass
    return pats


# Blob-wide destructive-sibling blockers (adversarial-review hardening). If a blocker
# matches ANYWHERE in the plan blob, the conservative carve for that reason is SKIPPED
# (the coarse high reason stands -> POLL_PAUSE). Robust across newlines/flags, unlike a
# per-match lookahead: `systemctl restart x\nsystemctl disable x` is correctly blocked.
_CONS_BLOCKERS = {
    "conservative:systemctl-restart": re.compile(r"\bsystemctl\s+(?:disable|mask|stop)\b"),
    "conservative:docker-restart": re.compile(r"\bdocker(?:\s+compose)?\s+(?:down|rm|kill)\b"),
    "conservative:pod-delete-reschedule": re.compile(
        r"\bkubectl\s+delete\b[^\n]*(?:--all|--selector|--field-selector|\s-l\b|\bpvc\b|\bpv\b|\bnamespace\b|\bns\b|\bsecret\b)"
        r"|\bkubectl\s+delete\s+(?:deployment|deploy|statefulset|sts|daemonset|ds|svc|service|node)\b"),
    "conservative:stale-lock-rm": re.compile(r"\brm\b[^\n]*\s-[a-zA-Z]*r"),  # any rm with -r/-rf
    "conservative:kubectl-rollout-restart": _STATEFUL_DENY_RE,
    "conservative:kubectl-scale-up": _STATEFUL_DENY_RE,
    "conservative:guest-restart": _GUEST_DESTRUCTIVE_RE,
}


def _host_reboot_auto():
    """Operator appetite (IFRNLLEI01PRD-1408): a NON-P0 host reboot is AUTO_NOTICE (auto +
    SMS, gate-governed by pve/CLAUDE.md + the verdict) instead of POLL_PAUSE. P0 hosts
    (pve01/03/04, fw01) stay POLL_PAUSE. Sentinel-gated; env override for tests."""
    return os.path.exists(os.environ.get("HOST_REBOOT_AUTO_SENTINEL")
                          or os.path.expanduser("~/gateway.host_reboot_auto"))


def _territory_gate_live():
    """The territory gate (PreToolUse manual prerequisite + Runner backstop) is wired+ON.
    Created last at deploy, so its presence == the FULL gate is live (no unguarded window).
    TERRITORY_GATE_SENTINEL overrides the path so tests never touch the live sentinel."""
    return os.path.exists(os.environ.get("TERRITORY_GATE_SENTINEL")
                          or os.path.expanduser("~/gateway.territory_gate"))


def _cons_blockers():
    """Per-run blockers. A value may be a single regex or a tuple (block if ANY matches).
    Stateful POLL_PAUSE floor (IFRNLLEI01PRD-1408): while the territory gate is LIVE the
    stateful denylist is RELAXED — the gate (k8s/CLAUDE.md etcd/drain rules must be loaded)
    + the infragraph verdict gate govern stateful rollout/scale/reboot instead of a hard
    block. The destructive/irreversible guest-op blocker (qm destroy/reset/...) ALWAYS stays."""
    deny = _stateful_deny_re()
    b = dict(_CONS_BLOCKERS)
    if _territory_gate_live():
        b["conservative:kubectl-rollout-restart"] = None
        b["conservative:kubectl-scale-up"] = None
        b["conservative:guest-restart"] = _GUEST_DESTRUCTIVE_RE  # destructive ops only
    else:
        b["conservative:kubectl-rollout-restart"] = deny
        b["conservative:kubectl-scale-up"] = deny
        b["conservative:guest-restart"] = (_GUEST_DESTRUCTIVE_RE, deny)
    return b


def _assign_bands(result: dict, matched_mutations: list, has_reboot: bool,
                  ig_bump: bool, ig_host: str) -> None:
    """Mutate `result` to add band + auto_proceed_on_timeout + sms_required.

    Called only under AUTONOMY_FORWARD. Assumes irreversible hits were already
    folded into matched_mutations as ('high', 'irreversible:*'), so risk_level
    reflects them. auto_approve_recommended is OVERWRITTEN here to follow the
    band (it remains necessary-not-sufficient: the Runner's prediction/verdict
    gate makes it sufficient).
    """
    risk = result["risk_level"]
    p0 = bool(ig_host) and ig_host in _p0_hosts()
    soft = _soft_reversible()
    high_reasons = [r for lvl, r in matched_mutations if lvl == "high"]
    mixed_reasons = [r for lvl, r in matched_mutations if lvl == "mixed"]
    # Reversible-mixed: there ARE mixed reasons, every one is whitelisted, and no
    # high reason is present (an irreversible/HIGH op would have forced risk=high).
    soft_only = bool(mixed_reasons) and all(r in soft for r in mixed_reasons) and not high_reasons
    # Pure host-reboot high: the only high signal is a bare `reboot`/`shutdown`.
    # system-reboot now excludes pct/qm guest reboots (lookbehind) — a graceful guest
    # reboot is carved reversible — so this is a true HOST reboot, the only high case
    # eligible for the P0 reboot opt-in.
    reboot_only_high = bool(high_reasons) and all(r == "system-reboot" for r in high_reasons)

    if risk == "low":
        band = "AUTO"
    elif risk == "high":
        if reboot_only_high and not p0 and _host_reboot_auto():
            band = "AUTO_NOTICE"            # non-P0 host reboot -> auto + SMS (operator appetite)
        elif reboot_only_high and p0 and _envflag("AUTONOMY_P0_REBOOT_AUTO"):
            band = "AUTO_NOTICE"            # operator opted P0 reboots into auto+SMS
        elif (high_reasons and all(r in _GATE_GOVERNABLE_HIGH for r in high_reasons)
              and _territory_gate_live()):
            # Network/firewall/BGP/AWX + service/container-stop, gate-governed: the territory
            # CLAUDE.md must be loaded (PreToolUse hook) + the verdict must match. A floor
            # reason (irreversible:*, code-deploy, config-overwrite) is NOT gate-governable,
            # so its co-occurrence drops out of `all(...)` -> POLL_PAUSE (IFRNLLEI01PRD-1408).
            band = "AUTO_NOTICE"
        else:
            band = "POLL_PAUSE"             # floor (incl. P0 host reboot)
    elif risk == "mixed" and soft_only:
        # Reversible + prediction-eligible -> auto-resolve. Elevated reversibles
        # (P0 host OR wide blast >= threshold) auto-proceed WITH a parallel SMS
        # page so the operator can veto out-of-band (AUTO_NOTICE); narrow
        # reversibles resolve silently (AUTO). This is the operator's Q1 intent
        # delivered directly: reversible work never stalls on an unwatched poll.
        # (POLL_PROCEED is retained as a reserved band but no longer assigned —
        # the bridge's timeout-pause only engages the 'awaiting-approval' text
        # flow, not the [POLL] flow this band would use, and the operator watches
        # SMS not polls; see docs/runbooks/risk-based-auto-approval.md.)
        band = "AUTO_NOTICE" if (p0 or ig_bump) else "AUTO"
    else:
        band = "POLL_PAUSE"                 # non-soft mixed / high / unknown -> pause + (if high) SMS

    result["band"] = band
    result["auto_approve_recommended"] = band in ("AUTO", "AUTO_NOTICE")
    result["auto_proceed_on_timeout"] = band != "POLL_PAUSE"
    result["sms_required"] = (risk == "high") or (band == "AUTO_NOTICE")
    # P0 critical signals for the SMS gate — host-membership based, so they hold
    # even when Infragraph is unavailable (fail-open advisory).
    if p0 and ig_bump:
        result["signals"].append(f"critical:blast-radius-p0:{ig_host}")
    if has_reboot and p0 and band == "POLL_PAUSE":
        result["signals"].append("critical:p0-reboot")


# IFRNLLEI01PRD-718 (Phase F of the agents-cli authoring-discipline uplift):
# Evidence-first enforcement. A reply that claims CONFIDENCE ≥ 0.8 but does
# not ship any concrete output (no triple-backtick code fence) is
# under-documented — force [POLL] so a human reviews the claim. Helper is
# also exposed via `--check-evidence` mode so the Runner can call it at
# Prepare-Result time against the final reply (not just the plan).
HIGH_CONFIDENCE_RE = re.compile(
    r"CONFIDENCE:\s*(0\.[89]\d*|1(?:\.0+)?)\b", re.IGNORECASE
)
CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)


def check_evidence(text: str) -> tuple[bool, str]:
    """Return (missing, reason).

    missing=True when the reply claims CONFIDENCE ≥ 0.8 AND does not include
    a fenced code block. Always returns (False, "") for short/empty text.
    """
    if not text or len(text) < 20:
        return False, ""
    m = HIGH_CONFIDENCE_RE.search(text)
    if not m:
        return False, ""
    confidence_literal = m.group(1)
    if CODE_FENCE_RE.search(text):
        return False, ""
    return True, f"high_confidence_no_code_fence:{confidence_literal}"


# Read-only patterns that are SAFE (not bringing the level up).
# Informational only — helps explain why we landed on LOW.
READ_ONLY_MARKERS = [
    (re.compile(r"\b(kubectl|k)\s+(get|describe|logs|top|auth\s+can-i|explain|diff)\b"), "kubectl-read"),
    (re.compile(r"\bpct\s+(list|config|status)\b"), "pct-read"),
    (re.compile(r"\bqm\s+(list|config|status)\b"), "qm-read"),
    (re.compile(r"\b(journalctl|dmesg|last|who|w|uptime|ps|top|htop|free|df|du|lsof|ss|ip\s+addr|ip\s+route|ping|traceroute|curl\s+-[sSI]|wget\s+--spider)\b"), "diagnostic-read"),
    (re.compile(r"\bshow\s+(run|interface|crypto|bgp|ip\s+route|access-list|logging|tech-support|version|running-config)\b"), "cisco-read"),
    (re.compile(r"\bvtysh.*-c\s+['\"]show\b"), "frr-read"),
    (re.compile(r"\bswanctl\s+--list-"), "swanctl-read"),
    (re.compile(r"\b(sqlite3.*SELECT|grep|awk|sed|cat|head|tail|less|more|wc|sort|uniq|diff)\b"), "text-read"),
]


INFRAGRAPH_BLAST_THRESHOLD = int(os.environ.get("INFRAGRAPH_BLAST_THRESHOLD", "8"))


def _infragraph_signal(hostname: str) -> tuple[str | None, bool, dict | None]:
    """Advisory blast-radius signal + compact context (IFRNLLEI01PRD-1036/-1038).

    Returns (signal, bump, context). bump=True means "raise low -> mixed" —
    the signal only ever RAISES risk, never lowers it, and any failure
    (disabled, host unknown, timeout, graph empty) degrades to
    ("infragraph:unavailable", False, None) with classification otherwise
    unaffected. Fail-open by contract.

    context is a compact machine-computed dependency summary the Runner's
    Build Prompt renders into the Tier 2 prompt (result["infragraph"]) — the
    orchestrator computes predictions, the LLM only consumes them.
    """
    if not hostname:
        return None, False, None
    if os.environ.get("INFRAGRAPH_DISABLED", "") not in ("", "0"):
        return None, False, None
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "infragraph-query.py")
    try:
        proc = subprocess.run(
            [sys.executable, cli, "blast-radius", "--host", hostname],
            capture_output=True, timeout=5, check=False)
        if proc.returncode != 0:
            return "infragraph:unavailable", False, None
        blast = json.loads(proc.stdout)
        n = int(blast["counts"]["total"])
        context = {
            "host": hostname,
            "blast_radius_total": n,
            "by_type": blast["counts"].get("by_type", {}),
            "top_affected": [x["name"] for x in (blast.get("nodes") or [])[:6]],
        }
        cas = subprocess.run(
            [sys.executable, cli, "cascade", "--host", hostname],
            capture_output=True, timeout=5, check=False)
        if cas.returncode == 0:
            cj = json.loads(cas.stdout)
            context["window_seconds"] = cj.get("window_seconds")
            context["cascade"] = [
                {"host": p["host"], "rule": p["rule"],
                 "confidence": p["confidence"], "source": p.get("source", "")}
                for p in (cj.get("predictions") or [])[:8]
            ]
        if n >= INFRAGRAPH_BLAST_THRESHOLD:
            return f"infragraph:blast-radius-high({n})", True, context
        return f"infragraph:blast-radius({n})", False, context
    except Exception:  # noqa: BLE001 — advisory path, never block classification
        return "infragraph:unavailable", False, None


# ── OOD / novel-incident gate (IFRNLLEI01PRD-1448) ──────────────────────────────
#
# A genuinely NOVEL incident class must not auto-resolve. "Novel" = there is no
# learned prior for this (host, rule)/alert signature, so the orchestrator has no
# verified precedent (no matching incident_knowledge resolution, no prior auto-
# resolve outcome) to lean on. The autonomy gate is designed for the REPEAT case
# (a known, reversible, predicted pattern); the first time we ever see a class,
# force a human into the loop.
#
# SAFE-DIRECTION ONLY: this can only RAISE review (force band=POLL_PAUSE). It never
# relaxes a band, never lowers risk_level. Gated behind AUTONOMY_FORWARD exactly
# like the band engine, so with the flag OFF the stdout JSON is byte-identical to
# legacy. Two novelty sources, cheapest-first:
#
#   1. An explicit caller signal — plan["prior_incidents"] or env PRIOR_INCIDENTS
#      (an int). == 0  => novel. This is the preferred path: the upstream (Runner
#      Build Prompt / build-investigation-plan.sh) already counts prior incidents
#      for the Tier-2 prompt, so passing that count in costs nothing and avoids a
#      DB round-trip in the n8n SSH node.
#   2. DB fallback — COUNT(*) over incident_knowledge for the (host, alert_rule)
#      signature. == 0  => novel. Used only when no explicit signal is available
#      AND we have BOTH a host and an alert_rule to key on.
#
# If neither source is usable (no explicit count, and no host+rule to query),
# novelty is UNKNOWN and the gate does NOT fire — we never invent a POLL from
# missing data (no false positives). That case is flagged for upstream wiring.

def _ood_novelty(plan: dict) -> tuple[bool, str]:
    """Return (is_novel, reason). is_novel=True only when we can POSITIVELY
    establish the incident class has no prior. Never raises."""
    # 1) Explicit prior-incident count signal (caller-provided).
    raw = plan.get("prior_incidents")
    if raw is None:
        raw = os.environ.get("PRIOR_INCIDENTS")
    if raw is not None and str(raw).strip() != "":
        try:
            n = int(str(raw).strip())
            if n <= 0:
                return True, "prior_incidents=0"
            return False, f"prior_incidents={n}"
        except (TypeError, ValueError):
            pass  # unparseable -> fall through to DB / unknown

    # 2) DB fallback — COUNT incident_knowledge rows for this (host, rule).
    host = plan.get("hostname") or os.environ.get("ALERT_HOSTNAME", "")
    rule = plan.get("alert_rule") or os.environ.get("ALERT_RULE", "")
    host = host.strip() if isinstance(host, str) else ""
    rule = rule.strip() if isinstance(rule, str) else ""
    if not host or not rule:
        return False, "novelty-unknown:no-prior-signal"  # cannot determine -> do not fire
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            pass
        # Host-specific OR host-agnostic ('*') learned suppression both count as a
        # known prior for this rule. Match the rule exactly + the host (or wildcard).
        row = conn.execute(
            "SELECT COUNT(*) FROM incident_knowledge "
            "WHERE alert_rule = ? AND (hostname = ? OR hostname = '*')",
            (rule, host),
        ).fetchone()
        conn.close()
        n = int(row[0]) if row else 0
        if n == 0:
            return True, f"no-incident-knowledge:{host}/{rule}"
        return False, f"incident-knowledge={n}:{host}/{rule}"
    except sqlite3.Error:
        # DB unavailable -> cannot positively establish novelty -> do NOT force a
        # POLL on a DB hiccup (fail toward existing behavior, not toward noise).
        return False, "novelty-unknown:db-error"


def classify(plan: dict, alert_category: str) -> dict[str, Any]:
    """Return classification dict. Does not raise; always yields a result."""
    cat = (alert_category or "generic").lower().strip()
    signals: list[str] = [f"category:{cat}"]
    matched_mutations: list[tuple[str, str]] = []  # (risk, reason)
    matched_read_only: list[str] = []

    # Concatenate all plan-contained text so a single regex pass covers
    # hypothesis + every step + tools_needed + awx_templates.
    blob_parts = []
    for key in ("hypothesis", "reason"):
        v = plan.get(key)
        if isinstance(v, str):
            blob_parts.append(v)
    for step in plan.get("steps", []) or []:
        if isinstance(step, str):
            blob_parts.append(step)
        elif isinstance(step, dict):
            for k in ("description", "action", "command", "hint"):
                if isinstance(step.get(k), str):
                    blob_parts.append(step[k])
    for t in plan.get("tools_needed", []) or []:
        if isinstance(t, str):
            blob_parts.append(t)
    for tmpl in plan.get("awx_templates", []) or []:
        if isinstance(tmpl, dict):
            blob_parts.append(tmpl.get("name", ""))
            blob_parts.append(tmpl.get("description", ""))
        elif isinstance(tmpl, str):
            blob_parts.append(tmpl)
    blob = " \n ".join(blob_parts)
    # Action view — EVERY step field the executing session can act on (command/action/
    # description/hint + bare string steps + tool names), EXCLUDING only the top-level
    # hypothesis/reason prose. Lets the guest-restart carve tell a real host reboot (in any
    # action field) from the word "reboot" in background prose. A host reboot hidden in a
    # step.description must NOT be superseded — the session reads descriptions too.
    _action_parts = []
    for _s in (plan.get("steps") or []):
        if isinstance(_s, str):
            _action_parts.append(_s)
        elif isinstance(_s, dict):
            for _k in ("command", "action", "description", "hint"):
                if isinstance(_s.get(_k), str):
                    _action_parts.append(_s[_k])
    for _t in (plan.get("tools_needed") or []):
        if isinstance(_t, str):
            _action_parts.append(_t)
    step_blob = " \n ".join(_action_parts)
    # Collapse runs of spaces/tabs so `qm  reboot` == `qm reboot` for the fixed-width
    # lookbehind in the reboot regexes (defends the variable-spacing bypass).
    _step_norm = re.sub(r"[ \t]+", " ", step_blob)

    # Inline jailbreak / prompt-injection screen (IFRNLLEI01PRD-1096): bring the
    # jailbreak detector (previously nightly-corpus-only) onto the live prompt
    # path. A detection forces HIGH risk so the session can NEVER auto-approve
    # (fail-closed).
    try:
        from lib.jailbreak_detector import detect_all as _jb_detect
    except Exception:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
            from jailbreak_detector import detect_all as _jb_detect
        except Exception:
            _jb_detect = None
    # Screen for prompt-injection on the UNTRUSTED NARRATIVE only (hypothesis/reason, which
    # echo the alert/operator text) — NOT the system-generated step commands. A legit
    # remediation step ("reboot the VM to recover it") is the system's OWN action, not a
    # buried injection; screening the full plan made lost-in-middle-bait fire on ~55 legit
    # plans/7d (the action sits at the end of a long triage narrative). The detector itself
    # is unchanged (still catches a real buried instruction in untrusted input; corpus
    # untouched) — only WHAT it is pointed at is scoped (IFRNLLEI01PRD-1408 jailbreak FP).
    _jb_input = " \n ".join(str(plan.get(k, "")) for k in ("hypothesis", "reason")
                            if isinstance(plan.get(k), str))
    if _jb_detect and _jb_input:
        try:
            _jb = _jb_detect(_jb_input)
        except Exception:
            _jb = []
        if _jb:
            _names = ",".join(sorted({d[0] for d in _jb})[:4])
            matched_mutations.append(("high", f"jailbreak-detected:{_names}"))

    # AWX remediation runbooks AVAILABLE != remediation PLANNED. build-investigation-
    # plan.sh attaches the category's applicable runbooks as context to EVERY plan, so
    # treating their mere presence as MIXED forced 100% of sessions to POLL_PAUSE and the
    # autonomy gate never auto-resolved anything. Risk is the PLANNED work: an actual awx
    # launch in a step is caught by the awx-launch MUTATION_PATTERN below (-> high);
    # merely-available runbooks are a transparency signal only. (An AUTO-band session
    # whose planned steps are read-only still emits [POLL] at runtime if it decides a
    # mutation/runbook is actually needed — Build Prompt instructs this.)
    if plan.get("awx_templates"):
        signals.append(f"awx-runbooks-available:{len(plan['awx_templates'])}")

    for pat, level, reason in MUTATION_PATTERNS:
        if pat.search(blob):
            matched_mutations.append((level, reason))
    for pat, reason in READ_ONLY_MARKERS:
        if pat.search(blob):
            matched_read_only.append(reason)

    # >>> IFRNLLEI01PRD-1408: conservative-remediation carve-out. A conservative
    # reversible verb SUPERSEDES the coarse 'high' MUTATION reason it overrides
    # (re-tagged 'mixed' soft-reversible -> reaches AUTO). Runs BEFORE the irreversible
    # fold below: a co-occurring irreversible token re-adds 'high' and defeats soft_only
    # -> POLL_PAUSE. Gated behind BOTH AUTONOMY_FORWARD and CONSERVATIVE_REMEDIATION
    # sentinels (dark by default); flag-off => byte-identical legacy.
    # Territory + stateful-target resolution (IFRNLLEI01PRD-1408 territory gate). Gated
    # behind AUTONOMY_FORWARD so flag-off output stays byte-identical legacy.
    _stateful_target = False
    if _envflag("AUTONOMY_FORWARD"):
        try:
            import territory as _terr_lib
            _thost = plan.get("hostname") or os.environ.get("ALERT_HOSTNAME", "")
            _vmids = re.findall(r"\b(?:pct|qm)\s+reboot\s+(\d+)", _step_norm)
            _ti = _terr_lib.resolve(host=_thost, command=step_blob,
                                    vmid=_vmids[0] if _vmids else None)
            _stateful_target = bool(_ti.get("is_stateful"))
            for _v in _vmids[1:]:
                if _terr_lib.resolve(vmid=_v).get("is_stateful"):
                    _stateful_target = True
            if _ti.get("territory"):
                signals.append("territory:" + _ti["territory"])
            if _stateful_target:
                signals.append("territory:stateful-target")
        except Exception:  # noqa: BLE001 — advisory; never block classification
            pass

    if _envflag("AUTONOMY_FORWARD") and _envflag("CONSERVATIVE_REMEDIATION"):
        _blockers = _cons_blockers()
        cons_hits = []
        for _pat, _reason in _conservative_remediation_patterns():
            if not _pat.search(blob):
                continue
            _blk = _blockers.get(_reason)
            if _blk is not None:
                _bset = _blk if isinstance(_blk, tuple) else (_blk,)
                if any(b.search(blob) for b in _bset):
                    continue  # destructive sibling or stateful target co-occurs anywhere -> stays HIGH
            if _reason in _SELF_PROTECTED_REASONS and _SELF_PROTECTED_RESTART_RE.search(blob):
                continue  # restart targets the gateway's OWN control plane (n8n/cronicle) -> POLL_PAUSE
            if _reason == "conservative:guest-restart" and (
                    _GUEST_LOOP_RE.search(_step_norm)
                    or len(_GUEST_REBOOT_CMD_RE.findall(_step_norm)) >= 2):
                continue  # multi-guest reboot (loop / 2+ targets) = quorum risk -> POLL_PAUSE
            cons_hits.append(_reason)
        if cons_hits:
            _superseded = set()
            for h in cons_hits:
                sup = _CONS_SUPERSEDES.get(h)
                if isinstance(sup, str):
                    _superseded.add(sup)
                elif sup:
                    _superseded.update(sup)  # frozenset (e.g. guest-restart -> qm/pct-write)
            # A guest reboot COMMAND + NO host reboot COMMAND => any system-reboot reason is
            # prose-induced ("reboot the frozen VM"), not an action — supersede it so the
            # guest reboot reaches AUTO. A real host-reboot command keeps system-reboot HIGH.
            if ("conservative:guest-restart" in cons_hits
                    and _GUEST_REBOOT_CMD_RE.search(_step_norm)
                    and not _HOST_REBOOT_CMD_RE.search(_step_norm)):
                _superseded.add("system-reboot")
            matched_mutations = [(lvl, r) for (lvl, r) in matched_mutations if r not in _superseded]
            for h in cons_hits:
                matched_mutations.append(("mixed", h))
            signals.append("conservative-carve:" + ",".join(sorted(cons_hits)))
    # <<< IFRNLLEI01PRD-1408

    # IFRNLLEI01PRD-1103: irreversible/destructive detection. has_reboot is always
    # computed (cheap, no output effect); the irreversible re-tagging is folded in
    # ONLY under AUTONOMY_FORWARD so legacy output stays byte-identical. Folding as
    # ('high', ...) before the risk decision means risk_level reflects them.
    irreversible_hits = [reason for pat, reason in IRREVERSIBLE_PATTERNS if pat.search(blob)]
    has_reboot = bool(REBOOT_RE.search(blob))
    if _envflag("AUTONOMY_FORWARD"):
        for _r in irreversible_hits:
            matched_mutations.append(("high", _r))
        # IFRNLLEI01PRD-1408 blind-spot closures (folded under AUTONOMY_FORWARD only, so
        # flag-off legacy stays byte-identical). Gate-governable highs relax in _assign_bands.
        for _pat, _lvl, _r in _AUTONOMY_BLINDSPOT_PATTERNS:
            if _pat.search(blob):
                matched_mutations.append((_lvl, _r))

    # IFRNLLEI01PRD-718: if the plan carries a draft / proposed reply, audit
    # it for the evidence-first invariant. Any claim of CONFIDENCE ≥ 0.8 in
    # the reply must ship a code-fence; otherwise signal + bump to mixed.
    evidence_missing = False
    evidence_reason = ""
    draft = plan.get("draft_reply") or plan.get("proposed_reply") or ""
    if isinstance(draft, str) and draft:
        evidence_missing, evidence_reason = check_evidence(draft)
        if evidence_missing:
            matched_mutations.append(("mixed", f"evidence_missing:{evidence_reason}"))

    # Decide risk
    if cat in HIGH_RISK_CATEGORIES:
        signals.append("category-high-risk-default")
        risk = "high"
    elif any(level == "high" for level, _ in matched_mutations):
        risk = "high"
    elif matched_mutations:
        risk = "mixed"
    elif cat in LOW_LEAN_CATEGORIES:
        risk = "low"
    else:
        # Unknown category with no mutation signals — conservative default
        risk = "mixed"
        signals.append("unknown-category-default")

    for level, reason in matched_mutations:
        signals.append(f"{level}:{reason}")
    for reason in matched_read_only[:5]:  # cap to keep signal list tight
        signals.append(f"read-only:{reason}")

    # Infragraph advisory (IFRNLLEI01PRD-1036/-1038): a wide blast radius
    # bumps a low-risk plan to mixed (forces [POLL]); it never lowers risk.
    # The compact context object rides along for Build Prompt to render.
    ig_host = plan.get("hostname") or os.environ.get("ALERT_HOSTNAME", "")
    ig_signal, ig_bump, ig_context = _infragraph_signal(
        ig_host if isinstance(ig_host, str) else "")
    if ig_signal:
        signals.append(ig_signal)
        if ig_bump and risk == "low":
            risk = "mixed"

    plan_hash = hashlib.sha256(
        json.dumps(plan, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]

    result: dict[str, Any] = {
        "risk_level": risk,
        "auto_approve_recommended": risk == "low",
        "signals": signals,
        "plan_hash": plan_hash,
    }
    if ig_context:
        result["infragraph"] = ig_context

    # IFRNLLEI01PRD-1103: autonomy-forward band assignment (default OFF => no-op,
    # output byte-identical to legacy). Adds band / auto_proceed_on_timeout /
    # sms_required and overwrites auto_approve_recommended to follow the band.
    if _envflag("AUTONOMY_FORWARD"):
        _assign_bands(result, matched_mutations, has_reboot, ig_bump,
                      ig_host if isinstance(ig_host, str) else "")
        # IFRNLLEI01PRD-1448: OOD / novel-incident gate. A genuinely novel incident
        # class (no learned prior for this (host,rule)/alert signature, or an explicit
        # prior_incidents==0 signal) has no verified precedent for the orchestrator to
        # auto-resolve against — force the human into the loop. SAFE-DIRECTION ONLY:
        # it can only DEMOTE an auto/proceed band to the POLL_PAUSE floor, never relax.
        # Applied AFTER _assign_bands so it overrides whatever band was chosen. Runs
        # only under AUTONOMY_FORWARD (the band engine's own gate), so flag-off output
        # stays byte-identical to legacy.
        is_novel, novel_reason = _ood_novelty(plan)
        if is_novel and result.get("band") != "POLL_PAUSE":
            result["band"] = "POLL_PAUSE"
            result["auto_approve_recommended"] = False
            result["auto_proceed_on_timeout"] = False
            # Keep SMS behavior monotonic: a HIGH-risk demotion still pages; we never
            # un-set an existing sms_required, but a novel demotion does not by itself
            # add an SMS page (the operator watches POLLs for novel classes).
            result["sms_required"] = bool(result.get("sms_required"))
            result["signals"].append(f"ood:novel-incident:{novel_reason}")
        elif is_novel:
            # Already POLL_PAUSE — just record the novelty signal for the audit trail.
            result["signals"].append(f"ood:novel-incident:{novel_reason}")
    # IFRNLLEI01PRD-1665 (silent-cognition guard, repositioned to Phase 5): emit a flag
    # the Runner's Prepare Result node reads to decide whether to suppress an
    # [AUTO-RESOLVE] that ships NO fenced post-state evidence at ANY confidence (the
    # J4 evidence-missing check only catches CONFIDENCE>=0.8). n8n Code nodes cannot
    # read ~/gateway.* sentinels, so this threads the sentinel state Phase 4 -> Phase 5.
    # Emitted ONLY when the sentinel is live => sentinel-off output is byte-identical.
    if _envflag("SILENT_COGNITION_GUARD"):
        result["silent_cognition_guard"] = True
    # IFRNLLEI01PRD-1824 (MUTATIONS=OFF shadow mode): when the operator has frozen actuation, the
    # classifier still reasons fully but MUST NOT recommend any auto-resolve — the whole system is
    # log-only. Placed OUTSIDE the AUTONOMY_FORWARD block so it dominates in BOTH flag states: with
    # the band engine on it demotes to POLL_PAUSE; with it off it still kills the legacy risk=='low'
    # auto path. The REAL YT-Done clamp lives in reconcile-completed-sessions.py (it re-derives auto
    # from the raw [AUTO-RESOLVE] text independently of band). Sentinel = ~/gateway.mutations_off.
    if _envflag("MUTATIONS_OFF"):
        result["mutations_off"] = True
        result["auto_approve_recommended"] = False
        if "band" in result:
            result["band"] = "POLL_PAUSE"
            result["auto_proceed_on_timeout"] = False
        result["signals"].append("shadow:mutations_off")
    return result


# ── Audit table ───────────────────────────────────────────────────────────────


def _audit_connect():
    """Lock-robust connection for the audit table. IFRNLLEI01PRD-1102 follow-up:
    the prior `timeout=5` lost the SQLite write-lock race under production load on
    the 455 MB WAL gateway.db — the write `except` swallowed SQLITE_BUSY, so the
    classification still returned (band reached Build Prompt) but NO audit row
    persisted (session_risk_audit sat empty despite the gate running). 30 s +
    explicit busy_timeout mirrors the documented teacher-agent fix
    (feedback_sqlite_busy_timeout)."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except sqlite3.Error:
        pass
    return conn


def _ensure_audit_schema():
    try:
        conn = _audit_connect()
        conn.execute(
            """CREATE TABLE IF NOT EXISTS session_risk_audit (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id          TEXT NOT NULL,
                classified_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
                alert_category    TEXT,
                risk_level        TEXT NOT NULL,
                auto_approved     INTEGER NOT NULL DEFAULT 0,
                signals_json      TEXT,
                plan_hash         TEXT,
                operator_override TEXT,
                schema_version    INTEGER DEFAULT 1
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_risk_audit_issue ON session_risk_audit(issue_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_risk_audit_time ON session_risk_audit(classified_at)"
        )
        # IFRNLLEI01PRD-1108: additive band columns (idempotent — SQLite has no
        # ADD COLUMN IF NOT EXISTS, so guard via PRAGMA). NULL = legacy row.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(session_risk_audit)")}
        for col, decl in (("band", "TEXT"),
                          ("auto_proceed_on_timeout", "INTEGER"),
                          ("sms_required", "INTEGER"),
                          ("prev_hash", "TEXT"),   # governance tamper-evidence: hash-chain (migration 021)
                          ("row_hash", "TEXT")):
            if col not in existing:
                conn.execute(f"ALTER TABLE session_risk_audit ADD COLUMN {col} {decl}")
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[classify] schema init failed: {e}", file=sys.stderr)


def write_audit_row(issue_id: str, category: str, result: dict,
                    auto_approved: bool, operator_override: str | None = None):
    _ensure_audit_schema()
    params = (
        issue_id or "unknown", category, result["risk_level"],
        1 if auto_approved else 0,
        json.dumps(result.get("signals", [])),
        result.get("plan_hash"),
        operator_override,
        schema_current("session_risk_audit"),
        result.get("band"),
        (1 if result["auto_proceed_on_timeout"] else 0) if "auto_proceed_on_timeout" in result else None,
        (1 if result["sms_required"] else 0) if "sms_required" in result else None,
    )
    sql = """INSERT INTO session_risk_audit
                (issue_id, alert_category, risk_level, auto_approved,
                 signals_json, plan_hash, operator_override, schema_version,
                 band, auto_proceed_on_timeout, sms_required, prev_hash, row_hash)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    # Tamper-evident hash-chain (bench IFRNLLEI01PRD-1422 governance gap): each decision row binds its
    # content to the prior row's hash, so deleting/altering/reordering the audit log is mechanically
    # detectable (scripts/verify-governance-chain.py). BEGIN IMMEDIATE serializes the read-prev+insert so
    # concurrent classifier writers can't fork the chain. Retry once on a transient lock so the spike
    # doesn't drop the row.
    last_err = None
    for attempt in (1, 2):
        conn = None
        try:
            conn = _audit_connect()
            conn.isolation_level = None  # manual txn mode so BEGIN IMMEDIATE actually drives the lock
            conn.execute("BEGIN IMMEDIATE")
            _prev = conn.execute(
                "SELECT row_hash FROM session_risk_audit WHERE row_hash IS NOT NULL AND row_hash != '' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = _prev[0] if (_prev and _prev[0]) else "GENESIS"
            row_hash = hashlib.sha256(
                ("|".join([prev_hash] + [str(p) for p in params])).encode("utf-8")).hexdigest()
            cur = conn.execute(sql, params + (prev_hash, row_hash))
            conn.execute("COMMIT")
            row_id = cur.lastrowid
            conn.close()
            _dbg("audit_write", outcome="ok", issue_id=issue_id or "unknown",
                 row_id=row_id, risk=result.get("risk_level"),
                 band=result.get("band"), auto_approved=bool(auto_approved),
                 attempt=attempt, db=DB_PATH)
            return
        except sqlite3.OperationalError as e:
            if conn is not None:
                try: conn.execute("ROLLBACK")
                except Exception: pass
                try: conn.close()
                except Exception: pass
            last_err = e
            if attempt == 1 and "lock" in str(e).lower():
                time.sleep(0.5)
                continue
            break
        except sqlite3.Error as e:
            if conn is not None:
                try: conn.execute("ROLLBACK")
                except Exception: pass
                try: conn.close()
                except Exception: pass
            last_err = e
            break
    _dbg("audit_write", outcome="failed", issue_id=issue_id or "unknown",
         err=f"{type(last_err).__name__}:{last_err}", db=DB_PATH)
    print(f"[classify] audit write failed (after retry): {last_err}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", help="path to plan JSON file; otherwise read stdin")
    ap.add_argument("--category",
                    default=os.environ.get("ALERT_CATEGORY", "generic"))
    ap.add_argument("--issue-id", default=os.environ.get("ISSUE_ID", ""))
    ap.add_argument("--no-audit", action="store_true",
                    help="skip writing to session_risk_audit (dry-run)")
    ap.add_argument("--override",
                    help="operator override reason (forces risk=high)")
    ap.add_argument("--check-evidence", action="store_true",
                    help="run only the evidence-first check on stdin text; emit JSON and exit")
    args = ap.parse_args()

    # Invocation context — the n8n SSH node's env is where the silent failures hide
    # (unset HOME => sentinel-based autonomy flag resolves OFF; wrong GATEWAY_DB =>
    # rows land elsewhere). Always logged so the env is visible per classification.
    _dbg("invoke",
         category=args.category, issue_id=args.issue_id or "",
         no_audit=args.no_audit, check_evidence=args.check_evidence,
         plan_file=args.plan or "", override=bool(args.override),
         home=os.environ.get("HOME", "<unset>"), cwd=os.getcwd(),
         gateway_db=DB_PATH,
         autonomy_sentinel=os.path.expanduser("~/gateway.autonomy_forward"),
         autonomy_forward=_envflag("AUTONOMY_FORWARD"),
         risk_fail_closed=os.environ.get("RISK_FAIL_CLOSED", ""))

    # IFRNLLEI01PRD-718: standalone evidence check. Reads reply text from
    # stdin, emits {"evidence_missing": bool, "reason": str, "force_poll": bool}.
    # For use by Runner Prepare-Result at reply time (the classifier proper
    # runs at plan time, so plans don't have the final reply).
    if args.check_evidence:
        try:
            reply = sys.stdin.read()
        except Exception as e:
            print(json.dumps({"evidence_missing": False, "reason": f"read-error:{e}", "force_poll": False}))
            sys.exit(1)
        missing, reason = check_evidence(reply)
        print(json.dumps({
            "evidence_missing": missing,
            "reason": reason,
            "force_poll": missing,
        }))
        sys.exit(0)

    # Read raw first (then parse) so a parse failure can log the EXACT bytes the
    # classifier received — this is what reveals a broken upstream node command
    # (e.g. the n8n "base64: invalid input" that fail-closed every session).
    try:
        if args.plan:
            with open(args.plan) as f:
                raw = f.read()
        else:
            raw = sys.stdin.read()
    except Exception as e:  # noqa: BLE001
        raw = ""
        _dbg("stdin_read_error", source=("file" if args.plan else "stdin"),
             err=f"{type(e).__name__}:{e}")
    _dbg("stdin", source=("file" if args.plan else "stdin"), length=len(raw),
         head=(raw if os.environ.get("GATEWAY_DEBUG") == "1" else raw[:160]))
    try:
        if not raw.strip():
            raise ValueError("empty plan (no stdin received)")
        plan = json.loads(raw)
    except Exception as e:
        fail_closed = os.environ.get("RISK_FAIL_CLOSED") == "1"
        _dbg("plan_parse_fail", err=f"{type(e).__name__}:{e}",
             raw_len=len(raw), raw_head=raw[:300],
             fail_closed=fail_closed, issue_id=args.issue_id or "",
             audit="skipped:fail_closed_exit" if fail_closed else "skipped:exit1")
        if fail_closed:
            print(json.dumps({
                "risk_level": "high",
                "auto_approve_recommended": False,
                "signals": [f"fail-closed:{type(e).__name__}"],
                "plan_hash": None,
            }))
            sys.exit(2)
        print(f"error parsing plan: {e}", file=sys.stderr)
        sys.exit(1)

    result = classify(plan, args.category)
    _dbg("classified", issue_id=args.issue_id or "", category=args.category,
         risk=result.get("risk_level"), band=result.get("band"),
         auto_approve=result.get("auto_approve_recommended"),
         sms_required=result.get("sms_required"),
         signals=result.get("signals", []))

    # Operator override force-bumps to high (and to the POLL_PAUSE floor + SMS
    # when autonomy-forward bands are active).
    if args.override:
        result["risk_level"] = "high"
        result["auto_approve_recommended"] = False
        result["signals"].append(f"operator-override:{args.override[:40]}")
        if "band" in result:
            result["band"] = "POLL_PAUSE"
            result["auto_proceed_on_timeout"] = False
            result["sms_required"] = True

    auto_approve = result["auto_approve_recommended"]
    if not args.no_audit:
        write_audit_row(args.issue_id, args.category, result,
                        auto_approve, args.override)
        # IFRNLLEI01PRD-1105: page the operator on critical bands (sms_required:
        # HIGH / P0 auto-proceed / deviation). Only on real classifications
        # (not --no-audit dry-runs), only when autonomy-forward is enabled.
        if result.get("sms_required") and _envflag("AUTONOMY_FORWARD"):
            _dbg("sms_fire", issue_id=args.issue_id or "", band=result.get("band"))
            _fire_session_sms(args.issue_id, plan, result)
    else:
        _dbg("audit_write", outcome="skipped", reason="no_audit_flag",
             issue_id=args.issue_id or "")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
