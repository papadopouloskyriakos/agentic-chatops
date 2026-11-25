#!/usr/bin/env python3
"""
galera_cluster.py — read-only state collection + the bootstrap decision for the shared NL
Galera cluster "eu-nl-mariadb01" (IFRNLLEI01PRD-2992, postmortem item 8).

Used by:
  scripts/write-galera-metrics.py      textfile metrics for GaleraNoPrimary (Cronicle, every minute)
  scripts/galera-guarded-bootstrap.py  plan / --execute of the runbook bootstrap

Runbook: infrastructure/nl/production native/dbcluster/CLAUDE.md § Troubleshooting.

collect_node()/collect_arbitrator() only READ (systemctl show, SHOW GLOBAL STATUS, grastate.dat,
df). decide() is a pure function over NodeState objects so its rules are unit-tested with
fixtures (scripts/qa/suites/test-galera-guarded-bootstrap.sh).

Node list: GALERA_DB_NODES="name=ip,name=ip" and GALERA_ARBITRATOR="name=ip" override the
defaults below. SSH: root@ip with GALERA_SSH_KEY (default ~/.ssh/one_key), BatchMode.
"""
import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

CLUSTER_NAME = "eu-nl-mariadb01"
DEFAULT_DB_NODES = [("nlcl01mariadb01", "10.0.181.X"),
                    ("nlcl01mariadb02", "10.0.181.X")]
DEFAULT_ARBITRATOR = ("nlcl01garbd01", "10.0.181.X")
DEFAULT_TIE_PREFER = "nlcl01mariadb02"   # writer node; the runbook's 2026-11-07 choice
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
SYNCED = 4                                     # wsrep_local_state 4 = Synced

# Exit codes shared by the bootstrap CLI.
EXIT_OK = 0            # nothing to do, or --execute finished and verified
EXIT_ERROR = 1         # collection / execution / verification failure
EXIT_REFUSED = 2       # unsafe: refused, nothing changed
EXIT_PLAN = 3          # plan mode: a bootstrap (or a recovery step) is needed

NOTHING, REFUSE, RECOVER, BOOTSTRAP = "NOTHING_TO_DO", "REFUSE", "NEED_RECOVERY", "BOOTSTRAP"


def _parse_nodes(env_val, default):
    if not env_val:
        return list(default)
    out = []
    for item in env_val.split(","):
        item = item.strip()
        if item:
            name, _, ip = item.partition("=")
            out.append((name.strip(), ip.strip()))
    return out


def db_nodes():
    return _parse_nodes(os.environ.get("GALERA_DB_NODES"), DEFAULT_DB_NODES)


def arbitrator():
    nodes = _parse_nodes(os.environ.get("GALERA_ARBITRATOR"), [DEFAULT_ARBITRATOR])
    return nodes[0] if nodes else None


@dataclass
class NodeState:
    name: str
    ip: str
    host_reachable: bool = False      # SSH answered
    sql_ok: bool = False              # SHOW GLOBAL STATUS answered
    active_state: str = ""            # systemd ActiveState of mariadb.service
    sub_state: str = ""
    state_age_s: Optional[float] = None
    mariadbd_running: bool = False
    cluster_status: str = ""          # wsrep_cluster_status: Primary / non-Primary / Disconnected
    cluster_size: Optional[int] = None
    ready: Optional[bool] = None
    local_state: Optional[int] = None
    local_state_comment: str = ""
    connected: Optional[bool] = None
    local_uuid: str = ""              # wsrep_local_state_uuid (the data history)
    last_committed: Optional[int] = None
    gra_uuid: str = ""
    gra_seqno: Optional[int] = None
    gra_safe: Optional[int] = None
    recovered_uuid: str = ""
    recovered_seqno: Optional[int] = None
    disk_used_pct: Optional[int] = None
    error: str = ""

    @property
    def primary(self) -> bool:
        return self.sql_ok and self.cluster_status == "Primary"

    @property
    def stuck(self) -> bool:
        """mariadbd present (or the unit mid-transition) but SQL does not answer."""
        if self.sql_ok:
            return False
        return self.mariadbd_running or self.active_state in ("activating", "deactivating", "reloading")

    @property
    def stopped(self) -> bool:
        return self.host_reachable and not self.sql_ok and not self.stuck

    def position(self):
        """(uuid, seqno, source) — best known replication position, or (uuid|'', None, why)."""
        if self.sql_ok and self.last_committed is not None and self.last_committed >= 0:
            return self.local_uuid or self.gra_uuid, self.last_committed, "wsrep_last_committed"
        if self.recovered_seqno is not None and self.recovered_seqno >= 0:
            return self.recovered_uuid, self.recovered_seqno, "wsrep-recover"
        if not self.mariadbd_running and self.gra_seqno is not None and self.gra_seqno >= 0:
            return self.gra_uuid, self.gra_seqno, "grastate.dat (clean shutdown)"
        return (self.local_uuid or self.recovered_uuid or self.gra_uuid), None, "unknown"


@dataclass
class ArbState:
    name: str
    ip: str
    host_reachable: bool = False
    active: bool = False
    active_state: str = ""
    error: str = ""


@dataclass
class Decision:
    action: str
    reason: str
    winner: Optional[str] = None
    winner_mode: str = ""                     # "in-place" (running) or "new-cluster" (stopped)
    steps: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def exit_code(self):
        return {NOTHING: EXIT_OK, REFUSE: EXIT_REFUSED}.get(self.action, EXIT_PLAN)


# --------------------------------------------------------------------------- remote access

def ssh_cmd(ip, remote, timeout=25):
    """Run `remote` (a bash script) as root@ip. Returns (rc, stdout, stderr); rc 255 = SSH failed."""
    key = os.path.expanduser(os.environ.get("GALERA_SSH_KEY", "~/.ssh/one_key"))
    cmd = ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
           "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=5",
           "-o", "ServerAliveCountMax=2", f"root@{ip}", "bash -s"]
    try:
        p = subprocess.run(cmd, input=remote, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 255, "", f"ssh to {ip} timed out after {timeout}s"


_WSREP_VARS = ("wsrep_cluster_status", "wsrep_cluster_size", "wsrep_ready", "wsrep_local_state",
               "wsrep_local_state_comment", "wsrep_local_state_uuid", "wsrep_last_committed",
               "wsrep_connected")

COLLECT_DB = r"""
set +e
echo "ssh_ok=1"
systemctl show mariadb -p ActiveState -p SubState -p StateChangeTimestampMonotonic 2>/dev/null
echo "uptime_s=$(cut -d' ' -f1 /proc/uptime)"
echo "mariadbd_pids=$(pgrep -x mariadbd | tr '\n' ' ')"
if out=$(timeout 10 mariadb --connect-timeout=5 -N -B -e "SHOW GLOBAL STATUS WHERE Variable_name IN (%s)" 2>/dev/null) && [ -n "$out" ]; then
  echo "sql_ok=1"
  printf '%%s\n' "$out" | awk -F'\t' '{print "sql_"$1"="$2}'
else
  echo "sql_ok=0"
fi
if [ -r /var/lib/mysql/grastate.dat ]; then
  awk -F': *' '/^uuid:/{print "gra_uuid="$2} /^seqno:/{print "gra_seqno="$2} /^safe_to_bootstrap:/{print "gra_safe="$2}' /var/lib/mysql/grastate.dat
fi
df -Pk /var/lib/mysql 2>/dev/null | awk 'NR==2{gsub("%%","",$5); print "disk_used_pct="$5}'
""" % ",".join("'%s'" % v for v in _WSREP_VARS)

COLLECT_ARB = r"""
set +e
echo "ssh_ok=1"
echo "garb_state=$(systemctl is-active garb 2>/dev/null)"
"""


def _kv(text):
    out = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_db(name, ip, rc, stdout, stderr) -> NodeState:
    n = NodeState(name=name, ip=ip)
    kv = _kv(stdout)
    if kv.get("ssh_ok") != "1":
        n.error = (stderr or "").strip().splitlines()[-1] if (stderr or "").strip() else f"ssh rc={rc}"
        return n
    n.host_reachable = True
    n.active_state = kv.get("ActiveState", "")
    n.sub_state = kv.get("SubState", "")
    mono = _int(kv.get("StateChangeTimestampMonotonic"))
    try:
        up = float(kv.get("uptime_s", ""))
        if mono:
            n.state_age_s = max(0.0, up - mono / 1e6)
    except ValueError:
        pass
    n.mariadbd_running = bool(kv.get("mariadbd_pids", "").strip())
    n.sql_ok = kv.get("sql_ok") == "1"
    if n.sql_ok:
        n.cluster_status = kv.get("sql_wsrep_cluster_status", "")
        n.cluster_size = _int(kv.get("sql_wsrep_cluster_size"))
        n.ready = kv.get("sql_wsrep_ready", "").upper() == "ON"
        n.local_state = _int(kv.get("sql_wsrep_local_state"))
        n.local_state_comment = kv.get("sql_wsrep_local_state_comment", "")
        n.connected = kv.get("sql_wsrep_connected", "").upper() == "ON"
        n.local_uuid = kv.get("sql_wsrep_local_state_uuid", "")
        n.last_committed = _int(kv.get("sql_wsrep_last_committed"))
    n.gra_uuid = kv.get("gra_uuid", "")
    n.gra_seqno = _int(kv.get("gra_seqno"))
    n.gra_safe = _int(kv.get("gra_safe"))
    n.disk_used_pct = _int(kv.get("disk_used_pct"))
    return n


def parse_arb(name, ip, rc, stdout, stderr) -> ArbState:
    a = ArbState(name=name, ip=ip)
    kv = _kv(stdout)
    if kv.get("ssh_ok") != "1":
        a.error = (stderr or "").strip().splitlines()[-1] if (stderr or "").strip() else f"ssh rc={rc}"
        return a
    a.host_reachable = True
    a.active_state = kv.get("garb_state", "")
    a.active = a.active_state == "active"
    return a


def collect_node(name, ip) -> NodeState:
    rc, out, err = ssh_cmd(ip, COLLECT_DB)
    return parse_db(name, ip, rc, out, err)


def collect_arbitrator(name, ip) -> ArbState:
    rc, out, err = ssh_cmd(ip, COLLECT_ARB)
    return parse_arb(name, ip, rc, out, err)


def collect_all():
    """Collect every DB node + the arbitrator in parallel. Returns (nodes, arb)."""
    from concurrent.futures import ThreadPoolExecutor
    dbs = db_nodes()
    arb = arbitrator()
    with ThreadPoolExecutor(max_workers=len(dbs) + 1) as ex:
        futs = [ex.submit(collect_node, n, ip) for n, ip in dbs]
        afut = ex.submit(collect_arbitrator, *arb) if arb else None
        nodes = [f.result() for f in futs]
        arb_state = afut.result() if afut else None
    return nodes, arb_state


# --------------------------------------------------------------------------- decision

def _healthy(n: NodeState, expected_size: int) -> bool:
    return (n.primary and n.ready is True and n.local_state == SYNCED
            and n.cluster_size is not None and n.cluster_size >= expected_size)


def decide(nodes: List[NodeState], tie_prefer: str = DEFAULT_TIE_PREFER, exclude=(),
           expected_size: Optional[int] = None) -> Decision:
    """The guarded-bootstrap rules. Pure: no I/O. Order matters (each rule is a refusal gate).

    1. --exclude may only name a node that is unreachable (never silence a live node).
    2. Any node Primary                 -> NOTHING_TO_DO if every node is Primary+Synced at the
                                           expected size, else REFUSE (bootstrapping next to a live
                                           Primary component = split brain; rejoin instead).
    3. Any considered node unreachable  -> REFUSE (its position may be ahead).
    4. Cluster UUIDs differ / all-zero  -> REFUSE.
    5. Any position unknown             -> NEED_RECOVERY (stop stuck units, mariadbd --wsrep-recover).
    6. Otherwise BOOTSTRAP the highest seqno; a tie picks `tie_prefer`.
    """
    names = {n.name for n in nodes}
    exclude = list(exclude or ())
    for x in exclude:
        if x not in names:
            return Decision(REFUSE, f"--exclude {x}: no such Galera node (known: {', '.join(sorted(names))})")
        node = next(n for n in nodes if n.name == x)
        if node.host_reachable:
            return Decision(REFUSE, f"--exclude {x}: the host answers SSH; --exclude is only for a host "
                                    f"that is down. Collect its state instead.")
    considered = [n for n in nodes if n.name not in exclude]
    if not considered:
        return Decision(REFUSE, "no Galera node left to consider")
    if expected_size is None:
        expected_size = len(nodes) + 1 - len(exclude)      # + the arbitrator

    # A live Primary component anywhere ends the question: never bootstrap next to it.
    primaries = [n for n in considered if n.primary]
    if primaries:
        if all(_healthy(n, expected_size) for n in considered):
            sizes = sorted({n.cluster_size for n in considered})
            return Decision(NOTHING, f"cluster Primary, nothing to do ({len(considered)} DB node(s) "
                                     f"Primary/Synced, wsrep_cluster_size {'/'.join(map(str, sizes))})")
        p = ", ".join(n.name for n in primaries)
        others = [n.name for n in considered if not n.primary]
        hint = (f"start the others normally (`systemctl start mariadb` on {', '.join(others)}; they "
                f"rejoin by IST/SST)" if others else "check wsrep_cluster_size / garbd")
        return Decision(REFUSE, f"{p} already Primary: a bootstrap would create a second Primary "
                                f"component (split brain). Do not bootstrap; {hint}, then "
                                f"`systemctl start garb` on the arbitrator if it is not active.")

    unreachable = [n for n in considered if not n.host_reachable]
    if unreachable:
        who = ", ".join(f"{n.name} ({n.error or 'no answer'})" for n in unreachable)
        return Decision(REFUSE, f"cannot read {who}: its replication position may be ahead of the "
                                f"others. Bring the host back, or (operator decision, accepting that its "
                                f"last transactions may be lost) rerun with --exclude <name>.")

    uuids = {}
    for n in considered:
        u, _, _ = n.position()
        if u:
            uuids.setdefault(u, []).append(n.name)
    if ZERO_UUID in uuids:
        return Decision(REFUSE, f"{', '.join(uuids[ZERO_UUID])} report the all-zero state UUID (no "
                                f"history / interrupted SST): not a bootstrap candidate, operator decision.")
    if len(uuids) > 1:
        detail = "; ".join(f"{u} on {', '.join(v)}" for u, v in sorted(uuids.items()))
        return Decision(REFUSE, f"cluster state UUID mismatch ({detail}): these nodes do not share a "
                                f"history; choosing one discards the other's data. Operator decision.")

    warnings = [f"{n.name}: /var/lib/mysql is {n.disk_used_pct}% full (a full disk stopped mysqld on "
                f"2026-10-04; free space before starting it)"
                for n in considered if n.disk_used_pct is not None and n.disk_used_pct >= 95]

    unknown = [n for n in considered if n.position()[1] is None]
    if unknown:
        steps = []
        for n in unknown:
            if n.stuck:
                steps.append(f"{n.name}: mariadb {n.active_state or '?'}/{n.sub_state or '?'}, mariadbd "
                             f"{'running' if n.mariadbd_running else 'absent'}, SQL not answering -> stop it "
                             f"(systemctl stop, SIGKILL after the grace period; it never became Primary, "
                             f"so it holds no writes), then mariadbd --wsrep-recover")
            else:
                steps.append(f"{n.name}: stopped, grastate.dat seqno {n.gra_seqno} -> mariadbd --wsrep-recover")
        return Decision(RECOVER, f"replication position unknown on {', '.join(n.name for n in unknown)}",
                        steps=steps, warnings=warnings)

    best = max(n.position()[1] for n in considered)
    tied = [n for n in considered if n.position()[1] == best]
    if len(tied) > 1:
        pick = next((n for n in tied if n.name == tie_prefer), sorted(tied, key=lambda n: n.name)[0])
        why = f"tie at seqno {best} between {', '.join(n.name for n in tied)} -> preferred {pick.name}"
    else:
        pick = tied[0]
        why = f"highest seqno {best} ({pick.position()[2]})"
    mode = "in-place" if pick.sql_ok else "new-cluster"
    steps = []
    if mode == "in-place":
        steps.append(f"{pick.name}: SET GLOBAL wsrep_provider_pc_bootstrap=ON (running, non-Primary)")
    else:
        steps.append(f"{pick.name}: grastate.dat safe_to_bootstrap: 1 (backup kept), then galera_new_cluster")
    steps.append(f"{pick.name}: wait for wsrep_cluster_status=Primary")
    for n in considered:
        if n.name == pick.name:
            continue
        if n.sql_ok:
            steps.append(f"{n.name}: running non-Primary -> should join the new Primary by itself; "
                         f"restarted if it is not Synced within the wait")
        else:
            steps.append(f"{n.name}: systemctl start mariadb (rejoins by IST)")
    steps.append("arbitrator: systemctl start garb (restart if the cluster stays below the expected size)")
    steps.append(f"verify: every DB node Primary + Synced + ready, wsrep_cluster_size {expected_size}")
    return Decision(BOOTSTRAP, why, winner=pick.name, winner_mode=mode, steps=steps, warnings=warnings)


def describe(n: NodeState) -> str:
    if not n.host_reachable:
        return f"{n.name:22} {n.ip:16} host=DOWN ({n.error})"
    u, s, src = n.position()
    parts = [f"{n.name:22} {n.ip:16} host=up", f"mariadb={n.active_state}/{n.sub_state}"]
    if n.sql_ok:
        parts.append(f"sql=up status={n.cluster_status} size={n.cluster_size} "
                     f"ready={'ON' if n.ready else 'OFF'} state={n.local_state_comment}({n.local_state})")
    else:
        age = f" for {int(n.state_age_s)}s" if n.state_age_s is not None else ""
        parts.append(f"sql=DOWN{age} mariadbd={'running' if n.mariadbd_running else 'absent'}")
    parts.append(f"uuid={u or '?'} seqno={s if s is not None else '?'} ({src})")
    if n.gra_safe is not None:
        parts.append(f"safe_to_bootstrap={n.gra_safe}")
    if n.disk_used_pct is not None:
        parts.append(f"disk={n.disk_used_pct}%")
    return "  ".join(parts)
