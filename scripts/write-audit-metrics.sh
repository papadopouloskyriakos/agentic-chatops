#!/bin/bash
# write-audit-metrics.sh — run the self-audit invariants and emit liveness + pass/fail
# metrics to the Prometheus textfile collector.
#
# WHY: audit-risk-decisions.sh (the autonomy-forward auto-resolve SAFETY invariant) and
# audit-skill-versions.sh were ONLY ever invoked from inside holistic-agentic-health.sh,
# which was itself never scheduled — so the safety invariant never ran automatically and
# a bad auto-resolve would go uncaught until a human ran it by hand. (Dark-component audit
# 2026-06-25.) This wrapper runs them on a real cron and publishes a metric an alert watches.
#
# Cron (nl-claude01): 15 5 * * 1  scripts/write-audit-metrics.sh
set -uo pipefail
REPO="/app/claude-gateway"
PROM_DIR="/var/lib/node_exporter/textfile_collector"
LOG="/home/app-user/logs/claude-gateway/self-audit.log"
now=$(date +%s)

"$REPO/scripts/audit-risk-decisions.sh"  >> "$LOG" 2>&1; risk_rc=$?
"$REPO/scripts/audit-skill-versions.sh"  >> "$LOG" 2>&1; skill_rc=$?

risk_fail=$(( risk_rc != 0 ? 1 : 0 ))
skill_fail=$(( skill_rc != 0 ? 1 : 0 ))

if [ -d "$PROM_DIR" ]; then
  tmp="$PROM_DIR/.self_audit.prom.$$"
  cat > "$tmp" <<PROM
# HELP risk_audit_fail 1 if audit-risk-decisions.sh found an unsafe auto-approval or a missing prediction gate (the autonomy-forward safety invariant)
# TYPE risk_audit_fail gauge
risk_audit_fail $risk_fail
# HELP risk_audit_exit_code raw exit code of audit-risk-decisions.sh (1=floor-signal violation, 2=structural)
# TYPE risk_audit_exit_code gauge
risk_audit_exit_code $risk_rc
# HELP risk_audit_last_run_timestamp_seconds unix time the risk-decision audit last ran
# TYPE risk_audit_last_run_timestamp_seconds gauge
risk_audit_last_run_timestamp_seconds $now
# HELP skill_version_audit_fail 1 if audit-skill-versions.sh exited non-zero
# TYPE skill_version_audit_fail gauge
skill_version_audit_fail $skill_fail
# HELP skill_version_audit_last_run_timestamp_seconds unix time the skill-version audit last ran
# TYPE skill_version_audit_last_run_timestamp_seconds gauge
skill_version_audit_last_run_timestamp_seconds $now
PROM
  mv -f "$tmp" "$PROM_DIR/self_audit.prom"
fi
echo "$(date -u +%FT%TZ) write-audit-metrics: risk_rc=$risk_rc skill_rc=$skill_rc" >> "$LOG"
