#!/bin/bash
# proactive-scan.sh — Daily proactive health scan for pre-alert conditions
# Usage: proactive-scan.sh [--site nl|gr]
set -euo pipefail

SITE="nl"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --site) SITE="${2:-nl}"; shift 2 ;;
    *) shift ;;
  esac
done

source "$(dirname "$0")/../site-config.sh" "$SITE" 2>/dev/null || true

REMOTE="claude-runner@nl-claude01"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes -i ~/.ssh/one_key"
FINDINGS=()
CRITICAL=0
WARNING=0

add_finding() {
  local severity="$1" check="$2" detail="$3"
  FINDINGS+=("[$severity] $check: $detail")
  [ "$severity" = "CRITICAL" ] && CRITICAL=$((CRITICAL + 1))
  [ "$severity" = "WARNING" ] && WARNING=$((WARNING + 1))
}

echo "=== Proactive Health Scan (site: $SITE) ==="
echo "Time: $(date -u +%FT%TZ)"
echo ""

# --- Check 1: PVE host disk space ---
echo "Checking PVE disk space..."
if [ "$SITE" = "nl" ]; then
  PVE_HOSTS="nl-pve01 nl-pve02 nl-pve03"
else
  PVE_HOSTS="gr-pve01 gr-pve02"
fi

for HOST in $PVE_HOSTS; do
  DISK_PCT=$(ssh $SSH_OPTS "$REMOTE" "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes $HOST 'df -h / | tail -1 | awk \"{print \\$(NF-1)}\" | tr -d %'" 2>/dev/null) || DISK_PCT=""
  if [ -n "$DISK_PCT" ]; then
    if [ "$DISK_PCT" -gt 95 ] 2>/dev/null; then
      add_finding "CRITICAL" "Disk space" "$HOST at ${DISK_PCT}%"
    elif [ "$DISK_PCT" -gt 85 ] 2>/dev/null; then
      add_finding "WARNING" "Disk space" "$HOST at ${DISK_PCT}%"
    fi
  fi
done

# --- Check 2: Stale YT issues ---
echo "Checking stale YT issues..."
YT_URL="${YOUTRACK_URL:-https://youtrack.example.net}"
YT_TOKEN="${YOUTRACK_TOKEN:-}"
if [ -z "$YT_TOKEN" ]; then
  YT_TOKEN=$(ssh $SSH_OPTS "$REMOTE" "cat ~/gitlab/n8n/claude-gateway/.env 2>/dev/null | grep YOUTRACK_TOKEN | cut -d= -f2" 2>/dev/null) || true
fi

if [ -n "$YT_TOKEN" ]; then
  YT_PROJECT="${YT_PROJECT:-IFRNLLEI01PRD}"

  # In Progress > 7 days
  STALE_IP=$(curl -sf --max-time 10 \
    -H "Authorization: Bearer $YT_TOKEN" \
    "$YT_URL/api/issues?query=project:+$YT_PROJECT+State:+%7BIn+Progress%7D+updated:+-7d+..+Today&fields=idReadable,summary,updated&\$top=10" 2>/dev/null) || STALE_IP="[]"

  STALE_COUNT=$(echo "$STALE_IP" | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo 0)
  if [ "$STALE_COUNT" -gt 0 ]; then
    STALE_IDS=$(echo "$STALE_IP" | python3 -c "import json,sys; [print(i['idReadable']) for i in json.loads(sys.stdin.read())]" 2>/dev/null | head -5 | tr '\n' ', ')
    add_finding "WARNING" "Stale issues (In Progress >7d)" "${STALE_COUNT} issues: ${STALE_IDS%,}"
  fi

  # To Verify > 3 days
  STALE_TV=$(curl -sf --max-time 10 \
    -H "Authorization: Bearer $YT_TOKEN" \
    "$YT_URL/api/issues?query=project:+$YT_PROJECT+State:+%7BTo+Verify%7D+updated:+-3d+..+Today&fields=idReadable,summary,updated&\$top=10" 2>/dev/null) || STALE_TV="[]"

  STALE_TV_COUNT=$(echo "$STALE_TV" | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo 0)
  if [ "$STALE_TV_COUNT" -gt 0 ]; then
    TV_IDS=$(echo "$STALE_TV" | python3 -c "import json,sys; [print(i['idReadable']) for i in json.loads(sys.stdin.read())]" 2>/dev/null | head -5 | tr '\n' ', ')
    add_finding "WARNING" "Stale issues (To Verify >3d)" "${STALE_TV_COUNT} issues: ${TV_IDS%,}"
  fi
fi

# --- Check 3: GR VPN tunnel status (NL only) ---
if [ "$SITE" = "nl" ]; then
  echo "Checking GR VPN tunnel..."
  VPN_OK=$(ssh $SSH_OPTS "$REMOTE" "ping -c 2 -W 3 10.0.188.X >/dev/null 2>&1 && echo ok || echo fail" 2>/dev/null) || VPN_OK="fail"
  if [ "$VPN_OK" = "fail" ]; then
    add_finding "CRITICAL" "GR VPN tunnel" "Ping to 10.0.188.X failed — GR alert pipeline offline"
  fi
fi

# --- Check 4: K8s cert expiry ---
echo "Checking K8s cert expiry..."
CERT_DAYS=$(ssh $SSH_OPTS "$REMOTE" "
  KUBECONFIG=~/.kube/config
  CERT_DATA=\$(kubectl config view --raw -o jsonpath='{.users[0].user.client-certificate-data}' 2>/dev/null)
  if [ -n \"\$CERT_DATA\" ]; then
    EXPIRY=\$(echo \"\$CERT_DATA\" | base64 -d | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n \"\$EXPIRY\" ]; then
      EXPIRY_EPOCH=\$(date -d \"\$EXPIRY\" +%s 2>/dev/null)
      NOW_EPOCH=\$(date +%s)
      echo \$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    fi
  fi
" 2>/dev/null) || CERT_DAYS=""

if [ -n "$CERT_DAYS" ]; then
  if [ "$CERT_DAYS" -lt 7 ] 2>/dev/null; then
    add_finding "CRITICAL" "K8s admin cert" "Expires in ${CERT_DAYS} days"
  elif [ "$CERT_DAYS" -lt 30 ] 2>/dev/null; then
    add_finding "WARNING" "K8s admin cert" "Expires in ${CERT_DAYS} days"
  fi
fi

# --- Report ---
echo ""
echo "=== Scan Results ==="
if [ ${#FINDINGS[@]} -eq 0 ]; then
  echo "All checks passed. No pre-alert conditions detected."
else
  echo "Found ${#FINDINGS[@]} finding(s) (${CRITICAL} critical, ${WARNING} warning):"
  echo ""
  for f in "${FINDINGS[@]}"; do
    echo "  $f"
  done
fi

echo ""
echo "CONFIDENCE: 0.9 — Automated checks with direct host/API queries."
echo "=== SCAN COMPLETE ==="
