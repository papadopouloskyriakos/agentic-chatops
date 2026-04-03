#!/bin/bash
# Kubernetes Alert Triage — automated L1 + L2 for Prometheus alerts
# Usage: ./skills/k8s-triage/k8s-triage.sh "<alertname>" "<severity>" "<namespace>" "<summary>" "<node>" "<pod>" [--site nl|gr]
# Creates YT issue (or reuses existing), investigates via kubectl, posts findings, escalates.
#
# Env vars:
#   FORCE_ESCALATE=true  — escalate regardless of severity (set by n8n for flapping alerts)
#   EXISTING_ISSUE=ID    — reuse this issue instead of creating new
#   TRIAGE_SITE=nl|gr    — site override (alternative to --site flag)

set -uo pipefail

ALERTNAME="${1:?Usage: k8s-triage.sh <alertname> <severity> <namespace> <summary> [node] [pod] [--site nl|gr]}"
SEVERITY="${2:-unknown}"
NAMESPACE="${3:-cluster-wide}"
SUMMARY="${4:-$ALERTNAME}"
NODE="${5:-}"
POD="${6:-}"

# Parse --site flag from remaining args
shift 6 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    --site) TRIAGE_SITE="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Auto-detect site from node name if not explicitly set
if [ -z "${TRIAGE_SITE:-}" ]; then
  if echo "$NODE" | grep -qi "^grskg"; then
    TRIAGE_SITE="gr"
  else
    TRIAGE_SITE="${TRIAGE_SITE:-nl}"
  fi
fi
export TRIAGE_SITE

# ─── Hostname validation ───
validate_hostname() {
  local host="$1"
  # Allow IPs (for scripts that take IPs)
  if [[ "$host" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    return 0
  fi
  # Validate hostname format: site prefix (2+ lowercase letters) + digits + identifier
  if [[ ! "$host" =~ ^[a-z]{2,}[a-z0-9]*[0-9]{2}[a-z0-9]+$ ]]; then
    echo "WARNING: Hostname '$host' does not match expected format (e.g., nl-pve01, gr-fw01)"
    echo "Continuing anyway — but verify this is a valid host"
  fi
}
# Validate node hostname if provided (alertname-based triage may not have one)
if [ -n "$NODE" ]; then
  validate_hostname "$NODE"
fi

# Load site configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SCRIPT_DIR/site-config.sh"

# --- Hostname resolution: convert IP to FQDN ---
if [ -n "$NODE" ] && echo "$NODE" | grep -qP '^\d+\.\d+\.\d+\.\d+$'; then
  RESOLVED_HOSTNAME=""
  # Method 1: Extract from pod name (kube-apiserver-nlk8s-ctrl01 → nlk8s-ctrl01)
  if [ -n "$POD" ]; then
    POD_HOST=$(echo "$POD" | sed -E 's/^(kube-apiserver|kube-controller-manager|kube-scheduler|etcd)-//')
    if [ "$POD_HOST" != "$POD" ] && echo "$POD_HOST" | grep -qE '^[a-z]'; then
      RESOLVED_HOSTNAME="$POD_HOST"
    fi
  fi
  # Method 2: DNS reverse lookup
  if [ -z "$RESOLVED_HOSTNAME" ]; then
    DNS_RESULT=$(dig -x "$NODE" +short 2>/dev/null | head -1 | sed 's/\.$//')
    [ -n "$DNS_RESULT" ] && [ "$DNS_RESULT" != "$NODE" ] && RESOLVED_HOSTNAME="$DNS_RESULT"
  fi
  # Method 3: NetBox IP lookup
  if [ -z "$RESOLVED_HOSTNAME" ] && [ -n "${NETBOX_TOKEN:-}" ]; then
    NB_RESULT=$(curl -sk -H "Authorization: Token $NETBOX_TOKEN" \
      "${NETBOX_URL}/api/ipam/ip-addresses/?address=$NODE" 2>/dev/null | \
      python3 -c "import json,sys; d=json.load(sys.stdin); r=d.get('results',[]); print(r[0].get('dns_name','') if r else '')" 2>/dev/null)
    [ -n "$NB_RESULT" ] && RESOLVED_HOSTNAME="$NB_RESULT"
  fi
  # Apply resolution or keep original
  if [ -n "$RESOLVED_HOSTNAME" ]; then
    echo "Resolved $NODE -> $RESOLVED_HOSTNAME"
    NODE="$RESOLVED_HOSTNAME"
  fi
fi

# Error propagation: track progress for structured error reporting
CURRENT_STEP="init"
COMPLETED_STEPS=""
ISSUE_ID=""

error_handler() {
  local exit_code=$?
  echo ""
  echo "ERROR_CONTEXT:"
  echo "- Failed at: $CURRENT_STEP"
  echo "- Completed steps: ${COMPLETED_STEPS:-none}"
  echo "- Error: exit code $exit_code"
  echo "- Issue ID: ${ISSUE_ID:-not created}"
  echo "- Alert: $ALERTNAME ($SEVERITY) in $NAMESPACE"
  echo "- Suggested next action: Review error above, check if cluster/node is reachable"

  # Critical alerts MUST escalate even if investigation failed — don't silently swallow them
  if [ "$SEVERITY" = "critical" ] || [ "${FORCE_ESCALATE:-}" = "true" ]; then
    echo ""
    echo "--- FAILSAFE: Critical alert with failed investigation — escalating to Tier 2 ---"
    ESCALATION_MSG="K8s triage FAILED at $CURRENT_STEP (exit $exit_code). Alert: $ALERTNAME ($SEVERITY) in $NAMESPACE. Issue: ${ISSUE_ID:-not created}. Investigation incomplete — needs manual Tier 2 review."
    ./skills/escalate-to-claude.sh "${ISSUE_ID:-UNKNOWN}" "$ESCALATION_MSG" 2>&1 || echo "WARN: Failsafe escalation also failed"
  fi
  exit $exit_code
}
trap error_handler ERR

# Load credentials
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace; do [ -r "$d/.env" ] && . "$d/.env" && break; done

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
  echo "K8s alert during maintenance — likely expected. Confidence: 0.1"
  echo ""
  exit 0
elif [ -f "$MAINT_ENDED_FILE" ]; then
  ENDED_TS=$(cat "$MAINT_ENDED_FILE" 2>/dev/null || echo "0")
  NOW_TS=$(date +%s)
  ELAPSED=$(( NOW_TS - ENDED_TS ))
  if [ "$ELAPSED" -lt 900 ]; then
    COOLDOWN_MIN=$(( (900 - ELAPSED) / 60 ))
    echo ""
    echo "*** POST-MAINTENANCE COOLDOWN ($COOLDOWN_MIN min remaining) ***"
    echo "K8s alert may be post-maintenance noise. Confidence will be reduced."
    echo ""
  fi
fi

echo "=== K8S TRIAGE: $ALERTNAME ($SEVERITY) ==="
echo "Namespace: $NAMESPACE | Node: ${NODE:-n/a} | Pod: ${POD:-n/a}"
echo ""

# ─── Step 0: Check for existing open issues with same alert ───
CURRENT_STEP="Step 0 (check existing issues)"
echo "--- Step 0: Checking for existing issues ---"
ISSUE_ID="${EXISTING_ISSUE:-}"
REUSING_ISSUE=false
RELATED_ISSUES=""
LINK_TO_ISSUE=""

if [ -z "$ISSUE_ID" ]; then
  # Search YouTrack for issues with same Alert Rule (within 7 days, including Done/Cancelled)
  EXISTING=$(python3 -c "
import urllib.request, json, ssl, urllib.parse, time
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
query = 'project: $YT_PROJECT Alert Rule: $ALERTNAME State: -Duplicate sort by: created desc'
url = '${YOUTRACK_URL}/api/issues?query=' + urllib.parse.quote(query) + '&fields=idReadable,created,summary,customFields(name,value(name))&\$top=5'
req = urllib.request.Request(url, headers={'Authorization': 'Bearer ${YOUTRACK_TOKEN}', 'Accept': 'application/json'})
try:
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    issues = json.loads(resp.read())
    now_ms = int(time.time() * 1000)
    for issue in issues:
        age_h = (now_ms - issue.get('created', 0)) / 3600000
        if age_h < 168:
            state = 'unknown'
            for cf in issue.get('customFields', []):
                if cf.get('name') == 'State' and cf.get('value'):
                    state = cf['value'].get('name', 'unknown')
            print(issue['idReadable'] + '|' + state + '|' + str(round(age_h, 1)) + 'h')
            break
except Exception as e:
    pass
" 2>/dev/null)

  if [ -n "$EXISTING" ]; then
    ISSUE_ID=$(echo "$EXISTING" | cut -d'|' -f1)
    EXISTING_STATE=$(echo "$EXISTING" | cut -d'|' -f2)
    EXISTING_AGE=$(echo "$EXISTING" | cut -d'|' -f3)
    echo "Found existing issue: $ISSUE_ID ($EXISTING_STATE, $EXISTING_AGE old)"

    if [ "$EXISTING_STATE" = "Done" ] || [ "$EXISTING_STATE" = "Cancelled" ]; then
      # Closed issue — create new but auto-link as "relates to"
      echo "Previous issue $ISSUE_ID is $EXISTING_STATE — will create new and link"
      LINK_TO_ISSUE="$ISSUE_ID"
      ISSUE_ID=""
      REUSING_ISSUE=false
    else
      echo "Reusing instead of creating new issue"
      REUSING_ISSUE=true

      # Reopen if it was in To Verify
      if [ "$EXISTING_STATE" = "To Verify" ]; then
        echo "Reopening issue (was To Verify)"
        python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'issues': [{'idReadable': '$ISSUE_ID'}], 'query': 'state Open'}).encode()
req = urllib.request.Request('${YOUTRACK_URL}/api/commands', data=data, headers={'Content-Type':'application/json', 'Authorization': 'Bearer ${YOUTRACK_TOKEN}'}, method='POST')
try: urllib.request.urlopen(req, context=ctx)
except: pass
" 2>/dev/null || true
      fi
    fi
  else
    echo "No existing issues found"
  fi

  # Also search for RELATED issues (different alert, same node or namespace, within 12h)
  if [ -n "$NODE" ] || [ "$NAMESPACE" != "cluster-wide" ]; then
    RELATED=$(python3 -c "
import urllib.request, json, ssl, urllib.parse, time
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
now_ms = int(time.time() * 1000)
results = []

# Search by node
node = '$NODE'
if node:
    query = 'project: $YT_PROJECT Hostname: ' + node + ' State: -Done,-Cancelled,-Duplicate sort by: created desc'
    url = '${YOUTRACK_URL}/api/issues?query=' + urllib.parse.quote(query) + '&fields=idReadable,created,summary,customFields(name,value(name))&\$top=5'
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ${YOUTRACK_TOKEN}', 'Accept': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        issues = json.loads(resp.read())
        for issue in issues:
            age_h = (now_ms - issue.get('created', 0)) / 3600000
            if age_h < 12:
                alert_rule = ''
                for cf in issue.get('customFields', []):
                    if cf.get('name') == 'Alert Rule' and cf.get('value'):
                        alert_rule = cf['value'] if isinstance(cf['value'], str) else str(cf['value'])
                if alert_rule != '$ALERTNAME':
                    results.append(issue['idReadable'] + ' (' + issue.get('summary','')[:60] + ')')
    except: pass

# Search by namespace
ns = '$NAMESPACE'
if ns and ns != 'cluster-wide':
    query = 'project: $YT_PROJECT Namespace: ' + ns + ' State: -Done,-Cancelled,-Duplicate sort by: created desc'
    url = '${YOUTRACK_URL}/api/issues?query=' + urllib.parse.quote(query) + '&fields=idReadable,created,summary,customFields(name,value(name))&\$top=5'
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ${YOUTRACK_TOKEN}', 'Accept': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=10)
        issues = json.loads(resp.read())
        for issue in issues:
            age_h = (now_ms - issue.get('created', 0)) / 3600000
            if age_h < 12 and issue['idReadable'] not in [r.split(' ')[0] for r in results]:
                results.append(issue['idReadable'] + ' (' + issue.get('summary','')[:60] + ')')
    except: pass

# Deduplicate and print
seen = set()
for r in results:
    iid = r.split(' ')[0]
    if iid not in seen:
        seen.add(iid)
        print(r)
" 2>/dev/null)
    if [ -n "$RELATED" ]; then
      RELATED_ISSUES="$RELATED"
      echo "Related open issues found:"
      echo "$RELATED_ISSUES"
    fi
  fi
fi

COMPLETED_STEPS="Step 0 (existing issue check)"
# ─── Step 1: Create or reuse YouTrack issue ───
CURRENT_STEP="Step 1 (create/reuse YT issue)"
if [ "$REUSING_ISSUE" = false ] && [ -z "$ISSUE_ID" ]; then
  echo ""
  echo "--- Step 1: Creating YouTrack issue ---"
  YT_SUMMARY="K8s Alert: $ALERTNAME ($SEVERITY)"
  [ -n "$NAMESPACE" ] && [ "$NAMESPACE" != "cluster-wide" ] && YT_SUMMARY="$YT_SUMMARY in $NAMESPACE"
  [ -n "$NODE" ] && YT_SUMMARY="$YT_SUMMARY on $NODE"

  YT_DESC="Prometheus alert: $ALERTNAME\nSeverity: $SEVERITY\nNamespace: $NAMESPACE\nSummary: $SUMMARY"
  [ -n "$NODE" ] && YT_DESC="$YT_DESC\nNode: $NODE"
  [ -n "$POD" ] && YT_DESC="$YT_DESC\nPod: $POD"
  [ -n "$RELATED_ISSUES" ] && YT_DESC="$YT_DESC\n\nRelated open issues:\n$RELATED_ISSUES"

  ISSUE_RESULT=$(./skills/yt-create-issue.sh $YT_PROJECT "$YT_SUMMARY" "$(echo -e "$YT_DESC")" 2>&1)
  echo "$ISSUE_RESULT"

  ISSUE_ID=$(echo "$ISSUE_RESULT" | grep -oP "${YT_PROJECT}-\d+" | head -1)
  if [ -z "$ISSUE_ID" ]; then
    echo "ERROR: Failed to create YT issue"
    exit 1
  fi
  echo "Issue: $ISSUE_ID"

  # Auto-link to previous closed issue if applicable
  if [ -n "${LINK_TO_ISSUE:-}" ]; then
    echo "Linking $ISSUE_ID to previous issue $LINK_TO_ISSUE"
    python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'issues': [{'idReadable': '$ISSUE_ID'}], 'query': 'relates to $LINK_TO_ISSUE'}).encode()
req = urllib.request.Request('${YOUTRACK_URL}/api/commands', data=data, headers={'Content-Type':'application/json', 'Authorization': 'Bearer ${YOUTRACK_TOKEN}'}, method='POST')
try: urllib.request.urlopen(req, context=ctx)
except: pass
" 2>/dev/null || true
  fi

  # Register callback to n8n (same pattern as infra-triage.sh)
  python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'action':'register','alertKey':'$ALERTNAME:$NAMESPACE','issueId':'$ISSUE_ID'}).encode()
req = urllib.request.Request('$PROM_WEBHOOK', data=data, headers={'Content-Type':'application/json'}, method='POST')
try: urllib.request.urlopen(req, context=ctx, timeout=5)
except: pass
" 2>/dev/null &

  # Set custom fields
  python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
yt_url = '${YOUTRACK_URL}'
yt_token = '${YOUTRACK_TOKEN}'
fields = [('Hostname', '${NODE:-k8s-cluster}'), ('Alert Rule', '$ALERTNAME'), ('Severity', '$SEVERITY'), ('Namespace', '$NAMESPACE'), ('Alert Source', 'Prometheus')]
pod = '$POD'
if pod:
    fields.append(('Pod', pod))
for name, val in fields:
    if not val:
        continue
    data = json.dumps({'issues': [{'idReadable': '$ISSUE_ID'}], 'query': name + ' ' + val}).encode()
    req = urllib.request.Request(yt_url + '/api/commands', data=data, headers={'Content-Type':'application/json', 'Authorization': 'Bearer ' + yt_token}, method='POST')
    try: urllib.request.urlopen(req, context=ctx)
    except: pass
" 2>/dev/null || true
else
  echo ""
  echo "--- Step 1: Reusing issue $ISSUE_ID ---"

  # Still register callback for reused issues
  python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'action':'register','alertKey':'$ALERTNAME:$NAMESPACE','issueId':'$ISSUE_ID'}).encode()
req = urllib.request.Request('$PROM_WEBHOOK', data=data, headers={'Content-Type':'application/json'}, method='POST')
try: urllib.request.urlopen(req, context=ctx, timeout=5)
except: pass
" 2>/dev/null &
fi

FINDINGS=""

COMPLETED_STEPS="Step 0 (issue check), Step 1 (issue ${ISSUE_ID})"

# Step 1.5: Query incident knowledge base for prior resolutions (semantic search)
echo "--- Step 1.5: Querying incident knowledge base (semantic) ---"
KB_QUERY="${HOSTNAME:-} ${ALERTNAME}"
PRIOR_KNOWLEDGE=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
  -i ~/.ssh/one_key app-user@nl-claude01 \
  "python3 ~/gitlab/n8n/claude-gateway/scripts/kb-semantic-search.py search '${KB_QUERY//\'/\\\'}' --limit 3 --days 90" 2>/dev/null) || true

PRIOR_NOTE=""
if [ -n "$PRIOR_KNOWLEDGE" ]; then
  PRIOR_NOTE="\n\n**Prior resolutions for similar alerts:**\n"
  while IFS='|' read -r pk_issue pk_host pk_alert pk_resolution pk_confidence pk_date pk_site pk_sim; do
    PRIOR_NOTE="${PRIOR_NOTE}- [${pk_date}] ${pk_issue}: ${pk_resolution} (confidence: ${pk_confidence}, similarity: ${pk_sim})\n"
  done <<< "$PRIOR_KNOWLEDGE"
  echo "Found $(echo "$PRIOR_KNOWLEDGE" | wc -l) prior resolution(s)"
else
  echo "No prior resolutions found"
fi

# ─── Step 2-pre: NetBox CMDB Lookup — device identity ───
CURRENT_STEP="Step 2-pre (NetBox lookup)"
echo ""
echo "--- Step 2-pre: NetBox CMDB Lookup ---"
NETBOX_RESULT=""
if [ -f "$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" ]; then
  # Look up the K8s node or pod's host node
  NB_LOOKUP="${NODE:-$POD}"
  if [ -n "$NB_LOOKUP" ]; then
    NETBOX_RESULT=$("$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" device "$NB_LOOKUP" 2>/dev/null || true)
    if [ -z "$NETBOX_RESULT" ] || echo "$NETBOX_RESULT" | grep -q "^No device found\|^Error"; then
      NETBOX_RESULT=$("$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" search "$NB_LOOKUP" 2>/dev/null || echo "No NetBox match for $NB_LOOKUP")
    fi
    echo "$NETBOX_RESULT" | head -15
    FINDINGS="$FINDINGS\nNetBox CMDB: $(echo "$NETBOX_RESULT" | head -5 | tr '\n' ' | ')"
  else
    echo "No node/pod to look up in NetBox"
  fi
else
  echo "NetBox lookup not available (netbox-lookup.sh not found)"
  FINDINGS="$FINDINGS\nNetBox: not available"
fi
COMPLETED_STEPS="$COMPLETED_STEPS, Step 2-pre (NetBox)"
echo ""

# ─── Step 2: K8s investigation ───
CURRENT_STEP="Step 2 (K8s investigation)"
echo ""
echo "--- Step 2: Investigating via kubectl ---"

# Cluster overview
echo "--- Cluster health ---"
NODES=$(kctl get nodes -o wide 2>&1)
echo "$NODES"
NOT_READY=$(echo "$NODES" | grep -v Ready | grep -v NAME || echo "All nodes Ready")
FINDINGS="$FINDINGS\nCluster nodes:\n$NODES"

# Node syslog (K8s nodes often send syslog for kernel/systemd events)
if [ -n "$NODE" ]; then
  echo ""
  echo "--- Node syslog: $NODE ---"
  NODE_SYSLOG=$(fetch_syslog "$NODE" 20 "error|fail|oom|kill|restart|timeout|unreachable|panic|segfault" 2>/dev/null || true)
  if [ -n "$NODE_SYSLOG" ] && ! echo "$NODE_SYSLOG" | grep -q "^No .* syslog"; then
    echo "$NODE_SYSLOG"
    FINDINGS="$FINDINGS\n\nNode syslog ($NODE):\n$NODE_SYSLOG"
  else
    echo "No syslog available for $NODE"
  fi
fi

# Node-specific checks
if [ -n "$NODE" ]; then
  echo ""
  echo "--- Node: $NODE ---"
  NODE_DESC=$(kctl describe node "$NODE" 2>&1 | grep -A5 "Conditions:" | head -10)
  echo "$NODE_DESC"
  FINDINGS="$FINDINGS\n\nNode $NODE conditions:\n$NODE_DESC"

  NODE_EVENTS=$(kctl get events --field-selector "involvedObject.name=$NODE" --sort-by='.lastTimestamp' 2>/dev/null | tail -5)
  echo "$NODE_EVENTS"
  FINDINGS="$FINDINGS\n\nNode events:\n$NODE_EVENTS"

  # Resource usage on node
  echo ""
  echo "--- Node resource usage ---"
  NODE_TOP=$(kctl top node "$NODE" 2>&1 || echo "metrics-server unavailable")
  echo "$NODE_TOP"
  FINDINGS="$FINDINGS\n\nNode resource usage:\n$NODE_TOP"

  # --- PVE VMID lookup + UID Schema Decode for K8s node ---
  # K8s nodes are PVE VMs/LXCs — look up VMID from IaC repo
  PVE_RESULT=$(grep -r "hostname: $NODE" ${IAC_REPO}/pve/ 2>/dev/null || echo "")
  K8S_VMID=""
  K8S_PVE_HOST=""
  K8S_HOST_TYPE=""
  if echo "$PVE_RESULT" | grep -q "qemu/"; then
    K8S_HOST_TYPE="QEMU"
    K8S_PVE_HOST=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/pve/\([^/]*\)/.*|\1|')
    K8S_VMID=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/qemu/\([0-9]*\)\.conf.*|\1|')
  elif echo "$PVE_RESULT" | grep -q "lxc/"; then
    K8S_HOST_TYPE="LXC"
    K8S_PVE_HOST=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/pve/\([^/]*\)/.*|\1|')
    K8S_VMID=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/lxc/\([0-9]*\)\.conf.*|\1|')
  fi

  # NetBox fallback if IaC lookup found nothing
  if [ -z "$K8S_VMID" ] && [ -n "${NETBOX_TOKEN:-}" ]; then
    echo "IaC lookup failed — trying NetBox for $NODE"
    NB_VM=$(curl -sk -H "Authorization: Token $NETBOX_TOKEN" \
      "${NETBOX_URL}/api/virtualization/virtual-machines/?name=$NODE" 2>/dev/null | \
      python3 -c "
import json, sys
try:
    d = json.load(sys.stdin); r = d.get('results', [])
    if r:
        vm = r[0]; vmid = vm.get('custom_fields', {}).get('vmid', '')
        cl = vm.get('cluster', {}); cn = cl.get('name', '') if isinstance(cl, dict) else ''
        print(str(vmid) + '|' + cn)
except: pass
" 2>/dev/null)
    if [ -n "$NB_VM" ]; then
      K8S_VMID=$(echo "$NB_VM" | cut -d'|' -f1)
      K8S_PVE_HOST=$(echo "$NB_VM" | cut -d'|' -f2)
      K8S_HOST_TYPE="NetBox"
      [ -n "$K8S_VMID" ] && echo "NetBox: VMID=$K8S_VMID, PVE Host=$K8S_PVE_HOST"
    fi
  fi

  if [ -n "$K8S_VMID" ]; then
    echo ""
    echo "--- PVE identity: $K8S_HOST_TYPE $K8S_VMID on $K8S_PVE_HOST ---"
    FINDINGS="$FINDINGS\n\nPVE: $K8S_HOST_TYPE $K8S_VMID on $K8S_PVE_HOST"

    # VMID UID Schema Decode (9-digit: S NN VV TT RR)
    # WARNING: Some VMIDs have drifted — always cross-check against actual PVE host
    if [ ${#K8S_VMID} -eq 9 ]; then
      V_SITE="${K8S_VMID:0:1}"; V_NODE="${K8S_VMID:1:2}"; V_VLAN="${K8S_VMID:3:2}"
      V_TAG="${K8S_VMID:5:2}"; V_RES="${K8S_VMID:7:2}"
      case "$V_SITE" in 1) V_S="NL" ;; 2) V_S="GR" ;; *) V_S="?" ;; esac
      case "$V_TAG" in
        00) V_T="OOB" ;; 01) V_T="Mgmt" ;; 02) V_T="Network" ;; 04) V_T="LB/HA" ;;
        07) V_T="Monitoring" ;; 10) V_T="DB/Web" ;; 12) V_T="Collaboration" ;;
        85) V_T="K8s Infra" ;; *) V_T="Tag$V_TAG" ;;
      esac
      VMID_INFO="VMID decode: Site=$V_S, Node=pve${V_NODE}, VLAN=$V_VLAN, Category=$V_T, Instance=$V_RES"
      echo "$VMID_INFO"
      FINDINGS="$FINDINGS\n$VMID_INFO"

      # Cross-check: VMID-encoded node vs actual PVE host
      ACTUAL_NODE=$(echo "$K8S_PVE_HOST" | grep -oE 'pve[0-9]+' | sed 's/pve//')
      if [ -n "$ACTUAL_NODE" ] && [ "$ACTUAL_NODE" != "$V_NODE" ]; then
        DRIFT_MSG="DRIFT WARNING: VMID says pve${V_NODE} but actually on pve${ACTUAL_NODE} — VMID may need update"
        echo "*** $DRIFT_MSG ***"
        FINDINGS="$FINDINGS\n⚠️ $DRIFT_MSG"
      fi
    fi

    # Set VMID and PVE Host custom fields on YT issue
    if [ -n "$ISSUE_ID" ]; then
      echo "Setting VMID/PVE Host custom fields on $ISSUE_ID"
      python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
yt_url = '${YOUTRACK_URL}'
yt_token = '${YOUTRACK_TOKEN}'
for name, val in [('VMID', '$K8S_VMID'), ('PVE Host', '$K8S_PVE_HOST')]:
    if not val: continue
    data = json.dumps({'issues': [{'idReadable': '$ISSUE_ID'}], 'query': name + ' ' + val}).encode()
    req = urllib.request.Request(yt_url + '/api/commands', data=data, headers={'Content-Type':'application/json', 'Authorization': 'Bearer ' + yt_token}, method='POST')
    try: urllib.request.urlopen(req, context=ctx)
    except: pass
" 2>/dev/null || true
    fi
  fi
fi

# Step 2e: Physical layer context — PVE host NIC config from 03_Lab (non-fatal)
if [ -n "$K8S_PVE_HOST" ]; then
  echo ""
  echo "--- Step 2e: PVE host NIC config ($K8S_PVE_HOST, 03_Lab) ---"
  K8S_NIC=$(./skills/lab-lookup/lab-lookup.sh nic-config "$K8S_PVE_HOST" 2>/dev/null) || true
  if [ -n "$K8S_NIC" ] && ! echo "$K8S_NIC" | grep -q "^No data"; then
    echo "$K8S_NIC"
    FINDINGS="$FINDINGS\n\nPVE host NIC config ($K8S_PVE_HOST, from 03_Lab):\n$K8S_NIC"
  fi
fi

# Namespace-specific checks
if [ -n "$NAMESPACE" ] && [ "$NAMESPACE" != "cluster-wide" ]; then
  echo ""
  echo "--- Namespace: $NAMESPACE ---"
  NS_PODS=$(kctl get pods -n "$NAMESPACE" -o wide 2>&1)
  echo "$NS_PODS"

  UNHEALTHY=$(echo "$NS_PODS" | grep -v Running | grep -v Completed | grep -v NAME || echo "All pods healthy")
  FINDINGS="$FINDINGS\n\nPods in $NAMESPACE:\n$NS_PODS"

  # Restart counts — flag any pod with restarts > 0
  RESTARTS=$(echo "$NS_PODS" | awk 'NR>1 && $4+0 > 0 {print $1 " restarts=" $4}')
  if [ -n "$RESTARTS" ]; then
    echo ""
    echo "--- Pods with restarts ---"
    echo "$RESTARTS"
    FINDINGS="$FINDINGS\n\nPods with restarts:\n$RESTARTS"
  fi

  NS_EVENTS=$(kctl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' 2>/dev/null | tail -15)
  if [ -n "$NS_EVENTS" ]; then
    echo "$NS_EVENTS"
    FINDINGS="$FINDINGS\n\nRecent events:\n$NS_EVENTS"
  fi
fi

# Pod-specific checks
if [ -n "$POD" ] && [ -n "$NAMESPACE" ] && [ "$NAMESPACE" != "cluster-wide" ]; then
  echo ""
  echo "--- Pod: $POD ---"
  POD_DESC=$(kctl describe pod "$POD" -n "$NAMESPACE" 2>&1 | tail -30)
  echo "$POD_DESC"
  FINDINGS="$FINDINGS\n\nPod $POD describe:\n$POD_DESC"

  # Pod resource usage
  echo ""
  echo "--- Pod resource usage ---"
  POD_TOP=$(kctl top pod "$POD" -n "$NAMESPACE" 2>&1 || echo "metrics-server unavailable")
  echo "$POD_TOP"
  FINDINGS="$FINDINGS\n\nPod resource usage:\n$POD_TOP"

  POD_LOGS=$(kctl logs "$POD" -n "$NAMESPACE" --tail=30 2>&1)
  echo "$POD_LOGS"
  FINDINGS="$FINDINGS\n\nPod logs (last 30):\n$POD_LOGS"

  # Previous container logs (if restarted)
  POD_PREV_LOGS=$(kctl logs "$POD" -n "$NAMESPACE" --previous --tail=20 2>&1)
  if ! echo "$POD_PREV_LOGS" | grep -q "previous terminated container"; then
    echo ""
    echo "--- Previous container logs ---"
    echo "$POD_PREV_LOGS"
    FINDINGS="$FINDINGS\n\nPrevious container logs:\n$POD_PREV_LOGS"
  fi
fi

# ─── Control plane cross-checks ───
# When one control plane component alerts, check ALL related components
CONTROL_PLANE_ALERT=false
case "$ALERTNAME" in
  *apiserver*|*APIServer*|*KubeAPI*|HighPodRestartRate)
    # For HighPodRestartRate, only do control plane checks if the pod is a control plane component
    if [[ "$ALERTNAME" != "HighPodRestartRate" ]] || echo "$POD" | grep -qE "kube-apiserver|kube-controller|kube-scheduler|etcd"; then
      CONTROL_PLANE_ALERT=true
    fi
    ;;
  etcd*|Etcd*)
    CONTROL_PLANE_ALERT=true
    ;;
  *ControllerManager*|*Scheduler*)
    CONTROL_PLANE_ALERT=true
    ;;
  KubeAPIErrorBudgetBurn)
    CONTROL_PLANE_ALERT=true
    ;;
esac

if [ "$CONTROL_PLANE_ALERT" = true ]; then
  echo ""
  echo "=== CONTROL PLANE DEEP INVESTIGATION ==="

  # etcd health
  echo ""
  echo "--- etcd pods ---"
  ETCD_PODS=$(kctl get pods -n kube-system -l component=etcd -o wide 2>&1)
  echo "$ETCD_PODS"
  FINDINGS="$FINDINGS\n\n=== CONTROL PLANE INVESTIGATION ===\n\netcd pods:\n$ETCD_PODS"

  # etcd logs (last 30 lines from each etcd pod)
  for ETCD_POD in $(kctl get pods -n kube-system -l component=etcd -o name 2>/dev/null); do
    ETCD_NAME=$(basename "$ETCD_POD")
    echo ""
    echo "--- etcd logs: $ETCD_NAME ---"
    ETCD_LOGS=$(kctl logs "$ETCD_POD" -n kube-system --tail=30 2>&1 | grep -v "^$" | tail -15)
    echo "$ETCD_LOGS"
    FINDINGS="$FINDINGS\n\netcd logs ($ETCD_NAME):\n$ETCD_LOGS"
  done

  # etcd events
  ETCD_EVENTS=$(kctl get events -n kube-system --field-selector "reason!=Pulled,reason!=Created,reason!=Started" --sort-by='.lastTimestamp' 2>/dev/null | grep -i etcd | tail -5)
  if [ -n "$ETCD_EVENTS" ]; then
    echo ""
    echo "--- etcd events ---"
    echo "$ETCD_EVENTS"
    FINDINGS="$FINDINGS\n\netcd events:\n$ETCD_EVENTS"
  fi

  # kube-apiserver status on ALL control plane nodes
  echo ""
  echo "--- kube-apiserver pods ---"
  API_PODS=$(kctl get pods -n kube-system -l component=kube-apiserver -o wide 2>&1)
  echo "$API_PODS"
  FINDINGS="$FINDINGS\n\nkube-apiserver pods:\n$API_PODS"

  # apiserver restart counts
  API_RESTARTS=$(kctl get pods -n kube-system -l component=kube-apiserver -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}' 2>/dev/null)
  if [ -n "$API_RESTARTS" ]; then
    echo ""
    echo "--- apiserver restart counts ---"
    echo "$API_RESTARTS"
    FINDINGS="$FINDINGS\n\napiserver restart counts:\n$API_RESTARTS"
  fi

  # apiserver logs — look for errors
  for API_POD in $(kctl get pods -n kube-system -l component=kube-apiserver -o name 2>/dev/null); do
    API_NAME=$(basename "$API_POD")
    echo ""
    echo "--- apiserver errors: $API_NAME ---"
    API_ERRORS=$(kctl logs "$API_POD" -n kube-system --tail=50 2>&1 | grep -iE "error|fatal|timeout|refused|unreachable|dial" | tail -10)
    if [ -n "$API_ERRORS" ]; then
      echo "$API_ERRORS"
      FINDINGS="$FINDINGS\n\napiserver errors ($API_NAME):\n$API_ERRORS"
    else
      echo "No errors in recent logs"
    fi
  done

  # kube-controller-manager and kube-scheduler
  echo ""
  echo "--- controller-manager + scheduler ---"
  CP_PODS=$(kctl get pods -n kube-system -l 'component in (kube-controller-manager,kube-scheduler)' -o wide 2>&1)
  echo "$CP_PODS"
  FINDINGS="$FINDINGS\n\ncontroller-manager + scheduler:\n$CP_PODS"

  # Control plane resource usage
  echo ""
  echo "--- Control plane resource usage ---"
  CP_TOP=$(kctl top pods -n kube-system -l 'component in (kube-apiserver,etcd,kube-controller-manager,kube-scheduler)' 2>&1 || echo "metrics-server unavailable")
  echo "$CP_TOP"
  FINDINGS="$FINDINGS\n\nControl plane resource usage:\n$CP_TOP"
fi

# Alert-specific checks (non-control-plane)
if [ "$CONTROL_PLANE_ALERT" = false ]; then
  case "$ALERTNAME" in
    etcd*)
      echo ""
      echo "--- etcd health ---"
      ETCD_PODS=$(kctl get pods -n kube-system -l component=etcd 2>&1)
      echo "$ETCD_PODS"
      FINDINGS="$FINDINGS\n\netcd pods:\n$ETCD_PODS"
      ;;
    KubeProxy*)
      echo ""
      echo "--- kube-proxy ---"
      PROXY_PODS=$(kctl get pods -n kube-system -l k8s-app=kube-proxy 2>&1)
      echo "$PROXY_PODS"
      FINDINGS="$FINDINGS\n\nkube-proxy pods:\n$PROXY_PODS"
      ;;
    Cilium*)
      echo ""
      echo "--- Cilium status ---"
      CILIUM_PODS=$(kctl get pods -n kube-system -l k8s-app=cilium -o wide 2>&1)
      echo "$CILIUM_PODS"
      FINDINGS="$FINDINGS\n\nCilium pods:\n$CILIUM_PODS"

      # Cilium connectivity
      echo ""
      echo "--- Cilium agent logs (errors) ---"
      for CPOD in $(kctl get pods -n kube-system -l k8s-app=cilium -o name 2>/dev/null); do
        CNAME=$(basename "$CPOD")
        CERR=$(kctl logs "$CPOD" -n kube-system --tail=30 2>&1 | grep -iE "error|unreachable|timeout" | tail -5)
        if [ -n "$CERR" ]; then
          echo "  $CNAME:"
          echo "$CERR"
          FINDINGS="$FINDINGS\n\nCilium errors ($CNAME):\n$CERR"
        fi
      done
      ;;
    *NFS*|*nfs*)
      echo ""
      echo "--- NFS/Storage ---"
      PVS=$(kctl get pv 2>&1 | head -10)
      echo "$PVS"
      FINDINGS="$FINDINGS\n\nPersistent Volumes:\n$PVS"
      ;;
    *CrashLooping*|*CrashLoop*)
      echo ""
      echo "--- CrashLoop investigation ---"
      if [ -n "$POD" ] && [ -n "$NAMESPACE" ] && [ "$NAMESPACE" != "cluster-wide" ]; then
        CRASH_EVENTS=$(kctl get events -n "$NAMESPACE" --field-selector "involvedObject.name=$POD" --sort-by='.lastTimestamp' 2>/dev/null | tail -10)
        echo "$CRASH_EVENTS"
        FINDINGS="$FINDINGS\n\nCrash events:\n$CRASH_EVENTS"
      fi
      ;;
  esac
fi

COMPLETED_STEPS="Step 0 (issue check), Step 1 (issue ${ISSUE_ID}), Step 2 (investigation)"
# ─── Step 3: Post findings to YT ───
CURRENT_STEP="Step 3 (post findings to YT)"
echo ""
echo "--- Step 3: Posting findings ---"

RECURRENCE_NOTE=""
if [ "$REUSING_ISSUE" = true ]; then
  RECURRENCE_NOTE="
** RECURRING ALERT — reusing existing issue **"
fi

RELATED_NOTE=""
if [ -n "$RELATED_ISSUES" ]; then
  RELATED_NOTE="
Related open issues (possible common root cause):
$RELATED_ISSUES"
fi

COMMENT="K8s Alert Investigation ($ALERTNAME, $SEVERITY)${RECURRENCE_NOTE}

Alert: $ALERTNAME
Severity: $SEVERITY
Namespace: $NAMESPACE
Summary: $SUMMARY
$([ -n "$NODE" ] && echo "Node: $NODE")
$([ -n "$POD" ] && echo "Pod: $POD")
${RELATED_NOTE}$(echo -e "$PRIOR_NOTE")
Investigation findings:
$(echo -e "$FINDINGS")"

./skills/yt-post-comment.sh "$ISSUE_ID" "$COMMENT" 2>&1 || echo "WARN: Failed to post YT comment"

# ─── Step 4: Acknowledge LibreNMS alerts if hostname matches ───
if [ -n "$NODE" ]; then
  echo ""
  echo "--- Step 4: Acknowledging alerts ---"
  ALERT_IDS=$(curl -sk -H "X-Auth-Token: $LIBRENMS_API_KEY" \
    "${LIBRENMS_URL}/api/v0/alerts?state=1" 2>/dev/null | \
    python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    for a in d.get('alerts',[]):
        if a.get('hostname','') == '$NODE' and a.get('state') == 1:
            print(a['id'])
except: pass
" 2>/dev/null)
  for AID in $ALERT_IDS; do
    curl -sk -X PUT -H "X-Auth-Token: $LIBRENMS_API_KEY" -H "Content-Type: application/json" \
      -d "{\"state\":2,\"note\":\"K8s triage. YT: $ISSUE_ID\"}" \
      "${LIBRENMS_URL}/api/v0/alerts/$AID" >/dev/null 2>&1
    echo "Acknowledged alert $AID"
  done
fi

# ─── Step 5: Escalation decision ───
echo ""
SHOULD_ESCALATE=false

# Escalate critical alerts
if [ "$SEVERITY" = "critical" ]; then
  SHOULD_ESCALATE=true
  echo "--- Step 5: Critical severity — escalating ---"
fi

# Escalate if forced (flapping alert detected by n8n)
if [ "${FORCE_ESCALATE:-}" = "true" ]; then
  SHOULD_ESCALATE=true
  echo "--- Step 5: Forced escalation (flapping/recurring alert) ---"
fi

# Escalate recurring alerts (reusing issue = this alert has fired before recently)
if [ "$REUSING_ISSUE" = true ]; then
  SHOULD_ESCALATE=true
  echo "--- Step 5: Recurring alert — escalating ---"
fi

# Escalate control plane alerts regardless of severity
if [ "$CONTROL_PLANE_ALERT" = true ] && [ "$SEVERITY" = "warning" ]; then
  SHOULD_ESCALATE=true
  echo "--- Step 5: Control plane warning — escalating (control plane alerts always escalate) ---"
fi

# Escalate if investigation confidence is low (< 0.7) — T1 couldn't fully diagnose
if [ "$SHOULD_ESCALATE" = false ] && [ -n "${TRIAGE_CONFIDENCE:-}" ]; then
  LOW_CONF=$(echo "${TRIAGE_CONFIDENCE:-1} < 0.7" | bc -l 2>/dev/null || echo 0)
  if [ "$LOW_CONF" = "1" ]; then
    SHOULD_ESCALATE=true
    echo "--- Step 5: Low confidence (${TRIAGE_CONFIDENCE}) — escalating to Tier 2 for deeper investigation ---"
  fi
fi

if [ "$SHOULD_ESCALATE" = true ]; then
  if [ "${SKIP_ESCALATION:-}" != "true" ]; then
    ESCALATION_REASON=""
    [ "$SEVERITY" = "critical" ] && ESCALATION_REASON="critical severity"
    [ "${FORCE_ESCALATE:-}" = "true" ] && ESCALATION_REASON="${ESCALATION_REASON:+$ESCALATION_REASON + }flapping alert"
    [ "$REUSING_ISSUE" = true ] && ESCALATION_REASON="${ESCALATION_REASON:+$ESCALATION_REASON + }recurring"
    [ "$CONTROL_PLANE_ALERT" = true ] && ESCALATION_REASON="${ESCALATION_REASON:+$ESCALATION_REASON + }control plane"

    TRIAGE_CONFIDENCE="${TRIAGE_CONFIDENCE:-0.5}" \
    TRIAGE_COMPLETED_STEPS="$COMPLETED_STEPS" \
    TRIAGE_HOSTNAME="${HOSTNAME:-}" \
    TRIAGE_ALERT_RULE="$ALERTNAME" \
    TRIAGE_SEVERITY="$SEVERITY" \
    TRIAGE_SITE="$SITE" \
    ./skills/escalate-to-claude.sh "$ISSUE_ID" "K8s alert: $ALERTNAME ($SEVERITY) in $NAMESPACE. Escalation reason: $ESCALATION_REASON. L2 findings posted as YT comment." 2>&1 || echo "WARN: Escalation failed"
  fi
else
  echo "--- Step 5: No escalation criteria met (monitoring only) ---"
fi

# ─── Step 6: Structured JSON summary (machine-parseable) ───
ESCALATION_REASON_JSON=""
[ "$SEVERITY" = "critical" ] && ESCALATION_REASON_JSON="critical"
[ "${FORCE_ESCALATE:-}" = "true" ] && ESCALATION_REASON_JSON="${ESCALATION_REASON_JSON:+$ESCALATION_REASON_JSON,}flapping"
[ "$REUSING_ISSUE" = true ] && ESCALATION_REASON_JSON="${ESCALATION_REASON_JSON:+$ESCALATION_REASON_JSON,}recurring"
[ "$CONTROL_PLANE_ALERT" = true ] && ESCALATION_REASON_JSON="${ESCALATION_REASON_JSON:+$ESCALATION_REASON_JSON,}control_plane"

echo ""
echo "TRIAGE_JSON:$(python3 -c "
import json
print(json.dumps({
    'issueId': '$ISSUE_ID',
    'alertname': '$ALERTNAME',
    'severity': '$SEVERITY',
    'namespace': '$NAMESPACE',
    'node': '${NODE:-}',
    'pod': '${POD:-}',
    'reused': $( [ "$REUSING_ISSUE" = true ] && echo "true" || echo "false" ),
    'controlPlane': $( [ "$CONTROL_PLANE_ALERT" = true ] && echo "true" || echo "false" ),
    'escalated': $( [ "$SHOULD_ESCALATE" = true ] && echo "true" || echo "false" ),
    'escalationReason': '${ESCALATION_REASON_JSON:-none}',
    'relatedIssues': [r.split(' ')[0] for r in '''$RELATED_ISSUES'''.strip().split('\n') if r.strip()],
}))" 2>/dev/null || echo '{"issueId":"'$ISSUE_ID'","error":"json_failed"}')"

# Validate TRIAGE_JSON schema (non-fatal)
python3 -c "
import json, sys
try:
    # Re-generate the same JSON to validate
    data = json.loads(json.dumps({
        'issueId': '$ISSUE_ID',
        'alertname': '$ALERTNAME',
        'severity': '$SEVERITY',
        'namespace': '$NAMESPACE',
        'node': '${NODE:-}',
        'pod': '${POD:-}',
        'reused': $( [ "$REUSING_ISSUE" = true ] && echo "True" || echo "False" ),
        'controlPlane': $( [ "$CONTROL_PLANE_ALERT" = true ] && echo "True" || echo "False" ),
        'escalated': $( [ "$SHOULD_ESCALATE" = true ] && echo "True" || echo "False" ),
        'escalationReason': '${ESCALATION_REASON_JSON:-none}',
    }))
    required = ['issueId', 'alertname', 'severity', 'escalated']
    missing = [f for f in required if f not in data]
    if missing:
        print(f'WARN: TRIAGE_JSON missing fields: {missing}')
    if data.get('issueId', '') and not any(data['issueId'].startswith(p) for p in ['IFRNLLEI01PRD-', 'IFRGRSKG01PRD-']):
        print(f'WARN: TRIAGE_JSON issueId has unexpected prefix: {data[\"issueId\"]}')
    if data.get('severity', '') not in ('critical', 'warning', 'info', 'unknown', ''):
        print(f'WARN: TRIAGE_JSON unexpected severity: {data[\"severity\"]}')
except Exception as e:
    print(f'WARN: TRIAGE_JSON validation failed: {e}')
" 2>/dev/null || true

# Structured triage log for agent metrics
TRIAGE_LOG="/app/cubeos/claude-context/triage.log"
OUTCOME=$([ "$SHOULD_ESCALATE" = "true" ] && echo "escalated" || echo "resolved")
TRIAGE_DURATION=$(($(date +%s) - ${TRIAGE_START:-$(date +%s)}))
echo "$(date -u +%FT%TZ)|${HOSTNAME:-k8s}|${ALERTNAME}|${TRIAGE_SITE:-nl}|${OUTCOME}|${TRIAGE_CONFIDENCE:-0}|${TRIAGE_DURATION}|${ISSUE_ID}" >> "$TRIAGE_LOG" 2>/dev/null || true

# Store episodic memory for OpenClaw
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
  -i ~/.ssh/one_key app-user@nl-claude01 \
  "sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db \"
    INSERT OR REPLACE INTO openclaw_memory (category, key, value, issue_id)
    VALUES ('triage', '${HOSTNAME:-k8s}:${ALERTNAME}', '${OUTCOME} (confidence: ${TRIAGE_CONFIDENCE:-0}, duration: ${TRIAGE_DURATION}s, escalated: ${SHOULD_ESCALATE})', '${ISSUE_ID}');
  \"" 2>/dev/null || true

echo ""
echo "=== K8S TRIAGE COMPLETE: $ISSUE_ID ==="
