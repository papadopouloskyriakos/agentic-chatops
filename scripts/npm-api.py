#!/usr/bin/env python3
"""scripts/npm-api.py — manage Nginx Proxy Manager (nlnpm01) via its REST API.

NPM here is backed by a CLUSTER database — NEVER edit the DB or the generated nginx
*.conf directly (they get regenerated). ALWAYS go through this API; it keeps the DB +
nginx config in sync and reloads automatically.

Credentials come from .env (NPM_HOST, NPM_PORT, NPM_IDENTITY, NPM_SECRET).

Usage:
  scripts/npm-api.py self-test
  scripts/npm-api.py list                       # all proxy hosts (id, domains, upstream)
  scripts/npm-api.py find <domain-substring>
  scripts/npm-api.py get /nginx/proxy-hosts/109
  scripts/npm-api.py update-proxy-host 109 forward_host=10.0.181.X [forward_port=3000 ...]
"""
import os, sys, json, urllib.request, urllib.error

def load_env():
    env = {}
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    try:
        for line in open(p):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env

ENV = load_env()
def cfg(k, d=None): return os.environ.get(k, ENV.get(k, d))
HOST, PORT = cfg("NPM_HOST", "10.0.181.X"), cfg("NPM_PORT", "81")
IDENT, SECRET = cfg("NPM_IDENTITY"), cfg("NPM_SECRET")
BASE = f"http://{HOST}:{PORT}/api"

def req(method, path, token=None, body=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        return json.load(urllib.request.urlopen(r, timeout=15))
    except urllib.error.HTTPError as e:
        sys.exit(f"NPM API {method} {path} -> HTTP {e.code}: {e.read().decode()[:400]}")

def token():
    if not IDENT or not SECRET:
        sys.exit("NPM_IDENTITY / NPM_SECRET not set (check .env)")
    return req("POST", "/tokens", body={"identity": IDENT, "secret": SECRET})["token"]

# fields NPM accepts on PUT /nginx/proxy-hosts/<id>
EDITABLE = ["domain_names", "forward_scheme", "forward_host", "forward_port",
            "access_list_id", "certificate_id", "ssl_forced", "hsts_enabled",
            "hsts_subdomains", "http2_support", "block_exploits", "caching_enabled",
            "allow_websocket_upgrade", "advanced_config", "locations", "meta"]

def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd, tk = a[0], token()
    if cmd == "self-test":
        hosts = req("GET", "/nginx/proxy-hosts", tk)
        print(f"OK: token valid, {len(hosts)} proxy hosts visible on {HOST}:{PORT}")
    elif cmd == "list":
        for p in req("GET", "/nginx/proxy-hosts", tk):
            print(f"  {p['id']:>4} {','.join(p['domain_names'])} -> "
                  f"{p['forward_scheme']}://{p['forward_host']}:{p['forward_port']} enabled={p['enabled']}")
    elif cmd == "find":
        for p in req("GET", "/nginx/proxy-hosts", tk):
            if a[1].lower() in ",".join(p["domain_names"]).lower():
                print(f"  {p['id']} {','.join(p['domain_names'])} -> "
                      f"{p['forward_scheme']}://{p['forward_host']}:{p['forward_port']}")
    elif cmd == "get":
        print(json.dumps(req("GET", a[1], tk), indent=2))
    elif cmd == "update-proxy-host":
        pid = a[1]
        changes = dict(kv.split("=", 1) for kv in a[2:])
        cur = req("GET", f"/nginx/proxy-hosts/{pid}", tk)
        payload = {k: cur.get(k) for k in EDITABLE if k in cur}
        for k, v in changes.items():
            payload[k] = int(v) if k == "forward_port" else v
        if payload.get("locations") is None:
            payload["locations"] = []
        out = req("PUT", f"/nginx/proxy-hosts/{pid}", tk, payload)
        print(f"  updated {pid}: {','.join(out['domain_names'])} -> "
              f"{out['forward_scheme']}://{out['forward_host']}:{out['forward_port']}")
    else:
        sys.exit(__doc__)

if __name__ == "__main__":
    main()
