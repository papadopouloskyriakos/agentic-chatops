#!/usr/bin/env bash
# seed-operator-blast-radius.sh — idempotently (re)install the operator-directed
# Tier-1 blast-radius suppression rows (2026-07-08 alert-automation directives #4/#5/#6).
#
# These fold recurring Device-Down noise from KNOWN-offline GR devices into their
# open tracking issue instead of spawning a new issue/session per alert. The fold is
# active ONLY while the parent issue is Open (tier1_suppression.py checks live YT
# state, fail-OPEN) — close the parent to instantly re-arm normal alerting.
#
#   IFRGRSKG01PRD-85  -> grpikvm01           (bricked since 2026-03-21, on-site fix)
#   IFRGRSKG01PRD-284 -> grap01 + cam01/cam02 (ap01 UTP pulled 07-06; cameras lose
#                                                    signal on the shared segment = ap01
#                                                    blast-radius, operator-confirmed)
#
# Reversible + reviewable: this script is the source of truth; re-running it replaces
# the operator-directed rows with identical content (won't touch other blast-radius
# rows like the infragraph-generated -1046/-1397 or the legacy -894/-241 control issues).
# Ref: memory/alert_automation_policy_decisions_20260708, blast_radius_control_issues_20260512.
set -euo pipefail
DB="${GATEWAY_DB:-/home/app-user/gateway-state/gateway.db}"

GATEWAY_DB="$DB" python3 - <<'PY'
import os, sqlite3, json, datetime
db = os.environ["GATEWAY_DB"]
now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
RULES = ["*Device Down*", "*ICMP*", "*SNMP*", "*up/down*", "*Port status*", "*Service up*"]
rows = [
  ("IFRGRSKG01PRD-85", {
     "hosts": ["grpikvm01"], "host_patterns": [], "rules": RULES,
     "description": "grpikvm01 bricked since 2026-03-21 (corrupted libgcc from forced pacman upgrade); recovery requires on-site SD reflash (docs/pikvm-recovery-guide.md). Recurring Device-Down is expected noise until physically fixed.",
     "started_at": "2026-03-21T00:00:00Z",
     "activation": "Operator directive 2026-07-08 (alert_automation_policy #4). Active while IFRGRSKG01PRD-85 is open; close -85 after physical recovery to re-arm.",
     "generated_by": "operator-directed"}),
  ("IFRGRSKG01PRD-284", {
     "hosts": ["grap01", "grcam01", "grcam02"], "host_patterns": [], "rules": RULES,
     "description": "grap01 deliberately disconnected (UTP pulled 2026-07-06; zombie since 06-26, RCA pending). grcam01/cam02 are ap01 blast-radius - they lose signal on the shared wireless segment while ap01 is down (operator-confirmed 2026-07-08). A camera still flapping AFTER ap01 is reconnected is a real hardware fault.",
     "started_at": "2026-07-06T00:00:00Z",
     "activation": "Operator directive 2026-07-08 (alert_automation_policy #5+#6). Active while IFRGRSKG01PRD-284 is open; close -284 after ap01 reconnect+RCA to re-arm.",
     "generated_by": "operator-directed"}),
]
conn = sqlite3.connect(db, timeout=30)
conn.execute("PRAGMA busy_timeout=30000")
for key, val in rows:
    conn.execute("DELETE FROM openclaw_memory WHERE category='blast-radius' AND key=? AND value LIKE '%operator-directed%'", (key,))
    conn.execute("INSERT INTO openclaw_memory (category, key, value, issue_id, updated_at) VALUES ('blast-radius', ?, ?, ?, ?)",
                 (key, json.dumps(val), key, now))
conn.commit()
n = conn.execute("SELECT COUNT(*) FROM openclaw_memory WHERE category='blast-radius' AND value LIKE '%operator-directed%'").fetchone()[0]
conn.close()
print(f"seed-operator-blast-radius: {n} operator-directed blast-radius row(s) installed.")
PY
