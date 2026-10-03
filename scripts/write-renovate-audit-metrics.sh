#!/bin/bash
# write-renovate-audit-metrics.sh — weekly bridge (Dim-6). Runs the floor-invariant auditor + the
# audit hash-chain verify and publishes their results as node_exporter textfile metrics. This is the file
# the RenovateAutonomyAuditFail / AuditStale alerts read (previously referenced but ABSENT → those alerts
# were dead). Cron: weekly (Mon), offset from the risk auditor. Note: fresh tamper alerting is via the
# */5 writer's `renovate_autonomy_chain_ok` (→ RenovateAuditChainBroken); the weekly `chain_broken` gauge
# below is a redundant cross-check (→ RenovateAuditChainBrokenWeekly, fires even if the */5 writer is down).
#   renovate_autonomy_audit_fail                        1 if audit-renovate-decisions.sh found a floor breach
#   renovate_autonomy_chain_broken                      1 if the audit hash chain failed to verify (weekly cross-check)
#   renovate_autonomy_audit_last_run_timestamp_seconds  freshness / dead-man
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DB="${GATEWAY_DB:-/home/app-user/gateway-state/gateway.db}"
OUT="${RENOVATE_AUDIT_METRICS_OUT:-/var/lib/node_exporter/textfile_collector/renovate_autonomy_audit.prom}"

bash "$DIR/audit-renovate-decisions.sh" >/dev/null 2>&1; fail=$?
python3 "$DIR/lib/renovate_audit.py" verify --db "$GATEWAY_DB" >/dev/null 2>&1; chain=$?   # 0 ok / 1 broken

mkdir -p "$(dirname "$OUT")"; tmp="$OUT.tmp"
{
  echo "# HELP renovate_autonomy_audit_fail 1 if the weekly floor-invariant auditor found a live AUTO out of policy."
  echo "# TYPE renovate_autonomy_audit_fail gauge"
  echo "renovate_autonomy_audit_fail $([ "$fail" -ne 0 ] && echo 1 || echo 0)"
  echo "# HELP renovate_autonomy_chain_broken 1 if the tamper-evident audit hash chain failed to verify."
  echo "# TYPE renovate_autonomy_chain_broken gauge"
  echo "renovate_autonomy_chain_broken $([ "$chain" -ne 0 ] && echo 1 || echo 0)"
  echo "# HELP renovate_autonomy_audit_last_run_timestamp_seconds Unix time the weekly auditor last ran."
  echo "# TYPE renovate_autonomy_audit_last_run_timestamp_seconds gauge"
  echo "renovate_autonomy_audit_last_run_timestamp_seconds $(date +%s)"
} > "$tmp"
mv "$tmp" "$OUT"
