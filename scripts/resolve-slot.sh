#!/usr/bin/env bash
# resolve-slot.sh — look up cwd/room/etc for a given slot from gateway-state/slot-config.json
#
# Usage:
#   ./resolve-slot.sh <slot> <field>
#   ./resolve-slot.sh meshsat cwd
#     → /app/cubeos/meshsat
#
# Unknown slots fall back to the "default" slot.
# Missing field exits non-zero with an error to stderr.
# Designed to be called from n8n SSH nodes that need slot-aware paths.

set -euo pipefail

CONFIG="${GATEWAY_SLOT_CONFIG:-/home/app-user/gateway-state/slot-config.json}"

if [ $# -ne 2 ]; then
  echo "usage: $0 <slot> <field>" >&2
  exit 2
fi

SLOT="$1"
FIELD="$2"

if [ ! -r "$CONFIG" ]; then
  echo "error: cannot read $CONFIG" >&2
  exit 3
fi

# Try the named slot first; fall back to "default" if absent.
# jq -e returns non-zero when the result is null or false, which we use to detect missing entries.
VALUE="$(jq -re --arg slot "$SLOT" --arg field "$FIELD" '
  (.[$slot] // .default) as $entry
  | if $entry == null then "ERR_NO_SLOT_AND_NO_DEFAULT"
    else ($entry[$field] // "ERR_NO_FIELD") end
' "$CONFIG" 2>/dev/null)" || {
  echo "error: jq failed on $CONFIG (malformed JSON?)" >&2
  exit 4
}

case "$VALUE" in
  ERR_NO_SLOT_AND_NO_DEFAULT)
    echo "error: slot '$SLOT' not in $CONFIG and no 'default' slot defined" >&2
    exit 5
    ;;
  ERR_NO_FIELD)
    echo "error: field '$FIELD' not set for slot '$SLOT' (or default) in $CONFIG" >&2
    exit 6
    ;;
esac

printf '%s\n' "$VALUE"
