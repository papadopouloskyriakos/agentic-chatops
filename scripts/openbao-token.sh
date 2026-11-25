#!/bin/bash
# G14: Fetch a short-lived token from OpenBao (AppRole auth)
#
# Usage:
#   source scripts/openbao-token.sh <secret-path> [--ttl <seconds>] [--issue <id>]
#   eval $(scripts/openbao-token.sh kv/data/claude-gateway/anthropic-api-key --ttl 3600)
#
# Prerequisites:
#   - OpenBao cluster reachable (3 nodes on pve01/pve02/pve03)
#   - AppRole auth enabled for app-user
#   - OPENBAO_ADDR, OPENBAO_ROLE_ID, OPENBAO_SECRET_ID set in environment or .env
#
# Currently supports:
#   - kv/data/claude-gateway/anthropic-api-key  → exports ANTHROPIC_API_KEY
#
# This is Phase 4 (research) — designed for future expansion.
# Does NOT modify any existing secrets. Logs all usage to credential_usage_log.

set -euo pipefail

DB="${HOME}/gitlab/products/cubeos/claude-context/gateway.db"
SECRET_PATH="${1:-}"
TTL=3600
ISSUE_ID=""
SESSION_ID=""

# Parse flags
shift 1 2>/dev/null || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ttl)     TTL="$2"; shift 2 ;;
    --issue)   ISSUE_ID="$2"; shift 2 ;;
    --session) SESSION_ID="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$SECRET_PATH" ]]; then
  echo "Usage: openbao-token.sh <secret-path> [--ttl <seconds>] [--issue <id>]" >&2
  exit 1
fi

# Load OpenBao config from environment or .env
OPENBAO_ADDR="${OPENBAO_ADDR:-}"
OPENBAO_ROLE_ID="${OPENBAO_ROLE_ID:-}"
OPENBAO_SECRET_ID="${OPENBAO_SECRET_ID:-}"

if [[ -z "$OPENBAO_ADDR" ]]; then
  ENV_FILE="${HOME}/gitlab/n8n/claude-gateway/.env"
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source <(grep -E '^OPENBAO_' "$ENV_FILE" | sed 's/^/export /')
  fi
fi

# Fallback: if OpenBao is not configured, use existing .env credential
if [[ -z "$OPENBAO_ADDR" || -z "$OPENBAO_ROLE_ID" ]]; then
  echo "# OpenBao not configured — falling back to persistent .env credential" >&2

  # Map secret path to env var name
  ENV_VAR=""
  case "$SECRET_PATH" in
    *anthropic*) ENV_VAR="ANTHROPIC_API_KEY" ;;
    *youtrack*)  ENV_VAR="YOUTRACK_TOKEN" ;;
    *netbox*)    ENV_VAR="NETBOX_TOKEN" ;;
    *matrix*)    ENV_VAR="MATRIX_ACCESS_TOKEN" ;;
    *)
      echo "Unknown secret path: $SECRET_PATH" >&2
      exit 1
      ;;
  esac

  # Read from .env
  VALUE=$(grep "^${ENV_VAR}=" "${HOME}/gitlab/n8n/claude-gateway/.env" 2>/dev/null | cut -d= -f2- | tr -d "'\"" || echo "")
  if [[ -z "$VALUE" ]]; then
    echo "# $ENV_VAR not found in .env" >&2
    exit 1
  fi

  # Log usage (persistent credential, TTL=0)
  sqlite3 "$DB" "INSERT INTO credential_usage_log (credential_name, source, session_id, issue_id, ttl_seconds) VALUES ('$ENV_VAR', 'env', '$SESSION_ID', '$ISSUE_ID', 0)" 2>/dev/null || true

  # Export for sourcing
  echo "export ${ENV_VAR}='${VALUE}'"
  exit 0
fi

# --- OpenBao AppRole authentication ---
echo "# Authenticating to OpenBao at $OPENBAO_ADDR" >&2

# Get a short-lived client token via AppRole
AUTH_RESPONSE=$(curl -sk --max-time 10 \
  --request POST \
  --data "{\"role_id\": \"$OPENBAO_ROLE_ID\", \"secret_id\": \"$OPENBAO_SECRET_ID\"}" \
  "$OPENBAO_ADDR/v1/auth/approle/login" 2>/dev/null)

CLIENT_TOKEN=$(echo "$AUTH_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('auth',{}).get('client_token',''))" 2>/dev/null)

if [[ -z "$CLIENT_TOKEN" ]]; then
  echo "# OpenBao AppRole auth failed — falling back to .env" >&2
  # Recursive fallback with empty OPENBAO_ADDR
  OPENBAO_ADDR="" exec "$0" "$SECRET_PATH" --ttl "$TTL" --issue "$ISSUE_ID" --session "$SESSION_ID"
fi

# Fetch the secret
SECRET_RESPONSE=$(curl -sk --max-time 10 \
  --header "X-Vault-Token: $CLIENT_TOKEN" \
  "$OPENBAO_ADDR/v1/$SECRET_PATH" 2>/dev/null)

SECRET_VALUE=$(echo "$SECRET_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin).get('data',{}).get('data',{}); print(next(iter(d.values()),''))" 2>/dev/null)

if [[ -z "$SECRET_VALUE" ]]; then
  echo "# Failed to read secret from $SECRET_PATH" >&2
  exit 1
fi

# Map secret path to env var
ENV_VAR=""
case "$SECRET_PATH" in
  *anthropic*) ENV_VAR="ANTHROPIC_API_KEY" ;;
  *youtrack*)  ENV_VAR="YOUTRACK_TOKEN" ;;
  *netbox*)    ENV_VAR="NETBOX_TOKEN" ;;
  *matrix*)    ENV_VAR="MATRIX_ACCESS_TOKEN" ;;
esac

EXPIRES_AT=$(date -u -d "+${TTL} seconds" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -v+${TTL}S '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)

# Log usage (short-lived credential)
sqlite3 "$DB" "INSERT INTO credential_usage_log (credential_name, source, session_id, issue_id, ttl_seconds, expires_at) VALUES ('$ENV_VAR', 'openbao', '$SESSION_ID', '$ISSUE_ID', $TTL, '$EXPIRES_AT')" 2>/dev/null || true

# Revoke the client token (minimize exposure window)
curl -sk --max-time 5 \
  --header "X-Vault-Token: $CLIENT_TOKEN" \
  --request POST \
  "$OPENBAO_ADDR/v1/auth/token/revoke-self" 2>/dev/null || true

echo "# OpenBao: fetched $ENV_VAR (TTL: ${TTL}s, expires: $EXPIRES_AT)" >&2
echo "export ${ENV_VAR}='${SECRET_VALUE}'"
