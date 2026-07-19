#!/bin/bash
# renovate-mr-gate.sh — Phase 2 brain of the Renovate MR Autonomy lane (IFRNLLEI01PRD-1645).
#
# The thin n8n workflow ("NL - Renovate MR Autonomy") SSH-calls this with the GitLab
# merge_request webhook body. Keeping the logic here (not in n8n Code nodes) is deliberate:
# it is offline-testable and dodges the n8n-code-node outage class.
#
# Pipeline:  parse+filter → classify → CI gate → review gate → [snapshot gate] → decide → act → audit
#
# SHADOW by default (analysis-only, merges NOTHING). LIVE actions (merge / snapshot / SMS+poll)
# fire ONLY when ~/gateway.renovate_autonomy exists AND --dry-run is not set. Fail-safe: any
# error or missing signal degrades to POLL/shadow, never to an unreviewed merge.
#
# Usage:
#   renovate-mr-gate.sh --event-json <file|->        # GitLab merge_request webhook body (n8n)
#   renovate-mr-gate.sh --project <id> --iid <n>     # manual / replay
#   flags: --dry-run (force shadow, for tests)
# Test hooks (never set in production):
#   RENOVATE_MR_STUB='<gitlab MR object json>'  # skip the API fetch (hermetic tests)
#   RENOVATE_REVIEW_STUB='{"verdict":"APPROVE","confidence":0.93}'  # skip real mr-review.sh (claude)
#   RENOVATE_CI_STUB=success|failed|running|none                    # skip real pipeline query
#   RENOVATE_SNAPSHOT_STUB=ok|fail                                  # skip Phase-3 snapshot (unbuilt)
#   GATEWAY_DB=$(mktemp)                                            # isolate audit writes
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# `set -a` so .env vars are EXPORTED to child processes (escalate.py / rollout.py / audit.py / presnapshot).
# .env bare-assigns (no `export`); without this, sourced vars are shell-local and every subprocess that
# reads os.environ (e.g. renovate-escalate.py's GITLAB_TOKEN/MATRIX_* → MR comment + Matrix) silently no-ops.
[ -f "$REPO_DIR/.env" ] && { set -a; source "$REPO_DIR/.env"; set +a; }
GITLAB_URL="${GITLAB_URL:-https://gitlab.example.net}"
GATEWAY_DB="${GATEWAY_DB:-/home/app-user/gateway-state/gateway.db}"
SENTINEL="$HOME/gateway.renovate_autonomy"
RENOVATE_BOT_USER="${RENOVATE_BOT_USER:-renovate-bot}"   # overridable only for controlled e2e tests
AUDIT_SCHEMA_VERSION=1   # registry: scripts/lib/schema_version.py CURRENT_SCHEMA_VERSION['renovate_autonomy_audit']

log(){ echo "[renovate-gate] $*" >&2; }
emit(){ echo "RENOVATE_GATE_RESULT:$1"; }
api(){ curl -sk --max-time 30 -H "PRIVATE-TOKEN: ${GITLAB_TOKEN:-}" "$@"; }

# audit(decision, reason, tier, snap_required, ci_status, verdict, confidence, package:update, gates_json)
audit(){
  # append THROUGH the tamper-evident hash chain (scripts/lib/renovate_audit.py) so the ledger can't be
  # silently edited. Fields: decision reason tier snap_required ci_status verdict confidence pkg:update gates_json
  # NB: do NOT write `${9:-{}}` — bash parses that as `${9:-{}` + a literal `}`, so an empty $9 yields `{}}`
  # and a real gates payload yields `…}}` = INVALID JSON. That silently poisons every AUTO/POLL row's
  # gates_json and makes the `merged_without_snapshot` safety invariant's json_extract throw (→ swallowed →
  # metric stuck at 0) the moment the lane auto-merges a snapshot-required tier. Default via a var instead.
  local gates_arg="${9:-}"; [ -n "$gates_arg" ] || gates_arg='{}'
  jq -nc --arg pid "$PROJECT_ID" --arg iid "$MR_IID" --arg title "${TITLE:-}" --arg pu "${8:-}" \
     --arg tier "${3:-}" --arg snap "${4:-}" --arg ci "${5:-}" --arg vd "${6:-}" --arg cf "${7:-}" \
     --arg dec "$1" --arg rsn "${2:-}" --arg mode "$MODE" --arg gates "$gates_arg" \
     '{project_id:$pid,mr_iid:$iid,mr_title:$title,package_update:$pu,tier:$tier,snapshot_required:$snap,
       ci_status:$ci,review_verdict:$vd,review_confidence:(try($cf|tonumber)catch 0),decision:$dec,
       reason:$rsn,mode:$mode,gates_json:$gates,schema_version:1}' 2>/dev/null \
   | python3 "$SCRIPT_DIR/lib/renovate_audit.py" append --db "$GATEWAY_DB" >/dev/null 2>&1 \
   || log "AUDIT WRITE FAILED (project=$PROJECT_ID iid=$MR_IID decision=$1) — ledger + daily-cap may undercount"
}

# ── args ──────────────────────────────────────────────────────────────────────
EVENT_JSON=""; PROJECT_ID=""; MR_IID=""; FORCE_SHADOW=0
while [ $# -gt 0 ]; do case "$1" in
  --event-json) EVENT_JSON="$2"; shift 2;;
  --project)    PROJECT_ID="$2"; shift 2;;
  --iid)        MR_IID="$2"; shift 2;;
  --dry-run)    FORCE_SHADOW=1; shift;;
  *) log "unknown arg: $1"; shift;;
esac; done

MODE="shadow"
# live iff the global sentinel is set (production arming) OR RENOVATE_FORCE_LIVE=1 (controlled e2e only —
# the webhook path never sets it, so a forced-live test cannot make the production lane live).
{ [ -f "$SENTINEL" ] || [ "${RENOVATE_FORCE_LIVE:-0}" = "1" ]; } && [ "$FORCE_SHADOW" -eq 0 ] && MODE="live"

# ── resolve project_id + iid from a webhook event (if given) ───────────────────
if [ -n "$EVENT_JSON" ]; then
  RAW=$([ "$EVENT_JSON" = "-" ] && cat || cat "$EVENT_JSON")
  EVT=$(echo "$RAW" | jq -c 'if .body then .body else . end' 2>/dev/null)
  [ -z "$EVT" ] && { emit '{"decision":"SKIP","reason":"bad-event-json"}'; exit 0; }
  [ "$(echo "$EVT" | jq -r '.object_kind // .event_type // ""')" != "merge_request" ] && {
    emit '{"decision":"SKIP","reason":"not-mr-event"}'; exit 0; }
  PROJECT_ID=$(echo "$EVT" | jq -r '.project.id // .object_attributes.target_project_id // empty')
  MR_IID=$(echo "$EVT" | jq -r '.object_attributes.iid // empty')
  ACTION=$(echo "$EVT" | jq -r '.object_attributes.action // ""')
  case "$ACTION" in open|reopen|update) : ;; *)
    emit "{\"decision\":\"SKIP\",\"reason\":\"action-$ACTION\"}"; exit 0;; esac
fi
{ [ -z "${PROJECT_ID:-}" ] || [ -z "${MR_IID:-}" ]; } && { emit '{"decision":"SKIP","reason":"no-project-iid"}'; exit 0; }

# ── canonical MR object (from stub, or the API) ────────────────────────────────
# Fetch the /changes variant: it returns the full MR object PLUS the diff (changes[]), which the
# classifier needs for affected-host + manager + never_auto-by-path detection.
if [ -n "${RENOVATE_MR_STUB:-}" ]; then MR="$RENOVATE_MR_STUB"; else
  MR=$(api "$GITLAB_URL/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/changes"); fi
{ [ -z "$MR" ] || [ "$(echo "$MR" | jq -r '.iid // "null"' 2>/dev/null)" = "null" ]; } && {
  emit '{"decision":"SKIP","reason":"mr-fetch-failed"}'; exit 0; }
AUTHOR=$(echo "$MR" | jq -r '.author.username // ""')
STATE=$(echo "$MR" | jq -r '.state // ""')
TARGET=$(echo "$MR" | jq -r '.target_branch // ""')
TITLE=$(echo "$MR" | jq -r '.title // ""')
HEAD_SHA=$(echo "$MR" | jq -r '.sha // ""')

# ── filter: only opened Renovate MRs targeting main ────────────────────────────
skip=""
[ "$AUTHOR" != "$RENOVATE_BOT_USER" ] && skip="author-$AUTHOR"
[ -z "$skip" ] && [ "$STATE" != "opened" ] && skip="state-$STATE"
[ -z "$skip" ] && [ "$TARGET" != "main" ] && skip="target-$TARGET"
if [ -n "$skip" ]; then
  log "filtered: $skip"; audit "SKIP" "$skip" "" "" "" "" "" "" ""
  emit "{\"decision\":\"SKIP\",\"reason\":\"$skip\",\"mr\":\"$PROJECT_ID!$MR_IID\"}"; exit 0; fi

# ── classify (dependency-aware reversibility) ──────────────────────────────────
# Feed the already-fetched MR object (incl. changes[]) straight to the classifier. Do NOT re-fetch via
# --project/--iid: that spawns a python subprocess needing GITLAB_TOKEN in ITS OWN env, but .env
# bare-assigns the token (no `export`) so the subprocess got none → sys.exit → empty $CLS → the fail-safe
# below fired on EVERY production run (every MR forced to critical/unknown/never_auto=false; the canary
# could never see a routine bump → never auto-merge). Feeding $MR removes that subprocess-env dependency.
CLS=$(echo "$MR" | python3 "$SCRIPT_DIR/classify-renovate-mr.py" --mr-json - 2>/dev/null)
[ -z "$CLS" ] && { log "classifier failed → fail-safe critical"; \
  CLS='{"tier":"critical","snapshot_required":true,"confidence_threshold":0.9,"package":"classifier-error","update_type":"unknown","never_auto":true}'; }
TIER=$(echo "$CLS" | jq -r '.tier'); SNAP_REQ=$(echo "$CLS" | jq -r '.snapshot_required')
CONF_TH=$(echo "$CLS" | jq -r '.confidence_threshold'); PKG=$(echo "$CLS" | jq -r '.package'); UPD=$(echo "$CLS" | jq -r '.update_type')
log "classified $PKG ($UPD) → tier=$TIER snapshot_required=$SNAP_REQ τ=$CONF_TH"

# ── gate 1: CI pipeline green ──────────────────────────────────────────────────
if [ -n "${RENOVATE_CI_STUB:-}" ]; then CI_STATUS="$RENOVATE_CI_STUB"; else
  CI_STATUS=$(api "$GITLAB_URL/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/pipelines" | jq -r '.[0].status // "none"'); fi
CI_OK=$([ "$CI_STATUS" = "success" ] && echo 1 || echo 0)

# ── idempotency: dedup rapid duplicate webhooks for the SAME head SHA ───────────
# A freshly-opened Renovate MR emits `open` + a near-simultaneous `update` (self-assign/label) event.
# Without dedup, both run the expensive review + escalation and write two audit rows for ONE MR (observed
# live on !359: execs 543003/543004, two review comments). Dedup on (project,iid,sha) via an atomic mkdir
# marker — no schema/chain change. A NEW sha (rebase) makes a new key and re-runs; a CI→success transition
# is allowed exactly one extra run. Bypass with RENOVATE_DEDUP_OFF=1 (tests set this).
if [ -z "${RENOVATE_DEDUP_OFF:-}" ] && [ -n "$HEAD_SHA" ]; then
  DEDUP_BASE="${RENOVATE_DEDUP_BASE:-$HOME/gateway-state/renovate-dedup}"; KEYDIR="$DEDUP_BASE/${PROJECT_ID}-${MR_IID}-${HEAD_SHA}"
  mkdir -p "$DEDUP_BASE" 2>/dev/null
  find "$DEDUP_BASE" -maxdepth 1 -type d -mmin +1440 -exec rm -rf {} + 2>/dev/null
  if [ "$CI_STATUS" = "success" ]; then
    mkdir -p "$KEYDIR" 2>/dev/null
    if ! mkdir "$KEYDIR/success" 2>/dev/null; then
      log "dedup: sha=$HEAD_SHA already decided at ci=success — skip"
      emit "{\"decision\":\"SKIP\",\"reason\":\"dup-sha-success\",\"mr\":\"$PROJECT_ID!$MR_IID\"}"; exit 0; fi
  else
    if ! mkdir "$KEYDIR" 2>/dev/null; then
      log "dedup: sha=$HEAD_SHA already handled (ci=$CI_STATUS) — skip"
      emit "{\"decision\":\"SKIP\",\"reason\":\"dup-sha\",\"mr\":\"$PROJECT_ID!$MR_IID\"}"; exit 0; fi
  fi
fi

# ── gate 2: review verdict at the tier's confidence threshold ──────────────────
# Routine version bumps get a FAST DETERMINISTIC structural review (pure version/tag/digest edit in
# manifest files only) — the full Claude review (mr-review.sh) was slow + flaky in the n8n SSH context
# (verdict came back EMPTY → nothing ever auto-merged). Claude review is reserved for elevated/critical
# (subjective risk). A routine MR that is NOT a pure version bump → structural REQUEST_CHANGES → POLL.
if [ -n "${RENOVATE_REVIEW_STUB:-}" ]; then RJ="$RENOVATE_REVIEW_STUB"
elif [ "$TIER" = "routine" ]; then
  RJ=$(python3 "$SCRIPT_DIR/renovate-structural-review.py" --project "$PROJECT_ID" --iid "$MR_IID" 2>/dev/null | grep -oE 'REVIEW_JSON:.*' | sed 's/^REVIEW_JSON://' | head -1)
else
  RJ=$("$SCRIPT_DIR/mr-review.sh" "$PROJECT_ID" "$MR_IID" 2>/dev/null | grep -oE 'REVIEW_JSON:.*' | sed 's/^REVIEW_JSON://' | head -1); fi
VERDICT=$(echo "$RJ" | jq -r '.verdict // "UNKNOWN"' 2>/dev/null || echo UNKNOWN)
CONFID=$(echo "$RJ" | jq -r '.confidence // 0' 2>/dev/null || echo 0)
REVIEW_OK=$(awk -v v="$VERDICT" -v c="$CONFID" -v t="$CONF_TH" 'BEGIN{print (v=="APPROVE" && c+0>=t+0)?1:0}')

# ── affected host/service (from the diff) — used by the snapshot AND post-merge health check ──
AFF_HOST=$(echo "$CLS" | jq -r '.affected_host // ""')
# Service to snapshot/health-check: a stateful match first, then the PATH-derived service dir
# (docker/<host>/<SVC>/…), then the package. The path-derived service is what names the RUNNING container
# — a Dockerfile build-tool bump (package=uv) must health-check the <SVC> container (librechat), not `uv`.
SNAP_SVC=$(echo "$CLS" | jq -r '(.stateful_match[0] // .affected_service // .package) // ""')
NEVER_AUTO=$(echo "$CLS" | jq -r '.never_auto // false')

# ── timeout-to-auto eligibility + operator veto (2026-07-07) ────────────────────
# The operator is not reachable via Matrix/SMS, so a POLL on a REVERSIBLE stateful/elevated bump must not
# stall forever. If BOTH sentinels are armed and the bump is eligible (lib/renovate_deferred.py: NOT
# never_auto ∧ tier critical/elevated ∧ reversible update_type), a POLL is HELD for a grace window and
# auto-merged later via THIS same path. A VETO — the hold label on the MR, or closing it — always wins.
TIMEOUT_SENTINEL="${RENOVATE_TIMEOUT_SENTINEL:-$HOME/gateway.renovate_timeout_auto}"
ROLLOUT_CFG="${RENOVATE_ROLLOUT_CONFIG:-$REPO_DIR/config/renovate-autonomy-rollout.json}"
VETO_LABEL=$(jq -r '.timeout_auto.veto_label // "renovate-hold"' "$ROLLOUT_CFG" 2>/dev/null); VETO_LABEL="${VETO_LABEL:-renovate-hold}"
GRACE_HOURS=$(jq -r '.timeout_auto.grace_hours // 48' "$ROLLOUT_CFG" 2>/dev/null); GRACE_HOURS="${GRACE_HOURS:-48}"
TIMEOUT_ELIGIBLE=0
if [ -f "$TIMEOUT_SENTINEL" ] && { [ -f "$SENTINEL" ] || [ "${RENOVATE_FORCE_LIVE:-0}" = "1" ]; } && \
   [ "$(python3 "$SCRIPT_DIR/lib/renovate_deferred.py" eligible --tier "$TIER" --update-type "$UPD" --never-auto "$NEVER_AUTO" 2>/dev/null)" = "1" ]; then
  TIMEOUT_ELIGIBLE=1; fi
VETOED=0
echo "$MR" | jq -e --arg L "$VETO_LABEL" '((.labels // []) | map(if type=="object" then .name else . end) | index($L)) != null' >/dev/null 2>&1 && VETOED=1

# ── gate 3: verified snapshot (only when the tier requires it) ─────────────────
SNAP_STATUS="n/a"; SNAP_OK=1; RESTORE_PT=""
if [ "$SNAP_REQ" = "true" ]; then
  if [ -n "${RENOVATE_SNAPSHOT_STUB:-}" ]; then
    SNAP_STATUS="$RENOVATE_SNAPSHOT_STUB"; SNAP_OK=$([ "$RENOVATE_SNAPSHOT_STUB" = "ok" ] && echo 1 || echo 0)
  elif [ -z "$AFF_HOST" ] || [ -z "$SNAP_SVC" ]; then
    SNAP_STATUS="no-host-or-engine"; SNAP_OK=0
  else
    # Shadow runs --dry-run (recipe feasibility only, no side effects); live takes + verifies the real dump.
    PS_FLAGS=""; [ "$MODE" != "live" ] && PS_FLAGS="--dry-run"
    if PS_OUT=$("$SCRIPT_DIR/renovate-presnapshot.sh" --host "$AFF_HOST" --service "$SNAP_SVC" $PS_FLAGS 2>/dev/null); then
      SNAP_OK=1; RESTORE_PT=$(echo "$PS_OUT" | grep -oE 'RESTORE_POINT:[^ ]*' | head -1); SNAP_STATUS="${RESTORE_PT:-ok}"
    else SNAP_OK=0; SNAP_STATUS="snapshot-failed-or-declined"; fi
  fi
fi
log "gates: ci=$CI_STATUS/$CI_OK review=$VERDICT@$CONFID/$REVIEW_OK snapshot=$SNAP_STATUS/$SNAP_OK never_auto=$NEVER_AUTO"

# ── decision (fail closed; a never_auto engine always POLLs) ───────────────────
DECISION="POLL"
{ [ "$CI_OK" -eq 1 ] && [ "$REVIEW_OK" -eq 1 ] && [ "$SNAP_OK" -eq 1 ] && [ "$NEVER_AUTO" != "true" ]; } && DECISION="AUTO"
[ "$VETOED" = "1" ] && DECISION="POLL"   # an operator hold label overrides everything — never auto-merge
GATES_JSON=$(jq -nc --argjson ci "$CI_OK" --argjson rv "$REVIEW_OK" --argjson sn "$SNAP_OK" \
  --arg cis "$CI_STATUS" --arg vd "$VERDICT" --arg cf "$CONFID" --arg ss "$SNAP_STATUS" \
  --argjson na "$([ "$NEVER_AUTO" = "true" ] && echo true || echo false)" \
  '{ci_green:($ci==1),ci_status:$cis,review_approve:($rv==1),verdict:$vd,confidence:(try ($cf|tonumber) catch 0),snapshot_verified:($sn==1),snapshot_status:$ss,never_auto:$na}')
log "DECISION=$DECISION (mode=$MODE)"

# ── act (shadow suppresses everything; live merges / holds / polls) ────────────
ACTED="shadow-logged"; REASON=""
if [ "$MODE" = "live" ]; then
  # Dim-5 staged rollout: is this tier enabled at the current stage, and under the daily cap? Arming the
  # sentinel starts a CANARY (routine only, few/day), NOT all-tiers-at-once. Promotion is data-driven.
  if [ "$DECISION" = "AUTO" ]; then
    RO=$(python3 "$SCRIPT_DIR/renovate-rollout.py" --tier "$TIER" --db "$GATEWAY_DB" 2>/dev/null); RO=${RO:-"POLL:rollout-error"}
    if [ "$RO" != "ALLOW" ]; then
      # timeout-to-auto: the rollout stage POLLs this tier (canary), but if the grace window has ELAPSED and
      # this is a reversible, non-vetoed, eligible bump, override the stage POLL → proceed to AUTO. The
      # tested snapshot + post-merge auto-rollback is the safety net, not a human vote. The processor only
      # sets RENOVATE_DEFERRED_ELAPSED=1 after the window + a daily-cap check; EVERY other safety gate
      # (independent floor / snapshot verify / sha-pin / auto-rollback) still runs below, unchanged.
      if [ "${RENOVATE_DEFERRED_ELAPSED:-0}" = "1" ] && [ "$TIMEOUT_ELIGIBLE" = "1" ] && [ "$VETOED" = "0" ]; then
        REASON="timeout-auto-override"; log "timeout-auto: grace elapsed → stage POLL overridden → AUTO"
      else
        DECISION="POLL"; REASON="$RO"
      fi
    fi
  fi

  if [ "$DECISION" = "AUTO" ]; then
    # TOCTOU: did Renovate push a new commit since we classified/reviewed? (Dim 2/3)
    if [ -n "${RENOVATE_MERGE_STUB:-}" ]; then LIVE_SHA="$HEAD_SHA"; else   # test hook: skip the live re-fetch
      LIVE_SHA=$(api "$GITLAB_URL/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID" | jq -r '.sha // ""'); fi
    HC=$([ -n "$LIVE_SHA" ] && [ "$LIVE_SHA" != "$HEAD_SHA" ] && echo true || echo false)
    # INDEPENDENT floor re-check — policy (scripts/lib/renovate_floor.py) separate from the decision
    # path above, so a bug in the decider cannot merge out of policy. (Dim 2)
    FLOOR=$(jq -nc --arg cis "$CI_STATUS" --arg vd "$VERDICT" --arg cf "$CONFID" --arg th "$CONF_TH" \
       --argjson sr "$([ "$SNAP_REQ" = "true" ] && echo true || echo false)" \
       --argjson sv "$([ "$SNAP_OK" -eq 1 ] && echo true || echo false)" \
       --argjson na "$([ "$NEVER_AUTO" = "true" ] && echo true || echo false)" --argjson hc "$HC" \
       '{ci_status:$cis,review_verdict:$vd,review_confidence:(try($cf|tonumber)catch 0),confidence_threshold:(try($th|tonumber)catch 1),snapshot_required:$sr,snapshot_verified:$sv,never_auto:$na,head_sha_changed:$hc}' \
       | python3 "$SCRIPT_DIR/lib/renovate_floor.py" 2>/dev/null)
    if [ "$FLOOR" = "ALLOW" ]; then
      # merge ONLY the exact reviewed SHA — GitLab rejects if the head moved (server-side TOCTOU close).
      if [ -n "${RENOVATE_MERGE_STUB:-}" ]; then   # test hook: never touch the real merge API
        MERGE_RESP=$([ "$RENOVATE_MERGE_STUB" = "merged" ] && echo '{"state":"merged","merge_commit_sha":"stub-merge-sha"}' || echo '{"state":"opened"}')
      else
        MERGE_RESP=$(api -X PUT "$GITLAB_URL/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/merge" \
           --data-urlencode "sha=$HEAD_SHA" \
           --data-urlencode "merge_commit_message=chore(deps): auto-merge ${PKG} ${UPD} [renovate-autonomy ${TIER}]"); fi
      if echo "$MERGE_RESP" | jq -e '.state=="merged"' >/dev/null 2>&1; then
        ACTED="merged"
        python3 "$SCRIPT_DIR/lib/renovate_deferred.py" mark --project "$PROJECT_ID" --iid "$MR_IID" --sha "$HEAD_SHA" --status merged --reason "${REASON:-auto}" --db "$GATEWAY_DB" >/dev/null 2>&1 || true
        MSHA=$(echo "$MERGE_RESP" | jq -r '.merge_commit_sha // ""')
        # async post-merge health check + auto-rollback (never blocks the webhook). (Dim 3)
        # Only when there IS a docker host to health-check (docker plane). A merge with no affected host
        # (non-docker-plane, e.g. a pure tf/helm change deployed via Atlantis) has nothing to poll here.
        if [ -n "$AFF_HOST" ]; then
          nohup "$SCRIPT_DIR/renovate-postmerge-verify.sh" --host "$AFF_HOST" --service "$SNAP_SVC" \
                --project "$PROJECT_ID" --iid "$MR_IID" --restore "$RESTORE_PT" --merge-sha "$MSHA" \
                --snapshot-required "$SNAP_REQ" >/dev/null 2>&1 &
        fi
      else DECISION="POLL"; REASON="merge-rejected-or-sha-moved"; fi
    else DECISION="POLL"; REASON="floor-veto:$FLOOR"; log "INDEPENDENT FLOOR VETO: $FLOOR"; fi
  fi

  if [ "$DECISION" = "POLL" ]; then
    if [ "$VETOED" = "1" ]; then
      ACTED="held:vetoed"           # a deliberate operator veto (hold label) — do NOT page
      python3 "$SCRIPT_DIR/lib/renovate_deferred.py" mark --project "$PROJECT_ID" --iid "$MR_IID" --sha "$HEAD_SHA" --status vetoed --reason "label:$VETO_LABEL" --db "$GATEWAY_DB" >/dev/null 2>&1 || true
    elif echo "$REASON" | grep -q 'rate-cap'; then
      ACTED="held:$REASON"          # throttle-hold — re-evaluated next Renovate run; do NOT page
      # A rate-cap is "try again later", but the ci=success dedup marker would SKIP this SHA forever → the
      # held MR never auto-merges even after budget frees (exactly the stall the cap-pollution bug caused).
      # Un-mark so the next reconcile tick re-evaluates. Safe: rate-cap does no merge + no escalation, so a
      # re-run is cheap + idempotent; only the retryable throttle-hold un-marks (terminal POLLs stay marked).
      [ -n "${KEYDIR:-}" ] && rmdir "$KEYDIR/success" 2>/dev/null || true
    elif [ "$TIMEOUT_ELIGIBLE" = "1" ] && [ "${RENOVATE_DEFERRED_ELAPSED:-0}" != "1" ]; then
      # NORMAL run of a reversible eligible bump: SCHEDULE a timeout-auto instead of paging into a channel
      # the operator doesn't watch. The webhook dedup guarantees one gate run per commit → records once +
      # posts ONE passive MR comment (no SMS). renovate-deferred-merge-processor.py drives the actual
      # auto-merge once the grace window elapses.
      DL=$(python3 "$SCRIPT_DIR/lib/renovate_deferred.py" record --project "$PROJECT_ID" --iid "$MR_IID" --sha "$HEAD_SHA" --tier "$TIER" --update-type "$UPD" --package "$PKG" --grace-hours "$GRACE_HOURS" --db "$GATEWAY_DB" 2>/dev/null)
      ACTED="deferred:${DL:-scheduled}"
      [ -z "${RENOVATE_MR_STUB:-}" ] && api -X POST "$GITLAB_URL/api/v4/projects/$PROJECT_ID/merge_requests/$MR_IID/notes" \
        --data-urlencode "body=🕒 **Renovate autonomy — timeout-to-auto scheduled.** This reversible \`$TIER\` bump (\`$PKG\` $UPD) will **auto-merge after the grace window (~${GRACE_HOURS}h)** unless vetoed — through the same tested-snapshot + independent-floor + post-merge-auto-rollback path. **To veto:** add the \`$VETO_LABEL\` label to this MR, or close it." >/dev/null 2>&1 || true
    elif [ "${RENOVATE_DEFERRED_ELAPSED:-0}" = "1" ]; then
      ACTED="deferred-retry:${REASON:-poll}"   # elapsed attempt didn't merge (CI/floor moved) — processor retries; no page
    else
      # ineligible (never_auto / MAJOR / no-snapshot) → escalate (MR comment + SMS + Matrix). (Dim 4)
      [ -z "${RENOVATE_MR_STUB:-}" ] && python3 "$SCRIPT_DIR/renovate-escalate.py" --project "$PROJECT_ID" --iid "$MR_IID" \
         --tier "$TIER" --package "$PKG" --sha "$HEAD_SHA" --reason "${REASON:-poll}" >/dev/null 2>&1 || true
      ACTED="polled:${REASON:-poll}"
    fi
  fi
fi

# ── audit + emit ───────────────────────────────────────────────────────────────
audit "$DECISION" "${REASON:-}" "$TIER" "$SNAP_REQ" "$CI_STATUS" "$VERDICT" "$CONFID" "$PKG:$UPD" "$GATES_JSON"
emit "$(jq -nc --arg d "$DECISION" --arg m "$MODE" --arg mr "$PROJECT_ID!$MR_IID" --arg t "$TIER" \
  --arg p "$PKG" --arg u "$UPD" --arg a "$ACTED" --argjson g "$GATES_JSON" \
  '{decision:$d,mode:$m,mr:$mr,tier:$t,package:$p,update_type:$u,acted:$a,gates:$g}')"
