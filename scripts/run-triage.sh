#!/bin/bash
# Wrapper invoked by n8n SSH receivers for cc-cc-mode triage.
# Usage: run-triage.sh <kind> <args...>
# Kinds: k8s | infra | security | correlated | escalate
set -uo pipefail

KIND="${1:-}"
shift || true

# Structured debug trail (IFRNLLEI01PRD pipeline observability).
PIPELINE_DEBUG_SCRIPT="run-triage.sh"
# shellcheck source=lib/pipeline-debug.sh
source /app/claude-gateway/scripts/lib/pipeline-debug.sh 2>/dev/null || pdbg() { :; }
pdbg "triage_start" "" "kind=$KIND argc=$# args=$*"

cd /app/claude-gateway/openclaw || { pdbg "triage_error" "" "cd-openclaw-failed"; exit 1; }

_rc=0
case "$KIND" in
  k8s)
    # args: alertname severity namespace summary node pod
    timeout 600 ./skills/k8s-triage/k8s-triage.sh "$@" 2>&1
    ;;
  infra)
    # args: hostname rule_name severity
    timeout 600 ./skills/infra-triage/infra-triage.sh "$@" 2>&1
    ;;
  security)
    # args: target summary severity scanner
    timeout 600 ./skills/security-triage/security-triage.sh "$@" 2>&1
    ;;
  correlated)
    # args: hosts rules sevs
    timeout 600 ./skills/correlated-triage/correlated-triage.sh "$@" 2>&1
    ;;
  escalate)
    # args: issue_id message
    FORCE_ESCALATE=true timeout 600 ./skills/escalate-to-claude.sh "$@" 2>&1
    ;;
  *)
    echo "ERROR: unknown triage kind: $KIND" >&2
    pdbg "triage_end" "" "kind=$KIND exit=2 reason=unknown-kind"
    exit 2
    ;;
esac
_rc=$?
pdbg "triage_end" "" "kind=$KIND exit=$_rc"
exit "$_rc"
