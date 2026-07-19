# nl-pve03

**Site:** NL (Leiden)

## Knowledge Base References

**nl:CLAUDE.md**
- | List LXCs on a node | `pve_list_lxc(node="nl-pve03")` | `ssh nl-pve03 "pct list"` |
- | List VMs on a node | `pve_list_vms(node="nl-pve03")` | `ssh nl-pve03 "qm list"` |
- | Get LXC config | `pve_lxc_config(node="nl-pve03", vmid=VMID_REDACTED)` | `ssh nl-pve03 "pct config VMID_REDACTED"` |
- | Get VM config | `pve_vm_config(node="nl-pve03", vmid=VMID_REDACTED)` | `ssh nl-pve03 "qm config VMID_REDACTED"` |
- | Get guest status | `pve_guest_status(node="nl-pve03", vmid=VMID_REDACTED, type="lxc")` | `ssh nl-pve03 "pct status VMID_REDACTED"` |

**nl:edge/CLAUDE.md**
- │   ├── nlk8s-frr02/         — NL, nl-pve03 (VMID VMID_REDACTED)
- | nlk8s-frr02 | NL | 10.0.X.X/27 | 21 (DMZ) | nl-pve03 | VMID_REDACTED | Debian 12 | 10.5.0 |

**nl:native/pve/CLAUDE.md**
- | nl-pve03 | i9-14900K | 24C/32T | 134.7 GB | bond0 (802.3ad, 10G) | 3.6 TB ZFS | GPU node (RTX 3090 Ti passthrough) |

**nl:native/servarr/CLAUDE.md**
- | PVE Host | nl-pve03 |
- **Calibre-Web (was nlcalibre01, VMID VMID_REDACTED, nl-pve03):**
- **Lyrion Music Server (was nllyrion01, VMID VMID_REDACTED, nl-pve03):**

**nl:native/syncthing/CLAUDE.md**
- | `nl-openclaw01` | (LXC `VMID_REDACTED` on `nl-pve03`) | n/a | Dormant — LXC stopped per `cc-cc` mode (since 2026-04-29). |
- | `nl-openclaw01` | LXC `VMID_REDACTED` on `nl-pve03` — `pct exec` (currently stopped) |

**nl:native/ncha/CLAUDE.md**
- └─ 10.0.181.X  nlhaproxy02 (nl-pve03) — nlnc02 PRIMARY, nlnc01 BACKUP (cross-site)
- └─ 10.0.181.X  nlnc02 (QEMU, nl-pve03) — BACKUP
- | nlhaproxy02 | VMID_REDACTED | nl-pve03 | 10.0.181.X | HAProxy 3.3.5. Same frontends, nlnc02=PRIMARY (cross-site failover). |
- | nlnc02 | VMID_REDACTED | nl-pve03 | 10.0.181.X, 10.0.X.X | Nextcloud 32.0.6, PHP 8.4.18, Apache 2.4.58 |
- | nlproxysql02 | VMID_REDACTED | nl-pve03 | 10.0.181.X | ProxySQL 2.7.2. Identical config. |

**nl:native/smtp/CLAUDE.md**
- | `rwfmoszw@mail.example.net` | nl-pve03 system mail |

**nl:native/haha/CLAUDE.md**
- | nl-iot02 | 777 | nl-pve03 | 10.0.181.X, 10.0.X.X | QEMU VM. 2C/2S, 4GB RAM, 64GB SSD. Active or passive (alternates each weekly update). |
- | `fence_iot02` | `fence_pve` | VMID 777 on nl-pve03 | Runs on nlcl01iotarb01 |
- **nl-pve03:** iot02 (VMID 777) — active node (currently running `g_iot_stack`)
- **Key risk:** Whichever PVE host runs the active IoT node is the SPOF for the IoT stack. Currently nl-pve03 → iot02 active → if nl-pve03 dies, Pacemaker fences iot02 (SBD + fence_pve) and starts `g_iot_stack` on iot01 (nl-pve01). The reverse failover (nl-pve01 dying with iot01 active) is more dangerous because **nl-pve01 also hosts nlcl01file01** (NFS source for `/mnt/iot`) — losing nl-pve01 takes both iot01 AND the NFS server, so failover requires nlcl01file01→nlcl01file02 cutover to complete first.

**nl:docker/nlfrigate01/frigate/CLAUDE.md**
- | PVE node | `nl-pve03` |
- | Repo PVE config | `pve/nl-pve03/lxc/VMID_REDACTED.conf` |
- ssh nl-pve03 'pct exec VMID_REDACTED -- docker compose -f /srv/frigate/docker-compose.yml restart'
- ssh nl-pve03 'pct exec VMID_REDACTED -- docker cp <new>.yaml frigate:/tmp/new.yaml'
- ssh nl-pve03 'pct exec VMID_REDACTED -- docker exec frigate python3 -c "

**nl:docker/nlservarr01/servarr/pinchflat/CLAUDE.md**
- # Or via PVE host (QEMU VM VMID_REDACTED on nl-pve03):
- ssh nl-pve03 "qm guest exec VMID_REDACTED -- <command>"
- ssh nl-pve03
- **VM Details**: VMID VMID_REDACTED on nl-pve03, IP 10.0.181.X, Ubuntu 24.04, 6 vCPU, 12 GB RAM.

**nl:pve/CLAUDE.md**
- | nl-pve03 | Dell Precision 3680 | i9-14900K (32T) | 128 GB | NVMe ZFS | 34 | 14 |
- ├── nl-pve03/
- | `nl-pve03-local-zfs` | Local ZFS | 29 LXC, 10 QEMU | Performance workloads |

**gateway:CLAUDE.md**
- Switch modes with the `!mode <mode>` command in any Matrix room where OpenClaw is present. ⚠ Restoring `oc-cc`/`oc-oc`/`cc-oc` is **no longer possible** — it required `pct start VMID_REDACTED` on `nl-pve03`, but that LXC no longer exists; it would have to be rebuilt from scratch. Do not rely on this path.
- - **nl-gpu01 qcow2 io-error freeze RCA + monitoring wired (2026-05-12, k8s MRs !294 + !295):** VM VMID_REDACTED on nl-pve03 "frozen many times daily" was QEMU `paused (io-error)` with `I/O status: nospace` on scsi0, not a guest kernel freeze. Root cause: qcow2 created without `discard=on`, so guest deletes never propagated → 99.56 % cluster allocation despite guest `/` at 77 %. Fix in-flight: `qm set --scsiN ...,discard=on` on both disks + `qm set --memory 32768` (operator override) + restart + `docker prune` + `fstrim -av` (1.27 TiB UNMAP, allocation 99.56 % → 71.55 %, ZFS −210 GiB). `fstrim.timer` already weekly-enabled. Monitoring landed via two MRs on the K8s repo: `/etc/cron.weekly/gpu01-health-metrics` on nl-gpu01 + PrometheusRules `Gpu01DockerDanglingImagesHigh` (> 5 GiB / 6h) + `Gpu01FstrimTimerInactive` (== 0 / 1h). MR !294 first wired the alert on `gpu01_docker_reclaimable_bytes` but that metric is misleading (counts images held by stopped containers, drifts upward forever); MR !295 swapped to dangling-images. Full memory: [`memory/gpu01_freeze_qcow2_io_error_20260512.md`](memory/gpu01_freeze_qcow2_io_error_20260512.md), feedback: [`memory/feedback_docker_reclaimable_misleading.md`](memory/feedback_docker_reclaimable_misleading.md), [`memory/feedback_gpu01_target_ram_32g.md`](memory/feedback_gpu01_target_ram_32g.md).
- - **Fleet-wide LibreNMS extender hardening + apcupsd + smart.config sweep + nlpve04 PBS backup unstuck (2026-05-15):** Multi-track session covering all 6 PVE hosts (NL pve01-04 + GR pve01-02). **nlpve04 went from bare → 7 extenders + apcupsd + smart.config + functional pbc-host-backup.sh** (the backup had been silently failing 5× weekly since 2026-05-10 onboarding because the PBS fingerprint trust file was never copied across). **proxmox-extender now uses cache pattern fleet-wide** (`*/5 cron writes /var/cache/proxmox`, snmpd just `cat`s it) — bypasses the `/etc/pve/priv/authkey.key` root-only requirement that made the snmpd-as-Debian-snmp proxmox extender fail with `exit=13 cfs-lock 'authkey' error` on every host. Rejected sudo-prefix (Fabian Grünbichler: "sudo is not the right way to implement unprivileged services") and `Debian-snmp → www-data` (PVE locks `/etc/pve/priv/` at mode 700 — group bits zero, group membership doesn't help). **apcupsd installed on nl-pve03+nlpve04** using nl-pve01's existing SNMP-over-Ethernet config (shared `10.0.181.X` APC Smart-UPS 1500, no USB needed). **smart.config sweep** caught stale `# smart.config for gr-pve01` clone-artifact headers on nl-pve01+nl-pve03 (now fixed; nl-pve01 also had a phantom `nvme1` line for an empty M.2 slot — real disks are FireCuda 530 at nvme0+nvme2) AND an essentially-empty smart.config on gr-pve02 despite 5 real disks (rewrote with 3 SCSI + 2 MegaRAID, all 5 now reporting). End-to-end verified via NL LibreNMS API (device_id 23/27/58/155) + GR LibreNMS API (device_id 34/35) — all 7 apps OK on every host. Side-finds: `alertmanager-twilio-bridge.service` runs as systemd `--user` inside nl-claude01 LXC at `oom_score_adj=200` — preferred OOM victim by design; left in place per operator decision but flagged. Full memory: [`memory/librenms_extender_fleet_deployment_20260515.md`](memory/librenms_extender_fleet_deployment_20260515.md). Architectural patterns: [`memory/feedback_pve_root_extender_cache_pattern.md`](memory/feedback_pve_root_extender_cache_pattern.md) + [`memory/feedback_systemd_user_slice_oom_score.md`](memory/feedback_systemd_user_slice_oom_score.md) + updated [`memory/feedback_no_sudo_install_on_pve_hosts.md`](memory/feedback_no_sudo_install_on_pve_hosts.md). Pending follow-ups: vzdump job for nlpve04 in `/etc/pve/jobs.cfg` (workload still unbacked), stale node-pinned VMIDs in nl-pve01/nl-pve03 backup jobs.
- - **nl-gpu01 / VM VMID_REDACTED io-error freeze TRUE root cause = ZFS DIO race (2026-05-14, IFRNLLEI01PRD-900, fix on all 6 PVE hosts):** The 2026-05-12 `discard=on` + memory bump (IFRNLLEI01PRD-892, now closed-as-hardening) was a useful hardening layer but never RC. Real cause: **OpenZFS 2.3+ Direct-I/O verify-write race** with QEMU `cache=none` (`cache.direct=true`) + `aio=io_uring` against qcow2 on a ZFS dataset. Stack: PVE **9.1.9** kernel `6.17.2-2-pve` with ZFS **2.4.1-pve1** — exactly the configuration affected by the known PVE 9 / ZFS 2.3+ regression. Mechanism: QEMU does zero-copy DMA from its userspace buffer; ZFS 2.3+ post-write verify-CRC catches any guest mutation of that page mid-flight (ollama loading models maximises this); on mismatch ZFS returns EIO; qcow2's cluster-allocation path **maps EIO → ENOSPC** internally; QEMU `werror=enospc,stop` pauses the VM with bogus "nospace" status (pool was 52 % full). 121 cumulative `ereport.fs.zfs.dio_verify_wr` events over 2 months mapped 1:1 to freeze incidents. Fix is 3-layer on every PVE host: `zfs set direct=disabled <pool>` + `/etc/modprobe.d/zfs-dio-disable.conf` (`options zfs zfs_dio_enabled=0`) + runtime `echo 0 > /sys/module/zfs/parameters/zfs_dio_enabled`. Per `man zfsprops`, `disabled` is "the default behavior for OpenZFS 2.2 and prior releases" — zero risk, just reverts to pre-2.3 behavior, ARC absorbs writes via buffered path. Applied to all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04 with `rpool`, nl-pve02 module-only; GR: gr-pve01 with `rpool`, gr-pve02 with `ssd-pool`). Drift-check: `scripts/check-zfs-dio-disabled.sh` (PASS = all hosts safe). VM resumed cleanly, 110k subsequent writes, zero new DIO errors. **Important nuance:** the `direct=disabled` workaround is community-validated (multiple PVE 9 `[SOLVED]` forum threads converge on it) but **NOT in any pve.proxmox.com wiki page** — no Proxmox staff endorsement found. Don't ever claim "it's the official Proxmox recommendation" — say "OpenZFS-documented + community-validated PVE 9 workaround for the ZFS 2.3+ DIO regression." `cache=none` itself IS Proxmox-official for ZFS-backed VMs. Follow-ups: (1) re-run drift-check + DIO error count on 2026-05-21 to verify fix held under sustained ollama load; (2) optionally file a Proxmox forum thread to push for official documentation; (3) re-evaluate at next PVE major upgrade. Detail in [`.claude/rules/infrastructure.md`](.claude/rules/infrastructure.md) §"Known Host: nl-gpu01". Full memory: [`memory/gpu01_zfs_dio_race_root_cause_20260514.md`](memory/gpu01_zfs_dio_race_root_cause_20260514.md) (includes Research validation section). Feedback for all future PVE-onboarding work: [`memory/feedback_zfs_dio_must_be_disabled_on_pve.md`](memory/feedback_zfs_dio_must_be_disabled_on_pve.md). Diagnostic recipe: [`memory/feedback_zfs_dio_diagnostic_recipe.md`](memory/feedback_zfs_dio_diagnostic_recipe.md).

## Incident History

| Date | Alert | Root Cause | Resolution | Confidence |
|------|-------|------------|------------|------------|
| 2026-06-21 | Service up/down | recurred 5x in 30d without durable fix | analysis-only pending root-cause | N/A |

## Related Memory Entries

- **apiserver-ctrl01-balloon-chronic-restart-fixed-20260515** (project): "RESOLVED 2026-05-15. nlk8s-ctrl01's kube-apiserver had restartCount=1665 (~27 days of crash-looping, ~24-min cycle). Root cause was the balloon device on the underlying VM (VMID_REDACTED on nlpve04) inflating during host pressure events, leaving the VM with only 3.7 GiB instead of 8 GiB. etcd's WAL/DB page cache got evicted → fsyncs disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kill → restart. Fix: `qm set --balloon 0` + VM reboot to apply [PENDING] (config change cannot live-remove a balloon device)."
- **cc-cc migration done — OpenClaw retired (2026-04-29)** (project): 2026-04-29 — OpenClaw LXC stopped + onboot=0. All 9 alert receivers rewired to call triage scripts via direct SSH to nl-claude01 instead of @openclaw Matrix mention. Webhook→SSH→YT issue chain verified ~6s end to end.
- **CodeGraphContext (CGC) Setup** (project): Code graph database for CubeOS/MeshSat — Neo4j backend, scheduled reindex (no live watcher), MCP server, 43K nodes across 5 repos
- **AWX EE Image Persistence Problem** (feedback): Custom EE images imported via ctr are lost on K8s node reboot. Need persistent registry or image in PVC.
- **gpu01-target-ram-32g** (feedback): "Operator's chosen RAM allocation for nl-gpu01 is 32 GiB (32768 MB), not the historical 28 GiB. Don't argue this down to 28 G citing nl-pve03 host pressure — operator owns the trade-off."
- **LibreNMS check_cororings hard-codes expected cluster size in every service** (feedback): Every PVE node has its own check_cororings service with a hard-coded --rings N. Adding/removing a node requires PATCHing N services on both LibreNMS instances.
- **feedback-no-balloon-on-k8s-control-plane** (feedback): "Never run k8s control-plane VMs (kube-apiserver / etcd / scheduler / controller-manager) with an active Proxmox balloon device. etcd is fsync-sensitive; when host pressure causes balloon to reclaim guest memory, etcd's WAL/DB page cache gets evicted → fsyncs become disk-bound → apiserver timeouts → liveness probe HTTP 500 → kubelet kills → restart cycle. Caught 2026-05-15: nlk8s-ctrl01 had 1665 restarts (27 days of crash-looping) because of this."
- **no-migration-off-pve03** (feedback): Do not propose migrating workloads off nl-pve03 to relieve memory/CPU pressure — solve in-place. Topology of the 5-node pve cluster is intentional.
- **feedback-no-sudo-install-on-pve-hosts** (feedback): "Don't reach for `sudo` (install it OR sudo-prefix invocations) to bridge a permission gap on a PVE host. The Proxmox-staff position is \"sudo is not the right way to implement unprivileged services\" (Fabian Grünbichler). All 6 NL+GR PVE hosts in this estate happen to have sudo installed from legacy setup, but new fixes should use PVE-native patterns (cache-pattern cron for snmpd extenders, pveum ACLs for delegated admin, system systemd units for services)."
- **no-zramswap-on-pve-hosts** (feedback): Do not propose or apply zramswap (or any swap) on PVE hosts as a memory-pressure remediation — Proxmox does not officially recommend swap on hypervisors. Find another lever.
- **gitlab_runner_topology** (project): NL + GR internal GitLab each have ONE online runner with run_untagged=false. NL failure mode = saturation (queued_duration>30m). GR failure mode = tag-less jobs hang 2h → stuck_or_timeout_failure.
- **gpu01_daily_reboot_rca_20260629** (project): "RCA for nl-gpu01 alert churn (1403 rebooted / 1465 ProactiveDiskPressure / 1467 RAGRerankServiceDown). 2 deliberate reboot mechanisms (daily cron + ollama-nvml-selfheal.sh), stale post-2026-05-14 ZFS-DIO fix (held, 0 errors). Disk 80%/168GB reclaimable. Reranker+ollama healthy; alerts were transient post-reboot. Prior 06-27 triage missed it."
- **gpu01-freeze-qcow2-io-error-20260512** (project): "nl-gpu01 (PVE VM VMID_REDACTED on nl-pve03) freeze RCA — symptom is QEMU paused state=\"io-error\" / I/O status=nospace on scsi0, not a guest-side kernel freeze. Root cause = qcow2 cluster exhaustion because disk was created without discard=on. Fixed with discard=on + fstrim + RAM bump 28 → 32 GiB."
- **gpu01-nvml-stale-handles-20260514** (project): "nl-gpu01 CPU hammer (load 18-19, ollama 1277% CPU for 10h) — container's bind-mounted /dev/nvidia* nodes went stale after nvidia-persistenced restart at 07:01:54 CEST cycled the host device nodes. Different failure mode from 2026-05-13 (VRAM shortage). Fix: `docker restart ollama`. Hardening pending."
- **gpu01-zfs-dio-race-root-cause-20260514** (project): "nl-gpu01 (VM VMID_REDACTED) \"frozen daily with io-error\" was OpenZFS 2.3 dio_verify_wr race with QEMU cache=none/aio=io_uring. Fixed by setting direct=disabled on rpool across all 6 PVE hosts (NL: nl-pve01/nl-pve03/nlpve04, GR: gr-pve01/gr-pve02) + zfs_dio_enabled=0 modprobe.d safety net."
- **GR Claude Agent (grclaude01)** (project): Claude Code agent at GR site for NL maintenance oversight. VMID 201021201, 10.0.X.X, gr-pve01.
- **HAHA reliability hardening 2026-04-30 (Phases 1-5 implemented)** (project): Same-day follow-up after the 2026-04-27 → 2026-04-30 ~66h HAHA outage. App-level OCF docker monitor_cmd, NFS auto-flush, NFS stale-fh exporter, proactive ARP, host-pressure alerts, Twilio escalation. T1 e2e verified: 18s detect, 3m30s recover.
- **healthchecks_langfuse_access_20260626** (reference): "STANDING access for the orchestrator brick-growth services — Healthchecks.io (ping-based never-ran detection) + Langfuse v2 (LLM/agent trace observability), both self-hosted Docker on nlopenobserve01. Operator-approved 2026-06-26."
- **ibgp_full_mesh_fix_20260413** (project): iBGP full mesh routing fix (2026-04-13). next-hop-self force + BFD + table-map SET_SRC. 18 baseline experiments validated. ASA 9.16 limitations documented. Needs IaC sync.
- **n8n SQLite mutex timeout incident 2026-04-16** (project): ~90s n8n outage at 20:12 UTC caused by nl-pve01 IO pressure starving SQLite. Self-healed. Root cause identical to 2026-04-15 nl-pve01 memory pressure class.
- **infragraph-epic-state-20260609** (project): "Infragraph epic IFRNLLEI01PRD-1029 FINAL STATE — model-based control LIVE 2026-06-09 (13/16 done, system active, first rule -1046 approved); canonical record in repo memory/infragraph_epic_buildout_20260609.md"
- **k8s-residual-triage-20260617** (project): "2026-06-17 — closed/triaged the residual open IFRNLLEI01PRD K8s alerts after the auto-resolve pipeline repair. seaweedfs filer OOM fix (MRs), notrf01dmz01 is a KNOWN scrape-path gap (not a real down), InfragraphPrecisionDrop is slow-recovery."
- **lab-pve03-interfaces-md-stale-20260514** (project): 03_Lab interface doc 20241222_nl-pve03_interfaces.md is stale on bond0 NIC layout — lists 4×1G but actual is 2×10GBASE-T X550. NetBox + live lspci correct.
- **LibreNMS cororings threshold + nlpve04 onboarding 2026-05-10** (project): Bumped 5 cororings services from --rings 5 to 6 on NL+GR LibreNMS after nlpve04 onboarding. Also added nlpve04 itself as NL device 155 + cororings svc 40. snmpd-clone trap caught mid-flight.
- **librenms-extender-fleet-deployment-20260515** (project): "2026-05-15 fleet-wide LibreNMS extender deployment and hardening. nlpve04 got all 7 extenders from scratch (was bare). proxmox-extender switched to smart-style cache pattern on all 6 PVE hosts to bypass the /etc/pve/priv/authkey.key root-only requirement. apcupsd installed on nl-pve03+nlpve04 (shared SNMP UPS at 10.0.181.X). smart.config fleet sweep found stale gr-pve01 header on nl-pve01+nl-pve03 (now fixed) and empty config on gr-pve02 (5 disks now monitored, incl 2 MegaRAID)."
- **maintenance_companion** (project): Maintenance Companion architecture — hybrid AWX/direct API, self-healing Layer 0, critical service map per PVE host, fallback ladder
- **OOB Access via PiKVM + Cloudflare Tunnel** (project): BROKEN (2026-03-21) — PiKVM bricked by forced package upgrade. Requires physical access to GR site to recover. Cloudflare tunnel config still exists but PiKVM is offline.
- **openobserve_access_20260626** (reference): "STANDING access + OTLP trace-export setup for OpenObserve (nlopenobserve01) — the gateway's distributed-tracing sink. Admin creds in .env; the OTLP auth + 5h ingest-window gotchas."
- **OpenObserve Grafana datasource deployed via GitOps** (project): OpenObserve (10.0.181.X:5080) added as Grafana datasource via additionalDataSources in kube-prometheus-stack Helm values
- **Operational Activation Audit 2026-04-10** (project): Comprehensive audit scoring operational activation (not just implementation). 21/21 tables populated after remediation. 8 YT issues (445-452).
- **Pipeline Hardening (2026-04-01)** (project): 11 fixes across 5 workflows + 3 scripts. NetBox Step 2-pre in triage, syslog 3-day, [POLL] fallback parser, escalation cooldown 1h, recovery dedup 60s, flapping timeout 4h, watchdog zombie bounce, Parse Response em-dash + [POLL] approval gate regex. All E2E verified.
- **portfolio-lab-page-rebuild-schedule-20260609** (project): "2026-06-09. kyriakos.papadopoulos.tech/lab/ auto-updates via Hugo CI build-time bake of data/lab_stats.json from n8n /webhook/lab-stats (lab-stats.py → NetBox+kubectl+ZFS). Rebuild schedule id=2 on GitLab project 9 is cron `0 * * * *` (HOURLY) despite being labeled \"5m\" and drawio saying \"*/5 cron\" — discrepancy, not yet fixed."
- **nl-pve01 memory pressure causing apiserver restarts** (project): PVE01 host 88% RAM (2.5x overcommit, zero swap) starved etcd I/O on nlk8s-ctrl01. 754 apiserver restarts. Mitigated by shutting down androidsdk01.
- **nl-pve01_rpool_suspend_heatwave_20260623** (project): 2026-06-23 nl-pve01 ZFS rpool I/O-suspended (heatwave) → froze ~40 guests incl nl-pihole01 → site-wide DNS cascade. 2026-06-24 VERIFIED: host recovered (up ~20h), rpool DEGRADED running on a SINGLE FireCuda; the twin FireCuda 530 7VS00ZJ8 (eui…0048c7) genuinely FAILED (EIO storm + absent from the PCIe bus) → pending physical reseat/replace. DISTINCT from gr-pve01 nvme2n1 (= thermal throttle, NOT failed).
- **nl-pve03 capacity pressure (2026-04-22)** (project): nl-pve03 mirrors pre-remediation nl-pve01 pattern — no swap/zram, sustained 92%+ memory, hosts K8s ctrlr+NMS+GPU inference. Apply same zram fix; OOM blast radius is the K8s control-plane share + LibreNMS + Ollama inference simultaneously.
- **pve03-vs-pve04-hardware-delta** (project): "Live-verified 2026-05-14 hardware delta between nl-pve03 (Dell Precision 3680 workstation) and nlpve04 (ASRock GENOAD8X-2T/BCM server). Non-derivable operational constraints — RAM caps, BMC presence, expansion headroom — that should inform future capacity / placement / DR planning."
- **PVE drift jobs can 1h-timeout on inventory blinks** (project): sync_pve_drift / detect_pve_lxc_drift can run for an hour deleting dozens of LXCs after a transient PVE inventory blink — needs a sanity cap.
- **PVE Swap Audit 2026-03-25** (project): Swap configuration audit across all 5 PVE nodes — findings, changes, Proxmox best practices, disk layout
- **Session summary IFRNLLEI01PRD-999** (project): Compacted session context for IFRNLLEI01PRD-999
- **VMID UID Schema** (project): Proxmox VMID encoding scheme — 9-digit structured ID encoding site, node, VLAN, automation tag, and resource ID. Some VMs have drifted from schema.
- **VPS BGP VTI update-source fix** (project): GR VPS peering used loopback IPs causing ASA next-hop resolution failure + cross-tunnel ECMP asymmetric routing. Fixed 2026-04-14.
- **yt_triage_alert_remediation_20260625** (project): 2026-06-25 YouTrack triage (8 issues closed with evidence) + the IFRNLLEI01PRD-1408 commit-label mislabel finding + active-alert remediation (in progress).

## Physical Documentation (03_Lab)

- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_interfaces.md`
- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_network_changes.md`
- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_sdn.md`
- `03_Lab/NL/Servers/nl-pve03/20241222_nl-pve03_storage.md`
- `03_Lab/NL/Servers/nl-pve03/20250330-1711_nl-pve03_interfaces.cfg`
- `03_Lab/NL/Servers/nl-pve03/20250515_nl-pve03_ansible_inventory.yaml`
- `03_Lab/NL/Servers/nl-pve03/Desktop-nlamt02-2025-05-25-00-02.jpg`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlwhiteboard01/nlwhiteboard01_docker-compose.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlimaginary01/nlimaginary01_docker-compose.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlopenwebui01/20241223_nlopenwebui01.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/VMID_REDACTED - nlollama01/20241224_nlollama01.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/132 - nlelastiflow01/20240414_nlelastiflow01_dpl_notes.txt`
- `03_Lab/NL/Servers/nl-pve03/lxc/132 - nlelastiflow01/kibana-8.2.x-flow-codex.ndjson`
- `03_Lab/NL/Servers/nl-pve03/lxc/143 - nlimap01/20240827_nlimap01_lxc_build_notes.txt`
- `03_Lab/NL/Servers/nl-pve03/lxc/143 - nlimap01/20240827_nlimap01_lxc_build_notes.txt~`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20240905_nllobechat01_dpl_notes.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20241224 Backup Before Destroy/.env`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20241224 Backup Before Destroy/docker-compose.yml`
- `03_Lab/NL/Servers/nl-pve03/lxc/150 - nllobechat01/20241224 Backup Before Destroy/minio-bucket-config.json`
- `03_Lab/NL/Servers/nl-pve03/vm/100 - haos9.5 (nlhaos01)/FireAngel hittemelder 230V kopen We ❤️ Smart! ROBBshop.url`

*Compiled: 2026-07-03 04:30 UTC*