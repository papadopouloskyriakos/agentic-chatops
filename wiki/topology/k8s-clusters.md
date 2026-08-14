# Kubernetes Clusters

> Compiled from 2 CLAUDE.md files + 5 memories. 2026-07-03 04:30 UTC.

## NL: k8s/CLAUDE.md

- **Cluster**: `nlcl01k8s` (ID: 1), K8s v1.34.2, API at `api-k8s.example.net:6443`
- **Nodes**: 3 control-plane (4 CPU, 8GB — ctrl02 4GB on pve02, ctrl01+ctrl03 upgraded 4→8GB on 2026-03-15) + 4 workers (8 CPU, 8GB), all Ubuntu 24.04, IPs 10.0.X.X-12 (CP), .20-23 (workers)
- **CNI**: Cilium v1.18.4, eBPF, kubeProxyReplacement, VXLAN tunneling, MTU 1350
- **Pod CIDR**: 10.0.0.0/16 (NL), 10.1.0.0/16 (GR) — must not overlap for ClusterMesh
- **ClusterMesh**: Connected to GR cluster `grcl01k8s` at 10.0.58.X:2379, mTLS via ExternalSecret from OpenBao
│   ├── cilium/          # CNI, BGP, ClusterMesh, SPIRE mTLS, Hubble
│   ├── external-secrets/# ClusterSecretStore "openbao" with Kubernetes auth
│   └── pod-disruption-budgets/ # CoreDNS + Metrics Server PDBs
    ├── pihole/          # DNS ad-blocker with Cilium network policy
- ClusterSecretStore name is `openbao` — reference it in all ExternalSecret specs
- cert-manager pushes the wildcard cert to OpenBao via PushSecret for GR cluster consumption
- Cilium BGP: local ASN 65001 peers with ASA firewall at 10.0.X.X (ASN 65000)
- Current LB allocations: .64 (ingress-nginx), .65 (hubble-relay), .66 (pihole-dns-tcp), .67 (pihole-dns-udp), .68 (promtail-syslog), .69 (clustermesh-api)
- **SPIRE mTLS**: Cilium mutual TLS for pod-to-pod authentication
- **Cilium Network Policies**: Applied to pihole, logging, gatus, well-known namespaces
- **Thanos**: Query (2 replicas) + Store (2 replicas, SeaweedFS S3) + Compactor. GR store reached via ClusterMesh.
- **Grafana**: 2 replicas, NFS-backed (20Gi). Datasources: Prometheus (local), Thanos (cross-site), Loki (logs). 10 custom dashboards provisioned via sidecar ConfigMaps (`grafana_dashboard=1` label) — 6 managed by OpenTofu in `dashboards.tf`, 4 via kubectl. Dashboard JSON source files in `namespaces/monitoring/dashboards/`. Never import dashboards via Grafana UI — they don't survive pod restarts.
- **Goldpinger**: DaemonSet for cross-node connectivity/latency testing
## Cluster Snapshots
- Auto-generated daily by `k8s-cluster-snapshot.sh v3.1.0` at 03:00 UTC
- `cluster-snapshots/latest.md` — current state
- `cluster-snapshots/cluster-context-lite.md` — 3K token summary for quick troubleshooting
- `cluster-snapshots/cluster-context-full.md` — 10K token deep analysis
- `cluster-snapshots/history/` — 130+ daily snapshots since 2025-11-27
- Read `cluster-context-lite.md` first when debugging cluster issues
n8n Prometheus Alert Receiver (24 nodes, ID: CqrN7hNiJsATcJGE)
**Custom alert rules** (`custom-alerts.tf`): ContainerOOMKilled, ContainerMemoryNearLimit, IngressNoBackendEndpoints, IngressHighErrorRate, IngressCertificateExpiringSoon, CiliumAgentNotReady, CiliumEndpointNotReady, CiliumPolicyImportErrors, NFSMountStale, NFSMountHighLatency, ArgocdAppDegraded, ArgocdAppOutOfSync, HighPodRestartRate.
**YT custom fields set by k8s-triage.sh:** Hostname, Alert Rule, Severity, Namespace, Pod, Alert Source (`Prometheus`).
- **kube-apiserver on ctrl01**: 754 restarts (exit code 137/SIGKILL) caused by etcd I/O starvation from PVE host memory pressure. Root cause: nl-pve01 ran 53 guests at 2.5x overcommit with zero swap, leaving only 1.9 GB free. etcd raft consensus latency 100-433ms (should be <10ms) causes apiserver readiness probe HTTP 500s (21,636 failures), then liveness probe kills it. Mitigated 2026-04-15: shut down nlandroidsdk01 (freed ~9.7 GB, host free 1.9->10 GB). Monitor: if restarts resume, further VM migration or swap addition needed.
- **SeaweedFS filer**: Helm cleanup + filer memory re-applied at 2Gi (MR !229, 2026-03-15). Multipath/iSCSI conflict fixed via Synology multipath blacklist on all 7 K8s nodes.
- **SeaweedFS cross-site replication — stale-checkpoint recovery (MR !290, 2026-05-05)**: Two independent failure modes, same shape (persisted offset → GC'd change-log volume → permanent retry-loop). Symptom: PUT to one site doesn't appear on the other; or appears intermittently because the GR cluster-service round-robins between filers and only one has the data. (1) **Cross-site `filer.sync`** — recover by setting `filer_sync_{a,b}_from_ts_ms` in `main.tf`'s `module "seaweedfs"` block to a recent ms timestamp; **upstream's `-{a,b}.fromTsMs` flags are inverted** (`-a.fromTsMs` controls direction `b→a`, REMOTE→LOCAL — the variable's description block has full notes). MR + `atlantis apply`; pod rolling-restart picks it up. (2) **GR intra-cluster `meta_aggregator`** between `seaweedfs-filer-0` ↔ `seaweedfs-filer-1` — recover via gRPC `KvPut` on each filer's `Meta`+peer-signature key with a recent ns. Tool + step-by-step in claude-gateway: `scripts/seaweedfs/fix_meta_offset.py`, `docs/runbooks/seaweedfs-cross-site-replication.md`. **Diagnostic gotcha**: read state per-pod (port-forward each `seaweedfs-filer-N` directly), not via the cluster-service — round-robin hides per-pod metadata divergence.
- **cilium-operator**: 90+ restarts accumulated — not a recent regression
- Do not change Pod CIDR (10.0.0.0/16) — it must not overlap with GR cluster (10.1.0.0/16)

## GR: k8s/CLAUDE.md

- **Cluster**: `grcl01k8s` (ID: 2), API at `gr-api-k8s.example.net:6443`
- **Nodes**: 3 workers, IPs 10.0.58.X, .58.21, .58.22
- **CNI**: Cilium v1.18.4, eBPF, kubeProxyReplacement, VXLAN tunneling
- **Pod CIDR**: 10.1.0.0/16 (GR), 10.0.0.0/16 (NL) — must not overlap for ClusterMesh
- **ClusterMesh**: Connected to NL cluster `nlcl01k8s` at 10.0.X.X, mTLS via ExternalSecret from OpenBao
│   ├── cilium/          # CNI, BGP, ClusterMesh, SPIRE mTLS, Hubble
│   ├── external-secrets/# ClusterSecretStore "openbao" + TokenReview RBAC
│   └── pod-disruption-budgets/ # CoreDNS + Metrics Server PDBs
- ClusterSecretStore name is `openbao` — reference it in all ExternalSecret specs
- Cilium BGP: local ASN 65001 peers with ASA firewall at 10.0.58.X (ASN 65000)
- **SPIRE mTLS**: Cilium mutual TLS for pod-to-pod authentication
- **CiliumNetworkPolicy**: Applied to gatus namespace
- **Thanos**: Cross-site query federation with NL via ClusterMesh
- **Goldpinger**: Cross-node connectivity/latency testing
| Pod Disruption Budgets | CoreDNS + Metrics Server PDBs | Missing | Medium |
| Cluster snapshots | Daily auto-generated, 130+ history | None | Low |
- Do not change Pod CIDR (10.1.0.0/16) — it must not overlap with NL cluster (10.0.0.0/16)
- Do not change Cilium cluster ID (2) — it must be unique across the ClusterMesh and is paired with NL cluster ID 1
