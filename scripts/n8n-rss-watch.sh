#!/bin/bash
# IFRNLLEI01PRD-623: 24h RSS trend watch for n8n LXC under 4 GiB ceiling.
# Appends per-run RSS reading to log. Alerts Matrix if RSS breaches
# (soft) 3 GiB threshold — the canary for "memory leak, not just needs-headroom".
#
# Cron (app-user): */15 * * * * /app/claude-gateway/scripts/n8n-rss-watch.sh

set -u
LOG="/home/app-user/logs/claude-gateway/n8n-rss.log"
ALERT_LOG="/home/app-user/logs/claude-gateway/n8n-rss-alerts.log"
N8N_HOST="10.0.181.X"
THRESHOLD_KB=$((3 * 1024 * 1024))  # 3 GiB

mkdir -p "$(dirname "$LOG")"

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
rss_kb=$(ssh -i ~/.ssh/one_key -o ConnectTimeout=5 -o BatchMode=yes \
    "root@${N8N_HOST}" \
    "awk '/^VmRSS/{print \$2}' /proc/\$(pidof -s node)/status 2>/dev/null" \
    2>/dev/null | tr -dc '0-9')

if [ -z "$rss_kb" ]; then
    echo "${ts} ERR ssh-or-process-gone" >> "$LOG"
    exit 0
fi

# cgroup memory.current — total LXC usage (includes all PIDs, buffers, etc.)
cgroup_bytes=$(ssh -i ~/.ssh/one_key -o ConnectTimeout=5 -o BatchMode=yes \
    root@nl-pve01 \
    'cat /sys/fs/cgroup/lxc/VMID_REDACTED/memory.current 2>/dev/null' \
    2>/dev/null | tr -dc '0-9')
cgroup_kb=$(( ${cgroup_bytes:-0} / 1024 ))

echo "${ts} n8n_rss_kb=${rss_kb} lxc_cgroup_kb=${cgroup_kb}" >> "$LOG"

if [ "$rss_kb" -gt "$THRESHOLD_KB" ]; then
    msg="n8n RSS=${rss_kb}kB crossed 3 GiB threshold (LXC cgroup=${cgroup_kb}kB). IFRNLLEI01PRD-623 canary fired — likely memory leak, investigate."
    echo "${ts} ALERT ${msg}" >> "$ALERT_LOG"
    # Matrix notify via existing helper if available
    if [ -x /app/claude-gateway/scripts/matrix-alert.sh ]; then
        /app/claude-gateway/scripts/matrix-alert.sh \
            "WARNING" "n8n memory watch" "$msg" 2>&1 >> "$ALERT_LOG"
    fi
fi
