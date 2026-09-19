---
name: feedback-zfs-dio-must-be-disabled-on-pve
description: "On any PVE host running OpenZFS 2.3+ with VMs using cache=none qcow2/raw on a ZFS dataset, ALWAYS set direct=disabled on the pool. Otherwise dio_verify_wr races between guest buffer mutation and ZFS DMA verify will pause VMs at random with bogus \"nospace\" io-error."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: f936b7bb-eed8-4b1c-b6b7-195adde4af9c
---

On any PVE host running OpenZFS 2.3+ with VMs using `cache=none` (`cache.direct=true` in QEMU `-blockdev` JSON) on a ZFS-backed disk image (qcow2 OR raw on directory storage), ALWAYS set `zfs set direct=disabled <pool>` and drop `/etc/modprobe.d/zfs-dio-disable.conf` with `options zfs zfs_dio_enabled=0`. Verify with `zfs get direct <pool>` and `cat /sys/module/zfs/parameters/zfs_dio_enabled`.

**Why:** OpenZFS 2.3 changed the default direct-I/O policy to `standard` (was `disabled` in 2.2-). With `standard`, ZFS honours `O_DIRECT` and does zero-copy DMA from the QEMU userspace buffer, then verifies CRC after the write completes. If the guest mutates that page mid-flight (very common — any RSS rewrite, container heap churn, ML model load), the CRC mismatches → ZFS returns EIO → qcow2 cluster-allocation path maps EIO to ENOSPC → QEMU `werror=enospc,stop` pauses the VM with bogus "nospace" status. Pool can have terabytes free and you still get io-error pauses. Manifested at NL on nl-gpu01 / VM VMID_REDACTED as "almost daily freezes" because ollama's buffer churn maximises the race window. 121 `ereport.fs.zfs.dio_verify_wr` events accumulated over 2 months before diagnosis.

**How to apply:** Whenever doing PVE-host onboarding (cf [[pve04_onboarding_in_progress_20260510]]) or after any major ZFS upgrade. Also when investigating any "VM paused with io-error but ZFS pool is fine" symptom. The man-page literally says `disabled` is "the default behavior for OpenZFS 2.2 and prior releases" — zero risk, just reverts to pre-2.3 behavior. ARC absorbs the writes via the buffered path.

Caught 2026-05-14 during nl-gpu01 RCA. Full mechanism + fix recipe: [[gpu01_zfs_dio_race_root_cause_20260514]].
