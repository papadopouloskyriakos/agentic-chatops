#!/bin/bash
# Write infrastructure alert metrics for Prometheus node_exporter textfile collector
# Reads from alert persistence files + YouTrack API

OUT=/var/lib/node_exporter/textfile_collector/infra.prom
TMPOUT="${OUT}.tmp"
CONTEXT_DIR=/home/claude-runner/gitlab/products/cubeos/claude-context

ALERTS_NL="${CONTEXT_DIR}/active-alerts.json"
ALERTS_GR="${CONTEXT_DIR}/active-alerts-gr.json"

# YouTrack config
YT_URL="${YOUTRACK_URL:-https://youtrack.example.net}"
YT_TOKEN="${YOUTRACK_TOKEN}"

# Start fresh
> "$TMPOUT"

###############################################################################
# Helper: count active alerts (no recoveredAt) from persistence file
###############################################################################
count_active_alerts() {
    local file="$1"
    if [ -f "$file" ]; then
        jq '[to_entries[] | select(.value.recoveredAt == null)] | length' "$file" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

###############################################################################
# Helper: count total alerts (all entries) from persistence file
###############################################################################
count_total_alerts() {
    local file="$1"
    if [ -f "$file" ]; then
        jq '[to_entries[]] | length' "$file" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

###############################################################################
# Helper: sum flapCount across all entries in persistence file
###############################################################################
sum_flap_count() {
    local file="$1"
    if [ -f "$file" ]; then
        jq '[to_entries[].value.flapCount // 0] | add // 0' "$file" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

###############################################################################
# Helper: query YouTrack for issue counts by state
###############################################################################
yt_issues_by_state() {
    local project="$1"
    local state="$2"
    if [ -z "$YT_TOKEN" ]; then
        echo 0
        return
    fi
    local query="project:${project}+State:${state}"
    local result
    result=$(curl -sk -H "Authorization: Bearer ${YT_TOKEN}" \
        -H "Accept: application/json" \
        "${YT_URL}/api/issues?query=${query}&fields=id&\$top=0" 2>/dev/null)
    # $top=0 returns headers only; use search count endpoint instead
    result=$(curl -sk -H "Authorization: Bearer ${YT_TOKEN}" \
        -H "Accept: application/json" \
        "${YT_URL}/api/issuesGetter/count?query=project:+${project}+State:+${state}" 2>/dev/null)
    # If count endpoint doesn't work, fall back to listing
    if echo "$result" | jq -e '.value' >/dev/null 2>&1; then
        echo "$result" | jq '.value // 0'
    else
        # Fallback: list issues and count
        result=$(curl -sk -H "Authorization: Bearer ${YT_TOKEN}" \
            -H "Accept: application/json" \
            "${YT_URL}/api/issues?query=project:+${project}+State:+${state}&fields=id&\$top=500" 2>/dev/null)
        echo "$result" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo 0
    fi
}

###############################################################################
# Helper: compute MTTR for Done issues in a project (seconds)
###############################################################################
yt_mttr() {
    local project="$1"
    if [ -z "$YT_TOKEN" ]; then
        echo 0
        return
    fi
    # Fetch Done issues with created and updated timestamps
    local result
    result=$(curl -sk -H "Authorization: Bearer ${YT_TOKEN}" \
        -H "Accept: application/json" \
        "${YT_URL}/api/issues?query=project:+${project}+State:+Done&fields=id,created,updated&\$top=200" 2>/dev/null)

    if ! echo "$result" | jq -e 'type == "array"' >/dev/null 2>&1; then
        echo 0
        return
    fi

    # YT timestamps are in milliseconds; compute average (updated - created) in seconds
    local mttr
    mttr=$(echo "$result" | jq '
        [.[] | select(.created != null and .updated != null) | ((.updated - .created) / 1000)] |
        if length > 0 then (add / length | floor) else 0 end
    ' 2>/dev/null || echo 0)
    echo "$mttr"
}

###############################################################################
# 1. Active alerts
###############################################################################
echo "# HELP infra_alerts_active Currently active alerts (not recovered)" >> "$TMPOUT"
echo "# TYPE infra_alerts_active gauge" >> "$TMPOUT"
ACTIVE_NL=$(count_active_alerts "$ALERTS_NL")
ACTIVE_GR=$(count_active_alerts "$ALERTS_GR")
echo "infra_alerts_active{site=\"nl\"} $ACTIVE_NL" >> "$TMPOUT"
echo "infra_alerts_active{site=\"gr\"} $ACTIVE_GR" >> "$TMPOUT"

###############################################################################
# 2. Total alerts (all entries in persistence files)
###############################################################################
echo "# HELP infra_alerts_total Total alert entries in persistence store" >> "$TMPOUT"
echo "# TYPE infra_alerts_total gauge" >> "$TMPOUT"
TOTAL_NL=$(count_total_alerts "$ALERTS_NL")
TOTAL_GR=$(count_total_alerts "$ALERTS_GR")
echo "infra_alerts_total{site=\"nl\"} $TOTAL_NL" >> "$TMPOUT"
echo "infra_alerts_total{site=\"gr\"} $TOTAL_GR" >> "$TMPOUT"

###############################################################################
# 3. Issues by state (from YouTrack)
###############################################################################
echo "# HELP infra_issues_by_state Infrastructure issues by state in YouTrack" >> "$TMPOUT"
echo "# TYPE infra_issues_by_state gauge" >> "$TMPOUT"
for state in Open "In Progress" Done "To Verify"; do
    # Sanitize state name for label
    label_state=$(echo "$state" | sed 's/ //g')
    NL_COUNT=$(yt_issues_by_state "IFRNLLEI01PRD" "$state")
    GR_COUNT=$(yt_issues_by_state "IFRGRSKG01PRD" "$state")
    echo "infra_issues_by_state{site=\"nl\",state=\"${label_state}\"} $NL_COUNT" >> "$TMPOUT"
    echo "infra_issues_by_state{site=\"gr\",state=\"${label_state}\"} $GR_COUNT" >> "$TMPOUT"
done

###############################################################################
# 4. Remediation success (Done issues count)
###############################################################################
echo "# HELP infra_remediation_success Count of issues with state Done" >> "$TMPOUT"
echo "# TYPE infra_remediation_success gauge" >> "$TMPOUT"
DONE_NL=$(yt_issues_by_state "IFRNLLEI01PRD" "Done")
DONE_GR=$(yt_issues_by_state "IFRGRSKG01PRD" "Done")
echo "infra_remediation_success{site=\"nl\"} $DONE_NL" >> "$TMPOUT"
echo "infra_remediation_success{site=\"gr\"} $DONE_GR" >> "$TMPOUT"

###############################################################################
# 5. Flap total
###############################################################################
echo "# HELP infra_flap_total Total flap count across all alert entries" >> "$TMPOUT"
echo "# TYPE infra_flap_total gauge" >> "$TMPOUT"
FLAP_NL=$(sum_flap_count "$ALERTS_NL")
FLAP_GR=$(sum_flap_count "$ALERTS_GR")
echo "infra_flap_total{site=\"nl\"} $FLAP_NL" >> "$TMPOUT"
echo "infra_flap_total{site=\"gr\"} $FLAP_GR" >> "$TMPOUT"

###############################################################################
# 6. MTTR (mean time to resolve in seconds)
###############################################################################
echo "# HELP infra_mttr_seconds Mean time to resolve Done issues (seconds)" >> "$TMPOUT"
echo "# TYPE infra_mttr_seconds gauge" >> "$TMPOUT"
MTTR_NL=$(yt_mttr "IFRNLLEI01PRD")
MTTR_GR=$(yt_mttr "IFRGRSKG01PRD")
echo "infra_mttr_seconds{site=\"nl\"} $MTTR_NL" >> "$TMPOUT"
echo "infra_mttr_seconds{site=\"gr\"} $MTTR_GR" >> "$TMPOUT"

# Atomic rename
mv "$TMPOUT" "$OUT"
