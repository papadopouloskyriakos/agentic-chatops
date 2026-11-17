#!/usr/bin/env python3
"""Teacher agent orchestrator (IFRNLLEI01PRD-653).

Dispatched by the n8n `claude-gateway-teacher-runner` workflow after the
matrix-bridge parses a `!learn` / `!quiz` / `!progress` / `!digest` command
in #learning (or in an operator's DM with the bot).

Subcommands (driven by the n8n workflow, not a human):

    --resolve-dm  --operator <mxid>
        Look up or lazy-create the DM room. Idempotent. Prints room_id.

    --next --operator <mxid>
        Pick the highest-priority due topic via SM-2. Prints its id + title.

    --lesson --operator <mxid> --topic <id> [--source-room <roomId>]
        Fetch curriculum sources, render markdown lesson, post to DM.
        If --source-room is #learning, also posts a brief in-channel ack.

    --quiz --operator <mxid> --topic <id>
        Generate a quiz question (hallucination-gated), persist as a
        learning_sessions row, post to DM. Returns session_id.

    --grade --operator <mxid> --session-id <N> --answer <text>
        Grade the operator's answer, update learning_progress via SM-2,
        post feedback to DM.

    --progress --operator <mxid> [--public]
        Print / DM-post a mastery + streak summary. --public posts in
        #learning instead (only allowed if the operator has opt-in).

    --leaderboard [--source-room <roomId>]
        Aggregate across public_sharing=1 operators, post in #learning.

    --class-digest [--weekly] [--source-room <roomId>]
        Anonymised totals (count mastered, total minutes, active members).

    --morning-nudge
        Cron entry point. Walks teacher_operator_dm, per operator posts
        a DM with today's due topics. No in-channel noise.

    --pause --operator <mxid>
    --resume --operator <mxid>
    --public-on --operator <mxid>
    --public-off --operator <mxid>

Authorisation: every operator-scoped command first checks that
`operator_mxid` is a joined member of CLASSROOM_ROOM_ID (#learning).
Fail-closed on Matrix errors.

This script is the single point that touches Matrix from the teacher
pipeline — n8n just invokes it with args and logs stdout.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from bloom import BLOOM_LEVELS, select_target_bloom, candidates_for, is_advance, is_valid_level  # noqa: E402
from sm2 import Card, initial_card, schedule as sm2_schedule, quality_from_score, due_topics  # noqa: E402
from schema_version import current as schema_current  # noqa: E402
import quiz_generator  # noqa: E402
import quiz_grader  # noqa: E402
import teacher_chat  # noqa: E402
import matrix_teacher as mx  # noqa: E402
from wiki_url import linkify as _link, wiki_url as _wurl  # noqa: E402


DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)
CURRICULUM_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "curriculum.json",
)
CLASSROOM_ROOM_ID = os.environ.get(
    "TEACHER_CLASSROOM_ROOM_ID",
    "!HdUfKpzHeplqBOYvwY:matrix.example.net",
)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRON_LAST_RUN_DIR = os.environ.get(
    "TEACHER_LAST_RUN_DIR",
    "/var/lib/claude-gateway",
)


def _touch_last_run(kind: str) -> None:
    """Bump /var/lib/claude-gateway/teacher-<kind>.last mtime. Best-effort —
    Prometheus stale-cron alerts key off these timestamps."""
    try:
        os.makedirs(CRON_LAST_RUN_DIR, exist_ok=True)
        path = os.path.join(CRON_LAST_RUN_DIR, f"teacher-{kind}.last")
        with open(path, "a"):
            os.utime(path, None)
    except OSError as e:
        print(f"[teacher-agent] _touch_last_run({kind}): {e}", file=sys.stderr)


# ── DB helpers ──────────────────────────────────────────────────────────────

def _db():
    # 30s busy_timeout protects the 100s+ Ollama-synthesis path — the final
    # UPDATE in cmd_chat/cmd_grade runs after the LLM returns and must not
    # lose to a competing writer (wiki-compile, session poller, parallel
    # teacher run). Without this, a write-lock contention killed user-visible
    # DM replies — Ollama ran to completion, but the Matrix post never fired.
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _get_progress_row(conn, operator: str, topic: str) -> dict:
    row = conn.execute(
        "SELECT * FROM learning_progress WHERE operator=? AND topic=?",
        (operator, topic),
    ).fetchone()
    if row:
        return dict(row)
    return {}


def _upsert_progress(conn, operator: str, topic: str, updates: dict) -> None:
    row = _get_progress_row(conn, operator, topic)
    if not row:
        conn.execute(
            "INSERT INTO learning_progress (operator, topic, schema_version) VALUES (?, ?, ?)",
            (operator, topic, schema_current("learning_progress")),
        )
        row = _get_progress_row(conn, operator, topic)
    cols = []
    vals = []
    for k, v in updates.items():
        cols.append(f"{k}=?")
        vals.append(v)
    cols.append("updated_at=CURRENT_TIMESTAMP")
    vals.extend([operator, topic])
    conn.execute(
        f"UPDATE learning_progress SET {', '.join(cols)} WHERE operator=? AND topic=?",
        vals,
    )
    conn.commit()


# ── Curriculum access ──────────────────────────────────────────────────────

def _load_curriculum() -> dict:
    with open(CURRICULUM_PATH) as f:
        return json.load(f)


def _get_topic(topic_id: str) -> Optional[dict]:
    for t in _load_curriculum().get("topics", []):
        if t["id"] == topic_id:
            return t
    return None


def _title_core(title: str) -> str:
    """Distinctive part of a curriculum title for fuzzy matching.

    'Gulli pattern #1: Tool Use' → 'Tool Use'
    'Foundation invariant 1: HITL gate on mutating actions' → 'HITL gate on mutating actions'
    """
    for sep in (":", "—", "–"):
        if sep in title:
            return title.split(sep, 1)[1].strip()
    return title.strip()


def _take_section(lines: list[str], start_idx: int, limit: int = 1500) -> str:
    level = len(lines[start_idx]) - len(lines[start_idx].lstrip("#"))
    buf = []
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("#"):
            new_level = len(lines[j]) - len(lines[j].lstrip("#"))
            if new_level <= level:
                break
        buf.append(lines[j])
    return "\n".join(buf).strip()[:limit]


def _take_table(lines: list[str], row_idx: int, limit: int = 1500) -> str:
    """Return header + separator + matching row from a markdown table."""
    start = row_idx
    while start > 0 and lines[start - 1].strip().startswith("|"):
        start -= 1
    # Keep at most the header (first 2 rows: column names + separator) + the target row.
    header = lines[start:start + 2] if row_idx > start else []
    pieces = header + [lines[row_idx]] if header and lines[row_idx] not in header else lines[start:row_idx + 1]
    return "\n".join(pieces)[:limit]


def _take_window(lines: list[str], idx: int, before: int = 2, after: int = 8,
                 limit: int = 1500) -> str:
    start = max(0, idx - before)
    end = min(len(lines), idx + after + 1)
    return "\n".join(lines[start:end]).strip()[:limit]


def _extract_section(text: str, topic: dict, src: dict) -> tuple[str, str]:
    """Return (section_label, extracted_text). Falls through four strategies:

    1. anchor → heading match
    2. topic-title core → heading match
    3. topic-title core → table row
    4. topic-title core → plain-line window

    Returns ("", "") when nothing useful matches — caller drops the snippet.
    """
    lines = text.split("\n")
    anchor = src.get("anchor", "")

    if anchor and anchor.startswith("#"):
        needle = anchor.lstrip("#").replace("-", " ").lower()
        for i, L in enumerate(lines):
            if L.startswith(("# ", "## ", "### ", "#### ")) and needle in L.lower():
                return (L.lstrip("# ").strip(), _take_section(lines, i))

    core = _title_core(topic.get("title", ""))
    if not core:
        return ("", "")
    core_low = core.lower()
    # 2. Heading containing the title core
    for i, L in enumerate(lines):
        if L.startswith(("# ", "## ", "### ", "#### ")) and core_low in L.lower():
            return (L.lstrip("# ").strip(), _take_section(lines, i))
    # 3. Table row containing the title core
    for i, L in enumerate(lines):
        if L.strip().startswith("|") and core_low in L.lower():
            return (core, _take_table(lines, i))
    # 4. Any line containing the title core
    for i, L in enumerate(lines):
        if core_low in L.lower():
            return (core, _take_window(lines, i))
    return ("", "")


def _snippets_for_topic(topic: dict) -> list[quiz_generator.Snippet]:
    """Read the topic's source files and return Snippet objects.

    Snippet extraction tries anchor match → title-heading → title-in-table-row
    → title-in-line window, in that order. When every strategy misses a source
    we skip it rather than dumping the document preamble.
    """
    out: list[quiz_generator.Snippet] = []
    for src in topic.get("sources", []):
        path_rel = src.get("path", "")
        full = path_rel
        if not os.path.isabs(full):
            full = os.path.join(REPO_ROOT, path_rel)
        if not os.path.exists(full):
            continue
        try:
            text = open(full).read()
        except OSError:
            continue
        section, extracted = _extract_section(text, topic, src)
        if not extracted:
            continue
        out.append(quiz_generator.Snippet(
            source_path=path_rel,
            section=section or "main",
            verbatim_text=extracted,
        ))
    return out


# ── Rendering ──────────────────────────────────────────────────────────────

def _render_lesson(topic: dict, snippets: list[quiz_generator.Snippet]) -> str:
    lines = [f"### 📖 Lesson — {topic['title']}", ""]
    for s in snippets[:2]:
        section_label = _link(s.source_path, s.section, label=f"**{s.section}**")
        src_link = _link(s.source_path, s.section)
        lines.append(f"{section_label} — from {src_link}")
        lines.append("")
        body = s.verbatim_text.strip()
        lines.append(body[:1200] + ("…" if len(body) > 1200 else ""))
        lines.append("")
    lines.append("**Sources**")
    seen = set()
    for s in snippets:
        if s.source_path in seen:
            continue
        seen.add(s.source_path)
        lines.append(f"- {_link(s.source_path, s.section)}")
    lines.append("")
    lines.append("_Ready for the quiz? Reply `!quiz` in this DM._")
    return "\n".join(lines)


def _render_quiz(session_id: int, question: quiz_generator.Question) -> str:
    lines = [
        f"🎯  QUIZ · Bloom level: `{question.bloom_level}`",
        "",
        question.question_text,
        "",
    ]
    if question.question_type == "recognition" and question.distractor_hints:
        # DM audit #2 (2026-04-23): numbered "1. 2. 3. 4." rendering made hints
        # look like multiple-choice options — operators picked a number instead
        # of answering in prose. Switch to bullets + explicit "not multiple-
        # choice" label so the UX can't be misread that way.
        lines.append("**Supporting keywords** (from the source material — _this is free-text, not multiple-choice_):")
        for d in question.distractor_hints[:4]:
            lines.append(f"- {d}")
        lines.append("")
    if question.source_snippets:
        lines.append("**Review sources**")
        seen = set()
        for s in question.source_snippets:
            path = s.get("source_path", "")
            sec = s.get("section", "")
            key = (path, sec)
            if not path or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {_link(path, sec)}")
        lines.append("")
    lines.append(f"_(session #{session_id} · reply with your answer, or `!skip` to defer)_")
    return "\n".join(lines)


def _render_grade(grade: quiz_grader.Grade, next_due_days: int,
                  mastery_before: float, mastery_after: float,
                  band_before: str, band_after: str,
                  source_snippets: Optional[list[dict]] = None) -> str:
    stars = "⭐" * min(5, max(1, round(grade.score_0_to_1 * 5)))
    lines = [
        f"{stars}  **Score:** {grade.score_0_to_1:.2f} / 1.0",
        "",
        grade.feedback,
        "",
        f"Bloom demonstrated: `{grade.bloom_demonstrated}`",
        f"Next review: in {next_due_days} days",
        f"Mastery: {mastery_before:.2f} → {mastery_after:.2f}  ({band_before} → {band_after})",
    ]
    if grade.citation_check.get("extra_claims"):
        lines.append("")
        lines.append("_Note: your answer cited material outside the sources "
                     "(may be correct synthesis — flagged for review):_")
        for c in grade.citation_check["extra_claims"][:3]:
            lines.append(f"· {c}")
    if grade.clarifying_question:
        lines.append("")
        lines.append(f"**Clarifying question:** {grade.clarifying_question}")
    if source_snippets:
        lines.append("")
        lines.append("**Re-read**")
        seen = set()
        for s in source_snippets:
            path = s.get("source_path", "")
            sec = s.get("section", "")
            key = (path, sec)
            if not path or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {_link(path, sec)}")
    return "\n".join(lines)


# ── Authorisation ─────────────────────────────────────────────────────────

def _check_auth(operator: str) -> bool:
    return mx.is_authorised(operator, CLASSROOM_ROOM_ID)


# ── Subcommand: next ──────────────────────────────────────────────────────

def _band(mastery: float) -> str:
    if mastery < 0.4: return "foundation"
    if mastery < 0.7: return "conceptual"
    if mastery < 0.9: return "analytical"
    return "mastery"


def cmd_next(operator: str, *, source_room: str = "") -> dict:
    if not _check_auth(operator):
        return {"ok": False, "error": "not authorised (join #learning first)"}
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM learning_progress WHERE operator=? AND paused=0 ORDER BY next_due",
            (operator,),
        ).fetchall()]
    finally:
        conn.close()
    due = due_topics(rows, datetime.datetime.utcnow())
    if due:
        target_topic = due[0]["topic"]
    else:
        seen = {r["topic"] for r in rows}
        unseen = [t for t in _load_curriculum().get("topics", []) if t["id"] not in seen]
        if not unseen:
            dm = mx.resolve_dm(operator)
            body = "🌱  You've seen every topic at least once — nothing due right now. Try `!quiz <topic>` to review, or `!progress` for mastery stats."
            mx.post_notice(dm, body, formatted_body=mx.md_to_html(body))
            return {"ok": True, "message": "curriculum exhausted", "dm_room_id": dm}
        target_topic = unseen[0]["id"]
    return cmd_lesson(operator, target_topic, source_room=source_room)


# ── Subcommand: lesson ────────────────────────────────────────────────────

def cmd_lesson(operator: str, topic_id: str, *, source_room: str = "") -> dict:
    if not _check_auth(operator):
        return {"ok": False, "error": "not authorised (join #learning first)"}
    topic = _get_topic(topic_id)
    if not topic:
        return {"ok": False, "error": f"unknown topic {topic_id!r}"}
    snippets = _snippets_for_topic(topic)
    if not snippets:
        return {"ok": False, "error": f"no source content found for {topic_id}"}
    body = _render_lesson(topic, snippets)
    dm = mx.resolve_dm(operator)
    # Persist learning_sessions row
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO learning_sessions "
            "(operator, topic, session_type, started_at, completed_at, schema_version) "
            "VALUES (?, ?, 'lesson', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)",
            (operator, topic_id, schema_current("learning_sessions")),
        )
        conn.commit()
    finally:
        conn.close()
    evt = mx.post_message(dm, body, formatted_body=mx.md_to_html(body))
    # Optional in-channel ack
    if source_room and source_room == CLASSROOM_ROOM_ID:
        mx.post_notice(source_room, f"📨 {operator} — lesson sent to your DM.")
    return {"ok": True, "dm_room_id": dm, "event_id": evt, "topic_id": topic_id}


# ── Subcommand: quiz ──────────────────────────────────────────────────────

def _pick_active_topic(operator: str) -> Optional[str]:
    """Auto-pick a topic for no-arg !quiz: last lesson/quiz the operator saw,
    or fallback to first-due SM-2 topic, or fallback to first unseen
    curriculum topic. Returns a topic_id string or None when curriculum is
    fully mastered with nothing due."""
    conn = _db()
    try:
        # Most recent learning_sessions row (lesson OR quiz) is what they're
        # currently studying. Prefer that so `!quiz` after `!learn X` picks X.
        last = conn.execute(
            "SELECT topic FROM learning_sessions WHERE operator=? "
            "ORDER BY started_at DESC LIMIT 1",
            (operator,),
        ).fetchone()
        if last and last[0]:
            return last[0]
        # No history yet — fall back to SM-2 due, then to first unseen curriculum.
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM learning_progress WHERE operator=? AND paused=0 ORDER BY next_due",
            (operator,),
        ).fetchall()]
    finally:
        conn.close()
    due = due_topics(rows, datetime.datetime.utcnow())
    if due:
        return due[0]["topic"]
    seen = {r["topic"] for r in rows}
    for t in _load_curriculum().get("topics", []):
        if t["id"] not in seen:
            return t["id"]
    return None


def cmd_quiz(operator: str, topic_id: str, *, source_room: str = "") -> dict:
    if not _check_auth(operator):
        return {"ok": False, "error": "not authorised"}
    if not topic_id:
        topic_id = _pick_active_topic(operator) or ""
        if not topic_id:
            dm = mx.resolve_dm(operator)
            body = ("🌱  No active lesson and no topics due. Run `!learn` to "
                    "start with the next curriculum topic, then `!quiz` will "
                    "follow up on it.")
            mx.post_notice(dm, body, formatted_body=mx.md_to_html(body))
            return {"ok": True, "message": "no active topic"}
    topic = _get_topic(topic_id)
    if not topic:
        return {"ok": False, "error": f"unknown topic {topic_id!r}"}
    snippets = _snippets_for_topic(topic)
    if not snippets:
        return {"ok": False, "error": f"no source content for {topic_id}"}

    # Pick target Bloom from mastery + repetition.
    conn = _db()
    try:
        row = _get_progress_row(conn, operator, topic_id)
    finally:
        conn.close()
    mastery = float(row.get("mastery_score") or 0.0)
    reps = int(row.get("repetition_count") or 0)
    target = select_target_bloom(mastery, reps)

    q = quiz_generator.generate(topic_id, target, snippets)
    if q is None:
        return {"ok": False, "error": "quiz generation failed (hallucination gate or Ollama unavailable)"}

    # Persist session
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO learning_sessions "
            "(operator, topic, session_type, bloom_level, started_at, "
            " question_payload, schema_version) "
            "VALUES (?, ?, 'quiz', ?, CURRENT_TIMESTAMP, ?, ?)",
            (operator, topic_id, target, json.dumps(q.to_dict()),
             schema_current("learning_sessions")),
        )
        session_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    dm = mx.resolve_dm(operator)
    body = _render_quiz(session_id, q)
    evt = mx.post_message(dm, body, formatted_body=mx.md_to_html(body))
    if source_room and source_room == CLASSROOM_ROOM_ID:
        mx.post_notice(source_room, f"📨 {operator} — quiz sent to your DM.")
    return {"ok": True, "session_id": session_id, "bloom": target, "dm_event": evt}


# ── Subcommand: grade ─────────────────────────────────────────────────────

_CHAT_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "at", "by", "for", "from", "with", "without",
    "into", "onto", "up", "down", "out", "over", "under", "and", "or", "nor",
    "but", "yet", "so", "because", "although", "if", "when", "while",
    "as", "than", "that", "this", "these", "those", "there", "here",
    "what", "which", "who", "whom", "whose", "where", "why", "how",
    "do", "does", "did", "doing", "have", "has", "had", "having",
    "can", "could", "will", "would", "should", "may", "might", "must",
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his",
    "she", "her", "it", "its", "they", "them", "their",
    "about", "also", "any", "just", "only", "some", "such", "very",
}


def _keywords(text: str) -> set[str]:
    """Bag of lowercase content words from the question. Used to score
    curriculum topics against the operator's query."""
    REDACTED_a7b84d63 as _re
    toks = _re.findall(r"[A-Za-z0-9]{3,}", text.lower())
    return {t for t in toks if t not in _CHAT_STOP_WORDS}


def _score_topic(topic: dict, kws: set[str]) -> int:
    """Higher = better match. Title + id carry most weight, sources/section
    are tiebreakers. Zero if no overlap."""
    if not kws:
        return 0
    title = (topic.get("title", "") + " " + topic.get("id", "")).lower()
    score = sum(2 for kw in kws if kw in title)
    for src in topic.get("sources", []):
        section = str(src.get("section") or src.get("anchor") or "").lower()
        path = str(src.get("path") or "").lower()
        score += sum(1 for kw in kws if kw in section or kw in path)
    return score


def _semantic_snippets(question: str, limit: int = 6
                       ) -> list[quiz_generator.Snippet]:
    """Nearest-neighbor lookup over wiki_articles embeddings.

    Returns [] (not None) when:
      - the embed call fails (Ollama unreachable, breaker open)
      - no article has an embedding yet
      - the top similarity is below 0.25 (noise floor)
    In those cases the caller drops through to the keyword fallback.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_kbs", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "kb-semantic-search.py"))
        if spec is None or spec.loader is None:
            return []
        kbs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kbs)
    except Exception as e:
        print(f"[chat] semantic import failed: {e}", file=sys.stderr)
        return []

    try:
        q_emb = kbs.embed_query(question)
    except Exception as e:
        print(f"[chat] embed_query failed: {e}", file=sys.stderr)
        return []
    if not q_emb:
        return []

    conn = _db()
    try:
        rows = conn.execute(
            "SELECT path, title, section, content_preview, embedding "
            "FROM wiki_articles WHERE embedding != '' "
        ).fetchall()
    finally:
        conn.close()

    _WIKI_HEADS = {"hosts", "services", "patterns", "incidents",
                   "operations", "health", "lab", "topology", "decisions"}

    def _is_wiki_served(path: str) -> bool:
        if path.startswith(("docs/", "wiki/", "memory/",
                            "project-docs/", "openclaw/")):
            return True
        if path in ("README.extensive.md", "README.md"):
            return True
        head = path.split("/", 1)[0]
        return head in _WIKI_HEADS

    def _is_index_only(path: str) -> bool:
        """Pure index/TOC pages — clickable but pointless as citations or
        see-also reading. Examples: `memory/MEMORY.md` (operator memory
        index, literally a markdown table of file links), per-section
        wiki TOCs like `incidents/index.md`, root landing `index.md` /
        `README.md`. Filter these before the LLM ever sees them so we
        don't waste a top-K slot on content-free metadata.
        """
        p = (path or "").split("#", 1)[0]
        if not p:
            return True
        base = p.rsplit("/", 1)[-1]
        return base in ("MEMORY.md", "index.md", "README.md")

    def _load_file_excerpt(raw_path: str, max_chars: int = 1500) -> str:
        """When content_preview is empty/thin, read the actual file so the
        LLM has something concrete to ground on.

        Content lives in several places — the repo tree for docs/wiki/
        openclaw/project-docs, ~/.claude/projects/.../memory/ for operator
        memory.
        """
        file_path = raw_path.split("#", 1)[0]
        if not file_path:
            return ""
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        memory_root = os.path.expanduser(
            "~/.claude/projects/-home-app-user-gitlab-n8n-claude-gateway"
        )
        candidates = [os.path.join(repo, file_path)]
        if file_path.startswith("memory/"):
            candidates.append(os.path.join(memory_root, file_path))
        if file_path.startswith("project-docs/"):
            # Wiki rewrites project-docs/foo → repo root /foo AND
            # project-docs/claude/bar → repo root /.claude/bar.
            rel = file_path[len("project-docs/"):]
            candidates.append(os.path.join(repo, rel))
            if rel.startswith("claude/"):
                candidates.append(os.path.join(repo, "." + rel))
        if file_path.split("/", 1)[0] in _WIKI_HEADS:
            candidates.append(os.path.join(repo, "wiki", file_path))
        for c in candidates:
            try:
                if os.path.isfile(c):
                    with open(c) as f:
                        return f.read(max_chars * 2)[:max_chars]
            except OSError:
                continue
        return ""

    scored = []
    for row in rows:
        raw_path = row["path"] or ""
        # Index-only pages (TOCs, operator memory index) are clickable but
        # substance-free — never useful as an answer citation or see-also.
        if _is_index_only(raw_path):
            continue
        try:
            emb = json.loads(row["embedding"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not emb:
            continue
        score = kbs.cosine_similarity(q_emb, emb)
        # Small bias toward wiki-served paths — breaks ties, doesn't
        # override genuinely better private-source content.
        if _is_wiki_served(raw_path):
            score += 0.03
        scored.append((score, row))
    if not scored:
        return []
    scored.sort(key=lambda x: -x[0])

    out: list[quiz_generator.Snippet] = []
    seen_keys: set[tuple] = set()
    # Pass 1: top-K by score — operator gets the best grounding the LLM
    # can use, regardless of whether the source is wiki-served.
    for score, row in scored:
        if score < 0.25:
            break
        raw_path = row["path"] or ""
        file_path = raw_path.split("#", 1)[0]
        section = row["section"] or row["title"] or ""
        key = (file_path, section)
        if not file_path or key in seen_keys:
            continue
        seen_keys.add(key)
        preview = row["content_preview"] or ""
        # content_preview is empty on many indexed articles (especially
        # wiki/services/* + wiki/hosts/*). Fall back to the source file so
        # the LLM has real text instead of just a title.
        if len(preview) < 200:
            excerpt = _load_file_excerpt(raw_path)
            if excerpt:
                preview = excerpt
        if not preview:
            preview = row["title"] or section or file_path
        out.append(quiz_generator.Snippet(
            source_path=file_path,
            section=section,
            verbatim_text=preview[:1500],
        ))
        if len(out) >= limit:
            break

    # Pass 2: guarantee at least one wiki-served hit so SOME citation
    # in the answer will be clickable, even if all the raw top-K were
    # private memory/ paths. Search further down the ranking for the
    # best wiki candidate above the noise floor.
    if not any(_is_wiki_served(s.source_path) for s in out) and len(out) < limit:
        for score, row in scored:
            raw_path = row["path"] or ""
            if score < 0.2 or not _is_wiki_served(raw_path):
                continue
            file_path = raw_path.split("#", 1)[0]
            section = row["section"] or row["title"] or ""
            key = (file_path, section)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            preview = row["content_preview"] or ""
            if len(preview) < 200:
                excerpt = _load_file_excerpt(raw_path)
                if excerpt:
                    preview = excerpt
            if not preview:
                preview = row["title"] or section or file_path
            out.append(quiz_generator.Snippet(
                source_path=file_path,
                section=section,
                verbatim_text=preview[:1500],
            ))
            break
    return out[:limit]


def _chat_snippets(operator: str, question: str, limit: int = 6
                   ) -> list[quiz_generator.Snippet]:
    """Pick up to `limit` curriculum snippets to ground the chat answer.

    Ordered strategy:
      0. Semantic nearest-neighbor over wiki_articles embeddings — handles
         paraphrased questions the keyword step would miss. When the embed
         backend is down or no article scores above the noise floor, this
         returns empty and we fall through to keyword matching.
      1. Score every curriculum topic by keyword-overlap with the
         question. Topics with score > 0 are highest priority — the
         operator is probably asking about those.
      2. The operator's most-recent learning_sessions topics — chat
         is often a follow-up to a lesson/quiz.
      3. First unseen curriculum topics so a fresh operator asking a
         cold question isn't refused for lack of context.

    Cap at `limit` snippets so the Ollama prompt fits under num_ctx.
    """
    semantic = _semantic_snippets(question, limit)
    if semantic:
        return semantic
    curriculum = _load_curriculum()
    topics = curriculum.get("topics", [])
    kws = _keywords(question)

    scored = sorted(
        [(t, _score_topic(t, kws)) for t in topics],
        key=lambda x: -x[1],
    )
    keyword_hits = [t for t, s in scored if s > 0]

    conn = _db()
    try:
        recent_rows = conn.execute(
            "SELECT DISTINCT topic FROM learning_sessions WHERE operator=? "
            "ORDER BY started_at DESC LIMIT ?",
            (operator, limit * 2),
        ).fetchall()
    finally:
        conn.close()
    recent_ids = [r[0] for r in recent_rows if r[0]]
    recent_topics = [_get_topic(tid) for tid in recent_ids]
    recent_topics = [t for t in recent_topics if t]

    out: list[quiz_generator.Snippet] = []
    seen_topics: set[str] = set()
    # Union: keyword hits first, then recent, then curriculum head.
    ordered = keyword_hits + [t for t in recent_topics if t not in keyword_hits]
    if len(ordered) < limit:
        for t in topics:
            if t not in ordered:
                ordered.append(t)

    for t in ordered:
        tid = t["id"]
        if tid in seen_topics:
            continue
        seen_topics.add(tid)
        for s in _snippets_for_topic(t):
            out.append(s)
            if len(out) >= limit:
                return out
    return out[:limit]


# Per-operator chat rate limit. Defensive — teacher_chat runs through
# the shared Ollama instance and each call costs local GPU time.
CHAT_RATE_WINDOW_SECONDS = int(os.environ.get("TEACHER_CHAT_RATE_WINDOW", "3600"))
CHAT_RATE_LIMIT_PER_WINDOW = int(os.environ.get("TEACHER_CHAT_RATE_LIMIT", "30"))


def _chat_rate_ok(operator: str) -> tuple[bool, int]:
    """Returns (allowed, count_in_window). Rolling-window over
    learning_sessions WHERE session_type='chat'."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM learning_sessions "
            "WHERE operator=? AND session_type='chat' "
            "AND started_at >= datetime('now', ?)",
            (operator, f"-{CHAT_RATE_WINDOW_SECONDS} seconds"),
        ).fetchone()
    finally:
        conn.close()
    n = int(row[0] if row else 0)
    return n < CHAT_RATE_LIMIT_PER_WINDOW, n


def _render_chat(answer: teacher_chat.ChatAnswer,
                 *, snippets: Optional[list[quiz_generator.Snippet]] = None) -> str:
    lines = ["💬  **Teacher**", ""]
    if answer.refused:
        lines.append(f"🤔  I can't ground that in your current curriculum.")
        if answer.refusal_reason:
            lines.append("")
            lines.append(f"_{answer.refusal_reason}_")
        lines.append("")
        lines.append("Tip: `!progress` shows which topics you've covered; "
                     "`!learn <topic-id>` picks a specific one.")
        return "\n".join(lines)
    if answer.clarifying_question:
        lines.append(answer.answer or "")
        lines.append("")
        lines.append(f"**Could you clarify?** {answer.clarifying_question}")
    else:
        lines.append(answer.answer)

    cited_files: set[str] = set()
    if answer.cited_snippets:
        lines.append("")
        lines.append("**Sources**")
        for c in answer.cited_snippets:
            path = c.get("source_path", "")
            if not path or path in cited_files:
                continue
            cited_files.add(path)
            lines.append(f"- {_link(path, c.get('section', ''))}")

    # Surface wiki-served snippets the LLM was given context on but didn't
    # directly cite — gives the operator clickable follow-up reading
    # without the LLM having to falsely claim a citation it didn't use.
    if snippets:
        wiki_extras = []
        seen_extra = set(cited_files)
        for s in snippets:
            if s.source_path in seen_extra:
                continue
            # Only promote wiki-served paths (others already render as plain code).
            if _wurl(s.source_path, s.section) is None:
                continue
            seen_extra.add(s.source_path)
            wiki_extras.append(s)
        if wiki_extras:
            lines.append("")
            lines.append("**See also**")
            for s in wiki_extras[:3]:
                lines.append(f"- {_link(s.source_path, s.section)}")
    return "\n".join(lines)


def cmd_chat(operator: str, question: str, *, source_room: str = "") -> dict:
    """Curriculum-grounded free chat. Hallucination-gated: refuses rather
    than inventing facts outside the operator's curriculum sources.

    Dispatched automatically by cmd_grade(sid=0) when there's no open
    quiz, OR via an explicit --chat CLI invocation.
    """
    if not _check_auth(operator):
        return {"ok": False, "error": "not authorised"}
    question = (question or "").strip()
    if not question:
        return {"ok": False, "error": "empty question"}

    # Per-operator rate limit — defensive against runaway loops.
    ok, count = _chat_rate_ok(operator)
    if not ok:
        dm = mx.resolve_dm(operator)
        body = (f"🛑  Chat rate limit reached "
                f"({count}/{CHAT_RATE_LIMIT_PER_WINDOW} messages in the "
                f"last {CHAT_RATE_WINDOW_SECONDS // 60} min). Try `!quiz` or "
                f"`!learn` instead — those have no limit.")
        mx.post_notice(dm, body, formatted_body=mx.md_to_html(body))
        return {"ok": True, "message": "rate limited",
                "chat_count_in_window": count}

    snippets = _chat_snippets(operator, question)
    if not snippets:
        dm = mx.resolve_dm(operator)
        body = ("🌱  No curriculum context loaded yet. Type `!learn` first so "
                "I have something to ground your questions in.")
        mx.post_notice(dm, body, formatted_body=mx.md_to_html(body))
        return {"ok": True, "message": "no curriculum context"}

    # Persist the chat turn as a learning_sessions row with session_type='chat'
    # so the exporter can count chat volume without conflating with quizzes.
    conn = _db()
    try:
        cur = conn.execute(
            "INSERT INTO learning_sessions "
            "(operator, topic, session_type, started_at, question_payload, schema_version) "
            "VALUES (?, ?, 'chat', CURRENT_TIMESTAMP, ?, ?)",
            (operator, snippets[0].source_path, question[:500],
             schema_current("learning_sessions")),
        )
        chat_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    ans = teacher_chat.chat(question, snippets)
    if ans is None:
        body = ("🔌  Teacher chat is offline right now (Ollama unreachable or "
                "grounding gate rejected 3 attempts). Try `!learn` for a "
                "deterministic lesson instead.")
        dm = mx.resolve_dm(operator)
        mx.post_notice(dm, body, formatted_body=mx.md_to_html(body))
        return {"ok": False, "error": "chat generation failed"}

    # Post the answer to Matrix FIRST — the user-visible reply matters more
    # than the audit row. If the UPDATE below runs into a long DB lock, the
    # operator still gets their answer instead of a silent crash (root cause
    # of the 2026-04-23 "what is judge" orphan — Ollama ran to completion,
    # then the final UPDATE hit sqlite3.OperationalError: database is locked,
    # the process raised, mx.post_message was never reached).
    dm = mx.resolve_dm(operator)
    body = _render_chat(ans, snippets=snippets)
    evt = mx.post_message(dm, body, formatted_body=mx.md_to_html(body))

    # Best-effort audit: mark the session as completed. busy_timeout=30s
    # in _db() covers most contention; if this still fails, the user's
    # reply is already delivered and we log but don't re-raise.
    try:
        conn = _db()
        try:
            conn.execute(
                "UPDATE learning_sessions SET completed_at=CURRENT_TIMESTAMP, "
                "answer_payload=? WHERE id=?",
                (json.dumps(ans.to_dict())[:8000], chat_id),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        print(f"[cmd_chat] UPDATE learning_sessions #{chat_id} failed "
              f"(reply already delivered): {e}", file=sys.stderr)
    return {
        "ok": True,
        "refused": ans.refused,
        "cited_count": len(ans.cited_snippets),
        "chat_session_id": chat_id,
        "dm_event": evt,
    }


def cmd_grade(operator: str, session_id: int, answer: str) -> dict:
    if not _check_auth(operator):
        return {"ok": False, "error": "not authorised"}
    conn = _db()
    try:
        if session_id and session_id > 0:
            row = conn.execute(
                "SELECT * FROM learning_sessions WHERE id=? AND operator=?",
                (session_id, operator),
            ).fetchone()
        else:
            # session_id == 0 means "latest open quiz for this operator".
            # Covers free-text DM replies where matrix-bridge can't know the id.
            row = conn.execute(
                "SELECT * FROM learning_sessions "
                "WHERE operator=? AND session_type='quiz' AND completed_at IS NULL "
                "ORDER BY started_at DESC LIMIT 1",
                (operator,),
            ).fetchone()
    finally:
        conn.close()
    if not row:
        if session_id and session_id > 0:
            return {"ok": False, "error": f"session {session_id} not found for this operator"}
        # No open quiz → fall through to curriculum-grounded chat.
        # cmd_grade(sid=0) is how matrix-bridge routes ANY free-text DM
        # reply; without an open quiz, the operator is asking a question
        # rather than answering one.
        return cmd_chat(operator, answer)
    row = dict(row)
    if row["session_type"] != "quiz":
        return {"ok": False, "error": "session is not a quiz"}
    if row.get("completed_at"):
        return {"ok": False, "error": "session already graded"}

    question = json.loads(row["question_payload"])
    g = quiz_grader.grade(question, answer)
    if g is None:
        return {"ok": False, "error": "grading failed (Ollama unavailable or invalid output)"}

    # Invariant #4: low grader confidence means the grader itself is asking for
    # clarification — the score is uncertain, so we close the session and record
    # the attempt but DO NOT move mastery, SM-2 schedule, or Bloom progression.
    low_conf = g.grader_confidence < quiz_grader.CONFIDENCE_THRESHOLD

    # Do all DB work in a best-effort block. If SQLite is locked beyond the
    # 30s busy_timeout (other teacher run, wiki-compile, etc.), log it but
    # still deliver the grade to Matrix — a silent crash that shows no reply
    # is strictly worse than a reply with stale progress state.
    db_ok = True
    try:
        conn = _db()
        try:
            prog = _get_progress_row(conn, operator, row["topic"])
            old_mastery = float(prog.get("mastery_score") or 0.0)
            quality = quality_from_score(g.score_0_to_1)
            highest = prog.get("highest_bloom_reached") or "recall"

            quiz_history = json.loads(prog.get("quiz_history") or "[]")
            quiz_history.append({
                "session_id": row["id"],
                "score": g.score_0_to_1,
                "grader_confidence": g.grader_confidence,
                "low_conf_skip": low_conf,
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
            })

            if low_conf:
                # Record the attempt but leave schedule + mastery alone.
                new_card = Card(
                    easiness_factor=float(prog.get("easiness_factor") or 2.5),
                    interval_days=int(prog.get("interval_days") or 1),
                    repetition_count=int(prog.get("repetition_count") or 0),
                    next_due=datetime.datetime.utcnow(),
                )
                new_mastery = old_mastery
                _upsert_progress(conn, operator, row["topic"], {
                    "last_reviewed": datetime.datetime.utcnow().isoformat(),
                    "quiz_history": json.dumps(quiz_history[-20:]),
                })
            else:
                card = Card(
                    easiness_factor=float(prog.get("easiness_factor") or 2.5),
                    interval_days=int(prog.get("interval_days") or 1),
                    repetition_count=int(prog.get("repetition_count") or 0),
                    next_due=datetime.datetime.utcnow(),
                )
                new_card = sm2_schedule(card, quality)
                # Mastery EMA toward score with smoothing 0.3
                new_mastery = max(0.0, min(1.0, 0.7 * old_mastery + 0.3 * g.score_0_to_1))
                if is_advance(highest, g.bloom_demonstrated):
                    highest = g.bloom_demonstrated
                _upsert_progress(conn, operator, row["topic"], {
                    "easiness_factor": new_card.easiness_factor,
                    "interval_days": new_card.interval_days,
                    "repetition_count": new_card.repetition_count,
                    "next_due": new_card.next_due.isoformat(),
                    "mastery_score": new_mastery,
                    "highest_bloom_reached": highest,
                    "last_reviewed": datetime.datetime.utcnow().isoformat(),
                    "quiz_history": json.dumps(quiz_history[-20:]),
                })

            conn.execute(
                "UPDATE learning_sessions SET completed_at=CURRENT_TIMESTAMP, "
                "quiz_score=?, answer_payload=?, judge_feedback=?, citation_flag=? "
                "WHERE id=?",
                (g.score_0_to_1,
                 json.dumps({"answer_text": answer, "submitted_at": datetime.datetime.utcnow().isoformat() + "Z"}),
                 g.feedback,
                 1 if g.citation_check.get("extra_claims") else 0,
                 row["id"]),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        db_ok = False
        print(f"[cmd_grade] DB write failed for session #{row['id']} "
              f"(reply will still be delivered): {e}", file=sys.stderr)
        # Fall-through values so the render + Matrix post below can proceed.
        new_card = Card(
            easiness_factor=2.5, interval_days=1, repetition_count=0,
            next_due=datetime.datetime.utcnow(),
        )
        old_mastery = new_mastery = 0.0
        quality = quality_from_score(g.score_0_to_1)

    dm = mx.resolve_dm(operator)
    body = _render_grade(
        g, new_card.interval_days,
        old_mastery, new_mastery,
        _band(old_mastery), _band(new_mastery),
        source_snippets=question.get("source_snippets") or [],
    )
    evt = mx.post_message(dm, body, formatted_body=mx.md_to_html(body))
    return {
        "ok": True,
        "score": g.score_0_to_1,
        "quality": quality,
        "next_due_days": new_card.interval_days,
        "dm_event": evt,
    }


# ── Subcommand: progress ──────────────────────────────────────────────────

def cmd_progress(operator: str, *, public: bool = False,
                 source_room: str = "") -> dict:
    if not _check_auth(operator):
        return {"ok": False, "error": "not authorised"}
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM learning_progress WHERE operator=?",
            (operator,),
        ).fetchall()]
    finally:
        conn.close()
    total = len(rows)
    mastered = sum(1 for r in rows if (r.get("mastery_score") or 0) >= 0.9)
    analytical = sum(1 for r in rows if 0.7 <= (r.get("mastery_score") or 0) < 0.9)
    conceptual = sum(1 for r in rows if 0.4 <= (r.get("mastery_score") or 0) < 0.7)
    foundation = sum(1 for r in rows if 0 < (r.get("mastery_score") or 0) < 0.4)
    started = mastered + analytical + conceptual + foundation
    due = len(due_topics(rows, datetime.datetime.utcnow()))
    body = "\n".join([
        f"📊  **Progress** for `{operator}`",
        "",
        f"  Mastered (≥0.9)      {mastered}",
        f"  Analytical (0.7-0.9) {analytical}",
        f"  Conceptual (0.4-0.7) {conceptual}",
        f"  Foundation (<0.4)    {foundation}",
        f"  Not started          {total - started}",
        "",
        f"  Due today: {due}",
    ])
    html_body = mx.md_to_html(body)
    if public:
        if not mx.is_public(operator):
            return {"ok": False, "error": "public sharing is OFF. Enable with `!learn public on`."}
        mx.post_notice(CLASSROOM_ROOM_ID, body, formatted_body=html_body)
        return {"ok": True, "posted_to": "classroom"}
    dm = mx.resolve_dm(operator)
    mx.post_message(dm, body, formatted_body=html_body)
    return {"ok": True, "posted_to": "dm"}


# ── Subcommand: class-digest ──────────────────────────────────────────────

def cmd_class_digest() -> dict:
    conn = _db()
    try:
        total_ops = conn.execute("SELECT COUNT(*) FROM teacher_operator_dm").fetchone()[0]
        total_mastered = conn.execute(
            "SELECT COUNT(*) FROM learning_progress WHERE mastery_score >= 0.9"
        ).fetchone()[0]
        total_sessions_7d = conn.execute(
            "SELECT COUNT(*) FROM learning_sessions "
            "WHERE completed_at >= datetime('now', '-7 days')"
        ).fetchone()[0]
    finally:
        conn.close()
    body = "\n".join([
        "📅  **Class digest — last 7 days**",
        "",
        f"  Members        {total_ops}",
        f"  Topics mastered (all-time aggregate)  {total_mastered}",
        f"  Sessions completed this week  {total_sessions_7d}",
        "",
        "Type `!progress` in your DM to see your own numbers.",
    ])
    mx.post_notice(CLASSROOM_ROOM_ID, body, formatted_body=mx.md_to_html(body))
    _touch_last_run("class_digest")
    return {"ok": True, "posted": "classroom"}


# ── Subcommand: morning-nudge ─────────────────────────────────────────────

def cmd_morning_nudge() -> dict:
    conn = _db()
    try:
        ops = [r[0] for r in conn.execute(
            "SELECT operator_mxid FROM teacher_operator_dm"
        ).fetchall()]
    finally:
        conn.close()
    nudged = 0
    for op in ops:
        conn = _db()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM learning_progress WHERE operator=? AND paused=0",
                (op,),
            ).fetchall()]
        finally:
            conn.close()
        due = due_topics(rows, datetime.datetime.utcnow())[:5]
        if not due:
            continue
        lines = [f"☀️  **Good morning.** {len(due)} topics due today:", ""]
        for i, r in enumerate(due, 1):
            topic = _get_topic(r["topic"]) or {}
            lines.append(f"  {i}. {topic.get('title', r['topic'])}")
        lines.append("")
        lines.append("Reply `!learn` in this DM to start.")
        dm = mx.resolve_dm(op)
        body = "\n".join(lines)
        try:
            mx.post_notice(dm, body, formatted_body=mx.md_to_html(body))
            nudged += 1
        except mx.MatrixError as e:
            print(f"[morning-nudge] {op}: {e}", file=sys.stderr)
    _touch_last_run("morning_nudge")
    return {"ok": True, "nudged": nudged}


# ── Subcommand: pause/resume/public ───────────────────────────────────────

def cmd_set_flag(operator: str, field: str, value: int) -> dict:
    if not _check_auth(operator):
        return {"ok": False, "error": "not authorised"}
    conn = _db()
    try:
        row = _get_progress_row(conn, operator, "__fake__")  # noop to init op
        conn.execute(
            f"UPDATE learning_progress SET {field}=? WHERE operator=?",
            (value, operator),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "set": {field: value}}


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--operator", default="")
    ap.add_argument("--topic", default="")
    ap.add_argument("--session-id", type=int, default=0)
    ap.add_argument("--answer", default="")
    ap.add_argument("--message", default="")
    ap.add_argument("--source-room", default="")
    ap.add_argument("--public", action="store_true")

    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument("--resolve-dm", action="store_true")
    sub.add_argument("--next", action="store_true")
    sub.add_argument("--lesson", action="store_true")
    sub.add_argument("--quiz", action="store_true")
    sub.add_argument("--grade", action="store_true")
    sub.add_argument("--chat", action="store_true")
    sub.add_argument("--progress", action="store_true")
    sub.add_argument("--class-digest", action="store_true")
    sub.add_argument("--morning-nudge", action="store_true")
    sub.add_argument("--pause", action="store_true")
    sub.add_argument("--resume", action="store_true")
    sub.add_argument("--public-on", action="store_true")
    sub.add_argument("--public-off", action="store_true")

    args = ap.parse_args()

    if args.resolve_dm:
        if not args.operator:
            print(json.dumps({"ok": False, "error": "--operator required"}))
            return 2
        dm = mx.resolve_dm(args.operator)
        print(json.dumps({"ok": True, "dm_room_id": dm}))
        return 0

    if args.next:
        print(json.dumps(cmd_next(args.operator, source_room=args.source_room)))
        return 0

    if args.lesson:
        print(json.dumps(cmd_lesson(args.operator, args.topic, source_room=args.source_room)))
        return 0

    if args.quiz:
        print(json.dumps(cmd_quiz(args.operator, args.topic, source_room=args.source_room)))
        return 0

    if args.grade:
        print(json.dumps(cmd_grade(args.operator, args.session_id, args.answer)))
        return 0

    if args.chat:
        msg = args.message or args.answer
        print(json.dumps(cmd_chat(args.operator, msg, source_room=args.source_room)))
        return 0

    if args.progress:
        print(json.dumps(cmd_progress(args.operator, public=args.public, source_room=args.source_room)))
        return 0

    if args.class_digest:
        print(json.dumps(cmd_class_digest()))
        return 0

    if args.morning_nudge:
        print(json.dumps(cmd_morning_nudge()))
        return 0

    if args.pause:
        print(json.dumps(cmd_set_flag(args.operator, "paused", 1)))
        return 0
    if args.resume:
        print(json.dumps(cmd_set_flag(args.operator, "paused", 0)))
        return 0
    if args.public_on:
        mx.set_public_sharing(args.operator, True)
        print(json.dumps({"ok": True, "public": True}))
        return 0
    if args.public_off:
        mx.set_public_sharing(args.operator, False)
        print(json.dumps({"ok": True, "public": False}))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
