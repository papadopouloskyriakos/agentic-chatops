#!/usr/bin/env python3
"""Index all memory/CLAUDE.md/rules files into wiki_articles for retrieval.

These files contain the most actionable knowledge (feedback, project facts,
references) but were never embedded. Running this closes the query-to-knowledge
gap exposed by the 20-query hard eval set.

Usage:
  index-memories.py
"""
import hashlib
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "kb_semantic_search",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb-semantic-search.py"),
)
kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kb)

DB_PATH = kb.DB_PATH
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR = os.path.expanduser(
    "~/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory"
)
CLAUDE_MD_DIRS = [
    REPO_DIR,
    os.path.join(REPO_DIR, ".claude/rules"),
]


def collect_sources():
    out = []
    # Memory files — include MEMORY.md too; its architecture rollup answers meta-queries
    if os.path.isdir(MEMORY_DIR):
        for fname in sorted(os.listdir(MEMORY_DIR)):
            if fname.endswith(".md"):
                out.append(("memory", os.path.join(MEMORY_DIR, fname)))
    # CLAUDE.md + .claude/rules files
    for d in CLAUDE_MD_DIRS:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".md") and f not in ("README.md",):
                out.append(("project-docs", os.path.join(d, f)))
    # docs/*.md — scorecard reports, runbooks, incident writeups live here
    docs_dir = os.path.join(REPO_DIR, "docs")
    if os.path.isdir(docs_dir):
        for root, _dirs, files in os.walk(docs_dir):
            for f in files:
                if f.endswith(".md"):
                    out.append(("docs", os.path.join(root, f)))
    return out


def chunk_by_sections(body, max_chunk_chars=1500, min_chunk_chars=200):
    """Split body into chunks along ## headings. Each chunk <= max_chunk_chars.

    D3: Min chunk size 200 chars — below this a chunk is too short to carry useful
    signal through embedding (tends to match on generic terms and pollute retrieval).
    Short tail sections are merged into the preceding one instead of emitted alone.
    """
    chunks = []
    lines = body.split("\n")
    current_section = "intro"
    current_buf = []
    current_len = 0

    def flush(section, buf):
        text = "\n".join(buf).strip()
        if len(text) >= min_chunk_chars:
            chunks.append((section, text))
        elif chunks:
            # Merge too-short tail into the previous chunk instead of dropping
            prev_section, prev_text = chunks[-1]
            merged = (prev_text + "\n\n" + text).strip()
            chunks[-1] = (prev_section, merged)

    for line in lines:
        if line.startswith("## "):
            flush(current_section, current_buf)
            current_section = line.lstrip("# ").strip()[:80]
            current_buf = []
            current_len = 0
            continue
        current_buf.append(line)
        current_len += len(line) + 1
        if current_len > max_chunk_chars:
            flush(current_section, current_buf)
            current_buf = []
            current_len = 0
    flush(current_section, current_buf)
    return chunks


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Ensure content_preview + source_mtime columns (live ALTER fallback — idempotent via migration 004/005)
    for stmt in (
        "ALTER TABLE wiki_articles ADD COLUMN content_preview TEXT DEFAULT ''",
        "ALTER TABLE wiki_articles ADD COLUMN source_mtime REAL DEFAULT 0",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    sources = collect_sources()
    print(f"collected {len(sources)} candidate files")
    texts, metas = [], []
    for src_type, fpath in sources:
        try:
            with open(fpath) as f:
                raw = f.read()
        except Exception as e:
            print(f"  skip {fpath}: {e}", file=sys.stderr)
            continue
        if len(raw.strip()) < 50:
            continue
        try:
            file_mtime = os.path.getmtime(fpath)
        except OSError:
            file_mtime = 0.0
        rel = os.path.relpath(fpath, os.path.dirname(fpath) if src_type != "project-docs" else REPO_DIR)
        # Parse YAML frontmatter — keep the description for embedding context
        body = raw
        fm_description = ""
        if raw.startswith("---\n"):
            end = raw.find("\n---\n", 4)
            if end > 0:
                fm_block = raw[4:end]
                body = raw[end + 5:]
                for line in fm_block.split("\n"):
                    if line.startswith("description:"):
                        fm_description = line.split(":", 1)[1].strip().strip('"').strip("'")
                        break
        path_key_base = f"{src_type}/{rel}"
        title_base = rel.replace(".md", "").replace("_", " ").replace("-", " ")

        # Small files: single chunk (whole-file semantics)
        if len(body) <= 2000:
            content_hash = hashlib.sha256((fm_description + body).encode()).hexdigest()
            parts = [title_base]
            if fm_description:
                parts.append(fm_description)
            parts.append(body[:800])
            embed_text = " | ".join(parts)
            texts.append(embed_text)
            metas.append((path_key_base, "", title_base, content_hash, body[:1200], file_mtime))
            continue

        # Large files: split on ## headings so every section is retrievable
        sections = chunk_by_sections(body)
        for section, section_text in sections:
            path_key = f"{path_key_base}#{section[:40].replace(' ', '-').lower()}"
            content_hash = hashlib.sha256((fm_description + section + section_text).encode()).hexdigest()
            parts = [title_base]
            if fm_description:
                parts.append(fm_description)
            parts.append(section)
            parts.append(section_text[:700])
            embed_text = " | ".join(parts)
            texts.append(embed_text)
            metas.append((path_key, section, title_base, content_hash, section_text[:1200], file_mtime))

    print(f"embedding {len(texts)} files ...")
    t0 = time.time()
    # Batch in groups of 16
    BATCH = 16
    vecs = []
    for i in range(0, len(texts), BATCH):
        chunk = texts[i:i + BATCH]
        vs = kb.batch_embed_documents(chunk)
        if not vs:
            vs = [None] * len(chunk)
        vecs.extend(vs)
    dt = time.time() - t0
    print(f"  embed: {dt:.1f}s ({len(texts)/max(dt,0.01):.1f} files/s)")

    # Insert into wiki_articles with unique (path, section) composite key
    inserted = 0
    for (path_key, section, title, chash, preview, mtime), vec in zip(metas, vecs):
        if vec is None:
            continue
        try:
            conn.execute(
                "INSERT OR REPLACE INTO wiki_articles "
                "(path, title, section, content_hash, embedding, content_preview, compiled_at, source_mtime) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?)",
                (path_key, title, section, chash, json.dumps(vec), preview, mtime),
            )
            inserted += 1
        except Exception as e:
            print(f"  insert err {path_key}: {e}", file=sys.stderr)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM wiki_articles WHERE embedding != ''").fetchone()[0]
    conn.close()
    print(f"indexed {inserted} memory/CLAUDE.md files; wiki_articles now {total} rows")


if __name__ == "__main__":
    main()
