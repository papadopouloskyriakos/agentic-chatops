#!/bin/bash
# Test harness for scripts/hooks/plan-adherence-gate.py (IFRNLLEI01PRD-1746).
# Isolated scratch DB + scratch sentinel/metrics via the hook's test-seam env
# vars (PLAN_ADHERENCE_SENTINEL/DB/METRICS) — never touches live state.
# Each case feeds hook-JSON on stdin and asserts exit (0 = allow, 2 = pause).
set -u
HOOK="$(cd "$(dirname "$0")" && pwd)/hooks/plan-adherence-gate.py"
TMP=$(mktemp -d)
DB="$TMP/gw.db"; SENT="$TMP/sentinel"; MET="$TMP/metrics.prom"
PASS=0; FAIL=0

sqlite3 "$DB" "
CREATE TABLE infragraph_predictions (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_issue_id TEXT, parent_host TEXT, action_target TEXT, predicted TEXT);
CREATE TABLE session_risk_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT, signals_json TEXT);
INSERT INTO infragraph_predictions (parent_issue_id,parent_host,action_target,predicted)
 VALUES ('IFRNLLEI01PRD-9001','gr-pve01','gr-pve01','[{\"host\":\"grk8s-ctrl01\",\"rule\":\"TargetDown\"}]');
INSERT INTO session_risk_audit (issue_id,signals_json) VALUES ('IFRNLLEI01PRD-9001','[\"host:gr-pve01\",\"category:availability\"]');
"

export PLAN_ADHERENCE_DB="$DB" PLAN_ADHERENCE_METRICS="$MET"

ENF="$TMP/enforce"
t() { # name expected issue sentinel(on/off) command   [runs in ENFORCE mode]
  local name="$1" exp="$2" issue="$3" sflag="$4" cmd="$5" rc
  if [ "$sflag" = "on" ]; then : > "$SENT"; : > "$ENF"; else rm -f "$SENT" "$ENF"; fi
  local json; json=$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$cmd")
  echo "$json" | PLAN_ADHERENCE_SENTINEL="$SENT" PLAN_ADHERENCE_ENFORCE="$ENF" ISSUE_ID="$issue" CLAUDE_SESSION_ID="test" python3 "$HOOK" >/dev/null 2>&1; rc=$?
  if [ "$rc" = "$exp" ]; then PASS=$((PASS+1)); echo "  [PASS] $name (exit $rc)"; else FAIL=$((FAIL+1)); echo "  [FAIL] $name (exit $rc, expected $exp)"; fi
}

echo "=== plan-adherence-gate tests ==="
t "sentinel-off = dark (allow blatant divergence)"      0 "IFRNLLEI01PRD-9001" off "ssh -i ~/.ssh/one_key root@nlpve04 systemctl stop pvestatd"
t "no-issue = interactive (allow)"                      0 ""                  on  "ssh root@nlpve04 systemctl stop pvestatd"
t "read-only cross-host (allow)"                        0 "IFRNLLEI01PRD-9001" on  "ssh -i ~/.ssh/one_key root@nlpve04 uptime"
t "local runner mutating (allow)"                       0 "IFRNLLEI01PRD-9001" on  "systemctl restart cronicle"
t "in-scope mutating (allow)"                           0 "IFRNLLEI01PRD-9001" on  "ssh -i ~/.ssh/one_key root@gr-pve01 systemctl restart pvestatd"
t "in-scope predicted-host mutating (allow)"            0 "IFRNLLEI01PRD-9001" on  "ssh root@grk8s-ctrl01 systemctl restart kubelet"
t "OUT-of-scope mutating (BLOCK)"                       2 "IFRNLLEI01PRD-9001" on  "ssh -i ~/.ssh/one_key root@nlpve04 systemctl stop pvestatd"
t "OUT-of-scope rm -rf (BLOCK)"                         2 "IFRNLLEI01PRD-9001" on  "ssh root@nl-matrix01 rm -rf /var/lib/x"
t "OUT-of-scope qm reboot (BLOCK)"                      2 "IFRNLLEI01PRD-9001" on  "ssh -i ~/.ssh/one_key root@nl-pve02 qm reboot VMID_REDACTED"
t "unknown-issue = no committed scope (allow/indeterm)" 0 "IFRNLLEI01PRD-9999" on  "ssh root@nlpve04 systemctl stop pvestatd"
t "unknown host (allow)"                                0 "IFRNLLEI01PRD-9001" on  "ssh root@somebox-not-infra systemctl stop x"
t "non-Bash-ish local git (allow, not mutating-infra)"  0 "IFRNLLEI01PRD-9001" on  "git status"

# Shadow mode: armed (gate sentinel on) but enforce sentinel OFF → would-block
# but ALLOWS (exit 0). Enforce sentinel ON → pauses (exit 2).
te() { # name expected issue enforce(on/off) command  [gate sentinel always on]
  local name="$1" exp="$2" issue="$3" eflag="$4" cmd="$5" rc
  : > "$SENT"
  local ES="$TMP/enforce"; [ "$eflag" = "on" ] && : > "$ES" || rm -f "$ES"
  local json; json=$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$cmd")
  echo "$json" | PLAN_ADHERENCE_SENTINEL="$SENT" PLAN_ADHERENCE_ENFORCE="$ES" ISSUE_ID="$issue" CLAUDE_SESSION_ID="test" python3 "$HOOK" >/dev/null 2>&1; rc=$?
  if [ "$rc" = "$exp" ]; then PASS=$((PASS+1)); echo "  [PASS] $name (exit $rc)"; else FAIL=$((FAIL+1)); echo "  [FAIL] $name (exit $rc, expected $exp)"; fi
}
te "SHADOW: out-of-scope would-block but ALLOWS"        0 "IFRNLLEI01PRD-9001" off "ssh root@nlpve04 systemctl stop pvestatd"
te "ENFORCE: out-of-scope PAUSES"                       2 "IFRNLLEI01PRD-9001" on  "ssh root@nlpve04 systemctl stop pvestatd"

echo ""
echo "RESULT: $PASS pass / $FAIL fail"
rm -rf "$TMP"
[ "$FAIL" = 0 ]
