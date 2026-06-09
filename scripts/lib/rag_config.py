"""Centralized RAG pipeline configuration.

Single source of truth for constants that were previously scattered across
kb-semantic-search.py, kb-latency-probe.py, and the refresh-* scripts.
Every value is env-overridable so tests and alternate deployments can tune
without forking code.

Import pattern:
    from rag_config import (
        EMBED_TABLES, RERANK_API_URL,
        MIGRATION_SCALE_THRESHOLD, MIGRATION_LATENCY_THRESHOLD,
        NUM_CTX_TINY, NUM_CTX_SMALL, NUM_CTX_MED,
        PROBE_QUERIES,
    )
"""
import os

# ── Tables holding embeddings (text, embedding) for the 4-signal RRF ────
# Used by kb-semantic-search.py (signal sources) + kb-latency-probe.py
# (kb_embedded_rows per-table gauge).
EMBED_TABLES = (
    "incident_knowledge",
    "wiki_articles",
    "session_transcripts",
    "chaos_experiments",
)

# ── Services ───────────────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
RERANK_API_URL = os.environ.get("RERANK_API_URL", "http://nl-gpu01:11436")

# ── G6 FAISS migration triggers ─────────────────────────────────────────
# Migrate when either bucket reaches 1.0.
# Scale: corpus size where SQLite linear scan gets painful (~25k embeddings).
# Latency: p95 threshold after which the cost of synth swaps becomes
# indistinguishable from real retrieval pressure. Rebaselined 2026-04-18
# post-L02 Haiku synth swap (baseline shifted from 5s to ~9s).
MIGRATION_SCALE_THRESHOLD = int(os.environ.get("MIGRATION_SCALE_THRESHOLD", "25000"))
MIGRATION_LATENCY_THRESHOLD = float(os.environ.get("MIGRATION_LATENCY_THRESHOLD", "15.0"))

# ── Ollama num_ctx (prevent CPU-spill under global OLLAMA_CONTEXT_LENGTH) ─
# Always pass per-request num_ctx to Ollama; the global default (64k) forces
# even 1B models to spill to CPU. See feedback_ollama_num_ctx_vram memory.
NUM_CTX_TINY = int(os.environ.get("NUM_CTX_TINY", "1024"))    # llama3.2:1b variants
NUM_CTX_SMALL = int(os.environ.get("NUM_CTX_SMALL", "2048"))  # rerank/qwen fallback
NUM_CTX_MED = int(os.environ.get("NUM_CTX_MED", "8192"))      # synth qwen

# ── Latency probe queries ───────────────────────────────────────────────
# 5 representative queries covering the high-semantic-match early-exit
# path (3) and full-fusion path (2). Used by kb-latency-probe cron */5
# to emit kb_retrieval_latency_seconds{quantile=...}.
#
# IFRNLLEI01PRD-703: split into two cohorts.
#   PROBE_QUERIES_REAL  — production-representative (have corpus matches).
#                         Alerts key off this cohort.
#   PROBE_QUERIES_NOVEL — deliberate stress test (no corpus match). Tracked
#                         as kb_retrieval_latency_seconds{category="novel"}
#                         for quality monitoring but NOT alerted on — novel
#                         queries are forced into RAG-fusion + rerank + synth
#                         fallback which is inherently 15-20s. Alerting on
#                         their p95 conflated corpus-coverage signal with
#                         production-latency signal.
# PROBE_QUERIES is kept as the union for back-compat with any external
# consumer; new code should use the split variables.
PROBE_QUERIES_REAL = (
    "pve01 memory apiserver",
    "freedom ISP tunnel outage",
    "GR isolation VTI",
)
PROBE_QUERIES_NOVEL = (
    "novel query about ARP cache poisoning",
    "unknown subject Layer 7 DDoS mitigation",
)
PROBE_QUERIES = PROBE_QUERIES_REAL + PROBE_QUERIES_NOVEL

# ── Haiku synth (Anthropic API) ─────────────────────────────────────────
# Pricing kept here so cost recording logic stays in one place.
SYNTH_HAIKU_MODEL = os.environ.get("SYNTH_HAIKU_MODEL", "claude-haiku-4-5-20251001")
SYNTH_HAIKU_COST_PER_M_INPUT = 1.0   # USD per million input tokens
SYNTH_HAIKU_COST_PER_M_OUTPUT = 5.0  # USD per million output tokens
