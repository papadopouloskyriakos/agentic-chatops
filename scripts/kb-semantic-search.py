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
import urllib.error
import math
import datetime
REDACTED_a7b84d63
import functools
import concurrent.futures

# IFRNLLEI01PRD-631: circuit breaker for external calls
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from circuit_breaker import CircuitBreaker  # noqa: E402

# Rerank service breaker: trip after 3 consecutive failures (~45s of timeouts),
# probe every 90s while open. Fallback is None → caller drops through to Ollama.
_RERANK_CB = CircuitBreaker(
    "rag_rerank_crossencoder",
    failure_threshold=3,
    cooldown_seconds=90,
)

# Ollama embeddings breaker — critical path (entire RAG stops without it).
# Higher threshold + longer cooldown because Ollama spinning up a model costs
# real time; one slow cold-start shouldn't trip the breaker.
_EMBED_CB = CircuitBreaker(
    "rag_embed_ollama",
    failure_threshold=5,
    cooldown_seconds=120,
)

# Anthropic Haiku synth breaker — external API, 529/529 overload events
# happen. Fallback is empty string → caller degrades to no-synth response.
_SYNTH_HAIKU_CB = CircuitBreaker(
    "rag_synth_haiku",
    failure_threshold=3,
    cooldown_seconds=180,
)

# Local Ollama synth breaker (qwen2.5:7b, primary synth path since 2026-04-19).
# Fallback behavior depends on whether Haiku is available as escape hatch.
_SYNTH_OLLAMA_CB = CircuitBreaker(
    "rag_synth_ollama",
    failure_threshold=4,
    cooldown_seconds=120,
)

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
# Auto-detect read-only mode: if the parent dir isn't writable by us, use
# SQLite immutable URI. Lets OpenClaw container (uid 1000) open the root-owned
# read-replica DB at /home/node/.claude-data/gateway.db without sqlite trying
# to write the journal file.
_DB_PARENT = os.path.dirname(DB_PATH) or "."
DB_READ_ONLY = os.environ.get("GATEWAY_DB_RO", "").lower() in ("1", "true") or (
    os.path.exists(DB_PATH) and not os.access(_DB_PARENT, os.W_OK)
)


def _db_connect():
    """Return a sqlite3 Connection, respecting DB_READ_ONLY."""
    if DB_READ_ONLY:
        return sqlite3.connect(f"file:{DB_PATH}?mode=ro&immutable=1", uri=True)
    return sqlite3.connect(DB_PATH)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from rag_config import (
    OLLAMA_URL, RERANK_API_URL,
    EMBED_TABLES,
    NUM_CTX_TINY, NUM_CTX_SMALL, NUM_CTX_MED,
    SYNTH_HAIKU_MODEL, SYNTH_HAIKU_COST_PER_M_INPUT, SYNTH_HAIKU_COST_PER_M_OUTPUT,
)

EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
RERANK_MODEL = os.environ.get("RERANK_MODEL", "qwen2.5:7b")
RERANK_BACKEND = os.environ.get("RERANK_BACKEND", "crossencoder")  # crossencoder | ollama
RERANK_ENABLED = os.environ.get("RERANK_ENABLED", "1") == "1"
SYNTH_ENABLED = os.environ.get("SYNTH_ENABLED", "1") == "1"
SYNTH_THRESHOLD = float(os.environ.get("SYNTH_THRESHOLD", "0.4"))
SYNTH_MODEL = os.environ.get("SYNTH_MODEL", "qwen2.5:7b")
SYNTH_BACKEND = os.environ.get("SYNTH_BACKEND", "qwen")  # qwen | haiku | auto (default: local-first; set to 'haiku' to opt in to Anthropic API synth)
RAG_FUSION = os.environ.get("RAG_FUSION", "1") == "1"
LCR_ENABLED = os.environ.get("LCR_ENABLED", "1") == "1"
# IFRNLLEI01PRD-647: multiplicative discount applied to incident_knowledge rows
# whose project='chatops-cli' (knowledge extracted from interactive CLI sessions,
# not real infra incidents). Keeps the signal available but lets real incidents
# dominate retrieval when both match. 1.0 disables the weighting.
CLI_INCIDENT_WEIGHT = float(os.environ.get("CLI_INCIDENT_WEIGHT", "0.75"))
# IFRNLLEI01PRD-703: overall search budget in seconds. cmd_search checks
# elapsed time before heavy fallbacks (HyDE generate_hypothetical_doc +
# re-embed) and skips them if the budget is already exceeded. This stops
# novel/unknown queries from pushing the kb-latency-probe p95 to the 30s
# probe cap. Default 10s = keeps p95 under the 12s alert threshold with a
# 2s margin. Set SEARCH_BUDGET_S=0 to disable.
SEARCH_BUDGET_S = float(os.environ.get("SEARCH_BUDGET_S", "10"))
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


def _embed_raw(texts):
    """Batch embed via Ollama. `texts` may be str or list[str]. Returns list[vec] or [vec] for single.

    Circuit-breaker protected (IFRNLLEI01PRD-631): 5 consecutive failures
    short-circuit to None-vectors until the 120s cooldown + one success.
    """
    is_single = isinstance(texts, str)
    payload_texts = [texts] if is_single else list(texts)
    if not _EMBED_CB.allow():
        return None if is_single else [None] * len(payload_texts)
    payload = json.dumps({"model": EMBED_MODEL, "input": payload_texts}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            _record_local_usage(EMBED_MODEL, data.get("prompt_eval_count", 0))
            vecs = data["embeddings"]
            _EMBED_CB.record_success()
            return vecs[0] if is_single else vecs
    except Exception as e:
        print(f"ERROR: Embedding failed: {e}", file=sys.stderr)
        _EMBED_CB.record_failure(e)
        return None if is_single else [None] * len(payload_texts)


@functools.lru_cache(maxsize=128)
def embed_query(text):
    """G7: Asymmetric query embedding with nomic-embed-text search_query: prefix."""
    return _embed_raw(f"search_query: {text}")


def embed_document(text):
    """G7: Asymmetric document embedding with nomic-embed-text search_document: prefix."""
    return _embed_raw(f"search_document: {text}")


def batch_embed_documents(texts):
    """G2/G7: Batch embed documents. 6x faster than sequential (benchmarked 2026-04-17)."""
    if not texts:
        return []
    prefixed = [f"search_document: {t}" for t in texts]
    return _embed_raw(prefixed) or [None] * len(texts)


def batch_embed_queries(texts):
    """G2: Batch embed query variants for RAG Fusion."""
    if not texts:
        return []
    prefixed = [f"search_query: {t}" for t in texts]
    return _embed_raw(prefixed) or [None] * len(texts)


def get_embedding(text):
    """Legacy alias. Defaults to document embedding for backward compatibility.

    DEPRECATED: Use embed_query() for search queries, embed_document() for docs.
    """
    return embed_document(text)


_TEMPORAL_RE_HOURS = re.compile(r"last\s+(\d+)\s+hours?", re.IGNORECASE)
_TEMPORAL_RE_DAYS = re.compile(r"last\s+(\d+)\s+days?|past\s+(\d+)\s+days?", re.IGNORECASE)
_TEMPORAL_RE_WINDOW_ENDING = re.compile(
    r"(?:in\s+the\s+)?(\d+)\s+hours?\s+ending\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE,
)
_TEMPORAL_RE_ON_DATE = re.compile(r"\bon\s+(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def extract_temporal_window(query):
    """Return (since_epoch, until_epoch) if the query has a time window, else None.

    IFRNLLEI01PRD-609 H06/H50: queries like "last 48 hours", "72 hours
    ending 2026-04-17", or "on 2026-04-14" need source_mtime-based
    filtering on wiki_articles. Everything else returns None (no filter).
    """
    now = datetime.datetime.utcnow()

    m = _TEMPORAL_RE_WINDOW_ENDING.search(query)
    if m:
        hours = int(m.group(1))
        end = datetime.datetime.strptime(m.group(2), "%Y-%m-%d") + datetime.timedelta(days=1)
        start = end - datetime.timedelta(hours=hours)
        return (start.timestamp(), end.timestamp())

    m = _TEMPORAL_RE_HOURS.search(query)
    if m:
        hours = int(m.group(1))
        start = now - datetime.timedelta(hours=hours)
        return (start.timestamp(), now.timestamp())

    m = _TEMPORAL_RE_DAYS.search(query)
    if m:
        days = int(m.group(1) or m.group(2))
        start = now - datetime.timedelta(days=days)
        return (start.timestamp(), now.timestamp())

    m = _TEMPORAL_RE_ON_DATE.search(query)
    if m:
        day = datetime.datetime.strptime(m.group(1), "%Y-%m-%d")
        return (day.timestamp(), (day + datetime.timedelta(days=1)).timestamp())

    return None


_MTIME_SORT_NOUNS = re.compile(
    r"\b(memory|memories|file|files|doc|docs|document|note|notes|entry|entries)\b",
    re.IGNORECASE,
)
_MTIME_SORT_VERBS = re.compile(
    r"\b(list|name|show|enumerate|what|which)\b.*\b(any|three|3|five|5|few|some|recent|newest|latest|most recent)\b",
    re.IGNORECASE,
)
_MTIME_SORT_CREATED = re.compile(
    r"\b(created|modified|updated|written|added)\b.*\b(in|during|within|after|since)\b.*\b(last|past|recent|today|yesterday)\b",
    re.IGNORECASE,
)


def detect_mtime_sort_intent(query):
    """True iff the query asks for recent files BY TIME, not by topic.

    IFRNLLEI01PRD-616 H50: "Name any three memory files created in the last
    48 hours and their types" is an mtime-sort question; semantic search
    can't answer it because the query text doesn't describe the files'
    contents. Signals: a temporal window exists AND either a listing-verb
    pattern ("name any three memory files") or a created-in-window pattern
    ("files modified in the last 48h") matches.
    """
    if extract_temporal_window(query) is None:
        return False
    if not _MTIME_SORT_NOUNS.search(query):
        return False
    if _MTIME_SORT_VERBS.search(query) or _MTIME_SORT_CREATED.search(query):
        return True
    return False


def list_recent_wiki(conn, since_epoch, until_epoch, limit=10, path_prefix=None):
    """Return [(path, title, section, source_mtime)] for wiki rows in window, newest first."""
    sql = (
        "SELECT path, title, section, source_mtime FROM wiki_articles "
        "WHERE source_mtime >= ? AND source_mtime < ?"
    )
    params = [since_epoch, until_epoch]
    if path_prefix:
        sql += " AND path LIKE ?"
        params.append(f"{path_prefix}%")
    sql += " ORDER BY source_mtime DESC LIMIT ?"
    params.append(limit)
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _path_to_type(path):
    """Infer a coarse 'type' label from the path prefix for list-recent output."""
    p = path.lower()
    if p.startswith("memory/"):
        if "feedback_" in p:
            return "memory:feedback"
        if "incident_" in p:
            return "memory:incident"
        if "session_summary" in p:
            return "memory:session"
        return "memory:project"
    if p.startswith("docs/"):
        return "docs"
    if p.startswith("project-docs/"):
        return "project-docs"
    if p.startswith(".claude/") or "/.claude/" in p:
        return "claude-rules"
    return "other"


def cmd_list_recent(hours=None, days=None, limit=10, path_prefix=None):
    """CLI: list wiki articles by source_mtime DESC within a window.

    Use case: answers questions like "what memory files changed in the last 48h"
    without needing semantic retrieval. Output: path | type | age-label.
    """
    now = datetime.datetime.utcnow()
    if hours is not None:
        since = now - datetime.timedelta(hours=hours)
    elif days is not None:
        since = now - datetime.timedelta(days=days)
    else:
        since = now - datetime.timedelta(hours=48)
    until = now
    conn = _db_connect()
    conn.row_factory = sqlite3.Row
    rows = list_recent_wiki(conn, since.timestamp(), until.timestamp(),
                            limit=limit, path_prefix=path_prefix)
    print(f"list-recent window: [{since:%Y-%m-%d %H:%M}..{until:%Y-%m-%d %H:%M}] UTC, {len(rows)} rows")
    for r in rows:
        mtime = datetime.datetime.utcfromtimestamp(r["source_mtime"])
        age_h = (now - mtime).total_seconds() / 3600.0
        print(f"  {r['path']:60} | {_path_to_type(r['path']):20} | {age_h:5.1f}h ago")


def cosine_similarity(a, b):
    """Cosine similarity between two vectors (pure Python, no numpy)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


REWRITE_MODEL = os.environ.get("REWRITE_MODEL", "qwen2.5:7b")


def rewrite_query(query, num_rewrites=2):
    """Use Ollama to generate query reformulations for better retrieval.

    IFRNLLEI01PRD-611: moved from qwen3:4b to qwen2.5:7b. qwen3's thinking
    mode emits to a `thinking` field and required <think> tag stripping;
    qwen2.5 has no thinking mode.
    """
    prompt = (
        f"Rewrite this infrastructure alert query into {num_rewrites} alternative phrasings "
        f"that would help find similar past incidents. Return ONLY the rewrites, one per line.\n\n"
        f"Original: {query}\n\nRewrites:"
    )
    payload = json.dumps({
        "model": REWRITE_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 400, "num_ctx": NUM_CTX_SMALL}
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            _record_local_usage(
                REWRITE_MODEL,
                data.get("prompt_eval_count", 0),
                data.get("eval_count", 0),
            )
            text = data.get("response", "").strip()
            # Parse lines, filter empty and the original
            rewrites = [
                line.strip().lstrip("0VMID_REDACTED.-) ")
                for line in text.split("\n")
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
    # IFRNLLEI01PRD-611: qwen2.5:7b instead of qwen3:4b (no thinking mode).
    payload = json.dumps({
        "model": REWRITE_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.5, "num_predict": 500, "num_ctx": NUM_CTX_SMALL}
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
            _record_local_usage(
                REWRITE_MODEL,
                data.get("prompt_eval_count", 0),
                data.get("eval_count", 0),
            )
            text = data.get("response", "").strip()
            return text if len(text) > 20 else None
    except Exception as e:
        print(f"[hyde] Ollama unavailable: {e}", file=sys.stderr)
        return None


REWRITE_MODEL = os.environ.get("REWRITE_MODEL", "llama3.2:1b")


def rewrite_query_multi(query, num_variants=3):
    """G2 RAG Fusion: generate N perspective-diverse rephrasings.

    Latency optimizations:
    - Plain-text output (no JSON schema overhead, ~40% faster on small models)
    - llama3.2:1b by default (5x smaller than qwen2.5:7b; <1s warm)
    - Each line = one variant; parse by splitting
    """
    prompt = (
        "Rewrite this infrastructure query 3 different ways. Output ONE rewrite per line, "
        "no numbering, no commentary. Each rewrite should use DIFFERENT vocabulary from the original.\n"
        "Line 1: reword as a question\n"
        "Line 2: phrase as a past incident summary\n"
        "Line 3: dense technical keywords only\n\n"
        f"Original: {query}\n\nRewrites:"
    )
    body = {
        "model": REWRITE_MODEL,
        "prompt": prompt,
        "stream": False,
        # NUM_CTX_TINY keeps llama3.2:1b fully on GPU (default 64k causes 22% CPU spill).
        "options": {
            "temperature": 0.0,  # Deterministic variants; reduces eval variance
            "num_predict": 180,
            "num_ctx": NUM_CTX_TINY,
            "stop": ["Original:", "\n\nNote", "\n\n4.", "Line 4:"],
        },
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            _record_local_usage(REWRITE_MODEL, data.get("prompt_eval_count", 0), data.get("eval_count", 0))
            text = (data.get("response", "") or data.get("thinking", "")).strip()
            if "<think>" in text:
                text = text.split("</think>")[-1].strip()
            lines = [ln.strip().lstrip("0VMID_REDACTED.-) ").strip("'\"") for ln in text.split("\n") if ln.strip()]
            variants = [ln for ln in lines if ln and ln.lower() != query.lower()][:num_variants]
            return [query] + variants
    except Exception as e:
        print(f"[rewrite] failed: {e}", file=sys.stderr)
        return [query]


def _rerank_via_crossencoder(query, docs):
    """Call the dedicated bge-reranker-v2-m3 cross-encoder service on gpu01.

    Returns list of raw scores aligned with `docs`, or None on failure.

    Circuit-breaker protected (IFRNLLEI01PRD-631): 3 consecutive failures open
    the circuit; subsequent calls return None immediately (skip the 15s
    timeout) until the 90s cooldown elapses and a probe succeeds. Caller
    drops through to Ollama rerank on None.
    """
    if not _RERANK_CB.allow():
        return None  # circuit open — skip upstream call, fall through to Ollama
    try:
        payload = json.dumps({
            "query": query,
            "documents": docs,
            "top_k": len(docs),
        }).encode()
        req = urllib.request.Request(
            f"{RERANK_API_URL}/rerank",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            scores = [0.0] * len(docs)
            for r in data.get("ranked", []):
                idx = r["index"]
                if 0 <= idx < len(docs):
                    scores[idx] = float(r["score"])
            _RERANK_CB.record_success()
            return scores
    except Exception as e:
        print(f"[rerank] crossencoder failed: {e}", file=sys.stderr)
        _RERANK_CB.record_failure(e)
        return None


def rerank_candidates(query, candidates, top_k=5):
    """G1: Cross-encoder rerank top-N RRF candidates.

    Primary backend: HuggingFace bge-reranker-v2-m3 via dedicated service on gpu01:11436
    Fallback: Ollama qwen2.5:7b yes/no prompt (legacy).

    `candidates` is a list of (score, sim, row, source) tuples from fusion.
    Returns the same shape but re-sorted by rerank score.
    """
    if not RERANK_ENABLED or not candidates:
        return candidates[:top_k]

    def _rowget(row, key, default=""):
        """sqlite3.Row doesn't support .get(); chaos rows are plain dicts."""
        try:
            return row[key] if row[key] is not None else default
        except (IndexError, KeyError, TypeError):
            return default

    def _doc_text(row, source):
        if source == "wiki":
            preview = _rowget(row, "content_preview")
            base = f"{_rowget(row,'path')}: {_rowget(row,'title')}"
            if preview:
                return f"{base} — {preview[:600]}"
            return f"{base} (section: {_rowget(row,'section')})"
        if source == "chaos":
            return f"{_rowget(row,'chaos_type')}: {_rowget(row,'targets')} verdict={_rowget(row,'verdict')}"
        if source == "transcript":
            return (_rowget(row, "content") or "")[:500]
        return f"{_rowget(row,'alert_rule')} on {_rowget(row,'hostname')}: {_rowget(row,'resolution')[:500]}"

    # --- Preferred path: dedicated cross-encoder service ---
    if RERANK_BACKEND == "crossencoder":
        docs = [_doc_text(row, src) for _, _, row, src in candidates]

        # Q1: max-over-variants — rerank against all query variants, take max per doc.
        # Unlocks oblique queries (H04 "yelling about shun") where the canonical rephrasing
        # scores much higher than the colloquial original.
        rerank_queries = getattr(rerank_candidates, "_current_variants", None) or [query]
        variants_to_score = rerank_queries[:4]
        # L02 helper: parallelize the 4 per-variant HTTP calls to the rerank service.
        # Each HTTP call to gpu01:11436 hits the same CrossEncoder model (GPU-bound),
        # but the service can batch internally; ThreadPool just removes serial network
        # roundtrip cost. Net: ~2s → ~0.8s on 4-variant max-over-variants path.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(lambda rq: _rerank_via_crossencoder(rq, docs), variants_to_score))
        all_scores = [s for s in results if s is not None]
        if all_scores:
            # Per-doc max across variants
            scores = [max(s[i] for s in all_scores) for i in range(len(docs))]
            print(
                f"[rerank] crossencoder scored {len(candidates)} cands × "
                f"{len(all_scores)} variants (top={max(scores):.3f})",
                file=sys.stderr,
            )
            max_rrf = max((c[0] for c in candidates), default=1.0) or 1.0
            max_score = max(scores)
            # Expose max cross-encoder score for synthesis trigger (Q2)
            rerank_candidates._last_max_ce = max_score
            blended = []
            for i, (rrf, sim, row, source) in enumerate(candidates):
                rrf_norm = rrf / max_rrf
                ce = scores[i]
                if max_score > 0.3:
                    blended_score = 0.3 * rrf_norm + 0.7 * math.sqrt(ce)
                else:
                    blended_score = 0.7 * rrf_norm + 0.3 * ce
                blended.append((blended_score, sim, row, source))
            blended.sort(key=lambda x: x[0], reverse=True)
            return blended[:top_k]
        # fall through to Ollama backend on service failure
        print(f"[rerank] falling back to Ollama yes/no", file=sys.stderr)

    # --- Legacy path: Ollama yes/no via qwen2.5:7b ---
    def score_pair(pair):
        idx, (_rrf, _sim, row, source) = pair
        # Extract doc text per source type
        if source == "wiki":
            doc_text = f"{_rowget(row,'title')}: {_rowget(row,'section')}"
        elif source == "chaos":
            doc_text = f"{_rowget(row,'chaos_type')}: {_rowget(row,'targets')} verdict={_rowget(row,'verdict')}"
        elif source == "transcript":
            doc_text = (_rowget(row, "content") or "")[:300]
        else:
            doc_text = f"{_rowget(row,'alert_rule')} {_rowget(row,'hostname')}: {_rowget(row,'resolution','')[:300]}"

        prompt = (
            f"Rate document relevance for an infrastructure incident search.\n"
            f"Query: {query}\n"
            f"Document: {doc_text[:400]}\n\n"
            "Scoring:\n"
            "  3 = directly addresses the query (same host AND same incident type/root cause)\n"
            "  2 = strongly related (same host OR same incident type)\n"
            "  1 = weakly related (same subsystem, site, or adjacent topic)\n"
            "  0 = unrelated\n\n"
            "Answer with ONLY the digit 0, 1, 2, or 3."
        )
        body = {
            "model": RERANK_MODEL,
            "prompt": prompt,
            "stream": False,
            # NUM_CTX_SMALL is enough for a query+doc pair; default 64k wastes VRAM
            "options": {"temperature": 0.0, "num_predict": 2, "num_ctx": NUM_CTX_SMALL},
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                _record_local_usage(RERANK_MODEL, data.get("prompt_eval_count", 0), data.get("eval_count", 0))
                text = (data.get("response", "") or data.get("thinking", "")).strip()
                # Parse 0-3 scale; normalize to 0.0-1.0
                for ch in text:
                    if ch in "0123":
                        return idx, int(ch) / 3.0
                # Backwards compat: handle old yes/no outputs too
                low = text.lower()
                if low.startswith("yes"):
                    return idx, 1.0
                if low.startswith("no"):
                    return idx, 0.0
                return idx, 0.33  # uncertain -> mild-positive (preserves rank for indirect matches)
        except Exception as e:
            print(f"[rerank] model error idx={idx}: {e}", file=sys.stderr)
            return idx, 0.33

    n = len(candidates)
    pairs = list(enumerate(candidates))
    # Parallel scoring — 6 threads for Qwen3-Reranker-0.6B on RTX 3090 Ti
    rerank_scores = [0.5] * n
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for idx, score in ex.map(score_pair, pairs):
            rerank_scores[idx] = score

    # Blend: 50% rerank + 50% normalized RRF. Keeps strong fusion signal alive
    # while still letting the reranker correct obvious ordering mistakes.
    max_rrf = max((c[0] for c in candidates), default=1.0) or 1.0
    blended = []
    for i, (rrf, sim, row, source) in enumerate(candidates):
        blended_score = 0.5 * rerank_scores[i] + 0.5 * (rrf / max_rrf)
        blended.append((blended_score, sim, row, source))
    blended.sort(key=lambda x: x[0], reverse=True)
    return blended[:top_k]


def _synth_fresh_candidates(conn, query, limit=10):
    """Q2: Pull candidates for synthesis using RAW query (no fusion variants).

    Fusion variants from llama3.2:1b sometimes hallucinate (e.g., RRF → RFM), polluting
    the rerank pool. For synthesis we want the cleanest possible candidates, so we
    re-probe wiki_articles + incident_knowledge using the raw query embedding alone.

    Q01: for negation queries, seed the pool with feedback_* files from the
    negation-keyword-first path so the synth LLM sees authoritative policy docs.
    """
    q_vec = embed_query(query)
    if not q_vec:
        return []
    scored = []
    # Q01: seed feedback_* rows at the TOP of the pool for negation queries.
    # These authoritative policy files rarely beat verbose prose on cosine alone.
    if _is_negation_query(query):
        neg_rows = _negation_keyword_boost(conn, query, [query], raw_vec=q_vec, limit=8)
        for r in neg_rows:
            # Use a high pseudo-similarity so they're ranked high in the top-10 pool
            scored.append((0.75, r, "wiki"))
    # Wiki (most likely to contain architectural/meta answers)
    try:
        wiki_rows = conn.execute(
            "SELECT path, title, section, embedding, content_preview FROM wiki_articles "
            "WHERE embedding IS NOT NULL AND embedding != ''"
        ).fetchall()
        for r in wiki_rows:
            try:
                v = json.loads(r["embedding"])
                sim = cosine_similarity(q_vec, v)
                if sim > 0.4:
                    scored.append((sim, r, "wiki"))
            except (json.JSONDecodeError, TypeError):
                continue
    except sqlite3.OperationalError:
        pass
    # Incident knowledge (for operational how-to queries)
    try:
        ik_rows = conn.execute(
            "SELECT * FROM incident_knowledge WHERE embedding IS NOT NULL AND embedding != ''"
        ).fetchall()
        for r in ik_rows:
            try:
                v = json.loads(r["embedding"])
                sim = cosine_similarity(q_vec, v)
                if sim > 0.4:
                    scored.append((sim, r, "incident"))
            except (json.JSONDecodeError, TypeError):
                continue
    except sqlite3.OperationalError:
        pass
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:limit]


def _anthropic_api_key():
    """Resolve Anthropic API key from env or repo .env (cached via attribute)."""
    if hasattr(_anthropic_api_key, "_cache"):
        return _anthropic_api_key._cache
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_path):
            try:
                for line in open(env_path):
                    if line.startswith("ANTHROPIC_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            except Exception:
                pass
    _anthropic_api_key._cache = key
    return key


def _call_haiku_synth(prompt_text, max_tokens=500):
    """L02: Haiku synthesis — 3-4× faster p95 than Ollama-serial qwen2.5 ensemble.

    Returns the text response, or empty string on failure. Records cost in llm_usage.

    Failure injection (for tests):
      SYNTH_HAIKU_FORCE_FAIL=1        generic empty-return (short-circuits before API call)
      SYNTH_HAIKU_FORCE_FAIL=429      raise simulated HTTP 429 rate-limit
      SYNTH_HAIKU_FORCE_FAIL=auth     raise simulated HTTP 401 bad auth
      SYNTH_HAIKU_FORCE_FAIL=timeout  raise socket.timeout
      SYNTH_HAIKU_FORCE_FAIL=network  raise URLError (DNS / connection refused)
    All modes land in the except branch and return "", letting _call() fall back to qwen.
    """
    fail_mode = os.environ.get("SYNTH_HAIKU_FORCE_FAIL", "")
    if fail_mode == "1":
        print("[synth-haiku] forced failure via SYNTH_HAIKU_FORCE_FAIL=1", file=sys.stderr)
        return ""
    if fail_mode == "429":
        try:
            raise urllib.error.HTTPError(
                "https://api.anthropic.com/v1/messages", 429,
                "Too Many Requests", {}, None,
            )
        except Exception as e:
            print(f"[synth-haiku] forced 429: {e}", file=sys.stderr)
            return ""
    if fail_mode == "auth":
        try:
            raise urllib.error.HTTPError(
                "https://api.anthropic.com/v1/messages", 401,
                "Unauthorized", {}, None,
            )
        except Exception as e:
            print(f"[synth-haiku] forced auth failure: {e}", file=sys.stderr)
            return ""
    if fail_mode == "timeout":
        import socket
        try:
            raise socket.timeout("forced timeout")
        except Exception as e:
            print(f"[synth-haiku] forced timeout: {e}", file=sys.stderr)
            return ""
    if fail_mode == "network":
        try:
            raise urllib.error.URLError("forced connection refused")
        except Exception as e:
            print(f"[synth-haiku] forced network error: {e}", file=sys.stderr)
            return ""
    key = _anthropic_api_key()
    if not key:
        return ""
    # Circuit-breaker (IFRNLLEI01PRD-631): 3 Anthropic failures -> skip for 180s
    if not _SYNTH_HAIKU_CB.allow():
        return ""
    body = json.dumps({
        "model": SYNTH_HAIKU_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt_text}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            # Record cost in llm_usage. Per-M rates come from rag_config.
            try:
                usage = data.get("usage", {})
                in_tok = usage.get("input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
                cost = ((in_tok / 1_000_000.0) * SYNTH_HAIKU_COST_PER_M_INPUT
                        + (out_tok / 1_000_000.0) * SYNTH_HAIKU_COST_PER_M_OUTPUT)
                conn2 = sqlite3.connect(DB_PATH)
                conn2.execute(
                    "INSERT INTO llm_usage (tier, model, input_tokens, output_tokens, cost_usd, issue_id) "
                    "VALUES (2, ?, ?, ?, ?, 'synth-haiku')",
                    (SYNTH_HAIKU_MODEL, in_tok, out_tok, round(cost, 6)),
                )
                conn2.commit()
                conn2.close()
            except Exception:
                pass
            _SYNTH_HAIKU_CB.record_success()
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[synth-haiku] failed: {e}", file=sys.stderr)
        _SYNTH_HAIKU_CB.record_failure(e)
        return ""


def synthesize_answer(query, rerank_pool, top_n=10, conn=None):
    """Q2: When no single doc strongly matches, synthesize an answer from multiple chunks.

    Pulls FRESH candidates using the raw query (bypassing fusion pollution) when a
    connection is provided. Falls back to rerank_pool otherwise.
    """
    if not SYNTH_ENABLED:
        return None

    def _doc_text(row, source):
        # Wider truncation than the rerank path — synthesis needs full context to extract answers
        if source == "wiki":
            preview = row["content_preview"] if "content_preview" in row.keys() else ""
            return f"{row['path']}: {preview[:1100] if preview else row['section']}"
        if source == "chaos":
            return f"{row.get('chaos_type','')}: {row.get('targets','')} verdict={row.get('verdict','')}"
        if source == "transcript":
            return (row.get("content") or "")[:800]
        if source == "incident":
            return f"{row['alert_rule']} on {row['hostname']}: {(row['resolution'] or '')[:900]}"
        return f"{row.get('alert_rule','')} on {row.get('hostname','')}: {(row.get('resolution','') or '')[:800]}"

    # Prefer fresh candidates (raw query) to avoid fusion hallucination pollution
    chunks = []
    if conn is not None:
        fresh = _synth_fresh_candidates(conn, query, limit=top_n)
        for i, (_sim, row, source) in enumerate(fresh, 1):
            try:
                chunks.append(f"[{i}] {_doc_text(row, source)}")  # no further truncation
            except Exception:
                continue
    if not chunks and rerank_pool:
        for i, (_score, _sim, row, source) in enumerate(rerank_pool[:top_n], 1):
            try:
                chunks.append(f"[{i}] {_doc_text(row, source)}")
            except Exception:
                continue
    if not chunks:
        return None
    joined = "\n".join(chunks)

    # H17: 2-prompt ensemble — try both prompts in parallel, pick the best non-empty.
    # Prompt A: direct-answer extractor (original)
    # Prompt B: cause-and-fix/mechanism extractor (better for "how is X fixed?" queries)
    prompt_a = (
        "You are an infrastructure retrieval synthesizer. Given a user query and "
        "several retrieved chunks, extract a DIRECT ANSWER to the query.\n\n"
        "Rules:\n"
        "- If the chunks together contain the answer, give a concise 2-3 sentence answer\n"
        "- Cite chunk numbers in square brackets like [1] [3]\n"
        "- If the chunks don't contain a clear answer, reply: NO_ANSWER\n"
        "- Keep technical terms verbatim (hostnames, commands, numbers)\n\n"
        f"Query: {query}\n\n"
        f"Retrieved chunks:\n{joined}\n\n"
        "Direct answer:"
    )
    prompt_b = (
        "You identify facts across multiple infrastructure documents. For the given "
        "query, extract from the chunks: (1) what happened/what the thing is, "
        "(2) the cause or mechanism, (3) the fix or resolution. Stitch them into a "
        "short factual paragraph with [N] citations.\n\n"
        "If the chunks truly lack information, still list what IS in them — do NOT "
        "reply with only NO_ANSWER unless the chunks are empty or entirely off-topic.\n\n"
        f"Query: {query}\n\n"
        f"Retrieved chunks:\n{joined}\n\n"
        "Factual answer:"
    )

    # L02: pick backend. "auto" uses Haiku when the API key is available (faster + better),
    # else falls back to Ollama qwen2.5:7b. "haiku"/"qwen" explicit overrides.
    use_haiku = False
    if SYNTH_BACKEND == "haiku":
        use_haiku = True
    elif SYNTH_BACKEND == "auto" and _anthropic_api_key():
        use_haiku = True

    def _call_qwen(prompt_text):
        # Circuit-breaker (IFRNLLEI01PRD-631): 4 Ollama synth failures -> skip 120s
        if not _SYNTH_OLLAMA_CB.allow():
            return ""
        body = {
            "model": SYNTH_MODEL,
            "prompt": prompt_text,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 400, "num_ctx": NUM_CTX_MED},
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = json.loads(resp.read())
                _record_local_usage(SYNTH_MODEL, data.get("prompt_eval_count", 0), data.get("eval_count", 0))
                text = (data.get("response", "") or data.get("thinking", "")).strip()
                if "<think>" in text:
                    text = text.split("</think>")[-1].strip()
                _SYNTH_OLLAMA_CB.record_success()
                return text
        except Exception as e:
            print(f"[synth] qwen call failed: {e}", file=sys.stderr)
            _SYNTH_OLLAMA_CB.record_failure(e)
            return ""

    def _call(prompt_text):
        if use_haiku:
            out = _call_haiku_synth(prompt_text, max_tokens=500)
            if out:
                return out
            # Haiku failed (network / rate limit) — fallback to qwen once
            return _call_qwen(prompt_text)
        return _call_qwen(prompt_text)

    # L02: Haiku is smarter than qwen2.5:7b and rarely returns NO_ANSWER, so
    # single-prompt is typically enough. Running only prompt B (cause+fix extractor,
    # better general-purpose) halves synth latency. Fall back to prompt A only
    # when B fails the NO_ANSWER guard.
    if use_haiku:
        ans_b = _call(prompt_b)
        ans_a = ""
        if not ans_b or "NO_ANSWER" in ans_b.upper():
            ans_a = _call(prompt_a)
    else:
        # Qwen path keeps the 2-prompt ensemble (diversity/error compensation)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fa = ex.submit(_call, prompt_a)
            fb = ex.submit(_call, prompt_b)
            ans_a = fa.result()
            ans_b = fb.result()

    def _score(text):
        """Higher is better. Penalize NO_ANSWER; reward citation count and length."""
        if not text or len(text) < 30:
            return -1
        low = text.upper()
        if low.startswith("NO_ANSWER") or low == "NO_ANSWER":
            return -1
        citations = sum(1 for c in text if c == "[")
        # Slight preference for citation-bearing answers
        return len(text) + citations * 50

    score_a, score_b = _score(ans_a), _score(ans_b)
    if score_a < 0 and score_b < 0:
        return None
    winner = ans_a if score_a >= score_b else ans_b
    return winner


def long_context_reorder(items):
    """G3: LongContextReorder — highest-scored items at positions [0, -1], lowest in middle.

    Mitigates 'lost in the middle' (Liu et al.) when the LLM reads >=5 chunks.
    """
    if not LCR_ENABLED or len(items) < 3:
        return items
    sorted_items = sorted(items, key=lambda x: x[0], reverse=True)
    result = []
    for i, item in enumerate(sorted_items):
        if i % 2 == 0:
            result.append(item)
        else:
            result.insert(0, item)
    return result


# ---- G5: LLM-driven Knowledge Graph traversal ----

JSON_MODEL = os.environ.get("JSON_MODEL", "qwen2.5:7b")


def _qwen_json(prompt, schema_required=None, attempts=3):
    """Call qwen2.5:7b with format=json; validate required keys; retry up to `attempts` times.

    IFRNLLEI01PRD-611: ladder collapsed to qwen2.5:7b only. qwen3:4b was in
    the fallback slot but required `think: false` + <think>-tag stripping +
    a retry loop that still only hit 87.5% first-try JSON reliability.
    qwen2.5:7b has no thinking mode and returns clean JSON; with attempts=3
    we clear >=98% without model diversity.
    """
    json_fail_count = 0
    for attempt in range(attempts):
        body = {
            "model": JSON_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 300, "num_ctx": NUM_CTX_SMALL},
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                _record_local_usage(JSON_MODEL, data.get("prompt_eval_count", 0), data.get("eval_count", 0))
                text = data.get("response", "").strip()
                parsed = json.loads(text)
                if schema_required:
                    missing = [k for k in schema_required if k not in parsed]
                    if missing:
                        json_fail_count += 1
                        print(f"[_qwen_json] attempt {attempt+1} missing {missing}", file=sys.stderr)
                        continue
                return parsed
        except Exception as e:
            json_fail_count += 1
            print(f"[_qwen_json] attempt {attempt+1} err: {type(e).__name__}", file=sys.stderr)
            continue
    _emit_qwen_json_failure(json_fail_count)
    return None


def _emit_qwen_json_failure(fail_count):
    """#17 observability: bump a counter on the latency-probe prom file."""
    try:
        for path in (
            "/var/lib/node_exporter/textfile_collector/kb_rag.prom",
            "/tmp/kb_rag.prom",
        ):
            if os.path.exists(path):
                with open(path, "a") as f:
                    f.write(f'kb_qwen_json_failure_total {fail_count}\n')
                break
    except Exception:
        pass


MULTIHOP_CUES = ("depend", "services", "affect", "cascade", "caused", "correlate",
                 "between", "both", "multiple", "what happens when", "touched")


def plan_traversal(question):
    """G5: Let LLM generate a graph traversal plan.

    Returns dict: {start: str, filters: [str], hops: int 1-3, rel_types: [str]}
    or None on failure.
    """
    prompt = (
        "You plan traversals over an infrastructure graph to answer questions.\n\n"
        "Schema:\n"
        "- entity_type in {host, incident, service, chaos_experiment, alert_rule, lesson}\n"
        '- rel_type examples: affects, caused_by, depends_on, resolves, chaos-tests, involves-service, triggers\n\n'
        "Rules:\n"
        "- Prefer hops=2 for questions about dependencies, cascades, or multi-entity relationships\n"
        "- Use hops=1 only when the question asks about direct attributes of one entity\n"
        "- Filters: include hostnames (e.g. 'nl-pve01'), site codes (nl/gr), or keywords (e.g. 'dmz', 'tunnel')\n"
        "- Start with the entity type most likely to anchor the search\n\n"
        "Examples:\n"
        "Q: 'Which services depend on pve01?'\n"
        '  -> {"start":"host","filters":["pve01"],"hops":2,"rel_types":["depends_on","affects","involves-service"]}\n'
        "Q: 'What incidents affected both sites during GR isolation?'\n"
        '  -> {"start":"incident","filters":["GR isolation","nl","gr"],"hops":2,"rel_types":["affects","caused_by"]}\n'
        "Q: 'Which chaos experiments touched Freedom ISP?'\n"
        '  -> {"start":"chaos_experiment","filters":["freedom","VTI","tunnel"],"hops":1,"rel_types":["chaos-tests"]}\n\n'
        'Output ONLY JSON: {"start":"...","filters":[...],"hops":1|2|3,"rel_types":[...]}\n\n'
        f"Question: {question}\n\nJSON:"
    )
    plan = _qwen_json(prompt, schema_required=["start", "filters", "hops", "rel_types"])
    if not plan:
        return None
    if plan.get("start") not in ("host", "incident", "service", "chaos_experiment", "alert_rule", "lesson"):
        return None
    if not isinstance(plan.get("hops"), int) or not (1 <= plan["hops"] <= 3):
        plan["hops"] = 2
    # Multi-hop cue override: if the question clearly asks for relationships, force hops>=2
    ql = question.lower()
    if plan["hops"] < 2 and any(cue in ql for cue in MULTIHOP_CUES):
        plan["hops"] = 2
    if not isinstance(plan.get("filters"), list):
        plan["filters"] = []
    # Coerce non-string filters (LLM sometimes returns dicts)
    plan["filters"] = [str(f) if not isinstance(f, str) else f for f in plan["filters"]][:8]
    if not isinstance(plan.get("rel_types"), list):
        plan["rel_types"] = []
    return plan


def embedding_fallback_traverse(conn, question, limit=20):
    """Fallback when plan fails: embed the question, rank graph entities by name/attr cosine."""
    q_vec = embed_query(question)
    if not q_vec:
        return []
    # Pull all entities with their name+attributes as embeddable text
    rows = conn.execute(
        "SELECT id, entity_type, name, attributes FROM graph_entities"
    ).fetchall()
    if not rows:
        return []
    # Embed in one batch (batch_embed_documents handles prefix)
    texts = [f"{r[1]}: {r[2]} {(r[3] or '')[:200]}" for r in rows]
    vecs = batch_embed_documents(texts) or []
    scored = []
    for (rid, etype, name, attrs), v in zip(rows, vecs):
        if v is None:
            continue
        s = cosine_similarity(q_vec, v)
        if s > 0.3:
            scored.append((s, rid, etype, name, attrs))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:limit]


ALLOWED_START_TYPES = ("host", "incident", "service", "chaos_experiment", "alert_rule", "lesson")


def _execute_plan_variant(conn, start_type, filter_params, seed_where, hops, limit,
                          filter_by_type):
    """One CTE execution. Separate helper so execute_plan can widen progressively."""
    type_clause = "entity_type = ? AND" if filter_by_type else ""
    type_binds = (start_type,) if filter_by_type else ()
    try:
        return conn.execute(f"""
            WITH RECURSIVE traversal AS (
                SELECT id, name, entity_type, attributes, 0 AS depth, CAST(name AS TEXT) AS path
                FROM graph_entities
                WHERE {type_clause} ({seed_where})
                UNION
                SELECT ge.id, ge.name, ge.entity_type, ge.attributes, t.depth + 1,
                       t.path || ' -> ' || ge.name
                FROM traversal t
                JOIN graph_relationships gr ON (gr.source_id = t.id OR gr.target_id = t.id)
                JOIN graph_entities ge ON ge.id = CASE WHEN gr.source_id = t.id THEN gr.target_id ELSE gr.source_id END
                WHERE t.depth < ?
            )
            SELECT DISTINCT name, entity_type, attributes, depth, path
            FROM traversal
            ORDER BY depth, name
            LIMIT ?
        """, (*type_binds, *filter_params, hops, limit)).fetchall()
    except Exception as e:
        print(f"[traverse] SQL error: {e}", file=sys.stderr)
        return []


def execute_plan(conn, plan, limit=50):
    """G5: Execute a traversal plan via SQLite WITH RECURSIVE. Returns path evidence.

    Progressive widening when strict match yields nothing:
      1. entity_type restricted + all filters AND'd (strict)
      2. entity_type restricted + filters OR'd (any filter matches)
      3. entity_type dropped + filters OR'd (planner's type guess was wrong)
    Each level logs so the caller can see which path produced the rows.
    """
    if not plan or plan["start"] not in ALLOWED_START_TYPES:
        return []
    start_type = plan["start"]
    hops = plan.get("hops", 2)

    # Build per-filter clause (case-insensitive LIKE on name OR attributes)
    per_filter = []
    for f in plan["filters"][:5]:
        if not isinstance(f, str) or not f.strip():
            continue
        safe = f.strip()[:80]
        per_filter.append(("(LOWER(name) LIKE ? OR LOWER(attributes) LIKE ?)",
                           (f"%{safe.lower()}%", f"%{safe.lower()}%")))
    if not per_filter:
        # No filters — single strict query (type only)
        return _execute_plan_variant(
            conn, start_type, (), "1=1", hops, limit, filter_by_type=True,
        )

    flat_params = [p for _, params in per_filter for p in params]

    # Level 1: strict — type restricted, all filters AND'd
    strict_where = " AND ".join(c for c, _ in per_filter)
    rows = _execute_plan_variant(
        conn, start_type, flat_params, strict_where, hops, limit, filter_by_type=True,
    )
    if rows:
        return rows

    # Level 2: same type, ANY filter matches (OR'd)
    or_where = " OR ".join(c for c, _ in per_filter)
    rows = _execute_plan_variant(
        conn, start_type, flat_params, or_where, hops, limit, filter_by_type=True,
    )
    if rows:
        print(f"[traverse] widened: OR'd filters (strict AND had 0 seeds)", file=sys.stderr)
        return rows

    # Level 3: drop type restriction, OR filters — planner's type guess was wrong
    rows = _execute_plan_variant(
        conn, start_type, flat_params, or_where, hops, limit, filter_by_type=False,
    )
    if rows:
        print(f"[traverse] widened: dropped entity_type={start_type} restriction", file=sys.stderr)
    return rows


def cmd_traverse(question):
    """G5 CLI: LLM-planned graph traversal with embedding-fallback."""
    plan = plan_traversal(question)
    conn = _db_connect()
    rows = []
    if plan:
        print(f"[traverse] plan: {json.dumps(plan)}", file=sys.stderr)
        rows = execute_plan(conn, plan)
    else:
        print(f"[traverse] plan generation failed for: {question}", file=sys.stderr)

    if not rows and plan:
        # Fallback 1: hostname-join query_graph if any filter looks like a hostname
        for f in plan.get("filters", []):
            if isinstance(f, str) and any(p in f.lower() for p in ("pve", "claude", "nms", "nllei", "grskg", "dmz", "fw01", "sw0")):
                print(f"[traverse] fallback to query_graph({f})", file=sys.stderr)
                graph_results = query_graph(f, db_path=DB_PATH, limit=15)
                for name, attrs, rel_type in graph_results:
                    rows.append((name, "incident", attrs, 1, f"{f} -> {name}"))
                if rows:
                    break

    if not rows:
        # Fallback 2: embedding cosine over all graph entities
        print(f"[traverse] fallback to embedding cosine on graph_entities", file=sys.stderr)
        scored = embedding_fallback_traverse(conn, question, limit=15)
        for s, rid, etype, name, attrs in scored:
            rows.append((name, etype, attrs, 1, f"cosine={s:.3f}"))

    conn.close()
    if not rows:
        return 0
    for name, etype, attrs, depth, path in rows:
        print(f"[depth={depth}] {etype}:{name}  ({path})")
    return len(rows)


def ensure_embedding_column(conn):
    """Add embedding column if it doesn't exist. No-op in read-only mode."""
    if DB_READ_ONLY:
        return
    cursor = conn.execute("PRAGMA table_info(incident_knowledge)")
    columns = [row[1] for row in cursor.fetchall()]
    if "embedding" not in columns:
        try:
            conn.execute("ALTER TABLE incident_knowledge ADD COLUMN embedding TEXT DEFAULT ''")
            conn.commit()
        except Exception:
            pass


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
    import time as _t
    _search_start = _t.time()
    def _budget_exceeded():
        return SEARCH_BUDGET_S > 0 and (_t.time() - _search_start) > SEARCH_BUDGET_S

    conn = _db_connect()
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
        # IFRNLLEI01PRD-703: if we've already spent SEARCH_BUDGET_S seconds
        # on the semantic path, skip HyDE (which chains LLM-generate +
        # re-embed + re-search, adding 20-30s on a cold query). Go straight
        # to keyword fallback — still returns something useful, within budget.
        if _budget_exceeded():
            print(f"[budget] semantic search exceeded {SEARCH_BUDGET_S}s — skipping HyDE, falling back to keyword", file=sys.stderr)
            return cmd_keyword_fallback(conn, query, limit, days)
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


def rrf_score(semantic_rank, keyword_rank, wiki_rank=None, transcript_rank=None,
              chaos_rank=None, k=60, sem_quality=None):
    """Reciprocal Rank Fusion — combines 5 signals with hand-tuned weights.

    Weights calibrated 2026-04-17:
    - semantic 1.0 (boosted to 1.5 on high confidence)
    - keyword 1.0
    - wiki 0.5 (generic markdown — often matches too many queries without specificity)
    - transcripts 0.4 (raw session text — richer than wiki for incident detail)
    - chaos 0.35 (quantitative baselines — useful when query mentions chaos/resilience)
    """
    score = 0.0
    sem_weight = float(os.environ.get("RRF_W_SEMANTIC", "1.0"))
    kw_weight = float(os.environ.get("RRF_W_KEYWORD", "1.0"))
    wiki_weight = float(os.environ.get("RRF_W_WIKI", "0.9"))
    tr_weight = float(os.environ.get("RRF_W_TRANSCRIPT", "0.4"))
    chaos_weight = float(os.environ.get("RRF_W_CHAOS", "0.35"))
    if sem_quality is not None and sem_quality > 0.8:
        sem_weight *= 1.5
    if semantic_rank is not None:
        score += sem_weight / (k + semantic_rank)
    if keyword_rank is not None:
        score += kw_weight / (k + keyword_rank)
    if wiki_rank is not None:
        score += wiki_weight / (k + wiki_rank)
    if transcript_rank is not None:
        score += tr_weight / (k + transcript_rank)
    if chaos_rank is not None:
        score += chaos_weight / (k + chaos_rank)
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


def search_chaos_experiments(conn, query, query_vec=None, hostname="", limit=5):
    """5th RRF signal: chaos experiment baselines for queried infrastructure.

    Hybrid: semantic similarity (when query_vec provided) + keyword LIKE fallback.
    Bridges chaos automation into the ChatOps RAG pipeline.
    """
    results = {}
    try:
        # --- Semantic path (preferred when embeddings exist and query_vec provided) ---
        semantic_rows = []
        if query_vec:
            try:
                emb_rows = conn.execute(
                    "SELECT experiment_id, chaos_type, targets, verdict, "
                    "convergence_seconds, mttd_seconds, mttr_seconds, recovery_seconds, "
                    "started_at, embedding FROM chaos_experiments "
                    "WHERE embedding IS NOT NULL AND embedding != '' "
                    "AND started_at > datetime('now', '-90 days')"
                ).fetchall()
                scored = []
                for r in emb_rows:
                    try:
                        v = json.loads(r[9])
                        sim = cosine_similarity(query_vec, v)
                        if sim > 0.3:
                            scored.append((sim, r))
                    except Exception:
                        continue
                scored.sort(key=lambda x: x[0], reverse=True)
                semantic_rows = scored[:limit]
            except sqlite3.OperationalError:
                pass
        # --- Keyword fallback (old behavior) ---
        if not semantic_rows:
            search_terms = []
            if hostname:
                search_terms.append(f"%{hostname}%")
            for site in ("NL", "GR", "NO", "CH"):
                if site.lower() in query.lower() or site in query:
                    search_terms.append(f"%{site}%")
            for keyword in ("tunnel", "vti", "freedom", "xs4all", "inalan", "dmz", "container"):
                if keyword in query.lower():
                    search_terms.append(f"%{keyword}%")
            if not search_terms:
                search_terms.append(f"%{query[:30]}%")
            placeholders = " OR ".join(["targets LIKE ?" for _ in search_terms])
            rows = conn.execute(
                f"SELECT experiment_id, chaos_type, targets, verdict, "
                f"convergence_seconds, mttd_seconds, mttr_seconds, recovery_seconds, "
                f"started_at FROM chaos_experiments "
                f"WHERE ({placeholders}) "
                f"AND started_at > datetime('now', '-90 days') "
                f"ORDER BY started_at DESC LIMIT ?",
                (*search_terms, limit),
            ).fetchall()
            semantic_rows = [(0.0, row + (None,)) for row in rows]  # pad embedding slot

        for rank, (sim, row) in enumerate(semantic_rows, 1):
            key = f"chaos:{row[0]}"
            results[key] = {
                "rank": rank,
                "sim": sim,
                "row": {
                    "experiment_id": row[0], "chaos_type": row[1],
                    "targets": row[2], "verdict": row[3],
                    "convergence_seconds": row[4], "mttd_seconds": row[5],
                    "mttr_seconds": row[6], "recovery_seconds": row[7],
                    "started_at": row[8],
                },
            }
    except Exception:
        pass  # chaos_experiments table may not exist
    return results


NEGATION_MARKERS = (
    r"\bnot\b", r"\bdo not\b", r"\bdon'?t\b", r"\bnever\b", r"\bavoid\b",
    r"\bexplicit(?:ly)? not\b", r"\bforbid", r"\bprohibit", r"\bmust not\b",
    r"\bshould not\b", r"\bno kubectl\b", r"\bNOT\b",  # capitalized NOT is often emphatic
)


def _is_negation_query(q):
    """True if the query has negation markers suggesting a 'do NOT' policy question.

    These queries benefit from keyword-first retrieval on feedback_* files where
    policy rules live — cosine retrieval on short feedback files loses to verbose
    prose on the same topic.
    """
    REDACTED_a7b84d63 as _re
    ql = q.strip()
    return any(_re.search(m, ql, _re.IGNORECASE) for m in NEGATION_MARKERS)


def _negation_keyword_boost(conn, query, query_terms, raw_vec=None, limit=15):
    """Retrieval for negation queries: mix cosine + keyword over feedback_* wiki rows.

    Negation queries lose on verbose-prose cosine; the tight policy statements live
    in memory/feedback_*. Strategy:
      1. Pull all feedback_* wiki rows (~60 files total, tiny universe)
      2. Rank them by cosine sim to raw query
      3. Union with any keyword-term matches (for queries with specific vocabulary)
      4. Return top `limit` to the caller, which seeds them at rank 1..N so they
         reach the rerank pool; the cross-encoder picks the actually-relevant ones.
    """
    try:
        rows = conn.execute(
            "SELECT path, title, section, embedding, content_preview "
            "FROM wiki_articles "
            "WHERE path LIKE 'memory/feedback_%' "
            "  AND embedding IS NOT NULL AND embedding != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    if not rows:
        return []

    # Cosine ranking (primary)
    scored = []
    if raw_vec:
        for r in rows:
            try:
                v = json.loads(r["embedding"])
                sim = cosine_similarity(raw_vec, v)
                scored.append((sim, r))
            except (json.JSONDecodeError, TypeError):
                continue
    else:
        scored = [(0.5, r) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)

    # Also consider keyword matches: any feedback row whose preview contains query terms
    stop = {"what", "which", "when", "where", "does", "should", "would", "could", "with",
            "from", "this", "that", "have", "were", "want", "during", "while", "after",
            "explicitly", "technique", "cluster"}
    terms = [t.lower().strip(".,?!") for t in query.split()
             if len(t) > 3 and t.lower() not in stop]
    kw_rows = set()
    if terms:
        for sim, r in scored:
            preview = (r["content_preview"] or "").lower()
            title = (r["title"] or "").lower()
            if any(t in preview or t in title for t in terms):
                kw_rows.add(r["path"])

    # Interleave: top cosine first, then any keyword-only matches (that cosine missed)
    result = []
    seen = set()
    for sim, r in scored:
        if r["path"] in seen:
            continue
        seen.add(r["path"])
        result.append(r)
        if len(result) >= limit:
            break
    return result


def cmd_hybrid_search(query, limit=5, days=90, threshold=0.3, use_rewrite=False):
    """Hybrid search combining semantic similarity and keyword matching via RRF.

    G2 RAG Fusion: when use_rewrite=True OR RAG_FUSION env var enabled, generates 3
    perspective-diverse rephrasings, batch-embeds all variants in one call, and
    fuses rankings across variants.

    IFRNLLEI01PRD-703: budget-aware. Checks `_budget_exceeded_hybrid()` before the
    optional synth step (the longest tail, 15-20s on novel queries). When the
    semantic + rerank path has already consumed SEARCH_BUDGET_S, skip synth and
    return the ranked candidates we already have. Keeps RAG p95 under the
    12s alert threshold without changing retrieval quality for fast-paths.
    """
    import time as _t
    _hy_start = _t.time()
    def _budget_exceeded_hybrid():
        return SEARCH_BUDGET_S > 0 and (_t.time() - _hy_start) > SEARCH_BUDGET_S

    conn = _db_connect()
    conn.row_factory = sqlite3.Row
    ensure_embedding_column(conn)

    # IFRNLLEI01PRD-616 H50: short-circuit on pure mtime-sort intent.
    # Queries like "name any three memory files created in the last 48 hours"
    # can't be answered by semantic search (the query text doesn't describe
    # the files' contents), so return the mtime-ranked window directly.
    if detect_mtime_sort_intent(query):
        window = extract_temporal_window(query)
        if window:
            since, until = window
            path_prefix = "memory/" if re.search(r"\bmemor", query, re.IGNORECASE) else None
            rows = list_recent_wiki(conn, since, until, limit=limit, path_prefix=path_prefix)
            print(f"[mtime-sort] intent detected, bypassing semantic retrieval. "
                  f"window=[{datetime.datetime.utcfromtimestamp(since):%Y-%m-%d %H:%M}..."
                  f"{datetime.datetime.utcfromtimestamp(until):%Y-%m-%d %H:%M}] UTC, "
                  f"{len(rows)} rows, prefix={path_prefix or '*'}",
                  file=sys.stderr)
            for r in rows:
                mtime = datetime.datetime.utcfromtimestamp(r["source_mtime"])
                age_h = (datetime.datetime.utcnow() - mtime).total_seconds() / 3600.0
                # Mimic the pipe-delimited row format downstream consumers expect.
                # sim score = 1.0 for mtime-sort (deterministic rank).
                print(f"wiki|{r['path']}|{r['title']}|{r['section']}|-1|{mtime.isoformat()}||1.000")
            print(f"RETRIEVAL_QUALITY:1.000|{len(rows)}|1.000|1.000")
            return

    # Embed raw query first (needed for both the early-exit probe AND the final search)
    raw_vec = embed_query(query)
    query_vecs_map = {query: raw_vec} if raw_vec else {}

    # G2 early-exit: if base semantic quality is already high, skip rewrite entirely.
    # Probes incident_knowledge + wiki_articles (where memory files now live).
    skip_rewrite = False
    if raw_vec and (use_rewrite or RAG_FUSION):
        try:
            top_sim = 0.0
            probe_rows = conn.execute(
                "SELECT embedding FROM incident_knowledge "
                "WHERE embedding IS NOT NULL AND embedding != '' "
                "AND (valid_until IS NULL OR valid_until > datetime('now')) "
                "LIMIT 200"
            ).fetchall()
            for r in probe_rows:
                try:
                    rv = json.loads(r["embedding"])
                    s = cosine_similarity(raw_vec, rv)
                    if s > top_sim:
                        top_sim = s
                except (json.JSONDecodeError, TypeError):
                    continue
            # Also probe wiki_articles (memory files have high-signal frontmatter desc here)
            try:
                wiki_probe = conn.execute(
                    "SELECT embedding FROM wiki_articles WHERE embedding IS NOT NULL AND embedding != '' LIMIT 300"
                ).fetchall()
                for r in wiki_probe:
                    try:
                        rv = json.loads(r["embedding"])
                        s = cosine_similarity(raw_vec, rv)
                        if s > top_sim:
                            top_sim = s
                    except (json.JSONDecodeError, TypeError):
                        continue
            except sqlite3.OperationalError:
                pass
            if top_sim >= 0.70:
                skip_rewrite = True
                print(f"[fusion] SKIP rewrite (raw query top-sim {top_sim:.3f} >= 0.70)", file=sys.stderr)
            # IFRNLLEI01PRD-703: low-signal short-circuit. If the raw query
            # has no plausibly-relevant candidate in the KB probe (top-sim
            # below 0.30 against 200 incident rows + 300 wiki rows), paying
            # for 3-variant rewrite + 30×4-pair rerank + synth is pointless —
            # we'd just be LLM-expanding a query that has no corpus match.
            # Skip rewrite, and the budget-guarded synth skip catches the
            # rest. Keeps the "probe novel query" p95 under the 12 s alert
            # threshold.
            elif top_sim < 0.30 and SEARCH_BUDGET_S > 0:
                skip_rewrite = True
                print(f"[fusion] SKIP rewrite (raw query top-sim {top_sim:.3f} < 0.30 — no corpus signal; budget-guarded)", file=sys.stderr)
        except sqlite3.OperationalError:
            pass

    # G2: Query rewriting — always-on with RAG_FUSION, opt-in with --rewrite, skipped on high base quality
    queries = [query]
    if (use_rewrite or RAG_FUSION) and not skip_rewrite:
        queries = rewrite_query_multi(query, num_variants=3)
        if len(queries) > 1:
            print(f"[fusion] Original: {query}", file=sys.stderr)
            for i, rw in enumerate(queries[1:], 1):
                print(f"[fusion] Variant {i}: {rw}", file=sys.stderr)
        # Only embed the NEW variants (we already have raw_vec cached)
        new_variants = [q for q in queries if q not in query_vecs_map]
        if new_variants:
            batch_vecs = batch_embed_queries(new_variants)
            for q, v in zip(new_variants, batch_vecs):
                if v is not None:
                    query_vecs_map[q] = v

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
            q_vec = query_vecs_map.get(q)
            if not q_vec:
                continue
            for row in rows:
                try:
                    row_vec = json.loads(row["embedding"])
                    sim = cosine_similarity(q_vec, row_vec)
                    # IFRNLLEI01PRD-647: discount chatops-cli rows (interactive
                    # CLI session knowledge) vs real infra incidents.
                    if row["project"] == "chatops-cli":
                        sim *= CLI_INCIDENT_WEIGHT
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
    # IFRNLLEI01PRD-609 H06/H50: temporal window filter on source_mtime.
    # When the query has "last N hours/days" / "N hours ending YYYY-MM-DD" /
    # "on YYYY-MM-DD", restrict to wiki rows whose source file was last
    # modified within that window. Without this, "files created in last 48h"
    # queries surface 30-day-old matches and confuse the synth step.
    temporal_window = extract_temporal_window(query)
    try:
        try:
            if temporal_window:
                since, until = temporal_window
                wiki_rows = conn.execute(
                    "SELECT path, title, section, embedding, content_preview FROM wiki_articles "
                    "WHERE embedding IS NOT NULL AND embedding != '' "
                    "AND source_mtime >= ? AND source_mtime < ?",
                    (since, until),
                ).fetchall()
                print(f"[temporal-filter] wiki_articles windowed to "
                      f"[{datetime.datetime.utcfromtimestamp(since):%Y-%m-%d %H:%M}..."
                      f"{datetime.datetime.utcfromtimestamp(until):%Y-%m-%d %H:%M}] "
                      f"-> {len(wiki_rows)} rows", file=sys.stderr)
            else:
                wiki_rows = conn.execute(
                    "SELECT path, title, section, embedding, content_preview FROM wiki_articles "
                    "WHERE embedding IS NOT NULL AND embedding != ''"
                ).fetchall()
        except sqlite3.OperationalError:
            # content_preview or source_mtime column may not exist yet
            wiki_rows = conn.execute(
                "SELECT path, title, section, embedding FROM wiki_articles "
                "WHERE embedding IS NOT NULL AND embedding != ''"
            ).fetchall()
        if wiki_rows:
            wiki_sims = {}
            for q in queries:
                q_vec = query_vecs_map.get(q)
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
            # D2: rank-boost memory/docs; penalize auto-generated index sections
            # that contain no original content (e.g., "Related Memory Entries").
            GENERIC_SECTIONS = {
                "related memory entries", "lessons learned", "links",
                "see also", "index", "references",
            }
            # Q01: for negation queries ("do NOT"), pull keyword-matched feedback files
            # with forced strong rank so they appear in the rerank pool even if cosine
            # didn't surface them.
            negation_rows = []
            if _is_negation_query(query):
                negation_rows = _negation_keyword_boost(
                    conn, query, queries, raw_vec=raw_vec, limit=12
                )
                print(f"[negation] cosine-over-feedback fetched {len(negation_rows)} rows", file=sys.stderr)
            for i, nrow in enumerate(negation_rows, 1):
                npath = nrow["path"]
                nkey = f"wiki:{npath}:{nrow['section']}"
                if nkey in wiki_ranked:
                    continue
                # Seed at ranks 1..N so negation feedback files reach the rerank pool
                # even when cosine alone didn't surface them. The cross-encoder will
                # demote any that aren't actually relevant.
                wiki_ranked[nkey] = {"rank": i, "sim": 0.5, "row": nrow}
            for rank, (sim, wrow) in enumerate(w_scored[: limit * 4], 1):
                path = wrow["path"] or ""
                section = (wrow["section"] or "").strip().lower()
                adjusted = rank
                # Memory/CLAUDE.md/docs files get a 2× rank boost (lower rank = better)
                if path.startswith("memory/") or path.startswith("project-docs/") or path.startswith("docs/"):
                    adjusted = rank / 2
                # Generic auto-generated index sections are pushed back 2×
                if section in GENERIC_SECTIONS:
                    adjusted = adjusted * 2
                # H08: tiny dense feedback files (policy statements like
                # "do NOT use kubectl") have concentrated signal but lose cosine
                # to verbose prose. Boost rank 1.5× when content_preview is small
                # AND similarity is already above threshold (so we know it's relevant).
                try:
                    preview = wrow["content_preview"] if "content_preview" in wrow.keys() else ""
                    if preview and len(preview) < 600 and sim > 0.55 and path.startswith("memory/feedback_"):
                        adjusted = adjusted / 1.5
                except (IndexError, KeyError):
                    pass
                key = f"wiki:{path}:{wrow['section']}"
                wiki_ranked[key] = {"rank": adjusted, "sim": sim, "row": wrow}
    except sqlite3.OperationalError:
        pass  # wiki_articles table doesn't exist yet

    # 4. Session transcript search (4th signal — MemPalace verbatim storage)
    transcript_ranked = {}
    try:
        # G2: fetch once, iterate variants in memory (no re-read per query)
        if days > 0:
            t_rows_all = conn.execute(
                "SELECT id, issue_id, chunk_index, role, content, embedding, created_at "
                "FROM session_transcripts "
                "WHERE embedding IS NOT NULL AND embedding != '' "
                "AND created_at > datetime('now', ?)",
                (f"-{days} days",),
            ).fetchall()
        else:
            t_rows_all = conn.execute(
                "SELECT id, issue_id, chunk_index, role, content, embedding, created_at "
                "FROM session_transcripts "
                "WHERE embedding IS NOT NULL AND embedding != ''"
            ).fetchall()
        for q in queries:
            q_vec = query_vecs_map.get(q)
            if not q_vec:
                continue
            for trow in t_rows_all:
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

    # 4b. Chaos baselines (5th RRF signal — semantic + keyword hybrid, uses raw_vec)
    chaos_ranked = search_chaos_experiments(conn, query, query_vec=query_vecs_map.get(query), limit=5)

    # 5. Reciprocal Rank Fusion (5 signals + quality-based weighting)
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

    # Add chaos baseline results to fusion (5th signal)
    for key, cdata in chaos_ranked.items():
        c_rank = cdata["rank"]
        score = rrf_score(None, None, chaos_rank=c_rank, sem_quality=sem_quality)
        fused.append((score, 0.0, cdata["row"], "chaos"))

    fused.sort(key=lambda x: x[0], reverse=True)

    if not fused:
        conn.close()
        return 0

    # G1 + Q1: Cross-encoder rerank top-30 candidates × all query variants.
    # Pass all variants (including HyDE-hypothesis, keyword-rich) so we can take
    # max-per-doc — unlocks oblique queries where the canonical rephrasing is what matches.
    rerank_pool = fused[:30]
    # Keep a copy of the pre-rerank pool for synthesis (it has wider candidate set)
    synthesis_pool = list(fused[:15])
    if RERANK_ENABLED and len(rerank_pool) > limit + 2:
        print(f"[rerank] scoring {len(rerank_pool)} candidates via {RERANK_MODEL}", file=sys.stderr)
        rerank_candidates._current_variants = queries  # pass variants to max-over path
        try:
            rerank_pool = rerank_candidates(query, rerank_pool, top_k=limit * 2)
        finally:
            rerank_candidates._current_variants = None
        # Use the reranked pool for synthesis if it has good items
        synthesis_pool = rerank_pool[:15] if rerank_pool else synthesis_pool

    # Q2: If cross-encoder max score is low (no single doc strongly matches), synthesize
    # an answer from multiple chunks. Targets meta-queries whose answer spans 3+ docs.
    synthesized = None
    max_ce = getattr(rerank_candidates, "_last_max_ce", None)
    trigger = False
    if SYNTH_ENABLED and synthesis_pool:
        # Primary trigger: cross-encoder max < threshold — no single doc is strongly relevant
        if max_ce is not None and max_ce < SYNTH_THRESHOLD:
            trigger = True
            trigger_reason = f"crossencoder max {max_ce:.3f} < {SYNTH_THRESHOLD}"
        # Fallback trigger: raw semantic quality low
        elif max_ce is None:
            max_sim_preview = max((c[1] for c in rerank_pool[:5]), default=0.0)
            if max_sim_preview < 0.6:
                trigger = True
                trigger_reason = f"max semantic sim {max_sim_preview:.3f} < 0.6"
    if trigger and _budget_exceeded_hybrid():
        print(f"[synth] SKIPPED ({trigger_reason}, but budget {SEARCH_BUDGET_S}s exceeded) — returning ranked candidates without synthesis", file=sys.stderr)
    elif trigger:
        print(f"[synth] triggered ({trigger_reason}) — synthesizing from fresh-query candidates", file=sys.stderr)
        synthesized = synthesize_answer(query, synthesis_pool, top_n=10, conn=conn)
        if synthesized:
            print(f"[synth] generated {len(synthesized)} chars", file=sys.stderr)
    # Clear the side-channel
    rerank_candidates._last_max_ce = None

    # Guarantee at least 1 chaos baseline in output when available (intelligence bridge)
    output_items = rerank_pool[:limit]
    has_chaos = any(src == "chaos" for _, _, _, src in output_items)
    if not has_chaos and chaos_ranked:
        # Replace last non-chaos item with top chaos result
        top_chaos = next((f for f in fused if f[3] == "chaos"), None)
        if top_chaos and len(output_items) >= limit:
            output_items[-1] = top_chaos
        elif top_chaos:
            output_items.append(top_chaos)

    # G3: LongContextReorder — highest-score items at positions [0, -1]
    output_items = long_context_reorder(output_items)

    # Q2: Prepend synthesized answer if available. Judge will see it at position 0.
    if synthesized:
        synth_line = (
            f"synthesis|composed-answer|{query[:80]}|"
            f"{synthesized.replace(chr(10),' ').replace('|',' ')[:800]}|"
            f"0.95|{NOW_ISO}||1.000"
        )
    else:
        synth_line = None

    # Emit quality metadata (G4 existing) — computed on pre-rerank fusion
    avg_sim = sum(c[1] for c in rerank_pool[:limit]) / max(len(rerank_pool[:limit]), 1)
    max_sim = max((c[1] for c in rerank_pool[:limit]), default=0.0)
    quality_score = round(avg_sim * 0.6 + max_sim * 0.4, 3)
    print(f"RETRIEVAL_QUALITY:{quality_score}|{len(output_items)}|{avg_sim:.3f}|{max_sim:.3f}")

    # Synthesis row goes first so the judge sees the direct answer before raw chunks
    if synth_line:
        print(synth_line)

    for score, sim, row, source in output_items:
        if source == "wiki":
            print(
                f"wiki|{row['path']}|{row['title']}|"
                f"{(row['section'] or '').replace('|', ' ')[:200]}|"
                f"-1|{NOW_ISO}||{sim:.3f}"
            )
        elif source == "chaos":
            targets = (row.get("targets", "") or "").replace("|", " ")[:100]
            verdict = row.get("verdict", "UNKNOWN")
            conv = row.get("convergence_seconds", "N/A")
            mttd = row.get("mttd_seconds", "N/A")
            print(
                f"{row['experiment_id']}|chaos-baseline|{row['chaos_type']}|"
                f"Verdict:{verdict} Convergence:{conv}s MTTD:{mttd}s Targets:{targets}|"
                f"0.8|{row.get('started_at', '')}||0.000"
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
            conn = _db_connect()
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

    elif cmd == "traverse":
        if len(sys.argv) < 3:
            print("Usage: kb-semantic-search.py traverse 'question'")
            sys.exit(1)
        cmd_traverse(sys.argv[2])

    elif cmd == "list-recent":
        # Usage: list-recent [--hours N | --days N] [--limit N] [--path-prefix PATH]
        hours, days, limit, path_prefix = None, None, 10, None
        argv = sys.argv[2:]
        i = 0
        while i < len(argv):
            a = argv[i]
            if a == "--hours" and i + 1 < len(argv):
                hours = int(argv[i + 1]); i += 2; continue
            if a == "--days" and i + 1 < len(argv):
                days = int(argv[i + 1]); i += 2; continue
            if a == "--limit" and i + 1 < len(argv):
                limit = int(argv[i + 1]); i += 2; continue
            if a == "--path-prefix" and i + 1 < len(argv):
                path_prefix = argv[i + 1]; i += 2; continue
            i += 1
        if hours is None and days is None:
            hours = 48
        cmd_list_recent(hours=hours, days=days, limit=limit, path_prefix=path_prefix)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
