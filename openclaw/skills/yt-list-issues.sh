#\!/bin/bash
# Usage: ./yt-list-issues.sh "<query>"
# Lists YouTrack issues matching a search query.
# Examples:
#   ./yt-list-issues.sh "project: CUBEOS State: {In Progress}"
#   ./yt-list-issues.sh "project: MESHSAT State: Open"
#   ./yt-list-issues.sh "State: In Progress"  (auto-wrapped to {In Progress})
set -eu
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace /app/claude-gateway; do [ -r "$d/.env" ] && . "$d/.env" && break; done
: "${YOUTRACK_TOKEN:=${YOUTRACK_API_TOKEN:-}}"
: "${YOUTRACK_URL:=https://youtrack.example.net}"


QUERY="${1:?Usage: yt-list-issues.sh \"<query>\"}"

# Auto-wrap multi-word state values in curly braces if missing
QUERY=$(echo "$QUERY" | sed 's/State: In Progress/State: {In Progress}/g;s/State: To Verify/State: {To Verify}/g')

curl -sS --fail -G \
  -H "Authorization: Bearer $YOUTRACK_TOKEN" \
  --data-urlencode "query=${QUERY}" \
  --data-urlencode "fields=idReadable,summary,customFields(name,value(name))" \
  --data-urlencode "\$top=20" \
  "${YOUTRACK_URL}/api/issues"
