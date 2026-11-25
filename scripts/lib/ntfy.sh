#!/bin/bash
# ntfy publish helper for the tier-1 paging channel (2026-08-25 cutover).
# Source AFTER the caller has sourced .env with `set -a` (NTFY_URL /
# NTFY_TOPIC_TIER1 / NTFY_TOKEN in the environment).
#
#   ntfy_publish "title" "body" [priority 1-5, default 5] [tags, default rotating_light]
#
# Publishes via the TOPIC path (metadata in query params) so it also works
# through the public root route https://matrix.example.net/alrt-*.
# DRY_RUN=1 echoes instead of sending. Never fails the caller (best-effort).
# Runbook: docs/runbooks/paging-ntfy.md

ntfy_publish() {
    local title="$1" body="$2" prio="${3:-5}" tags="${4:-rotating_light}"
    if [ "${DRY_RUN:-0}" = "1" ]; then
        echo "[DRY_RUN NTFY p=${prio}] ${title} | ${body}"
        return 0
    fi
    if [ -z "${NTFY_URL:-}" ] || [ -z "${NTFY_TOKEN:-}" ]; then
        return 1
    fi
    local topic="${NTFY_TOPIC_TIER1:-alrt-tier1}"
    local q
    q=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.urlencode({"title": sys.argv[1][:200], "priority": sys.argv[2], "tags": sys.argv[3]}))' "$title" "$prio" "$tags" 2>/dev/null) || return 1
    curl -s -m 8 -o /dev/null \
        -H "Authorization: Bearer ${NTFY_TOKEN}" \
        --data-raw "$body" \
        "${NTFY_URL%/}/${topic}?${q}" 2>/dev/null
}
