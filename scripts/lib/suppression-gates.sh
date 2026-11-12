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
# READ-ONLY monitors use readonly_monitor_gate instead (see below): they keep observing and
# writing metrics while gated; only their notifications are suppressed.
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

# READ-ONLY monitor classification (IFRNLLEI01PRD-2992, 2026-11-07). A script that only READS device
# state and writes metrics (no config change, no restart, no remediation, no actuation of any kind)
# is a READ-ONLY monitor. Its observe + metrics path runs even while ~/gateway.maintenance (incl. the
# 2026-08-26 master switch) or a chaos marker is present: exiting early there blinded the estate
# from 2026-08-26 to 2026-11-07 (no budget_pppoe.prom / vps_route_health.prom / bgp_mesh_watchdog.prom).
# Only the NOTIFICATION edge (SMS / ntfy / Matrix, plus the transition state file that drives it)
# still honours the gates, so paging behaviour is unchanged. Never exits. Usage:
#   readonly_monitor_gate; NOTIFY_SUPPRESSED=$?    # 0 = may notify, 1 = notifications suppressed
# Every caller MUST be listed in READONLY_MONITORS (QA asserts the list == the callers, and that no
# listed script carries an actuation verb). Actuators keep `check_suppression_gates || exit 0`.
READONLY_MONITORS="bgp-mesh-watchdog.sh budget-pppoe-health.sh vps-route-health.sh"
readonly_monitor_gate() {
    check_suppression_gates
}

# MUTATIONS=OFF shadow mode (IFRNLLEI01PRD-1824). Returns 0 (shadow ACTIVE = log-only) when
# $MUTATIONS_OFF is truthy or ~/gateway.mutations_off exists. Deliberately SEPARATE from
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

# Per-lane shadow exemption (pattern from the TG lane, commit 4e8e3c4; first lane user:
# the intersite tunnel heal family — IFRNLLEI01PRD-1833). An actuator lane may be allowed to
# act while GLOBAL shadow stays on, by arming ~/gateway.mutations_<lane>_allow. Every actuation
# admitted this way MUST be audited via mutation_exempt_audit (audit on ACTION, not per tick —
# */3 cron cadence would spam the per-command TG idiom).
#   mutation_shadow_exempt intersite || { mutation_shadow_log "<verb>" "suppressed..."; exit 0; }
# Returns 0 = OK to act (not shadow, or shadow+exemption armed); 1 = suppressed.
mutation_shadow_exempt() {
    mutation_shadow || return 0
    [ -f "${GATEWAY_HOME:-$HOME}/gateway.mutations_${1}_allow" ]
}

# Append one audit line for an actuation admitted by the lane exemption. $1=lane, rest=free text.
# Fail-open: audit failure must never block the allowed action (house rule from the TG lane).
mutation_exempt_audit() {
    local lane="$1"; shift
    local dir="${MUTATION_SHADOW_LOG_DIR:-${GATEWAY_HOME:-$HOME}/logs/claude-gateway/mutation-shadow}"
    mkdir -p "$dir" 2>/dev/null || true
    echo "$(date -u +%Y-%m-%dT%H:%M:%S) lane=${lane} source=$(basename "$0") $*" \
        >> "$dir/${lane}-exempt-allows.log" 2>/dev/null || true
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
