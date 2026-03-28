#!/bin/bash
# Site configuration for multi-site triage scripts
# Usage: source ./skills/site-config.sh [--site nl|gr]
# Defaults to NL site if no --site flag is provided.
# Sets: YT_PROJECT, IAC_REPO, SSH_RELAY, SWITCH_REF, LIBRENMS_WEBHOOK, PROM_WEBHOOK, K8S_CONTEXT, SITE_PREFIX

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

case "$SITE" in
  nl|NL|nl)
    export YT_PROJECT="IFRNLLEI01PRD"
    export IAC_REPO="/home/node/infrastructure/nl/production"
    export SSH_RELAY="nl-pve01"
    export SWITCH_REF="nl-sw01"
    export LIBRENMS_WEBHOOK="https://n8n.example.net/webhook/librenms-alert"
    export PROM_WEBHOOK="https://n8n.example.net/webhook/prometheus-alert"
    export K8S_CONTEXT=""
    export SITE_PREFIX="nl"
    export SITE_ID="nl"
    export SYSLOG_HOST="nlsyslogng01"
    export SYSLOG_BASE="/mnt/logs/syslog-ng"
    ;;
  gr|GR|gr)
    export YT_PROJECT="IFRGRSKG01PRD"
    export IAC_REPO="/home/node/infrastructure/gr/production"
    export SSH_RELAY="gr-pve01"
    export SWITCH_REF="gr-sw01"
    export LIBRENMS_WEBHOOK="https://n8n.example.net/webhook/librenms-alert-gr"
    export PROM_WEBHOOK="https://n8n.example.net/webhook/prometheus-alert-gr"
    export K8S_CONTEXT="gr"
    export SITE_PREFIX="gr"
    export SITE_ID="gr"
    export SYSLOG_HOST="grsyslogng01"
    export SYSLOG_BASE="/mnt/logs/syslog-ng"
    # Override LibreNMS to GR instance
    export LIBRENMS_URL="https://gr-nms01.example.net"
    export LIBRENMS_API_KEY="${LIBRENMS_GR_API_KEY:-ca7d4731865bb51d0a9c84b0a7d55e71}"
    ;;
  *)
    echo "ERROR: Unknown site '$SITE'. Use --site nl or --site gr"
    exit 1
    ;;
esac

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
# Returns last N lines from today's log, optionally filtered by pattern
fetch_syslog() {
  local hostname="$1"
  local lines="${2:-50}"
  local pattern="${3:-}"
  local year=$(date -u +%Y)
  local month=$(date -u +%m)
  local day=$(date -u +%Y-%m-%d)
  local logpath="${SYSLOG_BASE}/${hostname}/${year}/${month}/${hostname}-${day}.log"
  local ssh_opts="-i /home/node/.ssh/one_key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"

  if [ -n "$pattern" ]; then
    ssh $ssh_opts root@${SYSLOG_HOST} "grep -iE '$pattern' $logpath 2>/dev/null | tail -$lines || echo 'No matching syslog for $hostname'" 2>&1 | grep -v "^Warning:"
  else
    ssh $ssh_opts root@${SYSLOG_HOST} "tail -$lines $logpath 2>/dev/null || echo 'No syslog for $hostname'" 2>&1 | grep -v "^Warning:"
  fi
}
