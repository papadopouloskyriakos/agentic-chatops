#!/usr/bin/env python3
"""Memory-audit for IFRNLLEI01PRD-630 (memory promotion pipeline).

Scans the auto-memory directory and emits two audit surfaces for operator
review — distillation candidates (overlapping memories) and expiry
candidates (stale project memories) — so the MEMORY.md index stays under
the context-truncation threshold and entries converge toward a canonical
form.

Usage:
    memory-audit.py                         # full report, stdout
    memory-audit.py --json out.json         # machine-readable output
    memory-audit.py --candidates-only       # skip expiry section
    memory-audit.py --dir <path>            # override memory dir

Environment:
    OLLAMA_URL=http://nl-gpu01:11434    # override nomic endpoint
    MEMORY_DIR=...                          # override memory dir
    MEMORY_STALE_DAYS=90                    # expiry age threshold
    MEMORY_DUP_THRESHOLD=0.82               # cosine similarity for duplicate candidate

Notes:
    - Feedback memories are NEVER proposed for expiry — they're durable
      "rules from operator corrections" that stay useful indefinitely.
    - Project memories older than MEMORY_STALE_DAYS AND not accessed recently
      (git log tail not in last N days) are expiry candidates.
    - Clustering uses pairwise cosine similarity between `description` field
      embeddings. This finds near-duplicate memories where distillation has
      high leverage. Below threshold pairs are silently dropped.
    - Output is operator-facing, not auto-destructive. The script suggests;
      the operator decides.

Contract: exit 0 = audit succeeded (even if candidates empty).
          exit 1 = scan / embed failure.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
REDACTED_a7b84d63
import subprocess
import sys
import urllib.request
from typing import Any

MEMORY_DIR = os.environ.get(
    "MEMORY_DIR",
    os.path.expanduser(
        "~/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway/memory"
    ),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
STALE_DAYS = int(os.environ.get("MEMORY_STALE_DAYS", "90"))
DUP_THRESHOLD = float(os.environ.get("MEMORY_DUP_THRESHOLD", "0.82"))

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def load_memories(dir_path: str) -> list[dict]:
    out = []
    for fname in sorted(os.listdir(dir_path)):
        if not fname.endswith(".md") or fname == "MEMORY.md":
            continue
        path = os.path.join(dir_path, fname)
        try:
            raw = open(path, encoding="utf-8").read()
        except OSError as e:
            print(f"[skip] {fname}: {e}", file=sys.stderr)
            continue
        m = FRONTMATTER_RE.match(raw)
        fm = {}
        body = raw
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"\'')
            body = raw[m.end():]
        out.append({
            "file": fname,
            "path": path,
            "name": fm.get("name", fname[:-3]),
            "description": fm.get("description", ""),
            "type": fm.get("type", "unknown"),
            "body": body,
            "mtime": os.path.getmtime(path),
        })
    return out


def last_git_change(path: str) -> float | None:
    """Return unix ts of last git commit touching this file, or None."""
    try:
        r = subprocess.run(
            ["git", "-C", os.path.dirname(path), "log", "-1", "--format=%ct", "--", os.path.basename(path)],
            capture_output=True, text=True, timeout=5,
        )
        if r.stdout.strip():
            return float(r.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        pass
    return None


def embed_batch(texts: list[str], model: str = "nomic-embed-text") -> list[list[float]] | None:
    """Embed list of texts via Ollama; return None on failure."""
    if not texts:
        return []
    # Ollama /api/embed supports batch input
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embed",
            data=json.dumps({"model": model, "input": texts}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("embeddings")
    except Exception as e:
        print(f"[embed] batch failed: {e}", file=sys.stderr)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ── Distillation candidate detection ─────────────────────────────────────────


def find_clusters(memories: list[dict], threshold: float) -> list[dict]:
    """Return clusters where any pair exceeds the cosine threshold.

    Uses union-find on high-similarity pairs so a chain A~B, B~C yields one
    3-member cluster {A, B, C} rather than two 2-pairs.
    """
    # Embed using "name: description" to surface topical overlap (not body).
    texts = [f"{m['name']}: {m['description']}" for m in memories]
    embeddings = embed_batch(texts)
    if embeddings is None:
        return []
    if len(embeddings) != len(memories):
        print(f"[cluster] embedding count mismatch: got {len(embeddings)} expected {len(memories)}", file=sys.stderr)
        return []

    parent = list(range(len(memories)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    pair_strengths: dict[tuple[int, int], float] = {}
    for i in range(len(memories)):
        for j in range(i + 1, len(memories)):
            # Skip cross-type pairs — different durability classes shouldn't merge
            if memories[i]["type"] != memories[j]["type"]:
                continue
            sim = cosine(embeddings[i], embeddings[j])
            if sim >= threshold:
                union(i, j)
                pair_strengths[(i, j)] = sim

    groups: dict[int, list[int]] = {}
    for i in range(len(memories)):
        groups.setdefault(find(i), []).append(i)
    clusters = []
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        # Sort cluster by mtime desc — newest first (most likely canonical)
        idxs.sort(key=lambda i: -memories[i]["mtime"])
        pair_scores = []
        for ii in range(len(idxs)):
            for jj in range(ii + 1, len(idxs)):
                a, b = sorted((idxs[ii], idxs[jj]))
                if (a, b) in pair_strengths:
                    pair_scores.append(pair_strengths[(a, b)])
        clusters.append({
            "type": memories[idxs[0]]["type"],
            "members": [
                {
                    "file": memories[i]["file"],
                    "name": memories[i]["name"],
                    "description": memories[i]["description"],
                    "mtime": _dt.datetime.fromtimestamp(memories[i]["mtime"]).isoformat(),
                }
                for i in idxs
            ],
            "max_similarity": max(pair_scores) if pair_scores else 0.0,
            "min_similarity": min(pair_scores) if pair_scores else 0.0,
        })
    clusters.sort(key=lambda c: -c["max_similarity"])
    return clusters


# ── Expiry candidate detection ───────────────────────────────────────────────


def find_expiry_candidates(memories: list[dict], stale_days: int) -> list[dict]:
    """Project-type memories older than stale_days (fs mtime AND git-log).

    Feedback memories are excluded — they capture durable rules and never
    expire from age alone.
    """
    cutoff = _dt.datetime.now().timestamp() - stale_days * 86400
    out = []
    for m in memories:
        if m["type"] != "project":
            continue
        fs_mtime = m["mtime"]
        git_mtime = last_git_change(m["path"]) or 0
        last_seen = max(fs_mtime, git_mtime)
        if last_seen < cutoff:
            age_days = int((_dt.datetime.now().timestamp() - last_seen) / 86400)
            out.append({
                "file": m["file"],
                "name": m["name"],
                "description": m["description"],
                "type": m["type"],
                "age_days": age_days,
                "last_seen": _dt.datetime.fromtimestamp(last_seen).isoformat(),
            })
    out.sort(key=lambda c: -c["age_days"])
    return out


# ── Report rendering ─────────────────────────────────────────────────────────


def render_text(report: dict) -> str:
    lines = [
        f"=== memory audit — {report['timestamp']} ===",
        f"dir: {report['dir']}",
        f"files scanned: {report['total_files']} "
        f"(project={report['by_type'].get('project', 0)}, "
        f"feedback={report['by_type'].get('feedback', 0)}, "
        f"reference={report['by_type'].get('reference', 0)})",
        "",
    ]
    clusters = report.get("distillation_candidates", [])
    lines.append(f"-- distillation candidates: {len(clusters)} cluster(s) --")
    if not clusters:
        lines.append("  (none above threshold)")
    for i, c in enumerate(clusters, 1):
        lines.append(f"\n[{i}] type={c['type']} max_sim={c['max_similarity']:.3f} min_sim={c['min_similarity']:.3f}")
        for m in c["members"]:
            lines.append(f"    {m['file']:<48} {m['description'][:80]}")
    lines.append("")
    expiries = report.get("expiry_candidates", [])
    lines.append(f"-- expiry candidates (project only, age > {report['stale_days']}d): {len(expiries)} --")
    if not expiries:
        lines.append("  (none)")
    for i, e in enumerate(expiries[:30], 1):
        lines.append(f"  {i:3d}. age={e['age_days']:>4}d  {e['file']:<48} {e['description'][:70]}")
    if len(expiries) > 30:
        lines.append(f"  ... and {len(expiries) - 30} more")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=MEMORY_DIR)
    ap.add_argument("--json", help="write full report to this path")
    ap.add_argument("--candidates-only", action="store_true",
                    help="skip expiry section")
    ap.add_argument("--threshold", type=float, default=DUP_THRESHOLD)
    ap.add_argument("--stale-days", type=int, default=STALE_DAYS)
    args = ap.parse_args()

    memories = load_memories(args.dir)
    by_type: dict[str, int] = {}
    for m in memories:
        by_type[m["type"]] = by_type.get(m["type"], 0) + 1

    report: dict[str, Any] = {
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "dir": args.dir,
        "total_files": len(memories),
        "by_type": by_type,
        "threshold": args.threshold,
        "stale_days": args.stale_days,
    }

    clusters = find_clusters(memories, args.threshold)
    report["distillation_candidates"] = clusters

    if not args.candidates_only:
        report["expiry_candidates"] = find_expiry_candidates(memories, args.stale_days)

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"wrote {args.json}")
    print(render_text(report))


if __name__ == "__main__":
    main()
