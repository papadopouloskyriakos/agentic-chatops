"""
Fix SeaweedFS GR intra-cluster meta_aggregator stale-checkpoint offsets.

Each filer in a multi-filer cluster maintains a `Meta<peer-sig>` KV entry whose
value is the uint64 nanosecond timestamp at which to resume subscribing to that
peer's metadata change stream. When the peer's change-log volumes for that
period get GC'd, subscribe fails permanently.

Fix: KvPut a recent ns timestamp on each filer for its peer's offset key.
The meta_aggregator retries every 2s and re-reads the offset on each retry.
"""
import sys, struct, time
import grpc
sys.path.insert(0, "/tmp/sw-proto")
import filer_pb2, filer_pb2_grpc

def get_signature(host, port):
    chan = grpc.insecure_channel(f"{host}:{port}")
    stub = filer_pb2_grpc.SeaweedFilerStub(chan)
    resp = stub.GetFilerConfiguration(filer_pb2.GetFilerConfigurationRequest(), timeout=5)
    chan.close()
    return resp.signature, resp.version

def make_meta_key(peer_signature):
    """Replicate Go's GetPeerMetaOffsetKey(peerSignature):
       key = []byte("Meta") + 4 bytes BigEndian uint32(peerSignature)
    """
    sig_u32 = peer_signature & 0xFFFFFFFF
    return b"Meta" + struct.pack(">I", sig_u32)

def kv_get(host, port, key):
    chan = grpc.insecure_channel(f"{host}:{port}")
    stub = filer_pb2_grpc.SeaweedFilerStub(chan)
    resp = stub.KvGet(filer_pb2.KvGetRequest(key=key), timeout=5)
    chan.close()
    return resp.value, resp.error

def kv_put(host, port, key, value):
    chan = grpc.insecure_channel(f"{host}:{port}")
    stub = filer_pb2_grpc.SeaweedFilerStub(chan)
    resp = stub.KvPut(filer_pb2.KvPutRequest(key=key, value=value), timeout=5)
    chan.close()
    return resp.error

def fmt_ns(ns):
    if not ns:
        return "<empty>"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ns / 1e9))

def main():
    # GR filer pod IPs + grpc port (18888 is the filer-grpc port)
    # filer-0 = 10.1.4.214, filer-1 = 10.1.2.173
    filers = {
        "filer-0": ("127.0.0.1", 28800),  # port-forwarded externally
        "filer-1": ("127.0.0.1", 28801),
    }

    sigs = {}
    print("=== Step 1: get filer signatures ===")
    for name, (host, port) in filers.items():
        sig, ver = get_signature(host, port)
        sigs[name] = sig
        print(f"  {name} @ {host}:{port} -> signature={sig}  version={ver}")

    print()
    print("=== Step 2: read current Meta<peer> offsets ===")
    keys = {
        "filer-0": ("filer-1", make_meta_key(sigs["filer-1"])),  # filer-0 has key for following filer-1
        "filer-1": ("filer-0", make_meta_key(sigs["filer-0"])),  # filer-1 has key for following filer-0
    }
    for self_name, (peer_name, key) in keys.items():
        host, port = filers[self_name]
        v, err = kv_get(host, port, key)
        ns = struct.unpack(">Q", v)[0] if len(v) == 8 else 0
        print(f"  {self_name} key='Meta'+sig({peer_name})  hex={key.hex()}  current_value_ns={ns} ({fmt_ns(ns)})  err={err!r}")

    print()
    new_ns = time.time_ns()
    print(f"=== Step 3: KvPut new offset = {new_ns} ({fmt_ns(new_ns)}) ===")
    new_value = struct.pack(">Q", new_ns)
    for self_name, (peer_name, key) in keys.items():
        host, port = filers[self_name]
        err = kv_put(host, port, key, new_value)
        print(f"  KvPut on {self_name} for follow-{peer_name}: err={err!r}")

    print()
    print("=== Step 4: read back to verify ===")
    for self_name, (peer_name, key) in keys.items():
        host, port = filers[self_name]
        v, err = kv_get(host, port, key)
        ns = struct.unpack(">Q", v)[0] if len(v) == 8 else 0
        match = " <- MATCHES NEW" if ns == new_ns else ""
        print(f"  {self_name} follow-{peer_name}: value_ns={ns} ({fmt_ns(ns)}){match}  err={err!r}")

if __name__ == "__main__":
    main()
