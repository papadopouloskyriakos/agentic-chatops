#!/usr/bin/env python3
"""G4: Document reasoning chains — Map-Reduce and Refinement.

Handles long documents (YT threads, playbooks, session transcripts) that exceed
a single LLM context window. Pure stdlib + Ollama.

Usage:
  doc-chain.py map-reduce --input file.md [--query "optional question"]
  doc-chain.py refine --input file.md [--running-summary "seed text"]
  doc-chain.py --stdin --mode map-reduce --query "..."

Cost: tier-0 (local GPU) for map/refine stage via qwen3:4b.
      tier-2 (Haiku) for the reducer if --reducer=haiku is set (default qwen3:4b).
"""
import sys
import os
import json
import sqlite3
import urllib.request
import argparse
import time
import concurrent.futures
from typing import Optional

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
MAP_MODEL = os.environ.get("DOCCHAIN_MAP_MODEL", "qwen2.5:7b")
REDUCE_MODEL = os.environ.get("DOCCHAIN_REDUCE_MODEL", "qwen2.5:7b")

CHUNK_SIZE = 1400   # chars per chunk — ~350 tokens, leaves room for prompt + output
MAX_CHUNKS = 16     # safety cap to avoid runaway cost
MAP_WORKERS = 4     # parallel chunks against single GPU


def _record_local_usage(model, input_tokens, output_tokens=0):
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


def _ollama_generate(model, prompt, num_predict=600, temperature=0.2):
    """Generate text. Handles qwen3 thinking-mode bug by reading thinking field."""
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            _record_local_usage(model, data.get("prompt_eval_count", 0), data.get("eval_count", 0))
            text = (data.get("response", "") or data.get("thinking", "")).strip()
            if "<think>" in text:
                text = text.split("</think>")[-1].strip()
            return text
    except Exception as e:
        print(f"[docchain] {model} error: {e}", file=sys.stderr)
        return ""


def chunk_text(text, chunk_size=CHUNK_SIZE):
    """Split on paragraph boundaries, respecting chunk_size."""
    paragraphs = text.split("\n\n")
    chunks, cur = [], []
    cur_len = 0
    for p in paragraphs:
        if cur_len + len(p) > chunk_size and cur:
            chunks.append("\n\n".join(cur))
            cur, cur_len = [p], len(p)
        else:
            cur.append(p)
            cur_len += len(p) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks[:MAX_CHUNKS]


def map_chunk(chunk, query=None):
    """Map step: extract useful info from one chunk."""
    if query:
        prompt = (
            f"Extract from this text anything relevant to: {query}\n"
            "Keep technical details (hostnames, command names, CVEs, dates) verbatim.\n"
            "Respond with at least one relevant fact. If truly nothing relevant, say 'no-relevant-info'.\n\n"
            f"--- TEXT ---\n{chunk}\n\n--- RELEVANT FACTS ---"
        )
    else:
        prompt = (
            "Summarize the key technical facts from this text in <=5 bullet points.\n"
            "Keep hostnames, command names, dates, and CVE IDs verbatim.\n\n"
            f"--- TEXT ---\n{chunk}\n\n--- KEY FACTS ---"
        )
    return _ollama_generate(MAP_MODEL, prompt, num_predict=400, temperature=0.1)


def reduce_summaries(summaries, query=None):
    """Reduce step: combine per-chunk summaries into one final answer."""
    joined = "\n\n---\n\n".join(
        f"Chunk {i+1}:\n{s}" for i, s in enumerate(summaries)
        if s and "no-relevant-info" not in s.lower() and "NO_MATCH" not in s
    )
    if not joined:
        return "[No relevant information found across chunks]"
    if query:
        prompt = (
            f"Question: {query}\n\n"
            "You have per-chunk excerpts. Produce a single consolidated answer.\n"
            "Cite which chunk(s) each fact came from. Be concise and technical.\n\n"
            f"--- PER-CHUNK EXCERPTS ---\n{joined}\n\n--- CONSOLIDATED ANSWER ---"
        )
    else:
        prompt = (
            "You have per-chunk summaries of a long document. Merge them into a single "
            "coherent summary under 400 words. Dedupe repeated facts.\n\n"
            f"--- PER-CHUNK SUMMARIES ---\n{joined}\n\n--- FINAL SUMMARY ---"
        )
    return _ollama_generate(REDUCE_MODEL, prompt, num_predict=700, temperature=0.2)


def map_reduce(text, query=None):
    """G4 Map-Reduce chain."""
    chunks = chunk_text(text)
    t0 = time.time()
    print(f"[map-reduce] {len(chunks)} chunks, query={'yes' if query else 'no'}", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAP_WORKERS) as ex:
        summaries = list(ex.map(lambda c: map_chunk(c, query), chunks))
    t_map = time.time() - t0
    final = reduce_summaries(summaries, query)
    t_total = time.time() - t0
    print(f"[map-reduce] map={t_map:.1f}s total={t_total:.1f}s", file=sys.stderr)
    return final


def refine_chain(text, running_summary=""):
    """G4 Refinement chain: iteratively update a running summary over chunks.

    Unlike map-reduce, refinement carries running state — useful when later context
    should refine or correct earlier summary.
    """
    chunks = chunk_text(text)
    t0 = time.time()
    print(f"[refine] {len(chunks)} chunks", file=sys.stderr)
    summary = running_summary
    for i, chunk in enumerate(chunks):
        if not summary:
            prompt = (
                "Summarize the following in <=3 technical bullet points.\n\n"
                f"{chunk}\n\n--- SUMMARY ---"
            )
        else:
            prompt = (
                "You have a running summary of a long document. Given new context, "
                "REFINE the summary — correct any wrong claims, merge overlapping facts, "
                "add new info. Keep <=5 technical bullets.\n\n"
                f"--- CURRENT SUMMARY ---\n{summary}\n\n"
                f"--- NEW CONTEXT ---\n{chunk}\n\n--- REFINED SUMMARY ---"
            )
        summary = _ollama_generate(MAP_MODEL, prompt, num_predict=400, temperature=0.2)
        print(f"[refine] chunk {i+1}/{len(chunks)} done", file=sys.stderr)
    t_total = time.time() - t0
    print(f"[refine] total={t_total:.1f}s", file=sys.stderr)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Document reasoning chains")
    parser.add_argument("mode", choices=["map-reduce", "refine"], help="chain mode")
    parser.add_argument("--input", help="input file path")
    parser.add_argument("--stdin", action="store_true", help="read from stdin")
    parser.add_argument("--query", default=None, help="optional question for map-reduce")
    parser.add_argument("--running-summary", default="", help="seed for refine chain")
    args = parser.parse_args()

    if args.stdin:
        text = sys.stdin.read()
    elif args.input:
        with open(args.input) as f:
            text = f.read()
    else:
        print("Provide --input or --stdin", file=sys.stderr)
        sys.exit(1)

    if args.mode == "map-reduce":
        print(map_reduce(text, query=args.query))
    else:
        print(refine_chain(text, running_summary=args.running_summary))


if __name__ == "__main__":
    main()
