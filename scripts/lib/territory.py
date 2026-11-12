#!/usr/bin/env python3
"""Territory resolver (IFRNLLEI01PRD-1408 territory-gate).

Resolve {hostname, shell command, edited file-path, Proxmox VMID} -> the
infrastructure TERRITORY it belongs to, the guest ROLE, whether it is STATEFUL
(must not be auto-rebooted/restarted), and the chain of CLAUDE.md files whose
rules are load-bearing for that territory.

Offline-first and fail-SAFE: every lookup degrades gracefully (returns a partial
result, never raises) so a consumer hook can decide its own open/closed policy.
Single source of truth for "what territory is this work in" — used by the
PreToolUse territory gate, the risk classifier, the Build Prompt, and the Runner
Prepare-Result backstop.

Data sources (in priority order):
  1. command regex     -> territory (kubectl->k8s, qm/pct->pve, netmiko->network)
  2. file-path walk    -> nearest-ancestor CLAUDE.md under infrastructure/<site>/production/<territory>/
  3. graph_entities    -> host/vmid -> entity_type + vmid + site (gateway SQLite, 192 vm/lxc nodes)
  4. VMID schema decode-> S NN VV TT RR, TT digit -> role (zero-data fallback)
  5. hostname heuristic-> *fw01->network, *pve0x->pve, *k8s-*->k8s, *syno*->storage
"""
from __future__ import annotations

import json
import os
REDACTED_a7b84d63
import sqlite3

INFRA_ROOT = os.environ.get("INFRA_ROOT", "/app/infrastructure")
GATEWAY_DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")

# ── Territory definitions ───────────────────────────────────────────────────
# high_stakes territories are the ones the gate HARD-BLOCKS writes in until the
# CLAUDE.md is read. subdir is the path segment under <site>/production/.
TERRITORIES = {
    "k8s":     {"high_stakes": True,  "subdir": "k8s",
                "cmd": re.compile(r"\b(?:kubectl|helm|tofu|terraform|argocd|cilium)\b", re.I),
                "host": re.compile(r"k8s-(?:ctrlr|node|wrkr|frr|openbao|lb)|(?<![\w-])k8s(?![\w-])", re.I)},
    "network": {"high_stakes": True,  "subdir": "network",
                "cmd": re.compile(r"\b(?:netmiko|vtysh|napalm|hier_?config)\b|\bshow\s+(?:run|bgp|crypto|access-list|route)\b|\bcrypto\s+map\b|\bwrite\s+mem\b", re.I),
                "host": re.compile(r"(?:fw|sw|rtr|lte|ap)\d{2}\b", re.I)},
    "edge":    {"high_stakes": True,  "subdir": "edge",
                "cmd": re.compile(r"\b(?:swanctl|netplan|haproxy|frr|birdc)\b|\bip\s+xfrm\b", re.I),
                "host": re.compile(r"dmz\d{2}|vps\d{2}|chzrh|notrf|txhou", re.I)},
    "pve":     {"high_stakes": True,  "subdir": "pve",
                "cmd": re.compile(r"\b(?:qm|pct|pvesh|pvecm|pvesm|ha-manager)\b", re.I),
                "host": re.compile(r"pve\d{2}\b", re.I)},
    "native":  {"high_stakes": True,  "subdir": "native",
                "cmd": re.compile(r"\b(?:zfs|zpool|iscsiadm|seaweedfs|weed|synomib|exportfs)\b", re.I),
                "host": re.compile(r"syno\d{2}|pbs\d{2}|\bnas\b|filer", re.I)},
    "docker":  {"high_stakes": True,  "subdir": "docker",
                "cmd": re.compile(r"\bdocker(?:\s+compose|-compose)?\b", re.I),
                "host": None},
    "ci":      {"high_stakes": False, "subdir": "ci",  "cmd": None, "host": None},
    "images":  {"high_stakes": False, "subdir": "images", "cmd": None, "host": None},
}

# VMID schema S NN VV TT RR — TT (chars [5:7]) automation-tag -> role.
TT_ROLE = {
    "00": "oob", "01": "mgmt", "02": "network_services", "03": "firewall",
    "04": "loadbalancer", "05": "vpn", "06": "hypervisor", "07": "monitoring",
    "08": "backup", "09": "storage", "10": "db_web", "11": "media",
    "12": "collab", "13": "dmz", "14": "edge_iot", "15": "finance",
    "16": "workstation", "17": "mail", "18": "lab",
}
# role -> territory (best-effort; storage/backup are also the stateful floor)
ROLE_TERRITORY = {
    "hypervisor": "pve", "firewall": "network", "network_services": "network",
    "vpn": "edge", "dmz": "edge", "edge_iot": "edge", "loadbalancer": "edge",
    "storage": "native", "backup": "native", "monitoring": "native",
}
# Stateful: a reboot/restart mid-operation risks quorum/data loss. The name regex
# mirrors classify-session-risk._STATEFUL_DENY_RE; TT in {08,09} is the schema floor;
# k8s control-plane / openbao names are explicitly stateful.
# (?<![a-z]) not \b — hostnames concatenate the site prefix (nlk8s-ctrl01),
# so there is no word boundary before the role token; a digit/non-letter prefix is fine.
_STATEFUL_NAME_RE = re.compile(
    r"(?<![a-z])(?:etcd|postgres|pgsql|mysql|mariadb|galera|seaweedfs|thanos|redis|prometheus|"
    r"mongo|cassandra|elasticsearch|opensearch|vault|consul|clickhouse|kafka|"
    r"zookeeper|rabbitmq|nats|minio|influxdb|victoria|loki|cockroach|"
    r"mssql|sqlserver|oracle|couchdb|neo4j|qdrant|weaviate|valkey|pbs|synology|syno\d|"
    r"openbao|k8s-ctrlr|k8s-openbao|etcd)", re.I)
_STATEFUL_ROLES = {"storage", "backup"}


# A Bash command is a WRITE/mutation (gate-eligible) if it matches this — read-only
# investigation (get/show/list/describe/cat/df/status) is NEVER gated.
_WRITE_RE = re.compile(
    r"\b(?:kubectl|k)\s+(?:apply|create|delete|replace|patch|edit|scale|rollout|drain|cordon|uncordon|annotate|label|set|taint|exec)\b"
    r"|\bhelm\s+(?:install|upgrade|uninstall|rollback)\b"
    r"|\b(?:tofu|terraform)\s+(?:apply|destroy|import|state)\b"
    r"|\b(?:qm|pct)\s+(?:set|start|stop|reboot|shutdown|destroy|create|clone|reset|migrate|rollback|resize)\b"
    r"|\bpvesh\s+(?:create|set|delete)\b|\bpvecm\b|\bha-manager\s+(?:add|remove|set|migrate)\b"
    r"|\bsystemctl\s+(?:start|stop|restart|reload|enable|disable|mask|unmask)\b"
    r"|\bnetmiko\b|\bnapalm\b|\bwrite\s+mem(?:ory)?\b|\bcrypto\s+map\b|\bconf(?:igure)?\s+t(?:erminal)?\b|\bvtysh\b[^|]*-c\s+['\"](?:conf|write|clear)"
    r"|\b(?:zfs|zpool)\s+(?:create|destroy|set|add|remove|attach|detach|replace)\b"
    r"|\bdocker(?:\s+compose|-compose)?\s+(?:up|down|restart|rm|stop|kill|run|build|prune)\b"
    r"|\b(?:rm|mv|cp|chmod|chown|mkfs\w*|dd|truncate)\b"
    r"|\bnetplan\s+apply\b|\bswanctl\s+--(?:load|terminate|initiate|install)\b"
    r"|\biscsiadm\b[^\n]*(?:--op\s+(?:new|delete|update)|--logout)|\bexportfs\b"
    r"|>\s*/|>>\s*/|\btee\s+/", re.I)


def is_write_command(cmd):
    """True if the Bash command mutates state (gate-eligible). Read-only -> False."""
    return bool(cmd and _WRITE_RE.search(cmd))


def _q(db_path):
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        c.row_factory = sqlite3.Row
        return c
    except Exception:
        return None


def _entity_by_host(conn, host):
    try:
        r = conn.execute(
            "SELECT name, entity_type, attributes FROM graph_entities "
            "WHERE name=? AND source_table='infragraph' LIMIT 1", (host,)).fetchone()
        return r
    except Exception:
        return None


def _entity_by_vmid(conn, vmid):
    try:
        # vmid may be stored as a JSON number or string -> CAST both sides to TEXT.
        r = conn.execute(
            "SELECT name, entity_type, attributes FROM graph_entities "
            "WHERE source_table='infragraph' "
            "AND CAST(json_extract(attributes,'$.vmid') AS TEXT)=CAST(? AS TEXT) LIMIT 1",
            (str(vmid),)).fetchone()
        return r
    except Exception:
        return None


def _tt_role(vmid):
    s = str(vmid or "")
    if len(s) == 9 and s.isdigit():
        return TT_ROLE.get(s[5:7])
    return None


def _is_stateful(name, role, vmid):
    if name and _STATEFUL_NAME_RE.search(name):
        return True
    if role in _STATEFUL_ROLES:
        return True
    return False


def _name_role(name):
    """Hostname -> role (more reliable than the TT decode for our naming convention)."""
    if not name:
        return None
    n = name.lower()
    if re.search(r"k8s-(?:ctrlr|openbao)", n):
        return "k8s-control-plane"
    if re.search(r"k8s-(?:node|wrkr)", n):
        return "k8s-worker"
    if re.search(r"k8s-frr", n):
        return "k8s-network"
    if re.search(r"(?:fw|rtr|sw|ap|lte)\d{2}", n):
        return "network-device"
    if re.search(r"pve\d{2}", n):
        return "hypervisor"
    if re.search(r"syno\d|pbs\d|\bnas\b", n):
        return "storage"
    if _STATEFUL_NAME_RE.search(name):
        return "stateful-service"
    return None


def _host_territory(host):
    if not host:
        return None
    for terr, spec in TERRITORIES.items():
        hp = spec.get("host")
        if hp and hp.search(host):
            return terr
    return None


def _cmd_territory(command):
    if not command:
        return None
    # most-specific wins: check the higher-stakes/narrower patterns first
    for terr in ("k8s", "network", "edge", "pve", "native", "docker"):
        cp = TERRITORIES[terr].get("cmd")
        if cp and cp.search(command):
            return terr
    return None


def _path_territory(path):
    """Walk up from an edited file path to the nearest CLAUDE.md under the infra tree.
    Returns (territory, nearest_claudemd_abspath) or (None, None)."""
    if not path:
        return None, None
    p = os.path.abspath(path)
    if not p.startswith(INFRA_ROOT):
        return None, None
    d = p if os.path.isdir(p) else os.path.dirname(p)
    nearest = None
    cur = d
    while cur.startswith(INFRA_ROOT) and len(cur) > len(INFRA_ROOT):
        cand = os.path.join(cur, "CLAUDE.md")
        if os.path.isfile(cand):
            nearest = cand
            break
        cur = os.path.dirname(cur)
    # territory = the segment immediately under <site>/production/
    m = re.search(r"/(nl|gr|common)/production/([^/]+)/", p + "/")
    terr = None
    if m:
        seg = m.group(2)
        terr = seg if seg in TERRITORIES else "site-root"
    return terr, nearest


def _claudemd_chain(territory, site, nearest_from_path=None):
    """The load-bearing CLAUDE.md chain: nearest territory file -> site root -> common."""
    chain = []
    site_dir = None
    if site in ("nl", "nl"):
        site_dir = os.path.join(INFRA_ROOT, "nl", "production")
    elif site in ("gr", "gr"):
        site_dir = os.path.join(INFRA_ROOT, "gr", "production")
    if nearest_from_path and os.path.isfile(nearest_from_path):
        chain.append(nearest_from_path)
    elif territory and territory not in (None, "site-root") and site_dir:
        cand = os.path.join(site_dir, TERRITORIES.get(territory, {}).get("subdir", territory), "CLAUDE.md")
        if os.path.isfile(cand):
            chain.append(cand)
    if site_dir:
        root = os.path.join(site_dir, "CLAUDE.md")
        if os.path.isfile(root) and root not in chain:
            chain.append(root)
    common = os.path.join(INFRA_ROOT, "common", "production", "CLAUDE.md")
    if os.path.isfile(common) and common not in chain:
        chain.append(common)
    return chain


def resolve(host=None, command=None, path=None, vmid=None, cwd=None, db_path=None):
    """Resolve work -> {territory, role, is_stateful, high_stakes, claudemd_paths,
    site, source, confidence}. Never raises."""
    db_path = db_path or GATEWAY_DB
    out = {"territory": None, "role": None, "is_stateful": False, "high_stakes": False,
           "claudemd_paths": [], "site": None, "source": [], "confidence": 0.0}
    name = host
    site = None
    attrs = {}
    etype = None
    # Extract a guest VMID from a lifecycle command (`qm reboot VMID_REDACTED`) so the gate,
    # which only sees the command, still resolves the TARGET guest's role/territory.
    if not vmid and command:
        _m = re.search(r"\b(?:pct|qm)\s+(?:reboot|start|stop|shutdown|reset|migrate|destroy|set)\s+(\d{3,})", command)
        if _m:
            vmid = _m.group(1)

    def _set_terr(t, src, conf):
        if t and not out["territory"]:
            out["territory"] = t
            out["confidence"] = max(out["confidence"], conf)
        if src not in out["source"]:
            out["source"].append(src)

    # 1. path walk (deterministic, primary for Edit/Write)
    terr_path, nearest = _path_territory(path)
    if terr_path:
        _set_terr(terr_path, "path", 0.95)

    # 2. command regex (primary for Bash)
    tc = _cmd_territory(command)
    if tc:
        _set_terr(tc, "command", 0.85)

    # 3. graph_entities (reliable role/site/entity_type via host or vmid)
    conn = _q(db_path)
    ent = None
    if conn is not None:
        if vmid:
            ent = _entity_by_vmid(conn, vmid)
        if ent is None and host:
            ent = _entity_by_host(conn, host)
        if ent is not None:
            name = ent["name"] or name
            etype = ent["entity_type"]
            try:
                attrs = json.loads(ent["attributes"] or "{}")
            except Exception:
                attrs = {}
            site = attrs.get("site")
            out["source"].append("graph_entities")
        try:
            conn.close()
        except Exception:
            pass

    # 4. hostname heuristic (our naming convention is strict + reliable)
    th = _host_territory(name)
    if th:
        _set_terr(th, "host-heuristic", 0.8)

    # 5. entity_type territory hint (pve_node->pve, network_device->network)
    if etype == "pve_node":
        _set_terr("pve", "entity-type", 0.85)
    elif etype == "network_device":
        _set_terr("network", "entity-type", 0.85)

    # 6. VMID-schema TT decode — ROLE hint only (schema can drift); territory only as
    #    a last resort when nothing more reliable resolved it.
    # TT decode is for the stateful ROLE hint only — it is NOT used for territory
    # (the digit drifts: n8n01's TT reads edge_iot though it is the gateway app host).
    # Territory comes only from confident signals (path/command/host/entity-type); an
    # unplaceable host -> territory=None -> gate no-op (we never gate work we can't place).
    role = _tt_role(vmid) or _tt_role(attrs.get("vmid"))
    if role:
        out["source"].append("vmid-schema")
    out["role"] = _name_role(name) or role

    # site fallback from hostname prefix, then from the session cwd (territory repo root)
    if not site and name:
        if name.startswith("nl"):
            site = "nl"
        elif name.startswith("gr"):
            site = "gr"
    if not site and cwd:
        if "/nl/" in cwd:
            site = "nl"
        elif "/gr/" in cwd:
            site = "gr"
    out["site"] = site

    # stateful: name regex OR storage/backup role OR a k8s control-plane guest
    out["is_stateful"] = _is_stateful(name, role, vmid) or (
        out["territory"] == "k8s" and bool(name) and bool(re.search(r"ctrlr|openbao|etcd", name, re.I)))

    # A STATEFUL target's OWN territory dominates: `qm reboot <k8s-vmid>` is a pve
    # OPERATION, but the load-bearing instructions (etcd quorum, drain-first) live in the
    # k8s manual — so require THAT, not just pve's. The manual governs; we don't hard-block.
    if out["is_stateful"]:
        _tt = _host_territory(name)
        if _tt and TERRITORIES.get(_tt, {}).get("high_stakes") and _tt != out["territory"]:
            out["territory"] = _tt
            out["source"].append("stateful-target-territory")

    # high_stakes + claudemd chain
    spec = TERRITORIES.get(out["territory"]) if out["territory"] else None
    out["high_stakes"] = bool(spec and spec.get("high_stakes")) or out["is_stateful"]
    out["claudemd_paths"] = _claudemd_chain(out["territory"], site, nearest)
    return out


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    import sys
    kw = {}
    for a in sys.argv[1:]:
        k, _, v = a.partition("=")
        kw[k] = v
    print(json.dumps(resolve(**kw), indent=2))
