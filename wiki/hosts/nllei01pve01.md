# nl-pve01

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- - **Hosts**: NL primary (nl-pve01/02/03), GR DR (gr-pve01/02).
- | List all nodes | `pve_list_nodes()` | `ssh nl-pve01 "pvecm nodes"` |
- | Cluster status | `pve_cluster_status()` | `ssh nl-pve01 "pvecm status"` |
- | nl-pve01 | Proxmox hypervisor (primary) | `ssh nl-pve01` |
- 1. Check if it's a K8s node: `ssh nl-pve01 "pct exec <vmid> -- kubectl get nodes"`

**nl:k8s/CLAUDE.md**
- - **kube-apiserver on ctrl01**: 754 restarts (exit code 137/SIGKILL) caused by etcd I/O starvation from PVE host memory pressure. Root cause: nl-pve01 ran 53 guests at 2.5x overcommit with zero swap, leaving only 1.9 GB free. etcd raft consensus latency 100-433ms (should be <10ms) causes apiserver readiness probe HTTP 500s (21,636 failures), then liveness probe kills it. Mitigated 2026-04-15: shut down nlandroidsdk01 (freed ~9.7 GB, host free 1.9->10 GB). Monitor: if restarts resume, further VM migration or swap addition needed.

**nl:native/pve/CLAUDE.md**
- scp root@nl-pve01:/etc/network/interfaces native/pve/nl-pve01/network/interfaces
- git add native/pve/nl-pve01/
- git commit -m "chore(native): sync pve host configs from nl-pve01"
- All 5 PVE hosts are directly SSH-reachable as `root` via the standard host aliases (`ssh nl-pve01`, …) — no `-i ~/.ssh/one_key` needed for NL; GR hosts (`gr-pve01/02`) do require `-i ~/.ssh/one_key root@...` (see `feedback_gr_pve_ssh` memory).
- | nl-pve01 | i9-12900H | 14C/20T | 101 GB | bond0 (802.3ad, 10G) | 3.7 TB ZFS | Primary NL hypervisor |

**nl:native/ncha/CLAUDE.md**
- **Check:** `ssh nl-pve01 "pct exec VMID_REDACTED -- ipactl status"` (all 9 services should be RUNNING)

**nl:native/smtp/CLAUDE.md**
- | `nlsmtp-gpg01/` | nlsmtp-gpg01 | 10.0.181.X | VMID_REDACTED / nl-pve01 | GPG encryption (zeyple) | **Live** — Debian 12 LXC, 2C / 1GB RAM / 10G disk, VLAN 10 |
- | `nlsmtp-dkim01/` | nlsmtp-dkim01 | 10.0.181.X | VMID_REDACTED / nl-pve01 | DKIM signing (14 domains) + final outbound relay | **Live** — Debian 12 LXC, 2C / 1GB RAM / 10G disk, VLAN 10 |
- - `pve/nl-pve01/lxc/{VMID_REDACTED,VMID_REDACTED}.conf` — NL pair
- - `pve/nl-pve01/lxc/VMID_REDACTED.conf`, `VMID_REDACTED.conf` — NL LXC definitions (GitOps source of truth)

**nl:pve/CLAUDE.md**
- | nl-pve01 | Venus Series Mini PC | i9-12900H (20T) | 96 GB | NVMe ZFS | 75 | 8 |
- ├── nl-pve01/
- | `nl-pve01-local-zfs` | Local ZFS | 72 LXC, 6 QEMU | Performance workloads |

**gateway:CLAUDE.md**
- - **HAHA + FISHA reliability hardening (2026-04-30)** — closed IFRNLLEI01PRD-704, -801, -802, -803, -804, -805, -815 in one session after the 2026-04-27→04-30 ~66h HAHA outage. Memory entries: [`incident_haha_nfs_stale_fh_20260430.md`](memory/incident_haha_nfs_stale_fh_20260430.md), [`haha_reliability_hardening_20260430.md`](memory/haha_reliability_hardening_20260430.md), [`haha_chaos_engineering_20260430.md`](memory/haha_chaos_engineering_20260430.md). Components live: (a) `monitor_cmd` on all 5 OCF docker resources (HA `/manifest.json`, ESPHome `/`, Z2M wget, Node-RED `/`, Mosquitto `nc -z 1883`); (b) start/stop timeouts raised from 90s to 120-180s on the 4 sidecar resources to avoid fence-on-restart (caught by chaos C9); (c) `nfs-stale-fh-exporter.py` (HTTP/1.1 ThreadingHTTPServer, port 9101) on file01/02 + `exportfs-flush-webhook.py` (port 9107, bearer-token, IP-allowlist 10.0.X.X/27 + 10.0.181.X/24) on file01/02; (d) Pacemaker alert `alert_post_nfs_flush` on FISHA + `clear_arp_nfs.sh` on iot01/02 wired to call the exportfs-flush webhook on `p_fs_iot start` failures with stale-fh signature; (e) `alertmanager-twilio-bridge.py` user-systemd service on nl-claude01:9106 + Alertmanager `twilio-tier1` route matching `tier=1, severity=critical`; (f) Gatus `custom` Twilio provider with API-Key auth (`/srv/atlantis/twilio.env` env_file mounted into Atlantis runner), tier-1 endpoints for HA + NL K8s API + FISHA file01 + FISHA file02; (g) 7 PrometheusRules — `NFSStaleFhPoisoning`, `NFSStaleFhExporterDown`, `NFSStaleFhExporterStalePackets`, `PVEMemoryPressureHigh/Critical`, `PVELoadHigh`, `PVEZramSwapNearFull`; (h) ARP refresh cron on iot01/02 every 5 min (`ping -c 1 -W 2 -I enp6s19 10.0.X.X`); (i) `fence_pve` Python TypeError patched with `dpkg-divert --rename` on iot01/02/iotarb01 + file01/02/filearb01 (survives `apt upgrade fence-agents-pve`); (j) IFRNLLEI01PRD-704 balloon floors set on 6 VMs on nl-pve01 (75% on HA-critical iot01+file01, 50% on others) + balloon device attached on nlk8s-ctrl01 — immediate 5 GiB host memory recovered, ~14 GiB total reclaimable headroom. **14-test chaos catalog run end-to-end**; 12 of 14 confidence rows now >0.90 detection AND recovery. Two rows at acknowledged structural ceilings (in-container freeze rec 0.85 = OCF docker agent limit; FISHA migration rec 0.85 = recorder DB on NFS by operator decision).
- ## Known Host Pressure: nl-pve01 (remediated 2026-04-19, re-drift 2026-04-22)
- n8n LXC (CT VMID_REDACTED, hostname `nl-n8n01`, 10.0.181.X) lives on **nl-pve01**. Two remediations landed 2026-04-19 after IFRNLLEI01PRD-622 (LXC cgroup OOM-kill every ~90 min, 69 lifetime events):
- - **[P0] Full hostnames, no exceptions:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, nlcl01iot01 not iot01, nlcl01file02 not file02, gr-pve01 not pve01). Never use generic role labels ("the ASA", "the router", "the active node") as a substitute. Applies to all output: playbooks, comments, memory, YT, Matrix messages, tables, diagram labels, filenames. Reinforced 2026-04-30 after multiple session slips.

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
- **pct exec hang with running status = host I/O starvation, not LXC crash** (feedback): When pct exec into an LXC times out but pct status returns "running" and the LXC's processes are visible in the PVE host's ps output, the cause is host-level memory/IO pressure starving the LXC's kernel scheduling — not LXC corruption. Don't reboot the LXC.
- **Never install tools on the Proxmox hosts — use the site oversight agent** (feedback): PVE hosts (nl-pve01/02/03, gr-pve01/02) are hypervisors — keep them clean. For Python/netmiko/pexpect/etc., use the site oversight claude agent (nl-claude01 for NL, grclaude01 for GR), which is the intended tool-host with full tooling pre-installed.
- **ibgp_full_mesh_fix_20260413** (project): iBGP full mesh routing fix (2026-04-13). next-hop-self force + BFD + table-map SET_SRC. 18 baseline experiments validated. ASA 9.16 limitations documented. Needs IaC sync.
- **Corosync cluster split incident 2026-04-11** (project): PVE 5-node cluster split — stale ASA conn table routed nl-pve01 knet via outside_freedom instead of VTI. Fixed by clear conn + timeout floating-conn on both ASAs.
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **HAHA NFS stale-fh outage 2026-04-27 → 2026-04-30 (RESOLVED, ~66h 39m)** (project): Home Assistant down 2026-04-27 14:55 → 2026-04-30 09:34 UTC (~66h 39m). HA Python crashed with Bus error during nfs-group migration; container kept running so Pacemaker never noticed. Apr 30 02:15 weekly-update reboot exposed file02 fh-cache poisoning. Fixed by restarting Pacemaker exportfs resource.
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 pve01 memory pressure class.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **IoT Pacemaker HA Cluster** (project): 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **Operational Activation Audit 2026-04-10** (project): Comprehensive audit scoring operational activation (not just implementation). 21/21 tables populated after remediation. 8 YT issues (445-452).
- **Pipeline Hardening (2026-04-01)** (project): 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
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

*Compiled: 2026-05-06 00:48 UTC*