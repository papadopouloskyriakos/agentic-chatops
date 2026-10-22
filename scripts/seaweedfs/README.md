# SeaweedFS recovery scripts

## `fix_meta_offset.py` — meta-aggregator stale-checkpoint recovery

When two filer pods in a multi-filer SeaweedFS cluster cannot subscribe to each
other's metadata change streams because the underlying change-log volumes have
been GC'd, the symptoms are:

- `meta_aggregator.go:208 SubscribeLocalMetadata stream <peer>:8888: rpc error:
  ... reading from persisted logs: failed to get next log entry for
  HH-MM.<chunk-id>: volume <N> not found` (tight retry loop on the consumer)
- `filer_grpc_server_sub_meta.go:191 read on disk filer:<peer>:8888 ... local
  subscribe / from {Time:<stale-ts>}: ... volume <N> not found` (visible on the
  publisher side as the consumer immediately disconnects)
- New writes hitting one filer pod do NOT propagate to its peer's metadata
  store, so reads via the cluster service flap between 200 and 404 depending
  on which pod the load-balancer hits.

The fix is to rewrite each filer's persistent peer-follow offset (stored in
the local filer KV under key `Meta` + 4 bytes BE of peer signature) to a
recent ns timestamp. Filer's `meta_aggregator` retries every ~2s and re-reads
the offset on each retry, so no pod restart is needed.

This script does that via the filer's gRPC `KvPut` RPC.

### Reference event

2026-05-05 — GR cluster filer-0 ↔ filer-1 had been unable to follow each
other since 2025-12-28 (filer-1 → filer-0) and 2026-03-24 (filer-0 → filer-1)
because volumes 3, 918, etc. of their respective change-log streams had been
compacted away. Result: cross-site `filer.sync` writes were landing on filer-0
only; reads via cluster-mesh service hitting filer-1 returned 404 ~50% of the
time. Fix applied here brought 10/10 stress reads to 200, and verified
NL→GR PUT lands on both GR filers within 10 s.

### Usage

```bash
# Per-cluster: edit the filers map (pod names, ports) at the top of main()
# Default: GR cluster, filer-0 + filer-1 via two port-forwards on 28800/28801.

# 1) Set up port-forwards to each filer pod's gRPC port (18888):
kubectl --context=gr -n seaweedfs port-forward seaweedfs-filer-0 28800:18888 &
kubectl --context=gr -n seaweedfs port-forward seaweedfs-filer-1 28801:18888 &
sleep 3

# 2) Run the script
/tmp/sw-grpc-venv/bin/python fix_meta_offset.py

# 3) Verify in filer logs - subscribe should succeed, retry-loop gone:
kubectl --context=gr -n seaweedfs logs seaweedfs-filer-0 --since=30s | grep meta_aggregator
kubectl --context=gr -n seaweedfs logs seaweedfs-filer-1 --since=30s | grep meta_aggregator
```

### Setup

```bash
# Python venv with grpcio (one-time):
python3 -m venv /tmp/sw-grpc-venv
/tmp/sw-grpc-venv/bin/pip install grpcio grpcio-tools

# Compile the proto (one-time per upstream version bump):
cd $(dirname this-file)
/tmp/sw-grpc-venv/bin/python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. filer.proto
```

The compiled `filer_pb2.py` / `filer_pb2_grpc.py` are NOT committed — regenerate
from `filer.proto` (which IS committed at the repo's pinned version). The
proto here is for SeaweedFS 4.01; if upgrading the chart, refresh the proto
from `https://raw.githubusercontent.com/seaweedfs/seaweedfs/<tag>/weed/pb/filer.proto`.

### Key format

Verbatim from upstream `weed/filer/meta_aggregator.go::GetPeerMetaOffsetKey`:

```
key = []byte("Meta") + binary.BigEndian.Uint32(peer_signature)
val = binary.BigEndian.Uint64(offset_ns)
```

Peer signature is read via `GetFilerConfiguration` RPC (`signature` field in
the response). Each filer in a cluster has its own signature; signatures are
stable across pod restarts (persisted in the master).

### Why `KvPut` (not `KvDelete`)

The SeaweedFS filer gRPC API exposes `KvGet` and `KvPut`, but no `KvDelete`.
Setting the value to a recent ns timestamp (rather than empty) keeps the read
path simple: `readOffset` checks `len(value) == 8` and parses; on next retry
the meta-aggregator subscribes from that ns. Empty-value writes would also
work (they cause `readOffset` to return an error and `lastTsNs` to stay at
the caller's `startFrom`), but with explicit ns the behavior is more legible.
