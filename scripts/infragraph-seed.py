#!/usr/bin/env python3
"""infragraph-seed — populate infragraph topology from authoritative sources.

Epic IFRNLLEI01PRD-1029; this seeder is IFRNLLEI01PRD-1032.

Sources (each idempotent; re-runs refresh valid_until and enrich attributes):
  --pve        pvesh /cluster/resources via SSH to nl-pve01 (NL+GR share
               one cluster) → vm/lxc -runs_on-> pve_node edges with vmid.
               LIVE source of truth for placement (trust hierarchy #1).
               Replaces the planned --iac seeder: the production IaC repos
               don't carry target_node for guests, NetBox VM objects carry no
               placement either — the cluster API is both live and complete.
  --netbox     NetBox DCIM API → device -member_of-> site edges + device role
               typing (network_device / physical_host). CMDB layer.
  --tunnels    TUNNEL_GRAPH_EDGE from scripts/chaos-test.py → site/tunnel
               nodes, site -routes_via-> tunnel edges (both endpoints).
  --declared   docs/host-blast-radius.md table → operator-declared edges with
               expected_alerts. Malformed rows = loud non-zero exit.
  --all        all of the above.

netbox/pve edges get valid_until = now + 7 days, refreshed by the daily cron —
a dead seeder surfaces as stale_edges in health() + Prometheus instead of
silently wrong predictions. tunnels/declared edges are open-ended.

Cron (nl-claude01): 10 4 * * *  .../scripts/infragraph-seed.py --all
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
REDACTED_a7b84d63
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import infragraph  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECLARED_DOC = os.path.join(REPO_ROOT, "docs", "host-blast-radius.md")
CHAOS_TEST = os.path.join(REPO_ROOT, "scripts", "chaos-test.py")
# .env is uncommitted — when running from a worktree, fall back to the
# canonical deployment checkout.
ENV_CANDIDATES = (
    os.path.join(REPO_ROOT, ".env"),
    os.path.expanduser("~/gitlab/n8n/claude-gateway/.env"),
)

NETBOX_URL = os.environ.get("NETBOX_URL", "https://netbox.example.net")
PVE_SSH_HOST = os.environ.get("INFRAGRAPH_PVE_SSH_HOST", "nl-pve01")

VALID_DAYS = 7


def _valid_until() -> str:
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=VALID_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_file_vars() -> dict[str, str]:
    out: dict[str, str] = {}
    for path in ENV_CANDIDATES:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        out.setdefault(k.strip(), v.strip())
            break
        except FileNotFoundError:
            continue
    return out


def _netbox_token() -> str:
    return os.environ.get("NETBOX_TOKEN") or _env_file_vars().get("NETBOX_TOKEN", "")


def _netbox_get(path: str, token: str) -> dict:
    import ssl
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        NETBOX_URL + path, headers={"Authorization": f"Token {token}"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.load(resp)


# NetBox device role slug → infragraph entity_type
ROLE_TO_TYPE = {
    "firewall": "network_device", "router": "network_device",
    "switch": "network_device", "access-point": "network_device",
    "vpn-gateway": "network_device",
    "server": "physical_host", "hypervisor": "pve_node",
    "ups": "service", "pdu": "service",
}


def seed_netbox(conn) -> dict:
    token = _netbox_token()
    if not token:
        raise RuntimeError("no NETBOX_TOKEN in env or .env")
    n_dev = n_edge = 0
    url = "/api/dcim/devices/?limit=250"
    while url:
        page = _netbox_get(url, token)
        for d in page.get("results", []):
            name = d.get("name") or ""
            if not name:
                continue
            role = ((d.get("role") or {}).get("slug")) or ""
            site = ((d.get("site") or {}).get("slug")) or ""
            etype = ROLE_TO_TYPE.get(role, "physical_host")
            infragraph.upsert_entity(conn, etype, name, {
                "site": site, "role": role, "netbox_id": d.get("id"),
            })
            n_dev += 1
            if site:
                infragraph.upsert_entity(conn, "site", site, {"site": site})
                infragraph.upsert_edge(
                    conn, (etype, name), ("site", site), "member_of",
                    source="netbox", confidence=0.9,
                    valid_until=_valid_until())
                n_edge += 1
        nxt = page.get("next")
        url = nxt.replace(NETBOX_URL, "") if nxt else None

    # Cable-derived network dependency: an endpoint device depends on the
    # network device (switch/router/fw) it is physically cabled to. This is
    # the layer the 2026-05-11 replay exposed as missing — LibreNMS parents
    # cover only 14 devices; cables cover the rest of the physical fan-out.
    # network_device ↔ network_device cables are skipped (direction is
    # ambiguous; LibreNMS parents express that layer explicitly).
    n_cable = 0
    page = _netbox_get("/api/dcim/cables/?limit=500", token)
    for c in page.get("results", []):
        ends = []
        for side in ("a_terminations", "b_terminations"):
            for t in c.get(side) or []:
                dev = ((t.get("object") or {}).get("device") or {}).get("name")
                if dev:
                    ends.append(dev)
                    break
        if len(ends) != 2 or ends[0] == ends[1]:
            continue
        ra = infragraph.resolve_entity(conn, ends[0])
        rb = infragraph.resolve_entity(conn, ends[1])
        if not ra or not rb:
            continue
        a_net = ra[0] == "network_device"
        b_net = rb[0] == "network_device"
        if a_net == b_net:
            continue  # both or neither network devices
        leaf, net = (rb, ra) if a_net else (ra, rb)
        infragraph.upsert_edge(conn, leaf, net, "depends_on",
                               source="netbox", confidence=0.85,
                               valid_until=_valid_until(),
                               metadata={"via": "cable"})
        n_cable += 1
    infragraph.stamp_seed(conn, "netbox")
    return {"devices": n_dev, "edges": n_edge, "cable_edges": n_cable}


def seed_pve(conn) -> dict:
    """vm/lxc -runs_on-> pve_node from the live cluster API.

    Same access pattern as lab-stats.py get_compute(): NL+GR PVE hosts share
    ONE Proxmox cluster, so a single pvesh call returns every guest.
    """
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=8",
           PVE_SSH_HOST,
           "pvesh get /cluster/resources --type vm --output-format json 2>/dev/null"]
    out = subprocess.check_output(cmd, timeout=30, stderr=subprocess.DEVNULL).decode()
    guests = json.loads(out)
    n = 0
    for g in guests:
        name = g.get("name") or ""
        node = g.get("node") or ""
        if not name or not node:
            continue
        etype = "lxc" if g.get("type") == "lxc" else "vm"
        site = "nl" if node.startswith("nl") else (
            "gr" if node.startswith("gr") else "")
        infragraph.upsert_entity(conn, "pve_node", node,
                                 {"site": site} if site else {})
        infragraph.upsert_edge(
            conn, (etype, name), ("pve_node", node), "runs_on",
            source="pve", confidence=0.95, valid_until=_valid_until(),
            metadata={"vmid": g.get("vmid"), "status": g.get("status")})
        # enrich the guest entity
        infragraph.upsert_entity(conn, etype, name, {
            "vmid": g.get("vmid"), "site": site, "status": g.get("status"),
        })
        n += 1
    infragraph.stamp_seed(conn, "pve")
    return {"guests": n}


def _load_tunnel_graph_edge() -> dict:
    """Extract the TUNNEL_GRAPH_EDGE dict literal from chaos-test.py via ast —
    no import, no module-level side effects. The graph-parity QA check
    (IFRNLLEI01PRD-1042) keeps this in lockstep with the chaos safety BFS."""
    import ast
    src = open(CHAOS_TEST, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "TUNNEL_GRAPH_EDGE"):
            return ast.literal_eval(node.value)
    raise RuntimeError("TUNNEL_GRAPH_EDGE not found in chaos-test.py")


def seed_tunnels(conn) -> dict:
    edges = _load_tunnel_graph_edge()
    n = 0
    for (label, wan), (site_a, site_b) in edges.items():
        norm = label.replace(" ", "").replace("↔", "-")
        tname = f"tunnel:{norm}:{wan}"
        infragraph.upsert_entity(conn, "tunnel", tname,
                                 {"label": label, "wan": wan})
        for s in (site_a, site_b):
            infragraph.upsert_entity(conn, "site", s, {"site": s})
            # inter-site reachability of each endpoint site depends on the tunnel
            infragraph.upsert_edge(conn, ("site", s), ("tunnel", tname),
                                   "routes_via", source="declared",
                                   confidence=1.0)
            n += 1
    infragraph.stamp_seed(conn, "tunnels")
    return {"tunnels": len(edges), "edges": n}


_DECLARED_ROW_RE = re.compile(r"^\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]*)\|([^|]*)\|\s*$")


def _parse_entity(token: str) -> tuple[str, str]:
    token = token.strip()
    if ":" not in token:
        raise ValueError(f"declared edge entity {token!r} must be entity:name")
    etype, name = token.split(":", 1)
    if etype not in infragraph.ENTITY_TYPES:
        raise ValueError(f"unknown entity type {etype!r} in {token!r}")
    return etype, name.strip()


def seed_declared(conn) -> dict:
    n = skipped = 0
    errors: list[str] = []
    in_table = False
    with open(DECLARED_DOC, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if line.startswith("| source |"):
                in_table = True
                continue
            if not in_table:
                continue
            if line.startswith("|---"):
                continue
            m = _DECLARED_ROW_RE.match(line)
            if not m:
                if line.startswith("|"):
                    errors.append(f"line {lineno}: malformed row")
                continue
            src_tok, rel, tgt_tok, alerts, _notes = (g.strip() for g in m.groups())
            try:
                src = _parse_entity(src_tok)
                tgt = _parse_entity(tgt_tok)
                if rel not in infragraph.REL_TYPES:
                    raise ValueError(f"unknown rel_type {rel!r}")
            except ValueError as e:
                errors.append(f"line {lineno}: {e}")
                skipped += 1
                continue
            rel_id = infragraph.upsert_edge(conn, src, tgt, rel,
                                            source="declared", confidence=0.85)
            rules = [a.strip() for a in alerts.split(";") if a.strip()]
            if rules:
                infragraph.update_dynamics(conn, rel_id, observed_rules=rules)
            n += 1
    if errors:
        for e in errors:
            print(f"DECLARED-EDGE ERROR: {e}", file=sys.stderr)
        raise RuntimeError(f"{len(errors)} malformed declared-edge rows")
    infragraph.stamp_seed(conn, "declared")
    return {"edges": n, "skipped": skipped}


def _librenms_creds() -> list[tuple[str, str, str]]:
    """(site, url, key) for both LibreNMS instances, from env or .env."""
    env: dict[str, str] = dict(os.environ)
    for k, v in _env_file_vars().items():
        env.setdefault(k, v)
    out = []
    if env.get("LIBRENMS_URL") and env.get("LIBRENMS_API_KEY"):
        out.append(("nl", env["LIBRENMS_URL"].rstrip("/"), env["LIBRENMS_API_KEY"]))
    if env.get("LIBRENMS_GR_URL") and env.get("LIBRENMS_GR_API_KEY"):
        out.append(("gr", env["LIBRENMS_GR_URL"].rstrip("/"), env["LIBRENMS_GR_API_KEY"]))
    return out


def seed_librenms(conn) -> dict:
    """Network-layer dependency edges from LibreNMS device parents.

    This is the layer the 2026-05-11 replay exposed as missing: AP→switch,
    switch→switch, switch→firewall. Sparse (operator-maintained in LibreNMS)
    but causally exact — a parent down makes every transitive child
    unreachable. IP-literal parents (e.g. '10.0.X.X') are skipped: an edge
    to a node no alert will ever name is dead weight.
    """
    import ssl
    creds = _librenms_creds()
    if not creds:
        raise RuntimeError("no LibreNMS credentials in env or .env")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # self-signed certs on both instances
    n = skipped_ip = 0
    for site, url, key in creds:
        req = urllib.request.Request(
            url + "/api/v0/devices?limit=500",
            headers={"X-Auth-Token": key})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            devices = json.load(resp).get("devices", [])
        for d in devices:
            child = (d.get("hostname") or "").split(".")[0]
            parent = (d.get("dependency_parent_hostname") or "").split(",")[0].strip()
            if not child or not parent:
                continue
            if re.fullmatch(r"[\d.]+", parent):
                skipped_ip += 1
                continue
            parent = parent.split(".")[0]
            src = infragraph.resolve_entity(conn, child) or ("physical_host", child)
            tgt = infragraph.resolve_entity(conn, parent) or ("network_device", parent)
            infragraph.upsert_edge(conn, src, tgt, "depends_on",
                                   source="librenms", confidence=0.9,
                                   valid_until=_valid_until(),
                                   metadata={"site": site})
            n += 1
    infragraph.stamp_seed(conn, "librenms")
    return {"edges": n, "skipped_ip_parents": skipped_ip}


def main() -> int:
    ap = argparse.ArgumentParser(prog="infragraph-seed")
    ap.add_argument("--db", default=None)
    ap.add_argument("--netbox", action="store_true")
    ap.add_argument("--pve", action="store_true")
    ap.add_argument("--tunnels", action="store_true")
    ap.add_argument("--declared", action="store_true")
    ap.add_argument("--librenms", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        args.netbox = args.pve = args.tunnels = args.declared = args.librenms = True
    if not (args.netbox or args.pve or args.tunnels or args.declared or args.librenms):
        ap.error("pick at least one source "
                 "(--netbox/--pve/--tunnels/--declared/--librenms/--all)")

    conn = infragraph.get_db(args.db)
    report: dict[str, object] = {}
    failures = 0
    for name, enabled, fn in (
        ("tunnels", args.tunnels, seed_tunnels),
        ("declared", args.declared, seed_declared),
        ("pve", args.pve, seed_pve),
        ("netbox", args.netbox, seed_netbox),
        ("librenms", args.librenms, seed_librenms),
    ):
        if not enabled:
            continue
        try:
            report[name] = fn(conn)
            conn.commit()
        except Exception as e:  # noqa: BLE001 — per-source isolation, loud report
            conn.rollback()
            report[name] = {"error": f"{type(e).__name__}: {e}"}
            failures += 1
    report["health"] = {
        k: v for k, v in infragraph.health(conn).items()
        if k in ("nodes_total", "edges_total", "stale_edges", "dynamics_coverage")
    }
    conn.close()
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
