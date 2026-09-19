#!/usr/bin/env python3
"""Auto-regenerate docs/rag-architecture-current.md from live sources.

Introspects:
  - scripts/kb-semantic-search.py — RRF weight defaults, thresholds, env vars
  - gateway.db — row counts per embedded table
  - /var/lib/node_exporter/textfile_collector/kb_rag.prom — last p50/p95 latency
  - /tmp/kb_rag_eval.prom OR db ragas_evaluation — last hard-eval hit@5

Usage:
  python3 scripts/refresh-rag-architecture.py > docs/rag-architecture-current.md

Intended cron: 25 4 * * * (daily, after index-memories at 15, before metrics at 30)
"""
import os
REDACTED_a7b84d63
import sqlite3
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KB_PATH = os.path.join(REPO, "scripts/kb-semantic-search.py")
DB_PATH = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
METRICS_PATHS = [
    "/var/lib/node_exporter/textfile_collector/kb_rag.prom",
    "/tmp/kb_rag.prom",
]
EVAL_METRICS_PATHS = [
    "/var/lib/node_exporter/textfile_collector/kb_rag_eval.prom",
    "/tmp/kb_rag_eval.prom",
]


def _read_first(paths):
    for p in paths:
        if os.path.exists(p):
            try:
                return open(p).read()
            except Exception:
                continue
    return ""


def extract_defaults():
    """Collect RAG defaults from two sources.

    1. rag_config.py — the centralized module (truth for OLLAMA_URL,
       RERANK_API_URL, migration thresholds, Haiku model, EMBED_TABLES).
    2. kb-semantic-search.py — regex-scraped for the env-overridable
       values still defined inline (RERANK_MODEL, REWRITE_MODEL,
       SYNTH_MODEL, SYNTH_THRESHOLD, EMBED_MODEL, RRF weights).
    """
    defaults = {}

    # 1) rag_config imports — simpler and more reliable than regex.
    sys.path.insert(0, os.path.join(REPO, "scripts/lib"))
    try:
        import rag_config
        defaults["OLLAMA_URL"] = rag_config.OLLAMA_URL
        defaults["RERANK_API_URL"] = rag_config.RERANK_API_URL
        defaults["SYNTH_HAIKU_MODEL"] = rag_config.SYNTH_HAIKU_MODEL
    except ImportError:
        pass

    # 2) Inline env-var regex for values still defined directly in kb-semantic-search.
    if not os.path.exists(KB_PATH):
        return defaults
    src = open(KB_PATH).read()
    patterns = {
        "RERANK_MODEL": r'RERANK_MODEL = os\.environ\.get\("RERANK_MODEL",\s*"([^"]+)"\)',
        "REWRITE_MODEL": r'REWRITE_MODEL = os\.environ\.get\("REWRITE_MODEL",\s*"([^"]+)"\)',
        "SYNTH_MODEL": r'SYNTH_MODEL = os\.environ\.get\("SYNTH_MODEL",\s*"([^"]+)"\)',
        "SYNTH_THRESHOLD": r'SYNTH_THRESHOLD = float\(os\.environ\.get\("SYNTH_THRESHOLD",\s*"([^"]+)"\)\)',
        "EMBED_MODEL": r'EMBED_MODEL = os\.environ\.get\("EMBED_MODEL",\s*"([^"]+)"\)',
        "W_SEMANTIC": r'sem_weight = float\(os\.environ\.get\("RRF_W_SEMANTIC",\s*"([^"]+)"\)\)',
        "W_KEYWORD": r'kw_weight = float\(os\.environ\.get\("RRF_W_KEYWORD",\s*"([^"]+)"\)\)',
        "W_WIKI": r'wiki_weight = float\(os\.environ\.get\("RRF_W_WIKI",\s*"([^"]+)"\)\)',
        "W_TRANSCRIPT": r'tr_weight = float\(os\.environ\.get\("RRF_W_TRANSCRIPT",\s*"([^"]+)"\)\)',
        "W_CHAOS": r'chaos_weight = float\(os\.environ\.get\("RRF_W_CHAOS",\s*"([^"]+)"\)\)',
    }
    for k, pat in patterns.items():
        m = re.search(pat, src)
        if m:
            defaults[k] = m.group(1)
    return defaults


def row_counts():
    counts = {}
    if not os.path.exists(DB_PATH):
        return counts
    conn = sqlite3.connect(DB_PATH)
    for tbl in ("incident_knowledge", "wiki_articles", "session_transcripts", "chaos_experiments", "graph_entities", "graph_relationships"):
        try:
            c = conn.execute(
                f"SELECT COUNT(*) FROM {tbl} WHERE embedding IS NOT NULL AND embedding != ''"
            ).fetchone()[0]
            counts[tbl] = c
        except sqlite3.OperationalError:
            try:
                c = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                counts[tbl] = c
            except sqlite3.OperationalError:
                counts[tbl] = None
    conn.close()
    return counts


def latest_latency():
    text = _read_first(METRICS_PATHS)
    out = {}
    for name in ("kb_retrieval_latency_seconds", "kb_retrieval_latency_mean_seconds", "kb_rerank_service_up"):
        m = re.search(rf'{name}\{{quantile="0\.5"}}\s+([\d.]+)', text)
        if m:
            out["p50"] = float(m.group(1))
        m = re.search(rf'{name}\{{quantile="0\.95"}}\s+([\d.]+)', text)
        if m:
            out["p95"] = float(m.group(1))
        m = re.search(rf"^{re.escape(name)}\s+([\d.]+)\b", text, re.M)
        if m:
            out[name] = float(m.group(1))
    return out


def latest_eval():
    """Read hit@5 etc from eval metrics or ragas_evaluation table."""
    text = _read_first(EVAL_METRICS_PATHS)
    out = {}
    for field in ("kb_hard_eval_hit_rate", "kb_hard_eval_coverage_rate", "kb_hard_eval_kg_coverage", "kb_hard_eval_latency_p95_seconds"):
        m = re.search(rf"^{re.escape(field)}\s+([\d.]+)\b", text, re.M)
        if m:
            out[field] = float(m.group(1))
    # Fallback: RAGAS golden set — filter per-column to exclude -1 sentinels
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(
                "SELECT "
                " AVG(CASE WHEN faithfulness >= 0 THEN faithfulness END), "
                " AVG(CASE WHEN context_precision >= 0 THEN context_precision END), "
                " AVG(CASE WHEN context_recall >= 0 THEN context_recall END), "
                " AVG(CASE WHEN answer_relevance >= 0 THEN answer_relevance END), "
                " COUNT(*) "
                "FROM ragas_evaluation WHERE faithfulness > 0"
            ).fetchone()
            conn.close()
            if row and row[4]:
                out["ragas_faith"] = row[0]
                out["ragas_prec"] = row[1]
                out["ragas_recall"] = row[2]
                out["ragas_ansrel"] = row[3]
                out["ragas_n"] = row[4]
        except sqlite3.OperationalError:
            pass
    return out


def render(defaults, counts, latency, evalm):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    total = sum(c for c in counts.values() if isinstance(c, int) and c is not None)
    graph_total = (counts.get("graph_entities") or 0) + (counts.get("graph_relationships") or 0)

    def fmt(v, d=3):
        return f"{v:.{d}f}" if isinstance(v, (int, float)) else "n/a"

    lines = [
        "# RAG Pipeline — Current Architecture",
        "",
        f"Auto-generated by `scripts/refresh-rag-architecture.py` on {now}.",
        "Row counts and weights are introspected from the live system; prose is templated.",
        "",
        "## Headline numbers (live)",
        "",
        f"- **Hard retrieval judge hit@5**: {fmt(evalm.get('kb_hard_eval_hit_rate'))} (weekly cron) ",
        f"- **Hard KG traversal judge coverage@5**: {fmt(evalm.get('kb_hard_eval_kg_coverage'))}",
        f"- **RAGAS golden-set** (n={evalm.get('ragas_n', 'n/a')}): faithfulness {fmt(evalm.get('ragas_faith'), 2)}, precision {fmt(evalm.get('ragas_prec'), 2)}, recall {fmt(evalm.get('ragas_recall'), 2)}, answer_relevance {fmt(evalm.get('ragas_ansrel'), 2)}",
        f"- **End-to-end latency**: p50 {fmt(latency.get('p50'), 2)}s, p95 {fmt(latency.get('p95'), 2)}s (5-min rolling probe)",
        f"- **Total embedded vectors**: {total - (counts.get('graph_entities') or 0) - (counts.get('graph_relationships') or 0)} across embedded tables",
    ]
    lines.append("")
    lines.append("### Corpus by table — exact row counts")
    lines.append("")
    # Short anchor sentence with every number inline so exact-number retrieval hits
    c_ik = counts.get("incident_knowledge") or 0
    c_wiki = counts.get("wiki_articles") or 0
    c_trans = counts.get("session_transcripts") or 0
    c_chaos = counts.get("chaos_experiments") or 0
    c_ge = counts.get("graph_entities") or 0
    c_gr = counts.get("graph_relationships") or 0
    lines.append(
        f"**Embedded tables and row counts:** incident_knowledge ({c_ik}), wiki_articles ({c_wiki}), "
        f"session_transcripts ({c_trans}), chaos_experiments ({c_chaos}). "
        f"Graph: graph_entities ({c_ge}) and graph_relationships ({c_gr})."
    )
    lines.append("")
    lines.append("| Table | Embedded rows |")
    lines.append("|---|---|")
    for tbl in ("incident_knowledge", "wiki_articles", "session_transcripts", "chaos_experiments"):
        c = counts.get(tbl)
        lines.append(f"| `{tbl}` | {c if c is not None else 'n/a'} |")
    lines.append(f"| Graph entities / relationships | {counts.get('graph_entities', 'n/a')} / {counts.get('graph_relationships', 'n/a')} |")

    lines += [
        "",
        "## Pipeline stages (in order)",
        "",
        f"1. **Query embed** — `{defaults.get('EMBED_MODEL', 'nomic-embed-text')}` with `search_query:` prefix, `num_ctx=2048`.",
        "2. **Early-exit probe** — skip rewrite if raw-query top similarity ≥ 0.70 against `incident_knowledge` + `wiki_articles`.",
        f"3. **RAG Fusion rewrite** — `{defaults.get('REWRITE_MODEL', 'llama3.2:1b')}` temp=0.0, 3 perspective variants.",
        "4. **Batch embed variants** — single Ollama call, all prefixed `search_query:`.",
        "5. **5-signal retrieval** across 4 SQL sweeps + chaos.",
        f"6. **RRF fusion** — weights below.",
        f"7. **Cross-encoder rerank** — top-30 × 4 variants via `BAAI/bge-reranker-v2-m3` at `{defaults.get('RERANK_API_URL', 'http://nl-gpu01:11436')}` (fallback: Ollama yes/no via `{defaults.get('RERANK_MODEL', 'qwen2.5:7b')}`), max-per-doc, sqrt-blend.",
        f"8. **Multi-chunk synthesis** — triggers when cross-encoder max < {defaults.get('SYNTH_THRESHOLD', '0.6')}; 2-prompt ensemble via `{defaults.get('SYNTH_MODEL', 'qwen2.5:7b')}` num_ctx=8192.",
        "9. **LongContextReorder** — highest at positions [0, -1], lowest mid.",
        "10. **Output** — pipe-separated rows with `RETRIEVAL_QUALITY:` header.",
        "",
        "## RRF signal weights (live)",
        "",
        "| Signal | Default weight | Env override |",
        "|---|---|---|",
        f"| semantic (incident_knowledge) | {defaults.get('W_SEMANTIC', '1.0')} (×1.5 when sem_quality > 0.8) | `RRF_W_SEMANTIC` |",
        f"| keyword | {defaults.get('W_KEYWORD', '1.0')} | `RRF_W_KEYWORD` |",
        f"| wiki_articles | {defaults.get('W_WIKI', '0.9')} | `RRF_W_WIKI` |",
        f"| session_transcripts | {defaults.get('W_TRANSCRIPT', '0.4')} | `RRF_W_TRANSCRIPT` |",
        f"| chaos_experiments | {defaults.get('W_CHAOS', '0.35')} | `RRF_W_CHAOS` |",
        "",
        "Rank adjustments layered on top: `memory/`, `project-docs/`, `docs/` paths → rank /= 2 (boost). Generic sections like 'Related Memory Entries', 'Lessons Learned' → rank *= 2 (penalize). Small feedback files (<600 char preview, sim > 0.55, path `memory/feedback_*`) → rank /= 1.5.",
        "",
        "## KG traversal (separate path)",
        "",
        "- `plan_traversal()` — qwen2.5:7b, format=json, 3-shot examples, default hops=2 on multi-hop cues",
        "- `execute_plan()` — SQLite `WITH RECURSIVE` against `graph_entities` + `graph_relationships`",
        "- Fallback 1: `query_graph()` hostname join",
        "- Fallback 2: embedding cosine across all graph entities",
        "",
        "## Observability (live)",
        "",
        f"- Rerank service up: **{'UP' if latency.get('kb_rerank_service_up', 1) == 1 else 'DOWN'}**",
        "- `*/5 kb-latency-probe.py` — emits RAG metrics to `/var/lib/node_exporter/textfile_collector/kb_rag.prom`",
        "- `0 5 * * 1 weekly-eval-cron.sh` — weekly hard eval with `kb_hard_eval_*` metrics",
        "- `grafana/rag-observability.json` — 10-panel dashboard",
        "- `prometheus/alert-rules/rag-health.yml` — 6 alert rules",
        "",
        "## Dead-man switches (currently armed)",
        "",
        "- Daily `dmz-cleanup` cron at 05:45 UTC on both DMZ hosts (added 2026-04-17 after disk-full cascade)",
        "- `sync_certs_to_edge.yml` final banner play (ends silent-skip observability gap)",
        "- `*/15 faiss-index-sync.py` — FAISS warm index",
        "- `*/5 kb-latency-probe.py` — rerank service health gauge",
        "- `0 10 * * * chaos-calendar.sh` — daily chaos exercise selector (CMM L3)",
        "",
        "## Grafana dashboards",
        "",
        "10 live dashboards (sidecar-provisioned). RAG-specific: `rag-observability.json` (10 panels). Others: `chatops-platform.json`, `chatops-subsystem.json`, `chatsecops-subsystem.json`, `chatdevops-subsystem.json`, `cubeos-project.json`, `meshsat-project.json`, `infra-overview.json`, `infra-project.json`, `chaos-engineering.json`, `otel-traces.json`.",
        "",
        "## LongContextReorder",
        "",
        "Post-retrieval step: highest-scored items occupy positions `[0]` and `[-1]`, lowest in the middle. Mitigates 'lost in the middle' (Liu et al., 2023). Implemented in `long_context_reorder()`, env-gated by `LCR_ENABLED=1`. Applied only when `len(items) ≥ 3`.",
        "",
        "## Related",
        "",
        "- Cross-encoder service: memory/`rerank_service_crossencoder`",
        "- Synthesis: memory/`rag_synthesis_q2`",
        "- Asymmetric embeddings: `docs/rag-embedding-prefixes.md`",
        "- Crontab: `docs/crontab-reference.md` (auto-refreshed)",
        "- Host blast radius: `docs/host-blast-radius.md`",
        "- Metrics: `docs/rag-metrics-reference.md` (auto-refreshed)",
        "- Vector DB benchmark: `docs/vector-db-benchmark.md`",
        "",
        f"Last regenerated: {now}",
    ]
    return "\n".join(lines) + "\n"


def main():
    defaults = extract_defaults()
    counts = row_counts()
    latency = latest_latency()
    evalm = latest_eval()
    sys.stdout.write(render(defaults, counts, latency, evalm))


if __name__ == "__main__":
    main()
