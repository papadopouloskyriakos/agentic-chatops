#!/bin/bash
# Hermetic test for the Renovate timeout-to-auto lane (2026-07-07). No network, no live DB, no claude.
# Proves the SAFETY PROPERTIES: only reversible stateful/elevated bumps defer; never_auto (secrets) and
# MAJOR bumps NEVER defer (they escalate); a vetoed MR never merges even after the window; and the whole
# thing is byte-identically OFF unless the timeout sentinel is present. Merge is stubbed (RENOVATE_MERGE_STUB).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE="$DIR/renovate-mr-gate.sh"; LIB="$DIR/lib/renovate_deferred.py"
PASS=0; FAIL=0
ck(){ if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf 'PASS  %-50s %s\n' "$1" "$2"; else FAIL=$((FAIL+1)); printf 'FAIL  %-50s got[%s] want[%s]\n' "$1" "$2" "$3"; fi; }

DB=$(mktemp); SENT=$(mktemp); STATE=$(mktemp); rm -f "$STATE"    # SENT present = armed; no STATE = canary
CFG="$DIR/../config/renovate-autonomy-rollout.json"
for m in 023_renovate_autonomy_audit 024_renovate_autonomy_audit_hashchain 025_renovate_deferred_merges; do
  sqlite3 "$DB" < "$DIR/migrations/$m.sql" 2>/dev/null
done
APPROVE='{"verdict":"APPROVE","confidence":0.95}'
mr(){ # iid title branch labels_json  (stateful minor bump by default)
  jq -nc --arg i "$1" --arg t "$2" --arg b "$3" --argjson l "$4" \
    '{iid:$i,project_id:"7",author:{username:"renovate-bot"},state:"opened",target_branch:"main",title:$t,source_branch:$b,labels:$l,sha:("sha"+$i)}'; }

# run the LIVE gate (FORCE_LIVE) with the timeout sentinel; $5=elapsed(1/0) $6=sentinel-override-path
gate(){ local stub="$1" elapsed="${2:-0}" sent="${3:-$SENT}"
  RENOVATE_MR_STUB="$stub" RENOVATE_CI_STUB=success RENOVATE_REVIEW_STUB="$APPROVE" RENOVATE_SNAPSHOT_STUB=ok \
  RENOVATE_MERGE_STUB=merged RENOVATE_FORCE_LIVE=1 RENOVATE_TIMEOUT_SENTINEL="$sent" RENOVATE_DEDUP_OFF=1 \
  GATEWAY_DB="$DB" RENOVATE_ROLLOUT_STATE="$STATE" RENOVATE_ROLLOUT_CONFIG="$CFG" \
  RENOVATE_DEFERRED_ELAPSED="$elapsed" \
  bash "$GATE" --project 7 --iid "$(echo "$stub"|jq -r .iid)" 2>/dev/null | grep -oE 'RENOVATE_GATE_RESULT:.*' | sed 's/^RENOVATE_GATE_RESULT://'; }
dstatus(){ sqlite3 "$DB" "SELECT status FROM renovate_deferred_merges WHERE mr_iid='$1' ORDER BY id DESC LIMIT 1" 2>/dev/null; }
field(){ echo "$1" | jq -r "$2"; }

CRIT=$(mr 128 "chore(deps): update getmeili/meilisearch docker tag to v1.9" renovate/getmeili-meilisearch-1.x '["renovate"]')
BAO=$(mr 359 "chore(deps): update openbao/openbao docker tag to v2.5.5" renovate/openbao-openbao-2.x '["renovate"]')
MAJ=$(mr 900 "⚠️ [MAJOR] Update postgres Docker tag to v18" renovate/postgres-18.x '["major-update","renovate"]')
HELD=$(mr 228 "chore(deps): update getmeili/meilisearch docker tag to v1.9" renovate/getmeili-meilisearch-1.x '["renovate","renovate-hold"]')

# ── lib eligibility ──
ck "eligible: critical+minor+not-never"     "$(python3 "$LIB" eligible --tier critical --update-type minor_patch --never-auto false)" "1"
ck "NOT eligible: major"                     "$(python3 "$LIB" eligible --tier critical --update-type major --never-auto false)" "0"
ck "NOT eligible: never_auto"                "$(python3 "$LIB" eligible --tier critical --update-type digest --never-auto true)" "0"
ck "NOT eligible: routine tier"              "$(python3 "$LIB" eligible --tier routine --update-type minor_patch --never-auto false)" "0"

# ── 1. NORMAL run of an eligible reversible critical bump → DEFERRED (recorded pending, NOT merged) ──
O=$(gate "$CRIT" 0)
ck "eligible normal → decision POLL"         "$(field "$O" .decision)" "POLL"
ck "eligible normal → acted deferred"        "$(field "$O" .acted | grep -oE '^deferred' || echo no)" "deferred"
ck "eligible normal → deferred row pending"  "$(dstatus 128)" "pending"

# ── 2. ELAPSED run of that same eligible bump → AUTO (merged via stub); deferred row → merged ──
O=$(gate "$CRIT" 1)
ck "eligible elapsed → decision AUTO"         "$(field "$O" .decision)" "AUTO"
ck "eligible elapsed → acted merged"          "$(field "$O" .acted)" "merged"
ck "eligible elapsed → deferred row merged"   "$(dstatus 128)" "merged"

# ── 3. never_auto (openbao) → NEVER deferred; escalates instead ──
O=$(gate "$BAO" 0)
ck "never_auto → decision POLL"               "$(field "$O" .decision)" "POLL"
ck "never_auto → acted polled (not deferred)" "$(field "$O" .acted | grep -oE '^polled' || echo no)" "polled"
ck "never_auto → NO deferred row"             "$([ -z "$(dstatus 359)" ] && echo none || echo "$(dstatus 359)")" "none"
# even on an ELAPSED run a never_auto must NOT merge
O=$(gate "$BAO" 1)
ck "never_auto elapsed → still POLL (no merge)" "$(field "$O" .decision)" "POLL"

# ── 4. MAJOR (data-migrating) → NEVER deferred; escalates ──
O=$(gate "$MAJ" 0)
ck "major → acted polled (not deferred)"      "$(field "$O" .acted | grep -oE '^polled' || echo no)" "polled"
ck "major → NO deferred row"                  "$([ -z "$(dstatus 900)" ] && echo none || echo x)" "none"
O=$(gate "$MAJ" 1)
ck "major elapsed → still POLL (no merge)"    "$(field "$O" .decision)" "POLL"

# ── 5. VETO (hold label) → held, never merges, even on elapsed ──
O=$(gate "$HELD" 1)
ck "vetoed elapsed → decision POLL"           "$(field "$O" .decision)" "POLL"
ck "vetoed elapsed → acted held:vetoed"       "$(field "$O" .acted)" "held:vetoed"

# ── 6. SENTINEL OFF → byte-identical legacy: eligible bump escalates, does NOT defer, does NOT merge ──
NOSENT="$SENT.absent"
O=$(gate "$CRIT" 0 "$NOSENT")
ck "sentinel off → acted polled (legacy)"     "$(field "$O" .acted | grep -oE '^polled' || echo no)" "polled"
O=$(gate "$CRIT" 1 "$NOSENT")
ck "sentinel off + elapsed → still POLL"      "$(field "$O" .decision)" "POLL"

# ── 7. processor sentinel-guard no-op ──
ck "processor no-op when disarmed"            "$(RENOVATE_AUTONOMY_SENTINEL=/nonexistent/x RENOVATE_TIMEOUT_SENTINEL=/nonexistent/y python3 "$DIR/renovate-deferred-merge-processor.py" 2>/dev/null | grep -c 'disarmed')" "1"

# ── pacing (2026-07-07): merges drip out at most max_merges_per_run per tick, not batch ──
ck "processor enforces per-run cap"           "$(grep -c 'merged_this_run >= per_run' "$DIR/renovate-deferred-merge-processor.py")" "1"
ck "config has max_merges_per_run"            "$(python3 -c "import json;print(json.load(open('$CFG'))['timeout_auto'].get('max_merges_per_run'))" 2>/dev/null)" "1"

rm -f "$DB" "$SENT" "$STATE"
echo; echo "$((PASS+FAIL)) checks, $FAIL failure(s)"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
