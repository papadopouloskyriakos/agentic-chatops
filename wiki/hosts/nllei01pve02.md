# nl-pve02

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | nl-pve02 | Proxmox hypervisor (**VM on nl-nas01**) | `ssh nl-pve02` |

**nl:native/pve/CLAUDE.md**
- | nl-pve02 | Ryzen V1500B | 8C/8T | 16.8 GB | None (direct) | 36.5 GB ext4 | Low-tier, VM on Synology |

**nl:native/ncha/CLAUDE.md**
- | nlcl01garbd01 | VMID_REDACTED | nl-pve02 | 10.0.181.X | Galera Arbitrator (quorum voter, no data). |
- | nlredis02 | VMID_REDACTED | nl-pve02 | 10.0.181.X | Redis 8.6.1. **Master**. Docker. |
- **nl-pve02 (10.0.181.X):** garbd01, redis02 — arbitrators only
- **Key risk:** nl-pve03 failure takes out half the HA cluster + ALL backend services (imaginary, whiteboard, hpb, gpu). nl-pve01 failure takes out the primary frontends + NFS server. nl-pve02 only has arbitrators — losing it doesn't cause outage but reduces quorum safety.

**nl:native/smtp/CLAUDE.md**
- | `yopdstkd@mail.example.net` | nl-pve02 system mail |

**nl:pve/CLAUDE.md**
- | nl-pve02 | Synology DS1621+ VM | Ryzen V1500B (8C) | 16 GB | NAS iSCSI | 7 | 0 |
- ├── nl-pve02/

**gateway:CLAUDE.md**
- - **nl-gpu01 / VM VMID_REDACTED io-error freeze TRUE root cause = ZFS DIO race (2026-05-14, IFRNLLEI01PRD-900, fix on all 6 PVE hosts):** The 2026-05-12 `discard=on` + memory bump (IFRNLLEI01PRD-892, now closed-as-hardening) was a useful hardening layer but never RC. Real cause: **OpenZFS 2.3+ Direct-I/O verify-write race** with QEMU `cache=none` (`cache.direct=true`) + `aio=io_uring` against qcow2 on a ZFS dataset. Stack: PVE **9.1.9** kernel `6.17.2-2-pve` with ZFS **2.4.1-pve1** — exactly the configuration affected by the known PVE 9 / ZFS 2.3+ regression. Mechanism: QEMU does zero-copy DMA from its userspace buffer; ZFS 2.3+ post-write verify-CRC catches any guest mutation of that page mid-flight (ollama loading models maximises this); on mismatch ZFS returns EIO; qcow2's cluster-allocation path **maps EIO → ENOSPC** internally; QEMU `werror=enospc,stop` pauses the VM with bogus "nospace" status (pool was 52 % full). 121 cumulative `ereport.fs.zfs.dio_verify_wr` events over 2 months mapped 1:1 to freeze incidents. Fix is 3-layer on every PVE host: `zfs set direct=disabled <pool>` + `/etc/modprobe.d/zfs-dio-disable.conf` (`options zfs zfs_dio_enabled=0`) + runtime `echo 0 > /sys/module/zfs/parameters/zfs_dio_enabled`. Per `man zfsprops`, `disabled` is "the default behavior for OpenZFS 2.2 and prior releases" — zero risk, just reverts to pre-2.3 behavior, ARC absorbs writes via buffered path. Applied to all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04 with `rpool`, nl-pve02 module-only; GR: gr-pve01 with `rpool`, gr-pve02 with `ssd-pool`). Drift-check: `scripts/check-zfs-dio-disabled.sh` (PASS = all hosts safe). VM resumed cleanly, 110k subsequent writes, zero new DIO errors. **Important nuance:** the `direct=disabled` workaround is community-validated (multiple PVE 9 `[SOLVED]` forum threads converge on it) but **NOT in any pve.proxmox.com wiki page** — no Proxmox staff endorsement found. Don't ever claim "it's the official Proxmox recommendation" — say "OpenZFS-documented + community-validated PVE 9 workaround for the ZFS 2.3+ DIO regression." `cache=none` itself IS Proxmox-official for ZFS-backed VMs. Follow-ups: (1) re-run drift-check + DIO error count on 2026-05-21 to verify fix held under sustained ollama load; (2) optionally file a Proxmox forum thread to push for official documentation; (3) re-evaluate at next PVE major upgrade. Detail in [`.claude/rules/infrastructure.md`](.claude/rules/infrastructure.md) §"Known Host: nl-gpu01". Full memory: [`memory/gpu01_zfs_dio_race_root_cause_20260514.md`](memory/gpu01_zfs_dio_race_root_cause_20260514.md) (includes Research validation section). Feedback for all future PVE-onboarding work: [`memory/feedback_zfs_dio_must_be_disabled_on_pve.md`](memory/feedback_zfs_dio_must_be_disabled_on_pve.md). Diagnostic recipe: [`memory/feedback_zfs_dio_diagnostic_recipe.md`](memory/feedback_zfs_dio_diagnostic_recipe.md).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-21 | Space on / is >= 90% and < 95% in use | recurred 4x in 30d without durable fix | analysis-only pending root-cause | N/A |
| 2026-06-21 | Service up/down | recurred 3x in 30d without durable fix | analysis-only pending root-cause | N/A |
| 2026-04-03 | Service up/down. |  | Resolved via Claude session IFRNLLEI01PRD-338 | 0.8 |

## Lessons Learned

- **IFRNLLEI01PRD-338**: nl-pve02 service flaps during iSCSI storage operations or kernel module reloads. This host has the longest uptime (105+ days) and is pending kernel maintenance.

## Related Memory Entries

- **apiserver-ctrl01-balloon-chronic-restart-fixed-20260515** (project): "RESOLVED 2026-05-15. nlk8s-ctrl01's kube-apiserver had restartCount=1665 (~27 days of crash-looping, ~24-min cycle). Root cause was the balloon device on the underlying VM (VMID_REDACTED on nlpve04) inflating during host pressure events, leaving the VM with only 3.7 GiB instead of 8 GiB. etcd's WAL/DB page cache got evicted → fsyncs disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kill → restart. Fix: `qm set --balloon 0` + VM reboot to apply [PENDING] (config change cannot live-remove a balloon device)."
- **corosync CMAP version-mismatch = clone-of-member rejection** (feedback): corosync `[CMAP] Received config version (X) is different than my config version (Y)! Exiting` is the diagnostic signature for a node booting with a stale `corosync.conf` — typically a disk clone of an existing cluster member. SSH host-key change between reconnects is the parallel signature for a remote OS reinstall.
- **Always use full hostnames [P0]** (feedback): P0 rule — never strip site/cluster prefixes. Use nl-pve02 not pve02, gr-dmz01 not dmz01, never "the ASA"/"the router"
- **LibreNMS check_cororings hard-codes expected cluster size in every service** (feedback): Every PVE node has its own check_cororings service with a hard-coded --rings N. Adding/removing a node requires PATCHing N services on both LibreNMS instances.
- **feedback-no-balloon-on-k8s-control-plane** (feedback): "Never run k8s control-plane VMs (kube-apiserver / etcd / scheduler / controller-manager) with an active Proxmox balloon device. etcd is fsync-sensitive; when host pressure causes balloon to reclaim guest memory, etcd's WAL/DB page cache gets evicted → fsyncs become disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kills → restart cycle. Caught 2026-05-15: nlk8s-ctrl01 had 1665 restarts (27 days of crash-looping) because of this."
- **feedback-no-sudo-install-on-pve-hosts** (feedback): "Don't reach for `sudo` (install it OR sudo-prefix invocations) to bridge a permission gap on a PVE host. The Proxmox-staff position is \"sudo is not the right way to implement unprivileged services\" (Fabian Grünbichler). All 6 NL+GR PVE hosts in this estate happen to have sudo installed from legacy setup, but new fixes should use PVE-native patterns (cache-pattern cron for snmpd extenders, pveum ACLs for delegated admin, system systemd units for services)."
- **PVE-clone leaves snmpd.conf sysName pinned to the source host** (feedback): When a Proxmox node is cloned from another, /etc/snmp/snmpd.conf retains the source's sysName, blocking LibreNMS device add with "duplicate sysName"
- **freeipa01-httpd-scoreboard-outage-20260529** (project): "2026-05-29. nlfreeipa01 webui unreachable for 5d — httpd mpm_event scoreboard full since Sun May 24 00:00:11. Fixed short-term by LXC reboot. Two reusable findings — IPA host missing from LibreNMS (silent), chronic MPM tuning gap."
- **gitlab_runner_topology** (project): NL + GR internal GitLab each have ONE online runner with run_untagged=false. NL failure mode = saturation (queued_duration>30m). GR failure mode = tag-less jobs hang 2h → stuck_or_timeout_failure.
- **gpu01-zfs-dio-race-root-cause-20260514** (project): "nl-gpu01 (VM VMID_REDACTED) \"frozen daily with io-error\" was OpenZFS 2.3 dio_verify_wr race with QEMU cache=none/aio=io_uring. Fixed by setting direct=disabled on rpool across all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04, GR: gr-pve01/gr-pve02) + zfs_dio_enabled=0 modprobe.d safety net."
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by nl-pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 nl-pve01 memory pressure class.
- **Infrastructure Integration** (project): IaC repo integration, LibreNMS alerts, infra triage, Proxmox MCP, PVE drift detection, and operational details
- **LibreNMS cororings threshold + nlpve04 onboarding 2026-05-10** (project): Bumped 5 cororings services from --rings 5 to 6 on NL+GR LibreNMS after nlpve04 onboarding. Also added nlpve04 itself as NL device 155 + cororings svc 40. snmpd-clone trap caught mid-flight.
- **librenms-extender-fleet-deployment-20260515** (project): "2026-05-15 fleet-wide LibreNMS extender deployment and hardening. nlpve04 got all 7 extenders from scratch (was bare). proxmox-extender switched to smart-style cache pattern on all 6 PVE hosts to bypass the /etc/pve/priv/authkey.key root-only requirement. apcupsd installed on nl-pve03+nlpve04 (shared SNMP UPS at 10.0.181.X). smart.config fleet sweep found stale gr-pve01 header on nl-pve01+nl-pve03 (now fixed) and empty config on gr-pve02 (5 disks now monitored, incl 2 MegaRAID)."
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **n8n OOM outage + Restart= drop-in (2026-05-11)** (project): 4h n8n outage (06:50-10:48 UTC) — OOM-killed inside the LXC, sat dead because n8n.service had Type=simple with NO Restart= directive. Operator-reported via "both pages live stats widgets are offline". n8n LXC has migrated from nl-pve01 to nlpve04 since the 2026-04-22 Known Host Pressure note in CLAUDE.md.
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on nlk8s-ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **nl-pve03 capacity pressure (2026-04-22)** (project): nl-pve03 mirrors pre-remediation nl-pve01 pattern — no swap/zram, sustained 92%+ memory, hosts K8s ctrlr+NMS+GPU inference. Apply same zram fix; OOM blast radius is the K8s control-plane share + LibreNMS + Ollama inference simultaneously.
- **pve03-vs-pve04-hardware-delta** (project): "Live-verified 2026-05-14 hardware delta between nl-pve03 (Dell Precision 3680 workstation) and nlpve04 (ASRock GENOAD8X-2T/BCM server). Non-derivable operational constraints — RAM caps, BMC presence, expansion headroom — that should inform future capacity / placement / DR planning."
- **PVE Kernel Maintenance Automation** (project): Full-site PVE kernel update automation — ALL DONE + dry-run PASS on both sites. 14 playbooks, startup order (5 nodes), 6 AWX templates, maintenance mode (7 workflows), hardened per Proxmox best practices.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **Session DB write-back anomaly pattern** (project): IFRNLLEI01PRD-457 had 133 JSONL events but 0 messages in sessions DB — Runner write-back may silently fail
- **territory_gate_20260625** (project): "IFRNLLEI01PRD-1408 territory-aware hard-gate — make loading+respecting the relevant infra CLAUDE.md an ABSOLUTE prerequisite before a session acts in a territory. Operator chose Both (PreToolUse + Runner backstop), live-on-merge. Mid-build 2026-06-25."
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.

## Physical Documentation (03_Lab)

- `03_Lab/NL/Servers/nl-pve02/20241203_nl-pve02_interfaces.txt`
- `03_Lab/NL/Servers/nl-pve02/20250515_nl-pve02_ansible_inventory.yaml`
- `03_Lab/NL/Servers/nl-pve02/lxc/VMID_REDACTED - nlgitea01/20241104_nlgitea01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/VMID_REDACTED - nlsemaphore01/20241104_nlsemaphore01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/VMID_REDACTED - nlsemaphore01/playbooks/apt.yml`
- `03_Lab/NL/Servers/nl-pve02/lxc/125 - nlmeshcentral01/20240410_nlmeshcentral01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230919-1905_nlbaikal01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Dutch Lessons.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Family.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Fitness.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- F∴M∴.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Global Schema Placeholder.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Health.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- PT1-OT - LAB - DOWNTIME.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Personal.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Project Baltimore.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Social.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Trips.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/Calendar- Work.ics`
- `03_Lab/NL/Servers/nl-pve02/lxc/nlbaikal01/20230924-1451_exported_calendars/Personal/Calendars/baikal_personal_cal_configs.txt`

*Compiled: 2026-07-03 04:30 UTC*