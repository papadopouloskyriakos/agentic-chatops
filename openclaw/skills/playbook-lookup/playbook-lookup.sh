#!/bin/bash
# playbook-lookup.sh — Query incident knowledge base for past resolutions
# Usage: playbook-lookup.sh <search_term>
# Search term can be: hostname, alert rule name, or issue ID
set -euo pipefail

SEARCH="${1:-}"
if [ -z "$SEARCH" ]; then
  echo "Usage: playbook-lookup.sh <hostname|alert_rule|issue_id>"
  echo "Example: playbook-lookup.sh nl-pve01"
  exit 1
fi

REMOTE="app-user@nl-claude01"
SEARCH_SCRIPT="/app/claude-gateway/scripts/kb-semantic-search.py"

# Semantic search via SSH to app-user (where the DB + script live)
# Falls back to keyword search if Ollama is unreachable
RESULTS=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes \
  -i ~/.ssh/one_key "$REMOTE" \
  "python3 '$SEARCH_SCRIPT' search '${SEARCH//\'/\\\'}' --limit 5 --days 0" 2>/dev/null) || true

if [ -z "$RESULTS" ]; then
  echo "No past incidents found matching '$SEARCH'."
  echo ""
  echo "The knowledge base contains resolved infrastructure sessions."
  echo "Try searching by: hostname (e.g., nl-pve01), alert rule (e.g., CiliumAgentNotReady), or issue ID (e.g., IFRNLLEI01PRD-109)."
  exit 0
fi

echo "=== Past Incident Resolutions for '$SEARCH' ==="
echo ""

echo "$RESULTS" | while IFS='|' read -r issue_id hostname alert_rule resolution confidence created_at site similarity; do
  echo "--- $issue_id ($created_at, site: $site, match: ${similarity:-keyword}) ---"
  [ -n "$hostname" ] && echo "  Host : $hostname"
  [ -n "$alert_rule" ] && echo "  Alert: $alert_rule"
  echo "  Conf : $confidence"
  echo "  Resolution: $resolution"
  echo ""
done

COUNT=$(echo "$RESULTS" | wc -l)
echo "Found $COUNT matching incident(s)."
