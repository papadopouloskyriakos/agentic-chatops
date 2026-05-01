#!/usr/bin/env python3
"""Probe RAG retrieval latency. Emit textfile metric for node-exporter.

Cron: */5 * * * * probes 5 representative queries, emits kb_retrieval_latency_seconds
{quantile=0.5|0.95|0.99} to a prom textfile.

Also emits kb_embedded_rows{table} so the G6 migration trigger is observable.

Output: /var/lib/node_exporter/textfile_collector/kb_rag.prom (or fallback /tmp)
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))
from rag_config import (
    EMBED_TABLES, RERANK_API_URL,
    MIGRATION_SCALE_THRESHOLD, MIGRATION_LATENCY_THRESHOLD,
    PROBE_QUERIES, PROBE_QUERIES_REAL, PROBE_QUERIES_NOVEL,
)

KB = os.path.join(SCRIPT_DIR, "kb-semantic-search.py")
DB = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
RERANK_API = RERANK_API_URL  # back-compat alias

# Prefer textfile collector paths (node-exporter), fallback to /tmp
CANDIDATES = [
    "/var/lib/node_exporter/textfile_collector/kb_rag.prom",
    "/var/lib/prometheus/node-exporter/kb_rag.prom",
    "/tmp/kb_rag.prom",
]


def pick_output_path():
    for p in CANDIDATES:
        d = os.path.dirname(p)
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return p
    return CANDIDATES[-1]


PROBES = list(PROBE_QUERIES)


def pct(xs, q):
    s = sorted(xs)
    return s[min(int(len(s) * q), len(s) - 1)]


def probe_once(query):
    t0 = time.time()
    env = os.environ.copy()
    # Keep production defaults
    env.setdefault("RERANK_ENABLED", "1")
    env.setdefault("RAG_FUSION", "1")
    try:
        subprocess.run(
            ["python3", KB, "search", query, "--limit", "5"],
            capture_output=True, text=True, timeout=30, env=env,
        )
    except subprocess.TimeoutExpired:
        return 30.0
    return time.time() - t0


def probe_rerank_service():
    """Ping rerank service health + measure single-pair score latency.

    Returns (up: int, latency_ms: int).
    """
    # Health
    try:
        req = urllib.request.Request(f"{RERANK_API}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.read(8).startswith(b"ok"):
                pass
            else:
                return 0, 0
    except Exception:
        return 0, 0
    # Actual rerank call — single pair, measure round-trip
    payload = json.dumps({
        "query": "health probe",
        "documents": ["test document for rerank latency probe"],
        "top_k": 1,
    }).encode()
    req = urllib.request.Request(
        f"{RERANK_API}/rerank",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _ = json.loads(resp.read())
        return 1, int((time.time() - t0) * 1000)
    except Exception:
        return 0, 0


def main():
    # IFRNLLEI01PRD-703: split real vs novel so alerts key off production-
    # representative cohort. Probe each cohort separately but keep backward-
    # compatible unlabeled series (kb_retrieval_latency_seconds{quantile=...})
    # as the union p95 — gives operators a single "RAG overall" view while
    # alerts can target {category="real"} specifically.
    lats_real = [probe_once(q) for q in PROBE_QUERIES_REAL]
    lats_novel = [probe_once(q) for q in PROBE_QUERIES_NOVEL]
    lats = lats_real + lats_novel  # union, preserved for back-compat

    p50, p95, p99 = pct(lats, 0.5), pct(lats, 0.95), pct(lats, 0.99)
    mean = sum(lats) / len(lats)
    p50_real, p95_real, p99_real = pct(lats_real, 0.5), pct(lats_real, 0.95), pct(lats_real, 0.99)
    mean_real = sum(lats_real) / len(lats_real) if lats_real else 0.0
    p50_novel, p95_novel, p99_novel = pct(lats_novel, 0.5), pct(lats_novel, 0.95), pct(lats_novel, 0.99)
    mean_novel = sum(lats_novel) / len(lats_novel) if lats_novel else 0.0

    rerank_up, rerank_latency_ms = probe_rerank_service()

    # Embed counts
    counts = {}
    try:
        conn = sqlite3.connect(DB)
        for t in EMBED_TABLES:
            try:
                c = conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE embedding IS NOT NULL AND embedding != ''"
                ).fetchone()[0]
                counts[t] = c
            except sqlite3.OperationalError:
                counts[t] = 0
        conn.close()
    except Exception:
        pass

    out = [
        "# HELP kb_retrieval_latency_seconds Latency of RAG retrieval end-to-end (union of real + novel cohorts, back-compat)",
        "# TYPE kb_retrieval_latency_seconds summary",
        # Unlabeled (back-compat) — operators may still key on these
        f'kb_retrieval_latency_seconds{{quantile="0.5"}} {p50:.3f}',
        f'kb_retrieval_latency_seconds{{quantile="0.95"}} {p95:.3f}',
        f'kb_retrieval_latency_seconds{{quantile="0.99"}} {p99:.3f}',
        f"kb_retrieval_latency_seconds_count {len(lats)}",
        f"kb_retrieval_latency_seconds_sum {mean * len(lats):.3f}",
        # IFRNLLEI01PRD-703: category-labeled series. Alerts should key off
        # category="real"; category="novel" is a corpus-coverage quality
        # signal, not a production-latency signal.
        f'kb_retrieval_latency_seconds{{category="real",quantile="0.5"}} {p50_real:.3f}',
        f'kb_retrieval_latency_seconds{{category="real",quantile="0.95"}} {p95_real:.3f}',
        f'kb_retrieval_latency_seconds{{category="real",quantile="0.99"}} {p99_real:.3f}',
        f'kb_retrieval_latency_seconds{{category="novel",quantile="0.5"}} {p50_novel:.3f}',
        f'kb_retrieval_latency_seconds{{category="novel",quantile="0.95"}} {p95_novel:.3f}',
        f'kb_retrieval_latency_seconds{{category="novel",quantile="0.99"}} {p99_novel:.3f}',
        "# HELP kb_retrieval_latency_mean_seconds Mean latency",
        "# TYPE kb_retrieval_latency_mean_seconds gauge",
        f"kb_retrieval_latency_mean_seconds {mean:.3f}",
        f'kb_retrieval_latency_mean_seconds{{category="real"}} {mean_real:.3f}',
        f'kb_retrieval_latency_mean_seconds{{category="novel"}} {mean_novel:.3f}',
        "# HELP kb_embedded_rows Rows with non-null embeddings per table",
        "# TYPE kb_embedded_rows gauge",
    ]
    for t, c in counts.items():
        out.append(f'kb_embedded_rows{{table="{t}"}} {c}')
    total = sum(counts.values())
    out.append(f"kb_embedded_rows_total {total}")
    # Distance to G6 migration trigger. Thresholds centralized in rag_config.
    out.append("# HELP kb_migration_trigger_distance Ratio to migration trigger. >=1.0 = should migrate")
    out.append("# TYPE kb_migration_trigger_distance gauge")
    trigger_by_scale = total / float(MIGRATION_SCALE_THRESHOLD)
    trigger_by_latency = p95 / MIGRATION_LATENCY_THRESHOLD
    trigger_score = max(trigger_by_scale, trigger_by_latency)
    out.append(f'kb_migration_trigger_distance {trigger_score:.3f}')
    out.append(f'kb_migration_trigger_scale {trigger_by_scale:.3f}')
    out.append(f'kb_migration_trigger_latency {trigger_by_latency:.3f}')
    # P1: cross-encoder rerank service health + latency
    out.append("# HELP kb_rerank_service_up 1=up, 0=down (bge-reranker-v2-m3 on gpu01:11436)")
    out.append("# TYPE kb_rerank_service_up gauge")
    out.append(f"kb_rerank_service_up {rerank_up}")
    out.append("# HELP kb_rerank_probe_latency_ms Round-trip single-pair rerank call")
    out.append("# TYPE kb_rerank_probe_latency_ms gauge")
    out.append(f"kb_rerank_probe_latency_ms {rerank_latency_ms}")

    path = pick_output_path()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    print(f"wrote {len(out)} lines to {path}")
    print(f"p50={p50:.2f}s p95={p95:.2f}s p99={p99:.2f}s embedded={total}/{MIGRATION_SCALE_THRESHOLD} trigger_score={trigger_score:.3f}")
    print(f"  real-queries  p50={p50_real:.2f}s p95={p95_real:.2f}s")
    print(f"  novel-queries p50={p50_novel:.2f}s p95={p95_novel:.2f}s  (informational — NOT alerted)")


if __name__ == "__main__":
    main()
