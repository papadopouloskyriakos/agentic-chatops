#!/usr/bin/env bash
# IFRNLLEI01PRD-1408 R0 — the auto-resolve lane MUST consult the infragraph action
# verdict. An executed (action-prediction-bearing) AUTO session auto-resolves ONLY on
# verdict=match; deviation/partial/stale -> demoted; pending -> skip; read-only/confirm-
# close (no action prediction) -> resolves as before. Guards reconcile-completed-sessions.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="1408-autoresolve-verdict-gate"
REC="$REPO_ROOT/scripts/reconcile-completed-sessions.py"

# r0 <verdict|none|NOPRED> <evaluated 0/1> <age_h>  -> prints resolution_type or 'skip'
r0() {
python3 - "$1" "$2" "$3" "$REC" <<'PY'
import sqlite3,time,base64,importlib.util,sys
verdict,evaluated,age_h,rec_path=sys.argv[1],sys.argv[2],float(sys.argv[3]),sys.argv[4]
spec=importlib.util.spec_from_file_location("rec",rec_path);rec=importlib.util.module_from_spec(spec);spec.loader.exec_module(rec)
conn=sqlite3.connect(":memory:");conn.row_factory=sqlite3.Row
conn.execute("CREATE TABLE infragraph_predictions(id INTEGER PRIMARY KEY,kind TEXT,parent_issue_id TEXT,verdict TEXT,evaluated_at TEXT)")
if verdict!="NOPRED":
    ev=time.strftime("%Y-%m-%d %H:%M:%S") if evaluated=="1" else None
    v=None if verdict=="none" else verdict
    conn.execute("INSERT INTO infragraph_predictions(kind,parent_issue_id,verdict,evaluated_at) VALUES('action','I',?,?)",(v,ev));conn.commit()
class A:min_idle_min=15.0;very_old_h=48.0;recent_h=24.0;dry_run=True
row={"issue_id":"I","last_response_b64":base64.b64encode(b"[AUTO-RESOLVE] done").decode(),"paused":0,"session_id":"s12345678"}
d=rec.classify_session(row,"AUTO",age_h,A(),conn)
print(d.get("resolution_type") or d["action"])
PY
}
start_test "verdict_match_auto_resolves";         assert_eq auto_resolved "$(r0 match 1 1)";     end_test
start_test "verdict_deviation_demoted";           assert_eq completed     "$(r0 deviation 1 1)"; end_test
start_test "verdict_partial_demoted";             assert_eq completed     "$(r0 partial 1 1)";   end_test
start_test "verdict_pending_young_skips";         assert_eq skip          "$(r0 none 0 1)";      end_test
start_test "verdict_stale_old_demoted";           assert_eq completed     "$(r0 none 0 50)";     end_test
start_test "no_action_pred_confirm_close_resolves"; assert_eq auto_resolved "$(r0 NOPRED 0 1)";  end_test
start_test "unevaluated_match_not_trusted_skips"; assert_eq skip          "$(r0 match 0 1)";     end_test
