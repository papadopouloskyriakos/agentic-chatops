# gr-pve01

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:CLAUDE.md**
- - **Hosts**: NL primary (nl-pve01/02/03), GR DR (gr-pve01/02).
- | 06:20 | Cert Sync - Proxmox | pve01/02/03, gr-pve01/02 | `systemctl restart pveproxy` |

**nl:native/pve/CLAUDE.md**
- All 5 PVE hosts are directly SSH-reachable as `root` via the standard host aliases (`ssh nl-pve01`, …) — no `-i ~/.ssh/one_key` needed for NL; GR hosts (`gr-pve01/02`) do require `-i ~/.ssh/one_key root@...` (see `feedback_gr_pve_ssh` memory).
- | gr-pve01 | i9-12900H | 14C/20T | 101 GB | bond0 (1G) + bond1 (10G) | 1.9 TB ZFS + 2.0 TB ext4 | Primary GR hypervisor |
- 2. **gr-pve01 swap 99.8% exhausted** — 1.84x RAM overcommit, no balloon on any VM, 186 GB allocated vs 101 GB physical. Fix: enable ballooning, right-size LXCs, migrate guests to gr-pve02.
- 7. **gr-pve01 APT sources still on bookworm** — all others on trixie.

**nl:native/ncha/CLAUDE.md**
- | grnpm01 | — | gr-pve01 | 10.0.X.X | GR site entry point (DNS RR partner) |
- | grfreeipa01 | — | gr-pve01 | — | GR site replica. DNS RR partner + LDAP replication. |

**nl:native/smtp/CLAUDE.md**
- | `grsmtp-gpg01/` | grsmtp-gpg01 | 10.0.X.X | 201020204 / gr-pve01 | GPG encryption (zeyple) — GR site | **Live** — Debian 12 LXC, 2C / 1GB RAM / 10G disk, VLAN 2. In policy lock-step with NL as of 2026-04-26 |
- | `grsmtp-dkim01/` | grsmtp-dkim01 | 10.0.X.X | 201020205 / gr-pve01 | DKIM signing (14 domains) → independent leg, direct MX delivery from `203.0.113.X` | **Live** — Debian 12 LXC, 2C / 1GB RAM / 10G disk, VLAN 2. Signing all 14 domains as of 2026-05-04 |
- Both GR LXCs have been running since 2024-08-26 (≈30 d uptime as of last snapshot, 8+ months in service). They were never tracked in this repo until 2026-04-26; the parent `pve/gr-pve01/lxc/` directory was created during that catch-up.
- - `pve/gr-pve01/lxc/{201020204,201020205}.conf` — GR pair (added 2026-04-26)
- | `gsrruenl@mail.example.net` | gr-pve01 system mail |

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
- - **[P0] Full hostnames, no exceptions:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, nlcl01iot01 not iot01, nlcl01file02 not file02, gr-pve01 not pve01). Never use generic role labels ("the ASA", "the router", "the active node") as a substitute. Applies to all output: playbooks, comments, memory, YT, Matrix messages, tables, diagram labels, filenames. Reinforced 2026-04-30 after multiple session slips.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-08 | Devices up/down | GR devices showing down from NL LibreNMS perspective. Root c | Check NL ASA Freedom PPPoE status first: show vpdn pppinterf | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-381**: Freedom ISP PPPoE outages cause cascading NL+GR alerts (up/down on all NL devices + GR VPN-dependent devices). First check: show vpdn pppinterface on NL ASA. xs4all WAN takes over automatically via SLA track failover. Wait 15 min before investigating — most services self-recover.

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **GR ASA SSH requires stepstone via gr-pve01** (feedback): SSH to gr-fw01 only works via gr-pve01 as a jump host — direct SSH from NL is rejected (connection reset).
- **Never install tools on the Proxmox hosts — use the site oversight agent** (feedback): PVE hosts (nl-pve01/02/03, gr-pve01/02) are hypervisors — keep them clean. For Python/netmiko/pexpect/etc., use the site oversight claude agent (nl-claude01 for NL, grclaude01 for GR), which is the intended tool-host with full tooling pre-installed.
- **gr_chatops_infra** (project): GR site (gr) ChatOps infrastructure — complete multi-site alert pipeline, triage scripts, n8n workflows, kubeconfig, LibreNMS transport, Alertmanager webhook
- **GR Claude Agent (grclaude01)** (project): Claude Code agent at GR site for NL maintenance oversight. VMID 201021201, 10.0.X.X, gr-pve01.
- **ibgp_full_mesh_fix_20260413** (project): iBGP full mesh routing fix (2026-04-13). next-hop-self force + BFD + table-map SET_SRC. 18 baseline experiments validated. ASA 9.16 limitations documented. Needs IaC sync.
- **incident_dmz02_oom_shun_20260413** (project): grdmz02 OOM-killed twice on 2026-04-13, ASA shunned DMZ IP 10.0.X.X causing total network loss
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, dmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **Multi-layer incident 2026-04-17 — consolidated overview** (project): 4-layer cascade in one day — VTI IPsec SA stale, BGP ECMP asymmetric paths, DMZ disk-full, and silent playbook skips — each hid the next. This is the index; each layer has its own memory.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
- **VTI BGP outage investigation 2026-04-11** (project): NL-GR inter-site VTI tunnels down, BGP not peering, complete GR unreachability from NL. Root cause identified.

*Compiled: 2026-05-06 00:48 UTC*