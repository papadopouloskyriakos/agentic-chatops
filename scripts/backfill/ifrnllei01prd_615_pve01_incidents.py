#!/usr/bin/env python3
"""IFRNLLEI01PRD-615 backfill: pve01 memory-pressure incidents missed by
session-end auto-ingestion. These incidents were investigated and closed
via direct SSH triage rather than a Claude Code session, so the
claude-gateway-session-end.json writer never fired.

Inserts 3 rows (IFRNLLEI01PRD-566/567/589) into incident_knowledge with
root_cause + resolution extracted from the corresponding memory files.
Embedding happens via kb-semantic-search.py embed after insert.
"""
import os
import sqlite3
import sys

DB = os.path.expanduser("~/gitlab/products/cubeos/claude-context/gateway.db")

ROWS = [
    {
        "issue_id": "IFRNLLEI01PRD-566",
        "alert_rule": "KubeClientErrors",
        "hostname": "nlk8s-ctrl01",
        "site": "nl",
        "root_cause": (
            "nl-pve01 memory pressure: 53 guests (9 VMs + 44 LXCs), 2.5x memory "
            "overcommit, zero swap, only 1.9 GB free of 94 GB. Pressure starved etcd I/O "
            "on nlk8s-ctrl01 (raft consensus 100-433ms vs <10ms target, KV/Range "
            "DeadlineExceeded). kube-apiserver gRPC to local etcd failed every ~12s, "
            "readiness probe HTTP 500 (21,636 failures), kubelet SIGKILL after 8 liveness "
            "failures -> 754 apiserver restarts on ctrl01."
        ),
        "resolution": (
            "Shut down nlandroidsdk01 (freed ~9.7 GB, 8 CPUs) + nldmz02 (already "
            "stopped, onboot=0). Host free: 1.9 GB -> 10 GB, available: 10 GB -> 19 GB. "
            "ctrl02/ctrl03 unaffected because their PVE hosts have less memory pressure. "
            "Long-term: enable balloon on ctrl01, or add swap to pve01, or migrate a VM "
            "to pve02/pve03. See memory pve01_memory_pressure_apiserver_20260415.md."
        ),
        "confidence": 0.92,
        "created_at": "2026-04-15 13:30:00",
        "tags": "pve01,memory-pressure,apiserver,etcd,kubernetes,androidsdk01",
    },
    {
        "issue_id": "IFRNLLEI01PRD-567",
        "alert_rule": "KubeAPIErrorBudgetBurn",
        "hostname": "nlk8s-ctrl01",
        "site": "nl",
        "root_cause": (
            "Cascading from IFRNLLEI01PRD-566. The apiserver restart cycle on ctrl01 "
            "(754 kubelet SIGKILLs) caused the API error budget burn rate to cross the "
            "warning threshold. Same underlying pve01 memory-pressure starvation -> "
            "etcd deadline exceeded -> gRPC failures -> 500-class readiness probes."
        ),
        "resolution": (
            "Same mitigation as IFRNLLEI01PRD-566: shut down nlandroidsdk01 on pve01. "
            "Error budget recovered after restart storm ended. Both -566 and -567 moved "
            "to Done. Monitor apiserver_restart_total; if resumes, escalate to VM "
            "migration off pve01."
        ),
        "confidence": 0.90,
        "created_at": "2026-04-15 16:00:00",
        "tags": "pve01,memory-pressure,apiserver,error-budget,cascading",
    },
    {
        "issue_id": "IFRNLLEI01PRD-589",
        "alert_rule": "n8n SQLite mutex timeout",
        "hostname": "nl-n8n01",
        "site": "nl",
        "root_cause": (
            "Same pve01 memory-pressure class as IFRNLLEI01PRD-566/567. pve01 at "
            "74.8/94 GB used, zero swap, load avg 21.5, /proc/pressure/io some avg10=59.24 "
            "(severe). IO spike starved the n8n LXC's SQLite writer mutex (default 200ms "
            "timeout) -> n8n returned 503 'Database is not ready' upstream -> cascading "
            "ECONNRESET / 'Connection lost before handshake' on in-flight TLS. Self-healed "
            "in ~90s. n8n internals never actually broke; NPM + local port 5678 stayed "
            "healthy throughout. Heaviest VMs on pve01 at time: nlk8s-node01 (47% "
            "CPU), nlk8s-ctrl01 (42% CPU), nl-dmz01 (131% CPU). androidsdk01 "
            "was still stopped from 2026-04-15, but pve01 workload pressure regrew."
        ),
        "resolution": (
            "Self-healed in ~90s. No intervention needed. Recurring failure class: "
            "zero swap + 80% mem + high IO VMs co-located. Open remediation options: "
            "(1) add zram/swap on pve01, (2) bump n8n LXC 2G->4G RAM, "
            "(3) live-migrate n8n LXC off pve01 to pve02/pve03, "
            "(4) investigate workload growth after androidsdk01 shutdown. "
            "See memory incident_n8n_sqlite_mutex_20260416.md for full timeline."
        ),
        "confidence": 0.95,
        "created_at": "2026-04-16 20:20:00",
        "tags": "pve01,memory-pressure,n8n,sqlite,mutex,recurring-class",
    },
]


def main():
    dry_run = "--dry-run" in sys.argv
    conn = sqlite3.connect(DB)

    # Check for existing rows (idempotency)
    existing = {r[0] for r in conn.execute(
        "SELECT issue_id FROM incident_knowledge WHERE issue_id IN "
        "('IFRNLLEI01PRD-566','IFRNLLEI01PRD-567','IFRNLLEI01PRD-589')"
    ).fetchall()}
    print(f"Existing rows for these issue_ids: {sorted(existing) if existing else 'none'}")

    if dry_run:
        for r in ROWS:
            marker = "[skip]" if r["issue_id"] in existing else "[WOULD INSERT]"
            print(f"  {marker} {r['issue_id']} {r['alert_rule']} @ {r['hostname']}")
        return

    inserted = 0
    for r in ROWS:
        if r["issue_id"] in existing:
            print(f"  [skip] {r['issue_id']} already in incident_knowledge")
            continue
        conn.execute(
            "INSERT INTO incident_knowledge "
            "(alert_rule, hostname, site, root_cause, resolution, confidence, "
            "created_at, issue_id, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (r["alert_rule"], r["hostname"], r["site"], r["root_cause"],
             r["resolution"], r["confidence"], r["created_at"], r["issue_id"], r["tags"]),
        )
        inserted += 1
        print(f"  [ok] inserted {r['issue_id']}")
    conn.commit()
    conn.close()
    print(f"\nInserted: {inserted}/{len(ROWS)}. Next: run 'python3 scripts/kb-semantic-search.py embed' to generate embeddings.")


if __name__ == "__main__":
    main()
