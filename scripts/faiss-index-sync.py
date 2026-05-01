#!/usr/bin/env python3
"""G6: Sync SQLite embeddings to a local FAISS HNSW index. Parallel-write path.

Read path stays on SQLite until migration trigger (see bench-vector-search.py).
This script keeps a ready-to-cut-over index up to date as a cron job.

Output: `/var/claude-gateway/vector-indexes/{table}.faiss` + `{table}.idmap.json`

Usage:
  faiss-index-sync.py            # sync all tables
  faiss-index-sync.py --table incident_knowledge
  faiss-index-sync.py --verify   # sanity check existing indexes
"""
import argparse
import json
import os
import sqlite3
import sys
import time

import numpy as np
import faiss

_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_script_dir, "lib"))
from rag_config import EMBED_TABLES  # noqa: E402

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
INDEX_DIR = os.environ.get(
    "FAISS_INDEX_DIR",
    "/var/claude-gateway/vector-indexes",
)
DIM = 768
EMBED_MODEL_VERSION = os.environ.get("EMBED_MODEL", "nomic-embed-text")

# (pk_col, label_col) per table. Keep in sync with rag_config.EMBED_TABLES —
# the assert below catches accidental drift between what the retriever signals
# over and what FAISS pre-indexes.
TABLES = {
    "incident_knowledge": ("id", "issue_id"),
    "wiki_articles": ("id", "path"),
    "session_transcripts": ("id", "issue_id"),
    "chaos_experiments": ("id", "experiment_id"),
}
_missing = set(EMBED_TABLES) - set(TABLES.keys())
assert not _missing, f"FAISS sync TABLES missing rag_config.EMBED_TABLES entries: {_missing}"


def build_index_for_table(table, pk_col, label_col, verbose=True):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT {pk_col}, {label_col}, embedding FROM {table} "
        f"WHERE embedding IS NOT NULL AND embedding != ''"
    ).fetchall()
    conn.close()

    if not rows:
        if verbose:
            print(f"[{table}] no embeddings to index")
        return 0

    vecs = []
    idmap = []
    for r in rows:
        try:
            v = json.loads(r["embedding"])
            if len(v) != DIM:
                continue
            vecs.append(v)
            idmap.append({"pk": r[pk_col], "label": r[label_col]})
        except Exception:
            continue

    arr = np.array(vecs, dtype=np.float32)
    # Normalize for cosine-via-inner-product
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms

    # HNSW index — best speed/recall balance at our scale
    index = faiss.IndexHNSWFlat(DIM, 32, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = 128
    index.hnsw.efSearch = 64
    index.add(arr)

    os.makedirs(INDEX_DIR, exist_ok=True)
    index_path = os.path.join(INDEX_DIR, f"{table}.faiss")
    idmap_path = os.path.join(INDEX_DIR, f"{table}.idmap.json")

    faiss.write_index(index, index_path)
    with open(idmap_path, "w") as f:
        json.dump({
            "table": table,
            "count": len(idmap),
            "dim": DIM,
            "embed_model": EMBED_MODEL_VERSION,
            "index_type": "HNSW_Flat",
            "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "idmap": idmap,
        }, f)

    if verbose:
        print(f"[{table}] indexed {len(idmap)} vectors -> {index_path}")
    return len(idmap)


def verify(table, pk_col, label_col):
    index_path = os.path.join(INDEX_DIR, f"{table}.faiss")
    idmap_path = os.path.join(INDEX_DIR, f"{table}.idmap.json")
    if not os.path.exists(index_path):
        print(f"[{table}] MISSING index at {index_path}")
        return False
    with open(idmap_path) as f:
        meta = json.load(f)
    index = faiss.read_index(index_path)
    print(f"[{table}] count={meta['count']}, dim={meta['dim']}, synced_at={meta['synced_at']}, n_in_index={index.ntotal}")
    if meta["embed_model"] != EMBED_MODEL_VERSION:
        print(f"  WARNING: embed model drift {meta['embed_model']} -> {EMBED_MODEL_VERSION}; rebuild recommended")
        return False
    return meta["count"] == index.ntotal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", help="specific table; default all")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    tables = [args.table] if args.table else list(TABLES.keys())
    if args.verify:
        ok = all(verify(t, *TABLES[t]) for t in tables)
        sys.exit(0 if ok else 1)

    total = 0
    t0 = time.time()
    for t in tables:
        total += build_index_for_table(t, *TABLES[t])
    dt = time.time() - t0
    print(f"synced {total} vectors across {len(tables)} tables in {dt:.1f}s")


if __name__ == "__main__":
    main()
