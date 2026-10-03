#!/bin/bash
# pipeline-debug.sh — shared structured debug logging for the cc-cc triage pipeline.
#
# WHY: the alert -> triage -> escalate -> Runner -> classify chain failed silently
# (broken Classify-Risk node passed an empty plan; classifier fail-closed; audit
# never written). This helper leaves a JSON trail per stage so a future break is
# visible immediately. Source it, then call `pdbg <event> <issue_id> [detail...]`.
#
#   source /app/claude-gateway/scripts/lib/pipeline-debug.sh
#   pdbg triage_start "$ISSUE_ID" "kind=k8s alert=$ALERTNAME sev=$SEVERITY"
#
# Trail for one incident (this + classify-session-risk.py write to the SAME file):
#   grep <ISSUE-ID> /home/app-user/logs/claude-gateway/pipeline-debug.log
#
# Absolute default path — survives an unset/odd HOME in the n8n SSH context (the
# very condition that hid the autonomy sentinel). Override with GATEWAY_DEBUG_LOG.

PIPELINE_DEBUG_LOG="${GATEWAY_DEBUG_LOG:-/home/app-user/logs/claude-gateway/pipeline-debug.log}"
# Name of the script that sourced us (for the "script" field).
PIPELINE_DEBUG_SCRIPT="${PIPELINE_DEBUG_SCRIPT:-$(basename "${BASH_SOURCE[1]:-${0:-pipeline}}")}"

pdbg() {
  # pdbg <event> <issue_id> [detail words...]
  local event="${1:-event}" issue="${2:-}"
  shift 2 2>/dev/null || true
  local detail="$*"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$(dirname "$PIPELINE_DEBUG_LOG")" 2>/dev/null || true
  # python does the JSON escaping so arbitrary detail (summaries, errors) is safe.
  python3 - "$ts" "$PIPELINE_DEBUG_SCRIPT" "$event" "$issue" "$detail" \
    >> "$PIPELINE_DEBUG_LOG" 2>/dev/null <<'PY' || true
import json, sys, os
print(json.dumps({
    "ts": sys.argv[1], "script": sys.argv[2], "event": sys.argv[3],
    "issue_id": sys.argv[4], "detail": sys.argv[5], "pid": os.getppid(),
}))
PY
}
