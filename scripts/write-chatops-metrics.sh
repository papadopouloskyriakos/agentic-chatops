#!/bin/bash
DB=/home/claude-runner/gitlab/products/cubeos/claude-context/gateway.db
OUT=/var/lib/node_exporter/textfile_collector/chatops.prom
TMPOUT="${OUT}.tmp"
CMD_LOG=/home/claude-runner/gitlab/products/cubeos/claude-context/command.log

# Start fresh
> "$TMPOUT"

# Active sessions count
echo "# HELP chatops_active_sessions Currently active sessions" >> "$TMPOUT"
echo "# TYPE chatops_active_sessions gauge" >> "$TMPOUT"
ACTIVE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions" 2>/dev/null || echo 0)
echo "chatops_active_sessions $ACTIVE" >> "$TMPOUT"

# Total sessions in log
echo "# HELP chatops_sessions_logged_total Total sessions in session log" >> "$TMPOUT"
echo "# TYPE chatops_sessions_logged_total gauge" >> "$TMPOUT"
LOGGED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM session_log" 2>/dev/null || echo 0)
echo "chatops_sessions_logged_total $LOGGED" >> "$TMPOUT"

# Total messages across all active sessions
echo "# HELP chatops_messages_total Total messages across all active sessions" >> "$TMPOUT"
echo "# TYPE chatops_messages_total gauge" >> "$TMPOUT"
MSGS=$(sqlite3 "$DB" "SELECT COALESCE(SUM(message_count),0) FROM sessions" 2>/dev/null || echo 0)
echo "chatops_messages_total $MSGS" >> "$TMPOUT"

# Queue depth
echo "# HELP chatops_queue_depth Messages in queue" >> "$TMPOUT"
echo "# TYPE chatops_queue_depth gauge" >> "$TMPOUT"
QUEUE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM queue" 2>/dev/null || echo 0)
echo "chatops_queue_depth $QUEUE" >> "$TMPOUT"

# Lock held per slot (1 if lock file exists and is <10min old)
echo "# HELP chatops_lock_held 1 if gateway lock is held for this slot" >> "$TMPOUT"
echo "# TYPE chatops_lock_held gauge" >> "$TMPOUT"
GW_DIR=/home/claude-runner/gitlab/products/cubeos/claude-context
for SLOT in dev infra-nl infra-gr; do
    LOCK_FILE="$GW_DIR/gateway.lock.$SLOT"
    LOCK=0
    if [ -f "$LOCK_FILE" ]; then
        AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK_FILE") ))
        [ "$AGE" -lt 600 ] && LOCK=1
    fi
    echo "chatops_lock_held{slot=\"$SLOT\"} $LOCK" >> "$TMPOUT"
done

# Gateway mode (labeled, 1=active per mode)
echo "# HELP chatops_gateway_mode Current gateway mode (1=active)" >> "$TMPOUT"
echo "# TYPE chatops_gateway_mode gauge" >> "$TMPOUT"
MODE=$(cat /home/claude-runner/gateway.mode 2>/dev/null || echo "oc-cc")
for m in oc-cc oc-oc cc-cc cc-oc; do
    VAL=0; [ "$m" = "$MODE" ] && VAL=1
    echo "chatops_gateway_mode{mode=\"$m\"} $VAL" >> "$TMPOUT"
done

# Cooldown files active
echo "# HELP chatops_cooldowns_active Number of active cooldown files" >> "$TMPOUT"
echo "# TYPE chatops_cooldowns_active gauge" >> "$TMPOUT"
COOLDOWNS=$(find /home/claude-runner/gitlab/products/cubeos/claude-context/ -name "gateway.cooldown.*" -mmin -1 2>/dev/null | wc -l)
echo "chatops_cooldowns_active $COOLDOWNS" >> "$TMPOUT"

# Paused sessions
echo "# HELP chatops_paused_sessions Currently paused sessions" >> "$TMPOUT"
echo "# TYPE chatops_paused_sessions gauge" >> "$TMPOUT"
PAUSED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sessions WHERE paused=1" 2>/dev/null || echo 0)
echo "chatops_paused_sessions $PAUSED" >> "$TMPOUT"

# Session log by outcome
echo "# HELP chatops_sessions_by_outcome Historical sessions by outcome" >> "$TMPOUT"
echo "# TYPE chatops_sessions_by_outcome gauge" >> "$TMPOUT"
sqlite3 "$DB" "SELECT COALESCE(outcome,'unknown'), COUNT(*) FROM session_log GROUP BY outcome" 2>/dev/null | \
while IFS='|' read -r outcome count; do
    echo "chatops_sessions_by_outcome{outcome=\"$outcome\"} $count"
done >> "$TMPOUT"

# Per-command counters from command log (last 24h)
# Format: each line is "timestamp command subcommand"
if [ -f "$CMD_LOG" ]; then
    CUTOFF=$(date -d '24 hours ago' +%s 2>/dev/null || echo 0)

    echo "# HELP chatops_commands_total Commands executed (last 24h)" >> "$TMPOUT"
    echo "# TYPE chatops_commands_total gauge" >> "$TMPOUT"
    awk -v cutoff="$CUTOFF" '$1 >= cutoff {print $2}' "$CMD_LOG" | sort | uniq -c | \
    while read -r count cmd; do
        echo "chatops_commands_total{command=\"$cmd\"} $count"
    done >> "$TMPOUT"

    echo "# HELP chatops_messages_relayed Messages relayed to Claude (last 24h)" >> "$TMPOUT"
    echo "# TYPE chatops_messages_relayed gauge" >> "$TMPOUT"
    MSG_COUNT=$(awk -v cutoff="$CUTOFF" '$1 >= cutoff && $2 == "message" {c++} END {print c+0}' "$CMD_LOG")
    echo "chatops_messages_relayed $MSG_COUNT" >> "$TMPOUT"

    # Trim log entries older than 48h
    TRIM_CUTOFF=$(date -d '48 hours ago' +%s 2>/dev/null || echo 0)
    TMP_LOG="${CMD_LOG}.tmp"
    awk -v cutoff="$TRIM_CUTOFF" '$1 >= cutoff' "$CMD_LOG" > "$TMP_LOG" 2>/dev/null && mv "$TMP_LOG" "$CMD_LOG"
fi

# =============================================================================
# OpenAI Status (Tier 1 — OpenClaw uses GPT-4o via OpenAI API)
# Source: https://status.openai.com/api/v2/summary.json
# =============================================================================
OPENAI_STATUS=$(curl -sf --max-time 10 "https://status.openai.com/api/v2/summary.json" 2>/dev/null)
if [ -n "$OPENAI_STATUS" ]; then
    OAI_INDICATOR=$(echo "$OPENAI_STATUS" | jq -r '.status.indicator')
    case $OAI_INDICATOR in
        none) OAI_IVAL=0 ;; minor) OAI_IVAL=1 ;; major) OAI_IVAL=2 ;; critical) OAI_IVAL=3 ;; *) OAI_IVAL=-1 ;;
    esac
    echo "# HELP openai_status_indicator Overall OpenAI platform status (0=none,1=minor,2=major,3=critical)" >> "$TMPOUT"
    echo "# TYPE openai_status_indicator gauge" >> "$TMPOUT"
    echo "openai_status_indicator{indicator=\"$OAI_INDICATOR\"} $OAI_IVAL" >> "$TMPOUT"

    echo "# HELP openai_component_status Status per component (1=operational, 0=degraded)" >> "$TMPOUT"
    echo "# TYPE openai_component_status gauge" >> "$TMPOUT"
    # Filter to API-relevant components (skip consumer/FedRAMP/Sora/Video)
    echo "$OPENAI_STATUS" | jq -r '.components[] | select(.name | test("Chat Completions|Responses|Embeddings|Audio|Batch|Fine-tuning|Images|Moderations|Files$")) | [.name, .status] | @tsv' | \
    while IFS=$'\t' read -r name status; do
        SVAL=1
        [ "$status" != "operational" ] && SVAL=0
        SAFE_NAME=$(echo "$name" | sed 's/[^a-zA-Z0-9]/_/g' | tr '[:upper:]' '[:lower:]')
        echo "openai_component_status{component=\"$SAFE_NAME\",status=\"$status\"} $SVAL"
    done >> "$TMPOUT"

    OAI_INCIDENTS=$(echo "$OPENAI_STATUS" | jq '.incidents | length')
    echo "# HELP openai_active_incidents Number of active OpenAI incidents" >> "$TMPOUT"
    echo "# TYPE openai_active_incidents gauge" >> "$TMPOUT"
    echo "openai_active_incidents $OAI_INCIDENTS" >> "$TMPOUT"

    OAI_MAINT=$(echo "$OPENAI_STATUS" | jq '.scheduled_maintenances | length')
    echo "# HELP openai_scheduled_maintenances Upcoming OpenAI scheduled maintenances" >> "$TMPOUT"
    echo "# TYPE openai_scheduled_maintenances gauge" >> "$TMPOUT"
    echo "openai_scheduled_maintenances $OAI_MAINT" >> "$TMPOUT"
fi

# =============================================================================
# Anthropic / Claude Status (Tier 2 — Claude Code uses Anthropic API)
# Source: https://status.claude.com/api/v2/summary.json
# =============================================================================
CLAUDE_STATUS=$(curl -sf --max-time 10 "https://status.claude.com/api/v2/summary.json" 2>/dev/null)
if [ -n "$CLAUDE_STATUS" ]; then
    INDICATOR=$(echo "$CLAUDE_STATUS" | jq -r '.status.indicator')
    case $INDICATOR in
        none) IVAL=0 ;; minor) IVAL=1 ;; major) IVAL=2 ;; critical) IVAL=3 ;; *) IVAL=-1 ;;
    esac
    echo "# HELP claude_status_indicator Overall Claude platform status (0=none,1=minor,2=major,3=critical)" >> "$TMPOUT"
    echo "# TYPE claude_status_indicator gauge" >> "$TMPOUT"
    echo "claude_status_indicator{indicator=\"$INDICATOR\"} $IVAL" >> "$TMPOUT"

    echo "# HELP claude_component_status Status per component (1=operational, 0=degraded)" >> "$TMPOUT"
    echo "# TYPE claude_component_status gauge" >> "$TMPOUT"
    echo "$CLAUDE_STATUS" | jq -r '.components[] | select(.showcase == true) | select(.name | test("Government") | not) | [.name, .status] | @tsv' | \
    while IFS=$'\t' read -r name status; do
        SVAL=1
        [ "$status" != "operational" ] && SVAL=0
        SAFE_NAME=$(echo "$name" | sed 's/[^a-zA-Z0-9]/_/g' | tr '[:upper:]' '[:lower:]')
        echo "claude_component_status{component=\"$SAFE_NAME\",status=\"$status\"} $SVAL"
    done >> "$TMPOUT"

    INCIDENT_COUNT=$(echo "$CLAUDE_STATUS" | jq '.incidents | length')
    echo "# HELP claude_active_incidents Number of active incidents" >> "$TMPOUT"
    echo "# TYPE claude_active_incidents gauge" >> "$TMPOUT"
    echo "claude_active_incidents $INCIDENT_COUNT" >> "$TMPOUT"

    MAINT_COUNT=$(echo "$CLAUDE_STATUS" | jq '.scheduled_maintenances | length')
    echo "# HELP claude_scheduled_maintenances Upcoming scheduled maintenances" >> "$TMPOUT"
    echo "# TYPE claude_scheduled_maintenances gauge" >> "$TMPOUT"
    echo "claude_scheduled_maintenances $MAINT_COUNT" >> "$TMPOUT"
fi

mv "$TMPOUT" "$OUT"
