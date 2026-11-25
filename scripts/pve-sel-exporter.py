#!/usr/bin/env python3
"""
pve-sel-exporter.py — in-band BMC System Event Log (SEL) exporter for a PVE host, read through
/dev/ipmi0 with the Linux ipmi_devintf ioctls. No packages: PVE hosts get no installs, so no
ipmitool/freeipmi (IFRNLLEI01PRD-2992, postmortem item 13).

Why: on 2026-11-07 06:25:37 UTC nlpve04 (ASRock GENOAD8X-2T/BCM) halted on a PCI SERR from
its BCM57416 10 G NIC (bus 05, both bond0 legs). Firmware-first error handling left no kernel
trace; the SEL was the only evidence. This exporter makes a recurrence visible.

READ-ONLY toward the BMC: Get SEL Info / Get SEL Time / Reserve SEL / Get SEL Entry only. It never
clears the SEL or sets the BMC clock.

Deployed on nlpve04 (root, systemd timer every 5 min):
  /usr/local/bin/pve-sel-exporter.py
  /etc/systemd/system/pve-sel-exporter.{service,timer}   (scripts/systemd/ in claude-gateway)
  -> /var/lib/prometheus/node-exporter/pve_sel.prom      (node_exporter :9100 textfile collector,
                                                          NL Prometheus job pve-node-exporter)
  state /var/lib/pve-sel-exporter/state.json             (first-seen time per SEL record)

Metrics: pve_sel_read_ok, pve_sel_entries, pve_sel_free_bytes, pve_sel_records{sensor_type},
pve_sel_critical_events{type}, pve_sel_last_critical_event_timestamp_seconds{type},
pve_sel_last_critical_seen_timestamp_seconds{type}, pve_sel_bmc_clock_offset_seconds,
pve_sel_last_run_timestamp_seconds, pve_sel_exporter_duration_seconds.
Critical types: pci_serr, pci_perr, critical_interrupt (other critical-interrupt offsets: NMIs,
bus errors), processor (IERR, thermal trip, FRB, config error, uncorrectable CPU-complex error,
machine check), power_unit (power down by fault, AC lost, power unit failure), memory
(uncorrectable ECC, parity, scrub failure, critical over-temperature). Assertions only.

Timestamps. The BMC SEL clock is not UTC-stable: at every host boot the BIOS logs a clock-sync
pair (System Event offset 5, data2 bit 7 = 0 before / 1 after) that sets it to UTC, and later the
BMC drifts to its own offset (+2 h on nlpve04, measured). After an AC loss the BMC RTC
restarts at 2000-01-01 or 2022-01-01. So:
  * event timestamp ("_event_"): the raw SEL time after the last clock sync; a raw time in the
    future of the current segment is shifted by the measured BMC offset; a record stamped before
    the RTC was set gets the next clock-sync time as an upper bound; a record first seen within
    one run of its event uses the current offset. Best effort, for humans.
  * first-seen timestamp ("_seen_"): host clock when this exporter first saw the record. Clock-
    independent; this is what PVEBMCCriticalEvent keys on. The first run (no state file) seeds
    every existing record with its event time, so deploying never fires the alert.

  pve-sel-exporter.py                 # read, update state, write the .prom
  pve-sel-exporter.py --stdout        # read, print metrics, do not touch the state or the .prom
  pve-sel-exporter.py --dump          # print the raw records as JSON (fixtures)
  pve-sel-exporter.py --from-json F   # process a --dump file instead of /dev/ipmi0 (tests)
"""
import argparse
import json
import os
import struct
import sys
import tempfile
import time

TEXTFILE_DIR = os.environ.get("PVE_SEL_TEXTFILE_DIR", "/var/lib/prometheus/node-exporter")
STATE_FILE = os.environ.get("PVE_SEL_STATE_FILE", "/var/lib/pve-sel-exporter/state.json")
IPMI_DEV = os.environ.get("PVE_SEL_IPMI_DEV", "/dev/ipmi0")
PLAUSIBLE_MIN = VMID_REDACTED0        # 2024-01-01: anything older is a reset BMC RTC, not a real time
FUTURE_SLACK = 300
FRESH_SLACK = 900

SENSOR_TYPES = {
    0x01: "temperature", 0x02: "voltage", 0x03: "current", 0x04: "fan", 0x05: "chassis_intrusion",
    0x06: "security_violation", 0x07: "processor", 0x08: "power_supply", 0x09: "power_unit",
    0x0c: "memory", 0x0d: "drive_slot", 0x0f: "post_progress", 0x10: "event_logging",
    0x11: "watchdog1", 0x12: "system_event", 0x13: "critical_interrupt", 0x14: "button_switch",
    0x19: "chipset", 0x1d: "system_boot", 0x1e: "boot_error", 0x1f: "os_boot", 0x20: "os_stop",
    0x21: "slot_connector", 0x22: "acpi_power_state", 0x23: "watchdog2", 0x24: "platform_alert",
    0x28: "management_subsystem", 0x2b: "version_change",
}
CRITICAL_TYPES = ("pci_serr", "pci_perr", "critical_interrupt", "processor", "power_unit", "memory")


def critical_type(sensor_type, offset):
    """Map an ASSERTION (sensor type, event offset) to a critical type, or None."""
    if sensor_type == 0x13:                       # Critical Interrupt
        if offset == 5:
            return "pci_serr"
        if offset == 4:
            return "pci_perr"
        if offset != 7:                           # 7 = bus correctable error: not critical
            return "critical_interrupt"
    if sensor_type == 0x07 and offset in (0, 1, 2, 3, 4, 5, 6, 0x0b):
        return "processor"
    if sensor_type == 0x09 and offset in (2, 3, 4, 5, 6, 7):
        return "power_unit"
    if sensor_type == 0x0c and offset in (1, 2, 3, 0x0a):
        return "memory"
    return None


# --------------------------------------------------------------------------- /dev/ipmi0

def _ipmi_open():
    import ctypes
    import fcntl
    import select

    class ipmi_msg(ctypes.Structure):
        _fields_ = [("netfn", ctypes.c_ubyte), ("cmd", ctypes.c_ubyte),
                    ("data_len", ctypes.c_ushort), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    class ipmi_req(ctypes.Structure):
        _fields_ = [("addr", ctypes.c_void_p), ("addr_len", ctypes.c_uint),
                    ("msgid", ctypes.c_long), ("msg", ipmi_msg)]

    class ipmi_recv(ctypes.Structure):
        _fields_ = [("recv_type", ctypes.c_int), ("addr", ctypes.c_void_p), ("addr_len", ctypes.c_uint),
                    ("msgid", ctypes.c_long), ("msg", ipmi_msg)]

    class si_addr(ctypes.Structure):
        _fields_ = [("addr_type", ctypes.c_int), ("channel", ctypes.c_short), ("lun", ctypes.c_ubyte)]

    def ioc(d, t, nr, size):
        return (d << 30) | (size << 16) | (ord(t) << 8) | nr

    SEND = ioc(2, 'i', 13, ctypes.sizeof(ipmi_req))       # IPMICTL_SEND_COMMAND
    RECV = ioc(3, 'i', 11, ctypes.sizeof(ipmi_recv))      # IPMICTL_RECEIVE_MSG_TRUNC
    fd = os.open(IPMI_DEV, os.O_RDWR)
    state = {"msgid": 0}

    def cmd(netfn, c, data=b""):
        addr = si_addr(0x0c, 0x0f, 0)                     # system interface, BMC channel
        buf = (ctypes.c_ubyte * max(1, len(data))).from_buffer_copy(data or b"\0")
        state["msgid"] += 1
        mid = state["msgid"]
        req = ipmi_req(ctypes.cast(ctypes.pointer(addr), ctypes.c_void_p), ctypes.sizeof(addr), mid,
                       ipmi_msg(netfn, c, len(data), buf))
        fcntl.ioctl(fd, SEND, req)
        deadline = time.time() + 5
        while True:
            left = deadline - time.time()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise TimeoutError(f"no IPMI response to netfn {netfn:#x} cmd {c:#x}")
            raddr = si_addr()
            rbuf = (ctypes.c_ubyte * 1024)()
            rv = ipmi_recv(0, ctypes.cast(ctypes.pointer(raddr), ctypes.c_void_p), ctypes.sizeof(raddr), 0,
                           ipmi_msg(0, 0, 1024, rbuf))
            fcntl.ioctl(fd, RECV, rv)
            if rv.msgid == mid:
                return bytes(rbuf[:rv.msg.data_len])

    return fd, cmd


def read_sel():
    """Return {'info': {...}, 'bmc_time': int|None, 'host_time': int, 'records': [hex16, ...]}."""
    fd, cmd = _ipmi_open()
    try:
        info = cmd(0x0a, 0x40)                            # Get SEL Info
        if not info or info[0] != 0:
            raise RuntimeError(f"Get SEL Info completion code {info[0] if info else None}")
        sel_info = {"version": info[1], "entries": struct.unpack("<H", info[2:4])[0],
                    "free_bytes": struct.unpack("<H", info[4:6])[0]}
        t = cmd(0x0a, 0x48)                               # Get SEL Time
        bmc_time = struct.unpack("<I", t[1:5])[0] if t and t[0] == 0 and len(t) >= 5 else None
        host_time = int(time.time())
        for attempt in range(3):
            res = cmd(0x0a, 0x42)                         # Reserve SEL (cancelled if the SEL changes)
            rid = res[1:3] if res and res[0] == 0 else b"\0\0"
            records, nxt, cancelled = [], b"\0\0", False
            for _ in range(4096):
                r = cmd(0x0a, 0x43, rid + nxt + b"\x00\xff")   # Get SEL Entry, whole record
                if not r:
                    raise RuntimeError("empty Get SEL Entry response")
                if r[0] == 0xc5:                          # reservation cancelled: SEL changed mid-read
                    cancelled = True
                    break
                if r[0] == 0xcb and not records:          # requested record not present = empty SEL
                    break
                if r[0] != 0:
                    raise RuntimeError(f"Get SEL Entry completion code {r[0]:#x}")
                nxt = r[1:3]
                records.append(r[3:19].hex())
                if nxt == b"\xff\xff":
                    break
            if not cancelled:
                return {"info": sel_info, "bmc_time": bmc_time, "host_time": host_time, "records": records}
        raise RuntimeError("SEL reservation cancelled 3 times in a row")
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- processing

def parse_record(hexrec):
    b = bytes.fromhex(hexrec)
    rec = {"key": hexrec, "id": struct.unpack("<H", b[0:2])[0], "rtype": b[2], "raw": None,
           "sensor_type": None, "offset": None, "assert": None, "data": b[13:16].hex() if len(b) >= 16 else ""}
    if b[2] == 0x02 or 0xc0 <= b[2] <= 0xdf:              # standard or OEM timestamped
        rec["raw"] = struct.unpack("<I", b[3:7])[0]
    if b[2] == 0x02 and len(b) >= 16:
        rec["sensor_type"] = b[10]
        rec["assert"] = not (b[12] & 0x80)
        rec["offset"] = b[13] & 0x0f
        rec["data2"] = b[14]
    return rec


def is_clock_sync_after(r):
    return (r["sensor_type"] == 0x12 and r["offset"] == 5 and r.get("data2", 0) & 0x80
            and r["raw"] is not None and r["raw"] >= PLAUSIBLE_MIN)


def calibrate(records, bmc_offset, now):
    """Best-effort UTC event time per record (sets r['cal'], r['cal_how'])."""
    pending = []
    last_sync_idx = -1
    for i, r in enumerate(records):
        raw = r["raw"]
        if is_clock_sync_after(r):
            for p in pending:
                p["cal"], p["cal_how"] = raw, "next-clock-sync-upper-bound"
            pending = []
            last_sync_idx = i
        if raw is None:
            r["cal"], r["cal_how"] = None, "no-timestamp"
        elif raw < PLAUSIBLE_MIN:
            r["cal"], r["cal_how"] = None, "bmc-rtc-unset"
            pending.append(r)
        else:
            r["cal"], r["cal_how"] = raw, "raw-after-clock-sync"
    if bmc_offset:
        for r in records[last_sync_idx + 1:]:
            if r["cal"] is not None and r["cal_how"] == "raw-after-clock-sync" and r["cal"] > now + FUTURE_SLACK:
                r["cal"], r["cal_how"] = r["cal"] - bmc_offset, "current-bmc-offset"
    return records


def load_state(path):
    try:
        with open(path) as fh:
            st = json.load(fh)
        if isinstance(st, dict) and isinstance(st.get("seen"), dict):
            return st
    except (OSError, ValueError):
        pass
    return None


def process(dump, state, now=None):
    """Pure core: (dump, state|None, now) -> (metrics dict, new state). Used live and by tests."""
    now = int(now if now is not None else dump["host_time"])
    bmc_offset = (dump["bmc_time"] - dump["host_time"]) if dump.get("bmc_time") else 0
    records = calibrate([parse_record(h) for h in dump["records"]], bmc_offset, now)
    baseline = state is None
    old = (state or {}).get("seen", {})
    last_run = (state or {}).get("last_run", now)
    seen_map = {}
    for r in records:
        prev = old.get(r["key"])
        if prev is not None:
            r["seen"], r["cal"] = prev.get("seen", 0), prev.get("cal", r["cal"])
        elif baseline:                                    # deploy/state loss: already known
            r["seen"] = min(r["cal"] or 0, now)
        else:
            r["seen"] = now
            if r["raw"] is not None and r["raw"] >= PLAUSIBLE_MIN:
                cand = r["raw"] - bmc_offset
                if last_run - FRESH_SLACK <= cand <= now + FUTURE_SLACK:
                    r["cal"], r["cal_how"] = cand, "fresh-current-bmc-offset"
            if r["cal"] is None:
                r["cal"], r["cal_how"] = now, "first-seen"
        seen_map[r["key"]] = {"seen": r["seen"], "cal": r["cal"]}

    by_sensor, crit_count = {}, {t: 0 for t in CRITICAL_TYPES}
    crit_event, crit_seen, crit_last = ({t: 0 for t in CRITICAL_TYPES} for _ in range(3))
    for r in records:
        st = r["sensor_type"]
        name = "oem" if st is None else SENSOR_TYPES.get(st, f"type_{st:#04x}")
        by_sensor[name] = by_sensor.get(name, 0) + 1
        if not r["assert"]:
            continue
        ct = critical_type(st, r["offset"])
        if ct:
            crit_count[ct] += 1
            crit_event[ct] = max(crit_event[ct], r["cal"] or 0)
            if r["seen"] >= crit_seen[ct]:
                crit_seen[ct] = r["seen"]
                crit_last[ct] = r
    metrics = {"entries": dump["info"]["entries"], "free_bytes": dump["info"]["free_bytes"],
               "by_sensor": by_sensor, "crit_count": crit_count, "crit_event": crit_event,
               "crit_seen": crit_seen, "bmc_offset": bmc_offset, "baseline": baseline, "now": now,
               "crit_last": {t: (r["id"], r["data"], r["cal_how"]) for t, r in crit_last.items() if r}}
    new_state = {"version": 1, "baseline": (state or {}).get("baseline", now), "last_run": now, "seen": seen_map}
    return metrics, new_state


def render(m, duration):
    out = []

    def head(name, help_):
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} gauge")
    head("pve_sel_read_ok", "1 if the BMC SEL was read in full over /dev/ipmi0 on the last run")
    out.append("pve_sel_read_ok 1")
    head("pve_sel_entries", "entries in the BMC SEL (Get SEL Info)")
    out.append(f"pve_sel_entries {m['entries']}")
    head("pve_sel_free_bytes", "free SEL space in bytes; a full SEL drops new events")
    out.append(f"pve_sel_free_bytes {m['free_bytes']}")
    head("pve_sel_records", "SEL records by IPMI sensor type")
    for k in sorted(m["by_sensor"]):
        out.append(f'pve_sel_records{{sensor_type="{k}"}} {m["by_sensor"][k]}')
    head("pve_sel_critical_events", "critical SEL assertions by type")
    for t in CRITICAL_TYPES:
        out.append(f'pve_sel_critical_events{{type="{t}"}} {m["crit_count"][t]}')
    head("pve_sel_last_critical_event_timestamp_seconds",
         "best-effort UTC time of the newest critical SEL assertion of this type (0 = none)")
    for t in CRITICAL_TYPES:
        out.append(f'pve_sel_last_critical_event_timestamp_seconds{{type="{t}"}} {m["crit_event"][t]}')
    head("pve_sel_last_critical_seen_timestamp_seconds",
         "host time this exporter first saw the newest critical SEL assertion of this type (0 = none)")
    for t in CRITICAL_TYPES:
        out.append(f'pve_sel_last_critical_seen_timestamp_seconds{{type="{t}"}} {m["crit_seen"][t]}')
    head("pve_sel_bmc_clock_offset_seconds", "BMC SEL clock minus host clock")
    out.append(f"pve_sel_bmc_clock_offset_seconds {m['bmc_offset']}")
    head("pve_sel_exporter_duration_seconds", "wall time of the last run")
    out.append(f"pve_sel_exporter_duration_seconds {duration:.3f}")
    head("pve_sel_last_run_timestamp_seconds", "unix time of the last run (success or failure)")
    out.append(f"pve_sel_last_run_timestamp_seconds {m['now']}")
    return "\n".join(out) + "\n"


def render_failure(now, err):
    return ("# HELP pve_sel_read_ok 1 if the BMC SEL was read in full over /dev/ipmi0 on the last run\n"
            "# TYPE pve_sel_read_ok gauge\npve_sel_read_ok 0\n"
            "# HELP pve_sel_last_run_timestamp_seconds unix time of the last run (success or failure)\n"
            f"# TYPE pve_sel_last_run_timestamp_seconds gauge\npve_sel_last_run_timestamp_seconds {int(now)}\n")


def write_atomic(path, text, mode=0o644):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser(description="in-band BMC SEL exporter (read-only)")
    ap.add_argument("--stdout", action="store_true", help="print metrics; do not touch the state or the .prom")
    ap.add_argument("--dump", action="store_true", help="print the raw SEL as JSON")
    ap.add_argument("--from-json", metavar="FILE", help="process a --dump file instead of the BMC")
    ap.add_argument("--now", type=int, help="override the current time (tests)")
    args = ap.parse_args()
    started = time.time()
    prom = os.path.join(TEXTFILE_DIR, "pve_sel.prom")
    try:
        if args.from_json:
            with open(args.from_json) as fh:
                dump = json.load(fh)
        else:
            dump = read_sel()
    except Exception as e:                               # noqa: BLE001 - any failure = read_ok 0
        print(f"pve-sel-exporter: SEL read failed: {e}", file=sys.stderr)
        if not args.stdout and not args.dump:
            write_atomic(prom, render_failure(time.time(), e))
        return 1
    if args.dump:
        json.dump(dump, sys.stdout, indent=1)
        print()
        return 0
    state = load_state(STATE_FILE)
    metrics, new_state = process(dump, state, now=args.now)
    text = render(metrics, time.time() - started)
    if args.stdout:
        sys.stdout.write(text)
        for t, (rid, data, how) in sorted(metrics["crit_last"].items()):
            print(f"# newest {t}: record {rid:#06x} data {data} event-time via {how}", file=sys.stderr)
        return 0
    write_atomic(STATE_FILE, json.dumps(new_state), mode=0o600)
    write_atomic(prom, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
