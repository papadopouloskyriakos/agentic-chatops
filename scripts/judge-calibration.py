#!/usr/bin/env python3
"""Judge calibration: score the same queries with both Haiku and local gemma3:12b,
compute agreement rates per category, and record a reproducible baseline.

Rationale: the local-first judge migration (2026-04-19) was validated on a
10-query sample. Before treating the new hit-rate trend line as comparable to
the old (Haiku-judged) one, we need a larger-sample agreement measurement so
the week-over-week delta can be separated from calibration drift.

Design:
  1. Load the 50-query `hard-retrieval-v2.json` + 10-query `hard-kg.json` = 60.
  2. For each query, retrieve top-5 ONCE via kb-semantic-search. Both judges
     see identical input — no retrieval nondeterminism.
  3. Score each query's retrieved docs twice:
       Haiku (reference): via Anthropic API, costs ~$0.06 total
       Local (new):       via gemma3:12b with qwen2.5:7b fallback
  4. Compute agreement, FP rate (local hit, Haiku miss), FN rate (local miss,
     Haiku hit), per-category breakdown.
  5. Write a markdown report + a JSON artifact for reproducibility.

Cost: one-off ~$0.06. Run annually or after any judge-related change.
"""
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request
import concurrent.futures

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.path.join(SCRIPT_DIR, "eval-sets")
REPO_DIR = os.path.dirname(SCRIPT_DIR)
KB = os.path.join(SCRIPT_DIR, "kb-semantic-search.py")

HAIKU_MODEL = "claude-haiku-4-5-20251001"
LOCAL_MODEL = os.environ.get("JUDGE_LOCAL_MODEL", "gemma3:12b")
LOCAL_FALLBACK = os.environ.get("JUDGE_LOCAL_FALLBACK", "qwen2.5:7b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")


def _api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env_path = os.path.join(REPO_DIR, ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def retrieve(query, limit=5):
    """Run semantic search once, return top-K rows as strings."""
    result = subprocess.run(
        ["python3", KB, "search", query, "--limit", str(limit)],
        capture_output=True, text=True, timeout=60,
    )
    lines = [l for l in result.stdout.split("\n") if l.strip() and not l.startswith("RETRIEVAL_QUALITY:")]
    return lines[:limit]


def build_prompt(query, ground_truth, rows):
    docs_block = "\n".join(f"[{i+1}] {r[:280]}" for i, r in enumerate(rows[:5]))
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
    return system, user


def judge_haiku(system, user, key):
    body = json.dumps({
        "model": HAIKU_MODEL, "max_tokens": 400, "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, headers={
            "Content-Type": "application/json", "x-api-key": key,
            "anthropic-version": "2023-06-01",
        })
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    dt = time.time() - t0
    text = data["content"][0]["text"].strip()
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:]).rsplit("```", 1)[0]
    return dt, json.loads(text)


def judge_local(system, user):
    """Try gemma3:12b first, fall back to qwen2.5:7b on failure."""
    for model in (LOCAL_MODEL, LOCAL_FALLBACK):
        body = json.dumps({
            "model": model,
            "prompt": f"{system}\n\n{user}",
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 400, "num_ctx": 2048},
        }).encode()
        req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            dt = time.time() - t0
            return dt, json.loads(data.get("response", "").strip()), model
        except Exception as e:
            print(f"  [judge-local:{model}] {type(e).__name__}: {e}", file=sys.stderr)
            continue
    return 0, None, None


def load_cases():
    """Combine hard-retrieval-v2 + hard-kg into a single list of (id, category, query, gt)."""
    cases = []
    for fname, tag in (("hard-retrieval-v2.json", "retrieval"), ("hard-kg.json", "kg")):
        with open(os.path.join(EVAL_DIR, fname)) as f:
            for q in json.load(f):
                cases.append({
                    "id": q.get("id", "?"),
                    "category": q.get("category", tag),
                    "query": q["query"],
                    "ground_truth": q.get("ground_truth", q.get("expected_answer", "")),
                })
    return cases


def main():
    key = _api_key()
    if not key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    cases = load_cases()
    print(f"Loaded {len(cases)} cases across {len(set(c['category'] for c in cases))} categories")
    print("Retrieving top-5 per query (parallel)...", file=sys.stderr)

    # Phase 1: retrieve all (one thread pool, ThreadPool=4 to be nice to the GPU)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        retrieved = list(ex.map(lambda c: retrieve(c["query"]), cases))

    # Phase 2: judge both. Haiku via Anthropic API; local via Ollama.
    results = []
    for i, (case, rows) in enumerate(zip(cases, retrieved)):
        if not rows:
            results.append({**case, "haiku_hit": None, "local_hit": None, "skip": "no_rows"})
            continue
        system, user = build_prompt(case["query"], case["ground_truth"], rows)

        try:
            _, haiku = judge_haiku(system, user, key)
            haiku_hit = bool(haiku.get("any_relevant"))
            haiku_cov = len(haiku.get("relevant_indices", []))
        except Exception as e:
            print(f"  [{case['id']}] haiku failed: {e}", file=sys.stderr)
            haiku_hit, haiku_cov = None, 0

        local_dt, local, local_model = judge_local(system, user)
        if local is None:
            local_hit, local_cov = None, 0
        else:
            local_hit = bool(local.get("any_relevant"))
            local_cov = len(local.get("relevant_indices", []))

        results.append({
            "id": case["id"], "category": case["category"],
            "haiku_hit": haiku_hit, "haiku_cov": haiku_cov,
            "local_hit": local_hit, "local_cov": local_cov,
            "local_model": local_model,
            "local_dt": round(local_dt, 2),
        })
        if (i + 1) % 10 == 0:
            print(f"  ...{i + 1}/{len(cases)}", file=sys.stderr)

    # Aggregate
    complete = [r for r in results if r.get("haiku_hit") is not None and r.get("local_hit") is not None]
    agree = [r for r in complete if r["haiku_hit"] == r["local_hit"]]
    fp = [r for r in complete if r["local_hit"] is True and r["haiku_hit"] is False]
    fn = [r for r in complete if r["local_hit"] is False and r["haiku_hit"] is True]

    print()
    print(f"=== Judge Calibration Summary ===")
    print(f"Total cases:       {len(cases)}")
    print(f"Complete (both judged): {len(complete)}")
    print(f"Agreement:         {len(agree)}/{len(complete)} = "
          f"{len(agree)/max(len(complete),1)*100:.1f}%")
    print(f"  False positives (local hit, Haiku miss): {len(fp)}")
    print(f"  False negatives (local miss, Haiku hit): {len(fn)}")

    # Per-category
    from collections import Counter
    cats = Counter()
    cats_agree = Counter()
    for r in complete:
        cats[r["category"]] += 1
        if r["haiku_hit"] == r["local_hit"]:
            cats_agree[r["category"]] += 1

    print("\nBy category:")
    for cat in sorted(cats):
        n = cats[cat]; a = cats_agree[cat]
        print(f"  {cat:22} {a}/{n}  ({a/n*100:.1f}%)")

    # Hit rate per judge
    haiku_hits = sum(1 for r in complete if r["haiku_hit"])
    local_hits = sum(1 for r in complete if r["local_hit"])
    print(f"\nHit rate comparison (on {len(complete)} complete cases):")
    print(f"  Haiku judge:  {haiku_hits}/{len(complete)} = {haiku_hits/max(len(complete),1)*100:.1f}%")
    print(f"  Local judge:  {local_hits}/{len(complete)} = {local_hits/max(len(complete),1)*100:.1f}%")
    print(f"  Δ:            {(local_hits-haiku_hits)/max(len(complete),1)*100:+.1f} pp")

    # Persist
    stamp = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    json_path = os.path.join(REPO_DIR, "docs", f"judge-calibration-{stamp}.json")
    md_path = os.path.join(REPO_DIR, "docs", f"judge-calibration-{stamp}.md")
    with open(json_path, "w") as f:
        json.dump({
            "run_at": datetime.datetime.utcnow().isoformat() + "Z",
            "haiku_model": HAIKU_MODEL,
            "local_model": LOCAL_MODEL,
            "local_fallback": LOCAL_FALLBACK,
            "cases_total": len(cases),
            "cases_complete": len(complete),
            "agreement_rate": round(len(agree) / max(len(complete), 1), 4),
            "false_positives": len(fp),
            "false_negatives": len(fn),
            "haiku_hit_rate": round(haiku_hits / max(len(complete), 1), 4),
            "local_hit_rate": round(local_hits / max(len(complete), 1), 4),
            "per_category": {cat: {"n": cats[cat], "agree": cats_agree[cat]} for cat in cats},
            "per_case": results,
        }, f, indent=2)
    with open(md_path, "w") as f:
        f.write(f"# Judge Calibration Baseline — {stamp}\n\n")
        f.write(f"Dual-scored {len(cases)} queries (50 hard-retrieval-v2 + 10 hard-kg) with "
                f"both **Haiku {HAIKU_MODEL}** (reference) and **{LOCAL_MODEL}** (local, "
                f"with {LOCAL_FALLBACK} fallback). Retrieval ran once per query so both "
                f"judges saw identical top-5 docs.\n\n")
        f.write(f"## Overall\n\n")
        f.write(f"| Metric | Value |\n|---|---|\n")
        f.write(f"| Cases | {len(cases)} |\n")
        f.write(f"| Complete (both judged) | {len(complete)} |\n")
        f.write(f"| **Agreement rate** | **{len(agree)/max(len(complete),1)*100:.1f}%** |\n")
        f.write(f"| False positives (local hit, Haiku miss) | {len(fp)} |\n")
        f.write(f"| False negatives (local miss, Haiku hit) | {len(fn)} |\n")
        f.write(f"| Haiku hit rate | {haiku_hits}/{len(complete)} ({haiku_hits/max(len(complete),1)*100:.1f}%) |\n")
        f.write(f"| Local hit rate | {local_hits}/{len(complete)} ({local_hits/max(len(complete),1)*100:.1f}%) |\n")
        f.write(f"| Δ | {(local_hits-haiku_hits)/max(len(complete),1)*100:+.1f} pp |\n\n")
        f.write(f"## By category\n\n")
        f.write(f"| Category | Agreement |\n|---|---|\n")
        for cat in sorted(cats):
            f.write(f"| {cat} | {cats_agree[cat]}/{cats[cat]} ({cats_agree[cat]/cats[cat]*100:.1f}%) |\n")
        f.write(f"\n## Disagreements\n\n")
        if fp or fn:
            f.write(f"### False positives (local says hit, Haiku says miss)\n\n")
            for r in fp:
                f.write(f"- `{r['id']}` ({r['category']})\n")
            f.write(f"\n### False negatives (local says miss, Haiku says hit)\n\n")
            for r in fn:
                f.write(f"- `{r['id']}` ({r['category']})\n")
        else:
            f.write("None — perfect agreement.\n")
        f.write(f"\n## How to interpret\n\n")
        f.write(f"- **Agreement rate** is the headline number. ≥95% means the local judge is "
                f"a safe drop-in; 85-95% means absolute hit-rate numbers are comparable but "
                f"noisy across week-over-week comparisons; <85% means the two are materially "
                f"different judges and the local-era and Haiku-era trend lines should not be "
                f"charted together.\n")
        f.write(f"- **FP rate** indicates whether local is looser than Haiku (calls borderline "
                f"cases 'hit' that Haiku would reject). FP-heavy drift makes hit-rate "
                f"numbers look artificially high.\n")
        f.write(f"- **FN rate** indicates whether local is stricter than Haiku (misses hits "
                f"Haiku would accept). FN-heavy drift makes the pipeline look worse than it "
                f"is.\n\n")
        f.write(f"Repeat this calibration annually or after any change to the judge model/"
                f"prompt/rubric. Results persisted at `{os.path.basename(json_path)}`.\n")

    print(f"\nWritten: {md_path}")
    print(f"Written: {json_path}")


if __name__ == "__main__":
    main()
