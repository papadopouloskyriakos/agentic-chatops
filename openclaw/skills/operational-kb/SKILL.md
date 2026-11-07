---
name: operational-kb
description: Operational knowledge base — PVE node reference, IoT cluster, GR iSCSI server quick facts for triage context.
allowed-tools: Bash
user-invocable: false
metadata:
  openclaw:
    always: true
---

# Operational Knowledge Base (auto-updated)

## PVE Node Quick Reference
- **nl-pve01 (94GB, ZFS):** Chronically oversubscribed (80% RAM, 7 VMs + 57 LXC). No swap. CHECK FIRST on multi-host NL alert bursts.
- **nl-pve02 (16GB, ext4/LVM):** VM-based. 8GB swap, swappiness=10. Healthy.
- **nl-pve03 (125GB, ZFS):** No swap. High RAM (86%). CGC LXC here (8GB).
- **gr-pve01 (94GB, ZFS):** 8GB swapfile on NVMe, swappiness=10. 83% RAM.
- **gr-pve02 (31GB):** GR iSCSI server. ZFS ssd-pool RAID1, LIO targetcli, 15 targets, VLAN 188. SeaweedFS migrated to NFS on sdc.

## IoT Pacemaker Cluster (NL)
- 3-node: nlcl01iot01 (VMID 666), nl-iot02, nlcl01iotarb01
- Resources: HA, Mosquitto, Zigbee2MQTT, ESPHome, Node-RED (group failover)
- On failure: Pacemaker fences and migrates. DO NOT failback automatically.
- SSH: `ssh -i ~/.ssh/one_key root@nlcl01iotXX`
