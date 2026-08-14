#!/usr/bin/env python3
"""Reconcile completed gateway sessions -> archive + band-aware YT resolution.

WHY THIS EXISTS
---------------
The auto-resolve pipeline had NO close-out: the Runner runs an alert session and
posts the result to Matrix, but nothing ever archived the session or moved the
YouTrack issue forward. The Session End workflow exists for that but is only
triggered by the (now-unused) interactive `!session done` command, so it fired
0 times -- session_log went stale at 2026-04-07 and ~350 rows piled up in the
`sessions` table, and triaged issues sat Open forever. (Diagnosis: the
pipeline-deep-diagnose workflow + memory/... .)

This reconciler is the lowest-risk fix: it drives genuinely-completed sessions to
closure DIRECTLY (no surgery on the outage-sensitive Runner/Bridge, no 350x heavy
Session-End Claude-summary runs), and it is BAND-AWARE:

  * AUTO / AUTO_NOTICE band  -> archive + move the YT issue to **Done** (operator is
                               out of the loop; "To Verify" would just re-strand it).
  * completed, other/unknown -> archive + move the YT issue to **To Verify**.
  * POLL_PAUSE / [POLL] / paused (awaiting a human vote) -> SKIP (human owns it),
    unless it is orphaned (older than --very-old-h) -> archive only, leave YT alone.

YT state is changed ONLY for recent sessions (< --recent-h); the old backlog is
just archived (it was already triaged), so we don't re-close hundreds of old issues.

Idempotent (archived rows are DELETEd from `sessions`), rate-limited, and fully
instrumented (one JSON line per decision to the shared pipeline debug log).

  cron (nl-claude01):  */15 * * * *  scripts/reconcile-completed-sessions.py
  scripts/reconcile-completed-sessions.py --dry-run        # decide, change nothing
  scripts/reconcile-completed-sessions.py --backfill       # also drain the old backlog
"""
from __future__ import annotations

import argparse
import base64
import json
import os
REDACTED_a7b84d63
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

DB_PATH = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPTS_DIR)
GW_DIR = os.environ.get("GATEWAY_STATE_DIR", "/home/app-user/gateway-state")
YT_URL = os.environ.get("YOUTRACK_URL", "https://youtrack.example.net")
DBG_LOG = os.environ.get("GATEWAY_DEBUG_LOG",
                         "/home/app-user/logs/claude-gateway/pipeline-debug.log")
AUTO_BANDS = {"AUTO", "AUTO_NOTICE"}

# MUTATIONS=OFF shadow mode (IFRNLLEI01PRD-1824): reconcile is the authoritative YT-Done gate. When
# shadow is active it must NEVER mark a ticket Done/To-Verify — the sessions ran log-only, so the
# ticket stays for a human; the archive (internal DB) still happens.
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
    import mutation_mode as _mm
except Exception:  # noqa: BLE001
    _mm = None


def _shadow() -> bool:
    return bool(_mm and _mm.is_shadow())
LOCK_FILES = {"IFRNLLEI01PRD": "gateway.lock.infra-nl",
              "IFRGRSKG01PRD": "gateway.lock.infra-gr",
              "CUBEOS": "gateway.lock.cubeos", "MESHSAT": "gateway.lock.meshsat"}


def _dbg(event: str, **fields) -> None:
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "script": "reconcile-sessions", "pid": os.getpid(), "event": event, **fields}
        os.makedirs(os.path.dirname(DBG_LOG), exist_ok=True)
        with open(DBG_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _yt_token() -> str:
    tok = os.environ.get("YOUTRACK_API_TOKEN", "")
    if tok:
        return tok
    for p in (os.path.expanduser("~/gitlab/n8n/claude-gateway/.env"),
              "/app/claude-gateway/.env"):
        try:
            for line in open(p, encoding="utf-8"):
                if line.startswith("YOUTRACK_API_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def _decode_resp(b64: str) -> str:
    try:
        return base64.b64decode(b64 or "").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _latest_band(conn: sqlite3.Connection, issue_id: str) -> str | None:
    try:
        r = conn.execute(
            "SELECT band FROM session_risk_audit WHERE issue_id=? "
            "ORDER BY classified_at DESC, id DESC LIMIT 1", (issue_id,)).fetchone()
        return r["band"] if r and r["band"] else None
    except sqlite3.Error:
        return None


def _set_yt_state(token: str, issue_id: str, state: str, comment: str, dry: bool) -> str:
    if dry:
        return "dry"
    if not token:
        return "no-token"
    body = json.dumps({"query": f"State {state}", "comment": comment,
                       "issues": [{"idReadable": issue_id}]}).encode()
    req = urllib.request.Request(
        f"{YT_URL}/api/commands", method="POST", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"http{r.status}"
    except urllib.error.HTTPError as e:
        return f"http{e.code}"
    except Exception as e:  # noqa: BLE001
        return f"err:{type(e).__name__}"


def _archive(conn: sqlite3.Connection, row: sqlite3.Row, outcome: str,
             resolution_type: str, dry: bool) -> None:
    """Mirror the Session End 'Clean Up Files' archive: sessions -> session_log, delete."""
    if dry:
        return
    sid = row["session_id"]
    conn.execute(
        """INSERT INTO session_log
           (issue_id, issue_title, session_id, started_at, ended_at, message_count,
            outcome, cost_usd, num_turns, duration_seconds, confidence, resolution_type,
            prompt_variant, alert_category, model, schema_version)
           SELECT issue_id, issue_title, session_id, started_at, CURRENT_TIMESTAMP,
                  message_count, ?, COALESCE(cost_usd,0), COALESCE(num_turns,0),
                  COALESCE(duration_seconds,0), COALESCE(confidence,-1), ?,
                  COALESCE(prompt_variant,''), COALESCE(alert_category,''),
                  COALESCE(model,''), 1
           FROM sessions WHERE session_id=?""",
        (outcome, resolution_type, sid))
    conn.execute("DELETE FROM sessions WHERE session_id=?", (sid,))
    conn.execute("DELETE FROM queue WHERE issue_id=?", (row["issue_id"],))
    conn.commit()


def _post_archive_side_effects(conn: sqlite3.Connection, row: sqlite3.Row,
                               age_h: float, dry: bool) -> None:
    """Port the 4 analytics side-effects the n8n Session-End workflow used to run
    (it now fires 0x — session_quality/otel_spans/lessons_learned/tool_call_log went
    dark 2026-04). Runs AFTER _archive (so the session_log row exists for the quality
    score) while /tmp/claude-run-<issue>.jsonl is still present. Best-effort but every
    failure is LOGGED to the pipeline-debug log (NOT swallowed). Skipped for the old
    backlog (age>72h: JSONLs are gone and we don't want a backfill spawning thousands
    of subprocesses). Reuses scripts/{parse-tool-calls.py,export-otel-traces.py,
    compute-quality-score.sh}; absolute paths (no relative-cron trap)."""
    if dry or age_h > 72:
        return
    issue = row["issue_id"]
    jsonl = f"/tmp/claude-run-{issue}.jsonl"
    env = {**os.environ, "GATEWAY_DB": DB_PATH}

    # Best-effort LLM-trace export to self-hosted Langfuse (orchestrator Brick 2 observability,
    # 2026-06-26). Never blocks reconcile; missing config / unreachable host = silent no-op.
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(REPO_DIR, "scripts", "lib"))
        import langfuse_export
        _k = row.keys()
        langfuse_export.send_session(
            issue,
            model=row["model"] if "model" in _k else None,
            cost_usd=row["cost_usd"] if "cost_usd" in _k else None,
            num_turns=row["num_turns"] if "num_turns" in _k else None,
            confidence=row["confidence"] if "confidence" in _k else None,
            resolution_type=row["resolution_type"] if "resolution_type" in _k else None)
    except Exception as e:  # noqa: BLE001 — observability must never break reconcile
        _dbg("langfuse_export_failed", issue_id=issue, error=str(e)[:120])

    # Best-effort: ship the completed session to OpenObserve too (unified 'sessions' stream, so the
    # session layer is searchable alongside the scheduler + orchestrator streams). 2026-06-26.
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(REPO_DIR, "scripts", "lib"))
        import obs_log
        _k = row.keys()
        obs_log.event("sessions", source="reconcile", issue=issue,
                      model=row["model"] if "model" in _k else None,
                      cost_usd=row["cost_usd"] if "cost_usd" in _k else None,
                      num_turns=row["num_turns"] if "num_turns" in _k else None,
                      confidence=row["confidence"] if "confidence" in _k else None,
                      resolution_type=row["resolution_type"] if "resolution_type" in _k else None,
                      outcome=row["outcome"] if "outcome" in _k else None, level="info")
    except Exception as e:  # noqa: BLE001 — observability must never break reconcile
        _dbg("obs_log_session_failed", issue_id=issue, error=str(e)[:120])

    def _run(label, argv, need_jsonl=False):
        if need_jsonl and not os.path.exists(jsonl):
            _dbg("side_effect_skip", issue_id=issue, effect=label, reason="jsonl-absent")
            return
        try:
            r = subprocess.run(argv, cwd=REPO_DIR, env=env, capture_output=True,
                               text=True, timeout=120)
            if r.returncode != 0:
                _dbg("side_effect_fail", issue_id=issue, effect=label, rc=r.returncode,
                     err=((r.stderr or r.stdout) or "")[-200:])
            else:
                _dbg("side_effect_ok", issue_id=issue, effect=label)
        except Exception as e:  # noqa: BLE001
            _dbg("side_effect_error", issue_id=issue, effect=label,
                 err=f"{type(e).__name__}:{e}")

    _run("tool_calls", ["python3", os.path.join(SCRIPTS_DIR, "parse-tool-calls.py"),
                        jsonl, "--issue", issue], need_jsonl=True)
    # Push the trace FRESH at session-end (--otlp) so spans land inside OpenObserve's ~5h ingest
    # window, AND store locally for the record + the */5 retry. export-otel-traces.py now ALWAYS
    # stores locally even with --otlp + marks exported on success (fixing the old "dark on success"
    # bug); the prior deferred store-only path aged spans past the window -> bench IFRNLLEI01PRD-1422
    # measured 99.9% rejected as too-old. The */5 `--export` cron stays as the retry for failed pushes.
    _run("otel", ["python3", os.path.join(SCRIPTS_DIR, "export-otel-traces.py"),
                  "--otlp", "--issue", issue], need_jsonl=True)
    _run("quality", [os.path.join(SCRIPTS_DIR, "compute-quality-score.sh"), issue])
    # lessons_learned: pull a "LESSON:" line out of the response blob, if present.
    try:
        blob = row["last_response_b64"] or ""
        text = base64.b64decode(blob).decode("utf-8", "replace") if blob else ""
        m = re.search(r"LESSON:\s*(.+)", text, re.I)
        if m:
            lesson = m.group(1).strip()[:2000]
            conn.execute("INSERT INTO lessons_learned (issue_id, lesson, source) "
                         "VALUES (?,?,?)", (issue, lesson, "claude-code"))
            conn.commit()
            _dbg("side_effect_ok", issue_id=issue, effect="lesson", chars=len(lesson))
    except Exception as e:  # noqa: BLE001
        _dbg("side_effect_error", issue_id=issue, effect="lesson",
             err=f"{type(e).__name__}:{e}")


def _action_verdict(conn: sqlite3.Connection, issue_id: str):
    """Latest committed ACTION prediction for the issue, for the R0 auto-resolve gate.
    Returns (has_action_prediction, verdict, evaluated, lookup_error). verdict in
    {match, partial, deviation, None}; evaluated = the async verdict has been written
    (infragraph-eval.py --pending); lookup_error = the query FAILED on an existing table
    (lock/corruption) — the caller must then fail CLOSED (never auto-resolve blind).
    TZ-robust: no created_at parsing — staleness is decided from the session's age_h."""
    try:
        r = conn.execute(
            "SELECT verdict, evaluated_at FROM infragraph_predictions "
            "WHERE parent_issue_id=? AND kind='action' ORDER BY id DESC LIMIT 1",
            (issue_id,)).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            return (False, None, False, False)  # degenerate/test DB -> benign no-prediction
        return (False, None, False, True)        # real lock/corruption -> fail CLOSED
    except Exception:  # noqa: BLE001
        return (False, None, False, True)
    if not r:
        return (False, None, False, False)
    return (True, r["verdict"], bool(r["evaluated_at"]), False)


_TERR_HIGH = {"k8s", "network", "edge", "pve", "native", "docker"}


def _territory_unacked(conn: sqlite3.Connection, issue_id: str) -> bool:
    """Backstop (IFRNLLEI01PRD-1408): True if the latest classify tagged this issue with a
    HIGH-STAKES territory but the territory CLAUDE.md was never Read this issue (no per-issue
    ack marker) — i.e. the PreToolUse gate was bypassed. Caller gates on has_pred so this
    only applies to remediation (a write), not read-only work. Live-only (sentinel)."""
    if not os.path.exists(os.environ.get("TERRITORY_GATE_SENTINEL")
                          or os.path.expanduser("~/gateway.territory_gate")):
        return False
    try:
        r = conn.execute("SELECT signals_json FROM session_risk_audit WHERE issue_id=? "
                         "ORDER BY rowid DESC LIMIT 1", (issue_id,)).fetchone()
    except Exception:
        return False
    if not r or not r["signals_json"]:
        return False
    try:
        sigs = json.loads(r["signals_json"])
    except Exception:
        return False
    terr = next((s.split(":", 1)[1] for s in sigs
                 if isinstance(s, str) and s.startswith("territory:")
                 and s.split(":", 1)[1] in _TERR_HIGH), None)
    if not terr:
        return False
    return not os.path.exists(
        os.path.join("/tmp/claude-territory-acks", "issue-" + str(issue_id) + ".txt"))


def _fire_deviation_sms(issue_id: str, reason: str) -> None:
    """Best-effort page when an auto-EXECUTED action did NOT verify (deviation/stale).
    The operator ignores polls but watches SMS; fire-and-forget so it never blocks."""
    try:
        payload = json.dumps({"issue_id": issue_id or "unknown",
                              "summary": f"auto-remediation UNVERIFIED ({reason}) — review",
                              "band": "AUTO_NOTICE", "host": "",
                              "risk_level": "high", "reason": "deviation"}).encode()
        url = os.environ.get("AUTONOMY_SMS_URL", "http://127.0.0.1:9106/alert-session")
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=4).close()
    except Exception:  # noqa: BLE001 — paging must never block reconcile
        pass


def _schedule_poll_recheck(conn: sqlite3.Connection, row: sqlite3.Row, dry: bool) -> None:
    """IFRNLLEI01PRD-1709: an orphaned POLL_PAUSE archive used to be TERMINAL — the
    2026-07-03 IFRNLLEI01PRD-1536 disk alert (90-95% on nlghostfolio01) was
    archived orphaned-poll and silently worsened to 100% full. Schedule a delayed
    re-check row for scripts/requeue-escalations.py, which re-escalates through the
    normal webhook (+SMS) only if the condition is verifiably still active."""
    issue = row["issue_id"]
    recheck_h = float(os.environ.get("ORPHAN_RECHECK_H", "24"))
    try:
        if conn.execute(
                "SELECT 1 FROM escalation_queue WHERE issue_id=? AND kind='poll-recheck' "
                "AND status='pending'", (issue,)).fetchone():
            return
        if dry:
            _dbg("poll_recheck_scheduled", issue_id=issue, recheck_h=recheck_h, dry=True)
            return
        conn.execute(
            "INSERT INTO escalation_queue (issue_id, summary, kind, reason, eligible_at) "
            "VALUES (?, ?, 'poll-recheck', 'orphaned-poll', datetime('now', ?))",
            (issue, (row["issue_title"] or "")[:500], f"+{recheck_h:.0f} hours"))
        conn.commit()
        _dbg("poll_recheck_scheduled", issue_id=issue, recheck_h=recheck_h)
    except sqlite3.OperationalError as e:  # missing table pre-migration: log, never block
        _dbg("poll_recheck_schedule_failed", issue_id=issue, error=str(e))


def classify_session(row: sqlite3.Row, band: str | None, age_h: float,
                     args, conn: sqlite3.Connection | None = None) -> dict:
    """Return {action, yt_state|None, outcome, resolution_type, reason}."""
    resp = _decode_resp(row["last_response_b64"])
    is_poll = resp.lstrip().startswith("[POLL]") or band == "POLL_PAUSE" \
        or bool(row["paused"])
    if age_h < args.min_idle_min / 60.0:
        return {"action": "skip", "reason": "too-fresh"}
    if is_poll:
        if age_h > args.very_old_h:
            return {"action": "archive", "yt_state": None, "outcome": "abandoned",
                    "resolution_type": "poll_unanswered", "reason": "orphaned-poll"}
        return {"action": "skip", "reason": "awaiting-human-poll"}
    # completed, non-poll -> closeable
    # Shadow clamp: reconcile RE-DERIVES auto from the raw [AUTO-RESOLVE] text independently of the
    # classify band, so the band-level clamp is not enough — kill auto here too (and yt_state below).
    shadow = _shadow()
    auto = (band in AUTO_BANDS or resp.find("[AUTO-RESOLVE]") >= 0) and not shadow
    # >>> R0 (IFRNLLEI01PRD-1408): the auto-resolve lane MUST consult the infragraph
    # action verdict. An AUTO/[AUTO-RESOLVE] session that EXECUTED a remediation
    # (=> committed an 'action' prediction) auto-resolves ONLY on verdict=match; a
    # deviation/partial/stale-unevaluated action is demoted (To Verify + SMS); a
    # still-pending verdict is skipped until the window closes. Sessions with NO
    # action prediction are read-only/confirm-close (e.g. -1117) and resolve as before.
    gate_reason = ""
    if auto and conn is not None:
        has_pred, verdict, evaluated, lookup_error = _action_verdict(conn, row["issue_id"])
        if lookup_error:
            # cannot verify the action verdict (DB lock/corruption) -> fail CLOSED, retry next run
            return {"action": "skip", "reason": "action-verdict-lookup-error"}
        if has_pred:
            if evaluated and verdict == "match":
                pass  # executed action verified -> auto-resolve OK
            elif not evaluated and age_h < args.very_old_h:
                return {"action": "skip", "reason": "action-verdict-pending"}
            else:  # deviation / partial, OR unevaluated past very_old_h (eval cron behind)
                auto = False
                gate_reason = f"verdict-gate:{verdict or 'unevaluated'}"
                if not args.dry_run:
                    _fire_deviation_sms(row["issue_id"], verdict or "unevaluated")
        # Territory backstop: a REMEDIATION in a high-stakes territory must have loaded
        # that territory's CLAUDE.md (proof-of-read ack); no ack => the PreToolUse gate was
        # bypassed => do NOT auto-resolve. Read-only/confirm-close (no has_pred) is exempt.
        if auto and has_pred and _territory_unacked(conn, row["issue_id"]):
            auto = False
            gate_reason = gate_reason or "territory-gate:unacked"
            if not args.dry_run:
                _fire_deviation_sms(row["issue_id"], "territory-claudemd-unread")
    # <<< R0
    yt_state = None
    if age_h <= args.recent_h and not shadow:  # only touch YT for recent sessions (never in shadow)
        yt_state = "Done" if auto else "To Verify"
    if shadow and age_h <= args.recent_h and _mm:
        # In shadow we archive (internal bookkeeping) but leave YT untouched — log the intent.
        _mm.log_wouldve("reconcile-yt-state", rationale="shadow: session ran log-only; ticket left for a human",
                        issue=row["issue_id"], would_be_state=("Done" if (band in AUTO_BANDS or resp.find("[AUTO-RESOLVE]") >= 0) else "To Verify"))
    return {"action": "archive", "yt_state": yt_state, "outcome": "done",
            "resolution_type": ("auto_resolved" if auto else "completed"),
            "reason": (("shadow-log-only" if shadow else gate_reason) or ("auto-resolve" if auto else "completed"))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="decide + log, change nothing")
    ap.add_argument("--backfill", action="store_true",
                    help="also process the old backlog (raises the per-run cap)")
    ap.add_argument("--min-idle-min", type=float, default=15.0,
                    help="min idle minutes before a session is closeable")
    ap.add_argument("--recent-h", type=float, default=24.0,
                    help="only change YT state for sessions newer than this")
    ap.add_argument("--very-old-h", type=float, default=48.0,
                    help="orphaned poll/paused sessions older than this get archived")
    ap.add_argument("--max-per-run", type=int, default=8)
    args = ap.parse_args()
    if args.backfill:
        args.max_per_run = max(args.max_per_run, 1000)

    token = _yt_token()
    conn = _conn()
    # is_current=0, OR a stuck is_current=1 that's been idle >2h (a genuinely-active
    # session refreshes last_active every turn, so >2h idle = abandoned/stuck).
    rows = conn.execute(
        "SELECT * FROM sessions WHERE length(COALESCE(last_response_b64,''))>0 "
        "AND (is_current=0 OR (julianday('now')-julianday(last_active))*24 > 2.0) "
        "ORDER BY last_active ASC").fetchall()
    _dbg("reconcile_start", candidates=len(rows), dry=args.dry_run, backfill=args.backfill)

    acted = skipped = 0
    summary = {"Done": 0, "To Verify": 0, "archived_only": 0, "skipped": 0}
    for row in rows:
        if acted >= args.max_per_run:
            break
        try:
            age_h = (time.time() - _epoch(row["last_active"])) / 3600.0
        except Exception:  # noqa: BLE001
            age_h = 999.0
        band = _latest_band(conn, row["issue_id"])
        d = classify_session(row, band, age_h, args, conn)
        if d["action"] == "skip":
            skipped += 1
            summary["skipped"] += 1
            continue
        # archive + optional YT state
        yt_res = "-"
        if d.get("yt_state"):
            comment = (f"Auto-resolved by the gateway (band={band or 'n/a'}); session "
                       f"{row['session_id'][:8]} archived. Closing." if d["yt_state"] == "Done"
                       else f"Gateway session complete (band={band or 'n/a'}); ready for verification.")
            yt_res = _set_yt_state(token, row["issue_id"], d["yt_state"], comment, args.dry_run)
            summary[d["yt_state"]] += 1
        else:
            summary["archived_only"] += 1
        _archive(conn, row, d["outcome"], d["resolution_type"], args.dry_run)
        _post_archive_side_effects(conn, row, age_h, args.dry_run)
        if d.get("resolution_type") == "poll_unanswered":
            _schedule_poll_recheck(conn, row, args.dry_run)
        acted += 1
        _dbg("reconcile_session", issue_id=row["issue_id"], session=row["session_id"][:8],
             age_h=round(age_h, 1), band=band, action=d["action"],
             yt_state=d.get("yt_state"), yt_result=yt_res, reason=d["reason"], dry=args.dry_run)

    conn.close()
    _dbg("reconcile_done", acted=acted, skipped=skipped, summary=summary)
    out = {"acted": acted, "skipped": skipped, "candidates": len(rows),
           "dry_run": args.dry_run}
    out.update(summary)
    print(json.dumps(out))
    return 0


def _epoch(ts: str) -> float:
    # sqlite CURRENT_TIMESTAMP / DATETIME stored as 'YYYY-MM-DD HH:MM:SS' (UTC)
    return time.mktime(time.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")) - time.timezone


if __name__ == "__main__":
    sys.exit(main())
