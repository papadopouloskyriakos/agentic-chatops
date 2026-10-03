#!/bin/bash
# Hermetic offline test for scripts/renovate-mr-gate.sh — no network, no live DB, no claude.
# Proves: the Renovate/opened/main filter; tier→gate routing; each of the 3 gates blocking
# independently; and the SAFETY PROPERTY that a stateful (critical) bump cannot AUTO-merge
# until the Phase-3 snapshot gate exists. All runs are --dry-run (shadow) against a mktemp DB.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$DIR/renovate-mr-gate.sh"
export GATEWAY_DB="$(mktemp)"
PASS=0; FAIL=0

mr(){ # author state target title branch labels_json
  jq -nc --arg a "$1" --arg s "$2" --arg t "$3" --arg ti "$4" --arg b "$5" --argjson l "$6" \
    '{iid:"999",project_id:"30",author:{username:$a},state:$s,target_branch:$t,title:$ti,source_branch:$b,labels:$l}'; }

run(){ # name expected_decision  MR_STUB  [CI_STUB REVIEW_STUB SNAP_STUB]
  local name="$1" exp="$2" mrjson="$3" ci="${4:-}" rv="${5:-}" sn="${6:-}"
  local out dec
  out=$(RENOVATE_MR_STUB="$mrjson" RENOVATE_CI_STUB="$ci" RENOVATE_REVIEW_STUB="$rv" RENOVATE_SNAPSHOT_STUB="$sn" \
        bash "$GATE" --dry-run --project 30 --iid 999 2>/dev/null | grep -oE 'RENOVATE_GATE_RESULT:.*' | sed 's/^RENOVATE_GATE_RESULT://')
  dec=$(echo "$out" | jq -r '.decision' 2>/dev/null)
  if [ "$dec" = "$exp" ]; then PASS=$((PASS+1)); printf 'PASS  %-42s → %s\n' "$name" "$dec"
  else FAIL=$((FAIL+1)); printf 'FAIL  %-42s → got %s want %s  [%s]\n' "$name" "$dec" "$exp" "$out"; fi; }

APPROVE_HI='{"verdict":"APPROVE","confidence":0.95}'
APPROVE_MID='{"verdict":"APPROVE","confidence":0.83}'
APPROVE_LOW='{"verdict":"APPROVE","confidence":0.75}'
REJECT='{"verdict":"REQUEST_CHANGES","confidence":0.9}'

ROUTINE=$(mr renovate-bot opened main "chore(deps): update nginx docker tag to v1.29" renovate/nginx-1.x '["renovate"]')
ELEV=$(mr renovate-bot opened main "⚠️ [MAJOR] Update ubuntu Docker tag to v24" renovate/ubuntu-24.x '["major-update","renovate"]')
CRIT=$(mr renovate-bot opened main "⚠️ [MAJOR] Update postgres Docker tag to v18" renovate/postgres-18.x '["major-update","renovate"]')

# ── filter ──
run "filter: non-renovate author"      SKIP "$(mr Administrator opened main 'x' feature/x '[]')"
run "filter: state merged"             SKIP "$(mr renovate-bot merged main 'x' renovate/nginx-1.x '["renovate"]')"
run "filter: target develop"           SKIP "$(mr renovate-bot opened develop 'x' renovate/nginx-1.x '["renovate"]')"
# ── routine (τ 0.80) ──
run "routine + CI ok + approve"        AUTO "$ROUTINE" success "$APPROVE_MID"
run "routine + CI failed → CI gate"    POLL "$ROUTINE" failed  "$APPROVE_HI"
run "routine + reject → review gate"   POLL "$ROUTINE" success "$REJECT"
run "routine + conf<τ → confidence"    POLL "$ROUTINE" success "$APPROVE_LOW"
# ── elevated (stateless major, τ 0.90, no snapshot) ──
run "elevated + CI ok + approve0.95"   AUTO "$ELEV" success "$APPROVE_HI"
run "elevated + approve0.83<0.90"      POLL "$ELEV" success "$APPROVE_MID"
# ── critical (stateful): SAFETY — cannot AUTO without a verified snapshot ──
run "critical + all-pass, NO snapshot" POLL "$CRIT" success "$APPROVE_HI"
run "critical + snapshot ok → AUTO"    AUTO "$CRIT" success "$APPROVE_HI" ok
run "critical + snapshot fail → POLL"  POLL "$CRIT" success "$APPROVE_HI" fail
# ── P3 wiring end-to-end (real renovate-presnapshot.sh --dry-run through the gate; no side effects) ──
CRIT_PG='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"⚠️ [MAJOR] Update postgres Docker tag to v18","source_branch":"renovate/postgres-18.x","labels":["major-update","renovate"],"changes":[{"new_path":"docker/nldocuseal01/docuseal/docker-compose.yml"}]}'
CRIT_MILVUS='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"chore(deps): update milvusdb/milvus docker tag to v2.6.19","source_branch":"renovate/milvusdb-milvus-2.x","labels":["renovate"],"changes":[{"new_path":"docker/nl-gpu01/milvus/docker-compose.yml"}]}'
CRIT_ES='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"⚠️ [MAJOR] Update elasticsearch Docker tag to v9","source_branch":"renovate/elasticsearch-9.x","labels":["major-update","renovate"],"changes":[{"new_path":"docker/nles01/es/docker-compose.yml"}]}'
CRIT_BAO='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"chore(deps): update openbao/openbao docker tag to v2.5.5","source_branch":"renovate/openbao-openbao-2.x","labels":["renovate"],"changes":[{"new_path":"docker/nlk8s-openbao01/openbao/docker-compose.yml"}]}'
run "critical+host postgres → AUTO (P3)"  AUTO "$CRIT_PG" success "$APPROVE_HI"
run "critical+host milvus recipe → AUTO"  AUTO "$CRIT_MILVUS" success "$APPROVE_HI"
run "critical+host elasticsearch generic → AUTO" AUTO "$CRIT_ES" success "$APPROVE_HI"
run "critical+host openbao → POLL (always)" POLL "$CRIT_BAO" success "$APPROVE_HI"
run "never_auto(openbao) POLLs even w/ snapshot ok" POLL "$CRIT_BAO" success "$APPROVE_HI" ok
# a completely UNKNOWN engine fails closed to critical → snapshot-gated (generic recipe → still AUTO-able)
CRIT_UNK='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"chore(deps): update surrealdb docker tag to v2","source_branch":"renovate/surrealdb-2.x","labels":["renovate"],"changes":[{"new_path":"docker/nlx01/surreal/docker-compose.yml"}]}'
CRIT_UNK_NOHOST='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"chore(deps): update surrealdb docker tag to v2","source_branch":"renovate/surrealdb-2.x","labels":["renovate"]}'
run "unknown engine + snapshot ok → AUTO"    AUTO "$CRIT_UNK" success "$APPROVE_HI"
run "unknown engine, no host → POLL"         POLL "$CRIT_UNK_NOHOST" success "$APPROVE_HI"

# ── REGRESSION 2026-07-06: gate must NOT re-fetch via --project/--iid ──────────
# That spawns a classifier subprocess needing GITLAB_TOKEN in its own env; .env bare-assigns the token
# (no `export`) → empty $CLS → fail-safe (critical/unknown/never_auto=false) on EVERY production run, so
# the canary could never classify a routine bump → never auto-merge. The gate must feed the fetched MR.
if grep -qE 'classify-renovate-mr\.py"? --project' "$GATE"; then
  FAIL=$((FAIL+1)); echo "FAIL  gate re-fetches classifier via --project/--iid (token-subprocess trap)"
else PASS=$((PASS+1)); echo "PASS  gate feeds MR to classifier (no token-subprocess re-fetch)"; fi
if grep -qE 'merge_requests/\$MR_IID/changes' "$GATE"; then
  PASS=$((PASS+1)); echo "PASS  gate fetches the /changes MR variant (diff → affected_host)"
else FAIL=$((FAIL+1)); echo "FAIL  gate should fetch /changes so the classifier gets the diff"; fi
# REGRESSION 2026-07-06: .env must be EXPORTED (set -a) so subprocesses that read os.environ get it —
# renovate-escalate.py's GITLAB_TOKEN/MATRIX_* (MR comment + Matrix) silently no-op'd on !359 without this.
if grep -qE 'set -a; *source "\$REPO_DIR/\.env"; *set \+a' "$GATE"; then
  PASS=$((PASS+1)); echo "PASS  gate exports .env to subprocesses (escalate/rollout get their env)"
else FAIL=$((FAIL+1)); echo "FAIL  gate must set -a around source .env (subprocess env propagation)"; fi

# ── REGRESSION 2026-07-06: dedup rapid duplicate webhooks for the same head SHA ──
# Live !359 double-fired (open + self-assign) → 2 reviews + 2 audit rows. Dedup on (project,iid,sha).
gd(){ RENOVATE_MR_STUB="$1" RENOVATE_CI_STUB="${2:-running}" RENOVATE_REVIEW_STUB="$APPROVE_HI" \
      RENOVATE_DEDUP_BASE="$DDIR" bash "$GATE" --dry-run --project 30 --iid 999 2>/dev/null \
      | grep -oE 'RENOVATE_GATE_RESULT:.*' | sed 's/^RENOVATE_GATE_RESULT://'; }
DDIR=$(mktemp -d)
SHA1='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"chore(deps): update nginx docker tag to v1.29","source_branch":"renovate/nginx-1.x","labels":["renovate"],"sha":"aaaa1111bbbb2222"}'
SHA2='{"iid":"999","project_id":"30","author":{"username":"renovate-bot"},"state":"opened","target_branch":"main","title":"chore(deps): update nginx docker tag to v1.29","source_branch":"renovate/nginx-1.x","labels":["renovate"],"sha":"cccc3333dddd4444"}'
r1=$(gd "$SHA1" | jq -r '.decision'); r2=$(gd "$SHA1" | jq -r '.decision +"/"+ .reason'); r3=$(gd "$SHA2" | jq -r '.decision')
[ "$r1" != "SKIP" ]        && { PASS=$((PASS+1)); echo "PASS  dedup: first sighting processed ($r1)"; }        || { FAIL=$((FAIL+1)); echo "FAIL  dedup: first sighting should process, got $r1"; }
[ "$r2" = "SKIP/dup-sha" ] && { PASS=$((PASS+1)); echo "PASS  dedup: same-sha duplicate → SKIP/dup-sha"; }       || { FAIL=$((FAIL+1)); echo "FAIL  dedup: same-sha should SKIP/dup-sha, got $r2"; }
[ "$r3" != "SKIP" ]        && { PASS=$((PASS+1)); echo "PASS  dedup: different sha NOT deduped ($r3)"; }          || { FAIL=$((FAIL+1)); echo "FAIL  dedup: different sha should process, got $r3"; }
rm -rf "$DDIR"

# ── audit table populated ──
ROWS=$(sqlite3 "$GATEWAY_DB" "SELECT COUNT(*) FROM renovate_autonomy_audit" 2>/dev/null || echo 0)
SKIPS=$(sqlite3 "$GATEWAY_DB" "SELECT COUNT(*) FROM renovate_autonomy_audit WHERE decision='SKIP'" 2>/dev/null || echo 0)
echo "--- audit rows: $ROWS (skips=$SKIPS) ; all mode=shadow: $(sqlite3 "$GATEWAY_DB" "SELECT CASE WHEN COUNT(*)=SUM(mode='shadow') THEN 'yes' ELSE 'NO' END FROM renovate_autonomy_audit")"
[ "$ROWS" -ge 12 ] && PASS=$((PASS+1)) && echo "PASS  audit rows written (>=12)" || { FAIL=$((FAIL+1)); echo "FAIL  audit rows"; }

rm -f "$GATEWAY_DB"
echo; echo "$((PASS+FAIL)) checks, $FAIL failure(s)"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
