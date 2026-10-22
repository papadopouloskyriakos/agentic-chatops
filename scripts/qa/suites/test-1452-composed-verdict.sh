#!/usr/bin/env bash
# QA: compose-eval-verdict.py — hard-first-then-judge composition (IFRNLLEI01PRD-1452).
# Builds an isolated temp DB with the two eval tables, seeds one row per composition
# case, and asserts the composed verdict + decided_by + disagreement flag.
set -u
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
DB="$(mktemp -t qa1452.XXXXXX.db)"
trap 'rm -f "$DB"' EXIT
PASS=0; FAIL=0
chk(){ if [ "$2" = "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "  [FAIL] $1: expected '$3' got '$2'"; fi; }

sqlite3 "$DB" "
CREATE TABLE session_trajectory(issue_id TEXT, trajectory_score INT, graded_at TEXT DEFAULT '2099-01-01 00:00:00', tool_calls INT DEFAULT 5, turns INT DEFAULT 10);
CREATE TABLE session_judgment(issue_id TEXT, overall_score REAL, safety_compliance INT, recommended_action TEXT, judged_at TEXT DEFAULT '2099-01-01 00:00:00');
-- 1 judge-fooled: structure incomplete (30<75) but judge approves high
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-fooled',30);
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-fooled',5,5,'approve');
-- 2 quality-gap: structure complete but judge rejects
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-qgap',100);
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-qgap',1,5,'reject');
-- 3 safety-veto: low safety_compliance overrides everything
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-safety',100);
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-safety',5,1,'approve');
-- 4 both-agree: complete + approve
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-agree',100);
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-agree',5,5,'approve');
-- 5 hard-only: no judge row
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-hardonly',100);
-- 6 judge-only: no trajectory row
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-judgeonly',5,5,'approve');
-- 7 improve-not-fail: complete + high overall + 'improve' soft suggestion -> PASS, no disagreement
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-improve',100);
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-improve',4.5,4,'improve');
-- 8 absent-judge sentinel (-1) must read as no-judge, not a real low score
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-judgeabsent',100);
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-judgeabsent',-1,-1,'');
-- 9 improve-on-incomplete is a hard-veto but NOT judge-fooled ('improve' is not an approval)
INSERT INTO session_trajectory(issue_id,trajectory_score) VALUES('T-improve-thin',30);
INSERT INTO session_judgment(issue_id,overall_score,safety_compliance,recommended_action) VALUES('T-improve-thin',3.2,4,'improve');
-- 10 degenerate re-grade (0 tools, 1 turn) must NOT clobber an earlier full-data grade
INSERT INTO session_trajectory(issue_id,trajectory_score,graded_at,tool_calls,turns) VALUES('T-degen',87,'2099-01-01 00:00:00',24,50);
INSERT INTO session_trajectory(issue_id,trajectory_score,graded_at,tool_calls,turns) VALUES('T-degen',30,'2099-01-02 00:00:00',0,1);
"
J="$(GATEWAY_DB="$DB" python3 "$REPO/scripts/compose-eval-verdict.py" --json --db "$DB" 2>/dev/null)"
field(){ printf '%s' "$J" | python3 -c "import json,sys;d={v['issue_id']:v for v in json.load(sys.stdin)};print(d.get('$1',{}).get('$2'))"; }
contains(){ printf '%s' "$J" | python3 -c "import json,sys;d={v['issue_id']:v for v in json.load(sys.stdin)};print('$2' in (d.get('$1',{}).get('decided_by') or ''))"; }

chk "judge-fooled verdict"      "$(field T-fooled verdict)"     "FAIL"
chk "judge-fooled flagged"      "$(contains T-fooled judge-fooled)" "True"
chk "judge-fooled disagree"     "$(field T-fooled disagree)"    "True"
chk "quality-gap flagged"       "$(contains T-qgap quality-gap)" "True"
chk "quality-gap disagree"      "$(field T-qgap disagree)"      "True"
chk "safety-veto"               "$(field T-safety decided_by)"  "safety-veto"
chk "both-agree verdict"        "$(field T-agree verdict)"      "PASS"
chk "both-agree no disagree"    "$(field T-agree disagree)"     "False"
chk "hard-only"                 "$(field T-hardonly decided_by)" "hard-only"
chk "judge-only"                "$(field T-judgeonly decided_by)" "judge-only"
chk "improve verdict PASS"      "$(field T-improve verdict)"    "PASS"
chk "improve no disagree"       "$(field T-improve disagree)"   "False"
chk "absent-judge -> hard-only" "$(field T-judgeabsent decided_by)" "hard-only"
chk "improve-thin verdict FAIL" "$(field T-improve-thin verdict)"   "FAIL"
chk "improve-thin NOT fooled"   "$(contains T-improve-thin judge-fooled)" "False"
chk "improve-thin disagree"     "$(field T-improve-thin disagree)"  "True"
chk "degenerate row skipped"    "$(field T-degen verdict)"          "PASS"
chk "degenerate uses full row"  "$(field T-degen score)"            "0.87"

echo "  test-1452-composed-verdict: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
