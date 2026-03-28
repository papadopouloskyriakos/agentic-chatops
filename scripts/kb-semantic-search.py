#!/usr/bin/env python3
"""Semantic search for incident_knowledge table.

Uses Ollama embeddings (nomic-embed-text on gpu01) with cosine similarity.
Stores embeddings as JSON arrays in the `embedding` column.

Usage:
  kb-semantic-search.py embed [--backfill]     # Embed entries missing embeddings
  kb-semantic-search.py search "query text"     # Semantic search (top 5)
  kb-semantic-search.py search "query" --limit 3 --days 90  # With filters
"""

import sys
import os
import json
import sqlite3
import urllib.request
import math

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")


def get_embedding(text):
    """Get embedding vector from Ollama."""
    payload = json.dumps({"model": EMBED_MODEL, "input": text}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data["embeddings"][0]
    except Exception as e:
        print(f"ERROR: Embedding failed: {e}", file=sys.stderr)
        return None


def cosine_similarity(a, b):
    """Cosine similarity between two vectors (pure Python, no numpy)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def ensure_embedding_column(conn):
    """Add embedding column if it doesn't exist."""
    cursor = conn.execute("PRAGMA table_info(incident_knowledge)")
    columns = [row[1] for row in cursor.fetchall()]
    if "embedding" not in columns:
        conn.execute("ALTER TABLE incident_knowledge ADD COLUMN embedding TEXT DEFAULT ''")
        conn.commit()


def build_embed_text(row):
    """Build the text to embed from a knowledge entry."""
    parts = []
    if row["alert_rule"]:
        parts.append(f"alert: {row['alert_rule']}")
    if row["hostname"]:
        parts.append(f"host: {row['hostname']}")
    if row["root_cause"]:
        parts.append(f"cause: {row['root_cause']}")
    if row["resolution"]:
        parts.append(f"resolution: {row['resolution']}")
    if row["tags"]:
        parts.append(f"tags: {row['tags']}")
    return " | ".join(parts) if parts else ""


def cmd_embed(backfill=False):
    """Embed entries that are missing embeddings."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_embedding_column(conn)

    if backfill:
        rows = conn.execute(
            "SELECT * FROM incident_knowledge WHERE embedding IS NULL OR embedding = ''"
        ).fetchall()
    else:
        # Only the most recent entry (just inserted by Session End)
        rows = conn.execute(
            "SELECT * FROM incident_knowledge WHERE embedding IS NULL OR embedding = '' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchall()

    if not rows:
        print("No entries need embedding.")
        return 0

    count = 0
    for row in rows:
        text = build_embed_text(row)
        if not text:
            continue
        vec = get_embedding(text)
        if vec:
            conn.execute(
                "UPDATE incident_knowledge SET embedding = ? WHERE id = ?",
                (json.dumps(vec), row["id"]),
            )
            count += 1
            print(f"Embedded id={row['id']}: {text[:80]}...")

    conn.commit()
    conn.close()
    print(f"Embedded {count}/{len(rows)} entries.")
    return count


def cmd_search(query, limit=5, days=90):
    """Semantic search against the knowledge base.

    Output format (pipe-separated, one per line):
      issue_id|hostname|alert_rule|resolution|confidence|created_at|site|similarity
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_embedding_column(conn)

    query_vec = get_embedding(query)
    if not query_vec:
        print("ERROR: Could not embed query", file=sys.stderr)
        # Fall back to keyword search
        return cmd_keyword_fallback(conn, query, limit, days)

    if days > 0:
        rows = conn.execute(
            "SELECT * FROM incident_knowledge "
            "WHERE embedding IS NOT NULL AND embedding != '' "
            "AND created_at > datetime('now', ?)",
            (f"-{days} days",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM incident_knowledge "
            "WHERE embedding IS NOT NULL AND embedding != ''"
        ).fetchall()

    if not rows:
        # Fall back to keyword search if no embeddings exist yet
        return cmd_keyword_fallback(conn, query, limit, days)

    scored = []
    for row in rows:
        try:
            row_vec = json.loads(row["embedding"])
            sim = cosine_similarity(query_vec, row_vec)
            scored.append((sim, row))
        except (json.JSONDecodeError, TypeError):
            continue

    scored.sort(key=lambda x: x[0], reverse=True)

    # Threshold: only return results with similarity > 0.3
    results = [(sim, row) for sim, row in scored[:limit] if sim > 0.3]

    if not results:
        # Fall back to keyword if semantic search returns nothing useful
        return cmd_keyword_fallback(conn, query, limit, days)

    for sim, row in results:
        resolution = (row["resolution"] or "").replace("|", " ").replace("\n", " ")[:200]
        print(
            f"{row['issue_id']}|{row['hostname']}|{row['alert_rule']}|"
            f"{resolution}|{row['confidence']}|{row['created_at']}|"
            f"{row['site']}|{sim:.3f}"
        )

    conn.close()
    return len(results)


def cmd_keyword_fallback(conn, query, limit, days):
    """Keyword fallback when embeddings unavailable."""
    search = f"%{query}%"
    day_filter = f"AND created_at > datetime('now', '-{days} days')" if days > 0 else ""
    rows = conn.execute(
        f"SELECT issue_id, hostname, alert_rule, resolution, confidence, created_at, site "
        f"FROM incident_knowledge "
        f"WHERE (hostname LIKE ? OR alert_rule LIKE ? OR resolution LIKE ? OR tags LIKE ?) "
        f"{day_filter} "
        f"ORDER BY created_at DESC LIMIT ?",
        (search, search, search, search, limit),
    ).fetchall()
    for row in rows:
        resolution = (row["resolution"] or "").replace("|", " ").replace("\n", " ")[:200]
        print(
            f"{row['issue_id']}|{row['hostname']}|{row['alert_rule']}|"
            f"{resolution}|{row['confidence']}|{row['created_at']}|"
            f"{row['site']}|0.000"
        )
    conn.close()
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "embed":
        backfill = "--backfill" in sys.argv
        cmd_embed(backfill=backfill)

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: kb-semantic-search.py search 'query text' [--limit N] [--days N]")
            sys.exit(1)
        query = sys.argv[2]
        limit = 5
        days = 90
        for i, arg in enumerate(sys.argv[3:], 3):
            if arg == "--limit" and i + 1 < len(sys.argv):
                limit = int(sys.argv[i + 1])
            elif arg == "--days" and i + 1 < len(sys.argv):
                days = int(sys.argv[i + 1])
        cmd_search(query, limit=limit, days=days)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
