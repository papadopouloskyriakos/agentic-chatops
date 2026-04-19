#!/usr/bin/env python3
"""Agent diary — persistent per-agent knowledge across sessions.

Ported from MemPalace mcp_server.py diary_write/diary_read tools.
Sub-agents accumulate knowledge across invocations.

Usage:
  agent-diary.py write <agent_name> <entry> [--issue <id>] [--tags <tags>]
  agent-diary.py read <agent_name> [--last <n>] [--since <date>]
  agent-diary.py embed --backfill
"""
import sys
import os
import json
import sqlite3
from datetime import datetime

DB_PATH = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
OLLAMA_URL = "http://nl-gpu01:11434"
EMBED_MODEL = "nomic-embed-text"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _record_local_usage(model, input_tokens, output_tokens=0):
    """Record local GPU model usage to llm_usage table (tier 0)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO llm_usage (tier, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (0, ?, ?, ?, 0.0)",
            (model, input_tokens, output_tokens),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def generate_embedding(text):
    try:
        import urllib.request
        # G7: asymmetric document prefix + num_ctx to prevent CPU-spill on gpu01
        prefixed = f"search_document: {text[:2000]}"
        data = json.dumps({
            "model": EMBED_MODEL,
            "input": prefixed,
            "options": {"num_ctx": 2048},
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embed", data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            _record_local_usage(EMBED_MODEL, result.get("prompt_eval_count", 0))
            emb = result.get("embeddings", [[]])[0]
            return json.dumps(emb) if emb else ""
    except Exception:
        return ""


def cmd_write(agent_name, entry, issue_id="", tags=""):
    conn = get_db()
    embedding = generate_embedding(f"{agent_name}: {entry}")
    conn.execute(
        "INSERT INTO agent_diary (agent_name, issue_id, entry, tags, embedding) VALUES (?,?,?,?,?)",
        (agent_name, issue_id, entry, tags, embedding)
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    print(f"[diary] Written entry #{row_id} for {agent_name}" + (f" (issue {issue_id})" if issue_id else ""))
    return row_id


def cmd_read(agent_name, last_n=5, since=None):
    conn = get_db()
    if since:
        rows = conn.execute(
            "SELECT id, entry, tags, issue_id, created_at FROM agent_diary WHERE agent_name=? AND created_at>=? ORDER BY created_at DESC LIMIT ?",
            (agent_name, since, last_n)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, entry, tags, issue_id, created_at FROM agent_diary WHERE agent_name=? ORDER BY created_at DESC LIMIT ?",
            (agent_name, last_n)
        ).fetchall()
    conn.close()

    if not rows:
        print(f"[diary] No entries for {agent_name}")
        return []

    results = []
    for row in rows:
        r = dict(row)
        results.append(r)
        print(f"  [{r['created_at']}] #{r['id']} ({r['tags'] or 'no tags'}) {r['entry'][:120]}")
    print(f"[diary] {len(results)} entries for {agent_name}")
    return results


def cmd_backfill():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, agent_name, entry FROM agent_diary WHERE embedding='' OR embedding IS NULL"
    ).fetchall()
    print(f"[diary] {len(rows)} entries need embeddings")
    for row in rows:
        emb = generate_embedding(f"{row['agent_name']}: {row['entry']}")
        if emb:
            conn.execute("UPDATE agent_diary SET embedding=? WHERE id=?", (emb, row["id"]))
    conn.commit()
    conn.close()
    print("[diary] Backfill done")


def cmd_inject(agent_name, last_n=3):
    """Return formatted diary entries for prompt injection."""
    conn = get_db()
    rows = conn.execute(
        "SELECT entry, tags, issue_id, created_at FROM agent_diary WHERE agent_name=? ORDER BY created_at DESC LIMIT ?",
        (agent_name, last_n)
    ).fetchall()
    conn.close()

    if not rows:
        return ""

    lines = [f"<agent_diary agent=\"{agent_name}\" entries=\"{len(rows)}\">"]
    for row in rows:
        lines.append(f"  [{row['created_at']}] {row['entry'][:300]}")
    lines.append("</agent_diary>")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: agent-diary.py write|read|embed|inject <agent_name> ...")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "write" and len(sys.argv) >= 4:
        agent = sys.argv[2]
        entry = sys.argv[3]
        issue = ""
        tags = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--issue" and i + 1 < len(sys.argv):
                issue = sys.argv[i + 1]
            if arg == "--tags" and i + 1 < len(sys.argv):
                tags = sys.argv[i + 1]
        cmd_write(agent, entry, issue, tags)

    elif cmd == "read" and len(sys.argv) >= 3:
        agent = sys.argv[2]
        last_n = 5
        since = None
        for i, arg in enumerate(sys.argv):
            if arg == "--last" and i + 1 < len(sys.argv):
                last_n = int(sys.argv[i + 1])
            if arg == "--since" and i + 1 < len(sys.argv):
                since = sys.argv[i + 1]
        cmd_read(agent, last_n, since)

    elif cmd == "embed":
        cmd_backfill()

    elif cmd == "inject" and len(sys.argv) >= 3:
        agent = sys.argv[2]
        last_n = 3
        for i, arg in enumerate(sys.argv):
            if arg == "--last" and i + 1 < len(sys.argv):
                last_n = int(sys.argv[i + 1])
        print(cmd_inject(agent, last_n))

    else:
        print("Usage: agent-diary.py write|read|embed|inject <agent_name> ...")
        sys.exit(1)
