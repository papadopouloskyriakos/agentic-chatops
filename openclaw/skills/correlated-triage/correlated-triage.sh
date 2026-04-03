#!/bin/bash
# Correlated Alert Triage — multi-host burst handling
# Usage: ./skills/correlated-triage/correlated-triage.sh "host1,host2,host3" "rule1,rule2,rule3" "sev1,sev2,sev3" [--site nl|gr]
# Creates a master YT issue, runs per-host triage, links children, analyzes correlation.

set -uo pipefail

HOSTS_CSV="${1:?Usage: correlated-triage.sh \"hosts\" \"rules\" \"severities\" [--site nl|gr]}"
RULES_CSV="${2:-Unknown Alert,Unknown Alert,Unknown Alert}"
SEVS_CSV="${3:-unknown,unknown,unknown}"

# Parse --site flag from remaining args
shift 3 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    --site) TRIAGE_SITE="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Auto-detect site from first hostname if not explicitly set
if [ -z "${TRIAGE_SITE:-}" ]; then
  FIRST_HOST=$(echo "$HOSTS_CSV" | cut -d',' -f1)
  if echo "$FIRST_HOST" | grep -qi "^grskg"; then
    TRIAGE_SITE="gr"
  else
    TRIAGE_SITE="nl"
  fi
fi
export TRIAGE_SITE

# Load site configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SCRIPT_DIR/site-config.sh"

# Load credentials
source /home/app-user/.openclaw/workspace/.env

# Parse comma-separated inputs into arrays
IFS=',' read -ra HOSTS <<< "$HOSTS_CSV"
IFS=',' read -ra RULES <<< "$RULES_CSV"
IFS=',' read -ra SEVS <<< "$SEVS_CSV"

HOST_COUNT=${#HOSTS[@]}
BURST_TIME=$(date -u +%H:%M)
BURST_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo "=== CORRELATED ALERT TRIAGE: $HOST_COUNT hosts ==="
echo "Hosts: ${HOSTS_CSV}"
echo "Rules: ${RULES_CSV}"
echo "Severities: ${SEVS_CSV}"
echo ""

# ─── Step 1: Create MASTER YouTrack Issue ───
echo "--- Step 1: Creating MASTER YouTrack issue ---"
HOST_LIST=$(printf '%s, ' "${HOSTS[@]}")
HOST_LIST=${HOST_LIST%, }
MASTER_DESC="Correlated alert burst detected at $BURST_DATE

$HOST_COUNT hosts affected simultaneously:
$(for i in "${!HOSTS[@]}"; do echo "- ${HOSTS[$i]}: ${RULES[$i]:-Unknown} (${SEVS[$i]:-unknown})"; done)

This is likely a shared root cause (common hypervisor, VLAN, power, or upstream failure).
Individual host triage results will be linked as subtask issues below."

MASTER_RESULT=$(./skills/yt-create-issue.sh $YT_PROJECT \
  "Correlated alert burst: $HOST_COUNT hosts affected at $BURST_TIME UTC" \
  "$MASTER_DESC" 2>&1)
echo "$MASTER_RESULT"

MASTER_ID=$(echo "$MASTER_RESULT" | grep -oP '$YT_PROJECT-\d+' | head -1)
if [ -z "$MASTER_ID" ]; then
  echo "ERROR: Failed to create master issue. Falling back to individual triage."
  # Fallback: run individual triage for each host (with escalation)
  for i in "${!HOSTS[@]}"; do
    echo "--- Fallback triage for ${HOSTS[$i]} ---"
    ./skills/infra-triage/infra-triage.sh "${HOSTS[$i]}" "${RULES[$i]:-Unknown Alert}" "${SEVS[$i]:-unknown}" --site "$SITE_ID" 2>&1 || true
  done
  exit 1
fi
echo "Master issue created: $MASTER_ID"
echo ""

# ─── Step 2: Per-host triage (without individual escalation) ───
CHILD_IDS=()
export SKIP_ESCALATION=true

for i in "${!HOSTS[@]}"; do
  HOST="${HOSTS[$i]}"
  RULE="${RULES[$i]:-Unknown Alert}"
  SEV="${SEVS[$i]:-unknown}"

  echo "--- Step 2.$((i+1)): Triaging $HOST ---"
  TRIAGE_OUTPUT=$(./skills/infra-triage/infra-triage.sh "$HOST" "$RULE" "$SEV" 2>&1)
  echo "$TRIAGE_OUTPUT"

  # Extract child issue ID
  CHILD_ID=$(echo "$TRIAGE_OUTPUT" | grep -oP '$YT_PROJECT-\d+' | head -1)
  if [ -n "$CHILD_ID" ]; then
    CHILD_IDS+=("$CHILD_ID")
    echo "Child issue: $CHILD_ID"
  else
    echo "WARN: No issue ID extracted for $HOST"
  fi
  echo ""
done

unset SKIP_ESCALATION

# ─── Step 3: Link children to master via YT command API ───
echo "--- Step 3: Linking child issues to master ---"
for CHILD_ID in "${CHILD_IDS[@]}"; do
  echo "Linking $CHILD_ID as subtask of $MASTER_ID"
  python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
yt_url = '${YOUTRACK_URL}'
yt_token = '${YOUTRACK_TOKEN}'
data = json.dumps({'issues': [{'idReadable': '$CHILD_ID'}], 'query': 'subtask of $MASTER_ID'}).encode()
req = urllib.request.Request(yt_url + '/api/commands', data=data, headers={'Content-Type':'application/json', 'Authorization': 'Bearer ' + yt_token}, method='POST')
try:
    urllib.request.urlopen(req, context=ctx)
    print('  Linked OK')
except Exception as e:
    print(f'  WARN: Link failed: {e}')
" 2>/dev/null || echo "  WARN: Link command failed"
done
echo ""

# ─── Step 4: Correlation analysis ───
echo "--- Step 4: Analyzing correlation ---"
ANALYSIS=""

# Check if all hosts share a PVE hypervisor
PVE_HOSTS=()
for HOST in "${HOSTS[@]}"; do
  PVE_MATCH=$(grep -rl "hostname: $HOST" ${IAC_REPO}/pve/ 2>/dev/null | head -1 || echo "")
  if [ -n "$PVE_MATCH" ]; then
    PVE_HOST=$(echo "$PVE_MATCH" | sed 's|.*/pve/\([^/]*\)/.*|\1|')
    PVE_HOSTS+=("$PVE_HOST")
  else
    PVE_HOSTS+=("not-in-pve")
  fi
done

# Check common PVE host
UNIQUE_PVE=$(printf '%s\n' "${PVE_HOSTS[@]}" | sort -u)
UNIQUE_PVE_COUNT=$(printf '%s\n' "${PVE_HOSTS[@]}" | sort -u | wc -l)
if [ "$UNIQUE_PVE_COUNT" -eq 1 ] && [ "$(echo "$UNIQUE_PVE" | head -1)" != "not-in-pve" ]; then
  COMMON_PVE=$(echo "$UNIQUE_PVE" | head -1)
  ANALYSIS="$ANALYSIS\n**Common hypervisor: $COMMON_PVE** — ALL $HOST_COUNT hosts run on the same PVE node. Likely hypervisor-level issue (OOM, disk full, network, reboot)."
else
  ANALYSIS="$ANALYSIS\nPVE hosts: $(printf '%s=%s, ' "${HOSTS[@]}" "${PVE_HOSTS[@]}" | sed 's/, $//')"
fi

# Check common alert rule
UNIQUE_RULES=$(printf '%s\n' "${RULES[@]}" | sort -u)
UNIQUE_RULE_COUNT=$(printf '%s\n' "${RULES[@]}" | sort -u | wc -l)
if [ "$UNIQUE_RULE_COUNT" -eq 1 ]; then
  ANALYSIS="$ANALYSIS\n**Common alert rule: $(echo "$UNIQUE_RULES" | head -1)** — same failure mode across all hosts."
fi

# Check common severity
UNIQUE_SEVS=$(printf '%s\n' "${SEVS[@]}" | sort -u)
UNIQUE_SEV_COUNT=$(printf '%s\n' "${SEVS[@]}" | sort -u | wc -l)
if [ "$UNIQUE_SEV_COUNT" -eq 1 ]; then
  ANALYSIS="$ANALYSIS\nAll alerts severity: $(echo "$UNIQUE_SEVS" | head -1)"
fi

# Build child list for comment
CHILD_LIST=""
for i in "${!HOSTS[@]}"; do
  CID="${CHILD_IDS[$i]:-unknown}"
  CHILD_LIST="$CHILD_LIST\n- ${HOSTS[$i]}: $CID (${RULES[$i]:-?}, ${SEVS[$i]:-?})"
done

CORRELATION_COMMENT="Correlation Analysis ($HOST_COUNT hosts, burst at $BURST_TIME UTC):
$(echo -e "$ANALYSIS")

Child issues:
$(echo -e "$CHILD_LIST")

Recommended: Investigate shared root cause before addressing individual hosts."

echo "$CORRELATION_COMMENT"
./skills/yt-post-comment.sh "$MASTER_ID" "$CORRELATION_COMMENT" 2>&1 || echo "WARN: Failed to post correlation comment"
echo ""

# ─── Step 5: Escalate MASTER only to Claude Code ───
echo "--- Step 5: Escalating MASTER issue to Claude Code ---"
CHILD_ID_LIST=$(printf '%s, ' "${CHILD_IDS[@]}")
CHILD_ID_LIST=${CHILD_ID_LIST%, }
./skills/escalate-to-claude.sh "$MASTER_ID" "Correlated alert burst: $HOST_COUNT hosts affected ($HOST_LIST). Child issues: $CHILD_ID_LIST. Correlation analysis posted as YT comment." 2>&1 || echo "WARN: Escalation failed (continuing)"

echo ""
echo "=== CORRELATED TRIAGE COMPLETE: $MASTER_ID ($HOST_COUNT children) ==="
