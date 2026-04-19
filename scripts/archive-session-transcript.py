#!/usr/bin/env python3
"""Archive session JSONL transcripts to SQLite with embeddings.

Adapted from MemPalace convo_miner.py exchange-pair chunking.
Reads JSONL from /tmp/claude-run-<ISSUE>.jsonl, chunks by exchange pairs,
inserts into session_transcripts table, generates embeddings via Ollama.

Usage:
  archive-session-transcript.py <issue_id> [--session-id <sid>] [--embed]
  archive-session-transcript.py backfill-embed   # embed all missing
"""
import sys
import os
import json
import sqlite3
import gzip
import shutil
import hashlib
REDACTED_a7b84d63
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
ARCHIVE_DIR = os.path.expanduser("~/session-archives")
OLLAMA_URL = "http://nl-gpu01:11434"
EMBED_MODEL = "nomic-embed-text"
MIN_CHUNK_CHARS = 30
MAX_CHUNK_CHARS = 4000


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def parse_jsonl(path):
    """Parse JSONL transcript, extract user/assistant exchange pairs."""
    exchanges = []
    current_role = None
    current_content = []

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # stream-json format: look for message events
            msg_type = entry.get("type", "")
            role = entry.get("role", "")
            content = ""

            if msg_type == "result":
                # Final result message
                result = entry.get("result", "")
                if isinstance(result, str) and result:
                    content = result
                    role = "assistant"
                elif isinstance(result, dict):
                    content = result.get("text", "") or json.dumps(result)
                    role = "assistant"

            elif msg_type == "message":
                msg = entry.get("message", {})
                role = msg.get("role", role)
                msg_content = msg.get("content", "")
                if isinstance(msg_content, list):
                    parts = []
                    for block in msg_content:
                        if isinstance(block, dict):
                            parts.append(block.get("text", ""))
                    content = "\n".join(p for p in parts if p)
                elif isinstance(msg_content, str):
                    content = msg_content

            elif msg_type == "assistant" and entry.get("message"):
                msg = entry["message"]
                role = "assistant"
                msg_content = msg.get("content", "")
                if isinstance(msg_content, list):
                    parts = [b.get("text", "") for b in msg_content if isinstance(b, dict)]
                    content = "\n".join(p for p in parts if p)
                elif isinstance(msg_content, str):
                    content = msg_content

            # CLI session format: type=="user" with message.content (string or list)
            elif msg_type == "user" and entry.get("message"):
                msg = entry["message"]
                role = "user"
                msg_content = msg.get("content", "")
                if isinstance(msg_content, list):
                    parts = [b.get("text", "") for b in msg_content if isinstance(b, dict)]
                    content = "\n".join(p for p in parts if p)
                elif isinstance(msg_content, str):
                    content = msg_content

            if not content or not role:
                continue

            # Flush previous if role changed
            if role != current_role and current_content:
                text = "\n".join(current_content)
                if len(text) >= MIN_CHUNK_CHARS:
                    exchanges.append({"role": current_role, "content": text[:MAX_CHUNK_CHARS]})
                current_content = []

            current_role = role
            current_content.append(content)

    # Flush last
    if current_content:
        text = "\n".join(current_content)
        if len(text) >= MIN_CHUNK_CHARS:
            exchanges.append({"role": current_role, "content": text[:MAX_CHUNK_CHARS]})

    return exchanges


def chunk_exchange_pairs(exchanges):
    """Group into exchange pairs (user + assistant = one chunk) like MemPalace."""
    chunks = []
    i = 0
    chunk_idx = 0
    while i < len(exchanges):
        pair_parts = []
        roles = []

        # Take user message
        if exchanges[i]["role"] == "user":
            pair_parts.append(f"USER: {exchanges[i]['content']}")
            roles.append("user")
            i += 1

        # Take following assistant message
        if i < len(exchanges) and exchanges[i]["role"] == "assistant":
            pair_parts.append(f"ASSISTANT: {exchanges[i]['content']}")
            roles.append("assistant")
            i += 1

        if pair_parts:
            chunks.append({
                "chunk_index": chunk_idx,
                "role": "+".join(roles),
                "content": "\n\n".join(pair_parts)
            })
            chunk_idx += 1
            continue

        # Standalone assistant message (no preceding user)
        if exchanges[i]["role"] == "assistant":
            chunks.append({
                "chunk_index": chunk_idx,
                "role": "assistant",
                "content": f"ASSISTANT: {exchanges[i]['content']}"
            })
            chunk_idx += 1

        i += 1

    return chunks


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
    """Generate embedding via Ollama nomic-embed-text with asymmetric document prefix (G7)."""
    try:
        import urllib.request
        # search_document: prefix matches kb-semantic-search.py embed_document
        prefixed = f"search_document: {text[:2000]}"
        # options.num_ctx keeps nomic on GPU under CONTEXT_LENGTH=64k global setting
        data = json.dumps({
            "model": EMBED_MODEL,
            "input": prefixed,
            "options": {"num_ctx": 2048},
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embed",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            _record_local_usage(EMBED_MODEL, result.get("prompt_eval_count", 0))
            emb = result.get("embeddings", [[]])[0]
            return json.dumps(emb) if emb else ""
    except Exception:
        return ""


def archive_transcript(issue_id, session_id="", embed=True, source_path=None):
    """Main: parse JSONL, chunk, insert, optionally embed, archive."""
    jsonl_path = source_path or f"/tmp/claude-run-{issue_id}.jsonl"
    if not os.path.exists(jsonl_path):
        print(f"[archive] No JSONL found at {jsonl_path}")
        return 0

    # Parse and chunk
    exchanges = parse_jsonl(jsonl_path)
    if not exchanges:
        print(f"[archive] No exchanges parsed from {jsonl_path}")
        return 0

    chunks = chunk_exchange_pairs(exchanges)
    print(f"[archive] {issue_id}: {len(exchanges)} exchanges → {len(chunks)} chunks")

    # Insert into SQLite
    conn = get_db()
    inserted = 0
    for chunk in chunks:
        # Idempotent: check if already exists
        existing = conn.execute(
            "SELECT id FROM session_transcripts WHERE issue_id=? AND chunk_index=?",
            (issue_id, chunk["chunk_index"])
        ).fetchone()
        if existing:
            continue

        embedding = ""
        if embed:
            embedding = generate_embedding(chunk["content"])

        conn.execute(
            "INSERT INTO session_transcripts (issue_id, session_id, chunk_index, role, content, embedding, source_file) VALUES (?,?,?,?,?,?,?)",
            (issue_id, session_id, chunk["chunk_index"], chunk["role"], chunk["content"], embedding, jsonl_path)
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"[archive] Inserted {inserted} chunks for {issue_id}")

    # Archive raw JSONL
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(ARCHIVE_DIR, f"{issue_id}.jsonl.gz")
    if not os.path.exists(archive_path):
        with open(jsonl_path, "rb") as f_in:
            with gzip.open(archive_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        print(f"[archive] Archived to {archive_path}")

    # #18: If the session was long, run doc-chain refine to produce a condensed summary
    # and insert it as a special chunk_index=-1 row. Session End workflow can use this
    # for concise YT comments instead of the raw truncated resolution.
    generate_session_summary(issue_id, jsonl_path)

    return inserted


def generate_session_summary(issue_id, jsonl_path, char_threshold=5000):
    """#18: Run doc-chain refine on long sessions.

    Extracts assistant message content, checks size, runs refine chain on qwen2.5:7b,
    stores result in session_transcripts as chunk_index=-1 with role='summary'.

    Skips silently if:
    - Total assistant content < char_threshold
    - doc-chain.py unavailable / fails
    """
    try:
        assistant_chars = 0
        all_content = []
        with open(jsonl_path) as f:
            for line in f:
                try:
                    evt = json.loads(line)
                    # Accept both message.role='assistant' and direct role field
                    role = ""
                    content = ""
                    if isinstance(evt, dict):
                        msg = evt.get("message") or evt
                        role = msg.get("role", "") if isinstance(msg, dict) else ""
                        raw_content = msg.get("content") if isinstance(msg, dict) else None
                        if isinstance(raw_content, list):
                            for blk in raw_content:
                                if isinstance(blk, dict) and blk.get("type") == "text":
                                    content += blk.get("text", "")
                        elif isinstance(raw_content, str):
                            content = raw_content
                    if role == "assistant" and content:
                        assistant_chars += len(content)
                        all_content.append(content)
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

        if assistant_chars < char_threshold:
            print(f"[summary] session {issue_id} too short ({assistant_chars} chars) — skip refine")
            return

        combined = "\n\n".join(all_content)
        # Invoke doc-chain refine via subprocess (keeps imports minimal)
        dc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doc-chain.py")
        if not os.path.exists(dc_path):
            print(f"[summary] doc-chain.py not found — skip", file=sys.stderr)
            return
        # map-reduce is parallel (ThreadPool 4) — much faster than refine on long content
        proc = __import__("subprocess").run(
            ["python3", dc_path, "map-reduce", "--stdin",
             "--query", "Summarize this session: key decisions, commands run, findings, open items."],
            input=combined, capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            print(f"[summary] doc-chain failed rc={proc.returncode}: {proc.stderr[:200]}", file=sys.stderr)
            return
        summary = proc.stdout.strip()
        if len(summary) < 50:
            print(f"[summary] doc-chain output too short — skip", file=sys.stderr)
            return

        # Insert as a marker row (chunk_index=-1, role='summary')
        emb = generate_embedding(summary) if ("--no-embed" not in sys.argv) else ""
        conn = get_db()
        conn.execute(
            "INSERT INTO session_transcripts "
            "(issue_id, session_id, chunk_index, role, content, embedding, source_file) "
            "VALUES (?, '', -1, 'summary', ?, ?, ?)",
            (issue_id, summary, emb, jsonl_path),
        )
        conn.commit()
        conn.close()
        print(f"[summary] refined {assistant_chars}-char session into {len(summary)}-char summary ({issue_id})")
    except Exception as exc:
        print(f"[summary] refine failed: {exc}", file=sys.stderr)


def backfill_embeddings():
    """Generate embeddings for all chunks missing them."""
    conn = get_db()
    rows = conn.execute(
        "SELECT id, content FROM session_transcripts WHERE embedding='' OR embedding IS NULL"
    ).fetchall()
    print(f"[backfill] {len(rows)} chunks need embeddings")

    for row_id, content in rows:
        emb = generate_embedding(content)
        if emb:
            conn.execute("UPDATE session_transcripts SET embedding=? WHERE id=?", (emb, row_id))
    conn.commit()
    conn.close()
    print(f"[backfill] Done")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: archive-session-transcript.py <issue_id> [--session-id <sid>] [--embed]")
        print("       archive-session-transcript.py backfill-embed")
        sys.exit(1)

    if sys.argv[1] == "backfill-embed":
        backfill_embeddings()
    else:
        issue_id = sys.argv[1]
        session_id = ""
        # G7: embed defaults ON — use --no-embed to explicitly skip
        embed = "--no-embed" not in sys.argv
        source_path = None
        for i, arg in enumerate(sys.argv):
            if arg == "--session-id" and i + 1 < len(sys.argv):
                session_id = sys.argv[i + 1]
            elif arg == "--source" and i + 1 < len(sys.argv):
                source_path = sys.argv[i + 1]
        archive_transcript(issue_id, session_id, embed, source_path)
