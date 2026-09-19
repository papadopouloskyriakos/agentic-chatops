#!/bin/bash
# Write security alert metrics for Prometheus node_exporter textfile collector
# Cron: */5 * * * * /app/claude-gateway/scripts/write-security-metrics.sh

OUT="/var/lib/node_exporter/textfile_collector/security.prom"
TMPOUT="${OUT}.tmp"
CONTEXT_DIR="/app/cubeos/claude-context"

CS_NL="${CONTEXT_DIR}/active-crowdsec-alerts.json"
CS_GR="${CONTEXT_DIR}/active-crowdsec-alerts-gr.json"
SEC_NL="${CONTEXT_DIR}/active-security-alerts.json"

> "$TMPOUT"

# Active CrowdSec alerts (NL)
if [ -f "$CS_NL" ]; then
  CS_NL_COUNT=$(python3 -c "
import json
try:
    d = json.load(open('$CS_NL'))
    alerts = d.get('activeAlerts', {})
    active = sum(1 for a in alerts.values() if not a.get('recoveredAt'))
    print(active)
except: print(0)
" 2>/dev/null)
else
  CS_NL_COUNT=0
fi

# Active CrowdSec alerts (GR)
if [ -f "$CS_GR" ]; then
  CS_GR_COUNT=$(python3 -c "
import json
try:
    d = json.load(open('$CS_GR'))
    alerts = d.get('activeAlerts', {})
    active = sum(1 for a in alerts.values() if not a.get('recoveredAt'))
    print(active)
except: print(0)
" 2>/dev/null)
else
  CS_GR_COUNT=0
fi

# Active security scan alerts (NL)
if [ -f "$SEC_NL" ]; then
  SEC_NL_TARGETS=$(python3 -c "
import json
try:
    d = json.load(open('$SEC_NL'))
    print(len(d.get('targetIssues', {})))
except: print(0)
" 2>/dev/null)
else
  SEC_NL_TARGETS=0
fi

# CrowdSec flap counts
CS_NL_FLAPS=0
CS_GR_FLAPS=0
if [ -f "$CS_NL" ]; then
  CS_NL_FLAPS=$(python3 -c "
import json
try:
    d = json.load(open('$CS_NL'))
    alerts = d.get('activeAlerts', {})
    print(sum(a.get('flapCount', 0) for a in alerts.values()))
except: print(0)
" 2>/dev/null)
fi
if [ -f "$CS_GR" ]; then
  CS_GR_FLAPS=$(python3 -c "
import json
try:
    d = json.load(open('$CS_GR'))
    alerts = d.get('activeAlerts', {})
    print(sum(a.get('flapCount', 0) for a in alerts.values()))
except: print(0)
" 2>/dev/null)
fi

cat >> "$TMPOUT" <<EOF
# HELP security_crowdsec_active_alerts Active CrowdSec alerts by site
# TYPE security_crowdsec_active_alerts gauge
security_crowdsec_active_alerts{site="nl"} ${CS_NL_COUNT:-0}
security_crowdsec_active_alerts{site="gr"} ${CS_GR_COUNT:-0}
# HELP security_scan_tracked_targets Security scan targets with open YT issues
# TYPE security_scan_tracked_targets gauge
security_scan_tracked_targets{site="nl"} ${SEC_NL_TARGETS:-0}
# HELP security_crowdsec_flap_total Total CrowdSec flap events by site
# TYPE security_crowdsec_flap_total gauge
security_crowdsec_flap_total{site="nl"} ${CS_NL_FLAPS:-0}
security_crowdsec_flap_total{site="gr"} ${CS_GR_FLAPS:-0}
# HELP security_crowdsec_suppressed_scenarios Auto-suppressed CrowdSec scenario count
# TYPE security_crowdsec_suppressed_scenarios gauge
security_crowdsec_suppressed_scenarios $(sqlite3 "$CONTEXT_DIR/../gateway.db" "SELECT COUNT(*) FROM crowdsec_scenario_stats WHERE auto_suppressed = 1;" 2>/dev/null || echo 0)
# HELP security_crowdsec_total_scenarios Total tracked CrowdSec scenario-host pairs
# TYPE security_crowdsec_total_scenarios gauge
security_crowdsec_total_scenarios $(sqlite3 "$CONTEXT_DIR/../gateway.db" "SELECT COUNT(*) FROM crowdsec_scenario_stats;" 2>/dev/null || echo 0)
# HELP security_false_positive_rate CrowdSec false positive rate (suppressed / total actionable %)
# TYPE security_false_positive_rate gauge
security_false_positive_rate $(sqlite3 "$CONTEXT_DIR/../gateway.db" "SELECT CASE WHEN (SUM(suppressed_count) + SUM(escalated_count) + SUM(yt_issues_created)) > 0 THEN ROUND(CAST(SUM(suppressed_count) AS FLOAT) / (SUM(suppressed_count) + SUM(escalated_count) + SUM(yt_issues_created)) * 100, 1) ELSE 0 END FROM crowdsec_scenario_stats;" 2>/dev/null || echo 0)
# HELP security_alert_total Total CrowdSec alerts tracked
# TYPE security_alert_total gauge
security_alert_total $(sqlite3 "$CONTEXT_DIR/../gateway.db" "SELECT COALESCE(SUM(total_count),0) FROM crowdsec_scenario_stats;" 2>/dev/null || echo 0)
# HELP security_incident_total Total YT issues created from CrowdSec
# TYPE security_incident_total gauge
security_incident_total $(sqlite3 "$CONTEXT_DIR/../gateway.db" "SELECT COALESCE(SUM(yt_issues_created),0) FROM crowdsec_scenario_stats;" 2>/dev/null || echo 0)
# HELP security_scenario_efficacy Per-scenario escalation rate (escalated/total)
# TYPE security_scenario_efficacy gauge
$(sqlite3 "$CONTEXT_DIR/../gateway.db" "SELECT scenario, host, CASE WHEN total_count > 0 THEN ROUND(CAST(escalated_count AS FLOAT) / total_count, 3) ELSE 0 END FROM crowdsec_scenario_stats WHERE total_count > 5;" 2>/dev/null | while IFS='|' read -r s h e; do echo "security_scenario_efficacy{scenario=\"$s\",host=\"$h\"} $e"; done)
# HELP security_mitre_techniques_covered ATT&CK techniques with active detection
# TYPE security_mitre_techniques_covered gauge
security_mitre_techniques_covered $(python3 -c "import json; m=json.load(open('/app/claude-gateway/openclaw/skills/security-triage/mitre-mapping.json')); t=set(); [t.update(v.get('techniques',[])) for v in m.values()]; print(len(t))" 2>/dev/null || echo 0)
# HELP security_metrics_timestamp Last security metrics update
# TYPE security_metrics_timestamp gauge
security_metrics_timestamp $(date +%s)
EOF

mv "$TMPOUT" "$OUT"
