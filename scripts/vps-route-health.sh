#!/bin/bash
# vps-route-health.sh — Verify VPSs use a BGP-driven route for the DMZ /27
#
# Regression check for the 2026-04-21 swanctl-loader.service change that
# removed the two static `ip route add 10.0.X.X/27 dev xfrm-nl{-f}`
# lines on both VPSs. Intent was to let FRR own the route via BGP (with
# proto bgp), enabling BFD-driven sub-second ISP failover.
#
# Failure mode: if FRR stops installing its BGP route (FRR crash, rekey
# race, netlink glitch), the kernel has NO route for 10.0.X.X/27.
# `ip route get 10.0.X.X` would then resolve out `mainif` (public
# internet) — HAProxy backend connections → DMZ services silently
# blackhole.
#
# This script is read-only. On regression it emits vps_dmz_route_bgp=0
# and posts a Matrix notice. Actual remediation (re-installing the
# static /27 as a temporary band-aid, or restarting FRR) is a human
# decision, never automatic.
#
# Cron: */5 * * * * /app/claude-gateway/scripts/vps-route-health.sh
#
# Introduced 2026-04-22 [IFRNLLEI01PRD-672].

set -uo pipefail

REPO_DIR="/app/claude-gateway"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="/home/app-user/scripts/maintenance-state/vps-route-health.state"
LOG_TAG="[vps-route-health]"

if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

mkdir -p "$(dirname "$STATE_FILE")"

# shellcheck source=scripts/lib/suppression-gates.sh
source "$REPO_DIR/scripts/lib/suppression-gates.sh"
check_suppression_gates || exit 0

PW="${CISCO_ASA_PASSWORD:-}"  # needed for sudo on VPS (even for ip route get)
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -i "$HOME/.ssh/one_key")

# Returns status string: "bgp:<dev>" | "mainif" | "static:<dev>" | "unreachable" | "missing"
probe_vps() {
    local host="$1"
    # `ip route show 10.0.X.X/27` returns all routing-table entries; the
    # best one for lookup is the one with the lowest metric + best proto. We
    # look for proto=bgp as the healthy-state signal. Route-lookup-time
    # resolution via `ip route get` doesn't expose `proto`, hence `show`.
    local out
    out=$(ssh "${SSH_OPTS[@]}" "operator@${host}" \
        "ip route show 10.0.X.X/27 2>/dev/null" 2>/dev/null)
    if [ -z "$out" ]; then
        # Could be unreachable OR no route at all. Check live-route separately.
        local get_out
        get_out=$(ssh "${SSH_OPTS[@]}" "operator@${host}" \
            "ip route get 10.0.X.X 2>/dev/null | head -1" 2>/dev/null)
        if [ -z "$get_out" ]; then
            echo "unreachable"; return
        fi
        if echo "$get_out" | grep -qE 'dev mainif'; then
            echo "mainif"; return
        fi
        echo "missing"; return
    fi
    # Prefer lines with `proto bgp`; otherwise report static on the first dev
    local bgp_line
    bgp_line=$(echo "$out" | grep -E 'proto bgp' | head -1 || true)
    if [ -n "$bgp_line" ]; then
        local dev
        dev=$(echo "$bgp_line" | grep -oE 'dev [^ ]+' | head -1 | awk '{print $2}')
        echo "bgp:${dev:-unknown}"
        return
    fi
    # No BGP-installed entry. Check what IS there.
    if echo "$out" | grep -qE 'dev mainif'; then
        echo "mainif"
        return
    fi
    local first_dev
    first_dev=$(echo "$out" | head -1 | grep -oE 'dev [^ ]+' | head -1 | awk '{print $2}')
    echo "static:${first_dev:-unknown}"
}

write_prom() {
    local no_status="$1" ch_status="$2"
    local metrics_file="/var/lib/node_exporter/textfile_collector/vps_route_health.prom"
    local tmp="${metrics_file}.tmp"
    [ -d "$(dirname "$metrics_file")" ] || return 0
    local no_bgp ch_bgp
    [[ "$no_status" == bgp:* ]] && no_bgp=1 || no_bgp=0
    [[ "$ch_status" == bgp:* ]] && ch_bgp=1 || ch_bgp=0
    cat > "$tmp" <<PROM
# HELP vps_dmz_route_bgp 1 if VPS routes 10.0.X.X/27 via proto bgp, 0 if via mainif (regression) or static
# TYPE vps_dmz_route_bgp gauge
vps_dmz_route_bgp{vps="notrf01vps01"} $no_bgp
vps_dmz_route_bgp{vps="chzrh01vps01"} $ch_bgp
# HELP vps_dmz_route_status_info Label-carrying gauge with the route status string (value=1)
# TYPE vps_dmz_route_status_info gauge
vps_dmz_route_status_info{vps="notrf01vps01",status="${no_status}"} 1
vps_dmz_route_status_info{vps="chzrh01vps01",status="${ch_status}"} 1
# HELP vps_route_health_last_run_timestamp Unix ts of last successful run
# TYPE vps_route_health_last_run_timestamp gauge
vps_route_health_last_run_timestamp $(date +%s)
PROM
    mv "$tmp" "$metrics_file"
}

post_matrix() {
    local msg="$1"
    local token="${MATRIX_CLAUDE_TOKEN:-}"
    [ -z "$token" ] && return 0
    local room="!AOMuEtXGyzGFLgObKN:matrix.example.net"
    local txn="vps-route-$(date +%s%N)-$$"
    curl -sf --max-time 10 -X PUT \
      "https://matrix.example.net/_matrix/client/v3/rooms/${room}/send/m.room.message/${txn}" \
      -H "Authorization: Bearer ${token}" \
      -H "Content-Type: application/json" \
      -d "{\"msgtype\":\"m.notice\",\"body\":$(printf '%s' "$msg" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')}" \
      >/dev/null 2>&1 || true
}

# ── Main ──
no_status=$(probe_vps "198.51.100.X")
ch_status=$(probe_vps "198.51.100.X")
write_prom "$no_status" "$ch_status"

current_state=$(cat "$STATE_FILE" 2>/dev/null || echo "unknown")
new_state="no=${no_status}|ch=${ch_status}"

# Alert on regression to mainif (CRITICAL) or transition to any non-BGP state
if [[ "$no_status" == "mainif" || "$ch_status" == "mainif" ]]; then
    if [ "$current_state" != "$new_state" ]; then
        logger "$LOG_TAG REGRESSION: notrf01=${no_status} chzrh01=${ch_status}"
        post_matrix "[vps-route-health] CRITICAL: VPS kernel route for 10.0.X.X/27 regressed to mainif (public internet). HAProxy→DMZ blackhole imminent. notrf01vps01=${no_status} chzrh01vps01=${ch_status}. Investigate FRR on the affected VPS."
    fi
elif [[ "$no_status" == "unreachable" && "$ch_status" == "unreachable" ]]; then
    if [[ "$current_state" != *"unreachable|ch=unreachable"* ]]; then
        logger "$LOG_TAG both VPSs unreachable via SSH"
    fi
fi

echo "$new_state" > "$STATE_FILE"
