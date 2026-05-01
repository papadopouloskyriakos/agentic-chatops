#!/bin/bash
# Infrastructure Alert Triage — automated Level 1 + Level 2
# Usage: ./skills/infra-triage/infra-triage.sh <hostname> <rule_name> <severity> [--site nl|gr]
# Runs the complete triage flow: dedup via YT, create/reuse issue, investigate, post findings, escalate.
#
# Env vars:
#   FORCE_ESCALATE=true  — escalate regardless (set by n8n for flapping alerts)
#   EXISTING_ISSUE=ID    — reuse this issue instead of creating new
#   SKIP_ESCALATION=true — skip escalation step (for burst/correlated triage)
#   TRIAGE_SITE=nl|gr    — site override (alternative to --site flag)

set -uo pipefail

HOSTNAME="${1:?Usage: infra-triage.sh <hostname> <rule_name> <severity> [--site nl|gr]}"
RULE_NAME="${2:-Unknown Alert}"
SEVERITY="${3:-unknown}"

# Parse --site flag from remaining args
shift 3 2>/dev/null || true
while [ $# -gt 0 ]; do
  case "$1" in
    --site) TRIAGE_SITE="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# Auto-detect site from hostname if not explicitly set
if [ -z "${TRIAGE_SITE:-}" ]; then
  if echo "$HOSTNAME" | grep -qi "^grskg"; then
    TRIAGE_SITE="gr"
  else
    TRIAGE_SITE="nl"
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
validate_hostname "$HOSTNAME"

# Load site configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$SCRIPT_DIR/site-config.sh"

# ─── Maintenance mode check ───
MAINTENANCE_ACTIVE=false
MAINTENANCE_COOLDOWN=false
MAINT_FILE="/home/app-user/gateway.maintenance"
MAINT_ENDED_FILE="/home/app-user/gateway.maintenance-ended"

if [ -f "$MAINT_FILE" ]; then
  MAINTENANCE_ACTIVE=true
  MAINT_REASON=$(python3 -c "import json; print(json.load(open('$MAINT_FILE')).get('reason','unknown'))" 2>/dev/null || echo "unknown")
  echo ""
  echo "*** MAINTENANCE MODE ACTIVE ***"
  echo "Reason: $MAINT_REASON"
  echo "Alert suppressed — not escalating. Confidence: 0.1"
  echo "This alert occurred during scheduled maintenance and is likely expected."
  echo ""
  SKIP_ESCALATION=true
  exit 0
elif [ -f "$MAINT_ENDED_FILE" ]; then
  ENDED_TS=$(cat "$MAINT_ENDED_FILE" 2>/dev/null || echo "0")
  NOW_TS=$(date +%s)
  ELAPSED=$(( NOW_TS - ENDED_TS ))
  if [ "$ELAPSED" -lt 900 ]; then
    MAINTENANCE_COOLDOWN=true
    COOLDOWN_MIN=$(( (900 - ELAPSED) / 60 ))
    echo ""
    echo "*** POST-MAINTENANCE COOLDOWN ($COOLDOWN_MIN min remaining) ***"
    echo "This alert may be post-maintenance noise. Confidence will be reduced by 50%."
    echo ""
  fi
fi

# ─── Chaos exercise active check ───────────────────────────────────────────
# State lives at ~/chaos-state/*.json on nl-claude01. When this script runs
# on claude01 itself, read locally; when run from OpenClaw or other hosts, SSH
# across to claude01.
CHAOS_ACTIVE=false
if [ "$(hostname -s)" = "nl-claude01" ]; then
  CHAOS_RAW=$(cat /home/app-user/chaos-state/chaos-active.json 2>/dev/null \
    || cat /home/app-user/chaos-state/chaos-suppression.json 2>/dev/null \
    || echo NONE)
else
  CHAOS_RAW=$(ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
    -i ~/.ssh/one_key app-user@nl-claude01 \
    'cat ~/chaos-state/chaos-active.json 2>/dev/null || cat ~/chaos-state/chaos-suppression.json 2>/dev/null || echo NONE' \
    2>/dev/null) || CHAOS_RAW="NONE"
fi

if [ "$CHAOS_RAW" != "NONE" ] && [ -n "$CHAOS_RAW" ]; then
  CHAOS_TYPE=$(echo "$CHAOS_RAW" | python3 -c "import sys,json; print(json.load(sys.stdin).get('chaos_type','unknown'))" 2>/dev/null || echo "unknown")
  CHAOS_SOURCES=$(echo "$CHAOS_RAW" | python3 -c "import sys,json; print(','.join(json.load(sys.stdin).get('suppressed_sources',[])))" 2>/dev/null || echo "")

  if echo "$CHAOS_SOURCES" | grep -qi "$HOSTNAME"; then
    CHAOS_ACTIVE=true
    echo ""
    echo "*** CHAOS EXERCISE ACTIVE (type: $CHAOS_TYPE) ***"
    echo "This host ($HOSTNAME) is a SUPPRESSED CHAOS TARGET."
    echo "The fault is intentional. Alert is expected noise from the chaos test."
    echo "Suppressed targets: $CHAOS_SOURCES"
    echo "CONFIDENCE: 0.1 -- chaos-induced alert, not a real incident"
    echo ""
    SKIP_ESCALATION=true
    exit 0
  else
    echo ""
    echo "*** NOTE: Chaos exercise running (type: $CHAOS_TYPE) ***"
    echo "Suppressed targets: $CHAOS_SOURCES"
    echo "This host ($HOSTNAME) is NOT a chaos target -- alert is genuine."
    echo "Proceeding with normal triage, but factoring chaos context."
    echo ""
  fi
fi

# ─── Scheduled events check (ASA watchdog reboots) ───
# Checks if gateway.maintenance was set by asa-reboot-watch.sh for a known scheduled event.
# Belt-and-suspenders: the watcher creates gateway.maintenance (caught above at line 46),
# but if the watcher's cron ran slightly late and the maintenance file was just created
# between the check above and now, this catches it.
SCHED_EVENTS_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/config/scheduled-events.json"
if [ -f "$SCHED_EVENTS_FILE" ] && [ "$MAINTENANCE_ACTIVE" = "false" ]; then
  SCHED_MATCH=$(python3 -c "
import json, os, sys
try:
    events = json.load(open('$SCHED_EVENTS_FILE')).get('events', [])
    maint_file = '/home/app-user/gateway.maintenance'
    for ev in events:
        if not ev.get('enabled'): continue
        if ev.get('type') != 'eem_watchdog': continue
        site = ev.get('site', 'nl')
        affects = ev.get('affects', '')
        triage_site = '${TRIAGE_SITE}'
        if site != triage_site and affects != 'all': continue
        if os.path.exists(maint_file):
            try:
                mj = json.load(open(maint_file))
                if mj.get('event_id') == ev['id']:
                    print(ev['suppression']['message'])
                    sys.exit(0)
            except: pass
    print('NO_MATCH')
except Exception:
    print('NO_MATCH')
" 2>/dev/null)
  if [ "$SCHED_MATCH" != "NO_MATCH" ] && [ -n "$SCHED_MATCH" ]; then
    echo ""
    echo "*** SCHEDULED EVENT DETECTED ***"
    echo "$SCHED_MATCH"
    echo "CONFIDENCE: 0.1 — Scheduled ASA reboot, alert is expected maintenance noise"
    echo ""
    SKIP_ESCALATION=true
    exit 0
  fi
fi

# ─── Freedom ISP PPPoE fast-path check ───
# When triaging GR device-down alerts or NL service alerts, check Freedom PPPoE first.
# If Freedom is down, the alert is a secondary symptom — report with high confidence.
if [[ "$HOSTNAME" == gr* && "$RULE_NAME" == *"up/down"* ]] || \
   [[ "$HOSTNAME" == nlpve* && "$RULE_NAME" == *"Service up/down"* ]]; then
  FREEDOM_STATUS=$(python3 -c "
import pexpect, sys, os
pw = os.environ.get('CISCO_ASA_PASSWORD', 'REDACTED_PASSWORD')
try:
    child = pexpect.spawn('ssh -o StrictHostKeyChecking=no -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa -o ConnectTimeout=5 operator@10.0.181.X', timeout=10)
    child.expect('[Pp]assword:')
    child.sendline(pw)
    i = child.expect(['>', '#'], timeout=8)
    if i == 0:
        child.sendline('enable')
        child.expect('[Pp]assword:')
        child.sendline(pw)
        child.expect('#')
    child.sendline('show interface outside_freedom | include address')
    child.expect('#', timeout=5)
    output = child.before.decode()
    child.sendline('exit')
    child.close()
    if 'unassigned' in output:
        print('DOWN')
    else:
        print('UP')
except:
    print('UNKNOWN')
" 2>/dev/null)
  if [ "$FREEDOM_STATUS" = "DOWN" ]; then
    echo ""
    echo "*** FREEDOM ISP OUTAGE — FAST-PATH DIAGNOSIS ***"
    echo "Freedom PPPoE is DOWN (outside_freedom IP unassigned)."
    echo "This alert on $HOSTNAME is a secondary symptom of the Freedom ISP failure."
    echo "xs4all WAN (203.0.113.X) has full S2S tunnel coverage — GR connectivity"
    echo "auto-restores within 1-5 minutes via xs4all tunnels."
    echo ""
    echo "Physical fix: power-cycle Genexis XGS-PON ONT on nl-sw01 Gi1/0/36."
    echo "Tenant QoS: auto-applied (5/2 Mbps per room) via freedom-qos-toggle.sh."
    echo ""
    FINDINGS="Freedom ISP PPPoE outage detected. outside_freedom has no IP. Alert on $HOSTNAME is a secondary symptom. xs4all carrying all tunnels. Physical action needed: ONT power-cycle on sw01 Gi1/0/36."
    echo "CONFIDENCE: 0.95 — Freedom ISP PPPoE outage (fast-path confirmed via ASA)"
    echo ""
    # Continue triage for evidence collection but confidence is already high
  fi
fi

# ─── LibreNMS alert acknowledgment function ───
# Queries LibreNMS for active (state=1) alerts on a hostname and acknowledges them.
# Usage: acknowledge_librenms_alert <hostname> <issue_id>
# Non-fatal: logs warnings on failure, never exits.
acknowledge_librenms_alert() {
  local ack_hostname="$1"
  local ack_issue_id="$2"

  if [ -z "$ack_hostname" ] || [ -z "$ack_issue_id" ]; then
    echo "WARN: acknowledge_librenms_alert called without hostname or issue ID"
    return 0
  fi

  # Query active alerts filtered by hostname
  local alert_ids
  alert_ids=$(curl -sk -H "X-Auth-Token: $LIBRENMS_API_KEY" \
    "${LIBRENMS_URL}/api/v0/alerts?hostname=${ack_hostname}&state=1" 2>/dev/null | \
    python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for alert in data.get('alerts', []):
        if alert.get('state') == 1:
            print(alert['id'])
except Exception:
    pass
" 2>/dev/null) || true

  if [ -z "$alert_ids" ]; then
    echo "No active LibreNMS alerts to acknowledge for $ack_hostname"
    return 0
  fi

  local ack_count=0
  for aid in $alert_ids; do
    if curl -sk -X PUT \
      -H "X-Auth-Token: $LIBRENMS_API_KEY" \
      -H "Content-Type: application/json" \
      -d "{\"state\":2,\"note\":\"Acknowledged by ChatOps triage — $ack_issue_id\"}" \
      "${LIBRENMS_URL}/api/v0/alerts/${aid}" >/dev/null 2>&1; then
      echo "Acknowledged LibreNMS alert $aid for $ack_hostname (YT: $ack_issue_id)"
      ack_count=$((ack_count + 1))
    else
      echo "WARN: Failed to acknowledge LibreNMS alert $aid (continuing)"
    fi
  done
  echo "Acknowledged $ack_count LibreNMS alert(s) for $ack_hostname"
}

# Error propagation: track progress for structured error reporting
CURRENT_STEP="init"
COMPLETED_STEPS=""
ISSUE_ID=""
SHOULD_ESCALATE=false

error_handler() {
  local exit_code=$?
  echo ""
  echo "ERROR_CONTEXT:"
  echo "- Failed at: $CURRENT_STEP"
  echo "- Completed steps: ${COMPLETED_STEPS:-none}"
  echo "- Error: exit code $exit_code"
  echo "- Issue ID: ${ISSUE_ID:-not created}"
  echo "- Host: $HOSTNAME, Rule: $RULE_NAME, Severity: $SEVERITY"
  echo "- Suggested next action: Check host reachability, review error above"

  # Critical alerts MUST escalate even if investigation failed — don't silently swallow them
  if [ "$SEVERITY" = "critical" ] || [ "${FORCE_ESCALATE:-}" = "true" ]; then
    echo ""
    echo "--- FAILSAFE: Critical alert with failed investigation — escalating to Tier 2 ---"
    ESCALATION_MSG="Infra triage FAILED at $CURRENT_STEP (exit $exit_code). Host: $HOSTNAME, Rule: $RULE_NAME ($SEVERITY). Issue: ${ISSUE_ID:-not created}. Investigation incomplete — needs manual Tier 2 review."
    ./skills/escalate-to-claude.sh "${ISSUE_ID:-UNKNOWN}" "$ESCALATION_MSG" 2>&1 || echo "WARN: Failsafe escalation also failed"
  fi
  exit $exit_code
}
trap error_handler ERR

# Load credentials. Searches openclaw-container path first, falls back to app-user repo path.
for d in /root/.openclaw/workspace /home/app-user/.openclaw/workspace /app/claude-gateway; do [ -r "$d/.env" ] && . "$d/.env" && break; done
# Normalise env var names between openclaw .env and app-user .env conventions.
: "${YOUTRACK_TOKEN:=${YOUTRACK_API_TOKEN:-}}"
: "${YOUTRACK_URL:=https://youtrack.example.net}"
: "${LIBRENMS_API_KEY:=${LIBRENMS_NL_KEY:-${LIBRENMS_API_KEY:-}}}"

echo "=== INFRA TRIAGE: $HOSTNAME ==="
echo "Rule: $RULE_NAME"
echo "Severity: $SEVERITY"
echo ""

# ─── Step 0: Check for existing open issues with same host ───
CURRENT_STEP="Step 0 (check existing issues)"
echo "--- Step 0: Checking for existing issues ---"
ISSUE_ID="${EXISTING_ISSUE:-}"
REUSING_ISSUE=false
RELATED_ISSUES=""
LINK_TO_ISSUE=""

if [ -z "$ISSUE_ID" ]; then
  # Search YouTrack for issues with same hostname (within 7 days, including Done/Cancelled)
  EXISTING=$(python3 -c "
import urllib.request, json, ssl, urllib.parse, time
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
query = 'project: $YT_PROJECT Hostname: $HOSTNAME State: -Duplicate sort by: created desc'
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

  # Search for related issues (different hostname, same alert rule, within 12h)
  RELATED=$(python3 -c "
import urllib.request, json, ssl, urllib.parse, time
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
now_ms = int(time.time() * 1000)
query = 'project: $YT_PROJECT Alert Rule: ${RULE_NAME} State: -Done,-Cancelled,-Duplicate sort by: created desc'
url = '${YOUTRACK_URL}/api/issues?query=' + urllib.parse.quote(query) + '&fields=idReadable,created,summary,customFields(name,value(name))&\$top=5'
req = urllib.request.Request(url, headers={'Authorization': 'Bearer ${YOUTRACK_TOKEN}', 'Accept': 'application/json'})
try:
    resp = urllib.request.urlopen(req, context=ctx, timeout=10)
    issues = json.loads(resp.read())
    for issue in issues:
        age_h = (now_ms - issue.get('created', 0)) / 3600000
        if age_h < 12:
            hostname_cf = ''
            for cf in issue.get('customFields', []):
                if cf.get('name') == 'Hostname' and cf.get('value'):
                    hostname_cf = cf['value'] if isinstance(cf['value'], str) else str(cf['value'])
            if hostname_cf != '$HOSTNAME':
                print(issue['idReadable'] + ' (' + issue.get('summary','')[:60] + ')')
except: pass
" 2>/dev/null)
  if [ -n "$RELATED" ]; then
    RELATED_ISSUES="$RELATED"
    echo "Related open issues (same alert rule on other hosts):"
    echo "$RELATED_ISSUES"
  fi
fi

COMPLETED_STEPS="Step 0 (issue check)"
CURRENT_STEP="Step 1 (create/reuse YT issue)"
# ─── Per-host lock: prevent duplicate issues when multiple rules fire simultaneously ───
HOST_LOCK="/tmp/infra-triage-${HOSTNAME}.lock"
HOST_ISSUE_FILE="/tmp/infra-triage-${HOSTNAME}.issue"

if [ "$REUSING_ISSUE" = false ] && [ -z "$ISSUE_ID" ]; then
  if ! mkdir "$HOST_LOCK" 2>/dev/null; then
    # Another triage is running or completed for this host
    echo "Host $HOSTNAME already being triaged (lock exists)"
    # Wait up to 30s for the other triage to write its issue ID
    for i in $(seq 1 30); do
      if [ -f "$HOST_ISSUE_FILE" ]; then
        ISSUE_ID=$(cat "$HOST_ISSUE_FILE")
        echo "Using existing issue: $ISSUE_ID"
        REUSING_ISSUE=true
        # Register this rule under the same issue
        python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'action':'register','hostname':'$HOSTNAME','ruleName':'$RULE_NAME','issueId':'$ISSUE_ID'}).encode()
req = urllib.request.Request('$LIBRENMS_WEBHOOK', data=data, headers={'Content-Type':'application/json'}, method='POST')
try: urllib.request.urlopen(req, context=ctx)
except: pass
" 2>/dev/null
        # Post this rule as a comment on the existing issue
        ./skills/yt-post-comment.sh "$ISSUE_ID" "Additional alert rule for $HOSTNAME: $RULE_NAME ($SEVERITY)" 2>&1 || true
        echo "=== TRIAGE MERGED INTO $ISSUE_ID ==="
        exit 0
      fi
      sleep 1
    done
    echo "WARN: Lock exists but no issue ID found after 30s, proceeding anyway"
    rmdir "$HOST_LOCK" 2>/dev/null
    mkdir "$HOST_LOCK" 2>/dev/null || true
  fi
  # Cleanup lock on exit (keep issue file for other triages)
  trap "rmdir '$HOST_LOCK' 2>/dev/null" EXIT
fi

# ─── Level 1: Create or reuse YouTrack Issue ───
if [ "$REUSING_ISSUE" = false ] && [ -z "$ISSUE_ID" ]; then
  echo ""
  echo "--- Step 1: Creating YouTrack issue ---"

  YT_DESC="LibreNMS alert: $RULE_NAME\nSeverity: $SEVERITY\nHostname: $HOSTNAME\nTimestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  [ -n "$RELATED_ISSUES" ] && YT_DESC="$YT_DESC\n\nRelated open issues (same rule on other hosts):\n$RELATED_ISSUES"

  YT_RESULT=$(./skills/yt-create-issue.sh $YT_PROJECT \
    "Alert: $RULE_NAME on $HOSTNAME" \
    "$(echo -e "$YT_DESC")" 2>&1)
  echo "$YT_RESULT"

  # Extract issue ID (format: PROJECT-NN)
  ISSUE_ID=$(echo "$YT_RESULT" | grep -oP "${YT_PROJECT}-\d+" | head -1)
  if [ -z "$ISSUE_ID" ]; then
    echo "ERROR: Failed to create YouTrack issue"
    echo "$YT_RESULT"
    exit 1
  fi
  echo "Issue created: $ISSUE_ID"

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

  # Write issue ID for other concurrent triages of the same host
  echo "$ISSUE_ID" > "$HOST_ISSUE_FILE"

  # Register issue ID with n8n
  python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'action':'register','hostname':'$HOSTNAME','ruleName':'$RULE_NAME','issueId':'$ISSUE_ID'}).encode()
req = urllib.request.Request('$LIBRENMS_WEBHOOK', data=data, headers={'Content-Type':'application/json'}, method='POST')
try: urllib.request.urlopen(req, context=ctx)
except: pass
" 2>/dev/null || echo "WARN: Failed to register alert with n8n (continuing)"

  # Set YouTrack Custom Fields
  echo "--- Setting custom fields on $ISSUE_ID ---"
  python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
yt_url = '${YOUTRACK_URL}'
yt_token = '${YOUTRACK_TOKEN}'
fields = [
    ('Hostname', '$HOSTNAME'),
    ('Alert Rule', '$RULE_NAME'),
    ('Severity', '$SEVERITY'),
    ('Alert Source', 'LibreNMS'),
]
for name, val in fields:
    data = json.dumps({'issues': [{'idReadable': '$ISSUE_ID'}], 'query': name + ' ' + val}).encode()
    req = urllib.request.Request(yt_url + '/api/commands', data=data, headers={'Content-Type':'application/json', 'Authorization': 'Bearer ' + yt_token}, method='POST')
    try: urllib.request.urlopen(req, context=ctx)
    except Exception as e: print(f'WARN: Failed to set {name}: {e}')
" 2>/dev/null || echo "WARN: Failed to set custom fields (continuing)"
else
  echo ""
  echo "--- Step 1: Reusing issue $ISSUE_ID ---"

  # Still register callback for reused issues
  python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
data = json.dumps({'action':'register','hostname':'$HOSTNAME','ruleName':'$RULE_NAME','issueId':'$ISSUE_ID'}).encode()
req = urllib.request.Request('$LIBRENMS_WEBHOOK', data=data, headers={'Content-Type':'application/json'}, method='POST')
try: urllib.request.urlopen(req, context=ctx)
except: pass
" 2>/dev/null || true
fi
echo ""

COMPLETED_STEPS="Step 0 (issue check), Step 1 (issue ${ISSUE_ID})"
CURRENT_STEP="Step 2 (investigation)"
# ─── Level 2: Investigation ───
FINDINGS=""

# Alert category detection — guides investigation focus
ALERT_CATEGORY="general"
RULE_LOWER=$(echo "$RULE_NAME" | tr '[:upper:]' '[:lower:]')
case "$RULE_LOWER" in
  *"up/down"*|*"ping"*|*"icmp"*|*"unreachable"*) ALERT_CATEGORY="availability" ;;
  *"cpu"*|*"load"*|*"memory"*|*"ram"*|*"swap"*) ALERT_CATEGORY="resource" ;;
  *"disk"*|*"storage"*|*"iscsi"*|*"lun"*|*"io"*) ALERT_CATEGORY="storage" ;;
  *"interface"*|*"port"*|*"bgp"*|*"ospf"*|*"vlan"*|*"network"*) ALERT_CATEGORY="network" ;;
  *"cert"*|*"ssl"*|*"tls"*|*"expir"*) ALERT_CATEGORY="certificate" ;;
  *"service"*|*"process"*|*"systemd"*) ALERT_CATEGORY="service" ;;
esac
echo "Alert category: $ALERT_CATEGORY"

# Step 1.5: Query incident knowledge base for prior resolutions (semantic search)
echo "--- Step 1.5: Querying incident knowledge base (semantic) ---"
KB_QUERY="${HOSTNAME} ${RULE_NAME}"
# Local semantic search (gateway.db synced by repo-sync cron, Ollama on gpu01 reachable directly)
KB_SEARCH="$SCRIPT_DIR/kb-semantic-search.py"
_TRIAGE_GATEWAY_DB="${TRIAGE_GATEWAY_DB:-}"
if [ -z "$_TRIAGE_GATEWAY_DB" ]; then
  if [ -f "/home/node/.claude-data/gateway.db" ]; then
    _TRIAGE_GATEWAY_DB="/home/node/.claude-data/gateway.db"
  elif [ -f "/app/cubeos/claude-context/gateway.db" ]; then
    _TRIAGE_GATEWAY_DB="/app/cubeos/claude-context/gateway.db"
  fi
fi
if [ -f "$KB_SEARCH" ] && [ -f "$_TRIAGE_GATEWAY_DB" ]; then
  PRIOR_KNOWLEDGE=$(GATEWAY_DB="$_TRIAGE_GATEWAY_DB" python3 "$KB_SEARCH" search "${KB_QUERY//\'/\'}" --limit 3 --days 90 --threshold 0.5 --mode hybrid --rewrite 2>/dev/null) || true
else
  # Fallback to SSH if local DB not available
  PRIOR_KNOWLEDGE=$(ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
    -i ~/.ssh/one_key app-user@nl-claude01 \
    "python3 ~/gitlab/n8n/claude-gateway/scripts/kb-semantic-search.py search '${KB_QUERY//\'/\\\'}' --limit 3 --days 90 --threshold 0.5 --mode hybrid --rewrite" 2>/dev/null) || true
fi

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

# Step 2-pre: NetBox CMDB Lookup — establish device identity FIRST
echo "--- Step 2-pre: NetBox CMDB Lookup ---"
NETBOX_RESULT=""
NETBOX_DEVICE_TYPE=""
NETBOX_SITE=""
NETBOX_IP=""
NETBOX_ROLE=""
if [ -f "$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" ]; then
  NETBOX_RESULT=$("$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" device "$HOSTNAME" 2>/dev/null || echo "No NetBox match for $HOSTNAME")
  # If device lookup returned nothing, try search
  if echo "$NETBOX_RESULT" | grep -q "^No NetBox match\|^No device found\|^Error"; then
    NETBOX_RESULT=$("$SCRIPT_DIR/netbox-lookup/netbox-lookup.sh" search "$HOSTNAME" 2>/dev/null || echo "No NetBox match for $HOSTNAME")
  fi
  echo "$NETBOX_RESULT" | head -20
  # Extract key identity fields
  NETBOX_DEVICE_TYPE=$(echo "$NETBOX_RESULT" | grep -iE "type:|role:" | head -1 | sed 's/.*: *//' || true)
  NETBOX_SITE=$(echo "$NETBOX_RESULT" | grep -iE "site:" | head -1 | sed 's/.*: *//' || true)
  NETBOX_IP=$(echo "$NETBOX_RESULT" | grep -iE "primary.*ip:" | head -1 | sed 's/.*: *//' || true)
  FINDINGS="$FINDINGS\nNetBox CMDB: $(echo "$NETBOX_RESULT" | head -10 | tr '\n' ' | ')"
else
  echo "NetBox lookup not available (netbox-lookup.sh not found)"
  FINDINGS="$FINDINGS\nNetBox: not available"
fi
COMPLETED_STEPS="$COMPLETED_STEPS, Step 2-pre (NetBox)"
echo ""

# Step 2-chaos: Chaos Baseline Lookup (intelligence bridge — quantitative resilience data)
echo "--- Step 2-chaos: Chaos Baseline Lookup ---"
CHAOS_BASELINES=""
GATEWAY_DB="$HOME/gitlab/products/cubeos/claude-context/gateway.db"
if [ -f "$GATEWAY_DB" ]; then
  CHAOS_BASELINES=$(sqlite3 "$GATEWAY_DB" "
    SELECT experiment_id, verdict, convergence_seconds, mttd_seconds, started_at
    FROM chaos_experiments
    WHERE targets LIKE '%${HOSTNAME}%'
    ORDER BY started_at DESC LIMIT 3;
  " 2>/dev/null || true)
  if [ -n "$CHAOS_BASELINES" ]; then
    echo "CHAOS_BASELINES:"
    echo "$CHAOS_BASELINES" | while IFS='|' read -r eid verdict conv mttd started; do
      echo "  $eid: $verdict (convergence=${conv}s, mttd=${mttd}s) @ $started"
    done
    # Also get pass rate and resilience score
    PASS_RATE=$(sqlite3 "$GATEWAY_DB" "
      SELECT ROUND(100.0 * SUM(CASE WHEN verdict='PASS' THEN 1 ELSE 0 END) / COUNT(*), 1)
      FROM chaos_experiments
      WHERE targets LIKE '%${HOSTNAME}%'
      AND started_at > datetime('now', '-90 days');
    " 2>/dev/null || echo "N/A")
    echo "  Pass rate (90d): ${PASS_RATE}%"
    FINDINGS="$FINDINGS\nChaos Baselines: $CHAOS_BASELINES (pass rate: ${PASS_RATE}%)"
  else
    echo "No chaos experiments found for $HOSTNAME"
  fi
else
  echo "Gateway DB not available"
fi
COMPLETED_STEPS="$COMPLETED_STEPS, Step 2-chaos (Chaos Baselines)"
echo ""

# Step 2-kb: CLAUDE.md + Memory Knowledge (procedural context from IaC repos)
echo "--- Step 2-kb: CLAUDE.md + Memory Knowledge ---"
KB_CONTEXT=""
if [ -f "$SCRIPT_DIR/claude-knowledge-lookup.sh" ]; then
  KB_CONTEXT=$("$SCRIPT_DIR/claude-knowledge-lookup.sh" "$HOSTNAME" "$ALERT_CATEGORY" --site "$SITE_ID" 2>/dev/null) || true
  if [ -n "$KB_CONTEXT" ] && ! echo "$KB_CONTEXT" | grep -q "^No relevant"; then
    echo "$KB_CONTEXT" | head -20
    FINDINGS="$FINDINGS\n\n**Procedural Knowledge (CLAUDE.md + Memory):**\n$KB_CONTEXT"
  else
    echo "No relevant CLAUDE.md/memory knowledge found"
  fi
else
  echo "claude-knowledge-lookup.sh not available"
fi
COMPLETED_STEPS="$COMPLETED_STEPS, Step 2-kb (knowledge)"
echo ""

# Step 2a: Classify device via LibreNMS
echo "--- Step 2a: Classifying device via LibreNMS ---"
DEVICE_JSON=$(python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request('${LIBRENMS_URL}/api/v0/devices/${HOSTNAME}', headers={'X-Auth-Token': '${LIBRENMS_API_KEY}'})
try:
    resp = urllib.request.urlopen(req, context=ctx)
    data = json.loads(resp.read())
    d = data.get('devices', [{}])[0]
    print(json.dumps({'os': d.get('os','unknown'), 'type': d.get('type',''), 'sysName': d.get('sysName',''), 'hardware': d.get('hardware',''), 'sysDescr': d.get('sysDescr',''), 'status': d.get('status', False), 'device_id': d.get('device_id','')}))
except Exception as e:
    print(json.dumps({'os': 'unknown', 'type': '', 'sysName': '', 'hardware': '', 'sysDescr': '', 'status': False, 'device_id': '', 'error': str(e)}))
" 2>/dev/null)
DEVICE_OS=$(echo "$DEVICE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('os','unknown'))" 2>/dev/null || echo "unknown")
DEVICE_TYPE=$(echo "$DEVICE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('type',''))" 2>/dev/null || echo "")
DEVICE_SYSNAME=$(echo "$DEVICE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('sysName',''))" 2>/dev/null || echo "")
DEVICE_HW=$(echo "$DEVICE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('hardware',''))" 2>/dev/null || echo "")
DEVICE_ID=$(echo "$DEVICE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('device_id',''))" 2>/dev/null || echo "")
echo "LibreNMS: os=$DEVICE_OS type=$DEVICE_TYPE sysName=$DEVICE_SYSNAME hw=$DEVICE_HW"
FINDINGS="$FINDINGS\nLibreNMS Classification: os=$DEVICE_OS, type=$DEVICE_TYPE, sysName=$DEVICE_SYSNAME, hw=$DEVICE_HW"

# Step 2b: Fetch syslog (network devices, PVE hosts, anything sending syslog)
echo "--- Step 2b: Checking syslog ---"
SYSLOG_ERRORS=$(fetch_syslog "$HOSTNAME" 30 "error|fail|down|restart|critical|warn|denied|unreachable" 2>/dev/null | grep -v 'terminal-session:' || true)
SYSLOG_RECENT=$(fetch_syslog "$HOSTNAME" 20 2>/dev/null | grep -v 'terminal-session:' || true)
if [ -n "$SYSLOG_ERRORS" ] && ! echo "$SYSLOG_ERRORS" | grep -q "^No .* syslog"; then
  echo "Syslog errors/warnings (last 30 matches):"
  echo "$SYSLOG_ERRORS"
  FINDINGS="$FINDINGS\n\nSyslog errors/warnings:\n$SYSLOG_ERRORS"
else
  echo "No error-level syslog entries found"
fi
if [ -n "$SYSLOG_RECENT" ] && ! echo "$SYSLOG_RECENT" | grep -q "^No .* syslog"; then
  echo ""
  echo "Recent syslog (last 20 lines):"
  echo "$SYSLOG_RECENT"
  FINDINGS="$FINDINGS\n\nRecent syslog:\n$SYSLOG_RECENT"
else
  echo "No syslog available for $HOSTNAME (may not send syslog to ${SYSLOG_HOST})"
fi
echo ""

# Terminal session commands (what was someone doing on this host?)
TERMINAL_SESSIONS=$(fetch_terminal_sessions "$HOSTNAME" 15 2>/dev/null || true)
if [ -n "$TERMINAL_SESSIONS" ]; then
  echo "Recent terminal sessions (last 15 commands):"
  echo "$TERMINAL_SESSIONS"
  FINDINGS="$FINDINGS\n\nRecent terminal sessions:\n$TERMINAL_SESSIONS"
else
  echo "No terminal session logs found for $HOSTNAME"
fi
echo ""

# Step 2c: Find host in PVE (only if proxmox/linux type)
echo "--- Step 2c: Identifying host in PVE ---"
PVE_RESULT=$(grep -r "hostname: $HOSTNAME" ${IAC_REPO}/pve/ 2>/dev/null || echo "Not found in PVE")
echo "$PVE_RESULT"

PVE_HOST=""
VMID=""
HOST_TYPE=""
if echo "$PVE_RESULT" | grep -q "lxc/"; then
  HOST_TYPE="LXC"
  PVE_HOST=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/pve/\([^/]*\)/.*|\1|')
  VMID=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/lxc/\([0-9]*\)\.conf.*|\1|')
elif echo "$PVE_RESULT" | grep -q "qemu/"; then
  HOST_TYPE="QEMU"
  PVE_HOST=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/pve/\([^/]*\)/.*|\1|')
  VMID=$(echo "$PVE_RESULT" | head -1 | sed 's|.*/qemu/\([0-9]*\)\.conf.*|\1|')
fi

# --- VMID UID Schema Decode ---
# Schema: S(1) NN(2) VV(2) TT(2) RR(2) = 9 digits
# S=Site (1=NL,2=GR), NN=PVE Node, VV=VLAN, TT=Automation Tag, RR=Resource ID
# WARNING: Some VMIDs have drifted from schema — always cross-check against actual PVE host
VMID_DECODED=""
VMID_DRIFT=""
if [ -n "$VMID" ] && [ ${#VMID} -eq 9 ]; then
  VMID_SITE="${VMID:0:1}"
  VMID_NODE="${VMID:1:2}"
  VMID_VLAN="${VMID:3:2}"
  VMID_TAG="${VMID:5:2}"
  VMID_RES="${VMID:7:2}"

  # Decode site
  case "$VMID_SITE" in
    1) VMID_SITE_NAME="NL (nl)" ;;
    2) VMID_SITE_NAME="GR (gr)" ;;
    *) VMID_SITE_NAME="Unknown site $VMID_SITE" ;;
  esac

  # Decode automation tag
  case "$VMID_TAG" in
    00) VMID_TAG_NAME="OOB Access" ;;
    01) VMID_TAG_NAME="Management/Orchestration" ;;
    02) VMID_TAG_NAME="Network Infrastructure" ;;
    03) VMID_TAG_NAME="Firewall/IDS" ;;
    04) VMID_TAG_NAME="Load Balancing/HA" ;;
    05) VMID_TAG_NAME="VPN/Secure Tunnels" ;;
    06) VMID_TAG_NAME="Hypervisors/Cluster" ;;
    07) VMID_TAG_NAME="Monitoring/Analytics" ;;
    08) VMID_TAG_NAME="Backup/Restore" ;;
    09) VMID_TAG_NAME="Storage (NFS/iSCSI)" ;;
    10) VMID_TAG_NAME="Database/Web Servers" ;;
    11) VMID_TAG_NAME="Media Servers" ;;
    12) VMID_TAG_NAME="Collaboration Tools" ;;
    13) VMID_TAG_NAME="DMZ Servers" ;;
    14) VMID_TAG_NAME="Edge/IoT" ;;
    15) VMID_TAG_NAME="Finance/Investments" ;;
    16) VMID_TAG_NAME="Workstations" ;;
    17) VMID_TAG_NAME="Mail Servers" ;;
    18) VMID_TAG_NAME="Lab Nodes" ;;
    85) VMID_TAG_NAME="K8s Infrastructure" ;;
    *) VMID_TAG_NAME="Tag $VMID_TAG" ;;
  esac

  VMID_DECODED="VMID decode: Site=$VMID_SITE_NAME, Node=pve${VMID_NODE}, VLAN=$VMID_VLAN, Category=$VMID_TAG_NAME, Instance=$VMID_RES"
  echo "$VMID_DECODED"

  # Cross-check: does the VMID-encoded node match the actual PVE host?
  if [ -n "$PVE_HOST" ]; then
    ACTUAL_NODE=$(echo "$PVE_HOST" | grep -oE 'pve[0-9]+' | sed 's/pve//')
    if [ -n "$ACTUAL_NODE" ] && [ "$ACTUAL_NODE" != "$VMID_NODE" ]; then
      VMID_DRIFT="DRIFT WARNING: VMID says pve${VMID_NODE} but actually on pve${ACTUAL_NODE} — VMID may need update"
      echo "*** $VMID_DRIFT ***"
    fi
  fi

  # Cross-check: does the VMID-encoded site match the triage site?
  EXPECTED_SITE=""
  case "$TRIAGE_SITE" in
    nl) EXPECTED_SITE="1" ;;
    gr) EXPECTED_SITE="2" ;;
  esac
  if [ -n "$EXPECTED_SITE" ] && [ "$VMID_SITE" != "$EXPECTED_SITE" ]; then
    SITE_DRIFT="DRIFT WARNING: VMID says site $VMID_SITE but triaging site $TRIAGE_SITE — VMID may need update"
    echo "*** $SITE_DRIFT ***"
    VMID_DRIFT="${VMID_DRIFT:+$VMID_DRIFT; }$SITE_DRIFT"
  fi
elif [ -n "$VMID" ]; then
  VMID_DECODED="VMID $VMID has non-standard length (${#VMID} digits, expected 9) — cannot decode schema"
  echo "$VMID_DECODED"
fi

SSH_OPTS="-i ${TRIAGE_SSH_KEY:-/home/app-user/.ssh/one_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

# Step 2d: Physical layer context from 03_Lab (non-fatal)
echo "--- Step 2d: Physical layer context (03_Lab) ---"
LAB_PORT_MAP=$(./skills/lab-lookup/lab-lookup.sh port-map "$HOSTNAME" 2>/dev/null) || true
if [ -n "$LAB_PORT_MAP" ] && ! echo "$LAB_PORT_MAP" | grep -q "^No data"; then
  echo "$LAB_PORT_MAP"
  FINDINGS="$FINDINGS\n\nPhysical layer (03_Lab):\n$LAB_PORT_MAP"
else
  echo "No physical layer data found for $HOSTNAME"
fi

# For availability/network/storage alerts: include NIC config of the relevant host
LAB_NIC_HOST="${PVE_HOST:-$HOSTNAME}"
if [ "$ALERT_CATEGORY" = "availability" ] || [ "$ALERT_CATEGORY" = "network" ] || [ "$ALERT_CATEGORY" = "storage" ]; then
  LAB_NIC=$(./skills/lab-lookup/lab-lookup.sh nic-config "$LAB_NIC_HOST" 2>/dev/null) || true
  if [ -n "$LAB_NIC" ] && ! echo "$LAB_NIC" | grep -q "^No data"; then
    echo "NIC config ($LAB_NIC_HOST):"
    echo "$LAB_NIC"
    FINDINGS="$FINDINGS\n\nNIC config ($LAB_NIC_HOST, from 03_Lab):\n$LAB_NIC"
  fi
fi
echo ""

if [ -z "$PVE_HOST" ]; then
  # Not a PVE container — classify and investigate based on LibreNMS OS type
  echo "Not found in PVE. Classifying by LibreNMS OS: $DEVICE_OS"

  # Check network configs (Cisco IOS/IOS-XE/ASA)
  NET_RESULT=$(ls ${IAC_REPO}/network/configs/*/"$HOSTNAME" 2>/dev/null \
    || ls ${IAC_REPO}/network/configs/*/"$DEVICE_SYSNAME" 2>/dev/null \
    || echo "Not found in network configs")
  echo "$NET_RESULT"

  case "$DEVICE_OS" in
    ios|iosxe|asa)
      FINDINGS="$FINDINGS\nDevice class: Network ($DEVICE_OS, $DEVICE_HW)"
      FINDINGS="$FINDINGS\nConfig: $NET_RESULT"
      FINDINGS="$FINDINGS\nAction: Check config in network/configs/, verify interface status via LibreNMS. Changes via network/scripts/deploy.sh (Netmiko)."
      ;;
    ping|linux)
      DEVICE_DESC=$(echo "$DEVICE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('sysDescr',''))" 2>/dev/null || echo "")
      FINDINGS="$FINDINGS\nDevice class: $DEVICE_OS ($DEVICE_SYSNAME, sysDescr: $DEVICE_DESC)"

      echo "--- Checking LibreNMS ARP for MAC address ---"
      DEVICE_MAC=$(python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
req = urllib.request.Request('${LIBRENMS_URL}/api/v0/resources/ip/arp/${HOSTNAME}', headers={'X-Auth-Token': '${LIBRENMS_API_KEY}'})
try:
    resp = urllib.request.urlopen(req, context=ctx)
    data = json.loads(resp.read())
    arp = data.get('arp', [{}])[0]
    mac = arp.get('mac_address', '')
    print(f'MAC: {mac}')
except: print('MAC: unknown')
" 2>/dev/null || echo "MAC: unknown")
      echo "$DEVICE_MAC"
      FINDINGS="$FINDINGS\n$DEVICE_MAC"

      echo "--- Ping check from PVE host ---"
      PING_CHECK=$(ssh $SSH_OPTS $SSH_RELAY "ping -c 2 -W 2 $HOSTNAME 2>&1 | tail -2" 2>&1 | grep -v "^Warning:" || echo "Ping failed")
      echo "$PING_CHECK"
      FINDINGS="$FINDINGS\nPing from PVE: $PING_CHECK"

      SUBNET=$(echo "$HOSTNAME" | sed 's/\.[0-9]*$//')
      echo "--- Checking VLAN neighbors ---"
      NEIGHBOR_CHECK=$(ssh $SSH_OPTS $SSH_RELAY "for ip in ${SUBNET}.1 ${SUBNET}.2 ${SUBNET}.4 ${SUBNET}.5; do ping -c 1 -W 1 \$ip > /dev/null 2>&1 && echo \"\$ip: UP\" || echo \"\$ip: DOWN\"; done" 2>&1 | grep -v "^Warning:" || echo "Could not check")
      echo "$NEIGHBOR_CHECK"
      FINDINGS="$FINDINGS\nVLAN neighbors:\n$NEIGHBOR_CHECK"

      UP_COUNT=$(echo "$NEIGHBOR_CHECK" | grep -c "UP" || echo "0")
      if [ "$UP_COUNT" -gt 0 ]; then
        FINDINGS="$FINDINGS\nDiagnosis: VLAN healthy ($UP_COUNT neighbors up). Isolated device failure."
        FINDINGS="$FINDINGS\nAction: Check upstream switch port (may be admin-down). Switch $SWITCH_REF requires password SSH — use Netmiko deploy script or manual check. If port is up, likely PoE/hardware issue."
      else
        FINDINGS="$FINDINGS\nDiagnosis: VLAN-wide outage (no neighbors responding). Check switch VLAN config and uplink."
      fi
      ;;
    apc)
      FINDINGS="$FINDINGS\nDevice class: Power/UPS ($DEVICE_HW)"
      FINDINGS="$FINDINGS\nAction: Check LibreNMS for battery/load/runtime. Power issues may affect downstream devices."
      ;;
    dsm)
      FINDINGS="$FINDINGS\nDevice class: Synology NAS ($DEVICE_HW)"
      FINDINGS="$FINDINGS\nWARNING: NEVER restart — hosts NFS/iSCSI for K8s + Docker."

      # Determine SSH user (syno01=admin, syno02=synoadm)
      SYNO_USER="admin"
      echo "$HOSTNAME" | grep -qi "syno02" && SYNO_USER="synoadm"

      echo ""
      echo "--- Synology deep investigation ($HOSTNAME as $SYNO_USER) ---"

      # Storage pool & volume status
      echo "--- Storage pools ---"
      SYNO_STORAGE=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "cat /proc/mdstat 2>/dev/null | grep -E '^md|blocks' | head -20" 2>&1 | grep -v "^Warning:" || echo "SSH failed")
      echo "$SYNO_STORAGE"
      FINDINGS="$FINDINGS\n\nRAID status:\n$SYNO_STORAGE"

      # Volume usage
      echo "--- Volume usage ---"
      SYNO_DF=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "df -h /volume1 /volume2 2>/dev/null" 2>&1 | grep -v "^Warning:" || echo "SSH failed")
      echo "$SYNO_DF"
      FINDINGS="$FINDINGS\n\nVolume usage:\n$SYNO_DF"

      # System load and memory
      echo "--- System load ---"
      SYNO_LOAD=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "uptime && free -m | head -2" 2>&1 | grep -v "^Warning:" || echo "SSH failed")
      echo "$SYNO_LOAD"
      FINDINGS="$FINDINGS\n\nSystem load:\n$SYNO_LOAD"

      # Top I/O processes (if iotop available, otherwise top)
      echo "--- Top processes ---"
      SYNO_TOP=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "ps aux --sort=-%mem | head -10" 2>&1 | grep -v "^Warning:" || echo "SSH failed")
      echo "$SYNO_TOP"
      FINDINGS="$FINDINGS\n\nTop processes:\n$SYNO_TOP"

      # iSCSI target status (syno01 specific)
      if echo "$HOSTNAME" | grep -qi "syno01"; then
        echo "--- iSCSI targets ---"
        SYNO_ISCSI=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "cat /proc/net/iet/volume 2>/dev/null | head -20 || ls /sys/kernel/scst_tgt/targets/iscsi/ 2>/dev/null || echo 'iSCSI status unavailable'" 2>&1 | grep -v "^Warning:" || echo "SSH failed")
        echo "$SYNO_ISCSI"
        FINDINGS="$FINDINGS\n\niSCSI targets:\n$SYNO_ISCSI"

        # Check network throughput on storage VLAN
        echo "--- Storage network (VLAN 88) ---"
        SYNO_NET=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "ifconfig ovs_bond1 2>/dev/null | grep -E 'RX bytes|TX bytes|errors|dropped' || ip -s link show ovs_bond1 2>/dev/null | head -10" 2>&1 | grep -v "^Warning:" || echo "SSH failed")
        echo "$SYNO_NET"
        FINDINGS="$FINDINGS\n\nStorage network:\n$SYNO_NET"
      fi

      # Disk SMART quick check
      echo "--- Disk SMART status ---"
      SYNO_SMART=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "for d in /dev/sata[1-6]; do smartctl -H \$d 2>/dev/null | grep -E 'result|Reallocated|Current_Pending' | head -3; done 2>/dev/null || echo 'smartctl unavailable'" 2>&1 | grep -v "^Warning:" || echo "SSH failed")
      echo "$SYNO_SMART"
      FINDINGS="$FINDINGS\n\nDisk SMART:\n$SYNO_SMART"

      # DSM logs (recent storage/system errors)
      echo "--- Recent DSM logs ---"
      SYNO_LOGS=$(ssh $SSH_OPTS $SYNO_USER@$HOSTNAME "synolog --get 2>/dev/null | tail -15 || dmesg | grep -iE 'error|warn|fail|i/o|ata|scsi' | tail -10 || journalctl --no-pager -n 10 2>/dev/null" 2>&1 | grep -v "^Warning:" || echo "Logs unavailable")
      echo "$SYNO_LOGS"
      FINDINGS="$FINDINGS\n\nRecent logs:\n$SYNO_LOGS"
      ;;
    pfsense)
      FINDINGS="$FINDINGS\nDevice class: pfSense VPN gateway"
      FINDINGS="$FINDINGS\nAction: Check tunnel status, pfctl rules. VPN disruption affects GR site connectivity."
      ;;
    *)
      FINDINGS="$FINDINGS\nDevice class: $DEVICE_OS / $DEVICE_TYPE ($DEVICE_HW)"
      FINDINGS="$FINDINGS\nConfig: $NET_RESULT"
      FINDINGS="$FINDINGS\nAction: Manual review required."
      ;;
  esac
else
  echo "Found: $HOST_TYPE $VMID on $PVE_HOST"
  [ -n "$VMID_DECODED" ] && echo "$VMID_DECODED"
  [ -n "$VMID_DRIFT" ] && echo "*** $VMID_DRIFT ***"
  # Set VMID and PVE Host custom fields
  if [ "$REUSING_ISSUE" = false ]; then
    python3 -c "
import urllib.request, json, ssl
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
yt_url = '${YOUTRACK_URL}'
yt_token = '${YOUTRACK_TOKEN}'
for name, val in [('VMID', '$VMID'), ('PVE Host', '$PVE_HOST')]:
    data = json.dumps({'issues': [{'idReadable': '$ISSUE_ID'}], 'query': name + ' ' + val}).encode()
    req = urllib.request.Request(yt_url + '/api/commands', data=data, headers={'Content-Type':'application/json', 'Authorization': 'Bearer ' + yt_token}, method='POST')
    try: urllib.request.urlopen(req, context=ctx)
    except: pass
" 2>/dev/null || true
  fi
  FINDINGS="$FINDINGS\nType: $HOST_TYPE $VMID on $PVE_HOST"
  [ -n "$VMID_DECODED" ] && FINDINGS="$FINDINGS\n$VMID_DECODED"
  [ -n "$VMID_DRIFT" ] && FINDINGS="$FINDINGS\n⚠️ $VMID_DRIFT"

  # Step 3: Check status on Proxmox
  echo ""
  echo "--- Step 3: Checking status on $PVE_HOST ---"

  if [ "$HOST_TYPE" = "LXC" ]; then
    STATUS_RESULT=$(ssh $SSH_OPTS root@$PVE_HOST "pct status $VMID && pct config $VMID | grep -E 'hostname|cores|memory|net|rootfs'" 2>&1 | grep -v "^Warning: Permanently added" || echo "SSH failed")
  else
    STATUS_RESULT=$(ssh $SSH_OPTS root@$PVE_HOST "qm status $VMID && qm config $VMID | grep -E 'name|cores|memory|net|scsi|boot'" 2>&1 | grep -v "^Warning: Permanently added" || echo "SSH failed")
  fi
  echo "$STATUS_RESULT"
  CT_STATUS=$(echo "$STATUS_RESULT" | head -1)
  FINDINGS="$FINDINGS\nStatus: $CT_STATUS"

  # Step 4: Check connectivity (if running)
  if echo "$STATUS_RESULT" | grep -qi "running"; then
    echo ""
    echo "--- Step 4: Checking connectivity ---"
    if [ "$HOST_TYPE" = "LXC" ]; then
      PING_RESULT=$(ssh $SSH_OPTS root@$PVE_HOST "pct exec $VMID -- ping -c 2 -W 3 10.0.181.X 2>&1 | tail -3" 2>&1 | grep -v "^Warning: Permanently added" || echo "Ping failed")
    else
      PING_RESULT="QEMU - ping check skipped"
    fi
    echo "$PING_RESULT"
    FINDINGS="$FINDINGS\nNetwork: $PING_RESULT"
  else
    FINDINGS="$FINDINGS\nNetwork: Container/VM not running, connectivity check skipped"
  fi
fi

# Step 4b: K8s-specific diagnostics (if hostname matches k8s-*)
if echo "$HOSTNAME" | grep -qi "k8s"; then
  echo ""
  echo "--- Step 4b: K8s diagnostics for $HOSTNAME ---"

  K8S_NODE="$HOSTNAME"

  echo "--- Node status ---"
  K8S_NODE_STATUS=$(kctl get node "$K8S_NODE" -o wide 2>&1 || echo "Node not found in cluster")
  echo "$K8S_NODE_STATUS"
  FINDINGS="$FINDINGS\nK8s node: $K8S_NODE_STATUS"

  echo "--- Node conditions ---"
  K8S_CONDITIONS=$(kctl get node "$K8S_NODE" -o jsonpath='{range .status.conditions[*]}{.type}={.status} ({.reason}) {"\n"}{end}' 2>/dev/null || echo "Could not get conditions")
  echo "$K8S_CONDITIONS"
  FINDINGS="$FINDINGS\nK8s conditions: $K8S_CONDITIONS"

  echo "--- Pods on this node (non-Running) ---"
  K8S_PODS=$(kctl get pods -A --field-selector "spec.nodeName=$K8S_NODE" 2>/dev/null | grep -v Running | grep -v Completed | grep -v "NAMESPACE" | head -10 || echo "All pods healthy or node unreachable")
  echo "${K8S_PODS:-All pods Running}"
  FINDINGS="$FINDINGS\nK8s unhealthy pods: ${K8S_PODS:-None}"

  echo "--- Recent events on node ---"
  K8S_EVENTS=$(kctl get events -A --field-selector "involvedObject.name=$K8S_NODE" --sort-by='.lastTimestamp' 2>/dev/null | tail -5 || echo "No recent events")
  echo "$K8S_EVENTS"
  FINDINGS="$FINDINGS\nK8s events: $K8S_EVENTS"

  # Control plane deep investigation (if controller node)
  if echo "$HOSTNAME" | grep -qi "ctrlr"; then
    echo ""
    echo "=== CONTROL PLANE DEEP INVESTIGATION ==="

    echo "--- Control plane pods on this node ---"
    K8S_CP=$(kctl get pods -n kube-system -l tier=control-plane --field-selector "spec.nodeName=$K8S_NODE" -o wide 2>/dev/null | head -10 || echo "Could not check control plane")
    echo "$K8S_CP"
    FINDINGS="$FINDINGS\nK8s control plane: $K8S_CP"

    # etcd health
    echo "--- etcd pods ---"
    ETCD_PODS=$(kctl get pods -n kube-system -l component=etcd -o wide 2>&1)
    echo "$ETCD_PODS"
    FINDINGS="$FINDINGS\n\netcd pods:\n$ETCD_PODS"

    # etcd logs
    for ETCD_POD in $(kctl get pods -n kube-system -l component=etcd -o name 2>/dev/null); do
      ETCD_NAME=$(basename "$ETCD_POD")
      echo "--- etcd logs: $ETCD_NAME ---"
      ETCD_LOGS=$(kctl logs "$ETCD_POD" -n kube-system --tail=20 2>&1 | grep -iE "error|warn|timeout|leader|election" | tail -10)
      if [ -n "$ETCD_LOGS" ]; then
        echo "$ETCD_LOGS"
        FINDINGS="$FINDINGS\n\netcd errors ($ETCD_NAME):\n$ETCD_LOGS"
      else
        echo "No errors in recent logs"
      fi
    done

    # apiserver status
    echo "--- kube-apiserver pods ---"
    API_PODS=$(kctl get pods -n kube-system -l component=kube-apiserver -o wide 2>&1)
    echo "$API_PODS"
    FINDINGS="$FINDINGS\n\napiserver pods:\n$API_PODS"

    # CP resource usage
    echo "--- Control plane resource usage ---"
    CP_TOP=$(kctl top pods -n kube-system -l 'component in (kube-apiserver,etcd,kube-controller-manager,kube-scheduler)' 2>&1 || echo "metrics-server unavailable")
    echo "$CP_TOP"
    FINDINGS="$FINDINGS\n\nControl plane resource usage:\n$CP_TOP"
  fi

  echo "--- Cluster overview ---"
  K8S_OVERVIEW=$(kctl get nodes -o wide 2>/dev/null || echo "Cannot reach cluster")
  echo "$K8S_OVERVIEW"
  FINDINGS="$FINDINGS\nK8s cluster: $K8S_OVERVIEW"
fi

echo ""

# Step 5: Check Docker services
echo "--- Step 5: Checking Docker services ---"
DOCKER_RESULT=$(ls ${IAC_REPO}/docker/"$HOSTNAME"/ 2>/dev/null && grep 'image:' ${IAC_REPO}/docker/"$HOSTNAME"/*/docker-compose.yml 2>/dev/null | head -10 || echo "No Docker services")
echo "$DOCKER_RESULT"
FINDINGS="$FINDINGS\nServices: $DOCKER_RESULT"
echo ""

# Step 6: Query LibreNMS API
echo "--- Step 6: Querying LibreNMS ---"
NMS_RESULT=$(curl -sk -H "X-Auth-Token: $LIBRENMS_API_KEY" "$LIBRENMS_URL/api/v0/devices/$HOSTNAME" 2>/dev/null | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin).get('devices',[{}])[0]
  print(f'OS: {d.get(\"os\",\"?\")}, Status: {d.get(\"status\",\"?\")}, Uptime: {d.get(\"uptime\",\"?\")}s, Hardware: {d.get(\"hardware\",\"?\")}')
except:
  print('LibreNMS API query failed')
" 2>&1)
echo "$NMS_RESULT"
FINDINGS="$FINDINGS\nLibreNMS: $NMS_RESULT"
echo ""

COMPLETED_STEPS="Step 0 (issue check), Step 1 (issue ${ISSUE_ID}), Step 2 (investigation)"
CURRENT_STEP="Step 3 (post findings to YT)"
# ─── Level 2: Post findings to YouTrack ───
echo "--- Step 7: Posting findings to YouTrack ---"

RECURRENCE_NOTE=""
if [ "$REUSING_ISSUE" = true ]; then
  RECURRENCE_NOTE="
** RECURRING ALERT — reusing existing issue **"
fi

RELATED_NOTE=""
if [ -n "$RELATED_ISSUES" ]; then
  RELATED_NOTE="
Related open issues (same rule on other hosts):
$RELATED_ISSUES"
fi

# ─── Build structured Markdown report for YouTrack ───

# Severity badge
case "$SEVERITY" in
  critical) SEV_BADGE="**Critical**" ;;
  warning)  SEV_BADGE="Warning" ;;
  *)        SEV_BADGE="$SEVERITY" ;;
esac

# Extract NetBox role from compact result line
NB_ROLE=$(echo "$NETBOX_RESULT" | grep -oP 'role=\K[^ ]+' || true)

# Device identity table rows
ID_ROWS="| Field | Value |
|-------|-------|"
if [ -n "$PVE_HOST" ]; then
  ID_ROWS="$ID_ROWS
| Host | \`$HOSTNAME\` — $HOST_TYPE \`$VMID\` on \`$PVE_HOST\` |"
else
  ID_ROWS="$ID_ROWS
| Host | \`$HOSTNAME\` — ${DEVICE_OS:-unknown} |"
fi
[ -n "$DEVICE_HW" ] && [ "$DEVICE_HW" != "unknown" ] && ID_ROWS="$ID_ROWS
| Hardware | $DEVICE_HW |"
[ -n "$NB_ROLE" ] && ID_ROWS="$ID_ROWS
| Role | $NB_ROLE |"
[ -n "$NETBOX_SITE" ] && ID_ROWS="$ID_ROWS
| Site | $NETBOX_SITE |"
[ -n "$NETBOX_IP" ] && ID_ROWS="$ID_ROWS
| IP | \`$NETBOX_IP\` |"
if [ -n "$VMID_DECODED" ]; then
  VMID_SHORT=$(echo "$VMID_DECODED" | sed 's/VMID decode: //')
  ID_ROWS="$ID_ROWS
| VMID | $VMID_SHORT |"
fi

# Status lines
STATUS_SECTION=""
[ -n "${CT_STATUS:-}" ] && STATUS_SECTION="- **PVE Status:** $CT_STATUS"
if [ -n "${PING_RESULT:-}" ]; then
  PING_SHORT=$(echo "$PING_RESULT" | grep -oE '[0-9]+% packet loss' || echo "$PING_RESULT" | head -1)
  STATUS_SECTION="${STATUS_SECTION}
- **Connectivity:** $PING_SHORT"
fi
[ -n "${NMS_RESULT:-}" ] && STATUS_SECTION="${STATUS_SECTION}
- **LibreNMS:** $NMS_RESULT"
if [ -n "${DOCKER_RESULT:-}" ] && ! echo "$DOCKER_RESULT" | grep -q "^No Docker"; then
  DOCKER_COUNT=$(echo "$DOCKER_RESULT" | grep -c 'image:' || echo "0")
  STATUS_SECTION="${STATUS_SECTION}
- **Docker:** $DOCKER_COUNT service(s)"
fi

# K8s summary (if applicable)
K8S_SECTION=""
if [ -n "${K8S_NODE_STATUS:-}" ] && ! echo "$K8S_NODE_STATUS" | grep -q "not found"; then
  K8S_NODE_SHORT=$(echo "$K8S_NODE_STATUS" | awk 'NR==2{print $2, $3, $5}')
  K8S_SECTION="- **K8s Node:** $K8S_NODE_SHORT"
  if [ -n "${K8S_PODS:-}" ] && [ "$K8S_PODS" != "None" ] && ! echo "$K8S_PODS" | grep -qi "all pods"; then
    K8S_POD_COUNT=$(echo "$K8S_PODS" | wc -l)
    K8S_SECTION="${K8S_SECTION}
- **Unhealthy Pods:** $K8S_POD_COUNT"
  fi
fi
[ -n "$K8S_SECTION" ] && STATUS_SECTION="${STATUS_SECTION}
${K8S_SECTION}"

# Syslog section (only if errors found, capped)
SYSLOG_SECTION=""
if [ -n "${SYSLOG_ERRORS:-}" ] && ! echo "$SYSLOG_ERRORS" | grep -q "^No .* syslog"; then
  SYSLOG_CAPPED=$(echo "$SYSLOG_ERRORS" | head -10)
  SYSLOG_TOTAL=$(echo "$SYSLOG_ERRORS" | wc -l)
  SYSLOG_SECTION="### Recent Errors

\`\`\`
$SYSLOG_CAPPED
\`\`\`"
  [ "$SYSLOG_TOTAL" -gt 10 ] && SYSLOG_SECTION="${SYSLOG_SECTION}
*($SYSLOG_TOTAL total entries — showing first 10)*"
fi

# Terminal sessions section (operator commands around the time of alert)
TERMINAL_SECTION=""
if [ -n "${TERMINAL_SESSIONS:-}" ]; then
  TERM_CAPPED=$(echo "$TERMINAL_SESSIONS" | head -10)
  TERM_TOTAL=$(echo "$TERMINAL_SESSIONS" | wc -l)
  TERMINAL_SECTION="### Recent Terminal Sessions

\`\`\`
$TERM_CAPPED
\`\`\`"
  [ "$TERM_TOTAL" -gt 10 ] && TERMINAL_SECTION="${TERMINAL_SECTION}
*($TERM_TOTAL total entries — showing first 10)*"
fi

# Prior incidents section
PRIOR_SECTION=""
if [ -n "${PRIOR_KNOWLEDGE:-}" ]; then
  PRIOR_SECTION="### Prior Incidents
"
  while IFS='|' read -r pk_issue pk_host pk_alert pk_resolution pk_confidence pk_date pk_site pk_sim; do
    PRIOR_SECTION="${PRIOR_SECTION}
- **$pk_issue** ($pk_date) — $pk_resolution *(confidence: $pk_confidence)*"
  done <<< "$PRIOR_KNOWLEDGE"
fi

# Related issues section
RELATED_SECTION=""
if [ -n "${RELATED_ISSUES:-}" ]; then
  RELATED_SECTION="### Related Issues

$RELATED_ISSUES"
fi

# Drift warning
DRIFT_SECTION=""
[ -n "${VMID_DRIFT:-}" ] && DRIFT_SECTION="
> **Warning:** $VMID_DRIFT"

# Recurrence notice
RECUR_SECTION=""
[ "$REUSING_ISSUE" = true ] && RECUR_SECTION="
> **Recurring alert** — reusing existing issue."

# Assemble final comment
COMMENT="## Automated Triage — $RULE_NAME

**Host:** \`$HOSTNAME\` | **Severity:** $SEV_BADGE | **Category:** $ALERT_CATEGORY
${RECUR_SECTION}${DRIFT_SECTION}

### Device Identity

$ID_ROWS

### Current Status

${STATUS_SECTION:-No status data collected.}

${SYSLOG_SECTION}

${TERMINAL_SECTION}

${PRIOR_SECTION}

${RELATED_SECTION}

---
*Automated triage by OpenClaw · Confidence: ${TRIAGE_CONFIDENCE:-N/A}*"

./skills/yt-post-comment.sh "$ISSUE_ID" "$COMMENT" 2>&1 || echo "WARN: Failed to post YT comment (continuing)"
echo ""

# ─── Level 2: Escalation decision ───
echo ""
SHOULD_ESCALATE=false

if [ "${SKIP_ESCALATION:-}" = "true" ]; then
  echo "--- Step 8: Skipping escalation (SKIP_ESCALATION=true, correlated burst) ---"
else
  # Always escalate (original behavior) unless suppressed
  SHOULD_ESCALATE=true

  # Add extra context for recurring/forced escalations
  ESCALATION_REASON="standard triage"
  [ "${FORCE_ESCALATE:-}" = "true" ] && ESCALATION_REASON="flapping alert"
  [ "$REUSING_ISSUE" = true ] && ESCALATION_REASON="${ESCALATION_REASON} + recurring"

  echo "--- Step 8: Escalating to Claude Code ($ESCALATION_REASON) ---"
  TRIAGE_CONFIDENCE="${TRIAGE_CONFIDENCE:-0.5}" \
  TRIAGE_COMPLETED_STEPS="$COMPLETED_STEPS" \
  TRIAGE_HOSTNAME="$HOSTNAME" \
  TRIAGE_ALERT_RULE="$RULE_NAME" \
  TRIAGE_SEVERITY="$SEVERITY" \
  TRIAGE_SITE="$SITE" \
  ./skills/escalate-to-claude.sh "$ISSUE_ID" "Infrastructure alert: $HOSTNAME - $RULE_NAME. Escalation reason: $ESCALATION_REASON. Level 2 findings posted as YT comment." 2>&1 || echo "WARN: Escalation failed (continuing)"
fi

# ─── Step 9: Acknowledge LibreNMS alerts for this host ───
echo "--- Step 9: Acknowledging LibreNMS alerts ---"
acknowledge_librenms_alert "$HOSTNAME" "$ISSUE_ID"

# ─── Step 10: Structured JSON summary (machine-parseable) ───
ESCALATION_REASON_JSON="${ESCALATION_REASON:-none}"
echo ""
echo "TRIAGE_JSON:$(python3 -c "
import json
print(json.dumps({
    'issueId': '$ISSUE_ID',
    'hostname': '$HOSTNAME',
    'ruleName': '$RULE_NAME',
    'severity': '$SEVERITY',
    'reused': $( [ "$REUSING_ISSUE" = true ] && echo "True" || echo "False" ),
    'escalated': $( [ "$SHOULD_ESCALATE" = true ] && echo "True" || echo "False" ),
    'escalationReason': '$ESCALATION_REASON_JSON',
    'hostType': '${HOST_TYPE:-unknown}',
    'vmid': '${VMID:-}',
    'pveHost': '${PVE_HOST:-}',
    'vmidDecoded': '${VMID_DECODED:-}',
    'vmidDrift': '${VMID_DRIFT:-}',
    'deviceOs': '${DEVICE_OS:-unknown}',
    'relatedIssues': [r.split(' ')[0] for r in '''$RELATED_ISSUES'''.strip().split('\n') if r.strip()],
}))" 2>/dev/null || echo '{"issueId":"'$ISSUE_ID'","error":"json_failed"}')"

# Validate TRIAGE_JSON schema (non-fatal)
python3 -c "
import json, sys
try:
    # Re-generate the same JSON to validate
    data = json.loads(json.dumps({
        'issueId': '$ISSUE_ID',
        'hostname': '$HOSTNAME',
        'ruleName': '$RULE_NAME',
        'severity': '$SEVERITY',
        'reused': $( [ "$REUSING_ISSUE" = true ] && echo "True" || echo "False" ),
        'escalated': $( [ "$SHOULD_ESCALATE" = true ] && echo "True" || echo "False" ),
        'escalationReason': '$ESCALATION_REASON_JSON',
        'hostType': '${HOST_TYPE:-unknown}',
        'vmid': '${VMID:-}',
        'pveHost': '${PVE_HOST:-}',
        'deviceOs': '${DEVICE_OS:-unknown}',
    }))
    required = ['issueId', 'hostname', 'severity', 'escalated']
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
echo "$(date -u +%FT%TZ)|${HOSTNAME}|${RULE_NAME}|${TRIAGE_SITE:-nl}|${OUTCOME}|${TRIAGE_CONFIDENCE:-0}|${TRIAGE_DURATION}|${ISSUE_ID}" >> "$TRIAGE_LOG" 2>/dev/null || true

# Store episodic memory for OpenClaw (via SSH to app-user where DB lives)
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
  -i ~/.ssh/one_key app-user@nl-claude01 \
  "sqlite3 ~/gitlab/products/cubeos/claude-context/gateway.db \"
    INSERT OR REPLACE INTO openclaw_memory (category, key, value, issue_id)
    VALUES ('triage', '${HOSTNAME}:${RULE_NAME}', '${OUTCOME} (confidence: ${TRIAGE_CONFIDENCE:-0}, duration: ${TRIAGE_DURATION}s, escalated: ${SHOULD_ESCALATE})', '${ISSUE_ID}');
  \"" 2>/dev/null || true

echo ""
echo "=== TRIAGE COMPLETE: $ISSUE_ID ==="
