# shellcheck shell=bash
# scripts/lib/suppression-gates.sh — shared maintenance/chaos gate
#
# Usage (bash):
#   # shellcheck source=scripts/lib/suppression-gates.sh
#   source "$(dirname "$0")/lib/suppression-gates.sh"
#   check_suppression_gates || exit 0
#
# Returns 0 (OK to proceed) in the normal case.
# Returns 1 (suppressed) if:
#   - /home/app-user/gateway.maintenance exists (operator-driven maintenance)
#   - $HOME/chaos-state/chaos-active.json exists (chaos experiment in flight)
#
# Companion to IFRNLLEI01PRD-672. Replaces inline duplication previously found
# in vti-freedom-recovery.sh, asa-reboot-watch.sh, chaos-calendar.sh, etc.

check_suppression_gates() {
    if [ -f "/home/app-user/gateway.maintenance" ]; then
        return 1
    fi
    if [ -f "${HOME}/chaos-state/chaos-active.json" ]; then
        return 1
    fi
    return 0
}

# MUTATIONS=OFF shadow mode (IFRNLLEI01PRD-1824). Returns 0 (shadow ACTIVE = log-only) when
# $GATEWAY_MUTATIONS_OFF is truthy or ~/gateway.mutations_off exists. Deliberately SEPARATE from
# check_suppression_gates(): shadow preserves observability, so the read-only metric writers that
# source this lib must keep emitting under shadow — do NOT fold this into check_suppression_gates.
# Actuators call it right before mutating:  mutation_shadow && { echo "shadow: logged, not run"; exit 0; }
mutation_shadow() {
    if [ -n "${MUTATIONS_OFF:-}" ]; then
        case "${MUTATIONS_OFF}" in 0|false|False|no|NO|"") return 1 ;; *) return 0 ;; esac
    fi
    [ -f "${GATEWAY_HOME:-$HOME}/gateway.mutations_off" ]
}

# Convenience: log a would-have-actuated decision to the dedicated shadow folder, then the caller
# should exit 0. $1=short action verb, remaining args = free-text rationale/context.
mutation_shadow_log() {
    local action="$1"; shift
    local dir="${MUTATION_SHADOW_LOG_DIR:-${GATEWAY_HOME:-$HOME}/logs/claude-gateway/mutation-shadow}"
    mkdir -p "$dir" 2>/dev/null || true
    printf '{"ts":%s,"iso":"%s","host":"%s","source":"%s","action":"%s","rationale":"%s","mode":"shadow","blocked":true}\n' \
        "$(date +%s)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname)" "$(basename "$0")" "$action" "$*" \
        >> "$dir/shadow-$(date -u +%Y-%m-%d).jsonl" 2>/dev/null || true
}

# Exported for clarity in callers that want to branch on *reason*.
suppression_reason() {
    if [ -f "/home/app-user/gateway.maintenance" ]; then
        echo "maintenance"
    elif [ -f "${HOME}/chaos-state/chaos-active.json" ]; then
        echo "chaos"
    else
        echo "none"
    fi
}
