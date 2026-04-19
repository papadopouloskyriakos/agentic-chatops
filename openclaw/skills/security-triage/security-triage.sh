#!/bin/bash
# Security Scan Finding Triage — automated investigation of scanner findings
# Usage: ./skills/security-triage/security-triage.sh <target_ip> "<finding_title>" <severity> [scanner] [category] [port] [issue_id]
#
# Tier 1 quick triage: NetBox lookup, baseline check, latest report context.
# Posts findings as YT comment, registers callback to n8n, outputs TRIAGE_JSON.
# Deep verification (nuclei/nmap/testssl re-scan) left to Tier 2 escalation.
#
# Scanner mapping (cross-site scan design):
#   nlsec01 (NL) → scans GR + VPS targets
#   grsec01 (GR) → scans NL + VPS targets

set -uo pipefail

TRIAGE_START=$(date +%s)

TARGET_IP="${1:?Usage: security-triage.sh <target_ip> '<finding_title>' <severity> [scanner] [category] [port] [issue_id]}"
FINDING_TITLE="${2:-Unknown Finding}"
SEVERITY="${3:-unknown}"
SCANNER="${4:-auto}"
CATEGORY="${5:-unknown}"
PORT="${6:-}"
ISSUE_ID="${7:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_STEP="init"
COMPLETED_STEPS=""

# ─── Hostname validation ───
validate_hostname() {
  local host="$1"
  # Allow IPs (for security-triage which takes IPs)
  if [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    return 0
  fi
  # Validate hostname format: site prefix (2+ lowercase letters) + digits + identifier
  if [[ ! "$host" =~ ^[a-z]{2,}[a-z0-9]*[0-9]{2}[a-z0-9]+$ ]]; then
    echo "WARNING: Hostname '$host' does not match expected format (e.g., nl-pve01, gr-fw01)"
    echo "Continuing anyway — but verify this is a valid host"
  fi
}

# ─── Error trap ───
error_handler() {
  local exit_code=$?
  echo ""
  echo "ERROR_CONTEXT:"
  echo "- Failed at: $CURRENT_STEP"
  echo "- Completed steps: ${COMPLETED_STEPS:-none}"
  echo "- Error: exit code $exit_code"
  echo "- Issue ID: ${ISSUE_ID:-not provided}"
  echo "- Target: $TARGET_IP, Finding: $FINDING_TITLE, Severity: $SEVERITY"
  echo "- Suggested next action: Check scanner SSH connectivity and retry"
  exit $exit_code
}
trap error_handler ERR

# Scanner VM access
NL_SCANNER_IP="10.0.181.X"
GR_SCANNER_IP="10.0.X.X"
SCANNER_USER="operator"
SSH_KEY="/home/app-user/.ssh/one_key"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -o LogLevel=ERROR"
SUDO_PASS="${SCANNER_SUDO_PASS:?SCANNER_SUDO_PASS env var not set — add to .env}"

# Auto-detect which scanner has data for this target
if [ "$SCANNER" = "auto" ]; then
  case "$TARGET_IP" in
    45.138.*|145.53.*)  SCANNER="grsec01"; SCANNER_IP="$GR_SCANNER_IP" ;;
    91.211.*)           SCANNER="nlsec01"; SCANNER_IP="$NL_SCANNER_IP" ;;
    185.44.*|185.125.*) SCANNER="nlsec01"; SCANNER_IP="$NL_SCANNER_IP" ;;
    *)                  SCANNER="nlsec01"; SCANNER_IP="$NL_SCANNER_IP" ;;
  esac
else
  case "$SCANNER" in
    nlsec01)  SCANNER_IP="$NL_SCANNER_IP" ;;
    grsec01)  SCANNER_IP="$GR_SCANNER_IP" ;;
    *)             SCANNER_IP="$NL_SCANNER_IP" ;;
  esac
fi

# Determine site for YT routing and load site config
case "$TARGET_IP" in
  45.138.*|145.53.*) TARGET_SITE="NL"; TRIAGE_SITE="nl" ;;
  91.211.*)          TARGET_SITE="GR"; TRIAGE_SITE="gr" ;;
  185.*)             TARGET_SITE="VPS"; TRIAGE_SITE="nl" ;;
  *)                 TARGET_SITE="unknown"; TRIAGE_SITE="nl" ;;
esac
export TRIAGE_SITE

# Load site configuration (YT_PROJECT, SECURITY_WEBHOOK, etc.)
if [ -f "$SCRIPT_DIR/site-config.sh" ]; then
  source "$SCRIPT_DIR/site-config.sh"
fi

echo "=== Security Finding Triage ==="
echo "Target: $TARGET_IP (site: $TARGET_SITE)"
echo "Finding: $FINDING_TITLE"
echo "Severity: $SEVERITY | Category: $CATEGORY${PORT:+ | Port: $PORT}"
echo "Scanner: $SCANNER ($SCANNER_IP)"
echo "Issue: ${ISSUE_ID:-not provided}"
echo ""

FINDINGS=""

# ─── Maintenance mode check ───
MAINTENANCE_ACTIVE=false
MAINT_FILE="/home/app-user/gateway.maintenance"
MAINT_ENDED_FILE="/home/app-user/gateway.maintenance-ended"

if [ -f "$MAINT_FILE" ]; then
  MAINTENANCE_ACTIVE=true
  MAINT_REASON=$(python3 -c "import json; print(json.load(open('$MAINT_FILE')).get('reason','unknown'))" 2>/dev/null || echo "unknown")
  echo ""
  echo "*** MAINTENANCE MODE ACTIVE ***"
  echo "Reason: $MAINT_REASON"
  echo "Security finding during maintenance — still investigating but confidence reduced."
  echo ""
elif [ -f "$MAINT_ENDED_FILE" ]; then
  ENDED_TS=$(cat "$MAINT_ENDED_FILE" 2>/dev/null || echo "0")
  NOW_TS=$(date +%s)
  ELAPSED=$(( NOW_TS - ENDED_TS ))
  if [ "$ELAPSED" -lt 900 ]; then
    COOLDOWN_MIN=$(( (900 - ELAPSED) / 60 ))
    echo ""
    echo "*** POST-MAINTENANCE COOLDOWN ($COOLDOWN_MIN min remaining) ***"
    echo ""
  fi
fi

# ─── Step 0: Check for existing open issues (dedup) ───
CURRENT_STEP="Step 0 (dedup check)"
echo "--- Step 0: Checking for existing security issues ---"
DEDUP_QUERY="${TARGET_IP} ${FINDING_TITLE}"
EXISTING_ISSUE=""
if [ -n "${YT_PROJECT:-}" ]; then
  EXISTING_ISSUE=$(curl -s -H "Authorization: Bearer ${YT_TOKEN:-}" \
    "${YT_URL:-https://youtrack.example.net}/api/issues?query=project:%20${YT_PROJECT}%20%23Unresolved%20summary:%20${TARGET_IP}&fields=idReadable,summary" 2>/dev/null | \
    python3 -c "import json,sys; issues=json.loads(sys.stdin.read()); print(issues[0]['idReadable'] if issues else '')" 2>/dev/null) || true
fi
if [ -n "$EXISTING_ISSUE" ]; then
  echo "Found existing issue: $EXISTING_ISSUE — will add comment instead of creating new"
else
  echo "No existing issue found for $TARGET_IP"
fi
COMPLETED_STEPS="Step 0 (dedup)"

# ─── Step 0.5: Query incident knowledge base (RAG — semantic search) ───
CURRENT_STEP="Step 0.5 (knowledge RAG)"
echo "--- Step 0.5: Querying incident knowledge base (semantic) ---"
KB_QUERY="${TARGET_IP} ${FINDING_TITLE} ${CATEGORY} security"
# Local semantic search (gateway.db synced by repo-sync cron, Ollama on gpu01 reachable directly)
KB_SEARCH="$SCRIPT_DIR/kb-semantic-search.py"
if [ -f "$KB_SEARCH" ] && [ -f "/home/node/.claude-data/gateway.db" ]; then
  PRIOR_KNOWLEDGE=$(GATEWAY_DB=/home/node/.claude-data/gateway.db python3 "$KB_SEARCH" search "${KB_QUERY//\'/\'}" --limit 3 --days 90 2>/dev/null) || true
else
  PRIOR_KNOWLEDGE=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
    -i ~/.ssh/one_key app-user@nl-claude01 \
    "python3 ~/gitlab/n8n/claude-gateway/scripts/kb-semantic-search.py search '${KB_QUERY//\'/\\\'}' --limit 3 --days 90" 2>/dev/null) || true
fi

PRIOR_NOTE=""
if [ -n "$PRIOR_KNOWLEDGE" ]; then
  PRIOR_NOTE="\n\n**Prior resolutions for similar security findings:**\n"
  while IFS='|' read -r pk_issue pk_host pk_alert pk_resolution pk_confidence pk_date pk_site pk_sim; do
    PRIOR_NOTE="${PRIOR_NOTE}- [${pk_date}] ${pk_issue}: ${pk_resolution} (confidence: ${pk_confidence}, similarity: ${pk_sim})\n"
  done <<< "$PRIOR_KNOWLEDGE"
  echo "Found $(echo "$PRIOR_KNOWLEDGE" | wc -l) prior resolution(s)"
else
  echo "No prior resolutions found"
fi
COMPLETED_STEPS="Step 0 (dedup), Step 0.5 (knowledge RAG)"

# ─── Step 1: NetBox CMDB Lookup ───
CURRENT_STEP="Step 1 (NetBox lookup)"
echo "--- Step 1: NetBox Lookup ---"
NETBOX_RESULT=""
if [ -f "$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" ]; then
  NETBOX_RESULT=$("$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" search "$TARGET_IP" 2>/dev/null || echo "No NetBox match for $TARGET_IP")
  echo "$NETBOX_RESULT" | head -15
  FINDINGS="$FINDINGS\nNetBox: $(echo "$NETBOX_RESULT" | head -5 | tr '\n' ' ')"
else
  echo "NetBox lookup not available"
  FINDINGS="$FINDINGS\nNetBox: not available"
fi
COMPLETED_STEPS="Step 1 (NetBox)"
echo ""

# ─── Step 2: Baseline Check ───
CURRENT_STEP="Step 2 (baseline check)"
echo "--- Step 2: Baseline Check ---"
IN_BASELINE=false

BASELINE_RAW=$(ssh $SSH_OPTS $SCANNER_USER@$SCANNER_IP "
  echo '$SUDO_PASS' | sudo -S sh -c '
    echo \"=PORTS=\"
    grep \"$TARGET_IP\" /opt/scans/baseline/ports.txt 2>/dev/null || echo \"(none)\"
    echo \"=NUCLEI=\"
    grep -i \"$TARGET_IP\" /opt/scans/baseline/nuclei.txt 2>/dev/null || echo \"(none)\"
    echo \"=TLS=\"
    grep -i \"$TARGET_IP\" /opt/scans/baseline/testssl-issues.txt 2>/dev/null || echo \"(none)\"
  '
" 2>&1) || true

BASELINE_PORTS=""
BASELINE_NUCLEI=""
BASELINE_TLS=""

if echo "$BASELINE_RAW" | grep -q "=PORTS="; then
  BASELINE_PORTS=$(echo "$BASELINE_RAW" | sed -n '/=PORTS=/,/=NUCLEI=/p' | grep -v "^=" | head -5)
  BASELINE_NUCLEI=$(echo "$BASELINE_RAW" | sed -n '/=NUCLEI=/,/=TLS=/p' | grep -v "^=" | head -5)
  BASELINE_TLS=$(echo "$BASELINE_RAW" | sed -n '/=TLS=/,$p' | grep -v "^=" | head -5)
  echo "Baseline ports: $BASELINE_PORTS"
  echo "Baseline nuclei: $BASELINE_NUCLEI"
  echo "Baseline TLS: $BASELINE_TLS"
else
  echo "Could not retrieve baseline (scanner unreachable?)"
  echo "$BASELINE_RAW" | tail -3
fi

case "$CATEGORY" in
  port)
    if echo "$BASELINE_PORTS" | grep -q "${PORT:-NOPORT}"; then
      IN_BASELINE=true
      echo "⚠️  Port $PORT was ALREADY in baseline — possible false positive"
    else
      echo "✅ Port $PORT is NEW (not in baseline)"
    fi
    ;;
  cve)
    if echo "$BASELINE_NUCLEI" | grep -qi "$FINDING_TITLE"; then
      IN_BASELINE=true
      echo "⚠️  $FINDING_TITLE was ALREADY in baseline nuclei findings"
    else
      echo "✅ $FINDING_TITLE is NEW (not in baseline)"
    fi
    ;;
  tls)
    echo "TLS finding — check baseline TLS issues above"
    ;;
esac
FINDINGS="$FINDINGS\nBaseline check: in_baseline=$IN_BASELINE"
COMPLETED_STEPS="Step 1 (NetBox), Step 2 (baseline)"
echo ""

# ─── Step 2b: ACL Exposure Check ───
CURRENT_STEP="Step 2b (ACL exposure)"
echo "--- Step 2b: ACL Exposure Check ---"
ACL_PROTECTED=false
ACL_NAME=""
EXPOSURE="unknown"
# Check baseline annotations for exposure context
if echo "$BASELINE_PORTS" | grep -qi "acl_protected"; then
  ACL_PROTECTED=true
  ACL_NAME=$(echo "$BASELINE_PORTS" | grep -oP 'ACL:\s*\K\S+' | head -1)
  EXPOSURE="acl_protected"
  echo "🔒 Port is ACL-protected (${ACL_NAME:-unknown ACL}) — scanner-visible only, NOT publicly exposed"
  FINDINGS="$FINDINGS\nACL exposure: acl_protected (${ACL_NAME}). Scanner sees this port because it is in the firewall whitelist. Not a public exposure."
elif echo "$BASELINE_PORTS" | grep -qi "public"; then
  EXPOSURE="public"
  echo "🌐 Port is publicly exposed — reachable from any internet IP"
  FINDINGS="$FINDINGS\nACL exposure: public (internet-facing)"
else
  echo "⚠️ Exposure unknown — baseline has no ACL annotation for this port"
  FINDINGS="$FINDINGS\nACL exposure: unknown (no annotation in baseline)"
fi
COMPLETED_STEPS="Step 1 (NetBox), Step 2 (baseline), Step 2b (ACL)"
echo ""

# ─── Step 3: Latest Scan Context ───
CURRENT_STEP="Step 3 (scan context)"
echo "--- Step 3: Latest Scan Report Context ---"

# Split SSH + local parsing to avoid triple-escaped python3 inside sudo
REPORT_CONTEXT=$(ssh $SSH_OPTS $SCANNER_USER@$SCANNER_IP "
  echo '$SUDO_PASS' | sudo -S sh -c '
    LATEST_DIR=\$(ls -td /opt/scans/weekly/*/ 2>/dev/null | head -1)
    if [ -n \"\$LATEST_DIR\" ]; then
      echo \"Scan dir: \$LATEST_DIR\"
      echo \"=NMAP_CONTEXT=\"
      grep -B2 -A5 \"$TARGET_IP\" \"\${LATEST_DIR}nmap.txt\" 2>/dev/null | head -30 || echo \"(no nmap data)\"
      echo \"=FINDINGS_JSON=\"
      cat \"\${LATEST_DIR}findings.json\" 2>/dev/null || echo \"{}\"
    else
      echo \"No scan directories found\"
    fi
  '
" 2>&1) || true

NMAP_CTX=""
FINDINGS_CTX=""
if echo "$REPORT_CONTEXT" | grep -q "=NMAP_CONTEXT="; then
  NMAP_CTX=$(echo "$REPORT_CONTEXT" | sed -n '/=NMAP_CONTEXT=/,/=FINDINGS_JSON=/p' | grep -v "^=" | head -20)
  # Parse findings JSON locally (no escaping issues)
  FINDINGS_CTX=$(echo "$REPORT_CONTEXT" | sed -n '/=FINDINGS_JSON=/,$p' | grep -v "^=" | python3 -c "
import json, sys
try:
  data = json.load(sys.stdin)
  for f in (data if isinstance(data, list) else []):
    sev = f.get('severity', '?').upper()
    title = f.get('title', '?')
    detail = f.get('detail', '?')
    print(f'{sev}: {title} — {detail}')
except:
  print('(no findings.json)')
" 2>/dev/null) || true
  echo "nmap context:"
  echo "$NMAP_CTX"
  echo ""
  echo "All findings this scan:"
  echo "$FINDINGS_CTX"
else
  echo "Could not retrieve scan context (scanner unreachable or no scan data)"
  echo "$REPORT_CONTEXT" | tail -3
fi
FINDINGS="$FINDINGS\nnmap: $(echo "$NMAP_CTX" | head -5 | tr '\n' ' ')"
FINDINGS="$FINDINGS\nFindings: $(echo "$FINDINGS_CTX" | head -5 | tr '\n' ' ')"
COMPLETED_STEPS="Step 1 (NetBox), Step 2 (baseline), Step 3 (scan context)"
echo ""

# ─── Step 4: Quick Service Check ───
SVC_CHECK=""
if [ -n "$PORT" ] && [ "$CATEGORY" = "port" ]; then
  CURRENT_STEP="Step 4 (service check)"
  echo "--- Step 4: Quick Service Identification (port $PORT) ---"
  SVC_CHECK=$(ssh $SSH_OPTS $SCANNER_USER@$SCANNER_IP "
    echo '$SUDO_PASS' | sudo -S timeout 30 nmap -sV -p $PORT $TARGET_IP 2>/dev/null | grep -E 'open|closed|filtered' | head -5
  " 2>&1) || true
  echo "${SVC_CHECK:-Service check timed out or failed}"
  FINDINGS="$FINDINGS\nService check (port $PORT): ${SVC_CHECK:-timeout}"
  COMPLETED_STEPS="$COMPLETED_STEPS, Step 4 (service check)"
  echo ""
fi

# ─── Step 4b: CrowdSec Threat Intelligence ───
CURRENT_STEP="Step 4b (CrowdSec enrichment)"
echo "--- Step 4b: CrowdSec Active Threats for $TARGET_IP ---"

# Query CrowdSec on hosts that protect this target
# VPS hosts protect themselves, DMZ hosts protect the ASA-facing services
CS_ENRICHMENT=""
for cs_host_info in "operator@198.51.100.X:chzrh01vps01" "operator@198.51.100.X:notrf01vps01" "operator@nl-dmz01:nl-dmz01" "operator@gr-dmz01:gr-dmz01"; do
  cs_target="${cs_host_info%%:*}"
  cs_label="${cs_host_info##*:}"
  CS_RESULT=$(ssh $SSH_OPTS $cs_target "
    echo '$SUDO_PASS' | sudo -S sh -c '
      # Recent alerts related to this IP or port
      cscli alerts list --scope ip --value $TARGET_IP --since 7d -o json 2>/dev/null | python3 -c \"
import json,sys
try:
  alerts=json.load(sys.stdin)
  if alerts:
    print(str(len(alerts)) + \\\" alerts for $TARGET_IP in 7d\\\")
    for a in alerts[:3]:
      print(\\\"  \\\" + a.get(\\\"scenario\\\",\\\"?\\\") + \\\" (\\\" + str(a.get(\\\"events_count\\\",0)) + \\\" events)\\\")
  else:
    print(\\\"No alerts for $TARGET_IP\\\")
except: print(\\\"(parse error)\\\")
\" 2>/dev/null
      # Active decisions (bans) count
      echo \"Active bans: \$(cscli decisions list -o raw 2>/dev/null | tail -n+2 | wc -l)\"
    '
  " 2>&1 | grep -v "^Warning\|sudo.*password" | head -8) || true
  if [ -n "$CS_RESULT" ] && ! echo "$CS_RESULT" | grep -q "Connection refused\|Connection timed out\|Permission denied"; then
    echo "$cs_label: $CS_RESULT"
    CS_ENRICHMENT="$CS_ENRICHMENT\n$cs_label: $(echo "$CS_RESULT" | head -3 | tr '\n' ' ')"
  fi
done
FINDINGS="$FINDINGS\nCrowdSec: $(echo -e "$CS_ENRICHMENT" | head -5 | tr '\n' ' ')"
COMPLETED_STEPS="$COMPLETED_STEPS, Step 4b (CrowdSec)"
echo ""

# ─── Step 4c: CrowdSec CTI API (optional, free tier: 30 queries/week) ───
CURRENT_STEP="Step 4c (CrowdSec CTI)"
CTI_DATA=""
if [ -n "${CROWDSEC_CTI_KEY:-}" ] && { [ "$SEVERITY" = "critical" ] || [ "$SEVERITY" = "high" ]; }; then
  echo "--- Step 4c: CrowdSec CTI Lookup for $TARGET_IP ---"
  CTI_RESP=$(curl -sf --max-time 10 \
    -H "x-api-key: $CROWDSEC_CTI_KEY" \
    "https://cti.api.crowdsec.net/v2/smoke/$TARGET_IP" 2>/dev/null || echo "")
  if [ -n "$CTI_RESP" ] && echo "$CTI_RESP" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
    CTI_DATA=$(echo "$CTI_RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin)
rep = d.get('reputation','unknown')
bns = d.get('background_noise_score','?')
behaviors = ', '.join([b.get('name','?') for b in d.get('behaviors',[])][:5])
confidence = d.get('confidence','?')
mitre = ', '.join([t.get('label','?') + ' (' + t.get('name','?') + ')' for t in d.get('mitre_techniques',[])][:5]) or 'none'
print(f'Reputation: {rep} | Noise: {bns}/10 | Confidence: {confidence} | Behaviors: {behaviors} | MITRE: {mitre}')
" 2>/dev/null)
    CTI_MITRE=$(echo "$CTI_RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin)
mitre = [t.get('name','') for t in d.get('mitre_techniques',[])][:5]
print(','.join(mitre) if mitre else '')
" 2>/dev/null || echo "")
    echo "$CTI_DATA"
    # Baseline feedback: if CTI says safe/known with low noise, suggest baseline addition
    BASELINE_SUGGESTION="false"
    CTI_REPUTATION=$(echo "$CTI_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('reputation','unknown'))" 2>/dev/null || echo "unknown")
    CTI_NOISE=$(echo "$CTI_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('background_noise_score',99))" 2>/dev/null || echo "99")
    if [ "$CTI_REPUTATION" = "safe" ] || [ "$CTI_REPUTATION" = "known" ]; then
      if [ "${CTI_NOISE:-99}" -le 2 ] 2>/dev/null; then
        BASELINE_SUGGESTION="true"
        SUGGESTIONS_FILE="/app/cubeos/claude-context/baseline-suggestions.json"
        echo "CTI confirms $TARGET_IP is $CTI_REPUTATION (noise $CTI_NOISE/10) — adding to baseline suggestions"
        python3 -c "
import json, os
from datetime import datetime
f = '$SUGGESTIONS_FILE'
try:
    existing = json.load(open(f)) if os.path.exists(f) else []
except: existing = []
existing.append({
    'target': '$TARGET_IP',
    'finding': '$(echo "$FINDING_TITLE" | sed "s/'/\\\\'/g")',
    'ctiReputation': '$CTI_REPUTATION',
    'ctiNoise': $CTI_NOISE,
    'scanner': '$SCANNER',
    'suggestedAt': datetime.utcnow().isoformat() + 'Z'
})
with open(f, 'w') as out:
    json.dump(existing, out, indent=2)
" 2>/dev/null || echo "WARN: Failed to write baseline suggestion"
      fi
    fi
  else
    echo "CTI lookup failed or empty response (skipping)"
  fi
  FINDINGS="$FINDINGS\nCrowdSec CTI: ${CTI_DATA:-lookup failed}"
  COMPLETED_STEPS="$COMPLETED_STEPS, Step 4c (CTI)"
else
  echo "--- Step 4c: CrowdSec CTI [SKIPPED — key not set or severity < high] ---"
fi
echo ""

# ─── Step 4d: GreyNoise Community lookup (free, no auth) ───
CURRENT_STEP="Step 4d (GreyNoise)"
GN_DATA=""
echo "--- Step 4d: GreyNoise Community for $TARGET_IP ---"
GN_RESP=$(curl -sf --max-time 10 "https://api.greynoise.io/v3/community/$TARGET_IP" 2>/dev/null || echo "")
if [ -n "$GN_RESP" ] && echo "$GN_RESP" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
  GN_DATA=$(echo "$GN_RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin)
noise = d.get('noise', False)
riot = d.get('riot', False)
classification = d.get('classification', 'unknown')
name = d.get('name', '')
msg = 'Classification: ' + classification
if noise: msg += ' | NOISE (mass scanner)'
if riot: msg += ' | RIOT (known benign: ' + name + ')'
if not noise and not riot: msg += ' | Targeted (not mass scanning)'
print(msg)
" 2>/dev/null)
  echo "$GN_DATA"
  MALICIOUS_SOURCES=${MALICIOUS_SOURCES:-0}
  if echo "$GN_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if d.get('classification')=='malicious' else 1)" 2>/dev/null; then
    MALICIOUS_SOURCES=$((MALICIOUS_SOURCES + 1))
  fi
else
  echo "GreyNoise lookup failed or empty (skipping)"
fi
FINDINGS="$FINDINGS\nGreyNoise: ${GN_DATA:-unavailable}"
COMPLETED_STEPS="$COMPLETED_STEPS, Step 4d (GreyNoise)"
echo ""

# ─── Step 4e: AbuseIPDB lookup (optional, gated behind key) ───
CURRENT_STEP="Step 4e (AbuseIPDB)"
ABUSE_DATA=""
if [ -n "${ABUSEIPDB_KEY:-}" ]; then
  echo "--- Step 4e: AbuseIPDB for $TARGET_IP ---"
  ABUSE_RESP=$(curl -sf --max-time 10 \
    -H "Key: $ABUSEIPDB_KEY" -H "Accept: application/json" \
    "https://api.abuseipdb.com/api/v2/check?ipAddress=$TARGET_IP&maxAgeInDays=90" 2>/dev/null || echo "")
  if [ -n "$ABUSE_RESP" ] && echo "$ABUSE_RESP" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
    ABUSE_DATA=$(echo "$ABUSE_RESP" | python3 -c "
import json,sys
d=json.load(sys.stdin).get('data',{})
score = d.get('abuseConfidenceScore', 0)
reports = d.get('totalReports', 0)
last = d.get('lastReportedAt', 'never')
country = d.get('countryCode', '?')
print(f'Abuse score: {score}% | Reports: {reports} | Last: {last} | Country: {country}')
" 2>/dev/null)
    echo "$ABUSE_DATA"
    if echo "$ABUSE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin).get('data',{}); exit(0 if d.get('abuseConfidenceScore',0) >= 50 else 1)" 2>/dev/null; then
      MALICIOUS_SOURCES=$((${MALICIOUS_SOURCES:-0} + 1))
    fi
  else
    echo "AbuseIPDB lookup failed (skipping)"
  fi
  FINDINGS="$FINDINGS\nAbuseIPDB: ${ABUSE_DATA:-unavailable}"
  COMPLETED_STEPS="$COMPLETED_STEPS, Step 4e (AbuseIPDB)"
else
  echo "--- Step 4e: AbuseIPDB [SKIPPED — key not set] ---"
fi
echo ""

# ─── Step 4f: Retroactive log hunt (if IP confirmed malicious by 2+ sources) ───
CURRENT_STEP="Step 4f (retro hunt)"
if [ "${MALICIOUS_SOURCES:-0}" -ge 2 ]; then
  echo "--- Step 4f: Retroactive log hunt for $TARGET_IP ($MALICIOUS_SOURCES sources confirm malicious) ---"
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  if type fetch_syslog >/dev/null 2>&1; then
    RETRO_HITS=$(fetch_syslog "" 200 "$TARGET_IP" 2>/dev/null | head -10)
    if [ -n "$RETRO_HITS" ]; then
      echo "Historical activity found:"
      echo "$RETRO_HITS"
      FINDINGS="$FINDINGS\nRetro hunt: $(echo "$RETRO_HITS" | wc -l) log entries for $TARGET_IP"
    else
      echo "No historical log entries for $TARGET_IP"
    fi
  else
    echo "fetch_syslog not available (skipping)"
  fi
  COMPLETED_STEPS="$COMPLETED_STEPS, Step 4f (retro hunt)"
else
  echo "--- Step 4f: Retroactive log hunt [SKIPPED — <2 malicious sources] ---"
fi
echo ""

# ─── Step 4g: EPSS scoring for CVE findings (free, no auth) ───
CURRENT_STEP="Step 4g (EPSS)"
EPSS_SCORE=""
EPSS_PERCENTILE=""
if echo "$FINDING_TITLE" | grep -qiE "^CVE-"; then
  echo "--- Step 4g: EPSS Score for $FINDING_TITLE ---"
  EPSS_RESP=$(curl -sf --max-time 10 "https://api.first.org/data/v1/epss?cve=$FINDING_TITLE" 2>/dev/null || echo "")
  if [ -n "$EPSS_RESP" ]; then
    EPSS_SCORE=$(echo "$EPSS_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0]['epss'])" 2>/dev/null || echo "")
    EPSS_PERCENTILE=$(echo "$EPSS_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data'][0]['percentile'])" 2>/dev/null || echo "")
    echo "EPSS: $EPSS_SCORE (percentile: $EPSS_PERCENTILE)"
  else
    echo "EPSS lookup failed (skipping)"
  fi
  FINDINGS="$FINDINGS\nEPSS: ${EPSS_SCORE:-N/A} (percentile: ${EPSS_PERCENTILE:-N/A})"
  COMPLETED_STEPS="$COMPLETED_STEPS, Step 4g (EPSS)"
else
  echo "--- Step 4g: EPSS [SKIPPED — finding is not a CVE] ---"
fi
echo ""

# ─── Step 5: Post findings to YouTrack ───
CURRENT_STEP="Step 5 (YT comment)"
if [ -n "$ISSUE_ID" ] && [ -f "$SCRIPT_DIR/yt-post-comment.sh" ]; then
  echo "--- Step 5: Posting findings to YouTrack ($ISSUE_ID) ---"
  COMMENT="Security Scan Triage Results:
Target: $TARGET_IP ($TARGET_SITE)
Finding: $FINDING_TITLE ($SEVERITY)
Category: $CATEGORY${PORT:+ | Port: $PORT}
Scanner: $SCANNER
In baseline: $IN_BASELINE

$(echo -e "$FINDINGS")

$(echo -e "$PRIOR_NOTE")

Recommended action: $([ "$IN_BASELINE" = true ] && echo "Likely false positive — verify baseline is current." || echo "New finding — investigate service and apply patch/mitigation.")"

  "$SCRIPT_DIR/yt-post-comment.sh" "$ISSUE_ID" "$COMMENT" 2>&1 || echo "WARN: Failed to post YT comment (continuing)"
  COMPLETED_STEPS="$COMPLETED_STEPS, Step 5 (YT comment)"
else
  echo "--- Step 5: Skipping YT comment (no issue ID provided) ---"
fi
echo ""

# ─── Step 6: Register callback to n8n ───
CURRENT_STEP="Step 6 (register callback)"
if [ -n "$ISSUE_ID" ] && [ -n "${SECURITY_WEBHOOK:-}" ]; then
  echo "--- Step 6: Registering issue with n8n ---"
  curl -s -X POST "$SECURITY_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "{\"action\":\"register\",\"target\":\"$TARGET_IP\",\"issueId\":\"$ISSUE_ID\",\"inBaseline\":$( [ "$IN_BASELINE" = true ] && echo "true" || echo "false"),\"finding\":\"$(echo "$FINDING_TITLE" | sed 's/"/\\"/g')\",\"port\":\"${PORT:-}\",\"scanner\":\"$SCANNER\",\"severity\":\"$SEVERITY\"}" \
    --max-time 10 2>&1 || echo "WARN: Register callback failed (continuing)"
  COMPLETED_STEPS="$COMPLETED_STEPS, Step 6 (register)"
else
  echo "--- Step 6: Skipping register (no issue ID or webhook URL) ---"
fi
echo ""

# ─── Summary ───
echo "=== Triage Summary ==="
echo "Target: $TARGET_IP ($TARGET_SITE)"
echo "Finding: $FINDING_TITLE ($SEVERITY)"
echo "Scanner: $SCANNER"
echo "In baseline: $IN_BASELINE"
echo "Issue: ${ISSUE_ID:-not provided}"
echo ""
echo "For deep verification (nuclei re-scan, full nmap, testssl), escalate to Claude Code."
echo "Claude Code can SSH to $SCANNER ($SCANNER_IP) and run targeted scans."
echo ""
echo "Add your CONFIDENCE score based on the above findings."

# ─── TRIAGE_JSON output ───
TRIAGE_DURATION=$(($(date +%s) - TRIAGE_START))
echo ""
echo "TRIAGE_JSON:$(python3 -c "
import json
print(json.dumps({
    'issueId': '${ISSUE_ID:-}',
    'target': '$TARGET_IP',
    'targetSite': '$TARGET_SITE',
    'findingTitle': '$(echo "$FINDING_TITLE" | sed "s/'/\\\\'/g")',
    'severity': '$SEVERITY',
    'category': '$CATEGORY',
    'port': '${PORT:-}',
    'scanner': '$SCANNER',
    'inBaseline': $( [ "$IN_BASELINE" = true ] && echo "true" || echo "false" ),
    'ctiData': '$(echo "${CTI_DATA:-}" | sed "s/'/\\\\'/g")',
    'baselineSuggestion': $( [ "${BASELINE_SUGGESTION:-false}" = "true" ] && echo "true" || echo "false" ),
    'mitreAttack': '${CTI_MITRE:-}',
    'greynoise': '$(echo "${GN_DATA:-}" | sed "s/'/\\\\'/g")',
    'abuseipdb': '$(echo "${ABUSE_DATA:-}" | sed "s/'/\\\\'/g")',
    'epssScore': '${EPSS_SCORE:-}',
    'epssPercentile': '${EPSS_PERCENTILE:-}',
    'maliciousSources': ${MALICIOUS_SOURCES:-0},
    'triageDuration': $TRIAGE_DURATION,
}))" 2>/dev/null || echo '{"target":"'$TARGET_IP'","error":"json_failed"}')"

# ─── Evidence file ───
EVIDENCE_DIR="/app/cubeos/claude-context/evidence"
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
  -i "$SSH_KEY" app-user@nl-claude01 \
  "mkdir -p '$EVIDENCE_DIR' && python3 -c \"
import json
evidence = {
    'timestamp': '$(date -u +%FT%TZ)',
    'target': '$TARGET_IP',
    'targetSite': '$TARGET_SITE',
    'issueId': '${ISSUE_ID:-}',
    'finding': '$(echo "$FINDING_TITLE" | sed "s/'/\\\\'/g")',
    'severity': '$SEVERITY',
    'category': '$CATEGORY',
    'scanner': '$SCANNER',
    'inBaseline': $( [ "$IN_BASELINE" = true ] && echo "True" || echo "False" ),
    'triageDuration': $TRIAGE_DURATION,
    'completedSteps': '${COMPLETED_STEPS}',
    'sources': {
        'netbox': True, 'baseline': True, 'scanContext': True,
        'crowdsecLocal': True,
        'crowdsecCTI': $( [ -n '${CTI_DATA:-}' ] && echo 'True' || echo 'False' ),
        'greynoise': $( [ -n '${GN_DATA:-}' ] && echo 'True' || echo 'False' ),
        'abuseipdb': $( [ -n '${ABUSE_DATA:-}' ] && echo 'True' || echo 'False' ),
        'epss': $( [ -n '${EPSS_SCORE:-}' ] && echo 'True' || echo 'False' )
    },
    'maliciousSources': ${MALICIOUS_SOURCES:-0}
}
epath = '$EVIDENCE_DIR/$(date -u +%F)-${TARGET_IP}-${ISSUE_ID:-unknown}.json'
with open(epath, 'w') as f:
    json.dump(evidence, f, indent=2)
import hashlib
sha = hashlib.sha256(open(epath,'rb').read()).hexdigest()
evidence['sha256'] = sha
with open(epath, 'w') as f:
    json.dump(evidence, f, indent=2)
print(f'Evidence: {epath} (SHA-256: {sha})')
\"" 2>/dev/null || echo "WARN: Failed to write evidence file"

# ─── Triage log ───
TRIAGE_LOG="/app/cubeos/claude-context/triage.log"
OUTCOME=$([ "$IN_BASELINE" = true ] && echo "false_positive" || echo "new_finding")
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
  -i "$SSH_KEY" app-user@nl-claude01 \
  "echo '$(date -u +%FT%TZ)|${TARGET_IP}|${FINDING_TITLE}|${TRIAGE_SITE}|${OUTCOME}|0|${TRIAGE_DURATION}|${ISSUE_ID:-none}' >> '$TRIAGE_LOG'" 2>/dev/null || true
