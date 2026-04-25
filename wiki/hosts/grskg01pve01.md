# gr-pve01

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:CLAUDE.md**
- - **Hosts**: NL primary (nl-pve01/02/03), GR DR (gr-pve01/02).
- | 06:20 | Cert Sync - Proxmox | pve01/02/03, gr-pve01/02 | `systemctl restart pveproxy` |

**nl:native/librenms/CLAUDE.md**
- | gr-nms01 | GR (Thessaloniki) | `https://gr-nms01.example.net/` | gr-pve01 | 201020705 | 10.0.X.X | DR NMS — monitors GR site devices (52 after autodiscovery) |
- | NL monitors GR | gr-pve01, gr-sw02, 203.0.113.X | ping only |

**nl:native/pve/CLAUDE.md**
- All 5 PVE hosts are directly SSH-reachable as `root` via the standard host aliases (`ssh nl-pve01`, …) — no `-i ~/.ssh/one_key` needed for NL; GR hosts (`gr-pve01/02`) do require `-i ~/.ssh/one_key root@...` (see `feedback_gr_pve_ssh` memory).
- | gr-pve01 | i9-12900H | 14C/20T | 101 GB | bond0 (1G) + bond1 (10G) | 1.9 TB ZFS + 2.0 TB ext4 | Primary GR hypervisor |
- 2. **gr-pve01 swap 99.8% exhausted** — 1.84x RAM overcommit, no balloon on any VM, 186 GB allocated vs 101 GB physical. Fix: enable ballooning, right-size LXCs, migrate guests to gr-pve02.
- 7. **gr-pve01 APT sources still on bookworm** — all others on trixie.

**nl:native/openvpnas/CLAUDE.md**
- | groas01 | 201110501 | gr-pve01 | 10.0.X.X | 443 | TCP | 10.0.X.X/28 | operator, elliz |
- | groas02 | 201110502 | gr-pve01 | 10.0.X.X | 888 | TCP | 10.0.X.X/28 | operator, elliz |
- | groas03 | 201110503 | gr-pve01 | 10.0.X.X | 999 | UDP | 10.0.X.X/28 | operator, elliz |
- ### GR (via gr-pve01, needs -i key)
- ssh -i ~/.ssh/one_key root@gr-pve01 "pct exec 201110501 -- bash"   # oas01

**nl:native/syncthing/CLAUDE.md**
- | grsyncthing01 | 201090903 | gr-pve01 | 10.0.X.X | GR Syncthing hub (LXC, 4 cores, 4GB RAM, NFS→omv01, dual-homed) |
- | grstsrv01 | 201090904 | gr-pve01 | 10.0.X.X | GR discovery + relay + relay pool (Docker LXC, 2 cores, 1GB) |
- ssh -i ~/.ssh/one_key root@gr-pve01 "pct exec 201090903 -- cat /home/syncthing/.local/state/syncthing/config.xml" > grsyncthing01/config.xml

**nl:native/ncha/CLAUDE.md**
- | grnpm01 | — | gr-pve01 | 10.0.X.X | GR site entry point (DNS RR partner) |
- | grfreeipa01 | — | gr-pve01 | — | GR site replica. DNS RR partner + LDAP replication. |

**gr:CLAUDE.md**
- ssh -i ~/.ssh/one_key -o StrictHostKeyChecking=no root@gr-pve01 "pct list"
- ssh -i ~/.ssh/one_key -o StrictHostKeyChecking=no root@gr-pve01 "pct exec <VMID> -- <command>"
- - `gr-pve01`: 32 LXC + 10 QEMU (primary)

**gr:docker/CLAUDE.md**
- 15 hosts, 54+ containers across gr-pve01 and gr-pve02.

**gr:pve/CLAUDE.md**
- | gr-pve01 | TBD | Primary Proxmox host — K8s nodes, DMZ, FRR |
- <!-- TODO: Collect PVE configs from gr-pve01 and gr-pve02 into git -->
- | gr-dmz01 | QEMU | gr-pve01 | DMZ Docker host (10.0.X.X) |

**gr:edge/CLAUDE.md**
- | PVE Host | gr-pve01 |

**gateway:CLAUDE.md**
- - **Full hostnames:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, gr-pve01 not pve01). Multi-site environment makes short forms ambiguous. Applies to all output: playbooks, comments, memory, YT, Matrix messages.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-08 | Devices up/down | GR devices showing down from NL LibreNMS perspective. Root c | Check NL ASA Freedom PPPoE status first: show vpdn pppinterf | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-381**: Freedom ISP PPPoE outages cause cascading NL+GR alerts (up/down on all NL devices + GR VPN-dependent devices). First check: show vpdn pppinterface on NL ASA. xs4all WAN takes over automatically via SLA track failover. Wait 15 min before investigating — most services self-recover.

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **Always use full hostnames** (feedback): Never strip site/cluster prefixes from hostnames — use nl-nas02 not syno02, nl-pve01 not pve01
- **GR ASA SSH requires stepstone via gr-pve01** (feedback): SSH to gr-fw01 only works via gr-pve01 as a jump host — direct SSH from NL is rejected (connection reset).
- **gr_chatops_infra** (project): GR site (gr) ChatOps infrastructure — complete multi-site alert pipeline, triage scripts, n8n workflows, kubeconfig, LibreNMS transport, Alertmanager webhook
- **GR Claude Agent (grclaude01)** (project): Claude Code agent at GR site for NL maintenance oversight. VMID 201021201, 10.0.X.X, gr-pve01.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **VTI BGP outage investigation 2026-04-11** (project): NL-GR inter-site VTI tunnels down, BGP not peering, complete GR unreachability from NL. Root cause identified.

*Compiled: 2026-04-11 14:13 UTC*