#!/usr/bin/env python3
"""Build Prompt layered injection — MemPalace L0-L3 pattern.

Generates structured context for Claude Code sessions with explicit token caps.
Called by n8n Runner Build Prompt node via SSH.

Layers:
  L0 Identity  (~100 tokens, always): agent role, environment summary
  L1 Rules     (~300 tokens, always): top operational rules, data trust hierarchy
  L2 Context   (~2000 tokens, conditional): RAG results + agent diary, issue-specific
  L3 Search    (unlimited, on-demand): deep search only when needed

Usage:
  build-prompt-layers.py <issue_id> <hostname> [--category <cat>] [--agent <agent>]
  build-prompt-layers.py --layers-only   # Output just L0+L1 (wake-up context)
"""
import sys
import os
import json
import sqlite3
import subprocess

DB_PATH = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
SCRIPTS = os.path.dirname(os.path.abspath(__file__))

# Token budget caps (chars ≈ tokens * 4)
L0_CAP = 400    # ~100 tokens
L1_CAP = 1200   # ~300 tokens
L2_CAP = 8000   # ~2000 tokens
L3_CAP = 0      # unlimited (on-demand only)


def build_l0():
    """L0 Identity — always loaded, who is this agent."""
    return """You are an infrastructure operations agent for Example Corp Network.
Environment: 2 sites (NL Leiden, GR Skiathos), 310+ devices, 13 K8s nodes (v1.34.2), 5 PVE hosts.
Orchestration: n8n workflows bridge alerts to Claude Code sessions with human-in-the-loop via Matrix.
You have MCP access to: NetBox (CMDB), Kubernetes, Proxmox, YouTrack, n8n, OpenTofu, CodeGraph."""[:L0_CAP]


def build_l1():
    """L1 Critical Rules — always loaded, operational constraints."""
    rules = []

    # Top feedback memories (most critical operational rules)
    rules.append("DATA TRUST: Live device > LibreNMS > NetBox > supplementary. Running config = truth.")
    rules.append("NEVER modify config files, OOB systems, or infrastructure without explicit user approval.")
    rules.append("ALL K8s changes via OpenTofu + Atlantis MR. No kubectl apply, no exceptions.")
    rules.append("Always use full hostnames (nl-pve01 not pve01). Multi-site makes short forms ambiguous.")
    rules.append("NEVER mass-delete by grep pattern. Audit each line individually.")
    rules.append("ASA crypto-map: always DELETE then RE-CREATE entries. In-place changes leave stale TS tables.")
    rules.append("IPsec ISP changes must be additive (add backup, never replace primary).")
    rules.append("Solo operator managing 310 objects — optimize for minimum human interaction.")

    text = "OPERATIONAL RULES:\n" + "\n".join(f"- {r}" for r in rules)
    return text[:L1_CAP]


def build_l2(issue_id, hostname="", category="", agent_name=""):
    """L2 Incident Context — conditional, issue-specific RAG + agent diary."""
    parts = []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. Incident knowledge (last 5 for this hostname)
    if hostname:
        rows = conn.execute(
            "SELECT issue_id, alert_rule, resolution, confidence, created_at "
            "FROM incident_knowledge "
            "WHERE hostname=? AND (valid_until IS NULL OR valid_until > datetime('now')) "
            "ORDER BY created_at DESC LIMIT 5",
            (hostname,)
        ).fetchall()
        if rows:
            parts.append("<incident_knowledge>")
            for r in rows:
                res = (r["resolution"] or "")[:200]
                parts.append(f"  [{r['created_at']}] {r['issue_id']}: {r['alert_rule']} → {res} (conf:{r['confidence']})")
            parts.append("</incident_knowledge>")

    # 2. Session transcripts (last 3 for this hostname)
    if hostname:
        try:
            t_rows = conn.execute(
                "SELECT issue_id, content, created_at FROM session_transcripts "
                "WHERE content LIKE ? ORDER BY created_at DESC LIMIT 3",
                (f"%{hostname}%",)
            ).fetchall()
            if t_rows:
                parts.append("<session_transcripts>")
                for t in t_rows:
                    parts.append(f"  [{t['created_at']}] {t['issue_id']}: {t['content'][:200]}")
                parts.append("</session_transcripts>")
        except sqlite3.OperationalError:
            pass

    # 3. Agent diary (last 3 entries for relevant agent)
    if agent_name:
        try:
            d_rows = conn.execute(
                "SELECT entry, tags, created_at FROM agent_diary "
                "WHERE agent_name=? ORDER BY created_at DESC LIMIT 3",
                (agent_name,)
            ).fetchall()
            if d_rows:
                parts.append(f"<agent_diary agent=\"{agent_name}\">")
                for d in d_rows:
                    parts.append(f"  [{d['created_at']}] ({d['tags'] or 'no-tags'}) {d['entry'][:200]}")
                parts.append("</agent_diary>")
        except sqlite3.OperationalError:
            pass

    # 4. Lessons learned (last 3)
    l_rows = conn.execute(
        "SELECT issue_id, lesson, created_at FROM lessons_learned "
        "ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    if l_rows:
        parts.append("<lessons_learned>")
        for l in l_rows:
            parts.append(f"  [{l['created_at']}] {l['issue_id']}: {l['lesson'][:200]}")
        parts.append("</lessons_learned>")

    conn.close()

    text = "\n".join(parts)
    return text[:L2_CAP]


def build_all(issue_id, hostname="", category="", agent_name=""):
    """Build complete layered injection."""
    l0 = build_l0()
    l1 = build_l1()
    l2 = build_l2(issue_id, hostname, category, agent_name)

    total_chars = len(l0) + len(l1) + len(l2)

    output = {
        "l0_identity": l0,
        "l1_rules": l1,
        "l2_context": l2,
        "total_chars": total_chars,
        "total_tokens_approx": total_chars // 4,
        "layers_used": ["L0", "L1"] + (["L2"] if l2 else []),
    }
    return output


if __name__ == "__main__":
    if "--layers-only" in sys.argv:
        print(build_l0())
        print()
        print(build_l1())
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: build-prompt-layers.py <issue_id> <hostname> [--category <cat>] [--agent <agent>]")
        sys.exit(1)

    issue_id = sys.argv[1]
    hostname = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else ""
    category = ""
    agent_name = ""
    for i, arg in enumerate(sys.argv):
        if arg == "--category" and i + 1 < len(sys.argv):
            category = sys.argv[i + 1]
        if arg == "--agent" and i + 1 < len(sys.argv):
            agent_name = sys.argv[i + 1]

    result = build_all(issue_id, hostname, category, agent_name)
    print(json.dumps(result, indent=2))
