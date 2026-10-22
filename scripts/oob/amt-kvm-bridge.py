#!/usr/bin/env python3
"""AMT 16+ KVM redirection -> local VNC port. Usage: AMT_PASS=... amt-kvm-bridge.py <amt-ip> <local-port>"""
import os, socket, ssl, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "intel-amt"))
import amt.client

host, port = sys.argv[1], int(sys.argv[2])
user, pw = os.environ.get("AMT_USER", "operator"), os.environ["AMT_PASS"]


def patched_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
    ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    return ctx


srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port))
srv.listen(1)
print(f"listening 127.0.0.1:{port} -> {host}", flush=True)
while True:
    conn, _ = srv.accept()
    try:
        client = amt.client.Client(host, pw, username=user, protocol="https")
        kvm = amt.client.KVMClient(client, conn)
        kvm.context = patched_context()
        with kvm:
            kvm.start()
            kvm.loop()
    except Exception as e:  # keep serving the next connection
        print(f"session error: {e!r}", flush=True)
    finally:
        try:
            conn.close()
        except Exception:
            pass
