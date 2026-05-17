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
