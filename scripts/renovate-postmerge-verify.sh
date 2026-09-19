#!/usr/bin/env bash
# renovate-postmerge-verify.sh — post-merge health check + AUTOMATED rollback (Dim-3).
#
# Launched async (nohup) by renovate-mr-gate.sh after a live AUTO merge. The docker plane auto-deploys
# `compose pull && up -d` seconds after merge, so a merge that boots a broken image would otherwise sit
# unwatched. This waits for the redeploy, polls the affected container's health for a window, and:
#   - healthy  → record POSTMERGE_OK, done.
#   - unhealthy → AUTO-REVERT the deploy (GitLab revert API on main → CI redeploys the OLD image) and
#     PAGE the operator. For a STATEFUL bump the data restore is NOT auto-applied (auto-restoring prod
#     data is itself high-risk) — the operator is paged with the RESTORE_CMD to confirm. Automate the
#     reversible part; escalate the irreversible-data part.
#
# Fail-safe: revert/page only run for real when NOT --dry-run. Test hooks: RENOVATE_HEALTH_STUB=healthy|
# unhealthy, RENOVATE_POSTMERGE_DRY=1, GATEWAY_DB=$(mktemp).
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/../.env" ] && source "$SCRIPT_DIR/../.env"
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.net}"
GATEWAY_DB="${GATEWAY_DB:-/home/app-user/gateway-state/gateway.db}"
SSH_KEY="${RENOVATE_SSH_KEY:-$HOME/.ssh/one_key}"
WINDOW="${RENOVATE_HEALTH_WINDOW:-300}"; WAIT="${RENOVATE_DEPLOY_WAIT:-45}"

HOST=""; SVC=""; PROJECT=""; IID=""; RESTORE=""; MERGE_SHA=""; SNAPREQ="false"; DRY="${RENOVATE_POSTMERGE_DRY:-0}"
while [ $# -gt 0 ]; do case "$1" in
  --host) HOST="$2"; shift 2;; --service) SVC="$2"; shift 2;;
  --project) PROJECT="$2"; shift 2;; --iid) IID="$2"; shift 2;;
  --restore) RESTORE="$2"; shift 2;; --merge-sha) MERGE_SHA="$2"; shift 2;;
  --snapshot-required) SNAPREQ="$2"; shift 2;; --dry-run) DRY=1; shift;; *) shift;; esac; done
log(){ echo "[postmerge] $*" >&2; }
api(){ curl -sk --max-time 30 -H "PRIVATE-TOKEN: ${GITLAB_TOKEN:-}" "$@"; }

record(){ # decision reason  — append through the tamper-evident hash chain
  jq -nc --arg pid "$PROJECT" --arg iid "$IID" --arg pu "$SVC" --arg dec "$1" --arg rsn "$2" \
     '{project_id:$pid,mr_iid:$iid,package_update:$pu,decision:$dec,reason:$rsn,mode:"live",schema_version:1}' 2>/dev/null \
   | python3 "$SCRIPT_DIR/lib/renovate_audit.py" append --db "$GATEWAY_DB" >/dev/null 2>&1 || true
}

# ── 1. wait for the redeploy, then poll health ────────────────────────────────
[ "$DRY" -eq 1 ] || sleep "$WAIT"
healthy=0; ever_found=0
if [ -n "${RENOVATE_HEALTH_STUB:-}" ]; then
  case "$RENOVATE_HEALTH_STUB" in
    healthy)  ever_found=1; healthy=1;;   # container found + healthy → OK
    notfound) ever_found=0;;              # container NEVER located → inconclusive (escalate, no revert)
    *)        ever_found=1;;              # unhealthy → container found but sick → revert
  esac
else
  deadline=$(( $(date +%s) + WINDOW ))
  GSSH="ssh -i $SSH_KEY -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=accept-new root@$HOST"
  while [ "$(date +%s)" -lt "$deadline" ]; do
    # resolve the container by IMAGE (same surface the snapshot uses — NOT the container name, which need
    # not contain the engine token), then read its real state+health via docker inspect.
    cid=$($GSSH "docker ps --format '{{.ID}} {{.Image}}' | grep -Ei '$SVC' | head -1 | cut -d' ' -f1" 2>/dev/null)
    [ -z "$cid" ] && { sleep 15; continue; }   # not up yet (container not located this poll)
    ever_found=1                               # a matching container EXISTS → the health verdict is meaningful
    st=$($GSSH "docker inspect -f '{{.State.Status}}:{{if .State.Health}}{{.State.Health.Status}}{{end}}' $cid" 2>/dev/null)
    case "$st" in
      running:healthy|running:)  healthy=1; break;;    # up + healthy, or up with no healthcheck defined
      running:starting)          sleep 15; continue;;  # still warming up
      *)                         sleep 15; continue;;  # unhealthy/restarting/exited → retry until deadline
    esac
  done
fi

if [ "$healthy" -eq 1 ]; then
  log "service '$SVC' on $HOST healthy post-merge → OK"
  record "POSTMERGE_OK" "healthy"
  echo "POSTMERGE_RESULT:{\"result\":\"ok\",\"host\":\"$HOST\",\"service\":\"$SVC\"}"
  exit 0
fi

# ── 1b. INCONCLUSIVE → no container was ever located → ESCALATE, never revert ─────
# The container never appeared in the whole window: wrong host/service mapping, an unreachable remote host
# (e.g. a DMZ VPS), an `images/<x>` CI base-image bump with no running service, or a Dockerfile build-tool
# bump whose service didn't recreate. We CANNOT conclude the deploy is bad — and auto-reverting a possibly-
# fine deploy is itself an incident. So page the operator for a manual look; do NOT revert. (Closes the
# "broadening host-detection risks spurious auto-reverts" concern: not-found ⇒ escalate, only found-unhealthy ⇒ revert.)
if [ "${ever_found:-0}" -eq 0 ]; then
  log "service '$SVC' on $HOST NEVER located in ${WINDOW}s → INCONCLUSIVE (no container to health-check; NOT reverting)"
  [ "$DRY" -ne 1 ] && python3 "$SCRIPT_DIR/renovate-escalate.py" --project "$PROJECT" --iid "$IID" --tier "postmerge-inconclusive" \
        --package "$SVC" --sha "${MERGE_SHA:0:8}" --reason "postmerge could not locate a container for service '$SVC' on $HOST — deploy NOT reverted, please verify manually" >/dev/null 2>&1 || true
  record "POSTMERGE_INCONCLUSIVE" "no-container-found host=$HOST svc=$SVC"
  echo "POSTMERGE_RESULT:{\"result\":\"inconclusive\",\"host\":\"$HOST\",\"service\":\"$SVC\"}"
  exit 0
fi

# ── 2. UNHEALTHY (container found but not healthy) → auto-revert the deploy + page ──
log "service '$SVC' on $HOST UNHEALTHY post-merge → rolling back"
if [ "$SNAPREQ" = "true" ]; then
  # STATEFUL: the new image already forward-migrated the data on first boot, so auto-reverting ONLY the
  # image (old binary ↔ new-schema data) can be MORE broken than the failed bump. Hold the whole rollback
  # (image revert + data restore, done together) for the operator — page with the RESTORE_CMD.
  REVERTED="held-for-operator(stateful: revert image + restore data together)"
  reason="postmerge-unhealthy (STATEFUL); manual rollback needed — image revert + DATA restore: ${RESTORE:-n/a}"
elif [ "$DRY" -eq 1 ]; then
  REVERTED="would-revert(dry-run)"; reason="postmerge-unhealthy; would revert deploy"
else
  # STATELESS: reverting the tag fully reverts the change → auto-revert the deploy.
  [ -z "$MERGE_SHA" ] && MERGE_SHA=$(api "$GITLAB_URL/api/v4/projects/$PROJECT/merge_requests/$IID" | jq -r '.merge_commit_sha // .squash_commit_sha // ""')
  if [ -n "$MERGE_SHA" ] && api -X POST "$GITLAB_URL/api/v4/projects/$PROJECT/repository/commits/$MERGE_SHA/revert" \
        --data-urlencode "branch=main" | jq -e '.id' >/dev/null 2>&1; then
    REVERTED="reverted:$MERGE_SHA"   # CI now redeploys the OLD image
  else
    REVERTED="revert-failed"         # conflict/permission → operator must revert
  fi
  reason="postmerge-unhealthy; deploy $REVERTED"
fi
[ "$DRY" -ne 1 ] && python3 "$SCRIPT_DIR/renovate-escalate.py" --project "$PROJECT" --iid "$IID" --tier "rollback" \
        --package "$SVC" --sha "${MERGE_SHA:0:8}" --reason "$reason" >/dev/null 2>&1 || true
record "POSTMERGE_ROLLBACK" "unhealthy; $REVERTED"
echo "POSTMERGE_RESULT:{\"result\":\"rollback\",\"host\":\"$HOST\",\"service\":\"$SVC\",\"revert\":\"$REVERTED\"}"
exit 1
