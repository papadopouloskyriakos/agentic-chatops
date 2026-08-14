# Shared Tier 1 suppression flow — sourced by infra-triage.sh and k8s-triage.sh.
#
# Provides: run_tier1_suppression <hostname> <rule_name> <severity>
#
# On a suppression hit (Phase 1 dedup / Phase 2 knownpattern / Phase 3 active-memory):
#   - Posts a counter-bump comment on the target YT issue (if any)
#   - Acknowledges LibreNMS for the hostname (if ack function is defined)
#   - Writes event_log + openclaw_memory rows via SSH to nl-claude01
#   - Appends a triage.log row with the suppression outcome
#   - Emits a TRIAGE_JSON marker for n8n / observability
#   - calls `exit 0` to end the calling script
#
# On a no-match (outcome=escalate), returns 0 silently. The caller continues
# with the standard escalation flow.
#
# Required env (read from caller's scope):
#   ISSUE_ID           — current YT issue (may be empty if Step 0 didn't find one)
#   YOUTRACK_URL       — for the YT-open check inside the library
#   YOUTRACK_TOKEN     — same
#   TRIAGE_SITE        — nl|gr — used in the triage.log row
#   TRIAGE_START       — unix epoch when triage began — used to compute duration
#   FORCE_ESCALATE     — "true" forces escalate; library short-circuits in that case
#
# Optional env:
#   TIER1_SUPPRESSION_LIB — path to tier1_suppression.py (defaults to the cc-cc repo path)
#   TIER1_TRIAGE_LOG      — path to triage.log (defaults to the cc-cc production path)
#   TIER1_SUPPR_TEST_MODE — when set to "1", skips the SSH-back to claude01 and writes
#                           audit rows to TIER1_SUPPR_TEST_DB (a local SQLite file)
#                           and posts YT comments to TIER1_SUPPR_TEST_YT_LOG instead.
#                           Lets the E2E test exercise the same code path without
#                           touching production state.

run_tier1_suppression() {
  local hostname="$1"
  local rule_name="$2"
  local severity="$3"

  local suppr_lib="${TIER1_SUPPRESSION_LIB:-/app/claude-gateway/scripts/lib/tier1_suppression.py}"
  local triage_log_path="${TIER1_TRIAGE_LOG:-/app/cubeos/claude-context/triage.log}"
  local db_path="${TIER1_SUPPR_TEST_DB:-/app/cubeos/claude-context/gateway.db}"
  local test_mode="${TIER1_SUPPR_TEST_MODE:-0}"

  echo "--- Step 0.5: Tier 1 suppression check ---"

  local suppr_json='{"outcome":"escalate","phase":"none","reason":"not-run"}'
  if [ ! -f "$suppr_lib" ]; then
    echo "WARN: suppression library not found at $suppr_lib — skipping check"
  else
    local args=(
      --hostname "$hostname"
      --rule-name "$rule_name"
      --severity "$severity"
      --current-issue-id "${ISSUE_ID:-}"
      --yt-url "${YOUTRACK_URL:-}"
      --yt-token "${YOUTRACK_TOKEN:-}"
      --triage-log "$triage_log_path"
      --db "$db_path"
    )
    [ "${FORCE_ESCALATE:-}" = "true" ] && args+=(--force-escalate)
    suppr_json=$(timeout 10 python3 "$suppr_lib" "${args[@]}" 2>&1) \
      || suppr_json='{"outcome":"escalate","phase":"none","reason":"suppression CLI failed/timed out"}'
  fi

  local outcome phase reason parent comment_text
  outcome=$(echo "$suppr_json" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["outcome"])' 2>/dev/null || echo "escalate")
  phase=$(echo "$suppr_json" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["phase"])' 2>/dev/null || echo "none")
  reason=$(echo "$suppr_json" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["reason"])' 2>/dev/null || echo "library failure")
  parent=$(echo "$suppr_json" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["existing_issue_id"])' 2>/dev/null || echo "")
  comment_text=$(echo "$suppr_json" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["comment_text"])' 2>/dev/null || echo "")

  echo "Suppression decision: outcome=$outcome phase=$phase"
  echo "Reason: $reason"

  if [ "$outcome" = "escalate" ]; then
    echo "Suppression check: no match — continuing to standard triage"
    return 0
  fi

  # ── Suppression path ──
  local target_issue="${parent:-${ISSUE_ID:-}}"

  # 1. Post comment to parent issue (best-effort)
  if [ -n "$target_issue" ] && [ -n "$comment_text" ]; then
    echo "Posting suppression comment to $target_issue"
    if [ "$test_mode" = "1" ]; then
      printf 'YT_COMMENT|%s|%s\n' "$target_issue" "$comment_text" >> "${TIER1_SUPPR_TEST_YT_LOG:-/dev/null}"
    else
      ./skills/yt-post-comment.sh "$target_issue" "$comment_text" 2>&1 \
        || echo "WARN: yt-post-comment failed (continuing)"
    fi
  fi

  # 2. Acknowledge LibreNMS so the dashboard clears (only if caller defined the fn)
  if [ "$test_mode" != "1" ] && declare -f acknowledge_librenms_alert >/dev/null 2>&1; then
    acknowledge_librenms_alert "$hostname" "$target_issue"
  fi

  # 3. Persist event_log + active memory.
  #
  # The library's suppr_json contains JSON quotes (`"`) which would break any
  # bash- or SSH-double-quoted SQL string. Solution: pass every value via env
  # vars to a Python subprocess that uses parameterized SQL (?), so no shell
  # escape juggling is needed.
  #
  # Direct local write when the DB is locally accessible (the cc-cc case);
  # fall back to SSH for the dormant OpenClaw-container case.
  local memvalue="${outcome} via ${phase}: ${reason}"
  local prod_db="/app/cubeos/claude-context/gateway.db"
  local target_db="$prod_db"
  [ "$test_mode" = "1" ] && target_db="$TIER1_SUPPR_TEST_DB"

  if [ "$test_mode" = "1" ] || [ -w "$target_db" ]; then
    TARGET_DB="$target_db" \
    TARGET_ISSUE="$target_issue" \
    SUPPR_HOST="$hostname" \
    SUPPR_RULE="$rule_name" \
    SUPPR_JSON_PAYLOAD="$suppr_json" \
    SUPPR_MEMVALUE="$memvalue" \
    python3 - <<'PYEOF' 2>/tmp/tier1-suppr-dbwrite.err || echo "WARN: local DB write failed ($(cat /tmp/tier1-suppr-dbwrite.err 2>/dev/null))"
import os, sqlite3
db = sqlite3.connect(os.environ["TARGET_DB"], timeout=5.0)
try:
    db.execute(
        "INSERT INTO event_log (issue_id, agent_name, event_type, payload_json) VALUES (?, ?, ?, ?)",
        (os.environ["TARGET_ISSUE"], "tier1-suppression", "tier1_suppression", os.environ["SUPPR_JSON_PAYLOAD"]),
    )
    db.execute(
        "INSERT INTO openclaw_memory (category, key, value, issue_id) VALUES (?, ?, ?, ?)",
        ("triage", os.environ["SUPPR_HOST"] + ":" + os.environ["SUPPR_RULE"], os.environ["SUPPR_MEMVALUE"], os.environ["TARGET_ISSUE"]),
    )
    db.commit()
finally:
    db.close()
PYEOF
  else
    # OpenClaw-container fallback: SSH to claude01, pass payloads as base64
    # so we sidestep the multi-layer shell-quoting maze entirely.
    local sj_b64 mv_b64
    sj_b64=$(printf '%s' "$suppr_json" | base64 -w0)
    mv_b64=$(printf '%s' "$memvalue"   | base64 -w0)
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
      -i ~/.ssh/one_key app-user@nl-claude01 \
      "TARGET_DB='$prod_db' TARGET_ISSUE='$target_issue' SUPPR_HOST='$hostname' SUPPR_RULE='$rule_name' SUPPR_JSON_B64='$sj_b64' SUPPR_MEMVALUE_B64='$mv_b64' python3 -c 'import os,base64,sqlite3; sj=base64.b64decode(os.environ[\"SUPPR_JSON_B64\"]).decode(); mv=base64.b64decode(os.environ[\"SUPPR_MEMVALUE_B64\"]).decode(); db=sqlite3.connect(os.environ[\"TARGET_DB\"], timeout=5.0); db.execute(\"INSERT INTO event_log (issue_id, agent_name, event_type, payload_json) VALUES (?, ?, ?, ?)\", (os.environ[\"TARGET_ISSUE\"], \"tier1-suppression\", \"tier1_suppression\", sj)); db.execute(\"INSERT INTO openclaw_memory (category, key, value, issue_id) VALUES (?, ?, ?, ?)\", (\"triage\", os.environ[\"SUPPR_HOST\"]+\":\"+os.environ[\"SUPPR_RULE\"], mv, os.environ[\"TARGET_ISSUE\"])); db.commit(); db.close()'" 2>/dev/null \
      || echo "WARN: SSH DB write failed (continuing)"
  fi

  # 4. Triage log
  local triage_duration=$(($(date +%s) - ${TRIAGE_START:-$(date +%s)}))
  echo "$(date -u +%FT%TZ)|${hostname}|${rule_name}|${TRIAGE_SITE:-nl}|${outcome}|0.95|${triage_duration}|${target_issue}" >> "$triage_log_path" 2>/dev/null || true

  # 5. Structured JSON marker for n8n
  echo "TRIAGE_JSON:$(python3 -c "
import json
print(json.dumps({
  'issueId': '${target_issue}',
  'hostname': '${hostname}',
  'ruleName': '${rule_name}',
  'severity': '${severity}',
  'escalated': False,
  'suppressed': True,
  'suppressionPhase': '${phase}',
  'suppressionReason': '${reason}',
}))" 2>/dev/null || echo '{}')"

  echo ""
  echo "=== TRIAGE SUPPRESSED (${phase}) ==="
  echo "Target issue: ${target_issue}"

  # ── Two-phase verify-and-reopen (decision 1, 2026-06-29) ──
  # A phaseSR suppression means "on-schedule reboot, no investigation". The
  # irreducible residual is a reactive reboot (OOM/self-heal) that coincidentally
  # lands in-window. Within ~60s, re-check the host's actual boot reason: if it
  # was NOT a clean systemd-reboot, REOPEN (force investigation + page). Skipped
  # in test mode (QA exercises the matcher directly, not the SSH verify).
  if [[ "$phase" == phaseSR* ]] && [ "$test_mode" != "1" ]; then
    local verify_script="${TIER1_SCHED_REBOOT_VERIFY:-/app/claude-gateway/scripts/verify-scheduled-reboot-boot.sh}"
    local fire_utc
    fire_utc=$(echo "$suppr_json" | python3 -c 'import sys,json;print(json.loads(sys.stdin.read()).get("signals",{}).get("fire_utc",""))' 2>/dev/null || echo "")
    if [ -n "$fire_utc" ] && [ -n "$hostname" ] && [ -x "$verify_script" ]; then
      nohup "$verify_script" "$hostname" "$fire_utc" >/dev/null 2>&1 &
      echo "Two-phase verify launched: $verify_script $hostname fire=$fire_utc"
    fi
  fi

  exit 0
}
