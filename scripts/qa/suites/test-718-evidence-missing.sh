#!/usr/bin/env bash
# IFRNLLEI01PRD-718 — evidence_missing risk signal.
#
# Verifies that classify-session-risk.py emits the `evidence_missing`
# signal when a reply claims CONFIDENCE ≥ 0.8 but ships no code fence,
# and that the signal forces risk away from `low` (the only tier that
# allows auto-approval).
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"

export QA_SUITE_NAME="718-evidence-missing"
CLASSIFY="$REPO_ROOT/scripts/classify-session-risk.py"

_jq_field() {
  # Usage: _jq_field "<json>" "<field>"
  python3 -c "import json,sys; print(json.loads(sys.argv[1]).get(sys.argv[2], ''))" "$1" "$2"
}

# ─── T1 standalone --check-evidence: high confidence + no fence ─────────
start_test "check_evidence_high_conf_no_fence_flags"
  out=$(echo "CONFIDENCE: 0.9 — fix applied" | python3 "$CLASSIFY" --check-evidence 2>/dev/null)
  missing=$(_jq_field "$out" "evidence_missing")
  force=$(_jq_field "$out" "force_poll")
  if [ "$missing" = "True" ] && [ "$force" = "True" ]; then
    :
  else
    fail_test "expected evidence_missing=True force_poll=True, got: $out"
  fi
end_test

# ─── T2 standalone: high confidence + fence → not missing ────────────────
start_test "check_evidence_high_conf_with_fence_passes"
  out=$(printf 'CONFIDENCE: 0.9\n```\nsystemctl is-active foo\n```\n' | python3 "$CLASSIFY" --check-evidence 2>/dev/null)
  missing=$(_jq_field "$out" "evidence_missing")
  if [ "$missing" = "False" ]; then
    :
  else
    fail_test "expected evidence_missing=False with fence, got: $out"
  fi
end_test

# ─── T3 standalone: low confidence → never missing ──────────────────────
start_test "check_evidence_low_confidence_passes"
  out=$(echo "CONFIDENCE: 0.5 — need more info" | python3 "$CLASSIFY" --check-evidence 2>/dev/null)
  missing=$(_jq_field "$out" "evidence_missing")
  if [ "$missing" = "False" ]; then
    :
  else
    fail_test "expected evidence_missing=False at 0.5, got: $out"
  fi
end_test

# ─── T4 standalone: CONFIDENCE: 1.0 + no fence → missing ────────────────
start_test "check_evidence_confidence_one_no_fence_flags"
  out=$(echo "CONFIDENCE: 1.0 — done" | python3 "$CLASSIFY" --check-evidence 2>/dev/null)
  missing=$(_jq_field "$out" "evidence_missing")
  reason=$(_jq_field "$out" "reason")
  if [ "$missing" = "True" ] && [[ "$reason" == *"1.0"* ]]; then
    :
  else
    fail_test "expected CONFIDENCE:1.0 to flag, got: $out"
  fi
end_test

# ─── T5 plan-integration: availability + draft_reply with no fence → bump to mixed ──
start_test "plan_with_naked_high_conf_draft_bumps_to_mixed"
  PLAN_JSON='{
    "hypothesis": "Host is up, DNS flap",
    "steps": [{"description": "check DNS"}],
    "tools_needed": ["dig"],
    "draft_reply": "Everything is fine. CONFIDENCE: 0.9. Fix applied."
  }'
  out=$(echo "$PLAN_JSON" | ALERT_CATEGORY=availability ISSUE_ID=TEST-718-T5 \
         python3 "$CLASSIFY" --no-audit 2>/dev/null)
  risk=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['risk_level'])" "$out")
  signals=$(python3 -c "import json,sys; print(' '.join(json.loads(sys.argv[1])['signals']))" "$out")
  if [ "$risk" = "mixed" ] && [[ "$signals" == *"evidence_missing"* ]]; then
    :
  else
    fail_test "expected risk=mixed with evidence_missing signal, got risk=$risk signals=$signals"
  fi
end_test

# ─── T6 plan-integration: availability + draft_reply with fence → stays low ──
start_test "plan_with_fenced_high_conf_draft_stays_low"
  PLAN_JSON=$(python3 -c '
import json
print(json.dumps({
  "hypothesis": "Host is up, DNS flap",
  "steps": [{"description": "check DNS"}],
  "tools_needed": ["dig"],
  "draft_reply": "CONFIDENCE: 0.9\n```\ndig @127.0.0.1 OK\n```"
}))')
  out=$(echo "$PLAN_JSON" | ALERT_CATEGORY=availability ISSUE_ID=TEST-718-T6 \
         python3 "$CLASSIFY" --no-audit 2>/dev/null)
  risk=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['risk_level'])" "$out")
  if [ "$risk" = "low" ]; then
    :
  else
    fail_test "expected risk=low with fenced evidence, got risk=$risk"
  fi
end_test

# ─── T7 plan-integration: no draft_reply key → behavior unchanged ───────
start_test "plan_without_draft_reply_unchanged"
  PLAN_JSON='{
    "hypothesis": "plain availability alert",
    "steps": [{"description": "check service"}],
    "tools_needed": ["systemctl"]
  }'
  out=$(echo "$PLAN_JSON" | ALERT_CATEGORY=availability ISSUE_ID=TEST-718-T7 \
         python3 "$CLASSIFY" --no-audit 2>/dev/null)
  risk=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['risk_level'])" "$out")
  signals=$(python3 -c "import json,sys; print(' '.join(json.loads(sys.argv[1])['signals']))" "$out")
  # Should land `low` (availability category) with no evidence_missing signal
  if [ "$risk" = "low" ] && [[ "$signals" != *"evidence_missing"* ]]; then
    :
  else
    fail_test "expected low + no evidence_missing when draft absent, got risk=$risk signals=$signals"
  fi
end_test

# ─── T8 plan-integration: short/empty draft_reply → not flagged ─────────
start_test "plan_with_short_draft_not_flagged"
  PLAN_JSON='{
    "hypothesis": "plain alert",
    "steps": [{"description": "check"}],
    "draft_reply": "short"
  }'
  out=$(echo "$PLAN_JSON" | ALERT_CATEGORY=availability ISSUE_ID=TEST-718-T8 \
         python3 "$CLASSIFY" --no-audit 2>/dev/null)
  signals=$(python3 -c "import json,sys; print(' '.join(json.loads(sys.argv[1])['signals']))" "$out")
  if [[ "$signals" != *"evidence_missing"* ]]; then
    :
  else
    fail_test "short draft_reply should not flag, got signals=$signals"
  fi
end_test

# ─── T9 audit invariant: a bumped row cannot be auto-approved ───────────
start_test "evidence_missing_bump_prevents_auto_approve"
  PLAN_JSON='{"hypothesis": "x", "steps": [{"description": "y"}], "draft_reply": "CONFIDENCE: 0.95. Fix applied."}'
  out=$(echo "$PLAN_JSON" | ALERT_CATEGORY=availability ISSUE_ID=TEST-718-T9 \
         python3 "$CLASSIFY" --no-audit 2>/dev/null)
  auto=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['auto_approve_recommended'])" "$out")
  if [ "$auto" = "False" ]; then
    :
  else
    fail_test "expected auto_approve_recommended=False after bump, got: $auto"
  fi
end_test
