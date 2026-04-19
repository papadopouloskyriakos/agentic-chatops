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
import sys
import time
from typing import Any

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

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
    (re.compile(r"\bqm\s+(set|start|stop|reboot|shutdown|destroy|create|clone)\b"), "high", "qm-write"),
    (re.compile(r"\bsystemctl\s+(start|stop|restart|reload|enable|disable|mask|unmask|daemon-reload)\b"), "high", "systemctl-write"),
    (re.compile(r"\b(git\s+(commit|push|merge|rebase|reset|tag|branch)\b|git\s+checkout\s+-b)"), "high", "git-write"),
    (re.compile(r"\b(rm|mv|cp|chmod|chown|mkdir|rmdir|truncate)\s+-?"), "high", "fs-write"),
    (re.compile(r"\b(iptables|nft|ufw)\s+"), "high", "firewall-write"),
    (re.compile(r"\bcrypto\s+map\b|\bclear\s+(crypto|conn|shun|arp|xlate)\b"), "high", "asa-write"),
    (re.compile(r"\bswanctl\s+(--(load|terminate|initiate|install|flush))\b"), "high", "swanctl-write"),
    (re.compile(r"\bvtysh.*-c\s+['\"](conf|write|clear)"), "high", "frr-write"),
    (re.compile(r"\bawx.*(launch|post)|curl.*awx.*-X\s+POST"), "high", "awx-launch"),
    (re.compile(r"\b(reboot|shutdown|halt|poweroff|kexec|init\s+[06])\b"), "high", "system-reboot"),
    # Softer mutations — MIXED (usually wrapped in dry_run or preview)
    (re.compile(r"\b(atlantis\s+(plan|apply)|terraform\s+(plan|apply|destroy)|tofu\s+(plan|apply|destroy))\b"), "mixed", "iac-plan-or-apply"),
    (re.compile(r"\bdocker\s+(run|exec|stop|restart|rm|kill|build|pull|push|tag)\b"), "mixed", "docker-write"),
    (re.compile(r"\bcscli\s+decisions\s+(add|delete)\b"), "mixed", "crowdsec-write"),
    # Ban / unban / shun mentions as bare words — strong HITL signal
    (re.compile(r"\b(ban|unban|shun|block|isolate|quarantine|drain|evict|kill)\b", re.IGNORECASE), "mixed", "containment-verb"),
]

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

    # AWX templates attached = at minimum MIXED (plan references a mutation path).
    if plan.get("awx_templates"):
        matched_mutations.append(("mixed", f"awx-templates-referenced:{len(plan['awx_templates'])}"))

    for pat, level, reason in MUTATION_PATTERNS:
        if pat.search(blob):
            matched_mutations.append((level, reason))
    for pat, reason in READ_ONLY_MARKERS:
        if pat.search(blob):
            matched_read_only.append(reason)

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

    plan_hash = hashlib.sha256(
        json.dumps(plan, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]

    return {
        "risk_level": risk,
        "auto_approve_recommended": risk == "low",
        "signals": signals,
        "plan_hash": plan_hash,
    }


# ── Audit table ───────────────────────────────────────────────────────────────


def _ensure_audit_schema():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
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
                operator_override TEXT
            )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_risk_audit_issue ON session_risk_audit(issue_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_risk_audit_time ON session_risk_audit(classified_at)"
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[classify] schema init failed: {e}", file=sys.stderr)


def write_audit_row(issue_id: str, category: str, result: dict,
                    auto_approved: bool, operator_override: str | None = None):
    _ensure_audit_schema()
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute(
            """INSERT INTO session_risk_audit
                (issue_id, alert_category, risk_level, auto_approved,
                 signals_json, plan_hash, operator_override)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (issue_id or "unknown", category, result["risk_level"],
             1 if auto_approved else 0,
             json.dumps(result.get("signals", [])),
             result.get("plan_hash"),
             operator_override),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"[classify] audit write failed: {e}", file=sys.stderr)


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
    args = ap.parse_args()

    try:
        if args.plan:
            with open(args.plan) as f:
                plan = json.load(f)
        else:
            plan = json.load(sys.stdin)
    except Exception as e:
        if os.environ.get("RISK_FAIL_CLOSED") == "1":
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

    # Operator override force-bumps to high
    if args.override:
        result["risk_level"] = "high"
        result["auto_approve_recommended"] = False
        result["signals"].append(f"operator-override:{args.override[:40]}")

    auto_approve = result["auto_approve_recommended"]
    if not args.no_audit:
        write_audit_row(args.issue_id, args.category, result,
                        auto_approve, args.override)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
