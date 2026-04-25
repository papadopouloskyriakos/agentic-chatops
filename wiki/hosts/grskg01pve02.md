# gr-pve02

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:native/pve/CLAUDE.md**
- **gr-pve02 extras:** Dell OMSA systemd units (7 services), `iscsi-portal-fixer`, `rsyncd`, `perccli-log`, Dell APT repo.
- | gr-pve02 | Xeon E3-1270 V2 | 4C/8T | 33.6 GB | bond0 (1G) + bond1 (10G) | 8 TB ext4 + 966 GB SSD ZFS | Dell PowerEdge, NFS exports, OMSA |
- 9. **gr-pve02 iowait 11.7%** — Dell PERC RAID, investigate disk health via perccli.

**gr:CLAUDE.md**
- ssh -i ~/.ssh/one_key -o StrictHostKeyChecking=no root@gr-pve02 "pct list"
- - `gr-pve02`: 3 LXC (secondary + NFS/iSCSI storage)

**gr:k8s/CLAUDE.md**
- - No `nl-nas01-csi/` — GR uses `democratic-csi/` (iSCSI + ZFS on gr-pve02, which doubles as Proxmox host and storage server)

**gr:docker/CLAUDE.md**
- 15 hosts, 54+ containers across gr-pve01 and gr-pve02.

**gr:pve/CLAUDE.md**
- | gr-pve02 | TBD | Secondary Proxmox host |
- <!-- TODO: Collect PVE configs from gr-pve01 and gr-pve02 into git -->

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-03-25 | iSCSI I/O contention | SeaweedFS 2x500GB volume zvols on ssd-pool were the heaviest | Migrated SeaweedFS volumes from iSCSI (ZFS ssd-pool) to NFS  | 0.9 |

## Lessons Learned

- **IFRGRSKG01PRD-122**: GR SeaweedFS volumes now on NFS/sdc (HDD), NOT iSCSI/ssd-pool. PVs: seaweedfs-volume-0-nfs, seaweedfs-volume-1-nfs. NFS export: /mnt/gr-pve02-local-ext4/seaweedfs on 10.0.188.X. Masters+filers still on iSCSI. If SeaweedFS volume pods fail, check NFS export + mount, not iSCSI.

## Related Memory Entries

- **GR iSCSI Server (gr-pve02)** (project): GR K8s iSCSI storage — ZFS zvols on PERC H710P, architecture, tunables, AWX PVC fix, SeaweedFS migrated to NFS/sdc
- **Per-Model LLM Usage Tracking** (project): llm_usage table, 3-tier token tracking (Tier 0 local GPU, Tier 1 OpenAI, Tier 2 Claude Code), JSONL-based Claude poller, Prometheus metrics, portfolio live widget. Poller rewrite + data cleanup 2026-04-10.
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.

*Compiled: 2026-04-11 14:13 UTC*