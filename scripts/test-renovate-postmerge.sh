#!/usr/bin/env bash
# test-renovate-postmerge.sh — regression guard for renovate-postmerge-verify.sh (the auto-rollback net).
# INVARIANT (2026-07-07): a container that is never LOCATED post-merge is INCONCLUSIVE → escalate, NEVER
# revert (broadening host-detection to edge/dmz + Dockerfile layouts must not risk spurious auto-reverts of
# a good deploy). Only a container that IS found and stays unhealthy triggers a revert.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ck(){ if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf 'PASS  %-52s %s\n' "$1" "$2"; else FAIL=$((FAIL+1)); printf 'FAIL  %-52s got %s want %s\n' "$1" "$2" "$3"; fi; }

run(){ # $1=stub  $2=snapshot_required
  RENOVATE_HEALTH_STUB="$1" RENOVATE_POSTMERGE_DRY=1 GATEWAY_DB="$(mktemp)" \
    bash "$DIR/renovate-postmerge-verify.sh" --host testhost --service testsvc --project 7 --iid 9999 \
      --merge-sha deadbeefcafe --snapshot-required "${2:-false}" 2>/dev/null \
    | grep -o '"result":"[a-z]*"' | cut -d'"' -f4
}

ck "healthy container → ok"                       "$(run healthy false)"    "ok"
ck "found + unhealthy (stateless) → rollback"     "$(run unhealthy false)"  "rollback"
ck "found + unhealthy (stateful) → rollback-hold" "$(run unhealthy true)"   "rollback"
ck "NOT FOUND → inconclusive (NEVER revert)"      "$(run notfound false)"   "inconclusive"
ck "NOT FOUND + stateful → inconclusive"          "$(run notfound true)"    "inconclusive"

echo; echo "$((PASS+FAIL)) checks, $FAIL failure(s)"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
