#!/usr/bin/env python3
"""Run hard retrieval + KG eval sets.

Metrics:
  - retrieval hit@5: fraction of queries where ANY must_retrieve_any_of substring appears in top-5 results
  - retrieval precision@5: fraction of top-5 that match any must_retrieve substring
  - adversarial avoidance: fraction of queries that do NOT return any adversarial_near_misses in top-3
  - KG coverage@5: fraction of KG queries whose top results include expected_name_substrings

Output: JSON summary + per-query diagnostic.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import concurrent.futures

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KB = os.path.join(SCRIPT_DIR, "kb-semantic-search.py")
EVAL_DIR = os.path.join(SCRIPT_DIR, "eval-sets")
REPO_DIR = os.path.dirname(SCRIPT_DIR)

# LLM judge config
# JUDGE_BACKEND default is 'local' — uses gemma3:12b on gpu01 Ollama (benchmarked
# 100% agreement with Haiku on 10-query eval, ~0.3s slower p50). Set
# JUDGE_BACKEND=haiku to route to Anthropic API (costs ~$0.001/call, matches
# pre-2026-04-19 behavior).
JUDGE_MODEL = "claude-haiku-4-5-20251001"  # only used when JUDGE_BACKEND=haiku
JUDGE_ENABLED = os.environ.get("JUDGE_ENABLED", "1") == "1"
JUDGE_BACKEND = os.environ.get("JUDGE_BACKEND", "local")  # local | haiku
JUDGE_LOCAL_MODEL = os.environ.get("JUDGE_LOCAL_MODEL", "gemma3:12b")
JUDGE_LOCAL_FALLBACK = os.environ.get("JUDGE_LOCAL_FALLBACK", "qwen2.5:7b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")


def _load_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(REPO_DIR, ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _judge_local(model, system, user):
    """Ollama /api/generate judge call. Returns (dt_seconds, parsed_dict)."""
    body = json.dumps({
        "model": model,
        "prompt": f"{system}\n\n{user}",
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": 400, "num_ctx": 2048},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    dt = time.time() - t0
    return dt, data.get("response", "").strip()


def judge_hit(query, ground_truth, retrieved_rows):
    """Judge whether any retrieved row addresses the ground truth.

    Backend selected by JUDGE_BACKEND env:
      local (default) -> gemma3:12b via Ollama, fallback qwen2.5:7b on hard failure
      haiku           -> Anthropic API (legacy, kept for opt-in parity)

    Returns (hit: bool, coverage_count: int, rationale: str).
    """
    if not retrieved_rows:
        return False, 0, ""
    docs_block = "\n".join(f"[{i+1}] {r[:280]}" for i, r in enumerate(retrieved_rows[:5]))
    system = (
        "You judge whether retrieved documents are relevant to an infrastructure query. "
        "A document is RELEVANT if it addresses the ground-truth fact even when phrased "
        "differently, uses related hostnames/concepts, or provides partial evidence. "
        "Output ONLY a JSON object: "
        '{"any_relevant": true|false, "relevant_indices": [1-5], "rationale": "one short sentence"}'
    )
    user = (
        f"Query:\n{query}\n\n"
        f"Ground truth (what a good answer requires):\n{ground_truth}\n\n"
        f"Retrieved documents (top-5):\n{docs_block}\n\n"
        "Return ONLY the JSON."
    )

    # Local path: gemma3:12b primary -> qwen2.5:7b fallback. No Anthropic call.
    if JUDGE_BACKEND == "local":
        for model in (JUDGE_LOCAL_MODEL, JUDGE_LOCAL_FALLBACK):
            try:
                _, text = _judge_local(model, system, user)
                verdict = json.loads(text)
                return (bool(verdict.get("any_relevant")),
                        len(verdict.get("relevant_indices", [])),
                        verdict.get("rationale", ""))
            except Exception as e:
                print(f"[judge:{model}] {type(e).__name__}: {e}", file=sys.stderr)
                continue
        return False, 0, ""

    # Legacy Haiku path (JUDGE_BACKEND=haiku)
    key = _load_api_key()
    if not key:
        return False, 0, ""
    body = {
        "model": JUDGE_MODEL,
        "max_tokens": 400,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
            # E3: record Haiku judge usage in llm_usage (tier 2, actual cost)
            try:
                import sqlite3
                usage = data.get("usage", {})
                in_tok = usage.get("input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
                cost = (in_tok / 1_000_000.0) * 1.0 + (out_tok / 1_000_000.0) * 5.0
                db = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")
                conn = sqlite3.connect(db)
                conn.execute(
                    "INSERT INTO llm_usage (tier, model, input_tokens, output_tokens, cost_usd, issue_id) "
                    "VALUES (2, ?, ?, ?, ?, 'hard-eval-judge')",
                    (JUDGE_MODEL, in_tok, out_tok, round(cost, 6)),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
            text = data["content"][0]["text"].strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = "\n".join(text.split("\n")[1:])
                if text.endswith("```"):
                    text = text.rsplit("```", 1)[0]
            verdict = json.loads(text)
            hit = bool(verdict.get("any_relevant"))
            cov = len(verdict.get("relevant_indices", []))
            rat = verdict.get("rationale", "")
            return hit, cov, rat
    except Exception as e:
        print(f"[judge] {type(e).__name__}: {e}", file=sys.stderr)
        return False, 0, ""


def run_search(query, limit=5):
    t0 = time.time()
    result = subprocess.run(
        ["python3", KB, "search", query, "--limit", str(limit)],
        capture_output=True, text=True, timeout=60,
    )
    dt = time.time() - t0
    lines = [l for l in result.stdout.split("\n") if l.strip()]
    # Skip the RETRIEVAL_QUALITY header line
    rows = [l for l in lines if not l.startswith("RETRIEVAL_QUALITY:")]
    return dt, rows


def run_traverse(query):
    t0 = time.time()
    result = subprocess.run(
        ["python3", KB, "traverse", query],
        capture_output=True, text=True, timeout=60,
    )
    dt = time.time() - t0
    lines = [l for l in result.stdout.split("\n") if l.strip()]
    return dt, lines


def substr_hit(row_text, substrings):
    low = row_text.lower()
    return any(s.lower() in low for s in substrings)


def eval_retrieval(only_ids=None, verbose=False):
    # Prefer v2 (50-query) set when available
    eval_file = os.path.join(EVAL_DIR, "hard-retrieval-v2.json")
    if not os.path.exists(eval_file):
        eval_file = os.path.join(EVAL_DIR, "hard-retrieval.json")
    with open(eval_file) as f:
        queries = json.load(f)
    if only_ids:
        wanted = set(only_ids)
        queries = [q for q in queries if q["id"] in wanted]
        print(f"Filtered to {len(queries)} queries: {sorted(q['id'] for q in queries)}",
              file=sys.stderr)

    per_q = []
    substr_hit_at_5 = 0
    judge_hit_at_5 = 0
    judge_coverage_sum = 0
    prec_sum = 0.0
    adversarial_avoided = 0
    lats = []

    # E4: parallelize across queries — each worker does its own search + judge.
    # ThreadPool=8 — retrieval is I/O-bound (SSH to gpu01 + Haiku API), fits well.
    def _eval_one(q):
        dt, rows = run_search(q["query"], limit=5)
        top5 = rows[:5]
        top3 = rows[:3]
        combined_top5 = " | ".join(top5)
        combined_top3 = " | ".join(top3)
        sub_hit = substr_hit(combined_top5, q["must_retrieve_any_of"])
        precision_k = sum(1 for r in top5 if substr_hit(r, q["must_retrieve_any_of"])) / max(len(top5), 1)
        adv = substr_hit(combined_top3, q["adversarial_near_misses"])
        jhit, jcov, jrat = False, 0, ""
        if JUDGE_ENABLED:
            jhit, jcov, jrat = judge_hit(q["query"], q["ground_truth"], top5)
        if verbose:
            print(f"\n--- {q['id']} ({q.get('category','?')}) ---", file=sys.stderr)
            print(f"Q: {q['query']}", file=sys.stderr)
            print(f"must: {q['must_retrieve_any_of'][:4]}", file=sys.stderr)
            print(f"hit: substr={sub_hit} judge={jhit} (cov={jcov}/5)  adv_in_top3={adv}",
                  file=sys.stderr)
            print(f"rationale: {jrat[:120]}", file=sys.stderr)
            for i, row in enumerate(top5, 1):
                marker = "*" if substr_hit(row, q["must_retrieve_any_of"]) else " "
                print(f"  {marker} [{i}] {row[:140]}", file=sys.stderr)
        return {
            "q": q,
            "dt": dt,
            "sub_hit": sub_hit,
            "precision_k": precision_k,
            "adv": adv,
            "jhit": jhit,
            "jcov": jcov,
            "jrat": jrat,
        }

    eval_workers = int(os.environ.get("EVAL_WORKERS", "8"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=eval_workers) as ex:
        results = list(ex.map(_eval_one, queries))

    # Preserve input order (ex.map returns in-order)
    for r in results:
        q = r["q"]
        lats.append(r["dt"])
        if r["sub_hit"]:
            substr_hit_at_5 += 1
        if r["jhit"]:
            judge_hit_at_5 += 1
        judge_coverage_sum += r["jcov"]
        if not r["adv"]:
            adversarial_avoided += 1
        prec_sum += r["precision_k"]
        per_q.append({
            "id": q["id"],
            "category": q["category"],
            "query": q["query"][:80],
            "latency_s": round(r["dt"], 2),
            "substr_hit@5": r["sub_hit"],
            "judge_hit@5": r["jhit"],
            "judge_coverage@5": r["jcov"],
            "precision@5": round(r["precision_k"], 3),
            "adversarial_in_top3": r["adv"],
        })

    n = len(queries)
    return {
        "n": n,
        "substr_hit_at_5": round(substr_hit_at_5 / n, 4),
        "judge_hit_at_5": round(judge_hit_at_5 / n, 4),
        "judge_coverage_at_5_mean": round(judge_coverage_sum / (n * 5), 4),
        "precision_at_5_mean": round(prec_sum / n, 4),
        "adversarial_avoidance": round(adversarial_avoided / n, 4),
        "latency_p50": round(sorted(lats)[n // 2], 2),
        "latency_p95": round(sorted(lats)[min(int(n * 0.95), n - 1)], 2),
        "latency_mean": round(sum(lats) / n, 2),
        "per_query": per_q,
    }


def eval_kg():
    with open(os.path.join(EVAL_DIR, "hard-kg.json")) as f:
        queries = json.load(f)

    per_q = []
    substr_coverage = 0
    judge_coverage = 0
    min_results_hit = 0
    lats = []

    for q in queries:
        dt, lines = run_traverse(q["query"])
        lats.append(dt)
        combined = " | ".join(lines)
        sub_hit = substr_hit(combined, q["expected_name_substrings"])
        if sub_hit:
            substr_coverage += 1

        # LLM-judge: did traversal find anything relevant?
        jhit = False
        if JUDGE_ENABLED:
            gt = f"Expected entity names containing any of: {', '.join(q['expected_name_substrings'])}"
            jhit, _, _ = judge_hit(q["query"], gt, lines[:5])
        if jhit:
            judge_coverage += 1

        result_count = sum(1 for l in lines if l.startswith("[depth="))
        if result_count >= q["min_results"]:
            min_results_hit += 1

        per_q.append({
            "id": q["id"],
            "query": q["query"][:80],
            "latency_s": round(dt, 2),
            "substr_coverage": sub_hit,
            "judge_coverage": jhit,
            "result_count": result_count,
            "min_results_met": result_count >= q["min_results"],
        })

    n = len(queries)
    return {
        "n": n,
        "substr_coverage_at_5": round(substr_coverage / n, 4),
        "judge_coverage_at_5": round(judge_coverage / n, 4),
        "min_results_met": round(min_results_hit / n, 4),
        "latency_p50": round(sorted(lats)[n // 2], 2),
        "latency_mean": round(sum(lats) / n, 2),
        "per_query": per_q,
    }


def category_breakdown(per_query, hit_field):
    """Group by category and report hit rate."""
    cats = {}
    for q in per_query:
        c = q.get("category", "uncategorized")
        cats.setdefault(c, {"total": 0, "hits": 0})
        cats[c]["total"] += 1
        if q.get(hit_field):
            cats[c]["hits"] += 1
    return {
        c: {"hit_rate": round(v["hits"] / v["total"], 3), "n": v["total"]}
        for c, v in sorted(cats.items())
    }


def main():
    parser = argparse.ArgumentParser(description="Run hard retrieval + KG eval sets")
    parser.add_argument("--only-ids", default="",
                        help="Comma-separated query IDs to eval (e.g. 'H06,H08,H31')")
    parser.add_argument("--verbose", action="store_true",
                        help="Print full retrieval chain + judge rationale for each query")
    parser.add_argument("--skip-kg", action="store_true",
                        help="Skip the KG traversal eval")
    args = parser.parse_args()

    only_ids = [x.strip() for x in args.only_ids.split(",") if x.strip()] if args.only_ids else None

    r = eval_retrieval(only_ids=only_ids, verbose=args.verbose)
    print("=== Hard Retrieval Eval ===")
    print(f"  n = {r['n']}")
    print(f"  PRIMARY: judge_hit@5 = {r['judge_hit_at_5']:.3f}")
    print(f"           judge_coverage@5 = {r['judge_coverage_at_5_mean']:.3f}")
    print(f"  Secondary/diagnostic:")
    print(f"    substr_hit@5 = {r['substr_hit_at_5']:.3f} (deprecated — kept for comparison)")
    print(f"    precision@5  = {r['precision_at_5_mean']:.3f}")
    print(f"    adversarial_avoidance = {r['adversarial_avoidance']:.3f}")
    print(f"  Latency: p50={r['latency_p50']}s p95={r['latency_p95']}s mean={r['latency_mean']}s")
    print()
    print("  Judge hit@5 by category:")
    for cat, stats in category_breakdown(r["per_query"], "judge_hit@5").items():
        bar = "█" * int(stats["hit_rate"] * 20)
        print(f"    {cat:22} {stats['hit_rate']:.2f}  ({stats['n']:2} queries)  {bar}")

    if args.skip_kg or only_ids:
        print("\n(Skipping KG eval — --skip-kg or --only-ids set)")
        out_path = os.path.join(SCRIPT_DIR, "..", "docs",
                                f"hard-eval-results-{time.strftime('%Y-%m-%d-%H%M')}.json")
        with open(out_path, "w") as f:
            json.dump({"retrieval": r}, f, indent=2)
        print(f"\nResults written to {out_path}")
        return

    k = eval_kg()
    print("\n=== Hard KG Eval ===")
    print(f"  n = {k['n']}")
    print(f"  PRIMARY: judge_coverage@5 = {k['judge_coverage_at_5']:.3f}")
    print(f"  Secondary:")
    print(f"    substr_coverage@5 = {k['substr_coverage_at_5']:.3f}")
    print(f"    min_results_met   = {k['min_results_met']:.3f}")
    print(f"  Latency: p50={k['latency_p50']}s mean={k['latency_mean']}s")

    out_path = os.path.join(SCRIPT_DIR, "..", "docs", f"hard-eval-results-{time.strftime('%Y-%m-%d-%H%M')}.json")
    with open(out_path, "w") as f:
        json.dump({"retrieval": r, "kg": k}, f, indent=2)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
