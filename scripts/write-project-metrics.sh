#!/bin/bash
source /home/claude-runner/gitlab/n8n/claude-gateway/.env
OUT_CUBEOS=/var/lib/node_exporter/textfile_collector/cubeos.prom
OUT_MESHSAT=/var/lib/node_exporter/textfile_collector/meshsat.prom

write_project_metrics() {
    local project="$1" yt_project="$2" outfile="$3"
    local tmpout="${outfile}.tmp"
    > "$tmpout"

    # GitLab pipelines - project IDs from CLAUDE.md
    # CubeOS repos: api:13, dashboard:14, docs:16, coreapps:19, releases:20, hal:22
    local repos=""
    case $project in
        cubeos) repos="13 14 16 19 20 22" ;;
        meshsat) repos="27" ;;
    esac

    local total_pipelines=0 success_pipelines=0 failed_pipelines=0 running_pipelines=0

    for repo_id in $repos; do
        local result
        result=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
            "https://gitlab.example.net/api/v4/projects/$repo_id/pipelines?per_page=20" 2>/dev/null)
        if [ -n "$result" ]; then
            local statuses
            statuses=$(echo "$result" | jq -r '.[].status' 2>/dev/null)
            while read -r status; do
                [ -z "$status" ] && continue
                ((total_pipelines++))
                case "$status" in
                    success) ((success_pipelines++)) ;;
                    failed) ((failed_pipelines++)) ;;
                    running) ((running_pipelines++)) ;;
                esac
            done <<< "$statuses"
        fi
    done

    echo "# HELP project_pipelines_total Recent pipelines by status" >> "$tmpout"
    echo "# TYPE project_pipelines_total gauge" >> "$tmpout"
    echo "project_pipelines_total{project=\"$project\",status=\"success\"} $success_pipelines" >> "$tmpout"
    echo "project_pipelines_total{project=\"$project\",status=\"failed\"} $failed_pipelines" >> "$tmpout"
    echo "project_pipelines_total{project=\"$project\",status=\"running\"} $running_pipelines" >> "$tmpout"

    if [ $total_pipelines -gt 0 ]; then
        local rate=$(awk "BEGIN {printf \"%.1f\", $success_pipelines * 100 / $total_pipelines}" 2>/dev/null || echo 0)
        echo "# HELP project_pipeline_success_rate Pipeline success rate percentage" >> "$tmpout"
        echo "# TYPE project_pipeline_success_rate gauge" >> "$tmpout"
        echo "project_pipeline_success_rate{project=\"$project\"} $rate" >> "$tmpout"
    fi

    # Open MRs
    local open_mrs=0
    for repo_id in $repos; do
        local mr_count
        mr_count=$(curl -sf -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
            "https://gitlab.example.net/api/v4/projects/$repo_id/merge_requests?state=opened&per_page=100" 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
        open_mrs=$((open_mrs + mr_count))
    done
    echo "# HELP project_open_merge_requests Open merge requests" >> "$tmpout"
    echo "# TYPE project_open_merge_requests gauge" >> "$tmpout"
    echo "project_open_merge_requests{project=\"$project\"} $open_mrs" >> "$tmpout"

    # YouTrack issues by state
    if [ -n "$yt_project" ]; then
        local issues
        issues=$(curl -sf -H "Authorization: Bearer $YT_TOKEN" \
            "https://youtrack.example.net/api/issues?query=project:$yt_project&fields=customFields(name,value(name))&\$top=200" 2>/dev/null)

        if [ -n "$issues" ]; then
            echo "# HELP project_issues_by_state Issues by state" >> "$tmpout"
            echo "# TYPE project_issues_by_state gauge" >> "$tmpout"
            for state in "Open" "In Progress" "To Verify" "Done"; do
                local count
                count=$(echo "$issues" | jq "[.[] | .customFields[] | select(.name==\"State\") | select(.value.name==\"$state\")] | length" 2>/dev/null || echo 0)
                local safe_state=$(echo "$state" | tr ' ' '_' | tr '[:upper:]' '[:lower:]')
                echo "project_issues_by_state{project=\"$project\",state=\"$safe_state\"} $count" >> "$tmpout"
            done

            local total_issues
            total_issues=$(echo "$issues" | jq 'length' 2>/dev/null || echo 0)
            echo "# HELP project_issues_total Total issues" >> "$tmpout"
            echo "# TYPE project_issues_total gauge" >> "$tmpout"
            echo "project_issues_total{project=\"$project\"} $total_issues" >> "$tmpout"
        fi
    fi

    mv "$tmpout" "$outfile"
}

write_project_metrics "cubeos" "CUBEOS" "$OUT_CUBEOS"
write_project_metrics "meshsat" "" "$OUT_MESHSAT"
