#!/bin/bash
# Emit kb_content_refresh_age_seconds{doc=...} for every auto-refreshed doc.
# Let Prometheus / Grafana see if any refresh cron has fallen behind.
#
# Cron: */15 * * * *  (same cadence as faiss-index-sync; much more freq than refresh itself)

set -u
METRICS=/var/lib/node_exporter/textfile_collector/kb_refresh_staleness.prom
FALLBACK=/tmp/kb_refresh_staleness.prom
REPO=/app/claude-gateway

# Every auto-refreshed doc: label -> path
declare -A DOCS=(
  [rag_architecture]="$REPO/docs/rag-architecture-current.md"
  [rag_metrics]="$REPO/docs/rag-metrics-reference.md"
  [network_addresses]="$REPO/docs/network-addresses.md"
  [host_blast_radius]="$REPO/docs/host-blast-radius.md"
  [crontab_reference]="$REPO/docs/crontab-reference.md"
)

NOW=$(date +%s)
TMP=$(mktemp)
{
  echo "# HELP kb_content_refresh_age_seconds Seconds since each auto-refreshed doc was regenerated"
  echo "# TYPE kb_content_refresh_age_seconds gauge"
  for label in "${!DOCS[@]}"; do
    path="${DOCS[$label]}"
    if [ -f "$path" ]; then
      mtime=$(stat -c %Y "$path")
      age=$((NOW - mtime))
    else
      age=-1
    fi
    echo "kb_content_refresh_age_seconds{doc=\"$label\"} $age"
  done
  echo "# HELP kb_content_refresh_last_probe_timestamp_seconds When this staleness probe ran"
  echo "# TYPE kb_content_refresh_last_probe_timestamp_seconds gauge"
  echo "kb_content_refresh_last_probe_timestamp_seconds $NOW"
} > "$TMP"

# chmod 644 so node-exporter (running as 'nobody') can read. mktemp defaults
# to 0600 — same bug pattern as weekly-eval-cron.sh fixed under
# IFRNLLEI01PRD-614. Caught live by KBContentRefreshMetricAbsent after
# IFRNLLEI01PRD-617 deployment.
if [ -w "$(dirname "$METRICS")" ]; then
  mv "$TMP" "$METRICS"
  chmod 644 "$METRICS"
else
  mv "$TMP" "$FALLBACK"
  chmod 644 "$FALLBACK"
fi
