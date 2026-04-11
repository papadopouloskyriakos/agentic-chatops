#!/bin/bash
# build-investigation-plan.sh — Generate investigation plan via Haiku before Claude Code execution
#
# Called by Runner workflow "Build Plan" node, between Query Knowledge and Build Prompt.
# Uses Claude Haiku to generate a structured investigation plan based on alert context.
#
# Usage:
#   build-investigation-plan.sh <issue_id> <alert_category> "<summary>" "<kb_context>"
#
# Output: JSON with plan steps, tools, hypothesis, confidence
# Cost: ~$0.008 per plan (Haiku)
#
# Source: Atlas Agents Plan-and-Execute pattern (A3)
#   github.com/agulli/atlas-agents/ch01_react_from_scratch/online/atlas_v01_plan_and_execute.py

set -uo pipefail

ISSUE_ID="${1:-unknown}"
ALERT_CATEGORY="${2:-availability}"
SUMMARY="${3:-No summary}"
KB_CONTEXT="${4:-}"

DB="${GATEWAY_DB:-/app/cubeos/claude-context/gateway.db}"
LOG_TAG="[planner]"

# Load API key
ENV_FILE="/app/claude-gateway/.env"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $LOG_TAG $*" >&2; }

# If no API key, return empty plan (graceful degradation)
if [ -z "$ANTHROPIC_API_KEY" ]; then
  log "WARN: No ANTHROPIC_API_KEY — skipping plan generation"
  echo '{"plan_generated":false,"steps":[],"reason":"no_api_key"}'
  exit 0
fi

# Category-specific planning prompts
case "$ALERT_CATEGORY" in
  availability)
    CATEGORY_GUIDANCE="Focus on: service status checks, process health, recent changes, resource exhaustion, dependency chain analysis. Common tools: SSH (systemctl, docker ps, pct list), NetBox (device lookup), LibreNMS (alert history)."
    ;;
  kubernetes)
    CATEGORY_GUIDANCE="Focus on: pod status, node conditions, etcd health, resource limits, recent deployments, PVC status. Common tools: kubectl (get/describe/logs), NetBox (node inventory), Prometheus (metrics)."
    ;;
  network)
    CATEGORY_GUIDANCE="Focus on: interface status, BGP peer state, VPN tunnel health, routing table, packet loss, DNS resolution. Common tools: SSH (show run, show interface, ping, traceroute), NetBox (cable/interface mapping)."
    ;;
  storage)
    CATEGORY_GUIDANCE="Focus on: disk usage, iSCSI target status, ZFS pool health, NFS mount status, SMART data. Common tools: SSH (df, zpool status, iscsiadm), Proxmox MCP (storage info)."
    ;;
  security)
    CATEGORY_GUIDANCE="Focus on: CrowdSec decisions, failed auth attempts, open ports, vulnerability scan results, firewall ACLs. Common tools: SSH (cscli, fail2ban, iptables), scanner VMs (nmap, nuclei)."
    ;;
  certificate)
    CATEGORY_GUIDANCE="Focus on: certificate expiry dates, chain validation, renewal status, ACME/certbot logs. Common tools: SSH (openssl s_client, certbot), testssl."
    ;;
  resource)
    CATEGORY_GUIDANCE="Focus on: CPU/memory/disk usage trends, swap pressure, process resource consumption, OOM kills. Common tools: SSH (top, free, iostat, dmesg), Prometheus (node_exporter metrics)."
    ;;
  *)
    CATEGORY_GUIDANCE="Determine the nature of the issue first, then investigate systematically."
    ;;
esac

# Query AWX for applicable runbooks (microsoft/sre-agent pattern: "Knowledge Base as runbooks")
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AWX_RUNBOOKS=""
AWX_SECTION=""
if [ -x "$SCRIPT_DIR/query-awx-runbooks.sh" ]; then
  AWX_JSON=$("$SCRIPT_DIR/query-awx-runbooks.sh" "$ISSUE_ID" "$ALERT_CATEGORY" 2>/dev/null)
  AWX_COUNT=$(echo "$AWX_JSON" | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo 0)
  if [ "${AWX_COUNT:-0}" -gt 0 ]; then
    AWX_RUNBOOKS=$(echo "$AWX_JSON" | python3 -c "
import json, sys
templates = json.loads(sys.stdin.read())
lines = []
for t in templates:
    lines.append(f'- AWX Template {t[\"id\"]}: {t[\"name\"]} (playbook: {t[\"playbook\"]})')
    if t.get('ask_variables'):
        lines.append(f'  Accepts extra_vars on launch (host, dry_run, etc.)')
    lines.append(f'  Launch: curl -sk -X POST \"{t[\"awx_url\"]}/api/v2/job_templates/{t[\"id\"]}/launch/\" -H \"Authorization: Bearer AWX_TOKEN\" -H \"Content-Type: application/json\" -d \\'{{\"extra_vars\": {{\"target_host\": \"HOSTNAME\"}}}}\\'')
print('\n'.join(lines))
" 2>/dev/null)
    AWX_SECTION="
AVAILABLE AWX RUNBOOKS (proven Ansible playbooks — prefer these over ad-hoc investigation):
${AWX_RUNBOOKS}

When an AWX runbook matches the alert, include it as a remediation step in your plan. The agent can trigger AWX jobs via the API."
    log "Found $AWX_COUNT AWX runbooks for $ALERT_CATEGORY"
  fi
fi

# Extract hostname from issue ID for AWX hostname-specific lookup
ALERT_HOSTNAME=""
if echo "$SUMMARY" | grep -qoE '[a-z]{2}[a-z0-9]{4,}[0-9]{2}[a-z]+[0-9]+'; then
  ALERT_HOSTNAME=$(echo "$SUMMARY" | grep -oE '[a-z]{2}[a-z0-9]{4,}[0-9]{2}[a-z]+[0-9]+' | head -1)
  # Re-query AWX with the actual hostname if different from issue ID
  if [ -n "$ALERT_HOSTNAME" ] && [ "$ALERT_HOSTNAME" != "$ISSUE_ID" ]; then
    HOST_AWX=$("$SCRIPT_DIR/query-awx-runbooks.sh" "$ALERT_HOSTNAME" "$ALERT_CATEGORY" 2>/dev/null)
    HOST_COUNT=$(echo "$HOST_AWX" | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo 0)
    if [ "${HOST_COUNT:-0}" -gt 0 ] && [ "$HOST_COUNT" != "$AWX_COUNT" ]; then
      EXTRA=$(echo "$HOST_AWX" | python3 -c "
import json, sys
for t in json.loads(sys.stdin.read()):
    if t.get('hostname_match'):
        print(f'- AWX Template {t[\"id\"]}: {t[\"name\"]} (HOST-SPECIFIC match for $ALERT_HOSTNAME)')
" 2>/dev/null)
      [ -n "$EXTRA" ] && AWX_SECTION="${AWX_SECTION}
${EXTRA}"
    fi
  fi
fi

# Build the planner prompt
PLANNER_PROMPT="You are a planning agent for an infrastructure operations platform managing 310 devices across 2 sites (NL + GR). Generate a concise investigation plan for the following alert.

ALERT: ${SUMMARY}
CATEGORY: ${ALERT_CATEGORY}
${KB_CONTEXT:+
PRIOR KNOWLEDGE (from incident database):
${KB_CONTEXT}
}
GUIDANCE: ${CATEGORY_GUIDANCE}
${AWX_SECTION}
Generate a plan with 3-5 concrete investigation steps. Each step must be independently verifiable.
If an AWX runbook matches the situation, include 'Run AWX template ID' as a remediation step with the appropriate extra_vars.

Respond in JSON ONLY:
{
  \"hypothesis\": \"One-sentence theory of what's wrong\",
  \"steps\": [
    {
      \"id\": 1,
      \"action\": \"What to do (specific command or check)\",
      \"tool\": \"Which tool to use (ssh/kubectl/netbox/prometheus/mcp)\",
      \"expected\": \"What a healthy result looks like\",
      \"if_unhealthy\": \"What to do if this step reveals a problem\"
    }
  ],
  \"tools_needed\": [\"list of tools/MCPs this plan requires\"],
  \"estimated_minutes\": 5,
  \"plan_confidence\": 0.8
}"

# Call Haiku API — write prompt to temp file to avoid shell quoting issues
PROMPT_FILE=$(mktemp /tmp/plan-prompt-XXXXXX.txt)
echo "$PLANNER_PROMPT" > "$PROMPT_FILE"

PAYLOAD=$(python3 -c "
import json, sys
with open('$PROMPT_FILE') as f:
    prompt = f.read()
print(json.dumps({
    'model': 'claude-haiku-4-5-20251001',
    'max_tokens': 1200,
    'temperature': 0,
    'messages': [{'role': 'user', 'content': prompt}]
}))
" 2>/dev/null)
rm -f "$PROMPT_FILE"

if [ -z "$PAYLOAD" ]; then
  log "WARN: Failed to build planner payload"
  echo '{"plan_generated":false,"steps":[],"reason":"payload_build_failed"}'
  exit 0
fi

API_RESPONSE=$(curl -s --connect-timeout 10 --max-time 30 -X POST "https://api.anthropic.com/v1/messages" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d "$PAYLOAD" 2>/dev/null)

# Track usage
echo "$API_RESPONSE" | python3 -c "
import json, sys, sqlite3
try:
    data = json.loads(sys.stdin.read())
    usage = data.get('usage', {})
    model = data.get('model', 'claude-haiku-4-5-20251001')
    in_tok = usage.get('input_tokens', 0)
    out_tok = usage.get('output_tokens', 0)
    if in_tok > 0:
        cost = (in_tok * 0.80 + out_tok * 4.0) / 1_000_000
        db = sqlite3.connect('$DB')
        db.execute('INSERT INTO llm_usage (tier, model, issue_id, input_tokens, output_tokens, cost_usd) VALUES (2, ?, ?, ?, ?, ?)',
            (model, '$ISSUE_ID', in_tok, out_tok, round(cost, 6)))
        db.commit()
        db.close()
except: pass
" 2>/dev/null

# Parse plan from response (robust: handles trailing commas, comments, markdown)
PLAN=$(echo "$API_RESPONSE" | python3 -c "
import json, sys, re
try:
    data = json.loads(sys.stdin.read())
    text = data.get('content', [{}])[0].get('text', '{}')
    # Strip markdown code fences
    text = re.sub(r'\`\`\`json\s*', '', text)
    text = re.sub(r'\`\`\`\s*$', '', text)
    # Extract JSON block (greedy match for outermost braces)
    depth = 0; start = -1; end = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0: start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0: end = i + 1; break
    if start >= 0 and end > start:
        raw = text[start:end]
        # Fix common LLM JSON issues: trailing commas before } or ]
        raw = re.sub(r',\s*([}\]])', r'\1', raw)
        plan = json.loads(raw)
        plan['plan_generated'] = True
        if 'steps' not in plan or not plan['steps']:
            plan = {'plan_generated': False, 'steps': [], 'reason': 'no_steps_in_response'}
        elif len(plan['steps']) > 7:
            plan['steps'] = plan['steps'][:7]
        print(json.dumps(plan))
    else:
        print(json.dumps({'plan_generated': False, 'steps': [], 'reason': 'no_json_block_found'}))
except Exception as e:
    print(json.dumps({'plan_generated': False, 'steps': [], 'reason': str(e)[:100]}))
" 2>/dev/null)

if [ -z "$PLAN" ]; then
  log "WARN: Plan parsing failed"
  echo '{"plan_generated":false,"steps":[],"reason":"parse_failed"}'
  exit 0
fi

# Enrich plan with AWX template references
if [ -n "$AWX_JSON" ] && [ "$AWX_JSON" != "[]" ]; then
  AWX_TMP=$(mktemp /tmp/awx-enrich-XXXXXX.json)
  echo "$AWX_JSON" > "$AWX_TMP"
  PLAN=$(echo "$PLAN" | python3 -c "
import json, sys
plan = json.loads(sys.stdin.read())
try:
    with open('$AWX_TMP') as f:
        awx_templates = json.load(f)
    plan['awx_templates'] = [{'id': t['id'], 'name': t['name'], 'playbook': t['playbook']} for t in awx_templates]
    plan['awx_url'] = awx_templates[0].get('awx_url', '') if awx_templates else ''
except:
    plan['awx_templates'] = []
print(json.dumps(plan))
" 2>/dev/null)
  rm -f "$AWX_TMP"
fi

# Log plan summary
STEP_COUNT=$(echo "$PLAN" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(len(d.get('steps',[])))" 2>/dev/null)
CONFIDENCE=$(echo "$PLAN" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('plan_confidence','?'))" 2>/dev/null)
AWX_TMPL_COUNT=$(echo "$PLAN" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(len(d.get('awx_templates',[])))" 2>/dev/null)
log "Plan for $ISSUE_ID: $STEP_COUNT steps, confidence=$CONFIDENCE, awx_templates=$AWX_TMPL_COUNT"

echo "$PLAN"
