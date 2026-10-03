#!/usr/bin/env python3
"""G6+G8: Vector DB benchmark. SQLite pure-Python cosine vs faiss-cpu Flat/HNSW/IVF.

Generates synthetic 768-dim vectors (nomic dim), runs 100 queries per config,
reports p50/p95/p99.

Prints a migration trigger recommendation based on current scale.

Usage:
  bench-vector-search.py              # full suite
  bench-vector-search.py --sizes 1000,10000
  bench-vector-search.py --md         # Markdown report (for doc commit)
"""
import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
import time

import numpy as np

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    print("WARN: faiss not installed — will benchmark only SQLite", file=sys.stderr)


DIM = 768  # nomic-embed-text dimension


def gen_vectors(n, dim=DIM, seed=42):
    """Deterministic normalized random vectors."""
    rng = np.random.default_rng(seed)
    vecs = rng.standard_normal((n, dim), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / norms


def cosine_sim_python(a, b):
    """Pure-Python cosine — mirrors production."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na * nb else 0.0


def bench_sqlite_python(n, q=100):
    """SQLite-ish: linear scan with pure Python cosine (mirrors kb-semantic-search.py)."""
    docs = gen_vectors(n)
    queries = gen_vectors(q, seed=99)
    # Store as Python lists (mirrors JSON-decoded state in prod)
    docs_py = [v.tolist() for v in docs]
    latencies = []
    for qv in queries:
        qv_py = qv.tolist()
        t0 = time.perf_counter()
        scored = sorted(
            [(cosine_sim_python(qv_py, d), i) for i, d in enumerate(docs_py)],
            reverse=True,
        )[:5]
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def bench_faiss_flat(n, q=100):
    """FAISS IndexFlatIP (inner product on L2-normalized = cosine)."""
    docs = gen_vectors(n)
    queries = gen_vectors(q, seed=99)
    index = faiss.IndexFlatIP(DIM)
    index.add(docs)
    latencies = []
    for qv in queries:
        t0 = time.perf_counter()
        index.search(qv.reshape(1, -1), 5)
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def bench_faiss_hnsw(n, q=100):
    """FAISS HNSW with M=32, ef=128 — production-quality approximate search."""
    docs = gen_vectors(n)
    queries = gen_vectors(q, seed=99)
    index = faiss.IndexHNSWFlat(DIM, 32, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = 128
    index.hnsw.efSearch = 64
    index.add(docs)
    latencies = []
    for qv in queries:
        t0 = time.perf_counter()
        index.search(qv.reshape(1, -1), 5)
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def bench_faiss_ivf(n, q=100):
    """FAISS IVF-Flat, nlist=100 — speed+memory balance."""
    docs = gen_vectors(n)
    queries = gen_vectors(q, seed=99)
    nlist = min(100, max(4, int(math.sqrt(n))))
    quantizer = faiss.IndexFlatIP(DIM)
    index = faiss.IndexIVFFlat(quantizer, DIM, nlist, faiss.METRIC_INNER_PRODUCT)
    index.train(docs)
    index.add(docs)
    index.nprobe = min(10, nlist)
    latencies = []
    for qv in queries:
        t0 = time.perf_counter()
        index.search(qv.reshape(1, -1), 5)
        latencies.append((time.perf_counter() - t0) * 1000)
    return latencies


def summarize(latencies):
    sorted_l = sorted(latencies)
    return {
        "count": len(latencies),
        "p50_ms": round(statistics.median(sorted_l), 3),
        "p95_ms": round(sorted_l[int(len(sorted_l) * 0.95)], 3),
        "p99_ms": round(sorted_l[int(len(sorted_l) * 0.99)], 3),
        "mean_ms": round(statistics.mean(sorted_l), 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="1000,10000,100000")
    parser.add_argument("--md", action="store_true", help="Emit markdown report")
    parser.add_argument("--queries", type=int, default=100)
    args = parser.parse_args()

    sizes = [int(s) for s in args.sizes.split(",")]
    results = {}
    configs = [("sqlite_python", bench_sqlite_python)]
    if HAS_FAISS:
        configs += [
            ("faiss_flat", bench_faiss_flat),
            ("faiss_hnsw", bench_faiss_hnsw),
            ("faiss_ivf", bench_faiss_ivf),
        ]

    for n in sizes:
        results[n] = {}
        for name, fn in configs:
            # Skip pure-Python cosine beyond 10k — too slow to bench sensibly (minutes per run)
            if name == "sqlite_python" and n > 10000:
                results[n][name] = {"note": "skipped (projected >15min); extrapolate linearly from 10k"}
                print(f"Skipping {name} @ N={n} — would take >15min", file=sys.stderr)
                continue
            print(f"Running {name} @ N={n}...", file=sys.stderr)
            try:
                lat = fn(n, q=args.queries)
                results[n][name] = summarize(lat)
            except Exception as e:
                print(f"  {name} FAILED: {e}", file=sys.stderr)
                results[n][name] = {"error": str(e)}

    # Current production scale
    db = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
    try:
        conn = sqlite3.connect(db)
        counts = {}
        for t in ("incident_knowledge", "wiki_articles", "session_transcripts", "chaos_experiments"):
            try:
                c = conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE embedding IS NOT NULL AND embedding != ''"
                ).fetchone()[0]
                counts[t] = c
            except sqlite3.OperationalError:
                counts[t] = 0
        conn.close()
        total_prod = sum(counts.values())
    except Exception:
        counts, total_prod = {}, 0

    if args.md:
        lines = [
            "# Vector DB Benchmark — 2026-04-17",
            "",
            "Generated by `scripts/bench-vector-search.py`.",
            "Dim = 768 (nomic-embed-text), 100 queries per config.",
            "",
            f"## Production scale (current)",
            "",
            f"Total embedded vectors: **{total_prod}**",
        ]
        for t, c in counts.items():
            lines.append(f"- {t}: {c}")
        lines.append("")
        lines.append("## Results")
        lines.append("")
        lines.append("| N | Engine | p50 ms | p95 ms | p99 ms | mean ms |")
        lines.append("|---|---|---|---|---|---|")
        for n in sizes:
            for name in [c[0] for c in configs]:
                r = results[n].get(name, {})
                if "error" in r:
                    lines.append(f"| {n:,} | {name} | ERROR: {r['error'][:30]} | | | |")
                elif "note" in r:
                    lines.append(f"| {n:,} | {name} | — | — | — | {r['note']} |")
                else:
                    lines.append(
                        f"| {n:,} | {name} | {r['p50_ms']} | {r['p95_ms']} | {r['p99_ms']} | {r['mean_ms']} |"
                    )
        lines.append("")
        # Trigger recommendation
        lines.append("## Migration Trigger")
        lines.append("")
        sqlite_p95_at_10k = results.get(10000, {}).get("sqlite_python", {}).get("p95_ms", 0)
        lines.append(
            f"SQLite pure-Python p95 at 10k vectors: **{sqlite_p95_at_10k} ms**. "
            f"Current production scale is **{total_prod}** vectors."
        )
        lines.append("")
        lines.append(
            "**Trigger:** migrate to FAISS HNSW when any ONE of:"
        )
        lines.append("1. Total embedded vectors > 25,000, OR")
        lines.append("2. p95 retrieval latency > 200 ms in production Grafana panel, OR")
        lines.append("3. Ollama embed throughput saturates during batch backfill")
        lines.append("")
        lines.append("**Current decision:** stay on SQLite pure-Python. FAISS sync cron runs ready-to-cut-over.")
        print("\n".join(lines))
    else:
        print(json.dumps({"production_counts": counts, "results": results}, indent=2))


if __name__ == "__main__":
    main()
