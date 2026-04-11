#!/usr/bin/env python3
"""Semantic search for incident_knowledge table.

Uses Ollama embeddings (nomic-embed-text on gpu01) with cosine similarity.
Stores embeddings as JSON arrays in the `embedding` column.

Usage:
  kb-semantic-search.py embed [--backfill]     # Embed entries missing embeddings
  kb-semantic-search.py search "query text"     # Semantic search (top 5)
  kb-semantic-search.py search "query" --limit 3 --days 90  # With filters
  kb-semantic-search.py search "query" --threshold 0.5      # Custom similarity threshold
  kb-semantic-search.py search "query" --mode hybrid         # Hybrid search (semantic + keyword via RRF)
  kb-semantic-search.py search "query" --mode keyword        # Keyword-only search
  kb-semantic-search.py graph <hostname>                      # GraphRAG: past incidents for a host
"""

import sys
import os
import json
import sqlite3
import urllib.request
import math
import datetime

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
WIKI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wiki")
NOW_ISO = datetime.datetime.utcnow().isoformat()
NOW_DT = datetime.datetime.utcnow()


def staleness_warning(created_at_str):
    """Return age-proportional staleness warning for injected knowledge.

    B7: Results older than 7 days get a verification note; older than 30 days
    get a stronger outdated warning. This helps the model weight fresh vs stale
    knowledge appropriately.
    """
    if not created_at_str:
        return ""
    try:
        # Handle various SQLite datetime formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                     "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
            try:
                created = datetime.datetime.strptime(created_at_str.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return ""
        age_days = (NOW_DT - created).days
        if age_days > 30:
            return f" [Warning: recorded {age_days} days ago — may be outdated, check referenced systems]"
        elif age_days > 7:
            return f" [Note: recorded {age_days} days ago — verify current state]"
    except Exception:
        pass
    return ""


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


def rewrite_query(query, num_rewrites=2):
    """Use Ollama to generate query reformulations for better retrieval."""
    prompt = (
        f"Rewrite this infrastructure alert query into {num_rewrites} alternative phrasings "
        f"that would help find similar past incidents. Return ONLY the rewrites, one per line.\n\n"
        f"Original: {query}\n\nRewrites:"
    )
    payload = json.dumps({
        "model": "qwen3:4b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 150}
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            text = data.get("response", "")
            # Parse lines, filter empty and the original
            rewrites = [
                line.strip().lstrip("0VMID_REDACTED.-) ")
                for line in text.strip().split("\n")
                if line.strip() and line.strip().lower() != query.lower()
            ]
            return rewrites[:num_rewrites]
    except Exception as e:
        print(f"[rewrite] Ollama unavailable: {e}", file=sys.stderr)
        return []


def generate_hypothetical_doc(query):
    """G12: HyDE — generate a hypothetical incident report matching the query.

    When semantic search returns low-quality results, embedding a hypothetical
    matching document often retrieves better real matches than the raw query.
    Source: Agentic RAG Survey (arXiv 2501.09136)
    """
    prompt = (
        f"You are an infrastructure incident knowledge base. Generate a SHORT (3-4 sentences) "
        f"hypothetical past incident report that would match this query:\n\n"
        f'"{query}"\n\n'
        f"Include: hostname, alert type, root cause, and resolution. "
        f"Write as if this is a real past incident entry. Be technical and specific."
    )
    payload = json.dumps({
        "model": "qwen3:4b",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.5, "num_predict": 200}
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            text = data.get("response", "").strip()
            # Strip thinking tags if present (qwen3 quirk)
            if "<think>" in text:
                text = text.split("</think>")[-1].strip()
            return text if len(text) > 20 else None
    except Exception as e:
        print(f"[hyde] Ollama unavailable: {e}", file=sys.stderr)
        return None


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


def cmd_invalidate(hostname, alert_rule):
    """Invalidate open incident_knowledge entries (MemPalace temporal KG pattern).

    Sets valid_until = NOW() on matching entries where valid_until IS NULL.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "UPDATE incident_knowledge SET valid_until = datetime('now') "
        "WHERE hostname = ? AND alert_rule = ? AND valid_until IS NULL",
        (hostname, alert_rule),
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"Invalidated {count} entries for {hostname}/{alert_rule}")
    return count


def cmd_search(query, limit=5, days=90, threshold=0.3):
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

    # Temporal validity: exclude invalidated entries (MemPalace pattern)
    validity = "AND (valid_until IS NULL OR valid_until > datetime('now'))"
    if days > 0:
        rows = conn.execute(
            "SELECT * FROM incident_knowledge "
            "WHERE embedding IS NOT NULL AND embedding != '' "
            f"AND created_at > datetime('now', ?) {validity}",
            (f"-{days} days",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM incident_knowledge "
            f"WHERE embedding IS NOT NULL AND embedding != '' {validity}"
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

    # Threshold: only return results with similarity above threshold
    results = []
    for sim, row in scored[:limit]:
        if sim > threshold:
            results.append((sim, row))
        else:
            issue_id = row["issue_id"] or "unknown"
            print(f"[filtered] similarity {sim:.3f} < threshold {threshold} for {issue_id}", file=sys.stderr)

    if not results:
        # G12: HyDE fallback — generate hypothetical doc, embed, re-search
        hyde_doc = generate_hypothetical_doc(query)
        if hyde_doc:
            hyde_vec = get_embedding(hyde_doc)
            if hyde_vec:
                print("[hyde] Trying hypothetical document embedding fallback", file=sys.stderr)
                hyde_scored = []
                for row in rows:
                    try:
                        row_vec = json.loads(row["embedding"])
                        sim = cosine_similarity(hyde_vec, row_vec)
                        hyde_scored.append((sim, row))
                    except (json.JSONDecodeError, TypeError):
                        continue
                hyde_scored.sort(key=lambda x: x[0], reverse=True)
                for sim, row in hyde_scored[:limit]:
                    if sim > threshold * 0.8:  # Lower threshold for HyDE
                        results.append((sim, row))
                if results:
                    print(f"[hyde] Found {len(results)} results via HyDE", file=sys.stderr)

        if not results:
            # Fall back to keyword if HyDE also returns nothing
            return cmd_keyword_fallback(conn, query, limit, days)

    # G4: Self-correcting RAG — compute retrieval quality score
    avg_similarity = sum(s for s, _ in results) / len(results) if results else 0.0
    max_similarity = max((s for s, _ in results), default=0.0)
    quality_score = round(avg_similarity * 0.6 + max_similarity * 0.4, 3)

    # Emit quality metadata as first line (parseable by Query Knowledge)
    print(f"RETRIEVAL_QUALITY:{quality_score}|{len(results)}|{avg_similarity:.3f}|{max_similarity:.3f}")

    for sim, row in results:
        resolution = (row["resolution"] or "").replace("|", " ").replace("\n", " ")[:200]
        resolution += staleness_warning(row["created_at"])
        print(
            f"{row['issue_id']}|{row['hostname']}|{row['alert_rule']}|"
            f"{resolution}|{row['confidence']}|{row['created_at']}|"
            f"{row['site']}|{sim:.3f}"
        )

    conn.close()
    return len(results)


def query_graph(hostname, db_path=DB_PATH, limit=5):
    """Query GraphRAG for past incidents on a host and its dependencies."""
    conn = sqlite3.connect(db_path)
    # Find entity
    host_entity = conn.execute(
        "SELECT id FROM graph_entities WHERE entity_type='host' AND name=?", (hostname,)
    ).fetchone()
    if not host_entity:
        conn.close()
        return []
    host_id = host_entity[0]
    # Find incidents that affected this host (host as target)
    results = conn.execute("""
        SELECT ge.name, ge.attributes, gr.rel_type
        FROM graph_relationships gr
        JOIN graph_entities ge ON ge.id = gr.source_id
        WHERE gr.target_id = ? AND ge.entity_type = 'incident'
        ORDER BY ge.created_at DESC LIMIT ?
    """, (host_id, limit)).fetchall()
    # Also check reverse direction (host as source)
    results += conn.execute("""
        SELECT ge.name, ge.attributes, gr.rel_type
        FROM graph_relationships gr
        JOIN graph_entities ge ON ge.id = gr.target_id
        WHERE gr.source_id = ? AND ge.entity_type = 'incident'
        ORDER BY ge.created_at DESC LIMIT ?
    """, (host_id, limit)).fetchall()
    conn.close()
    return results[:limit]


def cmd_graph(hostname):
    """Print past incidents for a hostname from the GraphRAG knowledge graph."""
    results = query_graph(hostname)
    if not results:
        print(f"No graph incidents found for {hostname}")
        return 0
    print(f"GraphRAG incidents for {hostname}:")
    for name, attributes, rel_type in results:
        attrs = ""
        try:
            a = json.loads(attributes) if attributes else {}
            attrs = f" -- {a.get('resolution', a.get('root_cause', ''))}"[:100]
        except (json.JSONDecodeError, TypeError):
            pass
        print(f"  [{rel_type}] {name}{attrs}")
    return len(results)


def rrf_score(semantic_rank, keyword_rank, wiki_rank=None, transcript_rank=None, k=60, sem_quality=None):
    """Reciprocal Rank Fusion — combines semantic, keyword, wiki, and transcript rankings.

    When sem_quality > 0.8, boost the semantic signal weight (high confidence retrieval).
    """
    score = 0.0
    sem_weight = 1.0
    if sem_quality is not None and sem_quality > 0.8:
        sem_weight = 1.5  # Boost semantic weight when confidence is high
    if semantic_rank is not None:
        score += sem_weight / (k + semantic_rank)
    if keyword_rank is not None:
        score += 1.0 / (k + keyword_rank)
    if wiki_rank is not None:
        score += 1.0 / (k + wiki_rank)
    if transcript_rank is not None:
        score += 0.3 / (k + transcript_rank)  # Lower weight for raw transcripts
    return score


def search_transcripts(conn, query_vec, days=90, limit=10):
    """4th RRF signal: search session_transcripts table (MemPalace verbatim storage)."""
    if not query_vec:
        return {}
    try:
        if days > 0:
            rows = conn.execute(
                "SELECT id, issue_id, chunk_index, role, content, embedding, created_at "
                "FROM session_transcripts "
                "WHERE embedding IS NOT NULL AND embedding != '' "
                "AND created_at > datetime('now', ?)",
                (f"-{days} days",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, issue_id, chunk_index, role, content, embedding, created_at "
                "FROM session_transcripts "
                "WHERE embedding IS NOT NULL AND embedding != ''"
            ).fetchall()
    except Exception:
        return {}  # Table may not exist yet

    ranked = {}
    for row in rows:
        try:
            emb = json.loads(row["embedding"])
        except (json.JSONDecodeError, TypeError):
            continue
        sim = cosine_similarity(query_vec, emb)
        if sim > 0.3:
            key = f"transcript:{row['issue_id']}:{row['chunk_index']}"
            if key not in ranked or sim > ranked[key][1]:
                ranked[key] = (row, sim)

    sorted_items = sorted(ranked.values(), key=lambda x: x[1], reverse=True)
    return {item[0]["issue_id"]: (rank, item[1]) for rank, (item_row, sim) in enumerate(sorted_items[:limit]) for item in [(item_row, sim)]}


def cmd_hybrid_search(query, limit=5, days=90, threshold=0.3, use_rewrite=False):
    """Hybrid search combining semantic similarity and keyword matching via RRF."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_embedding_column(conn)

    # Query rewriting: expand search with reformulated queries
    queries = [query]
    if use_rewrite:
        rewrites = rewrite_query(query)
        if rewrites:
            queries.extend(rewrites)
            print(f"[rewrite] Original: {query}", file=sys.stderr)
            for i, rw in enumerate(rewrites):
                print(f"[rewrite] Variant {i+1}: {rw}", file=sys.stderr)

    day_filter = f"AND created_at > datetime('now', '-{days} days')" if days > 0 else ""
    validity = "AND (valid_until IS NULL OR valid_until > datetime('now'))"

    # 1. Semantic search (ranked by cosine similarity, across all query variants)
    semantic_ranked = {}
    if days > 0:
        rows = conn.execute(
            "SELECT * FROM incident_knowledge "
            "WHERE embedding IS NOT NULL AND embedding != '' "
            f"AND created_at > datetime('now', ?) {validity}",
            (f"-{days} days",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM incident_knowledge "
            f"WHERE embedding IS NOT NULL AND embedding != '' {validity}"
        ).fetchall()

    if rows:
        best_sims = {}  # key -> (best_sim, row)
        for q in queries:
            q_vec = get_embedding(q)
            if not q_vec:
                continue
            for row in rows:
                try:
                    row_vec = json.loads(row["embedding"])
                    sim = cosine_similarity(q_vec, row_vec)
                    key = row["issue_id"] or f"row-{row['id']}"
                    if sim > threshold and (key not in best_sims or sim > best_sims[key][0]):
                        best_sims[key] = (sim, row)
                except (json.JSONDecodeError, TypeError):
                    continue

        scored = sorted(best_sims.values(), key=lambda x: x[0], reverse=True)
        for rank, (sim, row) in enumerate(scored[:limit * 2], 1):
            key = row["issue_id"] or f"row-{row['id']}"
            semantic_ranked[key] = {"rank": rank, "sim": sim, "row": row}

    # 2. Keyword search (ranked by recency, using all query variant terms)
    keyword_ranked = {}
    search_terms = []
    for q in queries:
        search_terms.extend(q.split())
    like_clauses = []
    params = []
    for term in search_terms[:5]:  # limit to 5 terms
        like_clauses.append(
            "(hostname LIKE ? OR alert_rule LIKE ? OR resolution LIKE ? OR tags LIKE ? OR root_cause LIKE ?)"
        )
        params.extend([f"%{term}%"] * 5)

    if like_clauses:
        where = " OR ".join(like_clauses)
        sql = (
            f"SELECT * FROM incident_knowledge "
            f"WHERE ({where}) {day_filter} "
            f"ORDER BY created_at DESC LIMIT ?"
        )
        params.append(limit * 2)
        kw_rows = conn.execute(sql, params).fetchall()
        for rank, row in enumerate(kw_rows, 1):
            key = row["issue_id"] or f"row-{row['id']}"
            keyword_ranked[key] = {"rank": rank, "row": row}

    # 3. Wiki article search (if wiki_articles table exists)
    wiki_ranked = {}
    try:
        wiki_rows = conn.execute(
            "SELECT path, title, section, embedding FROM wiki_articles "
            "WHERE embedding IS NOT NULL AND embedding != ''"
        ).fetchall()
        if wiki_rows:
            wiki_sims = {}
            for q in queries:
                q_vec = get_embedding(q)
                if not q_vec:
                    continue
                for wrow in wiki_rows:
                    try:
                        w_vec = json.loads(wrow["embedding"])
                        sim = cosine_similarity(q_vec, w_vec)
                        key = f"wiki:{wrow['path']}:{wrow['section']}"
                        if sim > threshold and (key not in wiki_sims or sim > wiki_sims[key][0]):
                            wiki_sims[key] = (sim, wrow)
                    except (json.JSONDecodeError, TypeError):
                        continue
            w_scored = sorted(wiki_sims.values(), key=lambda x: x[0], reverse=True)
            for rank, (sim, wrow) in enumerate(w_scored[:limit * 2], 1):
                key = f"wiki:{wrow['path']}:{wrow['section']}"
                wiki_ranked[key] = {"rank": rank, "sim": sim, "row": wrow}
    except sqlite3.OperationalError:
        pass  # wiki_articles table doesn't exist yet

    # 4. Session transcript search (4th signal — MemPalace verbatim storage)
    transcript_ranked = {}
    try:
        for q in queries:
            q_vec = get_embedding(q)
            if not q_vec:
                continue
            if days > 0:
                t_rows = conn.execute(
                    "SELECT id, issue_id, chunk_index, role, content, embedding, created_at "
                    "FROM session_transcripts "
                    "WHERE embedding IS NOT NULL AND embedding != '' "
                    "AND created_at > datetime('now', ?)",
                    (f"-{days} days",),
                ).fetchall()
            else:
                t_rows = conn.execute(
                    "SELECT id, issue_id, chunk_index, role, content, embedding, created_at "
                    "FROM session_transcripts "
                    "WHERE embedding IS NOT NULL AND embedding != ''"
                ).fetchall()
            for trow in t_rows:
                try:
                    t_vec = json.loads(trow["embedding"])
                    sim = cosine_similarity(q_vec, t_vec)
                    key = f"transcript:{trow['issue_id']}:{trow['chunk_index']}"
                    if sim > threshold and (key not in transcript_ranked or sim > transcript_ranked[key][0]):
                        transcript_ranked[key] = (sim, trow)
                except (json.JSONDecodeError, TypeError):
                    continue
    except sqlite3.OperationalError:
        pass  # session_transcripts table may not exist yet

    t_scored = sorted(transcript_ranked.values(), key=lambda x: x[0], reverse=True)
    transcript_rank_map = {}
    for rank, (sim, trow) in enumerate(t_scored[:limit * 2], 1):
        key = trow["issue_id"]
        if key not in transcript_rank_map or rank < transcript_rank_map[key]["rank"]:
            transcript_rank_map[key] = {"rank": rank, "sim": sim, "row": trow}

    # 5. Reciprocal Rank Fusion (4 signals + quality-based weighting)
    # Compute semantic quality for adaptive weighting
    sem_sims = [s["sim"] for s in semantic_ranked.values()] if semantic_ranked else []
    sem_quality = (sum(sem_sims) / len(sem_sims)) if sem_sims else None

    all_keys = set(semantic_ranked.keys()) | set(keyword_ranked.keys()) | set(transcript_rank_map.keys())
    fused = []
    for key in all_keys:
        sem = semantic_ranked.get(key)
        kw = keyword_ranked.get(key)
        tr = transcript_rank_map.get(key)
        sem_rank = sem["rank"] if sem else None
        kw_rank = kw["rank"] if kw else None
        tr_rank = tr["rank"] if tr else None
        score = rrf_score(sem_rank, kw_rank, transcript_rank=tr_rank, sem_quality=sem_quality)
        row = sem["row"] if sem else (kw["row"] if kw else tr["row"])
        sim = sem["sim"] if sem else (tr["sim"] if tr else 0.0)
        source = "incident"
        if not sem and not kw and tr:
            source = "transcript"
        fused.append((score, sim, row, source))

    # Add wiki results to fusion
    for key, wdata in wiki_ranked.items():
        w_rank = wdata["rank"]
        score = rrf_score(None, None, w_rank, sem_quality=sem_quality)
        fused.append((score, wdata["sim"], wdata["row"], "wiki"))

    fused.sort(key=lambda x: x[0], reverse=True)

    if not fused:
        conn.close()
        return 0

    for score, sim, row, source in fused[:limit]:
        if source == "wiki":
            print(
                f"wiki|{row['path']}|{row['title']}|"
                f"{(row['section'] or '').replace('|', ' ')[:200]}|"
                f"-1|{NOW_ISO}||{sim:.3f}"
            )
        elif source == "transcript":
            content = (row["content"] or "").replace("|", " ").replace("\n", " ")[:200]
            content += staleness_warning(row["created_at"])
            print(
                f"{row['issue_id']}|transcript|chunk-{row['chunk_index']}|"
                f"{content}|"
                f"-1|{row['created_at']}||{sim:.3f}"
            )
        else:
            resolution = (row["resolution"] or "").replace("|", " ").replace("\n", " ")[:200]
            resolution += staleness_warning(row["created_at"])
            print(
                f"{row['issue_id']}|{row['hostname']}|{row['alert_rule']}|"
                f"{resolution}|{row['confidence']}|{row['created_at']}|"
                f"{row['site']}|{sim:.3f}"
            )

    conn.close()
    return min(len(fused), limit)


def cmd_keyword_fallback(conn, query, limit, days):
    """Keyword fallback when embeddings unavailable."""
    search = f"%{query}%"
    day_filter = f"AND created_at > datetime('now', '-{days} days')" if days > 0 else ""
    validity = "AND (valid_until IS NULL OR valid_until > datetime('now'))"
    rows = conn.execute(
        f"SELECT issue_id, hostname, alert_rule, resolution, confidence, created_at, site "
        f"FROM incident_knowledge "
        f"WHERE (hostname LIKE ? OR alert_rule LIKE ? OR resolution LIKE ? OR tags LIKE ?) "
        f"{day_filter} {validity} "
        f"ORDER BY created_at DESC LIMIT ?",
        (search, search, search, search, limit),
    ).fetchall()
    for row in rows:
        resolution = (row["resolution"] or "").replace("|", " ").replace("\n", " ")[:200]
        resolution += staleness_warning(row["created_at"])
        print(
            f"{row['issue_id']}|{row['hostname']}|{row['alert_rule']}|"
            f"{resolution}|{row['confidence']}|{row['created_at']}|"
            f"{row['site']}|0.000"
        )
    conn.close()
    return len(rows)


def ensure_wiki_table(conn):
    """Create wiki_articles table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wiki_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            section TEXT DEFAULT '',
            content_hash TEXT NOT NULL,
            embedding TEXT DEFAULT '',
            compiled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_files TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wa_path ON wiki_articles(path)")
    conn.commit()


def cmd_wiki_embed():
    """Embed wiki articles by section into wiki_articles table."""
    import hashlib

    if not os.path.isdir(WIKI_DIR):
        print("No wiki/ directory found. Run wiki-compile.py first.")
        return 0

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_wiki_table(conn)

    count = 0
    for root, _dirs, files in os.walk(WIKI_DIR):
        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, WIKI_DIR)

            with open(fpath, "r") as f:
                content = f.read()

            content_hash = hashlib.sha256(content.encode()).hexdigest()

            # Check if already embedded with same hash
            existing = conn.execute(
                "SELECT content_hash FROM wiki_articles WHERE path = ? AND section = ''",
                (rel_path,),
            ).fetchone()
            if existing and existing["content_hash"] == content_hash:
                continue  # No change

            # Chunk by ## headings
            sections = []
            current_section = ""
            current_title = os.path.splitext(fname)[0].replace("-", " ").title()
            current_text = []

            for line in content.split("\n"):
                if line.startswith("## "):
                    if current_text:
                        sections.append((current_title, "\n".join(current_text)))
                    current_title = line.lstrip("# ").strip()
                    current_text = [line]
                else:
                    current_text.append(line)
            if current_text:
                sections.append((current_title, "\n".join(current_text)))

            # Embed each section
            for section_title, section_text in sections:
                if len(section_text.strip()) < 50:
                    continue  # Skip trivial sections

                embed_text = f"{section_title}: {section_text[:500]}"
                vec = get_embedding(embed_text)
                if not vec:
                    continue

                section_key = section_title[:100]
                conn.execute(
                    "INSERT OR REPLACE INTO wiki_articles "
                    "(path, title, section, content_hash, embedding, compiled_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                    (rel_path, current_title, section_key, content_hash, json.dumps(vec)),
                )
                count += 1

            # Also store whole-article entry (for path-based lookups)
            whole_text = f"{rel_path}: {content[:500]}"
            vec = get_embedding(whole_text)
            if vec:
                conn.execute(
                    "INSERT OR REPLACE INTO wiki_articles "
                    "(path, title, section, content_hash, embedding, compiled_at) "
                    "VALUES (?, ?, '', ?, ?, datetime('now'))",
                    (rel_path, current_title, content_hash, json.dumps(vec)),
                )
                count += 1

    conn.commit()
    conn.close()
    print(f"Embedded {count} wiki sections/articles.")
    return count


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "embed":
        backfill = "--backfill" in sys.argv
        cmd_embed(backfill=backfill)

    elif cmd == "wiki-embed":
        cmd_wiki_embed()

    elif cmd == "search":
        if len(sys.argv) < 3:
            print("Usage: kb-semantic-search.py search 'query text' [--limit N] [--days N] [--threshold F] [--mode hybrid|semantic|keyword]")
            sys.exit(1)
        query = sys.argv[2]
        limit = 5
        days = 90
        threshold = 0.3
        mode = "hybrid"
        use_rewrite = False
        for i, arg in enumerate(sys.argv[3:], 3):
            if arg == "--limit" and i + 1 < len(sys.argv):
                limit = int(sys.argv[i + 1])
            elif arg == "--days" and i + 1 < len(sys.argv):
                days = int(sys.argv[i + 1])
            elif arg == "--threshold" and i + 1 < len(sys.argv):
                threshold = float(sys.argv[i + 1])
            elif arg == "--mode" and i + 1 < len(sys.argv):
                mode = sys.argv[i + 1]
            elif arg == "--rewrite":
                use_rewrite = True
        if mode == "hybrid":
            cmd_hybrid_search(query, limit=limit, days=days, threshold=threshold, use_rewrite=use_rewrite)
        elif mode == "keyword":
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cmd_keyword_fallback(conn, query, limit, days)
        else:
            cmd_search(query, limit=limit, days=days, threshold=threshold)

    elif cmd == "invalidate":
        if len(sys.argv) < 4:
            print("Usage: kb-semantic-search.py invalidate <hostname> <alert_rule>")
            sys.exit(1)
        cmd_invalidate(sys.argv[2], sys.argv[3])

    elif cmd == "graph":
        if len(sys.argv) < 3:
            print("Usage: kb-semantic-search.py graph <hostname>")
            sys.exit(1)
        cmd_graph(sys.argv[2])

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
