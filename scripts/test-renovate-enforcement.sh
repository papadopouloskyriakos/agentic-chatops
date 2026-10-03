#!/bin/bash
# Hermetic tests for the independent-enforcement + escalation + auto-rollback layer:
#   - scripts/lib/renovate_floor.py   (the AUTO-merge floor, policy separate from mechanism)
#   - scripts/renovate-escalate.py    (POLL → page the operator)
#   - scripts/renovate-postmerge-verify.sh (post-merge health check + auto-rollback)
# No network, no live DB, no SSH (all stubbed / --dry-run).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ck(){ if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf 'PASS  %-44s %s\n' "$1" "$2"; else FAIL=$((FAIL+1)); printf 'FAIL  %-44s got %s want %s\n' "$1" "$2" "$3"; fi; }

floor(){ echo "$1" | python3 "$DIR/lib/renovate_floor.py" >/dev/null 2>&1; echo $?; }
GOOD='{"ci_status":"success","review_verdict":"APPROVE","review_confidence":0.95,"confidence_threshold":0.9,"snapshot_required":true,"snapshot_verified":true,"never_auto":false,"head_sha_changed":false}'
ck "floor ALLOW when all pass"          "$(floor "$GOOD")" "0"
ck "floor DENY ci not success"          "$(floor '{"ci_status":"failed","review_verdict":"APPROVE","review_confidence":0.95,"confidence_threshold":0.9}')" "1"
ck "floor DENY review not APPROVE"      "$(floor '{"ci_status":"success","review_verdict":"REQUEST_CHANGES","review_confidence":0.95,"confidence_threshold":0.9}')" "1"
ck "floor DENY confidence<threshold"    "$(floor '{"ci_status":"success","review_verdict":"APPROVE","review_confidence":0.80,"confidence_threshold":0.9}')" "1"
ck "floor DENY snapshot not verified"   "$(floor '{"ci_status":"success","review_verdict":"APPROVE","review_confidence":0.95,"confidence_threshold":0.9,"snapshot_required":true,"snapshot_verified":false}')" "1"
ck "floor DENY never_auto"              "$(floor '{"ci_status":"success","review_verdict":"APPROVE","review_confidence":0.95,"confidence_threshold":0.9,"never_auto":true}')" "1"
ck "floor DENY head sha moved (TOCTOU)" "$(floor '{"ci_status":"success","review_verdict":"APPROVE","review_confidence":0.95,"confidence_threshold":0.9,"head_sha_changed":true}')" "1"
ck "floor DENY bad input (fail closed)" "$(echo 'not json' | python3 "$DIR/lib/renovate_floor.py" >/dev/null 2>&1; echo $?)" "1"

# escalation: dry-run runs all channels, exits 0
esc=$(python3 "$DIR/renovate-escalate.py" --project 30 --iid 999 --tier critical --package pg --sha abc --reason t --dry-run 2>&1; echo "rc=$?")
ck "escalate dry-run exits 0"           "$(echo "$esc" | grep -oE 'rc=[0-9]+')" "rc=0"
ck "escalate names the SMS bridge"      "$(echo "$esc" | grep -c 'would-sms')" "1"

# post-merge verify: healthy → ok(0); unhealthy(dry) → rollback(1)
DB=$(mktemp)
GATEWAY_DB="$DB" RENOVATE_HEALTH_STUB=healthy bash "$DIR/renovate-postmerge-verify.sh" --host h --service pg --project 30 --iid 1 --dry-run >/dev/null 2>&1
ck "postmerge healthy → exit 0"         "$?" "0"
GATEWAY_DB="$DB" RENOVATE_HEALTH_STUB=unhealthy bash "$DIR/renovate-postmerge-verify.sh" --host h --service pg --project 30 --iid 2 --snapshot-required true --restore "dump:h:x" --dry-run >/dev/null 2>&1
ck "postmerge unhealthy → exit 1 (rollback)" "$?" "1"
OKROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM renovate_autonomy_audit WHERE decision='POSTMERGE_OK'" 2>/dev/null)
RBROWS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM renovate_autonomy_audit WHERE decision='POSTMERGE_ROLLBACK'" 2>/dev/null)
ck "postmerge OK audited"               "$OKROWS" "1"
ck "postmerge ROLLBACK audited"         "$RBROWS" "1"

# regression (red-team Dim-6): the hash chain must stay intact with INTEGER-valued confidence rows
# (0 or 1), which SKIP/POLL rows carry — previously str(0)!=str(0.0) falsely reported BROKEN.
CDB=$(mktemp)
python3 "$DIR/lib/renovate_audit.py" append --db "$CDB" --json '{"decision":"SKIP","reason":"x","review_confidence":0,"mode":"shadow"}' >/dev/null
python3 "$DIR/lib/renovate_audit.py" append --db "$CDB" --json '{"decision":"AUTO","review_confidence":0.95,"mode":"live"}' >/dev/null
python3 "$DIR/lib/renovate_audit.py" append --db "$CDB" --json '{"decision":"AUTO","review_confidence":1,"mode":"live"}' >/dev/null
ck "chain OK with integer-confidence rows" "$(python3 "$DIR/lib/renovate_audit.py" verify --db "$CDB" >/dev/null 2>&1; echo $?)" "0"
rm -f "$CDB"

# regression (red-team Dim-3): post-merge revert is HELD for stateful, auto for stateless
sf=$(GATEWAY_DB=$(mktemp) RENOVATE_HEALTH_STUB=unhealthy bash "$DIR/renovate-postmerge-verify.sh" --host h --service pg --project 30 --iid 9 --snapshot-required true --restore "dump:h:x" --dry-run 2>/dev/null)
ck "postmerge stateful → held-for-operator" "$(echo "$sf" | grep -c 'held-for-operator')" "1"
sl=$(GATEWAY_DB=$(mktemp) RENOVATE_HEALTH_STUB=unhealthy bash "$DIR/renovate-postmerge-verify.sh" --host h --service nginx --project 30 --iid 9 --snapshot-required false --dry-run 2>/dev/null)
ck "postmerge stateless → would-revert"     "$(echo "$sl" | grep -c 'would-revert')" "1"
rm -f "$DB"

echo; echo "$((PASS+FAIL)) checks, $FAIL failure(s)"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
