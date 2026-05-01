# nlcl01iot01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:native/haha/CLAUDE.md**
- | nlcl01iot01 | 666 | pve01 | 10.0.181.X, 10.0.X.X | QEMU VM. 2C/2S, 4GB RAM, 64GB SSD. Currently standby. |
- ssh -i ~/.ssh/one_key root@nlcl01iot01
- | nlcl01iot01 | pacemaker/crm-config.txt, corosync/corosync.conf, scripts/{hard_reset_tubeszb_olimex.sh, pacemaker_update.sh, clear_arp_nfs.sh}, crontab-root, mnt-iot/{esphome, homeassistant, mosquitto, nodered, zigbee2mqtt} configs |
- **Check Pacemaker:** `ssh -i ~/.ssh/one_key root@nlcl01iot01 "crm status"`

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-03 | Device rebooted. |  | Resolved via Claude session IFRNLLEI01PRD-259 | 0.9 |
| 2026-03-25 | Devices up/down | iot01 is VMID 666 (non-standard) on pve01. Stopped by OOM pr | Started VM via qm start 666. Cluster rejoined: 3/3 nodes onl | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-259**: IoT devices (nlcl01iot01/02) reboot periodically — low-priority unless recurring. Protonmail bridge (nlprotonmail-bridge01) container restarts are common. These are informational alerts, not actionable.
- **IFRNLLEI01PRD-256**: iot01 is VMID 666 (non-standard) on pve01. IoT cluster is 3-node Pacemaker (iot01/iot02/iotarb01) with automatic failover. Do NOT failback services — leave on current active node. SSH requires one_key + root.

## Related Memory Entries

- **IoT Pacemaker HA Cluster** (project): 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout

*Compiled: 2026-04-11 14:13 UTC*