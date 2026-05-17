# Runbook: SeaweedFS cross-site replication broken

**Service**: SeaweedFS S3 backend on K8s clusters `nlcl01k8s` + `grcl01k8s`. Active-active filer replication via Cilium Cluster Mesh + a single `filer.sync` deployment running on the NL cluster.
**Symptom**: PUT to one site → object never appears on the other site (or appears intermittently). Loki/Thanos/Velero buckets are excluded from replication so the symptom is most visible on user buckets like `cluster-snapshots`, `omoikane-uploads`, `velero` (replication subset), or any newly-created bucket.
**Impact**: Cross-site DR is broken. Velero backups still land locally, but the GR copy is stale. Reading via either site's `seaweedfs-filer` cluster service may return 404 even when the data exists on the other site or the other filer pod.

## Why this runbook exists

2026-05-05 incident — the cross-site `filer.sync` had been stuck since **2025-12-11 19:07:15 UTC** (145 days) because GR's change-log volumes 1+2 referenced by `filer.sync`'s persisted resume offset had been GC'd. Pod was in a tight retry loop with `failed to get next log entry for HH-MM.<chunk-id>: volume <N> not found`. Fix landed in [MR `infrastructure/nl/production` !290](https://gitlab.example.net/infrastructure/nl/production/-/merge_requests/290).

While verifying that fix, a SECOND, independent stale-checkpoint failure was found inside GR cluster: `filer-0` ↔ `filer-1` `meta_aggregator` peer-follow had been broken since 2025-12-28 / 2026-03-24 with the same shape — referenced volumes 3 / 918 GC'd. This caused cross-site writes that landed on GR's filer-0 to never propagate to filer-1, producing intermittent 404s as Cilium round-robined cluster-service reads between the two pods.

**Both failures are the same pattern (persisted offset → GC'd change-log volume → permanent stuck retry) on different surfaces.** Same fix shape too: overwrite the offset with a recent ns timestamp.

## TL;DR

```
SYMPTOM:                    LIKELY CAUSE:                          FIX:
PUT to NL → 404 on GR       cross-site filer.sync stuck            MR variable bump (Atlantis)
  (or vice versa)             OR
                            GR intra-cluster meta_aggregator       fix_meta_offset.py (gRPC KvPut)
GR PUT/GET intermittent     GR filer-0 ↔ filer-1 desynced          fix_meta_offset.py
  200/404 (50/50)
```

## Triage — read this whole section before acting

The two failure modes look superficially similar but live in different components. Diagnose before fixing.

### 1. Cross-site `filer.sync` health

```bash
# Pod present + running on NL?
kubectl --context=kubernetes-admin@kubernetes -n seaweedfs get pods -l app.kubernetes.io/component=filer-sync -o wide

# Retry-loop signature?
kubectl --context=kubernetes-admin@kubernetes -n seaweedfs logs deploy/seaweedfs-filer-sync --since=2m 2>&1 | grep -c "filer_sync.go:215"
# > 0 means filer.sync is in the retry loop.

# What's the stuck timestamp + missing volume?
kubectl --context=kubernetes-admin@kubernetes -n seaweedfs logs deploy/seaweedfs-filer-sync --since=2m 2>&1 | grep "volume.*not found" | head -3
# Look for: "from <STALE-TS>" and "volume <N> not found"
```

### 2. Per-pod state on GR (the gotcha — DO NOT SKIP)

The cross-site write lands on whichever GR filer Cilium picks. If the intra-cluster `meta_aggregator` is broken, only THAT filer pod will have the data. Reads via the cluster service will flap.

```bash
# Set up port-forwards to each GR filer pod individually
kubectl --context=gr -n seaweedfs port-forward seaweedfs-filer-0 18901:8888 &
kubectl --context=gr -n seaweedfs port-forward seaweedfs-filer-1 18902:8888 &
sleep 3

# List the same bucket from each pod
for port in 18901 18902; do
  echo "=== filer pod via :$port ==="
  curl -sS -H "Accept: application/json" "http://127.0.0.1:$port/buckets/<some-bucket>/" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); [print(' ',e['FullPath']) for e in (d.get('Entries') or [])]"
done

# If the entry counts differ -> intra-cluster meta_aggregator is broken.

# Confirm with logs:
kubectl --context=gr -n seaweedfs logs seaweedfs-filer-0 --since=1m 2>&1 | grep -E "meta_aggregator|volume.*not found" | head -10
kubectl --context=gr -n seaweedfs logs seaweedfs-filer-1 --since=1m 2>&1 | grep -E "meta_aggregator|volume.*not found" | head -10
# Look for: "subscribing remote ... meta change: <STALE-TS>" + "volume <N> not found"
```

Repeat the same per-pod check on NL (`kubectl --context=kubernetes-admin@kubernetes ...`). NL had no `meta_aggregator` problem during the 2026-05-05 incident, but the failure mode is symmetric and could appear there too.

### 3. Is it actually stale-checkpoint or something else?

If the symptom matches but logs DON'T show `volume not found` errors, the cause may be different — check Cilium Cluster Mesh status (`cilium-dbg service list | grep seaweedfs-filer-`), filer pod health, NetworkPolicies, etc., before diving into the offset fixes below.

## Recovery

### A. Cross-site `filer.sync` stale checkpoint (the case from MR !290)

This is an IaC change. Goes via Atlantis MR.

1. Pick a recent ms timestamp:
   ```bash
   date -u -d "2 minutes ago" +%s%3N
   # E.g. VMID_REDACTED0258 = 2026-05-05 14:31:50 UTC
   ```
2. **Mind the upstream flag inversion** — the SeaweedFS v4.01 source consumes the variables backwards from intuition:
   - `-a.fromTsMs` (variable `filer_sync_a_from_ts_ms`) controls direction `b→a` (REMOTE→LOCAL, where filer A is the SINK)
   - `-b.fromTsMs` (variable `filer_sync_b_from_ts_ms`) controls direction `a→b` (LOCAL→REMOTE)

   So if the broken direction is GR→NL (the 2026-05-05 case), set `filer_sync_a_from_ts_ms`. The variable's `description` block in `infrastructure/nl/production/k8s/namespaces/seaweedfs/variables.tf` documents this in detail.
3. Edit `infrastructure/nl/production/k8s/main.tf`, in the `module "seaweedfs"` block, set the appropriate `filer_sync_{a,b}_from_ts_ms` variable to the ms timestamp. Open MR + `atlantis apply`. Pod rolling-restarts, picks up the override flag, persists new offset within ~1 min.
4. Verify:
   ```bash
   kubectl --context=kubernetes-admin@kubernetes -n seaweedfs get deploy seaweedfs-filer-sync -o jsonpath='{.spec.template.spec.containers[0].args}' | python3 -c "import sys,json; [print(a) for a in json.loads(sys.stdin.read())]" | grep fromTsMs
   # Expect: -a.fromTsMs / -b.fromTsMs <new-ms>

   kubectl --context=kubernetes-admin@kubernetes -n seaweedfs logs deploy/seaweedfs-filer-sync --since=30s 2>&1 | grep -c "volume.*not found"
   # Expect: 0
   ```
5. Once verified, the override is harmless to leave in place forever — the upstream `initOffsetFromTsMs` only applies it when `override > storedOffset`, and after the first iteration the stored offset advances past it.

### B. Intra-cluster `meta_aggregator` stale checkpoint (the case from the 2026-05-05 hidden second issue)

NOT an IaC change. Runtime data fix via gRPC `KvPut` on each filer's leveldb-backed `Meta`+peer-signature key. No pod restart needed — `meta_aggregator` retries every ~2s and re-reads the offset.

Recovery script: `scripts/seaweedfs/fix_meta_offset.py` in this repo.

```bash
# 1) One-time setup of Python venv (if not already there)
python3 -m venv /tmp/sw-grpc-venv
/tmp/sw-grpc-venv/bin/pip install grpcio grpcio-tools

# 2) Compile the proto (already committed at scripts/seaweedfs/filer.proto for v4.01)
cd /app/claude-gateway/scripts/seaweedfs
/tmp/sw-grpc-venv/bin/python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. filer.proto

# 3) Port-forward to each broken filer pod's gRPC port (18888)
#    Adjust kubectl --context= and pod names to the affected cluster
kubectl --context=gr -n seaweedfs port-forward seaweedfs-filer-0 28800:18888 &
kubectl --context=gr -n seaweedfs port-forward seaweedfs-filer-1 28801:18888 &
sleep 3

# 4) Run the script (default config matches the 2026-05-05 GR case;
#    edit the filers map at the top of main() for other clusters/pods)
/tmp/sw-grpc-venv/bin/python fix_meta_offset.py
```

The script: reads each filer's signature via `GetFilerConfiguration`, computes `Meta`+`uint32be(peer_sig)` keys, KvGets the current value, KvPuts a fresh `time.time_ns()` value, KvGets again to confirm.

5. Verify (within ~5 s — meta_aggregator retries every 2s):
   ```bash
   kubectl --context=gr -n seaweedfs logs seaweedfs-filer-0 --since=15s 2>&1 | grep meta_aggregator | head -5
   # Expect: "follow peer: <peer>:8888, last <today's date>"  + "subscribing remote ... meta change: <today>"

   kubectl --context=gr -n seaweedfs logs seaweedfs-filer-0 --since=15s 2>&1 | grep -c "volume.*not found"
   # Expect: 0 (or only stale chunk-pointer errors with a different volume number — those are unrelated)
   ```

### C. End-to-end verification (run after either fix)

```bash
# Live PUT/GET round-trip in both directions
kubectl --context=kubernetes-admin@kubernetes -n seaweedfs port-forward svc/seaweedfs-filer 18891:8888 &
kubectl --context=gr -n seaweedfs port-forward svc/seaweedfs-filer 18892:8888 &
sleep 3
TS=$(date +%s)
PATH_NL2GR="/buckets/sync-test-$TS/from-nl.txt"
PATH_GR2NL="/buckets/sync-test-$TS/from-gr.txt"

echo "=== NL -> GR ==="
echo "test-nl-$TS" | curl -sS -X PUT --data-binary @- "http://127.0.0.1:18891$PATH_NL2GR"
sleep 10
curl -sS -w "HTTP=%{http_code}\n" "http://127.0.0.1:18892$PATH_NL2GR"

echo "=== GR -> NL ==="
echo "test-gr-$TS" | curl -sS -X PUT --data-binary @- "http://127.0.0.1:18892$PATH_GR2NL"
sleep 10
curl -sS -w "HTTP=%{http_code}\n" "http://127.0.0.1:18891$PATH_GR2NL"

# Stress: poll the cluster-mesh service for the new file 10x — should be 10/10 200
for i in {1..10}; do curl -sS -o /dev/null -w "%{http_code} " "http://127.0.0.1:18892$PATH_NL2GR"; done; echo
```

If both directions return 200 and stress-poll is 10/10, replication is fully healthy.

## Pre-existing data divergence (separate concern)

The fixes above restore FORWARD replication. They do NOT backfill data that was missed during the broken window. If a filer pod was unable to follow its peer for weeks, files written during that gap exist on only one pod, and reads via the cluster service may 404 ~50% of the time for those files until they're either re-written or explicitly reconciled.

To reconcile, three options (all out of scope for "fix replication"):
1. `weed filer.meta.save -filer=<good-pod>:8888 -o /tmp/snap.dump` then `weed filer.meta.load -filer=<bad-pod>:8888 -i /tmp/snap.dump` — full snapshot/restore. Heaviest but cleanest.
2. Scale the filer StatefulSet to 1 replica (Atlantis MR setting `filer.replicas: 1` in `values.yaml.tpl`). Sacrifices HA on that filer cluster but eliminates the divergence symptom.
3. Wipe the diverged pod's leveldb PVC and let it bootstrap forward — loses all old metadata on that pod (worse than option 2).

Track these as separate work items.

## Architectural notes

- The single `filer.sync` deployment runs on **NL only** (`enable_cross_site_replication = true` in NL `main.tf`; default `false` on GR). Active-active SeaweedFS architecture only needs one syncer running — it handles BOTH `a→b` and `b→a` from the same pod, in two goroutines.
- The cluster-mesh stub service (`seaweedfs-filer-<remote-site>`) has NO selector; endpoints are injected by Cilium from the remote cluster. `kubectl get endpoints` will show "not found" — that's normal. Inspect via `cilium-dbg service list | grep <service-IP>`.
- Helm chart name: `seaweedfs/seaweedfs` (upstream). Chart version pinned in `var.seaweedfs_chart_version`. Chart values quirks (resources as objects vs strings, `data.type:persistentVolumeClaim` not `persistence.enabled`) are documented in `values.yaml.tpl` headers.

## See also

- Memory: `memory/seaweedfs_filer_sync_stale_checkpoint_20260505.md` — full incident timeline + the methodology slip caught by the operator (chasing logs vs reading per-pod state)
- Memory: `memory/feedback_per_pod_state_for_multi_replica_diagnosis.md` — generalized rule
- Recovery script: `scripts/seaweedfs/fix_meta_offset.py` + `scripts/seaweedfs/README.md`
- Reference IaC: `infrastructure/nl/production/k8s/namespaces/seaweedfs/cluster-mesh.tf` + `variables.tf` (the `filer_sync_{a,b}_from_ts_ms` block has the upstream flag-inversion documentation inline)
- Atlantis MR: `infrastructure/nl/production` !290 (merged 2026-05-05)
