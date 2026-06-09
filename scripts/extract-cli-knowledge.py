#!/usr/bin/env python3
"""Extract structured knowledge from CLI session summaries into incident_knowledge.

IFRNLLEI01PRD-647 — Tier 2 of CLI-session RAG capture.

Input  : session_transcripts rows with issue_id LIKE 'cli-%' AND chunk_index=-1
         (doc-chain refined summaries produced by archive-session-transcript.py).
Output : incident_knowledge rows with project='chatops-cli', embedded via
         nomic-embed-text so the RAG pipeline can retrieve them alongside
         real incidents (retrieval ranker weights them lower — see
         kb-semantic-search.py WEIGHT_INCIDENT_PROJECT).

Extraction: local gemma3:12b over Ollama, strict-JSON output. Breaker-aware
(rag_synth_ollama). No Haiku fallback — CLI rows are low-priority and local
capacity is adequate.

Usage:
    extract-cli-knowledge.py                  # process all un-extracted rows
    extract-cli-knowledge.py --limit 20       # cap per-run extraction count
    extract-cli-knowledge.py --dry-run        # print would-insert JSON, no DB writes
    extract-cli-knowledge.py --issue cli-...  # extract a single session_id
"""
from __future__ import annotations

import argparse
import json
import os
REDACTED_a7b84d63
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from schema_version import current as schema_current  # noqa: E402

try:
    from circuit_breaker import CircuitBreaker  # type: ignore
    _SYNTH_CB: Optional[CircuitBreaker] = CircuitBreaker(
        "rag_synth_ollama", failure_threshold=4, cooldown_seconds=120,
    )
except ImportError:
    _SYNTH_CB = None

DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://nl-gpu01:11434")
EXTRACT_MODEL = os.environ.get("CLI_KB_MODEL", "gemma3:12b")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
PROJECT_TAG = "chatops-cli"


EXTRACT_PROMPT = """You are extracting structured knowledge from a summary of a Claude Code CLI session between an operator and Claude. The session is not an infrastructure incident — it's an interactive coding/debugging session. Your job is to distill it into a single JSON record that a retrieval system can surface when a future session encounters a similar problem.

Output STRICT JSON only (no prose, no markdown fences). Schema:

{
  "root_cause": "<=200 chars, one sentence, what was actually wrong (if anything); empty string if the session was exploratory/design-only with no defect found",
  "resolution": "<=300 chars, one to three sentences, what the operator and Claude actually did to fix or decide; cite specific files/commands/commits if named",
  "subsystem": "<=40 chars lowercase-hyphenated area tag (e.g. 'n8n-workflow', 'asa-vti-bgp', 'k8s-helm', 'sqlite-schema', 'rag-pipeline'); empty if unclear",
  "tags": [ "<=6 short tags, lowercase, for filter-style retrieval; use common nouns not verbs" ],
  "confidence": 0.0-1.0 float — how sure you are the extraction captured the real content (low when the summary itself was thin)
}

Rules:
  * Do not invent facts not present in the summary.
  * If root_cause is unclear, leave it empty rather than guessing.
  * tags are the primary filter signal — prefer 'zigbee', 'permit-join', 'cp210x' over 'fixed', 'debugged'.
  * Do not include issue IDs in any field — they live in the row's issue_id column already.

--- SESSION SUMMARY ---
"""


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ollama_json(prompt_body: str, timeout: int = 120) -> Optional[dict]:
    """Call Ollama /api/generate with format=json; parse output. Breaker-aware."""
    if _SYNTH_CB is not None and not _SYNTH_CB.allow():
        print("[extract] rag_synth_ollama breaker OPEN — skipping run", file=sys.stderr)
        return None

    data = json.dumps({
        "model": EXTRACT_MODEL,
        "prompt": EXTRACT_PROMPT + prompt_body,
        "stream": False,
        "format": "json",
        "options": {"num_ctx": 8192, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
        _record_local_usage(EXTRACT_MODEL,
                            result.get("prompt_eval_count", 0),
                            result.get("eval_count", 0))
        raw = (result.get("response") or "").strip()
        if _SYNTH_CB is not None:
            _SYNTH_CB.record_success()
        # Gemma wraps sometimes in ```json fences despite format=json — strip.
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        return json.loads(m.group(0))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        if _SYNTH_CB is not None:
            _SYNTH_CB.record_failure()
        print(f"[extract] Ollama error: {exc}", file=sys.stderr)
        return None


def _record_local_usage(model: str, input_tokens: int, output_tokens: int = 0) -> None:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO llm_usage (tier, model, issue_id, input_tokens, output_tokens, cost_usd) "
            "VALUES (0, ?, 'cli-knowledge-extract', ?, ?, 0.0)",
            (model, input_tokens, output_tokens),
        )
        conn.commit()
        conn.close()
    except sqlite3.DatabaseError:
        pass


def _embed_document(text: str) -> str:
    """Generate nomic-embed-text document embedding. Returns '' on failure."""
    try:
        data = json.dumps({
            "model": EMBED_MODEL,
            "input": f"search_document: {text[:2000]}",
            "options": {"num_ctx": 2048},
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/embed", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            _record_local_usage(EMBED_MODEL, result.get("prompt_eval_count", 0))
            emb = result.get("embeddings", [[]])[0]
            return json.dumps(emb) if emb else ""
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return ""


def _sanitize_tags(raw_tags: Any) -> list[str]:
    """Normalize tag list: lowercase, hyphenate non-alnum runs, 2-40 chars, cap 6.

    Cap is applied AFTER filtering so a single too-long or empty tag doesn't
    knock out an otherwise-valid tag.
    """
    if not isinstance(raw_tags, list):
        return []
    out = []
    for t in raw_tags:
        if not isinstance(t, str):
            continue
        clean = re.sub(r"[^a-z0-9\-]+", "-", t.lower()).strip("-")
        if 2 <= len(clean) <= 40:
            out.append(clean)
        if len(out) >= 6:
            break
    return out


def fetch_pending(conn: sqlite3.Connection, limit: int, issue_filter: str = "") -> list[tuple]:
    """Return (issue_id, session_id, summary_text) for un-extracted CLI sessions."""
    where = "WHERE st.issue_id LIKE 'cli-%' AND st.chunk_index = -1"
    args: list[Any] = []
    if issue_filter:
        where += " AND st.issue_id = ?"
        args.append(issue_filter)
    sql = f"""
        SELECT st.issue_id, st.session_id, st.content
          FROM session_transcripts st
          LEFT JOIN incident_knowledge ik
            ON ik.issue_id = st.issue_id AND ik.project = ?
         {where}
           AND ik.id IS NULL
         ORDER BY st.created_at ASC
         LIMIT ?
    """
    return conn.execute(sql, [PROJECT_TAG, *args, limit]).fetchall()


def extract_row(issue_id: str, session_id: str, summary: str) -> Optional[dict]:
    """Run extraction on one summary. Returns dict or None."""
    if len(summary) < 100:
        return None  # too short to be worth extracting
    parsed = _ollama_json(summary[:6000])
    if not parsed or not isinstance(parsed, dict):
        return None
    return {
        "issue_id": issue_id,
        "session_id": session_id,
        "root_cause": str(parsed.get("root_cause", ""))[:400],
        "resolution": str(parsed.get("resolution", ""))[:600],
        "subsystem": str(parsed.get("subsystem", ""))[:40].lower(),
        "tags": ",".join(_sanitize_tags(parsed.get("tags"))),
        "confidence": float(parsed.get("confidence", 0.0)) if isinstance(parsed.get("confidence"), (int, float)) else 0.0,
    }


def insert_row(conn: sqlite3.Connection, row: dict, summary: str) -> None:
    # Embedding is over the composed text that future retrieval will match against.
    embed_source = "\n".join(filter(None, [
        row["subsystem"], row["root_cause"], row["resolution"], row["tags"]
    ]))
    embedding = _embed_document(embed_source) if embed_source else ""
    conn.execute(
        """INSERT INTO incident_knowledge
               (alert_rule, hostname, site, root_cause, resolution, confidence,
                session_id, issue_id, tags, embedding, project)
           VALUES ('', '', '', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (row["root_cause"], row["resolution"], row["confidence"],
         row["session_id"], row["issue_id"], row["tags"], embedding, PROJECT_TAG),
    )
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--issue", default="", help="only process this single issue_id")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    conn = _db_connect()
    pending = fetch_pending(conn, args.limit, args.issue)
    if not pending:
        print("[extract] nothing to do (no un-extracted cli- summaries)")
        return 0

    print(f"[extract] {len(pending)} pending row(s) — model={EXTRACT_MODEL} dry_run={args.dry_run}")
    inserted = 0
    skipped = 0
    failed = 0
    t0 = time.time()

    for issue_id, session_id, summary in pending:
        row = extract_row(issue_id, session_id, summary)
        if not row:
            failed += 1
            print(f"  [fail] {issue_id}: extraction returned no usable JSON")
            continue

        # Heuristic skip: if root_cause AND resolution are both empty, the session
        # produced no knowledge worth indexing.
        if not row["root_cause"].strip() and not row["resolution"].strip():
            skipped += 1
            print(f"  [skip] {issue_id}: no root_cause/resolution extracted")
            continue

        if args.dry_run:
            print(f"  [dry]  {issue_id}: {json.dumps({k: row[k] for k in ('subsystem','tags','confidence')})}")
            if args.verbose:
                print(f"         root_cause: {row['root_cause'][:120]}")
                print(f"         resolution: {row['resolution'][:120]}")
            inserted += 1
            continue

        try:
            insert_row(conn, row, summary)
            inserted += 1
            print(f"  [ok]   {issue_id}: subsystem={row['subsystem']} tags=[{row['tags']}] conf={row['confidence']:.2f}")
        except sqlite3.DatabaseError as exc:
            failed += 1
            print(f"  [err]  {issue_id}: {exc}")

    elapsed = time.time() - t0
    print(f"[extract] done — inserted={inserted} skipped={skipped} failed={failed} elapsed={elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
