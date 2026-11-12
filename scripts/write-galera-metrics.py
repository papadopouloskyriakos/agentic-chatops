#!/usr/bin/env python3
"""
write-galera-metrics.py — node_exporter textfile metrics for the shared NL Galera cluster
"eu-nl-mariadb01" (IFRNLLEI01PRD-2992, postmortem item 8). READ-ONLY: one SSH per node running
`systemctl show`, `SHOW GLOBAL STATUS`, grastate.dat and df (scripts/lib/galera_cluster.py).

Runs as Cronicle job `galera-metrics` (every minute) on nl-claude01 and writes
/var/lib/node_exporter/textfile_collector/galera.prom, scraped by NL Prometheus job
`chatops-node` (instance nl-claude01). It must NOT honour ~/gateway.maintenance or the
mutation master switch: it is a read-only monitor (postmortem item 19).

Alerts (infrastructure/nl/production k8s/namespaces/monitoring/galera-sel-alerts.tf, test
copy prometheus/alert-rules/galera-sel.yml):
  GaleraNoPrimary            no DB node Primary for 5 min while a DB host answers (critical)
  GaleraStateUnknown         no DB host answers SSH for 10 min (warning)
  GaleraStateExporterStale   this writer has not run for 10 min (warning)

Recovery when GaleraNoPrimary fires: scripts/galera-guarded-bootstrap.py (plan is read-only;
--execute is operator-only, never automatic).
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import galera_cluster as gc  # noqa: E402

TEXTFILE_DIR = os.environ.get("PROMETHEUS_TEXTFILE_DIR", "/var/lib/node_exporter/textfile_collector")
OUT_FILE = os.path.join(TEXTFILE_DIR, "galera.prom")


def _b(v):
    return 1 if v else 0


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render(nodes, arb, started, now):
    c = gc.CLUSTER_NAME
    lines = []

    def metric(name, help_, typ="gauge"):
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} {typ}")

    def each(name, fn):
        for n in nodes:
            v = fn(n)
            if v is not None:
                lines.append(f'{name}{{cluster="{c}",node="{n.name}"}} {v}')

    metric("galera_node_host_reachable", "1 if the Galera DB host answered SSH")
    each("galera_node_host_reachable", lambda n: _b(n.host_reachable))
    metric("galera_node_reachable", "1 if mariadbd answered SHOW GLOBAL STATUS (wsrep values below are only present then)")
    each("galera_node_reachable", lambda n: _b(n.sql_ok))
    metric("galera_node_primary", "1 if wsrep_cluster_status is Primary (0 when non-Primary, mariadbd down or host down)")
    each("galera_node_primary", lambda n: _b(n.primary))
    metric("galera_node_cluster_status", "wsrep_cluster_status as a label (value 1)")
    for n in nodes:
        if n.sql_ok:
            lines.append(f'galera_node_cluster_status{{cluster="{c}",node="{n.name}",status="{_esc(n.cluster_status)}"}} 1')
    metric("galera_node_cluster_size", "wsrep_cluster_size as this node sees it")
    each("galera_node_cluster_size", lambda n: n.cluster_size if n.sql_ok else None)
    metric("galera_node_ready", "1 if wsrep_ready is ON")
    each("galera_node_ready", lambda n: _b(n.ready) if n.sql_ok else None)
    metric("galera_node_local_state", "wsrep_local_state (1 Joining, 2 Donor/Desynced, 3 Joined, 4 Synced)")
    each("galera_node_local_state", lambda n: n.local_state if n.sql_ok else None)
    metric("galera_node_last_committed", "wsrep_last_committed seqno")
    each("galera_node_last_committed", lambda n: n.last_committed if n.sql_ok else None)
    metric("galera_node_mariadbd_running", "1 if a mariadbd process exists on the host")
    each("galera_node_mariadbd_running", lambda n: _b(n.mariadbd_running) if n.host_reachable else None)
    metric("galera_node_disk_used_percent", "used percent of the filesystem holding /var/lib/mysql")
    each("galera_node_disk_used_percent", lambda n: n.disk_used_pct if n.host_reachable else None)
    if arb:
        metric("galera_arbitrator_host_reachable", "1 if the garbd host answered SSH")
        lines.append(f'galera_arbitrator_host_reachable{{cluster="{c}",node="{arb.name}"}} {_b(arb.host_reachable)}')
        metric("galera_arbitrator_active", "1 if garb.service is active")
        lines.append(f'galera_arbitrator_active{{cluster="{c}",node="{arb.name}"}} {_b(arb.active)}')
    metric("galera_cluster_primary_nodes", "number of DB nodes reporting wsrep_cluster_status Primary")
    lines.append(f'galera_cluster_primary_nodes{{cluster="{c}"}} {sum(_b(n.primary) for n in nodes)}')
    metric("galera_exporter_duration_seconds", "wall time of the last collection")
    lines.append(f'galera_exporter_duration_seconds{{cluster="{c}"}} {now - started:.3f}')
    metric("galera_exporter_last_run_timestamp_seconds", "unix time of the last completed run")
    lines.append(f'galera_exporter_last_run_timestamp_seconds{{cluster="{c}"}} {int(now)}')
    return "\n".join(lines) + "\n"


def write_atomic(text):
    os.makedirs(TEXTFILE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".galera.", suffix=".tmp", dir=TEXTFILE_DIR)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, OUT_FILE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    started = time.time()
    nodes, arb = gc.collect_all()
    text = render(nodes, arb, started, time.time())
    if "--stdout" in sys.argv:
        sys.stdout.write(text)
        return 0
    write_atomic(text)
    for n in nodes:
        print(gc.describe(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
