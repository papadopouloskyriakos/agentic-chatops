#!/usr/bin/env python3
"""G7: Migrate all embeddings to nomic-embed-text asymmetric search_document: prefix.

Re-embeds:
  - incident_knowledge  (51 rows)
  - wiki_articles       (45 rows)
  - session_transcripts (837 rows — initial backfill; historically 0 embedded)

Uses batch_embed_documents() from kb-semantic-search (6x faster than sequential).

Usage:
  migrate-embeddings.py --dry-run       # Compute + compare, do not write
  migrate-embeddings.py --apply         # Actually re-embed and commit
  migrate-embeddings.py --table session_transcripts --apply
"""
import sys
import os
import json
import sqlite3
import math
import time

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "kb_semantic_search",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb-semantic-search.py"),
)
kb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kb)

DB_PATH = kb.DB_PATH
BATCH = 16


def _cos(a, b):
    if a is None or b is None:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na * nb else 0.0


def build_text_incident(row):
    parts = []
    for k in ("alert_rule", "hostname", "root_cause", "resolution", "tags"):
        v = row[k] if k in row.keys() else None
        if v:
            parts.append(f"{k}: {v}")
    return " | ".join(parts)


def build_text_wiki(row):
    return f"{row['title'] or row['path']}: {(row['section'] or '')[:500]}"


def build_text_transcript(row):
    # Verbatim content, prefixed with role for context
    content = (row["content"] or "")[:800]
    return f"[{row['role']}] {content}"


def build_text_chaos(row):
    # Compose chaos findings for searchability
    parts = []
    for k in ("chaos_type", "targets", "hypothesis", "verdict", "verdict_details"):
        v = row[k] if k in row.keys() else None
        if v:
            parts.append(f"{k}: {str(v)[:300]}")
    return " | ".join(parts)


TABLES = {
    "incident_knowledge": {
        "select": "SELECT * FROM incident_knowledge",
        "id_col": "id",
        "text_fn": build_text_incident,
    },
    "wiki_articles": {
        "select": "SELECT * FROM wiki_articles",
        "id_col": "id",
        "text_fn": build_text_wiki,
    },
    "session_transcripts": {
        "select": "SELECT * FROM session_transcripts",
        "id_col": "id",
        "text_fn": build_text_transcript,
    },
    "chaos_experiments": {
        "select": "SELECT * FROM chaos_experiments",
        "id_col": "id",
        "text_fn": build_text_chaos,
    },
}


def migrate_table(table_name, conn, apply=False, verbose=True):
    spec = TABLES[table_name]
    rows = conn.execute(spec["select"]).fetchall()
    n = len(rows)
    print(f"\n=== {table_name}: {n} rows ===")
    texts, ids, olds = [], [], []
    for r in rows:
        t = spec["text_fn"](r)
        if not t or len(t.strip()) < 10:
            continue
        texts.append(t)
        ids.append(r[spec["id_col"]])
        old_emb = None
        try:
            raw = r["embedding"] if "embedding" in r.keys() else ""
            if raw:
                old_emb = json.loads(raw)
        except Exception:
            old_emb = None
        olds.append(old_emb)

    print(f"  to embed: {len(texts)}")
    if not texts:
        return 0, 0

    total_batches = (len(texts) + BATCH - 1) // BATCH
    drift_samples = []
    updated = 0
    t0 = time.time()

    for bi in range(0, len(texts), BATCH):
        chunk = texts[bi : bi + BATCH]
        chunk_ids = ids[bi : bi + BATCH]
        chunk_olds = olds[bi : bi + BATCH]
        vecs = kb.batch_embed_documents(chunk)
        if not vecs or any(v is None for v in vecs):
            print(f"  batch {bi//BATCH+1}/{total_batches} FAILED — skipping", file=sys.stderr)
            continue
        if apply:
            for rid, vec in zip(chunk_ids, vecs):
                conn.execute(
                    f"UPDATE {table_name} SET embedding = ? WHERE {spec['id_col']} = ?",
                    (json.dumps(vec), rid),
                )
                updated += 1
            conn.commit()
        # Record cosine delta (old vs new) for drift check
        for old, new in zip(chunk_olds, vecs):
            if old is not None and new is not None:
                drift_samples.append(_cos(old, new))
        if verbose and bi % (BATCH * 5) == 0:
            pct = 100 * (bi + len(chunk)) / len(texts)
            print(f"  [{pct:5.1f}%] batch {bi//BATCH+1}/{total_batches}")

    dt = time.time() - t0
    print(f"  wall clock: {dt:.1f}s  ({len(texts)/dt:.1f} rows/s)")
    if drift_samples:
        drift_mean = sum(drift_samples) / len(drift_samples)
        drift_min = min(drift_samples)
        print(f"  cosine(old,new) samples={len(drift_samples)}  mean={drift_mean:.3f}  min={drift_min:.3f}")
        if drift_mean > 0.98 and len(drift_samples) > 5:
            print(f"  WARNING: high similarity suggests prefix not applied (expected ~0.85-0.95 with asymmetric shift)")
    print(f"  {'APPLIED' if apply else 'DRY-RUN'}: {updated} rows updated")
    return updated, len(texts)


def main():
    apply = "--apply" in sys.argv
    table_arg = None
    if "--table" in sys.argv:
        idx = sys.argv.index("--table")
        table_arg = sys.argv[idx + 1]

    if not apply and "--dry-run" not in sys.argv:
        print(__doc__)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tables = [table_arg] if table_arg else list(TABLES.keys())
    total_upd, total_scan = 0, 0
    for t in tables:
        u, s = migrate_table(t, conn, apply=apply)
        total_upd += u
        total_scan += s
    print(f"\n=== TOTAL: {total_upd} updated / {total_scan} scanned ({'APPLIED' if apply else 'dry-run'}) ===")
    conn.close()


if __name__ == "__main__":
    main()
