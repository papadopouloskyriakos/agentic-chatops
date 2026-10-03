"""Minimal Matrix client-server API helper for the teacher agent.

Scope is deliberately narrow — just the four things the teacher needs:

  · membership_of(room_id)       — who is in #learning (authorisation gate)
  · resolve_dm(operator_mxid)    — look up or lazy-create the DM room for an operator
  · post_message(room_id, body)  — send plain-text + formatted_body m.room.message
  · post_notice(room_id, body)   — m.notice variant (no ping sound)

No encryption support on purpose (n8n bridge limitation; #learning and DMs
are unencrypted per the IFRNLLEI01PRD-653 decision).

Credentials:
  MATRIX_HOMESERVER  e.g. https://matrix.example.net
  MATRIX_CLAUDE_TOKEN  bearer token of @claude:matrix.example.net

Both are read from scripts/../.env or the process environment.
"""
from __future__ import annotations

import html as _html
import json
import os
REDACTED_a7b84d63
import sys
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Iterable, Optional


DB_PATH = os.environ.get(
    "GATEWAY_DB",
    os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db"),
)


def _read_env(name: str) -> str:
    """Env-first, fall back to .env in the repo root."""
    v = os.environ.get(name, "")
    if v:
        return v
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".env",
    )
    if os.path.exists(env_path):
        try:
            for line in open(env_path):
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


def _homeserver() -> str:
    return (_read_env("MATRIX_HOMESERVER")
            or _read_env("MATRIX_URL")
            or "https://matrix.example.net").rstrip("/")


def _token() -> str:
    t = _read_env("MATRIX_CLAUDE_TOKEN")
    if not t:
        # Some prior scripts wrote the token to a file; fall back.
        p = os.path.expanduser("~/.matrix-claude-token")
        if os.path.exists(p):
            try:
                return open(p).read().strip()
            except OSError:
                pass
    return t


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


class MatrixError(RuntimeError):
    """Raised for non-recoverable Matrix API failures."""


def _request(method: str, path: str, body: Optional[dict] = None,
             *, timeout: int = 20) -> dict:
    url = f"{_homeserver()}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500] if e.fp else str(e)
        raise MatrixError(f"{method} {path} -> HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        raise MatrixError(f"{method} {path} -> {e}") from e


# ── Membership / authorisation ─────────────────────────────────────────────

def members_of(room_id: str) -> list[str]:
    """Return the list of joined user mxids in `room_id`."""
    esc = urllib.parse.quote(room_id, safe="")
    data = _request("GET", f"/_matrix/client/v3/rooms/{esc}/joined_members")
    return list((data.get("joined") or {}).keys())


def is_authorised(operator_mxid: str, classroom_room_id: str,
                  *, _members_fn=None) -> bool:
    """True iff `operator_mxid` is a joined member of `classroom_room_id`.

    `_members_fn` is an optional test injection for offline QA.
    """
    fn = _members_fn or members_of
    try:
        return operator_mxid in fn(classroom_room_id)
    except MatrixError:
        # Fail CLOSED on errors — don't authorise if Matrix is unreachable.
        return False


# ── DM resolution (lazy create, cached in teacher_operator_dm) ─────────────

import urllib.parse  # noqa: E402 — kept local to the module


def _db():
    return sqlite3.connect(DB_PATH)


def resolve_dm(operator_mxid: str, *, _create_fn=None) -> str:
    """Return the DM room id for the given operator, creating it if needed.

    `_create_fn` is an optional test injection: a callable taking the mxid
    and returning a room_id string (bypasses the live Matrix call).
    """
    conn = _db()
    try:
        row = conn.execute(
            "SELECT dm_room_id FROM teacher_operator_dm WHERE operator_mxid=?",
            (operator_mxid,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE teacher_operator_dm SET last_active=CURRENT_TIMESTAMP "
                "WHERE operator_mxid=?",
                (operator_mxid,),
            )
            conn.commit()
            return row[0]

        # Lazy create
        if _create_fn is not None:
            room_id = _create_fn(operator_mxid)
        else:
            resp = _request("POST", "/_matrix/client/v3/createRoom", {
                "preset": "trusted_private_chat",
                "is_direct": True,
                "invite": [operator_mxid],
                "name": f"Teacher — {operator_mxid}",
                "topic": "Private teacher-agent DM. Lessons, quizzes, and your progress.",
                "creation_content": {"m.federate": False},
            })
            room_id = resp.get("room_id")
            if not room_id:
                raise MatrixError(f"createRoom returned no room_id: {resp}")
        conn.execute(
            "INSERT INTO teacher_operator_dm (operator_mxid, dm_room_id, schema_version) "
            "VALUES (?, ?, 1)",
            (operator_mxid, room_id),
        )
        conn.commit()
        return room_id
    finally:
        conn.close()


def set_public_sharing(operator_mxid: str, public: bool) -> None:
    """Toggle the !progress-public / leaderboard opt-in for an operator."""
    conn = _db()
    try:
        conn.execute(
            "UPDATE teacher_operator_dm SET public_sharing=?, last_active=CURRENT_TIMESTAMP "
            "WHERE operator_mxid=?",
            (1 if public else 0, operator_mxid),
        )
        conn.commit()
    finally:
        conn.close()


def is_public(operator_mxid: str) -> bool:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT public_sharing FROM teacher_operator_dm WHERE operator_mxid=?",
            (operator_mxid,),
        ).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


# ── Markdown → HTML (minimal, for teacher lesson bodies) ───────────────────

_CODE_FENCE_RE = re.compile(r"^```([a-zA-Z0-9_-]*)\s*$")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC_STAR_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_ITALIC_UND_RE = re.compile(r"(?<![A-Za-z0-9_])_([^_\n]+)_(?![A-Za-z0-9_])")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*$")


def _inline_md_to_html(text: str) -> str:
    """Escape + apply inline markdown (code/bold/italic/link) in order.

    Code is handled first and its content is placeholdered so later rules
    don't mangle asterisks or backticks inside code spans.
    """
    placeholders: list[str] = []

    def _code_sub(m: re.Match) -> str:
        placeholders.append(_html.escape(m.group(1)))
        return f"\0CODE{len(placeholders) - 1}\0"

    work = _INLINE_CODE_RE.sub(_code_sub, text)
    work = _html.escape(work)
    work = _BOLD_RE.sub(r"<strong>\1</strong>", work)
    work = _ITALIC_STAR_RE.sub(r"<em>\1</em>", work)
    work = _ITALIC_UND_RE.sub(r"<em>\1</em>", work)
    work = _LINK_RE.sub(r'<a href="\2">\1</a>', work)
    # Put code spans back — escape ran on the surrounding text, not on them.
    for i, esc in enumerate(placeholders):
        work = work.replace(f"\0CODE{i}\0", f"<code>{esc}</code>")
    return work


def md_to_html(markdown: str) -> str:
    """Convert a narrow subset of markdown to Matrix-friendly HTML.

    Supports: ATX headings (1-4), bold/italic/inline-code/links, fenced code
    blocks, bullet lists (`- ` / `* `), blockquotes (`> `), tables (passed
    through as `<pre>`), paragraphs separated by blank lines.
    Returns a string the Element client renders well.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    in_list = False
    para: list[str] = []
    in_table = False
    table_buf: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + "<br/>".join(_inline_md_to_html(p) for p in para) + "</p>")
            para = []

    def flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def _split_row(row: str) -> list[str]:
        s = row.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    def _is_separator_row(row: str) -> bool:
        cells = _split_row(row)
        if not cells:
            return False
        return all(bool(re.match(r"^:?-{3,}:?$", c)) for c in cells)

    def flush_table():
        nonlocal in_table, table_buf
        if not in_table:
            return
        # Valid markdown table needs row[0]=header, row[1]=separator, row[2..]=data.
        if len(table_buf) >= 2 and _is_separator_row(table_buf[1]):
            header = _split_row(table_buf[0])
            pieces = ["<table><thead><tr>"]
            pieces.extend(f"<th>{_inline_md_to_html(c)}</th>" for c in header)
            pieces.append("</tr></thead>")
            if len(table_buf) > 2:
                pieces.append("<tbody>")
                for row in table_buf[2:]:
                    cells = _split_row(row)
                    # Pad/truncate to match header width
                    if len(cells) < len(header):
                        cells += [""] * (len(header) - len(cells))
                    else:
                        cells = cells[:len(header)]
                    pieces.append("<tr>")
                    pieces.extend(f"<td>{_inline_md_to_html(c)}</td>" for c in cells)
                    pieces.append("</tr>")
                pieces.append("</tbody>")
            pieces.append("</table>")
            out.append("".join(pieces))
        else:
            # Not a well-formed table — fall back to <pre> so the content
            # at least shows up faithfully instead of being silently dropped.
            out.append("<pre>" + _html.escape("\n".join(table_buf)) + "</pre>")
        table_buf = []
        in_table = False

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # Fenced code block
        if _CODE_FENCE_RE.match(stripped):
            flush_para(); flush_list(); flush_table()
            lang = _CODE_FENCE_RE.match(stripped).group(1)
            i += 1
            buf = []
            while i < len(lines) and not _CODE_FENCE_RE.match(lines[i].strip()):
                buf.append(lines[i])
                i += 1
            code = _html.escape("\n".join(buf))
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{cls}>{code}</code></pre>")
            i += 1  # skip closing fence
            continue

        # Table row → collect as a block, render as <pre> (Element renders
        # markdown tables via its own parser, but our HTML subset keeps
        # fidelity best with a monospaced <pre>).
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_para(); flush_list()
            in_table = True
            table_buf.append(raw)
            i += 1
            continue
        if in_table:
            flush_table()

        # Blank line → flush any open paragraph/list.
        if not stripped:
            flush_para(); flush_list()
            i += 1
            continue

        # Heading
        m = _HEADING_RE.match(raw)
        if m:
            flush_para(); flush_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline_md_to_html(m.group(2))}</h{level}>")
            i += 1
            continue

        # Bullet list
        if stripped.startswith(("- ", "* ", "· ")):
            flush_para()
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = stripped[2:]
            out.append(f"<li>{_inline_md_to_html(item)}</li>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith("> "):
            flush_para(); flush_list()
            out.append(f"<blockquote>{_inline_md_to_html(stripped[2:])}</blockquote>")
            i += 1
            continue

        # Horizontal rule
        if stripped == "---":
            flush_para(); flush_list()
            out.append("<hr/>")
            i += 1
            continue

        # Regular paragraph line
        flush_list()
        para.append(stripped)
        i += 1

    flush_para(); flush_list(); flush_table()
    return "\n".join(out)


# ── Posting messages ───────────────────────────────────────────────────────

def _send(room_id: str, content: dict) -> str:
    txn = f"teacher-{int(time.time() * 1000)}"
    esc_room = urllib.parse.quote(room_id, safe="")
    path = f"/_matrix/client/v3/rooms/{esc_room}/send/m.room.message/{txn}"
    resp = _request("PUT", path, content)
    return resp.get("event_id", "")


def post_message(room_id: str, body: str,
                 *, formatted_body: Optional[str] = None,
                 msgtype: str = "m.text") -> str:
    content = {
        "msgtype": msgtype,
        "body": body,
    }
    if formatted_body:
        content["format"] = "org.matrix.custom.html"
        content["formatted_body"] = formatted_body
    return _send(room_id, content)


def post_notice(room_id: str, body: str,
                *, formatted_body: Optional[str] = None) -> str:
    """m.notice variant — no ping sound in Element."""
    return post_message(room_id, body, formatted_body=formatted_body, msgtype="m.notice")
