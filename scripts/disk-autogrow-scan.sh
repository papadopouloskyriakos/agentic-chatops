#!/usr/bin/env bash
# disk-autogrow-scan.sh — auto-invoke the disk-pressure remediation ladder for any host
# with an active disk-space alert (operator directive #3, 2026-07-08). Hourly Cronicle.
#
# Finds LibreNMS "Space on /" active alerts (NL+GR) + optional extra hosts, and runs
# scripts/remediate-disk-pressure.py --execute for each. The actuator carries ALL the
# safety (sentinel gate, threshold, pool-25%-free floor, rpool health, pmxcfs-wedge
# pre-flight, 1-grow/guest/7d rate cap, AUTO_NOTICE) — so invoking it broadly is safe;
# a host that is fine, capped, or floor-blocked is a no-op/escalate, never a bad grow.
#
# Disabled unless ~/gateway.disk_autogrow_armed exists (the actuator enforces this too).
set -u
REPO=/app/claude-gateway
cd "$REPO" || exit 0
ENVF="$REPO/.env"
NL_KEY=$(grep -m1 '^LIBRENMS_API_KEY=' "$ENVF" | cut -d= -f2-)
GR_KEY=$(grep -m1 '^LIBRENMS_GR_API_KEY=' "$ENVF" | cut -d= -f2-)

if [ ! -e "$HOME/gateway.disk_autogrow_armed" ]; then
  echo "disk-autogrow-scan: disarmed (~/gateway.disk_autogrow_armed absent) — no-op"
  exit 0
fi

hosts_with_space_alert() {  # <base_url> <key>
  curl -sk -H "X-Auth-Token: $2" "$1/api/v0/alerts?state=1" 2>/dev/null | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit()
seen=set()
for a in (d.get("alerts") or []):
    rule=(str(a.get("rule") or a.get("name") or "")+" "+str(a.get("title") or "")).lower()
    if "space on" in rule or ("disk" in rule and "space" in rule) or "/ is >=" in rule:
        h=a.get("hostname") or a.get("sysName")
        if h and h not in seen:
            seen.add(h); print(h)
'
}

RAN=0
for h in $( { hosts_with_space_alert "https://nl-nms01.example.net" "$NL_KEY";
              hosts_with_space_alert "https://gr-nms01.example.net" "$GR_KEY"; } | sort -u); do
  # strip any domain suffix; the actuator resolves via live pvesh
  short="${h%%.*}"
  echo "disk-autogrow-scan: disk-space alert on $short — invoking actuator"
  timeout 300 python3 "$REPO/scripts/remediate-disk-pressure.py" --host "$short" --execute 2>&1 | tail -1
  RAN=$((RAN+1))
done
echo "disk-autogrow-scan: processed $RAN host(s) with active disk-space alerts"
exit 0
