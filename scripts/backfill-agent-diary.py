#!/usr/bin/env python3
"""Backfill agent_diary from tool_call_log Agent calls.

Reads tool_call_log for Agent tool calls, groups by session,
maps operations to agent archetypes, and inserts diary entries
summarizing the most common operations per agent.

No LLM calls needed -- pure aggregation of tool_call_log data.

Usage:
  backfill-agent-diary.py              # Run backfill
  backfill-agent-diary.py --stats      # Show current diary stats
"""
import sys
import os
REDACTED_a7b84d63
import sqlite3
from collections import defaultdict

# IFRNLLEI01PRD-635: schema version registry.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from schema_version import current as schema_current  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

# Map operation descriptions to agent archetypes
AGENT_PATTERNS = {
    "triage-researcher": [
        r"triage", r"investigate", r"diagnose", r"check.*alert",
        r"incident", r"monitor", r"health.*check"
    ],
    "k8s-diagnostician": [
        r"k8s", r"kubernetes", r"kubectl", r"helm", r"cilium",
        r"pod", r"deployment", r"node.*drain", r"cluster"
    ],
    "code-explorer": [
        r"explore.*(?:code|struct|project|pattern|repo|test)",
        r"audit.*(?:code|test|coverage|UI|completeness)",
        r"map.*structure", r"research.*(?:code|bug|pattern)"
    ],
    "infra-automator": [
        r"(?:ssh|configure|deploy|setup|install|provision)",
        r"playbook", r"awx", r"terraform", r"opentofu",
        r"ansible", r"pve|proxmox"
    ],
    "workflow-builder": [
        r"workflow", r"n8n", r"export.*workflow", r"node.*config",
        r"webhook", r"switch.*v3"
    ],
    "security-analyst": [
        r"security", r"crowdsec", r"vuln", r"scan", r"cve",
        r"nuclei", r"firewall", r"acl", r"ipsec"
    ],
    "dev-implementor": [
        r"(?:add|implement|create|wire|port|build|write).*(?:handler|command|api|bridge|worker|test|feature)",
        r"refactor", r"migration"
    ],
    "documentation-writer": [
        r"document", r"readme", r"wiki", r"compile.*wiki",
        r"memory", r"claude.*md"
    ],
}


def classify_agent(operation):
    """Classify an operation description into an agent archetype."""
    if not operation:
        return "general-agent"
    op_lower = operation.lower()
    for agent_name, patterns in AGENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, op_lower):
                return agent_name
    return "general-agent"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def backfill():
    """Main backfill logic."""
    conn = get_db()

    # Get all Agent calls grouped by session
    rows = conn.execute("""
        SELECT session_id, operation, COUNT(*) as cnt,
               MIN(created_at) as first_call, MAX(created_at) as last_call
        FROM tool_call_log
        WHERE tool_name = 'Agent'
          AND session_id != '' AND session_id IS NOT NULL
          AND operation != '' AND operation IS NOT NULL
        GROUP BY session_id, operation
        ORDER BY session_id, cnt DESC
    """).fetchall()

    if not rows:
        print("[diary] No Agent calls found in tool_call_log")
        return 0

    # Group by session_id
    sessions = defaultdict(list)
    for row in rows:
        sessions[row["session_id"]].append({
            "operation": row["operation"],
            "count": row["cnt"],
            "first": row["first_call"],
            "last": row["last_call"],
        })

    print(f"[diary] Found {len(sessions)} sessions with Agent calls")

    # Classify and aggregate per agent archetype
    agent_ops = defaultdict(lambda: defaultdict(int))  # agent -> operation -> count
    agent_sessions = defaultdict(set)  # agent -> set of session_ids

    for session_id, ops in sessions.items():
        for op_data in ops:
            agent_name = classify_agent(op_data["operation"])
            agent_ops[agent_name][op_data["operation"]] += op_data["count"]
            agent_sessions[agent_name].add(session_id)

    # Check existing diary entries to avoid duplicates
    existing = set()
    for row in conn.execute("SELECT agent_name, entry FROM agent_diary").fetchall():
        existing.add((row["agent_name"], row["entry"][:50]))

    inserted = 0
    for agent_name in sorted(agent_ops.keys()):
        ops = agent_ops[agent_name]
        session_count = len(agent_sessions[agent_name])
        top_ops = sorted(ops.items(), key=lambda x: x[1], reverse=True)[:8]

        # Create a summary entry
        op_list = ", ".join(f"{op} ({cnt}x)" for op, cnt in top_ops[:5])
        entry = (
            f"Observed across {session_count} sessions with {sum(ops.values())} total Agent calls. "
            f"Top operations: {op_list}"
        )

        # Check for duplicate
        if (agent_name, entry[:50]) in existing:
            print(f"  [skip] {agent_name} -- already has summary entry")
            continue

        tags = ",".join(
            ["backfill", "tool_call_log"]
            + [op for op, _ in top_ops[:3]]
        )[:500]

        conn.execute(
            "INSERT INTO agent_diary (agent_name, entry, tags, schema_version) VALUES (?, ?, ?, ?)",
            (agent_name, entry, tags, schema_current("agent_diary")),
        )
        inserted += 1
        print(f"  [insert] {agent_name}: {session_count} sessions, {sum(ops.values())} calls")

        # Also insert per-session diary entries for agents with >3 sessions
        # (gives more granular history)
        if session_count >= 3:
            sample_sessions = sorted(agent_sessions[agent_name])[:5]
            for sid in sample_sessions:
                session_ops = [
                    o for o in sessions[sid]
                    if classify_agent(o["operation"]) == agent_name
                ]
                if not session_ops:
                    continue
                op_desc = "; ".join(o["operation"] for o in session_ops[:3])
                per_entry = f"Session {sid[:12]}...: {op_desc}"
                if (agent_name, per_entry[:50]) in existing:
                    continue
                conn.execute(
                    "INSERT INTO agent_diary (agent_name, issue_id, entry, tags, schema_version) VALUES (?, ?, ?, ?, ?)",
                    (agent_name, sid, per_entry, "backfill,per-session", schema_current("agent_diary")),
                )
                inserted += 1

    conn.commit()
    conn.close()
    print(f"\n[diary] Inserted {inserted} diary entries across {len(agent_ops)} agent archetypes")
    return inserted


def show_stats():
    """Show current diary statistics."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM agent_diary").fetchone()[0]
    print(f"=== Agent Diary Stats ({total} entries) ===\n")

    rows = conn.execute("""
        SELECT agent_name, COUNT(*) as cnt
        FROM agent_diary
        GROUP BY agent_name
        ORDER BY cnt DESC
    """).fetchall()
    for row in rows:
        print(f"  {row['agent_name']}: {row['cnt']} entries")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        show_stats()
    else:
        backfill()
