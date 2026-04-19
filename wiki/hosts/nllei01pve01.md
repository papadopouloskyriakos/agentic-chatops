# nl-pve01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- - **Hosts**: NL primary (nl-pve01/02/03), GR DR (gr-pve01/02).
- | List all nodes | `pve_list_nodes()` | `ssh nl-pve01 "pvecm nodes"` |
- | Cluster status | `pve_cluster_status()` | `ssh nl-pve01 "pvecm status"` |
- | nl-pve01 | Proxmox hypervisor (primary) | `ssh nl-pve01` |
- 1. Check if it's a K8s node: `ssh nl-pve01 "pct exec <vmid> -- kubectl get nodes"`

**nl:native/pve/CLAUDE.md**
- scp root@nl-pve01:/etc/network/interfaces native/pve/nl-pve01/network/interfaces
- git add native/pve/nl-pve01/
- git commit -m "chore(native): sync pve host configs from nl-pve01"
- All 5 PVE hosts are directly SSH-reachable as `root` via the standard host aliases (`ssh nl-pve01`, …) — no `-i ~/.ssh/one_key` needed for NL; GR hosts (`gr-pve01/02`) do require `-i ~/.ssh/one_key root@...` (see `feedback_gr_pve_ssh` memory).
- | nl-pve01 | i9-12900H | 14C/20T | 101 GB | bond0 (802.3ad, 10G) | 3.7 TB ZFS | Primary NL hypervisor |

**nl:native/habitica/nlhabitica01/CLAUDE.md**
- | LXC VMID_REDACTED on nl-pve01 |
- | VMID_REDACTED | nlhabitica01 | 10.0.181.X | nl-pve01 | 4 | 4096 MB | 20 GB | Yes | Primary Habitica instance |
- | VMID_REDACTED | nlhabitica02 | 10.0.181.X | nl-pve01 | 4 | 4096 MB | 10 GB | No | Docker LXC (standby, unused) |
- ssh nl-pve01 "pct exec VMID_REDACTED -- bash"

**nl:native/openvpnas/CLAUDE.md**
- | nloas01 | VMID_REDACTED | nl-pve01 | 10.0.X.X | 443 | TCP | 10.0.X.X/28 | operator, elliz |
- | nloas02 | VMID_REDACTED | nl-pve01 | 10.0.X.X | 888 | TCP | 10.0.X.X/28 | operator, elliz |
- | nloas03 | VMID_REDACTED | nl-pve01 | 10.0.X.X | 999 | UDP | 10.0.X.X/28 | operator, elliz, georgez |
- ### NL (via nl-pve01)
- ssh nl-pve01 "pct exec VMID_REDACTED -- bash"   # oas01

**nl:native/syncthing/CLAUDE.md**
- | nlsyncthing01 | VMID_REDACTED | nl-pve01 | 10.0.181.X | NL Syncthing hub (LXC, 4 cores, 4GB RAM, NFS→syno01) |
- | nlstsrv01 | VMID_REDACTED | nl-pve01 | 10.0.181.X | NL discovery + relay + relay pool (Docker LXC, 2 cores, 1GB) |
- ssh nl-pve01 "pct exec VMID_REDACTED -- cat /home/syncthing/.local/state/syncthing/config.xml" > nlsyncthing01/config.xml
- ssh nl-pve01 "pct exec VMID_REDACTED -- cat /srv/stsrv/docker-compose.yml" > nlstsrv01/docker-compose.yml

**nl:native/ncha/CLAUDE.md**
- **Check:** `ssh nl-pve01 "pct exec VMID_REDACTED -- ipactl status"` (all 9 services should be RUNNING)

**nl:docker/nlmattermost01/mattermost/CLAUDE.md**
- Self-hosted **Mattermost Enterprise Edition** for `mattermost.example.net`, running on host `nlmattermost01` (LXC VMID_REDACTED on nl-pve01) at `/srv/mattermost/`. Deployed from this git directory via the standard Docker CI pipeline.
- - **VMID**: VMID_REDACTED on nl-pve01
- ssh -i ~/.ssh/one_key root@nl-pve01 "pct exec VMID_REDACTED -- docker compose -f /srv/mattermost/docker-compose.yml ps"
- ssh -i ~/.ssh/one_key root@nl-pve01 "pct exec VMID_REDACTED -- docker compose -f /srv/mattermost/docker-compose.yml logs --tail 50 mattermost"
- ssh -i ~/.ssh/one_key root@nl-pve01 "pct exec VMID_REDACTED -- docker compose -f /srv/mattermost/docker-compose.yml restart mattermost"

**nl:pve/CLAUDE.md**
- | nl-pve01 | Venus Series Mini PC | i9-12900H (20T) | 96 GB | NVMe ZFS | 75 | 8 |
- ├── nl-pve01/
- | `nl-pve01-local-zfs` | Local ZFS | 72 LXC, 6 QEMU | Performance workloads |

**gateway:CLAUDE.md**
- - **Full hostnames:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, gr-pve01 not pve01). Multi-site environment makes short forms ambiguous. Applies to all output: playbooks, comments, memory, YT, Matrix messages.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-08 | Service up/down | Multiple NL hosts showing Service up/down during Freedom ISP | Monitor and wait 15 minutes after Freedom drops. xs4all tunn | 0.9 |
| 2026-04-03 | Port status up/down. |  | Resolved via Claude session IFRNLLEI01PRD-282 | 0.9 |
| 2026-04-03 | Service up/down. |  | Resolved via Claude session IFRNLLEI01PRD-334 | 0.9 |
| 2026-03-25 | Service up/down | pve01 oversubscribed: 80% RAM (75/94GB), 7 VMs (40GB) + 57 L | Removed dangerous ZFS swapfile (orphaned, clears on reboot). | 0.9 |
| 2026-03-25 | Service up/down | PVE swap audit: pve01 had 1GB swapfile on ZFS (deadlock risk | pve01: removed ZFS swapfile (deadlocked on swapoff, clears o | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-282**: Port status up/down on PVE hosts typically indicates network interface flap during maintenance, storage failover, or bond reconfiguration. Check interface status and bond health.
- **IFRNLLEI01PRD-334**: Service up/down on PVE hosts (pve01, pve02) during cluster operations is expected. PVE services restart during HA migration, storage maintenance, or kernel updates. Correlate with maintenance window.
- **IFRNLLEI01PRD-381**: Freedom ISP PPPoE outages cause cascading NL+GR alerts (up/down on all NL devices + GR VPN-dependent devices). First check: show vpdn pppinterface on NL ASA. xs4all WAN takes over automatically via SLA track failover. Wait 15 min before investigating — most services self-recover.
- **IFRNLLEI01PRD-255**: NEVER use swap on ZFS (swapfile or zvol). Proxmox explicitly warns: swapoff deadlocks. pve01 proved it — swapoff hung, orphaned swap only clears on reboot. For ZFS hosts, use swap partition on physical disk outside ZFS, or no swap at all.
- **IFRNLLEI01PRD-255**: pve01 cascading failures: when pve01 load spikes (>50), expect apiserver crashes on ctrl01, iot01 VM shutdown, and service check failures across multiple hosts. Root cause is always RAM oversubscription. Check pve01 first before investigating individual alerts.

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **Corosync cluster split incident 2026-04-11** (project): PVE 5-node cluster split — stale ASA conn table routed nl-pve01 knet via outside_freedom instead of VTI. Fixed by clear conn + timeout floating-conn on both ASAs.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **IoT Pacemaker HA Cluster** (project): 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **Operational Activation Audit 2026-04-10** (project): Comprehensive audit scoring operational activation (not just implementation). 21/21 tables populated after remediation. 8 YT issues (445-452).
- **Pipeline Hardening (2026-04-01)** (project): 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.

## Physical Documentation (03_Lab)

- `03_Lab/NL/Servers/nl-pve01/20230923-1746_proxmox-backup-client-script-v03.txt`
- `03_Lab/NL/Servers/nl-pve01/20231226-2313_nl-pve01_solved_10Gbps_atlantic_issues.txt`
- `03_Lab/NL/Servers/nl-pve01/20240506_PVE_ISSUE_fstrim.txt`
- `03_Lab/NL/Servers/nl-pve01/20240506_pve_syslog_fstrim.log`
- `03_Lab/NL/Servers/nl-pve01/20240911_USB_Stick_with_Proxmox_DIED.txt`
- `03_Lab/NL/Servers/nl-pve01/20240914_PVE_Network_Changes.txt`
- `03_Lab/NL/Servers/nl-pve01/20240919_pve_api_calls.txt`
- `03_Lab/NL/Servers/nl-pve01/20241205-2212_nl-pve01_new_port_mappings.md`
- `03_Lab/NL/Servers/nl-pve01/20241205-2223_nl-pve01_interfaces.md`
- `03_Lab/NL/Servers/nl-pve01/20250330-1712_nl-pve01_interfaces.cfg`
- `03_Lab/NL/Servers/nl-pve01/20250330-1713_nl-pve01_interfaces_NEW_SWITCH.cfg`
- `03_Lab/NL/Servers/nl-pve01/20250515_nl-pve01_ansible_inventory (freeipa).yaml`
- `03_Lab/NL/Servers/nl-pve01/20250515_nl-pve01_ansible_inventory (oas).yaml`
- `03_Lab/NL/Servers/nl-pve01/20250515_nl-pve01_ansible_inventory.yaml`
- `03_Lab/NL/Servers/nl-pve01/70-persistent-net.rules`
- `03_Lab/NL/Servers/nl-pve01/gr-pve01_interfaces.ovs_rstp.bak.txt`
- `03_Lab/NL/Servers/nl-pve01/hosts`
- `03_Lab/NL/Servers/nl-pve01/interfaces`
- `03_Lab/NL/Servers/nl-pve01/lxc/!Decommissioned/nlk0s01/20230528_k0s_firefly.txt`
- `03_Lab/NL/Servers/nl-pve01/lxc/!Decommissioned/nlk0s01/firefly/Firefly III helm registry kubernetes.url`

*Compiled: 2026-04-11 14:13 UTC*