#!/usr/bin/env python3
"""write-fisha-backup-metrics.py -- node_exporter textfile collector for the
nightly file-level backup of the FISHA OCFS2 volume (Nextcloud + Home Assistant
data).

The backup is /opt/pve-backups/pbc-host-backup.sh, root cron 04:00 UTC on
nlcl01file01/02: the node running nfs-group adds ocfs2.pxar:/mnt/ocfs2 to
its host/<node> group on nlpbs01. A failed run leaves no trace outside that
node's own log (2026-11-07: "No route to host", nobody told).

This reads the result from the PBS datastore rather than from the node, so a
cron that never ran, a node that is down and a failed upload all look the same:
no new snapshot. A snapshot only counts when it is finished (index.json.blob
exists) and actually contains the OCFS2 archive. Only the newest one across both
nodes is published, so a failover does not leave an old series behind.

Read-only. Output: /var/lib/node_exporter/textfile_collector/fisha_backup.prom
Alerts: nfs-alerts.tf group fisha-ocfs2-backup (infra NL), test copy
prometheus/alert-rules/fisha-backup.yml.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
OUT_FILE = os.path.join(TEXTFILE_DIR, "fisha_backup.prom")
PBS_HOST = "nlpbs01"
SSH_KEY = os.path.expanduser("~/.ssh/one_key")
SSH_TIMEOUT_SECONDS = 90

# Runs on the PBS host. Prints one JSON object, or {} when nothing qualifies.
REMOTE = r"""
import json, os, subprocess
root = "/mnt/datastore/ds01/host"
best = None
for node in sorted(os.listdir(root)):
    if not node.startswith("nlcl01file") or node.startswith("nlcl01filearb"):
        continue
    group = os.path.join(root, node)
    for snap in sorted(os.listdir(group), reverse=True):
        path = os.path.join(group, snap)
        if not snap.startswith("20"):
            continue
        if os.path.exists(path + "/ocfs2.pxar.didx") and os.path.exists(path + "/index.json.blob"):
            if best is None or snap > best[1]:
                best = (node, snap, path)
            break
if best is None:
    print("{}")
else:
    out = subprocess.run(
        ["proxmox-backup-debug", "inspect", "file", "--decode", "-", best[2] + "/index.json.blob"],
        capture_output=True, text=True, timeout=60, check=True).stdout
    manifest, _ = json.JSONDecoder().raw_decode(out.lstrip())
    size = [f["size"] for f in manifest["files"] if f["filename"] == "ocfs2.pxar.didx"][0]
    print(json.dumps({"node": best[0], "snapshot": best[1], "size": size}))
"""


def fetch():
    """Return the newest finished OCFS2 snapshot as a dict, {} if there is none."""
    result = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
         f"root@{PBS_HOST}", "python3", "-"],
        input=REMOTE, capture_output=True, text=True,
        timeout=SSH_TIMEOUT_SECONDS, check=True)
    return json.loads(result.stdout)


def render(snapshot, collector_up):
    lines = [
        "# HELP fisha_ocfs2_backup_collector_up 1 if the PBS datastore could be read on the last run.",
        "# TYPE fisha_ocfs2_backup_collector_up gauge",
        f"fisha_ocfs2_backup_collector_up {collector_up}",
        "# HELP fisha_ocfs2_backup_collector_last_run_timestamp_seconds Last run of this collector.",
        "# TYPE fisha_ocfs2_backup_collector_last_run_timestamp_seconds gauge",
        f"fisha_ocfs2_backup_collector_last_run_timestamp_seconds {int(time.time())}",
    ]
    if snapshot:
        taken = datetime.datetime.strptime(snapshot["snapshot"], "%Y-%m-%dT%H:%M:%SZ")
        taken = taken.replace(tzinfo=datetime.timezone.utc)
        node = snapshot["node"]
        lines += [
            "# HELP fisha_ocfs2_backup_last_success_timestamp_seconds Start time of the newest finished OCFS2 snapshot on nlpbs01.",
            "# TYPE fisha_ocfs2_backup_last_success_timestamp_seconds gauge",
            f'fisha_ocfs2_backup_last_success_timestamp_seconds{{node="{node}"}} {int(taken.timestamp())}',
            "# HELP fisha_ocfs2_backup_last_size_bytes Size of ocfs2.pxar in that snapshot.",
            "# TYPE fisha_ocfs2_backup_last_size_bytes gauge",
            f'fisha_ocfs2_backup_last_size_bytes{{node="{node}"}} {snapshot["size"]}',
        ]
    return "\n".join(lines) + "\n"


def write(payload):
    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".fisha_backup.", suffix=".prom", dir=TEXTFILE_DIR)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        os.chmod(tmp, 0o644)
        os.replace(tmp, OUT_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    try:
        snapshot = fetch()
    except Exception as exc:  # the dead-man alert reports this
        print(f"collector failed: {exc}", file=sys.stderr)
        write(render(None, 0))
        return 1
    write(render(snapshot, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
