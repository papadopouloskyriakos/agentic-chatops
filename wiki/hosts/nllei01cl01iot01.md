# nlcl01iot01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:native/haha/CLAUDE.md**
- | nlcl01iot01 | 666 | nl-pve01 | 10.0.181.X, 10.0.X.X | QEMU VM. 2C/2S, 4GB RAM, 64GB SSD. Active or passive (alternates each weekly update). |
- ssh -i ~/.ssh/one_key root@nlcl01iot01
- | nlcl01iot01 | pacemaker/crm-config.txt, corosync/corosync.conf, scripts/{hard_reset_tubeszb_olimex.sh, pacemaker_update.sh, clear_arp_nfs.sh}, crontab-root, mnt-iot/{esphome, homeassistant, mosquitto, nodered, zigbee2mqtt} configs |
- **Check Pacemaker:** `ssh -i ~/.ssh/one_key root@nlcl01iot01 "crm status"`

**gateway:CLAUDE.md**
- - **[P0] Full hostnames, no exceptions:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, nlcl01iot01 not iot01, nlcl01file02 not file02, gr-pve01 not pve01). Never use generic role labels ("the ASA", "the router", "the active node") as a substitute. Applies to all output: playbooks, comments, memory, YT, Matrix messages, tables, diagram labels, filenames. Reinforced 2026-04-30 after multiple session slips.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Device rebooted. |  | Resolved via Claude session IFRNLLEI01PRD-259 | 0.9 |
| 2026-03-25 | Devices up/down | iot01 is VMID 666 (non-standard) on nl-pve01. Stopped by | Started VM via qm start 666. Cluster rejoined: 3/3 nodes onl | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-259**: IoT devices (nlcl01iot01/02) reboot periodically — low-priority unless recurring. Protonmail bridge (nlprotonmail-bridge01) container restarts are common. These are informational alerts, not actionable.
- **IFRNLLEI01PRD-256**: iot01 is VMID 666 (non-standard) on nl-pve01. IoT cluster is 3-node Pacemaker (iot01/iot02/nlcl01iotarb01) with automatic failover. Do NOT failback services — leave on current active node. SSH requires one_key + root.

## Related Memory Entries

- **OCF docker start/stop timeout must match real container boot time** (feedback): ocf:heartbeat:docker default 90s start/stop timeouts cause Pacemaker fence escalation when slow-booting containers (Node-RED, HA, Z2M, ESPHome) miss the deadline. Always size start/stop timeouts to ≥ p99 boot time + margin.
- **HAHA chaos engineering catalog 2026-04-30 (~14 tests, 2 bugs surfaced+fixed)** (project): Same-day chaos engineering pass over the whole IoT infrastructure (HAHA + FISHA + sidecars + voice pipeline + cluster fencing). 14 tests run, 2 real bugs surfaced and 1 fixed (nodered start timeout 90s→180s); 1 outstanding (fence_pve list TypeError, IFRNLLEI01PRD-806). Empirical confidence table inside.
- **HAHA reliability hardening 2026-04-30 (Phases 1-5 implemented)** (project): Same-day follow-up after the 2026-04-27 → 2026-04-30 ~66h HAHA outage. App-level OCF docker monitor_cmd, NFS auto-flush, NFS stale-fh exporter, proactive ARP, host-pressure alerts, Twilio escalation. T1 e2e verified: 18s detect, 3m30s recover.
- **HAHA NFS stale-fh outage 2026-04-27 → 2026-04-30 (RESOLVED, ~66h 39m)** (project): Home Assistant down 2026-04-27 14:55 → 2026-04-30 09:34 UTC (~66h 39m). HA Python crashed with Bus error during nfs-group migration; container kept running so Pacemaker never noticed. Apr 30 02:15 weekly-update reboot exposed nlcl01file02 fh-cache poisoning. Fixed by restarting Pacemaker exportfs resource.
- **IoT Pacemaker HA Cluster** (project): 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout

*Compiled: 2026-07-03 04:30 UTC*