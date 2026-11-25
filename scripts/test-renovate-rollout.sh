#!/bin/bash
# Hermetic test for the staged rollout (Dim-5): renovate-rollout.py (tier-gating + rate cap) and
# renovate-autonomy-promote.py (seed + data-driven promote/demote). Mutable stage lives in a RUNTIME
# state file (NOT the git config) — this test also proves the git config is never mutated. Temp DB + state.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ck(){ if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf 'PASS  %-46s %s\n' "$1" "$2"; else FAIL=$((FAIL+1)); printf 'FAIL  %-46s got %s want %s\n' "$1" "$2" "$3"; fi; }

DB=$(mktemp); STATE=$(mktemp); rm -f "$STATE"     # start with NO state file (missing = no state yet)
CFG="$DIR/../config/renovate-autonomy-rollout.json"
sqlite3 "$DB" < "$DIR/migrations/023_renovate_autonomy_audit.sql"
export GATEWAY_DB="$DB" RENOVATE_ROLLOUT_STATE="$STATE" RENOVATE_ROLLOUT_CONFIG="$CFG"
roll(){ python3 "$DIR/renovate-rollout.py" --tier "$1" --db "$DB" >/dev/null 2>&1; echo $?; }
ins_auto(){ sqlite3 "$DB" "INSERT INTO renovate_autonomy_audit(ts,decision,mode,tier,schema_version) VALUES($1,'AUTO','live','routine',1);"; }
prom(){ python3 "$DIR/renovate-autonomy-promote.py" --db "$DB" --now "$1" --apply; }
setstate(){ python3 -c "import json;json.dump({'stage':'$1','stage_since':$2},open('$STATE','w'))"; }
dec(){ python3 -c 'import json,sys;print(json.load(sys.stdin)["decision"])'; }
NOW=$(date -u +%s)

# ── rollout gate: canary (no state → config initial stage) enables ONLY routine ──
ck "routine ALLOW at canary"                  "$(roll routine)"  "0"
ck "elevated → tier-not-enabled at canary"    "$(roll elevated)" "2"
ck "critical → tier-not-enabled at canary"    "$(roll critical)" "2"
ins_auto "$NOW"; ins_auto "$NOW"; ins_auto "$NOW"
ck "routine HOLD at rate-cap(3/3)"            "$(roll routine)"  "3"

# ── promoter SEEDS the state on first run (no state file) ──
rm -f "$STATE"
ck "promoter seeds stage_since (no deadlock)" "$(prom "$NOW" | dec)" "seeded-stage-since"
ck "state file created (mutable, off-git)"    "$([ -f "$STATE" ] && echo yes)" "yes"

# ── promotion: state=canary + 8 days + 10 clean auto-merges → promote → state=expand ──
setstate canary "$((NOW-8*86400))"; for i in $(seq 1 10); do ins_auto "$NOW"; done
ck "promote decision"                         "$(prom "$NOW" | dec)" "promote"
ck "state advanced canary→expand"             "$(python3 -c 'import json;print(json.load(open("'"$STATE"'"))["stage"])')" "expand"
sqlite3 "$DB" "DELETE FROM renovate_autonomy_audit WHERE decision='AUTO'"   # clear day's cap
ck "elevated now ALLOWED at expand"           "$(roll elevated)" "0"
ck "critical still tier-not-enabled at expand" "$(roll critical)" "2"

# ── demotion: a rollback at the current stage → drop a rung ──
sqlite3 "$DB" "INSERT INTO renovate_autonomy_audit(ts,decision,mode,tier,schema_version) VALUES($NOW,'POSTMERGE_ROLLBACK','live','elevated',1);"
setstate expand "$((NOW-8*86400))"
ck "demote decision on rollback"              "$(prom "$NOW" | dec)" "demote"
ck "state dropped expand→canary"              "$(python3 -c 'import json;print(json.load(open("'"$STATE"'"))["stage"])')" "canary"

# ── the git-tracked config is NEVER mutated by the promoter (drift-sync safe) ──
ck "git config NOT mutated (no stage_since)"  "$(python3 -c 'import json;print("stage_since" in json.load(open("'"$CFG"'")))')" "False"

# ── REGRESSION 2026-07-06: fail CLOSED when the daily-cap count can't be verified ──
# Previously a DB error / missing audit table swallowed to n=0 → ALLOW (rate cap silently disabled).
setstate canary "$NOW"                                   # routine IS enabled at canary → reaches the DB check
EMPTY=$(mktemp)                                          # fresh DB, NO migration → no renovate_autonomy_audit table
OUT_MT=$(python3 "$DIR/renovate-rollout.py" --tier routine --db "$EMPTY" 2>/dev/null)
ck "missing audit table → fail CLOSED (not ALLOW)" "$(echo "$OUT_MT" | grep -q 'audit-table-missing' && echo closed || echo "${OUT_MT:-empty}")" "closed"
OUT_BAD=$(python3 "$DIR/renovate-rollout.py" --tier routine --db "/nonexistent/dir/x.db" 2>/dev/null)
ck "unreadable DB → fail CLOSED (not ALLOW)"       "$([ "$OUT_BAD" != "ALLOW" ] && echo closed || echo ALLOW)" "closed"
rm -f "$EMPTY"

# ── REGRESSION 2026-07-07: synthetic/test rows (mr_iid>=9000) must NOT consume real canary budget ──
# A test harness writing a mode='live' AUTO row into the LIVE db (RENOVATE_FORCE_LIVE / the 9998/9999 stubs)
# once stole a real canary slot → a genuine routine MR was wrongly HOLD:rate-cap'd. The cap must ignore 9000+
# while still counting real (small-int) AND null-iid rows. Proves BOTH directions.
ins_synth(){ sqlite3 "$DB" "INSERT INTO renovate_autonomy_audit(ts,decision,mode,tier,mr_iid,schema_version) VALUES($1,'AUTO','live','routine','9999',1);"; }
ins_real(){ sqlite3 "$DB" "INSERT INTO renovate_autonomy_audit(ts,decision,mode,tier,mr_iid,schema_version) VALUES($1,'AUTO','live','routine','$2',1);"; }
setstate canary "$NOW"                                   # routine enabled, fresh cap window
sqlite3 "$DB" "DELETE FROM renovate_autonomy_audit"      # reset the day's count
ins_real "$NOW" 375; ins_real "$NOW" 376                 # 2 REAL merges (small-int iid → counted)
ins_synth "$NOW"; ins_synth "$NOW"; ins_synth "$NOW"; ins_synth "$NOW"; ins_synth "$NOW"   # +5 synthetic — ignored
ck "synthetic iid>=9000 excluded from cap (2 real<3 → ALLOW)" "$(roll routine)" "0"
ins_real "$NOW" 377                                      # a 3rd REAL merge
ck "3rd REAL merge (iid<9000) DOES hit cap (3/3 → HOLD)"      "$(roll routine)" "3"

rm -f "$DB" "$STATE"
echo; echo "$((PASS+FAIL)) checks, $FAIL failure(s)"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
