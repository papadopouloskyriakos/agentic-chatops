#!/usr/bin/env bash
# renovate-atlantis-review.sh — the Atlantis discipline for k8s/IaC Renovate MRs, mechanized.
#
# WHY: the Renovate autonomy lane classifies reversibility but cannot do the Atlantis-specific
# handling a k8s/helm/terraform MR needs (2026-07-07 gap). classify-renovate-mr.py now emits
# atlantis_managed=true + never_auto for these so they POLL instead of auto-applying blind — and
# THIS script satisfies the gates mechanically: rebase-onto-main → atlantis plan → parse the plan
# for reversions/destroys → emit SAFE/UNSAFE + whether a canary is required. It automates the
# mechanical parts (rebase, plan, plan-parse) and REFUSES to auto-apply the judgment parts (canary
# controllers like cilium/ingress) — those it prints the procedure for and stops.
#
# Usage:
#   source .env    # GITLAB_TOKEN
#   scripts/renovate-atlantis-review.sh <project_id> <mr_iid>            # review only (rebase+plan+verdict)
#   scripts/renovate-atlantis-review.sh <project_id> <mr_iid> --apply    # + apply -p k8s + merge IF safe & non-canary
#
# Exit: 0 = SAFE (and applied+merged if --apply), 2 = needs-canary/operator, 3 = UNSAFE (reversion/destroy), 1 = error.
set -uo pipefail

API="${GITLAB_ENDPOINT:-https://gitlab.example.net/api/v4}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID="${1:?project_id required}"; IID="${2:?mr_iid required}"; APPLY="${3:-}"
[ -n "${GITLAB_TOKEN:-}" ] || { echo "GITLAB_TOKEN not set (source .env)"; exit 1; }
gcurl(){ curl -sk -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$@"; }
ts(){ date -u +%H:%M:%SZ; }

MR=$(gcurl "$API/projects/$PID/merge_requests/$IID")
TITLE=$(echo "$MR" | jq -r '.title // ""')
echo "[$(ts)] !$IID — $TITLE"

# 1) classify — bail if this is not an Atlantis MR (docker MRs use the normal lane)
CLS=$(gcurl "$API/projects/$PID/merge_requests/$IID/changes" | python3 "$SCRIPT_DIR/classify-renovate-mr.py" --mr-json - 2>/dev/null)
ATL=$(echo "$CLS" | jq -r '.atlantis_managed'); CANARY=$(echo "$CLS" | jq -r '.atlantis_canary_required')
[ "$ATL" = "true" ] || { echo "  not atlantis_managed (tier=$(echo "$CLS"|jq -r .tier)) — use the normal lane"; exit 1; }
echo "  atlantis_managed=true canary_required=$CANARY gates=$(echo "$CLS"|jq -c '.required_gates')"

# 2) rebase onto main (else the whole-project plan reverts a just-merged sibling MR)
echo "[$(ts)] rebasing onto main…"
gcurl -X PUT "$API/projects/$PID/merge_requests/$IID/rebase" >/dev/null
for i in $(seq 1 20); do
  R=$(gcurl "$API/projects/$PID/merge_requests/$IID?include_rebase_in_progress=true")
  [ "$(echo "$R"|jq -r '.rebase_in_progress')" = "false" ] && { ERR=$(echo "$R"|jq -r '.merge_error // "none"'); echo "  rebased (merge_error=$ERR)"; break; }
  sleep 5
done

# 3) atlantis plan
echo "[$(ts)] atlantis plan…"
TRIG=$(date -u +%s)
gcurl -X POST --data-urlencode "body=atlantis plan" "$API/projects/$PID/merge_requests/$IID/notes" >/dev/null
BODY=""
for i in $(seq 1 24); do
  BODY=$(gcurl "$API/projects/$PID/merge_requests/$IID/notes?per_page=30&sort=desc&order_by=created_at" \
    | jq -r --argjson t "$TRIG" '[.[]|select((.author.username|test("atlantis";"i")) and ((.created_at|fromdateiso8601)>$t) and (.body|test("Ran Plan|Plan Failed|No changes")))]|.[0].body // empty')
  [ -n "$BODY" ] && ! echo "$BODY" | grep -q "state lock\|locked by" && break
  if echo "$BODY" | grep -q "state lock\|locked by"; then echo "  ⏳ state-lock contention — pausing (don't fire back-to-back), retry…"; sleep 20; BODY=""; fi
  sleep 10
done
[ -n "$BODY" ] || { echo "  ✗ no plan result (timeout / lock) — retry later"; exit 1; }

# 4) parse the plan — the halt-gate: no destroys, no version reversions, no forces-replacement
SUMMARY=$(echo "$BODY" | grep -iE 'Plan: [0-9]+ to add' | head -1)
DESTROYS=$(echo "$BODY" | grep -icE 'will be destroyed|forces replacement|must be replaced')
# version reversions: a resource-level ~ version "NEW" -> "OLD" where OLD<NEW would revert a prior merge.
REVERSIONS=$(echo "$BODY" | grep -E '~ +version +=? *"[0-9][^"]*" *-> *"[0-9]' | head -8)
RESOURCES=$(echo "$BODY" | grep -iE '# module.*will be|# [a-z_].*will be' | sed 's/^/    /')
echo "[$(ts)] PLAN: ${SUMMARY:-<none>}"
echo "  resources changing:"; echo "$RESOURCES" | head -12
echo "  destroys/replacements: $DESTROYS"
[ -n "$REVERSIONS" ] && { echo "  ⚠ VERSION REVERSIONS (stale branch would undo a prior merge):"; echo "$REVERSIONS" | sed 's/^/    /'; }

VERDICT="SAFE"
[ "$DESTROYS" -gt 0 ] 2>/dev/null && VERDICT="UNSAFE"
[ -n "$REVERSIONS" ] && VERDICT="UNSAFE"
echo "[$(ts)] VERDICT: $VERDICT"

if [ "$VERDICT" = "UNSAFE" ]; then
  echo "  → HALT. Plan has a destroy/replacement or a version reversion. Do NOT apply. Investigate."
  exit 3
fi
if [ "$CANARY" = "true" ]; then
  echo "  → SAFE plan, but this is a high-blast-radius controller (CNI/ingress) → requires a CANARY."
  echo "    Do NOT blind-apply. Follow the canary procedure (per-node health/egress gate + rollback-ready):"
  echo "    e.g. cilium: apply with wait=false → gate each node (SSH + curl https://1.1.1.1) → rollback"
  echo "    (kubectl rollout undo daemonset/cilium) on any failure. See memory/cilium_1_19_upgrade_20260707."
  exit 2
fi
if [ "$APPLY" = "--apply" ]; then
  echo "[$(ts)] --apply + SAFE + non-canary → atlantis apply -p k8s"
  gcurl -X POST --data-urlencode "body=atlantis apply -p k8s" "$API/projects/$PID/merge_requests/$IID/notes" >/dev/null
  for i in $(seq 1 30); do
    N=$(gcurl "$API/projects/$PID/merge_requests/$IID/notes?per_page=8&sort=desc&order_by=created_at" | jq -r '.[].body')
    echo "$N" | grep -qE 'Apply complete!' && { echo "  APPLY COMPLETE"; break; }
    echo "$N" | grep -qE 'Apply Failed|Apply Error' && { echo "  ✗ APPLY ERROR — investigate"; exit 1; }
    sleep 10
  done
  SHA=$(gcurl "$API/projects/$PID/merge_requests/$IID" | jq -r '.sha')
  gcurl -X PUT --data-urlencode "sha=$SHA" --data-urlencode "should_remove_source_branch=true" "$API/projects/$PID/merge_requests/$IID/merge" \
    | jq -r 'if .merged_at then "  MERGED ✓ \(.merge_commit_sha[0:12])" else "  MERGE: \(.message//.)" end'
else
  echo "  → SAFE + non-canary. Re-run with --apply to atlantis-apply + merge, or apply manually."
fi
exit 0
