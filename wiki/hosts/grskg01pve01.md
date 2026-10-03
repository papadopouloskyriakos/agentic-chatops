# gr-pve01

**Site:** GR (Skagkia)

## Knowledge Base References

**nl:CLAUDE.md**
- - **Hosts**: NL primary (nl-pve01/02/03), GR DR (gr-pve01/02).
- | 06:20 | Cert Sync - Proxmox | pve01/02/03, gr-pve01/02 | `systemctl restart pveproxy` |

**nl:edge/CLAUDE.md**
- │   ├── gr-dmz01/             — Greece, Thessaloniki (QEMU on GR gr-pve01)
- │   ├── grdmz02/             — Greece, Thessaloniki (QEMU on GR gr-pve01, second host, runs agri Django app)
- ├── groas01/             — GR, gr-pve01 (VMID 201110501) — port 443/tcp
- ├── groas02/             — GR, gr-pve01 (VMID 201110502) — port 888/tcp
- └── groas03/             — GR, gr-pve01 (VMID 201110503) — port 999/udp

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
- - **Fleet-wide LibreNMS extender hardening + apcupsd + smart.config sweep + nlpve04 PBS backup unstuck (2026-05-15):** Multi-track session covering all 6 PVE hosts (NL pve01-04 + GR pve01-02). **nlpve04 went from bare → 7 extenders + apcupsd + smart.config + functional pbc-host-backup.sh** (the backup had been silently failing 5× weekly since 2026-05-10 onboarding because the PBS fingerprint trust file was never copied across). **proxmox-extender now uses cache pattern fleet-wide** (`*/5 cron writes /var/cache/proxmox`, snmpd just `cat`s it) — bypasses the `/etc/pve/priv/authkey.key` root-only requirement that made the snmpd-as-Debian-snmp proxmox extender fail with `exit=13 cfs-lock 'authkey' error` on every host. Rejected sudo-prefix (Fabian Grünbichler: "sudo is not the right way to implement unprivileged services") and `Debian-snmp → www-data` (PVE locks `/etc/pve/priv/` at mode 700 — group bits zero, group membership doesn't help). **apcupsd installed on nl-pve03+nlpve04** using nl-pve01's existing SNMP-over-Ethernet config (shared `10.0.181.X` APC Smart-UPS 1500, no USB needed). **smart.config sweep** caught stale `# smart.config for gr-pve01` clone-artifact headers on nl-pve01+nl-pve03 (now fixed; nl-pve01 also had a phantom `nvme1` line for an empty M.2 slot — real disks are FireCuda 530 at nvme0+nvme2) AND an essentially-empty smart.config on gr-pve02 despite 5 real disks (rewrote with 3 SCSI + 2 MegaRAID, all 5 now reporting). End-to-end verified via NL LibreNMS API (device_id 23/27/58/155) + GR LibreNMS API (device_id 34/35) — all 7 apps OK on every host. Side-finds: `alertmanager-twilio-bridge.service` runs as systemd `--user` inside nl-claude01 LXC at `oom_score_adj=200` — preferred OOM victim by design; left in place per operator decision but flagged. Full memory: [`memory/librenms_extender_fleet_deployment_20260515.md`](memory/librenms_extender_fleet_deployment_20260515.md). Architectural patterns: [`memory/feedback_pve_root_extender_cache_pattern.md`](memory/feedback_pve_root_extender_cache_pattern.md) + [`memory/feedback_systemd_user_slice_oom_score.md`](memory/feedback_systemd_user_slice_oom_score.md) + updated [`memory/feedback_no_sudo_install_on_pve_hosts.md`](memory/feedback_no_sudo_install_on_pve_hosts.md). Pending follow-ups: vzdump job for nlpve04 in `/etc/pve/jobs.cfg` (workload still unbacked), stale node-pinned VMIDs in nl-pve01/nl-pve03 backup jobs.
- - **nl-gpu01 / VM VMID_REDACTED io-error freeze TRUE root cause = ZFS DIO race (2026-05-14, IFRNLLEI01PRD-900, fix on all 6 PVE hosts):** The 2026-05-12 `discard=on` + memory bump (IFRNLLEI01PRD-892, now closed-as-hardening) was a useful hardening layer but never RC. Real cause: **OpenZFS 2.3+ Direct-I/O verify-write race** with QEMU `cache=none` (`cache.direct=true`) + `aio=io_uring` against qcow2 on a ZFS dataset. Stack: PVE **9.1.9** kernel `6.17.2-2-pve` with ZFS **2.4.1-pve1** — exactly the configuration affected by the known PVE 9 / ZFS 2.3+ regression. Mechanism: QEMU does zero-copy DMA from its userspace buffer; ZFS 2.3+ post-write verify-CRC catches any guest mutation of that page mid-flight (ollama loading models maximises this); on mismatch ZFS returns EIO; qcow2's cluster-allocation path **maps EIO → ENOSPC** internally; QEMU `werror=enospc,stop` pauses the VM with bogus "nospace" status (pool was 52 % full). 121 cumulative `ereport.fs.zfs.dio_verify_wr` events over 2 months mapped 1:1 to freeze incidents. Fix is 3-layer on every PVE host: `zfs set direct=disabled <pool>` + `/etc/modprobe.d/zfs-dio-disable.conf` (`options zfs zfs_dio_enabled=0`) + runtime `echo 0 > /sys/module/zfs/parameters/zfs_dio_enabled`. Per `man zfsprops`, `disabled` is "the default behavior for OpenZFS 2.2 and prior releases" — zero risk, just reverts to pre-2.3 behavior, ARC absorbs writes via buffered path. Applied to all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04 with `rpool`, nl-pve02 module-only; GR: gr-pve01 with `rpool`, gr-pve02 with `ssd-pool`). Drift-check: `scripts/check-zfs-dio-disabled.sh` (PASS = all hosts safe). VM resumed cleanly, 110k subsequent writes, zero new DIO errors. **Important nuance:** the `direct=disabled` workaround is community-validated (multiple PVE 9 `[SOLVED]` forum threads converge on it) but **NOT in any pve.proxmox.com wiki page** — no Proxmox staff endorsement found. Don't ever claim "it's the official Proxmox recommendation" — say "OpenZFS-documented + community-validated PVE 9 workaround for the ZFS 2.3+ DIO regression." `cache=none` itself IS Proxmox-official for ZFS-backed VMs. Follow-ups: (1) re-run drift-check + DIO error count on 2026-05-21 to verify fix held under sustained ollama load; (2) optionally file a Proxmox forum thread to push for official documentation; (3) re-evaluate at next PVE major upgrade. Detail in [`.claude/rules/infrastructure.md`](.claude/rules/infrastructure.md) §"Known Host: nl-gpu01". Full memory: [`memory/gpu01_zfs_dio_race_root_cause_20260514.md`](memory/gpu01_zfs_dio_race_root_cause_20260514.md) (includes Research validation section). Feedback for all future PVE-onboarding work: [`memory/feedback_zfs_dio_must_be_disabled_on_pve.md`](memory/feedback_zfs_dio_must_be_disabled_on_pve.md). Diagnostic recipe: [`memory/feedback_zfs_dio_diagnostic_recipe.md`](memory/feedback_zfs_dio_diagnostic_recipe.md).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-04-08 | Devices up/down | GR devices showing down from NL LibreNMS perspective. Root c | Check NL ASA Freedom PPPoE status first: show vpdn pppinterf | 0.9 |

## Lessons Learned

- **IFRNLLEI01PRD-381**: Freedom ISP PPPoE outages cause cascading NL+GR alerts (up/down on all NL devices + GR VPN-dependent devices). First check: show vpdn pppinterface on NL ASA. xs4all WAN takes over automatically via SLA track failover. Wait 15 min before investigating — most services self-recover.

## Related Memory Entries

- **03_Lab Reference Library Integration** (project): 03_Lab (~10GB, ~5200 files) integrated into ChatOps/ChatSecOps triage as supplementary reference. lab-lookup skill, SOUL.md, CLAUDE.md, infra-triage Step 2d, k8s-triage Step 2e, Runner Build Prompt labRefStep.
- **alerting_dispositions_silences_20260624** (project): "2026-06-24 alerting policy + the 'silence forever the not-actionable' silences created (GR etcd cascade, NL AS64512CountLow/InfragraphPrecisionDrop), killers kept live. Plus the NL-etcd-unmonitored gap."
- **apiserver-ctrl01-balloon-chronic-restart-fixed-20260515** (project): "RESOLVED 2026-05-15. nlk8s-ctrl01's kube-apiserver had restartCount=1665 (~27 days of crash-looping, ~24-min cycle). Root cause was the balloon device on the underlying VM (VMID_REDACTED on nlpve04) inflating during host pressure events, leaving the VM with only 3.7 GiB instead of 8 GiB. etcd's WAL/DB page cache got evicted → fsyncs disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kill → restart. Fix: `qm set --balloon 0` + VM reboot to apply [PENDING] (config change cannot live-remove a balloon device)."
- **awx-default-group-zero-capacity-20260620** (project): "2026-06-20 NL AWX default instance-group capacity=0 → all kyriakos portfolio deploys stuck pending → CI timeout. Infra outage, not a code bug."
- **dmz_chaos_engineering** (project): DMZ cluster monitoring + web service chaos engineering implementation (2026-04-10). Graph redesign, safety calculator, 7 scenarios.
- **feedback-always-netmiko-for-cisco** (feedback): "ALWAYS use netmiko (device_type cisco_asa / cisco_ios) for ANY Cisco ASA/IOS access — never sshpass, expect, or raw ssh/paramiko command-channel."
- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **GR ASA SSH requires stepstone via gr-pve01** (feedback): SSH to gr-fw01 only works via gr-pve01 as a jump host — direct SSH from NL is rejected (connection reset).
- **LibreNMS check_cororings hard-codes expected cluster size in every service** (feedback): Every PVE node has its own check_cororings service with a hard-coded --rings N. Adding/removing a node requires PATCHing N services on both LibreNMS instances.
- **feedback_never_abbreviate_hostnames** (feedback): "[P0] NEVER abbreviate or truncate a hostname — always the complete site-prefixed name (gr-pve01 not gr, nl-pve01 not pve01). Operator-anger rule, reinforced 2026-06-24."
- **Never install tools on the Proxmox hosts — use the site oversight agent** (feedback): PVE hosts (nl-pve01/02/03, gr-pve01/02) are hypervisors — keep them clean. For Python/netmiko/pexpect/etc., use the site oversight claude agent (nl-claude01 for NL, grclaude01 for GR), which is the intended tool-host with full tooling pre-installed.
- **feedback-no-balloon-on-k8s-control-plane** (feedback): "Never run k8s control-plane VMs (kube-apiserver / etcd / scheduler / controller-manager) with an active Proxmox balloon device. etcd is fsync-sensitive; when host pressure causes balloon to reclaim guest memory, etcd's WAL/DB page cache gets evicted → fsyncs become disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kills → restart cycle. Caught 2026-05-15: nlk8s-ctrl01 had 1665 restarts (27 days of crash-looping) because of this."
- **feedback-no-sudo-install-on-pve-hosts** (feedback): "Don't reach for `sudo` (install it OR sudo-prefix invocations) to bridge a permission gap on a PVE host. The Proxmox-staff position is \"sudo is not the right way to implement unprivileged services\" (Fabian Grünbichler). All 6 NL+GR PVE hosts in this estate happen to have sudo installed from legacy setup, but new fixes should use PVE-native patterns (cache-pattern cron for snmpd extenders, pveum ACLs for delegated admin, system systemd units for services)."
- **no-zramswap-on-pve-hosts** (feedback): Do not propose or apply zramswap (or any swap) on PVE hosts as a memory-pressure remediation — Proxmox does not officially recommend swap on hypervisors. Find another lever.
- **feedback-pve-lock-backup-with-fleecing-image** (feedback): "PVE 8.2+ aborted-vzdump leaves stale `lock: backup` + `[special:fleecing]` block + orphan fleecing qcow2 — diagnostic signature, why it stays invisible until restart, recovery sequence"
- **feedback-pve-root-extender-cache-pattern** (feedback): "For any LibreNMS / snmpd extender on a PVE host that needs root-only access (e.g. `/etc/pve/priv/authkey.key` for the `proxmox` app), DO NOT use sudo-prefix or www-data group hackery. Use the PVE-native cache pattern that `/etc/snmp/smart` already uses: cron writes data to /var/cache, snmpd just `cat`s it."
- **feedback_verify_belief_not_rationalize_observation** (feedback): "When an observation contradicts what you \"know\", the BELIEF is the suspect — verify it, don't invent a cause to defend it. Never attribute a cause to a host without the full site-prefixed hostname + a confirming fact (uptime/log), especially across same-named hosts."
- **gpu01-zfs-dio-race-root-cause-20260514** (project): "nl-gpu01 (VM VMID_REDACTED) \"frozen daily with io-error\" was OpenZFS 2.3 dio_verify_wr race with QEMU cache=none/aio=io_uring. Fixed by setting direct=disabled on rpool across all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04, GR: gr-pve01/gr-pve02) + zfs_dio_enabled=0 modprobe.d safety net."
- **gr_chatops_infra** (project): GR site (gr) ChatOps infrastructure — complete multi-site alert pipeline, triage scripts, n8n workflows, kubeconfig, LibreNMS transport, Alertmanager webhook
- **GR Claude Agent (grclaude01)** (project): Claude Code agent at GR site for NL maintenance oversight. VMID 201021201, 10.0.X.X, gr-pve01.
- **gr_grk8s-ctrl01_etcd_gr-pve01_saturation_rca_20260623** (project): "2026-06-23 RCA of the GR etcd disk-I/O cascade behind the 91-SMS storm — root cause is chronic gr-pve01 host saturation + a thermally-throttling (SMART-clean, NOT failing) rpool mirror disk nvme2n1, NOT a ctrl01-specific fault. See VERIFIED UPDATE 2026-06-24 — the disk is overheating, not degraded; fix=cooling not replacement."
- **grvmorpheus-stuck-lock-backup-20260513** (project): "grvmorpheus (VMID 201061601) stuck `lock: backup` + dangling fleecing qcow2 from pre-Apr-16 aborted vzdump — RESOLVED 2026-05-13, ~244 GiB reclaimed, VM running"
- **grskg_mass_flap_20260511** (project): "GR site mass flap 02:08-02:14 UTC 2026-05-11 — 16 devices ICMP-down. RC CONFIRMED: gr-nms01 chronically over-budget poll cycles (518s vs 300s) + IO starvation (PSI io.full avg300=7.32%) + 6 concurrent zombie poller-wrapper.py + cororings device 9 pushed past cliff by nlpve04 6th-node add 2026-05-10."
- **hostname_deabbreviation_sweep_20260624** (project): 2026-06-24 estate-wide hostname de-abbreviation — all docs across the 4 IaC-relevant repos to 0 bare, verified + merged; guard + CI gate + bidirectional [P0] rule shipped
- **ibgp_full_mesh_fix_20260413** (project): iBGP full mesh routing fix (2026-04-13). next-hop-self force + BFD + table-map SET_SRC. 18 baseline experiments validated. ASA 9.16 limitations documented. Needs IaC sync.
- **incident_grdmz02_oom_shun_20260413** (project): grdmz02 OOM-killed twice on 2026-04-13, ASA shunned DMZ IP 10.0.X.X causing total network loss
- **DMZ disk-full pipeline break + resize to 128G + cleanup cron 2026-04-17** (project): gr-dmz01 / 100% full blocked Ansible tmp-dir creation, producing recurring UNREACHABLE across all portfolio deploy pipelines. Resized both DMZ VMs 64->128G and installed daily cleanup cron.
- **Freedom ISP PPPoE Outage 2026-04-08** (project): Freedom PPPoE outage → full remediation session. 5 phases: GR VPN restoration, VPS migration, NAT parity, grdmz02 TS fix, operational readiness. Dual-WAN parity achieved. QoS + SMS + triage training.
- **GR Site Isolation 2026-04-17 (stale IPsec SA)** (project): NL↔GR VTI/BGP break 2026-04-17 ~05:23 UTC. Root cause = stale IPsec SA on Tunnel4 (Freedom VTI). Fix = `clear crypto ipsec sa peer 203.0.113.X` on NL ASA. Resolved 08:48 UTC.
- **Multi-layer incident 2026-04-17 — consolidated overview** (project): 4-layer cascade in one day — VTI IPsec SA stale, BGP ECMP asymmetric paths, DMZ disk-full, and silent playbook skips — each hid the next. This is the index; each layer has its own memory.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **infragraph_honest_gate_20260624** (project): "2026-06-24 why the infragraph B->C gate (-1040) can't graduate — it's unsatisfiable by honest predictions (~0.70 cascade ceiling), not a broken graph. Shipped honest v2-gate + fold-gate candidate metrics (MR !51); recalibration is the operator's -1040 decision."
- **kyriakos-portfolio-sitewide-audit-20260619** (project): "2026-06-19 full-site audit + fixes of kyriakos.papadopoulos.tech — 8 merged MRs (!18-!25), canonical infra numbers, verifiable certs, CV redesign"
- **LibreNMS cororings threshold + nlpve04 onboarding 2026-05-10** (project): Bumped 5 cororings services from --rings 5 to 6 on NL+GR LibreNMS after nlpve04 onboarding. Also added nlpve04 itself as NL device 155 + cororings svc 40. snmpd-clone trap caught mid-flight.
- **librenms-extender-fleet-deployment-20260515** (project): "2026-05-15 fleet-wide LibreNMS extender deployment and hardening. nlpve04 got all 7 extenders from scratch (was bare). proxmox-extender switched to smart-style cache pattern on all 6 PVE hosts to bypass the /etc/pve/priv/authkey.key root-only requirement. apcupsd installed on nl-pve03+nlpve04 (shared SNMP UPS at 10.0.181.X). smart.config fleet sweep found stale gr-pve01 header on nl-pve01+nl-pve03 (now fixed) and empty config on gr-pve02 (5 disks now monitored, incl 2 MegaRAID)."
- **npm_api_access_20260623** (reference): The agentic system has STANDING API access to Nginx Proxy Manager (nlnpm01) — manage proxy hosts with scripts/npm-api.py; NEVER edit the NPM DB/conf directly (cluster DB); never ask the operator for NPM creds again
- **postiz_gr-fw01_firewall_rules_pending_migration_20260624** (project): 2026-06-24 — gr-fw01 (GR ASA) firewall rules around the migrated postiz still point at GR; the :80 Meta-webhook static-NAT is BROKEN, Cloudflare still pins postiz to GR. Pending migration to nl-fw01.
- **postiz_migration_gr_to_nl_20260624** (project): 2026-06-24 migrated grpostiz01 (privileged Docker LXC) cross-site to nlpostiz01 on nlpve04 to relieve gr-pve01 memory pressure (the chronic etcd-cascade root). Full DNS/NPM/e2e done.
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **Syslog-ng servers are per-site — don't look for GR logs on the NL server** (reference): Each site has its own syslog-ng server; NL devices log to nlsyslogng01, GR devices log to grsyslogng01. Looking for GR device logs on the NL syslog-ng will silently return empty.
- **session-thermal-and-gr-unreachable-20260616** (project): "2026-06-16 triage — NL \"thermal\" was stale phantom data; GR site was isolated ~06-15 22:58 → RECOVERED by 2026-06-17 (GR back online, reachable from NL)"
- **token_spend_attribution_20260624** (project): "2026-06-24 evidence-based answer to \"where do Claude tokens/usage go?\" — 98.7% is Tier-2 Opus, driven by giant cached prompt context across k8s-cascade sessions; model right-sizing is dead."
- **VPS BGP VTI update-source fix** (project): GR VPS peering used loopback IPs causing ASA next-hop resolution failure + cross-tunnel ECMP asymmetric routing. Fixed 2026-04-14.
- **VTI BGP outage investigation 2026-04-11** (project): NL-GR inter-site VTI tunnels down, BGP not peering, complete GR unreachability from NL. Root cause identified.
- **yt_triage_alert_remediation_20260625** (project): 2026-06-25 YouTrack triage (8 issues closed with evidence) + the IFRNLLEI01PRD-1408 commit-label mislabel finding + active-alert remediation (in progress).

*Compiled: 2026-07-03 04:30 UTC*