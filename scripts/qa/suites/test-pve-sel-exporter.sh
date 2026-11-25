#!/bin/bash
# test-pve-sel-exporter.sh — scripts/pve-sel-exporter.py against the REAL nlpve04 SEL of
# 2026-11-07 (scripts/qa/fixtures/pve04-sel-20261107.json, records 0x30/0x31 = the 06:25:37 UTC
# PCI SERR on bus 05) plus synthetic records appended to it (IFRNLLEI01PRD-2992, item 13).
#
# Hermetic: --from-json, state + textfile dirs in mktemp; /dev/ipmi0 is never opened.
# QA_SUITE_TIMEOUT: 60
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$REPO_ROOT/scripts/qa/lib/assert.sh"
export QA_SUITE_NAME="test-pve-sel-exporter"

EXP="$REPO_ROOT/scripts/pve-sel-exporter.py"
FIX="$REPO_ROOT/scripts/qa/fixtures/pve04-sel-20261107.json"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PVE_SEL_TEXTFILE_DIR="$TMP/prom" PVE_SEL_STATE_FILE="$TMP/state/state.json" PVE_SEL_IPMI_DEV="$TMP/no-such-ipmi"
SERR_TS=VMID_REDACTED7   # 2026-11-07 06:25:37 UTC

_py() { python3 - "$@" <<PYEOF
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("sel", "$EXP")
sel = importlib.util.module_from_spec(spec); spec.loader.exec_module(sel)
FIX = json.load(open("$FIX"))
def rec(rid, ts, st, d1, d2=0, d3=0, deassert=False):
    import struct
    b = struct.pack("<HBI", rid, 0x02, ts) + bytes([0x20, 0x00, 0x04, st, 0x00, 0x6f | (0x80 if deassert else 0), d1, d2, d3])
    return b.hex()
$(cat)
PYEOF
}

# ── T1 baseline on the real SEL: the SERR is found, dated, and seeded (no alert on deploy) ──
start_test "baseline_real_pve04_sel"
out=$(echo '
m, st = sel.process(FIX, None)
print("serr", m["crit_count"]["pci_serr"], m["crit_event"]["pci_serr"], m["crit_seen"]["pci_serr"])
print("others", sum(v for k, v in m["crit_count"].items() if k != "pci_serr"))
print("offset", m["bmc_offset"], "baseline", m["baseline"], "entries", m["entries"], "keys", len(st["seen"]))
' | _py)
assert_contains "$out" "serr 2 $SERR_TS $SERR_TS" "2 SERR records, event 06:25:37 UTC, seen seeded = event time"
assert_contains "$out" "others 0" "the voltage/clock-sync records are not critical"
assert_contains "$out" "offset 7200 baseline True entries 52 keys 52" "BMC +2h measured, all 52 records in state"
end_test

# ── T2 classification table ─────────────────────────────────────────────────────────
start_test "critical_type_mapping"
out=$(echo '
c = sel.critical_type
print(c(0x13,5), c(0x13,4), c(0x13,9), c(0x13,7), c(0x07,0x0b), c(0x07,0x0c), c(0x09,4), c(0x09,0), c(0x0c,1), c(0x0c,0), c(0x02,9), c(0x12,5))
' | _py)
assert_eq "pci_serr pci_perr critical_interrupt None processor None power_unit None memory None None None" "$out" "type map"
end_test

# ── T3 a FRESH SERR on a running host (BMC clock +2h) -> seen = now, event = true UTC ───
start_test "fresh_event_fires_seen_now"
out=$(echo '
m, st = sel.process(FIX, None)
now = FIX["host_time"] + 300
d = dict(FIX); d["host_time"] = now; d["bmc_time"] = now + 7200
d["records"] = FIX["records"] + [rec(0x35, now - 60 + 7200, 0x13, 0xa5, 0x05, 0x00)]
m2, st2 = sel.process(d, st, now=now)
print("count", m2["crit_count"]["pci_serr"], "seen_age", now - m2["crit_seen"]["pci_serr"], "event_age", now - m2["crit_event"]["pci_serr"])
m3, _ = sel.process(d, st2, now=now + 600)
print("rerun_seen_age", now + 600 - m3["crit_seen"]["pci_serr"])
' | _py)
assert_contains "$out" "count 3 seen_age 0 event_age 60" "new SERR seen now; event time corrected by the +2h BMC offset"
assert_contains "$out" "rerun_seen_age 600" "first-seen is stable across runs (alert window closes)"
end_test

# ── T4 an event logged while the host was hung (the 2026-11-07 shape) -> seen at reboot ──
start_test "event_during_hang_seen_after_reboot"
out=$(echo '
m, st = sel.process(FIX, None)
st["last_run"] = FIX["host_time"]
now = FIX["host_time"] + 4 * 3600          # host back 4 h later
d = dict(FIX); d["host_time"] = now; d["bmc_time"] = now
d["records"] = FIX["records"] + [rec(0x35, FIX["host_time"] + 600, 0x07, 0x0b)]
m2, _ = sel.process(d, st, now=now)
print("proc", m2["crit_count"]["processor"], "seen_age", now - m2["crit_seen"]["processor"], "event", m2["crit_event"]["processor"] - FIX["host_time"])
' | _py)
assert_contains "$out" "proc 1 seen_age 0 event 600" "MCE logged during the hang: alert at first sight, event time kept"
end_test

# ── T5 RTC-unset record before a clock sync gets the sync time as upper bound ──────────
start_test "bmc_rtc_unset_upper_bound"
out=$(echo '
recs = [rec(1, 946684807, 0x09, 0x04), rec(2, VMID_REDACTED4, 0x12, 0x05, 0x00, 0xff), rec(3, VMID_REDACTED0, 0x12, 0x05, 0x80, 0xff)]
r = sel.calibrate([sel.parse_record(h) for h in recs], 0, VMID_REDACTED0)
print(r[0]["cal"], r[0]["cal_how"], r[2]["cal_how"])
' | _py)
assert_eq "VMID_REDACTED0 next-clock-sync-upper-bound raw-after-clock-sync" "$out" "AC-lost record dated by the next clock sync"
end_test

# ── T6 CLI end to end: .prom + state written atomically, read_ok 0 on a missing device ──
start_test "cli_from_json_and_failure_path"
python3 "$EXP" --from-json "$FIX" >/dev/null 2>&1
prom="$TMP/prom/pve_sel.prom"
body=$(cat "$prom" 2>/dev/null)
assert_contains "$body" "pve_sel_read_ok 1" "read ok"
assert_contains "$body" "pve_sel_last_critical_event_timestamp_seconds{type=\"pci_serr\"} $SERR_TS" "SERR event timestamp exported"
assert_contains "$body" "pve_sel_last_critical_seen_timestamp_seconds{type=\"pci_serr\"} $SERR_TS" "seen seeded"
assert_contains "$body" 'pve_sel_critical_events{type="pci_serr"} 2' "count"
assert_file_exists "$TMP/state/state.json" "state written"
python3 "$EXP" >/dev/null 2>&1; rc=$?
assert_eq 1 "$rc" "missing /dev/ipmi0 exits 1"
assert_contains "$(cat "$prom")" "pve_sel_read_ok 0" "failure exported as read_ok 0"
if ls "$TMP/prom"/.pve_sel.* >/dev/null 2>&1; then fail_test "temp file left behind"; fi
end_test

# ── T7 SEL cleared: counts drop to 0 and the state is pruned ─────────────────────────
start_test "sel_cleared_prunes_state"
out=$(echo '
m, st = sel.process(FIX, None)
d = dict(FIX); d["records"] = []; d["info"] = {"version": 81, "entries": 0, "free_bytes": 65535}
m2, st2 = sel.process(d, st, now=FIX["host_time"] + 300)
print(m2["crit_count"]["pci_serr"], m2["crit_seen"]["pci_serr"], len(st2["seen"]))
' | _py)
assert_eq "0 0 0" "$out" "cleared SEL"
end_test
