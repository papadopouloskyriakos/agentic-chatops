# Runbook — reviving a vanished NVMe with a cold AC drain (PVE hosts)

**Status:** PROVEN 2026-08-27 on `gr-pve01` — recovered `S7NUNE0X619155` (PM9F1 Samsung 2048GB) that had been absent from the PCIe bus for 2 days. IFRGRSKG01PRD-312.

---

## When to use this

Either of these, where the host has only had **warm reboots** since:

**(a) The drive vanished** — gone from `nvme list`, `lsblk`, `/sys/class/nvme`, and often from `lspci` entirely.

**(b) The drive is still enumerated but is stuck in a power state** (added 2026-09-16, nl-pve01, IFRNLLEI01PRD-2853):

```
nvme 0000:59:00.0: Unable to change power state from D3cold to D0, device inaccessible
I/O error, dev nvme0n1, sector ... op 0x1:(WRITE)
```

⭐ **The same cure applies** — a controller wedged in D3cold cannot be resumed by PERST#, only by a true POR. Variant (b) is more dangerous because it can hit **several drives at once**: on nl-pve01 both members of the rpool mirror went 13 s apart, so the pool died even though it was redundant. Redundancy does not protect against a *system-level* power-management event.

### ⭐⭐ Recognising variant (b) when you cannot log in

The host becomes a **RAM-zombie** and looks like a network fault:

| Signal | Reads as |
|---|---|
| ICMP | **UP, normal latency** (kernel + NIC are in RAM) |
| corosync | still a **voting member** |
| SSH | **dies at banner exchange** (needs disk) |
| SNMP | dead (LibreNMS: "responds to ICMP but not SNMP") |
| `pvesh get /nodes` from a peer | `status: unknown` |
| Running guests | still answering **out of page cache**, failing every write |

⛔ **Do not mistake this for the pmxcfs-wedge class** (`filename_create` D-state, load 100+, CPU idle) — the remedy there is `systemctl restart pve-cluster`, which is useless here and requires a shell you do not have. **Get the OOB console early**; on 2026-09-16 an AMT screenshot was the only thing that distinguished the two, and the wrong call was made first.

### ⭐ The rule this runbook exists to correct

> **Absence from PCIe enumeration is NOT proof of hardware death.**

On 2026-08-27 the drive presented *no root port with a link at all*, which was read as a dead PMIC or physically-removed hardware; revival odds were put at ~25%. That inference was wrong. **A hung NVMe controller can fail to train the link and still be fully recoverable.** Do the cold drain before concluding a drive is dead, ordering a replacement, or planning a site visit.

### Why a warm reboot cannot do it

A warm reboot asserts PERST#, which resets the PCIe **link** — not the SSD controller's internal state. The M.2 3.3 V rail stays powered, so a wedged controller never gets a power-on reset. Only removing AC (and letting the rails drain) forces a true POR. This is already noted in [`amt-headless-console.md`](amt-headless-console.md) §4.

⚠ **S5 is not sufficient either** — at least not on the Minisforum MS-01. `shutdown -h now` did not revive the drive on the 08-25 recovery; only full AC removal did.

### Signature that predicts a good outcome

- SMART was **clean immediately before the disappearance** (no wear, no media errors, no precursor). Check LibreNMS RRD history — see below.
- The drive was **mostly idle** (deep-idle/APST wedges are the classic case).
- It disappeared **in flight** rather than degrading.

Against it: a drive with rising reallocated sectors, media errors, or a wear-out trajectory is a genuine failure and this will not help.

---

## 0. Identify a disk that is already gone

The host has no record of it. **LibreNMS does** — the SMART app keys its RRDs by serial (`useSN=1`), so a dead disk's history survives its disappearance.

```bash
# on the site's LibreNMS host (gr-nms01 = CT 201020705 on gr-pve01)
ls /opt/librenms/rrd/<pvehost>/app-smart-*-*.rrd     # one file per serial, incl. the vanished one
rrdtool lastupdate app-smart-<appid>-<SERIAL>.rrd    # its FINAL readings
rrdtool first     app-smart_id9-<appid>-<SERIAL>.rrd # when LibreNMS first saw it
rrdtool fetch     app-smart_id9-<appid>-<SERIAL>.rrd AVERAGE -s -200d -r 86400   # POH trajectory
```

Useful DS names: `id9` = power-on hours · `id194` = temperature · `id231` = life-left percentage.

⭐ **`power_on_hours` frozen at the pre-death value after revival is proof the drive was genuinely dead** to the host, not silently running.

⚠ POH on an idle NVMe advances far slower than wall-clock (only *operational* hours count under APST). 4 h/day on a 24/7 host is normal for a near-idle drive — **not** evidence of failure.

---

## 1. Pre-flight — do not skip

```bash
# Both intersite legs healthy (this is the access lifeline for the whole window)
ssh root@<peer-pve> 'ping -c2 -W2 <NL-side-ip>'

# Quorum BEFORE you start; know your threshold
ssh root@<host> 'pvecm status | grep -E "Quorate|Total votes|Expected"'

# No chaos drill
ls ~/chaos-state/chaos-active.json 2>/dev/null && echo ABORT

# Not inside a backup window (GR: Thu 03:00) or Sunday 05:17 UTC
```

**Quorum maths matters.** With 6 expected votes the threshold is 4. If one node is already down by design, taking a second one down leaves you **exactly at quorum with zero margin** — any additional node or intersite loss makes the whole cluster inquorate. Never take both site nodes down at once.

**Alert suppression.** ⛔ If `~/gateway.maintenance` already exists and contains `"master_switch": true`, it is **owned by `gateway-master-switch.py`** — do **not** create, overwrite or `rm` it; that corrupts the ownership record `master-switch on` restores from. Suppression is already active in that state. Only write your own maintenance file if none exists, and then clear it with **both** `rm ~/gateway.maintenance` and `date +%s > ~/gateway.maintenance-ended` (the second is what arms the 15-min cooldown).

**⚠ nl-pve01 network (added 2026-09-19, IFRNLLEI01PRD-2871).** Its bond0 runs over OEM copper SFP-10G-T modules, and **every AC drain so far has killed one leg**: 09-16 Te1/1/3, then 09-19 Te1/1/4, which left the host with no network at all. Software resets do not bring them back (see the 2026-09-19 reference result). Before cutting, either have someone available to reseat the modules, or plan the [1 G fallback](#1-g-fallback-via-the-amt-port-nl-pve01).

**Pause the GR-touching cron jobs that are NOT maintenance-gated** (they error or lie through the window). Via `scripts/lib/cronicle.py` → `set_enabled(id, 0, sid)`:
`iscsi-orphan-detect.sh` · `check-asa-binding-drift.py` · `refresh-host-blast-radius.py` · `holistic-agentic-health.sh`

---

## 2. Confirm the PDU outlet — the trap that wastes a window

⛔ **Outlet names lie.** On 2026-08-06 an outlet labelled "DELL Precision 3680" was empty, and a "verified cold drain" through it was a **no-op**.

```bash
# read-only outlet listing (AOS v3.9.4 menu):
telnet <pdu-ip>  ->  1 Device Manager -> 2 Outlet Management -> 1 Outlet Control/Configuration
```

Guard your automation on the **live outlet name** before sending any action key, and stop if it does not match. ⛔ Python 3.13 removed `telnetlib` — use a raw socket with IAC refuse-all.

**Verified GR map (2026-08-27, creds `operator` + the shared AMT password):**

| PDU | Outlet | Device |
|---|---|---|
| `grpdu01` 10.0.X.X | 1-8 | ZTE ONT · Cisco C819 · **ASA 5508-X (gr-fw01)** · **CBS350 (gr-sw01)** · PoE→AP1041N · PiKVM · **DELL T110II (gr-pve02)** · FREE |
| `grpdu02` 10.0.X.X | 1 | **Cisco C1000-24T-4X-L (gr-sw02)** ⛔ GR L2 core / site SPOF |
| | **2** | **MINISFORUM MS-01 S1290 = gr-pve01** ← the target |

⛔ **Never option 9 (Master Control = all outlets).** ⛔ On `grpdu01`, outlets 3 and 4 are the ASA and gr-sw01 — cutting either removes your own path back to the PDU. Single console session only; concurrent telnet gets EOF at login.

**Verified NL map (2026-09-16, read live before the cut; `nlpdu01` = APC **AP7922**, 10.0.181.X, same creds):**

| Outlet | Device |
|---|---|
| 1 | Cisco Catalyst 3750X-48 = **nl-sw01** ⛔ NL L2 core |
| 2 | Cisco ASA 5508-X = **nl-fw01** ⛔ |
| 3 / 4 | Cisco ISR4321 · C819G-LTE |
| **5** | **MINISFORUM MS-01 S1290 = nl-pve01** ← the target |
| 6 / 10 | Synology DS1621+ · DS1513+ |
| 9 | "DELL Precision 3680" — **EMPTY, stale label** (the 2026-08-06 no-op) |
| **17** | **Master Control/Configuration** ⛔ never |

⛔ **Master Control is outlet 17 on the 16-outlet AP7922**, not 9 as on the 8-outlet GR AP7921 — the hazard index differs per model, so *read the live list*, never carry the number across.

⚠ **`nlamt01` (10.0.181.X) is fed by the SAME outlet 5 as nl-pve01.** Two consequences: AMT going dark **is** a valid proof-of-cut on this host (unlike the MS-01-in-S5 case), and there is **no out-of-band wake path while the outlet is off** — return depends entirely on board auto-resume, which nl-pve01 **is confirmed to do** (AMT back t+10 s, 2026-09-16).

⭐ **Tooling:** `scratchpad/pdu.py` + `outlet_action.py {off|on}` (raw socket, IAC refuse-all — ⛔ Python 3.13 dropped `telnetlib`). It **parses the option number out of the live menu** and **aborts unless the outlet screen matches a guard string**, so a renumbered or relabelled menu stops the run instead of switching the wrong outlet.

---

## 3. Execute

```
A. cordon k8s nodes on the host        # drain WILL hang if the cluster is unhealthy or has
                                       # nowhere to reschedule — cordon is the useful part,
                                       # abandon drain after ~2 min
B. graceful guest shutdown             # pct shutdown --timeout 60 / qm shutdown --timeout 120
                                       # --forceStop 1, in waves; DNS/IdM guests last
C. reboot the PEER node first          # hard gate: it must come back healthy before you take
                                       # the target down, or the site has no surviving node
D. shutdown -h now on the target
E. PDU outlet OFF  >= 5 min            # 30-60 s drains the rails; 5 min is free margin
F. PDU outlet ON
G. verify the disk BEFORE guests start
H. restore service
```

### Proof-of-cut, and its limitation

The intended proof is *"AMT stops answering"* (AMT is fed by the same outlet). ⚠ **On the MS-01 this does not work: AMT goes dark as soon as the host enters S5**, so it is already silent before you cut. Operator-confirmed expected behaviour, 2026-08-27.

Two consequences:
1. Your only pre-restore evidence is the PDU's own `State: OFF` plus the name-match guard.
2. **There is no remote wake path from S5** — AMT `PowerState=2` cannot reach a dark AMT. Return depends entirely on the board's **"restore on AC power loss"** BIOS setting, which is **not remotely readable**.

**gr-pve01 is confirmed to auto-resume on AC** (proven 2026-08-27: AMT back ~50 s after power-on, host pinging ~60 s, SSH at ~110 s). For any other host, confirm this before cutting, or accept that failure to resume means a physical visit. ⛔ There is no PiKVM fallback at GR — `grpikvm01` has been bricked since 2026-03-21 (IFRGRSKG01PRD-85).

---

## 4. Verify the disk — before guests start

⛔ Address by `by-id`/`by-uuid` only. **NVMe numbering is unstable across boots on this host** — after the 2026-08-27 revival the Samsung came back as `nvme0` and the Kingstons shifted to `nvme1`/`nvme2`, the reverse of before.

```bash
lspci | grep -ci non-volatile          # controller count — the headline answer
ls /sys/class/nvme/ ; nvme list
blkid | grep <known-fs-uuid>
ls -l /dev/disk/by-id/ | grep -i nvme | grep -v part
nvme smart-log /dev/nvmeN | grep -iE 'critical_warning|media_errors|num_err_log|percentage_used|power_on_hours'
dmesg -T | grep -iE 'nvme|AER|pcie bus error'
e2fsck -n /dev/nvmeNn1                 # READ-ONLY; note it skips journal recovery
```

---

## 5. ⛔ Do NOT re-trust the drive in the same window

A drive that wedged once **with no SMART precursor** can wedge again. Leave it exactly as the pre-window guards had it:

- `fstab` entries **commented**
- **swap NOT restored** — putting a host's *only* swap on a single non-redundant disk is what turned a disk failure into a whole-host SIGBUS crash in the first place
- PVE `dir:` storage left **`inactive`** via `is_mountpoint yes`

⭐ **`is_mountpoint yes` on every `dir:` storage backed by a separate disk is the standing rule** — without it, a missing disk turns into silent root-pool consumption (PVE stats the mountpoint through to the root pool and happily writes there).

Before trusting it: read-write `e2fsck` (to replay the journal), then a burn-in. Only then decide swap and backup-fleecing placement, as separate staged changes.

---

## 6. Restore checklist

```bash
# guests: onboot=1 auto-start via pve-guests. If they do not (half-init), use the API —
# pve-guests.service and pve-manager.service carry RefuseManualStart=true:
setsid nohup pvesh create /nodes/localhost/startall > /tmp/startall.log 2>&1 < /dev/null &

# half-init detector — compare against a healthy peer (~56 normal; ~17 means reboot again).
# systemctl is-system-running reports "running" with 0 failed units in this state and is worthless.
systemctl list-units --type=service --state=running --no-legend | wc -l
# ⛔ systemctl reboot FAILS with dbus down — use `shutdown -r now`
```

- **Guests that will NOT auto-return:** anything with `onboot` unset or `0`. Snapshot the running set *before* the window and diff after. (On gr-pve01, `gr-dmz01`/201121301 runs but is not onboot.)
- **`prometheus-node-exporter` will be dead** — it binds the mgmt IP and loses a boot race (IFRNLLEI01PRD-2807). `systemctl reset-failed && systemctl restart`, confirm `:9100` → 200.
- **Rebuild `/tmp/netmiko-venv`** on the site's claude host — tmpfs, dies every reboot (IFRNLLEI01PRD-2790).
- **Un-stack soft-anti-affinity workloads.** After a mass restart, `preferred` podAntiAffinity happily re-stacks replicas on one node — this has now bitten twice (2026-08-25 and 08-27, both times ingress-nginx). Delete one replica so it reschedules; diagnose by **requests**, not usage.
- Uncordon the k8s nodes; re-enable the paused Cronicle jobs; check for stale iSCSI sessions.

---

## Reference result (2026-08-27, gr-pve01)

| | |
|---|---|
| GR service outage | ~27 min (14:57 → 15:23:24Z) |
| Host downtime | ~10 min |
| Cut → restore | 15:09:51Z → 15:15:41Z (5 min drain) |
| AMT back / host ping / SSH | +50 s / +60 s / +110 s after power-on |
| Disk confirmed | 15:16:45Z, first boot |
| Guests | 36/36 back, 35/35 static IPs ping |
| Data loss | none |

Revived drive at first read: `critical_warning 0`, `media_errors 0`, `num_err_log_entries 0`, `percentage_used 0%`, `power_on_hours 953` (**unchanged from the reading at death**), ext4 `clean`, link `8.0 GT/s x2` (device caps at 16.0 GT/s x4 — check whether the slot is wired x2 by design before calling it degraded).


---

## Reference result (2026-09-16, nl-pve01) — variant (b), D3cold

| | |
|---|---|
| Failure | **BOTH** rpool mirror members inaccessible 13 s apart, 01:55:47Z |
| NL impact | 65 guests dark; several limped on page cache first |
| Host downtime | **~8 min** |
| Cut → restore | 02:26:55Z → 02:32:45Z (**5 min 35 s** drain) |
| AMT back / host ping / SSH | +10 s / +90 s / +90 s after power-on |
| Pool on return | `rpool ONLINE`, mirror intact, **0 read/write/cksum**, `No known data errors` |
| Data loss | **none** |
| Guests | 47 back (40 LXC + 7 QEMU); inventory reconciled exactly |

**Deviations from §3 that were correct here, and why:**
- **Step B (graceful guest shutdown) — impossible**, no shell. Acceptable: writes were *already* failing estate-wide, so nothing was left to flush, and ZFS CoW protects on-disk consistency. Proven out: every measurable guest fs came back `rw` and error-free.
- **Step C (reboot the peer first) — deliberately skipped.** That gate exists so a 2-node site is never left with zero survivors; NL already had nl-pve03 and nlpve04 healthy and serving, so rebooting a healthy peer would have been pure added risk. ⭐ Apply the gate to its *purpose*, not its letter.

⚠ **Quorum:** with nl-pve02 off by design, cutting nl-pve01 left the cluster at **exactly 4 votes against quorum 4 — zero margin** for ~6 minutes. It held, but any further node or intersite loss would have made the whole 6-node cluster inquorate. Know this number before you cut.

**Post-recovery residue (small, but expect it):** one service failed on a **stale pidfile** left by the hard cut (`oxidized.service`: `A server is already running` → systemd gave up after 10 retries). Sweep for `systemctl list-units --state=failed` inside guests afterwards — hard-cut pidfile/lockfile residue is the characteristic damage, not filesystem corruption.

⚠ **`/dev/nvme*` renumbered across the cold boot** (the Kingston became `nvme0n1`, reversing the prior order). ZFS was unaffected because the pool is keyed by `nvme-eui.*`; anything pinned to a device node or PCI path was not.

## Reference result (2026-09-17/18, nl-pve01) — variant (b), single leg; the drive came back SICK

- 18:53Z `7VS00YN2` @ 02:00.0 dropped alone (`controller is down; CSTS=0xffffffff` first, then the D3cold line — the message is the failed *recovery*, not the trigger). Host stayed up on `7VS00ZJ8`.
- Evening P0 evacuation (12 guests off, 10 P2 counterweights on) → the survivor stalled pool-wide under the inbound copies (22:25Z; 144 D-state, sshd/pveproxy hung before banner, guests still pinged) → **autonomous PDU drain** (operator pre-authorised): guard matched `MINISFORUM MS-01 S1290`, OFF 22:49:15Z, **AMT dark in 5 s = proof-of-cut**, ON 22:54:28Z, ICMP +174 s, SSH +178 s. `zpool status` before guests: **both legs ONLINE, resilver started** — 3-for-3 for the drain.
- ⭐⭐ **New lesson: revival ≠ health.** The returned leg ran at **w_await 1016 ms / ~1 write/s / 99 % util**; a mirror write waits for both legs, so it strangled the host (3/68 guests up after 6 min, resilver 23 MB/s, iowait 31 %). `zpool offline` of the returned leg fixed it instantly (0.8 ms). **After any drain, `iostat -x` the returned disk before trusting it.**
- ⭐⭐ Then the *survivor* stalled 3× in 45 min under ≤5 MB/s of writes, self-clearing in 1-5 min → both drives are faulty. **A drain resets a wedged controller; it does not make a bad drive good.** Interim rules and replacement plan: `.claude/rules/infrastructure.md` § Known Host nl-pve01, IFRNLLEI01PRD-2864.
- Tooling reused: `pdu.py` (raw socket, IAC refuse-all, live-menu parse, name guard), `postboot-verify.sh` (rpool BEFORE guests, `lspci -s 5a:00.0` = Kingston check for the vfio pin on cl01file01, half-init count), G-gates G1-G6 in the plan file. HAHA/FISHA did not fail over during the outage (fence path through the dead host, -2860).

## Reference result (2026-09-19, nl-pve01) — variant (b) on the last leg; storage back, network NOT

- 09-18 ~20:50 NL: the survivor `7VS00ZJ8` @ 59:00.0 went `D3cold → D0 inaccessible`. With `7VS00YN2` OFFLINE since 09-17, the pool had no working leg. RAM-zombie for ~5.5 h, and **unalerted**, because the primary alert intake (nltg01) lives on this host.
- The AMT console showed the D3cold line and the I/O errors, so this was variant (b), not a pmxcfs wedge. The PDU guard matched `MINISFORUM MS-01 S1290`. OFF at 00:25:56Z; AMT and ICMP dark in <9 s; ON after 5 m 52 s. Quorum stayed at 4/4 for the whole window (no HA resources, so no self-fence risk).
- **Storage: 4 for 4 for the drain.** rpool returned with `7VS00ZJ8` ONLINE and 0 errors. `pve-guests` waited for quorum, so no guest started early.
- **Network: both bond legs dark** (copper SFP-10G-T at both ends). Five remote resets failed: `link-down-on-close` + flap; switch shut/no shut (10 s, then 30 s); i40e reload + `ifreload -a`; warm reboot. Service was restored through the 1 G fallback below. Quorum 5 at 01:27Z, 36/36 guests by 01:37Z. The start burst peaked at 90 % util and 11 ms w_await, then settled to about 0.1 ms.
- ⛔ `pkill -f <script-name>` killed its own shell (the pattern matched its own command line), and the first OFF never ran. **Kill helpers by PID.**

## 1 G fallback via the AMT port (nl-pve01)

Use this when the bond is dead but the host is up. The i226-LM `enp109s0` shares its port with AMT, on nl-sw01 Te1/0/37 (access VLAN 10). Everything is runtime/unsaved so that it reverts cleanly.

1. **Host (AMT console):** `ip link set vmbr0 address 58:47:ca:79:61:80; ip link set bond0 nomaster; ip link set enp109s0 mtu 9000 master vmbr0; bridge vlan del dev enp109s0 vid 1; bridge vlan add dev enp109s0 vid 2-4094; bridge vlan add dev enp109s0 vid 10 pvid untagged`. Management (VLAN 10, untagged) works at once, even before the switch change. Pinning the MAC keeps vmbr0 from inheriting the AMT MAC. Detaching bond0 prevents a loop if a module comes back.
2. **Switch (netmiko):** guard that Te1/0/37 is still `switchport mode access` and that the host MAC `5847.ca79.6183` is on it, then `switchport trunk native vlan 10` + `switchport mode trunk` + a TEMP description. Expect ~30 s of STP convergence, during which SSH and AMT both drop. Do not `write mem`.
3. **Verify:** `pvecm status` (votes back), a guest on a non-10 VLAN answers ping, and the `pve-guests` journal shows `got quorum`.
4. **Revert** once Po7 shows both members `(P)`: host `ifreload -a`, then the switch back to `switchport mode access` + `no switchport trunk native vlan 10` + the original description.
