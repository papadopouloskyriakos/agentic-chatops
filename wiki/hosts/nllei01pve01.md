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

**nl:edge/CLAUDE.md**
- │   ├── nl-dmz01/             — Netherlands, Leiden (QEMU on nl-pve01)
- │   ├── nldmz02/             — Netherlands, Leiden (QEMU on nl-pve01, second host, baseline only)
- │   ├── nlk8s-frr01/         — NL, nl-pve01 (VMID VMID_REDACTED)
- ├── nloas01/             — NL, nl-pve01 (VMID VMID_REDACTED) — port 443/tcp
- ├── nloas02/             — NL, nl-pve01 (VMID VMID_REDACTED) — port 888/tcp

**nl:native/pve/CLAUDE.md**
- scp root@nl-pve01:/etc/network/interfaces native/pve/nl-pve01/network/interfaces
- git add native/pve/nl-pve01/
- git commit -m "chore(native): sync pve host configs from nl-pve01"
- All 5 PVE hosts are directly SSH-reachable as `root` via the standard host aliases (`ssh nl-pve01`, …) — no `-i ~/.ssh/one_key` needed for NL; GR hosts (`gr-pve01/02`) do require `-i ~/.ssh/one_key root@...` (see `feedback_gr_pve_ssh` memory).
- | nl-pve01 | i9-12900H | 14C/20T | 101 GB | bond0 (802.3ad, 10G) | 3.7 TB ZFS | Primary NL hypervisor |

**nl:native/servarr/CLAUDE.md**
- Tracked in IFRNLLEI01PRD-202. Consolidated 14 individual LXC containers into a single Docker Compose stack on nlservarr01 (VMID VMID_REDACTED, nl-pve01).

**nl:native/ncha/CLAUDE.md**
- ├─ 10.0.181.X  nlhaproxy01 (nl-pve01) — nlnc01 PRIMARY, nlnc02 BACKUP
- ├─ 10.0.181.X  nlnc01 (QEMU, nl-pve01) — PRIMARY
- | nlnpm01 | VMID_REDACTED | nl-pve01 | 10.0.181.X | OpenResty 1.27.1. Proxies nextcloud.example.net to HAProxy. ~98 proxy configs total. |
- | nlhaproxy01 | VMID_REDACTED | nl-pve01 | 10.0.181.X | HAProxy 3.3.5. Frontends: HTTPS(:443), Redis(:6380), ProxySQL(:6034), Collabora(:9980), Stats(:8404). nlnc01=PRIMARY. |
- | nlnc01 | VMID_REDACTED | nl-pve01 | 10.0.181.X, 10.0.X.X | Nextcloud 32.0.6, PHP 8.4.18, Apache 2.4.58 |

**nl:native/smtp/CLAUDE.md**
- | `nlsmtp-gpg01/` | nlsmtp-gpg01 | 10.0.181.X | VMID_REDACTED / nl-pve01 | GPG encryption (zeyple) | **Live** — Debian 12 LXC, 2C / 1GB RAM / 10G disk, VLAN 10 |
- | `nlsmtp-dkim01/` | nlsmtp-dkim01 | 10.0.181.X | VMID_REDACTED / nl-pve01 | DKIM signing (14 domains) + final outbound relay | **Live** — Debian 12 LXC, 2C / 1GB RAM / 10G disk, VLAN 10 |
- - `pve/nl-pve01/lxc/{VMID_REDACTED,VMID_REDACTED}.conf` — NL pair
- - `pve/nl-pve01/lxc/VMID_REDACTED.conf`, `VMID_REDACTED.conf` — NL LXC definitions (GitOps source of truth)

**nl:native/haha/CLAUDE.md**
- | nlcl01iot01 | 666 | nl-pve01 | 10.0.181.X, 10.0.X.X | QEMU VM. 2C/2S, 4GB RAM, 64GB SSD. Active or passive (alternates each weekly update). |
- | `fence_iot01` | `fence_pve` | VMID 666 on nl-pve01 | Runs on iot02 |
- **nl-pve01:** iot01 (VMID 666) — passive node (after 2026-05-01 weekly update; resource group ping-pongs each cycle)
- **Key risk:** Whichever PVE host runs the active IoT node is the SPOF for the IoT stack. Currently nl-pve03 → iot02 active → if nl-pve03 dies, Pacemaker fences iot02 (SBD + fence_pve) and starts `g_iot_stack` on iot01 (nl-pve01). The reverse failover (nl-pve01 dying with iot01 active) is more dangerous because **nl-pve01 also hosts nlcl01file01** (NFS source for `/mnt/iot`) — losing nl-pve01 takes both iot01 AND the NFS server, so failover requires nlcl01file01→nlcl01file02 cutover to complete first.

**nl:docker/nlservarr01/servarr/pinchflat/CLAUDE.md**
- **Migration History**: Pinchflat was originally on a dedicated LXC (`nlpinchflat01`, VMID VMID_REDACTED on nl-pve01). Migrated 2026-03-27 to the consolidated servarr VM as part of IFRNLLEI01PRD-202. All 21 servarr LXCs were consolidated into a single Docker Compose stack.

**nl:docker/nlsearxng01/searxng/CLAUDE.md**
- Federated metasearch engine on `nlsearxng01` (LXC VMID_REDACTED on nl-pve01, IP 10.0.181.X).
- 1. Edit `/srv/searxng/...` directly via `ssh nl-pve01 "pct exec VMID_REDACTED -- bash"`
- 5. Sync back to repo: `ssh nl-pve01 "pct exec VMID_REDACTED -- cat /srv/searxng/<path>" > <repo path>`
- ssh nl-pve01 "pct exec VMID_REDACTED -- bash -c 'cd /srv/searxng && docker compose ps'"
- ssh nl-pve01 "pct exec VMID_REDACTED -- docker exec searxng ps -eo comm | grep -c 'searxng worker'"

**nl:pve/CLAUDE.md**
- | nl-pve01 | Venus Series Mini PC | i9-12900H (20T) | 96 GB | NVMe ZFS | 75 | 8 |
- ├── nl-pve01/
- | `nl-pve01-local-zfs` | Local ZFS | 72 LXC, 6 QEMU | Performance workloads |

**gateway:CLAUDE.md**
- ## Known Host Pressure: nl-pve01
- **CORRECTED 2026-06-30:** n8n LXC (`nl-n8n01`, CT VMID_REDACTED) is on **nlpve04**, confirmed live via `pvesh get /cluster/resources` (vmid VMID_REDACTED → node nlpve04). The prior "n8n lives on nl-pve01" was stale VMID-node-digit decode drift — n8n was NOT affected by the 2026-06-30 nl-pve01 power-cycle. **What IS on nl-pve01 (and pressured):** ~40 onboot LXCs/QEMUs incl. matrix (`nl-matrix01`, CT VMID_REDACTED), NPM (`nlnpm01`), FreeIPA, Pi-hole, scanner (`nlsec01`), NetBox, HAProxy, code-server, and NFS server (`nlcl01file01`). nl-pve01 has repeatedly **wedged its pmxcfs** under load (2026-06-23/-27/-30): the signature is `load-avg very high (100+) + CPU ~idle + guest status=unknown + D-state procs wchan=filename_create on /etc/pve` = hung pmxcfs (NOT CPU/IO). Wedge AMPLIFIER found 2026-06-30: `scripts/lab-stats.py` pinned its `pvesh /cluster/resources` to pve01 with no server-side timeout → each call during a stall strands a permanent D-state orphan (D-state ignores SIGKILL) → 134 piled → pmxcfs deadlock. Fixed: lab-stats now queries a healthy node first (pve03/04/02, pve01 last) + `timeout 20 pvesh` (claude-gateway MR !130, merged). Fix WITHOUT reboot (proven 2026-06-27 pve04): `systemctl restart pve-cluster` FIRST (FUSE teardown releases D-states) THEN `reset-failed pvestatd && restart pvestatd`. **Dedicated wedge detection LIVE 2026-06-30 (IFRNLLEI01PRD-1501):** the generic `NodeSaturation` alert mis-reads the wedge as CPU, and pve01 is NOT a node_exporter/snmp Prometheus target (so the existing `PVELoadHigh`/`PVEMemoryPressure*` rules in `host-pressure-alerts.tf` are silently inert for pve01). New chain: `scripts/write-pve-wedge-metrics.sh` on nl-claude01 (Cronicle `pve-wedge-metrics` `*/2`, id `emr0p04dnkl`) SSHes pve01 and emits `pve_wedge_*` (dstate_procs / pmxcfs_probe_seconds / pmxcfs_probe_ok / guests_status_unknown / collector_up / collector_last_run); 3 alerts in `host-pressure-alerts.tf` group `pve-pmxcfs-wedge` (infra MR !354, Atlantis-applied + merged, PrometheusRule gen 2): `PVEPmxcfsWedgeForming` (warn), `PVEPmxcfsWedged` (critical/tier1 → Twilio SMS), `PVEWedgeCollectorStale` (dead-man). See [`memory/pve01_pmxcfs_wedge_lab_stats_amplifier_20260630.md`](memory/pve01_pmxcfs_wedge_lab_stats_amplifier_20260630.md) + [`memory/feedback_pve_mgmt_wedge_pmxcfs_restart.md`](memory/feedback_pve_mgmt_wedge_pmxcfs_restart.md).
- Full detail (remediation steps, IFRNLLEI01PRD-622/-692/-704 history, prior failure modes): [`.claude/rules/infrastructure.md`](.claude/rules/infrastructure.md) §"Known Host Pressure: nl-pve01".
- - **[P0] Full hostnames, no exceptions:** ALWAYS use full site-prefixed hostnames (nl-pve01 not pve01, nlcl01iot01 not iot01, nlcl01file02 not file02, gr-pve01 not pve01). Never use generic role labels ("the ASA", "the router", "the active node") as a substitute. Applies to all output: playbooks, comments, memory, YT, Matrix messages, tables, diagram labels, filenames. Reinforced 2026-04-30 after multiple session slips.
- - **Fleet-wide LibreNMS extender hardening + apcupsd + smart.config sweep + nlpve04 PBS backup unstuck (2026-05-15):** Multi-track session covering all 6 PVE hosts (NL pve01-04 + GR pve01-02). **nlpve04 went from bare → 7 extenders + apcupsd + smart.config + functional pbc-host-backup.sh** (the backup had been silently failing 5× weekly since 2026-05-10 onboarding because the PBS fingerprint trust file was never copied across). **proxmox-extender now uses cache pattern fleet-wide** (`*/5 cron writes /var/cache/proxmox`, snmpd just `cat`s it) — bypasses the `/etc/pve/priv/authkey.key` root-only requirement that made the snmpd-as-Debian-snmp proxmox extender fail with `exit=13 cfs-lock 'authkey' error` on every host. Rejected sudo-prefix (Fabian Grünbichler: "sudo is not the right way to implement unprivileged services") and `Debian-snmp → www-data` (PVE locks `/etc/pve/priv/` at mode 700 — group bits zero, group membership doesn't help). **apcupsd installed on nl-pve03+nlpve04** using nl-pve01's existing SNMP-over-Ethernet config (shared `10.0.181.X` APC Smart-UPS 1500, no USB needed). **smart.config sweep** caught stale `# smart.config for gr-pve01` clone-artifact headers on nl-pve01+nl-pve03 (now fixed; nl-pve01 also had a phantom `nvme1` line for an empty M.2 slot — real disks are FireCuda 530 at nvme0+nvme2) AND an essentially-empty smart.config on gr-pve02 despite 5 real disks (rewrote with 3 SCSI + 2 MegaRAID, all 5 now reporting). End-to-end verified via NL LibreNMS API (device_id 23/27/58/155) + GR LibreNMS API (device_id 34/35) — all 7 apps OK on every host. Side-finds: `alertmanager-twilio-bridge.service` runs as systemd `--user` inside nl-claude01 LXC at `oom_score_adj=200` — preferred OOM victim by design; left in place per operator decision but flagged. Full memory: [`memory/librenms_extender_fleet_deployment_20260515.md`](memory/librenms_extender_fleet_deployment_20260515.md). Architectural patterns: [`memory/feedback_pve_root_extender_cache_pattern.md`](memory/feedback_pve_root_extender_cache_pattern.md) + [`memory/feedback_systemd_user_slice_oom_score.md`](memory/feedback_systemd_user_slice_oom_score.md) + updated [`memory/feedback_no_sudo_install_on_pve_hosts.md`](memory/feedback_no_sudo_install_on_pve_hosts.md). Pending follow-ups: vzdump job for nlpve04 in `/etc/pve/jobs.cfg` (workload still unbacked), stale node-pinned VMIDs in nl-pve01/nl-pve03 backup jobs.

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-08 | Service up/down | Multiple NL hosts showing Service up/down during Freedom ISP | Monitor and wait 15 minutes after Freedom drops. xs4all tunn | 0.9 |
| 2026-04-03 | Port status up/down. |  | Resolved via Claude session IFRNLLEI01PRD-282 | 0.9 |
| 2026-04-03 | Service up/down. |  | Resolved via Claude session IFRNLLEI01PRD-334 | 0.9 |
| 2026-03-25 | Service up/down | nl-pve01 oversubscribed: 80% RAM (75/94GB), 7 VMs (40GB) | Removed dangerous ZFS swapfile (orphaned, clears on reboot). | 0.9 |
| 2026-03-25 | Service up/down | PVE swap audit: nl-pve01 had 1GB swapfile on ZFS (deadlo | nl-pve01: removed ZFS swapfile (deadlocked on swapoff, c | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-282**: Port status up/down on PVE hosts typically indicates network interface flap during maintenance, storage failover, or bond reconfiguration. Check interface status and bond health.
- **IFRNLLEI01PRD-334**: Service up/down on PVE hosts (nl-pve01, nl-pve02) during cluster operations is expected. PVE services restart during HA migration, storage maintenance, or kernel updates. Correlate with maintenance window.
- **IFRNLLEI01PRD-381**: Freedom ISP PPPoE outages cause cascading NL+GR alerts (up/down on all NL devices + GR VPN-dependent devices). First check: show vpdn pppinterface on NL ASA. xs4all WAN takes over automatically via SLA track failover. Wait 15 min before investigating — most services self-recover.
- **IFRNLLEI01PRD-255**: NEVER use swap on ZFS (swapfile or zvol). Proxmox explicitly warns: swapoff deadlocks. nl-pve01 proved it — swapoff hung, orphaned swap only clears on reboot. For ZFS hosts, use swap partition on physical disk outside ZFS, or no swap at all.
- **IFRNLLEI01PRD-255**: nl-pve01 cascading failures: when nl-pve01 load spikes (>50), expect apiserver crashes on nlk8s-ctrl01, iot01 VM shutdown, and service check failures across multiple hosts. Root cause is always RAM oversubscription. Check nl-pve01 first before investigating individual alerts.

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **apiserver-ctrl01-balloon-chronic-restart-fixed-20260515** (project): "RESOLVED 2026-05-15. nlk8s-ctrl01's kube-apiserver had restartCount=1665 (~27 days of crash-looping, ~24-min cycle). Root cause was the balloon device on the underlying VM (VMID_REDACTED on nlpve04) inflating during host pressure events, leaving the VM with only 3.7 GiB instead of 8 GiB. etcd's WAL/DB page cache got evicted → fsyncs disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kill → restart. Fix: `qm set --balloon 0` + VM reboot to apply [PENDING] (config change cannot live-remove a balloon device)."
- **CLAUDE.md refactor 2026-05-06 — 52.6 KB → 24.9 KB** (project): Distributed dated content out of CLAUDE.md to existing referenced files (platform-features.md, infrastructure.md, llm-usage-tracking.md, memory/*) to clear the 40 KB performance threshold. No information loss; 35/35 cross-file pointers resolve. Allocation table added at CLAUDE.md bottom to prevent regrowth.
- **defra01agri01 — agentic system mirror target** (project): Designated mirror target for gradual deploy of the NL agentic system (n8n + Claude Code + RAG + chaos). Access + baseline specs.
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **LibreNMS check_cororings hard-codes expected cluster size in every service** (feedback): Every PVE node has its own check_cororings service with a hard-coded --rings N. Adding/removing a node requires PATCHing N services on both LibreNMS instances.
- **pct exec hang with running status = host I/O starvation, not LXC crash** (feedback): When pct exec into an LXC times out but pct status returns "running" and the LXC's processes are visible in the PVE host's ps output, the cause is host-level memory/IO pressure starving the LXC's kernel scheduling — not LXC corruption. Don't reboot the LXC.
- **feedback_never_abbreviate_hostnames** (feedback): "[P0] NEVER abbreviate or truncate a hostname — always the complete site-prefixed name (gr-pve01 not gr, nl-pve01 not pve01). Operator-anger rule, reinforced 2026-06-24."
- **Never install tools on the Proxmox hosts — use the site oversight agent** (feedback): PVE hosts (nl-pve01/02/03, gr-pve01/02) are hypervisors — keep them clean. For Python/netmiko/pexpect/etc., use the site oversight claude agent (nl-claude01 for NL, grclaude01 for GR), which is the intended tool-host with full tooling pre-installed.
- **feedback-no-balloon-on-k8s-control-plane** (feedback): "Never run k8s control-plane VMs (kube-apiserver / etcd / scheduler / controller-manager) with an active Proxmox balloon device. etcd is fsync-sensitive; when host pressure causes balloon to reclaim guest memory, etcd's WAL/DB page cache gets evicted → fsyncs become disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kills → restart cycle. Caught 2026-05-15: nlk8s-ctrl01 had 1665 restarts (27 days of crash-looping) because of this."
- **feedback-no-sudo-install-on-pve-hosts** (feedback): "Don't reach for `sudo` (install it OR sudo-prefix invocations) to bridge a permission gap on a PVE host. The Proxmox-staff position is \"sudo is not the right way to implement unprivileged services\" (Fabian Grünbichler). All 6 NL+GR PVE hosts in this estate happen to have sudo installed from legacy setup, but new fixes should use PVE-native patterns (cache-pattern cron for snmpd extenders, pveum ACLs for delegated admin, system systemd units for services)."
- **no-zramswap-on-pve-hosts** (feedback): Do not propose or apply zramswap (or any swap) on PVE hosts as a memory-pressure remediation — Proxmox does not officially recommend swap on hypervisors. Find another lever.
- **feedback-pve-root-extender-cache-pattern** (feedback): "For any LibreNMS / snmpd extender on a PVE host that needs root-only access (e.g. `/etc/pve/priv/authkey.key` for the `proxmox` app), DO NOT use sudo-prefix or www-data group hackery. Use the PVE-native cache pattern that `/etc/snmp/smart` already uses: cron writes data to /var/cache, snmpd just `cat`s it."
- **feedback_verify_belief_not_rationalize_observation** (feedback): "When an observation contradicts what you \"know\", the BELIEF is the suspect — verify it, don't invent a cause to defend it. Never attribute a cause to a host without the full site-prefixed hostname + a confirming fact (uptime/log), especially across same-named hosts."
- **freeipa01-httpd-scoreboard-outage-20260529** (project): "2026-05-29. nlfreeipa01 webui unreachable for 5d — httpd mpm_event scoreboard full since Sun May 24 00:00:11. Fixed short-term by LXC reboot. Two reusable findings — IPA host missing from LibreNMS (silent), chronic MPM tuning gap."
- **gitlab_runner_topology** (project): NL + GR internal GitLab each have ONE online runner with run_untagged=false. NL failure mode = saturation (queued_duration>30m). GR failure mode = tag-less jobs hang 2h → stuck_or_timeout_failure.
- **gpu01-zfs-dio-race-root-cause-20260514** (project): "nl-gpu01 (VM VMID_REDACTED) \"frozen daily with io-error\" was OpenZFS 2.3 dio_verify_wr race with QEMU cache=none/aio=io_uring. Fixed by setting direct=disabled on rpool across all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04, GR: gr-pve01/gr-pve02) + zfs_dio_enabled=0 modprobe.d safety net."
- **HAHA chaos engineering catalog 2026-04-30 (~14 tests, 2 bugs surfaced+fixed)** (project): Same-day chaos engineering pass over the whole IoT infrastructure (HAHA + FISHA + sidecars + voice pipeline + cluster fencing). 14 tests run, 2 real bugs surfaced and 1 fixed (nodered start timeout 90s→180s); 1 outstanding (fence_pve list TypeError, IFRNLLEI01PRD-806). Empirical confidence table inside.
- **HAHA reliability hardening 2026-04-30 (Phases 1-5 implemented)** (project): Same-day follow-up after the 2026-04-27 → 2026-04-30 ~66h HAHA outage. App-level OCF docker monitor_cmd, NFS auto-flush, NFS stale-fh exporter, proactive ARP, host-pressure alerts, Twilio escalation. T1 e2e verified: 18s detect, 3m30s recover.
- **Holistic agentic health script — 100% pass (78/78)** (project): scripts/holistic-agentic-health.sh tests ALL README-claimed features across 20 sections. First run 91% (5 fixes needed), second run 100%.
- **hostname_deabbreviation_sweep_20260624** (project): 2026-06-24 estate-wide hostname de-abbreviation — all docs across the 4 IaC-relevant repos to 0 bare, verified + merged; guard + CI gate + bidirectional [P0] rule shipped
- **ibgp_full_mesh_fix_20260413** (project): iBGP full mesh routing fix (2026-04-13). next-hop-self force + BFD + table-map SET_SRC. 18 baseline experiments validated. ASA 9.16 limitations documented. Needs IaC sync.
- **Corosync cluster split incident 2026-04-11** (project): PVE 5-node cluster split — stale ASA conn table routed nl-pve01 knet via outside_freedom instead of VTI. Fixed by clear conn + timeout floating-conn on both ASAs.
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **GR Site Isolation 2026-04-17 (stale IPsec SA)** (project): NL↔GR VTI/BGP break 2026-04-17 ~05:23 UTC. Root cause = stale IPsec SA on Tunnel4 (Freedom VTI). Fix = `clear crypto ipsec sa peer 203.0.113.X` on NL ASA. Resolved 08:48 UTC.
- **HAHA NFS stale-fh outage 2026-04-27 → 2026-04-30 (RESOLVED, ~66h 39m)** (project): Home Assistant down 2026-04-27 14:55 → 2026-04-30 09:34 UTC (~66h 39m). HA Python crashed with Bus error during nfs-group migration; container kept running so Pacemaker never noticed. Apr 30 02:15 weekly-update reboot exposed nlcl01file02 fh-cache poisoning. Fixed by restarting Pacemaker exportfs resource.
- **Multi-layer incident 2026-04-17 — consolidated overview** (project): 4-layer cascade in one day — VTI IPsec SA stale, BGP ECMP asymmetric paths, DMZ disk-full, and silent playbook skips — each hid the next. This is the index; each layer has its own memory.
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by nl-pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 nl-pve01 memory pressure class.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **infragraph-epic-state-20260609** (project): "Infragraph epic IFRNLLEI01PRD-1029 FINAL STATE — model-based control LIVE 2026-06-09 (13/16 done, system active, first rule -1046 approved); canonical record in repo memory/infragraph_epic_buildout_20260609.md"
- **IoT Pacemaker HA Cluster** (project): 3-node Pacemaker/Corosync IoT cluster (nlcl01iot01/nl-iot02/nlcl01iotarb01) — topology, resources, failover behavior, VMID 666
- **kyriakos-portfolio-sitewide-audit-20260619** (project): "2026-06-19 full-site audit + fixes of kyriakos.papadopoulos.tech — 8 merged MRs (!18-!25), canonical infra numbers, verifiable certs, CV redesign"
- **LibreNMS cororings threshold + nlpve04 onboarding 2026-05-10** (project): Bumped 5 cororings services from --rings 5 to 6 on NL+GR LibreNMS after nlpve04 onboarding. Also added nlpve04 itself as NL device 155 + cororings svc 40. snmpd-clone trap caught mid-flight.
- **librenms-extender-fleet-deployment-20260515** (project): "2026-05-15 fleet-wide LibreNMS extender deployment and hardening. nlpve04 got all 7 extenders from scratch (was bare). proxmox-extender switched to smart-style cache pattern on all 6 PVE hosts to bypass the /etc/pve/priv/authkey.key root-only requirement. apcupsd installed on nl-pve03+nlpve04 (shared SNMP UPS at 10.0.181.X). smart.config fleet sweep found stale gr-pve01 header on nl-pve01+nl-pve03 (now fixed) and empty config on gr-pve02 (5 disks now monitored, incl 2 MegaRAID)."
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **n8n OOM outage + Restart= drop-in (2026-05-11)** (project): 4h n8n outage (06:50-10:48 UTC) — OOM-killed inside the LXC, sat dead because n8n.service had Type=simple with NO Restart= directive. Operator-reported via "both pages live stats widgets are offline". n8n LXC has migrated from nl-pve01 to nlpve04 since the 2026-04-22 Known Host Pressure note in CLAUDE.md.
- **omktst01_cloudinit_bootcmd_hang_20260624** (project): "2026-06-24 RCA+fix: nlomktst01 (omoikane.coach BENCHMARK host, NOT a test VM) wedged ~6 days — cloud-init bootcmd `systemctl enable --now qemu-guest-agent` deadlocks boot. Fixed via --no-block."
- **OpenClaw v2026.4.22 Upgrade Audit** (project): Pre-decision audit of OpenClaw v2026.4.22 (released 2026-04-23) vs our running v2026.4.11. 11 tags / 716 commits ahead. Relevant fixes, traps, non-applicable items, three paths. DECISION PENDING.
- **Operational Activation Audit 2026-04-10** (project): Comprehensive audit scoring operational activation (not just implementation). 21/21 tables populated after remediation. 8 YT issues (445-452).
- **Pipeline Hardening (2026-04-01)** (project): 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.
- **pmxcfs_wedge_alert_build_20260630** (project): "Built the pmxcfs-wedge Prometheus alert (IFRNLLEI01PRD-1501). KEY: pve01 is NOT a Prometheus target so the existing PVELoadHigh rules are silently dead; collector runs on claude01."
- **portfolio-lab-page-rebuild-schedule-20260609** (project): "2026-06-09. kyriakos.papadopoulos.tech/lab/ auto-updates via Hugo CI build-time bake of data/lab_stats.json from n8n /webhook/lab-stats (lab-stats.py → NetBox+kubectl+ZFS). Rebuild schedule id=2 on GitLab project 9 is cron `0 * * * *` (HOURLY) despite being labeled \"5m\" and drawio saying \"*/5 cron\" — discrepancy, not yet fixed."
- **postiz_migration_gr_to_nl_20260624** (project): 2026-06-24 migrated grpostiz01 (privileged Docker LXC) cross-site to nlpostiz01 on nlpve04 to relieve gr-pve01 memory pressure (the chronic etcd-cascade root). Full DNS/NPM/e2e done.
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on nlk8s-ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.
- **pve01_pmxcfs_wedge_20260630** (project): nl-pve01 pmxcfs wedge killed matrix; lab-stats.py was the orphan amplifier; n8n is on pve04 NOT pve01.
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **nl-pve03 capacity pressure (2026-04-22)** (project): nl-pve03 mirrors pre-remediation nl-pve01 pattern — no swap/zram, sustained 92%+ memory, hosts K8s ctrlr+NMS+GPU inference. Apply same zram fix; OOM blast radius is the K8s control-plane share + LibreNMS + Ollama inference simultaneously.
- **nlpve04 onboarding (COMPLETED)** (project): ASRock GENOAD8X-2T/BCM (AMD EPYC 9334 32C/64T, 128GB DDR5, 6TB max) onboarded as 6th cluster member nlpve04. Clone-of-pve02 corosync rejection → identity wipe → rename → join.
- **pve04_pvestatd_wedge_20260625** (project): nlpve04 PVE-management wedge (pvestatd D-state, cluster status=unknown, claude01 LXC OOM). RESOLVED 2026-06-27 WITHOUT a reboot — `systemctl restart pve-cluster` (un-hangs pmxcfs, releases D-state) THEN `restart pvestatd`. The 06-25 "reboot is the ONLY fix" was WRONG. IFRNLLEI01PRD-1419.
- **PVE drift jobs can 1h-timeout on inventory blinks** (project): sync_pve_drift / detect_pve_lxc_drift can run for an hour deleting dozens of LXCs after a transient PVE inventory blink — needs a sanity cap.
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
- **screenity-selfhost-deploy-20260622** (project): "2026-06-22 IN-PROGRESS — self-hosting Screenity as a dockerized nginx distribution LXC nlscreenity01 on nlpve04; VMID/IP/DNS/NPM plan locked, not yet executed."
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.
- **VPS BGP VTI update-source fix** (project): GR VPS peering used loopback IPs causing ASA next-hop resolution failure + cross-tunnel ECMP asymmetric routing. Fixed 2026-04-14.
- **youtrack_infra_board_triage_20260627** (project): 2026-06-27 triage of open NL/GR infra YouTrack issues. NL=31 open (17 work / 14 alert-generated), GR=4 (1 work / 3 alert). Systemic gap = alert→YT issues auto-CREATE but never auto-CLOSE → noise accrues. 2 genuinely-real items: NL-1333 (pve01 rpool DEGRADED) + GR-85 (bricked PiKVM). ~9 done-this-session items still open.
- **yt_triage_alert_remediation_20260625** (project): 2026-06-25 YouTrack triage (8 issues closed with evidence) + the IFRNLLEI01PRD-1408 commit-label mislabel finding + active-alert remediation (in progress).

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

*Compiled: 2026-07-03 04:30 UTC*