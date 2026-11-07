#!/bin/bash
# test-galera-guarded-bootstrap.sh — decision logic + plan/execute flow of
# scripts/galera-guarded-bootstrap.py and the textfile render of scripts/write-galera-metrics.py
# (IFRNLLEI01PRD-2992, postmortem item 8).
#
# Hermetic: every SSH goes to a FAKE `ssh` on PATH that simulates the two DB nodes + garbd from
# a JSON state file in a mktemp dir. Nothing here can reach the live cluster (GALERA_DB_NODES
# points at TEST-NET addresses and the fake refuses anything else).
# QA_SUITE_TIMEOUT: 120
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-galera-guarded-bootstrap"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export GALERA_DB_NODES="nlcl01mariadb01=192.0.2.150,nlcl01mariadb02=192.0.2.151"
export GALERA_ARBITRATOR="nlcl01garbd01=192.0.2.153"
export GALERA_BOOTSTRAP_LOCK="$TMP/lock"
export FAKE_GALERA_STATE="$TMP/state.json"
export FAKE_GALERA_LOG="$TMP/ssh.log"
export PROMETHEUS_TEXTFILE_DIR="$TMP/prom"
UUID=934a2ed1-acd0-11ef-9a22-ffacd51c27ac

# ── the fake ssh: argv[-2] = root@IP, stdin = the remote bash script ─────────────
mkdir -p "$TMP/bin"
cat >"$TMP/bin/ssh" <<'PYEOF'
#!/usr/bin/env python3
import fcntl, json, os, sys
ip = sys.argv[-2].split("@", 1)[1]
script = sys.stdin.read()
lock = open(os.environ["FAKE_GALERA_STATE"] + ".lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)          # the CLI collects all hosts in parallel
st = json.load(open(os.environ["FAKE_GALERA_STATE"]))
with open(os.environ["FAKE_GALERA_LOG"], "a") as fh:
    fh.write(f"=== {ip}\n{script}\n")
node = next((n for n in st["db"] if n["ip"] == ip), None)
arb = st["arb"] if st["arb"]["ip"] == ip else None
if (node is None and arb is None) or (node or arb).get("down"):
    sys.stderr.write(f"ssh: connect to host {ip} port 22: No route to host\n"); sys.exit(255)

def recalc():
    if any(n["sql"] and n["status"] == "Primary" for n in st["db"]):
        live = [n for n in st["db"] if n["sql"] and not n.get("down")]
        size = len(live) + (1 if st["arb"]["active"] else 0)
        for n in live:
            n.update(status="Primary", ready="ON", state=4, size=size)
out = []
if node is not None:
    n = node
    if "SHOW GLOBAL STATUS" in script:
        out += ["ssh_ok=1", f"ActiveState={n['active']}", "SubState=x", "StateChangeTimestampMonotonic=1000000",
                "uptime_s=4000.0", f"mariadbd_pids={'123' if n['mariadbd'] else ''}"]
        if n["sql"]:
            out += ["sql_ok=1", f"sql_wsrep_cluster_status={n['status']}", f"sql_wsrep_cluster_size={n['size']}",
                    f"sql_wsrep_ready={n['ready']}", f"sql_wsrep_local_state={n['state']}",
                    "sql_wsrep_local_state_comment=" + ("Synced" if n["state"] == 4 else "Initialized"),
                    f"sql_wsrep_local_state_uuid={n['uuid']}", f"sql_wsrep_last_committed={n['seqno']}",
                    "sql_wsrep_connected=ON"]
        else:
            out.append("sql_ok=0")
        out += [f"gra_uuid={n['uuid']}", f"gra_seqno={n.get('gra_seqno', -1)}", f"gra_safe={n.get('safe', 0)}",
                "disk_used_pct=40"]
    elif "wsrep_provider_pc_bootstrap=ON" in script:
        n["status"] = "Primary"; recalc(); out.append("ok=1")
    elif "systemctl stop --no-block mariadb" in script:
        n.update(sql=False, mariadbd=False, active="inactive", status="", gra_seqno=-1)
        out += ["sigkill=1", "waited=3", "final_state=inactive"]
    elif "--wsrep-recover" in script:
        out += ["recover_rc=0", f"recover_pos={n['uuid']}:{n['seqno']}"]
    elif "galera_new_cluster" in script:
        n.update(sql=True, mariadbd=True, active="active", status="Primary", safe=1); recalc()
        out += ["backup=/root/grastate.dat.bak-test", "safe=1", "rc=0"]
    elif "systemctl start mariadb" in script:
        n.update(sql=True, mariadbd=True, active="active", status="non-Primary"); recalc(); out.append("rc=0")
else:
    if "systemctl is-active garb" in script:
        out += ["ssh_ok=1", f"garb_state={'active' if arb['active'] else 'failed'}"]
    elif "garb" in script:
        arb["active"] = True; recalc(); out.append("rc=0")
tmp = os.environ["FAKE_GALERA_STATE"] + ".tmp"
json.dump(st, open(tmp, "w")); os.replace(tmp, os.environ["FAKE_GALERA_STATE"])
print("\n".join(out))
PYEOF
chmod +x "$TMP/bin/ssh"
export PATH="$TMP/bin:$PATH"

# state builder: node(ip, sql, status, seqno, ...) as JSON
mkstate() { python3 - "$@" >"$FAKE_GALERA_STATE" <<'PYEOF'
import json, sys
# argv: "<db1 spec>" "<db2 spec>" "<arb active 0|1>" ; spec = k=v;k=v
def node(ip, spec):
    n = dict(ip=ip, sql=True, mariadbd=True, active="active", status="non-Primary", size=1, ready="OFF",
             state=0, uuid="934a2ed1-acd0-11ef-9a22-ffacd51c27ac", seqno=32351129)
    for kv in filter(None, spec.split(";")):
        k, v = kv.split("=", 1)
        n[k] = {"true": True, "false": False}.get(v, int(v) if v.lstrip("-").isdigit() else v)
    return n
print(json.dumps({"db": [node("192.0.2.150", sys.argv[1]), node("192.0.2.151", sys.argv[2])],
                  "arb": {"ip": "192.0.2.153", "active": sys.argv[3] == "1"}}))
PYEOF
}
BOOT="$REPO_ROOT/scripts/galera-guarded-bootstrap.py"
HEALTHY="status=Primary;size=3;ready=ON;state=4"
run_plan() { : >"$FAKE_GALERA_LOG"; python3 "$BOOT" "$@" 2>&1; echo "rc=$?"; }
MUTATING='wsrep_provider_pc_bootstrap=ON|systemctl stop|systemctl kill|galera_new_cluster|systemctl start|systemctl restart|safe_to_bootstrap: 1|--wsrep-recover'

# ── T1 decide(): the operator's fixture list, as pure-function cases ─────────────
start_test "decide_fixture_cases"
out=$(cd "$REPO_ROOT/scripts/lib" && python3 - <<'PYEOF'
import galera_cluster as gc
U = "934a2ed1-acd0-11ef-9a22-ffacd51c27ac"
def N(name, **kw):
    base = dict(host_reachable=True, sql_ok=True, active_state="active", mariadbd_running=True,
                cluster_status="non-Primary", cluster_size=1, ready=False, local_state=0,
                local_uuid=U, last_committed=32351129)
    base.update(kw); return gc.NodeState(name=name, ip="x", **base)
M1, M2 = "nlcl01mariadb01", "nlcl01mariadb02"
H = dict(cluster_status="Primary", cluster_size=3, ready=True, local_state=4)
cases = {
 "healthy":        [N(M1, **H), N(M2, **H)],
 "uuid_mismatch":  [N(M1), N(M2, local_uuid="11111111-2222-3333-4444-555555555555")],
 "tie":            [N(M1), N(M2)],
 "one_higher":     [N(M1, last_committed=32351200), N(M2)],
 "one_primary":    [N(M1, cluster_status="Primary", cluster_size=2, ready=True, local_state=4),
                    N(M2, sql_ok=False, mariadbd_running=False, active_state="failed", gra_seqno=-1)],
 "one_unreachable":[N(M1, host_reachable=False, sql_ok=False, error="No route to host"), N(M2)],
 "stuck_both":     [N(M1, sql_ok=False, active_state="deactivating", last_committed=None),
                    N(M2, sql_ok=False, active_state="deactivating", last_committed=None)],
 "stopped_clean":  [N(M1, sql_ok=False, mariadbd_running=False, active_state="inactive", gra_uuid=U, gra_seqno=500),
                    N(M2, sql_ok=False, mariadbd_running=False, active_state="inactive", gra_uuid=U, gra_seqno=400)],
 "zero_uuid":      [N(M1, local_uuid=gc.ZERO_UUID), N(M2)],
}
for k, nodes in cases.items():
    d = gc.decide(nodes)
    print(f"CASE {k}: {d.action} winner={d.winner} mode={d.winner_mode} exit={d.exit_code} | {d.reason}")
d = gc.decide(cases["tie"], tie_prefer=M1);              print(f"CASE tie_prefer_m1: {d.action} winner={d.winner}")
d = gc.decide(cases["one_unreachable"], exclude=[M1]);    print(f"CASE excl_down: {d.action} winner={d.winner}")
d = gc.decide(cases["tie"], exclude=[M1]);                print(f"CASE excl_live: {d.action} | {d.reason}")
s = cases["stuck_both"]
for n in s:
    n.recovered_uuid, n.recovered_seqno, n.active_state, n.mariadbd_running = U, 32351129, "inactive", False
d = gc.decide(s);                                         print(f"CASE stuck_recovered: {d.action} winner={d.winner} mode={d.winner_mode}")
PYEOF
)
assert_contains "$out" "CASE healthy: NOTHING_TO_DO winner=None mode= exit=0 | cluster Primary, nothing to do" "healthy = nothing to do, exit 0"
assert_contains "$out" "CASE uuid_mismatch: REFUSE" "UUID mismatch refused"
assert_contains "$out" "cluster state UUID mismatch" "mismatch reason named"
assert_contains "$out" "CASE tie: BOOTSTRAP winner=nlcl01mariadb02 mode=in-place exit=3" "tie -> mariadb02, in place"
assert_contains "$out" "CASE tie_prefer_m1: BOOTSTRAP winner=nlcl01mariadb01" "tie preference configurable"
assert_contains "$out" "CASE one_higher: BOOTSTRAP winner=nlcl01mariadb01" "higher seqno wins over the tie preference"
assert_contains "$out" "CASE one_primary: REFUSE" "a live Primary refuses the bootstrap"
assert_contains "$out" "already Primary" "split-brain reason named"
assert_contains "$out" "CASE one_unreachable: REFUSE" "an unreadable node refuses"
assert_contains "$out" "CASE excl_down: BOOTSTRAP winner=nlcl01mariadb02" "--exclude of a DOWN host allows the survivor"
assert_contains "$out" "CASE excl_live: REFUSE | --exclude nlcl01mariadb01: the host answers SSH" "--exclude of a live host refused"
assert_contains "$out" "CASE stuck_both: NEED_RECOVERY" "the 2026-11-07 stuck pair needs recovery first"
assert_contains "$out" "CASE stuck_recovered: BOOTSTRAP winner=nlcl01mariadb02 mode=new-cluster" "recovered equal seqno -> mariadb02 galera_new_cluster (the manual 2026-11-07 choice)"
assert_contains "$out" "CASE stopped_clean: BOOTSTRAP winner=nlcl01mariadb01 mode=new-cluster" "grastate seqno of a clean shutdown is used"
assert_contains "$out" "CASE zero_uuid: REFUSE" "all-zero UUID refused"
end_test

# ── T2 plan mode via the CLI: exit codes + NO mutating command reaches a host ─────
start_test "plan_mode_cli_exit_codes_and_read_only"
mkstate "$HEALTHY" "$HEALTHY" 1
out=$(run_plan); assert_contains "$out" "cluster Primary, nothing to do" "healthy plan"; assert_contains "$out" "rc=0" "healthy exit 0"
mkstate "" "" 1
out=$(run_plan); assert_contains "$out" "Decision: BOOTSTRAP" "tie plan"; assert_contains "$out" "rc=3" "plan needing action exits 3"
assert_contains "$out" "No changes made" "plan says nothing changed"
mkstate "" "uuid=11111111-2222-3333-4444-555555555555" 1
out=$(run_plan); assert_contains "$out" "rc=2" "mismatch exits 2"
mkstate "down=true" "" 1
out=$(run_plan); assert_contains "$out" "host=DOWN" "down host shown"; assert_contains "$out" "rc=2" "unreachable exits 2"
mkstate "sql=false;active=deactivating" "sql=false;active=deactivating" 0
out=$(run_plan); assert_contains "$out" "NEED_RECOVERY" "stuck pair"; assert_contains "$out" "rc=3" "stuck plan exits 3"
if grep -qE "$MUTATING" "$FAKE_GALERA_LOG"; then fail_test "plan mode sent a mutating command: $(grep -oE "$MUTATING" "$FAKE_GALERA_LOG" | sort -u | tr '\n' ' ')"; fi
end_test

# ── T3 --execute, in place: tie, both running non-Primary, garb down ──────────────
start_test "execute_in_place_tie"
mkstate "" "" 0
: >"$FAKE_GALERA_LOG"
out=$(python3 "$BOOT" --execute 2>&1); rc=$?
assert_eq 0 "$rc" "execute exits 0 when verified"
assert_contains "$out" "nlcl01mariadb02: SET GLOBAL wsrep_provider_pc_bootstrap=ON" "bootstraps the preferred node in place"
assert_contains "$out" "VERIFIED: Primary, Synced, wsrep_cluster_size 3" "verified at size 3"
assert_contains "$(cat "$FAKE_GALERA_LOG")" "systemctl start garb" "garb was started"
if grep -q 'galera_new_cluster' "$FAKE_GALERA_LOG"; then fail_test "in-place case must not run galera_new_cluster"; fi
end_test

# ── T4 --execute, the 2026-11-07 shape: both stuck deactivating -> kill, recover, new cluster
start_test "execute_stuck_pair_recover_new_cluster"
mkstate "sql=false;active=deactivating" "sql=false;active=deactivating" 0
: >"$FAKE_GALERA_LOG"
out=$(python3 "$BOOT" --execute --grace 1 2>&1); rc=$?
assert_eq 0 "$rc" "execute exits 0"
assert_contains "$out" "nlcl01mariadb01: stopping mariadb" "stuck mariadb01 stopped"
assert_contains "$out" "nlcl01mariadb02: recovered position $UUID:32351129" "position recovered"
assert_contains "$out" "Winner:   nlcl01mariadb02 (new-cluster)" "tie -> mariadb02 via galera_new_cluster"
assert_contains "$out" "nlcl01mariadb01: systemctl start mariadb" "the other node started after the bootstrap"
assert_contains "$out" "VERIFIED" "verified"
order=$(grep -nE 'galera_new_cluster|systemctl start mariadb' "$FAKE_GALERA_LOG" | head -2 | tr '\n' ' ')
assert_contains "$order" "galera_new_cluster" "bootstrap issued"
end_test

# ── T5 --execute refuses (and changes nothing) next to a live Primary ─────────────
start_test "execute_refuses_with_live_primary"
mkstate "status=Primary;size=2;ready=ON;state=4" "sql=false;mariadbd=false;active=failed" 1
: >"$FAKE_GALERA_LOG"
out=$(python3 "$BOOT" --execute 2>&1); rc=$?
assert_eq 2 "$rc" "refusal exits 2"
assert_contains "$out" "already Primary" "reason"
if grep -qE "$MUTATING" "$FAKE_GALERA_LOG"; then fail_test "a refused --execute sent a mutating command"; fi
end_test

# ── T6 metrics writer renders the alert inputs ─────────────────────────────────
start_test "writer_render"
mkstate "sql=false;mariadbd=false;active=failed" "" 0
python3 "$REPO_ROOT/scripts/write-galera-metrics.py" >/dev/null 2>&1
prom="$PROMETHEUS_TEXTFILE_DIR/galera.prom"
assert_file_exists "$prom" "galera.prom written"
body=$(cat "$prom" 2>/dev/null)
assert_contains "$body" 'galera_node_primary{cluster="eu-nl-mariadb01",node="nlcl01mariadb01"} 0' "down node primary=0"
assert_contains "$body" 'galera_node_reachable{cluster="eu-nl-mariadb01",node="nlcl01mariadb01"} 0' "down node reachable=0"
assert_contains "$body" 'galera_node_host_reachable{cluster="eu-nl-mariadb01",node="nlcl01mariadb01"} 1' "host still reachable"
assert_contains "$body" 'galera_node_cluster_status{cluster="eu-nl-mariadb01",node="nlcl01mariadb02",status="non-Primary"} 1' "status label"
assert_contains "$body" 'galera_cluster_primary_nodes{cluster="eu-nl-mariadb01"} 0' "no primary"
assert_not_contains "$body" 'galera_node_cluster_size{cluster="eu-nl-mariadb01",node="nlcl01mariadb01"}' "no wsrep gauges without SQL"
assert_contains "$body" 'galera_exporter_last_run_timestamp_seconds' "dead-man timestamp"
if ls "$PROMETHEUS_TEXTFILE_DIR"/.galera.* >/dev/null 2>&1; then fail_test "temp file left behind"; fi
end_test
