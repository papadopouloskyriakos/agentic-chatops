#!/usr/bin/env python3
"""
galera-guarded-bootstrap.py — one-command, guarded bootstrap of the NL Galera cluster
"eu-nl-mariadb01" after it lost its Primary component (IFRNLLEI01PRD-2992, postmortem item 8:
"alert + guarded one-command bootstrap, never automatic").

    scripts/galera-guarded-bootstrap.py                 # PLAN: read-only, prints state + decision
    scripts/galera-guarded-bootstrap.py --recover       # PLAN + mariadbd --wsrep-recover on STOPPED nodes
    scripts/galera-guarded-bootstrap.py --execute       # act, following the runbook sequence

NEVER wire this into automation (no cron, no alert hook, no auto-heal lane): the operator decided
that a human runs it. The GaleraNoPrimary alert points here for the read-only plan.

Guards (scripts/lib/galera_cluster.py decide(), unit-tested in
scripts/qa/suites/test-galera-guarded-bootstrap.sh):
  - REFUSES if any node is already Primary (bootstrapping next to it = split brain);
  - REFUSES on a cluster state UUID mismatch or an all-zero UUID;
  - REFUSES if a DB host cannot be read (its position may be ahead) unless the operator names it
    with --exclude (only accepted for a host that does not answer SSH);
  - picks the highest seqno; a tie picks --tie-prefer (default nlcl01mariadb02).

--execute sequence (runbook infrastructure/nl/production native/dbcluster/CLAUDE.md
§ Troubleshooting, as done by hand on 2026-11-07):
  1. stuck units (mariadbd present but SQL dead, or the unit stuck activating/deactivating — the
     2026-11-07 gcomm reconnect loop with TimeoutStopSec 15 min): systemctl stop, SIGKILL after
     --grace seconds (a never-Primary node holds no writes), then mariadbd --wsrep-recover;
  2. bootstrap the winner: running -> SET GLOBAL wsrep_provider_pc_bootstrap=ON (11.8; the old
     wsrep_provider_options='pc.bootstrap=YES' is read-only now); stopped -> grastate.dat
     safe_to_bootstrap: 1 (backup in /root) + galera_new_cluster;
  3. start the other node (IST), restart it if it does not reach Synced;
  4. systemctl start garb on the arbitrator (it fails at boot when there is no Primary);
  5. verify every DB node Primary + Synced + ready at wsrep_cluster_size 3.

Exit: 0 nothing to do / executed and verified, 1 error, 2 refused, 3 plan only (action needed).
"""
import argparse
import fcntl
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import galera_cluster as gc  # noqa: E402

LOCK_PATH = os.environ.get("GALERA_BOOTSTRAP_LOCK", "/tmp/galera-guarded-bootstrap.lock")

RECOVER_SH = r"""
set -u
if pgrep -x mariadbd >/dev/null; then echo "recover_error=mariadbd is running"; exit 0; fi
log=/tmp/galera-recover.$$.log
timeout 600 runuser -u mysql -- mariadbd --wsrep-recover --log-error="$log" >/dev/null 2>&1
echo "recover_rc=$?"
echo "recover_pos=$(grep -o 'Recovered position: [0-9a-f-]*:-\{0,1\}[0-9]*' "$log" 2>/dev/null | tail -1 | sed 's/^Recovered position: //')"
rm -f "$log"
"""

STOP_HARD_SH = r"""
set -u
systemctl stop --no-block mariadb
i=0
while [ "$i" -lt %(grace)d ]; do
  st=$(systemctl show mariadb -p ActiveState --value)
  case "$st" in active|activating|deactivating|reloading) ;; *) pgrep -x mariadbd >/dev/null || break ;; esac
  sleep 1; i=$((i+1))
done
if pgrep -x mariadbd >/dev/null; then
  echo "sigkill=1"
  systemctl kill --signal=SIGKILL mariadb
  j=0; while pgrep -x mariadbd >/dev/null && [ "$j" -lt 30 ]; do sleep 1; j=$((j+1)); done
  pgrep -x mariadbd >/dev/null && pkill -9 -x mariadbd && sleep 2
fi
pgrep -x mariadbd >/dev/null && echo "still_running=1"
systemctl reset-failed mariadb 2>/dev/null
echo "waited=$i"
echo "final_state=$(systemctl show mariadb -p ActiveState --value)"
"""

IN_PLACE_SH = r"""
timeout 30 mariadb --connect-timeout=5 -N -B -e "SET GLOBAL wsrep_provider_pc_bootstrap=ON" && echo "ok=1"
"""

NEW_CLUSTER_SH = r"""
set -u
f=/var/lib/mysql/grastate.dat
[ -f "$f" ] || { echo "error=no grastate.dat"; exit 0; }
pgrep -x mariadbd >/dev/null && { echo "error=mariadbd is running"; exit 0; }
bak="/root/grastate.dat.bak-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$f" "$bak" && echo "backup=$bak"
sed -i 's/^safe_to_bootstrap:.*/safe_to_bootstrap: 1/' "$f"
echo "safe=$(awk -F': *' '/^safe_to_bootstrap:/{print $2}' "$f")"
timeout 900 galera_new_cluster >/dev/null 2>&1
echo "rc=$?"
"""

START_SH = r"""
systemctl reset-failed mariadb 2>/dev/null
timeout 900 systemctl start mariadb
echo "rc=$?"
"""


def log(msg):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}Z] {msg}", flush=True)


def remote(node, script, timeout):
    rc, out, err = gc.ssh_cmd(node.ip, script, timeout=timeout)
    kv = gc._kv(out)
    if rc != 0:
        kv.setdefault("error", (err.strip().splitlines() or [f"rc={rc}"])[-1])
    return kv


def print_state(nodes, arb):
    print(f"Galera cluster {gc.CLUSTER_NAME}")
    for n in nodes:
        print("  " + gc.describe(n))
    if arb:
        state = (f"garb={arb.active_state or '?'}" if arb.host_reachable else f"host=DOWN ({arb.error})")
        print(f"  {arb.name:22} {arb.ip:16} {state}")


def print_decision(d):
    print(f"Decision: {d.action} — {d.reason}")
    if d.winner:
        print(f"Winner:   {d.winner} ({d.winner_mode})")
    for w in d.warnings:
        print(f"WARNING:  {w}")
    for i, s in enumerate(d.steps, 1):
        print(f"  {i}. {s}")


def collect(args):
    nodes, arb = gc.collect_all()
    return nodes, arb


def recover_positions(nodes, exclude):
    """mariadbd --wsrep-recover on every STOPPED node whose position is unknown (never on a live one)."""
    for n in nodes:
        if n.name in exclude or not n.host_reachable or n.position()[1] is not None:
            continue
        if n.mariadbd_running or n.stuck:
            log(f"{n.name}: mariadbd present, not recovering (stop it first)")
            continue
        log(f"{n.name}: mariadbd --wsrep-recover ...")
        kv = remote(n, RECOVER_SH, timeout=660)
        pos = kv.get("recover_pos", "")
        if kv.get("recover_error") or ":" not in pos:
            log(f"{n.name}: recovery gave no position ({kv.get('recover_error') or kv.get('error') or 'rc=' + kv.get('recover_rc', '?')})")
            continue
        uuid, _, seqno = pos.rpartition(":")
        n.recovered_uuid, n.recovered_seqno = uuid, gc._int(seqno)
        log(f"{n.name}: recovered position {uuid}:{seqno}")


def wait_for(pred, timeout, interval=5):
    deadline = time.time() + timeout
    while True:
        nodes, arb = gc.collect_all()
        if pred(nodes, arb):
            return True, nodes, arb
        if time.time() >= deadline:
            return False, nodes, arb
        time.sleep(interval)


def by_name(nodes, name):
    return next(n for n in nodes if n.name == name)


def stop_hard(n, grace):
    log(f"{n.name}: stopping mariadb (SIGKILL after {grace}s if it does not stop)")
    kv = remote(n, STOP_HARD_SH % {"grace": grace}, timeout=grace + 90)
    log(f"{n.name}: stop -> state={kv.get('final_state', '?')} waited={kv.get('waited', '?')}s"
        f"{' SIGKILL' if kv.get('sigkill') else ''}{' STILL RUNNING' if kv.get('still_running') else ''}")
    return not kv.get("still_running") and not kv.get("error")


def start_db(n):
    log(f"{n.name}: systemctl start mariadb (blocks until joined; up to 15 min)")
    kv = remote(n, START_SH, timeout=960)
    log(f"{n.name}: start rc={kv.get('rc', kv.get('error', '?'))}")
    return kv.get("rc") == "0"


def execute(args, nodes, arb, d):
    exclude = set(args.exclude or [])
    expected = len(nodes) + 1 - len(exclude)
    if d.action == gc.RECOVER:
        for n in nodes:
            if n.name not in exclude and n.stuck and n.position()[1] is None:
                if not stop_hard(n, args.grace):
                    log(f"ABORT: {n.name} did not stop")
                    return gc.EXIT_ERROR
        nodes, arb = collect(args)
        recover_positions(nodes, exclude)
        d = gc.decide(nodes, tie_prefer=args.tie_prefer, exclude=args.exclude)
        print_state(nodes, arb)
        print_decision(d)
        if d.action != gc.BOOTSTRAP:
            if d.action == gc.RECOVER:
                log("ABORT: a replication position is still unknown; nothing was bootstrapped")
                return gc.EXIT_ERROR
            return d.exit_code

    w = by_name(nodes, d.winner)
    if d.winner_mode == "in-place":
        log(f"{w.name}: SET GLOBAL wsrep_provider_pc_bootstrap=ON")
        kv = remote(w, IN_PLACE_SH, timeout=45)
        if kv.get("ok") != "1":
            log(f"ABORT: in-place bootstrap failed on {w.name}: {kv.get('error', 'no ok')}")
            return gc.EXIT_ERROR
    else:
        log(f"{w.name}: safe_to_bootstrap: 1 + galera_new_cluster")
        kv = remote(w, NEW_CLUSTER_SH, timeout=960)
        if kv.get("error") or kv.get("rc") != "0":
            log(f"ABORT: galera_new_cluster failed on {w.name}: {kv.get('error') or 'rc=' + kv.get('rc', '?')} "
                f"(grastate backup {kv.get('backup', 'none')})")
            return gc.EXIT_ERROR
        log(f"{w.name}: grastate backup {kv.get('backup')}")
    ok, nodes, arb = wait_for(lambda ns, a: by_name(ns, w.name).primary, timeout=120)
    if not ok:
        log(f"ABORT: {w.name} did not become Primary")
        print_state(nodes, arb)
        return gc.EXIT_ERROR
    log(f"{w.name}: Primary")

    for n in nodes:
        if n.name == w.name or n.name in exclude:
            continue
        if n.sql_ok:
            ok, nodes, arb = wait_for(lambda ns, a, nm=n.name: by_name(ns, nm).primary
                                      and by_name(ns, nm).local_state == gc.SYNCED, timeout=120)
            if ok:
                log(f"{n.name}: joined (Synced)")
                continue
            log(f"{n.name}: not Synced after 120s, restarting it")
            if not stop_hard(by_name(nodes, n.name), args.grace):
                return gc.EXIT_ERROR
        if not start_db(n):
            log(f"ABORT: {n.name} failed to start (the cluster is Primary on {w.name})")
            return gc.EXIT_ERROR

    if arb and arb.host_reachable:
        for attempt in ("start", "restart"):
            log(f"{arb.name}: systemctl {attempt} garb")
            rc, _, err = gc.ssh_cmd(arb.ip, f"timeout 120 systemctl {attempt} garb; echo rc=$?", timeout=150)
            ok, nodes, arb2 = wait_for(lambda ns, a: all(x.cluster_size == expected for x in ns
                                                         if x.name not in exclude and x.sql_ok), timeout=60)
            if ok:
                break
        arb = arb2
    elif arb:
        log(f"{arb.name}: host unreachable, garb not started")

    def healthy(ns, a):
        return all(gc._healthy(x, expected) for x in ns if x.name not in exclude)
    ok, nodes, arb = wait_for(healthy, timeout=120)
    print_state(nodes, arb)
    if ok:
        log(f"VERIFIED: Primary, Synced, wsrep_cluster_size {expected}")
        return gc.EXIT_OK
    log("NOT VERIFIED: the cluster has a Primary but is not fully Synced at the expected size; check above")
    return gc.EXIT_ERROR


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="act (default: plan only)")
    ap.add_argument("--recover", action="store_true",
                    help="plan mode: run mariadbd --wsrep-recover on STOPPED nodes with an unknown position")
    ap.add_argument("--tie-prefer", default=gc.DEFAULT_TIE_PREFER,
                    help=f"winner on equal seqno (default {gc.DEFAULT_TIE_PREFER})")
    ap.add_argument("--exclude", action="append", default=[], metavar="NODE",
                    help="leave out a DB node whose HOST IS DOWN (operator decision: its last transactions "
                         "may be lost); refused for a host that answers SSH")
    ap.add_argument("--grace", type=int, default=60,
                    help="seconds a stuck mariadb gets to stop before SIGKILL (default 60)")
    args = ap.parse_args()

    nodes, arb = collect(args)
    if args.recover and not args.execute:
        recover_positions(nodes, set(args.exclude))
    d = gc.decide(nodes, tie_prefer=args.tie_prefer, exclude=args.exclude)
    print(f"MODE: {'EXECUTE' if args.execute else 'PLAN (read-only' + (', --recover' if args.recover else '') + ')'}")
    print_state(nodes, arb)
    print_decision(d)

    if not args.execute or d.action in (gc.NOTHING, gc.REFUSE):
        if d.action in (gc.BOOTSTRAP, gc.RECOVER) and not args.execute:
            print("No changes made. Rerun with --execute to act on this plan.")
        return d.exit_code

    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"another galera-guarded-bootstrap --execute holds {LOCK_PATH}", file=sys.stderr)
        return gc.EXIT_ERROR
    return execute(args, nodes, arb, d)


if __name__ == "__main__":
    sys.exit(main())
