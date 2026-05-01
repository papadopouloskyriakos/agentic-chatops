# Kubernetes Clusters

> Compiled from 2 CLAUDE.md files + 2 memories. 2026-04-11 14:13 UTC.

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
- **kube-apiserver on ctrl01**: Intermittent HTTP 500 probe failures, 370+ restarts — present for entire cluster lifetime, does not impact stability
- **SeaweedFS filer**: Helm cleanup + filer memory re-applied at 2Gi (MR !229, 2026-03-15). Multipath/iSCSI conflict fixed via Synology multipath blacklist on all 7 K8s nodes.
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
