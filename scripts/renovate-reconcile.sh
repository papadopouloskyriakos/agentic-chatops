#!/usr/bin/env bash
# renovate-reconcile.sh — CI-timing catch-up for the Renovate autonomy lane.
#
# WHY (2026-07-07): the lane evaluates an MR on the GitLab webhook (MR opened), when its pipeline is
# still `created`/`running` → CI_OK=0 → POLL. GitLab does NOT re-fire the MR webhook when CI later
# goes green, so a routine bump that WOULD auto-merge stays POLLed forever (the audit showed
# ci_status=created/running on the POLLed routine MRs). This reconciler — run on the heartbeat or a
# cron — re-feeds every open renovate-bot MR whose CI is NOW success back through the SAME gate. All
# the gate's safety runs unchanged (classify → structural/Claude review → snapshot → floor → merge);
# routine version bumps auto-merge, k8s/Atlantis + secret stores + stateful re-POLL harmlessly.
# Idempotent: the gate's own (project,iid,sha) dedup + the deferred ledger prevent double-merges.
#
# Usage: scripts/renovate-reconcile.sh            # projects from $RENOVATE_PROJECTS (default "7 30")
#        RENOVATE_RECONCILE_DRYRUN=1 scripts/renovate-reconcile.sh   # list only, don't feed the gate
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HOME/gitlab/n8n/claude-gateway/.env" ] && { set -a; . "$HOME/gitlab/n8n/claude-gateway/.env"; set +a; }
API="${GITLAB_ENDPOINT:-https://gitlab.example.net/api/v4}"
[ -n "${GITLAB_TOKEN:-}" ] || { echo "GITLAB_TOKEN not set"; exit 1; }
gcurl(){ curl -sk -H "PRIVATE-TOKEN: $GITLAB_TOKEN" "$@"; }
ts(){ date -u +%H:%M:%SZ; }
PROJECTS="${RENOVATE_PROJECTS:-7 30}"
VETO_LABEL="renovate-hold"
fed=0; skipped=0

for PID in $PROJECTS; do
  MRS=$(gcurl "$API/projects/$PID/merge_requests?state=opened&per_page=100")
  # renovate-bot MRs only (author or the 'renovate' label), not veto-labeled
  echo "$MRS" | jq -c '.[] | select((.author.username|test("renovate";"i")) or ((.labels//[])|index("renovate")))
     | {iid, sha, title, author:.author.username, labels}' 2>/dev/null | while read -r MR; do
    IID=$(echo "$MR" | jq -r '.iid'); SHA=$(echo "$MR" | jq -r '.sha')
    if echo "$MR" | jq -e --arg L "$VETO_LABEL" '(.labels//[])|index($L)' >/dev/null 2>&1; then
      echo "[$(ts)] !$PID·$IID SKIP (veto label)"; continue; fi
    CI=$(gcurl "$API/projects/$PID/merge_requests/$IID/pipelines" | jq -r '.[0].status // "none"')
    if [ "$CI" != "success" ]; then echo "[$(ts)] !$PID·$IID skip (ci=$CI, not green yet)"; continue; fi
    echo "[$(ts)] !$PID·$IID ci=success → re-feed gate ($(echo "$MR"|jq -r '.title'|cut -c1-50))"
    [ "${RENOVATE_RECONCILE_DRYRUN:-0}" = "1" ] && continue
    # Re-feed via the direct --project/--iid path (the gate re-runs every safety gate; it SKIPs a merged
    # or non-opened MR itself, and its (project,iid,sha) dedup makes a repeated pass idempotent).
    bash "$SCRIPT_DIR/renovate-mr-gate.sh" --project "$PID" --iid "$IID" 2>&1 | grep -iE 'DECISION|ACTED|merged|GATE_RESULT|classified' | sed 's/^/    /'
  done
done
echo "[$(ts)] reconcile pass done"
