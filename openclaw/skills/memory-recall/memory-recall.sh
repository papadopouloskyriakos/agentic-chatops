#!/bin/bash
# memory-recall.sh — Query OpenClaw's episodic memory (past triage outcomes)
# Usage: memory-recall.sh <search_term>
set -euo pipefail

SEARCH="${1:-}"
if [ -z "$SEARCH" ]; then
  echo "Usage: memory-recall.sh <hostname|alertname|keyword>"
  exit 1
fi

REMOTE="claude-runner@nl-claude01"
DB="/home/claude-runner/gitlab/products/cubeos/claude-context/gateway.db"

RESULTS=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes \
  -i ~/.ssh/one_key "$REMOTE" \
  "sqlite3 -separator '|' '$DB' \"
    SELECT key, value, issue_id, updated_at FROM openclaw_memory
    WHERE key LIKE '%${SEARCH}%' OR value LIKE '%${SEARCH}%'
    ORDER BY updated_at DESC LIMIT 5;
  \"" 2>/dev/null) || true

if [ -z "$RESULTS" ]; then
  echo "No past triage memory found for '$SEARCH'."
  exit 0
fi

echo "=== Past Triage Memory for '$SEARCH' ==="
echo ""

echo "$RESULTS" | while IFS='|' read -r key value issue_id updated_at; do
  echo "[$updated_at] $key — $value (issue: $issue_id)"
done

echo ""
echo "Found $(echo "$RESULTS" | wc -l) memory entries."
