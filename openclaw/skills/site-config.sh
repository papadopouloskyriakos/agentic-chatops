#!/bin/bash
# Site configuration for multi-site triage scripts
# Usage: source ./skills/site-config.sh [--site nl|gr]
# Defaults to NL site if no --site flag is provided.
# Sets: YT_PROJECT, IAC_REPO, SSH_RELAY, SWITCH_REF, LIBRENMS_WEBHOOK, PROM_WEBHOOK, SECURITY_WEBHOOK, CROWDSEC_WEBHOOK, K8S_CONTEXT, SITE_PREFIX

# Parse --site from caller's args (passed as $TRIAGE_SITE or from env)
SITE="${TRIAGE_SITE:-nl}"

# Auto-detect site from hostname argument if not explicitly set
auto_detect_site() {
  local hostname="$1"
  if echo "$hostname" | grep -qi "^gr"; then
    echo "gr"
  else
    echo "nl"
  fi
}

# Host-portable path detection. Inside OpenClaw container, /home/node/infrastructure
# is a ro bind-mount of /root/gitlab/infrastructure on the host. On app-user@nl-claude01
# the same source lives at /app/infrastructure. This block lets the
# triage scripts run from either host without modification. Caller can override with TRIAGE_IAC_BASE.
_TRIAGE_IAC_BASE="${TRIAGE_IAC_BASE:-}"
if [ -z "$_TRIAGE_IAC_BASE" ]; then
  if [ -d "/home/node/infrastructure" ]; then
    _TRIAGE_IAC_BASE="/home/node/infrastructure"
  elif [ -d "/app/infrastructure" ]; then
    _TRIAGE_IAC_BASE="/app/infrastructure"
  else
    _TRIAGE_IAC_BASE="/home/node/infrastructure"
  fi
fi
# SSH key — same dual-host pattern. Used by fetch_syslog and fetch_terminal_sessions below.
if [ -z "${TRIAGE_SSH_KEY:-}" ]; then
  if [ -r "/home/app-user/.ssh/one_key" ]; then
    export TRIAGE_SSH_KEY="/home/app-user/.ssh/one_key"
  elif [ -r "/home/app-user/.ssh/one_key" ]; then
    export TRIAGE_SSH_KEY="/home/app-user/.ssh/one_key"
  fi
fi

case "$SITE" in
  nl|NL|nl)
    export YT_PROJECT="IFRNLLEI01PRD"
    export IAC_REPO="${_TRIAGE_IAC_BASE}/nl/production"
    export SSH_RELAY="root@nl-pve01"
    export SWITCH_REF="nl-sw01"
    export LIBRENMS_WEBHOOK="https://n8n.example.net/webhook/librenms-alert"
    export PROM_WEBHOOK="https://n8n.example.net/webhook/prometheus-alert"
    export SECURITY_WEBHOOK="https://n8n.example.net/webhook/security-alert"
    export CROWDSEC_WEBHOOK="https://n8n.example.net/webhook/crowdsec-alert"
    export K8S_CONTEXT=""
    export SITE_PREFIX="nl"
    export SITE_ID="nl"
    export SYSLOG_HOST="nlsyslogng01"
    export SYSLOG_BASE="/mnt/logs/syslog-ng"
    ;;
  gr|GR|gr)
    export YT_PROJECT="IFRGRSKG01PRD"
    export IAC_REPO="${_TRIAGE_IAC_BASE}/gr/production"
    export SSH_RELAY="root@gr-pve01"
    export SWITCH_REF="gr-sw01"
    export LIBRENMS_WEBHOOK="https://n8n.example.net/webhook/librenms-alert-gr"
    export PROM_WEBHOOK="https://n8n.example.net/webhook/prometheus-alert-gr"
    export SECURITY_WEBHOOK="https://n8n.example.net/webhook/security-alert-gr"
    export CROWDSEC_WEBHOOK="https://n8n.example.net/webhook/crowdsec-alert-gr"
    export K8S_CONTEXT="gr"
    export SITE_PREFIX="gr"
    export SITE_ID="gr"
    export SYSLOG_HOST="grsyslogng01"
    export SYSLOG_BASE="/mnt/logs/syslog-ng"
    # Override LibreNMS to GR instance
    export LIBRENMS_URL="https://gr-nms01.example.net"
    export LIBRENMS_API_KEY="${LIBRENMS_GR_API_KEY:-REDACTED_LIBRENMS_GR_KEY}"
    ;;
  *)
    echo "ERROR: Unknown site '$SITE'. Use --site nl or --site gr"
    exit 1
    ;;
esac

# CrowdSec CTI API (optional, free tier: 30 queries/week)
# Set CROWDSEC_CTI_KEY in .env on OpenClaw container to enable
export CROWDSEC_CTI_KEY="${CROWDSEC_CTI_KEY:-}"

# AbuseIPDB (optional, free tier: 1000 checks/day)
# Set ABUSEIPDB_KEY in .env on OpenClaw container to enable
export ABUSEIPDB_KEY="${ABUSEIPDB_KEY:-}"
# GreyNoise Community API: free, no auth needed (used directly in triage.sh)

# NetBox CMDB — single instance for all sites
export NETBOX_URL="${NETBOX_URL:-https://netbox.example.net}"
export NETBOX_TOKEN="${NETBOX_TOKEN:-}"

# kubectl wrapper that adds --context for non-default sites
kctl() {
  if [ -n "$K8S_CONTEXT" ]; then
    kubectl --context "$K8S_CONTEXT" "$@"
  else
    kubectl "$@"
  fi
}

# Fetch syslog for a host from the site's syslog-ng server
# Usage: fetch_syslog <hostname> [lines] [grep_pattern]
# Searches last 3 days of logs (today + 2 prior), returns last N matching lines.
# Reports SSH failures visibly (does not suppress errors).
fetch_syslog() {
  local hostname="$1"
  local lines="${2:-50}"
  local pattern="${3:-}"
  local ssh_opts="-i ${TRIAGE_SSH_KEY:-/home/app-user/.ssh/one_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

  # Build list of log paths for last 3 days (today + 2 prior)
  local logpaths=""
  for offset in 0 1 2; do
    local d=$(date -u -d "$offset days ago" +%Y-%m-%d 2>/dev/null || date -u +%Y-%m-%d)
    local y=$(echo "$d" | cut -d- -f1)
    local m=$(echo "$d" | cut -d- -f2)
    logpaths="$logpaths ${SYSLOG_BASE}/${hostname}/${y}/${m}/${hostname}-${d}.log"
  done

  # Test SSH connectivity first (visible diagnostic on failure)
  if ! ssh $ssh_opts root@${SYSLOG_HOST} "true" 2>/dev/null; then
    echo "WARN: Cannot SSH to syslog server ${SYSLOG_HOST} — syslog lookup skipped"
    return 0
  fi

  if [ -n "$pattern" ]; then
    ssh $ssh_opts root@${SYSLOG_HOST} "cat $logpaths 2>/dev/null | grep -iE '$pattern' | tail -$lines || echo 'No matching syslog for $hostname (checked 3 days)'" 2>&1 | grep -v "^Warning:"
  else
    ssh $ssh_opts root@${SYSLOG_HOST} "cat $logpaths 2>/dev/null | tail -$lines || echo 'No syslog for $hostname (checked 3 days)'" 2>&1 | grep -v "^Warning:"
  fi
}

# Fetch terminal session commands for a host from syslog-ng
# Usage: fetch_terminal_sessions <hostname> [lines]
# Searches last 3 days of logs, returns last N terminal-session entries.
# Filters out syslog-ng dedup noise ("message repeated N times").
fetch_terminal_sessions() {
  local hostname="$1"
  local lines="${2:-15}"
  local ssh_opts="-i ${TRIAGE_SSH_KEY:-/home/app-user/.ssh/one_key} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

  # Build list of log paths for last 3 days (today + 2 prior)
  local logpaths=""
  for offset in 0 1 2; do
    local d=$(date -u -d "$offset days ago" +%Y-%m-%d 2>/dev/null || date -u +%Y-%m-%d)
    local y=$(echo "$d" | cut -d- -f1)
    local m=$(echo "$d" | cut -d- -f2)
    logpaths="$logpaths ${SYSLOG_BASE}/${hostname}/${y}/${m}/${hostname}-${d}.log"
  done

  if ! ssh $ssh_opts root@${SYSLOG_HOST} "true" 2>/dev/null; then
    echo "WARN: Cannot SSH to syslog server ${SYSLOG_HOST} — terminal session lookup skipped"
    return 0
  fi

  ssh $ssh_opts root@${SYSLOG_HOST} \
    "cat $logpaths 2>/dev/null | grep 'terminal-session:' | grep -v 'message repeated' | tail -$lines || true" \
    2>&1 | grep -v "^Warning:"
}
