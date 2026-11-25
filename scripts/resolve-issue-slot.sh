#!/usr/bin/env bash
# resolve-issue-slot.sh <issueId>
#
# Disambiguate which meshsat-family workspace slot a MESHSAT-* issue should
# dispatch to, based on its YouTrack tags (IFRNLLEI01PRD-940). All three
# meshsat sibling repos (meshsat / meshsat-hub / meshsat-android) share the
# single MESHSAT YouTrack project + #meshsat room, so the project prefix alone
# cannot tell them apart. Tags do:
#     tag 'meshsat-android' (or 'android') -> meshsat-android
#     tag 'meshsat-hub'     (or 'hub')     -> meshsat-hub
#     (no such tag / lookup fails)         -> meshsat   (bridge default)
#
# For non-MESHSAT issue IDs it prints NOTHING and exits 0 -- the caller keeps
# its prefix-derived slot. Prints ONLY the resolved slot to stdout; all
# diagnostics go to stderr. ALWAYS exits 0 on the resolution path so an n8n
# SSH node calling this never halts a dispatch (fail-safe == 'meshsat', i.e.
# the legacy single-slot behaviour).
#
# Consumed by the 'Resolve MESHSAT Slot' SSH nodes in:
#   - Runner       (qadF2WcaBsIR7SWG)  -> dispatch cwd/lock
#   - Matrix Bridge (QGKnHGkw4casiWIU) -> resume cwd/lock
#
# Test hook: set _TAGS_OVERRIDE to a tags JSON array to skip the HTTP call
# (used by scripts/qa/suites/test-940-meshsat-slot-routing.sh).

set -uo pipefail

ISSUE="${1:-}"

DBG_LOG="/home/app-user/logs/claude-gateway/pipeline-debug.log"
_pdbg() {
  [ -d "$(dirname "$DBG_LOG")" ] || return 0
  printf '{"ts":"%s","stage":"resolve-issue-slot","event":"%s","issue":"%s","detail":"%s"}\n' \
    "$(date -u +%FT%TZ 2>/dev/null)" "$1" "${ISSUE:-}" "${2:-}" >> "$DBG_LOG" 2>/dev/null || true
}

emit() { printf '%s\n' "$1"; _pdbg resolved "slot=$1"; exit 0; }

if [ -z "$ISSUE" ]; then
  echo "usage: $0 <issueId>" >&2
  exit 0   # empty stdout -> caller keeps its default slot
fi

# Only MESHSAT-* issues are ambiguous across the sibling repos.
case "$ISSUE" in
  MESHSAT-*) : ;;
  *) exit 0 ;;   # non-MESHSAT: print nothing, caller keeps prefix-derived slot
esac

# ---- obtain the issue's tags (JSON array of {"name":...}) ----
if [ -n "${_TAGS_OVERRIDE:-}" ]; then
  tags="$_TAGS_OVERRIDE"                 # test hook
else
  YT_URL="${YOUTRACK_URL:-https://youtrack.example.net}"
  TOKEN="${YOUTRACK_TOKEN:-${YT_TOKEN:-${YOUTRACK_API_TOKEN:-}}}"
  if [ -z "$TOKEN" ]; then
    for d in /app/claude-gateway /home/app-user; do
      if [ -r "$d/.env" ]; then
        # shellcheck source=/dev/null
        . "$d/.env" 2>/dev/null || true
        TOKEN="${YOUTRACK_TOKEN:-${YT_TOKEN:-${YOUTRACK_API_TOKEN:-}}}"
        [ -n "$TOKEN" ] && break
      fi
    done
  fi
  if [ -z "$TOKEN" ]; then
    echo "resolve-issue-slot: no YouTrack token found; defaulting to meshsat" >&2
    emit "meshsat"
  fi
  tags="$(curl -sk --max-time 8 \
    -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" \
    "$YT_URL/api/issues/$ISSUE/tags?fields=name" 2>/dev/null)" || tags=""
fi

# ---- match whole tag names (closing quote anchors the value, so 'github'
#      never matches 'hub', etc.) ----
tags_lc="$(printf '%s' "$tags" | tr '[:upper:]' '[:lower:]')"
_has_tag() { printf '%s' "$tags_lc" | grep -qE "\"name\"[[:space:]]*:[[:space:]]*\"($1)\""; }

if   _has_tag 'meshsat-android|android'; then emit "meshsat-android"
elif _has_tag 'meshsat-hub|hub';         then emit "meshsat-hub"
else                                          emit "meshsat"
fi
