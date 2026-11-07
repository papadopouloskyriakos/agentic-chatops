#!/usr/bin/env python3
"""remediate-disk-pressure.py — auto cleanup + disk-grow ladder (operator directive #3, 2026-07-08).

Ladder for a disk-pressure alert on a PVE guest:
  1. reversible cleanup (docker image prune, journal vacuum, apt clean, fstrim) → re-measure
  2. if still >= threshold, GROW the disk by grow-pct (clamped [min,max] G):
       LXC  -> `pct resize <vmid> <disk> +<N>G`  (grows the guest fs in one step)
       QEMU -> `qm resize <vmid> <disk> +<N>G` then guest-side growpart + resize2fs/xfs_growfs
  3. every executed grow pages AUTO_NOTICE (Matrix + SMS) and is logged to disk_grow_log.

HARD SAFETY FLOORS (all must pass, else refuse+escalate — never trade guest pressure for host
pressure, the rpool-99% incident class):
  * backing PVE storage pool must stay >= --pool-floor-pct free AFTER the grow
  * host ZFS rpool must not be near-full / suspended (zpool health probe)
  * target node's pmxcfs must NOT be wedged (a resize on a wedged node enters D-state and
    worsens the deadlock — the lab-stats amplifier incident) — pre-flight probe, abort if wedged
  * rate cap: no second grow on the same guest within --rate-cap-days (repeat pressure = a real
    leak; escalate instead of growing forever)
  * grow is ONE-WAY (never shrink); resolution is ALWAYS from live pvesh (never VMID math — drift)

GATED: ships behind ~/gateway.disk_autogrow_armed. Without the sentinel it runs in ANALYSIS-ONLY
mode (measures + decides + logs, executes nothing) regardless of --execute. `rm` the sentinel to
disable instantly.

  remediate-disk-pressure.py --host nlghostfolio01            # analysis (unless armed + --execute)
  remediate-disk-pressure.py --host nlghostfolio01 --execute  # act (only if sentinel present)
"""
from __future__ import annotations

import argparse
import json
import os
REDACTED_a7b84d63
import shlex
import sqlite3
import subprocess
import sys
import time
import urllib.request

DB = os.environ.get("GATEWAY_DB", "/home/app-user/gateway-state/gateway.db")
SENTINEL = os.path.expanduser("~/gateway.disk_autogrow_armed")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
try:
    import mutation_mode  # MUTATIONS=OFF shadow gate (IFRNLLEI01PRD-1824)
except Exception:  # noqa: BLE001
    mutation_mode = None
SMS_URL = os.environ.get("AUTONOMY_SMS_URL", "http://127.0.0.1:9106/alert-session")
HS = os.environ.get("MATRIX_HOME_SERVER", "https://matrix.example.net")
ROOM = os.environ.get("MATRIX_DISKGROW_ROOM", "!AOMuEtXGyzGFLgObKN:matrix.example.net")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DBG_LOG = os.environ.get("GATEWAY_DEBUG_LOG", "/home/app-user/logs/claude-gateway/pipeline-debug.log")
# Healthy-first so a wedged pve01 is queried LAST (lab-stats.py amplifier lesson).
PVE_CLUSTER_HOSTS = os.environ.get(
    "PVE_CLUSTER_HOSTS", "nl-pve03,nlpve04,nl-pve02,nl-pve01").split(",")


def _dbg(event, **f):
    try:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "script": "remediate-disk-pressure", "pid": os.getpid(), "event": event, **f}
        os.makedirs(os.path.dirname(DBG_LOG), exist_ok=True)
        with open(DBG_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _env_secret(name):
    v = os.environ.get(name, "")
    if v:
        return v
    try:
        for line in open(os.path.join(REPO, ".env"), encoding="utf-8"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _ssh_prefix(node):
    """NL PVE nodes: key-based `ssh <node>`. GR nodes: `ssh -i one_key root@<node>`."""
    if node.startswith("grskg"):
        return ["ssh", "-i", os.path.expanduser("~/.ssh/one_key"), "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", f"root@{node}"]
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=no", node]


def _run(argv, timeout=45):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}:{e}"


def _node_cmd(node, remote, timeout=45):
    """Run a remote command on a PVE node, ALWAYS timeout-wrapped server-side."""
    return _run(_ssh_prefix(node) + [f"timeout {min(timeout, 60)} {remote}"], timeout=timeout + 5)


def resolve_guest(host):
    """name -> {vmid, node, type, maxdisk_g} from LIVE pvesh (never VMID math). Healthy-node-first."""
    for probe in PVE_CLUSTER_HOSTS:
        rc, out, _ = _node_cmd(probe, "pvesh get /cluster/resources --type vm --output-format json 2>/dev/null", timeout=30)
        if rc != 0 or not out:
            continue
        try:
            for r in json.loads(out):
                if r.get("name") == host:
                    return {"vmid": r["vmid"], "node": r["node"], "type": r["type"],
                            "maxdisk_g": round(r.get("maxdisk", 0) / 1e9, 1), "status": r.get("status")}
            return None  # cluster answered but host not found
        except Exception:  # noqa: BLE001
            continue
    return "unreachable"


def pmxcfs_ok(node):
    """Pre-flight: the node's pmxcfs must answer quickly. A resize on a wedged node D-states."""
    rc, out, _ = _node_cmd(node, "timeout 8 pvesh get /cluster/status --output-format json >/dev/null 2>&1 && echo OK", timeout=15)
    return rc == 0 and out.strip().endswith("OK")


def disk_config(node, vmid, gtype):
    """Return (disk_key, storage, size_g) for the boot disk. Parses pct/qm config."""
    tool = "pct" if gtype == "lxc" else "qm"
    rc, out, _ = _node_cmd(node, f"{tool} config {vmid} 2>/dev/null", timeout=20)
    if rc != 0 or not out:
        return None
    boot_disk = None
    if gtype == "qemu":
        m = re.search(r"^boot:.*order=([a-z0-9]+)", out, re.M)
        boot_disk = m.group(1) if m else None
    keys = ["rootfs"] if gtype == "lxc" else ([boot_disk] if boot_disk else []) + ["scsi0", "virtio0", "sata0"]
    for key in keys:
        m = re.search(rf"^{re.escape(key)}:\s*(\S+)", out, re.M)
        if not m:
            continue
        spec = m.group(1)
        storage = spec.split(":", 1)[0]
        sz = re.search(r"size=(\d+)([GMT])", spec)
        size_g = None
        if sz:
            val, unit = float(sz.group(1)), sz.group(2)
            size_g = val * (1024 if unit == "T" else 1 if unit == "G" else 1 / 1024.0)
        return (key, storage, size_g)
    return None


def pool_free_pct(node, storage, minus_g=0.0):
    rc, out, _ = _node_cmd(node, f"pvesh get /nodes/{node}/storage/{storage}/status --output-format json 2>/dev/null", timeout=20)
    if rc != 0 or not out:
        return None
    try:
        d = json.loads(out)
        total, avail = float(d.get("total", 0)), float(d.get("avail", 0))
        if total <= 0:
            return None
        return (avail - minus_g * 1e9) / total * 100.0
    except Exception:  # noqa: BLE001
        return None


def rpool_healthy(node):
    """Guard the ZFS rpool-99%/suspend incident class independently of the dir-storage avail."""
    rc, out, _ = _node_cmd(node, "zpool list -Hp -o name,size,alloc,health rpool 2>/dev/null", timeout=15)
    if rc != 0 or not out:
        return None  # unknown -> caller treats as fail-safe (do not grow)
    try:
        _, size, alloc, health = out.split()
        used_pct = float(alloc) / float(size) * 100.0 if float(size) else 100.0
        return health == "ONLINE" and used_pct < 90.0
    except Exception:  # noqa: BLE001
        return None


def guest_df_pct(node, vmid, gtype, host):
    """Return int %used of the guest root fs, or None."""
    if gtype == "lxc":
        rc, out, _ = _node_cmd(node, f"pct exec {vmid} -- df -P / 2>/dev/null | tail -1", timeout=25)
    else:
        rc, out, _ = _guest_cmd(host, "df -P / 2>/dev/null | tail -1")
    if rc != 0 or not out:
        return None
    m = re.search(r"(\d+)%", out)
    return int(m.group(1)) if m else None


def _guest_cmd(host, remote, timeout=30):
    """SSH into the GUEST (QEMU fs-grow). Best-effort: key-based then one_key root@."""
    for pre in ([["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", host]],
                [["ssh", "-i", os.path.expanduser("~/.ssh/one_key"), "-o", "BatchMode=yes",
                  "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", f"root@{host}"]]):
        rc, out, err = _run(pre[0] + [f"timeout {timeout} {remote}"], timeout=timeout + 5)
        if rc == 0:
            return rc, out, err
    return 1, "", "guest-ssh-failed"


def cleanup(node, vmid, gtype, host):
    """Reversible reclaim inside the guest. Best-effort; returns GiB reclaimed (approx)."""
    script = ("docker image prune -a -f 2>/dev/null; journalctl --vacuum-size=200M 2>/dev/null; "
              "apt-get clean 2>/dev/null; rm -rf /tmp/*.tmp 2>/dev/null; fstrim -av 2>/dev/null; true")
    before = guest_df_pct(node, vmid, gtype, host)
    if gtype == "lxc":
        _node_cmd(node, f"pct exec {vmid} -- sh -c {shlex.quote(script)}", timeout=120)
    else:
        _guest_cmd(host, f"sh -c {shlex.quote(script)}", timeout=120)
    after = guest_df_pct(node, vmid, gtype, host)
    return before, after


def notify(text, sms=True):
    tok = _env_secret("MATRIX_ACCESS_TOKEN") or _env_secret("MATRIX_CLAUDE_TOKEN")
    if tok:
        try:
            body = json.dumps({"msgtype": "m.text", "body": text}).encode()
            txn = f"diskgrow-{int(time.time())}"
            req = urllib.request.Request(f"{HS}/_matrix/client/v3/rooms/{ROOM}/send/m.room.message/{txn}",
                                         data=body, method="PUT",
                                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=8).close()
        except Exception:  # noqa: BLE001
            pass
    if sms:
        try:
            payload = json.dumps({"issue_id": "disk-autogrow", "summary": text[:150],
                                  "band": "AUTO_NOTICE", "host": "", "risk_level": "high",
                                  "reason": "disk-autogrow"}).encode()
            req = urllib.request.Request(SMS_URL, data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=4).close()
        except Exception:  # noqa: BLE001
            pass


def _log(**cols):
    try:
        conn = sqlite3.connect(DB, timeout=20)
        conn.execute("PRAGMA busy_timeout=20000")
        keys = ",".join(cols)
        conn.execute(f"INSERT INTO disk_grow_log ({keys}) VALUES ({','.join('?' * len(cols))})",
                     tuple(cols.values()))
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        _dbg("log_failed", error=str(e)[:120])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", required=True)
    ap.add_argument("--execute", action="store_true", help="actually cleanup+grow (needs the sentinel too)")
    ap.add_argument("--threshold-pct", type=int, default=90)
    ap.add_argument("--grow-pct", type=float, default=20.0)
    ap.add_argument("--min-grow-g", type=float, default=5.0)
    ap.add_argument("--max-grow-g", type=float, default=50.0)
    ap.add_argument("--pool-floor-pct", type=float, default=25.0)
    ap.add_argument("--rate-cap-days", type=float, default=7.0)
    args = ap.parse_args()

    armed = os.path.exists(SENTINEL)
    execute = args.execute and armed and not (mutation_mode and mutation_mode.is_shadow())
    if args.execute and armed and mutation_mode and mutation_mode.is_shadow():
        mutation_mode.log_wouldve("disk-grow", rationale="would grow disk / run cleanup (analysis-only in shadow)")
    mode = "EXECUTE" if execute else ("ANALYSIS(disarmed)" if args.execute else "ANALYSIS")
    out = {"host": args.host, "mode": mode}

    g = resolve_guest(args.host)
    if g in (None, "unreachable"):
        out["result"] = f"resolve-failed:{g}"; print(json.dumps(out)); return 0
    out.update({"vmid": g["vmid"], "node": g["node"], "type": g["type"]})
    node, vmid, gtype = g["node"], g["vmid"], g["type"]

    if not pmxcfs_ok(node):
        notify(f"⚠ disk-autogrow ABORTED on {args.host}: node {node} pmxcfs probe failed (wedge risk). Manual check needed.")
        _log(hostname=args.host, vmid=vmid, node=node, guest_type=gtype, outcome="refused-pmxcfs-wedge")
        out["result"] = "refused-pmxcfs-wedge"; print(json.dumps(out)); return 0

    dc = disk_config(node, vmid, gtype)
    if not dc:
        out["result"] = "disk-config-parse-failed"; print(json.dumps(out)); return 0
    disk_key, storage, size_g = dc
    out.update({"disk": disk_key, "storage": storage, "size_g": size_g})

    pct0 = guest_df_pct(node, vmid, gtype, args.host)
    out["fs_pct_before"] = pct0

    # 1) cleanup (reversible) — only when executing; analysis mode just reports intent
    reclaimed_note = "skipped(analysis)"
    if execute:
        b, a = cleanup(node, vmid, gtype, args.host)
        reclaimed_note = f"{b}%->{a}%"
        pct_after_clean = a if a is not None else pct0
    else:
        pct_after_clean = pct0
    out["cleanup"] = reclaimed_note
    out["fs_pct_after_cleanup"] = pct_after_clean

    if pct_after_clean is None or pct_after_clean < args.threshold_pct:
        out["result"] = "cleanup-only" if execute else "would-cleanup-only-or-noop"
        _log(hostname=args.host, vmid=vmid, node=node, guest_type=gtype, disk_key=disk_key,
             storage=storage, before_size_g=size_g or 0, fs_pct_before=pct0 if pct0 is not None else -1,
             fs_pct_after=pct_after_clean if pct_after_clean is not None else -1, outcome=out["result"])
        print(json.dumps(out)); return 0

    # 2) still over threshold -> grow. Compute clamped grow.
    grow_g = max(args.min_grow_g, min(args.max_grow_g, round((size_g or 20) * args.grow_pct / 100.0)))
    out["grow_g"] = grow_g

    # rate cap
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
        recent = conn.execute("SELECT COUNT(*) FROM disk_grow_log WHERE vmid=? AND outcome='grown' "
                              "AND grown_at > datetime('now', ?)", (vmid, f"-{args.rate_cap_days} day")).fetchone()[0]
        conn.close()
    except Exception:  # noqa: BLE001
        recent = 0
    if recent > 0:
        notify(f"⚠ disk-autogrow ESCALATE {args.host}: still {pct_after_clean}% after cleanup but already "
               f"grown within {args.rate_cap_days}d ({recent}x) — likely a real leak, NOT growing again. Investigate.")
        _log(hostname=args.host, vmid=vmid, node=node, guest_type=gtype, disk_key=disk_key, storage=storage,
             before_size_g=size_g or 0, fs_pct_before=pct0 or -1, fs_pct_after=pct_after_clean,
             outcome="escalated-rate-cap")
        out["result"] = "escalated-rate-cap"; print(json.dumps(out)); return 0

    # pool floor + rpool health
    pf = pool_free_pct(node, storage, minus_g=grow_g)
    rp = rpool_healthy(node)
    out["pool_free_pct_after"] = round(pf, 1) if pf is not None else None
    out["rpool_healthy"] = rp
    if pf is None or pf < args.pool_floor_pct or rp is not True:
        notify(f"⚠ disk-autogrow REFUSED {args.host}: grow +{grow_g}G would leave pool {storage} at "
               f"{('%.1f' % pf) if pf is not None else '?'}% free (floor {args.pool_floor_pct}%) / rpool_ok={rp}. "
               f"Escalating instead of trading guest pressure for pool pressure.")
        _log(hostname=args.host, vmid=vmid, node=node, guest_type=gtype, disk_key=disk_key, storage=storage,
             before_size_g=size_g or 0, grow_g=grow_g, fs_pct_before=pct0 or -1, fs_pct_after=pct_after_clean,
             pool_free_pct_after=pf if pf is not None else -1, outcome="refused-pool-floor")
        out["result"] = "refused-pool-floor"; print(json.dumps(out)); return 0

    if not execute:
        out["result"] = "would-grow"
        print(json.dumps(out)); return 0

    # 3) EXECUTE grow
    if gtype == "lxc":
        rc, so, se = _node_cmd(node, f"pct resize {vmid} {disk_key} +{int(grow_g)}G", timeout=90)
        grow_ok = rc == 0
        fs_note = "pct-resize-onestep"
    else:
        rc, so, se = _node_cmd(node, f"qm resize {vmid} {disk_key} +{int(grow_g)}G", timeout=90)
        grow_ok = rc == 0
        fs_note = "qm-resize-block-only"
        if grow_ok:
            # guest fs-grow: probe layout, grow partition + fs online. Escalate on ambiguity.
            rcp, root_src, _ = _guest_cmd(args.host, "findmnt -no SOURCE / 2>/dev/null")
            if rcp == 0 and root_src:
                dev = root_src.strip()
                pm = re.match(r"(/dev/[a-z]+)(\d+)$", dev)
                if pm:
                    _guest_cmd(args.host, f"growpart {pm.group(1)} {pm.group(2)} 2>/dev/null; true", timeout=40)
                rcf, fstype, _ = _guest_cmd(args.host, "findmnt -no FSTYPE / 2>/dev/null")
                if fstype.strip() in ("ext4", "ext3", "ext2"):
                    rcg, _, _ = _guest_cmd(args.host, f"resize2fs {dev} 2>/dev/null; true", timeout=60)
                    fs_note = "qm-resize+resize2fs"
                elif fstype.strip() == "xfs":
                    rcg, _, _ = _guest_cmd(args.host, "xfs_growfs / 2>/dev/null; true", timeout=60)
                    fs_note = "qm-resize+xfs_growfs"
                else:
                    fs_note = f"qm-resize+UNGROWN-fs:{fstype.strip()[:12]}"
            else:
                fs_note = "qm-resize+guest-unreachable-for-fsgrow"

    time.sleep(3)
    pct1 = guest_df_pct(node, vmid, gtype, args.host)
    dc2 = disk_config(node, vmid, gtype)
    after_size = dc2[2] if dc2 else None
    out.update({"grow_ok": grow_ok, "fs_step": fs_note, "fs_pct_after": pct1, "after_size_g": after_size})
    outcome = "grown" if grow_ok else "grow-command-failed"
    _log(hostname=args.host, vmid=vmid, node=node, guest_type=gtype, disk_key=disk_key, storage=storage,
         before_size_g=size_g or 0, grow_g=grow_g, after_size_g=after_size or 0,
         fs_pct_before=pct0 or -1, fs_pct_after=pct1 if pct1 is not None else -1,
         pool_free_pct_after=pf, outcome=outcome, detail=fs_note)
    _dbg("disk_grow", host=args.host, vmid=vmid, outcome=outcome, grow_g=grow_g, fs=fs_note,
         pct_before=pct0, pct_after=pct1)
    notify(f"💽 disk-autogrow {args.host}: {pct0}%→{pct1 if pct1 is not None else '?'}% root — grew {disk_key} "
           f"+{int(grow_g)}G ({fs_note}); pool {storage} {('%.1f' % pf)}% free after. [{outcome}]")
    out["result"] = outcome
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
