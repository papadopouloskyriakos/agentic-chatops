#!/usr/bin/env python3
"""judge-frontier-crosscheck.py — IFRNLLEI01PRD-1451, no-human eval anchor (frontier cross-check).

Re-judges a sample of recently locally-judged sessions with a FRONTIER model (Opus) and compares
to the local gemma judge (session_judgment). Two failure modes it catches, with ZERO operator
involvement (the operator is deliberately absent — see memory/feedback_no_human_anchor_for_absent_operator):

  * DRIFT  — local and frontier disagree on the verdict (action_agreement_rate drops).
  * DEATH  — local returns -1 (unscored) while the frontier scores real. This is the exact
             3-week dead-judge class from 2026-06-27 that NO purely-LLM metric could catch,
             because the dead judge still wrote rows (all -1) so nothing looked "dark".

It loads the EXACT rubric the local judge uses (from llm-judge.sh) so the comparison is
apples-to-apples, and writes one row per check to judge_crosscheck + emits Prometheus metrics.

Usage:
  judge-frontier-crosscheck.py [--run [N]]   # crosscheck N recent sessions (default 8) + emit metrics
  judge-frontier-crosscheck.py --metrics      # recompute + emit metrics only (no new crosschecks)
"""
import os, sys, re, json, sqlite3, base64, urllib.request, urllib.error, time, argparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lib.schema_version import current as schema_current  # noqa: E402

DB = os.environ.get("GATEWAY_DB", "/app/cubeos/claude-context/gateway.db")
PROM_DIR = os.environ.get("TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector")
FRONTIER_MODEL = "mistral-large-latest"   # frontier judge -> Mistral via LiteLLM (no Anthropic)
JUDGE_SH = os.path.join(REPO, "scripts", "llm-judge.sh")
MAX_CHARS = 8000
WINDOW_DAYS = 14


def load_env_key():
    for line in open(os.path.join(REPO, ".env")):
        if line.startswith("LITELLM_GATEWAY_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("LITELLM_GATEWAY_KEY", "")


def load_local_rubric():
    """Load the SAME rubric llm-judge.sh uses, so the frontier scores the same thing."""
    txt = open(JUDGE_SH).read()
    m = re.search(r"^RUBRIC='(.*?)'\n", txt, re.DOTALL | re.MULTILINE)
    r = m.group(1) if m else None
    return r if (r and "recommended_action" in r) else None  # sanity: must include the full template


def robust_json(text):
    """Same robust parse as the fixed llm-judge.sh: direct load, then greedy outermost-brace."""
    text = (text or "{}").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                return {}
        return {}


def opus_judge(rubric, issue, title, response, api_key):
    content = (rubric + "\n\n---\n\nISSUE: " + issue + ": " + (title or "")
               + "\n\nAGENT RESPONSE:\n" + response[:MAX_CHARS])
    # Plane B: routes via the gateway LiteLLM -> gw-mistral-large (NO Anthropic). api_key = LITELLM_GATEWAY_KEY.
    base = os.environ.get("LITELLM_URL", "http://10.0.181.X:4000") + "/v1/messages"
    payload = json.dumps({"model": "gw-mistral-large", "max_tokens": 600,
                          "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(base, data=payload,
                                 headers={"Authorization": "Bearer " + api_key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json", "x-litellm-tags": "frontier-crosscheck"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return None, None, "http-%s:%s" % (e.code, body[:200])
    except Exception as e:
        return None, None, "api-error:" + str(e)[:80]
    text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict) and b.get("type") == "text")
    j = robust_json(text)
    try:
        score = int(j.get("overall_score", -1))
    except (ValueError, TypeError):
        score = -1
    action = str(j.get("recommended_action", "")).strip().lower()
    return score, action, ""


def run(n):
    rubric = load_local_rubric()
    if not rubric:
        sys.exit("FATAL: could not load the local RUBRIC from llm-judge.sh (cross-check would not be apples-to-apples)")
    api_key = load_env_key()
    if not api_key:
        sys.exit("FATAL: no LITELLM_GATEWAY_KEY in .env")
    db = sqlite3.connect(DB, timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    win = "-%d day" % WINDOW_DAYS
    # Sample from SESSIONS, not session_judgment (2026-07-03 starvation fix): a
    # fully-dead local judge writes no judgment rows, so sampling its own output
    # table gave the cross-check nothing to check — pairs sat below the alert
    # gate through BOTH dead-judge incidents. Sessions the judge never scored now
    # flow through with local_score=-1, which metrics() counts as local_dead ->
    # judge_frontier_local_unscored_rate rises -> JudgeFrontierDrift fires.
    rows = db.execute("""
        SELECT s.issue_id, j.overall_score, j.recommended_action, j.judge_model, s.last_response_b64, s.issue_title
        FROM sessions s
        LEFT JOIN (SELECT issue_id, overall_score, recommended_action, judge_model, MAX(judged_at)
                   FROM session_judgment WHERE overall_score >= 0 GROUP BY issue_id) j
               ON j.issue_id = s.issue_id
        WHERE s.last_active > datetime('now', ?)
          AND COALESCE(s.last_response_b64, '') != ''
          AND s.issue_id NOT IN (SELECT issue_id FROM judge_crosscheck WHERE checked_at > datetime('now', ?))
        GROUP BY s.issue_id
        ORDER BY MAX(s.last_active) DESC LIMIT ?
    """, (win, win, n)).fetchall()
    done = 0
    for issue, lscore, laction, lmodel, b64, title in rows:
        try:
            response = base64.b64decode(b64).decode("utf-8", errors="replace")
        except Exception:
            continue
        if not response.strip():
            continue
        fscore, faction, err = opus_judge(rubric, issue, title, response, api_key)
        if err:
            print("  skip %s: %s" % (issue, err))
            continue
        try:
            ls = int(lscore)
        except (ValueError, TypeError):
            ls = -1
        delta = (fscore - ls) if (fscore is not None and fscore >= 0 and ls >= 0) else -999
        la = (laction or "").strip().lower()
        agree = 1 if (la and faction and la == faction) else (0 if (la and faction) else -1)
        db.execute("""INSERT INTO judge_crosscheck
            (issue_id, local_model, local_score, local_action, frontier_model, frontier_score,
             frontier_action, score_delta, action_agree, schema_version)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                   (issue, lmodel or "", ls, la, FRONTIER_MODEL, fscore if fscore is not None else -1,
                    faction or "", delta, agree, schema_current("judge_crosscheck")))
        db.commit()
        done += 1
        flag = "  <-- DEAD-LOCAL" if (ls < 0 and (fscore or -1) >= 0) else ("  <-- DRIFT" if agree == 0 else "")
        print("  %-22s local=%s/%-7s frontier=%s/%-7s agree=%s%s"
              % (issue, ls, la or "-", fscore, faction or "-", agree, flag))
    print("crosschecked %d session(s)" % done)
    db.close()


def metrics():
    db = sqlite3.connect(DB, timeout=30)
    win = "-%d day" % WINDOW_DAYS
    r = db.execute("""SELECT
        COUNT(*),
        SUM(CASE WHEN action_agree = 1 THEN 1 ELSE 0 END),
        SUM(CASE WHEN action_agree IN (0, 1) THEN 1 ELSE 0 END),
        SUM(CASE WHEN local_score < 0 AND frontier_score >= 0 THEN 1 ELSE 0 END),
        AVG(CASE WHEN score_delta != -999 THEN ABS(score_delta) END)
        FROM judge_crosscheck WHERE checked_at > datetime('now', ?)""", (win,)).fetchone()
    pairs = r[0] or 0
    agree, actionable, local_dead, mae = (r[1] or 0), (r[2] or 0), (r[3] or 0), r[4]
    agreement_rate = (agree / actionable) if actionable else -1.0
    local_unscored_rate = (local_dead / pairs) if pairs else 0.0
    db.close()
    ts = int(time.time())
    lines = [
        "# HELP judge_frontier_pairs frontier-vs-local judge crosschecks in the last %dd" % WINDOW_DAYS,
        "# TYPE judge_frontier_pairs gauge",
        "judge_frontier_pairs %d" % pairs,
        "# HELP judge_frontier_action_agreement_rate fraction of pairs where local+frontier recommended_action match (-1=n/a)",
        "# TYPE judge_frontier_action_agreement_rate gauge",
        "judge_frontier_action_agreement_rate %.4f" % agreement_rate,
        "# HELP judge_frontier_score_mae mean abs(frontier_score - local_score) over scored pairs (-1=n/a)",
        "# TYPE judge_frontier_score_mae gauge",
        "judge_frontier_score_mae %.4f" % (mae if mae is not None else -1.0),
        "# HELP judge_frontier_local_unscored_rate fraction where local returned -1 but frontier scored (DEAD-JUDGE signal)",
        "# TYPE judge_frontier_local_unscored_rate gauge",
        "judge_frontier_local_unscored_rate %.4f" % local_unscored_rate,
        "# HELP judge_frontier_last_run_timestamp_seconds unix time of last crosscheck metric emit",
        "# TYPE judge_frontier_last_run_timestamp_seconds gauge",
        "judge_frontier_last_run_timestamp_seconds %d" % ts,
    ]
    tmp = os.path.join(PROM_DIR, ".judge_frontier.prom.%d" % os.getpid())
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, os.path.join(PROM_DIR, "judge_frontier.prom"))
    print("metrics: pairs=%d agreement=%.2f mae=%s local_unscored_rate=%.2f"
          % (pairs, agreement_rate, mae, local_unscored_rate))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="?", const=8, type=int, help="crosscheck N recent sessions (default 8)")
    ap.add_argument("--metrics", action="store_true", help="recompute + emit metrics only")
    a = ap.parse_args()
    if a.metrics and a.run is None:
        metrics()
    else:
        run(a.run if a.run is not None else 8)
        metrics()
