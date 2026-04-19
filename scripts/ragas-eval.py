#!/usr/bin/env python3
"""RAGAS evaluation pipeline for claude-gateway agentic system.

Pure Python (stdlib + urllib only) implementation of RAGAS metrics using
Claude Haiku as the LLM judge. No external packages required.

Metrics:
  - Faithfulness: claim decomposition + NLI verification against context
  - Context Precision: weighted precision@k (RAGAS formula)
  - Context Recall: reference coverage via claim verification

Usage:
  ragas-eval.py evaluate --query "q" --answer "a" --context "c" --ground-truth "gt"
  ragas-eval.py golden-set          # Extract 50 Q&A pairs from incident_knowledge
  ragas-eval.py run-golden           # Evaluate all golden set queries
  ragas-eval.py summary              # Print aggregate scores
"""

import argparse
import json
import math
import os
REDACTED_a7b84d63
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)

EVAL_MODEL = "claude-haiku-4-5-20251001"
GOLDEN_SET_PATH = os.path.join(SCRIPT_DIR, "eval-sets", "ragas-golden.json")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------


def _load_api_key():
    """Resolve Anthropic API key from env var or .env file."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key

    env_path = os.path.join(REPO_DIR, ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass

    print("FATAL: ANTHROPIC_API_KEY not found in env or .env file", file=sys.stderr)
    sys.exit(1)


API_KEY = _load_api_key()

# ---------------------------------------------------------------------------
# LLM call (pure Python, no SDK)
# ---------------------------------------------------------------------------

_MAX_LLM_RETRIES = 3
_LLM_RETRY_DELAY = 2  # seconds


# Judge backend config — local gemma3:12b (Ollama) by default,
# Haiku (Anthropic API) via JUDGE_BACKEND=haiku opt-in.
JUDGE_BACKEND = os.environ.get("JUDGE_BACKEND", "local")  # local | haiku
JUDGE_LOCAL_MODEL = os.environ.get("JUDGE_LOCAL_MODEL", "gemma3:12b")
JUDGE_LOCAL_FALLBACK = os.environ.get("JUDGE_LOCAL_FALLBACK", "qwen2.5:7b")


def _call_ollama_judge(model, system, user, max_tokens=2048):
    """Call a local Ollama model as judge. Returns text content."""
    payload = json.dumps({
        "model": model,
        "prompt": f"{system}\n\n{user}",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": max_tokens, "num_ctx": 4096},
    }).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = json.loads(resp.read())
        # Tier 0 usage record (no cost, tracked for observability)
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO llm_usage (tier, model, input_tokens, output_tokens, cost_usd, issue_id) "
                "VALUES (0, ?, ?, ?, 0.0, 'ragas-judge-local')",
                (model, body.get("prompt_eval_count", 0), body.get("eval_count", 0)),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        return body.get("response", "")


def call_haiku(system, user, max_tokens=2048):
    """Judge call — routes to local gemma3 by default, Haiku on JUDGE_BACKEND=haiku.

    Function name kept 'call_haiku' to minimize churn across 20+ call sites;
    the internal dispatch is what moved to local-first.
    """
    # Local-first path (default). Gemma3:12b primary, qwen2.5:7b fallback.
    if JUDGE_BACKEND == "local":
        for model in (JUDGE_LOCAL_MODEL, JUDGE_LOCAL_FALLBACK):
            try:
                return _call_ollama_judge(model, system, user, max_tokens)
            except Exception as exc:
                print(f"[judge:{model}] {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
        return ""

    # Legacy Haiku path (JUDGE_BACKEND=haiku)
    url = "https://api.anthropic.com/v1/messages"
    payload = json.dumps({
        "model": EVAL_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")

    for attempt in range(1, _MAX_LLM_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("x-api-key", API_KEY)
            req.add_header("anthropic-version", "2023-06-01")
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read())
                # E3: record Haiku judge usage in llm_usage (tier 2, actual cost)
                try:
                    usage = body.get("usage", {})
                    in_tok = usage.get("input_tokens", 0)
                    out_tok = usage.get("output_tokens", 0)
                    # Haiku 4.5 pricing: $1/M input, $5/M output (as of 2026-04)
                    cost = (in_tok / 1_000_000.0) * 1.0 + (out_tok / 1_000_000.0) * 5.0
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute(
                        "INSERT INTO llm_usage (tier, model, input_tokens, output_tokens, cost_usd, issue_id) "
                        "VALUES (2, ?, ?, ?, ?, 'ragas-judge')",
                        (EVAL_MODEL, in_tok, out_tok, round(cost, 6)),
                    )
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
                return body["content"][0]["text"]
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in (429, 500, 502, 503, 529) and attempt < _MAX_LLM_RETRIES:
                wait = _LLM_RETRY_DELAY * attempt
                print(
                    f"[haiku] HTTP {status}, retry {attempt}/{_MAX_LLM_RETRIES} in {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, OSError) as exc:
            if attempt < _MAX_LLM_RETRIES:
                wait = _LLM_RETRY_DELAY * attempt
                print(
                    f"[haiku] Network error ({exc}), retry {attempt}/{_MAX_LLM_RETRIES} in {wait}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            raise
    return ""


def _parse_json_response(text):
    """Parse JSON from Haiku response, stripping markdown fences if present."""
    cleaned = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove trailing ``` line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# RAGAS Metric 1: Faithfulness
# ---------------------------------------------------------------------------


def _decompose_claims(answer):
    """Break an answer into atomic factual claims via Haiku."""
    system = (
        "You are a claim decomposition engine. Given a text, extract every distinct "
        "atomic factual claim. Each claim must be a single, self-contained statement "
        "that can be independently verified. Return a JSON array of strings."
    )
    user = (
        f"Decompose this text into atomic claims. Return ONLY a JSON array of strings, "
        f"nothing else.\n\nText: {answer}"
    )
    raw = call_haiku(system, user, max_tokens=1024)
    try:
        claims = _parse_json_response(raw)
        if isinstance(claims, list):
            return [str(c) for c in claims if c]
        return []
    except (json.JSONDecodeError, ValueError):
        # Fallback: split on sentence boundaries
        sentences = [s.strip() for s in re.split(r'[.!?]+', answer) if s.strip()]
        return sentences if sentences else [answer]


def _verify_claims_nli(claims, context):
    """Verify each claim against context using Natural Language Inference.

    Returns (supported_count, total_count).
    """
    if not claims:
        return 0, 0

    system = (
        "You are an NLI (Natural Language Inference) judge. For each claim, determine "
        "whether the provided context SUPPORTS or DOES NOT SUPPORT the claim. "
        "A claim is supported if the context contains information that substantiates it, "
        "even if not word-for-word. Return a JSON array of objects with keys "
        '"claim" and "verdict" (one of "supported" or "unsupported").'
    )
    claims_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(claims))
    user = (
        f"Context:\n{context}\n\n"
        f"Claims to verify:\n{claims_text}\n\n"
        f"Return ONLY a JSON array of objects, nothing else."
    )
    raw = call_haiku(system, user, max_tokens=2048)
    try:
        verdicts = _parse_json_response(raw)
        if isinstance(verdicts, list):
            supported = sum(
                1 for v in verdicts
                if isinstance(v, dict) and v.get("verdict", "").lower() == "supported"
            )
            return supported, len(claims)
    except (json.JSONDecodeError, ValueError):
        pass
    # If parsing failed, count simple keyword matches as fallback
    lower_raw = raw.lower()
    supported = lower_raw.count('"supported"') - lower_raw.count('"unsupported"')
    return max(supported, 0), len(claims)


def compute_faithfulness(answer, context):
    """Compute faithfulness score: fraction of answer claims supported by context.

    Score = supported_claims / total_claims
    """
    if not answer or not context:
        return -1.0

    claims = _decompose_claims(answer)
    if not claims:
        return -1.0

    supported, total = _verify_claims_nli(claims, context)
    if total == 0:
        return -1.0

    score = supported / total
    return round(score, 4)


# ---------------------------------------------------------------------------
# RAGAS Metric 2: Context Precision (weighted precision@k)
# ---------------------------------------------------------------------------


def compute_context_precision(query, context_chunks, ground_truth):
    """Compute context precision using the RAGAS weighted precision@k formula.

    For each chunk at rank k, classify as relevant (1) or irrelevant (0).
    precision@k = sum(relevant_i for i=1..k) / k
    Context Precision = sum(precision@k * relevant_k for k=1..K) / total_relevant

    If total_relevant = 0, score is 0.0.
    """
    if not context_chunks or not ground_truth:
        return -1.0

    # Classify each chunk
    system = (
        "You are a relevance judge. Given a question, a ground truth answer, and a "
        "retrieved document chunk, determine whether the chunk is RELEVANT (contains "
        "information useful for answering the question correctly) or IRRELEVANT. "
        "Return ONLY a JSON object with key \"verdict\" set to \"relevant\" or \"irrelevant\"."
    )

    relevance = []
    for i, chunk in enumerate(context_chunks):
        user = (
            f"Question: {query}\n\n"
            f"Ground truth answer: {ground_truth}\n\n"
            f"Retrieved chunk (rank {i+1}):\n{chunk}\n\n"
            f"Return ONLY a JSON object, nothing else."
        )
        raw = call_haiku(system, user, max_tokens=256)
        try:
            obj = _parse_json_response(raw)
            verdict = obj.get("verdict", "").lower() if isinstance(obj, dict) else ""
            relevance.append(1 if verdict == "relevant" else 0)
        except (json.JSONDecodeError, ValueError):
            relevance.append(1 if "relevant" in raw.lower() and "irrelevant" not in raw.lower() else 0)

    # Compute weighted precision@k (RAGAS formula)
    total_relevant = sum(relevance)
    if total_relevant == 0:
        return 0.0

    weighted_sum = 0.0
    cumulative_relevant = 0
    for k in range(len(relevance)):
        cumulative_relevant += relevance[k]
        precision_at_k = cumulative_relevant / (k + 1)
        weighted_sum += precision_at_k * relevance[k]

    score = weighted_sum / total_relevant
    return round(score, 4)


# ---------------------------------------------------------------------------
# RAGAS Metric 3: Context Recall (reference coverage)
# ---------------------------------------------------------------------------


def compute_context_recall(context, ground_truth):
    """Compute context recall: fraction of ground truth claims covered by context.

    Score = covered_claims / total_ground_truth_claims
    """
    if not context or not ground_truth:
        return -1.0

    # Decompose ground truth into claims
    gt_claims = _decompose_claims(ground_truth)
    if not gt_claims:
        return -1.0

    # Verify which ground truth claims are covered by the retrieved context
    system = (
        "You are a coverage judge. For each claim from a reference answer, determine "
        "whether the provided context COVERS it (the context contains information that "
        "supports or addresses the claim). Return a JSON array of objects with keys "
        '"claim" and "covered" (boolean true/false).'
    )
    claims_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(gt_claims))
    user = (
        f"Retrieved context:\n{context}\n\n"
        f"Reference claims to check:\n{claims_text}\n\n"
        f"Return ONLY a JSON array of objects, nothing else."
    )
    raw = call_haiku(system, user, max_tokens=2048)
    try:
        verdicts = _parse_json_response(raw)
        if isinstance(verdicts, list):
            covered = sum(
                1 for v in verdicts
                if isinstance(v, dict) and v.get("covered") is True
            )
            return round(covered / len(gt_claims), 4) if gt_claims else -1.0
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: count "true" occurrences
    covered = raw.lower().count('"covered": true') + raw.lower().count('"covered":true')
    total = len(gt_claims)
    return round(covered / total, 4) if total > 0 else -1.0


# ---------------------------------------------------------------------------
# RAGAS Metric 4: Answer Relevance (synthetic question back-translation)
# ---------------------------------------------------------------------------


def compute_answer_relevance(query, answer, n_synth=3):
    """Compute answer relevance per RAGAS definition.

    Method: generate N synthetic questions from the answer, embed each and the
    original query, average cosine-sim. Higher = answer directly addresses query.
    """
    if not query or not answer:
        return -1.0
    system = (
        "Given an answer, generate alternative questions that the answer fully addresses. "
        "Output ONLY a JSON array of strings — each a standalone question."
    )
    user = (
        f"Answer:\n{answer[:1500]}\n\n"
        f"Produce {n_synth} distinct questions this answer would respond to. "
        "Return ONLY a JSON array, no prose."
    )
    raw = call_haiku(system, user, max_tokens=600)
    try:
        synth_qs = _parse_json_response(raw)
        if not isinstance(synth_qs, list):
            return -1.0
        synth_qs = [q for q in synth_qs if isinstance(q, str) and q.strip()][:n_synth]
    except (json.JSONDecodeError, ValueError):
        return -1.0
    if not synth_qs:
        return -1.0

    # Embed original query + each synthetic question (all as QUERIES)
    q_vec = _get_embedding(query, is_query=True)
    if q_vec is None:
        return -1.0
    sims = []
    for sq in synth_qs:
        sv = _get_embedding(sq, is_query=True)
        if sv is None:
            continue
        sims.append(_cosine_similarity(q_vec, sv))
    if not sims:
        return -1.0
    return round(sum(sims) / len(sims), 4)


# ---------------------------------------------------------------------------
# Context retrieval (via kb-semantic-search.py or direct DB query)
# ---------------------------------------------------------------------------


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


def _get_embedding(text, is_query=True):
    """Get embedding vector from Ollama (nomic-embed-text).

    G7: asymmetric embedding — queries use search_query: prefix, docs use search_document:.
    num_ctx=2048 prevents CPU-spill under the 64k global OLLAMA_CONTEXT_LENGTH.
    """
    prefix = "search_query: " if is_query else "search_document: "
    payload = json.dumps({
        "model": EMBED_MODEL,
        "input": f"{prefix}{text}",
        "options": {"num_ctx": 2048},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            _record_local_usage(EMBED_MODEL, data.get("prompt_eval_count", 0))
            return data["embeddings"][0]
    except Exception as exc:
        print(f"[embed] Ollama unavailable: {exc}", file=sys.stderr)
        return None


def _cosine_similarity(a, b):
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_context(query, limit=5):
    """Retrieve context chunks for a query from incident_knowledge.

    Uses Ollama embeddings for semantic search against the stored embeddings.
    Falls back to keyword search if Ollama is unavailable.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query_vec = _get_embedding(query)

    if query_vec:
        # Semantic search
        rows = conn.execute(
            "SELECT * FROM incident_knowledge "
            "WHERE embedding IS NOT NULL AND embedding != '' "
            "AND (valid_until IS NULL OR valid_until > datetime('now'))"
        ).fetchall()

        scored = []
        for row in rows:
            try:
                row_vec = json.loads(row["embedding"])
                sim = _cosine_similarity(query_vec, row_vec)
                scored.append((sim, row))
            except (json.JSONDecodeError, TypeError):
                continue

        scored.sort(key=lambda x: x[0], reverse=True)
        results = scored[:limit]
    else:
        # Keyword fallback
        terms = query.split()
        conditions = " OR ".join(
            "alert_rule LIKE ? OR hostname LIKE ? OR root_cause LIKE ? OR resolution LIKE ?"
            for _ in terms
        )
        params = []
        for term in terms:
            pattern = f"%{term}%"
            params.extend([pattern] * 4)

        rows = conn.execute(
            f"SELECT * FROM incident_knowledge WHERE ({conditions}) "
            "AND (valid_until IS NULL OR valid_until > datetime('now')) "
            "ORDER BY confidence DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        results = [(0.5, row) for row in rows]

    conn.close()

    chunks = []
    for sim, row in results:
        chunk = (
            f"Alert: {row['alert_rule']} | Host: {row['hostname']} | "
            f"Site: {row['site']} | "
            f"Root cause: {row['root_cause']} | "
            f"Resolution: {row['resolution']} | "
            f"Confidence: {row['confidence']} | "
            f"Tags: {row['tags']}"
        )
        chunks.append(chunk)

    return chunks


# ---------------------------------------------------------------------------
# Database: ragas_evaluation table
# ---------------------------------------------------------------------------


def ensure_table(conn):
    """Create the ragas_evaluation table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ragas_evaluation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            retrieved_docs TEXT DEFAULT '[]',
            answer TEXT DEFAULT '',
            ground_truth TEXT DEFAULT '',
            faithfulness REAL DEFAULT -1,
            context_precision REAL DEFAULT -1,
            context_recall REAL DEFAULT -1,
            answer_relevance REAL DEFAULT -1,
            semantic_quality REAL DEFAULT -1,
            num_retrieved INTEGER DEFAULT 0,
            eval_model TEXT DEFAULT 'claude-haiku-4-5-20251001',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            issue_id TEXT DEFAULT ''
        )
    """)
    conn.commit()


def store_result(conn, query, retrieved_docs, answer, ground_truth,
                 faithfulness, context_precision, context_recall,
                 num_retrieved, issue_id="", answer_relevance=-1.0):
    """Insert an evaluation result into the ragas_evaluation table."""
    conn.execute(
        "INSERT INTO ragas_evaluation "
        "(query, retrieved_docs, answer, ground_truth, faithfulness, "
        "context_precision, context_recall, answer_relevance, num_retrieved, eval_model, issue_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            query,
            json.dumps(retrieved_docs, ensure_ascii=False),
            answer,
            ground_truth,
            faithfulness,
            context_precision,
            context_recall,
            answer_relevance,
            num_retrieved,
            EVAL_MODEL,
            issue_id,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# CLI: evaluate
# ---------------------------------------------------------------------------


def cmd_evaluate(query, answer, context, ground_truth, issue_id=""):
    """Run all RAGAS metrics on a single Q&A pair and store results."""
    # Split context into chunks for precision@k (if it's a single block, split on double newline)
    if isinstance(context, str):
        context_chunks = [c.strip() for c in context.split("\n\n") if c.strip()]
        if not context_chunks:
            context_chunks = [context] if context else []
    elif isinstance(context, list):
        context_chunks = context
    else:
        context_chunks = []

    full_context = "\n\n".join(context_chunks)
    num_retrieved = len(context_chunks)

    print(f"Evaluating query: {query[:80]}...")
    print(f"  Context chunks: {num_retrieved}")

    # Metric 1: Faithfulness
    print("  Computing faithfulness...", end=" ", flush=True)
    faithfulness = compute_faithfulness(answer, full_context)
    print(f"{faithfulness:.4f}" if faithfulness >= 0 else "N/A")

    # Metric 2: Context Precision
    print("  Computing context precision...", end=" ", flush=True)
    ctx_precision = compute_context_precision(query, context_chunks, ground_truth)
    print(f"{ctx_precision:.4f}" if ctx_precision >= 0 else "N/A")

    # Metric 3: Context Recall
    print("  Computing context recall...", end=" ", flush=True)
    ctx_recall = compute_context_recall(full_context, ground_truth)
    print(f"{ctx_recall:.4f}" if ctx_recall >= 0 else "N/A")

    # Metric 4: Answer Relevance
    print("  Computing answer relevance...", end=" ", flush=True)
    ans_relevance = compute_answer_relevance(query, answer)
    print(f"{ans_relevance:.4f}" if ans_relevance >= 0 else "N/A")

    # Store results
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)
    store_result(
        conn, query, context_chunks, answer, ground_truth,
        faithfulness, ctx_precision, ctx_recall,
        num_retrieved, issue_id, answer_relevance=ans_relevance,
    )
    conn.close()

    print(f"\nResults stored in ragas_evaluation table.")
    print(f"  Faithfulness:       {faithfulness:.4f}" if faithfulness >= 0 else "  Faithfulness:       N/A")
    print(f"  Context Precision:  {ctx_precision:.4f}" if ctx_precision >= 0 else "  Context Precision:  N/A")
    print(f"  Context Recall:     {ctx_recall:.4f}" if ctx_recall >= 0 else "  Context Recall:     N/A")
    print(f"  Answer Relevance:   {ans_relevance:.4f}" if ans_relevance >= 0 else "  Answer Relevance:   N/A")

    return {
        "faithfulness": faithfulness,
        "context_precision": ctx_precision,
        "context_recall": ctx_recall,
        "answer_relevance": ans_relevance,
    }


# ---------------------------------------------------------------------------
# CLI: golden-set
# ---------------------------------------------------------------------------


def cmd_golden_set():
    """Extract 50 Q&A pairs from incident_knowledge with confidence >= 0.7.

    Generates synthetic questions from alert_rule + hostname + root_cause,
    uses resolution as the ground truth answer.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, alert_rule, hostname, site, root_cause, resolution, "
        "confidence, tags, issue_id "
        "FROM incident_knowledge "
        "WHERE confidence >= 0.7 "
        "AND resolution IS NOT NULL AND resolution != '' "
        "AND root_cause IS NOT NULL AND root_cause != '' "
        "ORDER BY confidence DESC, id DESC "
        "LIMIT 50"
    ).fetchall()
    conn.close()

    if not rows:
        print("ERROR: No incident_knowledge rows with confidence >= 0.7", file=sys.stderr)
        sys.exit(1)

    golden_set = []
    for row in rows:
        # Synthesize a question from the alert context
        parts = []
        if row["alert_rule"]:
            parts.append(row["alert_rule"])
        if row["hostname"]:
            parts.append(f"on {row['hostname']}")
        if row["site"]:
            parts.append(f"at site {row['site']}")

        question = f"How do I resolve: {' '.join(parts)}?"
        if row["root_cause"]:
            question += f" Root cause: {row['root_cause'][:200]}"

        entry = {
            "id": row["id"],
            "query": question,
            "ground_truth": row["resolution"],
            "hostname": row["hostname"] or "",
            "alert_rule": row["alert_rule"] or "",
            "confidence": row["confidence"],
            "issue_id": row["issue_id"] or "",
            "tags": row["tags"] or "",
        }
        golden_set.append(entry)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(GOLDEN_SET_PATH), exist_ok=True)

    with open(GOLDEN_SET_PATH, "w") as fh:
        json.dump(golden_set, fh, indent=2, ensure_ascii=False)

    print(f"Golden set saved: {GOLDEN_SET_PATH}")
    print(f"  Entries: {len(golden_set)}")
    print(f"  Confidence range: {golden_set[-1]['confidence']:.2f} - {golden_set[0]['confidence']:.2f}")
    return golden_set


# ---------------------------------------------------------------------------
# CLI: run-golden
# ---------------------------------------------------------------------------


def cmd_run_golden(limit=0, only_category=None):
    """Evaluate all golden set queries: retrieve context, run metrics, store results.

    limit: if >0, process only the first N entries (post-filter).
    only_category: if set (e.g. 'hard-eval', 'multi-hop'), keep only entries
                   whose tags field contains that category token.
    """
    if not os.path.isfile(GOLDEN_SET_PATH):
        print(f"ERROR: Golden set not found at {GOLDEN_SET_PATH}", file=sys.stderr)
        print("Run 'ragas-eval.py golden-set' first.", file=sys.stderr)
        sys.exit(1)

    with open(GOLDEN_SET_PATH, "r") as fh:
        golden_set = json.load(fh)

    if only_category:
        wanted = only_category.lower()
        golden_set = [e for e in golden_set
                      if any(t.strip().lower() == wanted
                             for t in e.get("tags", "").split(","))]
        print(f"Filtered to category '{only_category}': {len(golden_set)} entries")

    if limit and limit > 0:
        golden_set = golden_set[:limit]
        print(f"Limited to first {limit} entries")

    print(f"Running RAGAS evaluation on {len(golden_set)} golden set entries")
    print(f"Model: {EVAL_MODEL}")
    print("-" * 70)

    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)

    results = []
    failed = 0

    for i, entry in enumerate(golden_set):
        query = entry["query"]
        ground_truth = entry["ground_truth"]
        issue_id = entry.get("issue_id", "")

        print(f"\n[{i+1}/{len(golden_set)}] {query[:70]}...")

        try:
            # Retrieve context via semantic search
            context_chunks = retrieve_context(query, limit=5)

            if not context_chunks:
                print("  WARNING: No context retrieved, skipping")
                failed += 1
                continue

            full_context = "\n\n".join(context_chunks)
            num_retrieved = len(context_chunks)

            # Simulate an answer (the ground truth IS the expected answer;
            # for faithfulness we use it as the "system's answer" since we are
            # evaluating the RAG pipeline's ability to support correct answers)
            answer = ground_truth

            # Compute metrics
            print("  Faithfulness...", end=" ", flush=True)
            faithfulness = compute_faithfulness(answer, full_context)
            print(f"{faithfulness:.4f}" if faithfulness >= 0 else "N/A", end=" | ")

            print("Precision...", end=" ", flush=True)
            ctx_precision = compute_context_precision(query, context_chunks, ground_truth)
            print(f"{ctx_precision:.4f}" if ctx_precision >= 0 else "N/A", end=" | ")

            print("Recall...", end=" ", flush=True)
            ctx_recall = compute_context_recall(full_context, ground_truth)
            print(f"{ctx_recall:.4f}" if ctx_recall >= 0 else "N/A", end=" | ")

            print("AnsRel...", end=" ", flush=True)
            ans_rel = compute_answer_relevance(query, answer)
            print(f"{ans_rel:.4f}" if ans_rel >= 0 else "N/A")

            # Store
            store_result(
                conn, query, context_chunks, answer, ground_truth,
                faithfulness, ctx_precision, ctx_recall,
                num_retrieved, issue_id, answer_relevance=ans_rel,
            )

            results.append({
                "faithfulness": faithfulness,
                "context_precision": ctx_precision,
                "context_recall": ctx_recall,
                "answer_relevance": ans_rel,
            })

            # Rate limiting: small delay between entries to avoid API throttling
            time.sleep(0.5)

        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            failed += 1
            continue

    conn.close()

    # Summary
    print("\n" + "=" * 70)
    print("GOLDEN SET EVALUATION COMPLETE")
    print(f"  Evaluated: {len(results)}/{len(golden_set)}")
    print(f"  Failed:    {failed}")

    if results:
        def _avg(key):
            vals = [r[key] for r in results if r[key] >= 0]
            return sum(vals) / len(vals) if vals else -1.0

        avg_faith = _avg("faithfulness")
        avg_prec = _avg("context_precision")
        avg_recall = _avg("context_recall")
        avg_ansrel = _avg("answer_relevance")

        print(f"\n  Avg Faithfulness:       {avg_faith:.4f}" if avg_faith >= 0 else "\n  Avg Faithfulness:       N/A")
        print(f"  Avg Context Precision:  {avg_prec:.4f}" if avg_prec >= 0 else "  Avg Context Precision:  N/A")
        print(f"  Avg Context Recall:     {avg_recall:.4f}" if avg_recall >= 0 else "  Avg Context Recall:     N/A")
        print(f"  Avg Answer Relevance:   {avg_ansrel:.4f}" if avg_ansrel >= 0 else "  Avg Answer Relevance:   N/A")

        # Quality gate
        threshold = 0.80
        below = sum(1 for r in results if 0 <= r["faithfulness"] < threshold)
        if below > 0:
            print(f"\n  WARNING: {below} entries below faithfulness threshold ({threshold})")


# ---------------------------------------------------------------------------
# CLI: summary
# ---------------------------------------------------------------------------


def cmd_summary():
    """Print aggregate scores from the ragas_evaluation table."""
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)

    # Total count
    total = conn.execute("SELECT COUNT(*) FROM ragas_evaluation").fetchone()[0]
    if total == 0:
        print("No evaluation results found. Run 'ragas-eval.py run-golden' first.")
        conn.close()
        return

    # 7-day counts and averages
    row_7d = conn.execute("""
        SELECT
            COUNT(*) as cnt,
            AVG(CASE WHEN faithfulness >= 0 THEN faithfulness END) as avg_faith,
            AVG(CASE WHEN context_precision >= 0 THEN context_precision END) as avg_prec,
            AVG(CASE WHEN context_recall >= 0 THEN context_recall END) as avg_recall,
            MIN(CASE WHEN faithfulness >= 0 THEN faithfulness END) as min_faith,
            MAX(CASE WHEN faithfulness >= 0 THEN faithfulness END) as max_faith,
            SUM(CASE WHEN faithfulness >= 0 AND faithfulness < 0.80 THEN 1 ELSE 0 END) as below_thresh
        FROM ragas_evaluation
        WHERE created_at > datetime('now', '-7 days')
    """).fetchone()

    # All-time averages
    row_all = conn.execute("""
        SELECT
            AVG(CASE WHEN faithfulness >= 0 THEN faithfulness END) as avg_faith,
            AVG(CASE WHEN context_precision >= 0 THEN context_precision END) as avg_prec,
            AVG(CASE WHEN context_recall >= 0 THEN context_recall END) as avg_recall
        FROM ragas_evaluation
    """).fetchone()

    # Per-model breakdown
    model_rows = conn.execute("""
        SELECT
            eval_model,
            COUNT(*) as cnt,
            AVG(CASE WHEN faithfulness >= 0 THEN faithfulness END) as avg_faith,
            AVG(CASE WHEN context_precision >= 0 THEN context_precision END) as avg_prec,
            AVG(CASE WHEN context_recall >= 0 THEN context_recall END) as avg_recall
        FROM ragas_evaluation
        GROUP BY eval_model
    """).fetchall()

    # Latest 5 results
    recent = conn.execute("""
        SELECT query, faithfulness, context_precision, context_recall, created_at
        FROM ragas_evaluation
        ORDER BY id DESC LIMIT 5
    """).fetchall()

    conn.close()

    # Print report
    print("=" * 70)
    print("RAGAS EVALUATION SUMMARY")
    print("=" * 70)

    print(f"\nTotal evaluations: {total}")
    print(f"Last 7 days:       {row_7d[0]}")

    print(f"\n{'Metric':<25} {'7-day Avg':>10} {'All-time Avg':>13}")
    print("-" * 50)

    def _fmt(val):
        return f"{val:.4f}" if val is not None and val >= 0 else "N/A"

    print(f"{'Faithfulness':<25} {_fmt(row_7d[1]):>10} {_fmt(row_all[0]):>13}")
    print(f"{'Context Precision':<25} {_fmt(row_7d[2]):>10} {_fmt(row_all[1]):>13}")
    print(f"{'Context Recall':<25} {_fmt(row_7d[3]):>10} {_fmt(row_all[2]):>13}")

    if row_7d[0] > 0:
        print(f"\n7-day faithfulness range: {_fmt(row_7d[4])} - {_fmt(row_7d[5])}")
        print(f"Below 0.80 threshold:     {row_7d[6] or 0}")

    if len(model_rows) > 1:
        print(f"\nPer-model breakdown:")
        for mr in model_rows:
            print(f"  {mr[0]}: n={mr[1]}, faith={_fmt(mr[2])}, prec={_fmt(mr[3])}, recall={_fmt(mr[4])}")

    if recent:
        print(f"\nLatest 5 evaluations:")
        for r in recent:
            q_short = r[0][:50] + "..." if len(r[0]) > 50 else r[0]
            print(f"  [{r[4]}] F={_fmt(r[1])} P={_fmt(r[2])} R={_fmt(r[3])} -- {q_short}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="RAGAS evaluation pipeline for claude-gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="Subcommand")

    # evaluate
    p_eval = sub.add_parser("evaluate", help="Evaluate a single Q&A pair")
    p_eval.add_argument("--query", "-q", required=True, help="The question/query")
    p_eval.add_argument("--answer", "-a", required=True, help="The system's answer")
    p_eval.add_argument("--context", "-c", required=True, help="Retrieved context (double-newline separated chunks)")
    p_eval.add_argument("--ground-truth", "-g", required=True, help="Expected correct answer")
    p_eval.add_argument("--issue-id", default="", help="Optional issue ID")

    # golden-set
    sub.add_parser("golden-set", help="Extract golden Q&A set from incident_knowledge")

    # run-golden
    p_run = sub.add_parser("run-golden", help="Run evaluation on golden set")
    p_run.add_argument("--limit", type=int, default=0,
                       help="Process only the first N entries (after --only-category filter)")
    p_run.add_argument("--only-category", default=None,
                       help="Filter to entries tagged with this category (e.g. 'hard-eval', 'multi-hop', 'temporal')")

    # summary
    sub.add_parser("summary", help="Print aggregate evaluation scores")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "evaluate":
        cmd_evaluate(args.query, args.answer, args.context, args.ground_truth, args.issue_id)
    elif args.command == "golden-set":
        cmd_golden_set()
    elif args.command == "run-golden":
        cmd_run_golden(limit=args.limit, only_category=args.only_category)
    elif args.command == "summary":
        cmd_summary()


if __name__ == "__main__":
    main()
