#!/bin/bash
# query-awx-runbooks.sh — Find applicable AWX job templates for an alert
#
# Called by build-investigation-plan.sh to enrich the Haiku planner with
# proven remediation playbooks. Returns JSON array of matching templates.
#
# Usage:
#   query-awx-runbooks.sh <hostname> <alert_category> [site]
#
# Output: JSON array of matching AWX templates with launch instructions
#
# Source: microsoft/sre-agent pattern — "Knowledge Base as machine-readable runbooks"
#         Adapted to use existing AWX/Ansible infrastructure instead of new YAML format.

set -uo pipefail

HOSTNAME="${1:-}"
ALERT_CATEGORY="${2:-availability}"
SITE="${3:-nl}"

# AWX credentials
NL_AWX_URL="https://awx.example.net"
NL_AWX_TOKEN="REDACTED_bacaec8e"
GR_AWX_URL="https://gr-awx.example.net"
GR_AWX_TOKEN="${GR_AWX_TOKEN:-8N1p4G8TYoWyQtYiRJknuoxYgQffs0NP}"

# Select AWX instance based on site
if [[ "$HOSTNAME" == grskg* ]] || [ "$SITE" = "gr" ]; then
  AWX_URL="$GR_AWX_URL"
  AWX_TOKEN="$GR_AWX_TOKEN"
  SITE_LABEL="GR"
else
  AWX_URL="$NL_AWX_URL"
  AWX_TOKEN="$NL_AWX_TOKEN"
  SITE_LABEL="NL"
fi

# Alert category → relevant playbook keywords mapping
case "$ALERT_CATEGORY" in
  availability)
    KEYWORDS="maintenance|reboot|validation|startup|shutdown|post_reboot|restore"
    ;;
  kubernetes)
    KEYWORDS="k8s|drain|restore_cluster|validate_storage|kubernetes"
    ;;
  storage)
    KEYWORDS="storage|synology|dsm|iscsi|validate_storage|collect_pve"
    ;;
  certificate)
    KEYWORDS="cert|sync_cert|cert-manager|ssl"
    ;;
  network)
    KEYWORDS="pihole|dns|snmp|haproxy|edge|vpn"
    ;;
  security)
    KEYWORDS="snmp|ssh_key|terminal_logging|cleanup"
    ;;
  maintenance)
    KEYWORDS="maintenance|full_maintenance|maintenance_mode|maintenance_window|update|weekly"
    ;;
  resource)
    KEYWORDS="maintenance|collect|update|cleanup"
    ;;
  *)
    KEYWORDS="maintenance|validation|update"
    ;;
esac

# Query AWX API for templates
TEMPLATES=$(curl -sk --connect-timeout 5 --max-time 10 \
  -H "Authorization: Bearer $AWX_TOKEN" \
  "${AWX_URL}/api/v2/job_templates/?page_size=50" 2>/dev/null)

if [ -z "$TEMPLATES" ]; then
  echo '[]'
  exit 0
fi

# Write to temp file to avoid shell quoting issues
TMPFILE=$(mktemp /tmp/awx-templates-XXXXXX.json)
echo "$TEMPLATES" > "$TMPFILE"

# Filter and format matching templates
python3 -c "
import json, sys, re

try:
    with open('$TMPFILE') as f:
        data = json.load(f)
except:
    print('[]')
    sys.exit(0)

templates = data.get('results', [])
keywords = '$KEYWORDS'
hostname = '$HOSTNAME'
site = '$SITE_LABEL'
awx_url = '$AWX_URL'

matches = []
keyword_pattern = re.compile(keywords, re.IGNORECASE)

for t in templates:
    name = t.get('name', '')
    playbook = t.get('playbook', '')

    # Match by keyword in name or playbook path
    if keyword_pattern.search(name) or keyword_pattern.search(playbook):
        matches.append({
            'id': t['id'],
            'name': name,
            'playbook': playbook,
            'ask_variables': t.get('ask_variables_on_launch', False),
            'site': site,
            'awx_url': awx_url,
            'launch_cmd': f'curl -sk -X POST \"{awx_url}/api/v2/job_templates/{t[\"id\"]}/launch/\" -H \"Authorization: Bearer TOKEN\" -H \"Content-Type: application/json\"',
            'description': t.get('description', ''),
        })

# Also check for hostname-specific templates
for t in templates:
    name = t.get('name', '')
    if hostname and hostname.lower() in name.lower():
        # Avoid duplicates
        if not any(m['id'] == t['id'] for m in matches):
            matches.append({
                'id': t['id'],
                'name': name,
                'playbook': t.get('playbook', ''),
                'ask_variables': t.get('ask_variables_on_launch', False),
                'site': site,
                'awx_url': awx_url,
                'launch_cmd': f'curl -sk -X POST \"{awx_url}/api/v2/job_templates/{t[\"id\"]}/launch/\" -H \"Authorization: Bearer TOKEN\" -H \"Content-Type: application/json\"',
                'hostname_match': True,
            })

# Sort: hostname matches first, then by relevance
matches.sort(key=lambda x: (not x.get('hostname_match', False), x['name']))

print(json.dumps(matches[:5]))  # Top 5 matches
" 2>/dev/null || echo '[]'

rm -f "$TMPFILE"
