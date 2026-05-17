# SeaweedFS Cross-Site Storage

> Compiled 2026-05-06 00:48 UTC.

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

# SeaweedFS cross-site replication recovery — 2026-05-05

**Status:** RESOLVED end-to-end + DOCUMENTED. Health re-verified 2026-05-05 15:53 UTC (filer-sync 67 min uptime / 0 errors; 0 `volume not found` on all 4 filer pods; bidirectional PUT/GET 200; 10/10 stress reads via GR cluster-mesh).

**Documentation shipped:**
- Runbook: `docs/runbooks/seaweedfs-cross-site-replication.md` (claude-gateway, full triage + recovery A/B + verification)
- K8s CLAUDE.md Known Issues entry (Atlantis MR !291, merged sha `4e598cb`)
- claude-gateway CLAUDE.md: runbook list entry + 2026-05-05 incident summary at the end
- Recovery script: `scripts/seaweedfs/fix_meta_offset.py` + `filer.proto` (pinned v4.01) + `README.md`

## Two distinct stale-checkpoint failures, same pattern

Both failures = persisted offset pointing into a SeaweedFS change-log volume that was later GC'd. Both manifest as `failed to get next log entry for HH-MM.<chunk-id>: volume <N> not found`. Both required overriding the stored offset with a recent ns timestamp; once normal flow advances past it, override is silently no-op'd.

### Failure 1 — cross-site `filer.sync` (NL pod)

- Stuck since 2025-12-11 19:07:15 UTC. Volumes 1, 2 of GR's change-log gone.
- Affected `b→a` (GR→NL). `a→b` was healthy but starved by retry-spam (~10 min lag).
- **Counter-intuitive upstream flag:** in SeaweedFS v4.01 (verified vs `weed/command/filer_sync.go` @ tag 4.01), `-a.fromTsMs` controls direction `b→a` (sync that LANDS on filer A), `-b.fromTsMs` controls `a→b`. Confirmed empirically — first attempt set `-b.fromTsMs` and the override appeared on the WORKING direction in the logs; corrective commit swapped it.
- Fix: Atlantis MR !290 added conditional `-{a,b}.fromTsMs <ms>` flags via two new variables `filer_sync_a_from_ts_ms` / `filer_sync_b_from_ts_ms`. Set both to `VMID_REDACTED0258` (2026-05-05 14:31:50 UTC) as a permanent floor.
- Files: `infrastructure/nl/production/k8s/main.tf`, `namespaces/seaweedfs/cluster-mesh.tf`, `namespaces/seaweedfs/variables.tf`. Two commits: `59ac870` (initial, wrong assignment) + `2f5897b` (corrective swap). Merged 2026-05-05 15:15.

### Failure 2 — GR intra-cluster meta_aggregator

- GR's filer-0 ↔ filer-1 couldn't follow each other's metadata streams. Errors had been continuous since 2025-12-28 (filer-1→filer-0, volume 3) and 2026-03-24 (filer-0→filer-1, volume 918).
- Symptom: cross-site writes landed on whichever GR filer Cilium load-balanced to (filer-0 most of the time), but the OTHER filer never learned about them. Reads via `seaweedfs-filer` cluster service returned 404 ~50% of the time depending on round-robin.
- **Easy to miss in diagnosis** — `kubectl logs deploy/seaweedfs-filer-sync` shows happy progression because filer-sync's a→b stream IS receiving NL events. The break is downstream of filer-sync, INSIDE GR cluster, between filer pods. Must `kubectl logs seaweedfs-filer-1 -n seaweedfs` on each cluster to see meta_aggregator state, AND list buckets per-pod (port-forward each pod individually) to see which has what data.
- Fix: each filer's persistent peer-follow offset is in its leveldb under key `Meta` + 4 bytes BE of peer signature, value = uint64 BE ns. Filer's gRPC `KvPut` (no `KvDelete` exposed) overwrites it; meta_aggregator retries every ~2s and re-reads, so no pod restart needed.
- Tool: `scripts/seaweedfs/fix_meta_offset.py` (committed in claude-gateway). README: `scripts/seaweedfs/README.md`. Compile-from-proto setup; gRPC needs port-forward 18888 from each filer pod.
- Verified: post-fix `meta_aggregator.go:185 subscribing remote ... meta change: 2026-05-05 15:11:31` on both filers, zero `volume not found` errors, 10/10 stress reads via cluster-mesh return 200.

## Architectural lesson (write to feedback memory if not already there)

**Cluster-mesh `seaweedfs-filer-<remote>` round-robins across remote filer pods.** This means cross-site writes via the stub service can land on EITHER pod, and intra-cluster meta_aggregator must be healthy for the OTHER pod to see them. Cross-site replication health = `filer.sync` health × intra-cluster meta_aggregator health on the destination. Diagnose both before declaring fix complete.

## Methodology slip caught by operator

First diagnostic round chased filer-sync logs and inferred behavior — missed reading per-filer-pod state on GR. Operator pushed back: "are you trying to extrapolate ... instead of studying the actual configuration on both k8s sites?" Reading both site's `namespaces/seaweedfs/` IaC + comparing per-pod log streams + per-pod bucket listings revealed the real issue (filer-1 missing data) within minutes. Recorded as feedback in `feedback_per_pod_state_for_multi_replica_diagnosis.md`.

## Pre-existing data divergence on GR filer-1 (NOT fixed by this work)

Files written to GR between 2026-03-24 and 2026-05-05 only landed on filer-0 (filer-1's meta_aggregator was broken). The forward-only fix doesn't backfill these. Filer-1 also has stale chunk pointers (e.g. volume 914 references) that produce intermittent 404s on OLD files. To fully reconcile, would need:
1. `weed filer.meta.save -filer=filer-0 -o snap.dump` then `weed filer.meta.load -filer=filer-1 -i snap.dump`
2. Or scale GR filer to 1 replica (simpler, sacrifices HA)
3. Or wipe filer-1 PVC and let it bootstrap from forward sync (loses old metadata)

This is OUT OF SCOPE for "cross-site replication" — file a separate item if symptoms emerge for users on old data.

## Recovery time

- Cross-site sync stuck: 145 days (2025-12-11 → 2026-05-05)
- Intra-cluster meta_aggregator stuck: 38 days for filer-1→filer-0 / 42 days for filer-0→filer-1
- Total session time to fix: ~50 minutes including initial wrong-direction attempt
