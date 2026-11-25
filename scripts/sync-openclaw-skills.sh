#!/bin/bash
# Sync gateway skills → OpenClaw container's skill directory.
#
# Compares sha256 of source files in the gateway repo against the live copies
# inside the OpenClaw container mount (/root/.openclaw/workspace/skills/ on
# nl-openclaw01 host → /home/app-user/.openclaw/workspace/skills/ in container).
#
# Rationale: OpenClaw calls the same kb-semantic-search.py we run on claude01;
# without this cron the two drift silently and OpenClaw triage quality degrades
# behind whatever the gateway head is doing.
#
# Emits kb_openclaw_sync_{files_synced,drift_detected,last_run_timestamp_seconds}
# to the node-exporter textfile collector so Grafana / Prometheus can trend.
#
# Cron: 12 4 * * *  (before index-memories at 15 4; after refresh-* at 00-08 4)

set -u
REPO=/app/claude-gateway
LOG=/tmp/sync-openclaw-skills.log
METRICS=/var/lib/node_exporter/textfile_collector/kb_openclaw_sync.prom
FALLBACK_METRICS=/tmp/kb_openclaw_sync.prom
OPENCLAW_HOST=nl-openclaw01
OPENCLAW_SKILLS_DIR=/root/.openclaw/workspace/skills

# Files to keep in sync. Format: <source-relative-to-repo>:<dest-relative-to-skills-dir>
# Keep this list in lockstep with the OpenClaw skills we maintain in the gateway repo.
FILES=(
  "scripts/kb-semantic-search.py:kb-semantic-search.py"
  "openclaw/skills/infra-triage/infra-triage.sh:infra-triage/infra-triage.sh"
  "openclaw/skills/k8s-triage/k8s-triage.sh:k8s-triage/k8s-triage.sh"
  "openclaw/skills/security-triage/security-triage.sh:security-triage/security-triage.sh"
  "openclaw/skills/playbook-lookup/playbook-lookup.sh:playbook-lookup/playbook-lookup.sh"
  "openclaw/skills/proactive-scan/proactive-scan.sh:proactive-scan/proactive-scan.sh"
  "openclaw/skills/correlated-triage/correlated-triage.sh:correlated-triage/correlated-triage.sh"
)

ts() { date -Iseconds; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

log "sync start"
synced=0
drift=0
errors=0

for entry in "${FILES[@]}"; do
  src_rel="${entry%%:*}"
  dst_base="${entry##*:}"
  src_path="$REPO/$src_rel"
  dst_path="$OPENCLAW_SKILLS_DIR/$dst_base"

  if [ ! -f "$src_path" ]; then
    log "ERROR: source missing: $src_path"
    errors=$((errors + 1))
    continue
  fi

  src_hash=$(sha256sum "$src_path" | awk '{print $1}')
  dst_hash=$(ssh -o ConnectTimeout=8 "$OPENCLAW_HOST" "sha256sum $dst_path 2>/dev/null | awk '{print \$1}'" 2>/dev/null || echo "MISSING")

  if [ "$src_hash" = "$dst_hash" ]; then
    log "ok: $dst_base in sync (${src_hash:0:10})"
  else
    drift=$((drift + 1))
    log "DRIFT: $dst_base — src=${src_hash:0:10} dst=${dst_hash:0:10}; syncing..."
    if scp -o ConnectTimeout=8 -q "$src_path" "$OPENCLAW_HOST:$dst_path" 2>>"$LOG"; then
      synced=$((synced + 1))
      log "synced: $dst_base"
    else
      errors=$((errors + 1))
      log "ERROR: scp failed for $dst_base"
    fi
  fi
done

# Emit Prometheus metrics
out=$(cat <<EOF
# HELP kb_openclaw_sync_files_synced Files copied on this run (was drifted, now in sync)
# TYPE kb_openclaw_sync_files_synced gauge
kb_openclaw_sync_files_synced $synced
# HELP kb_openclaw_sync_drift_detected Files detected as drifted (may be synced or failed)
# TYPE kb_openclaw_sync_drift_detected gauge
kb_openclaw_sync_drift_detected $drift
# HELP kb_openclaw_sync_errors Files that failed to sync
# TYPE kb_openclaw_sync_errors gauge
kb_openclaw_sync_errors $errors
# HELP kb_openclaw_sync_last_run_timestamp_seconds Unix timestamp of last sync run
# TYPE kb_openclaw_sync_last_run_timestamp_seconds gauge
kb_openclaw_sync_last_run_timestamp_seconds $(date +%s)
EOF
)
if [ -w "$(dirname "$METRICS")" ]; then
  echo "$out" > "$METRICS"
else
  echo "$out" > "$FALLBACK_METRICS"
fi

log "sync done: synced=$synced drift=$drift errors=$errors"
