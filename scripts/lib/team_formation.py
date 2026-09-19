"""Team-formation rule library (IFRNLLEI01PRD-750 / G3.P1.2).

Given an alert (category, risk_level, hostname), propose a roster of sub-agents
with explicit roles. Pure-rule, no LLM, deterministic. Used by Build Prompt at
session start to emit a `team_charter` event so the implicit multi-agent graph
becomes inspectable in event_log + Grafana.

Closes NVIDIA-DLI dim #5 sub-pattern (CrewAI-style persona-team formation) per
docs/nvidia-dli-cross-audit-2026-04-29.md Part F P1.2. The agent selections
mirror Anthropic's "orchestrator-workers" pattern documented in
.claude/agents/*.md and indexed by `scripts/audit-skill-requires.sh`.

Usage:

    from team_formation import propose_team
    charter = propose_team("availability", "low", hostname="nl-pve01")
    # → {
    #     "category": "availability",
    #     "risk_level": "low",
    #     "rationale": "...",
    #     "agents": [
    #         {"agent": "triage-researcher", "role": "fact-gathering",
    #          "when": "phase 0", "rationale": "..."},
    #         ...
    #     ],
    #   }

Output is stable JSON (sorted keys via tuple ordering in lists). The caller
(Build Prompt) base64-injects the JSON into the prompt and emits the same JSON
as a `team_charter` event payload.
"""
from __future__ import annotations

REDACTED_a7b84d63
from typing import NamedTuple

# ── Agent inventory (kept in sync with `.claude/agents/*.md`) ────────────────
#
# Every agent listed here MUST have a corresponding `.claude/agents/<name>.md`
# file. `scripts/qa/suites/test-team-formation.sh` enforces this invariant so
# the charter cannot reference a non-existent agent.

KNOWN_AGENTS = {
    "triage-researcher": "Fast read-only investigation (NetBox + incident history)",
    "ci-debugger": "GitLab pipeline failure diagnosis",
    "cisco-asa-specialist": "ASA firewall + VPN/IPsec/BGP",
    "code-explorer": "Repository structure + dependency graphs",
    "code-reviewer": "Code-review-with-fresh-eyes for diff/branch",
    "dependency-analyst": "Cross-repo refactor impact analysis",
    "k8s-diagnostician": "Kubernetes cluster diagnostics",
    "security-analyst": "CrowdSec / scanner / CVE deep-dive",
    "storage-specialist": "Synology NAS, Proxmox ZFS, iSCSI, NFS",
    "workflow-validator": "n8n workflow JSON validation",
    "teacher-agent": "Operator-facing learning loop (read-only)",
}


# ── Charter primitives ───────────────────────────────────────────────────────


class AgentSlot(NamedTuple):
    agent: str
    role: str
    when: str            # "phase 0".."phase 6" or "always"
    rationale: str


# ── Hostname → specialist heuristics ─────────────────────────────────────────

_HOSTNAME_HINTS = [
    (re.compile(r"k8s|kube|ctrlr|worker", re.I), "k8s-diagnostician"),
    (re.compile(r"fw0[12]|asa", re.I), "cisco-asa-specialist"),
    (re.compile(r"syno|zfs|iscsi|nfs|nas|ceph", re.I), "storage-specialist"),
    (re.compile(r"crowdsec|scanner|sec0[12]|nuclei", re.I), "security-analyst"),
    (re.compile(r"cubeos|meshsat|n8n|gitlab", re.I), "ci-debugger"),
]


def _specialist_for_hostname(hostname: str | None) -> str | None:
    if not hostname:
        return None
    for pat, agent in _HOSTNAME_HINTS:
        if pat.search(hostname):
            return agent
    return None


# ── Category-driven default rosters ──────────────────────────────────────────


def _base_for_category(category: str) -> list[AgentSlot]:
    """Return the always-on roster for a given alert category.

    Always includes triage-researcher (Phase 0 fact-gathering). Specific
    specialists added per category. Dev-shaped categories include
    code-explorer instead.
    """
    cat = (category or "").lower()
    out: list[AgentSlot] = []

    if cat in ("dev", "ci-failure", "code-review"):
        out.append(AgentSlot("code-explorer", "code investigation", "phase 0",
                             "Dev-shaped session needs repo navigation first."))
        if cat == "ci-failure":
            out.append(AgentSlot("ci-debugger", "pipeline failure diagnosis",
                                 "phase 1", "CI alert — pin the failing job."))
        return out

    # Infra-shaped categories all start with triage-researcher.
    out.append(AgentSlot("triage-researcher", "fact-gathering",
                         "phase 0",
                         "Read-only NetBox + incident-history triage."))

    if cat == "kubernetes":
        out.append(AgentSlot("k8s-diagnostician", "cluster + pod health",
                             "phase 2", "Alert is K8s-shaped."))
    elif cat == "network":
        out.append(AgentSlot("cisco-asa-specialist",
                             "VPN / BGP / ACL inspection",
                             "phase 2", "Alert is network-shaped."))
    elif cat == "storage":
        out.append(AgentSlot("storage-specialist",
                             "ZFS / iSCSI / NFS health",
                             "phase 2", "Alert is storage-shaped."))
    elif cat == "security-incident":
        out.append(AgentSlot("security-analyst",
                             "CrowdSec + scanner correlation",
                             "phase 2", "Security incident requires deep-dive."))

    return out


def _risk_overlay(slots: list[AgentSlot], risk_level: str) -> list[AgentSlot]:
    """Augment the base roster based on risk level."""
    rl = (risk_level or "").lower()
    out = list(slots)

    if rl in ("mixed", "high"):
        out.append(AgentSlot(
            "workflow-validator",
            "validate any n8n change before push",
            "phase 5",
            "Mixed/high-risk session — workflow edits need validator gate.",
        ))
    if rl == "high":
        out.append(AgentSlot(
            "code-reviewer",
            "fresh-eyes review of any diff",
            "phase 5",
            "High-risk — independent review reduces blast-radius.",
        ))
    return out


def _hostname_specialist_overlay(slots: list[AgentSlot], hostname: str | None) -> list[AgentSlot]:
    """If hostname hints at a specialist not already in roster, add it."""
    spec = _specialist_for_hostname(hostname)
    if not spec:
        return slots
    if any(s.agent == spec for s in slots):
        return slots
    return slots + [AgentSlot(
        spec, "specialist (hostname-derived)", "phase 2",
        f"Hostname {hostname!r} maps to specialist {spec}.",
    )]


def _dedup_preserving_order(slots: list[AgentSlot]) -> list[AgentSlot]:
    seen: set[str] = set()
    out: list[AgentSlot] = []
    for s in slots:
        if s.agent in seen:
            continue
        seen.add(s.agent)
        out.append(s)
    return out


# ── Public API ───────────────────────────────────────────────────────────────


def propose_team(
    category: str,
    risk_level: str = "low",
    hostname: str | None = None,
) -> dict:
    """Compute the team charter for a session.

    Returns a JSON-serialisable dict. Always includes a non-empty `agents`
    list — a session with no obvious specialist still gets at least
    triage-researcher (or code-explorer for dev sessions).
    """
    base = _base_for_category(category)
    base = _hostname_specialist_overlay(base, hostname)
    base = _risk_overlay(base, risk_level)
    base = _dedup_preserving_order(base)

    # Defensive: every emitted agent must be in KNOWN_AGENTS — otherwise the
    # Build Prompt would reference a non-existent .claude/agents/*.md file.
    base = [s for s in base if s.agent in KNOWN_AGENTS]

    return {
        "category": (category or "").lower(),
        "risk_level": (risk_level or "").lower(),
        "hostname": hostname or "",
        "agents": [
            {"agent": s.agent, "role": s.role, "when": s.when, "rationale": s.rationale}
            for s in base
        ],
        "rationale": _summary_rationale(category, risk_level, len(base)),
    }


def _summary_rationale(category: str, risk_level: str, agent_count: int) -> str:
    return (
        f"{(risk_level or 'low').lower()}-risk {(category or 'unknown').lower()} session — "
        f"{agent_count} agent{'s' if agent_count != 1 else ''} chartered by team-formation rules."
    )


# ── CLI (smoke + ad-hoc inspection) ──────────────────────────────────────────


def _cli() -> int:
    import argparse
    import json
    import sys

    p = argparse.ArgumentParser(description="Propose a sub-agent team charter.")
    p.add_argument("--category", required=True)
    p.add_argument("--risk-level", default="low")
    p.add_argument("--hostname", default=None)
    p.add_argument("--json", action="store_true", help="machine-readable")
    args = p.parse_args()
    charter = propose_team(args.category, args.risk_level, args.hostname)
    if args.json:
        json.dump(charter, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(f"# Team charter — {charter['rationale']}")
        for a in charter["agents"]:
            print(f"  - {a['agent']:<24}  {a['role']}  ({a['when']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
