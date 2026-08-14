#!/bin/bash
# write-pve-wedge-metrics.sh — Prometheus textfile metrics for the PVE pmxcfs-wedge
# signature on nl-pve01 (and any host in PVE_WEDGE_HOSTS).
#
# WHY THIS EXISTS (IFRNLLEI01PRD-1501): nl-pve01 has wedged its pmxcfs (the
# /etc/pve FUSE fs) 3× (2026-06-23/-27/-30; the -30 wedge took matrix down). The
# signature is load-avg 100+ while CPU is ~IDLE — dozens of pvesh/qm/pvestatd
# stuck in D-state on /etc/pve. The only alert that fired was a generic
# NodeSaturation, which mis-reads it as CPU. pve01 is NOT a node_exporter or
# snmp_exporter Prometheus target, and the no-install-on-PVE rule forbids putting
# an exporter on it — so this collector runs on nl-claude01 (which IS a
# textfile-collector target), SSHes to each PVE host, and emits the wedge
# signature. Paired with the PVEPmxcfsWedge* alerts (host-pressure-alerts.tf).
#
# Metrics (labeled by host):
#   pve_wedge_dstate_procs{host}         gauge  D-state pvesh/qm/pct/pvestatd/pveproxy count
#   pve_wedge_pmxcfs_probe_seconds{host} gauge  wall time of `pvesh get /cluster/status`
#   pve_wedge_pmxcfs_probe_ok{host}      gauge  1 if probe returned rc=0 in time, else 0
#   pve_wedge_guests_status_unknown{host} gauge guests whose status != running/stopped (pvestatd blind)
#   pve_wedge_collector_up{host}         gauge  1 if the SSH snapshot itself succeeded, else 0 (host unreachable/SSH-wedged)
#   pve_wedge_collector_last_run_timestamp_seconds  gauge  unix ts of this run (staleness guard)

set -uo pipefail

REPO_DIR="/app/claude-gateway"
OUTDIR="${PROMETHEUS_TEXTFILE_DIR:-/var/lib/node_exporter/textfile_collector}"
TARGET="$OUTDIR/pve-wedge-metrics.prom"
TMP="$TARGET.$$.tmp"
KEY="${PVE_WEDGE_SSH_KEY:-/home/app-user/.ssh/one_key}"
HOSTS="${PVE_WEDGE_HOSTS:-nl-pve01}"
SSH_DEADLINE="${PVE_WEDGE_SSH_DEADLINE:-20}"   # hard ceiling on the whole SSH+probe round-trip
LOG_FILE="/home/app-user/logs/claude-gateway/pve-wedge-metrics.log"

mkdir -p "$OUTDIR" "$(dirname "$LOG_FILE")"

# Suppression: skip during maintenance window or active chaos test (a PDU/maint
# reboot legitimately makes the host unreachable — don't emit a false wedge).
# shellcheck source=scripts/lib/suppression-gates.sh
source "$REPO_DIR/scripts/lib/suppression-gates.sh"
check_suppression_gates || exit 0

now_ts=$(date +%s)

# Remote collector: one SSH round-trip per host, transported base64 to dodge quoting.
# Mirrors logs/claude-gateway/pve-snap.py but self-contained so it has no path dep.
read -r -d '' REMOTE <<'PYEOF'
REDACTED_a7b84d63,json,subprocess,time
def sh(c,t=10):
    try: return subprocess.run(c,shell=True,capture_output=True,text=True,timeout=t).stdout
    except Exception: return ""
dstate=0
for l in sh("ps -eo stat,comm").splitlines():
    f=l.split()
    if len(f)>=2 and f[0][:1]=="D" and re.match(r"(pvesh|qm|pct|pvestatd|pveproxy|pve-ha)",f[1]):
        dstate+=1
t0=time.time()
p=subprocess.run("pvesh get /cluster/status --output-format json",shell=True,
                 capture_output=True,text=True,timeout=8)
probe_s=round(time.time()-t0,3); probe_ok=1 if p.returncode==0 and p.stdout.strip() else 0
gr=sh("pvesh get /cluster/resources --type vm --output-format json 2>/dev/null",t=8)
unknown=0
try:
    import os
    me=os.uname().nodename
    for v in json.loads(gr):
        if v.get("node")==me and v.get("status") not in ("running","stopped"):
            unknown+=1
except Exception:
    unknown=-1   # couldn't enumerate guests (pmxcfs likely already wedged)
print(json.dumps({"dstate":dstate,"probe_s":probe_s,"probe_ok":probe_ok,"unknown":unknown}))
PYEOF
B64=$(printf '%s' "$REMOTE" | base64 -w0)

{
  echo "# HELP pve_wedge_dstate_procs D-state pvesh/qm/pct/pvestatd/pveproxy procs (pmxcfs-wedge canary)."
  echo "# TYPE pve_wedge_dstate_procs gauge"
  echo "# HELP pve_wedge_pmxcfs_probe_seconds Wall time of 'pvesh get /cluster/status' on the host."
  echo "# TYPE pve_wedge_pmxcfs_probe_seconds gauge"
  echo "# HELP pve_wedge_pmxcfs_probe_ok 1 if the pmxcfs probe returned rc=0 with output in time, else 0."
  echo "# TYPE pve_wedge_pmxcfs_probe_ok gauge"
  echo "# HELP pve_wedge_guests_status_unknown Guests on the host whose status is neither running nor stopped (pvestatd blind); -1 if guest list couldn't be read."
  echo "# TYPE pve_wedge_guests_status_unknown gauge"
  echo "# HELP pve_wedge_collector_up 1 if the SSH snapshot to the host succeeded, else 0 (host down or SSH-wedged)."
  echo "# TYPE pve_wedge_collector_up gauge"

  for host in $HOSTS; do
    raw=$(timeout "$SSH_DEADLINE" ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 \
            -o StrictHostKeyChecking=no "root@$host" \
            "echo $B64 | base64 -d | python3 -" 2>/dev/null)
    if [ -z "$raw" ]; then
      # SSH itself failed/timed out — host unreachable OR so wedged sshd can't fork.
      # collector_up=0 is itself a wedge/outage signal; emit it (the alert keys on it).
      echo "pve_wedge_collector_up{host=\"$host\"} 0"
      continue
    fi
    vals=$(printf '%s' "$raw" | python3 -c '
import sys,json
try:
    d=json.loads(sys.stdin.read())
    print(f'"'"'{d["dstate"]} {d["probe_s"]} {d["probe_ok"]} {d["unknown"]}'"'"')
except Exception:
    print("PARSEFAIL")' 2>/dev/null)
    if [ "$vals" = "PARSEFAIL" ] || [ -z "$vals" ]; then
      echo "pve_wedge_collector_up{host=\"$host\"} 0"
      continue
    fi
    read -r d_dstate d_probe d_ok d_unknown <<< "$vals"
    echo "pve_wedge_collector_up{host=\"$host\"} 1"
    echo "pve_wedge_dstate_procs{host=\"$host\"} $d_dstate"
    echo "pve_wedge_pmxcfs_probe_seconds{host=\"$host\"} $d_probe"
    echo "pve_wedge_pmxcfs_probe_ok{host=\"$host\"} $d_ok"
    echo "pve_wedge_guests_status_unknown{host=\"$host\"} $d_unknown"
  done

  echo "# HELP pve_wedge_collector_last_run_timestamp_seconds Unix ts of the last collector run (staleness guard)."
  echo "# TYPE pve_wedge_collector_last_run_timestamp_seconds gauge"
  echo "pve_wedge_collector_last_run_timestamp_seconds $now_ts"
} > "$TMP" 2>>"$LOG_FILE"

# Atomic publish (node_exporter must never read a half-written file).
mv -f "$TMP" "$TARGET"
