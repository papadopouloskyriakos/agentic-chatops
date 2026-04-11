# SeaweedFS Cross-Site Storage

> Compiled 2026-04-09 06:19 UTC.

## Architecture

Both NL and GR run independent SeaweedFS clusters (v4.01, Helm chart 4.0.401):

| Component | NL | GR |
|-----------|----|----|
| Masters | 3 (leader rotates) | 3 (leader rotates) |
| Filers | 2 (2Gi memory) | 2 (1Gi memory) |
| Volume servers | 2 x 500Gi (iSCSI/SSD) | 2 x 500Gi (**NFS/HDD sdc** — migrated from iSCSI 2026-03-25) |
| filer-sync | 1 pod (handles both directions) | NONE |
| MaxVolumeId | ~436 | ~901 |
| Volume size limit | 1GB (`-volumeSizeLimitMB=1000`) | 1GB |

Cross-site connectivity via **Cilium ClusterMesh global services**:
- `seaweedfs-filer-nl` — local selector on NL, remote-stub on GR
- `seaweedfs-filer-gr` — local selector on GR, remote-stub on NL
- Both annotated `service.cilium.io/global: "true"`

## Replication: Bidirectional via Single filer-sync on NL

The NL filer-sync pod does **bidirectional** replication (NL↔GR). It uses `-a` and `-b` flags without `-isActivePassive`, watching both filers and replicating changes in both directions. Only ONE pod runs (on NL). GR has `enable_cross_site_replication = false` — no redundant filer-sync.

**Why:** Avoids duplicate sync conflicts. Trade-off: NL cluster down = sync stops in both directions.

## Buckets and Exclusions

**Replicated (both directions):**
- `/buckets/cluster-snapshots`
- `/buckets/velero`
- `/buckets/portfolio`

**Excluded from replication (`-a.excludePaths` and `-b.excludePaths`):**
- `/buckets/thanos-nl` (~168 GB on NL)
- `/buckets/thanos-gr` (~174 GB on GR)
- `/buckets/loki` (~44 GB on NL)
- `/buckets/loki-gr` (~51 GB on GR)

**Why:** Thanos and Loki data is site-local by design. Replicating 400GB+ of metrics/logs cross-site would saturate the VPN.

## Known Quirks and Limitations

### 1. Replication factor silently 000 (no intra-cluster copies)
Helm values set `global.replicationPlacment: "001"` but masters run with `-defaultReplication=000`. The Helm chart key has a known typo (`Placment` not `Placement`) — it IS the correct key name for the chart, but the value is overridden by the chart's own command generation. **Result:** Every file has a single copy. Durability relies entirely on the iSCSI backend (Synology/democratic-csi).

**How to apply:** When investigating data loss, don't assume SeaweedFS has replicas. It doesn't. The single copy is on whichever volume server the master assigned.

### 2. filer-sync is a single point of failure
Only runs on NL. If NL K8s cluster is down, GR→NL replication stops AND NL→GR replication stops. No automatic failover. GR IaC has a `cluster-mesh.tf` with filer-sync config but `enable_cross_site_replication = false`.

**How to apply:** During NL maintenance, expect replication lag. filer-sync resumes from where it left off (persistent offset), so data isn't lost — just delayed.

### 3. GR IaC filer-sync config has drift from NL
GR `cluster-mesh.tf` uses `-debug` (global flag) instead of `-a.debug -b.debug` (per-side) and is **missing excludePaths**. If you ever enable filer-sync on GR (`enable_cross_site_replication = true`), it would replicate Thanos/Loki buckets cross-site AND conflict with the NL filer-sync.

**How to apply:** Before enabling GR filer-sync, align the config with NL's excludePaths and debug flags. Never run filer-sync on both sites simultaneously without `-isActivePassive`.

### 4. GR default collection bloat (227GB / 9.2M files)
GR has 227GB in the unnamed default collection (234 volumes). NL's default is only 0.5GB. This is likely filer metadata shards or data written without explicit collection assignment. Warrants investigation.

### 5. VPN dependency for all cross-site traffic
filer-sync, filer-proxy data transfers, and ClusterMesh global service resolution all traverse the IPsec VPN. VPN blips cause filer-sync stalls (resumes automatically) and potentially incomplete file reads if volume data is proxied cross-site.

### 6. excludePaths may log events even when filtering
filer-sync logs show Loki bucket events despite `/buckets/loki` being in excludePaths. Investigation suggests the exclude filter works at the data-transfer level (GR has 0.00GB in `loki` collection) but events are still logged before filtering. This is cosmetic — not a real data leak.

### 7. S3 credentials shared across sites
Both sites use identical S3 accessKey/secretKey (from OpenBao via ExternalSecrets). Required for cross-site replication transparency.

### 8. No erasure coding (EC)
Both sites show 0 EC shards. All data in standard volumes.

### 9. Filer metadata backend is LevelDB2
Both sites use `leveldb2` at `/data/filerldb2`. Not a distributed backend — tied to the filer pod's PVC. If a filer PVC is lost, its portion of the directory tree is gone (the other filer has its own LevelDB2 instance, not a shared one).

## Operational Impact: Node Reboots

**Incident 2026-03-21:** Rolling reboot of GR grk8s-node01+grk8s-node02 caused SeaweedFS volume-1, filer-0, filer-1, master-1, master-2 to restart simultaneously. Low-numbered volumes (3, 7, 65) lost from master registry. Result: thanos-store-0 crash loop (can't read deletion-mark.json from lost volumes), 74 restarts over 7+ hours.

**Lesson:** SeaweedFS has no PodDisruptionBudgets. Draining a node that runs SeaweedFS components can cause cascade restarts affecting data availability. The 000 replication factor means any lost volume = data loss.

## IaC Paths
- NL: `~/gitlab/infrastructure/nl/production/k8s/namespaces/seaweedfs/` (cluster-mesh.tf, values.yaml.tpl, variables.tf)
- GR: `~/gitlab/infrastructure/gr/production/k8s/namespaces/seaweedfs/` (same files)
- NL main.tf: `enable_cross_site_replication = true` (line ~202)
- GR main.tf: `enable_cross_site_replication = false`

## Thanos: NOT Replicated via SeaweedFS (by design)

Thanos uses Thanos Store gRPC federation via ClusterMesh, NOT S3 bucket replication. Each site's Thanos Store reads from its local bucket and serves data to the remote site's Thanos Query over ClusterMesh. This is correct and efficient — the 43ms latency adds ~50ms per gRPC round-trip, well within dashboard query budgets. See [thanos_crosssite.md](thanos_crosssite.md) for details.
