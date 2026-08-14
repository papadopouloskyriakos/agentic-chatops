#!/usr/bin/env python3
"""judge-calibrate.py — automated response to the ComposedEvalJudgeFooled alert (directive #9, 2026-07-08).

A session is "judge-fooled" when the local judge said approve/approve_with_notes but the trajectory
scorer marked it structurally incomplete (trajectory_score < 75). The count is 30d-windowed.

CRITICAL DESIGN NOTE (why this does NOT auto-edit the judge rubric):
The fooled count is a JOIN of TWO independent layers, so a high count has two very different causes:
  * genuine judge softness  — judge approved a THIN session (few tool calls, no real investigation)
  * trajectory-scorer FALSE-NEGATIVE — the session did real work (many tool calls/turns) but the
    scorer's brittle grep-markers (has_incident_kb_query / has_react_structure / has_ssh_investigation)
    missed it, so the judge's approve is actually CORRECT.
Blindly tightening the judge rubric on scorer-false-negatives would convert good approvals into false
REJECTS and degrade the eval layer. So this actuator CLASSIFIES first and takes the SAFE action:
  - genuine-softness  -> re-judge with the current (already-strict 2026-07-03) rubric; if it still
                         approves, ESCALATE a human-review rubric-tightening proposal (never auto-edit
                         the bash-single-quoted rubric string — that would risk the frontier anchor).
  - scorer-false-neg  -> the judge is fine; ESCALATE a trajectory-scorer marker-widening recommendation.
Always posts a Matrix notice with the breakdown. Re-judge is the only state change and only on
genuine-softness sessions; gated by ~/gateway.judge_autocalibrate_armed.

  judge-calibrate.py --analyze        # classify + notice, no changes
  judge-calibrate.py --recalibrate    # + re-judge genuine-softness (needs the sentinel)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sqlite3
import sys
import time
import urllib.request

DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENTINEL = os.path.expanduser("~/gateway.judge_autocalibrate_armed")
HS = os.environ.get("MATRIX_HOME_SERVER", "https://matrix.example.net")
ROOM = os.environ.get("MATRIX_JUDGE_ROOM", "!xeNxtpScJWCmaFjeCL:matrix.example.net")  # #alerts
DBG_LOG = os.environ.get("GATEWAY_DEBUG_LOG", "/home/app-user/logs/claude-gateway/pipeline-debug.log")
# A session with real investigation the judge reasonably approved -> a scorer FALSE-NEGATIVE, not
# judge softness. Tunable floor.
ACTIVE_TOOLCALLS = int(os.environ.get("JUDGE_CAL_ACTIVE_TOOLCALLS", "8"))
ACTIVE_TURNS = int(os.environ.get("JUDGE_CAL_ACTIVE_TURNS", "8"))

FOOLED_SQL = """
WITH latest_judg AS (
  SELECT j.issue_id, j.overall_score, j.safety_compliance, j.recommended_action, j.rationale, j.judged_at
  FROM session_judgment j
  JOIN (SELECT issue_id, MAX(judged_at) mj FROM session_judgment WHERE overall_score>=0 GROUP BY issue_id) m
    ON j.issue_id=m.issue_id AND j.judged_at=m.mj),
latest_traj AS (
  SELECT t.* FROM session_trajectory t
  JOIN (SELECT issue_id, MAX(graded_at) mg FROM session_trajectory
        WHERE trajectory_score>=0 AND NOT (COALESCE(tool_calls,0)=0 AND COALESCE(turns,0)<=1)
        GROUP BY issue_id) mm
    ON t.issue_id=mm.issue_id AND t.graded_at=mm.mg)
SELECT tr.issue_id, tr.trajectory_score, tr.steps_completed, tr.steps_expected,
       COALESCE(tr.tool_calls,0), COALESCE(tr.turns,0), j.overall_score, j.recommended_action,
       (CASE WHEN tr.has_incident_kb_query=0 THEN 'kb ' ELSE '' END ||
        CASE WHEN tr.has_react_structure=0  THEN 'react ' ELSE '' END ||
        CASE WHEN tr.has_confidence=0       THEN 'confidence ' ELSE '' END ||
        CASE WHEN tr.has_evidence_commands=0 THEN 'evidence-cmds ' ELSE '' END ||
        CASE WHEN tr.has_ssh_investigation=0 THEN 'ssh ' ELSE '' END ||
        CASE WHEN tr.has_poll_or_approval=0  THEN 'poll/autoresolve ' ELSE '' END ||
        CASE WHEN tr.has_netbox_lookup=0     THEN 'netbox ' ELSE '' END ||
        CASE WHEN tr.has_yt_comment=0        THEN 'yt-comment ' ELSE '' END) AS missing
FROM latest_traj tr JOIN latest_judg j ON tr.issue_id=j.issue_id
WHERE tr.trajectory_score < 75
  AND LOWER(TRIM(j.recommended_action)) IN ('approve','approve_with_notes')
  AND NOT (j.safety_compliance BETWEEN 0 AND 2)
  AND MAX(tr.graded_at, j.judged_at) >= datetime('now','-30 days')
ORDER BY COALESCE(tr.tool_calls,0)
"""


def _dbg(event, **f):
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "script": "judge-calibrate", "pid": os.getpid(), "event": event, **f}
        os.makedirs(os.path.dirname(DBG_LOG), exist_ok=True)
        with open(DBG_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _env_secret(name):
    v = os.environ.get(name, "")
    if v:
        return v
    try:
        for line in open(os.path.join(REPO, ".env"), encoding="utf-8"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def classify():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    rows = conn.execute(FOOLED_SQL).fetchall()
    conn.close()
    out = []
    for iid, hard, sc, se, tc, tu, judge, action, missing in rows:
        scorer_fn = tc >= ACTIVE_TOOLCALLS and tu >= ACTIVE_TURNS
        out.append({"issue": iid, "hard": hard, "steps": f"{sc}/{se}", "tool_calls": tc,
                    "turns": tu, "judge": judge, "action": action, "missing": missing.strip(),
                    "class": "scorer-false-negative" if scorer_fn else "genuine-softness"})
    return out


def rejudge(issue: str) -> bool:
    """DELETE the stale judgment (bypass the already-judged guard) + re-run the judge with the
    CURRENT strict rubric. Reversible in effect (recomputes). Only called on genuine-softness."""
    try:
        conn = sqlite3.connect(DB, timeout=20)
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("DELETE FROM session_judgment WHERE issue_id=?", (issue,))
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        _dbg("rejudge_delete_failed", issue=issue, error=str(e)[:100])
        return False
    try:
        r = subprocess.run([os.path.join(REPO, "scripts", "llm-judge.sh"), issue],
                           cwd=REPO, capture_output=True, text=True, timeout=180)
        return r.returncode == 0
    except Exception as e:  # noqa: BLE001
        _dbg("rejudge_run_failed", issue=issue, error=str(e)[:100])
        return False


def notify(text):
    tok = _env_secret("MATRIX_ACCESS_TOKEN") or _env_secret("MATRIX_CLAUDE_TOKEN")
    if not tok:
        return
    try:
        body = json.dumps({"msgtype": "m.text", "body": text}).encode()
        txn = f"judgecal-{int(time.time())}"
        req = urllib.request.Request(f"{HS}/_matrix/client/v3/rooms/{ROOM}/send/m.room.message/{txn}",
                                     data=body, method="PUT",
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8).close()
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--analyze", action="store_true", help="classify + notice, no changes")
    ap.add_argument("--recalibrate", action="store_true", help="+ re-judge genuine-softness (needs sentinel)")
    args = ap.parse_args()
    armed = os.path.exists(SENTINEL)

    fooled = classify()
    scorer_fn = [f for f in fooled if f["class"] == "scorer-false-negative"]
    soft = [f for f in fooled if f["class"] == "genuine-softness"]
    out = {"fooled_total": len(fooled), "scorer_false_negative": len(scorer_fn),
           "genuine_softness": len(soft), "armed": armed}

    rejudged = []
    if args.recalibrate and armed and soft:
        for f in soft:
            ok = rejudge(f["issue"])
            rejudged.append({"issue": f["issue"], "rejudged_ok": ok})
        # recompute after re-judge
        post = classify()
        out["fooled_after_rejudge"] = len(post)
    out["rejudged"] = rejudged

    # Build the notice + escalation guidance
    lines = [f"🧑‍⚖ Judge-fooled calibration: {len(fooled)} in 30d "
             f"({len(scorer_fn)} scorer-false-negative, {len(soft)} genuine-softness)."]
    if scorer_fn:
        top = scorer_fn[0]
        lines.append(f"• {len(scorer_fn)} are SCORER false-negatives (real investigation the judge "
                     f"reasonably approved: e.g. {top['issue']} {top['tool_calls']} tool-calls/{top['turns']} "
                     f"turns, scorer missing '{top['missing']}'). The JUDGE is fine — do NOT tighten it. "
                     f"Fix: widen trajectory-scorer markers (has_incident_kb_query/has_react_structure/"
                     f"has_ssh_investigation) in score-trajectory to detect real investigation.")
    if soft:
        lines.append(f"• {len(soft)} look like GENUINE judge softness (thin sessions the judge approved)."
                     + (f" Re-judged {sum(1 for r in rejudged if r['rejudged_ok'])}/{len(soft)} with the "
                        f"current strict rubric." if rejudged else " Run --recalibrate to re-judge; if they "
                        "still approve, a human should tighten scripts/llm-judge.sh:59-62."))
    if not fooled:
        lines.append("✅ 0 fooled — nothing to calibrate.")
    lines.append("(Auto-rubric-mutation is deliberately NOT performed: the count mixes two failure "
                 "modes; tightening the judge on scorer-FNs would create false-rejects.)")
    text = "\n".join(lines)
    print(text)
    print(json.dumps(out))
    notify(text)
    _dbg("judge_calibrate", **out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
