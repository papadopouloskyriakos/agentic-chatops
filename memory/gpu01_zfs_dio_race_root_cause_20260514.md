---
name: gpu01-zfs-dio-race-root-cause-20260514
description: "nl-gpu01 (VM VMID_REDACTED) \"frozen daily with io-error\" was OpenZFS 2.3 dio_verify_wr race with QEMU cache=none/aio=io_uring. Fixed by setting direct=disabled on rpool across all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04, GR: gr-pve01/gr-pve02) + zfs_dio_enabled=0 modprobe.d safety net."
metadata: 
  node_type: memory
  type: project
  originSessionId: f936b7bb-eed8-4b1c-b6b7-195adde4af9c
---

# nl-gpu01 io-error freeze — true root cause is ZFS Direct I/O verify race

RESOLVED 2026-05-14 ~22:00 CEST. The 2026-05-12 fix ([[gpu01_freeze_qcow2_io_error_20260512]]) — discard=on + memory bump + fstrim — addressed the secondary symptom (qcow2 cluster bloat) but **not** the actual root cause. Real RC is the OpenZFS 2.3 Direct I/O verify-write race with QEMU `cache=none` (`cache.direct=true`) + `aio=io_uring` against qcow2 files on a ZFS dataset.

## The race (mechanism)

1. QEMU opens the qcow2 file with `O_DIRECT` (PVE default for SCSI/Virtio drives in `cache=none` mode — see `cat /proc/<qemu-pid>/cmdline` for `"cache":{"direct":true,"no-flush":false},"aio":"io_uring"`).
2. ZFS 2.3+ with `direct=standard` (the new default) honours `O_DIRECT` by doing zero-copy DMA from the QEMU userspace buffer into pool vdevs.
3. ZFS 2.3 added `DIO_CHECKSUM_VERIFY` zio stage: after the write, ZFS reads back the buffer and compares CRC against what was written. This is meant to catch DMA buffer corruption.
4. **Race window:** between QEMU submitting the write and ZFS completing the DMA + verify, the guest userspace can mutate that page (any heap rewrite — e.g. ollama loading a model, container churning RSS pages). When the page changes mid-flight, the post-write CRC mismatches the pre-write CRC.
5. ZFS fires `ereport.fs.zfs.dio_verify_wr` (with `zio_err=0x5` = EIO) and returns EIO to QEMU.
6. QEMU's qcow2 driver, encountering EIO during a cluster-allocation write, **maps it internally to ENOSPC** (well-known QEMU-on-ZFS surprise).
7. QEMU's default `werror=enospc,stop` policy pauses the VM — `qmpstatus: io-error`, `I/O status: nospace` even though ZFS has terabytes free.

## Evidence chain (nl-pve03)

- `zpool events -v` → 4 `dio_verify_wr` events on May 14, the most recent at **19:42:05** matching qcow2 mtime + freeze window. `dio_verify_errors` counter: 0x66 (Apr 24) → 0x79 (May 14) = 121 cumulative.
- Each cluster of `dio_verify_wr` events maps to a freeze incident in `pvenode task list --vmid VMID_REDACTED`:
  - May 9 16:55/19:00/19:24 → 2× qmstop/qmstart May 9 18:05 + 19:50
  - May 11 05:49/22:31 → qmstop/qmstart May 11 11:38
  - May 14 18:03/19:42 → freeze + manual resume May 14 22:00
- 8 of 8 VMs on nl-pve03 use `cache.direct=true` (PVE default for SCSI/Virtio data disks) → all 8 are at-risk. Only VMID_REDACTED manifested because ollama's heavy buffer churn (5 GiB swap activity, 10–25 GiB model loads/unloads) maximises the race window.
- ZFS pool was healthy (52% capacity, 1.7 TiB free, 0 read/write/cksum errors). The "nospace" was a QEMU mapping artefact, not actual ENOSPC.

## Fix applied (3 layers, all 6 PVE hosts)

| Host | Pool(s) | direct property | modprobe + runtime |
|------|---------|-----------------|---------------------|
| nl-pve01 | rpool | `disabled` | `zfs_dio_enabled=0` |
| nl-pve02 | (no ZFS pools) | n/a | `zfs_dio_enabled=0` |
| nl-pve03 | rpool | `disabled` | `zfs_dio_enabled=0` |
| nlpve04 | rpool | `disabled` | `zfs_dio_enabled=0` |
| gr-pve01 | rpool | `disabled` | `zfs_dio_enabled=0` |
| gr-pve02 | ssd-pool | `disabled` | `zfs_dio_enabled=0` |

Layer 1: `zfs set direct=disabled <pool>` — inherited by all child datasets. Per `man zfsprops`, `disabled` is "the default behavior for OpenZFS 2.2 and prior releases" — zero risk, just reverting to pre-2.3 behavior. ARC handles all writes (buffered path).

Layer 2: `/etc/modprobe.d/zfs-dio-disable.conf` with `options zfs zfs_dio_enabled=0` — survives ZFS module reload + kernel upgrades. Belt-and-suspenders for case where dataset property could get reset (e.g. `zfs inherit direct rpool` accident).

Layer 3: `echo 0 > /sys/module/zfs/parameters/zfs_dio_enabled` — runtime application without reboot. Already loaded module honours new value.

## Verification (post-fix, ~30 min observed)

- VM VMID_REDACTED resumed cleanly via `qm resume`.
- Stress test inside guest: `dd if=/dev/zero of=/tmp/dio-test.bin bs=1M count=512 oflag=direct` — completed (32 MB/s under load 23, expected). No new `dio_verify_wr` event.
- ~110k new write operations on scsi0 since fix; `failed_wr_operations` count unchanged (still 2 from pre-fix).
- ollama serving nomic-embed-text + llama3.2:1b + bge-m3 from VRAM, GPU usable.
- DIO error count frozen at 121 (was climbing 1-2/day for past 2 months).

## Why the May-12 fix only bought 2.28 days

`discard=on` + `detect-zeroes=unmap` reduced qcow2 cluster allocation rate (deletes propagate as UNMAP, sparse holes form). Lower allocation rate = fewer race opportunities. But the race exists for any write that touches a new cluster, and ollama's workload still triggers it within ~2-3 days. **`discard=on` was the right hardening but never the root cause.**

## What to do if it recurs

1. Check `zfs get direct rpool` on the host — if it shows `standard`, the property got reset → re-apply `zfs set direct=disabled <pool>`.
2. Check `cat /sys/module/zfs/parameters/zfs_dio_enabled` — if `1`, runtime drifted → `echo 0 > ...` and verify `/etc/modprobe.d/zfs-dio-disable.conf` exists.
3. Check `zpool events | grep dio_verify_wr | wc -l` — if climbing past the baseline count for that pool, the fix isn't taking effect.
4. Resume any io-error-paused VMs: `qm resume <vmid>`.

## Drift-detection (light)

`scripts/check-zfs-dio-disabled.sh` runs the property + module-param check and exits non-zero with diagnostic output. Suitable for cron + email or manual run during routine PVE audits.

## Related

- [[gpu01_freeze_qcow2_io_error_20260512]] — qcow2/discard layer (now known to be partial fix).
- [[gpu01_nvml_stale_handles_20260514]] — separate issue (NVML container stale handles after nvidia-persistenced restart). Different mechanism, same VM.
- [[ollama_gpu_only_lockdown_20260513]] — Modelfile num_gpu=999 lockdown. Same VM.
- [[feedback_zfs_dio_must_be_disabled_on_pve]] — guidance for future PVE work.
