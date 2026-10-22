#!/bin/bash
# Auto-heal stale NVML handles in the ollama containers (both planes).
#
# Why: when nvidia-persistenced restarts (e.g. after a driver/package update)
# it cycles the host /dev/nvidia* chardev nodes. A long-running container that
# bind-mounted the older nodes keeps stale device handles, so NVML init inside
# the container fails and ollama silently falls back to 100% CPU. Restarting
# the container re-binds against the live device nodes.
#
# Failure mode caught: 2026-05-14 incident, 10h CPU burn before operator noticed.
# Pairs with prom alert OllamaModelNotGpuOnly (15min) — this cron heals sooner.
#
# 2026-08-26 hardening (nl-gpu01 VRAM-starvation RCA): 16 restarts in
# 30 days against only 3 nvidia-persistenced cycles — most restarts were
# false positives, and every restart kills the in-flight requests of every
# Ollama client (omoikane, territory-grounder, the gateway RAG). Now:
#   * STRIKES consecutive minutes of NVML failure are required before a
#     restart (per-container state file), not a single probe + one 5 s retry;
#   * the host-side NVML must be healthy (otherwise a restart cannot help —
#     log and leave it to the operator);
#   * the actual nvidia-smi error text is logged to the journal so the next
#     real occurrence is diagnosable;
#   * `docker exec` is bounded with `timeout` so a wedged exec cannot be
#     mistaken for a broken NVML.
# 2026-08-26 (same RCA, later): Ollama split into two planes — `ollama`
# (:11434, embed-only) + `ollama-gen` (:11441, gateway LLM generates); both
# are checked independently.
set -u
STATE_DIR=/var/lib/ollama-nvml-selfheal
TAG=ollama-nvml-selfheal
THROTTLE_SEC=${THROTTLE_SEC:-300}
STRIKES=${STRIKES:-3}
PROBE_TIMEOUT=${PROBE_TIMEOUT:-20}
CONTAINERS=${CONTAINERS:-"ollama ollama-gen"}

mkdir -p "$STATE_DIR"

probe() {  # $1=container. Prints error text on failure; rc = nvidia-smi's (124 timeout).
    timeout "$PROBE_TIMEOUT" docker exec "$1" nvidia-smi -L 2>&1 >/dev/null
}

heal_container() {  # $1=container name
    local c="$1"
    local stamp="$STATE_DIR/last-restart-$c"
    local strike_file="$STATE_DIR/strikes-$c"

    if ! docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null | grep -q true; then
        logger -t "$TAG" "skip: container $c not running"
        return 0
    fi

    local err rc strikes age host_err
    if err=$(probe "$c"); then
        [ -f "$strike_file" ] && { rm -f "$strike_file"; logger -t "$TAG" "recovered: $c NVML OK again, strikes cleared"; }
        return 0
    fi
    rc=$?

    strikes=$(( $(cat "$strike_file" 2>/dev/null || echo 0) + 1 ))
    echo "$strikes" > "$strike_file"
    logger -t "$TAG" "strike ${strikes}/${STRIKES}: $c NVML probe failed rc=${rc}: $(echo "$err" | tr '\n' ' ' | cut -c1-200)"
    [ "$strikes" -lt "$STRIKES" ] && return 0

    # Enough strikes. Only restart if the HOST side is healthy — a broken host
    # driver cannot be fixed by restarting the container.
    if ! host_err=$(timeout "$PROBE_TIMEOUT" nvidia-smi -L 2>&1 >/dev/null); then
        logger -t "$TAG" "ERROR: host NVML also broken (rc=$?): $(echo "$host_err" | tr '\n' ' ' | cut -c1-200) — NOT restarting $c; investigate manually"
        return 2
    fi

    if [ -f "$stamp" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$stamp") ))
        if [ "$age" -lt "$THROTTLE_SEC" ]; then
            logger -t "$TAG" "throttled: $c last restart ${age}s ago (<${THROTTLE_SEC}s); investigate manually"
            return 1
        fi
    fi

    logger -t "$TAG" "WARN: NVML init failed inside $c ${strikes}x consecutively (host OK), restarting"
    docker restart "$c"
    touch "$stamp"
    rm -f "$strike_file"
    sleep 5
    if probe "$c" >/dev/null; then
        logger -t "$TAG" "OK: $c NVML restored after restart"
        return 0
    fi
    logger -t "$TAG" "ERROR: $c NVML still broken after restart"
    return 2
}

worst=0
for c in $CONTAINERS; do
    heal_container "$c"; rc=$?
    [ "$rc" -gt "$worst" ] && worst=$rc
done
exit "$worst"
